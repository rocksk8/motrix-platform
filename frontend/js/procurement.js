const API = '/api'
function app() {
  return {
    session: {},
    loading: true,
    items: [],
    search: '',
    tab: 'all',

    get filtered() {
      let list = this.items
      if (this.tab !== 'all') list = list.filter(m => m.status === this.tab)
      const q = this.search.trim().toLowerCase()
      if (q) list = list.filter(m =>
        (m.name||'').toLowerCase().includes(q) ||
        (m.model||'').toLowerCase().includes(q) ||
        (m.quoteNo||'').toLowerCase().includes(q) ||
        (m.customer||'').toLowerCase().includes(q)
      )
      return list
    },

    async init() {
      const s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      if (!s.token) { location.href = 'login.html'; return }
      this.session = s
      try {
        const r = await fetch(`${API}/auth/me`, { headers: { Authorization: 'Bearer ' + s.token } })
        if (!r.ok) { location.href = 'login.html'; return }
        const me = await r.json(); this.session.displayName = me.display_name
      } catch {}
      await this.load()
    },

    async load() {
      this.loading = true
      try {
        const r = await fetch(`${API}/materials-summary`, { headers: { Authorization: 'Bearer ' + this.session.token } })
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
