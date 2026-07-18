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
    execSubTab: 'progress',
    cr: { dealTag: '已成案', caseRecord: null },
    dirty: false,
    saving: false,
    saveStatus: '',
    saveMsg: '',
    _autoSaveTimer: null,
    dragFromIdx: null,
    showImportPanel: false,
    showLog: false,
    _allDonePrompted: false,
    _syncWarrantyDate: '',
    _syncWarrantyMonths: 12,
    linkedProjectId: null,
    showCreateProjectModal: false,
    newProjectName: '',
    creatingProject: false,
    selectableUsers: [],

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
      if (this.listTab !== 'all') list = list.filter(c => c.deal_tag === this.listTab)
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
        this.showImportPanel = false
        this._allDonePrompted = false
        this._syncWarrantyDate = ''
        this._syncWarrantyMonths = 12
        this.linkedProjectId = null
        // 背景查詢是否已有關聯專案
        this._checkLinkedProject(quoteNo)
      } catch {}
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
    importAllFromQuote() {
      const items = this.selected?.data?.items || []
      items.forEach(qi => this.addMaterialFromQuote(qi))
      this.showImportPanel = false
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

    logout() {
      fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + (this.session.token || '') } }).catch(() => {})
      localStorage.removeItem('motrix_session'); location.href = 'login.html'
    },
  }
}
