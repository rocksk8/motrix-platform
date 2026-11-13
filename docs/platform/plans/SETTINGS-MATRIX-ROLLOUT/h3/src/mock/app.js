/* 甲份 mockup：業務與財務規則。DATA 由 gen_index.py 從 settings_groups.json（registry 匯出）＋盤點表產生。值（目前生效值、來源、人名）是假資料。 */
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const R = {};
D.rows.forEach(r => R[r.id] = r);
const S = {gver: {}, gchg: {}, val: {}, ver: {}, pend: {}, src: {}, sel: new Set(), skip: {}, f: 'all', q: '', sec: 'all', advOpen: {}, hv: {}, last: null, toastT: null};
D.rows.forEach(r => { S.gver[r.gk] = 1;
  S.val[r.id] = (r.id in D.fake) ? D.fake[r.id] : r.def;
  S.ver[r.id] = 1;
  S.src[r.id] = D.fakeSrc[r.id] || null;
});
Object.keys(D.fakePend).forEach(id => S.pend[id] = D.fakePend[id]);
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
  if (p) h = '<span class="pill pnd">等待生效</span>';
  else if (s) h = '<span class="pill oth">公司</span> <span class="mute">' + esc(s.by) + '・' + esc(s.at) + '</span>';
  else h = '<span class="pill adv">預設</span>';
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
  if (p) h += '<div class="pendline">待生效：' + esc(vt(r, p.val)) + '（' + esc(p.eff) + ' 生效' + (p.need2 ? '；等第二位最高管理者核准' : '') + '）<button class="btn sm" data-act="cancelpend" data-id="' + r.id + '">取消待生效</button></div>';
  return h;
}
function checkbox(r) {
  if (r.type === 'str') return '';
  const dis = !r.elig;
  return '<input type="checkbox" data-act="sel" data-id="' + r.id + '"' + (S.sel.has(r.id) ? ' checked' : '') + (dis ? ' disabled title="' + esc(r.why) + '"' : '') + ' aria-label="選取 ' + esc(r.name) + '">';
}
function rowHtml(r) {
  const off = depOff(r);
  return '<div class="row' + (isDiff(r) ? ' chg' : '') + (S.pend[r.id] ? ' pnd' : '') + (off ? ' off' : '') + (S.sel.has(r.id) ? ' sel' : '') + '" data-row="' + r.id + '">'
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
function render() {
  const keepY = window.scrollY;
  let h = '';
  const all = D.rows;
  const visCount = all.filter(matchRow).length;
  h += '<div class="sum"><div class="card"><b>' + all.length + '</b><span class="mute">本頁設定項目</span></div><div class="card"><b>' + all.filter(isDiff).length + '</b><span class="mute">與預設不同</span></div><div class="card"><b>' + Object.keys(S.pend).length + '</b><span class="mute">等待生效</span></div><div class="card"><b>' + all.filter(r => r.elig).length + '</b><span class="mute">可批次（其餘永遠逐項）</span></div></div>';
  h += '<div class="card toolbar"><input type="search" id="q" placeholder="搜尋：名稱、代碼、說明、選項…" value="' + esc(S.q) + '" aria-label="搜尋">';
  [['all', '全部'], ['diff', '與預設不同'], ['heavy', '影響大'], ['oth', '影響別人'], ['ext', '需外部設定'], ['adv', '進階'], ['batch', '可批次'], ['pend', '等待生效']].forEach(([k, l]) => h += '<button class="chip" aria-pressed="' + (S.f === k) + '" data-act="filter" data-k="' + k + '">' + l + '</button>');
  h += '<select id="secsel" aria-label="分區"><option value="all">全部分區</option>' + D.sections.map(s => '<option value="' + s.code + '"' + (S.sec === s.code ? ' selected' : '') + '>' + esc(s.label) + '</option>').join('') + '</select><span class="mute">符合 ' + visCount + ' 項</span></div>';
  D.sections.forEach(sec => {
    let sh = '';
    sec.subs.forEach(sub => {
      const rows = all.filter(r => r.sec === sub.code && matchRow(r));
      if (!rows.length) return;
      const elig = rows.filter(r => r.elig), allSel = elig.length && elig.every(r => S.sel.has(r.id));
      sh += '<section class="card subsec" id="s-' + sub.code + '"><div class="subh"><input type="checkbox" data-act="selsub" data-sec="' + sub.code + '"' + (allSel ? ' checked' : '') + (elig.length ? '' : ' disabled title="這一區沒有可批次的項目"') + ' aria-label="選取本區可批次項目"><h3>' + esc(sub.label) + '</h3><span class="mute">' + esc(sub.desc) + '</span>'+ (rows.some(r => r.heavy) ? '<button class="pill heavy" data-act="hvtoggle" data-sec="' + sub.code + '" aria-expanded="' + !!S.hv[sub.code] + '">內含高風險項目 ' + (S.hv[sub.code] ? '▴' : '▾') + '</button>' : '') + '<span class="cnt">' + rows.length + ' 項・' + elig.length + ' 項可批次</span></div>' + (S.hv[sub.code] ? '<div class="banner2">高風險項目：' + rows.filter(r => r.heavy).map(r => esc(r.name)).join('、') + '。這些永遠逐項設定，不進批次。</div>' : '') + sectionBody(sub.code, rows) + '</section>';
    });
    if (sh) h += '<div class="topsec">' + esc(sec.label) + '</div>' + sh;
  });
  if (!visCount) h += '<div class="card panelnote">沒有符合的項目。清除搜尋或改選「全部」。</div>';
  $('#t1').innerHTML = h;
  renderBatch();
  window.scrollTo(0, keepY);
  const q = $('#q'); if (q && document.activeElement === document.body && S._focusQ) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
}
function renderBatch() {
  const n = S.sel.size, b = $('#batch');
  if (!n) { b.classList.add('hide'); return; }
  b.classList.remove('hide');
  b.innerHTML = '<b>已選 ' + n + ' 項</b><span style="opacity:.7;font-size:12px">（批次只做三件事，不繞過等待期與核准）</span>'
    + '<button class="btn" data-act="batch" data-m="rec">套用建議值</button><button class="btn" data-act="presetpick">套用預設組合</button><button class="btn" data-act="batch" data-m="def">重設為預設</button><button class="btn" data-act="selclear">取消選取</button>';
    + '<button class="btn" data-act="batch" data-m="rec">套用建議值</button><button class="btn" data-act="batch" data-m="def">重設為預設值</button><button class="btn" data-act="selclear">取消選取</button>';
}

/* ---------- 對話框／吐司 ---------- */
function closeDlg() { const o = $('#ov'); o.classList.add('hide'); o.innerHTML = ''; }
function openDlg(html) { const o = $('#ov'); o.innerHTML = '<div class="dlg" role="dialog" aria-modal="true">' + html + '</div>'; o.classList.remove('hide'); const f = $('#ov button.primary') || $('#ov textarea'); if (f) f.focus(); }
function toast(msg, undoFn, undoLabel, kind) {
  const t = $('#toast'); clearTimeout(S.toastT);
  t.innerHTML = msg + (undoFn ? ' <button class="btn sm" id="undoBtn">' + (undoLabel || '復原') + '</button><i class="tm"></i>' : '');
  t.classList.remove('hide');
  if (undoFn) $('#undoBtn').onclick = () => { clearTimeout(S.toastT); t.classList.add('hide'); undoFn(); };
  S.toastT = setTimeout(() => t.classList.add('hide'), undoFn ? 6000 : 3500);
}
function showHelp(id) {
  const r = R[id];
  openDlg('<div class="help"><h3>' + esc(r.name) + '</h3><div class="k">' + id + '</div><h4>這是什麼</h4><p>' + esc(r.helpWhat) + '</p>' + (r.helpWhen ? '<h4>什麼時候要改</h4><p>' + esc(r.helpWhen) + '</p>' : '') + '<h4>改了會影響什麼</h4><p>' + esc(r.helpImpact) + '</p><h4>建議值</h4><p>' + esc(r.helpRec) + '</p><div class="mute" style="margin-top:8px">說明由設定登錄表的 question／help／impact／riskText／recommended 產生；「什麼時候要改」＝新增的 SettingDef.when（沒填就不顯示這一段）。</div></div><div class="acts"><button class="btn primary" data-act="closedlg">關閉</button></div>');
}

/* ---------- 變更 ---------- */
function applyVal(id, v, by) {
  S.val[id] = v; S.ver[id]++; S.gver[R[id].gk]++; S.gchg[R[id].gk] = {by: by || '你（王經理）', at: TODAY + ' ' + nowHM(), key: R[id].name}; S.src[id] = isDiff(R[id]) ? {by: by || '你（王經理）', at: TODAY} : null;
}
function requestChange(id, v) {
  const r = R[id], old = S.val[id];
  if (same(v, old)) return render();
  const bad = validate(r, v);
  if (bad) { toast('<span>「' + esc(r.name) + '」：' + esc(bad) + '，沒有儲存</span>'); return render(); }
  const toPend = r.rp || isLoosen(r, old, v);
  if (toPend || heavyRisk(r)) {
    const sentence = '你即將把「' + esc(r.name) + '」從「' + esc(vt(r, old)) + '」改成「' + esc(vt(r, v)) + '」，' + (toPend ? '<b>要等 ' + CC + ' 天才生效</b>' + (isLoosen(r, old, v) ? '，且這是放寬方向，<b>須第二位最高管理者核准</b>' : '') : '<b>立即生效</b>') + '。';
    openDlg('<h3>確認變更</h3><p>' + sentence + '</p>' + (r.riskText ? '<div class="hl red">' + esc(r.riskText) + '</div>' : '') + '<p class="mute">高風險設定沒有「復原」：要等的變更，等待期間可隨時「取消待生效」。</p><label>變更原因（必填）<textarea id="reason" placeholder="例：客戶要求…"></textarea></label><div class="acts"><button class="btn" data-act="closedlg">取消</button><button class="btn primary" id="okBtn" disabled data-act="okone" data-id="' + id + '" data-v="' + encodeURIComponent(JSON.stringify(v)) + '" data-pend="' + (toPend ? 1 : 0) + '" data-need2="' + (isLoosen(r, old, v) ? 1 : 0) + '">送出</button></div>');
    return;
  }
  applyVal(id, v);
  render();
  toast('<span>已更新「' + esc(r.name) + '」→ ' + esc(vt(r, v)) + '（要還原請到「變更紀錄」）</span>');
}
function openBatchDialog(title, changes, skipped, label) {
  // changes: [{id, to}]
  const rows = changes.map(c => {
    const r = R[c.id], old = S.val[c.id];
    const pend = r.rp || isLoosen(r, old, c.to);
    return {r, old, to: c.to, same: same(old, c.to), pend, bad: validate(r, c.to)};
  });
  const todo = rows.filter(x => !x.same && !x.bad), unchanged = rows.filter(x => x.same), bads = rows.filter(x => x.bad);
  const nOps = todo.filter(x => x.r.confirm && !x.pend).length, nPend = todo.filter(x => x.pend).length;
  const sk = Object.keys(skipped || {});
  let h = '<h3>' + esc(title) + '</h3><p>將變更 <b>' + todo.length + '</b> 項；已經是目標值 ' + unchanged.length + ' 項（不動）' + (bads.length ? '；<b>' + bads.length + ' 項不合格，整批不會送出</b>' : '') + '。</p>';
  if (sk.length) { const g = {}; sk.forEach(i => (g[skipped[i]] = g[skipped[i]] || []).push(R[i].name)); h += '<div class="hl">已略過 ' + sk.length + ' 項：' + Object.keys(g).map(k => esc(k) + '（' + g[k].length + ' 項）').join('；') + '。這些要逐項設定。</div>'; }
  if (nPend) h += '<div class="hl">其中 ' + nPend + ' 項是放寬方向或需要等待：<b>不會立即生效</b>，會依原規則進入等待（' + CC + ' 天，放寬須第二位最高管理者核准）。批次不會繞過變更管制。</div>';
  h += '<table><thead><tr><th>項目</th><th>現在</th><th>之後</th><th></th></tr></thead><tbody>' + todo.map(x => '<tr><td>' + esc(x.r.name) + '</td><td>' + esc(vt(x.r, x.old)) + '</td><td>' + esc(vt(x.r, x.to)) + '</td><td>' + (x.pend ? '<span class="pill pnd">等待生效</span>' : x.r.confirm ? '<span class="pill ext">營運</span>' : '') + '</td></tr>').join('') + '</tbody></table>';
  bads.forEach(x => h += '<div class="err">' + esc(x.r.name) + '：' + esc(x.bad) + '</div>');
  if (nOps) h += '<label class="hl" style="display:block"><input type="checkbox" id="opsOk"> 我確認要改這 ' + nOps + ' 項營運設定（會影響日常作業的畫面或提醒）</label>';
  h += '<label>變更原因<input type="text" id="reason" style="width:100%" value="批次調整（' + todo.length + ' 項）"></label><div class="acts"><button class="btn" data-act="closedlg">取消</button><button class="btn primary" id="okBtn" data-act="okbatch"' + (todo.length && !bads.length && !nOps ? '' : ' disabled') + '>套用 ' + todo.length + ' 項</button></div>';
  S._pendingBatch = todo.map(x => ({id: x.r.id, to: x.to, pend: x.pend}));
  S._needOps = nOps;
  openDlg(h);
}
function startBatch(mode) {
  const changes = [];
  S.sel.forEach(id => { const r = R[id]; if (mode === 'rec') { if (r.rec !== undefined && r.rec !== null) changes.push({id, to: r.rec}); } else changes.push({id, to: r.def}); });
  if (mode === 'rec') { const none = Array.from(S.sel).filter(id => R[id].rec === undefined || R[id].rec === null); none.forEach(id => S.skip[id] = '沒有建議值'); }
  openBatchDialog(mode === 'rec' ? '批次：套用建議值' : '批次：重設為預設值', changes, S.skip);
}
function doBatch() {
  const items = S._pendingBatch, reason = ($('#reason') || {}).value || '批次調整';
  const rec = [], gs = {};
  items.forEach(it => {
    const r = R[it.id];
    if (it.pend) { S.pend[it.id] = {val: it.to, eff: '11/20', need2: isLoosen(r, S.val[it.id], it.to), by: '你'}; rec.push({id: it.id, pend: true}); }
    else { const before = S.val[it.id], bsrc = S.src[it.id]; applyVal(it.id, it.to); rec.push({id: it.id, before, bsrc}); gs[r.gk] = 1; }
  });
  // 記下「套用後」各群組的版本號：復原時若版本變了＝別人改過
  const gv = {}; Object.keys(gs).forEach(g => gv[g] = S.gver[g]);
  closeDlg(); S.sel.clear(); S.skip = {};
  S.last = {rec, gv};
  render();
  const nApplied = rec.filter(x => !x.pend).length, nP = rec.length - nApplied;
  toast('<span>已套用 ' + nApplied + ' 項' + (nP ? '，另 ' + nP + ' 項進入等待生效' : '') + '（原因：' + esc(reason) + '）</span>', undoBatch, '復原這一批');
}
function undoBatch() {
  const L = S.last; if (!L) return;
  const bad = Object.keys(L.gv).filter(g => S.gver[g] !== L.gv[g]);
  if (bad.length) {
    const c = S.gchg[bad[0]] || {by: '另一位管理者', at: TODAY, key: ''};
    toast('<span>無法復原這一批：' + bad.map(g => esc(D.groups[g])).join('、') + '的設定在你套用之後被 ' + esc(c.by) + ' 於 ' + esc(c.at) + ' 改過' + (c.key ? '（' + esc(c.key) + '）' : '') + '，為了不蓋掉別人的修改，系統拒絕整批復原。</span>');
    return;
  }
  L.rec.forEach(x => { if (x.pend) delete S.pend[x.id]; else { S.val[x.id] = x.before; S.ver[x.id]++; S.src[x.id] = x.bsrc; S.gver[R[x.id].gk]++; } });
  const n = L.rec.length; S.last = null; render(); toast('<span>已復原這一批（' + n + ' 項）</span>');
}
function simulateConflict() {
  if (!S.last) { toast('<span>先做一次批次（選幾項 → 套用建議值），再按這個示範</span>'); return; }
  const g = Object.keys(S.last.gv)[0]; if (!g) return;
  S.gver[g]++; S.gchg[g] = {by: '李會計', at: TODAY + ' 15:42', key: ''};
  toast('<span>已模擬：李會計在 15:42 改了「' + esc(D.groups[g]) + '」。現在按「復原這一批」會被拒絕。</span>', undoBatch, '復原這一批');
}

/* ---------- 事件 ---------- */
document.addEventListener('click', e => {
  const t = e.target.closest('[data-act]'); if (!t) return;
  const a = t.dataset.act, id = t.dataset.id;
  if (a === 'filter') { S.f = t.dataset.k; render(); }
  else if (a === 'help') showHelp(id);
  else if (a === 'closedlg') closeDlg();
  else if (a === 'toggle') requestChange(id, !S.val[id]);
  else if (a === 'reset') requestChange(id, R[id].def);
  else if (a === 'lockpick') requestChange(id, Number(t.dataset.v));
  else if (a === 'hvtoggle') { S.hv[t.dataset.sec] = !S.hv[t.dataset.sec]; render(); }
  else if (a === 'advtoggle') { S.advOpen[t.dataset.sec] = !S.advOpen[t.dataset.sec]; render(); }
  else if (a === 'cancelpend') { delete S.pend[id]; render(); toast('<span>已取消待生效：' + esc(R[id].name) + '</span>'); }
  else if (a === 'ins') { const ta = $('textarea[data-chg="' + id + '"]'); ta.value += t.dataset.tok; requestChange(id, ta.value); }
  else if (a === 'selclear') { S.sel.clear(); S.skip = {}; render(); }
  else if (a === 'batch') startBatch(t.dataset.m);
  else if (a === 'okbatch') doBatch();
  else if (a === 'presetpick') {
    const all = D.profitPresets.map((p, i) => ({lbl: '利潤提醒色帶：' + p.name, act: 'preset', i})).concat(D.agingPresets.map((p, i) => ({lbl: '帳齡分界：' + p.name, act: 'agingpreset', i})));
    openDlg('<h3>套用預設組合</h3><p class="mute">預設組合是登錄表 presets 的內容（目前 0 個，下列為本份提案）。套用前會先確認。</p>' + all.map(x => '<div style="margin:4px 0"><button class="btn" data-act="' + x.act + '" data-i="' + x.i + '">' + esc(x.lbl) + '</button></div>').join('') + '<div class="acts"><button class="btn" data-act="closedlg">取消</button></div>');
  }
  else if (a === 'preset') { const p = D.profitPresets[Number(t.dataset.i)]; openBatchDialog('預設組合：' + p.name, Object.keys(p.v).map(k => ({id: k, to: p.v[k]})), {}); }
  else if (a === 'agingpreset') { const p = D.agingPresets[Number(t.dataset.i)]; openBatchDialog('預設組合：帳齡 ' + p.name, Object.keys(p.v).map(k => ({id: k, to: p.v[k]})), {}); }
  else if (a === 'okone') {
    const v = JSON.parse(decodeURIComponent(t.dataset.v)), r = R[id], reason = $('#reason').value.trim();
    if (!reason) return;
    closeDlg();
    if (t.dataset.pend === '1') { S.pend[id] = {val: v, eff: '11/20', need2: t.dataset.need2 === '1', by: '你'}; render(); toast('<span>已送出：「' + esc(r.name) + '」要等 ' + CC + ' 天才生效</span>'); }
    else { applyVal(id, v); render(); toast('<span>已變更「' + esc(r.name) + '」</span>'); }
  }
  else if (a === 'sel') { t.checked ? S.sel.add(id) : S.sel.delete(id); render(); }
  else if (a === 'selpair') { t.dataset.ids.split(',').forEach(i => t.checked ? S.sel.add(i) : S.sel.delete(i)); render(); }
  else if (a === 'selsub') {
    const rows = D.rows.filter(r => r.sec === t.dataset.sec && matchRow(r));
    rows.forEach(r => { if (r.elig) { t.checked ? S.sel.add(r.id) : S.sel.delete(r.id); } else if (t.checked) S.skip[r.id] = r.why; else delete S.skip[r.id]; });
    render();
  }
  else if (a === 'tab') showTab(t.dataset.t);
  else if (a === 'demo-conflict') simulateConflict();
});
document.addEventListener('change', e => {
  const t = e.target;
  if (t.id === 'secsel') { S.sec = t.value; render(); return; }
  const id = t.dataset && t.dataset.chg; if (!id) return;
  const r = R[id];
  let v;
  if (t.type === 'radio') v = Number(t.value);
  else if (t.type === 'number') v = t.value === '' ? NaN : Number(t.value);
  else if (t.tagName === 'SELECT') v = Number(t.value);
  else v = t.value;
  requestChange(id, v);
});
document.addEventListener('input', e => {
  const t = e.target;
  if (t.id === 'q') { S.q = t.value; S._focusQ = true; render(); const q = $('#q'); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
  if (t.id === 'reason') { const b = $('#okBtn'); if (b && b.dataset.act === 'okone') b.disabled = !t.value.trim(); }
  if (t.id === 'opsOk') { const b = $('#okBtn'); b.disabled = !t.checked || !S._pendingBatch.length; }
});
document.addEventListener('change', e => { if (e.target.id === 'opsOk') { $('#okBtn').disabled = !e.target.checked; } });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#ov').classList.contains('hide')) closeDlg(); });
function showTab(t) {
  $$('.tab').forEach(b => b.setAttribute('aria-selected', b.dataset.t === t));
  ['t1', 't2', 't3'].forEach(x => $('#' + x).classList.toggle('hide', x !== t));
  try { sessionStorage.setItem('mx-tab', t); } catch (e) {}
}
render();
let _t = 't1'; try { _t = sessionStorage.getItem('mx-tab') || 't1'; } catch (e) {}
showTab(_t);
