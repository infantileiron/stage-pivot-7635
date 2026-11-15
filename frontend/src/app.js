import {api,post} from './api/client.js';import {state} from './stores/session.js';import {routes,page} from './router/index.js';import {values,feedback} from './hooks/form.js';import {esc} from './utils/html.js';import * as settlements from './pages/settlements.js';import * as layout from './pages/layout.js';import * as pivot from './pages/pivot.js';import * as reviews from './pages/reviews.js';import * as receipts from './pages/receipts.js';import * as reconciliation from './pages/reconciliation.js';
const pages=[settlements,layout,pivot,reviews,receipts,reconciliation];
const root=document.querySelector('#app');
async function load(){
 [state.settlements,state.pivots,state.reviews,state.receipts,state.batches,state.reconciliations]=
  await Promise.all(['/settlements','/pivots','/reviews','/receipts','/receipt-batches','/reconciliations'].map(x=>api(x)));
 state.selected=state.pivots.find(r=>r.id===state.selected?.id)||state.pivots[0]||null;
 state.reconDetail=state.reconciliations.find(r=>r.id===state.reconDetail?.id)||state.reconciliations.find(r=>r.is_current)||state.reconciliations[0]||null;
}
function login(){root.innerHTML=`<div class="login"><section class="cover"><div class="eyebrow">YUN MU / SETTLEMENT PROGRAMME 012</div><h1>散场之后，<br>每一笔都有回声。</h1><p>云幕剧院 · 场次结算节目单<br>明细 → 透视 → 冻结下钻 → 差异签核 → 回单核销<br>三处场馆 / 分币守恒 / 逐笔可核</p></section><section><div class="eyebrow">STAGE PIVOT</div><h2>登录结算节目单</h2><form id="login"><label>工作邮箱<input name="email" type="email" value="analyst@demo.local" required></label><label>密码<input name="password" type="password" value="Demo123!" required></label><button class="primary">进入场次结算</button></form><p id="error" class="error"></p><p>admin / analyst / viewer @demo.local<br>密码：Demo123!</p></section></div>`;document.querySelector('form').onsubmit=e=>{e.preventDefault();run(async()=>{let d=await post('/auth/login',values(e.target));localStorage.setItem('token',d.token);state.user=d.user;await load();render()})}}
function render(){let n=Math.min(pages.length-1,Math.max(0,page()));root.innerHTML=`<header><div class="brand">云幕 / 场次结算节目单 <span class="eyebrow">STAGE PIVOT</span></div><div>${esc(state.user.email)} · ${esc(state.user.role)} <button id="logout">退出</button></div></header><div class="layout"><nav>${routes.map((r,i)=>`<button data-nav="${i}" class="${i===n?'active':''}">0${i+1} ${r}</button>`).join('')}<span class="eyebrow">THEATRE ACCOUNTS / 2026</span></nav><main><div class="intro"><div><div class="eyebrow">SETTLEMENT PROGRAMME / 0${n+1}</div><h1>${routes[n]}</h1><p>让票款、退款、渠道费与渠道回单回到具体场次。每份透视与核销保留冻结明细，差异由财务负责人签核。</p></div><span class="tag">3 场馆 / 散场结算 / 逐笔核销</span></div><p id="error" class="error"></p>${pages[n].render()}</main></div>`;bind();if(state.user.role==='viewer')document.querySelectorAll('form button,button.primary').forEach(b=>{b.disabled=true;b.textContent='观察员只读'});}
async function run(fn){try{await fn()}catch(e){feedback(e.message)}}
function download(path,filename){return run(async()=>{let d=await api(path);let u=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));let a=document.createElement('a');a.href=u;a.download=filename;a.click();URL.revokeObjectURL(u)})}
function bind(){
 document.querySelectorAll('[data-nav]').forEach(b=>b.onclick=()=>location.hash=b.dataset.nav);
 document.querySelector('#logout').onclick=()=>{localStorage.removeItem('token');state.user=null;login()};
 for(let [id,path] of [['settlement','/settlements'],['pivot','/pivots'],['review','/reviews']]){
  const f=document.querySelector('#'+id);if(!f)continue;
  f.onsubmit=e=>{e.preventDefault();run(async()=>{let d=values(f);for(let k of ['gross_cents','refund_cents','fee_cents','seats','checked','pivot_id','expected_cents'])if(k in d)d[k]=Number(d[k]);let record=d.record_id;delete d.record_id;let created=record?await api(path+'/'+record,{method:'PUT',body:JSON.stringify(d)}):await post(path,d);if(id==='pivot'){state.selected=created;state.drill=null;state.chosen=null}await load();if(id==='pivot'&&location.hash!=='#2')location.hash='2';else render()})};
 }
 // 批量收单
 const rb=document.querySelector('#receipt-batch');
 if(rb)rb.onsubmit=e=>{e.preventDefault();run(async()=>{let d=values(rb);let out=await post('/receipt-batches',d);let fb=document.querySelector('#receipt-feedback');fb.style.display='block';fb.textContent=`入账 ${out.ingested.length} 笔，跳过(同内容重试) ${out.skipped.length} 笔`+(out.parse_errors.length?('；解析问题：'+out.parse_errors.join('；')):'');await load();render()})};
 // 发起核销
 const rc=document.querySelector('#reconciliation');
 if(rc)rc.onsubmit=e=>{e.preventDefault();run(async()=>{let created=await post('/reconciliations',values(rc));state.reconDetail=created;state.reconDrill=null;await load();state.reconDetail=await api('/reconciliations/'+created.id);render()})};
 document.querySelectorAll('[data-recon]').forEach(b=>b.onclick=()=>run(async()=>{state.reconDetail=await api('/reconciliations/'+b.dataset.recon);state.reconDrill=null;render()}));
 const rr=document.querySelector('#recon-refresh');if(rr)rr.onclick=()=>run(async()=>{if(state.reconDetail){state.reconDetail=await api('/reconciliations/'+state.reconDetail.id)}await load();render()});
 document.querySelectorAll('[data-drill-receipt]').forEach(b=>b.onclick=()=>run(async()=>{state.reconDrill=await api('/reconciliations/'+state.reconDetail.id+'/allocations?'+new URLSearchParams({receipt_no:b.dataset.drillReceipt}));render()}));
 document.querySelectorAll('[data-drill-code]').forEach(b=>b.onclick=()=>run(async()=>{state.reconDrill=await api('/reconciliations/'+state.reconDetail.id+'/allocations?'+new URLSearchParams({code:b.dataset.drillCode}));render()}));
 const rcd=document.querySelector('#recon-clear-drill');if(rcd)rcd.onclick=()=>{state.reconDrill=null;render()};
 const rdl=document.querySelector('#recon-download');if(rdl)rdl.onclick=()=>download('/reconciliations/'+state.reconDetail.id+'/export','reconciliation-'+state.reconDetail.id+'.json');
 document.querySelectorAll('[data-pivot]').forEach(b=>b.onclick=()=>run(async()=>{state.selected=await api('/pivots/'+b.dataset.pivot);state.drill=null;state.chosen=null;if(location.hash!=='#2')location.hash='2';else render()}));
 document.querySelectorAll('[data-drill-row]').forEach(b=>b.onclick=()=>run(async()=>{state.drill=await api('/pivots/'+state.selected.id+'/drill?'+new URLSearchParams({row_key:b.dataset.drillRow,col_key:b.dataset.drillCol}));render();document.querySelector('#draft-review')?.scrollIntoView({block:'center'})}));
 const draft=document.querySelector('#draft-review');if(draft)draft.onclick=()=>{state.chosen=state.drill.cell;location.hash='3'};
 document.querySelectorAll('[data-approve]').forEach(b=>b.onclick=()=>run(async()=>{await post('/reviews/'+b.dataset.approve+'/approve',{});await load();render()}));
 const refresh=document.querySelector('#refresh');if(refresh)refresh.onclick=()=>run(async()=>{await load();render()}));
 const downloadBtn=document.querySelector('#download');if(downloadBtn)downloadBtn.onclick=()=>download('/pivots/'+state.selected.id+'/export','stage-pivot-'+state.selected.id+'.json');
}
window.onhashchange=()=>{if(state.user){render();window.scrollTo(0,0)}};if(localStorage.getItem('token'))run(async()=>{try{state.user=await api('/me');await load();render()}catch(e){localStorage.removeItem('token');login();feedback(e.message)}});else login();
