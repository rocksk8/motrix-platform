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
        + 'border:none;cursor:pointer;font-size:11px;font-family:Inter,sans-serif;'
        + 'padding:0 7px;height:22px;line-height:22px;border-radius:3px;'
        + 'transition:background .15s,color .15s">'
        + step.label
        + '</button>'
    }).join('')
    return '<div style="display:flex;align-items:center;border:1px solid #333;border-radius:4px;overflow:hidden;margin-right:4px" title="調整字體大小">'
      + btns
      + '</div>'
  }

  // ── Topbar ─────────────────────────────────────────────────────────────────
  function buildTopbar() {
    var el = document.getElementById('app-topbar')
    if (!el) return

    var cpHref = inPg ? 'change-password.html' : 'pages/change-password.html'

    // Notification bell (Alpine scope is self-contained inside notifStore())
    var bell =
      '<div x-data="notifStore()" x-init="init()" style="position:relative">'
      + '<button class="topbar__btn" @click="toggle()" style="position:relative">'
      + '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6 6 0 10-12 0v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/></svg>'
      + '通知'
      + '<span x-show="unread>0" x-text="unread>9?\'9+\':unread"'
      + ' style="background:var(--danger);color:#fff;font-size:9px;padding:1px 5px;border-radius:8px;font-family:Inter,sans-serif;font-weight:700;min-width:16px;text-align:center"></span>'
      + '</button>'
      + '<div x-show="open" @click.outside="open=false"'
      + ' style="display:none;position:absolute;top:calc(100% + 6px);right:0;width:310px;background:#fff;border:1px solid var(--border);border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,.13);z-index:999;overflow:hidden">'
      + '<div style="padding:11px 16px;border-bottom:1px solid var(--border-light);font-size:13px;font-weight:600;color:var(--text-main)">近期操作</div>'
      + '<div style="max-height:320px;overflow-y:auto">'
      + '<template x-for="item in items" :key="item.id">'
      + '<div style="padding:10px 16px;border-bottom:1px solid var(--border-light)">'
      + '<div style="display:flex;justify-content:space-between;align-items:center">'
      + '<span x-text="actionLabel(item.action)" :style="`color:${actionColor(item.action)};font-size:12px;font-weight:600`"></span>'
      + '<span x-text="formatTime(item.at)" style="font-size:10px;color:var(--text-dim);font-family:Inter,sans-serif"></span>'
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

    el.innerHTML =
      '<button class="sidebar-toggle" id="sidebar-toggle" aria-label="選單" title="選單">'
      + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:20px;height:20px;"><path d="M4 6h16M4 12h16M4 18h16"/></svg>'
      + '</button>'
      + '<a href="' + up + 'index.html" class="topbar__logo">'
      + '<img src="' + up + 'static/logo.png" alt="MOTRIX" style="height:26px"'
      + ' onerror="this.replaceWith(Object.assign(document.createElement(\'span\'),{textContent:\'MOTRIX\',style:\'color:#F5F4F0;font-family:Inter,sans-serif;font-weight:700;font-size:15px;letter-spacing:.08em\'}))">'
      + '</a>'
      + '<div class="topbar__divider"></div>'
      + '<span class="topbar__title">Motrix 營運系統</span>'
      + '<div class="topbar__right">'
      + '<span id="tb-display-name" style="font-size:12px;color:#888;font-family:Inter,sans-serif">' + esc(dn) + '</span>'
      + buildFontCtrl()
      + bell
      + '<a href="' + cpHref + '" class="topbar__btn" style="text-decoration:none;color:#888;border-color:#333;font-size:11px">修改密碼</a>'
      + '<button class="topbar__btn" onclick="motrixLogout()" style="color:#888;border-color:#333;font-size:11px">登出</button>'
      + '<div class="topbar__avatar">' + esc(av) + '</div>'
      + '</div>'

    // Process Alpine directives in the injected topbar (notifStore x-data)
    if (window.Alpine && window.Alpine.initTree) window.Alpine.initTree(el)
  }

  // ── Sidebar ─────────────────────────────────────────────────────────────────
  var sa  = role === 'superadmin'
  var ad  = sa || role === 'admin'
  var eng = role === 'engineer'
  var cQ  = mods.indexOf('quotation')   >= 0 || ad
  var cCu = mods.indexOf('customer')    >= 0 || ad
  var cPr = mods.indexOf('procurement') >= 0 || ad
  var cFi = mods.indexOf('finance')     >= 0 || ad
  var cCM = mods.indexOf('case_manage') >= 0 || eng || ad
  var cPj = (sa || ad || eng) || mods.some(function (m) { return m.slice(0, 8) === 'project_' })

  var ic = {
    dash:  '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    wlog:  '<path d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>',
    quote: '<path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0119 9.414V19a2 2 0 01-2 2z"/>',
    cust:  '<path d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0"/>',
    case_: '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2"/>',
    proj:  '<path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>',
    order: '<path d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2 9m12-9l2 9M9 21h6"/>',
    part:  '<path d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10"/>',
    proc:  '<path d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2V9M9 21H5a2 2 0 01-2-2V9m0 0h18"/>',
    supp:  '<path d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-2 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>',
    dev:   '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    warr:  '<path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>',
    recv:  '<path d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1"/>',
    rpt:   '<path d="M9 17v-2m3 2v-4m3 4v-6M3 21h18M3 10l9-7 9 7M12 3v1"/>',
    users: '<path d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"/>',
    sett:  '<path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><circle cx="12" cy="12" r="3"/>',
    hist:  '<path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414A1 1 0 0119 9.414V19a2 2 0 01-2 2z"/>',
  }

  function ni(href, icKey, label, activeNames, show) {
    if (show === false) return ''
    return '<a href="' + href + '" class="nav__item' + act(activeNames) + '">'
      + '<svg class="nav__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">' + ic[icKey] + '</svg>'
      + label + '</a>'
  }

  function sec(label, show) {
    if (show === false) return ''
    return '<div class="nav__section">' + label + '</div>'
  }

  var canDash = sa || ad || mods.indexOf('finance') >= 0 || mods.indexOf('quotation') >= 0

  function buildSidebar() {
    var html = [
      sec('主選單'),
      ni(up + 'index.html',          'dash',  '儀表板',   ['index.html', ''],                       canDash),
      sec('業務', cQ || cCM || cPj),
      ni(pg('quotations.html'),      'quote', '報價單',   ['quotations.html', 'quotation-form.html'], cQ),
      ni(pg('case-management.html'), 'case_', '案件管理', ['case-management.html'],                   cCM),
      ni(pg('projects.html'),        'proj',  '專案管理', ['projects.html'],                          cPj),
      sec('廠商與採購', cCu || cPr),
      ni(pg('customers.html'),       'cust',  '客戶管理', ['customers.html', 'customer-log.html'],   cCu),
      ni(pg('suppliers.html'),       'supp',  '供應商管理', ['suppliers.html', 'supplier-log.html'], cPr),
      ni(pg('parts.html'),           'part',  '料號主檔',  ['parts.html'],                           cPr),
      ni(pg('procurement.html'),     'proc',  '採購管理',  ['procurement.html'],                     cPr),
      sec('設備'),
      ni(pg('devices.html'),         'dev',   '設備登載', ['devices.html']),
      ni(pg('warranty.html'),        'warr',  '保固追蹤', ['warranty.html']),
      sec('財務', cFi),
      ni(pg('receivables.html'),     'recv',  '應收帳款', ['receivables.html'],                      cFi),
      ni(pg('reports.html'),         'rpt',   '營運報表', ['reports.html'],                          ad),
      sec('出勤'),
      ni(pg('work-log.html'),        'wlog',  '工作日誌', ['work-log.html']),
      sec('系統'),
      ni(pg('users.html'),             'users', '使用者管理', ['users.html'],             sa),
      ni(pg('approval-settings.html'), 'sett',  '簽核設定',   ['approval-settings.html'], sa),
      ni(pg('audit-log.html'),         'hist',  '歷史紀錄',   ['audit-log.html'],         ad),
      ni(pg('contractors.html'),       'cust',  '外包名冊',   ['contractors.html'],       sa),
      ni(pg('payslips.html'),          'hist',  '勞報單',     ['payslips.html', 'payslip-form.html'], sa),
    ].filter(Boolean).join('')

    var el = document.getElementById('app-sidebar')
    if (el) el.innerHTML = html
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

  // ── Entry ──────────────────────────────────────────────────────────────────
  function build() {
    buildTopbar()
    buildSidebar()
    bindMobileToggle()
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build)
  } else {
    build()
  }
})()
