/* ui.js — 共用提示／對話框（CM12 P4 預備，2026-09-24）
 *
 * 取代瀏覽器原生 alert／confirm／prompt：
 *   ☠️ 原生對話框會卡住整個分頁（含其他視窗的 e2e 與背景同步）、樣式不隨深色模式、
 *      Playwright 只能靠 page.on('dialog') 盲接——接錯一個就整支題失準。
 *
 * API（全部掛在 window.MotrixUI）：
 *   toast(message, {kind:'ok'|'error'|'info', ms})        → 元素；幾秒後自動消失（role=status）
 *   confirm(message, {title, okText, cancelText, danger}) → Promise<true|false>
 *   prompt(message, {title, value, placeholder, okText, cancelText, required})
 *                                                        → Promise<字串|null>（取消＝null；空字串是合法答案，除非 required）
 *   banner(message, {kind, id, dismissible})              → {el, close()}；常駐直到 close()（role=alert）；同 id 取代
 *
 * 鍵盤：Esc＝取消、Enter＝確認（prompt 的輸入框內也是）、Tab／Shift+Tab 焦點鎖在對話框內；
 *       關閉後焦點回到開啟前的元素。一次只開一個對話框：後來的排隊。
 *
 * 深色模式：style.css 用反轉濾鏡處理 `body` 的直接子元素（各頁 Modal 同一條路）⇒ 這裡的元素掛在 body 直下、
 *   用淺色 token（--white／--text-primary／--border-light／--accent）繪製，深色模式自動跟著反轉；
 *   不另外判斷 data-theme，否則會被反轉兩次。沒載 style.css 的頁面用 var() 的後備值。
 *
 * 測試掛點：[data-testid=ui-dialog]／ui-dialog-ok／ui-dialog-cancel／ui-dialog-input／ui-toast／ui-banner。
 * e2e 請用 backend/tests/_ui_dialogs.py 的 helper，不要再用 page.on('dialog')。
 */
(function () {
  if (window.MotrixUI) return

  var STYLE_ID = 'motrix-ui-style'
  var CSS = [
    '.mui-backdrop{position:fixed;inset:0;background:rgba(10,10,10,.42);display:flex;align-items:center;justify-content:center;z-index:9000;padding:16px}',
    '.mui-dialog{background:var(--white,#F5F4F0);color:var(--text-primary,#0A0A0A);border:1px solid var(--border-light,#E5E3DE);border-radius:10px;box-shadow:0 12px 32px rgba(0,0,0,.18);width:min(420px,100%);padding:18px 18px 14px;font-family:var(--font-zh,system-ui,sans-serif);font-size:14px;line-height:1.6}',
    '.mui-dialog:focus{outline:none}',
    '.mui-title{font-weight:700;font-size:15px;margin:0 0 6px}',
    '.mui-msg{white-space:pre-wrap;margin:0 0 12px;color:var(--text-primary,#0A0A0A)}',
    '.mui-input{width:100%;box-sizing:border-box;padding:7px 10px;border:1px solid var(--border-light,#E5E3DE);border-radius:6px;font-size:14px;background:#fff;color:var(--text-primary,#0A0A0A);margin-bottom:6px}',
    '.mui-err{color:#B91C1C;font-size:12px;min-height:16px;margin-bottom:6px}',
    '.mui-actions{display:flex;justify-content:flex-end;gap:8px}',
    '.mui-btn{padding:6px 14px;border-radius:6px;border:1px solid var(--border-light,#E5E3DE);background:#fff;color:var(--text-primary,#0A0A0A);font-size:13px;cursor:pointer;font-family:inherit}',
    '.mui-btn:focus-visible{outline:2px solid var(--accent,#C8102E);outline-offset:2px}',
    '.mui-btn--ok{background:var(--text-primary,#0A0A0A);color:var(--white,#F5F4F0);border-color:var(--text-primary,#0A0A0A)}',
    '.mui-btn--danger{background:var(--accent,#C8102E);border-color:var(--accent,#C8102E);color:#fff}',
    '.mui-toasts{position:fixed;right:16px;bottom:16px;display:flex;flex-direction:column;gap:8px;z-index:9100;pointer-events:none}',
    '.mui-toast{pointer-events:auto;padding:9px 14px;border-radius:8px;font-size:13px;font-family:var(--font-zh,system-ui,sans-serif);box-shadow:0 6px 18px rgba(0,0,0,.14);background:#fff;color:var(--text-primary,#0A0A0A);border:1px solid var(--border-light,#E5E3DE);max-width:360px}',
    '.mui-toast--ok{border-color:#A7F3D0;background:#ECFDF5;color:#047857}',
    '.mui-toast--error{border-color:#FECACA;background:#FEF2F2;color:#B91C1C}',
    '.mui-banners{position:fixed;left:0;right:0;top:0;z-index:8900;display:flex;flex-direction:column}',
    '.mui-banner{display:flex;align-items:center;gap:10px;padding:8px 16px;font-size:13px;font-family:var(--font-zh,system-ui,sans-serif);border-bottom:1px solid #FDE68A;background:#FFFBEB;color:#92400E}',
    '.mui-banner--error{border-color:#FECACA;background:#FEF2F2;color:#B91C1C}',
    '.mui-banner--info{border-color:#BFDBFE;background:#EFF6FF;color:#1E3A8A}',
    '.mui-banner__msg{flex:1}',
    '.mui-banner__x{background:none;border:none;font-size:16px;cursor:pointer;color:inherit;padding:0 4px}',
  ].join('\n')

  function ensureStyle() {
    if (document.getElementById(STYLE_ID)) return
    var st = document.createElement('style')
    st.id = STYLE_ID
    st.textContent = CSS
    document.head.appendChild(st)
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag)
    if (cls) e.className = cls
    if (text !== undefined && text !== null) e.textContent = String(text)   // 一律 textContent：訊息可能含使用者輸入
    return e
  }

  // ── 對話框（confirm／prompt 共用），一次一個、後來的排隊 ─────────────────
  var queue = Promise.resolve()
  var seq = 0

  function openDialog(kind, message, opts) {
    opts = opts || {}
    var run = queue.then(function () {
      return new Promise(function (resolve) {
        ensureStyle()
        var prevFocus = document.activeElement
        var id = 'mui-d' + (++seq)
        var back = el('div', 'mui-backdrop')
        var box = el('div', 'mui-dialog')
        box.setAttribute('role', kind === 'confirm' && opts.danger ? 'alertdialog' : 'dialog')
        box.setAttribute('aria-modal', 'true')
        box.setAttribute('data-testid', 'ui-dialog')
        box.setAttribute('data-kind', kind)
        box.tabIndex = -1
        if (opts.title) {
          var t = el('h2', 'mui-title', opts.title)
          t.id = id + '-t'
          box.setAttribute('aria-labelledby', t.id)
          box.appendChild(t)
        }
        var m = el('p', 'mui-msg', message)
        m.id = id + '-m'
        box.setAttribute('aria-describedby', m.id)
        box.appendChild(m)

        var input = null
        var err = null
        if (kind === 'prompt') {
          input = el('input', 'mui-input')
          input.type = 'text'
          input.value = opts.value == null ? '' : String(opts.value)
          if (opts.placeholder) input.placeholder = opts.placeholder
          input.setAttribute('data-testid', 'ui-dialog-input')
          input.setAttribute('aria-labelledby', m.id)
          box.appendChild(input)
          err = el('div', 'mui-err')
          err.setAttribute('role', 'alert')
          box.appendChild(err)
        }

        var actions = el('div', 'mui-actions')
        var cancel = el('button', 'mui-btn', opts.cancelText || '取消')
        cancel.type = 'button'
        cancel.setAttribute('data-testid', 'ui-dialog-cancel')
        var ok = el('button', 'mui-btn ' + (opts.danger ? 'mui-btn--danger' : 'mui-btn--ok'), opts.okText || '確定')
        ok.type = 'button'
        ok.setAttribute('data-testid', 'ui-dialog-ok')
        actions.appendChild(cancel)
        actions.appendChild(ok)
        box.appendChild(actions)
        back.appendChild(box)
        document.body.appendChild(back)

        var done = false
        function finish(value) {
          if (done) return
          done = true
          document.removeEventListener('keydown', onKey, true)
          if (back.parentNode) back.parentNode.removeChild(back)
          try { if (prevFocus && prevFocus.focus) prevFocus.focus() } catch (e) {}
          resolve(value)
        }
        function accept() {
          if (kind === 'confirm') return finish(true)
          var v = input.value
          if (opts.required && !v.trim()) {
            err.textContent = typeof opts.required === 'string' ? opts.required : '這一欄必填'
            input.focus()
            return
          }
          finish(v)
        }
        function dismiss() { finish(kind === 'confirm' ? false : null) }
        function focusables() {
          return Array.prototype.filter.call(box.querySelectorAll('button, input'), function (x) { return !x.disabled })
        }
        function onKey(e) {
          if (!document.body.contains(back)) return
          if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); dismiss(); return }
          if (e.key === 'Enter') {
            // 焦點在「取消」上按 Enter ＝ 取消（按鈕的預設行為），其餘一律確認
            if (document.activeElement === cancel) { e.preventDefault(); dismiss(); return }
            e.preventDefault(); e.stopPropagation(); accept(); return
          }
          if (e.key === 'Tab') {
            var f = focusables()
            if (!f.length) return
            var i = f.indexOf(document.activeElement)
            var next = e.shiftKey ? (i <= 0 ? f.length - 1 : i - 1) : (i === f.length - 1 || i < 0 ? 0 : i + 1)
            e.preventDefault()
            f[next].focus()
          }
        }
        ok.addEventListener('click', accept)
        cancel.addEventListener('click', dismiss)
        back.addEventListener('mousedown', function (e) { if (e.target === back) dismiss() })
        document.addEventListener('keydown', onKey, true)
        // 初始焦點：prompt ⇒ 輸入框；危險確認 ⇒ 取消（誤按 Enter 不會做下去）；一般確認 ⇒ 確定
        setTimeout(function () {
          var first = input || (opts.danger ? cancel : ok)
          first.focus()
          if (input) input.select()
        }, 0)
      })
    })
    queue = run.catch(function () {})
    return run
  }

  // ── toast ─────────────────────────────────────────────────────────────
  function toast(message, opts) {
    opts = opts || {}
    ensureStyle()
    var wrap = document.querySelector('.mui-toasts')
    if (!wrap) {
      wrap = el('div', 'mui-toasts')
      wrap.setAttribute('aria-live', 'polite')
      document.body.appendChild(wrap)
    }
    var t = el('div', 'mui-toast mui-toast--' + (opts.kind || 'info'), message)
    t.setAttribute('role', opts.kind === 'error' ? 'alert' : 'status')
    t.setAttribute('data-testid', 'ui-toast')
    t.setAttribute('data-kind', opts.kind || 'info')
    wrap.appendChild(t)
    var ms = opts.ms == null ? (opts.kind === 'error' ? 6000 : 3000) : opts.ms
    if (ms > 0) setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t) }, ms)
    return t
  }

  // ── banner（常駐，直到 close） ─────────────────────────────────────────
  var banners = {}
  function banner(message, opts) {
    opts = opts || {}
    ensureStyle()
    var wrap = document.querySelector('.mui-banners')
    if (!wrap) {
      wrap = el('div', 'mui-banners')
      document.body.appendChild(wrap)
    }
    if (opts.id && banners[opts.id]) banners[opts.id].close()
    var b = el('div', 'mui-banner mui-banner--' + (opts.kind || 'warn'))
    b.setAttribute('role', 'alert')
    b.setAttribute('data-testid', 'ui-banner')
    if (opts.id) b.setAttribute('data-banner-id', opts.id)
    b.appendChild(el('span', 'mui-banner__msg', message))
    var handle = {
      el: b,
      close: function () {
        if (b.parentNode) b.parentNode.removeChild(b)
        if (opts.id && banners[opts.id] === handle) delete banners[opts.id]
      },
    }
    if (opts.dismissible !== false) {
      var x = el('button', 'mui-banner__x', '×')
      x.type = 'button'
      x.setAttribute('aria-label', '關閉提示')
      x.setAttribute('data-testid', 'ui-banner-close')
      x.addEventListener('click', handle.close)
      b.appendChild(x)
    }
    wrap.appendChild(b)
    if (opts.id) banners[opts.id] = handle
    return handle
  }

  window.MotrixUI = {
    toast: toast,
    banner: banner,
    confirm: function (message, opts) { return openDialog('confirm', message, opts) },
    prompt: function (message, opts) { return openDialog('prompt', message, opts) },
  }
})()
