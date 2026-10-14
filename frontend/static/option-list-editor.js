/* option-list-editor.js — 選項清單編輯器（census #4）：新增選項、改顯示名稱、重排、停用；發布前預覽哪些畫面用這份清單
 *
 * 載入方式：頁面只宣告 <meta name="motrix-option-lists" content="清單代號,清單代號">；sidebar.js 在 /api/platform/menu 回
 * builderOptionLists:true（builder_option_lists 開啟、建構器治理開啟、且是最高管理者才有這個鍵）時才載入本檔。關著 ⇒ 完全不載入、沒有額外請求。
 * 發布走既有的定義端點（kind=option_list，key=清單代號，scope=company）：版本／還原／稽核／治理（發布前預覽雜湊、待核准）全部沿用。
 *
 * 規則（伺服端同一組驗證）：已發布的選項不能刪除、不能改字（value），只能停用或改顯示名稱（有些清單不能改名）；
 * 停用＝新增／編輯時不能再選，舊資料照常顯示。所有文字用 textContent 寫入（選項是使用者輸入，不用 innerHTML）。
 */
;(function () {
  if (window.MotrixOptionListEditor) return
  var LABEL_MAX = 20
  var m = document.querySelector && document.querySelector('meta[name="motrix-option-lists"]')
  var IDS = ((m && m.getAttribute('content')) || window.MOTRIX_OPTION_LIST_IDS || '').split(',').map(function (x) { return x.trim() }).filter(Boolean)
  var st = { open: false, busy: false, state: 'idle', msg: '', msgBad: false, id: IDS[0] || '', meta: null, items: [], locked: {}, etag: '', versions: [], preview: null, previewKey: '', previewHash: '', note: '', newValue: '' }
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
  function textProblem(v, what) {
    v = String(v == null ? '' : v)
    if (!v.trim()) return what + '不可空白'
    if (v !== v.trim()) return what + '前後不可有空白'
    if (v.length > LABEL_MAX) return what + '最多 ' + LABEL_MAX + ' 字'
    if (/[<>&"'`\\{}\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]/.test(v)) return what + '不可含 < > & 引號、反斜線、花括號或隱形字元'
    if (/^[=+\-@]/.test(v)) return what + '不可以 = + - @ 開頭'
    return ''
  }
  function toBody() {
    return { version: 1, values: st.items.map(function (x) {
      var o = { value: x.value, label: (st.meta && st.meta.relabel === false) ? x.value : x.label }
      if (x.disabled) o.disabled = true
      if (st.meta && st.meta.prefix) o.prefix = x.prefix
      return o
    }) }
  }
  function curKey() { return JSON.stringify(toBody()) }
  function problems() {
    var out = [], vs = {}, ls = {}, ps = {}
    st.items.forEach(function (x) {
      var p = textProblem(x.value, '選項'); if (p) out.push(p)
      if (vs[x.value]) out.push('選項重複：' + x.value); vs[x.value] = true
      if (!(st.meta && st.meta.relabel === false)) {
        p = textProblem(x.label, '顯示名稱'); if (p) out.push(x.value + '：' + p)
        if (ls[x.label]) out.push('顯示名稱重複：' + x.label); ls[x.label] = true
      }
      if (st.meta && st.meta.prefix) {
        if (!/^[A-Z]{2,5}$/.test(x.prefix || '')) out.push(x.value + '：料號前綴要 2～5 個大寫英文字母')
        if (ps[x.prefix]) out.push('料號前綴重複：' + x.prefix); ps[x.prefix] = true
      }
    })
    if (st.items.length && st.items.every(function (x) { return x.disabled })) out.push('至少要有一個未停用的選項')
    if (st.items.length > 40) out.push('最多 40 個選項')
    return out
  }

  function load() {
    st.busy = true; st.msg = '讀取中…'; render()
    return Promise.all([api('GET', '/api/option-lists/' + encodeURIComponent(st.id) + '/status'),
                        api('GET', '/api/definitions/option_list/' + encodeURIComponent(st.id) + '?scope=company')]).then(function (rs) {
      st.meta = rs[0]
      var d = rs[1], src = ((d.draft && d.draft.body) || (d.latest && d.latest.body) || { values: st.meta.current || [] }).values || []
      var pub = {}
      ;((d.latest && d.latest.body && d.latest.body.values) || (st.meta.defaults || [])).forEach(function (x) { pub[x.value] = true })
      ;(st.meta.defaults || []).forEach(function (x) { pub[x.value] = true })
      st.locked = pub                                         // 已發布（或程式預設）的選項：不能刪除、不能改字
      st.items = src.map(function (x) { return { value: x.value, label: x.label, disabled: !!x.disabled, prefix: x.prefix || '' } })
      st.etag = (d.draft && d.draft.etag) || ''
      st.versions = (d.versions || []).filter(function (v) { return v.status === 'published' })
      st.busy = false; st.msg = ''; st.msgBad = false; st.state = 'idle'; st.preview = null; render()
    }).catch(function (e) { st.busy = false; st.state = 'error'; st.msg = '讀取失敗：' + e.message; st.msgBad = true; render() })
  }
  function changed() { st.preview = null; st.previewHash = ''; st.state = 'idle'; st.msg = ''; render() }
  function saveDraft() {
    var p = problems()
    if (p.length) { st.msg = p.join('；'); st.msgBad = true; render(); return Promise.reject(new Error(st.msg)) }
    return api('PUT', '/api/definitions/option_list/' + encodeURIComponent(st.id) + '/draft?scope=company', { body: toBody(), base_etag: st.etag || '' }).then(function (r) { st.etag = r.etag || st.etag; return r })
  }
  function doPreview() {
    st.busy = true; st.msg = '產生預覽中…'; st.msgBad = false; render()
    var key = curKey()
    return saveDraft().then(function () {
      return api('POST', '/api/option-lists/' + encodeURIComponent(st.id) + '/preview', { template: JSON.parse(key) })
    }).then(function (pv) {
      st.preview = pv
      return api('GET', '/api/def-governance/option_list/' + encodeURIComponent(st.id) + '/impact?scope=company').then(function (im) { st.previewHash = im.previewHash || '' }, function () { st.previewHash = '' })
    }).then(function () { st.previewKey = key; st.busy = false; st.msg = ''; st.state = 'previewed'; render() })
      .catch(function (e) { st.busy = false; st.state = 'error'; st.msg = '預覽失敗：' + e.message; st.msgBad = true; render() })
  }
  function pendingText(d) {
    var reasons = []
    ;(d.reasons || []).forEach(function (r) { var t = typeof r === 'string' ? r : ((r && (r.message || r.text)) || ''); if (t && reasons.indexOf(t) < 0) reasons.push(t) })
    var at = d.effectiveAt ? String(d.effectiveAt).replace('T', ' ').slice(0, 16) : ''
    return '已送出發布，待第二位最高管理者核准；核准前不會生效' + (at ? '，生效時間 ' + at + ' 之後' : '') + (reasons.length ? '。原因：' + reasons.join('；') : '') + '。'
  }
  function afterWrite(r, doneText) {
    st.busy = false
    if (r && r.pending === true) { st.state = 'pending'; st.msg = pendingText(r); st.msgBad = false; render(); return Promise.resolve() }
    st.state = 'published'; st.msg = doneText; st.msgBad = false
    return load().then(function () { st.msg = doneText + ' 重新整理頁面後下拉選單就會用新的清單。'; st.state = 'published'; render() })
  }
  function doPublish() {
    if (st.previewKey !== curKey()) { st.msg = '請先預覽目前這份清單，再發布。'; st.msgBad = true; render(); return Promise.resolve() }
    st.busy = true; st.msg = '發布中…'; render()
    var body = { note: st.note || '', base_etag: st.etag || undefined }
    if (st.previewHash) body.preview_hash = st.previewHash
    return api('POST', '/api/definitions/option_list/' + encodeURIComponent(st.id) + '/publish?scope=company', body).then(function (r) { return afterWrite(r, '已發布。') })
      .catch(function (e) {
        st.busy = false; st.state = 'error'; st.msgBad = true
        var code = e.body && e.body.code
        st.msg = (code === 'preview_required' || code === 'preview_stale') ? '發布前必須先看過目前這份清單的預覽，請重新預覽。' : '發布失敗：' + e.message
        render()
      })
  }
  function doRestore(v) {
    st.busy = true; st.msg = '還原中…'; render()
    return api('POST', '/api/definitions/option_list/' + encodeURIComponent(st.id) + '/restore/' + v + '?scope=company', {}).then(function (r) { return afterWrite(r, '已還原到第 ' + v + ' 版。') })
      .catch(function (e) { st.busy = false; st.state = 'error'; st.msg = '還原失敗：' + e.message; st.msgBad = true; render() })
  }
  function move(i, dir) { var j = i + dir; if (j < 0 || j >= st.items.length) return; var t = st.items[i]; st.items[i] = st.items[j]; st.items[j] = t; changed() }
  function addItem() {
    var v = st.newValue.trim(); var p = textProblem(v, '選項'); if (p) { st.msg = p; st.msgBad = true; render(); return }
    if (st.items.some(function (x) { return x.value === v })) { st.msg = '選項已存在：' + v; st.msgBad = true; render(); return }
    st.items.push({ value: v, label: v, disabled: false, prefix: '' }); st.newValue = ''; changed()
  }

  function render() {
    if (!root) return
    while (root.firstChild) root.removeChild(root.firstChild)
    root.setAttribute('data-state', st.state)
    root.appendChild(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: st.open ? '收起選項清單' : '編輯選項清單', onclick: function () { st.open = !st.open; if (st.open) load(); else render() } }))
    if (!st.open) return
    var panel = el('div', { style: 'margin-top:6px;padding:10px;border:1px solid var(--border,#ccc);border-radius:8px;background:var(--bg-card,#fff);max-width:680px;max-height:70vh;overflow:auto' })
    if (IDS.length > 1) {
      panel.appendChild(el('select', { style: 'margin-bottom:6px', onchange: function (ev) { st.id = ev.target.value; load() } }, IDS.map(function (id) { return el('option', { value: id, text: id, selected: id === st.id ? 'selected' : null }) })))
    }
    if (st.meta) {
      panel.appendChild(el('div', { text: (st.meta.label || st.id) + '：已發布的選項不能刪除，只能停用；停用後新增／編輯時不能再選，舊資料照常顯示。', style: 'font-size:12px;margin-bottom:4px' }))
      ;(st.meta.usedBy || []).forEach(function (u) { panel.appendChild(el('div', { text: '・用在：' + u, style: 'font-size:11px;color:var(--text-dim,#888)' })) })
      if (st.meta.relabel === false) panel.appendChild(el('div', { text: '這份清單的顯示名稱固定（同一個字也被報表或科目對照使用），只能新增、重排或停用。', style: 'font-size:11px;color:var(--text-dim,#888)' }))
    }
    st.items.forEach(function (x, i) {
      var fixedLabel = st.meta && st.meta.relabel === false
      panel.appendChild(el('div', { style: 'display:flex;gap:6px;align-items:center;margin:2px 0' }, [
        el('span', { text: x.value, style: 'min-width:90px;font-size:12px', title: st.locked[x.value] ? '已發布，不能改字' : '新選項' }),
        fixedLabel ? null : el('input', { type: 'text', value: x.label, maxlength: String(LABEL_MAX), style: 'flex:1;font-size:12px', oninput: function (ev) { x.label = ev.target.value; st.preview = null; st.previewHash = ''; st.state = 'idle' } }),
        (st.meta && st.meta.prefix) ? el('input', { type: 'text', value: x.prefix, maxlength: '5', placeholder: '料號前綴', disabled: st.locked[x.value] ? 'disabled' : null, style: 'width:80px;font-size:12px', oninput: function (ev) { x.prefix = ev.target.value; st.preview = null; st.previewHash = ''; st.state = 'idle' } }) : null,
        el('label', { style: 'font-size:11px' }, [el('input', { type: 'checkbox', checked: x.disabled ? 'checked' : null, onchange: function (ev) { x.disabled = !!ev.target.checked; changed() } }), el('span', { text: ' 停用' })]),
        el('button', { type: 'button', text: '↑', onclick: function () { move(i, -1) } }),
        el('button', { type: 'button', text: '↓', onclick: function () { move(i, 1) } }),
        st.locked[x.value] ? null : el('button', { type: 'button', text: '移除', onclick: function () { st.items.splice(i, 1); changed() } })
      ]))
    })
    panel.appendChild(el('div', { style: 'display:flex;gap:6px;margin-top:6px' }, [
      el('input', { type: 'text', value: st.newValue, placeholder: '新增選項', maxlength: String(LABEL_MAX), style: 'font-size:12px', oninput: function (ev) { st.newValue = ev.target.value } }),
      el('button', { type: 'button', class: 'btn btn-sm', text: '＋ 新增選項', onclick: addItem }),
      el('button', { type: 'button', class: 'btn btn-sm', text: '預覽', disabled: st.busy ? 'disabled' : null, onclick: doPreview })
    ]))
    if (st.preview) {
      var pv = st.preview
      panel.appendChild(el('div', { text: '預覽：' + (pv.values || []).map(function (v) { return v.label + (v.disabled ? '（停用）' : '') }).join('、'), style: 'font-size:12px;margin-top:6px' }))
      if ((pv.added || []).length) panel.appendChild(el('div', { text: '新增：' + pv.added.join('、'), style: 'font-size:11px' }))
      ;(pv.warnings || []).forEach(function (w) { panel.appendChild(el('div', { text: w, style: 'font-size:11px;color:#b45309' })) })
    }
    panel.appendChild(el('div', { style: 'display:flex;gap:6px;margin-top:8px' }, [
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
    if (!IDS.length) return
    root = el('div', { id: 'option-list-editor-root', style: 'position:fixed;left:12px;bottom:12px;z-index:60;max-width:700px' })
    document.body.appendChild(root)
    render()
  }
  window.MotrixOptionListEditor = {
    _state: st, _toBody: toBody, _problems: problems, _pendingText: pendingText, _publish: doPublish, _preview: doPreview, _restore: doRestore,
    _init: function (meta, items, locked) { st.meta = meta; st.items = items; st.locked = locked || {}; root = null },
    open: function () { st.open = true; return load() }
  }
  boot()
})()
