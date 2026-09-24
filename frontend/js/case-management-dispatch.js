// case-management-dispatch.js — 案件管理頁：承攬商分頁：派工、承攬商匯款申請
// CM12 P1（2026-09-24）：由 case-management.js 原樣搬出，成員文字未改；組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({

    // ── 承攬商派發 ──
    vendors: [],
    contractorRoster: [],
    dispatches: [],
    dispatchesLoading: false,
    showDispatchModal: false,
    editDispatchId: null,
    dispatchSaving: false,
    dispatchForm: {},
    dispatchMsg: '',
    _newDispatchPersonnelId: '',


    // ── 承攬商匯款申請 ──
    contractorVouchers: [],
    contractorVouchersLoading: false,
    cvPreviewModal: false,
    cvPreviewBlobUrl: '',
    cvPreviewVoucher: null,
    cvPreviewFetching: false,
    // ── 標記已匯款 Modal（2026-08-31 新增，原本用 prompt() 只能填備註，
    // 沒有地方填實際匯款日期，一律誤記成操作當下的系統時間）
    payVoucherModal: false,
    payVoucherTarget: null,
    payVoucherDate: '',
    payVoucherNote: '',
    payVoucherBankAcctCode: '',
    payVoucherSaving: false,
    // T100 傳票匯出設定裡的銀行帳戶清單（2026-09-01 新增），標記已匯款/已收款
    // 時挑選要用哪個帳戶；每次開啟標記 Modal 都重抓最新清單，見
    // loadT100BankAccounts()
    t100BankAccounts: [],
    t100DefaultBankAcctCode: '',   // 2026-09-02 新增：系統預設銀行帳戶，見 _resolveDefaultBankAccount()
    // ── 產生匯款申請 Modal（2026-08-31 新增，讓應付款日期在產生申請當下就能
    // 直接填/改，不用先跳去編輯派發紀錄）
    createVoucherModal: false,
    createVoucherDispatch: null,
    createVoucherPayableDate: '',
    createVoucherSaving: false,

    // ── 承攬商 ──────────────────────────────────────────────────────────────

    async loadVendors() {
      try {
        const r = await fetch('/api/vendor-contractors/selectable', {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.vendors = await r.json()
      } catch {}
      try {
        const r2 = await fetch('/api/contractors/selectable', {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r2.ok) this.contractorRoster = await r2.json()
      } catch {}
    },

    async loadDispatches(quoteNo, pre) {
      if (!quoteNo) return
      const live = this._selectLive()
      this.dispatchesLoading = true
      this.dispatches = []
      try {
        const r = pre ? this._preResp(pre) : await fetch(`/api/contractor-dispatches?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? await r.json() : null
        if (!live()) return
        if (r.ok) this.dispatches = body
      } catch {}
      this.dispatchesLoading = false
    },

    dispatchTotalCost() {
      // 承攬商含稅合計 + 外包人員金額（不計稅），與精算頁面「承攬商派發成本」算法一致
      return this.dispatches
        .filter(d => d.status !== 'cancelled')
        .reduce((s, d) => s + (d.grandTotal || 0), 0)
    },

    // 財務 Tab 顯示的精算結果是完結當下凍結的 caseSettleSummary().dispatchTotal 快照，
    // 跟 dispatchTotalCost() 目前即時計算值比對——不一致代表承攬商派發在精算完結後
    // 又被異動過，此頁數字尚未反映最新狀況（見 settlement.html dispatchStale() 同一邏輯）
    financeDispatchStale() {
      if (this.caseSettleStatus() !== 'finalized') return null
      const frozen = Math.round(this.caseSettleSummary().dispatchTotal || 0)
      const live   = Math.round(this.dispatchTotalCost() || 0)
      if (frozen === live) return null
      return { frozen, live, diff: live - frozen }
    },

    _blankDispatchForm() {
      const today = new Date().toISOString().slice(0, 10)
      return {
        quote_no: this.selected?.quote_no || '',
        vendor_id: '',
        dispatch_date: today,
        scope: '',
        notes: '',
        invoice_no: '',
        invoice_date: '',
        payable_date: '',
        status: this._quoteStatusToDispatch(this.selected?.status || ''),
        tax_rate: 0.05,
        items: [],
        personnel: []
      }
    },

    openNewDispatch() {
      this.editDispatchId = null
      this.dispatchForm = this._blankDispatchForm()
      this.dispatchMsg = ''
      this._newDispatchPersonnelId = ''
      this.showDispatchModal = true
    },

    openEditDispatch(d) {
      this.editDispatchId = d.id
      this.dispatchForm = {
        quote_no: d.quoteNo,
        vendor_id: d.vendorId,
        dispatch_date: d.dispatchDate || '',
        scope: d.scope || '',
        notes: d.notes || '',
        invoice_no: d.invoiceNo || '',
        invoice_date: d.invoiceDate || '',
        payable_date: d.payableDate || '',
        status: d.status || 'draft',
        tax_rate: d.taxRate !== undefined ? d.taxRate : 0.05,
        items: JSON.parse(JSON.stringify(d.items || [])),
        personnel: JSON.parse(JSON.stringify(d.personnel || [])),
        _expectedUpdatedAt: d.updatedAt || ''
      }
      this.dispatchMsg = ''
      this._newDispatchPersonnelId = ''
      this.showDispatchModal = true
    },

    addDispatchPersonnel() {
      const cid = Number(this._newDispatchPersonnelId)
      if (!cid) return
      if ((this.dispatchForm.personnel || []).some(p => p.id === cid)) { this._newDispatchPersonnelId = ''; return }
      const c = this.contractorRoster.find(x => x.id === cid)
      if (!c) return
      this.dispatchForm.personnel.push({ id: c.id, name: c.name, amount: 0, note: '' })
      this._newDispatchPersonnelId = ''
    },

    async removeDispatchPersonnel(idx) {
      const p = this.dispatchForm.personnel[idx]
      if (!(await MotrixUI.confirm(`確定要刪除派工人員「${(p && p.name) || '未命名'}」這一列？`, {danger: true}))) return
      this.dispatchForm.personnel.splice(idx, 1)
    },

    _dispatchPersonnelTotal() {
      return (this.dispatchForm.personnel || []).reduce((s, p) => s + (+p.amount || 0), 0)
    },

    addDispatchItem() {
      this.dispatchForm.items.push({
        id: Date.now() + Math.random(),
        description: '', qty: 1, unit: '式', unitPrice: '', amount: 0, note: ''
      })
    },

    async removeDispatchItem(idx) {
      const it = this.dispatchForm.items[idx]
      if (!(await MotrixUI.confirm(`確定要刪除派工品項「${(it && it.description) || '未命名'}」這一列？`, {danger: true}))) return
      this.dispatchForm.items.splice(idx, 1)
      this._recalcDispatchTotal()
    },

    onDispatchItemPrice(idx) {
      const it = this.dispatchForm.items[idx]
      if (!it) return
      it.amount = Math.round((+it.qty || 0) * (+it.unitPrice || 0))
      this._recalcDispatchTotal()
    },

    _recalcDispatchTotal() {
      this.dispatchForm._total = this.dispatchForm.items.reduce((s, it) => s + (+it.amount || 0), 0)
    },

    async saveDispatch() {
      if (!this.dispatchForm.vendor_id && !(this.dispatchForm.personnel || []).length) {
        this.dispatchMsg = '請至少選擇承攬商或外包人員其中一項'; return
      }
      this.dispatchSaving = true; this.dispatchMsg = ''
      const body = {
        quote_no: this.dispatchForm.quote_no,
        vendor_id: this.dispatchForm.vendor_id ? Number(this.dispatchForm.vendor_id) : null,
        dispatch_date: this.dispatchForm.dispatch_date || '',
        scope: this.dispatchForm.scope || '',
        notes: this.dispatchForm.notes || '',
        invoice_no: this.dispatchForm.invoice_no || '',
        invoice_date: this.dispatchForm.invoice_date || '',
        payable_date: this.dispatchForm.payable_date || '',
        status: this.dispatchForm.status || 'draft',
        tax_rate: parseFloat(this.dispatchForm.tax_rate) || 0,
        items_json: this.dispatchForm.items || [],
        personnel_json: (this.dispatchForm.personnel || []).map(p => ({
          id: p.id, name: p.name, amount: +p.amount || 0, note: p.note || ''
        }))
      }
      if (this.editDispatchId) body.expectedUpdatedAt = this.dispatchForm._expectedUpdatedAt || ''
      const method = this.editDispatchId ? 'PUT' : 'POST'
      const url    = this.editDispatchId
        ? `/api/contractor-dispatches/${this.editDispatchId}`
        : '/api/contractor-dispatches'
      try {
        const r = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(body)
        })
        if (!r.ok) { this.dispatchMsg = (await r.json()).detail || '儲存失敗'; this.dispatchSaving = false; return }
        this.showDispatchModal = false
        await this.loadDispatches(this.selected?.quote_no)
      } catch(e) { this.dispatchMsg = '網路錯誤：' + e.message }
      this.dispatchSaving = false
    },

    // `AC2`：派工的廠商發票日期（'' ＝清除）。專用端點：已有匯款申請（PUT 會 409）也登得進去
    async setDispatchInvoiceDate(d, value) {
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/invoice-date`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ invoiceDate: value || '' })
        })
        const j = await r.json().catch(() => ({}))
        if (!r.ok) { MotrixUI.toast(j.detail || '發票日期儲存失敗', {kind: 'error'}); return }
        d.invoiceDate = j.invoiceDate
        this.flashSaved('dispatch-' + d.id)
        if (j.updated_at) d.updatedAt = j.updated_at
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async deleteDispatch(d) {
      if (!(await MotrixUI.confirm(`確定刪除派發給「${this._dispatchLabel(d)}」的紀錄？`, {danger: true}))) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) await this.loadDispatches(this.selected?.quote_no)
        else MotrixUI.toast((await r.json()).detail || '刪除失敗', {kind: 'error'})
      } catch {}
    },

    async importDispatchToQuote(d) {
      if (!d.items || d.items.length === 0) { MotrixUI.toast('此派發紀錄沒有報價品項', {kind: 'info'}); return }
      if (!(await MotrixUI.confirm(`確定將「${this._dispatchLabel(d)}」共 ${d.items.length} 筆品項匯入至報價單？\n（報價單必須處於草稿狀態）`))) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/import-to-quote`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        const data = await r.json()
        if (r.ok) MotrixUI.toast(`✓ 已成功匯入 ${data.imported} 筆品項至報價單`, {kind: 'ok'})
        else MotrixUI.toast(data.detail || '匯入失敗', {kind: 'error'})
      } catch(e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    // ── 承攬商匯款申請 ──────────────────────────────────────────────────────────

    async loadContractorVouchers(quoteNo) {
      if (!quoteNo) return
      const live = this._selectLive()
      this.contractorVouchersLoading = true
      this.contractorVouchers = []
      try {
        const r = await fetch(`/api/contractor-vouchers?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? await r.json() : null
        if (!live()) return
        if (r.ok) this.contractorVouchers = body
      } catch {}
      this.contractorVouchersLoading = false
    },

    _dispatchVoucher(d) {
      return this.contractorVouchers.find(v => v.dispatchId === d.id) || null
    },

    createContractorVoucher(d) {
      this.createVoucherDispatch = d
      this.createVoucherPayableDate = d.payableDate || ''
      this.createVoucherModal = true
    },

    async confirmCreateContractorVoucher() {
      const d = this.createVoucherDispatch
      if (!d) return
      this.createVoucherSaving = true
      try {
        const r = await fetch('/api/contractor-vouchers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ dispatch_id: d.id, payable_date: this.createVoucherPayableDate || null })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '建立失敗', {kind: 'error'}); this.createVoucherSaving = false; return }
        this.createVoucherModal = false
        this.createVoucherDispatch = null
        await this.loadDispatches(this.selected?.quote_no)
        await this.loadContractorVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
      this.createVoucherSaving = false
    },

    async deleteContractorVoucher(v) {
      if (!(await MotrixUI.confirm(`確定刪除匯款申請「${v.voucherNo}」？`, {danger: true}))) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) await this.loadContractorVouchers(this.selected?.quote_no)
        else MotrixUI.toast((await r.json()).detail || '刪除失敗', {kind: 'error'})
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async submitContractorVoucher(v) {
      if (!(await MotrixUI.confirm(`確定送出匯款申請「${v.voucherNo}」進行簽核？`))) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/submit`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '送出失敗', {kind: 'error'}); return }
        await this.loadContractorVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async approveContractorVoucher(v) {
      // 同一人連任多層時一次簽完（2026-09-15，見 static/approval-cascade.js）。
      // 清單資料沒帶 approval.tiers 時算出來是空陣列，行為跟以前一樣。
      const _appr = v.approval || {}
      const _casc = window.MotrixApproval.selfCascadeTiers(
        _appr.tiers || [], _appr.currentTier ?? 0, this.session.username, [])
      if (!(await MotrixUI.confirm(`確定簽核匯款申請「${v.voucherNo}」？` + window.MotrixApproval.cascadeNote(_casc)))) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ cascade: _casc.length > 0 })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '簽核失敗', {kind: 'error'}); return }
        await this.loadContractorVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async rejectContractorVoucher(v) {
      const note = (await MotrixUI.prompt(`退回匯款申請「${v.voucherNo}」，可填寫退回原因（選填）：`))
      if (note === null) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/reject`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '退回失敗', {kind: 'error'}); return }
        await this.loadContractorVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async revokeContractorVoucherApproval(v) {
      const note = (await MotrixUI.prompt(`撤銷匯款申請「${v.voucherNo}」的核准？將退回草稿。\n\n可填寫撤銷原因（選填）：`))
      if (note === null) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/revoke-approval`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '撤銷失敗', {kind: 'error'}); return }
        await this.loadContractorVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async loadT100BankAccounts() {
      // 2026-09-02：改成每次開啟標記 Modal 都重抓（不再 cache-once），確保跟
      // 案件管理／出納／庫存管理三處標記畫面共用同一份最新清單——superadmin
      // 在 T100 設定頁新增/修改銀行帳戶後，其他人下一次開啟標記視窗立刻看得到，
      // 不用重新整理整頁（使用者要求「要能互相連動」）。GET 這支很輕量，
      // 每次重抓成本可忽略。
      try {
        const r = await fetch('/api/settings/t100-export-config', { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) {
          const d = await r.json()
          this.t100BankAccounts = d.bankAccounts || []
          this.t100DefaultBankAcctCode = d.defaultBankAccountCode || ''
        }
      } catch {}
    },

    // 銀行帳戶預設值（2026-09-02 新增，比照 reports.js 同款 helper）：①這個
    // 對象上次標記用的帳戶 ②系統預設帳戶 ③兩者都沒有就空白。
    async _resolveDefaultBankAccount(lastUsedUrl) {
      if (lastUsedUrl) {
        try {
          const r = await fetch(lastUsedUrl, { headers: { Authorization: 'Bearer ' + this.session.token } })
          if (r.ok) {
            const d = await r.json()
            if (d.acctCode) return d.acctCode
          }
        } catch {}
      }
      return this.t100DefaultBankAcctCode || ''
    },

    onPayVoucherBankChange() {
      this._payVoucherBankName = (this.t100BankAccounts.find(b => b.acctCode === this.payVoucherBankAcctCode) || {}).name || ''
    },

    async toggleContractorVoucherPaid(v, action) {
      // 標記已匯款需要填實際匯款日期（不一定等於操作當下），改走 Modal；
      // 取消已匯款不涉及日期，維持原本 confirm() 快速操作。
      if (action === 'pay') {
        this.payVoucherTarget = v
        this.payVoucherDate = this._localDateStr()
        this.payVoucherNote = ''
        this.payVoucherBankAcctCode = ''
        this._payVoucherBankName = ''
        this.payVoucherModal = true
        await this.loadT100BankAccounts()
        const url = v.vendorId ? `/api/contractor-vouchers/last-paid-bank-account?vendor_id=${v.vendorId}` : ''
        this.payVoucherBankAcctCode = await this._resolveDefaultBankAccount(url)
        this.onPayVoucherBankChange()
        return
      }
      if (!(await MotrixUI.confirm(`確定取消匯款申請「${v.voucherNo}」的已匯款標記？`, {danger: true}))) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/paid-toggle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ action: 'unpay', note: '' })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '操作失敗', {kind: 'error'}); return }
        await this.loadContractorVouchers(this.selected?.quote_no)
        this.loadFinanceSummary(this.selected?.quote_no)   // 已付/未付數字會變
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async confirmPayVoucher() {
      const v = this.payVoucherTarget
      if (!v || !this.payVoucherDate) return
      this.payVoucherSaving = true
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/paid-toggle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({
            action: 'pay', paid_at: this.payVoucherDate, note: this.payVoucherNote,
            bankAccountCode: this.payVoucherBankAcctCode, bankAccountName: this._payVoucherBankName || '',
          })
        })
        if (!r.ok) { alert((await r.json()).detail || '操作失敗'); this.payVoucherSaving = false; return }
        this.payVoucherModal = false
        this.payVoucherTarget = null
        await this.loadContractorVouchers(this.selected?.quote_no)
        this.loadFinanceSummary(this.selected?.quote_no)   // 已付/未付數字會變
      } catch (e) { alert('網路錯誤：' + e.message) }
      this.payVoucherSaving = false
    },

    async downloadContractorVoucherPdf(v) {
      try {
        fetch(`/api/contractor-vouchers/${v.voucherNo}/export?mode=external`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        }).catch(() => {})
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗', {kind: 'error'}); return }
        const blob = await r.blob()
        const url  = URL.createObjectURL(blob)
        const a    = document.createElement('a')
        a.href     = url
        a.download = `${v.voucherNo}.pdf`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      } catch (e) { MotrixUI.toast('下載失敗：' + e.message, {kind: 'error'}) }
    },

    async previewContractorVoucherPdf(v) {
      this.cvPreviewFetching = true
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗', {kind: 'error'}); this.cvPreviewFetching = false; return }
        const blob = await r.blob()
        this.cvPreviewBlobUrl = URL.createObjectURL(blob)
        this.cvPreviewVoucher = v
        this.cvPreviewModal = true
      } catch (e) { MotrixUI.toast('預覽失敗：' + e.message, {kind: 'error'}) }
      this.cvPreviewFetching = false
    },

    closeContractorVoucherPreview() {
      if (this.cvPreviewBlobUrl) URL.revokeObjectURL(this.cvPreviewBlobUrl)
      this.cvPreviewBlobUrl = ''
      this.cvPreviewModal = false
      this.cvPreviewVoucher = null
    },

    _cvStatusLabel(s) {
      return { '草稿': '草稿', '待審核': '待審核', '簽核中': '簽核中', '已核准': '已核准' }[s] || s
    },

    _cvStatusClass(s) {
      return { '草稿': 'badge--draft', '待審核': 'badge--pending', '簽核中': 'badge--signing', '已核准': 'badge--approved' }[s] || ''
    },

    async uploadDispatchFiles(d, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/files`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '上傳失敗', {kind: 'error'}); return }
        const body = await r.json()
        if (!d.files) d.files = []
        d.files.push(...body.files)
      } catch (e) { MotrixUI.toast('上傳失敗：' + e.message, {kind: 'error'}) }
      evt.target.value = ''
    },

    async deleteDispatchFile(d, fileId) {
      if (!(await MotrixUI.confirm('確定刪除此報價附件？', {danger: true}))) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/files/${fileId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '刪除失敗', {kind: 'error'}); return }
        if (d.files) d.files = d.files.filter(f => f.id !== fileId)
      } catch (e) { MotrixUI.toast('刪除失敗：' + e.message, {kind: 'error'}) }
    },

    async uploadDispatchInvoiceFiles(d, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/invoice-files`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '上傳失敗', {kind: 'error'}); return }
        const body = await r.json()
        if (!d.invoiceFiles) d.invoiceFiles = []
        d.invoiceFiles.push(...body.files)
      } catch (e) { MotrixUI.toast('上傳失敗：' + e.message, {kind: 'error'}) }
      evt.target.value = ''
    },

    async deleteDispatchInvoiceFile(d, fileId) {
      if (!(await MotrixUI.confirm('確定刪除此廠商發票？', {danger: true}))) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/invoice-files/${fileId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '刪除失敗', {kind: 'error'}); return }
        if (d.invoiceFiles) d.invoiceFiles = d.invoiceFiles.filter(f => f.id !== fileId)
      } catch (e) { MotrixUI.toast('刪除失敗：' + e.message, {kind: 'error'}) }
    },

    _quoteStatusToDispatch(s) {
      return { '草稿': 'draft', '待審核': 'draft', '已核准': 'confirmed', '已結案': 'completed', '已取消': 'cancelled' }[s] || 'draft'
    },

    _dispatchSubtotal() {
      return (this.dispatchForm.items || []).reduce((s, it) => s + (+it.amount || 0), 0)
    },

    _dispatchTaxAmount() {
      return Math.round(this._dispatchSubtotal() * (+(this.dispatchForm.tax_rate) || 0))
    },

    _dispatchTotalWithTax() {
      return this._dispatchSubtotal() + this._dispatchTaxAmount()
    },

    _dispatchGrandTotal() {
      return this._dispatchTotalWithTax() + this._dispatchPersonnelTotal()
    },

    _dispatchLabel(d) {
      return d.vendorName || '外包人員（點工）'
    },

    _dispatchStatusClass(s) {
      return { draft: 'badge--draft', sent: 'badge--pending', confirmed: 'badge--approved', pending_acceptance: 'badge--signing', accepted: 'badge--running', completed: 'badge--settled', cancelled: 'badge--danger' }[s] || ''
    },

    async markPendingAcceptance(d) {
      if (!confirm(`確定將「${this._dispatchLabel(d)}」標記為待驗收？`)) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/accept`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ action: 'pending_acceptance' })
        })
        if (!r.ok) { alert((await r.json()).detail || '操作失敗'); return }
        await this.loadDispatches(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async acceptDispatch(d) {
      if (!(await MotrixUI.confirm(`確定驗收「${this._dispatchLabel(d)}」的工程？\n驗收後將記錄您的姓名與時間。`))) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/accept`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ action: 'accepted' })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '操作失敗', {kind: 'error'}); return }
        await this.loadDispatches(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    // CM12 P2：切換案件時重設本模組的案件層級狀態（時點見 core 的 _resetCaseScoped）
    _reset_dispatch(phase, data) {
      if (phase === 'early') {
        this.contractorVouchers = []
        this.contractorVouchersLoading = true
      }
      if (phase === 'late') {
        this.closeContractorVoucherPreview()
      }
    },
}))
