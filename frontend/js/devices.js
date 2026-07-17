  const API = '/api'

  function devicesPage() {
    return {
      session: {},
      devices: [],
      loading: true,
      search: '',
      filterCustomer: '',
      filterWarranty: '',
      tabDeal: '',
      selectedId: null,

      async init() {
        const s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
        if (!s.token) { location.href = 'login.html'; return }
        this.session = s
        await this.load()
        this.loading = false
      },

      async load() {
        try {
          const r = await fetch(`${API}/devices`, {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (r.ok) {
            const data = await r.json()
            this.devices = data.items || []
          }
        } catch {}
      },

      get filtered() {
        let list = this.devices
        if (this.tabDeal) list = list.filter(d => d.dealTag === this.tabDeal)
        if (this.filterCustomer) list = list.filter(d => d.customer === this.filterCustomer)
        if (this.filterWarranty) {
          list = list.filter(d => {
            const dl = d.daysLeft
            if (this.filterWarranty === 'expired') return dl !== null && dl < 0
            if (this.filterWarranty === 'soon')    return dl !== null && dl >= 0 && dl <= 30
            if (this.filterWarranty === 'ok')      return dl !== null && dl > 30
            if (this.filterWarranty === 'none')    return dl === null
            return true
          })
        }
        const q = (this.search || '').trim().toLowerCase()
        if (q) list = list.filter(d =>
          [d.name, d.sn, d.mac, d.customer, d.location, d.quoteNo]
            .some(v => (v || '').toLowerCase().includes(q))
        )
        return list
      },

      get customerOptions() {
        return [...new Set(this.devices.map(d => d.customer).filter(Boolean))].sort()
      },
      get expiredCount() { return this.devices.filter(d => d.daysLeft !== null && d.daysLeft < 0).length },
      get soonCount()    { return this.devices.filter(d => d.daysLeft !== null && d.daysLeft >= 0 && d.daysLeft <= 30).length },
      get uniqueCustomers() { return new Set(this.devices.map(d => d.customer).filter(Boolean)).size },

      get selected() { return this.devices.find(d => d.id + '|' + d.quoteNo === this.selectedId) || null },
      select(d) { this.selectedId = d.id + '|' + d.quoteNo },

      wbCls(d) {
        const dl = d.daysLeft
        if (dl === null || dl === undefined) return 'wb-none'
        if (dl < 0)  return 'wb-expired'
        if (dl <= 30) return 'wb-soon'
        return 'wb-ok'
      },
      wbLabel(d) {
        const dl = d.daysLeft
        if (dl === null || dl === undefined) return '無紀錄'
        if (dl < 0)  return `已過期 ${Math.abs(dl)} 天`
        if (dl === 0) return '今日到期'
        if (dl <= 30) return `${dl} 天後到期`
        return '保固中'
      },

      logout() {
        fetch(`${API}/auth/logout`, { method:'POST', headers:{ Authorization:'Bearer '+(this.session.token||'') } }).catch(()=>{})
        localStorage.removeItem('motrix_session')
        location.href = 'login.html'
      },
    }
  }
