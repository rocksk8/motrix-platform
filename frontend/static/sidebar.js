/*!
 * MOTRIX ERP — Shared Layout Module
 * Builds topbar + sidebar from session. Handles mobile slide-in toggle.
 * Load at end of <body> (after notif.js).
 */
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
    var t = (document.title || '').split('\u2014')[0].trim()
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
          <input type="text" x-model="q" @input="onInput()" @focus="q && (open = true)" @keydown.escape="close()"
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
    if (!el) return

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
      + '<div style="padding:11px 16px;border-bottom:1px solid var(--border-light);font-size:13px;font-weight:600;color:var(--text-main)">近期操作</div>'
      + '<div style="max-height:320px;overflow-y:auto">'
      + '<template x-for="item in items" :key="item.id">'
      + '<div style="padding:10px 16px;border-bottom:1px solid var(--border-light)">'
      + '<div style="display:flex;justify-content:space-between;align-items:center">'
      + '<span x-text="actionLabel(item.action)" :style="`color:${actionColor(item.action)};font-size:12px;font-weight:600`"></span>'
      + '<span x-text="formatTime(item.at)" style="font-size:10px;color:var(--text-dim);font-family:LINE Seed TW_OTF, sans-serif"></span>'
      + '</div>'
      + '<div x-text="item.target_label||item.target_id" style="font-size:11px;color:var(--text-secondary);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></div>'
      + '<div x-text="item.display_name||item.username" style="font-size:11px;color:var(--text-dim);margin-top:1px"></div>'
      + '</div>'
      + '</template>'
      + '<div x-show="items.length===0" style="padding:20px;text-align:center;font-size:12px;color:var(--text-dim)">暫無紀錄</div>'
      + '</div>'
      + '<a :href="auditHref" style="display:block;padding:9px 16px;text-align:center;font-size:12px;color:var(--accent);border-top:1px solid var(--border-light);text-decoration:none;font-weight:500">查看完整紀錄 →</a>'
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
  var sa  = role === 'superadmin'
  var ad  = sa || role === 'admin'
  var eng = role === 'engineer'
  var cQ   = mods.indexOf('quotation')   >= 0 || ad
  var cCu  = mods.indexOf('customer')    >= 0 || ad
  var cPr  = mods.indexOf('procurement') >= 0 || ad
  var cFi  = mods.indexOf('finance')     >= 0 || ad
  var cCash = mods.indexOf('cashier')    >= 0 || ad
  var cCM  = mods.indexOf('case_manage') >= 0 || eng || ad
  var cEq  = mods.indexOf('equipment')   >= 0 || ad
  var cInv = mods.indexOf('inventory')   >= 0 || ad
  var cRpt = mods.indexOf('reports')     >= 0 || ad
  var cWL  = mods.indexOf('work_log')    >= 0 || role !== 'viewer'
  var cDT  = mods.indexOf('daily_task')  >= 0 || role !== 'viewer'
  var cDev = mods.indexOf('dev_crm')     >= 0 || ad
  var cCon = mods.indexOf('contractor_list') >= 0 || sa
  var cPay = mods.indexOf('payslip')    >= 0 || sa
  var cEnvG = mods.indexOf('env_guide')  >= 0 || ad
  var cNetG = mods.indexOf('netarch_guide') >= 0 || ad
  var cSwitchG = mods.indexOf('switch_guide') >= 0 || ad
  var cMonitorG = mods.indexOf('monitor_guide') >= 0 || ad
  var cAccessG = mods.indexOf('access_guide') >= 0 || ad
  var cGatewayG = mods.indexOf('gateway_guide') >= 0 || ad
  var cAutomationG = mods.indexOf('automation_guide') >= 0 || ad
  var cNetPlan = mods.indexOf('netplan_edit') >= 0 || ad || eng

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
    envg:  '<path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>',
    netg:  '<path d="M12 20h.01M8.5 16.5a5 5 0 017 0M5 12.859a10 10 0 0114 0M1.5 9.5a15 15 0 0121 0"/>',
    switchg: '<rect x="2" y="3" width="20" height="6" rx="1"/><rect x="2" y="15" width="20" height="6" rx="1"/><path d="M6 6h.01M6 18h.01"/>',
    monitorg: '<path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>',
    accessg: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/>',
    automationg: '<rect x="3" y="11" width="18" height="8" rx="2"/><circle cx="7.5" cy="7" r="2.5"/><circle cx="16.5" cy="7" r="2.5"/><path d="M7.5 9.5v1.5M16.5 9.5v1.5"/>',
    ovg: '<path d="M3 3v18h18"/><path d="M18.7 8l-5.1 5.1-2.8-2.8L7 14"/>',
    schema: '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v6c0 1.657 4.03 3 9 3s9-1.343 9-3V5"/><path d="M3 11v6c0 1.657 4.03 3 9 3s9-1.343 9-3v-6"/>',
    gcal: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    netplan: '<rect x="9" y="2" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="16" y="16" width="6" height="6" rx="1"/><path d="M12 8v4M12 12H5v4M12 12h7v4"/>',
  }

  // Module → localStorage key map (used to mark current page's module as "seen")
  var _FILE_MODULE = {
    'dev-crm.html':            'dev_crm',
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
    'env-guide.html':          'env_guide',
    'netarch-guide.html':      'netarch_guide',
    'switch-guide.html':       'switch_guide',
    'monitor-guide.html':      'monitor_guide',
    'access-guide.html':       'access_guide',
    'gateway-guide.html':      'gateway_guide',
    'automation-guide.html':   'automation_guide',
    'selection-db-overview.html': 'selection_db_overview',
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

  function ni(href, icKey, label, activeNames, show, badgeId) {
    if (show === false) {
      _deniedPages = _deniedPages.concat(activeNames || [])
      return ''
    }
    var bspan = badgeId ? '<span id="' + badgeId + '" style="' + _SB_BADGE_STYLE + '"></span>' : ''
    return '<a href="' + href + '" class="nav__item' + act(activeNames) + '" title="' + esc(label) + '">'
      + '<svg class="nav__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">' + ic[icKey] + '</svg>'
      + '<span class="nav__label">' + esc(label) + '</span>'
      + bspan + '</a>'
  }

  function sec(label, show) {
    if (show === false) return ''
    return '<div class="nav__section">' + label + '</div>'
  }

  var canDash = sa || ad || mods.indexOf('finance') >= 0 || mods.indexOf('quotation') >= 0 || mods.indexOf('dashboard') >= 0

  function buildSidebar() {
    var html = [
      sec('主選單'),
      ni(up + 'index.html',          'dash',  '儀表板',   ['index.html', ''],                       canDash),
      sec('業務', cDev || cQ || cCM),
      ni(pg('dev-crm.html'),         'bdev',  '業務開發', ['dev-crm.html'],                          cDev, 'sb-mod-dev-crm'),
      ni(pg('quotations.html'),      'quote', '報價單',   ['quotations.html', 'quotation-form.html'], cQ,   'sb-mod-quotation'),
      (cQ ? '<a href="' + pg('approval-queue.html') + '" class="nav__item' + act(['approval-queue.html']) + '" title="簽核佇列">'
        + '<svg class="nav__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>'
        + '<span class="nav__label">簽核佇列</span>'
        + '<span id="sb-approval-badge" style="display:none;background:#DC2626;color:#fff;font-size:9px;font-weight:700;font-family:LINE Seed TW_OTF, sans-serif;padding:1px 5px;border-radius:8px;margin-left:auto;min-width:16px;text-align:center;line-height:1.6"></span>'
        + '</a>' : ''),
      ni(pg('approval-delegates.html'), 'appr', '簽核代理人', ['approval-delegates.html'], cQ || sa || ad),
      ni(pg('approval-history.html'), 'apprhist', '簽核歷史', ['approval-history.html'], cQ || sa || ad),
      ni(pg('case-management.html'), 'case_', '案件管理', ['case-management.html'],                   cCM,  'sb-mod-case'),
      ni(pg('case-stage-board.html'),'case_', '案件執行看板', ['case-stage-board.html'],               cCM),
      sec('廠商與採購', cCu || cPr),
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
      sec('財務', cFi || cRpt || cCash),
      // 2026-09-13（模組權限稽核）：補上 badge id。`finance` 模組的紅點原本掛在
      // 'sb-mod-finance' / 'sb-mod-sales-orders' 這兩個 id 上，而它們所屬的
      // 應收帳款／銷售訂單兩個側欄項目在 2026-08-31（87e16cb）退役後就不再渲染
      // ——後端 `_MODULE_ACTION_PREFIXES['finance']` 照樣在算 payment./sales_order./
      // settlement. 三種異動的數量，前端卻永遠找不到元素可以顯示，等於這個模組的
      // 通知數字靜靜消失了。那些內容現在都在營運報表頁，紅點就掛回這裡。
      ni(pg('reports.html'),         'rpt',   '營運報表', ['reports.html', 'cashier.html'],          cRpt || cCash || cFi, 'sb-mod-finance'),
      sec('勞務管理', cCon || cPay),
      ni(pg('contractors.html'),     'contl', '外包名冊', ['contractors.html'],                      cCon),
      ni(pg('payslips.html'),        'paysl', '勞報單',   ['payslips.html', 'payslip-form.html'],    cPay),
      sec('工作內容', cWL || cDT),
      ni(pg('work-log.html'),        'wlog',  '工作日誌',   ['work-log.html'],                         cWL,  'sb-mod-worklog'),
      (cDT ? '<a href="' + pg('daily-tasks.html') + '" class="nav__item' + act(['daily-tasks.html']) + '" title="每日工作事項">'
      + '<svg class="nav__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">' + ic['dtask'] + '</svg>'
      + '<span class="nav__label">每日工作事項</span>'
      + '<span id="sb-dt-badge" style="display:none;background:#7C3AED;color:#fff;font-size:9px;font-weight:700;font-family:LINE Seed TW_OTF, sans-serif;padding:1px 5px;border-radius:8px;margin-left:auto;min-width:16px;text-align:center;line-height:1.6"></span>'
      + '<span id="sb-mod-daily-task" style="display:none;background:var(--accent);color:#fff;font-size:9px;font-weight:700;font-family:LINE Seed TW_OTF, sans-serif;padding:1px 5px;border-radius:8px;margin-left:4px;min-width:16px;text-align:center;line-height:1.6"></span>'
      + '</a>' : ''),
      sec('選型資料庫', cEnvG || cNetG || cSwitchG || cMonitorG || cAccessG || cGatewayG || cAutomationG),
      ni(pg('env-guide.html'),      'envg',    '場域選型導覽',     ['env-guide.html'],     cEnvG),
      ni(pg('netarch-guide.html'),  'netg',    '網路架構選型導覽', ['netarch-guide.html'], cNetG),
      ni(pg('switch-guide.html'),   'switchg', '交換器選型導覽',   ['switch-guide.html'],  cSwitchG),
      ni(pg('monitor-guide.html'),  'monitorg', '監控系統選型導覽', ['monitor-guide.html'], cMonitorG),
      ni(pg('access-guide.html'),   'accessg',  '門禁系統選型導覽', ['access-guide.html'],  cAccessG),
      ni(pg('gateway-guide.html'),  'gwg',      '閘道器與控制器選型導覽', ['gateway-guide.html'], cGatewayG),
      ni(pg('automation-guide.html'), 'automationg', '自動化系統選型導覽', ['automation-guide.html'], cAutomationG),
      ni(pg('selection-db-overview.html'), 'ovg', '涵蓋度總覽', ['selection-db-overview.html'], ad),
      sec('系統'),
      ni(pg('users.html'),             'users', '使用者管理', ['users.html'],             sa),
      ni(pg('org-structure.html'),     'org',   '組織架構設定', ['org-structure.html'],   sa),
      ni(pg('approval-settings.html'),      'sett',  '簽核設定',   ['approval-settings.html'],      sa),
      ni(pg('contractor-voucher-approval-settings.html'), 'sett', '匯款申請簽核設定', ['contractor-voucher-approval-settings.html'], sa),
      ni(pg('notification-settings.html'), 'ntfy',  '通知設定',   ['notification-settings.html'],  sa),
      ni(pg('google-calendar-settings.html'), 'gcal', 'Google 行事曆設定', ['google-calendar-settings.html'], sa),
      ni(pg('company-profile-settings.html'), 'co',   '公司資料設定',   ['company-profile-settings.html'], sa),
      ni(pg('audit-log.html'),         'hist',  '歷史紀錄',   ['audit-log.html'],         ad),
      ni(pg('shipping-export-history.html'), 'hist', '出貨單歷史紀錄', ['shipping-export-history.html'], ad),
      ni(pg('module-versions.html'),  'ver',   '版本紀錄',   ['module-versions.html'],               ad),
      ni(pg('online-stats.html'),     'hist',  '在線時數統計', ['online-stats.html'],              sa),
      ni(pg('schema-status.html'),    'schema', 'Schema 狀態', ['schema-status.html'],               sa),
    ].filter(Boolean).join('')

    var el = document.getElementById('app-sidebar')
    if (el) el.innerHTML = html

    // 使用者正站在一個「側欄判定他不該看到」的頁面上 → 顯示沒有權限，而不是
    // 把頁面內容留在那裡讓 API 一路 403（看起來像壞掉，不像沒權限）。
    //
    // **刻意不導轉**：`index.html` 自己也有一道守門（非 admin 且沒有 finance／
    // quotation 模組就導去 case-management.html），導轉會直接做出迴圈——
    // 只有「儀表板」模組的檢視者會在 index ⇄ case-management 之間無限跳。
    // 只處理側欄真的列過的頁面（`_deniedPages` 來自 ni() 的顯示條件），
    // 沒列過的頁面一律放行：寧可漏擋也不要把人鎖在門外，資料那層 API 會擋。
    if (_deniedPages.indexOf(file) >= 0) _showNoPermission()
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
    var _origFetch = window.fetch
    window.fetch = function (url, opts) {
      return _origFetch.apply(this, arguments).then(function (resp) {
        if (resp.ok && opts) {
          var method = (opts.method || '').toUpperCase()
          if (method === 'POST' || method === 'PUT' || method === 'PATCH' || method === 'DELETE') {
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
    quotation:   ['sb-mod-quotation'],
    case_manage: ['sb-mod-case'],
    customer:    ['sb-mod-customer'],
    procurement: ['sb-mod-suppliers', 'sb-mod-vendor', 'sb-mod-parts', 'sb-mod-procurement'],
    equipment:   ['sb-mod-equipment', 'sb-mod-warranty'],
    finance:     ['sb-mod-finance'],   // 2026-09-13：'sb-mod-sales-orders' 隨 sales-orders.html 退役移除
    work_log:    ['sb-mod-worklog'],
    daily_task:  ['sb-mod-daily-task'],
  }

  // 後端 audit_log.at 存的是台灣本地時間（datetime.now().isoformat()，無時區資訊），
  // module-counts 端點用 SQL 字串 "at > ?" 直接比較；若這裡送 UTC 字串（toISOString()
  // 帶 'Z'），本地時間字串在字典序上幾乎恆大於 UTC 字串（差 8 小時），角標會永遠判定
  // 「有更新」。改產生格式一致、無時區尾碼的本地時間字串。
  function _localISOString(d) {
    d = d || new Date()
    var tz = d.getTimezoneOffset() * 60000
    return new Date(d.getTime() - tz).toISOString().slice(0, -1)
  }

  function _clearModBadge(modKey) {
    var bids = _MOD_BADGES[modKey]
    if (!bids) return
    for (var i = 0; i < bids.length; i++) {
      var el = document.getElementById(bids[i])
      if (el) el.style.display = 'none'
    }
  }

  // ── Entry ──────────────────────────────────────────────────────────────────
  function build() {
    var _curMod = _FILE_MODULE[file]

    // For admin+ users: ensure every known module has an entry in motrix_module_seen
    // so _fetchModuleCounts() queries badge counts for ALL modules, not just visited ones.
    // Unvisited modules are seeded with a 7-day lookback timestamp.
    if (s.token && (role === 'superadmin' || role === 'admin')) {
      try {
        var _ms = JSON.parse(localStorage.getItem('motrix_module_seen') || '{}')
        var _seed = _localISOString(new Date(Date.now() - 7 * 86400 * 1000))
        var _allModKeys = Object.keys(_MOD_BADGES)
        var _seeded = false
        for (var _mi = 0; _mi < _allModKeys.length; _mi++) {
          if (!_ms[_allModKeys[_mi]]) {
            _ms[_allModKeys[_mi]] = _seed
            _seeded = true
          }
        }
        if (_seeded) localStorage.setItem('motrix_module_seen', JSON.stringify(_ms))
      } catch (_e) {}
    }

    // Mark current page's module as "seen" so its badge clears on next fetch
    if (_curMod && s.token) {
      try {
        var _ms2 = JSON.parse(localStorage.getItem('motrix_module_seen') || '{}')
        // Save the PREVIOUS seen time so module pages can highlight items updated since last visit
        var _prev = JSON.parse(localStorage.getItem('motrix_module_prev_seen') || '{}')
        if (_ms2[_curMod]) _prev[_curMod] = _ms2[_curMod]
        localStorage.setItem('motrix_module_prev_seen', JSON.stringify(_prev))
        _ms2[_curMod] = _localISOString()
        localStorage.setItem('motrix_module_seen', JSON.stringify(_ms2))
      } catch (_e) {}
    }

    buildTopbar()
    buildSidebar()
    // Defensively clear this module's badge immediately after DOM creation,
    // so it's hidden even if _fetchModuleCounts() hasn't resolved yet.
    if (_curMod) _clearModBadge(_curMod)
    bindMobileToggle()
    bindNavGuard()
  }

  // ── Async session refresh（背景刷新模組權限，有變動立即重建 sidebar）──────────
  function _refreshSession() {
    if (!s || !s.token) return
    fetch('/api/auth/me', { headers: { Authorization: 'Bearer ' + s.token } })
      .then(function (r) { return r.ok ? r.json() : null })
      .then(function (d) {
        if (!d) return
        var stored = JSON.parse(localStorage.getItem('motrix_session') || '{}')
        var modsChanged = JSON.stringify(stored.modules) !== JSON.stringify(d.modules)
        var roleChanged = stored.role !== d.role
        if (!modsChanged && !roleChanged && stored.displayName === d.displayName) return
        stored.role               = d.role
        stored.displayName        = d.displayName
        stored.modules            = d.modules
        stored.mustChangePassword = d.mustChangePassword
        localStorage.setItem('motrix_session', JSON.stringify(stored))
        // 重新計算 flags 並重建 sidebar
        role = d.role
        mods = Array.isArray(d.modules) ? d.modules : []
        sa  = role === 'superadmin'
        ad  = sa || role === 'admin'
        eng = role === 'engineer'
        cQ   = mods.indexOf('quotation')   >= 0 || ad
        cCu  = mods.indexOf('customer')    >= 0 || ad
        cPr  = mods.indexOf('procurement') >= 0 || ad
        cFi  = mods.indexOf('finance')     >= 0 || ad
        cCash = mods.indexOf('cashier')    >= 0 || ad
        cCM  = mods.indexOf('case_manage') >= 0 || eng || ad
        cEq  = mods.indexOf('equipment')   >= 0 || ad
        cInv = mods.indexOf('inventory')   >= 0 || ad
        cRpt = mods.indexOf('reports')     >= 0 || ad
        cWL  = mods.indexOf('work_log')    >= 0 || role !== 'viewer'
        cDT  = mods.indexOf('daily_task')  >= 0 || role !== 'viewer'
        cDev = mods.indexOf('dev_crm')     >= 0 || ad
        cEnvG = mods.indexOf('env_guide')  >= 0 || ad
        cNetG = mods.indexOf('netarch_guide') >= 0 || ad
        cSwitchG = mods.indexOf('switch_guide') >= 0 || ad
        cMonitorG = mods.indexOf('monitor_guide') >= 0 || ad
        cAccessG = mods.indexOf('access_guide') >= 0 || ad
        cGatewayG = mods.indexOf('gateway_guide') >= 0 || ad
        cAutomationG = mods.indexOf('automation_guide') >= 0 || ad
        canDash = sa || ad || mods.indexOf('finance') >= 0 || mods.indexOf('quotation') >= 0 || mods.indexOf('dashboard') >= 0
        buildSidebar()
        var dnEl = document.getElementById('tb-display-name')
        if (dnEl) dnEl.textContent = esc(d.displayName || d.username || '')
      })
      .catch(function () {})
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { build(); _refreshSession() })
  } else {
    build()
    _refreshSession()
  }
})()
