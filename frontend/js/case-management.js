function app() {
  return {
      isMobileView: window.innerWidth <= 767,
    session: {},
    loading: true,
    cases: [],
    filteredCases: [],
    listTab: 'all',
    search: '',
    unreadOnly: false,
    readAt: null,
    caseActivity: {},
    selected: null,
    activeTab: 'biz',
    execSubTab: 'progress',
    cr: { dealTag: '已成案', caseRecord: null },
    dirty: false,
    saving: false,
    saveStatus: '',
    saveMsg: '',
    _autoSaveTimer: null,
    writeoffModal: { open: false, idx: null, mode: 'request', reason: '' },
    dragFromIdx: null,
    _openStageDetail: {},
    _newStageAssignee: {},
    stageView: 'list',
    _ganttInstance: null,
    showImportModal: false,
    importMode: 'materials',
    importSelectedItems: {},
    showLog: false,
    _allDonePrompted: false,
    _syncWarrantyDate: '',
    _syncWarrantyMonths: 12,
    _openDevGroups: {},
    _devDragId: null,        // device.id being dragged
    _devDragOverId: null,    // current hover target string ('dev_X' | 'group_X')
    _devInsertBeforeId: null,// where to show insert line ('dev_X' | 'end' | null)
    _devHoverGroupId: null,  // group ID when hovering group header → add-to-group mode
    _devHoverStart: 0,       // timestamp when we entered _devDragOverId
    _devGroupTarget: null,   // 'dev_X' confirmed for grouping after 900ms hover
    linkedProjectId: null,
    showCreateProjectModal: false,
    newProjectName: '',
    creatingProject: false,
    selectableUsers: [],

    caseTasks: [],
    caseTasksLoading: false,
    caseTasksOpen: true,

    // ── 今日相關任務 回報 ──
    caseTaskEditing: { taskId: null, text: '' },
    caseTaskEditSubmitting: false,
    caseTaskEditLogs: {},
    caseTaskLogsOpen: {},

    // ── 動態 Tab ──
    caseUpdates: [],
    updatesLoading: false,
    newComment: '',
    postingComment: false,

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

    // ── 出貨單 ──
    shippingNotes: [],
    shippingNotesLoading: false,
    showShippingModal: false,
    editShippingNoteNo: null,
    shippingSaving: false,
    shippingForm: {},
    shippingMsg: '',
    _shippingLogOpen: {},
    shippingContactOptions: [],
    showShippingContactPicker: false,
    shippingPreviewModal: false,
    shippingPreviewBlobUrl: '',
    shippingPreviewFetching: false,
    shippingPreviewNote: null,

    canSeeFinancial() {
      const m = this.session.modules || []
      return m.includes('financial_view') || ['superadmin','admin','sales'].includes(this.session.role)
    },

    canManageProject() {
      const m = this.session.modules || []
      return m.includes('project_manage') || ['superadmin','admin'].includes(this.session.role)
    },

    caseSettlement()    { return this.selected?.data?.settlement || null },
    caseSettleStatus()  { return this.caseSettlement()?.status || '' },
    caseSettleSummary() { return this.caseSettlement()?.summary || {} },
    caseSettleItems()   { return this.caseSettlement()?.items   || [] },
    caseSettleExtras()  { return this.caseSettlement()?.extraItems || [] },
    caseSettleMemo()    { return this.caseSettlement()?.memo || '' },
    caseSettleFmt(n)    { return 'NT$ ' + (Math.round(n || 0)).toLocaleString() },

    async init() {
      window.addEventListener('resize', () => { this.isMobileView = window.innerWidth <= 767 })
      const s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      if (!s.token) { location.href = 'login.html'; return }
      this.session = s
      try {
        const r = await fetch('/api/auth/me', { headers: { Authorization: 'Bearer ' + s.token } })
        if (!r.ok) { location.href = 'login.html'; return }
        const me = await r.json()
        this.session.displayName = me.display_name
      } catch {}
      try {
        const ru = await fetch('/api/users/selectable', { headers: { Authorization: 'Bearer ' + s.token } })
        if (ru.ok) this.selectableUsers = await ru.json()
      } catch {}
      try {
        const stored = localStorage.getItem('motrix_casemgmt_read_at')
        if (stored) {
          this.readAt = stored
        } else {
          this.readAt = new Date().toISOString()
          localStorage.setItem('motrix_casemgmt_read_at', this.readAt)
        }
      } catch {}
      await this.loadCases()
      this.loadVendors()
      const _qp = new URLSearchParams(location.search).get('q')
      if (_qp) {
        const _found = this.filteredCases.find(c => c.quote_no === _qp)
        if (_found) await this.selectCase(_found.quote_no)
      }
    },

    async loadCases() {
      this.loading = true
      try {
        const s = this.session
        const r = await fetch('/api/quotations?deal_tag=%E5%B7%B2%E6%88%90%E6%A1%88,%E5%B7%B2%E7%B5%90%E6%A1%88&limit=500', {
          headers: { Authorization: 'Bearer ' + s.token }
        })
        if (r.ok) {
          const data = await r.json()
          this.cases = data.items || []
        }
      } catch {}
      this.loading = false
      this.filterCases()
      this.loadCaseActivity()
    },

    async loadCaseActivity() {
      const quoteNos = this.cases.map(c => c.quote_no).filter(Boolean)
      if (!quoteNos.length) { this.caseActivity = {}; return }
      try {
        const r = await fetch('/api/quotations/case-activity', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token, 'Content-Type': 'application/json' },
          body: JSON.stringify({ quote_nos: quoteNos }),
        })
        if (r.ok) this.caseActivity = await r.json()
      } catch {}
    },

    isUnread(c) {
      const ts = this.caseActivity[c.quote_no]
      if (!this.readAt || !ts) return false
      const u = new Date(ts.replace(' ', 'T'))
      if (isNaN(u)) return false
      return u.getTime() > new Date(this.readAt).getTime()
    },

    unreadCount() {
      return this.cases.filter(c => this.isUnread(c)).length
    },

    markAllRead() {
      this.readAt = new Date().toISOString()
      try { localStorage.setItem('motrix_casemgmt_read_at', this.readAt) } catch {}
      this.unreadOnly = false
      this.filterCases()
    },

    filterCases() {
      let list = this.cases
      if (this.listTab === '待精算') {
        list = list.filter(c => c.settle_status === 'draft')
      } else if (this.listTab === 'all') {
        list = list.filter(c => c.deal_tag !== '已結案')
      } else {
        list = list.filter(c => c.deal_tag === this.listTab)
      }
      if (this.unreadOnly) {
        list = list.filter(c => this.isUnread(c))
      }
      if (this.search.trim()) {
        const q = this.search.trim().toLowerCase()
        list = list.filter(c =>
          (c.quote_no || '').toLowerCase().includes(q) ||
          (c.customer_name || '').toLowerCase().includes(q) ||
          (c.project_name  || '').toLowerCase().includes(q)
        )
      }
      this.filteredCases = list
    },

    async selectCase(quoteNo) {
      clearTimeout(this._autoSaveTimer)
      try {
        const r = await fetch('/api/quotations/' + quoteNo, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) return
        const data = await r.json()
        this.selected = data
        this.cr.dealTag = data.data?.dealTag || data.deal_tag || '已成案'
        this.cr.caseRecord = data.data?.caseRecord || null
        this.ensureCaseRecord()
        this.dirty = false
        this.saveStatus = ''
        this.saveMsg = ''
        this.activeTab = 'biz'
        this.execSubTab = 'progress'
        this.showLog = false
        this.showImportModal = false
        this._allDonePrompted = false
        this._syncWarrantyDate = ''
        this._syncWarrantyMonths = 12
        this._openDevGroups = {}
        this.stageView = 'list'
        this._devDragId = null
        this._devDragOverId = null
        this._devInsertBeforeId = null
        this._devHoverGroupId = null
        this._devGroupTarget = null
        this._devHoverStart = 0
        this.linkedProjectId = null
        this.caseTasks = []
        this.caseUpdates = []
        this.newComment = ''
        this.shippingNotes = []
        this.showShippingModal = false
        this._shippingLogOpen = {}
        this.shippingContactOptions = []
        this.showShippingContactPicker = false
        this.closeShippingPreview()
        // 背景查詢是否已有關聯專案
        this._checkLinkedProject(quoteNo)
        this._loadCaseTasks(quoteNo)
        this.loadDispatches(quoteNo)
      } catch {}
    },

    async _loadCaseTasks(quoteNo) {
      if (!quoteNo) return
      this.caseTasksLoading = true
      try {
        const today = new Date().toISOString().slice(0, 10)
        const r = await fetch(`/api/daily-tasks?date=${today}&case_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.caseTasks = (await r.json()).items || []
      } catch {}
      this.caseTasksLoading = false
    },

    async _checkLinkedProject(quoteNo) {
      try {
        const r = await fetch(`/api/projects?case_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) return
        const d = await r.json()
        this.linkedProjectId = d.items?.length > 0 ? d.items[0].id : null
      } catch {}
    },

    async goToProject() {
      if (!this.selected) return
      if (this.linkedProjectId) {
        location.href = `projects.html?id=${this.linkedProjectId}`
        return
      }
      // 非管理員直接導到專案列表過濾此案件
      if (!this.canManageProject()) {
        location.href = `projects.html?caseNo=${this.selected.quote_no}`
        return
      }
      // 管理員：預填名稱後開啟建立 Modal
      this.newProjectName = this.selected.project_name || this.selected.customer_name || ''
      this.showCreateProjectModal = true
    },

    async createProjectFromCase() {
      if (!this.newProjectName.trim() || !this.selected) return
      this.creatingProject = true
      try {
        const r = await fetch('/api/projects', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({
            name: this.newProjectName.trim(),
            status: '進行中',
            description: `由案件 ${this.selected.quote_no} 轉入`,
            linked_cases: [this.selected.quote_no],
          })
        })
        if (!r.ok) { alert('建立失敗：' + (await r.json()).detail); return }
        const d = await r.json()
        this.showCreateProjectModal = false
        location.href = `projects.html?id=${d.id}`
      } catch(e) {
        alert('發生錯誤：' + e.message)
      } finally {
        this.creatingProject = false
      }
    },

    ensureCaseRecord() {
      if (!this.cr.caseRecord) {
        this.cr.caseRecord = {
          stages: [
            { id: 1, label: '訂單確認', done: false, doneAt: '', visits: [], startDate:'', dueDate:'', assignedTo:[], dependsOn:[] },
            { id: 2, label: '叫料出貨', done: false, doneAt: '', visits: [], startDate:'', dueDate:'', assignedTo:[], dependsOn:[] },
            { id: 3, label: '施工安裝', done: false, doneAt: '', visits: [], startDate:'', dueDate:'', assignedTo:[], dependsOn:[] },
            { id: 4, label: '客戶驗收', done: false, doneAt: '', visits: [], startDate:'', dueDate:'', assignedTo:[], dependsOn:[] },
            { id: 5, label: '尾款結清', done: false, doneAt: '', visits: [], startDate:'', dueDate:'', assignedTo:[], dependsOn:[] },
          ],
          payment: { items: [
            { id: 1, type: '訂金款', pct: 30, received: false, receivedAt: '', invoiceNo: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
            { id: 2, type: '交貨款', pct: 30, received: false, receivedAt: '', invoiceNo: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
            { id: 3, type: '驗收款', pct: 40, received: false, receivedAt: '', invoiceNo: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          ], note: '' },
          materials: [], devices: [], warrantyNote: '', notes: '',
        }
      }
      if (!this.cr.caseRecord.stages)    this.cr.caseRecord.stages    = []
      if (!this.cr.caseRecord.materials) this.cr.caseRecord.materials = []
      if (!this.cr.caseRecord.devices)   this.cr.caseRecord.devices   = []
      if (!this.cr.caseRecord.contract) {
        this.cr.caseRecord.contract = { deliveryAddress: '', deliveryTerms: '', contactPerson: '', contactPhone: '', contractNote: '' }
      }
      if (!this.cr.caseRecord.roles) {
        this.cr.caseRecord.roles = { filler: '', sales: '', executor: '' }
      }

      this.cr.caseRecord.materials.forEach(mat => {
        if (!mat.devices) mat.devices = []
        if (!mat.model)   mat.model   = ''
        if (!mat.unit)    mat.unit    = '台'
      })

      this.cr.caseRecord.stages.forEach(st => {
        if (!st.visits) {
          st.visits = (st.visitDate || st.note)
            ? [{ id: Date.now() + Math.random(), visitDate: st.visitDate || '', visitPeople: st.visitPeople || '', note: st.note || '' }]
            : []
          delete st.visitDate; delete st.visitPeople; delete st.note
        }
        if (st.startDate  === undefined) st.startDate  = ''
        if (st.dueDate    === undefined) st.dueDate    = ''
        if (!st.assignedTo) st.assignedTo = []
        if (!st.dependsOn)  st.dependsOn  = []
      })

      if (!this.cr.caseRecord.payment) {
        this.cr.caseRecord.payment = { items: [
          { id: 1, type: '訂金款', pct: 30, amount: null, received: false, receivedAt: '', invoiceNo: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          { id: 2, type: '交貨款', pct: 30, amount: null, received: false, receivedAt: '', invoiceNo: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          { id: 3, type: '驗收款', pct: 40, amount: null, received: false, receivedAt: '', invoiceNo: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
        ], note: '' }
      } else if (!this.cr.caseRecord.payment.items) {
        this.cr.caseRecord.payment = { items: [
          { id: 1, type: '訂金款', pct: 30, amount: null, received: false, receivedAt: '', invoiceNo: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          { id: 2, type: '交貨款', pct: 30, amount: null, received: false, receivedAt: '', invoiceNo: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          { id: 3, type: '驗收款', pct: 40, amount: null, received: false, receivedAt: '', invoiceNo: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
        ], note: this.cr.caseRecord.payment.note || '' }
      }
    },

    paymentItems() { return this.cr.caseRecord?.payment?.items || [] },

    totalWithTax()  { return this.selected?.total    || 0 },
    totalPretax()   { return this.selected?.pretax   || 0 },
    totalTax()      { return this.totalWithTax() - this.totalPretax() },

    totalEnteredPct() {
      return this.paymentItems().reduce((s, p) => s + (+p.pct || 0), 0)
    },

    itemAmountWithTax(idx) {
      const items = this.paymentItems()
      if (items[idx]?.amount != null) return items[idx].amount
      return Math.round(this.totalWithTax() * (+items[idx]?.pct || 0) / 100)
    },

    // 未稅原價：不受沖銷影響，永遠是該筆款項依報價單稅率換算的未稅基準
    itemAmountPretax(idx) {
      const items  = this.paymentItems()
      const total  = this.totalWithTax()
      const pretax = this.totalPretax()
      if (items[idx]?.amount != null && total > 0)
        return Math.round(items[idx].amount * pretax / total)
      return Math.round(pretax * (+items[idx]?.pct || 0) / 100)
    },

    itemAmountTax(idx) {
      if (this.paymentItems()[idx]?.taxExempt) return 0
      return this.itemAmountWithTax(idx) - this.itemAmountPretax(idx)
    },

    // 該筆款項實際應收／已收金額：已核准沖銷免稅 → 客戶只付未稅價，稅額不再收取
    itemAmountReceivable(idx) {
      const items = this.paymentItems()
      return items[idx]?.taxExempt ? this.itemAmountPretax(idx) : this.itemAmountWithTax(idx)
    },

    _setItemAmount(items, idx, withTax) {
      // 規範值：直接存含稅整數，pct 作為百分比 input 顯示用
      const total = this.totalWithTax()
      items[idx].amount = Math.round(withTax)
      items[idx].pct    = total > 0 ? Math.round(withTax / total * 10000) / 100 : 0
    },

    _syncLast(items) {
      // 讓最後一筆含稅 = 合約總額 − Σ其他，確保合計精確
      const total   = this.totalWithTax()
      const lastIdx = items.length - 1
      const othersAmount = items.reduce((s, p, i) => i === lastIdx ? s : s + (p.amount ?? Math.round(total * (+p.pct || 0) / 100)), 0)
      this._setItemAmount(items, lastIdx, Math.max(0, total - othersAmount))
    },

    onPctChange(idx) {
      const items   = this.paymentItems()
      const total   = this.totalWithTax()
      const lastIdx = items.length - 1
      if (items.length > 1 && idx !== lastIdx) {
        // cap：非尾款項目的 pct 不超過 100 − 其他非尾款加總
        const othersExclLast = items.reduce((s, p, i) => (i === idx || i === lastIdx) ? s : s + (+p.pct || 0), 0)
        if ((+items[idx].pct || 0) > Math.max(0, 100 - othersExclLast))
          items[idx].pct = Math.max(0, 100 - othersExclLast)
        items[idx].amount = Math.round(total * (+items[idx].pct || 0) / 100)
        this._syncLast(items)
      } else {
        const othersSum = items.reduce((s, p, i) => i === idx ? s : s + (+p.pct || 0), 0)
        if ((+items[idx].pct || 0) > Math.max(0, 100 - othersSum))
          items[idx].pct = Math.max(0, 100 - othersSum)
        items[idx].amount = Math.round(total * (+items[idx].pct || 0) / 100)
      }
      this.setDirty()
    },

    onAmountWithTaxChange(idx, val) {
      const total = this.totalWithTax()
      if (!total || !isFinite(val) || val < 0) return
      const items   = this.paymentItems()
      const lastIdx = items.length - 1
      // 計算本項能用的最大含稅（其他非尾款已佔的部分之外）
      const othersTaken = items.reduce((s, p, i) => (i === idx || i === lastIdx) ? s
        : s + (p.amount ?? Math.round(total * (+p.pct || 0) / 100)), 0)
      const capped = Math.min(Math.round(val), Math.max(0, total - othersTaken))
      this._setItemAmount(items, idx, capped)
      if (items.length > 1 && idx !== lastIdx) this._syncLast(items)
      this.setDirty()
    },

    onAmountPretaxChange(idx, val) {
      const pretax = this.totalPretax()
      const total  = this.totalWithTax()
      if (!pretax || !isFinite(val) || val < 0) return
      // 未稅 → 換算含稅後，同 onAmountWithTaxChange 邏輯
      const withTax = Math.round(val * total / pretax)
      const items   = this.paymentItems()
      const lastIdx = items.length - 1
      const othersTaken = items.reduce((s, p, i) => (i === idx || i === lastIdx) ? s
        : s + (p.amount ?? Math.round(total * (+p.pct || 0) / 100)), 0)
      const capped = Math.min(withTax, Math.max(0, total - othersTaken))
      this._setItemAmount(items, idx, capped)
      if (items.length > 1 && idx !== lastIdx) this._syncLast(items)
      this.setDirty()
    },

    balanceLastPayment() {
      const items = this.paymentItems()
      if (items.length < 2) return
      this._syncLast(items)
      this.setDirty()
    },

    receivedTotal() {
      return this.paymentItems().reduce((s, p, i) => p.received ? s + this.itemAmountReceivable(i) : s, 0)
    },
    receivedPct() {
      return this.paymentItems().reduce((s, p) => p.received ? s + (+p.pct || 0) : s, 0)
    },
    feeTotal() {
      return this.paymentItems().reduce((s, p) => p.received ? s + (+p.feeAmount || 0) : s, 0)
    },
    netReceivedTotal() {
      return this.paymentItems().reduce((s, p, i) => {
        if (!p.received) return s
        const base = p.actualAmount != null ? +p.actualAmount : this.itemAmountReceivable(i)
        return s + base - (+p.feeAmount || 0)
      }, 0)
    },
    outstandingTotal() {
      return Math.max(0, this.paymentItems().reduce((s, p, i) => p.received ? s : s + this.itemAmountReceivable(i), 0))
    },
    outstandingPct()   { return Math.max(0, 100 - this.receivedPct()) },

    addPaymentItem() {
      const items = this.cr.caseRecord.payment.items
      items.push({ id: Date.now(), type: '進度款', pct: 0, received: false, receivedAt: '', invoiceNo: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' })
      this.setDirty()
    },
    removePaymentItem(idx) {
      if (this.cr.caseRecord.payment.items.length <= 1) return
      this.cr.caseRecord.payment.items.splice(idx, 1)
      if (this.cr.caseRecord.payment.items.length === 1) {
        this.cr.caseRecord.payment.items[0].pct = 100
      }
      this.setDirty()
    },

    setDirty() {
      this.dirty = true
      this.saveStatus = 'dirty'
      this.saveMsg = '未儲存'
      clearTimeout(this._autoSaveTimer)
      this._autoSaveTimer = setTimeout(() => this.saveCaseRecord(), 1500)
      this._checkAllStagesDone()
    },

    _checkAllStagesDone() {
      if (this.cr.dealTag !== '已成案') return
      const stages = this.cr.caseRecord?.stages || []
      if (!stages.length) return
      if (!stages.every(s => s.done)) { this._allDonePrompted = false; return }
      if (this._allDonePrompted) return
      this._allDonePrompted = true
      setTimeout(() => {
        if (confirm('所有執行進度已完成！\n\n是否現在完結案件並進入保固追蹤期？\n（可稍後再按右上角「完結案」按鈕）')) {
          this.closeCaseAction()
        }
      }, 300)
    },

    async saveCaseRecord() {
      if (!this.selected) return
      this.saving = true
      try {
        const r = await fetch('/api/quotations/' + this.selected.quote_no + '/case-record', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ case_record: this.cr.caseRecord })
        })
        if (r.ok) {
          this.dirty = false
          this.saveStatus = 'saved'
          this.saveMsg = '已儲存'
          setTimeout(() => { if (!this.dirty) { this.saveStatus = ''; this.saveMsg = '' } }, 2000)
        } else {
          this.saveStatus = 'error'
          this.saveMsg = '儲存失敗'
        }
      } catch {
        this.saveStatus = 'error'
        this.saveMsg = '網路錯誤'
      }
      this.saving = false
    },

    openWriteoffModal(idx, mode) {
      this.writeoffModal = { open: true, idx, mode, reason: '', msg: '' }
    },

    async _postWriteoff(idx, path, body) {
      const quoteNo = this.selected.quote_no
      const r = await fetch(`/api/quotations/${quoteNo}/payment/${idx}/${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
        body: JSON.stringify(body || {})
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        return { ok: false, msg: err.detail || '操作失敗' }
      }
      return { ok: true }
    },

    async submitWriteoffModal() {
      const { idx, mode, reason } = this.writeoffModal
      if (!reason.trim()) return
      const item = this.paymentItems()[idx]
      const me = this.session.displayName || this.session.username || ''
      let res
      if (mode === 'request') {
        res = await this._postWriteoff(idx, 'request-writeoff', { reason })
        if (res.ok) {
          item.writeOffStatus = 'pending'
          item.writeOffReason = reason
          item.writeOffRequestedBy = me
          item.writeOffRequestedAt = new Date().toISOString()
        }
      } else {
        res = await this._postWriteoff(idx, 'approve-writeoff', { approve: false, reject_reason: reason })
        if (res.ok) {
          item.writeOffStatus = 'rejected'
          item.writeOffRejectReason = reason
        }
      }
      if (res.ok) {
        this.writeoffModal.open = false
      } else {
        this.writeoffModal.msg = res.msg
      }
    },

    async cancelWriteoff(idx) {
      const item = this.paymentItems()[idx]
      const res = await this._postWriteoff(idx, 'cancel-writeoff')
      if (res.ok) {
        for (const k of ['writeOffStatus', 'writeOffReason', 'writeOffRequestedBy', 'writeOffRequestedAt']) delete item[k]
      } else {
        alert(res.msg)
      }
    },

    async approveWriteoff(idx) {
      const item = this.paymentItems()[idx]
      const me = this.session.displayName || this.session.username || ''
      const res = await this._postWriteoff(idx, 'approve-writeoff', { approve: true })
      if (res.ok) {
        item.writeOffStatus = 'approved'
        item.taxExempt = true
        item.writeOffApprovedBy = me
        item.writeOffApprovedAt = new Date().toISOString()
      } else {
        alert(res.msg)
      }
    },

    async closeCaseAction() {
      if (!confirm('確認完結案件？\n\n完結後此案件將進入「已結案」狀態並開始保固追蹤期。\n此操作無法復原，請確認所有款項與設備資料已填寫完畢。')) return
      clearTimeout(this._autoSaveTimer)
      await this.saveCaseRecord()
      const entry = { at: new Date().toISOString(), user: this.session.displayName || '', from: '已成案', to: '已結案' }
      await this.updateDealTag('已結案', entry)
      if (this.cr.dealTag === '已結案') {
        setTimeout(() => { location.href = 'warranty.html' }, 800)
      }
    },

    async updateDealTag(tag, logEntry) {
      if (!this.selected) return
      try {
        const body = { deal_tag: tag }
        if (logEntry) body.log_entry = logEntry
        const r = await fetch('/api/quotations/' + this.selected.quote_no + '/deal-tag', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(body)
        })
        if (r.ok) {
          this.cr.dealTag = tag
          this.selected.deal_tag = tag
          if (!this.selected.data)             this.selected.data = {}
          if (!this.selected.data.statusLog)   this.selected.data.statusLog = []
          if (logEntry) this.selected.data.statusLog.push(logEntry)
          const idx = this.cases.findIndex(c => c.quote_no === this.selected.quote_no)
          if (idx !== -1) this.cases[idx].deal_tag = tag
          this.filterCases()
        }
      } catch {}
    },

    caseProgressPct() {
      const stages = this.cr.caseRecord?.stages || []
      if (!stages.length) return 0
      return Math.round(stages.filter(s => s.done).length / stages.length * 100)
    },

    addStage() {
      this.ensureCaseRecord()
      this.cr.caseRecord.stages.push({ id: Date.now(), label: '新階段', done: false, doneAt: '', visits: [], startDate:'', dueDate:'', assignedTo:[], dependsOn:[] })
      this.setDirty()
    },
    removeStage(idx)  {
      const stages = this.cr.caseRecord.stages
      const removedId = stages[idx]?.id
      stages.splice(idx, 1)
      stages.forEach(s => { if (s.dependsOn) s.dependsOn = s.dependsOn.filter(id => id !== removedId) })
      this.setDirty()
    },

    toggleStageDetail(id) { this._openStageDetail[id] = !this._openStageDetail[id] },

    stageIsOverdue(st) {
      if (st.done || !st.dueDate) return false
      return st.dueDate < new Date().toISOString().slice(0,10)
    },

    otherStages(stageId) {
      return (this.cr.caseRecord?.stages || []).filter(s => s.id !== stageId)
    },

    addStageAssignee(st, username) {
      if (!username) return
      if (!st.assignedTo) st.assignedTo = []
      if (!st.assignedTo.includes(username)) st.assignedTo.push(username)
      this.setDirty()
    },
    removeStageAssignee(st, username) {
      st.assignedTo = (st.assignedTo || []).filter(u => u !== username)
      this.setDirty()
    },

    wouldCreateCycle(stageId, candidateId) {
      // 若讓 stageId 依賴 candidateId，順著 dependsOn 追下去會不會繞回 stageId 自己
      if (stageId === candidateId) return true
      const byId = Object.fromEntries((this.cr.caseRecord?.stages || []).map(s => [s.id, s]))
      const seen = new Set()
      const dfs = (id) => {
        if (id === stageId) return true
        if (seen.has(id)) return false
        seen.add(id)
        return ((byId[id]?.dependsOn) || []).some(dfs)
      }
      return dfs(candidateId)
    },

    toggleStageDependency(st, candidateId) {
      if (!st.dependsOn) st.dependsOn = []
      const idx = st.dependsOn.indexOf(candidateId)
      if (idx >= 0) { st.dependsOn.splice(idx, 1); this.setDirty(); return }
      if (this.wouldCreateCycle(st.id, candidateId)) {
        alert('這樣設定會讓階段之間互相循環依賴，請重新選擇前置階段')
        return
      }
      st.dependsOn.push(candidateId)
      this.setDirty()
    },

    switchToTimeline() {
      this.stageView = 'timeline'
      this.$nextTick(() => this.renderGantt())
    },

    _ganttTasks() {
      const stages = this.cr.caseRecord?.stages || []
      const today  = new Date().toISOString().slice(0,10)
      const addDays = (dateStr, n) => {
        const d = new Date(dateStr + 'T00:00:00')
        d.setDate(d.getDate() + n)
        return d.toISOString().slice(0,10)
      }
      return stages.map(st => {
        let start = st.startDate || st.dueDate || today
        let end   = st.dueDate   || st.startDate || addDays(start, 1)
        if (start === end) end = addDays(start, 1)
        return {
          id:           String(st.id),
          name:         st.label || '（未命名階段）',
          start, end,
          progress:     st.done ? 100 : 0,
          dependencies: (st.dependsOn || []).map(String).join(','),
          custom_class: st.done ? 'stage-done' : (this.stageIsOverdue(st) ? 'stage-overdue' : ''),
        }
      })
    },

    renderGantt() {
      const el = this.$refs.ganttContainer
      if (!el || typeof Gantt === 'undefined') return
      const tasks = this._ganttTasks()
      el.innerHTML = ''
      if (!tasks.length) return
      this._ganttInstance = new Gantt(el, tasks, {
        view_mode: 'Day',
        on_date_change: (task, start, end) => {
          const st = (this.cr.caseRecord?.stages || []).find(s => String(s.id) === task.id)
          if (!st) return
          const fmt = d => (d instanceof Date ? d : new Date(d)).toISOString().slice(0,10)
          st.startDate = fmt(start)
          st.dueDate   = fmt(end)
          this.setDirty()
        },
      })
    },
    addVisit(stageIdx) {
      const st = this.cr.caseRecord.stages[stageIdx]
      if (!st.visits) st.visits = []
      st.visits.push({ id: Date.now(), visitDate: '', visitPeople: '', note: '' })
      this.setDirty()
    },
    removeVisit(stageIdx, visitIdx) {
      const st = this.cr.caseRecord.stages[stageIdx]
      if (st.visits) st.visits.splice(visitIdx, 1)
      this.setDirty()
    },
    stageTotalVisits(st) { return (st.visits || []).filter(v => v.visitDate || v.note).length },
    stageTotalPeople(st) { return (st.visits || []).reduce((s, v) => s + (+v.visitPeople || 0), 0) },

    dragStart(idx) { this.dragFromIdx = idx },
    dragOver(e, idx) {
      e.preventDefault()
      if (this.dragFromIdx === null || this.dragFromIdx === idx) return
      const stages = this.cr.caseRecord.stages
      const moved  = stages.splice(this.dragFromIdx, 1)[0]
      stages.splice(idx, 0, moved)
      this.dragFromIdx = idx
    },
    dragEnd() { this.dragFromIdx = null; this.setDirty() },

    addMaterial() {
      this.ensureCaseRecord()
      this.cr.caseRecord.materials.push({ id: Date.now(), name: '', model: '', qty: 1, unit: '台', ordered: false, arrived: false, devices: [], note: '' })
      this.setDirty()
    },
    removeMaterial(idx) { this.cr.caseRecord.materials.splice(idx, 1); this.setDirty() },
    addMaterialFromQuote(qi) {
      this.ensureCaseRecord()
      this.cr.caseRecord.materials.push({
        id: Date.now() + Math.random(),
        name: qi.description || '', model: qi.brand || '',
        qty: qi.qty || 1, unit: qi.unit || '台',
        ordered: false, arrived: false, devices: [], note: ''
      })
      this.setDirty()
    },
    quoteItemsForImport() {
      return (this.selected?.data?.items || []).filter(
        i => i.type !== 'header' && (i.description || '').trim()
      )
    },
    openImportModal(mode) {
      this.importMode = mode
      const items = this.quoteItemsForImport()
      if (!items.length) { alert('報價單無可匯入的品項'); return }
      const sel = {}
      items.forEach(function(_, i) { sel[i] = true })
      this.importSelectedItems = sel
      this.showImportModal = true
    },
    toggleImportItem(idx) {
      this.importSelectedItems = Object.assign({}, this.importSelectedItems, { [idx]: !this.importSelectedItems[idx] })
    },
    selectAllImportItems(val) {
      const sel = {}
      this.quoteItemsForImport().forEach(function(_, i) { sel[i] = val })
      this.importSelectedItems = sel
    },
    doImport() {
      const items = this.quoteItemsForImport()
      const selected = items.filter(function(_, i) { return this.importSelectedItems[i] }, this)
      if (!selected.length) { alert('請至少選擇一個品項'); return }
      if (this.importMode === 'materials') {
        selected.forEach(qi => this.addMaterialFromQuote(qi))
      } else {
        this.ensureCaseRecord()
        const base = Date.now()
        selected.forEach((item, ii) => {
          const groupId = 'grp_' + (base + ii).toString(36) + Math.random().toString(36).slice(2, 5)
          const qty = Math.min(Math.round(item.qty) || 1, 50)
          for (let i = 0; i < qty; i++) {
            this.cr.caseRecord.devices.push({
              id: base + Math.random(),
              name: item.description + (qty > 1 ? ` #${i + 1}` : ''),
              sn: '', mac: '', location: '', warrantyStart: '', warrantyMonths: 12, note: '',
              _groupId: groupId, _groupName: item.description, _groupIdx: i + 1, _groupTotal: qty
            })
          }
          this._openDevGroups = Object.assign({}, this._openDevGroups, { [groupId]: true })
        })
        this.setDirty()
      }
      this.showImportModal = false
    },
    onMaterialArrived(mat) {
      if (mat.arrived) {
        const need = mat.qty || 1
        if (!mat.devices) mat.devices = []
        while (mat.devices.length < need) mat.devices.push({ id: Date.now() + Math.random(), sn: '', mac: '' })
        if (mat.devices.length > need) mat.devices.splice(need)
      }
      this.setDirty()
    },
    syncMaterialsToDevices() {
      this.ensureCaseRecord()
      const mats     = (this.cr.caseRecord.materials || []).filter(m => m.arrived)
      const existing = this.cr.caseRecord.devices
      mats.forEach(mat => {
        (mat.devices || []).forEach((md, mi) => {
          let dev = existing.find(d => d._matId === mat.id && d._devIdx === mi)
          if (!dev) {
            const label = mat.name + ((mat.qty || 1) > 1 ? ` #${mi + 1}` : '')
            dev = { id: Date.now() + Math.random(), name: label, sn: md.sn || '', mac: md.mac || '', location: '', warrantyStart: '', warrantyMonths: 12, note: '', _matId: mat.id, _devIdx: mi }
            existing.push(dev)
          } else {
            if (md.sn)  dev.sn  = md.sn
            if (md.mac) dev.mac = md.mac
            if (!dev.name) dev.name = mat.name
          }
        })
      })
      this.activeTab = 'exec'
      this.execSubTab = 'devices'
      this.setDirty()
    },
    autoSyncDevice(mat, mi) {
      const md = mat.devices && mat.devices[mi]
      if (!md) { this.setDirty(); return }
      this.ensureCaseRecord()
      const devs = this.cr.caseRecord.devices
      let dev = devs.find(d => d._matId === mat.id && d._devIdx === mi)
      if (!dev) {
        const label = mat.name + ((mat.qty || 1) > 1 ? ` #${mi + 1}` : '')
        dev = { id: Date.now() + Math.random(), name: label, sn: md.sn || '', mac: md.mac || '', location: '', warrantyStart: '', warrantyMonths: 12, note: '', _matId: mat.id, _devIdx: mi }
        devs.push(dev)
      } else {
        dev.sn  = md.sn  !== undefined ? md.sn  : dev.sn
        dev.mac = md.mac !== undefined ? md.mac : dev.mac
        if (!dev.name) dev.name = mat.name
      }
      this.setDirty()
    },
    addDevice() {
      this.ensureCaseRecord()
      this.cr.caseRecord.devices.push({ id: Date.now(), name: '', sn: '', mac: '', location: '', warrantyStart: '', warrantyMonths: 12, note: '' })
      this.setDirty()
    },
    removeDevice(idx) { this.cr.caseRecord.devices.splice(idx, 1); this.setDirty() },
    removeDeviceByObj(dev) {
      const devs = this.cr.caseRecord.devices
      const idx = devs.findIndex(d => d.id === dev.id)
      if (idx !== -1) { devs.splice(idx, 1); this.setDirty() }
    },
    removeDeviceGroup(groupId) {
      if (!confirm('確定要刪除整個設備群組？')) return
      this.cr.caseRecord.devices = this.cr.caseRecord.devices.filter(d => d._groupId !== groupId)
      this.setDirty()
    },
    toggleDevGroup(groupId) {
      this._openDevGroups = { ...this._openDevGroups, [groupId]: !this._openDevGroups[groupId] }
    },

    // ── 設備拖曳（自訂 ghost + insertion line + timestamp 計時，不依賴 setTimeout）──
    devDragStart(e, dev) {
      this._devDragId = dev.id
      e.dataTransfer.effectAllowed = 'move'
      // 自訂 ghost：克隆 → 定位至畫面外 → setDragImage → 下一 tick 移除
      const card = e.currentTarget
      const ghost = card.cloneNode(true)
      ghost.style.cssText = [
        'position:fixed','left:-9999px','top:0',
        `width:${card.offsetWidth}px`,
        'opacity:.88','pointer-events:none',
        'transform:rotate(1.5deg) scale(1.04)',
        'box-shadow:0 12px 32px rgba(0,0,0,.22)',
        'border-radius:8px','background:#fff',
        'border:1px solid #C7D2FE','z-index:9999'
      ].join(';')
      document.body.appendChild(ghost)
      e.dataTransfer.setDragImage(ghost, e.offsetX + 8, e.offsetY + 8)
      setTimeout(() => ghost.remove(), 0)
      this._devDragOverId = null
      this._devInsertBeforeId = null
      this._devHoverGroupId = null
      this._devGroupTarget = null
      this._devHoverStart = 0
    },

    devDragEnd() {
      this._devDragId = null
      this._devDragOverId = null
      this._devInsertBeforeId = null
      this._devHoverGroupId = null
      this._devGroupTarget = null
      this._devHoverStart = 0
    },

    devDragOver(e, targetId) {
      if (!this._devDragId) return
      const devs = this.cr.caseRecord?.devices || []
      const dragged = devs.find(d => d.id === this._devDragId)
      if (!dragged) return
      if (targetId === 'dev_' + String(dragged.id)) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      // 自動捲動設備 Tab 容器
      const scrollEl = document.querySelector('.cm-detail__body')
      if (scrollEl) {
        const ZONE = 70, SPD = 10, r = scrollEl.getBoundingClientRect()
        if (e.clientY < r.top + ZONE)      scrollEl.scrollTop -= SPD
        else if (e.clientY > r.bottom - ZONE) scrollEl.scrollTop += SPD
      }
      // 進入新目標：重置計時與狀態
      if (targetId !== this._devDragOverId) {
        this._devDragOverId = targetId
        this._devHoverStart = Date.now()
        this._devGroupTarget = null
        this._devInsertBeforeId = null
        this._devHoverGroupId = null
      }
      // 群組標頭 → add-to-group 模式（不顯示插入線）
      if (targetId.startsWith('group_')) {
        this._devHoverGroupId = targetId.slice(6)
        this._devInsertBeforeId = null
        return
      }
      this._devHoverGroupId = null
      // 設備卡片：900ms 後轉合併模式；否則以上/下半決定插入位置
      if (targetId.startsWith('dev_')) {
        if (!this._devGroupTarget && Date.now() - this._devHoverStart > 900)
          this._devGroupTarget = targetId
        if (this._devGroupTarget === targetId) { this._devInsertBeforeId = null; return }
        const rect = e.currentTarget.getBoundingClientRect()
        this._devInsertBeforeId = e.clientY < rect.top + rect.height / 2
          ? targetId
          : this._devNextId(parseInt(targetId.slice(4)))
      } else {
        this._devInsertBeforeId = 'end'
      }
    },

    devDragLeave(e) {
      if (e.relatedTarget && e.currentTarget.contains(e.relatedTarget)) return
      this._devDragOverId = null
      this._devHoverGroupId = null
      this._devGroupTarget = null
      this._devInsertBeforeId = 'end'
      this._devHoverStart = 0
    },

    // 取得 devId 在顯示順序中的「下一張」device（跳過自身），回傳 'dev_X' 或 'end'
    _devNextId(devId) {
      const list = this.deviceDisplayList()
      let found = false
      for (const entry of list) {
        if (entry.type === 'group') {
          for (const d of entry.devices) {
            if (found && d.id !== this._devDragId) return 'dev_' + d.id
            if (d.id === devId) found = true
          }
        } else if (entry.type === 'device') {
          if (found && entry.dev.id !== this._devDragId) return 'dev_' + entry.dev.id
          if (entry.dev.id === devId) found = true
        }
      }
      return 'end'
    },

    devDropOnDevice(e, targetDev) {
      e.preventDefault()
      const devs = this.cr.caseRecord.devices
      const dragged = devs.find(d => d.id === this._devDragId)
      if (!dragged || dragged.id === targetDev.id) { this.devDragEnd(); return }
      if (this._devGroupTarget === 'dev_' + targetDev.id) {
        // ── 合併成群組 ──
        const oldGid = dragged._groupId || ''
        if (targetDev._groupId) {
          dragged._groupId = targetDev._groupId; dragged._groupName = targetDev._groupName
          if (oldGid && oldGid !== targetDev._groupId) this._devReindex(devs, oldGid)
          this._devReindex(devs, targetDev._groupId)
        } else {
          const gid = 'grp_' + Date.now().toString(36)
          const gName = (targetDev.name || dragged.name || '設備群組').slice(0, 30)
          if (oldGid) { dragged._groupId = ''; this._devReindex(devs, oldGid) }
          targetDev._groupId = gid; targetDev._groupName = gName
          dragged._groupId   = gid; dragged._groupName   = gName
          this._devReindex(devs, gid)
          this._openDevGroups = { ...this._openDevGroups, [gid]: true }
        }
      } else {
        // ── 排序：依 _devInsertBeforeId 插入 ──
        const insertId = this._devInsertBeforeId
        const fromIdx = devs.indexOf(dragged)
        devs.splice(fromIdx, 1)
        if (!insertId || insertId === 'end') {
          devs.push(dragged)
        } else {
          const tid = parseInt(insertId.slice(4))
          const toIdx = devs.findIndex(d => d.id === tid)
          if (toIdx === -1) devs.push(dragged); else devs.splice(toIdx, 0, dragged)
        }
      }
      this.cr.caseRecord.devices = [...devs]
      this.devDragEnd()
      this.setDirty()
    },

    devDropOnGroup(e, groupId, groupName) {
      e.preventDefault()
      const devs = this.cr.caseRecord.devices
      const dragged = devs.find(d => d.id === this._devDragId)
      if (!dragged || dragged._groupId === groupId) { this.devDragEnd(); return }
      const oldGid = dragged._groupId || ''
      dragged._groupId = groupId; dragged._groupName = groupName
      if (oldGid) this._devReindex(devs, oldGid)
      this._devReindex(devs, groupId)
      this.cr.caseRecord.devices = [...devs]
      this.devDragEnd()
      this.setDirty()
    },

    devDropAtEnd(e) {
      e.preventDefault()
      const devs = this.cr.caseRecord.devices
      const dragged = devs.find(d => d.id === this._devDragId)
      if (!dragged) { this.devDragEnd(); return }
      const fromIdx = devs.indexOf(dragged)
      devs.splice(fromIdx, 1)
      devs.push(dragged)
      this.cr.caseRecord.devices = [...devs]
      this.devDragEnd()
      this.setDirty()
    },
    _devReindex(devs, groupId) {
      const members = devs.filter(d => d._groupId === groupId)
      if (members.length <= 1) {
        if (members[0]) { members[0]._groupId = ''; members[0]._groupName = ''; members[0]._groupIdx = 0; members[0]._groupTotal = 0 }
      } else {
        members.forEach((d, i) => { d._groupIdx = i + 1; d._groupTotal = members.length })
      }
    },
    devUngroupDevice(dev) {
      if (!dev._groupId) return
      const groupId = dev._groupId
      const devs = this.cr.caseRecord.devices
      dev._groupId = ''; dev._groupName = ''; dev._groupIdx = 0; dev._groupTotal = 0
      this._devReindex(devs, groupId)
      this.cr.caseRecord.devices = [...devs]
      this.setDirty()
    },

    deviceDisplayList() {
      const devices = this.cr.caseRecord?.devices || []
      const seenGroups = {}
      const groupOrder = []
      const groups = {}
      const ungrouped = []
      devices.forEach((dev, gi) => {
        if (dev._groupId) {
          if (!seenGroups[dev._groupId]) {
            seenGroups[dev._groupId] = true
            groupOrder.push(dev._groupId)
            groups[dev._groupId] = {
              id: 'group_' + dev._groupId,
              type: 'group',
              groupId: dev._groupId,
              groupName: dev._groupName || dev.name,
              groupTotal: dev._groupTotal || 0,
              devices: []
            }
          }
          groups[dev._groupId].devices.push(dev)
        } else {
          ungrouped.push({ id: 'dev_' + dev.id, type: 'device', dev, idx: gi })
        }
      })
      const result = []
      groupOrder.forEach(gid => result.push(groups[gid]))
      ungrouped.forEach(u => result.push(u))
      return result
    },
    syncAllWarranty() {
      if (!this._syncWarrantyDate) return
      const devs = this.cr.caseRecord?.devices || []
      devs.forEach(d => {
        d.warrantyStart   = this._syncWarrantyDate
        d.warrantyMonths  = this._syncWarrantyMonths
      })
      this.setDirty()
    },

    warrantyExpiry(start, months) {
      if (!start || !months) return ''
      const d = new Date(start)
      d.setMonth(d.getMonth() + (+months))
      return d.toLocaleDateString('zh-TW')
    },
    warrantyStatus(start, months) {
      if (!start || !months) return 'active'
      const expiry = new Date(start)
      expiry.setMonth(expiry.getMonth() + (+months))
      const daysLeft = Math.round((expiry - new Date()) / 86400000)
      if (daysLeft < 0)  return 'expired'
      if (daysLeft < 90) return 'expiring'
      return 'active'
    },
    warrantyStatusLabel(start, months) {
      const s = this.warrantyStatus(start, months)
      if (s === 'expired')  return '已過保'
      if (s === 'expiring') return '即將到期'
      return '保固中'
    },

    // ── 承攬商派發 methods ──────────────────────────────────────────────────────

    // ── 動態 Tab ──────────────────────────────────────────────────────────────

    async loadCaseUpdates(quoteNo) {
      if (!quoteNo) return
      this.updatesLoading = true
      this.caseUpdates = []
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/updates`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.caseUpdates = await r.json()
      } catch {}
      this.updatesLoading = false
    },

    async postComment() {
      const content = this.newComment.trim()
      if (!content || this.postingComment) return
      this.postingComment = true
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(this.selected.quote_no)}/updates`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token, 'Content-Type': 'application/json' },
          body: JSON.stringify({ content })
        })
        if (r.ok) {
          const item = await r.json()
          this.caseUpdates.unshift(item)
          this.newComment = ''
        }
      } catch {}
      this.postingComment = false
    },

    async deleteUpdate(uid) {
      if (!confirm('確定刪除這則更新？')) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(this.selected.quote_no)}/updates/${uid}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.caseUpdates = this.caseUpdates.filter(x => x.id !== uid)
      } catch {}
    },

    fmtFeedTime(ts) {
      if (!ts) return ''
      try {
        const d = new Date(ts.replace(' ', 'T'))
        const now = new Date()
        const diff = Math.floor((now - d) / 1000)
        if (diff < 60) return '剛剛'
        if (diff < 3600) return Math.floor(diff / 60) + ' 分鐘前'
        if (diff < 86400) return Math.floor(diff / 3600) + ' 小時前'
        if (diff < 86400 * 3) return Math.floor(diff / 86400) + ' 天前'
        return ts.slice(0, 10)
      } catch { return ts.slice(0, 10) }
    },

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

    async loadDispatches(quoteNo) {
      if (!quoteNo) return
      this.dispatchesLoading = true
      this.dispatches = []
      try {
        const r = await fetch(`/api/contractor-dispatches?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.dispatches = await r.json()
      } catch {}
      this.dispatchesLoading = false
    },

    dispatchTotalCost() {
      // 承攬商含稅合計 + 外包名單人員金額（不計稅），與精算頁面「承攬商派發成本」算法一致
      return this.dispatches
        .filter(d => d.status !== 'cancelled')
        .reduce((s, d) => s + (d.grandTotal || 0), 0)
    },

    _blankDispatchForm() {
      const today = new Date().toISOString().slice(0, 10)
      return {
        quote_no: this.selected?.quote_no || '',
        vendor_id: '',
        dispatch_date: today,
        scope: '',
        notes: '',
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
        status: d.status || 'draft',
        tax_rate: d.taxRate !== undefined ? d.taxRate : 0.05,
        items: JSON.parse(JSON.stringify(d.items || [])),
        personnel: JSON.parse(JSON.stringify(d.personnel || []))
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

    removeDispatchPersonnel(idx) {
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

    removeDispatchItem(idx) {
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
        this.dispatchMsg = '請至少選擇承攬商或外包名單人員其中一項'; return
      }
      this.dispatchSaving = true; this.dispatchMsg = ''
      const body = {
        quote_no: this.dispatchForm.quote_no,
        vendor_id: this.dispatchForm.vendor_id ? Number(this.dispatchForm.vendor_id) : null,
        dispatch_date: this.dispatchForm.dispatch_date || '',
        scope: this.dispatchForm.scope || '',
        notes: this.dispatchForm.notes || '',
        status: this.dispatchForm.status || 'draft',
        tax_rate: parseFloat(this.dispatchForm.tax_rate) || 0,
        items_json: this.dispatchForm.items || [],
        personnel_json: (this.dispatchForm.personnel || []).map(p => ({
          id: p.id, name: p.name, amount: +p.amount || 0, note: p.note || ''
        }))
      }
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

    async deleteDispatch(d) {
      if (!confirm(`確定刪除派發給「${this._dispatchLabel(d)}」的紀錄？`)) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) await this.loadDispatches(this.selected?.quote_no)
        else alert((await r.json()).detail || '刪除失敗')
      } catch {}
    },

    async importDispatchToQuote(d) {
      if (!d.items || d.items.length === 0) { alert('此派發紀錄沒有報價品項'); return }
      if (!confirm(`確定將「${this._dispatchLabel(d)}」共 ${d.items.length} 筆品項匯入至報價單？\n（報價單必須處於草稿狀態）`)) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/import-to-quote`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        const data = await r.json()
        if (r.ok) alert(`✓ 已成功匯入 ${data.imported} 筆品項至報價單`)
        else alert(data.detail || '匯入失敗')
      } catch(e) { alert('網路錯誤：' + e.message) }
    },

    // ── 出貨單 ────────────────────────────────────────────────────────────────

    async loadShippingNotes(quoteNo) {
      if (!quoteNo) return
      this.shippingNotesLoading = true
      this.shippingNotes = []
      try {
        const r = await fetch(`/api/shipping-notes?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.shippingNotes = await r.json()
      } catch {}
      this.shippingNotesLoading = false
    },

    _blankShippingForm() {
      const today = new Date().toISOString().slice(0, 10)
      return {
        quote_no: this.selected?.quote_no || '',
        ship_date: today,
        recipient: '',
        delivery_address: '',
        notes: '',
        items: []
      }
    },

    async _loadShippingContactOptions() {
      this.shippingContactOptions = []
      try {
        let customer = null
        const customerId = this.selected?.data?.customerId
        if (customerId) {
          const r = await fetch(`/api/customers/${customerId}`, {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (r.ok) customer = await r.json()
        } else {
          const targetName = (this.selected?.customer_name || '').trim()
          if (targetName) {
            const r = await fetch('/api/customers', {
              headers: { Authorization: 'Bearer ' + this.session.token }
            })
            if (r.ok) {
              const all = await r.json()
              customer = all.find(c => c.name && c.name.trim() === targetName) || null
            }
          }
        }
        this.shippingContactOptions = (customer?.contacts || [])
          .filter(ct => ct.name || ct.phone || ct.email)
          .map(ct => ({ name: ct.name || '', _display: [ct.name, ct.title].filter(Boolean).join(' · ') }))
      } catch {}
    },

    applyShippingContact(ct) {
      this.shippingForm.recipient = ct.name
      this.showShippingContactPicker = false
    },

    openNewShippingNote() {
      this.editShippingNoteNo = null
      this.shippingForm = this._blankShippingForm()
      this.shippingMsg = ''
      this.showShippingContactPicker = false
      this._loadShippingContactOptions()
      this.showShippingModal = true
    },

    async openEditShippingNote(n) {
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert('讀取出貨單失敗'); return }
        const d = await r.json()
        this.editShippingNoteNo = d.noteNo
        this.shippingForm = {
          quote_no: d.quoteNo,
          ship_date: d.shipDate || '',
          recipient: d.recipient || '',
          delivery_address: d.deliveryAddress || '',
          notes: d.notes || '',
          items: JSON.parse(JSON.stringify(d.items || []))
        }
        this.shippingMsg = ''
        this.showShippingContactPicker = false
        this._loadShippingContactOptions()
        this.showShippingModal = true
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    importItemsFromQuote() {
      const srcItems = this.selected?.data?.items || []
      if (srcItems.length === 0) { alert('此案件的報價單沒有品項可匯入'); return }
      for (const it of srcItems) {
        if (it.type === 'header') {
          this.shippingForm.items.push({
            id: Date.now() + Math.random(), type: 'header', description: it.description || ''
          })
        } else {
          this.shippingForm.items.push({
            id: Date.now() + Math.random(),
            description: it.description || '', brand: it.brand || '',
            qty: it.qty || 1, unit: it.unit || '台', notes: ''
          })
        }
      }
    },

    addShippingItem() {
      this.shippingForm.items.push({
        id: Date.now() + Math.random(), description: '', brand: '', qty: 1, unit: '台', notes: ''
      })
    },

    addShippingHeader() {
      this.shippingForm.items.push({
        id: Date.now() + Math.random(), type: 'header', description: ''
      })
    },

    removeShippingItem(idx) {
      this.shippingForm.items.splice(idx, 1)
    },

    async saveShippingNote() {
      this.shippingSaving = true; this.shippingMsg = ''
      const body = {
        quote_no: this.shippingForm.quote_no,
        ship_date: this.shippingForm.ship_date || '',
        recipient: this.shippingForm.recipient || '',
        delivery_address: this.shippingForm.delivery_address || '',
        notes: this.shippingForm.notes || '',
        items: this.shippingForm.items || []
      }
      const method = this.editShippingNoteNo ? 'PUT' : 'POST'
      const url    = this.editShippingNoteNo
        ? `/api/shipping-notes/${this.editShippingNoteNo}`
        : '/api/shipping-notes'
      try {
        const r = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(body)
        })
        if (!r.ok) { this.shippingMsg = (await r.json()).detail || '儲存失敗'; this.shippingSaving = false; return }
        this.showShippingModal = false
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { this.shippingMsg = '網路錯誤：' + e.message }
      this.shippingSaving = false
    },

    async deleteShippingNote(n) {
      if (!confirm(`確定刪除出貨單「${n.noteNo}」？`)) return
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) await this.loadShippingNotes(this.selected?.quote_no)
        else alert((await r.json()).detail || '刪除失敗')
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async submitShippingNote(n) {
      if (!confirm(`確定送出出貨單「${n.noteNo}」進行簽核？`)) return
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/submit`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json()).detail || '送出失敗'); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async approveShippingNote(n) {
      if (!confirm(`確定簽核出貨單「${n.noteNo}」？`)) return
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({})
        })
        if (!r.ok) { alert((await r.json()).detail || '簽核失敗'); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async rejectShippingNote(n) {
      const note = prompt(`退回出貨單「${n.noteNo}」，可填寫退回原因（選填）：`)
      if (note === null) return
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/reject`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note })
        })
        if (!r.ok) { alert((await r.json()).detail || '退回失敗'); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async toggleSigned(n, action) {
      const msg = action === 'sign'
        ? `確定標記出貨單「${n.noteNo}」已回簽？`
        : `確定取消出貨單「${n.noteNo}」的已回簽標記？`
      if (!confirm(msg)) return
      const note = action === 'sign' ? (prompt('備註（選填，例如簽收人姓名或方式）：') || '') : ''
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/signed-toggle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ action, note })
        })
        if (!r.ok) { alert((await r.json()).detail || '操作失敗'); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async downloadShippingPdf(n) {
      try {
        // 記錄匯出（fire-and-forget，不阻塞 PDF 下載）
        fetch(`/api/shipping-notes/${n.noteNo}/export?mode=external`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        }).catch(() => {})

        const r = await fetch(`/api/shipping-notes/${n.noteNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗'); return }
        const blob = await r.blob()
        const url  = URL.createObjectURL(blob)
        const a    = document.createElement('a')
        a.href     = url
        a.download = `${n.noteNo}.pdf`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      } catch (e) { alert('下載失敗：' + e.message) }
    },

    async previewShippingPdf(n) {
      this.shippingPreviewFetching = true
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗'); this.shippingPreviewFetching = false; return }
        const blob = await r.blob()
        this.shippingPreviewBlobUrl = URL.createObjectURL(blob)
        this.shippingPreviewNote = n
        this.shippingPreviewModal = true
      } catch (e) { alert('預覽失敗：' + e.message) }
      this.shippingPreviewFetching = false
    },

    closeShippingPreview() {
      if (this.shippingPreviewBlobUrl) URL.revokeObjectURL(this.shippingPreviewBlobUrl)
      this.shippingPreviewBlobUrl = ''
      this.shippingPreviewModal = false
      this.shippingPreviewNote = null
    },

    _shippingStatusLabel(s) {
      return { '草稿': '草稿', '待審核': '待審核', '簽核中': '簽核中', '已核准': '已核准' }[s] || s
    },

    _shippingStatusClass(s) {
      return { '草稿': 'badge--draft', '待審核': 'badge--pending', '簽核中': 'badge--signing', '已核准': 'badge--approved' }[s] || ''
    },

    // ── 今日相關任務 回報 helpers ──────────────────────────────────────────────
    _caseMyComp(t) {
      return (t.completions || []).find(c => c.username === this.session.username)
    },

    _caseTaskStartEdit(t) {
      const comp = this._caseMyComp(t)
      this.caseTaskEditing = { taskId: t.id, text: comp?.report || '' }
    },

    async _caseTaskSubmitReport(taskId) {
      const text = this.caseTaskEditing.text.trim()
      if (!text) { alert('請填寫回報內容'); return }
      this.caseTaskEditSubmitting = true
      try {
        const today = new Date().toISOString().slice(0, 10)
        const r = await fetch(`/api/daily-tasks/${taskId}/complete`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ completed: true, report: text, occurrence_date: today })
        })
        if (!r.ok) { const e = await r.json().catch(() => ({})); alert(e.detail || '送出失敗'); return }
        this.caseTaskEditing = { taskId: null, text: '' }
        await this._loadCaseTasks(this.selected?.quote_no)
      } catch(e) { alert('網路錯誤：' + e.message) }
      this.caseTaskEditSubmitting = false
    },

    async _caseTaskToggleLog(taskId) {
      this.caseTaskLogsOpen = { ...this.caseTaskLogsOpen, [taskId]: !this.caseTaskLogsOpen[taskId] }
      if (this.caseTaskLogsOpen[taskId] && !this.caseTaskEditLogs[taskId]) {
        try {
          const r = await fetch(`/api/daily-tasks/${taskId}/edit-log`, {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (r.ok) {
            const d = await r.json()
            this.caseTaskEditLogs = { ...this.caseTaskEditLogs, [taskId]: d.items || [] }
          } else {
            this.caseTaskEditLogs = { ...this.caseTaskEditLogs, [taskId]: [] }
          }
        } catch {
          this.caseTaskEditLogs = { ...this.caseTaskEditLogs, [taskId]: [] }
        }
      }
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

    _dispatchStatusLabel(s) {
      return { draft: '草稿', sent: '已送出', confirmed: '已確認', pending_acceptance: '待驗收', accepted: '已驗收', completed: '完工', cancelled: '已取消' }[s] || s
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
      if (!confirm(`確定驗收「${this._dispatchLabel(d)}」的工程？\n驗收後將記錄您的姓名與時間。`)) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/accept`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ action: 'accepted' })
        })
        if (!r.ok) { alert((await r.json()).detail || '操作失敗'); return }
        await this.loadDispatches(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    logout() {
      fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + (this.session.token || '') } }).catch(() => {})
      localStorage.removeItem('motrix_session'); location.href = 'login.html'
    },
  }
}
