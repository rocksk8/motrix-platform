/* 「?」說明元件（選單去工程師化 批次 9；全站共用，設定中心先用，業務頁之後沿用）。
 *
 * 用法（頁面只放一個空殼，內容由資料檔 settings_help.json 經 API 傳來）：
 *   <span class="hint" data-hint='{"what":"…","when":"…","impact":"…","suggest":"…"}' data-hint-label="欄位名稱"></span>
 * 本檔會自動把 .hint[data-hint] 升級成「標籤旁 16px 的 ? 按鈕」：
 *   - 桌機：滑過或鍵盤聚焦顯示（點一下＝釘住，再點一下收起）。彈出框是 role="tooltip"，裡面沒有按鈕。
 *   - 手機（窄螢幕或觸控）：點一下開底部面板（role="dialog"）；點暗色背景、點「關閉」、按 Esc 都會收起。
 *     開啟時焦點移進面板（「關閉」鈕）並鎖在面板內，收起後焦點回到 ? 按鈕。
 *   - 鍵盤：Tab 可聚焦；Enter／Space 開關；Esc 關。aria-expanded／aria-controls／aria-describedby 都有。
 *   - 彈出內容四小段：這是什麼／什麼時候要改／改了會影響什麼／預設值與建議；缺的段落不顯示。內容一律用 textContent 寫入（不把資料當 HTML 解析）。
 * 開啟時彈出框與暗色背景都掛在 <body> 下、用 position:fixed 定位——不受祖先元素的 transform／filter／overflow 影響（業務頁沿用時也安全）；收起時放回原位。
 * 頁面用 Alpine 重畫時（data-hint 屬性變動、節點新增或移除）由 MutationObserver 自動重新升級或清理；沒有任何頁面專屬的程式碼。
 * 樣式在 css/hint-popover.css。 */
(function () {
  'use strict'
  var SECTIONS = [['what', '這是什麼'], ['when', '什麼時候要改'], ['impact', '改了會影響什麼'], ['suggest', '預設值與建議']]
  var seq = 0
  var openEl = null
  var closeTimer = null
  var backdrop = null

  function isSheet() {
    try { return window.matchMedia('(max-width: 767px), (pointer: coarse)').matches } catch (e) { return false }
  }

  function parse(el) {
    try { var d = JSON.parse(el.getAttribute('data-hint') || ''); return d && typeof d === 'object' ? d : null } catch (e) { return null }
  }

  function parts(el) { return { btn: el.querySelector('.hint__btn'), pop: el.__pop || el.querySelector('.hint__pop') } }

  function build(el, data) {
    if (openEl === el) hide(el)
    if (el.__pop && el.__pop.parentNode) el.__pop.parentNode.removeChild(el.__pop)
    var label = el.getAttribute('data-hint-label') || ''
    var id = el.getAttribute('data-hint-id') || ('hint-pop-' + (++seq))
    el.setAttribute('data-hint-id', id)
    el.textContent = ''
    var btn = document.createElement('button')
    btn.type = 'button'
    btn.className = 'hint__btn'
    btn.textContent = '?'
    btn.setAttribute('aria-label', label ? ('說明：' + label) : '說明')
    btn.setAttribute('aria-expanded', 'false')
    btn.setAttribute('aria-controls', id)
    btn.setAttribute('aria-describedby', id)
    var pop = document.createElement('div')
    pop.className = 'hint__pop'
    pop.id = id
    pop.setAttribute('role', 'tooltip')
    pop.hidden = true
    pop.__hintEl = el
    if (label) {
      var t = document.createElement('div')
      t.className = 'hint__title'
      t.textContent = label
      pop.appendChild(t)
    }
    SECTIONS.forEach(function (s) {
      var v = data[s[0]]
      if (typeof v !== 'string' || !v.trim()) return
      var row = document.createElement('div')
      row.className = 'hint__sec'
      var h = document.createElement('div')
      h.className = 'hint__h'
      h.textContent = s[1]
      var p = document.createElement('div')
      p.className = 'hint__p'
      p.textContent = v
      row.appendChild(h)
      row.appendChild(p)
      pop.appendChild(row)
    })
    el.appendChild(btn)
    el.appendChild(pop)
    el.__pop = pop
    el.setAttribute('data-hint-built', el.getAttribute('data-hint'))
  }

  function upgrade(el) {
    var raw = el.getAttribute('data-hint')
    if (!raw) {
      if (openEl === el) hide(el)
      el.textContent = ''
      el.__pop = null
      el.removeAttribute('data-hint-built')
      return
    }
    if (el.getAttribute('data-hint-built') === raw) return
    var data = parse(el)
    if (!data) return
    build(el, data)
  }

  function scan(root) {
    if (!root || !root.querySelectorAll) return
    if (root.matches && root.matches('.hint[data-hint]')) upgrade(root)
    var list = root.querySelectorAll('.hint[data-hint]')
    for (var i = 0; i < list.length; i++) upgrade(list[i])
  }

  function ensureBackdrop() {
    if (!backdrop) {
      backdrop = document.createElement('div')
      backdrop.className = 'hint__backdrop'
      backdrop.addEventListener('click', function () { if (openEl) hide(openEl, true) })
    }
    if (!backdrop.parentNode) document.body.appendChild(backdrop)
    return backdrop
  }

  function show(el) {
    if (openEl && openEl !== el) hide(openEl)
    var p = parts(el), pop = p.pop, btn = p.btn
    if (!pop || !btn) return
    window.clearTimeout(closeTimer)
    var sheet = isSheet()
    document.body.appendChild(pop)                          // 掛到 body：不受祖先 transform／filter／overflow 影響
    pop.hidden = false
    pop.classList.add('is-floating')
    pop.classList.toggle('is-sheet', sheet)
    el.classList.add('is-open')
    el.classList.toggle('is-sheet', sheet)
    btn.setAttribute('aria-expanded', 'true')
    openEl = el
    if (sheet) {
      pop.setAttribute('role', 'dialog')
      pop.setAttribute('aria-modal', 'true')
      var label = el.getAttribute('data-hint-label')
      if (label) pop.setAttribute('aria-label', '說明：' + label)
      var close = document.createElement('button')            // 關閉鈕只在手機面板裡才有（tooltip 裡不放按鈕）
      close.type = 'button'
      close.className = 'hint__close'
      close.textContent = '關閉'
      close.addEventListener('click', function () { hide(el, true) })
      pop.appendChild(close)
      ensureBackdrop().hidden = false
      el.__restoreFocus = btn
      close.focus()
    } else {
      place(btn, pop)
    }
  }

  function place(btn, pop) {            // 桌機：預設在按鈕下方；右邊放不下就往左靠、下面放不下就改放上方（fixed，用視窗座標）
    pop.style.left = '0px'; pop.style.top = '0px'
    var r = btn.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight
    var left = Math.max(12, Math.min(r.left, window.innerWidth - w - 12))
    var top = r.bottom + 6
    if (top + h > window.innerHeight - 8 && r.top - h - 6 > 8) top = r.top - h - 6
    pop.style.left = left + 'px'
    pop.style.top = top + 'px'
  }

  function hide(el, refocus) {
    if (!el) return
    var p = parts(el), pop = p.pop, btn = p.btn
    if (pop) {
      pop.hidden = true
      pop.classList.remove('is-floating', 'is-sheet')
      pop.style.left = ''; pop.style.top = ''
      pop.setAttribute('role', 'tooltip')
      pop.removeAttribute('aria-modal')
      pop.removeAttribute('aria-label')
      var c = pop.querySelector('.hint__close')
      if (c && c.parentNode) c.parentNode.removeChild(c)
      if (pop.parentNode === document.body) {                // 放回原位（原位已被移除就直接丟掉）
        if (el.isConnected) el.appendChild(pop); else document.body.removeChild(pop)
      }
    }
    el.classList.remove('is-open', 'is-sheet')
    el.removeAttribute('data-hint-pinned')
    if (btn) btn.setAttribute('aria-expanded', 'false')
    if (backdrop) backdrop.hidden = true
    if (openEl === el) openEl = null
    var back = el.__restoreFocus
    el.__restoreFocus = null
    if (refocus && back && back.isConnected) { try { back.focus() } catch (e) { /* 忽略 */ } }
  }

  function hintOf(node) {
    if (!node || !node.closest) return null
    var h = node.closest('.hint')
    if (h) return h
    var pop = node.closest('.hint__pop')            // 彈出框掛在 body 時，仍算是它那個 ? 的一部分
    return pop && pop.__hintEl ? pop.__hintEl : null
  }

  document.addEventListener('click', function (e) {
    var el = hintOf(e.target)
    if (el && e.target.closest('.hint__btn')) {
      e.preventDefault()
      if (isSheet()) { if (el.classList.contains('is-open')) hide(el, true); else show(el); return }
      // 桌機：滑過／聚焦已經打開時，點一下＝「釘住」（不會因為滑鼠移開而收起）；再點一下才收起
      if (!el.classList.contains('is-open')) { show(el); el.setAttribute('data-hint-pinned', '1') }
      else if (el.getAttribute('data-hint-pinned') !== '1') el.setAttribute('data-hint-pinned', '1')
      else hide(el)
      return
    }
    if (!el && openEl) hide(openEl)                           // 點外面收起（手機的暗色背景另有自己的處理）
  })
  document.addEventListener('keydown', function (e) {
    if (!openEl) return
    if (e.key === 'Escape') { hide(openEl, true); return }
    if (e.key === 'Tab' && openEl.classList.contains('is-sheet')) {        // 手機面板：焦點鎖在面板內
      var close = openEl.__pop && openEl.__pop.querySelector('.hint__close')
      if (close) { e.preventDefault(); close.focus() }
    }
  })
  document.addEventListener('mouseover', function (e) {
    if (isSheet()) return
    var el = hintOf(e.target)
    if (el && e.target.closest('.hint__btn, .hint__pop') && !el.classList.contains('is-open')) show(el)
    else if (el) window.clearTimeout(closeTimer)
  })
  document.addEventListener('mouseout', function (e) {
    if (isSheet()) return
    var el = hintOf(e.target)
    if (el && el.classList.contains('is-open') && el.getAttribute('data-hint-pinned') !== '1' && !hintOf(e.relatedTarget)) {
      window.clearTimeout(closeTimer)
      closeTimer = window.setTimeout(function () { hide(el) }, 150)
    }
  })
  document.addEventListener('focusin', function (e) {
    var el = hintOf(e.target)
    if (el && e.target.closest('.hint__btn') && !isSheet() && !el.classList.contains('is-open')) show(el)
  })
  document.addEventListener('focusout', function (e) {
    var el = hintOf(e.target)
    if (el && el.classList.contains('is-open') && el.getAttribute('data-hint-pinned') !== '1' && !isSheet() && !hintOf(e.relatedTarget)) hide(el)
  })
  window.addEventListener('resize', function () {
    if (!openEl) return
    var p = parts(openEl)
    if (!isSheet() && p.btn && p.pop) place(p.btn, p.pop)
  })

  function boot() {
    scan(document.body)
    new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        if (m.type === 'attributes') { if (m.target.matches && m.target.matches('.hint')) upgrade(m.target) }
        else {
          m.addedNodes.forEach(function (n) { if (n.nodeType === 1) scan(n) })
          if (openEl && !openEl.isConnected) hide(openEl)        // 開著的那個 ? 被頁面移除了：清掉掛在 body 的彈出框
        }
      })
    }).observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-hint'] })
  }
  if (document.body) boot(); else document.addEventListener('DOMContentLoaded', boot)
  window.MotrixHint = { scan: scan, hide: function () { hide(openEl, true) } }
})()
