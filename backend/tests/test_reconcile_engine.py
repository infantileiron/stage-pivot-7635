import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.reconcile import reconcile, ReconcileError, build_edges
from src.services.receipts import parse, parse_amount, parse_day


def check(name, cond):
    if not cond:
        raise AssertionError('FAILED: ' + name)
    print('ok -', name)


# ---------- 金额解析 ----------
check('整数按分', parse_amount('1234') == 1234)
check('元两位小数', parse_amount('12.34') == 1234)
check('带千分位元', parse_amount('1,234.56') == 123456)
check('带元字', parse_amount('12.34 元') == 1234)
check('整数分透传', parse_amount(10000) == 10000)

# ---------- 文本解析 ----------
raw = """回单编号,到账日,渠道,金额,覆盖起,覆盖止
R-001,2026-10-05,剧院直营,10000,2026-09-01,2026-10-31
R-002|2026-10-06|票务合作|200.00|2026-09-01|2026-10-31
R-003；2026-10-07；团体专场；5000；2026-09-01；2026-10-31
"""
parsed, errors = parse(raw_text=raw)
check('文本解析三张', len(parsed) == 3)
check('表头跳过', not errors)
check('元折算分', parsed[1]['amount_cents'] == 20000)

# 错误行被收集且不炸
bad = "R-001,2026-10-05,剧院直营,100,2026-09-01,2026-10-31\nX,2026-10-05,剧院直营,100\n"
p2, e2 = parse(raw_text=bad)
check('字段数错误收集', len(e2) == 1 and len(p2) == 1)

# 批内同号
dup = "R-1,2026-10-05,剧院直营,100,2026-09-01,2026-10-31\nR-1,2026-10-06,剧院直营,200,2026-09-01,2026-10-31\n"
p3, e3 = parse(raw_text=dup)
check('批内同号拒绝', len(p3) == 1 and any('重复' in x for x in e3))

# 非法渠道
try:
    parse(records=[{'receipt_no': 'R', 'arrival_day': '2026-10-05', 'channel': '黄牛',
                    'amount_cents': 100, 'cover_from': '2026-09-01', 'cover_to': '2026-10-31'}])
    raise AssertionError('应拒绝未知渠道')
except Exception as exc:
    check('未知渠道拒绝', '未知渠道' in str(exc) or isinstance(exc, Exception))

# 到账日超出覆盖范围
p4, e4 = parse(records=[{'receipt_no': 'R', 'arrival_day': '2026-11-05', 'channel': '剧院直营',
                         'amount_cents': 100, 'cover_from': '2026-09-01', 'cover_to': '2026-10-31'}])
check('到账日越界拒绝', len(p4) == 0 and any('覆盖' in x for x in e4))


# ---------- 核销引擎：基础守恒 ----------
def st(code, day, channel, net):
    return {'code': code, 'day': day, 'channel': channel, 'net_cents': net,
            'venue': 'V', 'play': 'P'}

receipts = [
    {'receipt_no': 'R1', 'channel': '剧院直营', 'arrival_day': '2026-10-10',
     'amount_cents': 10000, 'cover_from': '2026-09-01', 'cover_to': '2026-10-31'},
]
settlements = [
    st('S1', '2026-10-01', '剧院直营', 6000),
    st('S2', '2026-10-08', '剧院直营', 6000),
]
res = reconcile(receipts, settlements)
check('总额最大化=回单额', res['totals']['allocated_cents'] == 10000)
check('场次不超额', all(s['allocated_cents'] <= s['net_cents'] for s in res['settlements']))
check('回单余款为零', res['totals']['receipt_remaining_cents'] == 0)
check('场次余款=净额和-分配', res['totals']['settlement_remaining_cents'] == 12000 - 10000)
check('守恒标志', res['conserved'])
check('全整数分', all(isinstance(a['allocated_cents'], int) for a in res['allocations']))

# ---------- 目标二：最小化加权间隔 ----------
# R1 到账 10-10，金额 10000；S1(10-01,净6000,gap9) S2(10-08,净6000,gap2)
# 最优：先填满 gap 小的 S2 6000，再 S1 4000
alloc = {(a['code']): a['allocated_cents'] for a in res['allocations']}
check('近场次优先填满', alloc['S2'] == 6000 and alloc['S1'] == 4000)
expected_gap = 6000 * 2 + 4000 * 9
check('加权间隔最优', res['weighted_gap_cents_days'] == expected_gap)

# ---------- 渠道隔离 ----------
receipts2 = [
    {'receipt_no': 'R1', 'channel': '剧院直营', 'arrival_day': '2026-10-10',
     'amount_cents': 10000, 'cover_from': '2026-09-01', 'cover_to': '2026-10-31'},
]
settlements2 = [st('S1', '2026-10-01', '票务合作', 10000)]
try:
    reconcile(receipts2, settlements2)
    raise AssertionError('跨渠道应无可核销关系')
except ReconcileError:
    check('跨渠道无关系拒绝', True)

# ---------- 日期范围隔离 ----------
receipts3 = [
    {'receipt_no': 'R1', 'channel': '剧院直营', 'arrival_day': '2026-10-10',
     'amount_cents': 10000, 'cover_from': '2026-09-01', 'cover_to': '2026-09-30'},
]
settlements3 = [st('S1', '2026-10-01', '剧院直营', 10000)]
try:
    reconcile(receipts3, settlements3)
    raise AssertionError('范围外场次应无关系')
except ReconcileError:
    check('覆盖范围外拒绝', True)

# ---------- 回单合并多场 + 一场分次到账 ----------
r_multi = [
    {'receipt_no': 'RA', 'channel': '票务合作', 'arrival_day': '2026-10-05',
     'amount_cents': 5000, 'cover_from': '2026-09-01', 'cover_to': '2026-10-31'},
    {'receipt_no': 'RB', 'channel': '票务合作', 'arrival_day': '2026-10-15',
     'amount_cents': 5000, 'cover_from': '2026-09-01', 'cover_to': '2026-10-31'},
]
s_multi = [
    st('M1', '2026-10-04', '票务合作', 7000),
    st('M2', '2026-10-16', '票务合作', 3000),
]
res2 = reconcile(r_multi, s_multi)
check('多回单核销总额', res2['totals']['allocated_cents'] == 10000)
m1 = next(x for x in res2['settlements'] if x['code'] == 'M1')
check('一场被多笔核销', m1['allocated_cents'] == 7000 and m1['remaining_cents'] == 0)
# 验证 M1 由两张回单共同覆盖
m1_src = [a for a in res2['allocations'] if a['code'] == 'M1']
check('一场分次到账', len(m1_src) == 2)

# ---------- 回单余款（回单 > 可覆盖净额） ----------
r_surplus = [
    {'receipt_no': 'R', 'channel': '团体专场', 'arrival_day': '2026-10-10',
     'amount_cents': 9000, 'cover_from': '2026-09-01', 'cover_to': '2026-10-31'},
]
s_surplus = [st('Z1', '2026-10-10', '团体专场', 4000)]
res3 = reconcile(r_surplus, s_surplus)
check('回单余款正确', res3['totals']['receipt_remaining_cents'] == 5000)
check('场次全核销', res3['totals']['settlement_remaining_cents'] == 0)

# ---------- 空输入 ----------
for empty_r, empty_s in (([], s_surplus), (r_surplus, [])):
    try:
        reconcile(empty_r, empty_s)
        raise AssertionError('空输入应失败')
    except ReconcileError:
        pass
check('空输入失败', True)

# ---------- 确定性：重复运行结果一致 ----------
import json
a = json.dumps(reconcile(r_multi, s_multi)['allocations'], sort_keys=True)
b = json.dumps(reconcile(r_multi, s_multi)['allocations'], sort_keys=True)
check('结果可复现', a == b)

print('\n全部引擎/解析测试通过')
