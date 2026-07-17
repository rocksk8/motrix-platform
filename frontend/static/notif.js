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

function notifStore() {
  const isPages = window.location.pathname.includes('/pages/')
  const auditHref = isPages ? 'audit-log.html' : 'pages/audit-log.html'
  const queueHref = isPages ? 'quotations.html?view=queue' : 'pages/quotations.html?view=queue'
  return {
    open:   false,
    items:  [],
    unread: 0,
    auditHref,
    _sess: null,
    _popupShown: false,

    async init() {
      this._sess = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      if (!this._sess.token) return
      if (this._sess.mustChangePassword) return
      await Promise.all([this._fetchAuditLog(), this._fetchNotifications()])
    },

    async _fetchAuditLog() {
      try {
        const r = await fetch('/api/audit-log?limit=30', {
          headers: { Authorization: 'Bearer ' + this._sess.token }
        })
        if (!r.ok) return
        const d = await r.json()
        this.items = d.items || []
      } catch(e) {}
    },

    async _fetchNotifications() {
      try {
        const r = await fetch('/api/notifications/mine', {
          headers: { Authorization: 'Bearer ' + this._sess.token }
        })
        if (!r.ok) return
        const d = await r.json()
        this.unread = d.unread || 0
        const pending = (d.items || []).filter(i => !i.is_read && i.type === 'approval_request')
        if (pending.length > 0 && !this._popupShown) {
          this._popupShown = true
          setTimeout(() => this._showApprovalBanner(pending.length, queueHref), 900)
        }
      } catch(e) {}
    },

    toggle() {
      this.open = !this.open
      if (this.open) this._markAllRead()
    },

    async _markAllRead() {
      if (!this._sess?.token) return
      const latest = this.items.length ? this.items[0].at : ''
      if (latest) localStorage.setItem('motrix_notif_seen_at', latest)
      await fetch('/api/notifications/read-all', {
        method: 'PATCH',
        headers: { Authorization: 'Bearer ' + this._sess.token }
      }).catch(() => {})
      this.unread = 0
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
        'z-index:99999;font-family:Inter,sans-serif;max-width:300px',
        'animation:notif-slide-in .25s ease',
      ].join(';')
      el.innerHTML = `
        <div style="display:flex;align-items:flex-start;gap:10px">
          <div style="color:#4F46E5;flex-shrink:0;margin-top:1px">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6 6 0 10-12 0v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>
            </svg>
          </div>
          <div style="flex:1">
            <div style="font-size:13px;font-weight:600;color:#3730A3;margin-bottom:4px">待簽核通知</div>
            <div style="font-size:12px;color:#4338CA;line-height:1.5">您有 <b>${count}</b> 份報價單等待您簽核</div>
            <a href="${href}" style="display:inline-block;margin-top:8px;font-size:11px;color:#fff;background:#6366F1;padding:4px 12px;border-radius:5px;text-decoration:none;font-weight:600">前往簽核 →</a>
          </div>
          <button onclick="document.getElementById('approval-notif-banner').remove()"
                  style="border:none;background:none;cursor:pointer;color:#9CA3AF;font-size:20px;line-height:1;padding:0;flex-shrink:0;margin-top:-2px">×</button>
        </div>
      `
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
    }
  }
}
