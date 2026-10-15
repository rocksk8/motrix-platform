/* notify-action-editor.js — 額外通知編輯器（BP-4 S5；設計 docs/platform/plans/BP4-STORAGE-NOTIFY-DESIGN.md §4、§5）
 *
 * 管理者宣告「當某件事發生時，額外通知指定的人，內容是…」。只能挑系統已登記的事件、固定目錄裡的收件人（角色、群組、現有帳號、事件裡的人）；
 * 不能關掉或改寫任何內建通知；通知內容只能用純文字與該事件允許的占位符。畫面一律白話：不顯示代號、列舉值、單號鍵。
 *
 * 載入方式：approval-settings.html 底部的小載入器——只有最高管理者、且 MotrixPublicFlags 讀到 builder_notify.enabled 開啟時，
 * 才依序載入 def-governance.js 與本檔；旗標關／不是最高管理者 ⇒ 本檔根本不會被載入（唯一的請求是那一次旗標讀取）。
 * 載入後再問 GET /api/notify-actions/status（治理沒開也回 enabled:false ⇒ 什麼都不畫）。
 *
 * 流程：清單（名稱、事件、狀態）→ 新增／編輯（事件、條件、收件人挑選器、通道、節流、內容）→「用建議內容填入」一鍵帶入安全預設 →
 * 「試跑看看」（POST /api/notify-actions/{key}/preview：唯讀；顯示會通知約幾個人、每天大約幾則、逐角色看到的文字、放寬警告）→
 * 檢查並發布（存草稿 → 後端檢查 → MotrixDefGovernance.review 發布前影響預覽 → 發布）。放寬（更多人／更多情況收到通知）→ 後端回 pending:true，
 * 面板如實說「待第二位最高管理者核准」；收緊（停用、縮小）立即生效。「版本與還原」開治理面板（回到舊版也走同一條管線）。
 * 不用 innerHTML、不用原生對話框；所有文字用 textContent 寫入。
 * e2e 等待點：#notify-action-editor-root 的 data-state（idle／checked／pending／published／error）與 data-busy（'0'／'1'）。
 */
;(function () {
  if (window.MotrixNotifyActionEditor) return
  var KIND = 'notify_action'
  var BASE = '/api/definitions/' + KIND
  var BAD = /[<>&"'`\\\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]/
  var INVIS = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}\p{Co}\p{Cs}ᅟᅠㅤﾠ⠀᠎͏؜឴឵­⁠]/u
  var ALLOWED = /^[一-鿿㐀-䶿　-〿A-Za-z0-9 .,:;!?()\[\]\-_~{}]*$/
  var URLISH = /https?|:\/\/|www\.|[A-Za-z0-9_]+\.[A-Za-z0-9_]{2,}|\//i
  var RESERVED = ['正本', '副本', '已核准', '已核可', '核准', '核可', '簽核完成', '签核完成', '已付款', '已收款', '已簽回', '已簽收', '作廢', '作废',
    '已通過', '通過', '已通过', '通过', '批准', '審核通過', '审核通过', '簽核通過', '签核通过', '已簽核', '已签核', '已批', '已生效']
  var RESERVED_EN = /(?<![a-z])(?:approve|approved|passed|paid|original|void|signed|final)(?![a-z])/
  var PH = /\{([^{}]{1,12})\}/g
  var LIMIT = { label: 30, title: 60, body: 400 }
  var DEFAULT_THROTTLE = { dedupe: 60, perDay: 5 }

  var st = { open: false, busy: false, state: 'idle', msg: '', msgBad: false, cat: null, list: [], f: null, preview: null, previewRole: 'admin', etag: '', note: '' }
  var root = null

  function session() { try { return JSON.parse(localStorage.getItem('motrix_session') || 'null') || {} } catch (e) { return {} } }
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
  function msgOf(j) {                                      // 只顯示白話原因，不顯示欄位路徑（路徑是內部代號）
    var d = j && (j.detail !== undefined ? j.detail : j)
    if (d && d.problems) return d.problems.map(function (p) { return p.message }).join('；')
    if (j && j.problems && j.problems.length) return j.problems.map(function (p) { return p.message }).join('；')
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
  function dim(text) { return el('div', { text: text, style: 'font-size:11px;color:var(--text-dim,#888);margin-top:3px' }) }
  function eventOf(name) { return ((st.cat && st.cat.events) || []).filter(function (e) { return e.event === name })[0] || null }
  function curEvent() { return st.f ? eventOf(st.f.event) : null }
  function skeleton(s) { return String(s).normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '') }

  // ── 白話名稱 ────────────────────────────────────────────────────────────────
  function pickerLabel(list, v) { var m = (list || []).filter(function (x) { return x.value === v })[0]; return m ? m.label : '' }
  function whoText(r) {
    var p = (st.cat && st.cat.picker) || {}
    if (r.kind === 'requester' || r.kind === 'owner') return pickerLabel(p.people, r.kind) || '事件裡的人'
    if (r.kind === 'role') return '角色「' + (pickerLabel(p.roles, r.value) || '未知') + '」的所有人'
    if (r.kind === 'group') return '群組「' + (pickerLabel(p.groups, r.value) || '未知') + '」'
    if (r.kind === 'user') { var u = (p.users || []).filter(function (x) { return x.username === r.value })[0]; return '指定人員：' + (u ? u.displayName : '（帳號已不存在）') }
    return '未知的收件人'
  }

  // ── 表單 ↔ 定義 ─────────────────────────────────────────────────────────────
  function newKey() { return 'na_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5) }
  function blank() {
    return { key: newKey(), isNew: true, label: '', enabled: true, event: '', when: [], email: false, recipients: [], title: '', body: '',
             dedupe: DEFAULT_THROTTLE.dedupe, perDay: DEFAULT_THROTTLE.perDay }
  }
  function splitValues(t) { return String(t || '').split(/[、,，\n]/).map(function (x) { return x.trim() }).filter(Boolean) }
  function toBody(f) {
    return {
      version: 1, label: (f.label || '').trim(), enabled: !!f.enabled, event: f.event,
      when: f.when.filter(function (c) { return c.field }).map(function (c) { return { field: c.field, in: splitValues(c.values) } }),
      channels: f.email ? ['in_app', 'email'] : ['in_app'],
      recipients: f.recipients.map(function (r) { var o = { kind: r.kind }; if (r.value !== undefined && r.value !== null && r.value !== '') o.value = r.value; return o }),
      template: { title: (f.title || '').trim(), body: (f.body || '').trim() },
      throttle: { dedupeMinutes: Number(f.dedupe), maxPerRecipientPerDay: Number(f.perDay) }
    }
  }
  function fromBody(key, b) {
    b = b || {}
    var t = b.template || {}, th = b.throttle || {}
    return { key: key, isNew: false, label: b.label || '', enabled: b.enabled !== false, event: b.event || '',
             when: (b.when || []).map(function (c) { return { field: c.field, values: (c.in || []).join('、') } }),
             email: (b.channels || []).indexOf('email') >= 0, recipients: (b.recipients || []).map(function (r) { return { kind: r.kind, value: r.value } }),
             title: t.title || '', body: t.body || '', dedupe: th.dedupeMinutes || DEFAULT_THROTTLE.dedupe, perDay: th.maxPerRecipientPerDay || DEFAULT_THROTTLE.perDay }
  }

  // ── 前端檢查（與後端 helpers/notify_actions.definition_problems 同一套規則；後端仍是權威）────────────────
  function textProblem(v, limit, allowed) {
    v = String(v || '')
    if (!v.trim()) return '不可空白'
    if (v.length > limit) return '最多 ' + limit + ' 字'
    if (INVIS.test(v)) return '不可含控制、隱形、雙向或私用字元'
    if (BAD.test(v)) return '不可含標記字元（< > & 引號 反斜線）'
    if (!ALLOWED.test(v.normalize('NFKC'))) return '只能使用中文、英數字與常用標點（不接受外觀相似的其他文字）'
    if (URLISH.test(v.replace(PH, '').normalize('NFKC'))) return '不可含網址或連結（含斜線、網域寫法）'
    var m, names = []
    PH.lastIndex = 0
    while ((m = PH.exec(v))) names.push(m[1])
    for (var i = 0; i < names.length; i++) if (allowed.indexOf(names[i]) < 0) return '不認得的占位符 {' + names[i] + '}'
    var rest = v.replace(PH, '')
    if (rest.indexOf('{') >= 0 || rest.indexOf('}') >= 0) return '大括號只能用在占位符'
    var sk = skeleton(rest)
    for (var k = 0; k < RESERVED.length; k++) if (sk.indexOf(skeleton(RESERVED[k])) >= 0) return '不可含官方狀態字樣：' + RESERVED[k]
    var en = RESERVED_EN.exec(rest.normalize('NFKC').toLowerCase()); if (en) return '不可含官方狀態字樣：' + en[0]
    return ''
  }
  function allowedPh(ev) { return ev ? ev.placeholders.filter(function (p) { return (ev.internal || []).indexOf(p) < 0 }) : [] }
  function problems(f) {
    var out = [], ev = eventOf(f.event)
    var p = textProblem(f.label, LIMIT.label, []); if (p) out.push('名稱：' + p)
    if (!ev) { out.push('請先選擇「什麼事發生時要通知」'); return out }
    if (f.when.length > 3) out.push('條件最多 3 條')
    var seen = {}
    f.when.forEach(function (c) {
      if (!c.field) { out.push('有一條條件還沒選欄位'); return }
      if (seen[c.field]) out.push('同一個欄位只能設一條條件（' + c.field + '）')
      seen[c.field] = 1
      var vals = splitValues(c.values)
      if (!vals.length || vals.length > 10 || vals.some(function (x) { return x.length > 40 })) out.push('條件「' + c.field + '」要填 1～10 個值（每個最多 40 字）')
    })
    if (!f.recipients.length) out.push('請至少加入一位要通知的對象')
    if (f.recipients.length > 8) out.push('通知對象最多 8 項')
    p = textProblem(f.title, LIMIT.title, allowedPh(ev)); if (p) out.push('標題：' + p)
    p = textProblem(f.body, LIMIT.body, allowedPh(ev)); if (p) out.push('內文：' + p)
    var d = Number(f.dedupe), n = Number(f.perDay)
    if (!(Number.isInteger(d) && d >= 1 && d <= 1440)) out.push('「同一件事幾分鐘內不重複通知」要填 1～1440 的整數')
    if (!(Number.isInteger(n) && n >= 1 && n <= 20)) out.push('「每人每天最多幾則」要填 1～20 的整數')
    return out
  }

  // ── 讀取 ────────────────────────────────────────────────────────────────────
  function setMsg(text, bad, state) { st.msg = text; st.msgBad = !!bad; if (state) st.state = state }
  function loadList() {
    st.busy = true; setMsg('讀取中…', false); render()
    return api('GET', BASE).then(function (rows) {
      rows = Array.isArray(rows) ? rows : []
      return Promise.all(rows.map(function (r) {
        return api('GET', BASE + '/' + encodeURIComponent(r.key) + '?scope=company').then(function (d) {
          var b = (d.draft && d.draft.body) || (d.latest && d.latest.body) || {}
          var live = d.latest && d.latest.body
          return { key: r.key, label: b.label || '（未命名）', event: b.event || '', enabled: live ? live.enabled !== false : false, published: !!live,
                   hasDraft: !!(d.draft && d.draft.body), draftBody: d.draft && d.draft.body, etag: (d.draft && d.draft.etag) || '', liveBody: live || null }
        }).catch(function () { return { key: r.key, label: '（讀取失敗）', event: '', enabled: false, published: false, hasDraft: false } })
      }))
    }).then(function (items) {
      st.list = items; st.busy = false; setMsg('', false, 'idle'); render()
    }).catch(function (e) {
      if (e.status === 404 || e.status === 400) { st.list = []; st.busy = false; setMsg('', false, 'idle'); render(); return }
      st.busy = false; setMsg('讀取失敗：' + e.message, true, 'error'); render()
    })
  }
  function statusText(it) {
    if (!it.published) return '還沒發布（只有草稿）'
    if (!it.enabled) return '已停用'
    return it.hasDraft ? '使用中（另有未發布的修改）' : '使用中'
  }

  // ── 編輯動作 ────────────────────────────────────────────────────────────────
  function touch() { st.preview = null; if (st.state !== 'error') st.state = 'idle' }
  function startNew() { st.f = blank(); st.etag = ''; st.preview = null; setMsg('', false, 'idle'); render() }
  function startEdit(it) {
    st.f = fromBody(it.key, it.draftBody || it.liveBody); st.etag = it.etag || ''; st.preview = null; setMsg('', false, 'idle'); render()
  }
  function setEvent(name) {
    var f = st.f, ev = eventOf(name); if (!ev) return
    var before = f.event
    f.event = name
    var dropped = []
    f.recipients = f.recipients.filter(function (r) {
      if ((r.kind === 'requester' || r.kind === 'owner') && ev.people.indexOf(r.kind) < 0) { dropped.push(whoText(r)); return false }
      return true
    })
    f.when = f.when.filter(function (c) { return ev.filterable.indexOf(c.field) >= 0 })
    var keep = allowedPh(ev)
    ;['title', 'body'].forEach(function (k) {                            // 換事件後，內文裡這個事件沒有的占位符會失效 ⇒ 提醒（不偷偷改字）
      var bad = []; String(f[k] || '').replace(PH, function (m, n) { if (keep.indexOf(n) < 0) bad.push(n); return m })
      if (bad.length) dropped.push((k === 'title' ? '標題' : '內文') + '裡的 {' + bad.join('}{') + '} 這個事件沒有')
    })
    touch()
    if (before && dropped.length) setMsg('換了事件，請留意：' + dropped.join('；') + '。', false)
    render()
  }
  function applySuggest() {
    var f = st.f, ev = curEvent(); if (!ev || !ev.suggest) return
    var s = ev.suggest
    f.label = s.label; f.recipients = s.recipients.map(function (r) { return { kind: r.kind, value: r.value } }); f.title = s.title; f.body = s.body
    f.when = []; f.email = false; f.enabled = true; f.dedupe = DEFAULT_THROTTLE.dedupe; f.perDay = DEFAULT_THROTTLE.perDay
    touch(); setMsg('已用建議內容填入，請看過再試跑。', false); render()
  }
  function addRecipient(code) {
    if (!code || !st.f) return
    var i = code.indexOf(':'), kind = code.slice(0, i), value = code.slice(i + 1)
    var r = { kind: kind }; if (value) r.value = value
    if (st.f.recipients.some(function (x) { return x.kind === r.kind && (x.value || '') === (r.value || '') })) return
    if (st.f.recipients.length >= 8) { setMsg('通知對象最多 8 項。', true); render(); return }
    st.f.recipients.push(r); touch(); render()
  }
  function insertAt(input, key, ph) {
    var v = input.value, a = input.selectionStart == null ? v.length : input.selectionStart, b = input.selectionEnd == null ? a : input.selectionEnd
    st.f[key] = v.slice(0, a) + ph + v.slice(b); touch(); render()
    var again = root && root.querySelector && root.querySelector('[data-path="' + key + '"]')
    if (again) { again.focus(); try { again.setSelectionRange(a + ph.length, a + ph.length) } catch (e) { /* 忽略 */ } }
  }

  // ── 試跑與發布 ──────────────────────────────────────────────────────────────
  function runPreview() {
    var p = problems(st.f)
    if (p.length) { setMsg(p.join('；'), true, 'error'); render(); return Promise.resolve() }
    st.busy = true; setMsg('試跑中…', false); render()
    return api('POST', '/api/notify-actions/' + encodeURIComponent(st.f.key) + '/preview', { template: toBody(st.f) }).then(function (d) {
      st.preview = d; st.busy = false; setMsg('', false, 'checked'); render()
    }).catch(function (e) { st.busy = false; setMsg('試跑失敗：' + e.message, true, 'error'); render() })
  }
  function pendingText(d) {
    var reasons = []
    ;(d.reasons || []).forEach(function (r) { var t = typeof r === 'string' ? r : ((r && (r.message || r.text)) || ''); if (t && reasons.indexOf(t) < 0) reasons.push(t) })
    var at = d.effectiveAt ? String(d.effectiveAt).replace('T', ' ').slice(0, 16) : ''
    return '已送出發布，待第二位最高管理者核准；核准前不會生效' + (at ? '，生效時間 ' + at + ' 之後' : '') + (reasons.length ? '。原因：' + reasons.join('；') : '') + '。'
  }
  function doPublish() {
    var f = st.f
    var p = problems(f)
    if (p.length) { setMsg(p.join('；'), true, 'error'); render(); return Promise.resolve() }
    st.busy = true; setMsg('檢查中…', false); render()
    var body = toBody(f), key = encodeURIComponent(f.key)
    return api('PUT', BASE + '/' + key + '/draft?scope=company', { body: body, base_etag: st.etag || '' }).then(function (r) {
      st.etag = r.etag || st.etag
      return api('POST', '/api/notify-actions/' + key + '/preview', { template: body })
    }).then(function (d) {
      st.preview = d; setMsg('檢查通過，請確認影響後發布。', false, 'checked'); render()
      var G = window.MotrixDefGovernance
      if (!G || !G.review) return { noGovernance: true }
      return G.review({ kind: KIND, key: f.key, scope: 'company', title: '發布前影響預覽：額外通知「' + (f.label || '') + '」' })
    }).then(function (hash) {
      if (hash && hash.noGovernance === true) hash = ''
      else if (!hash) hash = null
      if (hash === null) { st.busy = false; setMsg('已取消發布（草稿已存）。', false, 'idle'); render(); return }
      setMsg('發布中…', false); render()
      var b = { note: st.note || '', base_etag: st.etag || undefined }
      if (hash) b.preview_hash = hash
      return api('POST', BASE + '/' + key + '/publish?scope=company', b).then(function (r) {
        st.busy = false
        if (r && r.pending === true) { st.state = 'pending'; setMsg(pendingText(r), false); render(); return }
        st.f = null; st.preview = null
        return loadList().then(function () { setMsg('已發布。之後發生這件事時，會依這份設定額外通知。', false, 'published'); render() })
      })
    }).catch(function (e) {
      var code = e.body && e.body.code
      st.busy = false
      setMsg(code === 'preview_required' || code === 'preview_stale' ? '發布前必須先看過目前這份設定的影響預覽，請重新發布：' + e.message : '失敗：' + e.message, true, 'error'); render()
    })
  }
  function disableNow(it) {                                              // 一鍵停用＝收緊，立即生效（走同一條發布管線）
    var f = fromBody(it.key, it.liveBody || it.draftBody); f.enabled = false
    st.f = f; st.etag = it.etag || ''; return doPublish()
  }

  // ── 畫面 ────────────────────────────────────────────────────────────────────
  function field(label, node, hint) {
    return el('div', { style: 'margin:8px 0' }, [el('div', { text: label, style: 'font-size:12px;font-weight:600;margin-bottom:2px' }), node, hint ? dim(hint) : null])
  }
  function select(opts, value, onchange, extra) {
    var s = el('select', Object.assign({ style: 'font-size:12px;max-width:100%', onchange: function (ev) { onchange(ev.target.value) } }, extra || {}),
      opts.map(function (o) { return el('option', { value: o.value, text: o.label, selected: o.value === value ? 'selected' : null }) }))
    return s
  }
  function recipientOptions(ev) {
    var p = st.cat.picker || {}, out = [{ value: '', label: '請選擇要加入的對象…' }]
    ;(p.people || []).forEach(function (x) { if (ev.people.indexOf(x.value) >= 0) out.push({ value: x.value + ':', label: '事件裡的人：' + x.label }) })
    ;(p.roles || []).forEach(function (x) { out.push({ value: 'role:' + x.value, label: '角色：' + x.label + '（所有人）' }) })
    ;(p.groups || []).forEach(function (x) { out.push({ value: 'group:' + x.value, label: '群組：' + x.label }) })
    ;(p.users || []).forEach(function (x) { out.push({ value: 'user:' + x.username, label: '指定人員：' + x.displayName }) })
    return out
  }
  function listView() {
    var box = el('div', { 'data-role': 'list' })
    if (!st.list.length) box.appendChild(el('div', { text: '還沒有額外通知。按「新增通知」建立第一個。', style: 'font-size:12px;color:var(--text-dim,#888);margin:6px 0' }))
    st.list.forEach(function (it) {
      var ev = eventOf(it.event)
      box.appendChild(el('div', { style: 'display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:6px 0;border-bottom:1px solid var(--border-light,#eee)', 'data-role': 'item' }, [
        el('div', { style: 'flex:1;min-width:200px' }, [
          el('div', { text: it.label, style: 'font-size:13px;font-weight:600' }),
          el('div', { text: (ev ? '當「' + ev.label + '」時通知　' : '') + '｜' + statusText(it), style: 'font-size:11px;color:var(--text-dim,#888)' })]),
        el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-role': 'edit', text: '編輯', disabled: st.busy ? 'disabled' : null, onclick: function () { startEdit(it) } }),
        it.published && it.enabled ? el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-role': 'disable', text: '停用', disabled: st.busy ? 'disabled' : null, onclick: function () { disableNow(it) } }) : null,
        el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '版本與還原', onclick: function () { if (window.MotrixDefGovernance) window.MotrixDefGovernance.open({ kind: KIND, key: it.key, scope: 'company', title: '額外通知「' + it.label + '」的版本與還原', onRestored: loadList }) } })
      ]))
    })
    box.appendChild(el('div', { style: 'margin-top:8px' }, [el('button', { type: 'button', class: 'btn btn-primary btn-sm', 'data-role': 'new', text: '新增通知', disabled: st.busy ? 'disabled' : null, onclick: startNew })]))
    return box
  }
  function previewView() {
    var d = st.preview
    var box = el('div', { 'data-role': 'preview', style: 'margin-top:10px;padding:8px;border:1px dashed var(--border,#bbb);border-radius:8px' })
    box.appendChild(el('div', { text: '試跑結果（用範例資料，不會真的寄出）', style: 'font-size:12px;font-weight:600' }))
    var c = d.classification || {}
    if (c['class'] === 'loosen') {
      box.appendChild(el('div', { 'data-role': 'loosen', style: 'margin-top:6px;padding:8px;border:1px solid #b91c1c;background:#fef2f2;color:#7f1d1d;border-radius:6px;font-size:12px' }, [
        el('div', { text: '這次變更屬於「放寬」：會讓更多人、或在更多情況下收到額外通知。', style: 'font-weight:700' }),
        el('div', { text: '需要第二位最高管理者核准，核准前不會生效。影響範圍：被通知的人會多收到這個事件的相關訊息（不影響原本的內建通知）。', style: 'margin-top:2px' }),
        el('ul', { style: 'margin:4px 0 0 16px;padding:0' }, (c.reasons || []).map(function (r) { return el('li', { text: r }) }))]))
    } else {
      box.appendChild(el('div', { 'data-role': 'tighten', text: c['class'] === 'tighten' ? '這次變更屬於「收緊」（停用或縮小範圍），發布後立即生效。' : '這次變更不會讓更多人收到通知，發布後立即生效。', style: 'margin-top:6px;font-size:12px;color:#166534' }))
    }
    var people = d.knownRecipientCount + ' 人' + (d.eventDependentRecipients ? '（另有 ' + d.eventDependentRecipients + ' 項要看實際發生的事才知道是誰）' : '')
    box.appendChild(el('div', { 'data-role': 'impact', style: 'margin-top:6px;font-size:13px;font-weight:600',
      text: '預計會通知約 ' + people + '；過去 30 天這個設定平均每天寄出約 ' + ((d.estimate && d.estimate.perDay) || 0) + ' 則（新設定是 0）。' }))
    box.appendChild(el('div', { 'data-role': 'matches', style: 'margin-top:4px;font-size:12px',
      text: (d.matches ? '用範例資料：會觸發通知。' : '用範例資料：不會觸發（條件不符）。') + (d.conditions || []).map(function (x) { return '　' + x.field + '＝' + x.value + (x.ok ? '（符合）' : '（不符）') }).join('') }))
    box.appendChild(el('ul', { 'data-role': 'recipients', style: 'margin:4px 0 0 16px;padding:0;font-size:12px' }, (d.recipients || []).map(function (r) {
      return el('li', { text: whoText(r) + '：' + (r.count === null || r.count === undefined ? '依實際發生的事而定' : r.count + ' 人') })
    })))
    var roles = d.renders || []
    box.appendChild(el('div', { text: '不同的人收到的文字（沒有權限看金額的人，金額會顯示「（略）」）：', style: 'font-size:11px;color:var(--text-dim,#888);margin-top:6px' }))
    box.appendChild(el('div', { style: 'display:flex;gap:4px;flex-wrap:wrap;margin:4px 0', 'data-role': 'role-tabs' }, roles.map(function (r) {
      return el('button', { type: 'button', class: 'btn btn-sm ' + (r.role === st.previewRole ? 'btn-primary' : 'btn-ghost'), text: r.roleName, 'data-render-role': r.role,
                            onclick: function () { st.previewRole = r.role; render() } })
    })))
    var shown = roles.filter(function (r) { return r.role === st.previewRole })[0] || roles[0]
    if (shown) box.appendChild(el('div', { style: 'padding:6px 8px;background:var(--bg-hover,#f3f4f6);border-radius:6px' }, [
      el('div', { text: shown.title, style: 'font-size:13px;font-weight:700', 'data-role': 'pv-title' }), el('div', { text: shown.body, style: 'font-size:12px;margin-top:2px', 'data-role': 'pv-body' })]))
    ;(d.warnings || []).forEach(function (w) { box.appendChild(dim(w)) })
    if (d.readable) box.appendChild(dim(d.readable))
    return box
  }
  function formView() {
    var f = st.f, ev = curEvent()
    var panel = el('div', { 'data-role': 'form', style: 'margin-top:6px;padding:12px;border:1px solid var(--border,#ccc);border-radius:8px' })
    panel.appendChild(el('div', { text: f.isNew ? '新增額外通知' : '編輯額外通知', style: 'font-size:13px;font-weight:600' }))
    var evSel = select([{ value: '', label: '請選擇…' }].concat(st.cat.events.map(function (e) { return { value: e.event, label: e.label } })), f.event, setEvent, { 'data-role': 'event' })
    panel.appendChild(field('什麼事發生時要通知？', evSel, ev ? ev.desc : '只能選系統已經準備好的事件。'))
    if (!ev) return panel
    panel.appendChild(el('div', { style: 'margin:4px 0' }, [el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-role': 'suggest', text: '用建議內容填入（名稱、對象、文字一次帶入）', onclick: applySuggest })]))
    panel.appendChild(field('這個通知叫什麼名字？（只給管理者看）', el('input', { type: 'text', 'data-path': 'label', value: f.label, maxlength: String(LIMIT.label + 10), style: 'width:100%;font-size:12px', oninput: function (e) { f.label = e.target.value; touch() } })))
    // 條件
    var condHost = el('div', { 'data-role': 'conditions' })
    f.when.forEach(function (c, i) {
      condHost.appendChild(el('div', { style: 'display:flex;gap:4px;align-items:center;flex-wrap:wrap;margin:3px 0' }, [
        select([{ value: '', label: '選擇欄位…' }].concat(ev.filterable.map(function (n) { return { value: n, label: n } })), c.field, function (v) { c.field = v; touch(); render() }),
        el('span', { text: '是', style: 'font-size:12px' }),
        el('input', { type: 'text', value: c.values, placeholder: '值（多個用頓號分隔）', style: 'flex:1;min-width:160px;font-size:12px', oninput: function (e) { c.values = e.target.value; touch() } }),
        el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '移除', onclick: function () { f.when.splice(i, 1); touch(); render() } })]))
    })
    if (ev.filterable.length && f.when.length < 3) condHost.appendChild(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-role': 'add-cond', text: '＋ 加一條條件', onclick: function () { f.when.push({ field: '', values: '' }); touch(); render() } }))
    panel.appendChild(field('只在符合這些情況時才通知（可以不設，最多 3 條）', condHost, ev.filterable.length ? '例如：' + ev.filterable[0] + ' 是「' + (ev.sample[ev.placeholders.length ? '' : ''] || '') + '」'.replace('「」', '') : '這個事件沒有可設的條件。'))
    // 收件人
    var chips = el('div', { 'data-role': 'chips', style: 'display:flex;gap:4px;flex-wrap:wrap;margin:3px 0' }, f.recipients.map(function (r, i) {
      return el('span', { 'data-role': 'chip', style: 'display:inline-flex;gap:4px;align-items:center;padding:2px 8px;border:1px solid var(--border,#bbb);border-radius:10px;font-size:12px' }, [
        el('span', { text: whoText(r) }), el('button', { type: 'button', text: '✕', 'aria-label': '移除', style: 'border:none;background:none;cursor:pointer', onclick: function () { f.recipients.splice(i, 1); touch(); render() } })])
    }))
    var addSel = select(recipientOptions(ev), '', function (v) { addRecipient(v) }, { 'data-role': 'add-recipient' })
    panel.appendChild(field('要通知誰？（最多 8 項）', el('div', {}, [chips, addSel]), '只能從清單挑選；不接受電子郵件位址。收件人必須有權限看到那張單據才會收到。'))
    // 通道
    panel.appendChild(field('用什麼方式通知？', el('div', {}, [
      el('label', { style: 'font-size:12px;margin-right:12px' }, [el('input', { type: 'checkbox', checked: 'checked', disabled: 'disabled' }), el('span', { text: ' 站內通知（一定會有）' })]),
      el('label', { style: 'font-size:12px' }, [el('input', { type: 'checkbox', 'data-role': 'email', checked: f.email ? 'checked' : null, onchange: function (e) { f.email = !!e.target.checked; touch(); render() } }), el('span', { text: ' 同時寄電子郵件' })])]),
      f.email ? '加寄信件屬於放寬；信件主旨前綴固定為【MOTRIX 系統通知】，每個設定每小時最多寄 ' + ((st.cat.caps && st.cat.caps.mailsPerHour) || 200) + ' 封，收件人可在通知偏好自行關閉。' : ''))
    // 內容
    ;[['title', '通知標題', 1], ['body', '通知內文', 3]].forEach(function (t) {
      var key = t[0], prob = textProblem(f[key], LIMIT[key], allowedPh(ev))
      var input = el(t[2] === 1 ? 'input' : 'textarea', { type: t[2] === 1 ? 'text' : null, rows: t[2] === 1 ? null : '3', 'data-path': key, value: f[key], placeholder: ev.suggest ? ev.suggest[key] : '', maxlength: String(LIMIT[key] + 20),
        style: 'width:100%;font-size:12px', oninput: function (e) { f[key] = e.target.value; touch(); var pr = panel.querySelector && panel.querySelector('[data-problem="' + key + '"]'); if (pr) pr.textContent = f[key] ? textProblem(f[key], LIMIT[key], allowedPh(ev)) : '' } })
      if (t[2] !== 1) input.textContent = f[key]
      panel.appendChild(field(t[1] + '（最多 ' + LIMIT[key] + ' 字）', el('div', {}, [input,
        el('div', { style: 'display:flex;gap:4px;flex-wrap:wrap;margin-top:3px' }, allowedPh(ev).map(function (p) {
          return el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-ph': p, text: '插入「' + p + '」', onclick: function () { insertAt(input, key, '{' + p + '}') } })
        })),
        el('div', { 'data-problem': key, text: f[key] ? prob : '', style: 'color:#b91c1c;font-size:11px' })]),
        '文字只能用中文、英數字與常用標點；不能放網址、$、/ 或標記；不能寫「已核准」這類官方狀態字樣。「插入」的詞會換成實際內容。'))
    })
    // 節流
    panel.appendChild(field('避免打擾', el('div', { style: 'display:flex;gap:10px;flex-wrap:wrap;align-items:center;font-size:12px' }, [
      el('span', { text: '同一件事' }), el('input', { type: 'number', min: '1', max: '1440', value: String(f.dedupe), 'data-path': 'dedupe', style: 'width:70px', oninput: function (e) { f.dedupe = e.target.value; touch() } }), el('span', { text: '分鐘內不重複通知同一個人；每人每天最多' }),
      el('input', { type: 'number', min: '1', max: '20', value: String(f.perDay), 'data-path': 'perDay', style: 'width:60px', oninput: function (e) { f.perDay = e.target.value; touch() } }), el('span', { text: '則' })]),
      '次數放多、間隔縮短屬於放寬，需要第二位最高管理者核准。'))
    panel.appendChild(el('label', { style: 'font-size:12px;display:block;margin:8px 0' }, [el('input', { type: 'checkbox', 'data-role': 'enabled', checked: f.enabled ? 'checked' : null, onchange: function (e) { f.enabled = !!e.target.checked; touch() } }), el('span', { text: ' 啟用（取消勾選並發布＝停用）' })]))
    panel.appendChild(el('div', { 'data-role': 'live-host' }, st.preview ? [previewView()] : []))
    panel.appendChild(el('div', { style: 'display:flex;gap:6px;align-items:center;margin-top:8px;flex-wrap:wrap' }, [
      el('input', { type: 'text', placeholder: '備註（選填）', value: st.note, style: 'flex:1;min-width:140px;font-size:12px', oninput: function (e) { st.note = e.target.value } }),
      el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-role': 'cancel', text: '返回清單', disabled: st.busy ? 'disabled' : null, onclick: function () { st.f = null; st.preview = null; setMsg('', false, 'idle'); render() } }),
      el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-role': 'preview-btn', text: '試跑看看', disabled: st.busy ? 'disabled' : null, onclick: runPreview }),
      el('button', { type: 'button', class: 'btn btn-primary btn-sm', 'data-role': 'publish', text: '檢查並發布', disabled: st.busy ? 'disabled' : null, onclick: doPublish })]))
    panel.appendChild(dim('新增通知、增加收件人、加寄信件、放寬次數都需要第二位最高管理者核准後才生效；停用與縮小範圍立即生效。已經寄出的通知不會改變，也不會影響原本的內建通知。'))
    return panel
  }
  function render() {
    if (!root) return
    while (root.firstChild) root.removeChild(root.firstChild)
    root.setAttribute('data-state', st.state); root.setAttribute('data-busy', st.busy ? '1' : '0')
    root.appendChild(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-role': 'toggle', text: st.open ? '收起額外通知' : '額外通知（指定事件發生時，額外通知指定的人）', onclick: function () {
      st.open = !st.open; if (st.open && !st.list.length && !st.f) { loadList() } else { render() } } }))
    if (!st.open || !st.cat) return
    var panel = el('div', { style: 'margin-top:6px;padding:12px;border:1px solid var(--border,#ccc);border-radius:8px;background:var(--bg-card,#fff);max-width:760px' })
    panel.appendChild(el('div', { text: '額外通知：當指定的事情發生時，額外通知你選的人。內建的通知與信件不受影響、也不能在這裡關掉。', style: 'font-size:12px;margin-bottom:6px' }))
    panel.appendChild(st.f ? formView() : listView())
    if (st.msg) panel.appendChild(el('div', { text: st.msg, 'data-role': 'msg', style: 'margin-top:6px;font-size:12px;color:' + (st.msgBad ? '#b91c1c' : 'inherit') }))
    root.appendChild(panel)
  }

  function boot(mount) {
    api('GET', '/api/notify-actions/status').then(function (s) {
      if (!s || !s.enabled || !s.canEdit || !s.events || !s.events.length) return   // 旗標關／治理沒開／不是最高管理者 ⇒ 完全不畫
      st.cat = { events: s.events, picker: s.picker || {}, caps: s.caps || {} }
      root = el('div', { id: 'notify-action-editor-root', style: 'margin:12px 0' })
      ;(mount || document.body).appendChild(root)
      render()
    }).catch(function () { /* 讀不到狀態 ⇒ 當作未開放 */ })
  }
  window.MotrixNotifyActionEditor = {
    _toBody: toBody, _fromBody: fromBody, _problems: problems, _textProblem: textProblem, _whoText: whoText, _pendingText: pendingText, _state: st,
    _init: function (cat) { st.cat = cat; st.list = []; st.f = null; st.preview = null; st.open = true; root = document.getElementById('notify-action-editor-root') || el('div', { id: 'notify-action-editor-root' }) },
    _startNew: startNew, _setEvent: setEvent, _applySuggest: applySuggest, _addRecipient: addRecipient, _loadList: loadList, _preview: runPreview, _startEdit: startEdit,
    _recipientOptions: recipientOptions, _render: render, _root: function () { return root },
    publish: doPublish, start: function () { boot(document.getElementById('notify-action-editor-mount')) }
  }
})()
