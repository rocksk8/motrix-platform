const API = '/api'

function app() {
  return {
    session: {},
    loading: true,
    items: [],
    meta: { totalAmount: 0, receivedAmount: 0, unreceived: 0, uninvoicedCount: 0, feeTotal: 0, netReceived: 0 },
    tab: 'all',
    search: '',
    modal: { show: false, item: null, date: '', actualAmount: '', feeAmount: '', feeNote: '', note: '' },
    invoiceModal: { show: false, item: null, no: '' },

    get caseSet() {
      return new Set(this.items.map(i => i.quoteNo))
    },

    get filtered() {
      let list = this.items
      if (this.tab === 'unreceived')  list = list.filter(i => !i.received)
      if (this.tab === 'received')    list = list.filter(i =>  i.received)
      if (this.tab === 'uninvoiced')  list = list.filter(i => !i.invoiceNo)
      const q = this.search.trim().toLowerCase()
      if (q) list = list.filter(i =>
        (i.quoteNo||'').toLowerCase().includes(q) ||
        (i.customer||'').toLowerCase().includes(q) ||
        (i.label||'').toLowerCase().includes(q) ||
        (i.invoiceNo||'').toLowerCase().includes(q)
      )
      return list
    },

    fmtM(n) {
      if (!n) return '—'
      if (n >= 1000000) return 'NT$ ' + (n/1000000).toFixed(2) + 'M'
      if (n >= 1000)    return 'NT$ ' + Math.round(n/1000) + 'K'
      return 'NT$ ' + (n||0).toLocaleString()
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
        const r = await fetch(`${API}/receivables`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) {
          const d = await r.json()
          this.items = d.items || []
          this.meta = {
            totalAmount:     d.totalAmount     || 0,
            receivedAmount:  d.receivedAmount  || 0,
            unreceived:      d.unreceived      || 0,
            uninvoicedCount: d.uninvoicedCount || 0,
            feeTotal:        d.feeTotal        || 0,
            netReceived:     d.netReceived      || 0,
          }
        }
      } catch {}
      this.loading = false
    },

    openReceiveModal(item) {
      this.modal = {
        show: true,
        item,
        date:         new Date().toISOString().slice(0, 10),
        actualAmount: String(item.amount),
        feeAmount:    '',
        feeNote:      '',
        note:         '',
      }
    },

    get modalNetAmount() {
      const actual = parseFloat(this.modal.actualAmount) || 0
      const fee    = parseFloat(this.modal.feeAmount)    || 0
      return actual - fee
    },

    async confirmReceived() {
      const item = this.modal.item
      if (!item || !this.modal.date) return
      const by   = this.session.displayName || this.session.username || ''
      const body = {
        received:     true,
        receivedAt:   this.modal.date,
        receivedBy:   by,
        actualAmount: parseFloat(this.modal.actualAmount) || item.amount,
        feeAmount:    parseFloat(this.modal.feeAmount)    || 0,
        feeNote:      this.modal.feeNote.trim(),
        note:         this.modal.note.trim(),
      }
      const ok = await this.patchPayment(item, body)
      if (ok) {
        item.received     = true
        item.receivedAt   = this.modal.date
        item.receivedBy   = by
        item.actualAmount = body.actualAmount
        item.feeAmount    = body.feeAmount
        item.feeNote      = body.feeNote
        item.note         = body.note
        this.recalcMeta()
        this.modal.show = false
      }
    },

    async toggleReceived(item, received) {
      if (!confirm(received ? '標記此款項為已收？' : '取消此款項的收款紀錄？')) return
      const ok = await this.patchPayment(item, { received, receivedAt: '', receivedBy: '' })
      if (ok) {
        item.received     = received
        item.receivedAt   = ''
        item.receivedBy   = ''
        item.actualAmount = null
        item.feeAmount    = 0
        item.feeNote      = ''
        item.note         = ''
        this.recalcMeta()
      }
    },

    openInvoiceModal(item) {
      this.invoiceModal = { show: true, item, no: item.invoiceNo || '' }
    },

    async confirmInvoice() {
      const item = this.invoiceModal.item
      if (!item) return
      const ok = await this.patchPayment(item, { invoiceNo: this.invoiceModal.no.trim() })
      if (ok) {
        item.invoiceNo = this.invoiceModal.no.trim()
        this.recalcMeta()
        this.invoiceModal.show = false
      }
    },

    async patchPayment(item, body) {
      try {
        const r = await fetch(`${API}/quotations/${item.quoteNo}/payment/${item.idx}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(body)
        })
        return r.ok
      } catch { return false }
    },

    recalcMeta() {
      const total        = this.items.reduce((s, i) => s + i.amount, 0)
      const received     = this.items.filter(i => i.received).reduce((s, i) => s + i.amount, 0)
      const uninv        = this.items.filter(i => !i.invoiceNo).length
      const feeTotal     = this.items.filter(i => i.received).reduce((s, i) => s + (i.feeAmount || 0), 0)
      const netReceived  = this.items.filter(i => i.received).reduce((s, i) => s + ((i.actualAmount != null ? i.actualAmount : i.amount) - (i.feeAmount || 0)), 0)
      this.meta = { totalAmount: total, receivedAmount: received, unreceived: total - received, uninvoicedCount: uninv, feeTotal, netReceived }
    },

    logout() {
      fetch(`${API}/auth/logout`, { method:'POST', headers:{ Authorization:'Bearer '+(this.session.token||'') } }).catch(()=>{})
      localStorage.removeItem('motrix_session'); location.href = 'login.html'
    }
  }
}
