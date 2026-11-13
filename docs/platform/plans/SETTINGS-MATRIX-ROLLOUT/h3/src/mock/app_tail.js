/* ================= r3：外框（SPEC §14）＋草稿與儲存列（§13）＋逐欄 CAS 復原（§5）＋兩種等待（§4） ================= */
const CATS = ['業務', '財務', '系統', '安全'];
const SUBS = D.sections.reduce((a, s) => a.concat(s.subs), []);
const who = '你（王經理）';
const draftIds = () => D.rows.filter(r => !same(S.val[r.id], S.sv[r.id])).map(r => r.id);
const pageDraftCount = () => Object.values(S.pdraft).reduce((a, x) => a + x.n, 0);
const totalDrafts = () => draftIds().length + pageDraftCount();
function pendKind(r, oldv, newv) { // 'now' | 'wait'（只等待）| 'wait2'（等待加第二人核准）
  if (isLoosen(r, oldv, newv)) return S.solo ? 'wait' : 'wait2'; // r3.2：只有一位最高管理者時，放寬沒有第二人可核准，只剩等待（伺服器 plan().kind／otherSuperadmins 決定；這裡是假資料切換）
  if (r.rp) return 'wait';
  return 'now';
}
const KIND_TXT = {
  wait: '要等 ' + CC + ' 天確認期，不需要別人核准，滿 ' + CC + ' 天後自動生效。',
  wait2: '放寬：要等 ' + CC + ' 天確認期，並要第二位最高管理者核准。'
};
function groupRows(gk) { return D.rows.filter(r => r.gk === gk); }
const isDiffSv = r => !same(S.sv[r.id], r.def);
const gDiff = gk => groupRows(gk).filter(isDiffSv).length;
const gHeavy = gk => groupRows(gk).some(r => r.heavy);
function notifyPreview(items) {
  const roles = new Set(), heavy = items.some(x => x.r.heavy || x.r.risk === 'money' || x.r.risk === 'legal' || x.r.risk === 'security');
  items.forEach(x => (x.r.roles || []).forEach(t => roles.add(t)));
  let h = '最高管理者（所有人）';
  h += '；受影響的人：' + (roles.size ? Array.from(roles).join('、') : '使用該功能的同仁');
  if (heavy) h += '；<b>另外發 LINE 給最高管理者</b>（含影響大項目）';
  return h + '。多項合併成一則：「' + who.replace('你（', '').replace('）', '') + '調整了 ' + items.length + ' 項設定」，點開看明細。';
}

/* ---------- 版面 ---------- */
function navHtml() {
  let h = '<div class="seg">' + ['全部'].concat(CATS).map(c => '<button class="' + (S.seg === c ? 'on' : '') + '" data-act="seg" data-c="' + c + '">' + c + '</button>').join('') + '</div>';
  CATS.forEach(c => {
    if (S.seg !== '全部' && S.seg !== c) return;
    const gs = D.groupOrder.filter(g => D.shell[g].category === c);
    if (!gs.length) { h += '<div class="cat"><div class="ch"><span>' + c + '</span></div><div class="mute" style="padding:2px 10px">（本稿只含甲份；系統類群組見乙份）</div></div>'; return; }
    h += '<div class="cat"><div class="ch"><span>' + c + '</span><span>' + gs.length + '</span></div>' + gs.map(g => {
      const n = gDiff(g), on = S.view.k === 'group' && S.view.g === g;
      return '<button class="gi' + (on ? ' on' : '') + '" data-act="grp" data-g="' + g + '"><span>' + esc(D.shell[g].plain) + '<br><span class="k">' + esc(D.shell[g].currentName) + '</span></span><span class="bd">' + (n ? '<span class="dot2" title="與預設不同 ' + n + ' 項">' + n + '</span>' : '') + (D.shell[g].privacy ? '<span class="pill ext" title="影響隱私">隱私</span>' : '') + (gHeavy(g) ? '<span class="hi" title="內含高風險項目">🔴</span>' : '') + '</span></button>';
    }).join('') + '</div>';
  });
  h += '<div class="cat"><div class="ch"><span>其他位置的設定</span></div><button class="gi" data-act="tab" data-t="t3"><span>獎金、傳票科目、T100、營運目標、報價條款…<br><span class="k">不在設定中心，原頁面改版</span></span><span class="bd">7 ›</span></button></div>';
  return h;
}
function filterBar() {
  let h = '<div class="card toolbar2">';
  [['all', '全部'], ['diff', '與預設不同'], ['heavy', '影響大'], ['oth', '影響別人'], ['ext', '需外部設定'], ['adv', '進階']].forEach(([k, l]) => h += '<button class="chip" aria-pressed="' + (S.f === k) + '" data-act="filter" data-k="' + k + '">' + l + '</button>');
  return h + '</div>';
}
function groupView(gk) {
  const meta = D.shell[gk], rows = groupRows(gk), vis = rows.filter(matchRow);
  const elig = vis.filter(r => r.elig), allSel = elig.length && elig.every(r => S.sel.has(r.id));
  let h = '<h2>' + esc(meta.plain) + '</h2><div class="sub">' + esc(D.groupHelp[gk]) + '　<span class="k">原名：' + esc(meta.currentName) + '（' + gk + '）</span>' + (gHeavy(gk) ? ' <button class="pill heavy" data-act="hvtoggle" data-sec="' + gk + '">內含高風險項目 ' + (S.hv[gk] ? '▴' : '▾') + '</button>' : '') + '</div>';
  if (S.hv[gk]) h += '<div class="banner2" style="border-radius:8px;margin-bottom:8px">高風險項目：' + rows.filter(r => r.heavy).map(r => esc(r.name)).join('、') + '。這些永遠逐項設定，不進批次。</div>';
  h += filterBar() + '<div class="muted2"><label><input type="checkbox" data-act="selgrp" data-g="' + gk + '"' + (allSel ? ' checked' : '') + (elig.length ? '' : ' disabled') + '> 選取本群組可批次的項目（' + elig.length + ' 項）</label>　符合 ' + vis.length + ' 項</div>';
  let any = false;
  SUBS.forEach(sub => {
    const rs = vis.filter(r => r.sec === sub.code);
    if (!rs.length) return;
    any = true;
    const showHead = SUBS.filter(s => rows.some(r => r.sec === s.code)).length > 1;
    h += '<section class="card subsec" id="s-' + sub.code + '">' + (showHead ? '<div class="subh"><h3>' + esc(sub.label) + '</h3><span class="mute">' + esc(sub.desc) + '</span></div>' : '') + sectionBody(sub.code, rs) + '</section>';
  });
  if (!any) h += '<div class="card panelnote">沒有符合的項目。改選「全部」。</div>';
  return h;
}
function recentRows(n) {
  return S.log.slice(0, n).map(e => '<tr><td data-l="時間">' + esc(e.at) + '</td><td data-l="誰">' + esc(e.by) + '</td><td class="l" data-l="項目"><b>' + esc(R[e.id].name) + '</b><div class="k">' + e.id + '</div></td><td data-l="舊→新">' + esc(e.old) + ' → ' + esc(e.neu) + (e.note ? ' <span class="pill pnd">' + esc(e.note) + '</span>' : '') + '</td><td data-l="原因">' + esc(e.reason) + '</td><td><button class="btn sm" data-act="goto" data-id="' + e.id + '">查看該項</button></td></tr>').join('');
}
const RECENT_HEAD = '<table class="mx stack"><thead><tr><th>時間</th><th>誰</th><th class="l">項目</th><th>舊 → 新</th><th>原因</th><th></th></tr></thead><tbody>';
function homeView() {
  const diffN = D.rows.filter(isDiffSv).length, pendN = Object.keys(S.pend).length, hv = D.groupOrder.filter(gHeavy).length;
  return '<h2>設定中心　總覽（甲份：業務與財務規則）</h2><div class="sub">這份稿只有甲份 20 個群組；乙、丙份的群組在各自的稿裡。</div>'
    + '<div class="stats"><button class="stat" data-act="view" data-v="diff"><div class="big">' + diffN + '</div><div class="lb">與預設不同的項目 ›</div></button>'
    + '<button class="stat" data-act="view" data-v="pending"><div class="big">' + pendN + '</div><div class="lb">等待生效的項目 ›</div></button>'
    + '<button class="stat" data-act="view" data-v="risk"><div class="big">' + hv + '</div><div class="lb">內含高風險項目的群組 ›</div></button></div>'
    + '<div class="card"><h3>最近變更</h3>' + RECENT_HEAD + recentRows(5) + '</tbody></table><button class="btn sm" data-act="view" data-v="recent" style="margin-top:6px">前往全部 ›</button></div>';
}
function pendingView() {
  const ids = Object.keys(S.pend);
  let h = '<h2>等待生效</h2><div class="sub">這些變更已送出，還沒生效。</div><div class="card">';
  if (!ids.length) return h + '<div class="panelnote">目前沒有等待生效的項目。</div></div>';
  h += '<table class="mx stack"><thead><tr><th class="l">項目</th><th>現在 → 之後</th><th>誰申請</th><th>預計生效</th><th>誰要核准</th><th></th></tr></thead><tbody>' + ids.map(id => { const r = R[id], p = S.pend[id]; return '<tr><td class="l" data-l="項目"><b>' + esc(r.name) + '</b><div class="k">' + id + '</div></td><td data-l="變更">' + esc(vt(r, S.sv[id])) + ' → ' + esc(vt(r, p.val)) + '</td><td data-l="誰申請">' + esc(p.by || '王經理') + '</td><td data-l="預計生效">' + esc(p.eff) + '</td><td data-l="誰要核准">' + (p.need2 ? '第二位最高管理者' : '不需核准（期滿自動生效）') + '</td><td><button class="btn sm" data-act="cancelpend" data-id="' + id + '">撤銷申請</button></td></tr>'; }).join('') + '</tbody></table></div>';
  return h;
}
function diffView(riskOnly) {
  let h = '<h2>' + (riskOnly ? '內含高風險項目的群組' : '與預設不同的項目') + '</h2><div class="sub">跨群組列出；可直接在這裡改（一樣是草稿）。</div>';
  D.groupOrder.forEach(g => {
    if (riskOnly ? !gHeavy(g) : !gDiff(g)) return;
    const rs = groupRows(g).filter(r => riskOnly ? r.heavy : isDiffSv(r));
    h += '<div class="topsec">' + esc(D.shell[g].plain) + '</div><section class="card subsec">' + rs.map(rowHtml).join('') + '</section>';
  });
  return h;
}
function render() {
  const keepY = window.scrollY, v = S.view;
  $('#nav').innerHTML = navHtml();
  $('#main').innerHTML = v.k === 'group' ? groupView(v.g) : v.k === 'pending' ? pendingView() : v.k === 'recent' ? '<h2>最近變更</h2><div class="sub">資料來源：變更紀錄。</div><div class="card">' + RECENT_HEAD + recentRows(50) + '</tbody></table></div>' : v.k === 'diff' ? diffView(false) : v.k === 'risk' ? diffView(true) : homeView();
  $('#nPend').textContent = Object.keys(S.pend).length;
  ['gPend', 'gRecent', 'gHome'].forEach(i => { const e = $('#' + i); if (e) e.classList.toggle('on', (i === 'gPend' && v.k === 'pending') || (i === 'gRecent' && v.k === 'recent') || (i === 'gHome' && v.k === 'home')); });
  renderSavebar(); renderBatch();
  window.scrollTo(0, keepY);
  if (S.flash) { const el = $('[data-row="' + S.flash + '"]'); if (el) { el.scrollIntoView({block: 'center'}); el.classList.add('flash'); } S.flash = null; }
}
function renderSavebar() {
  const n = draftIds().length, p = pageDraftCount(), b = $('#savebar');
  if (!n && !p) { b.classList.add('hide'); return; }
  b.classList.remove('hide');
  $('#nDraft').textContent = n + p;
  $('#draftNote').textContent = (n && p ? '（設定中心 ' + n + ' 項、其他頁面 ' + p + ' 處）' : '');
}
function renderBatch() {
  const n = S.sel.size, b = $('#batch');
  if (!n) { b.classList.add('hide'); return; }
  b.classList.remove('hide');
  b.innerHTML = '<b>已選 ' + n + ' 項</b><span style="opacity:.7;font-size:12px">（批次只改草稿；儲存後才寫入，不繞過等待期與核准）</span>'
    + '<button class="btn" data-act="batch" data-m="rec">套用建議值</button><button class="btn" data-act="presetpick">套用預設組合</button><button class="btn" data-act="batch" data-m="def">重設為預設</button><button class="btn" data-act="selclear">取消選取</button>';
}

/* ---------- 對話框／吐司／說明 ---------- */
function closeDlg() { const o = $('#ov'); o.classList.add('hide'); o.innerHTML = ''; }
function openDlg(html) { const o = $('#ov'); o.innerHTML = '<div class="dlg" role="dialog" aria-modal="true">' + html + '</div>'; o.classList.remove('hide'); const f = $('#ov button.primary:not([disabled])') || $('#ov textarea') || $('#ov button'); if (f) f.focus(); }
function toast(msg, undoFn, undoLabel) {
  const t = $('#toast'); clearTimeout(S.toastT);
  t.innerHTML = msg + (undoFn ? ' <button class="btn sm" id="undoBtn">' + (undoLabel || '復原') + '</button><i class="tm"></i>' : '');
  t.classList.remove('hide');
  if (undoFn) $('#undoBtn').onclick = () => { clearTimeout(S.toastT); t.classList.add('hide'); undoFn(); };
  S.toastT = setTimeout(() => t.classList.add('hide'), undoFn ? 8000 : 4500);
}
function showHelp(id) {
  const r = R[id];
  openDlg('<div class="help"><h3>' + esc(r.name) + '</h3><div class="k">' + id + '</div><h4>這是什麼</h4><p>' + esc(r.helpWhat) + '</p>' + (r.helpWhen ? '<h4>什麼時候要改</h4><p>' + esc(r.helpWhen) + '</p>' : '') + '<h4>改了會影響什麼</h4><p>' + esc(r.helpImpact) + '</p><h4>建議值</h4><p>' + esc(r.helpRec) + '</p><div class="mute" style="margin-top:8px">說明由設定登錄表的 question／help／impact／riskText／recommended 產生；「什麼時候要改」＝新增的 SettingDef.when（沒填就不顯示這一段）。</div></div><div class="acts"><button class="btn primary" data-act="closedlg">關閉</button></div>');
}

/* ---------- 草稿 ---------- */
function setDraft(id, v) {
  const r = R[id], bad = validate(r, v);
  if (bad) { toast('<span>「' + esc(r.name) + '」：' + esc(bad) + '，沒有放進草稿</span>'); render(); return false; }
  S.val[id] = v; return true;
}
function requestChange(id, v) { if (!same(v, S.val[id])) setDraft(id, v); render(); }
function discardAll() {
  D.rows.forEach(r => S.val[r.id] = JSON.parse(JSON.stringify(S.sv[r.id])));
  S.sel.clear(); S.skip = {}; S.batchIds.clear();
  if (window.pageClear) window.pageClear();
  S.pdraft = {}; render(); toast('<span>已放棄所有未儲存的修改</span>');
}
function startBatch(mode) {
  let n = 0; const skip = Object.assign({}, S.skip);
  S.sel.forEach(id => {
    const r = R[id], to = mode === 'rec' ? r.rec : r.def;
    if (mode === 'rec' && (to === undefined || to === null)) { skip[id] = '沒有建議值'; return; }
    if (same(to, S.val[id])) return;
    const bad = validate(r, to);
    if (bad) { skip[id] = '不合格：' + bad; return; }
    S.val[id] = to; S.batchIds.add(id); n++;
  });
  S.skip = skip; S.sel.clear(); render();
  toast('<span>已把 ' + n + ' 項放進草稿（尚未儲存）' + (Object.keys(skip).length ? '；略過 ' + Object.keys(skip).length + ' 項' : '') + '。確認後按上方「儲存」。</span>');
}
function applyPreset(map, label) {
  for (const k of Object.keys(map)) { const bad = (() => { const r = R[k]; const old = S.val[k]; S.val[k] = map[k]; const m = validate(r, map[k]); S.val[k] = old; return m; })(); }
  const old = Object.assign({}, S.val); let n = 0;
  Object.keys(map).forEach(k => { if (!same(S.val[k], map[k])) { S.val[k] = map[k]; S.batchIds.add(k); n++; } });
  for (const k of Object.keys(map)) { const m = validate(R[k], S.val[k]); if (m) { Object.keys(old).forEach(i => S.val[i] = old[i]); toast('<span>「' + esc(label) + '」套不進去：' + esc(R[k].name) + ' ' + esc(m) + '</span>'); render(); return; } }
  render(); toast('<span>已把「' + esc(label) + '」放進草稿（' + n + ' 項，尚未儲存）。</span>');
}

/* ---------- 儲存（確認視窗＋通知預覽） ---------- */
function buildItems() {
  return draftIds().map(id => { const r = R[id], old = S.sv[id], to = S.val[id]; return {r, id, old, to, kind: pendKind(r, old, to), batch: S.batchIds.has(id)}; });
}
function openSave() {
  const items = buildItems(), pages = Object.values(S.pdraft);
  if (!items.length && !pages.length) return;
  const heavy = items.some(x => x.r.heavy || x.kind !== 'now' || heavyRisk(x.r)) || pages.some(p => p.heavy);
  const nOps = items.filter(x => x.batch && x.r.confirm && x.kind === 'now').length;
  const sk = Object.keys(S.skip);
  let h = '<h3>儲存修改</h3><p>將變更 <b>' + (items.length + pages.reduce((a, p) => a + p.n, 0)) + '</b> 項，略過 ' + sk.length + ' 項。</p>';
  if (sk.length) { const g = {}; sk.forEach(i => (g[S.skip[i]] = g[S.skip[i]] || []).push(R[i].name)); h += '<div class="hl">已略過（不能批次，請逐項設定）：' + Object.keys(g).map(k => esc(k) + '（' + g[k].length + ' 項）').join('；') + '</div>'; }
  if (items.length) {
    h += '<table><thead><tr><th>項目</th><th>現在</th><th>之後</th><th>怎麼生效</th></tr></thead><tbody>' + items.map(x => '<tr><td>' + esc(x.r.name) + (x.r.heavy ? ' <span class="pill heavy">影響大</span>' : '') + '</td><td>' + esc(vt(x.r, x.old)) + '</td><td>' + esc(vt(x.r, x.to)) + '</td><td>' + (x.kind === 'now' ? '立即生效' : x.kind === 'wait' ? '<span class="pill pnd">只等待</span>' : '<span class="pill pnd">等待加核准</span>') + '</td></tr>').join('') + '</tbody></table>';
    if (items.some(x => x.kind === 'wait')) h += '<div class="hl">只等待：' + KIND_TXT.wait + '</div>';
    if (S.solo && items.some(x => isLoosen(x.r, x.old, x.to))) h += '<div class="hl">其中有放寬方向的項目：目前系統裡<b>只有一位最高管理者</b>，沒有第二人可核准，所以改成「填原因、等 ' + CC + ' 天後生效，並留下紀錄」。</div>';
    if (items.some(x => x.kind === 'wait2')) h += '<div class="hl">' + KIND_TXT.wait2 + '</div>';
  }
  if (pages.length) h += '<p><b>其他頁面的修改：</b></p><ul>' + pages.map(p => '<li>' + esc(p.title) + '（' + p.n + ' 處）：' + (p.cc ? '<span class="pill pnd">要等 ' + CC + ' 天確認期或第二位最高管理者核准</span>' : '立即生效') + '</li>').join('') + '</ul>';
  const notifyItems = items.concat(pages.map(p => ({r: {heavy: p.heavy, risk: p.heavy ? 'money' : 'ops', roles: [p.notify]}})));
  h += '<div class="hl" style="background:var(--bluebg);color:var(--blue)"><b>通知預覽（儲存後送出）</b><br>' + notifyPreview(notifyItems) + '</div>';
  if (nOps) h += '<label class="hl" style="display:block"><input type="checkbox" id="opsOk"> 我確認要改這 ' + nOps + ' 項營運設定（會影響日常作業的畫面或提醒）</label>';
  h += '<label>變更原因' + (heavy ? '（含影響大項目，必填，至少 4 個字）' : '（選填）') + '<textarea id="reason" placeholder="例：客戶要求…">' + (S.batchIds.size ? '批次調整（' + S.batchIds.size + ' 項）' : '') + '</textarea></label><div class="acts"><button class="btn" data-act="closedlg">取消</button><button class="btn primary" id="okBtn" data-act="dosave" data-heavy="' + (heavy ? 1 : 0) + '" data-ops="' + nOps + '">儲存</button></div>';
  openDlg(h); checkSaveBtn();
}
function checkSaveBtn() {
  const b = $('#okBtn'); if (!b) return;
  const heavy = b.dataset.heavy === '1', ops = Number(b.dataset.ops), reason = ($('#reason') || {}).value || '';
  b.disabled = (heavy && reason.trim().length < 4) || (ops > 0 && !($('#opsOk') || {}).checked);
}
function doSave() {
  const items = buildItems(), reason = ($('#reason') || {}).value || '', at = TODAY + ' ' + nowHM();
  const rec = [], now = [], wait = [], wait2 = [];
  items.forEach(x => {
    const logBase = {id: x.id, by: who, at, reason: reason.trim() || '（未填）', old: vt(x.r, x.old), neu: vt(x.r, x.to)};
    if (x.kind === 'now') {
      S.sv[x.id] = JSON.parse(JSON.stringify(x.to)); S.chg[x.id] = {by: who, at}; S.src[x.id] = same(x.to, x.r.def) ? null : {by: '王經理', at: TODAY};
      now.push(x); if (x.batch) rec.push({id: x.id, before: x.old, wrote: x.to}); S.log.unshift(logBase);
    } else {
      S.pend[x.id] = {val: x.to, eff: '11/20', need2: x.kind === 'wait2', by: '王經理'};
      S.val[x.id] = JSON.parse(JSON.stringify(x.old)); (x.kind === 'wait' ? wait : wait2).push(x);
      S.log.unshift(Object.assign(logBase, {note: x.kind === 'wait' ? '只等待' : '等待加核准'}));
    }
  });
  const np = pageDraftCount(); const pages = Object.values(S.pdraft);
  const ccPages = pages.filter(p => p.cc).reduce((a, p) => a + p.n, 0);
  if (window.pageClear) window.pageClear();
  S.pdraft = {}; S.batchIds.clear(); S.skip = {}; S.sel.clear();
  S.last = rec.length ? {rec} : null;
  closeDlg(); render();
  const parts = [];
  if (now.length + (np - ccPages)) parts.push('已生效 ' + (now.length + np - ccPages) + ' 項');
  if (wait.length) parts.push('等待生效 ' + wait.length + ' 項（只等待，預計 11/20 自動生效）');
  if (wait2.length + ccPages) parts.push('等待核准 ' + (wait2.length + ccPages) + ' 項（預計 11/20 生效，要第二位最高管理者核准）');
  toast('<span>' + parts.join('；') + '。已通知最高管理者與受影響的人。</span>', rec.length ? undoBatch : null, '復原這一批');
}
function undoBatch() {
  const L = S.last; if (!L) return;
  const bad = L.rec.filter(x => !same(S.sv[x.id], x.wrote));
  if (bad.length) {
    const c = S.chg[bad[0].id] || {by: '另一位管理者', at: TODAY};
    toast('<span>無法復原這一批：' + bad.map(x => '「' + esc(R[x.id].name) + '」').join('、') + '在你套用之後被 ' + esc(c.by) + ' 於 ' + esc(c.at) + ' 改過，為了不蓋掉別人的修改，系統拒絕整批復原。</span>');
    return;
  }
  L.rec.forEach(x => { S.sv[x.id] = JSON.parse(JSON.stringify(x.before)); if (same(S.val[x.id], x.wrote)) S.val[x.id] = JSON.parse(JSON.stringify(x.before)); S.chg[x.id] = {by: who, at: TODAY + ' ' + nowHM()}; S.src[x.id] = same(x.before, R[x.id].def) ? null : S.src[x.id]; });
  const n = L.rec.length; S.last = null; render(); toast('<span>已復原這一批（' + n + ' 項）</span>');
}
function simulateConflict() {
  if (!S.last) { toast('<span>先做一次批次：選幾項 → 套用建議值 → 儲存，再按這個示範</span>'); return; }
  const x = S.last.rec[0], r = R[x.id];
  const alt = (r.choices && r.choices.length) ? (r.choices.find(c => c.value !== x.wrote && !/尚未提供/.test(c.label)) || {value: x.before}).value : (typeof x.wrote === 'number' ? x.wrote + 1 : x.wrote);
  S.sv[x.id] = alt; if (same(S.val[x.id], x.wrote)) S.val[x.id] = alt;
  S.chg[x.id] = {by: '李會計', at: TODAY + ' 15:42'};
  render(); toast('<span>已模擬：李會計在 15:42 改了「' + esc(r.name) + '」。現在按「復原這一批」會被拒絕。</span>', undoBatch, '復原這一批');
}

/* ---------- 全域搜尋 ---------- */
function doSearch(q) {
  const box = $('#gres'); q = q.trim().toLowerCase();
  if (!q) { box.classList.add('hide'); return; }
  const m = D.rows.filter(r => (r.name + ' ' + r.id + ' ' + r.desc + ' ' + D.shell[r.gk].plain + ' ' + D.shell[r.gk].currentName + ' ' + (r.choices || []).map(c => c.label).join(' ')).toLowerCase().includes(q)).slice(0, 12);
  box.innerHTML = m.length ? m.map(r => '<button data-act="gosearch" data-id="' + r.id + '"><span class="mute">' + esc(D.shell[r.gk].plain) + ' ›</span> <b>' + esc(r.name) + '</b> <span class="k">' + r.id + '</span></button>').join('') : '<div class="mute" style="padding:8px">沒有符合的設定</div>';
  box.classList.remove('hide');
}
function gotoRow(id) { const r = R[id]; S.view = {k: 'group', g: r.gk}; S.f = 'all'; S.flash = id; $('#gres').classList.add('hide'); $('#gq').value = ''; render(); }

/* ---------- 事件 ---------- */
document.addEventListener('click', e => {
  const t = e.target.closest('[data-act]'); if (!t) { if (!e.target.closest('.searchw')) $('#gres').classList.add('hide'); return; }
  const a = t.dataset.act, id = t.dataset.id;
  if (a === 'filter') { S.f = t.dataset.k; render(); }
  else if (a === 'help') showHelp(id);
  else if (a === 'closedlg') closeDlg();
  else if (a === 'toggle') requestChange(id, !S.val[id]);
  else if (a === 'reset') requestChange(id, R[id].def);
  else if (a === 'lockpick') requestChange(id, Number(t.dataset.v));
  else if (a === 'advtoggle') { S.advOpen[t.dataset.sec] = !S.advOpen[t.dataset.sec]; render(); }
  else if (a === 'hvtoggle') { S.hv[t.dataset.sec] = !S.hv[t.dataset.sec]; render(); }
  else if (a === 'cancelpend') { delete S.pend[id]; S.log.unshift({id, by: who, at: TODAY + ' ' + nowHM(), reason: '撤銷申請', old: '（等待中）', neu: '維持現值'}); render(); toast('<span>已撤銷申請：' + esc(R[id].name) + '</span>'); }
  else if (a === 'ins') { const ta = $('textarea[data-chg="' + id + '"]'); ta.value += t.dataset.tok; requestChange(id, ta.value); }
  else if (a === 'selclear') { S.sel.clear(); S.skip = {}; render(); }
  else if (a === 'batch') startBatch(t.dataset.m);
  else if (a === 'presetpick') {
    const all = D.profitPresets.map((p, i) => ({lbl: '利潤提醒色帶：' + p.name, act: 'preset', i})).concat(D.agingPresets.map((p, i) => ({lbl: '帳齡分界：' + p.name, act: 'agingpreset', i})));
    openDlg('<h3>套用預設組合</h3><p class="mute">預設組合是登錄表 presets 的內容（目前 0 個，下列為本份提案，使用者看過才上線）。選了只會放進草稿。</p>' + all.map(x => '<div style="margin:4px 0"><button class="btn" data-act="' + x.act + '" data-i="' + x.i + '">' + esc(x.lbl) + '</button></div>').join('') + '<div class="acts"><button class="btn" data-act="closedlg">取消</button></div>');
  }
  else if (a === 'preset') { closeDlg(); const p = D.profitPresets[Number(t.dataset.i)]; applyPreset(p.v, '利潤提醒色帶：' + p.name); }
  else if (a === 'agingpreset') { closeDlg(); const p = D.agingPresets[Number(t.dataset.i)]; applyPreset(p.v, '帳齡分界：' + p.name); }
  else if (a === 'dosave') doSave();
  else if (a === 'openSave') openSave();
  else if (a === 'discard') discardAll();
  else if (a === 'sel') { t.checked ? S.sel.add(id) : S.sel.delete(id); render(); }
  else if (a === 'selpair') { t.dataset.ids.split(',').forEach(i => t.checked ? S.sel.add(i) : S.sel.delete(i)); render(); }
  else if (a === 'selgrp') {
    groupRows(t.dataset.g).filter(matchRow).forEach(r => { if (r.elig) { t.checked ? S.sel.add(r.id) : S.sel.delete(r.id); } else if (t.checked) S.skip[r.id] = r.why; else delete S.skip[r.id]; });
    render();
  }
  else if (a === 'grp') { S.view = {k: 'group', g: t.dataset.g}; S.f = 'all'; $('#nav').classList.remove('open'); render(); window.scrollTo(0, 0); }
  else if (a === 'seg') { S.seg = t.dataset.c; render(); }
  else if (a === 'view') { S.view = {k: t.dataset.v}; render(); window.scrollTo(0, 0); }
  else if (a === 'goto' || a === 'gosearch') gotoRow(id);
  else if (a === 'tab') tryTab(t.dataset.t);
  else if (a === 'leave') { discardAll(); closeDlg(); showTab(t.dataset.t); }
  else if (a === 'menu') $('#nav').classList.toggle('open');
  else if (a === 'demo-conflict') simulateConflict();
  else if (a === 'solo') { S.solo = !S.solo; t.setAttribute('aria-pressed', S.solo); t.textContent = S.solo ? '目前：只有一位最高管理者（再按切回）' : '示範：只有一位最高管理者'; render(); toast('<span>' + (S.solo ? '已切換：系統只有一位最高管理者，放寬方向改為「填原因＋等待＋留紀錄」，沒有第二人核准。' : '已切回：有其他最高管理者，放寬方向要第二位核准。') + '</span>'); }
});
document.addEventListener('change', e => {
  const t = e.target;
  if (t.id === 'opsOk') { checkSaveBtn(); return; }
  const id = t.dataset && t.dataset.chg; if (!id) return;
  let v;
  if (t.type === 'radio') v = Number(t.value);
  else if (t.type === 'number') v = t.value === '' ? NaN : Number(t.value);
  else if (t.tagName === 'SELECT') v = Number(t.value);
  else v = t.value;
  requestChange(id, v);
});
document.addEventListener('input', e => {
  const t = e.target;
  if (t.id === 'gq') doSearch(t.value);
  if (t.id === 'reason') checkSaveBtn();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('#ov').classList.contains('hide')) closeDlg(); });
window.addEventListener('beforeunload', e => { if (totalDrafts() > 0) { e.preventDefault(); e.returnValue = ''; } });
window.pageDirty = (pg, n, title, notify, heavy, cc) => { if (n > 0) S.pdraft[pg] = {n, title, notify, heavy: !!heavy, cc: !!cc}; else delete S.pdraft[pg]; renderSavebar(); };
function showTab(t) {
  $$('.tab').forEach(b => b.setAttribute('aria-selected', b.dataset.t === t));
  ['t1', 't2', 't3'].forEach(x => $('#' + x).classList.toggle('hide', x !== t));
  S.tab = t; try { sessionStorage.setItem('mx-tab', t); } catch (e) {}
}
function tryTab(t) {
  if (t === S.tab) return;
  if (totalDrafts() > 0) { openDlg('<h3>你有未儲存的修改</h3><p>切換到別的頁面會放掉這些草稿（共 ' + totalDrafts() + ' 項）。</p><div class="acts"><button class="btn" data-act="closedlg">留在這裡</button><button class="btn primary" data-act="leave" data-t="' + t + '">放棄並離開</button></div>'); return; }
  showTab(t);
}
S.tab = 't1';
render();
let _t = 't1'; try { _t = sessionStorage.getItem('mx-tab') || 't1'; } catch (e) {}
showTab(_t);
