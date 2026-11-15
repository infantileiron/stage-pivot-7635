"""端到端集成测试：用 SQLite 内存库替代 MySQL，直接调用发布服务替代 Redis worker。

仅依赖 FastAPI 路由与真实服务层，验证：收单幂等、同号异内容拒绝、原子发布、
过期/并发守卫、守恒对账、只读权限。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('JWT_SECRET', 'test-secret')
os.environ.setdefault('REDIS_URL', 'redis://unused:6379/0')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from src.config import database as db_config
from src.routes.api import router, db as db_dependency
import src.models.entities  # noqa: F401 注册实体到 db_config.Base
from src.models.entities import User, Settlement, Reconciliation, Receipt
from src.utils.security import hash_password
from src.services.reconciliation_service import publish_reconciliation

# 让应用所有会话共享同一个内存 SQLite（StaticPool 保持单连接不被回收）
test_engine = create_engine(
    'sqlite://', connect_args={'check_same_thread': False},
    poolclass=StaticPool)
db_config.engine = test_engine
db_config.Session.configure(bind=test_engine)
db_config.Base.metadata.create_all(test_engine)
TestSession = db_config.Session


def override_db():
    s = TestSession()
    try:
        yield s
    finally:
        s.close()


app = FastAPI()
app.include_router(router)
app.dependency_overrides[db_dependency] = override_db


import redis as _redis


class _FakeClient:
    def rpush(self, *a):
        return 1


class FakeRedis:
    RedisError = _redis.RedisError

    class Redis:
        @staticmethod
        def from_url(url):
            return _FakeClient()


import src.routes.api as api_mod
api_mod.redis = FakeRedis()

client = TestClient(app)


def check(name, cond):
    if not cond:
        raise AssertionError('FAILED: ' + name)
    print('ok -', name)


def login(role):
    with TestSession() as s:
        email = f'{role}@t.local'
        if not s.query(User).filter_by(email=email).first():
            s.add(User(email=email, role=role, password=hash_password('pw123456')))
            s.commit()
    r = client.post('/auth/login', json={'email': email, 'password': 'pw123456'})
    return r.json()['token']


def auth(token):
    return {'Authorization': 'Bearer ' + token}


analyst = login('analyst')
admin = login('admin')
viewer = login('viewer')

# ---------- 录入场次 ----------
def add_settlement(code, day, channel, gross=10000, refund=1000, fee=500):
    body = {'code': code, 'day': day, 'venue': '云幕大剧场', 'play': '测试剧',
            'channel': channel, 'gross_cents': gross, 'refund_cents': refund,
            'fee_cents': fee, 'seats': 100, 'checked': 80}
    r = client.post('/settlements', json=body, headers=auth(analyst))
    check('录入场次 ' + code, r.status_code == 200)

add_settlement('T-001', '2026-10-01', '剧院直营')  # 净 8500
add_settlement('T-002', '2026-10-08', '剧院直营')  # 净 8500
add_settlement('T-003', '2026-10-05', '票务合作', gross=8000, refund=0, fee=0)  # 净 8000

# viewer 只读
r = client.post('/settlements', json={
    'code': 'X', 'day': '2026-10-01', 'venue': '云幕大剧场', 'play': 'p',
    'channel': '剧院直营', 'gross_cents': 1, 'refund_cents': 0, 'fee_cents': 0,
    'seats': 1, 'checked': 1}, headers=auth(viewer))
check('viewer 只读拒绝', r.status_code == 403)

# ---------- 批量收单（文本） ----------
raw_text = (
    '回单编号,到账日,渠道,金额,覆盖起,覆盖止\n'
    'RC-1,2026-10-10,剧院直营,10000,2026-09-01,2026-10-31\n'
    'RC-2,2026-10-09,票务合作,8000,2026-09-01,2026-10-31\n'
)
r = client.post('/receipt-batches', json={'batch_no': 'B-1', 'raw_text': raw_text},
                headers=auth(analyst))
check('收单 200', r.status_code == 200)
check('两张入账', sorted(r.json()['ingested']) == ['RC-1', 'RC-2'])

# 同批重试：批次号冲突
r = client.post('/receipt-batches', json={'batch_no': 'B-1', 'raw_text': raw_text},
                headers=auth(analyst))
check('重复批次号 409', r.status_code == 409)

# 同内容重试（新批次号）：不重复入账，全部 skipped
r = client.post('/receipt-batches',
                json={'batch_no': 'B-2', 'raw_text': raw_text}, headers=auth(analyst))
check('重试 200', r.status_code == 200 and r.json()['ingested'] == [])
check('同内容跳过', sorted(r.json()['skipped']) == ['RC-1', 'RC-2'])

with TestSession() as s:
    check('回单未重复', s.query(Receipt).count() == 2)

# 同号异内容：整批拒绝且无新增
conflict = ('回单编号,到账日,渠道,金额,覆盖起,覆盖止\n'
            'RC-1,2026-10-10,剧院直营,9999,2026-09-01,2026-10-31\n'
            'RC-9,2026-10-10,剧院直营,100,2026-09-01,2026-10-31\n')
r = client.post('/receipt-batches', json={'batch_no': 'B-3', 'raw_text': conflict},
                headers=auth(analyst))
check('同号异内容 409', r.status_code == 409)
with TestSession() as s:
    check('冲突批无残留', s.query(Receipt).count() == 2 and
          s.query(Receipt).filter_by(receipt_no='RC-9').first() is None)

# ---------- 提交并发布核销 #1 ----------
r = client.post('/reconciliations', json={'name': '十月核销'}, headers=auth(analyst))
check('提交核销', r.status_code == 200)
rid1 = r.json()['id']

with TestSession() as s:
    rec = publish_reconciliation(s, rid1)
check('发布成功', rec is not None and rec.state == 'done' and rec.is_current)

r = client.get(f'/reconciliations/{rid1}', headers=auth(analyst))
result = r.json()['result']
check('守恒', result['conserved'])
check('RC-2 全额核销票务合作', result['totals']['allocated_cents'] >= 8000)
# RC-1 10000 覆盖直营两场净 17000 → 核销 10000，直营场次余款 7000
check('总额最大化', result['totals']['allocated_cents'] == 18000)
check('回单余款为零', result['totals']['receipt_remaining_cents'] == 0)
check('场次余款守恒', result['totals']['settlement_remaining_cents'] ==
      (8500 + 8500 + 8000) - 18000)
# 恒等式
t = result['totals']
check('回单恒等式', t['receipt_cents'] == t['allocated_cents'] + t['receipt_remaining_cents'])
check('场次恒等式', t['net_cents'] == t['allocated_cents'] + t['settlement_remaining_cents'])

# 当前版本
r = client.get('/reconciliations/current', headers=auth(analyst))
check('当前版本接口', r.status_code == 200 and r.json()['id'] == rid1)

# 分配下钻
r = client.get(f'/reconciliations/{rid1}/allocations?receipt_no=RC-1', headers=auth(analyst))
check('按回单下钻', r.status_code == 200 and
      all(a['receipt_no'] == 'RC-1' for a in r.json()['allocations']))
r = client.get(f'/reconciliations/{rid1}/allocations?code=T-001', headers=auth(analyst))
check('按场次下钻', r.status_code == 200 and
      all(a['code'] == 'T-001' for a in r.json()['allocations']))

# 导出冻结分配
r = client.get(f'/reconciliations/{rid1}/export', headers=auth(viewer))
import json as _json
_parsed = _json.loads(r.text)
check('导出冻结 JSON', r.status_code == 200 and
      'allocations' in _parsed['result'] and
      'attachment' in r.headers.get('content-disposition', ''))

# ---------- 过期发布守卫：提交后修订场次 ----------
r = client.post('/reconciliations', json={'name': '十月核销v2'}, headers=auth(analyst))
rid2 = r.json()['id']
# 在 #2 提交之后、发布之前修订场次 → 指纹变化
with TestSession() as s:
    st = s.query(Settlement).filter_by(code='T-001').first()
    sid = st.id
client.put(f'/settlements/{sid}', json={
    'code': 'T-001', 'day': '2026-10-01', 'venue': '云幕大剧场', 'play': '测试剧',
    'channel': '剧院直营', 'gross_cents': 12000, 'refund_cents': 1000, 'fee_cents': 500,
    'seats': 100, 'checked': 80}, headers=auth(analyst))
with TestSession() as s:
    rec2 = publish_reconciliation(s, rid2)
check('过期发布失败', rec2 is None)
with TestSession() as s:
    failed = s.get(Reconciliation, rid2)
    current = s.query(Reconciliation).filter_by(is_current=True).first()
    check('失败态保留原因', failed.state == 'failed' and '过期' in failed.error)
    check('旧版本仍为当前', current.id == rid1)

# ---------- 并发守卫：更新版本先完成 ----------
r = client.post('/reconciliations', json={'name': 'v3'}, headers=auth(analyst))
rid3 = r.json()['id']
r = client.post('/reconciliations', json={'name': 'v4'}, headers=auth(analyst))
rid4 = r.json()['id']
with TestSession() as s:
    pub4 = publish_reconciliation(s, rid4)
    pub4_ok = bool(pub4 and pub4.state == 'done' and pub4.is_current)
    pub3 = publish_reconciliation(s, rid3)
    pub3_none = pub3 is None
check('v4 先发布成功', pub4_ok)
check('v3 过期拒绝', pub3_none)
with TestSession() as s:
    check('当前为 v4', s.query(Reconciliation).filter_by(is_current=True).one().id == rid4)
    check('同时只有一个当前', s.query(Reconciliation).filter(Reconciliation.is_current.is_(True)).count() == 1)

# ---------- 无回单时拒绝提交 ----------
with TestSession() as s:
    s.query(Receipt).delete()
    s.commit()
r = client.post('/reconciliations', json={'name': '空'}, headers=auth(analyst))
check('无回单拒绝核销', r.status_code == 422)

print('\n全部端到端集成测试通过')
