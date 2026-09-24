// case-management-biz.js — 案件管理頁：案件資訊分頁：合約、案件角色
// CM12 P1（2026-09-24）：由 case-management.js 原樣搬出，成員文字未改；組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({

    // 報價單 → 案件合約資訊的欄位對照。contactPerson/contactPhone 在報價單
    // 是 contactName/contactPhone；contractNote 報價單沒有對應欄位，維持案件自填。
    _quoteContractFields() {
      const q = (this.selected && this.selected.data) || {}
      return {
        deliveryAddress: q.deliveryAddress || '',
        deliveryTerms:   q.deliveryTerms   || '',
        contactPerson:   q.contactName     || '',
        contactPhone:    q.contactPhone    || '',
      }
    },
    _fillContractFromQuote(target) {
      const src = this._quoteContractFields()
      // 只填空的欄位——不覆蓋案件上已經有的值
      Object.keys(src).forEach(k => { if (src[k] && !target[k]) target[k] = src[k] })
    },
    get quoteContractAvailable() {
      return Object.values(this._quoteContractFields()).some(v => !!v)
    },
    pullContractFromQuote() {
      const c = this.cr.caseRecord && this.cr.caseRecord.contract
      if (!c) return
      const src = this._quoteContractFields()
      const filled = Object.keys(src).filter(k => src[k] && !c[k])
      if (!filled.length) { MotrixUI.toast('報價單上沒有可帶入的欄位，或案件這邊都已經有值了。', {kind: 'info'}); return }
      this._fillContractFromQuote(c)
      this.setDirty && this.setDirty()
      this.dirty = true
    },

    // CM3（2026-09-24）：案件角色存 {username, display}；未轉換的舊資料是顯示名稱字串（升級時查不到或
    // 同名的不猜，見 db.py::_m116_case_roles_username）。選單的 value 一律是帳號。
    roleUser(k) {
      const v = this.cr.caseRecord?.roles?.[k]
      if (v && typeof v === 'object') return v.username || ''
      return (typeof v === 'string' && v.trim()) ? '__legacy__' : ''
    },
    setRole(k, val) {
      if (!this.cr.caseRecord || val === '__legacy__' || val === this.roleUser(k)) return
      if (!this.cr.caseRecord.roles) this.cr.caseRecord.roles = { filler: '', sales: '', executor: '' }
      if (!val) { this.cr.caseRecord.roles[k] = '' } else {
        const u = (this.selectableUsers || []).find(x => x.username === val)
        const cur = this.cr.caseRecord.roles[k]
        this.cr.caseRecord.roles[k] = { username: val, display: (u && (u.display_name || u.username)) || cur?.display || val }
      }
      this.setDirty()
    },
    // 選單裡沒有對應選項的現值：未對應帳號的舊字串、或已不在可選名單的帳號（例如停用）
    roleExtra(k) {
      const v = this.cr.caseRecord?.roles?.[k]
      if (typeof v === 'string' && v.trim()) return { value: '__legacy__', label: v + '（未對應帳號）' }
      if (v && typeof v === 'object' && v.username && !(this.selectableUsers || []).some(u => u.username === v.username)) {
        return { value: v.username, label: (v.display || v.username) + '（不在可選名單）' }
      }
      return null
    },
    get roleSel() {
      const self = this
      const o = {}
      for (const k of ['filler', 'sales', 'executor']) {
        Object.defineProperty(o, k, { enumerable: true, get: () => self.roleUser(k), set: v => self.setRole(k, v) })
      }
      return o
    },
}))
