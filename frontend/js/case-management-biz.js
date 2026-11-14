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
      if (!filled.length) { MotrixUI.toast('報價單上尚無可帶入的欄位，或案件已全部有值。', {kind: 'info'}); return }
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
    // 業務負責（業績歸屬）＝caseRecord.roles.sales；沒填時退回報價單的報價人（quotations.sales_person）。
    // 2026-11-06 產品負責人裁示：清單卡片／詳情頭的「業務」改讀這個口徑（比照營運報表 reports.py::_case_sales_owner）。
    // 兩個欄位仍各自存、互不寫入；這裡只決定「顯示哪一個」。docs/platform/plans/SALES-PERSON-VS-ROLES-SALES-ANALYSIS.md
    _roleSalesDisplay() {
      const v = this.cr && this.cr.caseRecord && this.cr.caseRecord.roles && this.cr.caseRecord.roles.sales
      if (v && typeof v === 'object') {
        // 帳號形狀：顯示「現在的」名稱（與下拉、清單卡片同一個來源）；查不到才用存檔當下的 display
        const u = (this.selectableUsers || []).find(x => x.username === v.username)
        return String((u && (u.display_name || u.username)) || v.display || v.username || '').trim()
      }
      return String(typeof v === 'string' ? v : '').trim()
    },
    // 清單卡片：列表端點回 sales_owner（伺服器端解析 roles.sales，見 list_cases）；沒有 ⇒ 報價人
    salesOwnerName(c) {
      return String((c && (c.sales_owner || c.sales_person)) || '').trim()
    },
    // 詳情頭：用頁面上現在的 roles.sales（改了下拉立刻跟著變），沒填 ⇒ 報價人
    get selectedSalesOwner() {
      return this._roleSalesDisplay() || String((this.selected && this.selected.sales_person) || '').trim()
    },
    // 報價人與業務負責兩邊都有值且顯示名不同 ⇒ 一句中性提示（不是錯誤：本來就是兩個欄位）；只讀顯示，不改任何欄位。
    get salesRoleDiffNote() {
      const quoter = String((this.selected && this.selected.sales_person) || '').trim()
      const owner = this._roleSalesDisplay()
      if (!quoter || !owner || quoter === owner) return ''
      return '報價人（' + quoter + '）與業務負責（' + owner + '）不是同一人：清單、營運報表的業績與部門依業務負責；業務獎金（尚未建立分潤單者）依業務負責，已建立的分潤單不回頭更動。'
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
