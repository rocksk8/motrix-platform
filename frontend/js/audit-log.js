function auditApp() {
  return {
    API: '',
    session: {},
    items:  [],
    total:  0,
    page:   1,
    perPage: 50,
    loading: false,
    q: '',
    filterAction: '',

    async init() {
      const s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      if (!s.token) { location.href = 'login.html'; return }
      this.session = s
      await this.load()
    },

    async load() {
      this.loading = true
      const params = new URLSearchParams({
        limit:  this.perPage,
        offset: (this.page - 1) * this.perPage,
      })
      if (this.filterAction) params.set('action', this.filterAction)
      if (this.q.trim())    params.set('q', this.q.trim())
      try {
        const r = await fetch(`/api/audit-log?${params}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.status === 401) { this.logout(); return }
        if (r.ok) {
          const d = await r.json()
          this.items = d.items || []
          this.total = d.total || 0
        }
      } catch(e) {}
      this.loading = false
    },

    prevPage() { if (this.page > 1) { this.page--; this.load() } },
    nextPage() { if (this.page * this.perPage < this.total) { this.page++; this.load() } },

    logout() {
      const s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      if (s.token) fetch('/api/auth/logout', { method:'POST', headers:{ Authorization:'Bearer '+s.token } }).catch(()=>{})
      localStorage.removeItem('motrix_session')
      location.href = 'login.html'
    },

    actionLabel(action) {
      const map = {
        'auth.login':            '登入',
        'auth.logout':           '登出',
        'auth.change_password':  '修改密碼',
        'quotation.create':      '新增報價單',
        'quotation.submit':      '送出審核',
        'quotation.approve':     '簽核通過',
        'quotation.update':      '更新報價單',
        'quotation.delete':      '刪除報價單',
        'quotation.status_change':'狀態變更',
        'quotation.export_pdf':  '匯出 PDF',
        'quotation.settlement':  '成本精算',
        'deal_tag.change':       '案件進度',
        'case.update':           '案件資料更新',
        'part.create':           '新增料號',
        'part.update':           '更新料號',
        'part.delete':           '刪除料號',
        'customer.create':       '新增客戶',
        'customer.update':       '更新客戶',
        'customer.delete':       '刪除客戶',
        'customer.visit.update': '拜訪紀錄',
        'payment.mark':          '收款標記',
        'user.create':           '新增使用者',
        'user.update':           '更新使用者',
        'user.delete':           '刪除使用者',
        'user.active':           '帳號啟停',
      }
      return map[action] || action
    },

    badgeBg(action) {
      if (action.includes('delete'))              return '#fee2e2'
      if (action === 'part.delete')               return '#fef3c7'
      if (action === 'user.active')               return '#fff7ed'
      if (action === 'auth.logout')               return '#f1f5f9'
      if (action === 'quotation.approve')         return '#dcfce7'
      if (action === 'quotation.submit' || action === 'quotation.create') return '#dbeafe'
      if (action === 'auth.login')                return '#f3f4f6'
      if (action === 'payment.mark')              return '#fef3c7'
      if (action === 'case.update')               return '#f0fdf4'
      if (action.startsWith('part.'))             return '#fefce8'
      if (action === 'customer.visit.update')     return '#fdf4ff'
      if (action.includes('customer'))            return '#f5f3ff'
      return '#eff6ff'
    },

    badgeFg(action) {
      if (action.includes('delete'))              return '#b91c1c'
      if (action === 'part.delete')               return '#92400e'
      if (action === 'user.active')               return '#c2410c'
      if (action === 'auth.logout')               return '#64748b'
      if (action === 'quotation.approve')         return '#15803d'
      if (action === 'quotation.submit' || action === 'quotation.create') return '#1d4ed8'
      if (action === 'auth.login')                return '#6b7280'
      if (action === 'payment.mark')              return '#92400e'
      if (action === 'case.update')               return '#166534'
      if (action.startsWith('part.'))             return '#854d0e'
      if (action === 'customer.visit.update')     return '#9333ea'
      if (action.includes('customer'))            return '#7c3aed'
      return '#1d4ed8'
    },

    dotBg(action) {
      if (action.includes('delete'))              return '#fee2e2'
      if (action === 'part.delete')               return '#fef3c7'
      if (action === 'user.active')               return '#fff7ed'
      if (action === 'auth.logout')               return '#f1f5f9'
      if (action === 'quotation.approve')         return '#dcfce7'
      if (action === 'payment.mark')              return '#fef3c7'
      if (action === 'case.update')               return '#f0fdf4'
      if (action.startsWith('part.'))             return '#fefce8'
      if (action === 'customer.visit.update')     return '#fdf4ff'
      if (action.includes('customer'))            return '#f5f3ff'
      if (action === 'auth.login')                return '#f3f4f6'
      return '#dbeafe'
    },

    dotIcon(action) {
      if (action === 'part.delete')               return '🗃'
      if (action.includes('delete'))              return '🗑'
      if (action === 'user.active')               return '🔓'
      if (action === 'auth.logout')               return '🚪'
      if (action === 'quotation.approve')         return '✅'
      if (action === 'quotation.submit')          return '📤'
      if (action === 'quotation.export_pdf')      return '📄'
      if (action === 'quotation.settlement')      return '🧮'
      if (action === 'payment.mark')              return '💰'
      if (action === 'case.update')               return '🗂'
      if (action.startsWith('part.'))             return '🔩'
      if (action === 'customer.visit.update')     return '📋'
      if (action.includes('customer'))            return '👤'
      if (action === 'auth.login')                return '🔑'
      if (action === 'auth.change_password')      return '🔐'
      if (action === 'deal_tag.change')           return '🏷'
      if (action.includes('user.'))               return '👥'
      return '📝'
    },

    formatAt(at) {
      if (!at) return ''
      const d = new Date(at)
      return d.toLocaleString('zh-TW', {
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      })
    },
  }
}
