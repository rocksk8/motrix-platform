  const API = '/api'

  function quotationList() {
    return {
      isMobileView: window.innerWidth <= 767,
      session: {},
      backendOnline: false,
      loading: true,
      retrying: false,
      loadErr: false,
      quotes: [],
      search: '',
      activeTab: 'all',
      filterSales: '',
      filterMonth: '',
      filterDealTag: '',
      view: 'list',           // 'list' | 'queue'
      queueItems: [],
      queueTotal: 0,
      queueLoading: false,
      selectedQueue: null,
      queueActing: false,
      queueRejectNote: '',

      tabs: [
        { key: 'all',    label: '全部'  },
        { key: '草稿',   label: '草稿'  },
        { key: '待審核', label: '待審核' },
        { key: '簽核中', label: '簽核中' },
        { key: '已核准', label: '已核准' },
        { key: '已送出', label: '已送出' },
        { key: '已確認', label: '已確認' },
        { key: '未成案', label: '未成案', isDealTag: true },
        { key: '已結案', label: '已結案', isDealTag: true },
        { key: '已取消', label: '已取消' },
      ],

      get canDelete() {
        return ['superadmin','admin'].includes(this.session.role)
      },

      tabCount(key) {
        if (key === 'all') return this.quotes.length
        const tab = this.tabs.find(t => t.key === key)
        if (tab && tab.isDealTag) return this.quotes.filter(q => q.deal_tag === key).length
        return this.quotes.filter(q => q.status === key).length
      },

      dealDisplayStatus(q) {
        const s   = q.status
        const tag = q.deal_tag || ''
        if (s === '已送出') {
          if (tag === '已成案') return '執行中'
          if (tag === '已結案') return '已結案'
          if (tag === '未成案') return '未成案'
        }
        return s
      },

      dealDisplayStatusClass(q) {
        const ds = this.dealDisplayStatus(q)
        const map = {
          '草稿':  'badge--draft',
          '待審核': 'badge--pending',
          '簽核中': 'badge--signing',
          '已核准': 'badge--approved',
          '已送出': 'badge--sent',
          '已確認': 'badge--done',
          '已取消': 'badge--danger',
          '已拒絕': 'badge--rejected',
          '執行中': 'badge--running',
          '已結案': 'badge--settled',
          '未成案': 'badge--lost',
        }
        return map[ds] || ''
      },

      editTypeLabel(type) {
        if (type === 'quote_edit')          return '報價單編輯'
        if (type === 'settlement_finalized') return '成本精算(完結)'
        if (type === 'settlement_draft')     return '成本精算'
        return '修改'
      },

      fmtEditAt(at) {
        if (!at) return ''
        const d = new Date(at)
        const mo = String(d.getMonth()+1).padStart(2,'0')
        const da = String(d.getDate()).padStart(2,'0')
        const hh = String(d.getHours()).padStart(2,'0')
        const mm = String(d.getMinutes()).padStart(2,'0')
        return mo + '/' + da + ' ' + hh + ':' + mm
      },

      get salesOptions() {
        return [...new Set(this.quotes.map(q => q.sales_person).filter(Boolean))].sort()
      },

      get monthOptions() {
        return [...new Set(this.quotes.map(q => (q.quote_date || q.created_at || '').slice(0,7)).filter(Boolean))].sort().reverse()
      },

      get filtered() {
        return this.quotes.filter(q => {
          let matchTab
          if (this.activeTab === 'all') {
            matchTab = true
          } else {
            const tab = this.tabs.find(t => t.key === this.activeTab)
            matchTab = tab && tab.isDealTag
              ? (q.deal_tag || '') === this.activeTab
              : q.status === this.activeTab
          }
          const s            = this.search.trim().toLowerCase()
          const matchSearch  = !s || (q.quote_no||'').includes(s) || (q.customer_name||'').toLowerCase().includes(s) || (q.project_name||'').toLowerCase().includes(s)
          const matchSales   = !this.filterSales || q.sales_person === this.filterSales
          const matchMonth   = !this.filterMonth || (q.quote_date || q.created_at || '').startsWith(this.filterMonth)
          const matchDealTag = !this.filterDealTag || (q.deal_tag || '') === this.filterDealTag
          return matchTab && matchSearch && matchSales && matchMonth && matchDealTag
        })
      },

      summaryData: { thisMonth: 0, thisMonthTotal: 0, pending: 0, signing: 0, confirmed: 0, avgMargin: '—' },

      _computeSummary() {
        const ym = new Date().toISOString().slice(0,7)
        const thisMonthQ         = this.quotes.filter(q => (q.quote_date || q.created_at || '').startsWith(ym))
        const thisMonthConfirmed = thisMonthQ.filter(q => q.deal_tag === '已成案' || q.deal_tag === '已結案')
        const margins            = this.quotes.filter(q => q.direct_margin_pct > 0).map(q => q.direct_margin_pct)
        this.summaryData = {
          thisMonth:      thisMonthQ.length,
          thisMonthTotal: thisMonthConfirmed.reduce((s, q) => s + (q.total || 0), 0),
          pending:        this.quotes.filter(q => q.status === '待審核').length,
          signing:        this.quotes.filter(q => q.status === '簽核中').length,
          confirmed:      this.quotes.filter(q => q.status === '已確認').length,
          avgMargin:      margins.length ? (margins.reduce((a,b)=>a+b,0)/margins.length).toFixed(1) : '—',
        }
      },

      async loadQuotes() {
        this.loading = true
        this.loadErr = false
        try {
          const r = await fetch(`${API}/quotations?limit=2000`, {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          this.backendOnline = true          // 有收到 HTTP 回應 = 後端在線
          if (r.status === 401) { this.logout(); return false }
          if (r.ok) {
            const d = await r.json()
            this.quotes = d.items || []
            this._computeSummary()
            this.loading = false
            return true
          }
          this.loadErr = true
        } catch {
          this.backendOnline = false         // 網路錯誤 = 後端真的離線
          this.loadErr = true
        }
        this.loading = false
        return false
      },

      async reload() {
        await this.loadQuotes()
      },

      async updateDealTag(quoteNo, tag, q) {
        const quote = q || this.quotes.find(q => q.quote_no === quoteNo)
        const oldTag = quote?.deal_tag || ''
        if (tag === '已成案') {
          if (!confirm(`確認將報價單 ${quoteNo} 標記為「已成案」？\n\n確認後案件進度將鎖定，僅能透過「案件管理」頁面完結案件。\n此操作將留下操作紀錄。`)) {
            if (quote) quote.deal_tag = oldTag
            return
          }
        }
        if (quote) quote.deal_tag = tag
        this._computeSummary()
        try {
          const entry = { at: new Date().toISOString(), user: this.session.displayName || '', from: oldTag, to: tag }
          await fetch(`${API}/quotations/${quoteNo}/deal-tag`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({ deal_tag: tag, log_entry: entry }),
          })
        } catch { this.toast('更新失敗，請重試') ; return }
        this.toast(tag ? `案件進度已更新：${tag}` : '案件進度已清除')
        await this.loadQuotes()
      },

      async deleteQuote(quoteNo) {
        if (!confirm(`確定刪除報價單 ${quoteNo}？此操作無法復原。`)) return
        try {
          const r = await fetch(`${API}/quotations/${quoteNo}`, {
            method: 'DELETE',
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (!r.ok) { alert('後端刪除失敗'); return }
        } catch { alert('網路錯誤，刪除失敗'); return }
        this.quotes = this.quotes.filter(q => q.quote_no !== quoteNo)
        this.toast('報價單已刪除')
      },

      toast(msg, bg = '#0A0A0A') {
        const el = document.createElement('div')
        el.textContent = msg
        el.style.cssText = `position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:${bg};color:#F5F4F0;padding:8px 18px;border-radius:6px;font-size:12px;z-index:9999;font-family:Inter,sans-serif`
        document.body.appendChild(el)
        setTimeout(() => el.remove(), 2500)
      },

      switchView(v) {
        this.view = v
        history.replaceState(null, '', v === 'queue' ? '?view=queue' : '?')
        if (v === 'queue') this.loadQueue()
      },

      async loadQueue() {
        this.queueLoading = true
        this.selectedQueue = null
        try {
          const r = await fetch(`${API}/approval-queue`, {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (!r.ok) return
          const d = await r.json()
          // Flatten: all individual items from all groups
          const all = []
          for (const g of (d.queue || [])) {
            for (const item of (g.items || [])) all.push(item)
          }
          // Sort: mine first, then by requestedAt
          all.sort((a, b) => {
            const aMine = this.canApproveQueue(a) ? 0 : 1
            const bMine = this.canApproveQueue(b) ? 0 : 1
            if (aMine !== bMine) return aMine - bMine
            return (a.requestedAt || '').localeCompare(b.requestedAt || '')
          })
          this.queueItems = all
          this.queueTotal = d.total || all.length
        } catch(e) {}
        this.queueLoading = false
      },

      canApproveQueue(item) {
        if (!item) return false
        const steps = item.steps || []
        if (steps.length > 0) {
          const cur = item.currentStep ?? 0
          if (cur >= steps.length) return false
          return steps[cur].username === this.session.username
        }
        return this.session.role === 'superadmin' && item.requestedBy !== this.session.username
      },

      canRejectQueue(item) {
        if (!item) return false
        const steps = item.steps || []
        if (steps.length > 0) {
          const cur = item.currentStep ?? 0
          if (cur < steps.length && steps[cur].username === this.session.username) return true
          return this.session.role === 'superadmin'
        }
        return this.session.role === 'superadmin'
      },

      async doQueueApprove() {
        if (!this.selectedQueue || this.queueActing) return
        this.queueActing = true
        try {
          const r = await fetch(`${API}/quotations/${this.selectedQueue.quoteNo}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({ approvedByDisplay: this.session.displayName })
          })
          if (!r.ok) {
            const e = await r.json().catch(() => ({}))
            this.toast('簽核失敗：' + (e.detail || r.status), '#DC2626')
            return
          }
          const d = await r.json()
          if (d.allDone) {
            this.toast('✓ 報價單已完成所有簽核，狀態更新為已送出', '#15803D')
          } else {
            this.toast('✓ 步驟已完成，轉交下一位簽核人', '#2563EB')
          }
          await this.loadQueue()
        } catch(e) {
          this.toast('網路錯誤：' + e.message, '#DC2626')
        }
        this.queueActing = false
      },

      async doQueueReject() {
        if (!this.selectedQueue || this.queueActing) return
        if (!confirm(`確定將報價單 ${this.selectedQueue.quoteNo} 退回草稿？`)) return
        this.queueActing = true
        try {
          const r = await fetch(`${API}/quotations/${this.selectedQueue.quoteNo}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({ note: this.queueRejectNote })
          })
          if (!r.ok) {
            const e = await r.json().catch(() => ({}))
            this.toast('退回失敗：' + (e.detail || r.status), '#DC2626')
            return
          }
          this.toast('報價單已退回草稿')
          this.queueRejectNote = ''
          await this.loadQueue()
        } catch(e) {
          this.toast('網路錯誤：' + e.message, '#DC2626')
        }
        this.queueActing = false
      },

      fmtDate(iso) {
        if (!iso) return ''
        const d = new Date(iso)
        const now = new Date()
        const diff = (now - d) / 1000
        if (diff < 3600)  return Math.floor(diff / 60) + ' 分鐘前'
        if (diff < 86400) return Math.floor(diff / 3600) + ' 小時前'
        return d.toLocaleDateString('zh-TW', { month: 'numeric', day: 'numeric' })
      },

      fmtDateFull(iso) {
        if (!iso) return ''
        const d = new Date(iso)
        return d.toLocaleDateString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit' }) + ' ' +
               d.toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })
      },

      logout() {
        fetch('/api/auth/logout', { method:'POST', headers:{ Authorization:'Bearer '+(this.session.token||'') } }).catch(()=>{})
        localStorage.removeItem('motrix_session'); window.location.href = 'login.html'
      },

      async init() {
      window.addEventListener('resize', () => { this.isMobileView = window.innerWidth <= 767 })
        const s = localStorage.getItem('motrix_session')
        if (!s) { window.location.href = 'login.html'; return }
        try { this.session = JSON.parse(s) } catch { window.location.href = 'login.html'; return }

        // Check ?view= param
        const param = new URLSearchParams(window.location.search).get('view')
        if (param === 'queue') this.view = 'queue'

        const ok = await this.loadQuotes()
        if (!ok || this.quotes.length === 0) {
          this.retrying = true
          await new Promise(r => setTimeout(r, 2000))
          this.retrying = false
          await this.loadQuotes()
        }
        if (this.view === 'queue') await this.loadQueue()
      }
    }
  }
