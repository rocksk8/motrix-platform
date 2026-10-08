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
    _dispatchesFor: '',
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
    payLinks: null,          // R12：個人外包人員 ↔ 勞報單（同出納頁）
    payLinksError: '',
    payVoucherTarget: null,
    payVoucherDate: '',
    payVoucherNote: '',
    payVoucherBankAcctCode: '',
    payVoucherSaving: false,
    // W1：匯款實付／手續費（實付空白＝等於應付；手續費是公司自付、不參與比對；實付≠應付 ⇒ 差額待審核，管理員在出納頁核可）
    payRemit: { actual: '', hasFee: false, fee: '' },
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
    // 31-B S3：款別（分期）——款別清單來自 GET /api/remit-kinds；試算打 POST /api/contractor-vouchers/preview（與建立同一支後端規則，畫面不自己算）
    remitKinds: [],
    cvForm: { mode: 'whole', kind: '', input: 'ratio', ratio: '', amount: '' },
    cvPlan: null,           // 試算結果（後端回傳的 plan＋序號＋警示）
    cvPlanError: '',
    cvPlanBusy: false,
    _cvPlanTimer: null,
    _cvPlanSeq: 0,

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

    // 派發 ⇄ 勞報單連結（第46班 P3）：每張派發卡片一個區塊；只顯示單號、狀態、受領人，**沒有金額**；建立／解除只有最高管理者
    dpSlips: {},
    async dpSlipLoad(d) {
      const cur = this.dpSlips[d.id] || { items: [], notice: '', canOpen: false, canEdit: false, input: '', err: '', loaded: false, hidden: false }
      // 沒有 procurement／case_manage／contractor_list／quotation 任一模組的人（非最高管理者）後端一律 403：不送請求、整塊不顯示（不留紅字也不留 console 錯誤）
      const mods = (this.session && this.session.modules) || []
      if (!(this.session && this.session.role === 'superadmin') && !['procurement', 'case_manage', 'contractor_list', 'quotation'].some(k => mods.includes(k))) {
        this.dpSlips = { ...this.dpSlips, [d.id]: { ...cur, loaded: true, hidden: true } }; return
      }
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/payslip-links`, { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) { const b = await r.json(); this.dpSlips = { ...this.dpSlips, [d.id]: { ...cur, ...b, loaded: true, err: '' } } }
        else if (r.status === 403 || r.status === 404) this.dpSlips = { ...this.dpSlips, [d.id]: { ...cur, loaded: true, hidden: true } }      // 無權限／看不到該案：安靜地不顯示
        else this.dpSlips = { ...this.dpSlips, [d.id]: { ...cur, loaded: true, err: '無法讀取勞報單關聯（HTTP ' + r.status + '）' } }
      } catch (e) { this.dpSlips = { ...this.dpSlips, [d.id]: { ...cur, loaded: true, err: '無法讀取勞報單關聯' } } }
    },
    async dpSlipAdd(d) {
      const s = this.dpSlips[d.id]; if (!s) return
      const no = (s.input || '').trim()
      if (!no) { s.err = '請填勞報單單號'; return }
      const r = await fetch(`/api/contractor-dispatches/${d.id}/payslip-links`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token }, body: JSON.stringify({ slipNo: no }) })
      if (!r.ok) { let m = ''; try { m = (await r.json()).detail } catch (e) {}; s.err = m || ('關聯失敗（HTTP ' + r.status + '）'); return }
      s.input = ''; await this.dpSlipLoad(d)
    },
    async dpSlipRemove(d, slipNo) {
      const s = this.dpSlips[d.id]; if (!s) return
      const r = await fetch(`/api/contractor-dispatches/${d.id}/payslip-links/${encodeURIComponent(slipNo)}`, { method: 'DELETE', headers: { Authorization: 'Bearer ' + this.session.token } })
      if (!r.ok) { let m = ''; try { m = (await r.json()).detail } catch (e) {}; s.err = m || ('解除失敗（HTTP ' + r.status + '）'); return }
      await this.dpSlipLoad(d)
    },

    async loadDispatches(quoteNo, pre) {
      if (!quoteNo) return
      const live = this._selectLive()
      this.dispatchesLoading = true
      // 同一個案件重新載入（按鈕操作後、頁面自己的二次載入）不先清空清單：清空再填會讓整張卡片被換掉（x-for 重建），
      // 使用者正要按的按鈕在點擊瞬間脫離 DOM（e2e 偶發 detached）。換案件才清空，避免短暫顯示別案的派發。
      if (this._dispatchesFor !== quoteNo) this.dispatches = []
      this._dispatchesFor = quoteNo
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

    // 31-A：與營運報表同一條規則——已取消、草稿、已退回不計；待審核／簽核中計入（另標「含待審核」）；已核准與舊單照舊
    _dispatchCounts(d) {
      return d.status !== 'cancelled' && !['草稿', '已退回'].includes(d.approvalStatus || '')
    },

    // 2026-10-06（使用者裁示）：外包總成本跟營運報表同一條切換規則——派發單日期（dispatchDate）≥ 2026-10-01 的派發含稅計入（未稅承攬費＋稅額＋外包人員）；
    // 之前的派發照舊（未稅承攬費＋外包人員，稅額不計成本）。已完結案顯示的是存檔值（caseSettleSummary），不走這裡。切換日要與 recognition.DISPATCH_TAXED_FROM 同值。
    DISPATCH_TAXED_FROM: '2026-10-01',
    _dispatchTaxed(d) { return String(d.dispatchDate || '').slice(0, 10) >= this.DISPATCH_TAXED_FROM },
    _dispatchPretax(d) { return (d.totalAmount || 0) + (d.personnelTotal || 0) },
    _dispatchCost(d) { return this._dispatchTaxed(d) ? (d.grandTotal || 0) : this._dispatchPretax(d) },

    dispatchTotalCost() {
      return this.dispatches
        .filter(d => this._dispatchCounts(d))
        .reduce((s, d) => s + this._dispatchCost(d), 0)
    },

    // 含稅合計（全部派發）：給已完結案「過期」比對（完結摘要沒有標記或標記 taxed 時與它比）
    dispatchTotalCostGross() {
      return this.dispatches
        .filter(d => this._dispatchCounts(d))
        .reduce((s, d) => s + (d.grandTotal || 0), 0)
    },

    // 35c／36 完結案（標記 pretax）的「過期」比對用：全部派發的未稅承攬費＋外包人員
    dispatchTotalCostPretax() {
      return this.dispatches
        .filter(d => this._dispatchCounts(d))
        .reduce((s, d) => s + this._dispatchPretax(d), 0)
    },

    // 含在外包總成本內的稅額（切換日後的派發）／不計成本的稅額（切換日前的派發，照舊未稅）
    dispatchTaxCost() {
      return this.dispatches.filter(d => this._dispatchCounts(d) && this._dispatchTaxed(d))
        .reduce((s, d) => s + Math.max(0, (d.grandTotal || 0) - this._dispatchPretax(d)), 0)
    },
    dispatchTaxExcludedCost() {
      return this.dispatches.filter(d => this._dispatchCounts(d) && !this._dispatchTaxed(d))
        .reduce((s, d) => s + Math.max(0, (d.grandTotal || 0) - this._dispatchPretax(d)), 0)
    },

    dispatchPendingNote() {
      const p = this.dispatches.filter(d => this._dispatchCounts(d) && ['待審核', '簽核中'].includes(d.approvalStatus || ''))
      if (!p.length) return ''
      return `含待審核 ${p.length} 筆 NT$ ${p.reduce((s, d) => s + this._dispatchCost(d), 0).toLocaleString()}`
    },

    // 可往下推進作業狀態：已核准或舊單（後端同一道閘）
    _dispatchCanAdvance(d) {
      return d.status !== 'cancelled' && (d.legacy || d.approvalStatus === '已核准')
    },

    _dispatchReviewing(d) {
      return ['待審核', '簽核中'].includes(d.approvalStatus || '') || ['待審核', '簽核中'].includes(d.completionStatus || '')
    },

    // 財務 Tab 顯示的精算結果是完結當下凍結的 caseSettleSummary().dispatchTotal 快照，
    // 跟 dispatchTotalCost() 目前即時計算值比對——不一致代表承攬商派發在精算完結後
    // 又被異動過，此頁數字尚未反映最新狀況（見 settlement.html dispatchStale() 同一邏輯）
    financeDispatchStale() {
      if (this.caseSettleStatus() !== 'finalized') return null
      const frozen = MotrixLegalRound.halfUp(this.caseSettleSummary().dispatchTotal || 0)
      // 35c：完結 summary 帶 dispatchBasis='pretax' ⇒ 與未稅現算值比；沒有（舊完結案、含稅口徑）⇒ 與含稅現算值比（舊案不會因口徑切換而誤報過期）
      const live   = MotrixLegalRound.halfUp((this.caseSettleSummary().dispatchBasis === 'pretax' ? this.dispatchTotalCostPretax() : this.dispatchTotalCostGross()) || 0)
      if (frozen === live) return null
      return { frozen, live, diff: live - frozen }
    },

    _blankDispatchForm() {
      const today = MotrixDate.today()
      return {
        quote_no: this.selected?.quote_no || '',
        vendor_id: '',
        dispatch_date: today,
        scope: '',
        notes: '',
        invoice_no: '',
        invoice_date: '',
        payable_date: '',
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
      it.amount = MotrixLegalRound.halfUp(+it.qty || 0, +it.unitPrice || 0)
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
        const saved = await r.json().catch(() => ({}))
        if (!r.ok) { this.dispatchMsg = saved.detail || '儲存失敗'; this.dispatchSaving = false; return }
        this.showDispatchModal = false
        if (saved.legacyModified) MotrixUI.toast('舊單已修改：內容未經審核，成本與總帳照舊計入；稽核已記錄這次修改', {kind: 'warning'})
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
        if (j.glWarning) MotrixUI.toast(j.glWarning, {kind: 'info', ms: 9000})   // MONEY-FLOWS §9 L3：已入帳的 E04 會 drift
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
      if (!this.remitKinds.length) this.loadRemitKinds()
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

    // 一張派發可有多張匯款申請（31-B 分期）：全部（含已作廢，畫面灰字顯示）依建立順序
    _dispatchVouchers(d) {
      return this.contractorVouchers.filter(v => v.dispatchId === d.id).sort((a, b) => (a.id || 0) - (b.id || 0))
    },

    _dispatchOpenVouchers(d) {
      return this._dispatchVouchers(d).filter(v => !v.voidedAt)
    },

    // 舊式整筆申請（不分期）：同派發最多一張未作廢
    _dispatchVoucher(d) {
      return this._dispatchOpenVouchers(d).find(v => !v.kind) || null
    },

    // 後進先出：只有最新一張未作廢的分期申請可以作廢
    _cvIsLatestOpen(d, v) {
      const open = this._dispatchOpenVouchers(d).filter(x => x.kind)
      return open.length > 0 && open[open.length - 1].voucherNo === v.voucherNo
    },

    _cvKindLabel(v) {
      return v.kind ? `${v.kindName || v.kind}　第 ${v.seq} 期` : ''
    },

    // 已申請稅前合計／剩餘（只算未作廢的分期申請；舊式整筆不分期）
    _cvIssuedPretax(d) {
      return this._dispatchOpenVouchers(d).filter(x => x.kind).reduce((s, x) => s + (x.pretaxAmount || 0), 0)
    },

    _cvRemaining(d) {
      return MotrixLegalRound.halfUp(d.totalAmount || 0) - this._cvIssuedPretax(d)      // 後端以四捨五入的整數元計額度（派發金額可能帶角分）
    },

    // 這張派發現在能開的款別（啟用中、派發狀態在該款別的可開立狀態內）
    _cvKindsFor(d) {
      if (!d) return []
      return (this.remitKinds || []).filter(k => k.active !== false && (k.stages || []).includes(d.status))
    },

    // 「產生匯款申請／新增一期」是否顯示：有舊式未作廢申請 ⇒ 不顯示；已分期且已全部申請完 ⇒ 不顯示
    _cvCanCreate(d) {
      if (this._dispatchVoucher(d)) return false
      const kinded = this._dispatchOpenVouchers(d).filter(x => x.kind)
      if (kinded.length) return this._cvRemaining(d) > 0
      return d.status === 'completed' || d.status === 'accepted' || this._cvKindsFor(d).length > 0
    },

    // 整列（匯款申請區）是否顯示：已有申請（含已作廢）或現在能開
    _cvRowVisible(d) {
      return this._dispatchVouchers(d).length > 0 || d.status === 'completed' || d.status === 'accepted' || this._cvKindsFor(d).length > 0
    },

    async loadRemitKinds() {
      if (!['superadmin', 'finance'].includes(this.session?.role)) return      // 第42班：匯款款別下拉＝財務角色
      try {
        const r = await fetch('/api/remit-kinds', { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) this.remitKinds = (await r.json()).kinds || []
      } catch {}
    },

    createContractorVoucher(d) {
      this.createVoucherDispatch = d
      this.createVoucherPayableDate = d.payableDate || ''
      const kinded = this._dispatchOpenVouchers(d).some(x => x.kind)
      const kinds = this._cvKindsFor(d)
      const wholeOk = d.status === 'completed' || d.status === 'accepted'
      // 已分期 ⇒ 只能續開分期；否則整筆可用就預設整筆（與舊流程一致），不能整筆就預設分期
      const mode = kinded || !wholeOk ? 'kind' : 'whole'
      this.cvForm = { mode, kind: (kinds[0] || {}).code || '', input: 'ratio', ratio: '', amount: '' }
      this.cvPlan = null
      this.cvPlanError = ''
      this.createVoucherModal = true
    },

    // 試算（後端算，畫面不重算）：輸入改了 300ms 後送一次；回應順序錯亂時只認最後一次
    cvPlanSchedule() {
      clearTimeout(this._cvPlanTimer)
      this._cvPlanSeq++                // 在途的舊請求作廢：它回來時不可以把舊輸入的試算蓋回畫面（確認鈕會在新試算回來前被誤開）
      this.cvPlanBusy = false
      this.cvPlan = null
      this.cvPlanError = ''
      const f = this.cvForm
      const d = this.createVoucherDispatch
      if (!d || f.mode !== 'kind' || !f.kind) return
      const v = f.input === 'ratio' ? f.ratio : f.amount
      if (v === '' || v == null) return
      this._cvPlanTimer = setTimeout(() => this.cvPlanRun(), 300)
    },

    async cvPlanRun() {
      const f = this.cvForm
      const d = this.createVoucherDispatch
      if (!d) return
      const mine = ++this._cvPlanSeq
      this.cvPlanBusy = true
      try {
        const r = await fetch('/api/contractor-vouchers/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(this._cvKindBody(d, f))
        })
        const body = await r.json().catch(() => ({}))
        if (mine !== this._cvPlanSeq) return
        if (r.ok) { this.cvPlan = body; this.cvPlanError = '' }
        else { this.cvPlan = null; this.cvPlanError = body.detail || '試算失敗' }
      } catch (e) { if (mine === this._cvPlanSeq) { this.cvPlan = null; this.cvPlanError = '網路錯誤：' + e.message } }
      if (mine === this._cvPlanSeq) this.cvPlanBusy = false
    },

    _cvKindBody(d, f) {
      const b = { dispatch_id: d.id, kind: f.kind }
      if (f.input === 'ratio') b.ratio_percent = Number(f.ratio)
      else b.amount = Number(f.amount)
      return b
    },

    // 試算區顯示用：本期稅前／稅額、是否最後一期
    cvPlanSummary() {
      const p = this.cvPlan && this.cvPlan.plan
      if (!p) return ''
      const money = n => Number(n || 0).toLocaleString()
      let t = `第 ${this.cvPlan.seq} 期　稅前 ${money(p.pretax)}　稅額 ${money(p.tax)}　`
      t += p.is_last ? '（最後一期，補到與整筆一致）' : `（剩餘額度 ${money(p.remaining_after)}）`
      return t
    },

    async confirmCreateContractorVoucher() {
      const d = this.createVoucherDispatch
      if (!d) return
      this.createVoucherSaving = true
      try {
        const r = await fetch('/api/contractor-vouchers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(this.cvForm.mode === 'kind'
            ? Object.assign(this._cvKindBody(d, this.cvForm), { payable_date: this.createVoucherPayableDate || null })
            : { dispatch_id: d.id, payable_date: this.createVoucherPayableDate || null })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '建立失敗', {kind: 'error'}); this.createVoucherSaving = false; return }
        this.createVoucherModal = false
        this.createVoucherDispatch = null
        await this.loadDispatches(this.selected?.quote_no)
        await this.loadContractorVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
      this.createVoucherSaving = false
    },

    // 作廢分期申請（後進先出；已付款須先取消已匯款）：原因必填，後端也強制
    async voidContractorVoucher(v) {
      for (;;) {
        const reason = await MotrixUI.prompt(`作廢匯款申請「${v.voucherNo}」：作廢後這一期不再占用額度，可重新開立；序號不會回頭重用。請填寫作廢原因（必填）：`)
        if (reason === null || reason === undefined) return
        if (!String(reason).trim()) { MotrixUI.toast('作廢要填原因', {kind: 'error'}); continue }
        try {
          const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/void`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({ reason: String(reason).trim() })
          })
          if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '作廢失敗', {kind: 'error'}); return }
        } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}); return }
        await this.loadContractorVouchers(this.selected?.quote_no)
        return
      }
    },

    // 登錄／更正／清除分期申請自己的發票（D11：可事後補；沒有發票日就不產生該期的應付認列分錄）。兩欄都留空＝清除。
    async setVoucherInvoice(v) {
      const no = await MotrixUI.prompt(`匯款申請「${v.voucherNo}」的發票號碼（可留空）：`, { value: v.invNo || '' })
      if (no === null || no === undefined) return
      const date = await MotrixUI.prompt(`發票日期（YYYY-MM-DD；留空＝清除發票，該期不認列）：`, { value: v.invDate || '' })
      if (date === null || date === undefined) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/invoice`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ invNo: String(no).trim(), invDate: String(date).trim() })
        })
        const body = await r.json().catch(() => ({}))
        if (!r.ok) { MotrixUI.toast(body.detail || '登錄失敗', {kind: 'error'}); return }
        if (body.glWarning) MotrixUI.toast(body.glWarning, {kind: 'warning'})
        await this.loadContractorVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
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

    // 退回（列表按鈕與預覽裡的「退回修改」同一條路）：原因必填，後端也強制
    rejectContractorVoucher(v) {
      window.MotrixApprovalReturn.ask({
        title: `退回匯款申請「${v.voucherNo}」`,
        post: (reason) => fetch(`/api/contractor-vouchers/${v.voucherNo}/reject`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note: reason })
        }),
        onDone: () => this.loadContractorVouchers(this.selected?.quote_no),
      })
    },

    returnFromContractorVoucherPreview() {
      const v = this.cvPreviewVoucher
      this.closeContractorVoucherPreview()
      if (v) this.rejectContractorVoucher(v)
    },

    // 撤銷核准（退回草稿）：原因必填，後端也強制
    revokeContractorVoucherApproval(v) {
      window.MotrixApprovalReturn.ask({
        title: `撤銷匯款申請「${v.voucherNo}」的核准`,
        hint: '撤銷後單據退回草稿。撤銷原因必填，會寫進稽核並通知申請人。',
        post: (reason) => fetch(`/api/contractor-vouchers/${v.voucherNo}/revoke-approval`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note: reason })
        }),
        onDone: () => this.loadContractorVouchers(this.selected?.quote_no),
      })
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

    remitDiff(st, payable) {
      const a = (st.actual === '' || st.actual == null) ? Number(payable) : Number(st.actual)
      return MotrixLegalRound.halfUp((a - Number(payable || 0)) * 100) / 100
    },
    remitError(st) {
      if (st.actual !== '' && st.actual != null && !(Number(st.actual) > 0)) return '實付金額必須大於 0'
      if (st.hasFee && (st.fee === '' || st.fee == null || !(Number(st.fee) >= 0))) return '請填寫手續費金額（不可為負數）'
      return ''
    },
    remitBody(st) {
      const b = {}
      if (st.actual !== '' && st.actual != null) b.actualAmount = Number(st.actual)
      if (st.hasFee) { b.hasFee = true; b.fee = Number(st.fee) }
      return b
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
        this.payRemit = { actual: v.grandTotal != null ? String(v.grandTotal) : '', hasFee: false, fee: '' }
        this.payVoucherBankAcctCode = ''
        this._payVoucherBankName = ''
        this.payLinks = null
        this.payLinksError = ''
        this.payVoucherModal = true
        await this.loadPayLinks()
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
        const unpayRes = await r.json().catch(() => ({}))
        if (unpayRes.glWarning) MotrixUI.toast(unpayRes.glWarning, {kind: 'info', ms: 9000})   // MONEY-FLOWS §9 L3：已入帳的 E05 會 orphan（反向草稿）
        await this.loadContractorVouchers(this.selected?.quote_no)
        this.loadFinanceSummary(this.selected?.quote_no)   // 已付/未付數字會變
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async loadPayLinks() {
      const v = this.payVoucherTarget
      if (!v) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${encodeURIComponent(v.voucherNo)}/personnel-links`, { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) { this.payLinksError = (await r.json().catch(() => ({}))).detail || '讀取勞報單關聯失敗'; return }
        const d = await r.json()
        this.payLinks = d.lines.length ? d : null
        this.payLinksError = ''
      } catch (e) { this.payLinksError = '讀取勞報單關聯失敗：' + e.message }
    },

    payLinksBlocked() { return !!(this.payLinks && !this.payLinks.canPay) },

    async linkPayslip(line, slipNo) {
      const v = this.payVoucherTarget
      if (!v) return
      this.payLinksError = ''
      try {
        const r = await fetch(`/api/contractor-vouchers/${encodeURIComponent(v.voucherNo)}/personnel-link`, {
          method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ personId: line.id, payslipNo: slipNo || '' })
        })
        if (!r.ok) this.payLinksError = (await r.json().catch(() => ({}))).detail || '關聯失敗'
      } catch (e) { this.payLinksError = '關聯失敗：' + e.message }
      await this.loadPayLinks()
    },

    async confirmPayVoucher() {
      const v = this.payVoucherTarget
      if (!v || !this.payVoucherDate || this.remitError(this.payRemit) || this.payLinksBlocked()) return
      this.payVoucherSaving = true
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/paid-toggle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({
            action: 'pay', paid_at: this.payVoucherDate, note: this.payVoucherNote,
            bankAccountCode: this.payVoucherBankAcctCode, bankAccountName: this._payVoucherBankName || '',
            ...this.remitBody(this.payRemit),
          })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '操作失敗', {kind: 'error'}); this.payVoucherSaving = false; return }
        const res = await r.json().catch(() => ({}))
        if (res.remitReview) MotrixUI.toast('實付與應付差 ' + res.diff + ' 元，已送管理員審核（出納頁「差額審核」）', {kind: 'warn'})
        this.payVoucherModal = false
        this.payVoucherTarget = null
        await this.loadContractorVouchers(this.selected?.quote_no)
        this.loadFinanceSummary(this.selected?.quote_no)   // 已付/未付數字會變
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
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
      await window.MotrixApprovalReturn.loadDelegators(this.session.token)   // 代理簽核人也要看得到「退回修改」
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
      return { '草稿': '草稿', '待審核': '待審核', '簽核中': '簽核中', '已核准': '已核准', '已作廢': '已作廢' }[s] || s
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

    // 承攬商報價單附件刪除＝申請刪除、要審核（N1）：核可前檔案保留並標「刪除待審」；沒設簽核層且是最高管理者才直接刪
    async deleteDispatchFile(d, fileId) {
      const reason = await MotrixUI.prompt('刪除承攬商報價單附件需要審核，請填寫刪除原因：', {title: '申請刪除報價單附件', required: true, okText: '送出申請'})
      if (reason === null || reason === undefined || reason === false) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/files/${fileId}`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ reason: String(reason) })
        })
        const body = await r.json().catch(() => ({}))
        if (!r.ok) { MotrixUI.toast(body.detail || '申請失敗', {kind: 'error'}); return }
        if (body.deleted) { if (d.files) d.files = d.files.filter(f => f.id !== fileId) }
        else { MotrixUI.toast('已送出刪除申請，核可前檔案會保留', {kind: 'success'}); await this.loadDispatches(this.selected?.quote_no) }
      } catch (e) { MotrixUI.toast('申請失敗：' + e.message, {kind: 'error'}) }
    },

    // 這個刪除申請現在輪到我審核嗎（有簽核層：當層排序最前的未簽人；沒有簽核層：最高管理者）
    canDecideFileDelete(f) {
      const req = f && f.deleteRequest
      if (!req) return false
      const tiers = req.tiers || []
      if (!tiers.length) return this.session.role === 'superadmin'
      const t = tiers[req.currentTier || 0]
      const first = t && (t.approvers || []).find(a => a.status !== 'approved')
      return !!first && first.username === this.session.username
    },

    async decideFileDelete(d, f, decision) {
      let note = ''
      if (decision === 'reject') {
        note = await MotrixUI.prompt('退回刪除申請（檔案會保留），原因：', {title: '退回刪除申請', okText: '退回'})
        if (note === null || note === undefined || note === false) return
      } else if (!(await MotrixUI.confirm('核可後這個報價單附件會被刪除，確定？', {danger: true}))) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/files/${f.id}/${decision === 'approve' ? 'delete-approve' : 'delete-reject'}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note: String(note || '') })
        })
        const body = await r.json().catch(() => ({}))
        if (!r.ok) { MotrixUI.toast(body.detail || '操作失敗', {kind: 'error'}); return }
        await this.loadDispatches(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('操作失敗：' + e.message, {kind: 'error'}) }
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
      // X-VAT（2026-09-26）：與後端 contractor_vouchers／vendor_contractors 的稅額同一套四捨五入
      return MotrixLegalRound.halfUp(this._dispatchSubtotal(), +(this.dispatchForm.tax_rate) || 0)
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

    // 派發卡片上的操作按鈕（送審／撤回／已送出／已確認／申請完工／取消）：一律打後端，狀態只由後端決定
    async _dispatchPost(d, path, body, confirmMsg, opts) {
      if (confirmMsg && !(await MotrixUI.confirm(confirmMsg, opts || {}))) return false
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}${path}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(body || {})
        })
        const j = await r.json().catch(() => ({}))
        if (!r.ok) { MotrixUI.toast(j.detail || '操作失敗', {kind: 'error'}); return false }
        if (j.autoApproved) MotrixUI.toast('未設定簽核層，已直接核准')
        await this.loadDispatches(this.selected?.quote_no)
        return true
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}); return false }
    },

    submitDispatch(d) {
      return this._dispatchPost(d, '/submit', {}, `送審「${this._dispatchLabel(d)}」？送出後在核准前不能編輯。`)
    },
    withdrawDispatch(d) {
      return this._dispatchPost(d, '/withdraw', {}, `撤回「${this._dispatchLabel(d)}」的送審？`)
    },
    setDispatchStatus(d, target, label) {
      return this._dispatchPost(d, '/status', { target }, `將「${this._dispatchLabel(d)}」標記為${label}？`)
    },
    requestDispatchCompletion(d) {
      return this._dispatchPost(d, '/completion/request', {}, `申請「${this._dispatchLabel(d)}」完工？需經完工審核通過才會完結。`)
    },
    withdrawDispatchCompletion(d) {
      return this._dispatchPost(d, '/completion/withdraw', {}, `撤回「${this._dispatchLabel(d)}」的完工申請？`)
    },
    async cancelDispatch(d) {
      const needReason = d.approvalStatus === '已核准' || ['pending_acceptance', 'accepted'].includes(d.status)
      const reason = await MotrixUI.prompt(`取消「${this._dispatchLabel(d)}」（金額不再計入成本）${needReason ? '，請填寫取消原因：' : '：'}`,
        { title: '取消派發', required: needReason, okText: '取消派發' })
      if (reason === null || reason === undefined || reason === false) return
      return this._dispatchPost(d, '/status', { target: 'cancelled', reason })
    },

    async markPendingAcceptance(d) {
      if (!(await MotrixUI.confirm(`確定將「${this._dispatchLabel(d)}」標記為待驗收？`))) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/accept`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ action: 'pending_acceptance' })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '操作失敗', {kind: 'error'}); return }
        await this.loadDispatches(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
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
        this._dispatchesFor = ''
        this.contractorVouchers = []
        this.contractorVouchersLoading = true
      }
      if (phase === 'late') {
        this.closeContractorVoucherPreview()
      }
    },
}))
