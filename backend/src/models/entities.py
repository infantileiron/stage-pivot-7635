from sqlalchemy import Column,Integer,BigInteger,String,JSON,Text,Boolean,ForeignKey
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True,nullable=False);password=Column(String(200));role=Column(String(20))
class Settlement(Base):
 __tablename__='settlements'
 id=Column(Integer,primary_key=True);code=Column(String(60),unique=True,nullable=False);day=Column(String(10));venue=Column(String(40));play=Column(String(60));channel=Column(String(30));gross_cents=Column(BigInteger);refund_cents=Column(BigInteger);fee_cents=Column(BigInteger);seats=Column(Integer);checked=Column(Integer)
class Pivot(Base):
 __tablename__='pivots'
 id=Column(Integer,primary_key=True);name=Column(String(100));row_dim=Column(String(30));col_dim=Column(String(30));state=Column(String(20),default='queued');result=Column(JSON,nullable=True);error=Column(Text,default='')
class Review(Base):
 __tablename__='reviews'
 id=Column(Integer,primary_key=True);pivot_id=Column(Integer,ForeignKey('pivots.id'));row_key=Column(String(100));col_key=Column(String(100));book_cents=Column(BigInteger);expected_cents=Column(BigInteger);difference_cents=Column(BigInteger);note=Column(Text);status=Column(String(20),default='draft')
class ReceiptBatch(Base):
 __tablename__='receipt_batches'
 id=Column(Integer,primary_key=True);batch_no=Column(String(60),unique=True,nullable=False);source=Column(String(20),default='text');state=Column(String(20),default='parsed');parse_errors=Column(JSON,default=list);note=Column(Text,default='')
class Receipt(Base):
 __tablename__='receipts'
 id=Column(Integer,primary_key=True);batch_id=Column(Integer,ForeignKey('receipt_batches.id'));receipt_no=Column(String(60),unique=True,nullable=False);arrival_day=Column(String(10));channel=Column(String(30));amount_cents=Column(BigInteger);cover_from=Column(String(10));cover_to=Column(String(10));content_hash=Column(String(64));ingested=Column(Boolean,default=True)
class Reconciliation(Base):
 __tablename__='reconciliations'
 id=Column(Integer,primary_key=True);name=Column(String(120));state=Column(String(20),default='queued');is_current=Column(Boolean,default=False);snapshot_fingerprint=Column(String(64));result=Column(JSON,nullable=True);error=Column(Text,default='')
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
