import random
from datetime import date,timedelta
from src.config.database import Base,engine,Session
from src.models.entities import User,Settlement,Receipt,ReceiptBatch,Reconciliation
from src.utils.security import hash_password
from src.constants.enums import VENUES,CHANNELS
from src.services.reconciliation_service import (
    receipt_hash,settlement_snapshot,receipt_snapshot,snapshot_fingerprint)
from src.services.reconcile import reconcile


def seed():
 Base.metadata.create_all(engine);rng=random.Random(3112)
 with Session() as s:
  for role in ('admin','analyst','viewer'):
   email=role+'@demo.local'
   if not s.query(User).filter_by(email=email).first():s.add(User(email=email,role=role,password=hash_password('Demo123!')))
  for i in range(180):
   code=f'YM-{i+1:03}';seats=[800,240,120][i%3];checked=rng.randint(seats//2,seats);gross=checked*rng.choice([8000,12000,18000]);refund=rng.randint(0,checked//10)*8000;fee=int((gross-refund)*[0,.07,.03][i%3])
   if not s.query(Settlement).filter_by(code=code).first():s.add(Settlement(code=code,day=(date(2026,9,1)+timedelta(days=i//3)).isoformat(),venue=VENUES[i%3],play=['渡口来信','星河漫游','一间书房','冬日序曲'][i%4],channel=CHANNELS[(i//3)%3],gross_cents=gross,refund_cents=refund,fee_cents=fee,seats=seats,checked=checked))
  s.commit()
  _seed_receipts(s)
  _seed_reconciliation(s)
  print({'users':s.query(User).count(),'settlements':s.query(Settlement).count(),
         'receipts':s.query(Receipt).count(),'reconciliations':s.query(Reconciliation).count()})


def _seed_receipts(s):
 """按 渠道×月份 汇总净结算，回单取约 80% 制造双方余款；幂等。"""
 if s.query(Receipt).count()>0:return
 rows=settlement_snapshot(s)
 groups={}
 for r in rows:
  month=r['day'][:7]
  groups.setdefault((r['channel'],month),0)
  groups[(r['channel'],month)]+=r['net_cents']
 batch=ReceiptBatch(batch_no='SEED-RECEIPTS',source='records',state='parsed',parse_errors=[],note='演示种子：渠道×月份合并回单，约覆盖净结算80%')
 s.add(batch);s.flush()
 for (channel,month),net in sorted(groups.items()):
  amount=max(1,int(net*0.8))
  y,m=map(int,month.split('-'))
  arrival=(date(y,m,15)).isoformat()
  item={'receipt_no':f'RC-{channel[:2]}-{month}','arrival_day':arrival,'channel':channel,
        'amount_cents':amount,'cover_from':f'{month}-01','cover_to':f'{month}-28'}
  s.add(Receipt(batch_id=batch.id,content_hash=receipt_hash(item),ingested=True,**item))
 s.commit()


def _seed_reconciliation(s):
 """基于当前快照生成一份冻结的当前核销，等价于 worker 产出；幂等。"""
 if s.query(Reconciliation).count()>0:return
 settlements=settlement_snapshot(s)
 receipts=[{k:r[k] for k in ('receipt_no','arrival_day','channel','amount_cents','cover_from','cover_to')}
           for r in receipt_snapshot(s)]
 result=reconcile(receipts,settlements)
 record=Reconciliation(name='演示·渠道回单核销',state='done',is_current=True,
                      snapshot_fingerprint=snapshot_fingerprint(settlements),
                      result={**result,'settlement_snapshot':settlements,'receipt_snapshot':receipts})
 s.add(record);s.commit()


if __name__=='__main__':seed()
