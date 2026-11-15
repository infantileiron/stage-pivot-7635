import {state} from '../stores/session.js';
import {esc} from '../utils/html.js';
import {badge} from '../components/common/status.js';
import {table} from '../components/common/table.js';
import {field} from '../components/common/fields.js';
import {money} from '../utils/format.js';

function allocationTable(rows){
 return `<div class="scroll"><table><thead><tr><th>回单编号</th><th>场次编号</th><th>渠道</th><th>到账日</th><th>场次日</th><th>间隔(天)</th><th>分配 ¥</th></tr></thead><tbody>${
  rows.map(a=>`<tr><td><button data-drill-receipt="${esc(a.receipt_no)}">${esc(a.receipt_no)}</button></td>
   <td><button data-drill-code="${esc(a.code)}">${esc(a.code)}</button></td>
   <td>${esc(a.channel)}</td><td>${esc(a.arrival_day)}</td><td>${esc(a.settlement_day)}</td>
   <td>${a.gap_days}</td><td>${money(a.allocated_cents)}</td></tr>`).join('')
 }</tbody></table></div>`;
}

function metrics(r){
 const t=r.result.totals;
 return `<div class="metrics">
 <div><strong>${money(t.allocated_cents)}</strong>核销总额 / 元</div>
 <div><strong>${money(t.receipt_remaining_cents)}</strong>回单余款 / 元</div>
 <div><strong>${money(t.settlement_remaining_cents)}</strong>场次余款 / 元</div>
 <div><strong>${r.result.conserved?'守恒':'异常'}</strong>双方恒等式</div>
 <div><strong>${r.result.weighted_gap_cents_days.toLocaleString('zh-CN')}</strong>金额加权间隔(分·天)</div>
 </div>`;
}

export function render(){
 const d=state.reconDetail;
 const done=d&&d.state==='done';
 const drillRows=state.reconDrill?state.reconDrill.allocations:null;
 return `<div class="split"><section class="panel">
 <div class="result-head"><h2>回单核销，整数分守恒分配 ${d?badge(d.state):''}</h2><button id="recon-refresh">刷新状态</button></div>
 ${done?`
 ${metrics(d)}
 <p class="notice">${esc(d.result.method)}</p>
 <div class="rulehead"><h3>分配明细（点击编号下钻）</h3>${drillRows?`<button id="recon-clear-drill">清除下钻（${drillRows.length} 笔）</button>`:'<span class="eyebrow">按回单或场次过滤</span>'}</div>
 ${allocationTable(drillRows||d.result.allocations)}
 <h3>回单侧余款</h3>
 ${table(['回单编号','渠道','到账 ¥','已核销 ¥','余款 ¥'],d.result.receipts.map(x=>[x.receipt_no,x.channel,money(x.amount_cents),money(x.allocated_cents),money(x.remaining_cents)]))}
 <h3>场次侧余款（净结算上限）</h3>
 ${table(['场次','日期','渠道','净结算 ¥','已核销 ¥','余款 ¥'],d.result.settlements.map(x=>[x.code,x.day,x.channel,money(x.net_cents),money(x.allocated_cents),money(x.remaining_cents)]))}
 <button id="recon-download">导出冻结分配 JSON</button>
 `:d?`<p class="notice">${esc(d.error||'后台计算中，请稍后刷新。')}</p>`:'<p class="notice">在右侧提交核销，或从历史版本选择一份查看冻结分配。</p>'}
 <h3>历史核销版本</h3>
 ${state.reconciliations.map(r=>`<button class="study" data-recon="${r.id}">#${r.id} ${esc(r.name)} ${badge(r.state)}${r.is_current?' · 当前':''}</button>`).join('')||'<p>尚无核销版本。</p>'}
 </section>
 <aside class="side"><h2>发起核销计算</h2>
 <p class="notice">提交即冻结当前场次与回单快照。计算从“待计算”到完成后原子替换当前版本；若场次已修订或有更新版本先完成，本次拒绝过期发布，旧版本保留。</p>
 <form id="reconciliation">
 ${field('核销名称','name','text','required minlength=2 value=渠道回单核销-'+(state.reconciliations.length+1))}
 <button class="primary">提交并后台计算</button>
 </form>
 <div id="recon-feedback" class="notice" style="display:none"></div>
 </aside></div>`;
}
