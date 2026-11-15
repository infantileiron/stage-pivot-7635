import {state} from '../stores/session.js';
import {esc} from '../utils/html.js';
import {badge} from '../components/common/status.js';
import {table} from '../components/common/table.js';
import {field} from '../components/common/fields.js';
import {money} from '../utils/format.js';
import {CHANNELS} from '../constants/enums.js';

const sample=()=>`回单编号,到账日,渠道,金额,覆盖起,覆盖止
RC-1001,2026-10-06,剧院直营,128000,2026-09-01,2026-10-31
RC-1002;2026-10-09;票务合作;2560.50;2026-09-01;2026-10-31`;

export function render(){
 return `<div class="split"><section class="panel"><h2>批量收单，逐笔可核</h2><p class="notice">每行一张回单：编号、到账日、渠道、金额、覆盖场次起、覆盖场次止。逗号/竖线/分号/制表符/多空格均可分隔，金额支持“12.34 元”或整数分。同批重试不重复入账，同号异内容整批拒绝。</p>
 <h3>已入账回单（${state.receipts.length}）</h3>
 ${table(['回单编号','到账日','渠道','金额 ¥','覆盖起','覆盖止'],state.receipts.map(r=>[r.receipt_no,r.arrival_day,r.channel,money(r.amount_cents),r.cover_from,r.cover_to]))}
 <h3>收单批次</h3>
 ${state.batches.map(b=>`<article class="rec"><h3>${esc(b.batch_no)} ${badge(b.state)} · ${esc(b.source)}</h3><p>解析提示：${b.parse_errors&&b.parse_errors.length?esc(b.parse_errors.join('；')):'无'}${b.note?'<br>备注：'+esc(b.note):''}</p></article>`).join('')||'<p>尚无批次。</p>'}
 </section>
 <aside class="side"><h2>粘贴回单明细</h2>
 <form id="receipt-batch">
 ${field('批次号','batch_no','text','required minlength=2 value=B-'+(state.batches.length+1))}
 <label>回单明细文本<textarea name="raw_text" rows="10" placeholder="每行：编号,到账日,渠道,金额,覆盖起,覆盖止" required>${esc(sample())}</textarea></label>
 ${field('备注（可选）','note','text','maxlength=2000')}
 <button class="primary">批量解析并入账</button>
 </form>
 <p class="notice">合法渠道：${CHANNELS.map(esc).join('、')}。到账日须落在覆盖范围内。</p>
 <div id="receipt-feedback" class="notice" style="display:none"></div>
 </aside></div>`;
}
