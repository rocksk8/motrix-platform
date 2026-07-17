const API = '/api'
function app() {
  return {
    session: {},
    loading: true,
    items: [],
    search: '',
    filterCat: '',
    modal: { show: false, id: null, partNo: '', name: '', brand: '', unit: '台', cost: 0, listPrice: 0, category: '', note: '', saving: false, error: '' },

    get categories() {
      return [...new Set(this.items.map(p => p.category).filter(Boolean))].sort()
    },
    get filtered() {
      let list = this.items
      if (this.filterCat) list = list.filter(p => p.category === this.filterCat)
      const q = this.search.trim().toLowerCase()
      if (q) list = list.filter(p =>
        (p.part_no||'').toLowerCase().includes(q) ||
        (p.name||'').toLowerCase().includes(q) ||
        (p.brand||'').toLowerCase().includes(q)
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
        const r = await fetch(`${API}/parts`, { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) { const d = await r.json(); this.items = d.items || [] }
      } catch {}
      this.loading = false
    },

    openModal(part) {
      if (part) {
        this.modal = { show: true, id: part.id, partNo: part.part_no, name: part.name, brand: part.brand || '', unit: part.unit || '台', cost: part.cost || 0, listPrice: part.list_price || 0, category: part.category || '', note: part.note || '', saving: false, error: '' }
      } else {
        this.modal = { show: true, id: null, partNo: '', name: '', brand: '', unit: '台', cost: 0, listPrice: 0, category: '', note: '', saving: false, error: '' }
      }
    },

    async savePart() {
      if (!this.modal.partNo.trim()) { this.modal.error = '料號不得為空'; return }
      if (!this.modal.name.trim())   { this.modal.error = '品名不得為空'; return }
      this.modal.saving = true; this.modal.error = ''
      const body = { partNo: this.modal.partNo, name: this.modal.name, brand: this.modal.brand, unit: this.modal.unit, cost: this.modal.cost, listPrice: this.modal.listPrice, category: this.modal.category, note: this.modal.note }
      const url  = this.modal.id ? `${API}/parts/${this.modal.id}` : `${API}/parts`
      const meth = this.modal.id ? 'PUT' : 'POST'
      try {
        const r = await fetch(url, { method: meth, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token }, body: JSON.stringify(body) })
        if (r.ok) { await this.load(); this.modal.show = false }
        else { const e = await r.json(); this.modal.error = e.detail || '儲存失敗' }
      } catch { this.modal.error = '網路錯誤' }
      this.modal.saving = false
    },

    async deletePart(part) {
      if (!confirm(`確認刪除料號「${part.part_no}」？`)) return
      try {
        const r = await fetch(`${API}/parts/${part.id}`, { method: 'DELETE', headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) await this.load()
      } catch {}
    },

    logout() {
      fetch(`${API}/auth/logout`, { method:'POST', headers:{ Authorization:'Bearer '+(this.session.token||'') } }).catch(()=>{})
      localStorage.removeItem('motrix_session'); location.href = 'login.html'
    }
  }
}
