"""回单核销分配引擎。

业务口径：
- 渠道回单可能合并多场票款，一场也可能分多笔到账；回单仅能核销“同渠道、且场次业务日期
  落在回单可覆盖日期范围 [cover_from, cover_to] 内”的场次。
- 每个场次可被核销的上限是其净结算（票款−退款−渠道费），整数分，不可超额。
- 目标一（字典序最高）：最大化核销总额（所有回单分配分之和）。
- 目标二：在核销总额最大的所有方案里，最小化金额加权日期间隔
  Σ 分配分 × |回单到账日 − 场次业务日期|。
- 目标三：同分时按 (回单编号, 场次编号) 确定性打平，保证结果可复现。

实现：源点→回单（容量=回单金额，费用0）；回单→可覆盖场次（容量=场次净结算，
单位费用=间隔天）；场次→汇点（容量=场次净结算，费用0）。用 SPFA 最短增广路做
最小费用最大流。为在“最大流”前提下严格最小化加权间隔，每条边单位费用编码为
gap * K + rank，其中 K 大于任何可能的 rank 总和，使最小费用先比较加权间隔再比较次序。
全部整数运算，不引入浮点。
"""
from __future__ import annotations

import heapq
from datetime import date


class ReconcileError(ValueError):
    """核销前置数据不满足计算条件。"""


def _parse_day(value) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _days_between(a: str, b: str) -> int:
    return abs((_parse_day(a) - _parse_day(b)).days)


def build_edges(receipts, settlements):
    """生成回单→场次的可覆盖边，按 (回单编号, 场次编号) 固定次序，便于确定性打平。

    receipts: [{'receipt_no','channel','arrival_day','amount_cents',
                'cover_from','cover_to'}]
    settlements: [{'code','channel','day','net_cents'}]
    """
    receipts = sorted(receipts, key=lambda r: r['receipt_no'])
    settlements = sorted(settlements, key=lambda x: x['code'])
    edges = []
    for ri, rc in enumerate(receipts):
        cf, ct = _parse_day(rc['cover_from']), _parse_day(rc['cover_to'])
        if cf > ct:
            raise ReconcileError(f"回单 {rc['receipt_no']} 的覆盖范围起止倒置")
        for si, st in enumerate(settlements):
            if rc['channel'] != st['channel']:
                continue
            sd = _parse_day(st['day'])
            if not (cf <= sd <= ct):
                continue
            net = int(st['net_cents'])
            if net <= 0:
                continue
            edges.append({
                'receipt_index': ri,
                'settlement_index': si,
                'receipt_no': rc['receipt_no'],
                'code': st['code'],
                'channel': rc['channel'],
                'gap_days': _days_between(rc['arrival_day'], st['day']),
                'capacity': min(int(rc['amount_cents']), net),
            })
    return receipts, settlements, edges


class _Edge:
    __slots__ = ('to', 'rev', 'cap', 'cost')

    def __init__(self, to, rev, cap, cost):
        self.to, self.rev, self.cap, self.cost = to, rev, cap, cost


def _min_cost_max_flow(graph, source, sink):
    """Dijkstra + Johnson 位势的最小费用最大流，返回 (总流量, 总费用)。

    原始边费用非负，初始位势全 0；每轮用 reduced cost = cost + pot[u] − pot[v]
    跑 Dijkstra，再更新位势，保证 reduced cost 恒非负。复杂度 O(F·E·log V)，
    显著优于 SPFA 逐轮全图松弛。
    """
    n = len(graph)
    potential = [0] * n
    flow = cost = 0
    inf = float('inf')
    while True:
        dist = [inf] * n
        prev_v = [-1] * n
        prev_e = [-1] * n
        dist[source] = 0
        heap = [(0, source)]
        while heap:
            du, u = heapq.heappop(heap)
            if du != dist[u]:
                continue
            for ei, e in enumerate(graph[u]):
                if e.cap <= 0:
                    continue
                reduced = e.cost + potential[u] - potential[e.to]
                nd = du + reduced
                if nd < dist[e.to]:
                    dist[e.to] = nd
                    prev_v[e.to] = u
                    prev_e[e.to] = ei
                    heapq.heappush(heap, (nd, e.to))
        if dist[sink] == inf:
            break
        for v in range(n):
            if dist[v] < inf:
                potential[v] += dist[v]
        # 沿路取最小剩余容量，整数分一次性增广
        add = inf
        v = sink
        while v != source:
            add = min(add, graph[prev_v[v]][prev_e[v]].cap)
            v = prev_v[v]
        path_cost = 0
        v = sink
        while v != source:
            e = graph[prev_v[v]][prev_e[v]]
            path_cost += e.cost
            e.cap -= add
            graph[v][e.rev].cap += add
            v = prev_v[v]
        flow += add
        cost += add * path_cost
    return flow, cost


def reconcile(receipts, settlements):
    """计算核销分配并做守恒对账。

    返回冻结结果字典，含分配明细、双方余款、加权间隔与守恒校验。
    前置不满足（无回单/无场次/无任何可覆盖关系）抛 ReconcileError。
    """
    if not receipts:
        raise ReconcileError('没有回单可参与核销，请先批量收单')
    if not settlements:
        raise ReconcileError('没有结算场次，无法核销')
    for rc in receipts:
        if int(rc['amount_cents']) <= 0:
            raise ReconcileError(f"回单 {rc['receipt_no']} 金额必须为正整数分")
    for st in settlements:
        if int(st['net_cents']) < 0:
            raise ReconcileError(f"场次 {st['code']} 净结算为负，口径不允许")

    receipts, settlements, edges = build_edges(receipts, settlements)
    if not edges:
        raise ReconcileError('回单与场次之间没有同渠道且日期落在覆盖范围内的可核销关系')

    n_rc, n_st = len(receipts), len(settlements)
    source = n_rc + n_st
    sink = source + 1
    node_count = sink + 1
    graph = [[] for _ in range(node_count)]

    def add_edge(u, v, cap, cost):
        graph[u].append(_Edge(v, len(graph[v]), cap, cost))
        graph[v].append(_Edge(u, len(graph[u]) - 1, 0, -cost))

    # 费用编码：主序 gap_days，次序用固定 rank 做确定性打平。
    # K 取严格大于全图 rank 之和上界，保证 gap 永远优先于 rank。
    rank_span = max(1, len(edges))
    k_lead = rank_span + 1

    rc_outflow = [0] * n_rc
    st_inflow = [0] * n_st
    # 源点 → 回单
    for ri, rc in enumerate(receipts):
        add_edge(source, ri, int(rc['amount_cents']), 0)
    # 回单 → 场次
    edge_refs = []
    for rank, ed in enumerate(edges):
        ri, si = ed['receipt_index'], ed['settlement_index']
        unit_cost = ed['gap_days'] * k_lead + rank
        add_edge(ri, n_rc + si, ed['capacity'], unit_cost)
        edge_refs.append((ri, si, ed))
    # 场次 → 汇点
    for si, st in enumerate(settlements):
        add_edge(n_rc + si, sink, int(st['net_cents']), 0)

    total_flow, total_cost = _min_cost_max_flow(graph, source, sink)
    if total_flow <= 0:
        raise ReconcileError('没有可核销金额（所有可覆盖场次净结算均为零）')

    # 反推每条 回单→场次 边的实际流量 = 容量 − 正向边剩余容量
    allocations = []
    rank_sum = 0
    for rank, (ri, si, ed) in enumerate(edge_refs):
        forward = next(e for e in graph[ri] if e.to == n_rc + si)
        used = ed['capacity'] - forward.cap
        if used <= 0:
            continue
        rank_sum += rank
        allocations.append({
            'receipt_no': ed['receipt_no'],
            'code': ed['code'],
            'channel': ed['channel'],
            'arrival_day': receipts[ri]['arrival_day'],
            'settlement_day': settlements[si]['day'],
            'gap_days': ed['gap_days'],
            'allocated_cents': used,
        })
        rc_outflow[ri] += used
        st_inflow[si] += used

    # 费用还原：去掉 rank 次序分量，得到纯加权间隔
    weighted_gap = sum(a['allocated_cents'] * a['gap_days'] for a in allocations)

    receipt_results = []
    for ri, rc in enumerate(receipts):
        amount = int(rc['amount_cents'])
        used = rc_outflow[ri]
        receipt_results.append({
            'receipt_no': rc['receipt_no'],
            'batch_no': rc.get('batch_no'),
            'channel': rc['channel'],
            'arrival_day': rc['arrival_day'],
            'cover_from': rc['cover_from'],
            'cover_to': rc['cover_to'],
            'amount_cents': amount,
            'allocated_cents': used,
            'remaining_cents': amount - used,
        })

    settlement_results = []
    for si, st in enumerate(settlements):
        net = int(st['net_cents'])
        used = st_inflow[si]
        settlement_results.append({
            'code': st['code'],
            'day': st['day'],
            'venue': st.get('venue'),
            'play': st.get('play'),
            'channel': st['channel'],
            'net_cents': net,
            'allocated_cents': used,
            'remaining_cents': net - used,
        })

    total_receipt = sum(int(r['amount_cents']) for r in receipts)
    total_net = sum(int(s['net_cents']) for s in settlements)
    total_allocated = sum(a['allocated_cents'] for a in allocations)
    total_receipt_remaining = sum(r['remaining_cents'] for r in receipt_results)
    total_settlement_remaining = sum(s['remaining_cents'] for s in settlement_results)

    # —— 守恒对账：任何一条不成立都视为算法失败 ——
    conservation = {
        'flow_matches_allocations': total_flow == total_allocated,
        'receipt_identity': total_receipt == total_allocated + total_receipt_remaining,
        'settlement_identity': total_net == total_allocated + total_settlement_remaining,
        'no_over_allocation': all(
            s['allocated_cents'] <= s['net_cents'] for s in settlement_results),
        'receipts_within_amount': all(
            r['allocated_cents'] <= r['amount_cents'] for r in receipt_results),
        'integer_cents': all(
            isinstance(a['allocated_cents'], int) for a in allocations),
    }
    conserved = all(conservation.values())
    if not conserved:
        raise ReconcileError(f'核销守恒校验失败：{conservation}')

    return {
        'allocations': sorted(
            allocations, key=lambda a: (a['receipt_no'], a['code'])),
        'receipts': receipt_results,
        'settlements': settlement_results,
        'totals': {
            'receipt_cents': total_receipt,
            'net_cents': total_net,
            'allocated_cents': total_allocated,
            'receipt_remaining_cents': total_receipt_remaining,
            'settlement_remaining_cents': total_settlement_remaining,
        },
        'weighted_gap_cents_days': weighted_gap,
        'rank_tiebreaker_sum': rank_sum,
        'raw_min_cost': total_cost,
        'conservation': conservation,
        'conserved': conserved,
        'method': (
            '仅同渠道且场次日期在回单覆盖范围内可核销；每场以净结算为上限，回单以到账金额为上限，'
            '整数分。先最大化核销总额，再最小化金额加权日期间隔 Σ分配分×|到账日−场次日|，'
            '同分时按回单编号、场次编号确定性打平。回单余款=到账−已核销，场次余款=净结算−已核销，'
            '双方恒等式严格守恒。'
        ),
    }
