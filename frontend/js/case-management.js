function app() {
  return {
      isMobileView: window.innerWidth <= 767,
    session: {},
    loading: true,
    cases: [],
    filteredCases: [],
    listTab: 'all',
    search: '',
    selected: null,
    activeTab: 'biz',
    cr: { dealTag: '已成案', caseRecord: null },
    dirty: false,
    saving: false,
    saveStatus: '',
    saveMsg: '',
    _autoSaveTimer: null,
    dragFromIdx: null,
    showImportModal: false,
    importMode: 'materials',
    importSelectedItems: {},
    showLog: false,
    _allDonePrompted: false,
    _syncWarrantyDate: '',
    _syncWarrantyMonths: 12,
    _openDevGroups: {},
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

    // ── 承攬商派發 ──
    vendors: [],
    dispatches: [],
    dispatchesLoading: false,
    showDispatchModal: false,
    editDispatchId: null,
    dispatchSaving: false,
    dispatchForm: {},
    dispatchMsg: '',

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
        this.showLog = false
        this.showImportModal = false
        this._allDonePrompted = false
        this._syncWarrantyDate = ''
        this._syncWarrantyMonths = 12
        this._openDevGroups = {}
        this.linkedProjectId = null
        this.caseTasks = []
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
            { id: 1, label: '訂單確認', done: false, doneAt: '', visits: [] },
            { id: 2, label: '叫料出貨', done: false, doneAt: '', visits: [] },
            { id: 3, label: '施工安裝', done: false, doneAt: '', visits: [] },
            { id: 4, label: '客戶驗收', done: false, doneAt: '', visits: [] },
            { id: 5, label: '尾款結清', done: false, doneAt: '', visits: [] },
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

    itemAmountPretax(idx) {
      const items  = this.paymentItems()
      const total  = this.totalWithTax()
      const pretax = this.totalPretax()
      if (items[idx]?.amount != null && total > 0)
        return Math.round(items[idx].amount * pretax / total)
      return Math.round(pretax * (+items[idx]?.pct || 0) / 100)
    },

    itemAmountTax(idx) { return this.itemAmountWithTax(idx) - this.itemAmountPretax(idx) },

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
      return this.paymentItems().reduce((s, p, i) => p.received ? s + this.itemAmountWithTax(i) : s, 0)
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
        const base = p.actualAmount != null ? +p.actualAmount : this.itemAmountWithTax(i)
        return s + base - (+p.feeAmount || 0)
      }, 0)
    },
    outstandingTotal() { return Math.max(0, this.totalWithTax() - this.receivedTotal()) },
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
      this.cr.caseRecord.stages.push({ id: Date.now(), label: '新階段', done: false, doneAt: '', visits: [] })
      this.setDirty()
    },
    removeStage(idx)  { this.cr.caseRecord.stages.splice(idx, 1); this.setDirty() },
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
      this.activeTab = 'devices'
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

    async loadVendors() {
      try {
        const r = await fetch('/api/vendor-contractors/selectable', {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.vendors = await r.json()
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
      return this.dispatches.reduce((s, d) => s + (d.totalAmount || 0), 0)
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
        items: []
      }
    },

    openNewDispatch() {
      this.editDispatchId = null
      this.dispatchForm = this._blankDispatchForm()
      this.dispatchMsg = ''
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
        items: JSON.parse(JSON.stringify(d.items || []))
      }
      this.dispatchMsg = ''
      this.showDispatchModal = true
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
      if (!this.dispatchForm.vendor_id) { this.dispatchMsg = '請選擇承攬商'; return }
      this.dispatchSaving = true; this.dispatchMsg = ''
      const body = {
        quote_no: this.dispatchForm.quote_no,
        vendor_id: Number(this.dispatchForm.vendor_id),
        dispatch_date: this.dispatchForm.dispatch_date || '',
        scope: this.dispatchForm.scope || '',
        notes: this.dispatchForm.notes || '',
        status: this.dispatchForm.status || 'draft',
        tax_rate: parseFloat(this.dispatchForm.tax_rate) || 0,
        items_json: this.dispatchForm.items || []
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
      if (!confirm(`確定刪除派發給「${d.vendorName}」的紀錄？`)) return
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
      if (!confirm(`確定將「${d.vendorName}」共 ${d.items.length} 筆品項匯入至報價單？\n（報價單必須處於草稿狀態）`)) return
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

    _dispatchStatusLabel(s) {
      return { draft: '草稿', sent: '已送出', confirmed: '已確認', pending_acceptance: '待驗收', accepted: '已驗收', completed: '完工', cancelled: '已取消' }[s] || s
    },

    _dispatchStatusClass(s) {
      return { draft: 'badge--draft', sent: 'badge--pending', confirmed: 'badge--approved', pending_acceptance: 'badge--signing', accepted: 'badge--running', completed: 'badge--settled', cancelled: 'badge--danger' }[s] || ''
    },

    async markPendingAcceptance(d) {
      if (!confirm(`確定將「${d.vendorName}」標記為待驗收？`)) return
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
      if (!confirm(`確定驗收「${d.vendorName}」的工程？\n驗收後將記錄您的姓名與時間。`)) return
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
