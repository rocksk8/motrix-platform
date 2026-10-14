/* notify-editor.js — 簽核通知用語編輯器（S-X3；設計 docs/platform/plans/S-X3-NOTIFY-WORDING-DESIGN-T62.md）
 *
 * 載入方式：approval-settings.html 底部的小載入器——只有最高管理者、且 MotrixPublicFlags 讀到 builder_notify.enabled 開啟時，
 * 才依序載入 def-governance.js 與本檔；旗標關／不是最高管理者 ⇒ 本檔根本不會被載入（唯一的請求是那一次旗標讀取）。
 * 載入後再問 GET /api/notify-templates/{event}/status（治理沒開也回 enabled:false ⇒ 什麼都不畫）。
 *
 * 編輯：每個欄位一個文字框，旁邊是占位符按鈕（{單號} {對象} {標記}…，只列該欄位允許的）；留空＝用系統預設字。
 * 即時預覽（輸入時就更新，純前端、與後端同一套展開規則）：站內訊息（含『沒有財務權限的簽核人』遮蔽視角）、通知信
 * （主旨前綴與分類固定、灰字顯示；內文以樣本單據畫出）。
 * 發布：存草稿 → 後端預覽檢查（422 顯示白話原因）→ MotrixDefGovernance.review（發布前影響預覽，確認後才發布）→ 發布；
 * 新增或改變用語屬放寬，後端回 pending:true，面板如實說『已送出，待第二位最高管理者核准』。不用原生對話框；所有文字用 textContent 寫入。
 * e2e 等待點：#notify-editor-root 的 data-state（idle／checked／pending／published／error）與 data-busy（'0'／'1'）。
 */
;(function () {
  if (window.MotrixNotifyEditor) return
  var EVENT = 'approval:submitted'
  var KIND = 'notify_template'
  var PREFIX = '【MOTRIX 系統通知】簽核－'
  var MONEY = /(?:NT\$|NTD|\$)\s*[-+]?\d[\d,]*(?:\.\d+)?|[-+]?\d[\d,]*(?:\.\d+)?\s*元(?![一-鿿])/g
  var BAD = /[<>&"'`\\\x00-\x1f\x7f​-‏‪-‮⁦-⁩﻿]/
  var INVIS = /[\p{Cc}\p{Cf}\p{Zl}\p{Zp}\p{Co}\p{Cs}\u115f\u1160\u3164\uffa0\u2800\u180e\u034f\u061c\u17b4\u17b5\u00ad\u2060]/u
  var ALLOWED = /^[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303fA-Za-z0-9 .,:;!?()\[\]\-_~{}]*$/
  var URLISH = /https?|:\/\/|www\.|[A-Za-z0-9_]+\.[A-Za-z0-9_]{2,}|\//i
  var RESERVED = ['正本', '副本', '已核准', '已核可', '核准', '核可', '簽核完成', '签核完成', '已付款', '已收款', '已簽回', '已簽收', '作廢', '作废',
    '已通過', '通過', '已通过', '通过', '批准', '審核通過', '审核通过', '簽核通過', '签核通过', '已簽核', '已签核', '已批', '已生效']
  var RESERVED_EN = /(?<![a-z])(?:approve|approved|passed|paid|original|void|signed|final)(?![a-z])/
  var PH = /\{([^{}]{1,12})\}/g

  // st.cat＝目前選的事件描述（欄位、預設字、樣本、信件明細列）；st.events＝全部事件；st.store＝各事件各自的編輯副本（切換不遺失）
  var st = { open: false, busy: false, state: 'idle', msg: '', msgBad: false, cat: null, events: [], cur: 0, store: {}, loaded: {}, vals: {}, etag: '', note: '' }
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
  function msgOf(j) {
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
  function fields() { return (st.cat && st.cat.fields) || [] }
  function fieldOf(path) { return fields().filter(function (f) { return f.field === path })[0] }
  function expand(text, ctx) { return String(text).replace(PH, function (m, k) { return ctx[k] === undefined ? '' : ctx[k] }) }
  function skeleton(s) { return String(s).normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '') }

  // 與後端 helpers/notify_templates._text_problems 同一套規則（後端仍是權威）
  function problemOf(path, v) {
    var f = fieldOf(path); if (!f) return ''
    v = String(v || '')
    if (!v.trim()) return ''
    if (v === f.default) return ''                        // 與預設字相同＝程式碼寫死的字，放行（可能含斜線、狀態字樣）
    if (v.length > f.limit) return '最多 ' + f.limit + ' 字'
    if (INVIS.test(v)) return '不可含控制、隱形、雙向或私用字元'
    if (BAD.test(v)) return '不可含標記字元（< > & 引號 反斜線）'
    if (!ALLOWED.test(v.normalize('NFKC'))) return '只能使用中文、英數字與常用標點（不接受外觀相似的其他文字）'
    if (URLISH.test(v.replace(PH, '').normalize('NFKC'))) return '不可含網址或連結（含斜線、網域寫法）'
    var names = [], m
    PH.lastIndex = 0
    while ((m = PH.exec(v))) names.push(m[1])
    for (var i = 0; i < names.length; i++) if (f.placeholders.indexOf(names[i]) < 0) return '不認得的占位符 {' + names[i] + '}'
    var rest = v.replace(PH, '')
    if (rest.indexOf('{') >= 0 || rest.indexOf('}') >= 0) return '大括號只能用在占位符'
    if (f.need && f.need.length) for (var j = 0; j < f.need.length; j++) if (names.indexOf(f.need[j]) < 0) return '必須包含 {' + f.need[j] + '}（讓收件人認得是哪一張單）'
    if (f.allowStatus) return ''                          // 這個欄位本來就是在說明該事件的官方結果（例如核准事件）：事件鍵決定能不能說
    var sk = skeleton(rest)
    for (var k = 0; k < RESERVED.length; k++) if (sk.indexOf(skeleton(RESERVED[k])) >= 0) return '不可含官方狀態字樣：' + RESERVED[k]
    var en = RESERVED_EN.exec(rest.normalize('NFKC').toLowerCase()); if (en) return '不可含官方狀態字樣：' + en[0]
    return ''
  }
  function allProblems() {
    var out = []
    fields().forEach(function (f) { var p = problemOf(f.field, st.vals[f.field]); if (p) out.push(f.label + '：' + p) })
    return out
  }
  function eff(path) {
    var v = (st.vals[path] || '').trim()
    if (v && !problemOf(path, v)) return v
    var f = fieldOf(path); return f ? f.default : ''
  }
  function toTemplate() {
    var t = { version: 1 }, any = false
    fields().forEach(function (f) {
      var v = (st.vals[f.field] || '').trim(); if (!v) return
      var c = f.field.split('.'); (t[c[0]] = t[c[0]] || {})[c[1]] = v; any = true
    })
    if (!any) {                                           // 全部留空＝回到系統預設字：明確發布一份等於預設的範本（驗證要求至少一個欄位）
      fields().forEach(function (f) { var c = f.field.split('.'); (t[c[0]] = t[c[0]] || {})[c[1]] = f.default })
    }
    return t
  }
  function fromTemplate(tpl) {
    var vals = {}
    fields().forEach(function (f) {
      var c = f.field.split('.'); var v = tpl && tpl[c[0]] && tpl[c[0]][c[1]]
      vals[f.field] = (typeof v === 'string' && v !== f.default) ? v : ''
    })
    return vals
  }

  // 切換事件（報價單送審／輪到下一層／核准／退回）：先把目前這一個的編輯內容收進 st.store，再還原要看的那個；沒讀過就向後端讀一次
  function selectEvent(i) {
    if (i === st.cur && st.loaded[EVENT]) return Promise.resolve()
    st.store[EVENT] = { vals: st.vals, etag: st.etag }
    st.cur = i; st.cat = st.events[i]; EVENT = st.cat.event
    st.msg = ''; st.msgBad = false; st.state = 'idle'
    var s = st.store[EVENT]
    if (s) { st.vals = s.vals; st.etag = s.etag; render(); return Promise.resolve() }
    st.vals = fromTemplate(null); st.etag = ''
    return load()
  }
  function load() {
    st.loaded[EVENT] = true
    st.busy = true; st.msg = '讀取中…'; render()
    return api('GET', '/api/definitions/' + KIND + '/' + encodeURIComponent(EVENT) + '?scope=company').then(function (d) {
      var src = (d.draft && d.draft.body) || (d.latest && d.latest.body) || null
      st.vals = fromTemplate(src)
      st.etag = (d.draft && d.draft.etag) || ''
      st.busy = false; st.msg = ''; st.msgBad = false; st.state = 'idle'; render()
    }).catch(function (e) {
      if (e.status === 404 || e.status === 400) { st.vals = fromTemplate(null); st.etag = ''; st.busy = false; st.msg = ''; st.state = 'idle'; render(); return }
      st.busy = false; st.state = 'error'; st.msg = '讀取失敗：' + e.message; st.msgBad = true; render()
    })
  }
  function pendingText(d) {
    var reasons = []
    ;(d.reasons || []).forEach(function (r) { var t = typeof r === 'string' ? r : ((r && (r.message || r.text)) || ''); if (t && reasons.indexOf(t) < 0) reasons.push(t) })
    var at = d.effectiveAt ? String(d.effectiveAt).replace('T', ' ').slice(0, 16) : ''
    return '已送出發布，待第二位最高管理者核准；核准前不會生效' + (at ? '，生效時間 ' + at + ' 之後' : '') + (reasons.length ? '。原因：' + reasons.join('；') : '') + '。'
  }
  function fail(prefix, e) { st.busy = false; st.state = 'error'; st.msg = prefix + e.message; st.msgBad = true; render() }

  // 發布：存草稿 → 後端預覽檢查 → 影響預覽（確認）→ 發布
  function doPublish() {
    var p = allProblems()
    if (p.length) { st.msg = p.join('；'); st.msgBad = true; st.state = 'error'; render(); return Promise.resolve() }
    st.busy = true; st.msg = '檢查中…'; st.msgBad = false; render()
    var tpl = toTemplate()
    return api('PUT', '/api/definitions/' + KIND + '/' + encodeURIComponent(EVENT) + '/draft?scope=company', { body: tpl, base_etag: st.etag || '' }).then(function (r) {
      st.etag = r.etag || st.etag
      return api('POST', '/api/notify-templates/' + encodeURIComponent(EVENT) + '/preview', { template: tpl })
    }).then(function () {
      st.state = 'checked'; st.msg = '檢查通過，請在右側確認影響後發布。'; render()
      var G = window.MotrixDefGovernance
      if (!G || !G.review) return { noGovernance: true }  // 沒有治理面板元件 ⇒ 不帶預覽雜湊（後端強制時會擋下並提示）；與『使用者取消』分開
      return G.review({ kind: KIND, key: EVENT, scope: 'company', title: '發布前影響預覽：簽核通知用語' })
    }).then(function (hash) {
      if (hash && hash.noGovernance === true) hash = ''
      else if (!hash) hash = null                         // 任何空值（null／undefined／''）＝使用者取消
      if (hash === null) { st.busy = false; st.state = 'idle'; st.msg = '已取消發布（草稿已存）。'; render(); return }
      st.msg = '發布中…'; render()
      var body = { note: st.note || '', base_etag: st.etag || undefined }
      if (hash) body.preview_hash = hash
      return api('POST', '/api/definitions/' + KIND + '/' + encodeURIComponent(EVENT) + '/publish?scope=company', body).then(function (r) {
        st.busy = false
        if (r && r.pending === true) { st.state = 'pending'; st.msg = pendingText(r); st.msgBad = false; render(); return }
        st.state = 'published'; st.msg = '已發布。之後的「' + st.cat.label + '」通知依這份用語。'; st.msgBad = false
        return load().then(function () { st.msg = '已發布。之後的「' + st.cat.label + '」通知依這份用語。'; st.state = 'published'; render() })
      })
    }).catch(function (e) {
      var code = e.body && e.body.code
      fail(code === 'preview_required' || code === 'preview_stale' ? '發布前必須先看過目前這份用語的影響預覽，請重新發布：' : '失敗：', e)
    })
  }
  function insertAt(input, path, ph) {
    var v = input.value, a = input.selectionStart == null ? v.length : input.selectionStart, b = input.selectionEnd == null ? a : input.selectionEnd
    var next = v.slice(0, a) + ph + v.slice(b)
    st.vals[path] = next; st.state = 'idle'; render()
    var again = root && root.querySelector('[data-path="' + path + '"]')
    if (again) { again.focus(); try { again.setSelectionRange(a + ph.length, a + ph.length) } catch (e) { /* 忽略 */ } }
  }

  function previewCard() {
    var ctx = st.cat.sample || {}
    var ctxShow = {}; Object.keys(ctx).forEach(function (k) { ctxShow[k] = ctx[k] })
    var msg = expand(eff('inapp.message'), ctxShow)
    var masked = msg.replace(MONEY, '（金額略）')
    var reason = expand(eff('mail.reason'), ctxShow)
    var mailRows = st.cat.mailRows || []
    var box = el('div', { style: 'margin-top:10px;padding:8px;border:1px dashed var(--border,#bbb);border-radius:8px', 'data-role': 'preview' })
    box.appendChild(el('div', { text: '即時預覽（樣本單據：' + (ctx['單號'] || '') + '／' + (ctx['對象'] || '') + '）', style: 'font-size:12px;font-weight:600' }))
    box.appendChild(el('div', { text: '站內訊息（簽核人看到）', style: 'font-size:11px;color:var(--text-dim,#888);margin-top:6px' }))
    box.appendChild(el('div', { text: msg, style: 'font-size:13px;padding:4px 6px;background:var(--bg-hover,#f3f4f6);border-radius:6px', 'data-role': 'pv-inapp' }))
    box.appendChild(el('div', { text: '沒有財務權限的簽核人看到（金額會被遮蔽）', style: 'font-size:11px;color:var(--text-dim,#888);margin-top:4px' }))
    box.appendChild(el('div', { text: masked, style: 'font-size:13px;padding:4px 6px;background:var(--bg-hover,#f3f4f6);border-radius:6px', 'data-role': 'pv-masked' }))
    box.appendChild(el('div', { text: '通知信', style: 'font-size:11px;color:var(--text-dim,#888);margin-top:8px' }))
    var subj = el('div', { style: 'font-size:12px', 'data-role': 'pv-subject' }, [
      el('span', { text: PREFIX, style: 'color:var(--text-dim,#999)' }), el('span', { text: reason })
    ])
    box.appendChild(subj)
    box.appendChild(el('div', { style: 'margin-top:4px;padding:10px;border:1px solid var(--border,#ddd);border-radius:8px;background:#fff;color:#111;font-size:12px' }, [
      el('div', { style: 'font-size:15px;font-weight:700' }, [
        el('span', { text: expand(eff('mail.title'), ctxShow) + ' ', 'data-role': 'pv-title' }),
        el('span', { text: expand(eff('mail.badge'), ctxShow), style: 'font-size:11px;background:#2F6FD6;color:#fff;padding:1px 6px;border-radius:8px', 'data-role': 'pv-badge' })
      ]),
      el('div', { text: '事由', style: 'font-weight:700;margin-top:8px' }),
      el('div', { text: expand(eff('mail.intro'), ctxShow), 'data-role': 'pv-intro' }),
      el('div', {}, mailRows.map(function (r) {              // 信件明細列（固定，不由範本決定）：標籤＋樣本值
        return el('div', {}, [el('div', { text: r[0], style: 'color:#666;margin-top:6px' }), el('div', { text: r[1].indexOf('{') >= 0 ? expand(r[1], ctxShow) : (ctx[r[1]] || '') })])
      })),
      st.cat.noteSample ? el('div', { text: st.cat.noteSample, style: 'margin-top:8px;padding:6px 8px;background:#FFF8E1;border-radius:6px;color:#7A5A00' }) : null,
      el('div', { text: expand(eff('mail.button'), ctxShow), style: 'display:inline-block;margin-top:10px;padding:6px 14px;background:#1D4ED8;color:#fff;border-radius:6px', 'data-role': 'pv-button' })
    ]))
    box.appendChild(el('div', { text: '主旨前綴與分類、信件版型、收件人與寄送時機都不能改；信件沒有金額欄位。', style: 'font-size:11px;color:var(--text-dim,#888);margin-top:4px' }))
    return box
  }

  function render() {
    if (!root) return
    while (root.firstChild) root.removeChild(root.firstChild)
    root.setAttribute('data-state', st.state); root.setAttribute('data-busy', st.busy ? '1' : '0')
    root.appendChild(el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-role': 'toggle', text: st.open ? '收起簽核通知用語' : '簽核通知用語', onclick: function () { st.open = !st.open; if (st.open && !st.loaded[EVENT]) load(); else render() } }))
    if (!st.open || !st.cat) return
    var panel = el('div', { style: 'margin-top:6px;padding:12px;border:1px solid var(--border,#ccc);border-radius:8px;background:var(--bg-card,#fff);max-width:720px' })
    if (st.events.length > 1) {                           // 事件分頁：報價單送審／輪到下一層／核准／退回
      panel.appendChild(el('div', { style: 'display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px', 'data-role': 'tabs' }, st.events.map(function (ev, i) {
        return el('button', { type: 'button', class: 'btn btn-sm ' + (i === st.cur ? 'btn-primary' : 'btn-ghost'), 'data-event': ev.event, text: ev.label.replace(/（.*$/, ''),
                              disabled: st.busy ? 'disabled' : null, onclick: function () { selectEvent(i) } })
      })))
    }
    panel.appendChild(el('div', { text: st.cat.label + '：調整收到的訊息與通知信文字（留空＝用系統預設字）', style: 'font-size:13px;font-weight:600;margin-bottom:6px' }))
    panel.appendChild(el('div', { text: '文字只能用中文、英數字與常用標點；不能使用 $ 與 /（金額請寫成「1,200 元」這類說法），也不能放網址或標記。', style: 'font-size:11px;color:var(--text-dim,#888);margin-bottom:6px', 'data-role': 'help' }))
    fields().forEach(function (f) {
      var prob = problemOf(f.field, st.vals[f.field])
      var input = el('input', { type: 'text', 'data-path': f.field, value: st.vals[f.field] || '', placeholder: f.default, maxlength: String(f.limit + 20), style: 'flex:1;font-size:12px', oninput: function (ev) { st.vals[f.field] = ev.target.value; st.state = 'idle'; refreshLive() } })
      var row = el('div', { style: 'margin:6px 0' }, [
        el('div', { text: f.label + '（最多 ' + f.limit + ' 字）', style: 'font-size:12px' }),
        el('div', { style: 'display:flex;gap:4px;align-items:center;flex-wrap:wrap' }, [input].concat(f.placeholders.map(function (p) {
          return el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '{' + p + '}', 'data-ph': p, onclick: function () { insertAt(input, f.field, '{' + p + '}') } })
        })).concat([el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '恢復預設', onclick: function () { st.vals[f.field] = ''; st.state = 'idle'; render() } })])),
        el('div', { text: prob, 'data-role': 'problem', style: 'color:#b91c1c;font-size:11px;min-height:0' })
      ])
      panel.appendChild(row)
    })
    panel.appendChild(el('div', { 'data-role': 'live-host' }))
    panel.appendChild(el('div', { style: 'display:flex;gap:6px;align-items:center;margin-top:8px' }, [
      el('input', { type: 'text', placeholder: '備註（選填）', value: st.note, style: 'flex:1;font-size:12px', oninput: function (ev) { st.note = ev.target.value } }),
      el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '版本與還原', onclick: function () { if (window.MotrixDefGovernance) window.MotrixDefGovernance.open({ kind: KIND, key: EVENT, scope: 'company', title: '簽核通知用語：版本帳本', onRestored: load }) } }),
      el('button', { type: 'button', class: 'btn btn-primary btn-sm', 'data-role': 'publish', text: '檢查並發布', disabled: st.busy ? 'disabled' : null, onclick: doPublish })
    ]))
    panel.appendChild(el('div', { text: '新增或更換用語需要第二位最高管理者核准後才生效；已經寄出的通知不會改變。', style: 'font-size:11px;color:var(--text-dim,#888);margin-top:4px' }))
    if (st.msg) panel.appendChild(el('div', { text: st.msg, 'data-role': 'msg', style: 'margin-top:6px;font-size:12px;color:' + (st.msgBad ? '#b91c1c' : 'inherit') }))
    root.appendChild(panel)
    refreshLive()
  }
  // 輸入時只更新預覽與各欄問題字樣，不重畫整個面板（保留游標與焦點）
  function refreshLive() {
    if (!root) return
    var host = root.querySelector('[data-role="live-host"]'); if (!host) return
    while (host.firstChild) host.removeChild(host.firstChild)
    host.appendChild(previewCard())
    var probs = root.querySelectorAll('[data-role="problem"]')
    fields().forEach(function (f, i) { if (probs[i]) probs[i].textContent = problemOf(f.field, st.vals[f.field]) })
  }

  function boot(mount) {
    api('GET', '/api/notify-templates/status').then(function (s) {
      if (!s || !s.enabled || !s.canEdit || !s.events || !s.events.length) return   // 旗標關／治理沒開／不是最高管理者 ⇒ 完全不畫
      st.events = s.events; st.cur = 0; st.cat = s.events[0]; EVENT = st.cat.event
      root = el('div', { id: 'notify-editor-root', style: 'margin:12px 0' })
      ;(mount || document.body).appendChild(root)
      render()
    }).catch(function () { /* 讀不到狀態 ⇒ 當作未開放 */ })
  }
  window.MotrixNotifyEditor = {
    _toTemplate: toTemplate, _problems: allProblems, _problemOf: problemOf, _pendingText: pendingText, publish: doPublish, _expand: expand, _state: st,
    _init: function (cat) { st.events = [cat]; st.cur = 0; st.cat = cat; EVENT = cat.event || EVENT; st.store = {}; st.loaded = {}; st.vals = fromTemplate(null) },
    _initAll: function (events) { st.events = events; st.cur = 0; st.cat = events[0]; EVENT = events[0].event; st.store = {}; st.loaded = {}; st.vals = fromTemplate(null) },
    _select: selectEvent,
    start: function () { boot(document.getElementById('notify-editor-mount')) }
  }
})()
