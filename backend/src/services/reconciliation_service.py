"""回单与核销的服务层：幂等收单、快照指纹、原子发布与并发守卫。"""
from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from src.models.entities import Receipt, ReceiptBatch, Reconciliation, Settlement
from src.services.business import dump
from src.services.receipts import parse, ReceiptParseError
from src.services.reconcile import reconcile, ReconcileError


def receipt_hash(item: dict) -> str:
    payload = {k: item[k] for k in
               ('receipt_no', 'arrival_day', 'channel', 'amount_cents', 'cover_from', 'cover_to')}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def settlement_snapshot(s):
    rows = [dump(r) for r in s.query(Settlement).order_by(Settlement.id).all()]
    for r in rows:
        r['net_cents'] = r['gross_cents'] - r['refund_cents'] - r['fee_cents']
    return rows


def snapshot_fingerprint(rows) -> str:
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def receipt_snapshot(s):
    return [dump(r) for r in s.query(Receipt).order_by(Receipt.id).all()]


def ingest_batch(s, data):
    """幂等批量收单。

    - 同批回单重试不重复入账：按 receipt_no 唯一，已存在且内容一致 → 跳过（skipped）。
    - 同号异内容拒绝：已存在 receipt_no 但 content_hash 不同 → 整批 409，不写入任何新行。
    - batch_no 唯一，重复提交批次号 → 409。
    """
    try:
        parsed, errors = parse(raw_text=data.raw_text,
                               records=[r.model_dump(mode='json') for r in data.records]
                               if data.records else None)
    except ReceiptParseError as exc:
        raise HTTPException(422, str(exc))

    if not parsed:
        raise HTTPException(422, f'没有可入账的回单：{"；".join(errors) or "明细为空"}')

    # 先做同号异内容预检，保证整批要么全进要么不进
    for item in parsed:
        existing = s.query(Receipt).filter_by(receipt_no=item['receipt_no']).first()
        if existing and existing.content_hash != receipt_hash(item):
            raise HTTPException(
                409,
                f"回单 {item['receipt_no']} 同号异内容：库内与本次明细不一致，拒绝入账",
            )

    batch = ReceiptBatch(batch_no=data.batch_no,
                         source='records' if data.records else 'text',
                         parse_errors=errors, note=data.note or '')
    s.add(batch)
    try:
        s.flush()  # 取 batch.id，同时触发 batch_no 唯一约束
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, f'批次号 {data.batch_no} 已存在，重复批次拒绝入账')

    ingested, skipped = [], []
    for item in parsed:
        existing = s.query(Receipt).filter_by(receipt_no=item['receipt_no']).first()
        if existing:  # 内容一致：重试不重复入账
            skipped.append(item['receipt_no'])
            continue
        s.add(Receipt(batch_id=batch.id, content_hash=receipt_hash(item),
                      ingested=True, **item))
        ingested.append(item['receipt_no'])
    try:
        s.commit()
    except IntegrityError:
        s.rollback()
        raise HTTPException(409, '回单编号冲突，入账已回滚')
    return {
        'batch': dump(batch),
        'ingested': ingested,
        'skipped': skipped,
        'parse_errors': errors,
        'receipts': [dump(r) for r in s.query(Receipt)
                     .filter(Receipt.batch_id == batch.id).order_by(Receipt.id).all()],
    }


def submit_reconciliation(s, name):
    """冻结当前场次与回单快照并入队，状态机 queued→running→done/failed。"""
    settlements = settlement_snapshot(s)
    receipts = receipt_snapshot(s)
    if not receipts:
        raise HTTPException(422, '尚无回单，请先批量收单')
    if not settlements:
        raise HTTPException(422, '尚无结算场次，无法核销')
    record = Reconciliation(
        name=name, state='queued', is_current=False,
        snapshot_fingerprint=snapshot_fingerprint(settlements),
        result={'settlement_snapshot': settlements,
                'receipt_snapshot': [
                    {k: r[k] for k in
                     ('receipt_no', 'arrival_day', 'channel', 'amount_cents',
                      'cover_from', 'cover_to')}
                    for r in receipts]})
    s.add(record)
    s.commit()
    return record


def publish_reconciliation(s, record_id):
    """worker 调用：计算并原子替换当前版本。失败保留旧版。

    并发守卫：
    - 过期发布（场次修订后快照指纹变化）→ failed，旧 current 保留。
    - 已有更新版本完成（更高 id 的 current/done）→ 当前任务判过期失败。
    - 任一场次超额（分配>净结算）→ 守恒失败，不切换 current。
    """
    record = s.get(Reconciliation, record_id)
    if not record or record.state != 'queued':
        return
    record.state = 'running'
    s.commit()

    frozen = record.result
    settlements = frozen['settlement_snapshot']
    receipts = frozen['receipt_snapshot']
    try:
        # 守卫一：场次修订后，冻结快照与当前库不一致 → 过期发布
        live_fingerprint = snapshot_fingerprint(settlement_snapshot(s))
        if live_fingerprint != record.snapshot_fingerprint:
            raise ReconcileError('场次已修订，冻结快照过期，拒绝发布；请基于最新数据新建核销')

        # 守卫二：另一核销已先行完成 → 拒绝过期发布，避免交叉超额
        newer = (s.query(Reconciliation)
                 .filter(Reconciliation.id > record.id,
                         Reconciliation.state == 'done')
                 .order_by(Reconciliation.id.desc()).first())
        if newer:
            raise ReconcileError(f'更新的核销版本 #{newer.id} 已完成，本任务过期，拒绝发布')

        result = reconcile(receipts, settlements)
        if not result['allocations']:
            raise ReconcileError('未产生任何分配，拒绝发布')

        # 原子替换：单事务内撤下旧 current，再挂上本版本
        s.query(Reconciliation).filter(Reconciliation.is_current.is_(True)) \
            .update({Reconciliation.is_current: False}, synchronize_session=False)
        record.result = {**result, **frozen}
        record.state = 'done'
        record.error = ''
        record.is_current = True
        s.commit()
        return record
    except Exception as exc:
        s.rollback()
        record = s.get(Reconciliation, record_id)
        record.state = 'failed'
        record.error = str(exc)
        record.is_current = False
        s.commit()
        return None
