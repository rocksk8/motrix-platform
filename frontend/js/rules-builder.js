/* rules-builder.js — BP-2 標示型規則編輯面板（設計 docs/platform/plans/BP2-RULES-MARK-DESIGN-T62.md §8）。
 *
 * 獨立元件（不依賴 Alpine），只有最高管理者用：
 *   MotrixRulesBuilder.available()            ⇒ Promise<boolean>（旗標關／不是最高管理者 ⇒ false，頁面不顯示入口）
 *   MotrixRulesBuilder.open({ entity })       ⇒ 開面板：規則清單、下拉選單編輯器、即時預覽「現有哪些紀錄會被標示」、儲存草稿、預覽並發布
 * 規則只用下拉選單設定（欄位 → 比較 → 門檻 → 顏色 → 提示文字），沒有任何運算式輸入。複雜條件（且／或／非）只顯示、可停用或刪除，不在此編輯。
 * 發布一律經 MotrixDefGovernance.review()（看過同一份草稿的影響預覽 ⇒ preview_hash）；沒有治理面板就不能發布。
 * 放寬（標示變少）會回 pending：畫面如實說「已送出、待第二位最高管理者核准、核准前不會生效」，不說已發布。
 * 所有文字用 esc() 轉義；不用原生 confirm()／alert()（刪除用兩段式內嵌確認）。
 * e2e 等待點：#rb-panel 的 data-state（idle｜previewing｜ready｜saving｜published｜pending｜error）與 data-busy（'0'｜'1'）。
 */
;(function () {
  if (window.MotrixRulesBuilder) return

  function hdr() {
    var s = {}
    try { s = JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) {}
    return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + (s.token || '') }
  }
  function enc(x) { return encodeURIComponent(x) }
  async function call(method, url, payload) {
    var r = await fetch(url, { method: method, headers: hdr(), body: payload === undefined ? undefined : JSON.stringify(payload) })
    var d = await r.json().catch(function () { return null })
    return { ok: r.ok, status: r.status, data: d }
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] }) }
  function clone(x) { return JSON.parse(JSON.stringify(x)) }
  function detailText(r, fallback) {
    var d = r && r.data && r.data.detail
    if (d && typeof d === 'object' && d.problems) return d.problems.map(function (p) { return p.message }).join('；')
    return (typeof d === 'string' && d) || fallback + '（' + (r ? r.status : '?') + '）'
  }

  var OPNAME = { lt: '低於', le: '低於或等於', gt: '高於', ge: '高於或等於', eq: '等於', ne: '不等於', between: '介於', 'in': '屬於', empty: '沒有填', not_empty: '有填' }
  var LEVELS = { red: '紅', yellow: '黃', info: '灰' }
  var NOVAL = { empty: 1, not_empty: 1 }

  var CSS = [
    '#rb-panel{position:fixed;top:0;right:0;bottom:0;width:480px;max-width:100vw;z-index:1300;background:var(--bg-card,#fff);color:var(--text-primary,#222);',
    'border-left:1px solid var(--border-light,#ddd);box-shadow:-8px 0 24px rgba(0,0,0,.1);display:flex;flex-direction:column;font-size:13px}',
    '#rb-panel .rb-head{padding:12px 14px;border-bottom:1px solid var(--border-light,#ddd);display:flex;gap:8px;align-items:center}',
    '#rb-panel .rb-head b{flex:1}#rb-panel .rb-body{flex:1;overflow:auto;padding:10px 14px}#rb-panel .rb-foot{padding:10px 14px;border-top:1px solid var(--border-light,#ddd);display:flex;gap:8px;flex-wrap:wrap}',
    '#rb-panel .rb-row{display:flex;gap:6px;align-items:center;padding:6px 0;border-bottom:1px solid var(--border-light,#eee)}#rb-panel .rb-grow{flex:1;min-width:0}',
    '#rb-panel .rb-dim{color:var(--text-dim,#888);font-size:12px}#rb-panel .rb-bad{color:var(--danger,#c00)}#rb-panel .rb-ok{color:var(--success,#1a7f37)}',
    '#rb-panel .rb-warn{margin:6px 0;padding:6px 8px;border:1px solid var(--warning,#c80);border-radius:6px;font-size:12px}',
    '#rb-panel .rb-chip{display:inline-block;padding:0 6px;border-radius:8px;border:1px solid var(--border-light,#ccc);font-size:12px}',
    '#rb-panel button.rb-btn{padding:3px 9px;border:1px solid var(--border-light,#ccc);border-radius:6px;background:var(--bg-card,#fff);color:inherit;cursor:pointer}',
    '#rb-panel label{display:block;margin:6px 0 2px}#rb-panel input,#rb-panel select{padding:3px 6px;max-width:100%}',
    '#rb-panel .rb-box{margin-top:10px;padding:8px;border:1px solid var(--border-light,#ddd);border-radius:6px}'
  ].join('')

  var st = null
  var VAL_KEYS = { value: 1, min: 1, max: 1, values: 1 }

  function setState(s) { var p = document.getElementById('rb-panel'); if (p) p.setAttribute('data-state', s) }
  function setBusy(b) { if (st) st.busy = b; var p = document.getElementById('rb-panel'); if (p) p.setAttribute('data-busy', b ? '1' : '0') }
  function fieldOf(id) { return (st.ent.fields || []).filter(function (f) { return f.id === id })[0] }
  function simple(r) { var w = r && r.when; return !!(w && w.field && !/^(and|or|not)$/.test(w.op)) }

  function valText(w, f) {
    var u = f && f.unit ? f.unit : ''
    if (NOVAL[w.op]) return ''
    if (w.op === 'between') return w.min + '～' + w.max + u
    if (w.op === 'in') return (w.values || []).join('、')
    return w.value + u
  }
  function condText(r) {
    if (!simple(r)) return '進階條件（且／或／非）'
    var f = fieldOf(r.when.field)
    return (f ? f.label : r.when.field) + ' ' + (OPNAME[r.when.op] || r.when.op) + ' ' + valText(r.when, f)
  }
  function dirty() { return JSON.stringify(st.rules) !== st.base }

  function newRule() {
    var f = (st.ent.fields || [])[0] || { id: '', type: 'number', ops: ['lt'] }
    var n = 1, ids = st.rules.map(function (r) { return r.id })
    while (ids.indexOf('rule_' + n) >= 0) n++
    return { id: 'rule_' + n, name: '新規則', enabled: true, mode: 'mark', on_failure: 'degrade_loud',
             when: defaultWhen(f), mark: { level: 'red', text: '請留意', target: 'row' } }
  }
  function defaultWhen(f) {
    var op = (f.ops || ['eq'])[0]
    var v = f.type === 'number' ? 0 : f.type === 'bool' ? true : f.type === 'date' ? '2026-01-01' : (f.options && f.options[0]) || '值'
    return { op: op, field: f.id, value: v }
  }
  function setOp(w, f, op) {
    var keep = w.field
    Object.keys(w).forEach(function (k) { delete w[k] })
    w.op = op; w.field = keep
    var d = defaultWhen(f).value
    if (op === 'between') { w.min = d; w.max = d }
    else if (op === 'in') { w.values = [d] }
    else if (!NOVAL[op]) { w.value = d }
  }
  function coerce(f, raw) {
    if (f.type === 'number') { var n = Number(raw); return raw === '' || !isFinite(n) ? raw : n }
    if (f.type === 'bool') return raw === 'true'
    return raw
  }

  // ── 畫面 ─────────────────────────────────────────────────────────────────────
  function valueInputs(r) {
    var w = r.when, f = fieldOf(w.field) || {}
    if (NOVAL[w.op]) return ''
    var type = f.type === 'number' ? 'number' : f.type === 'date' ? 'date' : 'text'
    function one(key, val, idx) {
      if (f.type === 'bool') return '<select data-rb-in="' + key + '"><option value="true"' + (val === true ? ' selected' : '') + '>是</option><option value="false"' + (val === false ? ' selected' : '') + '>否</option></select>'
      if (f.type === 'enum' && f.options && f.options.length) {
        return '<select data-rb-in="' + key + '"' + (idx != null ? ' data-i="' + idx + '"' : '') + '>' + f.options.map(function (o) { return '<option' + (o === val ? ' selected' : '') + '>' + esc(o) + '</option>' }).join('') + '</select>'
      }
      return '<input type="' + type + '" data-rb-in="' + key + '"' + (idx != null ? ' data-i="' + idx + '"' : '') + ' value="' + esc(val) + '">'
    }
    if (w.op === 'between') return one('min', w.min) + ' 到 ' + one('max', w.max) + (f.unit ? ' ' + esc(f.unit) : '')
    if (w.op === 'in') return (w.values || []).map(function (v, i) { return one('values', v, i) }).join(' ') + ' <button class="rb-btn" data-rb="addval">＋</button>'
    return one('value', w.value) + (f.unit ? ' ' + esc(f.unit) : '')
  }
  function editor() {
    var r = st.rules[st.sel]
    if (!r) return ''
    if (!simple(r)) {
      return '<div class="rb-box"><div class="rb-warn">這條規則是進階條件，這裡只能啟用／停用或刪除，不能編輯條件。</div>' + ruleMeta(r) + '</div>'
    }
    var w = r.when, f = fieldOf(w.field) || { ops: [] }
    return '<div class="rb-box"><b>編輯規則</b>' +
      '<label>名稱</label><input data-rb-in="name" value="' + esc(r.name) + '" maxlength="30">' +
      '<label>欄位</label><select data-rb-in="field">' + st.ent.fields.map(function (x) { return '<option value="' + esc(x.id) + '"' + (x.id === w.field ? ' selected' : '') + '>' + esc(x.label) + '</option>' }).join('') + '</select>' +
      '<label>比較</label><select data-rb-in="op">' + (f.ops || []).map(function (o) { return '<option value="' + o + '"' + (o === w.op ? ' selected' : '') + '>' + esc(OPNAME[o] || o) + '</option>' }).join('') + '</select>' +
      '<label>門檻</label><div>' + valueInputs(r) + '</div>' + ruleMeta(r) + '</div>'
  }
  function ruleMeta(r) {
    var m = r.mark || {}
    return '<label>標示顏色</label><select data-rb-in="level">' + Object.keys(LEVELS).map(function (k) { return '<option value="' + k + '"' + (k === m.level ? ' selected' : '') + '>' + LEVELS[k] + '</option>' }).join('') + '</select>' +
      '<label>提示文字（最多 40 字，純文字）</label><input data-rb-in="text" value="' + esc(m.text) + '" maxlength="40">' +
      '<label><input type="checkbox" data-rb-in="enabled"' + (r.enabled !== false ? ' checked' : '') + '> 啟用</label>'
  }
  function previewBox() {
    var p = st.preview
    if (st.previewing) return '<div class="rb-box rb-dim" data-rb-preview="loading">預覽計算中…</div>'
    if (!p) return '<div class="rb-box rb-dim" data-rb-preview="none">修改規則後，這裡會顯示現有紀錄有哪些會被標示。</div>'
    if (p.error) return '<div class="rb-box rb-bad" data-rb-preview="error">' + esc(p.error) + '</div>'
    if (p.available === false) return '<div class="rb-box" data-rb-preview="unavailable">' + esc(p.message || '無法預覽') + '</div>'
    var dir = { tighten: '標示變多（收緊，立即生效）', loosen: '標示變少或無法判斷（放寬，需第二位最高管理者核准）', neutral: '標示範圍不變' }[p.direction] || ''
    var rows = (p.samples || []).slice(0, 10).map(function (s) {
      return '<div class="rb-row"><span class="rb-grow">' + esc(s.label) + '</span>' + (s.isNew ? '<span class="rb-chip">新增</span>' : '') + '</div>'
    }).join('')
    return '<div class="rb-box" data-rb-preview="ok"><b>預覽（尚未發布）</b>' +
      '<div>目前已發布會標示 <b>' + esc(p.published.records) + '</b> 筆 → 套用後 <b>' + esc(p.draft.records) + '</b> 筆（新增 ' + esc(p.added) + '、取消 ' + esc(p.removed) + '）</div>' +
      (dir ? '<div class="' + (p.direction === 'loosen' ? 'rb-bad' : 'rb-ok') + '">' + esc(dir) + '</div>' : '') +
      ((p.reasons || []).length ? '<div class="rb-dim">' + p.reasons.map(esc).join('；') + '</div>' : '') +
      (p.degraded && p.degraded.length ? '<div class="rb-warn">有 ' + p.degraded.length + ' 條規則在預覽時故障，已略過。</div>' : '') +
      (rows ? '<div class="rb-dim" style="margin-top:6px">樣本（你看得到的前 10 筆）</div>' + rows : '') +
      '<div class="rb-dim" style="margin-top:6px">' + esc(p.note || '') + '</div></div>'
  }
  function render() {
    var p = document.getElementById('rb-panel')
    if (!p || !st) return
    var listing = st.rules.map(function (r, i) {
      var hits = st.hits && st.hits[r.id] != null ? '目前命中 ' + st.hits[r.id] + ' 筆' : ''
      return '<div class="rb-row" data-rb-rule="' + esc(r.id) + '"><div class="rb-grow"><b>' + esc(r.name) + '</b> <span class="rb-chip">' + esc(LEVELS[(r.mark || {}).level] || '?') + '</span>' +
        (r.enabled === false ? ' <span class="rb-dim">（停用）</span>' : '') + '<div class="rb-dim">' + esc(condText(r)) + (hits ? '　' + esc(hits) : '') + '</div></div>' +
        '<button class="rb-btn" data-rb="edit:' + i + '">編輯</button>' +
        (st.delConfirm === i ? '<span class="rb-bad">刪除？</span><button class="rb-btn" data-rb="del-yes:' + i + '">確定</button><button class="rb-btn" data-rb="del-no">取消</button>'
          : '<button class="rb-btn" data-rb="del:' + i + '">刪除</button>') + '</div>'
    }).join('') || '<div class="rb-dim">還沒有規則。按「新增規則」開始。</div>'
    p.innerHTML = '<div class="rb-head"><b>標示規則：' + esc(st.ent.label) + '</b><span class="rb-dim">已發布第 ' + esc(st.pubVersion || 0) + ' 版' + (dirty() ? '・有未儲存的修改' : '') + '</span>' +
      '<button class="rb-btn" data-rb="close" aria-label="關閉">✕</button></div>' +
      '<div class="rb-body">' +
      (st.msg ? '<div class="' + (st.msgBad ? 'rb-warn rb-bad' : 'rb-warn') + '" data-rb-msg="1">' + esc(st.msg) + '</div>' : '') +
      '<div class="rb-dim">規則只做標示：不會改資料、不會擋存檔。看不到來源欄位的人（例如沒有成本權限者）不會看到由該欄位產生的標示。</div>' +
      listing + '<div style="margin-top:8px"><button class="rb-btn" data-rb="add">新增規則</button></div>' + editor() + previewBox() + '</div>' +
      '<div class="rb-foot">' + (st.k01 && st.ent.key === 'case' && !st.rules.some(function (r) { return r.id === 'k01_project_margin' }) ? '<button class="rb-btn" data-rb="k01">匯入現有利潤警示</button>' : '') + '<button class="rb-btn" data-rb="save"' + (st.busy || !dirty() ? ' disabled' : '') + '>儲存草稿</button>' +
      '<button class="rb-btn" data-rb="publish"' + (st.busy ? ' disabled' : '') + '>預覽並發布…</button></div>'
  }

  // ── 動作 ─────────────────────────────────────────────────────────────────────
  var timer = null, seq = 0
  function schedulePreview() {
    clearTimeout(timer)
    timer = setTimeout(runPreview, 400)
  }
  async function runPreview() {
    if (!st) return
    var mine = ++seq
    st.previewing = true; setState('previewing'); render()
    var r = await call('POST', '/api/rules/preview', { entity: st.o.entity, body: { rules: st.rules } })
    if (!st || mine !== seq) return                                          // 面板已關、或有更新的一次預覽在跑 ⇒ 丟掉舊結果
    st.previewing = false
    st.preview = r.ok ? r.data : { error: detailText(r, '預覽失敗') }         // 失敗就如實顯示，不留舊結果
    setState(r.ok ? 'ready' : 'error'); render()
  }
  async function refreshHits() {
    var r = await call('GET', '/api/rules/summary?entity=' + enc(st.o.entity))
    if (st && r.ok && r.data && r.data.available) { st.hits = r.data.hits || {}; render() }
  }
  async function load() {
    var c = await call('GET', '/api/rules/config')
    if (!c.ok) throw new Error(detailText(c, '載入失敗'))
    st.k01 = !!c.data.k01Seed
    st.ent = (c.data.entities || []).filter(function (e) { return e.key === st.o.entity })[0]
    if (!st.ent) throw new Error('未知的規則主題')
    var d = await call('GET', '/api/definitions/rule_set/' + enc(st.o.entity) + '?scope=company')
    if (!d.ok) throw new Error(detailText(d, '載入規則失敗'))
    var src = d.data.draft || d.data.latest
    st.rules = clone(((src && src.body) || {}).rules || [])
    st.pubVersion = d.data.latest ? d.data.latest.version : 0
    st.base = JSON.stringify(st.rules)                                          // 載入時的內容＝基準；之後的差異才算『未儲存的修改』
  }
  async function save() {
    setBusy(true); setState('saving')
    var r = await call('PUT', '/api/definitions/rule_set/' + enc(st.o.entity) + '/draft?scope=company', { body: { rules: st.rules } })
    setBusy(false)
    if (!st) return
    if (r.ok) { st.base = JSON.stringify(st.rules); st.msg = '已儲存草稿'; st.msgBad = false; setState('ready') }
    else { st.msg = '儲存失敗：' + detailText(r, '') ; st.msgBad = true; setState('error') }
    render()
    return r.ok
  }
  async function seedK01() {
    setBusy(true)
    var r = await call('POST', '/api/rules/k01/seed')
    if (!r.ok) { setBusy(false); st.msg = '匯入失敗：' + detailText(r, ''); st.msgBad = true; setState('error'); return render() }
    try { await load() } catch (e) { st.msg = String(e.message || e); st.msgBad = true }
    setBusy(false)
    st.msg = (r.data && r.data.message) || '已匯入為草稿'; st.msgBad = false; setState('ready'); schedulePreview(); render()
  }
  async function publish() {
    if (!window.MotrixDefGovernance) { st.msg = '找不到治理面板，無法發布（發布前一定要先看過影響預覽）'; st.msgBad = true; setState('error'); return render() }
    if (!(await save())) return
    var pvh = await window.MotrixDefGovernance.review({ kind: 'rule_set', key: st.o.entity, scope: 'company', title: '發布前影響預覽：標示規則' })
    if (!st) return
    if (!pvh) { st.msg = '已取消發布'; st.msgBad = false; setState('ready'); return render() }
    setBusy(true)
    var r = await call('POST', '/api/definitions/rule_set/' + enc(st.o.entity) + '/publish?scope=company', { note: '標示規則', preview_hash: pvh })
    setBusy(false)
    if (!st) return
    if (!r.ok) { st.msg = '發布失敗：' + detailText(r, ''); st.msgBad = true; setState('error'); return render() }
    if (r.data && r.data.pending === true) {                                   // 放寬：還沒生效，不能說已發布
      var at = r.data.effectiveAt ? String(r.data.effectiveAt).replace('T', ' ').slice(0, 16) : ''
      st.msg = '已送出，待第二位最高管理者核准；核准前不會生效' + (at ? '，最早生效時間 ' + at + ' 之後' : '') +
        ((r.data.reasons || []).length ? '。原因：' + r.data.reasons.join('；') : '')
      st.msgBad = false; setState('pending')
    } else {
      st.pubVersion = r.data.version; st.msg = '已發布第 ' + r.data.version + ' 版'; st.msgBad = false; setState('published')
      refreshHits()
    }
    render()
  }

  function onClick(e) {
    var b = e.target.closest ? e.target.closest('[data-rb]') : null
    if (!b || !st) return
    var a = b.getAttribute('data-rb')
    if (a === 'close') return close()
    if (a === 'add') { st.rules.push(newRule()); st.sel = st.rules.length - 1; schedulePreview(); return render() }
    if (a.indexOf('edit:') === 0) { st.sel = Number(a.slice(5)); return render() }
    if (a.indexOf('del:') === 0) { st.delConfirm = Number(a.slice(4)); return render() }
    if (a === 'del-no') { st.delConfirm = -1; return render() }
    if (a.indexOf('del-yes:') === 0) { st.rules.splice(Number(a.slice(8)), 1); st.delConfirm = -1; st.sel = -1; schedulePreview(); return render() }
    if (a === 'addval') { var w = st.rules[st.sel].when; w.values.push(w.values[0]); schedulePreview(); return render() }
    if (a === 'k01') return seedK01()
    if (a === 'save') return save()
    if (a === 'publish') return publish()
  }
  function onInput(e) {
    var el = e.target, k = el.getAttribute && el.getAttribute('data-rb-in')
    if (!k || !st || st.sel < 0) return
    var r = st.rules[st.sel], redraw = false
    if (k === 'name') r.name = el.value
    else if (k === 'level') r.mark.level = el.value
    else if (k === 'text') r.mark.text = el.value
    else if (k === 'enabled') r.enabled = !!el.checked
    else if (k === 'field') { var f = fieldOf(el.value); r.when = defaultWhen(f); redraw = true }
    else if (k === 'op') { setOp(r.when, fieldOf(r.when.field), el.value); redraw = true }
    else if (VAL_KEYS[k]) {
      var f2 = fieldOf(r.when.field), v = coerce(f2, el.value)
      if (k === 'values') r.when.values[Number(el.getAttribute('data-i') || 0)] = v
      else r.when[k] = v
    }
    schedulePreview()
    if (redraw || k === 'name' || k === 'level' || k === 'enabled') render()        // 打字中的欄位（門檻、文字）不重畫，避免失去游標
  }

  function close() {
    var p = document.getElementById('rb-panel')
    if (p) p.remove()
    clearTimeout(timer); st = null
  }

  //: 入口：宣告了規則插槽的頁面（同 rule-marks.js 的 PAGES）。由頁面在『已讀到 builder_rules.enabled＝1』後呼叫 mountEntry()；不是最高管理者 ⇒ 不送任何請求。
  var ENTRY = { 'case-management.html': 'case' }
  function entryButton() {
    var ent = ENTRY[String(location.pathname || '').split('/').pop()]
    var sess = {}
    try { sess = JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) {}
    if (!ent || !sess.token || sess.role !== 'superadmin') return              // 其他人連探測都不送
    window.MotrixRulesBuilder.available().then(function (ok) {
      if (!ok || document.getElementById('rb-btn')) return
      if (!document.getElementById('rb-style')) { var s = document.createElement('style'); s.id = 'rb-style'; s.textContent = CSS; document.head.appendChild(s) }
      var b = document.createElement('button')
      b.id = 'rb-btn'; b.type = 'button'; b.textContent = '標示規則'; b.className = 'btn'
      b.setAttribute('style', 'position:fixed;left:120px;bottom:12px;z-index:1150;padding:6px 12px;font-size:12px')
      b.addEventListener('click', function () { window.MotrixRulesBuilder.open({ entity: ent }) })
      document.body.appendChild(b)
    }).catch(function () {})
  }

  window.MotrixRulesBuilder = {
    async available() {
      try {
        var r = await fetch('/api/rules/config', { headers: hdr() })
        return r.ok
      } catch (e) { return false }
    },
    async open(o) {
      if (!o || !o.entity) return
      close()
      if (!document.getElementById('rb-style')) { var s = document.createElement('style'); s.id = 'rb-style'; s.textContent = CSS; document.head.appendChild(s) }
      var p = document.createElement('div')
      p.id = 'rb-panel'; p.setAttribute('role', 'dialog'); p.setAttribute('aria-label', '標示規則'); p.setAttribute('data-busy', '0'); p.setAttribute('data-state', 'idle')
      p.addEventListener('click', onClick); p.addEventListener('input', onInput); p.addEventListener('change', onInput)
      document.body.appendChild(p)
      st = { o: o, ent: null, rules: [], base: '[]', pubVersion: 0, sel: -1, delConfirm: -1, busy: false, preview: null, previewing: false, hits: null, msg: '', msgBad: false }
      try {
        await load()
      } catch (e) {
        if (st) { st.ent = { label: o.entity, fields: [] }; st.msg = String(e.message || e); st.msgBad = true; setState('error') }
      }
      if (!st) return
      render()
      refreshHits()
    },
    _state: function () { return st }
  }
  window.MotrixRulesBuilder.mountEntry = entryButton          // 不會自己執行：頁面讀到設定 builder_rules.enabled＝1 之後才呼叫（旗標關時載入本檔完全惰性）
})()
