"""渠道回单批量解析。

支持两种输入：
1. records：已结构化的字典列表（前端表格/API 直接提交）。
2. raw_text：粘贴的回单明细文本，每行一张回单，字段支持逗号/制表符/竖线/中文逗号/
   分号/多空格分隔，表头行（含“编号”等字样）自动跳过。金额兼容“1,234.56 元”和
   整数分两种写法，统一折算为非负整数分。

只做解析与口径校验，不写库；幂等与同号异内容判定放在服务层。
"""
from __future__ import annotations

import re
from datetime import date

from src.constants.enums import CHANNELS

CHANNEL_SET = set(CHANNELS)
_SPLIT_RE = re.compile(r'[,\t;，；|]|\s{1,}')
_AMOUNT_RE = re.compile(r'[^0-9.]')
# 结构化字段 → 文本列序号（编号, 到账日, 渠道, 金额, 覆盖起, 覆盖止）
TEXT_COLUMNS = ('receipt_no', 'arrival_day', 'channel', 'amount', 'cover_from', 'cover_to')
HEADER_HINTS = ('编号', '到账', '渠道', '金额', '覆盖', 'receipt', 'amount')


class ReceiptParseError(ValueError):
    pass


def normalize_channel(value) -> str:
    channel = str(value or '').strip()
    if channel not in CHANNEL_SET:
        raise ReceiptParseError(f'未知渠道“{channel}”，允许：{ "、".join(CHANNELS) }')
    return channel


def parse_day(value, field='日期') -> str:
    text = str(value or '').strip().replace('/', '-').replace('.', '-')
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ReceiptParseError(f'{field}“{value}”不是合法 YYYY-MM-DD 日期') from exc


def parse_amount(value) -> int:
    """12.34 元 / 1,234.56 / 1234（分）→ 整数分。

    规则：带小数点按元折算（两位小数）；纯整数按“分”处理，与现有录入口径一致。
    """
    if isinstance(value, int):
        return value
    text = str(value or '').strip().replace(',', '').replace('，', '')
    if not text:
        raise ReceiptParseError('金额为空')
    if '.' in text:
        core = _AMOUNT_RE.sub('', text)
        try:
            whole, frac = core.split('.')
        except ValueError as exc:
            raise ReceiptParseError(f'金额“{value}”格式非法') from exc
        frac = (frac + '00')[:2]
        return int(whole or '0') * 100 + int(frac)
    digits = _AMOUNT_RE.sub('', text)
    if not digits.isdigit():
        raise ReceiptParseError(f'金额“{value}”格式非法')
    return int(digits)


def _split_line(line: str):
    return [part.strip() for part in _SPLIT_RE.split(line.strip()) if part is not None and part.strip()]


def parse_text(raw_text: str):
    parsed = []
    errors = []
    for lineno, line in enumerate(raw_text.splitlines(), start=1):
        if not line.strip():
            continue
        parts = _split_line(line)
        if not parts:
            continue
        if any(hint in line for hint in HEADER_HINTS) and not _looks_like_data(parts):
            continue
        if len(parts) != 6:
            errors.append(f'第 {lineno} 行字段数为 {len(parts)}，应为 6（编号,到账日,渠道,金额,覆盖起,覆盖止）')
            continue
        try:
            parsed.append(_build(dict(zip(TEXT_COLUMNS, parts)), lineno))
        except ReceiptParseError as exc:
            errors.append(f'第 {lineno} 行：{exc}')
    return parsed, errors


def _looks_like_data(parts) -> bool:
    # 首列像编号且第二列像日期才视为数据，否则按表头跳过
    if len(parts) < 2:
        return False
    try:
        parse_day(parts[1])
    except ReceiptParseError:
        return False
    return True


def parse_records(records):
    parsed = []
    errors = []
    for index, raw in enumerate(records, start=1):
        try:
            parsed.append(_build(raw, index))
        except (ReceiptParseError, KeyError, TypeError) as exc:
            errors.append(f'第 {index} 条：{exc}')
    return parsed, errors


def _build(raw, position) -> dict:
    receipt_no = str(raw.get('receipt_no', '')).strip()
    if not receipt_no:
        raise ReceiptParseError('回单编号为空')
    arrival_day = parse_day(raw['arrival_day'], '到账日')
    channel = normalize_channel(raw['channel'])
    amount_cents = parse_amount(raw['amount_cents'] if 'amount_cents' in raw else raw['amount'])
    if amount_cents <= 0:
        raise ReceiptParseError('金额必须为正整数分')
    cover_from = parse_day(raw['cover_from'], '覆盖起始日')
    cover_to = parse_day(raw['cover_to'], '覆盖截止日')
    if cover_from > cover_to:
        raise ReceiptParseError('覆盖日期范围起止倒置')
    if not (cover_from <= arrival_day <= cover_to):
        raise ReceiptParseError('到账日应落在可覆盖场次日期范围内')
    if not (cover_from <= arrival_day <= cover_to):
        raise ReceiptParseError('到账日应落在可覆盖场次日期范围内')
    return {
        'receipt_no': receipt_no,
        'arrival_day': arrival_day,
        'channel': channel,
        'amount_cents': amount_cents,
        'cover_from': cover_from,
        'cover_to': cover_to,
        '_position': position,
    }


def parse(raw_text=None, records=None):
    """统一入口，返回 (parsed, errors)。两者至少提供一个。"""
    if records is not None:
        parsed, errors = parse_records(records)
    elif raw_text is not None and raw_text.strip():
        parsed, errors = parse_text(raw_text)
    else:
        raise ReceiptParseError('请提供回单明细文本或结构化记录')
    # 批内同号校验
    seen = {}
    deduped = []
    for item in parsed:
        no = item['receipt_no']
        if no in seen:
            errors.append(f"回单编号 {no} 在本批重复（第 {seen[no]}、{item['_position']} 条）")
            continue
        seen[no] = item['_position']
        deduped.append(item)
    for item in deduped:
        item.pop('_position', None)
    return deduped, errors
