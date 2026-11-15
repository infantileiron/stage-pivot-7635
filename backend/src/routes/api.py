import os,json
import redis
from fastapi import APIRouter,Depends,HTTPException,Response
from src.config.database import db
from src.models.entities import User,Settlement,Pivot,Review,Audit,Receipt,ReceiptBatch,Reconciliation
from src.schemas.business import Login,SettlementInput,PivotInput,ReviewInput,ReviewEdit,ReceiptBatchInput,ReconciliationInput
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services.settlements import save
from src.services.analysis import key
from src.services.reconciliation_service import ingest_batch,submit_reconciliation
from src.controllers.business import ensure_pivot,ensure_review,cell,ensure_reconciliation,done_reconciliation
router=APIRouter()
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/settlements')
def settlements(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Settlement).order_by(Settlement.id).all()]
@router.post('/settlements')
def create(data:SettlementInput,u=Depends(editor),s=Depends(db)):
 r=save(s,data);audit(s,u,'录入结算 '+r['code']);return r
@router.put('/settlements/{i}')
def edit(i:int,data:SettlementInput,u=Depends(editor),s=Depends(db)):
 r=save(s,data,i);audit(s,u,'修订结算 '+str(i));return r
@router.get('/pivots')
def pivots(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Pivot).order_by(Pivot.id.desc()).all()]
@router.post('/pivots')
def submit(data:PivotInput,u=Depends(editor),s=Depends(db)):
 rows=[dump(r) for r in s.query(Settlement).order_by(Settlement.id).all()]
 r=Pivot(**data.model_dump(),result={'snapshot':rows});s.add(r);s.commit()
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('stage:pivots',r.id)
 except redis.RedisError:r.state='failed';r.error='队列暂不可用，请恢复后新建透视';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交透视 '+str(r.id));return dump(r)
@router.get('/pivots/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):return dump(ensure_pivot(s,i))
@router.get('/pivots/{i}/drill')
def drill(i:int,row_key:str,col_key:str,u=Depends(current),s=Depends(db)):
 r,c=cell(s,i,row_key,col_key)
 return {'cell':c,'rows':[x for x in r.result['snapshot'] if key(x,r.row_dim)==row_key and key(x,r.col_dim)==col_key]}
@router.get('/pivots/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_pivot(s,i)
 if r.state!='done':raise HTTPException(409,'仅成功透视可以导出')
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="stage-pivot-{i}.json"'})
@router.get('/reviews')
def reviews(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Review).order_by(Review.id.desc()).all()]
@router.post('/reviews')
def review(data:ReviewInput,u=Depends(editor),s=Depends(db)):
 run,c=cell(s,data.pivot_id,data.row_key,data.col_key)
 r=Review(**data.model_dump(),book_cents=c['net_cents'],difference_cents=data.expected_cents-c['net_cents']);s.add(r);s.commit();audit(s,u,'起草差异复核 '+str(r.id));return dump(r)
@router.put('/reviews/{i}')
def edit_review(i:int,data:ReviewEdit,u=Depends(editor),s=Depends(db)):
 r=ensure_review(s,i)
 if r.status!='draft':raise HTTPException(409,'已签核复核单不可覆盖，请新建复核')
 r.expected_cents=data.expected_cents;r.difference_cents=data.expected_cents-r.book_cents;r.note=data.note;s.commit();audit(s,u,'修改差异复核 '+str(i));return dump(r)
@router.post('/reviews/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=ensure_review(s,i)
 if r.status!='draft':raise HTTPException(409,'已签核复核单不可重复签核')
 r.status='approved';s.commit();audit(s,u,'签核差异复核 '+str(i));return dump(r)
# —— 渠道回单与核销 ——
@router.get('/receipts')
def receipts(u=Depends(current),s=Depends(db)):
 return [dump(r) for r in s.query(Receipt).order_by(Receipt.id).all()]
@router.get('/receipt-batches')
def receipt_batches(u=Depends(current),s=Depends(db)):
 return [dump(r) for r in s.query(ReceiptBatch).order_by(ReceiptBatch.id.desc()).all()]
@router.post('/receipt-batches')
def create_receipt_batch(data:ReceiptBatchInput,u=Depends(editor),s=Depends(db)):
 out=ingest_batch(s,data);audit(s,u,'批量收单 '+data.batch_no);return out
@router.get('/reconciliations')
def reconciliations(u=Depends(current),s=Depends(db)):
 return [dump(r) for r in s.query(Reconciliation).order_by(Reconciliation.id.desc()).all()]
@router.post('/reconciliations')
def create_reconciliation(data:ReconciliationInput,u=Depends(editor),s=Depends(db)):
 r=submit_reconciliation(s,data.name)
 try:redis.Redis.from_url(os.environ['REDIS_URL']).rpush('stage:reconciliations',r.id)
 except redis.RedisError:
  r.state='failed';r.error='队列暂不可用，请恢复后新建核销';s.commit();raise HTTPException(503,r.error)
 audit(s,u,'提交核销 '+str(r.id));return dump(r)
@router.get('/reconciliations/current')
def reconciliation_current(u=Depends(current),s=Depends(db)):
 r=s.query(Reconciliation).filter_by(is_current=True).order_by(Reconciliation.id.desc()).first()
 if not r:raise HTTPException(404,'尚无完成的当前版本')
 return dump(r)
@router.get('/reconciliations/{i}')
def reconciliation_detail(i:int,u=Depends(current),s=Depends(db)):
 return dump(ensure_reconciliation(s,i))
@router.get('/reconciliations/{i}/allocations')
def reconciliation_allocations(i:int,receipt_no:str='',code:str='',u=Depends(current),s=Depends(db)):
 r=done_reconciliation(s,i);rows=r.result['allocations']
 if receipt_no:rows=[x for x in rows if x['receipt_no']==receipt_no]
 if code:rows=[x for x in rows if x['code']==code]
 return {'allocations':rows,'conserved':r.result['conserved'],'totals':r.result['totals']}
@router.get('/reconciliations/{i}/export')
def export_reconciliation(i:int,u=Depends(current),s=Depends(db)):
 r=done_reconciliation(s,i)
 return Response(json.dumps(dump(r),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="reconciliation-{i}.json"'})
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]
