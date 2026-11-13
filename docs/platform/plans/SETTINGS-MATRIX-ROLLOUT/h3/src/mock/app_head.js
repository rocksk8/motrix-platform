/* 甲份 mockup：業務與財務規則。DATA 由 gen_index.py 從 settings_groups.json（registry 匯出）＋盤點表產生。值（目前生效值、來源、人名）是假資料。 */
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const R = {};
D.rows.forEach(r => R[r.id] = r);
/* r3：sv＝已儲存（生效中）的值；val＝畫面上的草稿值（點選只改 val，按「儲存」才寫入 sv） */
const S = {sv: {}, val: {}, chg: {}, pend: {}, src: {}, sel: new Set(), skip: {}, batchIds: new Set(), pdraft: {}, log: [], seg: '全部', view: {k: 'home'}, flash: null, tab: 't1', f: 'all', q: '', sec: 'all', advOpen: {}, hv: {}, last: null, toastT: null};
D.rows.forEach(r => {
  S.sv[r.id] = (r.id in D.fake) ? D.fake[r.id] : r.def;
  S.val[r.id] = JSON.parse(JSON.stringify(S.sv[r.id]));
  S.src[r.id] = D.fakeSrc[r.id] || null;
  if (D.fakeSrc[r.id]) S.chg[r.id] = {by: D.fakeSrc[r.id].by, at: D.fakeSrc[r.id].at};
});
Object.keys(D.fakePend).forEach(id => S.pend[id] = D.fakePend[id]);
S.log = [
  {id: 'finance_reports.aging_day3', by: '王經理', at: '11/05 10:12', reason: '客戶付款習慣變慢', old: '90 天', neu: '60 天'},
  {id: 'quote_defaults.valid_days', by: '李會計', at: '10/28 16:40', reason: '報價單有效期統一', old: '30 天', neu: '14 天'},
  {id: 'profit_warning.quote_form_low', by: '王經理', at: '10/28 09:03', reason: '利潤要求提高', old: '12 %', neu: '15 %'},
  {id: 'alerts.warranty_report_days', by: '李會計', at: '10/20 14:22', reason: '保固單提早提醒', old: '60 天', neu: '90 天'},
  {id: 'quote_backfill.auto_off_hours', by: '王經理', at: '10/12 11:05', reason: '補開作業限時', old: '24 小時', neu: '12 小時'}
].filter(e => e.id in R);
const CC = D.ccDays;
const TODAY = '11/13';
function nowHM() { const d = new Date(); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }

/* ---------- 判定 ---------- */
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const isDiff = r => !same(S.val[r.id], r.def);
function vt(r, v) {
  if (r.choices && r.choices.length) { const c = r.choices.find(c => c.value === v); return c ? c.label : String(v); }
  if (r.type === 'bool') return v ? '開啟' : '關閉';
  if (r.type === 'str') return v === '' ? '（空白）' : '「' + v + '」';
  return (typeof v === 'number' ? v.toLocaleString('zh-TW') : v) + (r.unit ? ' ' + r.unit : '');
}
function isLoosen(r, oldv, newv) {
  if (!r.loosen || typeof oldv !== 'number' || typeof newv !== 'number') return false;
  return r.loosen === 'up' ? newv > oldv : newv < oldv;
}
const heavyRisk = r => ['money', 'legal', 'security'].includes(r.risk);
function depOff(r) {
  const d = D.deps[r.id];
  if (!d) return null;
  const on = S.val[d];
  return on ? null : '要先開啟：' + R[d].name.replace(/[「」]/g, '');
}
function validate(r, v) {
  if (typeof v === 'number' && (r.type === 'int' || r.type === 'float')) {
    if (isNaN(v)) return '請輸入數字';
    if (r.min != null && v < r.min) return '不能小於 ' + r.min;
    if (r.max != null && v > r.max) return '不能大於 ' + r.max;
    if (r.type === 'int' && !Number.isInteger(v)) return '請輸入整數';
  }
  const pair = (lowId, goodId, val, id) => {
    const lo = id === lowId ? val : S.val[lowId], go = id === goodId ? val : S.val[goodId];
    return lo < go ? null : '紅線必須低於達標線';
  };
  for (const [lo, go] of D.pairs) if (r.id === lo || r.id === go) { const m = pair(lo, go, v, r.id); if (m) return m; }
  const ag = ['finance_reports.aging_day1', 'finance_reports.aging_day2', 'finance_reports.aging_day3'];
  if (ag.includes(r.id)) {
    const a = ag.map(i => i === r.id ? v : S.val[i]);
    if (!(a[0] < a[1] && a[1] < a[2])) return '三個分界天數必須由小到大';
  }
  if (r.id === 'quote_defaults.valid_days' && v > S.val['quote_approval.max_valid_days']) return '預設有效天數不能超過「有效天數上限」（' + S.val['quote_approval.max_valid_days'] + ' 天）';
  return null;
}
function matchRow(r) {
  const f = S.f;
  if (f === 'diff' && !isDiff(r)) return false;
  if (f === 'heavy' && !r.heavy) return false;
  if (f === 'oth' && !r.others) return false;
  if (f === 'ext' && !r.ext) return false;
  if (f === 'adv' && !r.adv) return false;
  if (f === 'batch' && !r.elig) return false;
  if (f === 'pend' && !S.pend[r.id]) return false;
  if (S.sec !== 'all' && r.top !== S.sec) return false;
  const q = S.q.trim().toLowerCase();
  if (q) {
    const hay = (r.name + ' ' + r.id + ' ' + r.desc + ' ' + r.groupLabel + ' ' + r.secLabel + ' ' + (r.choices || []).map(c => c.label).join(' ')).toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

/* ---------- 版面 ---------- */
function tags(r) {
  let h = '';
  if (r.heavy) h += ' <span class="pill heavy" title="' + esc(r.dangerText) + '">影響大</span>';
  if (r.others) h += ' <span class="pill oth">影響別人</span>';
  if (r.ext) h += ' <span class="pill ext" title="' + esc(r.ext) + '">需外部設定</span>';
  if (r.cust) h += ' <span class="pill cust">客戶看得到</span>';
  if (r.adv) h += ' <span class="pill adv">進階</span>';
  return h;
}
function srcBadge(r) {
  const p = S.pend[r.id], s = S.src[r.id];
  let h = '';
  if (p) h = '<span class="pill pnd">' + (p.need2 ? '等待加核准' : '只等待') + '</span>';
  else if (s) h = '<span class="pill oth">公司</span> <span class="mute">' + esc(s.by) + '・' + esc(s.at) + '</span>';
  else h = '<span class="pill adv">預設</span>';
  if (!same(S.val[r.id], S.sv[r.id])) h += ' <span class="pill draft">未儲存</span>';
  if (isDiff(r)) h += '<div class="dot">● 與預設不同（預設：' + esc(vt(r, r.def)) + '）</div>';
  return '<div class="src">' + h + '</div>';
}
function ctl(r) {
  const off = depOff(r), dis = off ? ' disabled' : '';
  const v = S.val[r.id];
  let h = '';
  if (r.choices && r.choices.length) {
    h = r.choices.map(c => {
      const na = /尚未提供/.test(c.label);
      const on = c.value === v;
      return '<label class="opt' + (on ? ' on' : '') + (na ? ' dis' : '') + '"><input type="radio" name="' + r.id + '" data-chg="' + r.id + '" value="' + c.value + '"' + (on ? ' checked' : '') + (na || off ? ' disabled' : '') + '><b>' + esc(c.label) + '</b><small>' + esc(c.impact) + '</small></label>';
    }).join('');
  } else if (r.type === 'bool') {
    h = '<button class="sw" role="switch" aria-checked="' + (v ? 'true' : 'false') + '" data-act="toggle" data-id="' + r.id + '"' + dis + ' aria-label="' + esc(r.name) + '"></button> <span class="mute">' + (v ? '開啟' : '關閉') + '</span>';
  } else if (r.type === 'str' && D.chipKeys.includes(r.id)) {
    h = '<div class="chips">' + String(v).split(',').filter(Boolean).map(x => '<span>' + esc(x) + '</span>').join('') + '</div><input type="text" style="width:100%" data-chg="' + r.id + '" value="' + esc(v) + '"' + dis + ' aria-label="' + esc(r.name) + '"><div class="mute">逗號分隔，越前面越優先，最多 20 個</div>';
  } else if (r.type === 'str' && (r.id === 'quote_defaults.estimate_no_prefix' || r.id === 'quote_alt.total_text')) {
    h = '<input type="text" style="width:100%" data-chg="' + r.id + '" value="' + esc(v) + '"' + dis + ' aria-label="' + esc(r.name) + '"><div class="mute">' + (r.id === 'quote_alt.total_text' ? '客戶看到的樣子：稅前合計　' + esc(v) + '　／　總計　' + esc(v) : '估價單單號會長這樣：' + esc(v) + '-0001（字首 + 流水號，示意）') + '</div>';
  } else if (r.type === 'str') {
    h = '<textarea style="width:100%" rows="2" data-chg="' + r.id + '"' + dis + ' aria-label="' + esc(r.name) + '">' + esc(v) + '</textarea>';
    if (r.id === 'quote_alt.note_template') h += '<div style="margin-top:4px"><button class="btn sm" data-act="ins" data-id="' + r.id + '" data-tok="{items}">＋插入「項次」</button> <button class="btn sm" data-act="ins" data-id="' + r.id + '" data-tok="{group}">＋插入「組別名稱」</button></div>';
    h += '<div class="mute">客戶看到的樣子：' + esc(String(v).replace('{items}', '1、2').replace('{group}', '電源方案')) + '</div>';
  } else {
    const step = r.type === 'float' ? '0.5' : '1';
    h = '<input type="number" step="' + step + '" data-chg="' + r.id + '" value="' + v + '"' + (r.min != null ? ' min="' + r.min + '"' : '') + (r.max != null ? ' max="' + r.max + '"' : '') + dis + ' aria-label="' + esc(r.name) + '" style="width:110px">' + (r.unit ? '<span class="unit">' + esc(r.unit) + '</span>' : '') + '<div class="mute">範圍 ' + (r.min != null ? r.min : '—') + '～' + (r.max != null ? r.max : '—') + (r.rec !== undefined && r.rec !== null ? '　建議 ' + esc(vt(r, r.rec)) : '') + '</div>';
  }
  if (off) h += '<div class="note">' + off + '，目前不會生效</div>';
  const p = S.pend[r.id];
  if (p) h += '<div class="pendline">' + (p.need2 ? '<b>等待加核准</b>：' : '<b>只等待</b>：') + '之後改成 ' + esc(vt(r, p.val)) + '；' + esc(p.eff) + ' 期滿' + (p.need2 ? '，且第二位最高管理者核准後才生效' : '自動生效，不需要別人核准') + '。<button class="btn sm" data-act="cancelpend" data-id="' + r.id + '">撤銷申請</button></div>';
  else if (!same(S.val[r.id], S.sv[r.id])) { const k = pendKind(r, S.sv[r.id], S.val[r.id]); if (k !== 'now') h += '<div class="pendline">儲存後：' + KIND_TXT[k] + '</div>'; }
  return h;
}
function checkbox(r) {
  if (r.type === 'str') return '<span class="mute" title="' + esc(r.why) + '">✎</span>';
  const dis = !r.elig;
  return '<input type="checkbox" data-act="sel" data-id="' + r.id + '"' + (S.sel.has(r.id) ? ' checked' : '') + (dis ? ' disabled title="' + esc(r.why) + '"' : '') + ' aria-label="選取 ' + esc(r.name) + '">';
}
function rowHtml(r) {
  const off = depOff(r);
  return '<div class="row' + (same(S.val[r.id], S.sv[r.id]) ? '' : ' drf') + (isDiff(r) ? ' chg' : '') + (S.pend[r.id] ? ' pnd' : '') + (off ? ' off' : '') + (S.sel.has(r.id) ? ' sel' : '') + '" data-row="' + r.id + '">'
    + '<div>' + checkbox(r) + '</div>'
    + '<div><div class="nm">' + esc(r.name) + ' <button class="q" data-act="help" data-id="' + r.id + '" aria-label="說明">?</button>' + tags(r) + '</div><div class="k">' + r.id + '</div><div class="ds">' + esc(r.desc) + '</div></div>'
    + '<div>' + ctl(r) + '</div>'
    + '<div>' + srcBadge(r) + '</div>'
    + '<div>' + (isDiff(r) ? '<button class="btn sm" data-act="reset" data-id="' + r.id + '">還原預設</button>' : '') + '</div></div>';
}
/* 特殊區塊 */
const PW = [['報價單表單', 'profit_warning.quote_form_low', 'profit_warning.quote_form_good'], ['報表頁分項', 'profit_warning.report_low', 'profit_warning.report_good'], ['案件頁與結算摘要', 'profit_warning.case_floor', 'profit_warning.case_good'], ['結算頁', null, 'profit_warning.settlement_good']];
function band(lo, go) {
  const mn = -10, mx = 40, pc = x => Math.max(0, Math.min(100, (x - mn) / (mx - mn) * 100));
  const a = lo == null ? 0 : pc(lo), b = pc(go);
  return '<div class="band" title="紅：低於紅線　黃：介於　綠：達標"><i style="left:0;width:' + a + '%;background:#e5484d"></i><i style="left:' + a + '%;width:' + (b - a) + '%;background:#f5b041"></i><i style="left:' + b + '%;right:0;background:#30a46c"></i></div>';
}
function profitBlock(rows) {
  const vis = id => id && rows.find(r => r.id === id);
  let h = '<div class="presets"><b>預設組合</b><span class="mute">一鍵填入整張表（套用前會先確認）：</span>';
  D.profitPresets.forEach((p, i) => h += '<button class="btn sm" data-act="preset" data-i="' + i + '">' + esc(p.name) + '</button>');
  h += '</div><table class="mx stack"><thead><tr><th></th><th class="l">畫面</th><th>紅線（低於變紅）</th><th>達標線（達到變綠）</th><th>色帶預覽</th><th>來源</th></tr></thead><tbody>';
  PW.forEach(([nm, lo, go]) => {
    if (!(vis(lo) || vis(go))) return;
    const ids = [lo, go].filter(Boolean), sel = ids.every(i => S.sel.has(i));
    const cellOf = id => {
      if (!id) return '<span class="mute">— 不適用</span>';
      const r = R[id], p = S.pend[id];
      return '<input type="number" step="0.5" data-chg="' + id + '" value="' + S.val[id] + '" min="' + r.min + '" max="' + r.max + '" aria-label="' + esc(r.name) + '"><span class="unit">%</span>' + (isDiff(r) ? '<div class="dot">●預設 ' + r.def + '</div>' : '');
    };
    const anyDiff = ids.some(i => isDiff(R[i]));
    h += '<tr class="' + (sel ? 'sel' : '') + '"><td><input type="checkbox" data-act="selpair" data-ids="' + ids.join(',') + '"' + (sel ? ' checked' : '') + ' aria-label="選取 ' + nm + '"></td><td class="l" data-l="畫面"><b>' + nm + '</b> <button class="q" data-act="help" data-id="' + (go) + '">?</button><div class="k">' + ids.join('、').replace(/profit_warning\./g, '') + '</div></td><td data-l="紅線">' + cellOf(lo) + '</td><td data-l="達標線">' + cellOf(go) + '</td><td data-l="色帶">' + band(lo ? S.val[lo] : null, S.val[go]) + '</td><td data-l="來源">' + (anyDiff ? '<span class="pill oth">公司</span>' : '<span class="pill adv">預設</span>') + '</td></tr>';
  });
  return h + '</tbody></table>';
}
function lockBlock(rows) {
  let h = '<div class="banner2">這 ' + rows.length + ' 條是「客戶回簽後」的高風險鎖定規則：每一格的變更都要填原因、要等 ' + CC + ' 天才生效；放寬（選到較寬的那一格）還要第二位最高管理者核准。<b>不能批次。</b>灰色格＝系統尚未提供。</div>';
  h += '<table class="mx stack"><thead><tr><th class="l" style="width:26%">規則</th><th>最嚴（建議）</th><th>放寬一</th><th>放寬二</th><th style="width:130px">目前</th></tr></thead><tbody>';
  rows.forEach(r => {
    const p = S.pend[r.id];
    h += '<tr><td class="l" data-l="規則"><b>' + esc(r.name) + '</b> <button class="q" data-act="help" data-id="' + r.id + '">?</button> <span class="pill heavy">影響大</span><div class="k">' + r.id + '</div></td>';
    for (let i = 0; i < 3; i++) {
      const c = r.choices[i];
      if (!c) { h += '<td></td>'; continue; }
      const na = /尚未提供/.test(c.label), on = c.value === S.val[r.id];
      h += '<td data-l="' + (i === 0 ? '最嚴' : '放寬' + (i === 1 ? '一' : '二')) + '"><button class="cell' + (on ? ' on' : '') + '" data-act="lockpick" data-id="' + r.id + '" data-v="' + c.value + '"' + (na ? ' disabled' : '') + '>' + (on ? '● ' : '') + esc(c.label) + '<small>' + esc(c.impact) + '</small></button></td>';
    }
    h += '<td data-l="目前">' + (p ? '<span class="pill pnd">等待生效</span><div class="mute">→ ' + esc(vt(r, p.val)) + '</div>' : isDiff(r) ? '<span class="pill oth">公司</span><div class="dot">●與預設不同</div>' : '<span class="pill adv">預設</span>') + '</td></tr>';
  });
  return h + '</tbody></table>';
}
function agingBlock() {
  const ids = ['finance_reports.aging_day1', 'finance_reports.aging_day2', 'finance_reports.aging_day3'];
  const d = ids.map(i => S.val[i]), off = !S.val['finance_reports.custom_aging'];
  const mx = Math.max(d[2] * 1.4, 120), pc = x => x / mx * 100;
  let h = '<div class="presets"><b>帳齡分界</b><span class="mute">預設組合：</span>';
  D.agingPresets.forEach((p, i) => h += '<button class="btn sm" data-act="agingpreset" data-i="' + i + '">' + esc(p.name) + '</button>');
  h += '</div><div style="padding:10px 12px' + (off ? ';opacity:.5' : '') + '"><div class="band" style="height:18px"><i style="left:0;width:' + pc(d[0]) + '%;background:#30a46c"></i><i style="left:' + pc(d[0]) + '%;width:' + (pc(d[1]) - pc(d[0])) + '%;background:#f5b041"></i><i style="left:' + pc(d[1]) + '%;width:' + (pc(d[2]) - pc(d[1])) + '%;background:#ef7a3c"></i><i style="left:' + pc(d[2]) + '%;right:0;background:#e5484d"></i></div>'
    + '<div class="mute" style="margin:4px 0 8px">0 ～ ' + d[0] + ' 天（正常）｜' + (d[0] + 1) + ' ～ ' + d[1] + ' 天（注意，橘字）｜' + (d[1] + 1) + ' ～ ' + d[2] + ' 天（紅字）｜超過 ' + d[2] + ' 天（逾期很久）</div>';
  ids.forEach((id, i) => { const r = R[id]; h += '<label style="margin-right:14px">' + esc(r.name) + ' <input type="number" data-chg="' + id + '" value="' + S.val[id] + '" min="' + r.min + '" max="' + r.max + '" style="width:80px"' + (off ? ' disabled' : '') + '><span class="unit">天</span></label>'; });
  h += (off ? '<div class="note">目前未啟用自訂區間，維持 30／60／90 天；套用預設組合不會自動打開開關。</div>' : '') + '<div class="mute">三個天數要由小到大；填不合理時報表會退回 30／60／90，所以畫面先擋下。</div></div>';
  return h;
}
function legalBlock(rows) {
  const m = R['legal_params_reminder.start_month'], dd = R['legal_params_reminder.start_day'];
  const sel = ['legal_params_reminder.start_month', 'legal_params_reminder.start_day'].every(i => S.sel.has(i));
  let o = ''; for (let i = 1; i <= 12; i++) o += '<option value="' + i + '"' + (i === S.val[m.id] ? ' selected' : '') + '>' + i + ' 月</option>';
  let o2 = ''; for (let i = 1; i <= 28; i++) o2 += '<option value="' + i + '"' + (i === S.val[dd.id] ? ' selected' : '') + '>' + i + ' 日</option>';
  return '<div class="row' + (sel ? ' sel' : '') + '"><div><input type="checkbox" data-act="selpair" data-ids="' + m.id + ',' + dd.id + '"' + (sel ? ' checked' : '') + ' aria-label="選取"></div><div><div class="nm">每年從哪一天起，提醒設定下一年度法規參數 <button class="q" data-act="help" data-id="' + m.id + '">?</button> <span class="pill heavy">放寬須核准</span></div><div class="k">' + m.id + '、' + dd.id + '</div><div class="ds">' + esc(m.desc) + ' 日數只能選到 28，避免沒有 29～31 日的月份。往後延＝放寬提醒，須第二位最高管理者核准。</div></div><div>每年 <select data-chg="' + m.id + '" aria-label="月">' + o + '</select> <select data-chg="' + dd.id + '" aria-label="日">' + o2 + '</select> 起提醒</div><div>' + srcBadge(m) + '</div><div></div></div>';
}
function notePreview() {
  const g = k => S.val['completion_note.' + k];
  const items = [['分段標題：入口網路', 0], ['攝影機 IPC-2K', 10], ['電源供應器', 5]];
  const done = [0, 6, 0];
  let h = '<div class="panelnote"><b>帶入後的樣子</b>（用報價單 3 列示範，依上面目前的設定即時變化）<table class="mx" style="margin-top:6px"><thead><tr><th class="l">品名</th><th>報價數量</th><th>預設完工數量</th><th>預設狀態</th></tr></thead><tbody>';
  const st = ['完成', '部分完成', '未施作'][g('default_status')];
  items.forEach((it, i) => {
    if (it[1] === 0) { if (g('include_headers')) h += '<tr><td class="l" colspan="4"><b>' + it[0] + '</b></td></tr>'; return; }
    const remain = it[1] - done[i], q = g('qty_mode') === 0 ? remain : it[1];
    h += '<tr><td class="l">' + (g('brand_prefix') ? '某牌 ' : '') + it[0] + '</td><td>' + it[1] + '</td><td>' + q + '</td><td>' + st + '</td></tr>';
  });
  return h + '</tbody></table><span class="mute">範例：第二列已完工 6 個。</span></div>';
}
/* 區段 */
function sectionBody(code, rows) {
  const used = new Set();
  let h = '';
  if (code === 'p-warning') {
    const pr = rows.filter(r => r.gk === 'profit_warning');
    if (pr.length) { h += profitBlock(pr); pr.forEach(r => used.add(r.id)); }
  } else if (code === 'q-alt-lock') {
    const lr = rows.filter(r => r.lockRule);
    if (lr.length) { h += lockBlock(lr); lr.forEach(r => used.add(r.id)); }
  } else if (code === 'f-reports') {
    const g = rows.find(r => r.id === 'finance_reports.custom_aging');
    if (g) { h += rowHtml(g); used.add(g.id); }
    if (rows.some(r => /aging_day/.test(r.id))) { h += agingBlock(); rows.filter(r => /aging_day/.test(r.id)).forEach(r => used.add(r.id)); }
  } else if (code === 'r-legal') {
    if (rows.length) { h += legalBlock(rows); rows.forEach(r => used.add(r.id)); }
  }
  const rest = rows.filter(r => !used.has(r.id));
  const adv = rest.filter(r => r.adv), norm = rest.filter(r => !r.adv);
  h += norm.map(rowHtml).join('');
  if (adv.length) {
    const open = S.advOpen[code] || S.f === 'adv' || S.q.trim();
    h += '<div class="panelnote"><button class="btn sm" data-act="advtoggle" data-sec="' + code + '">' + (open ? '▼' : '▶') + ' 進階（' + adv.length + ' 項，平常不用動）</button></div>';
    if (open) h += adv.map(rowHtml).join('');
  }
  if (code === 'c-note') h += notePreview();
  return h;
}
