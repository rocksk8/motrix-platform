const API = '/api'
function app() {
  return {
    session: {},
    loading: true,
    items: [],
    search: '',
    filterTag: '',

    get filtered() {
      let list = this.items
      if (this.filterTag) list = list.filter(o => o.dealTag === this.filterTag)
      const q = this.search.trim().toLowerCase()
      if (q) list = list.filter(o =>
        (o.quoteNo||'').toLowerCase().includes(q) ||
        (o.customer||'').toLowerCase().includes(q) ||
        (o.projectName||'').toLowerCase().includes(q)
      )
      return list
    },
    get totalAmount()    { return this.items.reduce((s,o) => s + (o.total||0), 0) },
    get receivedAmount() { return this.items.reduce((s,o) => s + (o.receivedAmount||0), 0) },
    get closedCount()    { return this.items.filter(o => o.dealTag === '已結案').length },

    fmtM(n) {
      if (!n) return '—'
      if (n >= 1000000) return 'NT$ ' + (n/1000000).toFixed(2) + 'M'
      if (n >= 1000)    return 'NT$ ' + Math.round(n/1000) + 'K'
      return 'NT$ ' + Math.round(n).toLocaleString()
    },

    async init() {
      const s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      if (!s.token) { location.href = 'login.html'; return }
      this.session = s
      try {
        const r = await fetch(`${API}/auth/me`, { headers: { Authorization: 'Bearer ' + s.token } })
        if (!r.ok) { location.href = 'login.html'; return }
        const me = await r.json()
        this.session.displayName = me.display_name
      } catch {}
      await this.load()
    },

    async load() {
      this.loading = true
      try {
        const r = await fetch(`${API}/sales-orders`, { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) { const d = await r.json(); this.items = d.items || [] }
      } catch {}
      this.loading = false
    },

    logout() {
      fetch(`${API}/auth/logout`, { method:'POST', headers:{ Authorization:'Bearer '+(this.session.token||'') } }).catch(()=>{})
      localStorage.removeItem('motrix_session'); location.href = 'login.html'
    }
  }
}
