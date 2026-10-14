/* export-editor.js — 匯出範本編輯器（BP-3）：決定匯出檔有哪些欄位、標題文字與順序；發布前預覽實際輸出
 *
 * 載入方式：頁面只宣告 <meta name="motrix-export-id" content="匯出代號">；sidebar.js 在 /api/platform/menu 回 builderExports:true
 * （builder_exports.enabled 開啟 ＋ 最高管理者才有這個鍵）時才載入本檔。關著 ⇒ 本檔根本不會被載入，頁面沒有任何額外請求。
 * 載入後再問 GET /api/export-templates/{id}/status 取得欄位目錄；不是可編輯 ⇒ 什麼都不畫。
 * 發布走既有的定義端點（kind=export_template，key=匯出代號，scope=company）：版本／還原／稽核／治理（發布前預覽雜湊、待核准）全部沿用。
 *
 * 只是『匯出哪些欄位、叫什麼名字、什麼順序』：資料仍是端點今天的查詢結果；沒有權限的欄位預覽會標示「不會出現」；範本不能新增資料。
 * 發布前一定要先預覽『同一份』草稿；草稿一改就要重新預覽。所有文字用 textContent 寫入（標題是使用者輸入，不用 innerHTML）。
 */
;(function () {
  if (window.MotrixExportEditor) return
  var LABEL_MAX = 20
  var cs = document.currentScript
  var EXPORT_ID = (cs && cs.getAttribute && cs.getAttribute('data-export-id')) || window.MOTRIX_EXPORT_ID || ''
  var st = { open: false, busy: false, state: 'idle', msg: '', msgBad: false, cat: null, cols: [], header: '', footer: '', etag: '', versions: [], previewKey: '', previewHash: '', preview: null, user: '', sample: 'sample', note: '' }
  var root = null

  function session() {
    try { return JSON.parse(localStorage.getItem('motrix_session') || 'null') || {} } catch (e) { return {} }
  }
  function api(method, url, body) {
    var h = { Authorization: 'Bearer ' + (session().token || '') }
    if (body !== undefined) h['Content-Type'] = 'application/json'
    return fetch(url, { method: method, headers: h, body: body === undefined ? undefined : JSON.stringify(body) }).then(function (r) {
      return r.json().catch(function () { return {} }).then(function (j) {
        if (!r.ok) { var e = new Error(msgOf(j) || ('HTTP ' + r.status)); e.status = r.status; e.body = j; throw e }
        return j
      })
    })
  }
  function msgOf(j) {
    var d = j && (j.detail !== undefined ? j.detail : j)
    if (d && d.problems) return d.problems.map(function (p) { return (p.path ? p.path + '：' : '') + p.message }).join('；')
    if (j && j.problems && j.problems.length) return j.problems.map(function (p) { return (p.path ? p.path + '：' : '') + p.message }).join('；')
    return typeof d === 'string' ? d : ''
  }
  function el(tag, attrs, kids) {
    var n = document.createElement(tag)
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] === null || attrs[k] === undefined) return
      if (k === 'text') n.textContent = attrs[k]
      else if (k.indexOf('on') === 0) n.addEventListener(k.slice(2), attrs[k])
      else n.setAttribute(k, attrs[k])
    })
    ;(kids || []).forEach(function (c) { if (c) n.appendChild(c) })
    return n
  }
  function labelProblem(v) {
    if (!String(v).trim()) return '標題不可空白'
    if (String(v).length > LABEL_MAX) return '最多 ' + LABEL_MAX + ' 字'
    if (/[<>&"'`\\{}\x00-\x1f\x7f]/.test(v)) return '不可含 < > & 引號、反斜線、花括號'
    if (/^\s*[=+\-@]/.test(v)) return '不可以 = + - @ 開頭'
    return ''
  }

  // ── 工作副本：目錄順序 ＋ 已存範本 ⇒ cols = [{id, label, on}]（on 的才會輸出；順序即輸出順序）──
  function fromTemplate(tpl) {
    var cat = (st.cat && st.cat.columns) || []
    var byId = {}; cat.forEach(function (c) { byId[c.id] = c })
    var cols = [], seen = {}
    ;((tpl && tpl.columns) || []).forEach(function (c) {
      if (!byId[c.id]) return
      seen[c.id] = true; cols.push({ id: c.id, label: c.label, on: true, money: byId[c.id].money })
    })
    cat.forEach(function (c) { if (!seen[c.id]) cols.push({ id: c.id, label: c.label, on: !tpl, money: c.money }) })
    return cols
  }
  function fmt() { return (st.cat && st.cat.formats && st.cat.formats[0]) || 'csv' }
  function caps() { return ((st.cat && st.cat.caps && st.cat.caps[fmt()]) || []) }
  function toTemplate() {
    var catLabel = {}
    ;((st.cat && st.cat.columns) || []).forEach(function (c) { catLabel[c.id] = c.label })
    var t = { version: 1, format: fmt(),
              columns: st.cols.filter(function (c) { return c.on }).map(function (c) {
                return { id: c.id, label: (st.cat && st.cat.lockLabels && catLabel[c.id]) ? catLabel[c.id] : c.label.trim() } }) }
    if (caps().indexOf('header') >= 0 && st.header.trim()) t.header = { text: st.header.trim() }
    if (caps().indexOf('footer') >= 0 && st.footer.trim()) t.footer = { text: st.footer.trim() }
    return t
  }
  function textProblem(v, what) {
    if (!v.trim()) return ''
    if (v.length > 60) return what + '最多 60 字'
    if (/[<>&"'`\\{}\x00-\x1f\x7f]/.test(v)) return what + '不可含 < > & 引號、反斜線、花括號'
    if (/^\s*[=+\-@]/.test(v)) return what + '不可以 = + - @ 開頭'
    return ''
  }
  function curKey() { return JSON.stringify(toTemplate()) }
  function problems() {
    var out = [], used = {}
    ;[['header', '頁首文字'], ['footer', '頁尾文字']].forEach(function (x) {
      if (caps().indexOf(x[0]) >= 0) { var tp = textProblem(st[x[0]], x[1]); if (tp) out.push(tp) }
    })
    st.cols.forEach(function (c) {
      if (!c.on) return
      var p = (st.cat && st.cat.lockLabels) ? '' : labelProblem(c.label); if (p) out.push(c.id + '：' + p)
      if (used[c.label.trim()]) out.push(c.id + '：標題重複')
      used[c.label.trim()] = true
    })
    if (!st.cols.some(function (c) { return c.on })) out.push('至少要選一個欄位')
    return out
  }

  function load() {
    st.busy = true; st.msg = '讀取中…'; render()
    return api('GET', '/api/definitions/export_template/' + encodeURIComponent(EXPORT_ID) + '?scope=company').then(function (d) {
      var src = (d.draft && d.draft.body) || (d.latest && d.latest.body) || null
      st.cols = fromTemplate(src)
      st.header = (src && src.header && src.header.text) || ''; st.footer = (src && src.footer && src.footer.text) || ''
      st.etag = (d.draft && d.draft.etag) || ''
      st.versions = (d.versions || []).filter(function (v) { return v.status === 'published' })
      st.busy = false; st.msg = ''; st.msgBad = false; st.state = 'idle'; render()
    }).catch(function (e) { st.busy = false; st.state = 'error'; st.msg = '讀取失敗：' + e.message; st.msgBad = true; render() })
  }
  function changed() { st.preview = null; st.previewHash = ''; st.state = 'idle'; st.msg = ''; render() }

  function saveDraft() {
    var p = problems()
    if (p.length) { st.msg = p.join('；'); st.msgBad = true; render(); return Promise.reject(new Error(st.msg)) }
    return api('PUT', '/api/definitions/export_template/' + encodeURIComponent(EXPORT_ID) + '/draft?scope=company', { body: toTemplate(), base_etag: st.etag || '' }).then(function (r) {
      st.etag = r.etag || st.etag
      return r
    })
  }
  // 預覽＝先存草稿，再以選定使用者的權限算出實際輸出；治理開啟時再取『發布前影響預覽』的雜湊（伺服端會記一筆看過預覽）
  function doPreview() {
    st.busy = true; st.msg = '產生預覽中…'; st.msgBad = false; render()
    var key = curKey()
    return saveDraft().then(function () {
      return api('POST', '/api/export-templates/' + encodeURIComponent(EXPORT_ID) + '/preview', { template: JSON.parse(key), user: st.user || undefined, sample: st.sample })
    }).then(function (pv) {
      st.preview = pv
      return api('GET', '/api/def-governance/export_template/' + encodeURIComponent(EXPORT_ID) + '/impact?scope=company').then(function (im) { st.previewHash = im.previewHash || '' }, function () { st.previewHash = '' })
    }).then(function () {
      st.previewKey = key; st.busy = false; st.msg = ''; st.state = 'previewed'; render()
    }).catch(function (e) { st.busy = false; st.state = 'error'; st.msg = '預覽失敗：' + e.message; st.msgBad = true; render() })
  }
  // 待核准的白話說明（與選單編輯器、排版器同一套說法）
  function pendingText(d) {
    var reasons = []
    ;(d.reasons || []).forEach(function (r) { var t = typeof r === 'string' ? r : ((r && (r.message || r.text)) || ''); if (t && reasons.indexOf(t) < 0) reasons.push(t) })
    var at = d.effectiveAt ? String(d.effectiveAt).replace('T', ' ').slice(0, 16) : ''
    return '已送出發布，待第二位最高管理者核准；核准前不會生效' + (at ? '，生效時間 ' + at + ' 之後' : '') + (reasons.length ? '。原因：' + reasons.join('；') : '') + '。'
  }
  function afterWrite(r, doneText) {
    st.busy = false
    if (r && r.pending === true) { st.state = 'pending'; st.msg = pendingText(r); st.msgBad = false; render(); return }
    st.state = 'published'; st.msg = doneText; st.msgBad = false
    return load().then(function () { st.msg = doneText; st.state = 'published'; render() })
  }
  function doPublish() {
    if (st.previewKey !== curKey()) { st.msg = '請先預覽目前這份設定，再發布。'; st.msgBad = true; render(); return Promise.resolve() }
    st.busy = true; st.msg = '發布中…'; render()
    var body = { note: st.note || '', base_etag: st.etag || undefined }
    if (st.previewHash) body.preview_hash = st.previewHash
    return api('POST', '/api/definitions/export_template/' + encodeURIComponent(EXPORT_ID) + '/publish?scope=company', body).then(function (r) {
      return afterWrite(r, '已發布。之後匯出的檔案依這份欄位設定。')
    }).catch(function (e) {
      st.busy = false; st.state = 'error'; st.msgBad = true
      var code = e.body && e.body.code
      st.msg = code === 'preview_required' || code === 'preview_stale' ? '發布前必須先看過目前這份設定的預覽，請重新預覽。' : '發布失敗：' + e.message
      render()
    })
  }
  function doRestore(v) {
    st.busy = true; st.msg = '還原中…'; render()
    return api('POST', '/api/definitions/export_template/' + encodeURIComponent(EXPORT_ID) + '/restore/' + v + '?scope=company', {}).then(function (r) {
      return afterWrite(r, '已還原到第 ' + v + ' 版。')
    }).catch(function (e) { st.busy = false; st.state = 'error'; st.msg = '還原失敗：' + e.message; st.msgBad = true; render() })
  }
  function move(i, dir) {
    var j = i + dir
    if (j < 0 || j >= st.cols.length) return
    var t = st.cols[i]; st.cols[i] = st.cols[j]; st.cols[j] = t; changed()
  }

  // ── 畫面 ──
  function render() {
    if (!root) return
    while (root.firstChild) root.removeChild(root.firstChild)
    root.setAttribute('data-state', st.state)
    var btn = el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: st.open ? '收起匯出格式' : '匯出格式', onclick: function () { st.open = !st.open; if (st.open) load(); else render() } })
    root.appendChild(btn)
    if (!st.open) return
    var panel = el('div', { style: 'margin-top:6px;padding:10px;border:1px solid var(--border,#ccc);border-radius:8px;background:var(--bg-card,#fff);max-width:640px' })
    panel.appendChild(el('div', { text: (st.cat && st.cat.label || '匯出') + '：選擇要匯出的欄位、標題與順序（資料與權限不變；沒有權限看的欄位不會出現）', style: 'font-size:12px;margin-bottom:6px' }))
    st.cols.forEach(function (c, i) {
      var lp = (c.on && !(st.cat && st.cat.lockLabels)) ? labelProblem(c.label) : ''
      panel.appendChild(el('div', { style: 'display:flex;gap:6px;align-items:center;margin:2px 0' }, [
        el('input', { type: 'checkbox', checked: c.on ? 'checked' : null, onchange: function (ev) { c.on = !!ev.target.checked; changed() } }),
        el('input', { type: 'text', value: c.label, maxlength: String(LABEL_MAX), disabled: (st.cat && st.cat.lockLabels) ? 'disabled' : null, style: 'flex:1;font-size:12px', oninput: function (ev) { c.label = ev.target.value; st.preview = null; st.previewHash = ''; st.state = 'idle' } }),
        el('span', { text: c.money ? '（有權限條件）' : '', style: 'font-size:11px;color:var(--text-dim,#888)' }),
        el('button', { type: 'button', text: '↑', onclick: function () { move(i, -1) } }),
        el('button', { type: 'button', text: '↓', onclick: function () { move(i, 1) } }),
        lp ? el('span', { text: lp, style: 'color:#b91c1c;font-size:11px' }) : null
      ]))
    })
    if (st.cat && st.cat.lockLabels) panel.appendChild(el('div', { text: '這個匯出的檔案會被匯入回來（靠表頭文字對應），所以欄位標題固定；可以選欄位與換順序。', style: 'font-size:11px;color:var(--text-dim,#888)' }))
    ;[['header', '頁首文字（列印頁首）'], ['footer', '頁尾文字（列印頁尾）']].forEach(function (x) {
      if (caps().indexOf(x[0]) < 0) return
      panel.appendChild(el('div', { style: 'display:flex;gap:6px;align-items:center;margin-top:6px' }, [
        el('span', { text: x[1], style: 'font-size:12px;min-width:140px' }),
        el('input', { type: 'text', value: st[x[0]], maxlength: '60', style: 'flex:1;font-size:12px', oninput: function (ev) { st[x[0]] = ev.target.value; st.preview = null; st.previewHash = ''; st.state = 'idle' } })
      ]))
    })
    panel.appendChild(el('div', { style: 'display:flex;gap:6px;align-items:center;margin-top:8px' }, [
      el('span', { text: '以誰的身分預覽', style: 'font-size:12px' }),
      el('input', { type: 'text', placeholder: '帳號（空白＝我自己）', value: st.user, style: 'font-size:12px', oninput: function (ev) { st.user = ev.target.value; st.preview = null; st.state = 'idle' } }),
      el('select', { onchange: function (ev) { st.sample = ev.target.value; st.preview = null; st.state = 'idle' } }, [
        el('option', { value: 'sample', text: '樣本資料', selected: st.sample === 'sample' ? 'selected' : null }),
        el('option', { value: 'visible', text: '這個帳號看得到的真實資料', selected: st.sample === 'visible' ? 'selected' : null })
      ]),
      el('button', { type: 'button', class: 'btn btn-sm', text: '預覽', disabled: st.busy ? 'disabled' : null, onclick: doPreview })
    ]))
    if (st.preview) {
      var pv = st.preview
      panel.appendChild(el('div', { text: '預覽（' + pv.user + '，' + (pv.sample === 'visible' ? '真實資料' : '樣本資料') + '；實際輸出的前幾列）', style: 'font-size:12px;margin-top:8px' }))
      var tb = el('table', { style: 'border-collapse:collapse;font-size:11px' })
      tb.appendChild(el('tr', {}, pv.columns.map(function (h) { return el('th', { text: h, style: 'border:1px solid #ccc;padding:2px 4px' }) })))
      pv.rows.forEach(function (r) { tb.appendChild(el('tr', {}, r.map(function (v) { return el('td', { text: v === null || v === undefined ? '' : String(v), style: 'border:1px solid #ccc;padding:2px 4px' }) }))) })
      panel.appendChild(tb)
      if (pv.header) panel.appendChild(el('div', { text: '列印頁首：' + pv.header, style: 'font-size:11px' }))
      if (pv.footer) panel.appendChild(el('div', { text: '列印頁尾：' + pv.footer, style: 'font-size:11px' }))
      ;(pv.warnings || []).forEach(function (w) { panel.appendChild(el('div', { text: w, style: 'font-size:11px;color:#b45309' })) })
    }
    panel.appendChild(el('div', { style: 'display:flex;gap:6px;align-items:center;margin-top:8px' }, [
      el('input', { type: 'text', placeholder: '備註（選填）', value: st.note, style: 'flex:1;font-size:12px', oninput: function (ev) { st.note = ev.target.value } }),
      el('button', { type: 'button', class: 'btn btn-primary btn-sm', text: '發布', disabled: (st.busy || st.previewKey !== curKey()) ? 'disabled' : null, onclick: doPublish })
    ]))
    if (st.versions.length) {
      panel.appendChild(el('div', { style: 'margin-top:8px;font-size:12px' }, [el('span', { text: '還原到：' })].concat(st.versions.slice().reverse().slice(0, 6).map(function (v) {
        return el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '第 ' + v.version + ' 版', onclick: function () { if (window.confirm && !window.confirm('確定還原到第 ' + v.version + ' 版？')) return; doRestore(v.version) } })
      }))))
    }
    if (st.msg) panel.appendChild(el('div', { text: st.msg, style: 'margin-top:6px;font-size:12px;color:' + (st.msgBad ? '#b91c1c' : 'inherit') }))
    root.appendChild(panel)
  }

  function boot() {
    if (!EXPORT_ID) return
    api('GET', '/api/export-templates/' + encodeURIComponent(EXPORT_ID) + '/status').then(function (s) {
      if (!s || !s.enabled || !s.canEdit) return                      // 旗標關／不是最高管理者 ⇒ 完全不畫
      st.cat = s
      root = el('div', { id: 'export-editor-root', style: 'position:fixed;left:12px;bottom:12px;z-index:60;max-width:660px' })
      var host = document.getElementById('export-editor-mount') || document.body
      host.appendChild(root)
      render()
    }).catch(function () { /* 讀不到狀態 ⇒ 當作未開放 */ })
  }
  window.MotrixExportEditor = {
    _toTemplate: toTemplate, _pendingText: pendingText, _publish: doPublish, _preview: doPreview, _restore: doRestore, _state: st,
    _init: function (cat) { st.cat = cat; st.cols = fromTemplate(null); root = null }, _fromTemplate: fromTemplate, _problems: problems,
    open: function () { st.open = true; return load() }
  }
  boot()
})()
