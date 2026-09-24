;(function () {
  var _origFetch = window.fetch
  var _redirecting = false
  window.fetch = async function () {
    var r = await _origFetch.apply(this, arguments)
    if (r.status === 403 && !_redirecting) {
      var clone = r.clone()
      try {
        var d = await clone.json()
        if (d && d.code === 'must_change_password') {
          try {
            var sess = JSON.parse(localStorage.getItem('motrix_session') || '{}')
            sess.mustChangePassword = true
            localStorage.setItem('motrix_session', JSON.stringify(sess))
          } catch (e) {}
          var currentFile = window.location.pathname.split('/').pop()
          if (currentFile !== 'change-password.html') {
            _redirecting = true
            var isPages = window.location.pathname.includes('/pages/')
            window.location.replace(isPages ? 'change-password.html?forced=1' : 'pages/change-password.html?forced=1')
          }
        }
      } catch (e) {}
    }
    return r
  }
})()

// ── 逐筆已讀（UR1）：存伺服器，時間由伺服器蓋 ─────────────────────────────
// 使用者：「點選後紅色未讀沒有即時消失」。規則：
//   ① 點下去**當下**先清 UI，再送請求（keepalive：換頁中也送得出去），不等回應
//   ② 標記之後寫 `motrix_reads_bump` ⇒ 其他分頁的 `storage` 事件會重抓
//   ③ 上一頁回來（pageshow persisted）也重抓
//   各頁監聽 `motrix:reads-changed` 事件重抓自己的清單標記。
window.MotrixReads = (function () {
  var BUMP_KEY = 'motrix_reads_bump'
  var MIGRATED_KEY = 'motrix_reads_migrated_v1'
  function _tok() {
    try { return (JSON.parse(localStorage.getItem('motrix_session') || '{}') || {}).token || '' } catch (e) { return '' }
  }
  function _bump() {
    try { localStorage.setItem(BUMP_KEY, String(Date.now()) + ':' + Math.random()) } catch (e) {}
  }
  function _post(url, body) {
    var t = _tok()
    if (!t) return Promise.resolve(null)
    return fetch(url, {
      method: 'POST', keepalive: true,
      headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).catch(function () { return null })
  }

  // 舊 localStorage「看過」紀錄：第一次載入時一次性上傳，之後停用。
  // ⚠️ 必須在第一次查未讀之前完成：伺服器的基準只會往後推，
  //    先建了「現在」的基準，較舊的舊紀錄就蓋不過去了。
  var _ready = (function migrate() {
    try {
      if (localStorage.getItem(MIGRATED_KEY) === '1' || !_tok()) return Promise.resolve()
      var items = []
      var seen = JSON.parse(localStorage.getItem('motrix_module_seen') || '{}') || {}
      Object.keys(seen).forEach(function (m) { items.push({ kind: 'module', key: m, read_at: seen[m] }) })
      var prev = JSON.parse(localStorage.getItem('motrix_module_prev_seen') || '{}') || {}
      if (prev.daily_task) items.push({ kind: 'baseline', key: 'daily_task', read_at: prev.daily_task })
      var dc = localStorage.getItem('motrix_devcrm_read_at')
      if (dc) items.push({ kind: 'baseline', key: 'dev_case', read_at: dc })
      var cm = localStorage.getItem('motrix_casemgmt_read_at')
      if (cm) items.push({ kind: 'baseline', key: 'case', read_at: cm })
      if (!items.length) { localStorage.setItem(MIGRATED_KEY, '1'); return Promise.resolve() }
      return _post('/api/reads/batch', { items: items }).then(function (r) {
        if (!r || !r.ok) return
        localStorage.setItem(MIGRATED_KEY, '1')
        var old = ['motrix_module_seen', 'motrix_module_prev_seen', 'motrix_devcrm_read_at', 'motrix_casemgmt_read_at']
        old.forEach(function (k) { try { localStorage.removeItem(k) } catch (e) {} })
      })
    } catch (e) { return Promise.resolve() }
  })()

  function _changed() {
    try { window.dispatchEvent(new CustomEvent('motrix:reads-changed')) } catch (e) {}
  }
  window.addEventListener('storage', function (e) { if (e.key === BUMP_KEY) _changed() })
  window.addEventListener('pageshow', function (e) { if (e.persisted) _changed() })

  // ── 跨分頁「樂觀已讀」（使用者：「要再優化」）──────────────────────────
  //   標記的**當下**就告訴其他分頁是哪一筆（不等伺服器）：點了之後立刻換頁，
  //   本分頁後續的程式不會再跑，而其他分頁仍會在當下同步。
  //   其他分頁只**合併那一筆**（`motrix:item-read`），不整包重抓。
  //   伺服器**明確拒絕**（HTTP 錯誤）⇒ 廣播 failed，各分頁還原那一筆。
  //   ⚠️ 網路錯誤**不**還原：換頁時 keepalive 的請求仍可能送達，還原會與伺服器相反。
  var OPT_KEY = 'motrix_reads_optimistic'
  var _ch = null
  try { if ('BroadcastChannel' in window) _ch = new BroadcastChannel('motrix-reads') } catch (e) {}
  function _emit(msg) {
    if (!msg || !msg.kind) return
    var name = msg.type === 'failed' ? 'motrix:item-read-failed' : 'motrix:item-read'
    try { window.dispatchEvent(new CustomEvent(name, { detail: { kind: msg.kind, key: String(msg.key) } })) } catch (e) {}
  }
  function _announce(msg) {
    try {
      if (_ch) _ch.postMessage(msg)
      else localStorage.setItem(OPT_KEY, JSON.stringify({ type: msg.type, kind: msg.kind, key: msg.key, n: Math.random() }))
    } catch (e) {}
  }
  if (_ch) _ch.onmessage = function (e) { _emit(e.data) }
  window.addEventListener('storage', function (e) {
    if (e.key === OPT_KEY && e.newValue) { try { _emit(JSON.parse(e.newValue)) } catch (x) {} }
  })

  return {
    ready: _ready,
    /** 標記一筆已讀：呼叫端要**先**清自己的 UI，這裡只負責送出與通知其他分頁。 */
    mark: function (kind, key) {
      key = String(key)
      _announce({ type: 'read', kind: kind, key: key })
      // ⚠️ 伺服器收到**之後**才發「整包重抓」的通知：先發的話，對方重抓時伺服器還沒記下。
      return _post('/api/reads', { kind: kind, key: key }).then(function (r) {
        if (r && !r.ok) {
          var m = { type: 'failed', kind: kind, key: key }
          _announce(m)
          _emit(m)              // 本分頁也還原（BroadcastChannel 不會送回給自己）
        } else if (r) {
          _bump()
        }
        return r
      })
    },
    /** 回 Set：伺服器判斷的未讀鍵（已排除本人、已套可見性）。 */
    unread: function (kind, keys) {
      return _ready.then(function () {
        var t = _tok()
        if (!t || !keys || !keys.length) return new Set()
        return fetch('/api/reads/unread', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' },
          body: JSON.stringify({ kind: kind, keys: keys.map(String) }),
        }).then(function (r) { return r.ok ? r.json() : { unread: [] } })
          .then(function (d) { return new Set(d.unread || []) })
          .catch(function () { return new Set() })
      })
    },
  }
})()

function notifStore() {
  const isPages = window.location.pathname.includes('/pages/')
  const auditHref = isPages ? 'audit-log.html' : 'pages/audit-log.html'
  const queueHref = isPages ? 'approval-queue.html' : 'pages/approval-queue.html'
  return {
    open:   false,
    items:  [],
    unread: 0,
    auditHref,
    _sess: null,
    _popupShown: false,

    // 🔴 這兩支 store 是 `sidebar.js` **注入**的 ⇒ **每一頁都跑兩遍**，
    //    而 53 頁那份待修清單裡**沒有它們**（工具只掃 pages/*.html）。
    // ⚠️ 宣告點在 `sidebar.js`，**定義點在這裡** —— 數的檔與改的檔不是同一個。
    // ☠️ notifStore 的 init() 是 `Promise.all` 六支 fetch
    //    ⇒ 沒有守衛時**每次開頁 12 個請求不是 6**。
    _initDone: false,

    async init() {
      if (this._initDone) return
      this._initDone = true
      this._sess = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      if (!this._sess.token) return
      if (this._sess.mustChangePassword) return
      window.addEventListener('motrix:reads-changed', () => this.refresh())
      await Promise.all([this._fetchNotifications(), this._fetchApprovalCount(), this._fetchDailyTaskCount(), this._fetchModuleCounts(), this._fetchTotpReminder()])
    },

    /** 上一頁回來／其他分頁標了已讀 ⇒ 鈴鐺與選單數字重抓。 */
    refresh() {
      if (!this._sess?.token) return
      this._fetchNotifications()
      this._fetchModuleCounts()
    },

    async _fetchTotpReminder() {
      // 架構地圖 §6.2：superadmin/admin 自助啟用 TOTP，非強制——見
      // routers/auth.py totp_* 端點與 db.py::_m072_totp() docstring。這裡只是
      // 提醒，每個分頁（sessionStorage）最多彈一次，不會每換頁就再跳出來，
      // 且刻意不在 change-password.html 本身顯示（那裡就是設定入口，重複無意義）。
      try {
        const role = this._sess?.role || ''
        if (role !== 'superadmin' && role !== 'admin') return
        const currentFile = window.location.pathname.split('/').pop()
        if (currentFile === 'change-password.html') return
        const ssKey = 'motrix_totp_reminder_shown'
        if (sessionStorage.getItem(ssKey)) return
        const r = await fetch('/api/auth/totp/status', {
          headers: { Authorization: 'Bearer ' + this._sess.token }
        })
        if (!r.ok) return
        const d = await r.json()
        if (d.enabled) return
        sessionStorage.setItem(ssKey, '1')
        const isPages = window.location.pathname.includes('/pages/')
        setTimeout(() => this._showTotpReminderBanner(isPages ? 'change-password.html' : 'pages/change-password.html'), 1400)
      } catch (e) {}
    },

    async _fetchNotifications() {
      try {
        const r = await fetch('/api/notifications/mine', {
          headers: { Authorization: 'Bearer ' + this._sess.token }
        })
        if (!r.ok) return
        const d = await r.json()
        const items = d.items || []
        // 鈴鐺 badge 只計非簽核類通知（簽核類由 sidebar badge 獨立顯示）⇒ 下拉也只列這些，
        // 否則數字與清單對不起來。
        this.items = items.filter(i => i.type !== 'approval_request')
        this.unread = this.items.filter(i => !i.is_read).length

        // Banner 每個 browser session（tab）最多顯示一次，避免每換頁都彈出
        const pending = items.filter(i => !i.is_read && i.type === 'approval_request')
        const ssKey = 'motrix_approval_banner_shown'
        if (pending.length > 0 && !this._popupShown && !sessionStorage.getItem(ssKey)) {
          this._popupShown = true
          sessionStorage.setItem(ssKey, '1')
          setTimeout(() => this._showApprovalBanner(pending.length, queueHref), 900)
        }
      } catch(e) {}
    },

    async _fetchModuleCounts() {
      try {
        const _role = this._sess?.role || ''
        if (_role !== 'superadmin' && _role !== 'admin') return
        // UR1：「看過」時間存伺服器（`/api/reads`），不再讀 localStorage
        //   ⇒ 換電腦、上一頁回來、其他分頁都看到同一個結果。
        if (window.MotrixReads) await window.MotrixReads.ready
        var r = await fetch('/api/reads/module-counts', {
          headers: { Authorization: 'Bearer ' + this._sess.token }
        })
        if (!r.ok) return
        var d = await r.json()
        // 🔴 與 sidebar.js `_MOD_BADGES` 同一組 key（test_module_badge_maps_agree 守）。
        var modBadge = {
          dev_crm:    ['sb-mod-dev-crm'],
          tender_radar: ['sb-mod-tender-radar'],
          quotation:  ['sb-mod-quotation'],
          case_manage:['sb-mod-case'],
          customer:   ['sb-mod-customer'],
          procurement:['sb-mod-suppliers', 'sb-mod-vendor', 'sb-mod-parts', 'sb-mod-procurement'],
          equipment:  ['sb-mod-equipment', 'sb-mod-warranty'],
          finance:    ['sb-mod-finance'],   // 2026-09-13：見 sidebar.js 同一張表
          work_log:   ['sb-mod-worklog'],
          daily_task: ['sb-mod-daily-task'],
        }
        for (var k in d) {
          var bids = modBadge[k]
          if (!bids) continue
          // 目前這一頁所屬的模組：已經在 sidebar.js 標成看過（請求可能還在路上）⇒ 不要再亮起來。
          var cnt = (k === window.motrixCurrentModule) ? 0 : (d[k] || 0)
          for (var bi = 0; bi < bids.length; bi++) {
            var el = document.getElementById(bids[bi])
            if (!el) continue
            if (cnt > 0) {
              el.textContent = cnt > 9 ? '9+' : String(cnt)
              el.style.display = 'inline-block'
            } else {
              el.style.display = 'none'
            }
          }
        }
      } catch(_e) {}
    },

    async _fetchApprovalCount() {
      try {
        const r = await fetch('/api/approval-queue/count', {
          headers: { Authorization: 'Bearer ' + this._sess.token }
        })
        if (!r.ok) return
        const d = await r.json()
        this._updateApprovalBadge(d.count || 0)
      } catch(e) {}
    },

    _updateApprovalBadge(count) {
      const badge = document.getElementById('sb-approval-badge')
      if (!badge) return
      if (count > 0) {
        badge.textContent = count > 9 ? '9+' : String(count)
        badge.style.display = 'inline-block'
      } else {
        badge.style.display = 'none'
      }
    },

    async _fetchDailyTaskCount() {
      try {
        const me = this._sess.username
        if (!me) return
        const today = new Date().toISOString().slice(0, 10)
        const r = await fetch('/api/daily-tasks?date=' + today + '&username=' + encodeURIComponent(me), {
          headers: { Authorization: 'Bearer ' + this._sess.token }
        })
        if (!r.ok) return
        const d = await r.json()
        let pending = 0
        for (const t of (d.items || [])) {
          if (!(t.assigned_to || []).includes(me)) continue
          const myComp = (t.completions || []).find(function(c) { return c.username === me })
          if (!myComp || !myComp.completed) pending++
        }
        this._updateDTBadge(pending)
      } catch(e) {}
    },

    _updateDTBadge(count) {
      const badge = document.getElementById('sb-dt-badge')
      if (!badge) return
      if (count > 0) {
        badge.textContent = count > 9 ? '9+' : String(count)
        badge.style.display = 'inline-block'
      } else {
        badge.style.display = 'none'
      }
    },

    toggle() {
      // UR1：打開下拉**不再**全部標為已讀——點哪一則標哪一則（`markOne`）。
      this.open = !this.open
    },

    /** 點一則：當下先改畫面，再送出（keepalive、不等回應）。 */
    markOne(item) {
      if (!item || !this._sess?.token) return
      if (!item.is_read) {
        item.is_read = 1
        this.unread = Math.max(0, this.unread - 1)
        fetch('/api/notifications/' + encodeURIComponent(item.id) + '/read', {
          method: 'PATCH', keepalive: true,
          headers: { Authorization: 'Bearer ' + this._sess.token }
        }).then(() => {
          try { localStorage.setItem('motrix_reads_bump', String(Date.now())) } catch (e) {}
        }).catch(() => {})
      }
    },

    markAllNotifications() {
      if (!this._sess?.token) return
      this.items.forEach(i => { i.is_read = 1 })
      this.unread = 0
      fetch('/api/notifications/read-all', {
        method: 'PATCH', keepalive: true,
        headers: { Authorization: 'Bearer ' + this._sess.token }
      }).then(() => {
        try { localStorage.setItem('motrix_reads_bump', String(Date.now())) } catch (e) {}
      }).catch(() => {})
      // 清除 session flag，讓下一批新簽核通知能再次顯示
      sessionStorage.removeItem('motrix_approval_banner_shown')
    },

    actionLabel(action) {
      const map = {
        'auth.login':              '使用者登入',
        'auth.change_password':    '修改密碼',
        'quotation.create':        '新增報價單',
        'quotation.submit':        '送出審核',
        'quotation.approve':       '簽核通過',
        'quotation.reject':        '退回草稿',
        'quotation.update':        '更新報價單',
        'quotation.delete':        '刪除報價單',
        'quotation.status_change': '狀態變更',
        'quotation.export_pdf':    '匯出 PDF',
        'deal_tag.change':         '案件進度',
        'customer.create':         '新增客戶',
        'customer.update':         '更新客戶',
        'customer.delete':         '刪除客戶',
        'supplier.create':         '新增供應商',
        'supplier.update':         '更新供應商',
        'supplier.delete':         '刪除供應商',
        'payment.mark':            '收款標記',
        'user.create':             '新增使用者',
        'user.update':             '更新使用者',
        'settings.approval_flow.update': '簽核設定更新',
        'daily_task.create':       '新增工作事項',
        'daily_task.update':       '更新工作事項',
        'daily_task.delete':       '刪除工作事項',
        'daily_task.complete':     '完成工作回報',
        'daily_task.uncomplete':   '取消工作回報',
      }
      return map[action] || action
    },

    actionColor(action) {
      if (action.includes('delete') || action.includes('reject')) return '#dc2626'
      if (action === 'quotation.approve') return '#16a34a'
      if (action === 'quotation.submit')  return '#2563eb'
      if (action === 'auth.login')        return '#6b7280'
      if (action === 'payment.mark')      return '#d97706'
      return '#2563eb'
    },

    formatTime(at) {
      if (!at) return ''
      const d   = new Date(at)
      const now = new Date()
      const diff = (now - d) / 1000
      if (diff < 60)    return '剛剛'
      if (diff < 3600)  return Math.floor(diff / 60) + ' 分鐘前'
      if (diff < 86400) return Math.floor(diff / 3600) + ' 小時前'
      return d.toLocaleDateString('zh-TW', { month: 'numeric', day: 'numeric' }) + ' ' +
             d.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })
    },

    _showApprovalBanner(count, href) {
      if (document.getElementById('approval-notif-banner')) return
      const el = document.createElement('div')
      el.id = 'approval-notif-banner'
      el.style.cssText = [
        'position:fixed;top:72px;right:20px',
        'background:#EEF2FF;border:1.5px solid #6366F1',
        'border-radius:10px;padding:14px 18px',
        'box-shadow:0 6px 24px rgba(99,102,241,.22)',
        'z-index:99999;font-family:LINE Seed TW_OTF, sans-serif;max-width:300px',
        'animation:notif-slide-in .25s ease',
      ].join(';')
      // Build banner DOM without innerHTML to avoid XSS from count/href
      const row = document.createElement('div')
      row.style.cssText = 'display:flex;align-items:flex-start;gap:10px'

      const icon = document.createElement('div')
      icon.style.cssText = 'color:#4F46E5;flex-shrink:0;margin-top:1px'
      icon.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6 6 0 10-12 0v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/></svg>'

      const body = document.createElement('div')
      body.style.cssText = 'flex:1'

      const title = document.createElement('div')
      title.style.cssText = 'font-size:13px;font-weight:600;color:#3730A3;margin-bottom:4px'
      title.textContent = '待簽核通知'

      const msg = document.createElement('div')
      msg.style.cssText = 'font-size:12px;color:#4338CA;line-height:1.5'
      const b = document.createElement('b')
      b.textContent = String(Number(count))
      msg.append('您有 ', b, ' 份報價單等待您簽核')

      const link = document.createElement('a')
      link.href = href
      link.style.cssText = 'display:inline-block;margin-top:8px;font-size:11px;color:#fff;background:#6366F1;padding:4px 12px;border-radius:5px;text-decoration:none;font-weight:600'
      link.textContent = '前往簽核 →'

      body.append(title, msg, link)

      const closeBtn = document.createElement('button')
      closeBtn.style.cssText = 'border:none;background:none;cursor:pointer;color:#9CA3AF;font-size:20px;line-height:1;padding:0;flex-shrink:0;margin-top:-2px'
      closeBtn.textContent = '×'
      closeBtn.addEventListener('click', () => el.remove())

      row.append(icon, body, closeBtn)
      el.appendChild(row)
      if (!document.querySelector('#notif-kf')) {
        const s = document.createElement('style')
        s.id = 'notif-kf'
        s.textContent = '@keyframes notif-slide-in{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}'
        document.head.appendChild(s)
      }
      document.body.appendChild(el)
      setTimeout(() => {
        if (el.parentNode) {
          el.style.transition = 'opacity .5s'
          el.style.opacity = '0'
          setTimeout(() => el.remove(), 500)
        }
      }, 7000)
    },

    _showTotpReminderBanner(href) {
      if (document.getElementById('totp-reminder-banner')) return
      const el = document.createElement('div')
      el.id = 'totp-reminder-banner'
      el.style.cssText = [
        'position:fixed;top:72px;right:20px',
        'background:#FFFBEB;border:1.5px solid #D97706',
        'border-radius:10px;padding:14px 18px',
        'box-shadow:0 6px 24px rgba(217,119,6,.22)',
        'z-index:99999;font-family:LINE Seed TW_OTF, sans-serif;max-width:300px',
        'animation:notif-slide-in .25s ease',
      ].join(';')
      const row = document.createElement('div')
      row.style.cssText = 'display:flex;align-items:flex-start;gap:10px'

      const icon = document.createElement('div')
      icon.style.cssText = 'color:#B45309;flex-shrink:0;margin-top:1px'
      icon.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="10" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>'

      const body = document.createElement('div')
      body.style.cssText = 'flex:1'

      const title = document.createElement('div')
      title.style.cssText = 'font-size:13px;font-weight:600;color:#92400E;margin-bottom:4px'
      title.textContent = '尚未啟用兩步驟驗證'

      const msg = document.createElement('div')
      msg.style.cssText = 'font-size:12px;color:#B45309;line-height:1.5'
      msg.textContent = '密碼外洩時，兩步驟驗證能多一道防線擋下未授權登入，建議管理員帳號啟用。'

      const link = document.createElement('a')
      link.href = href
      link.style.cssText = 'display:inline-block;margin-top:8px;font-size:11px;color:#fff;background:#D97706;padding:4px 12px;border-radius:5px;text-decoration:none;font-weight:600'
      link.textContent = '前往設定 →'

      body.append(title, msg, link)

      const closeBtn = document.createElement('button')
      closeBtn.style.cssText = 'border:none;background:none;cursor:pointer;color:#C2954D;font-size:20px;line-height:1;padding:0;flex-shrink:0;margin-top:-2px'
      closeBtn.textContent = '×'
      closeBtn.addEventListener('click', () => el.remove())

      row.append(icon, body, closeBtn)
      el.appendChild(row)
      if (!document.querySelector('#notif-kf')) {
        const s = document.createElement('style')
        s.id = 'notif-kf'
        s.textContent = '@keyframes notif-slide-in{from{opacity:0;transform:translateY(-8px)}to{opacity:1;transform:translateY(0)}}'
        document.head.appendChild(s)
      }
      document.body.appendChild(el)
      setTimeout(() => {
        if (el.parentNode) {
          el.style.transition = 'opacity .5s'
          el.style.opacity = '0'
          setTimeout(() => el.remove(), 500)
        }
      }, 9000)
    }
  }
}

/* ── 全域搜尋（topbar）─────────────────────────────────────────────────────
   跨客戶/供應商/報價單/業務開發案/料號快速查找；後端 GET /api/search 已依各模組
   既有角色規則過濾，前端不需再判斷可見性。無 ?id= 深連結的清單頁（客戶/供應商/
   業務開發案/料號）點擊後導向該模組列表頁，只有報價單支援直達單筆。 */
function globalSearchStore() {
  const isPages = window.location.pathname.includes('/pages/')
  const href = (name) => isPages ? name : 'pages/' + name
  const empty = () => ({ customers: [], suppliers: [], quotations: [], devCases: [], parts: [] })

  return {
    q:       '',
    open:    false,
    loading: false,
    results: empty(),
    _sess:   null,
    _timer:  null,

    // 🔴 這兩支 store 是 `sidebar.js` **注入**的 ⇒ **每一頁都跑兩遍**，
    //    而 53 頁那份待修清單裡**沒有它們**（工具只掃 pages/*.html）。
    // ⚠️ 宣告點在 `sidebar.js`，**定義點在這裡** —— 數的檔與改的檔不是同一個。
    // ☠️ notifStore 的 init() 是 `Promise.all` 六支 fetch
    //    ⇒ 沒有守衛時**每次開頁 12 個請求不是 6**。
    _initDone: false,

    init() {
      if (this._initDone) return
      this._initDone = true
      this._sess = JSON.parse(localStorage.getItem('motrix_session') || '{}')
    },

    get hasResults() {
      const r = this.results
      return (r.customers.length + r.suppliers.length + r.quotations.length + r.devCases.length + r.parts.length) > 0
    },

    onInput() {
      clearTimeout(this._timer)
      const term = this.q.trim()
      if (!term) { this.results = empty(); this.open = false; return }
      this._timer = setTimeout(() => this._search(term), 300)
    },

    async _search(term) {
      if (!this._sess?.token) return
      this.loading = true
      try {
        const r = await fetch('/api/search?q=' + encodeURIComponent(term), {
          headers: { Authorization: 'Bearer ' + this._sess.token }
        })
        if (r.ok) { this.results = await r.json(); this.open = true }
      } catch (e) {} finally { this.loading = false }
    },

    goCustomer()      { window.location.href = href('customers.html') },
    goSupplier()      { window.location.href = href('suppliers.html') },
    goQuotation(no)   { window.location.href = href('quotation-form.html') + '?id=' + encodeURIComponent(no) },
    goDevCase()       { window.location.href = href('dev-crm.html') },
    goPart()          { window.location.href = href('parts.html') },

    close() { this.open = false; this.q = ''; this.results = empty() }
  }
}
