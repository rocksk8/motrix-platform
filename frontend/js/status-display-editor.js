/* status-display-editor.js — 狀態顯示名稱與顏色編輯面板（S-X2；設計 docs/platform/plans/STATUS-DISPLAY-INVENTORY-T62.md）。
 *
 * 獨立元件（不依賴 Alpine），只有最高管理者用：
 *   MotrixStatusEditor.available()  ⇒ Promise<boolean>（旗標關／不是最高管理者 ⇒ false，頁面不顯示入口）
 *   MotrixStatusEditor.open()       ⇒ 開面板：每個狀態一列（資料庫值唯讀）、顯示名稱、各情境簡稱、顏色（固定色盤）、
 *                                      即時預覽：同一個狀態在報價單列表／案件卡片／出納 三個地方看起來的樣子；儲存草稿、發布。
 * 只改『看到的字與色』：狀態的鍵（資料庫值）、查詢、權限、流程都不變。顏色只能從固定色盤選，沒有自由色碼。
 * 發布一律經 MotrixDefGovernance.review()（看過同一份草稿的影響預覽 ⇒ preview_hash）；沒有治理面板就不能發布。
 * 核准／付款類狀態改名或改色＝放寬：回 pending，畫面如實說「待第二位最高管理者核准、核准前不會生效」。
 * 所有文字用 esc() 轉義；不用瀏覽器原生對話框。
 * e2e 等待點：#sde-panel 的 data-state（idle｜ready｜saving｜published｜pending｜error）與 data-busy（'0'｜'1'）。
 */
;(function () {
  if (window.MotrixStatusEditor) return

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

  var TONE_NAME = { neutral: '中性（無色）', draft: '灰（草稿）', pending: '琥珀（待審）', signing: '藍（簽核中）', approved: '綠（已核准）', rejected: '紅（駁回）', paid: '深綠（已付款）', 'void': '淡灰（作廢）' }
  var GROUP_NAME = { approval: '單據與簽核狀態', quote: '報價單', deal: '案件進度（deal_tag）', settle: '成本精算' }
  var CTX_NAME = { quote_list: '報價單列表', quote_form: '報價單表單', 'case': '案件管理', cashier: '出納', report: '報表', settlement: '精算頁' }
  var PREVIEW_CTX = [['quote_list', '報價單列表'], ['case', '案件卡片'], ['cashier', '出納']]
  var OFFICIAL = ['核准', '核準', '批准', '核可', '已簽核', '簽核完成', '簽核通過', '審核通過', '已通過', '通過', '生效', '確認', '已批', '批示', '已准', '准予', '承認', '認可', '同意', '已签核', '审核通过', '通过', '确认', '承认', '认可', 'OK', 'Approved']   // 僅供即時提示；伺服器才是準的（會去掉分隔、比對繁簡與英文）

  var CSS = [
    '#sde-panel{position:fixed;top:0;right:0;bottom:0;width:560px;max-width:100vw;z-index:1300;background:var(--bg-card,#fff);color:var(--text-primary,#222);',
    'border-left:1px solid var(--border-light,#ddd);box-shadow:-8px 0 24px rgba(0,0,0,.1);display:flex;flex-direction:column;font-size:13px}',
    '#sde-panel .sde-head{padding:12px 14px;border-bottom:1px solid var(--border-light,#ddd);display:flex;gap:8px;align-items:center}',
    '#sde-panel .sde-head b{flex:1}#sde-panel .sde-body{flex:1;overflow:auto;padding:10px 14px}#sde-panel .sde-foot{padding:10px 14px;border-top:1px solid var(--border-light,#ddd);display:flex;gap:8px;align-items:center}',
    '#sde-panel .sde-row{padding:8px 0;border-bottom:1px solid var(--border-light,#eee)}#sde-panel .sde-line{display:flex;gap:6px;align-items:center;flex-wrap:wrap}',
    '#sde-panel .sde-key{min-width:72px;font-weight:600}#sde-panel .sde-dim{color:var(--text-dim,#888);font-size:12px}',
    '#sde-panel .sde-bad{color:var(--danger,#c00)}#sde-panel .sde-ok{color:var(--success,#1a7f37)}',
    '#sde-panel .sde-warn{margin:6px 0;padding:6px 8px;border:1px solid var(--warning,#c80);border-radius:6px;font-size:12px}',
    '#sde-panel .sde-grp{margin:12px 0 4px;font-weight:600}#sde-panel input,#sde-panel select{padding:3px 6px;max-width:100%}',
    '#sde-panel button.sde-btn{padding:3px 9px;border:1px solid var(--border-light,#ccc);border-radius:6px;background:var(--bg-card,#fff);color:inherit;cursor:pointer}',
    '#sde-panel .sde-prev{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:4px}#sde-panel .sde-ctx{font-size:11px;color:var(--text-dim,#888)}'
  ].join('')

  var st = null
  function setState(s) { var p = document.getElementById('sde-panel'); if (p) p.setAttribute('data-state', s) }
  function setBusy(b) { if (st) st.busy = b; var p = document.getElementById('sde-panel'); if (p) p.setAttribute('data-busy', b ? '1' : '0') }

  // ── 表：預設（server 回的完整表是『預設疊上已發布版』，所以另外抓預設） ─────────────────────────
  function eff(k) {                      // 目前草稿疊在預設上的有效值
    var d = st.defaults[k], o = st.draft[k] || {}
    return { label: o.label != null ? o.label : d.label, tone: o.tone != null ? o.tone : d.tone, order: d.order,
             names: Object.assign({}, d.names, o.names || {}) }
  }
  function nameFor(k, ctx) { var e = eff(k); return e.names[ctx] || e.label }
  function chip(k, ctx) {
    var e = eff(k)
    return '<span class="st-chip' + (e.tone && e.tone !== 'neutral' ? ' st-chip--' + e.tone : '') + '">' + esc(nameFor(k, ctx)) + '</span>'
  }
  function setField(k, field, value) {
    var o = st.draft[k] || (st.draft[k] = {}), d = st.defaults[k]
    if (field === 'label') { if (value === d.label || value === '') delete o.label; else o.label = value }
    else if (field === 'tone') { if (value === d.tone) delete o.tone; else o.tone = value }
    else if (field.indexOf('names.') === 0) {
      var c = field.slice(6), names = o.names || (o.names = {})
      if (value === '' || value === (d.names[c] || '')) delete names[c]; else names[c] = value
      if (!Object.keys(names).length) delete o.names
    }
    if (!Object.keys(o).length) delete st.draft[k]
  }
  function bodyOut() { return { statuses: clone(st.draft) } }
  function dirty() { return JSON.stringify(bodyOut()) !== st.base }

  function hint(k) {
    var meta = st.meta[k] || {}, e = eff(k), bad = []
    if (meta.semantic !== 'approved') {
      var texts = [e.label].concat(Object.keys(e.names).map(function (c) { return e.names[c] }))
      var dflt = [st.defaults[k].label].concat(Object.keys(st.defaults[k].names).map(function (c) { return st.defaults[k].names[c] }))
      texts.forEach(function (t) { if (dflt.indexOf(t) < 0 && !/^(待|未|尚未|等待|不)/.test(t) && OFFICIAL.some(function (w) { return t.replace(/[^\p{L}\p{N}]/gu, '').toLowerCase().indexOf(w.toLowerCase()) >= 0 })) bad.push(t) })
    }
    return bad.length ? '「' + bad.join('、') + '」含官方用語（' + OFFICIAL.join('、') + '），這個狀態不能使用' : ''
  }

  function render() {
    var p = document.getElementById('sde-panel')
    if (!p || !st) return
    var groups = {}
    Object.keys(st.defaults).forEach(function (k) { var g = (st.meta[k] || {}).group || 'approval'; (groups[g] = groups[g] || []).push(k) })
    var html = '<div class="sde-head"><b>狀態顯示名稱與顏色</b><button class="sde-btn" data-sde="close" aria-label="關閉">關閉</button></div><div class="sde-body">'
    html += '<div class="sde-dim">只改畫面上看到的字與色；狀態的值（資料庫裡存的字）、查詢與權限都不變。核准、付款類狀態改名或改色需要第二位最高管理者核准。「顯示名稱」是預設用字；若某個畫面有自己的簡稱（例如報價單列表的「審核中」），要改那個畫面就改它的簡稱欄，只改顯示名稱不會蓋掉它。</div>'
    Object.keys(GROUP_NAME).forEach(function (g) {
      if (!groups[g]) return
      html += '<div class="sde-grp">' + esc(GROUP_NAME[g]) + '</div>'
      groups[g].forEach(function (k) {
        var e = eff(k), d = st.defaults[k], meta = st.meta[k] || {}, changed = !!st.draft[k]
        html += '<div class="sde-row" data-key="' + esc(k) + '"><div class="sde-line"><span class="sde-key">' + esc(k) + '</span>' +
          '<span class="sde-dim">顯示名稱</span><input data-sde-in="label:' + esc(k) + '" value="' + esc(e.label) + '" maxlength="12" size="9" aria-label="' + esc(k) + ' 的顯示名稱">' +
          '<span class="sde-dim">顏色</span><select data-sde-in="tone:' + esc(k) + '" aria-label="' + esc(k) + ' 的顏色">' +
          (meta.allowedTones || ['neutral']).map(function (t) { return '<option value="' + esc(t) + '"' + (t === e.tone ? ' selected' : '') + '>' + esc(TONE_NAME[t] || t) + '</option>' }).join('') +
          '</select>' + (changed ? '<button class="sde-btn" data-sde="reset:' + esc(k) + '">還原預設</button>' : '') + '</div>'
        var ctxIn = Object.keys(d.names).concat(Object.keys(e.names).filter(function (c) { return !(c in d.names) }))
        if (ctxIn.length) {
          html += '<div class="sde-line sde-dim">各畫面簡稱：' + ctxIn.map(function (c) {
            return esc(CTX_NAME[c] || c) + ' <input data-sde-in="names.' + esc(c) + ':' + esc(k) + '" value="' + esc(e.names[c] || '') + '" maxlength="12" size="7" aria-label="' + esc(k) + ' 在' + esc(CTX_NAME[c] || c) + '的簡稱">'
          }).join('　') + '</div>'
        }
        html += '<div class="sde-prev" data-sde-preview="' + esc(k) + '">' + PREVIEW_CTX.map(function (c) { return '<span><span class="sde-ctx">' + esc(c[1]) + '</span> ' + chip(k, c[0]) + '</span>' }).join('') + '</div>'
        var h = hint(k)
        if (h) html += '<div class="sde-bad" role="alert">' + esc(h) + '</div>'
        html += '</div>'
      })
    })
    html += '</div><div class="sde-foot"><button class="sde-btn" data-sde="save"' + (st.busy ? ' disabled' : '') + '>儲存草稿</button>' +
      '<button class="sde-btn" data-sde="publish"' + (st.busy ? ' disabled' : '') + '>預覽並發布</button>' +
      '<span class="' + (st.msgBad ? 'sde-bad' : 'sde-ok') + '" role="status">' + esc(st.msg || (dirty() ? '有尚未儲存的修改' : '')) + '</span></div>'
    p.innerHTML = html
  }

  // 輸入時只更新預覽（不整個重畫，才不會失去游標）
  function refreshPreview(k) {
    var el = document.querySelector('#sde-panel [data-sde-preview="' + k + '"]')
    if (el) el.innerHTML = PREVIEW_CTX.map(function (c) { return '<span><span class="sde-ctx">' + esc(c[1]) + '</span> ' + chip(k, c[0]) + '</span>' }).join('')
  }

  async function load() {
    var pub = await call('GET', '/api/status-display')
    if (!pub.ok || !pub.data || pub.data.enabled !== true) throw new Error('狀態自訂功能未開啟')
    st.meta = pub.data.meta || {}
    var d = await call('GET', '/api/definitions/status_display/default?scope=company')
    if (!d.ok) throw new Error(detailText(d, '載入失敗'))
    var src = d.data.draft || d.data.latest
    st.draft = clone(((src && src.body) || {}).statuses || {})
    st.defaults = clone(pub.data.defaults)           // 程式內建的預設表（草稿只存和預設不同的欄位）
    st.base = JSON.stringify(bodyOut())
  }
  async function save() {
    setBusy(true); setState('saving')
    var r = await call('PUT', '/api/definitions/status_display/default/draft?scope=company', { body: bodyOut() })
    setBusy(false)
    if (!st) return false
    if (r.ok) { st.base = JSON.stringify(bodyOut()); st.msg = '已儲存草稿'; st.msgBad = false; setState('ready') }
    else { st.msg = '儲存失敗：' + detailText(r, ''); st.msgBad = true; setState('error') }
    render()
    return r.ok
  }
  async function publish() {
    if (!window.MotrixDefGovernance) { st.msg = '找不到治理面板，無法發布（發布前一定要先看過影響預覽）'; st.msgBad = true; setState('error'); return render() }
    if (!(await save())) return
    var pvh = await window.MotrixDefGovernance.review({ kind: 'status_display', key: 'default', scope: 'company', title: '發布前影響預覽：狀態顯示名稱與顏色' })
    if (!st) return
    if (!pvh) { st.msg = '已取消發布'; st.msgBad = false; setState('ready'); return render() }
    setBusy(true)
    var r = await call('POST', '/api/definitions/status_display/default/publish?scope=company', { note: '狀態顯示名稱與顏色', preview_hash: pvh })
    setBusy(false)
    if (!st) return
    if (!r.ok) { st.msg = '發布失敗：' + detailText(r, ''); st.msgBad = true; setState('error'); return render() }
    if (r.data && r.data.pending === true) {
      var at = r.data.effectiveAt ? String(r.data.effectiveAt).replace('T', ' ').slice(0, 16) : ''
      st.msg = '已送出，待第二位最高管理者核准；核准前不會生效' + (at ? '，最早生效時間 ' + at + ' 之後' : '') + ((r.data.reasons || []).length ? '。原因：' + r.data.reasons.join('；') : '')
      st.msgBad = false; setState('pending')
    } else {
      st.msg = '已發布第 ' + r.data.version + ' 版；重新整理頁面後各畫面會顯示新的名稱與顏色'; st.msgBad = false; setState('published')
      if (window.MotrixStatus && window.MotrixStatus.reset) { window.MotrixStatus.reset(); window.MotrixStatus.load() }
    }
    render()
  }

  function onClick(e) {
    var b = e.target.closest ? e.target.closest('[data-sde]') : null
    if (!b || !st) return
    var a = b.getAttribute('data-sde')
    if (a === 'close') return close()
    if (a === 'save') return save()
    if (a === 'publish') return publish()
    if (a.indexOf('reset:') === 0) { delete st.draft[a.slice(6)]; st.msg = ''; return render() }
  }
  function onInput(e) {
    var el = e.target, k = el.getAttribute && el.getAttribute('data-sde-in')
    if (!k || !st) return
    var i = k.indexOf(':'), field = k.slice(0, i), key = k.slice(i + 1)
    setField(key, field, field === 'tone' ? el.value : el.value.trim())
    st.msg = ''
    if (field === 'tone') return render()
    refreshPreview(key)
  }

  function close() { var p = document.getElementById('sde-panel'); if (p) p.remove(); st = null }

  var ENTRY_PAGES = { 'case-management.html': 1, 'quotations.html': 1 }
  function entryButton() {
    var sess = {}
    try { sess = JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) {}
    if (!ENTRY_PAGES[String(location.pathname || '').split('/').pop()] || !sess.token || sess.role !== 'superadmin') return
    window.MotrixStatusEditor.available().then(function (ok) {
      if (!ok || document.getElementById('sde-btn')) return
      if (!document.getElementById('sde-style')) { var s = document.createElement('style'); s.id = 'sde-style'; s.textContent = CSS; document.head.appendChild(s) }
      var b = document.createElement('button')
      b.id = 'sde-btn'; b.type = 'button'; b.textContent = '狀態名稱與顏色'; b.className = 'btn'
      b.setAttribute('style', 'position:fixed;left:250px;bottom:12px;z-index:1150;padding:6px 12px;font-size:12px')
      b.addEventListener('click', function () { window.MotrixStatusEditor.open() })
      document.body.appendChild(b)
    }).catch(function () {})
  }

  window.MotrixStatusEditor = {
    async available() {
      try { var r = await call('GET', '/api/status-display'); return !!(r.ok && r.data && r.data.enabled === true) } catch (e) { return false }
    },
    async open() {
      close()
      if (!document.getElementById('sde-style')) { var s = document.createElement('style'); s.id = 'sde-style'; s.textContent = CSS; document.head.appendChild(s) }
      var p = document.createElement('div')
      p.id = 'sde-panel'; p.setAttribute('role', 'dialog'); p.setAttribute('aria-label', '狀態顯示名稱與顏色'); p.setAttribute('data-busy', '0'); p.setAttribute('data-state', 'idle')
      p.addEventListener('click', onClick); p.addEventListener('input', onInput); p.addEventListener('change', onInput)
      document.body.appendChild(p)
      st = { defaults: {}, meta: {}, draft: {}, base: '{}', busy: false, msg: '', msgBad: false }
      try { await load(); setState('ready') } catch (e) { if (st) { st.msg = String(e.message || e); st.msgBad = true; setState('error') } }
      if (st) render()
    },
    _state: function () { return st }
  }
  window.MotrixStatusEditor.mountEntry = entryButton       // 頁面讀到旗標 builder_status_display.enabled＝1 之後才呼叫；旗標關時載入本檔完全惰性
})()
