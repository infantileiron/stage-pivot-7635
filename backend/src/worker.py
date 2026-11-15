import os,time,json,logging
from pathlib import Path
import redis
from src.config.database import Session
from src.models.entities import Pivot,Reconciliation
from src.services.analysis import pivot
from src.services.reconciliation_service import publish_reconciliation
q=redis.Redis.from_url(os.environ['REDIS_URL'])
with Session() as s:
 for r in s.query(Pivot).filter(Pivot.state.in_(['queued','running'])).all():r.state='queued';q.rpush('stage:pivots',r.id)
 for r in s.query(Reconciliation).filter(Reconciliation.state.in_(['queued','running'])).all():r.state='queued';q.rpush('stage:reconciliations',r.id)
 s.commit()
def run_pivot(item):
 with Session() as s:
  r=s.get(Pivot,int(item[1]))
  if not r or r.state!='queued':return
  snapshot=r.result['snapshot'];r.state='running';s.commit()
  try:
   r.result={**pivot(snapshot,r.row_dim,r.col_dim),'snapshot':snapshot};r.state='done';Path('/artifacts/pivot-'+str(r.id)+'.json').write_text(json.dumps(r.result,ensure_ascii=False))
  except Exception as e:r.state='failed';r.error=str(e)
  s.commit()
def run_reconciliation(item):
 with Session() as s:
  record=publish_reconciliation(s,int(item[1]))
  if record and record.state=='done':
   Path('/artifacts/reconciliation-'+str(record.id)+'.json').write_text(json.dumps(record.result,ensure_ascii=False))
QUEUES=(('stage:pivots',run_pivot),('stage:reconciliations',run_reconciliation))
while True:
 Path('/tmp/heartbeat').touch()
 try:
  item=None;runner=None
  for name,fn in QUEUES:
   item=q.blpop(name,timeout=1)
   if item:runner=fn;break
  if not item:continue
  runner(item)
 except Exception:logging.exception('worker');time.sleep(2)
