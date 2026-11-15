/** @typedef {{id:number,code:string,day:string,venue:string,play:string,channel:string,gross_cents:number,refund_cents:number,fee_cents:number,seats:number,checked:number}} Settlement */
/** @typedef {{id:number,name:string,row_dim:string,col_dim:string,state:string,result:object}} Pivot */
/** @typedef {{id:number,pivot_id:number,row_key:string,col_key:string,book_cents:number,expected_cents:number,difference_cents:number,status:string,note:string}} Review */
/** @typedef {{id:number,batch_id:number,receipt_no:string,arrival_day:string,channel:string,amount_cents:number,cover_from:string,cover_to:string,content_hash:string,ingested:boolean}} Receipt */
/** @typedef {{id:number,batch_no:string,source:string,state:string,parse_errors:string[],note:string}} ReceiptBatch */
/** @typedef {{receipt_no:string,code:string,channel:string,arrival_day:string,settlement_day:string,gap_days:number,allocated_cents:number}} Allocation */
/** @typedef {{id:number,name:string,state:string,is_current:boolean,snapshot_fingerprint:string,error:string,result:{allocations:Allocation[],receipts:object[],settlements:object[],totals:object,weighted_gap_cents_days:number,conserved:boolean,method:string}}} Reconciliation */
