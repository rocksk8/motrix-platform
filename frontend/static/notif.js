;(function () {
  if (window.MOTRIX_PREVIEW || window.MOTRIX_EMBED) return   // 建構器即時預覽（BUILDER-UX §3.3）／被嵌入的頁面（方案 B）：不打 API、不彈橫幅
  var _origFetch = window.fetch
  var _redirecting = false
  // ── 本公司資料設定閘門（COMPANY-SETUP-GATE §3.6、§4.2）──────────────────────────
  // ① 428 company_setup_required ⇒ 最高管理者導向設定頁、其他人導向說明頁（這兩頁本身與登入頁不導）
  // ② 回應標頭 X-Motrix-Company-Setup（status_error／grace）⇒ 所有頁面頂端橫幅；之後的 /api 回應沒有這個標頭 ⇒ 移除
  var _SETUP_BANNER_TEXT = {
    status_error: '本公司設定狀態無法判定，對外文件暫停輸出，請聯絡管理員',
    grace: '本公司資料尚未確認，目前為暫時放行（有期限），請最高管理者儘快到「公司資料設定」確認',
  }
  function _setupBanner(kind) {
    var el = document.getElementById('motrix-company-setup-banner')
    if (!kind || !_SETUP_BANNER_TEXT[kind]) { if (el) el.remove(); return }
    if (!document.body) return
    if (!el) {
      el = document.createElement('div')
      el.id = 'motrix-company-setup-banner'
      el.setAttribute('role', 'alert')
      el.style.cssText = 'position:sticky;top:0;z-index:9999;padding:8px 14px;font-size:13px;text-align:center;' +
        'background:var(--danger-light);color:var(--danger);border-bottom:1px solid var(--danger-border)'
      document.body.insertBefore(el, document.body.firstChild)
    }
    el.setAttribute('data-kind', kind)
    el.textContent = _SETUP_BANNER_TEXT[kind]
  }
  // ── 授權閘門（helpers/licensing.py；T80）──────────────────────────────────────
  // ① 402 license_required ⇒ 導向「授權無法使用」說明頁（不是系統壞了；頁上講原因與找誰）。說明頁與登入頁本身不導。
  // ② 回應標頭 X-Motrix-License：`emergency;until=YYYY-MM-DD`（授權金鑰失效、靠緊急放行通行證撐著）／`dev_key`
  //    （裝的是開發金鑰簽的授權）⇒ 所有頁面頂端橫幅；值 `none` ⇒ 移除橫幅。**已登入**的請求回應一定帶這個標頭（有提示＝值、沒有＝none）；
  //    公開／未登入的回應沒有標頭 ⇒ 不動橫幅（不然呼叫一次公開端點橫幅就閃掉）。
  function _licenseBanner(value) {
    var el = document.getElementById('motrix-license-banner')
    var text = ''
    if (value) {
      if (value.indexOf('emergency') === 0) {
        var m = /until=([0-9-]+)/.exec(value)
        text = '授權金鑰目前無法通過驗證，系統暫時靠「緊急放行通行證」運作' + (m ? '（至 ' + m[1] + '）' : '') +
          '。請盡快聯絡供應商處理；通行證到期後系統將停止使用。'
      } else if (value === 'dev_key') {
        text = '這台伺服器使用的是開發用授權金鑰，不是正式金鑰。請聯絡供應商換發正式授權金鑰。'
      }
    }
    if (!text) { if (el) el.remove(); return }
    if (!document.body) return
    if (!el) {
      el = document.createElement('div')
      el.id = 'motrix-license-banner'
      el.setAttribute('role', 'alert')
      el.style.cssText = 'position:sticky;top:0;z-index:9998;padding:8px 14px;font-size:13px;text-align:center;' +
        'background:var(--warning-light);color:var(--warning);border-bottom:1px solid var(--warning)'
      document.body.insertBefore(el, document.body.firstChild)
    }
    el.setAttribute('data-kind', value.indexOf('emergency') === 0 ? 'emergency' : 'dev_key')
    el.textContent = text
  }
  // ③ 回應標頭 X-Motrix-License-Expiry（T83）：`days=12;level=warning;kind=subscription`（授權剩 30 天內、或永久授權已過維護期）⇒ 頂端橫幅，
  //    30／14／7 天各一個嚴重程度（notice／warning／critical）；值 `none` ⇒ 移除。規則同上（已登入的回應一定帶；沒有標頭 ⇒ 不動）。
  //    **只有最高管理者**收到標頭、看到橫幅（橫幅帶「前往授權頁」連結；頁面本身仍由伺服器驗權限）；其他角色不顯示剩餘天數。
  function _licenseExpiryBanner(value) {
    var el = document.getElementById('motrix-license-expiry-banner')
    var m = value ? /days=(-?[0-9]+);level=([a-z]+);kind=([a-z]+)/.exec(value) : null
    if (!m) { if (el) el.remove(); return }
    if (!document.body) return
    var days = parseInt(m[1], 10), level = m[2], perpetual = m[3] === 'perpetual'
    var what = perpetual ? '授權的維護期' : '系統授權'
    var text
    if (level === 'ended') text = what + '已結束 ' + (-days) + ' 天，系統仍可繼續使用，但不再提供更新。'
    else if (days === 0) text = what + '今天' + (perpetual ? '結束' : '到期') + '。'
    else text = what + '將在 ' + days + ' 天後' + (perpetual ? '結束' : '到期') + (perpetual ? '，之後仍可繼續使用但不再提供更新' : '，到期後系統會暫停使用') + '。'
    // 只有最高管理者看得到（伺服器只對最高管理者回這個標頭；這裡再擋一次，萬一標頭被別的角色收到也不顯示）
    var role = ''
    try { role = (JSON.parse(localStorage.getItem('motrix_session') || '{}') || {}).role || '' } catch (e) {}
    if (role !== 'superadmin') { if (el) el.remove(); return }
    text += ' 請向供應商取得新授權檔後匯入。'
    var critical = level === 'critical'
    if (!el) {
      el = document.createElement('div')
      el.id = 'motrix-license-expiry-banner'
      el.setAttribute('role', 'alert')
      document.body.insertBefore(el, document.body.firstChild)
    }
    el.style.cssText = 'position:sticky;top:0;z-index:9997;padding:8px 14px;font-size:13px;text-align:center;' +
      (critical ? 'background:var(--danger-light);color:var(--danger);border-bottom:1px solid var(--danger-border)'
                : 'background:var(--warning-light);color:var(--warning);border-bottom:1px solid var(--warning)')
    el.setAttribute('data-level', level)
    el.textContent = text
    var a = document.createElement('a')
    a.href = (window.location.pathname.includes('/pages/') ? '' : 'pages/') + 'license-settings.html'
    a.textContent = '前往授權頁'
    a.style.cssText = 'margin-left:8px;color:inherit;font-weight:600;text-decoration:underline'
    el.appendChild(a)
  }
  function _isApi(args) {
    var u = args && args[0]
    u = (u && u.url) || String(u || '')
    return u.indexOf('/api/') >= 0
  }
  window.fetch = async function () {
    var r = await _origFetch.apply(this, arguments)
    if (_isApi(arguments) && r.status < 500) {
      try { _setupBanner(r.headers.get('X-Motrix-Company-Setup')) } catch (e) {}
      try { var lh = r.headers.get('X-Motrix-License'); if (lh !== null) _licenseBanner(lh === 'none' ? '' : lh) } catch (e) {}
      try { var xh = r.headers.get('X-Motrix-License-Expiry'); if (xh !== null) _licenseExpiryBanner(xh === 'none' ? '' : xh) } catch (e) {}
    }
    if (r.status === 402 && !_redirecting && _isApi(arguments)) {
      try {
        var d402 = await r.clone().json()
        if (d402 && d402.code === 'license_required') {
          var here402 = window.location.pathname.split('/').pop()
          // 授權頁（license-settings.html）也不導：授權失效時它正是用來匯入新授權的頁面（它只呼叫授權豁免端點，不會走到這裡；保險用）
          if (['license-required.html', 'login.html'].indexOf(here402) < 0 && here402 !== 'license-settings.html') {
            _redirecting = true
            window.location.replace(window.location.pathname.includes('/pages/') ? 'license-required.html' : 'pages/license-required.html')
          }
        }
      } catch (e) {}
    }
    if (r.status === 428 && !_redirecting) {
      try {
        var d428 = await r.clone().json()
        if (d428 && d428.code === 'company_setup_required') {
          var here = window.location.pathname.split('/').pop()
          if (['company-profile-settings.html', 'company-setup-required.html', 'login.html'].indexOf(here) < 0) {
            _redirecting = true
            var inPages = window.location.pathname.includes('/pages/')
            var target = d428.canFix ? 'company-profile-settings.html?setup=1' : 'company-setup-required.html'
            window.location.replace(inPages ? target : 'pages/' + target)
          }
        }
      } catch (e) {}
    }
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
          if (currentFile !== 'my-account.html' && currentFile !== 'change-password.html') {
            _redirecting = true
            var isPages = window.location.pathname.includes('/pages/')
            window.location.replace(isPages ? 'my-account.html?forced=1' : 'pages/my-account.html?forced=1')
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
  // ── 伺服器還沒記下的已讀：查詢結果不可以把它蓋回未讀 ──────────────────────
  //   各頁只擋「點選前就送出的查詢」（t0 比較）。而點選**之後**才送出、卻比 POST /api/reads
  //   先被伺服器算完的查詢（兩條連線，先後不保證）一樣會回「未讀」⇒ 標記被蓋回來。
  //   ⇒ 在這裡記下：哪些已讀還在路上、什麼時候被伺服器確認；`unread()` 據此濾掉。
  //   伺服器拒絕（HTTP 錯誤）⇒ 不算確認，之後的查詢照伺服器的說法。
  var _pending = {}       // 'kind:key' -> 在途的 POST 數
  var _confirmedAt = {}   // 'kind:key' -> 伺服器確認的時間（ms）
  function _stillUnconfirmedAt(kind, key, t0) {
    var id = kind + ':' + key
    return !!_pending[id] || (_confirmedAt[id] || 0) >= t0
  }

  if (_ch) _ch.onmessage = function (e) { _emit(e.data) }
  window.addEventListener('storage', function (e) {
    if (e.key === OPT_KEY && e.newValue) { try { _emit(JSON.parse(e.newValue)) } catch (x) {} }
  })

  return {
    ready: _ready,
    /** 只廣播（不送請求）：給自己送請求的呼叫端（例如鈴鐺的 PATCH）。 */
    announce: function (kind, key) { _announce({ type: 'read', kind: kind, key: String(key) }) },
    /** 伺服器拒絕：廣播給其他分頁，本分頁也收到。 */
    announceFailed: function (kind, key) {
      var m = { type: 'failed', kind: kind, key: String(key) }
      _announce(m)
      _emit(m)
    },
    /** 標記一筆已讀：呼叫端要**先**清自己的 UI，這裡只負責送出與通知其他分頁。 */
    mark: function (kind, key) {
      key = String(key)
      var id = kind + ':' + key
      _pending[id] = (_pending[id] || 0) + 1
      _announce({ type: 'read', kind: kind, key: key })
      // ⚠️ 伺服器收到**之後**才發「整包重抓」的通知：先發的話，對方重抓時伺服器還沒記下。
      return _post('/api/reads', { kind: kind, key: key }).then(function (r) {
        if (--_pending[id] <= 0) delete _pending[id]
        if (r && r.ok) _confirmedAt[id] = Date.now()
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
      var t0 = Date.now()
      return _ready.then(function () {
        var t = _tok()
        if (!t || !keys || !keys.length) return new Set()
        return fetch('/api/reads/unread', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' },
          body: JSON.stringify({ kind: kind, keys: keys.map(String) }),
        }).then(function (r) { return r.ok ? r.json() : { unread: [] } })
          .then(function (d) {
            return new Set((d.unread || []).filter(function (k) { return !_stillUnconfirmedAt(kind, k, t0) }))
          })
          .catch(function () { return new Set() })
      })
    },
  }
})()

// 待簽數上次抓取的時間（回到前景的節流用）。放在模組層、不進元件狀態：元件狀態會被頁面狀態比對（case 切換＝重開同狀態）
// 與序列化看到，時間戳每次都不同，放進去就是無謂的差異。
var _approvalFetchedAt = 0

function notifStore() {
  const isPages = window.location.pathname.includes('/pages/')
  const auditHref = isPages ? 'audit-log.html' : 'pages/audit-log.html'
  const queueHref = isPages ? 'approval-queue.html' : 'pages/approval-queue.html'
  return {
    open:   false,
    items:  [],
    unread: 0,
    // 提醒（D1，2026-11-11）：待簽核、尚未啟用兩步驟驗證——原本是右下角浮動卡片（會蓋住內容、7～9 秒就消失），
    // 改成鈴鐺下拉最上方的「提醒」列＋鈴鐺上一顆小點：不浮在內容上、不會把頁面往下推、看漏了也還在。
    // 關閉（×）記在分頁的 sessionStorage（鍵沿用舊橫幅的：測試與登入注入用同一組旗標當『已處理』）。
    reminders: [],
    auditHref,
    _sess: null,

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
      // 簽核處理完（簽核佇列頁每次重載清單後發出）／分頁回到前景 ⇒ 重抓待簽數，紅點不會停在舊值；
      // 不另開輪詢：回到前景最多每 60 秒抓一次，與頁面載入時的那一次共用 _fetchApprovalCount。
      window.addEventListener('motrix:approval-changed', () => this._fetchApprovalCount())
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState !== 'visible') return
        const now = Date.now()
        if (now - _approvalFetchedAt < 60000) return
        this._fetchApprovalCount()
      })
      // 跨分頁即時（使用者：「選單紅點數字與鈴鐺也跨分頁即時更新」）：
      //   已讀 ⇒ 只改那一個模組／那一則通知；伺服器拒絕 ⇒ 重抓伺服器的數字。
      window.addEventListener('motrix:item-read', e => {
        const { kind, key } = e.detail
        if (kind === 'module') this._hideModBadge(key)
        if (kind === 'notification') this._markLocal(key)
      })
      window.addEventListener('motrix:item-read-failed', e => {
        if (e.detail.kind === 'module') this._fetchModuleCounts()
        if (e.detail.kind === 'notification') this._fetchNotifications()
      })
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
      // 且刻意不在 my-account.html 本身顯示（那裡就是設定入口，重複無意義）。
      try {
        const role = this._sess?.role || ''
        if (role !== 'superadmin' && role !== 'admin') return
        const currentFile = window.location.pathname.split('/').pop()
        if (currentFile === 'my-account.html' || currentFile === 'change-password.html') {
          // 狀態會在這一頁改變 ⇒ 離開後重新查一次（不沿用舊快取）
          try { sessionStorage.removeItem('motrix_totp_status') } catch (_e) { /* 無痕／禁用儲存：下次多查一次而已 */ }
          return
        }
        if (this._reminderDismissed('totp')) return
        // 提醒每頁都要重新出現（直到按 ×），但「有沒有啟用」每個分頁只查一次：之前是每分頁只彈一次所以只查一次，
        // 改成常駐後不能變成每換頁多打一支 API（e2e golden 的 API 請求清單釘住這一點）。
        // 快取值帶帳號（同一分頁登出再換人登入時不沿用上一位的狀態）
        const who = String(this._sess.username || this._sess.userId || '')
        let st = ''
        try { st = sessionStorage.getItem('motrix_totp_status') || '' } catch (_e) { st = '' }
        st = st.startsWith(who + ':') ? st.slice(who.length + 1) : ''
        if (st === 'on') return
        if (st !== 'off') {
          const r = await fetch('/api/auth/totp/status', {
            headers: { Authorization: 'Bearer ' + this._sess.token }
          })
          if (!r.ok) return
          const d = await r.json()
          try { sessionStorage.setItem('motrix_totp_status', who + ':' + (d.enabled ? 'on' : 'off')) } catch (_e) { /* 同上 */ }
          if (d.enabled) return
        }
        const isPages = window.location.pathname.includes('/pages/')
        this._setReminder({
          id: 'totp', tone: 'warning', title: '尚未啟用兩步驟驗證',
          msg: '密碼外洩時，兩步驟驗證能多一道防線擋下未授權登入，建議管理員帳號啟用。',
          href: isPages ? 'my-account.html?tab=security' : 'pages/my-account.html?tab=security', linkText: '前往設定 →'
        })
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
        // 「待簽核」橫幅不在這裡判斷：未讀通知列不代表「現在還輪到我簽」（簽過、被別人簽掉、退回後通知列仍未讀），
        // 用它數會讓已簽過的項目每次登入再跳一次（2026-10-01 使用者回報）⇒ 改由 _fetchApprovalCount 用真實待簽數決定。
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
        // 🔴 對照表只有一份：sidebar.js `_MOD_BADGES`（`window.MOTRIX_MOD_BADGES`）。
        var modBadge = window.MOTRIX_MOD_BADGES || {}
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
        _approvalFetchedAt = Date.now()
        this._updateApprovalBadge(d.count || 0)
        this._maybeShowApprovalBanner(d.count || 0)
      } catch(e) {}
    },

    /** 鈴鐺裡的「待簽核」提醒：數字＝/api/approval-queue/count（與角標、簽核佇列同一份）；0 件就收掉；關掉後同分頁不再出現。 */
    _maybeShowApprovalBanner(count) {
      if (!(count > 0)) { this._removeReminder('approval'); return }
      if (this._reminderDismissed('approval')) return
      const isPages = window.location.pathname.includes('/pages/')
      this._setReminder({
        id: 'approval', tone: 'info', title: '待簽核通知', msg: '您有 ' + Number(count) + ' 件待您簽核',
        href: isPages ? 'approval-queue.html' : 'pages/approval-queue.html', linkText: '前往簽核 →'
      })
    },

    // ── 提醒（鈴鐺下拉最上方）──
    _reminderKey(id) { return id === 'totp' ? 'motrix_totp_reminder_shown' : 'motrix_approval_banner_shown' },
    _reminderDismissed(id) { try { return !!sessionStorage.getItem(this._reminderKey(id)) } catch (e) { return false } },
    _setReminder(r) {
      const i = this.reminders.findIndex(x => x.id === r.id)
      if (i >= 0) this.reminders.splice(i, 1, r)
      else this.reminders.push(r)
    },
    _removeReminder(id) { this.reminders = this.reminders.filter(x => x.id !== id) },
    dismissReminder(id) {
      try { sessionStorage.setItem(this._reminderKey(id), '1') } catch (e) {}
      this._removeReminder(id)
    },

    _updateApprovalBadge(count) {
      const badge = document.getElementById('sb-approval-badge')
      if (!badge) return
      // 群組標題的紅點（sidebar.js 為每個有 key 的群組畫一顆）：跟面板內的數字徽章同一個 count、同一次更新
      const grp = badge.closest('.mnav__grp')
      const dot = grp && grp.querySelector('.mnav__dot')
      if (dot) dot.style.display = count > 0 ? 'inline-block' : 'none'
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
        const _d = new Date()                                   // 本地日期（notif.js 每頁都載，不靠 motrix-date.js 有沒有先載）
        const today = _d.getFullYear() + '-' + String(_d.getMonth() + 1).padStart(2, '0') + '-' + String(_d.getDate()).padStart(2, '0')
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

    _hideModBadge(mod) {
      const bids = (window.MOTRIX_MOD_BADGES || {})[mod] || []
      bids.forEach(id => { const el = document.getElementById(id); if (el) el.style.display = 'none' })
    },

    /** 其他分頁點了某一則（`*`＝全部）⇒ 本分頁只改那一則。 */
    _markLocal(key) {
      this.items.forEach(i => { if (key === '*' || String(i.id) === String(key)) i.is_read = 1 })
      this.unread = this.items.filter(i => !i.is_read).length
    },

    /** 通知指向的頁面；認不得的 ref_id ⇒ null（只標已讀、不換頁，跟原本一樣）。
     *  P8：自訂模組單據的 ref_id＝`custom:<模組 key>:<單號>`（helpers.custom_modules.notify_ref）
     *  ⇒ 開執行頁的那一張（單號可能含冒號：只切前兩段）。 */
    // 第44班：通知可帶 `link`（伺服器寫入時已驗過：只准「頁面檔名.html」加選填查詢字串）。這裡再驗一次（深度防禦）：不合格 ⇒ 當成沒有連結。
    _linkHref(link) {
      link = String(link || '')
      if (!/^[A-Za-z0-9_-]+\.html(\?[A-Za-z0-9_.=&%:+-]*)?$/.test(link)) return null
      return (window.location.pathname.includes('/pages/') ? '' : 'pages/') + link
    },

    refHref(item) {
      const lk = this._linkHref(item && item.link)
      if (lk) return lk
      const ref = String((item && item.ref_id) || '')
      // 模組定義送審：`customdef:<模組 key>:<版號>` ⇒ 審核頁（key 不含冒號）
      if (ref.indexOf('customdef:') === 0) {
        const parts = ref.slice(10).split(':')
        if (!parts[0]) return null
        const pg = window.location.pathname.includes('/pages/') ? 'custom-def-review.html' : 'pages/custom-def-review.html'
        return pg + '?key=' + encodeURIComponent(parts[0])
      }
      if (ref.indexOf('custom:') !== 0) return null
      const rest = ref.slice(7)
      const i = rest.indexOf(':')
      if (i <= 0 || i === rest.length - 1) return null
      const page = window.location.pathname.includes('/pages/') ? 'custom-records.html' : 'pages/custom-records.html'
      return page + '?key=' + encodeURIComponent(rest.slice(0, i)) + '&no=' + encodeURIComponent(rest.slice(i + 1))
    },

    /** 點一則：當下先改畫面，再送出（keepalive、不等回應）；有對應頁面就開過去。 */
    markOne(item) {
      if (!item || !this._sess?.token) return
      const href = this.refHref(item)
      this._markOneRead(item)
      if (href) { this.open = false; window.location.href = href }
    },

    _markOneRead(item) {
      if (!item.is_read) {
        item.is_read = 1
        this.unread = Math.max(0, this.unread - 1)
        if (window.MotrixReads) window.MotrixReads.announce('notification', item.id)
        fetch('/api/notifications/' + encodeURIComponent(item.id) + '/read', {
          method: 'PATCH', keepalive: true,
          headers: { Authorization: 'Bearer ' + this._sess.token }
        }).then(r => {
          if (!r.ok) { if (window.MotrixReads) window.MotrixReads.announceFailed('notification', item.id); return }
          try { localStorage.setItem('motrix_reads_bump', String(Date.now())) } catch (e) {}
        }).catch(() => {})
      }
    },

    markAllNotifications() {
      if (!this._sess?.token) return
      this.items.forEach(i => { i.is_read = 1 })
      this.unread = 0
      if (window.MotrixReads) window.MotrixReads.announce('notification', '*')
      fetch('/api/notifications/read-all', {
        method: 'PATCH', keepalive: true,
        headers: { Authorization: 'Bearer ' + this._sess.token }
      }).then(r => {
        if (!r.ok) { if (window.MotrixReads) window.MotrixReads.announceFailed('notification', '*'); return }
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
        'quotation.submit':        '送出簽核',
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
