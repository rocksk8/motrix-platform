/*!
 * MOTRIX ERP — Shared Layout Module
 * Builds topbar + sidebar from session. Handles mobile slide-in toggle.
 * Load at end of <body> (after notif.js).
 */
/* ── 這一次的 /api/auth/me 回應，可不可以拿來覆寫既有的 session？ ──────────
 *
 * 🔴 缺陷（2026-09-22 §4 YB）：這裡原本只擋 `null`
 *      if (!d) return
 *      stored.modules = d.modules        // ← undefined 時把既有值蓋掉
 *    ⇒ 一次「200 但缺欄位」的回應就把權限洗空，畫面變「你沒有這個頁面的權限」。
 *
 * ☠️ 而真正難查的是那個**不對稱**：
 *      :909  mods = Array.isArray(d.modules) ? d.modules : []   ← 有防護
 *      :903  stored.modules = d.modules                          ← 沒有
 *    ⇒ 當下那一頁自己恢復了，**而存下來的值已經被洗掉** ⇒ 下一次載入才爆。
 *    🔑 「重新載入不會自己好，要載入兩次」就是這個不對稱的指紋。
 *    ⇒ 修法不是在兩個地方各補一次判斷，是**讓它們共用同一個決定**。
 *
 * 🔑 而這個決定最容易寫錯的地方是 `[]`：
 *      modules: []          真的沒有模組（權限被拿掉了）⇒ **要**覆寫
 *      modules: undefined   這次回應沒帶                ⇒ **不可以**覆寫
 *    ☠️ `if (d.modules)` 會把合法的 `[]` 當成「沒帶」
 *    ⇒ **真正的權限撤銷永遠生效不了** —— 管理員把某人的模組全拿掉，
 *      而那個人的瀏覽器永遠停在舊權限上。
 *
 * 📌 它是**純函式**（沒有 DOM、沒有 fetch、沒有 localStorage）——
 *    那是為了讓它在 node 裡被直接問答案。行為不對的話，
 *    在瀏覽器裡量到的與在 node 裡量到的會不一樣，而那會讓那些綠燈失去意義。
 */
function acceptsSessionUpdate(d) {
  if (!d || typeof d !== 'object') return false
  // ⚠️ 用 `Array.isArray` 不用真假值 —— `[]` 是合法的。
  if (!Array.isArray(d.modules)) return false
  if (typeof d.role !== 'string' || !d.role) return false
  return true
}

/* 匯出：瀏覽器走 globalThis，node 走 module.exports。
 * ⚠️ 兩個都要，而且要在下面那個 IIFE **之前** ——
 *    IIFE 第一行就碰 `localStorage`，在 node 裡會丟，
 *    而丟出去之後 `module.exports` 就拿不到了；`globalThis` 的賦值留得住。
 * 🔑 「它載入失敗」與「它不存在」是兩件事，而這個順序讓前者仍然問得到答案。 */
if (typeof globalThis !== 'undefined') {
  globalThis.MotrixSession = globalThis.MotrixSession || {}
  globalThis.MotrixSession.acceptsSessionUpdate = acceptsSessionUpdate
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports.acceptsSessionUpdate = acceptsSessionUpdate
}

;(function () {
  // ── Session & path ──────────────────────────────────────────────────────────
  var raw  = localStorage.getItem('motrix_session')
  var s    = raw ? JSON.parse(raw) : {}
  var role = s.role    || ''
  var mods = Array.isArray(s.modules) ? s.modules : []
  var dn   = s.displayName || s.username || ''
  var av   = (dn || '?')[0]

  // ── Font zoom（立即套用，避免頁面閃爍）──────────────────────────────────────
  var FZ_KEY   = 'motrix_font_zoom'
  var FZ_STEPS = [
    { v: 0.85, label: '小' },
    { v: 1.0,  label: '標' },
    { v: 1.15, label: '大' },
    { v: 1.3,  label: '特' }
  ]
  var _initZoom = parseFloat(localStorage.getItem(FZ_KEY)) || 1.0
  document.documentElement.style.zoom = _initZoom
  // 字級「特」：根元素 zoom 會把 vh／dvh 一起放大 ⇒ 以視窗高度限高的元素超出畫面。
  // 各頁的 `Nvh` 已改寫成 `calc(Nvh / var(--fz,1))`，這裡把目前倍率交給 CSS。
  document.documentElement.style.setProperty('--fz', String(_initZoom))

  // ── Dark mode（立即套用，避免頁面閃爍；各頁 <head> 亦有相同邏輯的同步腳本先跑過一次）──
  var THEME_KEY = 'motrix_theme'
  if (localStorage.getItem(THEME_KEY) === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark')
  }

  var path = window.location.pathname
  var file = path.split('/').pop() || 'index.html'
  var inPg = path.indexOf('/pages/') >= 0
  var up   = inPg ? '../' : ''

  // 強制改密：除修改密碼頁外一律導向
  if (s.mustChangePassword && file !== 'change-password.html' && file !== 'login.html') {
    window.location.replace(inPg ? 'change-password.html?forced=1' : 'pages/change-password.html?forced=1')
  }

  function pg(f) { return inPg ? f : 'pages/' + f }
  function esc(t) { return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') }
  // 頂欄顯示的頁面名稱（2026-09-14）。
  // 各頁的 <title> 格式是「頁名 — MOTRIX 專案管理系統」，直接取前半段；
  // **刻意不另外維護一份 file → label 對照表**，那種表跟頁面遲早會對不起來。
  // 首頁的 title 是倒過來的（「MOTRIX 專案管理系統 — 營運儀表板」），
  // 切出來是系統名，正好就是首頁該顯示的東西。
  function _pageName() {
    // 大部分頁面用破折號分隔，但 quotation-form / dev-crm /
    // completion-note-form 這三頁用的是半形連字號。兩種都要吃，
    // 否則整串 title 會被當成頁名塞進頂欄、把 logo 蒟掉。
    var t = (document.title || '')
    var i = t.indexOf('\u2014')
    if (i < 0) i = t.indexOf(' - ')
    t = (i >= 0 ? t.slice(0, i) : t).trim()
    return t || 'MOTRIX 專案管理系統'
  }

  function act(names) {
    for (var i = 0; i < names.length; i++) {
      if (file === names[i]) return ' active'
    }
    return ''
  }

  // ── Global font zoom (used by topbar buttons via onclick) ─────────────────
  window.motrixSetZoom = function (z) {
    localStorage.setItem(FZ_KEY, String(z))
    document.documentElement.style.zoom = z
    document.documentElement.style.setProperty('--fz', String(z))
    FZ_STEPS.forEach(function (step, i) {
      var btn = document.getElementById('fz-' + i)
      if (!btn) return
      var on = Math.abs(step.v - z) < 0.01
      btn.style.background  = on ? 'rgba(255,255,255,0.18)' : 'transparent'
      btn.style.color       = on ? '#F5F4F0' : '#666'
      btn.style.fontWeight  = on ? '700' : '400'
    })
  }

  // ── Global dark mode toggle (used by topbar button via onclick) ───────────
  window.motrixToggleTheme = function () {
    var dark = document.documentElement.getAttribute('data-theme') === 'dark'
    var next = !dark
    if (next) {
      document.documentElement.setAttribute('data-theme', 'dark')
      localStorage.setItem(THEME_KEY, 'dark')
    } else {
      document.documentElement.removeAttribute('data-theme')
      localStorage.removeItem(THEME_KEY)
    }
    var btn = document.getElementById('theme-toggle-btn')
    if (btn) btn.innerHTML = _themeIcon(next)
  }

  function _themeIcon(isDark) {
    // isDark: 目前已是深色模式 → 顯示太陽（點擊可切回淺色）；反之顯示月亮
    return isDark
      ? '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>'
      : '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>'
  }

  function buildThemeToggle() {
    var isDark = document.documentElement.getAttribute('data-theme') === 'dark'
    return '<button id="theme-toggle-btn" class="topbar__btn" onclick="motrixToggleTheme()"'
      + ' title="切換深色/淺色模式" style="padding:6px 8px">'
      + _themeIcon(isDark)
      + '</button>'
  }

  // ── Global logout (used by topbar button via onclick) ─────────────────────
  window.motrixLogout = function () {
    var sess = JSON.parse(localStorage.getItem('motrix_session') || '{}')
    if (sess.token) {
      fetch('/api/auth/logout', {
        method:  'POST',
        headers: { Authorization: 'Bearer ' + sess.token }
      }).catch(function () {})
    }
    localStorage.removeItem('motrix_session')
    window.location.href = inPg ? 'login.html' : 'pages/login.html'
  }

  // ── Font size control widget ───────────────────────────────────────────────
  function buildFontCtrl() {
    var curZ = parseFloat(localStorage.getItem(FZ_KEY)) || 1.0
    var btns = FZ_STEPS.map(function (step, i) {
      var on = Math.abs(step.v - curZ) < 0.01
      return '<button id="fz-' + i + '"'
        + ' onclick="motrixSetZoom(' + step.v + ')"'
        + ' title="字體大小：' + step.label + '"'
        + ' style="'
        + 'background:' + (on ? 'rgba(255,255,255,0.18)' : 'transparent') + ';'
        + 'color:' + (on ? '#F5F4F0' : '#666') + ';'
        + 'font-weight:' + (on ? '700' : '400') + ';'
        + 'border:none;cursor:pointer;font-size:11px;font-family:LINE Seed TW_OTF, sans-serif;'
        + 'padding:0 7px;height:22px;line-height:22px;border-radius:3px;'
        + 'transition:background .15s,color .15s">'
        + step.label
        + '</button>'
    }).join('')
    return '<div style="display:flex;align-items:center;border:1px solid #333;border-radius:4px;overflow:hidden;margin-right:4px" title="調整字體大小">'
      + btns
      + '</div>'
  }

  // ── 全域搜尋（跨客戶/供應商/報價單/業務開發案/料號）──────────────────────────
  function buildGlobalSearch() {
    return `
      <div x-data="globalSearchStore()" x-init="init()" style="position:relative;flex:1;max-width:320px;margin:0 14px">
        <div style="position:relative">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#888" stroke-width="2" style="position:absolute;left:9px;top:50%;transform:translateY(-50%);pointer-events:none"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
          <input type="text" class="global-search-input" x-model="q" @input="onInput()" @focus="q && (open = true)" @keydown.escape="close()"
                 placeholder="搜尋客戶／報價單／案件／料號…"
                 style="width:100%;padding:6px 10px 6px 28px;border:1px solid #333;border-radius:5px;background:#1a1a1a;color:#eee;font-size:12px;outline:none;box-sizing:border-box">
        </div>
        <div x-show="open" @click.outside="close()" x-cloak
             style="display:none;position:absolute;top:calc(100% + 6px);left:0;width:340px;background:#fff;border:1px solid var(--border);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.13);z-index:999;max-height:420px;overflow-y:auto">
          <template x-if="!loading && !hasResults">
            <div style="padding:20px;text-align:center;font-size:12px;color:var(--text-dim)">查無符合結果</div>
          </template>
          <template x-if="results.quotations.length">
            <div style="border-bottom:1px solid var(--border-light)">
              <div style="padding:8px 14px 4px;font-size:10px;color:var(--text-dim);font-weight:600">報價單</div>
              <template x-for="item in results.quotations" :key="'quote-'+item.quoteNo">
                <div @click="goQuotation(item.quoteNo)" style="padding:7px 14px;cursor:pointer" @mouseenter="$el.style.background='#FAFAF8'" @mouseleave="$el.style.background=''">
                  <div style="font-size:12px;font-weight:600;color:var(--text-main)" x-text="item.quoteNo + '　' + (item.customerName || '—')"></div>
                  <div style="font-size:10px;color:var(--text-dim)" x-text="item.projectName || item.status || ''"></div>
                </div>
              </template>
            </div>
          </template>
          <template x-if="results.devCases.length">
            <div style="border-bottom:1px solid var(--border-light)">
              <div style="padding:8px 14px 4px;font-size:10px;color:var(--text-dim);font-weight:600">業務開發案</div>
              <template x-for="item in results.devCases" :key="'dc-'+item.id">
                <div @click="goDevCase()" style="padding:7px 14px;cursor:pointer" @mouseenter="$el.style.background='#FAFAF8'" @mouseleave="$el.style.background=''">
                  <div style="font-size:12px;font-weight:600;color:var(--text-main)" x-text="item.caseName"></div>
                  <div style="font-size:10px;color:var(--text-dim)" x-text="(item.customerName || '—') + '　' + item.status"></div>
                </div>
              </template>
            </div>
          </template>
          <template x-if="results.customers.length">
            <div style="border-bottom:1px solid var(--border-light)">
              <div style="padding:8px 14px 4px;font-size:10px;color:var(--text-dim);font-weight:600">客戶</div>
              <template x-for="item in results.customers" :key="'c-'+item.id">
                <div @click="goCustomer()" style="padding:7px 14px;cursor:pointer" @mouseenter="$el.style.background='#FAFAF8'" @mouseleave="$el.style.background=''">
                  <div style="font-size:12px;font-weight:600;color:var(--text-main)" x-text="item.name"></div>
                  <div style="font-size:10px;color:var(--text-dim)" x-text="item.code"></div>
                </div>
              </template>
            </div>
          </template>
          <template x-if="results.suppliers.length">
            <div style="border-bottom:1px solid var(--border-light)">
              <div style="padding:8px 14px 4px;font-size:10px;color:var(--text-dim);font-weight:600">供應商</div>
              <template x-for="item in results.suppliers" :key="'s-'+item.id">
                <div @click="goSupplier()" style="padding:7px 14px;cursor:pointer" @mouseenter="$el.style.background='#FAFAF8'" @mouseleave="$el.style.background=''">
                  <div style="font-size:12px;font-weight:600;color:var(--text-main)" x-text="item.name"></div>
                  <div style="font-size:10px;color:var(--text-dim)" x-text="item.code"></div>
                </div>
              </template>
            </div>
          </template>
          <template x-if="results.parts.length">
            <div>
              <div style="padding:8px 14px 4px;font-size:10px;color:var(--text-dim);font-weight:600">料號</div>
              <template x-for="item in results.parts" :key="'p-'+item.partNo">
                <div @click="goPart()" style="padding:7px 14px;cursor:pointer" @mouseenter="$el.style.background='#FAFAF8'" @mouseleave="$el.style.background=''">
                  <div style="font-size:12px;font-weight:600;color:var(--text-main)" x-text="item.partNo + '　' + item.name"></div>
                  <div style="font-size:10px;color:var(--text-dim)" x-text="item.brand"></div>
                </div>
              </template>
            </div>
          </template>
        </div>
      </div>
    `
  }

  // ── Topbar ─────────────────────────────────────────────────────────────────
  // ── 在線成員（2026-09-14，僅最高管理者）─────────────────────────────────
  //
  // 使用者要求「右上角可顯示在線成員跟數量」。刻意做成**輪詢 /api/online-users**
  // 而不是心跳或 WebSocket：
  //   ①「在線」的資料來源是 sessions.last_active，那個欄位本來就在更新，不需要
  //     為了這個功能讓每個閒置分頁定時打伺服器
  //   ② 這是內網 ERP，60 秒的延遲對「誰在線上」完全夠用，不值得為它常駐連線
  // 精度上限就是 last_active 的節流（5 分鐘），所以剛登入的人最慢 5 分鐘後才出現，
  // 這一點寫在下拉選單的說明文字裡，免得有人以為是壞掉。
  function buildOnlineWidget() {
    if (!sa) return ''
    return '<div id="tb-online-wrap" style="position:relative">'
      + '<button class="topbar__btn" id="tb-online-btn" title="在線成員" style="color:#888;border-color:#333;font-size:11px">'
      + '<span style="width:7px;height:7px;border-radius:50%;background:#22C55E;display:inline-block;margin-right:5px"></span>'
      + '在線 <span id="tb-online-count" style="font-family:LINE Seed TW_OTF, sans-serif;font-weight:700;margin-left:3px">–</span>'
      + '</button>'
      + '<div id="tb-online-pop" style="display:none;position:absolute;top:calc(100% + 6px);right:0;width:280px;background:#fff;'
      + 'border:1px solid var(--border);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.13);z-index:999;overflow:hidden">'
      + '<div style="padding:11px 16px;border-bottom:1px solid var(--border-light);font-size:13px;font-weight:600;color:var(--text-main)">目前在線</div>'
      + '<div id="tb-online-list" style="max-height:320px;overflow-y:auto"></div>'
      + '<div style="padding:8px 16px;border-top:1px solid var(--border-light);font-size:10px;color:var(--text-dim);line-height:1.7">'
      + '依最後活動時間判定（5 分鐘內），最慢 5 分鐘更新一次</div>'
      + '<a href="' + pg('online-stats.html') + '" style="display:block;padding:9px 16px;text-align:center;font-size:12px;color:var(--accent);border-top:1px solid var(--border-light);text-decoration:none;font-weight:500">查看在線時數統計 →</a>'
      + '</div></div>'
  }

  function _roleLabel(r) {
    return { superadmin: '最高管理者', admin: '管理員', sales: '業務', engineer: '工程師', viewer: '檢視者' }[r] || r
  }

  function refreshOnlineWidget() {
    if (!sa) return
    var btn = document.getElementById('tb-online-btn')
    if (!btn) return
    fetch('/api/online-users', { headers: { Authorization: 'Bearer ' + s.token } })
      .then(function (r) { return r.ok ? r.json() : null })
      .then(function (d) {
        if (!d) return
        var cnt = document.getElementById('tb-online-count')
        if (cnt) cnt.textContent = d.count
        var list = document.getElementById('tb-online-list')
        if (!list) return
        if (!d.users.length) {
          list.innerHTML = '<div style="padding:20px;text-align:center;font-size:12px;color:var(--text-dim)">目前沒有其他人在線</div>'
          return
        }
        list.innerHTML = d.users.map(function (u) {
          var mins = Math.floor(u.secondsAgo / 60)
          var ago = mins <= 0 ? '剛剛' : mins + ' 分鐘前'
          return '<div style="padding:9px 16px;border-bottom:1px solid var(--border-light);display:flex;align-items:center;gap:8px">'
            + '<span style="width:7px;height:7px;border-radius:50%;background:#22C55E;flex:0 0 auto"></span>'
            + '<div style="min-width:0;flex:1">'
            + '<div style="font-size:12px;color:var(--text-main);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
            + esc(u.displayName) + '<span style="color:var(--text-dim);font-size:10px;margin-left:6px">' + esc(_roleLabel(u.role)) + '</span></div>'
            + '<div style="font-size:10px;color:var(--text-dim);font-family:LINE Seed TW_OTF, sans-serif">' + ago + '</div>'
            + '</div></div>'
        }).join('')
      })
      .catch(function () {})
  }

  function bindOnlineWidget() {
    var btn = document.getElementById('tb-online-btn')
    var pop = document.getElementById('tb-online-pop')
    if (!btn || !pop) return
    btn.addEventListener('click', function (e) {
      e.stopPropagation()
      pop.style.display = pop.style.display === 'none' ? 'block' : 'none'
      if (pop.style.display === 'block') refreshOnlineWidget()
    })
    document.addEventListener('click', function (e) {
      if (!document.getElementById('tb-online-wrap')) return
      if (!document.getElementById('tb-online-wrap').contains(e.target)) pop.style.display = 'none'
    })
  }

  function buildTopbar() {
    var el = document.getElementById('app-topbar')
    if (!el) {
      // 🔴 這一行原本只是 `if (!el) return` —— **安靜地什麼都不做**。
      //
      // ☠️ 2026-09-22：`map.html` 從來沒有 `#app-topbar`（`6e4dcc9` 建那一頁
      //    時漏的），而使用者看到的是「logo／搜尋列／通知整個欄位都沒有」。
      //    沒有錯誤、沒有空白框 ⇒ **畫面看起來像那一頁本來就長那樣**
      //    ⇒ 它安靜了整整一天，而那一天裡我們出了一個包。
      //
      // 🔑 而**不能一律報錯**：login／轉址頁是**合法的沒有**。
      //    ⇒ 用一個明著的宣告把兩者分開：`<body data-no-topbar>`。
      //    📌 「刻意沒有」與「忘了加」先前是同一件事，這一行把它們拆開。
      //
      // ⚠️ **不丟例外**：頂欄缺了不該讓整頁的側邊欄也跟著不渲染 ——
      //    那會把一個「少一條列」的問題變成「整頁壞掉」。
      if (!document.body || !document.body.hasAttribute('data-no-topbar')) {
        try {
          console.error('[sidebar] 找不到 #app-topbar 掛載點，頂欄不會顯示：'
            + location.pathname
            + '　⇒ 這一頁若刻意不要頂欄，請在 <body> 加 data-no-topbar')
        } catch (_e) { /* console 不可用時不要再炸一次 */ }
      }
      return
    }

    var cpHref = inPg ? 'change-password.html' : 'pages/change-password.html'

    // Notification bell — admin/superadmin only
    var bell = ''
    if (ad) {
    bell =
      '<div x-data="notifStore()" x-init="init()" style="position:relative">'
      + '<button class="topbar__btn" @click="toggle()" style="position:relative">'
      + '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6 6 0 10-12 0v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/></svg>'
      + '通知'
      + '<span x-show="unread>0" x-text="unread>9?\'9+\':unread"'
      + ' style="background:var(--danger);color:#fff;font-size:9px;padding:1px 5px;border-radius:8px;font-family:LINE Seed TW_OTF, sans-serif;font-weight:700;min-width:16px;text-align:center"></span>'
      + '</button>'
      + '<div x-show="open" @click.outside="open=false"'
      + ' style="display:none;position:absolute;top:calc(100% + 6px);right:0;width:310px;background:#fff;border:1px solid var(--border);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.13);z-index:999;overflow:hidden">'
      // UR1：下拉列的是**通知本身**（原本是近期操作紀錄，而紅色數字數的是通知 ⇒ 兩者對不起來）。
      //      點一則 ⇒ 當下只把那一則標成已讀（`markOne`），打開下拉不再全部清掉。
      + '<div style="display:flex;justify-content:space-between;align-items:center;padding:11px 16px;border-bottom:1px solid var(--border-light)">'
      + '<span style="font-size:13px;font-weight:600;color:var(--text-main)">通知</span>'
      + '<button type="button" x-show="unread>0" @click="markAllNotifications()" data-notif-all'
      + ' style="background:none;border:none;color:var(--accent);font-size:11px;cursor:pointer;padding:0">全部標為已讀</button>'
      + '</div>'
      + '<div style="max-height:320px;overflow-y:auto">'
      + '<template x-for="item in items" :key="item.id">'
      + '<div @click="markOne(item)" :data-notif-id="item.id" :data-unread="item.is_read ? 0 : 1"'
      + ' :style="`padding:10px 16px;border-bottom:1px solid var(--border-light);cursor:pointer;${item.is_read ? \'\' : \'background:#FFF7ED\'}`">'
      + '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px">'
      + '<span x-text="item.ref_label||\'通知\'" :style="`font-size:12px;font-weight:${item.is_read ? 400 : 700};color:var(--text-main);overflow:hidden;text-overflow:ellipsis;white-space:nowrap`"></span>'
      + '<span x-text="formatTime(item.created_at)" style="font-size:10px;color:var(--text-dim);font-family:LINE Seed TW_OTF, sans-serif;flex-shrink:0"></span>'
      + '</div>'
      + '<div x-text="item.message" style="font-size:11px;color:var(--text-secondary);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></div>'
      + '</div>'
      + '</template>'
      + '<div x-show="items.length===0" style="padding:20px;text-align:center;font-size:12px;color:var(--text-dim)">目前沒有通知</div>'
      + '</div>'
      + '<a :href="auditHref" style="display:block;padding:9px 16px;text-align:center;font-size:12px;color:var(--accent);border-top:1px solid var(--border-light);text-decoration:none;font-weight:500">查看操作紀錄 →</a>'
      + '</div>'
      + '</div>'
    } // end if (ad)

    el.innerHTML =
      '<button class="sidebar-toggle" id="sidebar-toggle" aria-label="選單" title="選單">'
      + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:20px;height:20px;"><path d="M4 6h16M4 12h16M4 18h16"/></svg>'
      + '</button>'
      + '<a href="' + up + 'index.html" class="topbar__logo">'
      + '<img src="' + up + 'static/logo.png" alt="MOTRIX" style="height:26px"'
      + ' onerror="this.replaceWith(Object.assign(document.createElement(\'span\'),{textContent:\'MOTRIX\',style:\'color:#F5F4F0;font-family:LINE Seed TW_OTF, sans-serif;font-weight:700;font-size:15px;letter-spacing:.08em\'}))">'
      + '</a>'
      + '<div class="topbar__divider"></div>'
      + '<span class="topbar__title">' + esc(_pageName()) + '</span>'
      + buildGlobalSearch()
      + '<div class="topbar__right">'
      + '<span id="tb-display-name" style="font-size:12px;color:#888;font-family:LINE Seed TW_OTF, sans-serif">' + esc(dn) + '</span>'
      + buildFontCtrl()
      + buildThemeToggle()
      + buildOnlineWidget()
      + bell
      + '<a href="' + cpHref + '" class="topbar__btn" style="text-decoration:none;color:#888;border-color:#333;font-size:11px">修改密碼</a>'
      + '<button class="topbar__btn" onclick="motrixLogout()" style="color:#888;border-color:#333;font-size:11px">登出</button>'
      + '<div class="topbar__avatar">' + esc(av) + '</div>'
      + '</div>'

    // Process Alpine directives in the injected topbar (notifStore x-data)
    if (window.Alpine && window.Alpine.initTree) window.Alpine.initTree(el)
    bindOnlineWidget()
    refreshOnlineWidget()
    if (sa) setInterval(refreshOnlineWidget, 60000)
  }

  // ── Sidebar ─────────────────────────────────────────────────────────────────
  // ── 2026-09-14：取消 admin 直通，全站改成純模組判定 ──────────────────────
  //
  // 使用者裁示：「管理者一樣依據有開權限的內容去顯示，沒開的就不顯示，包含模組
  // 名稱。超級管理者預設全開，使用者部分看模組內容去檢核，未開啟的直接不顯示」。
  //
  // 在此之前這 20 幾個旗標一律長成 `mods.indexOf(x) >= 0 || ad`，等於 admin 與
  // superadmin 看到的東西完全一樣、模組勾選對他們毫無作用。真正的代價不是
  // 「admin 看得太多」，而是**沒有人發現既有 admin 帳號的模組清單早就過時了**
  // ——2026-08／09 陸續新增的模組（監控／門禁／閘道器／自動化選型導覽、出納、
  // 網路架構規劃書）加進了角色樣板，既有帳號卻從來沒補過，只因為 admin 直通
  // 所以完全看不出來。DB v84 已把那批帳號補齊，這裡才敢把直通拿掉。
  //
  // 同一輪也拿掉另外兩種「不是模組」的放行（v84 一併補進對應帳號的模組清單，
  // 所以沒有人會因此少掉今天看得到的東西）：
  //   `|| eng`             工程師無條件看到案件管理
  //   `|| role !== 'viewer'` 非檢視者無條件看到工作日誌／每日工作事項
  //
  // **只剩 `sa` 一個直通**，對應「超級管理者預設全開」。
  //
  // 分組名稱不需要另外處理：renderMainNav() 已經會過濾掉 items 為空的分組，
  // 所以整組都沒權限時連分組名稱都不會出現（＝裁示裡的「包含模組名稱」）。
  //
  // **只在這一個地方算**（2026-09-14）：原本這段在檔案裡有**兩份**——這裡一份、
  // `_refreshSession()` 裡再抄一份供「模組被改過就即時重建選單」使用。兩份已經
  // 漂掉了：下面那份漏了 `cCon`／`cPay`／`cNetPlan` 三個旗標，所以 session 更新
  // 後那三項會停在舊值。收斂成一支 computeFlags()，兩邊共用。
  var sa, ad, has
  var cQ, cCu, cPr, cFi, cCash, cCM, cEq, cInv, cRpt, cWL, cDT, cDev, cCon, cPay
  var cNetPlan
  var cAudit, cShipLog, cVer, cSet, canDash

  function computeFlags() {
    sa  = role === 'superadmin'
    has = function (k) { return sa || mods.indexOf(k) >= 0 }
    // `ad` 只剩通知鈴鐺在用（那是角色功能不是模組），其餘一律走 has()
    ad  = sa || role === 'admin'

    cQ   = has('quotation')
    cCu  = has('customer')
    cPr  = has('procurement')
    cFi  = has('finance')
    cCash = has('cashier')
    cCM  = has('case_manage')
    cEq  = has('equipment')
    cInv = has('inventory')
    cRpt = has('reports')
    cWL  = has('work_log')
    cDT  = has('daily_task')
    cDev = has('dev_crm')
    cTdr = has('tender_radar')
    cMap = has('map')            // 地圖是共用能力，刻意不綁 tender_radar
    cCon = has('contractor_list')
    cPay = has('payslip')
    // 檢視或編輯任一即可看到入口（編輯權當然也看得到）
    cNetPlan = has('netplan') || has('netplan_edit')
    // 四個原本沒有模組 key、只能靠角色寫死的稽核／維運頁（2026-09-14 使用者裁示
    // 「沒有對應模組 key 也建立就沒有這個問題」）
    cAudit = has('audit_log')
    cShipLog = has('shipping_export_log')
    cVer = has('module_versions')
    cSet = has('settings')

    canDash = has('dashboard') || has('finance') || has('quotation')
  }
  computeFlags()

  var ic = {
    dash:  '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    bdev:  '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>',
    appr:  '<path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>',
    apprhist: '<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 106 5.3L3 8"/><path d="M12 7v5l3 2"/>',
    wlog:  '<path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>',
    quote: '<path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0119 9.414V19a2 2 0 01-2 2z"/>',
    cust:  '<path d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0"/>',
    case_: '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/>',
    proj:  '<path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>',
    order: '<path d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2 9m12-9l2 9M9 21h6"/>',
    part:  '<path d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10"/>',
    inv:   '<path d="M21 8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><path d="M3.27 6.96L12 12l8.73-5.04M12 22.08V12"/>',
    proc:  '<path d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18"/>',
    supp:  '<path d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-2 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>',
    dev:   '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    warr:  '<path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>',
    recv:  '<path d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1"/>',
    cash:  '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M6 6v.01M18 6v.01M6 18v-.01M18 18v-.01"/>',
    rpt:   '<path d="M9 17v-2m3 2v-4m3 4v-6M3 21h18M3 10l9-7 9 7M12 3v1"/>',
    users: '<path d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>',
    org:   '<path d="M3 21h18M5 21V7l7-4 7 4v14M9 9h1m-1 4h1m4-4h1m-1 4h1M9 21v-4h6v4"/>',
    sett:  '<path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><circle cx="12" cy="12" r="3"/>',
    hist:  '<path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0119 9.414V19a2 2 0 01-2 2z"/>',
    ntfy:  '<path d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>',
    dtask: '<path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"/>',
    ver:   '<path d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A2 2 0 013 12V7a4 4 0 014-4z"/>',
    vend:  '<path d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>',
    contl: '<path d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0"/>',
    paysl: '<path d="M17 9V7a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2m2 4h10a2 2 0 002-2v-6a2 2 0 00-2-2H9a2 2 0 00-2 2v6a2 2 0 002 2zm7-5a2 2 0 11-4 0 2 2 0 014 0z"/>',
    schema: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.657 4.03 3 9 3s9-1.343 9-3V5"/><path d="M3 11v6c0 1.657 4.03 3 9 3s9-1.343 9-3v-6"/>',
    gcal: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    netplan: '<rect x="9" y="2" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="16" y="16" width="6" height="6" rx="1"/><path d="M12 8v4M12 12H5v4M12 12h7v4"/>',
  }

  // Module → localStorage key map (used to mark current page's module as "seen")
  var _FILE_MODULE = {
    'dev-crm.html':            'dev_crm',
    'tender-radar.html':       'tender_radar',
    'map.html':                'map',
    'quotations.html':         'quotation',
    'quotation-form.html':     'quotation',
    'approval-queue.html':     'quotation',
    'approval-history.html':   'quotation',
    'case-management.html':    'case_manage',
    'case-stage-board.html':   'case_manage',
    'customers.html':          'customer',
    'customer-log.html':       'customer',
    'suppliers.html':          'procurement',
    'supplier-log.html':       'procurement',
    'vendor-contractors.html': 'procurement',
    'parts.html':              'procurement',
    'inventory.html':          'procurement',
    'procurement.html':        'procurement',
    'devices.html':            'equipment',
    'warranty.html':           'equipment',
    'network-plans.html':      'netplan_edit',
    'network-plan-form.html':  'netplan_edit',
    'topology-quick.html':     'netplan_edit',
    // 這兩頁 2026-08-31（87e16cb）已退役成導向頁，留著對應只是為了舊書籤
    // 進來時仍能把 finance 模組標成已讀（導向前會先跑到這段）。
    'receivables.html':        'finance',
    'sales-orders.html':       'finance',
    'reports.html':            'finance',
    'work-log.html':           'work_log',
    'daily-tasks.html':        'daily_task',
  }

  var _SB_BADGE_STYLE = 'display:none;background:var(--accent);color:#fff;font-size:9px;font-weight:700;font-family:LINE Seed TW_OTF, sans-serif;padding:1px 5px;border-radius:8px;margin-left:auto;min-width:16px;text-align:center;line-height:1.6'

  // 2026-09-13（模組權限稽核）：頁面層守門的資料來源。
  //
  // 在此之前前端**沒有任何頁面層檢查**——`auth-guard.js` 只驗 session，沒有某個
  // 模組的人手打網址照樣打得開那一頁（只是資料會被 API 擋成一片 403，畫面看起來
  // 像壞掉而不是像沒權限）。
  //
  // 刻意不另外維護一份「頁面→模組」對照表：那會跟下面 ni() 的顯示條件漂移，而
  // 漂移的症狀就是這次盤點抓到的那一堆。改成**直接沿用同一組條件**——側欄決定
  // 不顯示某個項目時，順手把它的頁面記下來，渲染完再看使用者現在是不是正站在
  // 其中一頁上。條件只有一份，不可能對不齊。
  var _deniedPages = []

  // ── 2026-09-14：側欄退役，改成上方分組下拉選單 ────────────────────────
  // sec()/ni() 仍然照舊被呼叫（權限旗標、href、active 判定一行都不用改），
  // 但改成「記錄成結構資料」而不是直接吐側欄 HTML。渲染交給 renderMainNav()。
  var _navGroups = []
  var _curGroup = null

  function ni(href, icKey, label, activeNames, show, badgeId, extraBadge) {
    if (show === false) {
      _deniedPages = _deniedPages.concat(activeNames || [])
      return ''
    }
    if (!_curGroup) { _curGroup = { label: '', items: [] }; _navGroups.push(_curGroup) }
    _curGroup.items.push({
      href: href,
      label: label,
      active: act(activeNames) !== '',
      badgeId: badgeId || '',
      extraBadge: extraBadge || ''
    })
    return ''
  }

  function sec(label, show) {
    if (show === false) { _curGroup = { label: label, items: [], hidden: true }; return '' }
    _curGroup = { label: label, items: [] }
    _navGroups.push(_curGroup)
    return ''
  }

  // 分組下拉選單。每個 sec() 是一個頂層項目，底下的 ni() 排成多欄面板。
  // 只有一個子項的分組（例如「主選單／儀表板」）直接當成連結，不開面板。
  function renderMainNav() {
    var groups = _navGroups.filter(function (g) { return g.items.length > 0 })
    if (!groups.length) return

    var html = '<div class="mnav__in">' + groups.map(function (g, gi) {
      var anyActive = g.items.some(function (it) { return it.active })
      if (g.items.length === 1) {
        var it0 = g.items[0]
        return '<a class="mnav__top' + (it0.active ? ' is-on' : '') + '" href="' + it0.href + '">'
          + esc(it0.label) + '</a>'
      }
      // 一欄最多 6 項，超過就分欄——欄數自適應，不用寫死
      var per = 6
      var cols = []
      for (var i = 0; i < g.items.length; i += per) cols.push(g.items.slice(i, i + per))
      var panel = '<div class="mnav__panel"><div class="mnav__cols">' + cols.map(function (col) {
        return '<div class="mnav__col">' + col.map(function (it) {
          return '<a class="mnav__item' + (it.active ? ' is-on' : '') + '" href="' + it.href + '">'
            + '<span>' + esc(it.label) + '</span>'
            + (it.badgeId ? '<span id="' + it.badgeId + '" style="' + _SB_BADGE_STYLE + '"></span>' : '')
            + it.extraBadge
            + '</a>'
        }).join('') + '</div>'
      }).join('') + '</div></div>'
      return '<div class="mnav__grp' + (anyActive ? ' is-on' : '') + '" tabindex="0">'
        + '<span class="mnav__top">' + esc(g.label)
        + '<svg viewBox="0 0 10 6" fill="none" aria-hidden="true"><path d="M1 1l4 4 4-4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'
        + '</span>' + panel + '</div>'
    }).join('') + '</div>'

    var bar = document.getElementById('app-mainnav')
    if (!bar) {
      bar = document.createElement('nav')
      bar.id = 'app-mainnav'
      bar.className = 'mnav'
      bar.setAttribute('aria-label', '\u4e3b\u9078\u55ae')
      var tb = document.getElementById('app-topbar')
      if (tb && tb.parentNode) tb.parentNode.insertBefore(bar, tb.nextSibling)
      else document.body.insertBefore(bar, document.body.firstChild)
    }
    bar.innerHTML = html
  }


  function buildSidebar() {
    var html = [
      sec('主選單', canDash),
      ni(up + 'index.html',          'dash',  '儀表板',   ['index.html', ''],                       canDash),
      // 2026-09-14：只留真正的業務項目（開發、報價、簽核）。
      // 案件管理拆到下方獨立分組，理由見那邊註解。
      // ⚠️ UI8：少了 `cMap` ⇒ 只有地圖權限的人會看到「地圖」掛在一個
      //    **不顯示的分組標題**底下。分組條件必須是底下每一項條件的聯集。
      sec('業務', cDev || cQ || cTdr || cMap),
      ni(pg('dev-crm.html'),         'bdev',  '業務開發', ['dev-crm.html'],                          cDev, 'sb-mod-dev-crm'),
      ni(pg('tender-radar.html'),    'radar', '標案雷達', ['tender-radar.html'],                     cTdr, 'sb-mod-tender-radar'),
      ni(pg('map.html'),             'radar', '地圖',     ['map.html'],                              cMap),
      ni(pg('quotations.html'),      'quote', '報價單',   ['quotations.html', 'quotation-form.html'], cQ,   'sb-mod-quotation'),
      // ── 案件：成案之後的執行與財務（2026-09-14 從「業務」拆出來）──
      // 拆出來的原因：cCM 包含 eng（工程師），而 cQ / cDev 不包含。
      // 舊分法下，一個沒有任何模組的工程師會看到一個叫「業務」的分組，
      // 裡面只有這兩項——名叫業務卻沒有半個業務項目。
      sec('案件', cCM),
      ni(pg('case-management.html'), 'case_', '案件管理', ['case-management.html'],                   cCM,  'sb-mod-case'),
      ni(pg('case-stage-board.html'),'case_', '案件執行看板', ['case-stage-board.html'],               cCM),
      // ⚠️ UI8：少了 `cInv`（庫存管理）—— 同上。
      sec('廠商與採購', cCu || cPr || cInv),
      ni(pg('customers.html'),       'cust',  '客戶管理', ['customers.html', 'customer-log.html'],   cCu,  'sb-mod-customer'),
      ni(pg('suppliers.html'),          'supp',  '供應商管理', ['suppliers.html', 'supplier-log.html'],    cPr,  'sb-mod-suppliers'),
      ni(pg('vendor-contractors.html'), 'vend',  '承攬商管理', ['vendor-contractors.html'],               cPr,  'sb-mod-vendor'),
      ni(pg('parts.html'),              'part',  '料號主檔',  ['parts.html'],                            cPr,  'sb-mod-parts'),
      ni(pg('inventory.html'),          'inv',   '庫存管理',  ['inventory.html'],                        cInv, 'sb-mod-inventory'),
      ni(pg('procurement.html'),        'proc',  '採購管理',  ['procurement.html'],                      cPr,  'sb-mod-procurement'),
      sec('設備', cEq || cNetPlan),
      ni(pg('devices.html'),         'dev',   '設備登載', ['devices.html'],  cEq,  'sb-mod-equipment'),
      ni(pg('warranty.html'),        'warr',  '保固追蹤', ['warranty.html'], cEq,  'sb-mod-warranty'),
      ni(pg('network-plans.html'),   'netplan', '網路架構規劃書', ['network-plans.html', 'network-plan-form.html', 'topology-quick.html'], cNetPlan, 'sb-mod-netplan'),
      // 分組條件＝底下各項條件的聯集（test_sidebar_finance 守）：`true` 是獎金分潤那一項
      // （2026-09-24 任何登入者可開，見下方 bonus.html 那一列）
      sec('財務', cFi || cRpt || cCash || true),
      // 2026-09-13（模組權限稽核）：補上 badge id。`finance` 模組的紅點原本掛在
      // 'sb-mod-finance' / 'sb-mod-sales-orders' 這兩個 id 上，而它們所屬的
      // 應收帳款／銷售訂單兩個側欄項目在 2026-08-31（87e16cb）退役後就不再渲染
      // ——後端 `_MODULE_ACTION_PREFIXES['finance']` 照樣在算 payment./sales_order./
      // settlement. 三種異動的數量，前端卻永遠找不到元素可以顯示，等於這個模組的
      // 通知數字靜靜消失了。那些內容現在都在營運報表頁，紅點就掛回這裡。
      // ⚠️ `UI9`（2026-09-23）：`'cashier.html'` 從這裡**拿掉**了。
      //    它在 `UI6` 時代要留著，因為那時 cashier.html 是一頁轉址存根、
      //    出納的內容在本頁的一個頁籤裡。出納拆回獨立頁之後**它換了主人**。
      //    🔑 兩項條件不同（`cCash` vs `cRpt||cCash||cFi`）而同時宣告同一個
      //       檔名的話，`_deniedPages` 會讓其中一邊把另一邊的人鎖在門外。
      // 🔴 `UI10`（2026-09-23）：`cCash` 從這裡**拿掉** —— 這就是 `§46b`。
      //    只有 `cashier` 權限的人原本會看到一個叫「營運報表」的項目，
      //    而那一頁的內容他一格都看不到（12 個頁籤只給 admin+）。
      // ⚠️ `§65` 當時**擋下**了同一個改動，而那個理由現在不成立了：
      //    當時出納沒有自己的檔名，拿掉 `cCash` 會讓 `_deniedPages` 把
      //    只有出納權限的人鎖在 `reports.html` 外面 —— 原本是「看得到一個
      //    不屬於他的項目」，改完變成「點不進自己的頁」。
      //    🔑 `UI9` 之後出納有了 `cashier.html`，那條路不再經過這一頁。
      // 📌 ⇒ **推翻一個改動的理由，不等於那個改動永遠不能做。**
      //    理由消失的那一天要有人回來看它 —— 這一次是守門把它叫回來的。
      ni(pg('reports.html'),         'rpt',   '營運報表', ['reports.html'],                          cRpt || cFi, 'sb-mod-finance'),
      // 🔴 UI6（使用者 2026-09-23）：出納在側欄上原本**沒有任何入口** ——
      // 只有 `cashier` 權限的人看得到一個叫「營運報表」的項目，
      // 而他被授權的那一頁點不到。
      //
      // 🔑 `UI9`（同日）把出納**拆回獨立頁面** ⇒ 這裡從
      //    `reports.html?tab=cashier` 改成 `cashier.html`，而 `activeNames`
      //    從空的變成 `['cashier.html']` —— 它現在是這個檔案的主人。
      // ⚠️ `UI6` 當時 `activeNames` 刻意留空，理由是 `act()` 只比對檔名、
      //    query 不在 `location.pathname` 裡 ⇒ 那一項**永遠不會亮**。
      //    拆成獨立頁之後那個限制連同 `§46b` 一起消失了 —— **同一個根因
      //    （兩個功能共用一頁）的三個出口一起關掉。**
      ni(pg('cashier.html'),         'cash',  '出納',     ['cashier.html'],                          cCash),
      // 🔑 `VC4a`（2026-09-23）：傳票。放在「出納」後面 —— 使用者原話
      //    「要由**出納獨立作業**還有送審流程跟編號」⇒ 它是出納的作業，
      //    不是另一個部門的東西。權限沿用 `cCash`（與後端的
      //    `routers/vouchers.py::_VOUCHER_MODULES` 對得上：cashier／finance）。
      // ⚠️ 而**看得到入口 ≠ 改得動** —— 後端另有 `can_edit(status)`：只有草稿可改。
      ni(pg('voucher.html'),         'vouch', '傳票',     ['voucher.html'],                          cCash),
      // 🔑 `FN1`（2026-09-23）：會計科目樹。放在出納後面，因為它是**出納與
      //    傳票挑科目時的那份清單**，不是一個獨立的業務流程。
      // ⚠️ 權限沿用 `cCash`：它目前是唯讀的參考資料，而會看它的正是出納。
      //    ⇒ 日後要開放給更多人時，這裡與 `_deniedPages` 要一起改。
      ni(pg('account-items.html'),   'acct',  '會計科目', ['account-items.html'],                     cCash),
      // 🔑 `FN2`：獎金分潤。使用者原話「一樣加在營運報表那個模組獨立」
      //    ⇒ 它與出納、營運報表並列在「財務」這一組，**不是獨立分組**。
      // 🔴 2026-09-24 使用者裁示：「任何登入者都能打開，內容照規則過濾」（SPEC-BONUS M1）
      //    ⇒ 不再沿用 `cRpt`（營運報表）：受獎人多半沒有營運報表權限，沿用的話他們看不到自己的獎金。
      //    🔑 看得到入口 ≠ 看得到金額 —— 後端（/api/bonus/cases）過濾：最高管理者看全部、
      //       出納看待發放／已發放整張金額、名單上的人只看自己那一列、其餘看到空狀態。
      ni(pg('bonus.html'),           'bonus', '獎金分潤', ['bonus.html'],                              true),
      sec('勞務管理', cCon || cPay),
      ni(pg('contractors.html'),     'contl', '外包名冊', ['contractors.html'],                      cCon),
      ni(pg('payslips.html'),        'paysl', '勞報單',   ['payslips.html', 'payslip-form.html'],    cPay),
      // 🔑 2026-09-22 使用者裁示：「工作內容」改名為「我的工作」，
      //    並把簽核相關的三項從「業務」搬進來（見下方 ⬇️ 那一段）。
      // ⚠️ 這裡**刻意不逐一列出那三項的名稱**：一段複述項目名稱的註解，
      //    在有人改名的那天就會變成兩個說法，而讀的人不知道哪個是真的。
      //    理由（使用者的話轉述）：搬完之後這一組全部是**「等我處理」或
      //    「我做過的」** —— 主語是使用者自己，不是模組類型。
      //    「工作內容」描述的是資料，而一張等你簽的單不是資料，
      //    是一件要你去做的事。
      // ⚠️ 顯示條件加上 `cQ`：三項的條件是 `cQ`，而**分組的條件必須是
      //    底下每一項條件的聯集** —— 漏掉的話，一個只有 `cQ` 沒有
      //    `cWL`／`cDT` 的人會看到三個項目掛在一個不顯示的標題底下。
      sec('我的工作', cWL || cDT || cQ),
      ni(pg('work-log.html'),        'wlog',  '工作日誌',   ['work-log.html'],                         cWL,  'sb-mod-worklog'),
      ni(pg('daily-tasks.html'), 'dtask', '\u6bcf\u65e5\u5de5\u4f5c\u4e8b\u9805', ['daily-tasks.html'], cDT, 'sb-mod-daily-task',
         '<span id="sb-dt-badge" style="display:none;background:#7C3AED;color:#fff;font-size:9px;font-weight:700;font-family:LINE Seed TW_OTF, sans-serif;padding:1px 6px;border-radius:9px;margin-left:auto"></span>'),
      // ⬇️ 2026-09-22 從「業務」搬過來的三項。**條件仍然是 `cQ`，一個字沒改。**
      ni(pg('approval-queue.html'), 'appr', '\u7c3d\u6838\u4f47\u5217', ['approval-queue.html'], cQ, '',
         '<span id="sb-approval-badge" style="display:none;background:#DC2626;color:#fff;font-size:9px;font-weight:700;font-family:LINE Seed TW_OTF, sans-serif;padding:1px 6px;border-radius:9px;margin-left:auto"></span>'),
      ni(pg('approval-delegates.html'), 'appr', '簽核代理人', ['approval-delegates.html'], cQ),
      ni(pg('approval-history.html'), 'apprhist', '簽核歷史', ['approval-history.html'], cQ),
      // ⚠️ UI8：這一處是**多**不是少 —— `cSet` 底下**沒有任何一個 `ni()`**
      //    用它們 ⇒ 只有那個權限的人會看到一個**空的分組標題**。
      //    🔑 方向與前三處相反，而成因相同：條件與項目各自演進，沒有東西在比對。
      sec('系統', sa || cAudit || cShipLog || cVer),
      ni(pg('users.html'),             'users', '使用者管理', ['users.html'],             sa),
      ni(pg('org-structure.html'),     'org',   '組織架構設定', ['org-structure.html'],   sa),
      // 🔴 `AS4`（2026-09-23）：「匯款申請簽核設定」這個獨立入口拿掉了——
      //    使用者原話：「匯款申請會簽整合進簽核設定，但系統內仍然有一個
      //    匯款申請簽核設定的選項」。舊頁與新的「簽核設定」寫的是**同一把
      //    key**（contractor_voucher_approval_flow），而舊頁不知道
      //    「統一／獨立」那個開關存在 ⇒ 範圍是統一流程時，舊頁存的設定
      //    永遠不會被用到，而舊頁的說明承諾了一件它做不到的事。
      //    舊頁本身**沒有刪**（書籤／收藏的連結還在，見該頁的導向說明），
      //    只是拿掉側欄入口，不讓人再從這裡點進去設一個不會生效的東西。
      ni(pg('approval-settings.html'),      'sett',  '簽核設定',   ['approval-settings.html'],      sa),
      ni(pg('notification-settings.html'), 'ntfy',  '通知設定',   ['notification-settings.html'],  sa),
      // CORE-SPEC「信件與通知的收件人、用語」：每一種信件指定收件人（僅超級管理員）
      ni(pg('mail-settings.html'),   'ntfy',  '信件與通知收件設定', ['mail-settings.html'],   sa),
      ni(pg('google-calendar-settings.html'), 'gcal', 'Google 行事曆設定', ['google-calendar-settings.html'], sa),
      ni(pg('company-profile-settings.html'), 'co',   '公司資料設定',   ['company-profile-settings.html'], sa),
      // CORE-SPEC §9c：模組啟停／授權狀態（啟停重啟後生效）
      ni(pg('module-settings.html'),   'sett',  '模組管理',   ['module-settings.html'],   sa),
      ni(pg('legal-params.html'),      'sett',  '法規參數設定', ['legal-params.html'],     sa),
      ni(pg('audit-log.html'),         'hist',  '歷史紀錄',   ['audit-log.html'],         cAudit),
      ni(pg('shipping-export-history.html'), 'hist', '出貨單歷史紀錄', ['shipping-export-history.html'], cShipLog),
      ni(pg('module-versions.html'),  'ver',   '版本紀錄',   ['module-versions.html'],               cVer),
      ni(pg('online-stats.html'),     'hist',  '在線時數統計', ['online-stats.html'],              sa),
      ni(pg('schema-status.html'),    'schema', 'Schema 狀態', ['schema-status.html'],               sa),
    ].filter(Boolean).join('')

    // 側欄已退役：html 現在恆為空字串，元素留著也不渲染任何東西。
    var el = document.getElementById('app-sidebar')
    if (el) el.innerHTML = ''
    renderMainNav()

    // 使用者正站在一個「側欄判定他不該看到」的頁面上 → 顯示沒有權限，而不是
    // 把頁面內容留在那裡讓 API 一路 403（看起來像壞掉，不像沒權限）。
    //
    // **刻意不導轉**：`index.html` 自己也有一道守門（非 admin 且沒有 finance／
    // quotation 模組就導去 case-management.html），導轉會直接做出迴圈——
    // 只有「儀表板」模組的檢視者會在 index ⇄ case-management 之間無限跳。
    // 只處理側欄真的列過的頁面（`_deniedPages` 來自 ni() 的顯示條件），
    // 沒列過的頁面一律放行：寧可漏擋也不要把人鎖在門外，資料那層 API 會擋。
    if (_deniedPages.indexOf(file) >= 0) _showNoPermission()

    // 🔴 `BR1` 第三格：**把「這個行程載入的是哪一版」放到每一頁的頁尾。**
    //
    // ☠️ 2026-09-23：666 的行程 05:56 起來、載入 dd50d2e，而磁碟上已經
    //    往前 25 個 commit ⇒ **使用者在瀏覽器上一個都沒看到**，
    //    而 git 是對的、全量是綠的、他的畫面是舊的 —— 三邊都不會報錯。
    // 🔑 只做啟動 log 與 API 的話，是把它放進**一個沒有人會去看的地方**，
    //    而現在的問題正是沒有人去看。
    renderBuildFooter()
  }

  //: 頁尾：執行中的版本。**而真正要講的是「它與磁碟上一不一樣」。**
  //
  // ⚠️ 只印一個 SHA 的話，看到的人還是得自己去比對 —— 而那正是沒有人做的那一步。
  // 🔑 所以 `stale` 為真時它**不是一行小字，是一條要被看見的橫幅**。
  function renderBuildFooter() {
    // login／轉址頁刻意沒有頂欄（`<body data-no-topbar>`）⇒ 頁尾也不要硬塞。
    if (document.body && document.body.hasAttribute('data-no-topbar')) return
    if (document.getElementById('build-footer')) return
    var bar = document.createElement('div')
    bar.id = 'build-footer'
    bar.setAttribute('data-testid', 'build-footer')
    bar.style.cssText = 'position:fixed;right:10px;bottom:6px;z-index:40;'
      + 'font-size:11px;color:var(--text-dim,#6B6B6B);font-family:monospace;'
      + 'background:rgba(255,255,255,.82);padding:2px 8px;border-radius:9px;'
      + 'pointer-events:none;max-width:60vw;white-space:nowrap;overflow:hidden;'
      + 'text-overflow:ellipsis'
    document.body.appendChild(bar)

    var sess = {}
    try { sess = JSON.parse(localStorage.getItem('motrix_session') || '{}') }
    catch (e) { sess = {} }
    fetch('/api/build-info', {
      headers: { Authorization: 'Bearer ' + (sess.token || '') },
    }).then(function (r) {
      // 🔴 **404／405 本身就是答案。**
      //
      //    路由是在 **import 當下**註冊的 ⇒ 一個在 BR1 之前啟動的行程
      //    **沒有這支端點** ⇒ 它回 404（或 405）。
      // 🔑 ⇒ 那不是「查不到版本」，那是「**這個行程比 BR1 還舊**」——
      //    而那正是使用者需要知道的那一句。
      // ☠️ 而原本的寫法是 `bar.remove()` ⇒ **一句話都不說**。
      //    那與 `§219` 同一種病：錯誤被藏在一個顯示不出來的地方，
      //    而**空白比一句假話更難查**。
      if (r.status === 404 || r.status === 405) return { _tooOld: true }
      return r.ok ? r.json() : null
    }).then(function (d) {
      if (!d) { bar.remove(); return }
      if (d._tooOld) {
        bar.style.cssText += ';background:#FEF2F2;color:#B91C1C;font-weight:700;'
          + 'pointer-events:auto;cursor:help'
        bar.textContent = '⚠️ 伺服器載入的是舊版（沒有版本資訊端點）—— 請重新啟動'
        bar.title = '這個行程是在「顯示執行中版本」這個功能之前啟動的。'
          + '重新啟動伺服器之後這裡才會顯示版本。'
        return
      }
      var started = (d.started_at || '').replace('T', ' ').slice(0, 16)
      bar.textContent = (d.commit_short || '不可得') + ' · 啟動 ' + started
      // 🔴 `BR4`（2026-09-23）：`stale` 的語意改了 —— 現在是「有沒有 commit
      //    **動到程式碼**」，不是「HEAD 是否相等」。這個 repo 四個視窗持續
      //    在提交（多數是純 .md），HEAD 不相等在這裡幾乎永遠成立；而使用者
      //    要問的是「我要驗的東西在不在我這一版裡」，不是「HEAD 動過沒」。
      //    ☠️ 舊版每次重啟幾分鐘內橫幅必定變紅，使用者因此不敢驗證——
      //    他要驗的東西其實一直都在他跑的那一版裡。
      if (d.stale === true) {
        // 🔴 過期是**要被看見的**：小字沒有人會讀。
        bar.style.cssText += ';background:#FEF2F2;color:#B91C1C;font-weight:700;'
          + 'pointer-events:auto;cursor:help'
        var n = d.behindCount || 0
        bar.textContent = '⚠️ 執行中 ' + (d.commit_short || '?')
          + '　落後 ' + n + ' 個後端／前端異動'
          + '　—— 建議重新啟動'
        // 🔑 列出標題，讓使用者自己判斷「我要驗的東西在不在裡面」，
        //    不必來問任何人（`BR4` 的核心訴求）。
        var titles = d.behindTitles || []
        bar.title = '這個行程是 ' + started + ' 啟動的。磁碟上 '
          + (d.disk_commit_short || '?') + ' 之後多了 ' + n
          + ' 個動到程式碼的異動：\n' + titles.map(function (t) {
              return '• ' + t
            }).join('\n')
          + (n > titles.length ? '\n…（只列前 ' + titles.length + ' 條）' : '')
      } else if (d.stale === false) {
        // ✅ HEAD 可能不同，但沒有任何一個動到程式碼 —— 正常顯示，不是紅的。
        //    使用者要驗的東西就在這一版裡。
      } else if (d.stale === null) {
        // ⚠️ `null` ＝ 落後的程式碼異動數算不出來（SHA 不可得、或兩者不在
        //    同一條歷史線上），**不是「沒有過期」**。
        //    ☠️ 當成「最新」的話，畫面會在不知道的時候給人保證。
        bar.textContent += ' · 版本比對不可得'
        if (d.behindUnavailableReason) bar.title = d.behindUnavailableReason
      }
    }).catch(function () { bar.remove() })
  }

  function _showNoPermission() {
    var main = document.querySelector('main')
    var html =
      '<div id="no-module-notice" style="max-width:520px;margin:64px auto;text-align:center;' +
      'font-family:LINE Seed TW_OTF, sans-serif">' +
      '<div style="font-size:40px;margin-bottom:12px">🔒</div>' +
      '<div style="font-size:17px;font-weight:600;margin-bottom:8px">你沒有這個頁面的權限</div>' +
      '<div style="font-size:13px;color:var(--text-dim);line-height:1.9">' +
      '這一頁需要對應的模組權限，請洽系統管理員在「使用者管理」中開通。<br>' +
      '左側選單中的項目才是你目前可以使用的功能。</div></div>'
    if (main) {
      main.innerHTML = html
    } else {
      var d = document.createElement('div')
      d.innerHTML = html
      document.body.appendChild(d)
    }
  }

  // ── Mobile toggle ──────────────────────────────────────────────────────────
  function bindMobileToggle() {
    var toggle  = document.getElementById('sidebar-toggle')
    var overlay = document.getElementById('sidebar-overlay')
    var sbEl    = document.getElementById('app-sidebar')

    function openSB() {
      if (sbEl)    sbEl.classList.add('mobile-open')
      if (overlay) overlay.classList.add('active')
      document.body.classList.add('sidebar-lock')
    }
    function closeSB() {
      if (sbEl)    sbEl.classList.remove('mobile-open')
      if (overlay) overlay.classList.remove('active')
      document.body.classList.remove('sidebar-lock')
    }
    if (toggle)  toggle.addEventListener('click', openSB)
    if (overlay) overlay.addEventListener('click', closeSB)
    if (sbEl) sbEl.addEventListener('click', function (e) {
      var a = e.target && e.target.closest ? e.target.closest('a') : null
      if (a && window.innerWidth <= 767) closeSB()
    })
  }

  // ── Unsaved-changes guard ─────────────────────────────────────────────────
  // Pages set window.motrixIsDirty = true when a form is being edited.
  // sidebar.js intercepts link-clicks and the beforeunload event to warn.
  // Successful API mutations (POST/PUT/PATCH/DELETE) auto-clear the flag.
  window.motrixIsDirty = window.motrixIsDirty || false

  function bindNavGuard() {
    // Intercept link-click navigation
    document.addEventListener('click', function (e) {
      if (!window.motrixIsDirty) return
      var link = e.target && e.target.closest ? e.target.closest('a[href]') : null
      if (!link) return
      var href = link.getAttribute('href') || ''
      if (!href || href === '#' || href.slice(0, 11) === 'javascript:') return
      // Same-page anchor → allow
      try {
        var dest = new URL(link.href, window.location.href).pathname
        if (dest === window.location.pathname) return
      } catch (_) {}
      e.preventDefault()
      if (confirm('您有尚未儲存的輸入內容\n\n離開此頁面將導致資料遺失，確定要離開嗎？')) {
        window.motrixIsDirty = false
        window.location.href = link.href
      }
    }, true)

    // Intercept tab-close / browser back-forward / manual URL change
    window.addEventListener('beforeunload', function (e) {
      if (window.motrixIsDirty) {
        e.preventDefault()
        e.returnValue = ''
      }
    })

    // Auto-set dirty on any user text input (excludes read-only search boxes)
    function _maybeSetDirty(e) {
      var el = e.target
      if (!el) return
      if (el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA' && el.tagName !== 'SELECT') return
      if (el.readOnly || el.disabled) return
      if (el.type === 'search' || el.type === 'range') return
      // Skip purely-cosmetic search / filter inputs by class name
      var cls = (el.className || '')
      if (cls.indexOf('search') >= 0 || cls.indexOf('filter') >= 0) return
      window.motrixIsDirty = true
    }
    document.addEventListener('input',  _maybeSetDirty, true)
    document.addEventListener('change', _maybeSetDirty, true)

    // Auto-clear dirty after any successful mutating API call
    // 2026-09-24：同時編輯提示的心跳不算——edit-presence.js 每 8～15 秒 POST 一次，
    // 跟表單有沒有存無關，原本會讓離頁警告在打字後最多 15 秒就失效。
    var _origFetch = window.fetch
    window.fetch = function (url, opts) {
      return _origFetch.apply(this, arguments).then(function (resp) {
        if (resp.ok && opts) {
          var method = (opts.method || '').toUpperCase()
          var path = typeof url === 'string' ? url : ((url && url.url) || '')
          var isPresence = path.indexOf('/api/edit-presence') === 0
          if (!isPresence && (method === 'POST' || method === 'PUT' || method === 'PATCH' || method === 'DELETE')) {
            window.motrixIsDirty = false
          }
        }
        return resp
      })
    }
  }

  // Module key → sidebar badge element IDs (mirrors modBadge in notif.js)
  var _MOD_BADGES = {
    dev_crm:     ['sb-mod-dev-crm'],
    tender_radar: ['sb-mod-tender-radar'],
    quotation:   ['sb-mod-quotation'],
    case_manage: ['sb-mod-case'],
    customer:    ['sb-mod-customer'],
    procurement: ['sb-mod-suppliers', 'sb-mod-vendor', 'sb-mod-parts', 'sb-mod-procurement'],
    equipment:   ['sb-mod-equipment', 'sb-mod-warranty'],
    finance:     ['sb-mod-finance'],   // 2026-09-13：'sb-mod-sales-orders' 隨 sales-orders.html 退役移除
    work_log:    ['sb-mod-worklog'],
    daily_task:  ['sb-mod-daily-task'],
  }
  window.MOTRIX_MOD_BADGES = _MOD_BADGES   // notif.js 讀這一份（不再各抄一份）

  function _clearModBadge(modKey) {
    var bids = _MOD_BADGES[modKey]
    if (!bids) return
    for (var i = 0; i < bids.length; i++) {
      var el = document.getElementById(bids[i])
      if (el) el.style.display = 'none'
    }
  }

  // UR1：點選單項目的**當下**就清掉那個模組的紅點並送出「看過」（keepalive），
  //      不等下一頁載入、不等伺服器回應。「看過」存伺服器，時間由伺服器蓋。
  function _markModuleSeen(modKey) {
    if (!modKey) return
    _clearModBadge(modKey)
    if (window.MotrixReads) window.MotrixReads.mark('module', modKey)
  }

  function bindBadgeClear() {
    document.addEventListener('click', function (e) {
      var a = e.target && e.target.closest ? e.target.closest('a[href]') : null
      if (!a) return
      var f = (a.getAttribute('href') || '').split('#')[0].split('?')[0].split('/').pop()
      var mod = _FILE_MODULE[f]
      if (mod) _markModuleSeen(mod)
    }, true)
  }

  // ── Entry ──────────────────────────────────────────────────────────────────
  function build() {
    var _curMod = _FILE_MODULE[file]

    // UR1：「看過」改存伺服器（`/api/reads`，kind='module'）。
    //   原本寫 localStorage、用用戶端時鐘，且「沒看過的模組往回看 7 天」的種子也在這裡；
    //   兩者都移到後端（`routers/item_reads.py::module_counts`）。舊值由 notif.js 一次性遷移。
    // `motrixCurrentModule`：notif.js 數字回來時不要把目前這一頁的紅點又點亮
    //   （這一頁的「看過」請求可能還在路上）。
    window.motrixCurrentModule = _curMod || ''
    if (_curMod && s.token && window.MotrixReads) {
      window.MotrixReads.ready.then(function () { window.MotrixReads.mark('module', _curMod) })
    }

    buildTopbar()
    buildSidebar()
    // Defensively clear this module's badge immediately after DOM creation,
    // so it's hidden even if _fetchModuleCounts() hasn't resolved yet.
    if (_curMod) _clearModBadge(_curMod)
    bindBadgeClear()
    bindMobileToggle()
    bindNavGuard()
  }

  // ── Async session refresh（背景刷新模組權限，有變動立即重建 sidebar）──────────
  function _refreshSession() {
    if (!s || !s.token) return
    fetch('/api/auth/me', { headers: { Authorization: 'Bearer ' + s.token } })
      .then(function (r) { return r.ok ? r.json() : null })
      .then(function (d) {
        // 🔴 **一個決定，管住下面兩件事**（寫回 localStorage ＋ 重算 mods）。
        // ⚠️ 不接受就整筆不覆寫 —— 保留既有權限，等下一次刷新。
        if (!acceptsSessionUpdate(d)) return
        var stored = JSON.parse(localStorage.getItem('motrix_session') || '{}')
        var modsChanged = JSON.stringify(stored.modules) !== JSON.stringify(d.modules)
        var roleChanged = stored.role !== d.role
        if (!modsChanged && !roleChanged && stored.displayName === d.displayName) return
        stored.role               = d.role
        stored.displayName        = d.displayName
        stored.modules            = d.modules
        stored.mustChangePassword = d.mustChangePassword
        localStorage.setItem('motrix_session', JSON.stringify(stored))
        // 重新計算 flags 並重建選單。2026-09-14：這裡原本抄了一份跟上面幾乎
        // 一樣的旗標計算，而且已經漏掉 cCon／cPay／cNetPlan——改成共用
        // computeFlags()，之後新增模組只會有一個地方要改。
        role = d.role
        // 📌 `acceptsSessionUpdate()` 已經保證它是陣列 ——
        // 這裡再判一次的話就又變成「兩個地方各自判斷同一件事」。
        mods = d.modules
        computeFlags()
        // 重建前要清掉上一輪累積的分組與被擋頁面清單，否則重建會把新舊選單接在一起
        _navGroups = []
        _curGroup = null
        _deniedPages = []
        buildSidebar()
        _applyUnavailablePages()
        var dnEl = document.getElementById('tb-display-name')
        if (dnEl) dnEl.textContent = esc(d.displayName || d.username || '')
      })
      .catch(function () {})
  }

  // ── 獎金分潤：出貨暫停使用（`BONUS_MODULE_ENABLED`，`SPEC-BN21.md`）──────
  //
  // 🔴 旗標要後端給，不能寫死在這裡（改天修好了、開關打開，這裡不用跟著改）。
  // ⚠️ 不把它織進 `ni()`／`buildSidebar()` 的同步流程——那個流程是同步的，
  //    而這支旗標要打一次後端才知道。改成事後找到已經渲染好的連結直接藏起來，
  //    不動 build() 本身的邏輯，風險最小（今晚其餘 60+ 支既有測試都靠它穩定）。
  function _hideBonusEntryIfModuleDisabled() {
    if (!s || !s.token) return
    fetch('/api/system/bonus-module-status', { headers: { Authorization: 'Bearer ' + s.token } })
      .then(function (r) { return r.ok ? r.json() : null })
      .then(function (d) {
        if (!d || d.enabled) return
        // ⚠️ 只藏這個 `<a>` 本身——不可以藏它的 `.mnav__grp` 祖先：
        //    那個 div 是整個下拉面板（財務那一組），連出納／傳票／會計科目
        //    都在裡面，藏了祖先會把整組一起藏掉。
        document.querySelectorAll('a[href$="bonus.html"]').forEach(function (a) {
          a.style.display = 'none'
        })
      })
      .catch(function () {})
  }

  // ── CORE-SPEC §9c／STATES-PLATFORM P-FE-02・03：模組頁面的入口與直接打網址 ──────────────
  //
  // 狀態要後端給（`/api/system/modules/availability`，來源是載入器這次啟動的結果），不寫死在這裡；
  // 寫死的只有「哪一頁屬於哪個模組」（守門：每個 modules/*/module.json 的 pages 都要在這張表裡、key 對得上）。
  // 🔴 入口只在狀態是 loaded 時顯示：**清單裡沒有這個 key ＝不在安裝包**，也要藏（P-FE-02；原本只藏
  //    「列為未載入」的頁面，不在包內的模組永遠列不進去，入口照樣出現）。
  // ⚠️ 清單取不到（網路、後端錯）⇒ 入口照常顯示（P-FE-04：API 仍會 404，不會越權）。
  // ⚠️ 選單會被 `_refreshSession()` 重建 ⇒ 重建後要再套用一次（所以把結果留著）。
  var MODULE_PAGES = {
    'tender-radar.html': { key: 'tender_radar', name: '標案雷達' },
    'daily-tasks.html': { key: 'daily_tasks', name: '每日任務' },
    'network-plans.html': { key: 'netplan', name: '網路規劃' },
    'network-plan-form.html': { key: 'netplan', name: '網路規劃' },
    'topology-quick.html': { key: 'netplan', name: '網路規劃' },
    'dev-crm.html': { key: 'crm', name: '業務開發' },
  }
  window.MOTRIX_MODULE_PAGES = MODULE_PAGES
  var _moduleAvailability = null
  function _moduleLoaded(pgName) {
    var m = MODULE_PAGES[pgName]
    if (!m || !_moduleAvailability) return true
    var st = _moduleAvailability[m.key]
    return !!(st && st.state === 'loaded')
  }
  function _applyUnavailablePages() {
    if (!_moduleAvailability) return
    Object.keys(MODULE_PAGES).forEach(function (pgName) {
      if (_moduleLoaded(pgName)) return
      document.querySelectorAll('a[href$="' + pgName + '"]').forEach(function (a) {
        a.style.display = 'none'
      })
    })
  }
  // 直接打網址（書籤、別頁連結）進入未載入模組的頁面 ⇒ 提示頁：404 而沒有說明會讓人以為網址打錯；
  // 而「頁面照常載入、API 404、區塊空白」會讓人以為壞了（P-FE-03）。
  // 2026-09-26（階段 C／C1，裁示 D2 選項 A）：**主要由伺服器處理**——core.pages 對未載入模組的頁面回
  // HTTP 404＋同一組文案的提示頁，頁面本體不送出。這裡只剩**後備**：伺服器不認得這一頁屬於哪個模組
  // （例：模組資料夾不在安裝包、頁面檔卻還留在 frontend/pages）時，仍由前端依 availability 蓋提示框。
  // 文案改動要兩邊一起改（core/pages.py NOTICE）。
  var _MODULE_NOTICE = {
    disabled:   ['此模組目前已停用', '請洽最高管理者於「系統 → 模組管理」啟用，重新啟動服務後生效。'],
    unlicensed: ['此模組未授權', '目前的授權不包含這個模組，請聯絡供應商取得包含此模組的授權。'],
    failed:     ['此模組載入失敗', '請洽系統管理者於「系統 → 模組管理」查看原因。'],
    missing:    ['此模組未安裝', '這個安裝包沒有包含這個模組。'],
  }
  function _showModuleNotice() {
    var m = MODULE_PAGES[file]
    if (!m || _moduleLoaded(file)) return
    var st = _moduleAvailability[m.key]
    var kind = st ? st.state : 'missing'
    var txt = _MODULE_NOTICE[kind] || _MODULE_NOTICE.failed
    var main = document.querySelector('main')
    if (!main || document.querySelector('[data-testid="module-unavailable"]')) return
    main.style.display = 'none'
    var box = document.createElement('div')
    box.className = main.className
    box.setAttribute('data-testid', 'module-unavailable')
    box.setAttribute('data-state', kind)
    box.innerHTML = '<div style="max-width:640px;margin:48px auto;padding:24px 28px;border:1px solid var(--border-light,#E5E7EB);'
      + 'border-radius:10px;background:var(--white,#fff);line-height:1.7">'
      + '<div style="font-size:12px;color:var(--text-secondary,#6B7280)">' + esc(m.name) + '</div>'
      + '<h2 style="margin:4px 0 8px;font-size:20px">' + esc(txt[0]) + '</h2>'
      + '<p style="margin:0 0 16px;color:var(--text-secondary,#4B5563)">' + esc(txt[1]) + '</p>'
      + '<a class="btn" href="index.html">回首頁</a></div>'
    main.parentNode.insertBefore(box, main.nextSibling)
  }
  function _hideUnavailableModulePages() {
    if (!s || !s.token) return
    fetch('/api/system/modules/availability', { headers: { Authorization: 'Bearer ' + s.token } })
      .then(function (r) { return r.ok ? r.json() : null })
      .then(function (d) {
        if (!d || typeof d !== 'object') return
        _moduleAvailability = d
        window.MOTRIX_MODULE_AVAILABILITY = d
        _applyUnavailablePages()
        _showModuleNotice()
      })
      .catch(function () {})
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      build(); _refreshSession(); _hideBonusEntryIfModuleDisabled(); _hideUnavailableModulePages()
    })
  } else {
    build()
    _refreshSession()
    _hideBonusEntryIfModuleDisabled()
    _hideUnavailableModulePages()
  }
})()

// ── P8：已發布的自訂模組併進主選單（CUSTOMIZATION-SPEC §3.7）──────────────────────────
// 🔴 疊加點只有這一段：選單邏輯全在 custom-modules-nav.js（在已渲染的 #app-mainnav 上追加項目），
//    上面的 buildSidebar()／renderMainNav() 不動。階段 C 改由 /api/platform/menu 產生選單時，把這段搬走即可。
;(function () {
  if (document.querySelector('script[data-custom-modules-nav]')) return
  var el = document.createElement('script')
  el.src = (location.pathname.indexOf('/pages/') >= 0 ? '../' : '') + 'static/custom-modules-nav.js'
  el.setAttribute('data-custom-modules-nav', '')
  document.head.appendChild(el)
})()
