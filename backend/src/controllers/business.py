from fastapi import HTTPException
from src.models.entities import Pivot,Review,Reconciliation,Receipt,ReceiptBatch
from src.services.analysis import key
def ensure_pivot(s,i):
 r=s.get(Pivot,i)
 if not r:raise HTTPException(404,'透视方案不存在')
 return r
def ensure_review(s,i):
 r=s.get(Review,i)
 if not r:raise HTTPException(404,'差异复核不存在')
 return r
def cell(s,i,a,b):
 r=ensure_pivot(s,i)
 if r.state!='done':raise HTTPException(409,'透视完成后才能核对差异')
 c=next((c for c in r.result['cells'] if c['row_key']==a and c['col_key']==b),None)
 if not c or c['count']==0:raise HTTPException(404,'该透视单元没有结算记录')
 return r,c
def ensure_reconciliation(s,i):
 r=s.get(Reconciliation,i)
 if not r:raise HTTPException(404,'核销版本不存在')
 return r
def done_reconciliation(s,i):
 r=ensure_reconciliation(s,i)
 if r.state!='done':raise HTTPException(409,'核销完成后才能查看分配或导出')
 return r
def ensure_receipt(s,i):
 r=s.get(Receipt,i)
 if not r:raise HTTPException(404,'回单不存在')
 return r

