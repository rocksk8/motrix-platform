/* form-preview.js — 模組建構器的即時預覽與縮圖（docs/platform/BUILDER-UX.md §3.2；A 的元件，B 不改本檔）
 *
 * ① 預覽＝執行頁本身：render() 在容器裡放一個 iframe，載入 custom-records.html?preview=1，用 postMessage 傳草稿。
 *    表單的欄位、版面、必填標示全由執行頁的同一份模板畫 ⇒ 改執行期模板，預覽跟著變（不另寫一套會漂移的渲染）。
 *    預覽模式的防線在執行頁（同一個旗標擋住所有 API，§3.3）；本檔的 iframe sandbox 只是第二道。
 * ② 縮圖：流程／簽核／通知／輸出四步用純函式從草稿畫 inline SVG（MotrixFormPreview.svg.*，可單獨測）；
 *    欄位／版面兩步用縮小的預覽 iframe。
 *
 * 約定（BUILDER-UX §3.2）：
 *   父 → 子 {type:'motrix-preview', v:1, kind:'draft', draft, mode}、{…, kind:'highlight', field}
 *   子 → 父 {type:'motrix-preview', v:1, kind:'ready'}、{…, kind:'height', px}
 *   雙向只收同源、type／v 對得上的訊息。
 * 不搶焦點：update() 只送訊息，不重新載入、不重建 iframe、不 focus；ready 之前收到的草稿只留最後一份。
 * 無框架、無 CDN；顏色只用 currentColor（跟著外層文字色，不寫色碼）。
 */
;(function () {
  var TYPE = 'motrix-preview'
  var V = 1
  var PAGE = '/pages/custom-records.html'

  function clone(x) {
    try { return JSON.parse(JSON.stringify(x === undefined ? {} : x)) } catch (e) { return {} }
  }

  /** 表單或列表預覽 ⇒ {update(draft), setHighlight(key), destroy(), iframe} */
  function render(el, draft, opts) {
    opts = opts || {}
    var mode = opts.mode === 'list' ? 'list' : 'form'
    var iframe = document.createElement('iframe')
    iframe.className = 'fp-frame'
    iframe.setAttribute('title', mode === 'list' ? '列表預覽' : '表單預覽')
    iframe.setAttribute('sandbox', 'allow-scripts allow-same-origin')   // 不給 forms、不給 top-navigation
    iframe.setAttribute('tabindex', '-1')                                // 預覽是唯讀的，鍵盤導覽不進去
    iframe.style.width = '100%'
    iframe.style.border = '0'
    iframe.src = PAGE + '?preview=1'
    var ready = false
    var pending = clone(draft)          // ready 之前只留最後一份
    var hl = opts.highlight === undefined ? null : opts.highlight
    var alive = true

    function send(msg) {
      if (!alive || !iframe.contentWindow) return
      iframe.contentWindow.postMessage(Object.assign({ type: TYPE, v: V }, msg), location.origin)
    }
    function flush() {
      if (pending !== null) { send({ kind: 'draft', draft: pending, mode: mode }); pending = null }
      send({ kind: 'highlight', field: hl })
    }
    function onMessage(e) {
      if (e.origin !== location.origin || e.source !== iframe.contentWindow) return
      var d = e.data
      if (!d || typeof d !== 'object' || d.type !== TYPE || d.v !== V) return
      if (d.kind === 'ready') { ready = true; flush() }
      else if (d.kind === 'height' && typeof d.px === 'number' && isFinite(d.px)) {
        iframe.style.height = Math.max(0, Math.round(d.px)) + 'px'
      }
    }
    window.addEventListener('message', onMessage)
    el.appendChild(iframe)
    return {
      iframe: iframe,
      update: function (next) {
        pending = clone(next)
        if (ready) flush()
      },
      setHighlight: function (key) {
        hl = key === undefined ? null : key
        if (ready) send({ kind: 'highlight', field: hl })
      },
      destroy: function () {
        alive = false
        window.removeEventListener('message', onMessage)
        if (iframe.parentNode) iframe.parentNode.removeChild(iframe)
      },
    }
  }

  // ── 縮圖：純函式 ⇒ SVG 字串 ─────────────────────────────────────────────
  function esc(s) {
    return String(s === undefined || s === null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  }
  function cut(s, n) { s = String(s || ''); return s.length > n ? s.slice(0, n - 1) + '…' : s }
  function states(def) { return ((def && def.workflow && def.workflow.states) || []).filter(function (s) { return s && s.key }) }
  function frame(w, h, body, label, step) {
    return '<svg xmlns="http://www.w3.org/2000/svg" class="fp-thumb" data-thumb="' + esc(step) + '" viewBox="0 0 ' + w + ' ' + h +
      '" width="' + w + '" height="' + h + '" role="img" aria-label="' + esc(label) + '" fill="none" stroke="currentColor"' +
      ' font-family="inherit" font-size="10">' + body + '</svg>'
  }
  function empty(step, text) {
    return frame(160, 40, '<text x="80" y="24" text-anchor="middle" fill="currentColor" stroke="none" opacity=".6">' +
      esc(text) + '</text>', text, step)
  }
  function box(x, y, w, h, text, attrs) {
    return '<g' + (attrs || '') + '><rect x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="4"/>' +
      '<text x="' + (x + w / 2) + '" y="' + (y + h / 2 + 3.5) + '" text-anchor="middle" fill="currentColor" stroke="none">' +
      esc(cut(text, 8)) + '</text></g>'
  }

  /** 流程：狀態排成一列，轉換畫成箭頭（有 from 陣列的每一個都畫）；起始狀態粗框、結束狀態虛框。 */
  function workflowSvg(def) {
    var ss = states(def)
    if (!ss.length) return empty('workflow', '尚未設定狀態')
    var W = 64, H = 22, GAP = 22, pad = 8
    var idx = {}
    ss.forEach(function (s, i) { idx[s.key] = i })
    var initial = (def.workflow && def.workflow.initial) || ss[0].key
    var body = ''
    ss.forEach(function (s, i) {
      var cls = ' data-state="' + esc(s.key) + '"' + (s.key === initial ? ' stroke-width="2"' : '') +
        (s.final ? ' stroke-dasharray="3 2"' : '')
      body += box(pad + i * (W + GAP), 30, W, H, s.label || s.key, cls)
    })
    var arcs = 0
    ;((def.workflow && def.workflow.transitions) || []).forEach(function (t) {
      if (!t) return
      var froms = Array.isArray(t.from) ? t.from : [t.from]
      froms.forEach(function (f) {
        if (!(f in idx) || !(t.to in idx)) return
        var a = pad + idx[f] * (W + GAP) + W / 2, b = pad + idx[t.to] * (W + GAP) + W / 2
        var up = b >= a                                  // 往後走畫上方，退回畫下方
        var y0 = up ? 30 : 52, bend = up ? 12 : 72
        body += '<path data-transition="' + esc(t.key) + '" d="M' + a + ' ' + y0 + ' Q' + ((a + b) / 2) + ' ' + bend + ' ' + b + ' ' + y0 +
          '" marker-end="url(#fp-arrow)" opacity=".8"/>'
        arcs++
      })
    })
    var w = pad * 2 + ss.length * W + (ss.length - 1) * GAP
    var defs = '<defs><marker id="fp-arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="6" markerHeight="6" orient="auto">' +
      '<path d="M0 0 L6 3 L0 6 z" fill="currentColor" stroke="none"/></marker></defs>'
    return frame(w, 84, defs + body, '流程：' + ss.length + ' 個狀態、' + arcs + ' 個轉換', 'workflow')
  }

  /** 簽核：每個有簽核的狀態一列，後面依層數畫小方塊（方塊內＝該層簽核人數；有條件的層虛框）。 */
  function approvalSvg(def) {
    var rows = states(def).filter(function (s) { return s.approval && Array.isArray(s.approval.tiers) && s.approval.tiers.length })
    if (!rows.length) return empty('approval', '沒有簽核')
    var body = ''
    rows.forEach(function (s, r) {
      var y = 8 + r * 26
      body += '<text x="6" y="' + (y + 13) + '" fill="currentColor" stroke="none">' + esc(cut(s.label || s.key, 6)) + '</text>'
      s.approval.tiers.forEach(function (t, i) {
        var n = (t && Array.isArray(t.approvers)) ? t.approvers.length : 0
        body += box(70 + i * 30, y, 24, 18, String(n), ' data-tier="' + esc(s.key) + ':' + i + '"' + (t && t.when ? ' stroke-dasharray="3 2"' : ''))
      })
    })
    var maxT = Math.max.apply(null, rows.map(function (s) { return s.approval.tiers.length }))
    return frame(80 + maxT * 30, 16 + rows.length * 26, body, '簽核：' + rows.length + ' 個狀態有簽核', 'approval')
  }

  /** 通知：每個有通知的狀態一列，後面列出通知誰（申請人／指定人數）。 */
  function notifySvg(def) {
    var rows = states(def).filter(function (s) { return s.notify && (s.notify.requester || (s.notify.users || []).length) })
    if (!rows.length) return empty('notify', '沒有通知')
    var body = ''
    rows.forEach(function (s, r) {
      var y = 8 + r * 24
      var who = []
      if (s.notify.requester) who.push('申請人')
      if ((s.notify.users || []).length) who.push('指定 ' + s.notify.users.length + ' 人')
      body += '<g data-notify="' + esc(s.key) + '"><text x="6" y="' + (y + 12) + '" fill="currentColor" stroke="none">' +
        esc(cut(s.label || s.key, 6)) + '</text><path d="M70 ' + (y + 8) + ' h10 l4 4 l-4 4 h-10 z"/>' +
        '<text x="92" y="' + (y + 12) + '" fill="currentColor" stroke="none">' + esc(who.join('、')) + '</text></g>'
    })
    return frame(200, 16 + rows.length * 24, body, '通知：' + rows.length + ' 個狀態會通知', 'notify')
  }

  /** 輸出：版型的區塊依序疊成長條（條內＝區塊型別）。 */
  function outputSvg(def) {
    var tpl = def && def.output && def.output.template
    var blocks = (tpl && Array.isArray(tpl.blocks)) ? tpl.blocks.filter(Boolean) : []
    if (!blocks.length) return empty('output', '沒有輸出版型')
    var body = '<rect x="4" y="4" width="112" height="' + (12 + blocks.length * 16) + '" rx="3" opacity=".5"/>'
    blocks.forEach(function (b, i) {
      body += '<g data-block="' + esc(b.type) + '"><rect x="10" y="' + (10 + i * 16) + '" width="100" height="12" rx="2"/>' +
        '<text x="60" y="' + (19 + i * 16) + '" text-anchor="middle" fill="currentColor" stroke="none">' + esc(cut(b.type, 12)) + '</text></g>'
    })
    return frame(120, 20 + blocks.length * 16, body, '輸出：' + blocks.length + ' 個區塊', 'output')
  }

  var SVG = { workflow: workflowSvg, approval: approvalSvg, notify: notifySvg, output: outputSvg }

  /** 各步縮圖。fields／layout ⇒ 縮小的預覽 iframe（回傳同 render 的控制物件）；其他 ⇒ SVG（回傳 {update, destroy}）。 */
  function thumb(el, draft, opts) {
    var step = (opts && opts.step) || 'fields'
    if (step === 'fields' || step === 'layout') {
      var wrap = document.createElement('div')
      wrap.className = 'fp-thumb-frame'
      wrap.style.cssText = 'overflow:hidden;pointer-events:none;height:120px'
      var inner = document.createElement('div')
      inner.style.cssText = 'transform:scale(.3);transform-origin:0 0;width:333%'
      wrap.appendChild(inner)
      el.appendChild(wrap)
      var h = render(inner, draft, { mode: step === 'layout' ? 'list' : 'form' })
      var destroy = h.destroy
      h.destroy = function () { destroy(); if (wrap.parentNode) wrap.parentNode.removeChild(wrap) }
      return h
    }
    var fn = SVG[step]
    function paint(d) { el.innerHTML = fn ? fn(clone(d)) : empty(step, '此步驟尚無縮圖') }
    paint(draft)
    return { update: paint, setHighlight: function () {}, destroy: function () { el.innerHTML = '' } }
  }

  window.MotrixFormPreview = { render: render, thumb: thumb, svg: SVG, PAGE: PAGE }
})()
