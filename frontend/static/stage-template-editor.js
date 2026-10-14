/* stage-template-editor.js — 案件階段樣板編輯器（S-ST2；設計 docs/platform/plans/CASE-STAGE-TEMPLATE-INVESTIGATION-T62.md）
 *
 * 載入方式：案件頁載入本檔（惰性：載入時不做任何事、不送請求）；頁面在已讀到旗標 builder_stage_templates.enabled＝1 且是最高管理者時，
 * 由「管理階段樣板」按鈕呼叫 MotrixStageTemplateEditor.open()。關著 ⇒ 沒有入口、沒有請求。
 * 發布走既有的定義端點（kind=case_stage_template，key=樣板鍵，scope=company）：版本／還原／稽核／治理（發布前預覽雜湊、待核准）全部沿用。
 *
 * 規則（伺服端同一組驗證 helpers/stage_templates.py）：階段種類鍵建立後不可改（已發布的鍵鎖住）；只要有一個階段設了建議收入認列比例，
 * 每個階段都要設，合計必須剛好 100%；前置階段不可循環。比例是金流：新增或更動比例＝放寬，需要第二位最高管理者核准。
 * 所有文字用 textContent 寫入（樣板是使用者輸入，不用 innerHTML）；不使用原生對話框。
 */
;(function () {
  if (window.MotrixStageTemplateEditor) return
  var KEY_RE = /^[a-z][a-z0-9_]{0,29}$/
  var BAD = /[<>&"'`\\{}\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]/
  var st = { open: false, busy: false, state: 'idle', msg: '', msgBad: false, keys: [], key: '', isNew: false, label: '', stages: [], locked: {},
             useRatio: false, etag: '', versions: [], preview: null, previewKey: '', previewHash: '', note: '', base: '' }
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
  function today() {
    var t = new Date()
    return t.getFullYear() + '-' + String(t.getMonth() + 1).padStart(2, '0') + '-' + String(t.getDate()).padStart(2, '0')
  }
  function nameProblem(v, max, what) {
    v = String(v == null ? '' : v)
    if (!v.trim()) return what + '不可空白'
    if (v !== v.trim()) return what + '前後不可有空白'
    if (v.length > max) return what + '最多 ' + max + ' 字'
    if (BAD.test(v)) return what + '不可含 < > & 引號、反斜線、花括號或隱形字元'
    if (/^[=+\-@]/.test(v)) return what + '不可以 = + - @ 開頭'
    return ''
  }
  function toBody() {
    return { version: 1, label: st.label, stages: st.stages.map(function (s) {
      var o = { key: s.key, label: s.label, offsetDays: Number(s.offsetDays), durationDays: Number(s.durationDays), dependsOn: s.dependsOn.slice() }
      if (st.useRatio) o.ratioBp = Math.round(Number(s.ratioPct) * 100)
      return o
    }) }
  }
  function curKey() { return st.key + '|' + JSON.stringify(toBody()) }
  function ratioSum() { return st.stages.reduce(function (a, s) { return a + Math.round(Number(s.ratioPct || 0) * 100) }, 0) }
  function intIn(v, lo, hi) { v = Number(v); return Math.floor(v) === v && v >= lo && v <= hi }
  function problems() {
    var out = [], keys = {}, names = {}
    if (!KEY_RE.test(st.key || '')) out.push('樣板鍵必須是小寫英文字母開頭的英數底線（最多 30 字）')
    var p = nameProblem(st.label, 30, '樣板名稱'); if (p) out.push(p)
    if (!st.stages.length) out.push('至少要有一個階段')
    if (st.stages.length > 30) out.push('最多 30 個階段')
    st.stages.forEach(function (s, i) {
      var w = '第 ' + (i + 1) + ' 個階段'
      if (!KEY_RE.test(s.key || '')) out.push(w + '：種類鍵必須是小寫英文字母開頭的英數底線')
      else if (keys[s.key]) out.push(w + '：種類鍵重複 ' + s.key)
      keys[s.key] = true
      p = nameProblem(s.label, 20, w + '名稱'); if (p) out.push(p)
      else if (names[s.label]) out.push(w + '：名稱重複')
      names[s.label] = true
      if (!intIn(s.offsetDays, 0, 730)) out.push(w + '：開始天數要是 0～730 的整數')
      if (!intIn(s.durationDays, 0, 730)) out.push(w + '：工期要是 0～730 的整數')
      if (st.useRatio && !(Number(s.ratioPct) >= 0 && Number(s.ratioPct) <= 100 && Math.round(Number(s.ratioPct) * 100) === Number(s.ratioPct) * 100)) out.push(w + '：比例要是 0～100%（最多兩位小數）')
    })
    if (st.useRatio && st.stages.length && ratioSum() !== 10000) out.push('收入認列比例合計必須剛好 100%（目前 ' + (ratioSum() / 100) + '%）')
    return out
  }

  function setBody(key, body, locked) {
    st.key = key; st.label = body.label || ''
    st.useRatio = (body.stages || []).some(function (s) { return s.ratioBp !== null && s.ratioBp !== undefined })
    st.stages = (body.stages || []).map(function (s) {
      return { key: s.key, label: s.label, offsetDays: s.offsetDays, durationDays: s.durationDays, ratioPct: s.ratioBp === null || s.ratioBp === undefined ? '' : s.ratioBp / 100, dependsOn: (s.dependsOn || []).slice() }
    })
    st.locked = locked || {}
  }
  function loadList() {
    st.busy = true; st.msg = '讀取中…'; render()
    return api('GET', '/api/definitions/case_stage_template').then(function (r) {
      st.keys = ((r.items || r) || []).filter(function (x) { return x.scope === 'company' }).map(function (x) { return x.key })
      st.busy = false; st.msg = ''; render()
      if (st.keys.length && !st.key) return loadOne(st.keys[0])
    }).catch(function (e) { st.busy = false; st.state = 'error'; st.msg = '讀取失敗：' + e.message; st.msgBad = true; render() })
  }
  function loadOne(key) {
    st.busy = true; st.msg = '讀取中…'; render()
    return api('GET', '/api/definitions/case_stage_template/' + encodeURIComponent(key) + '?scope=company').then(function (d) {
      var src = (d.draft && d.draft.body) || (d.latest && d.latest.body) || { stages: [] }
      var pub = {}
      ;((d.latest && d.latest.body && d.latest.body.stages) || []).forEach(function (s) { pub[s.key] = true })
      st.isNew = false; setBody(key, src, pub)
      st.etag = (d.draft && d.draft.etag) || ''
      st.versions = (d.versions || []).filter(function (v) { return v.status === 'published' })
      st.busy = false; st.msg = ''; st.msgBad = false; st.state = 'idle'; st.preview = null; st.previewKey = ''; render()
    }).catch(function (e) { st.busy = false; st.state = 'error'; st.msg = '讀取失敗：' + e.message; st.msgBad = true; render() })
  }
  function newTemplate() {
    st.isNew = true; st.key = ''; st.etag = ''; st.versions = []; st.preview = null; st.previewKey = ''
    setBody('', { label: '', stages: [{ key: 'stage1', label: '', offsetDays: 0, durationDays: 1, dependsOn: [] }] }, {})
    st.state = 'idle'; st.msg = ''; render()
  }
  function changed() { st.preview = null; st.previewKey = ''; st.previewHash = ''; st.state = 'idle'; st.msg = ''; render() }
  function saveDraft() {
    var p = problems()
    if (p.length) { st.msg = p.join('；'); st.msgBad = true; render(); return Promise.reject(new Error(st.msg)) }
    return api('PUT', '/api/definitions/case_stage_template/' + encodeURIComponent(st.key) + '/draft?scope=company', { body: toBody(), base_etag: st.etag || '' })
      .then(function (r) { st.etag = r.etag || st.etag; return r })
  }
  function doPreview() {
    st.busy = true; st.msg = '產生預覽中…'; st.msgBad = false; render()
    var key = curKey()
    return saveDraft().then(function () {
      return api('POST', '/api/quotations/stage-templates/preview', { key: st.key, template: toBody(), baseDate: st.base || today() })
    }).then(function (pv) {
      st.preview = pv
      return api('GET', '/api/def-governance/case_stage_template/' + encodeURIComponent(st.key) + '/impact?scope=company').then(function (im) { st.previewHash = im.previewHash || ''; st.impact = im }, function () { st.previewHash = '' })
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
    var k = st.key
    return loadList().then(function () { return loadOne(k) }).then(function () { st.state = 'published'; st.msg = doneText + ' 已套用過的案件不受影響。'; render() })
  }
  function doPublish() {
    if (st.previewKey !== curKey()) { st.msg = '請先預覽目前這份樣板，再發布。'; st.msgBad = true; render(); return Promise.resolve() }
    st.busy = true; st.msg = '發布中…'; render()
    var body = { note: st.note || '', base_etag: st.etag || undefined }
    if (st.previewHash) body.preview_hash = st.previewHash
    return api('POST', '/api/definitions/case_stage_template/' + encodeURIComponent(st.key) + '/publish?scope=company', body).then(function (r) { return afterWrite(r, '已發布。') })
      .catch(function (e) {
        st.busy = false; st.state = 'error'; st.msgBad = true
        var code = e.body && e.body.code
        st.msg = (code === 'preview_required' || code === 'preview_stale') ? '發布前必須先看過目前這份樣板的預覽，請重新預覽。' : '發布失敗：' + e.message
        render()
      })
  }
  function doRestore(v) {
    st.busy = true; st.msg = '還原中…'; render()
    return api('POST', '/api/definitions/case_stage_template/' + encodeURIComponent(st.key) + '/restore/' + v + '?scope=company', {}).then(function (r) { return afterWrite(r, '已還原到第 ' + v + ' 版。') })
      .catch(function (e) { st.busy = false; st.state = 'error'; st.msg = '還原失敗：' + e.message; st.msgBad = true; render() })
  }
  function move(i, dir) { var j = i + dir; if (j < 0 || j >= st.stages.length) return; var t = st.stages[i]; st.stages[i] = st.stages[j]; st.stages[j] = t; changed() }
  function addStage() {
    var n = st.stages.length + 1
    while (st.stages.some(function (s) { return s.key === 'stage' + n })) n++
    st.stages.push({ key: 'stage' + n, label: '', offsetDays: 0, durationDays: 1, ratioPct: st.useRatio ? 0 : '', dependsOn: [] }); changed()
  }
  function removeStage(i) {
    var k = st.stages[i].key
    st.stages.splice(i, 1)
    st.stages.forEach(function (s) { s.dependsOn = s.dependsOn.filter(function (d) { return d !== k }) })
    changed()
  }
  function num(label, obj, field, w) {
    return el('label', { style: 'font-size:11px' }, [el('span', { text: label + ' ' }), el('input', { type: 'number', value: String(obj[field]), style: 'width:' + w + 'px;font-size:12px', oninput: function (ev) { obj[field] = ev.target.value; st.preview = null; st.previewKey = ''; st.state = 'idle' } })])
  }

  function render() {
    if (!root) return
    while (root.firstChild) root.removeChild(root.firstChild)
    root.style.display = st.open ? 'flex' : 'none'
    root.setAttribute('data-state', st.state)
    if (!st.open) return
    var panel = el('div', { role: 'dialog', 'aria-modal': 'true', 'data-testid': 'stage-template-editor', style: 'margin:auto;background:var(--surface,#fff);border-radius:12px;width:100%;max-width:760px;max-height:88vh;overflow:auto;padding:14px 18px;box-shadow:var(--shadow-popover,0 8px 30px rgba(0,0,0,.2))' })
    panel.appendChild(el('div', { style: 'display:flex;align-items:center;gap:10px;margin-bottom:8px' }, [
      el('span', { text: '案件階段樣板', style: 'font-size:14px;font-weight:700;flex:1' }),
      el('button', { type: 'button', text: '×', 'aria-label': '關閉', onclick: function () { st.open = false; render() }, style: 'width:28px;height:28px;border:none;border-radius:5px;cursor:pointer' })
    ]))
    panel.appendChild(el('div', { text: '樣板只是新增案件階段時的預填：套用＝複製成該案自己的階段，之後樣板改了不影響已套用的案件。階段種類鍵建立後不能改。', style: 'font-size:12px;color:var(--text-dim,#888);margin-bottom:8px' }))
    var sel = el('select', { 'data-testid': 'st-ed-select', style: 'font-size:12px', onchange: function (ev) { if (ev.target.value === '__new') newTemplate(); else loadOne(ev.target.value) } },
      st.keys.map(function (k) { return el('option', { value: k, text: k, selected: (!st.isNew && k === st.key) ? 'selected' : null }) }).concat([el('option', { value: '__new', text: '＋ 新增樣板', selected: st.isNew ? 'selected' : null })]))
    panel.appendChild(sel)
    if (st.isNew || st.key) {
      panel.appendChild(el('div', { style: 'display:flex;gap:6px;margin:8px 0;flex-wrap:wrap' }, [
        st.isNew ? el('input', { type: 'text', value: st.key, placeholder: '樣板鍵（英文小寫）', maxlength: '30', 'data-testid': 'st-ed-key', style: 'font-size:12px;width:150px', oninput: function (ev) { st.key = ev.target.value; st.preview = null; st.previewKey = '' } })
                    : el('span', { text: st.key, style: 'font-size:12px;align-self:center' }),
        el('input', { type: 'text', value: st.label, placeholder: '樣板名稱', maxlength: '30', 'data-testid': 'st-ed-label', style: 'font-size:12px;flex:1;min-width:160px', oninput: function (ev) { st.label = ev.target.value; st.preview = null; st.previewKey = '' } }),
        el('label', { style: 'font-size:12px;align-self:center' }, [el('input', { type: 'checkbox', 'data-testid': 'st-ed-ratio', checked: st.useRatio ? 'checked' : null, onchange: function (ev) { st.useRatio = ev.target.checked; st.stages.forEach(function (s) { s.ratioPct = st.useRatio ? (s.ratioPct === '' ? 0 : s.ratioPct) : '' }); changed() } }), el('span', { text: ' 預設收入認列比例（合計 100%）' })])
      ]))
      st.stages.forEach(function (s, i) {
        var others = st.stages.filter(function (o) { return o.key !== s.key })
        panel.appendChild(el('div', { 'data-stage-row': s.key, style: 'display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin:4px 0;padding:4px 0;border-bottom:1px solid var(--border-light,#eee)' }, [
          el('input', { type: 'text', value: s.key, maxlength: '30', disabled: st.locked[s.key] ? 'disabled' : null, title: st.locked[s.key] ? '已發布，種類鍵不能改' : '種類鍵', style: 'width:96px;font-size:12px', oninput: function (ev) { var old = s.key; s.key = ev.target.value; st.stages.forEach(function (o) { o.dependsOn = o.dependsOn.map(function (d) { return d === old ? s.key : d }) }); st.preview = null; st.previewKey = '' } }),
          el('input', { type: 'text', value: s.label, placeholder: '階段名稱', maxlength: '20', style: 'flex:1;min-width:110px;font-size:12px', oninput: function (ev) { s.label = ev.target.value; st.preview = null; st.previewKey = '' } }),
          num('開始 +天', s, 'offsetDays', 56), num('工期 天', s, 'durationDays', 56),
          st.useRatio ? num('比例 %', s, 'ratioPct', 64) : null,
          others.length ? el('span', { style: 'font-size:11px' }, [el('span', { text: '前置：' })].concat(others.map(function (o) {
            return el('label', { style: 'margin-right:4px' }, [el('input', { type: 'checkbox', checked: s.dependsOn.indexOf(o.key) >= 0 ? 'checked' : null, onchange: function (ev) { s.dependsOn = s.dependsOn.filter(function (d) { return d !== o.key }); if (ev.target.checked) s.dependsOn.push(o.key); changed() } }), el('span', { text: o.label || o.key })])
          }))) : null,
          el('button', { type: 'button', text: '↑', onclick: function () { move(i, -1) } }), el('button', { type: 'button', text: '↓', onclick: function () { move(i, 1) } }),
          el('button', { type: 'button', text: '移除', onclick: function () { removeStage(i) } })
        ]))
      })
      if (st.useRatio) panel.appendChild(el('div', { 'data-testid': 'st-ed-sum', text: '比例合計：' + (ratioSum() / 100) + '%', style: 'font-size:12px;margin-top:4px;color:' + (ratioSum() === 10000 ? 'inherit' : '#b91c1c') }))
      panel.appendChild(el('div', { style: 'display:flex;gap:6px;margin-top:8px;align-items:center' }, [
        el('button', { type: 'button', class: 'btn btn-sm', text: '＋ 新增階段', onclick: addStage }),
        el('label', { style: 'font-size:12px' }, [el('span', { text: '預覽基準日 ' }), el('input', { type: 'date', value: st.base || today(), style: 'font-size:12px', onchange: function (ev) { st.base = ev.target.value; changed() } })]),
        el('button', { type: 'button', class: 'btn btn-sm', 'data-testid': 'st-ed-preview', text: '預覽', disabled: st.busy ? 'disabled' : null, onclick: doPreview })
      ]))
      if (st.preview) {
        panel.appendChild(el('div', { 'data-testid': 'st-ed-preview-box', style: 'margin-top:8px;font-size:12px' }, (st.preview.stages || []).map(function (s) {
          return el('div', { text: s.label + '　' + s.startDate + ' → ' + s.dueDate + (s.ratioBp === null || s.ratioBp === undefined ? '' : '　' + (s.ratioBp / 100) + '%') })
        })))
        var im = st.impact || {}
        if (im.classification || im.kind) panel.appendChild(el('div', { text: '這次變更的性質：' + (({ loosen: '放寬（需第二位最高管理者核准）', tighten: '收緊', neutral: '中性' })[im.classification] || im.classification || ''), style: 'font-size:12px;margin-top:4px' }))
        ;(im.reasons || []).forEach(function (r) { panel.appendChild(el('div', { text: '・' + (typeof r === 'string' ? r : (r.message || r.text || '')), style: 'font-size:11px;color:#b45309' })) })
      }
      panel.appendChild(el('div', { style: 'display:flex;gap:6px;margin-top:8px' }, [
        el('input', { type: 'text', placeholder: '備註（選填）', value: st.note, style: 'flex:1;font-size:12px', oninput: function (ev) { st.note = ev.target.value } }),
        el('button', { type: 'button', class: 'btn btn-primary btn-sm', 'data-testid': 'st-ed-publish', text: '發布', disabled: (st.busy || st.previewKey !== curKey()) ? 'disabled' : null, onclick: doPublish })
      ]))
      if (st.versions.length) {
        panel.appendChild(el('div', { style: 'margin-top:8px;font-size:12px' }, [el('span', { text: '還原到：' })].concat(st.versions.slice().reverse().slice(0, 6).map(function (v) {
          return el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '第 ' + v.version + ' 版', onclick: function () { doRestore(v.version) } })
        }))))
      }
    }
    if (st.msg) panel.appendChild(el('div', { 'data-testid': 'st-ed-msg', text: st.msg, style: 'margin-top:6px;font-size:12px;color:' + (st.msgBad ? '#b91c1c' : 'inherit') }))
    root.appendChild(panel)
  }

  function boot() {
    root = el('div', { id: 'stage-template-editor-root', style: 'display:none;position:fixed;inset:0;z-index:420;background:var(--overlay-backdrop,rgba(0,0,0,.4));padding:20px' })
    root.addEventListener('click', function (ev) { if (ev.target === root) { st.open = false; render() } })
    document.body.appendChild(root)
  }
  window.MotrixStageTemplateEditor = {
    _state: st, _toBody: toBody, _problems: problems, _pendingText: pendingText, _publish: doPublish, _preview: doPreview, _restore: doRestore, _init: function (b, locked) { setBody('x', b, locked) },
    open: function () { if (!root) boot(); st.open = true; render(); return loadList() }
  }
})()
