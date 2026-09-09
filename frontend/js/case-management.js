// 依字串 hash 對應固定色盤，跟 daily-tasks.html 的 _avatarColor 用同一組色碼與演算法，
// 讓同一位負責人在甘特圖／每日工作事項月曆／看板三處的顏色一致。
const _GANTT_COLORS = ['#2563EB','#7C3AED','#DB2777','#D97706','#16A34A','#0891B2','#DC2626','#9333EA']
function _avatarColor(u) {
  let h = 0
  for (let i = 0; i < u.length; i++) h = (h * 31 + u.charCodeAt(i)) | 0
  return _GANTT_COLORS[Math.abs(h) % _GANTT_COLORS.length]
}

function app() {
  return {
      isMobileView: window.innerWidth <= 767,
    session: {},
    loading: true,
    cases: [],
    filteredCases: [],
    caseSortPref: { sortMode: '', sortDir: 'desc', customOrder: [] },
    _caseSortable: null,
    listTab: 'all',
    caseViewMode: 'list',
    stageBoardItems: [],
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
    selectableUsers: [],

    // ── 代辦事項（2026-08-26 專案管理併入案件管理）──
    caseActionItems: [],
    caseActionItemsLoading: false,
    newActionItemText: '',
    addingActionItem: false,

    // ── 專案資訊（成員分配）──
    assignedUserIds: [],
    assignedUsersSaving: false,
    exportingProjectReport: false,

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
    newCommentImportant: false,
    newCommentPhotos: [],
    newCommentHours: '',
    newCommentContactType: '',
    newCommentContactTypeCustom: '',
    newCommentLogDate: new Date().toISOString().slice(0, 10),
    newCommentUserId: '',   // 空字串＝記錄人＝目前登入者，見 postWorkLogEntry()
    postingComment: false,
    _ptCache: {},
    feedCalMode:    false,
    feedCalYear:    new Date().getFullYear(),
    feedCalMonth:   new Date().getMonth() + 1,
    feedCalSelDate: '',

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
    snSortPref: { sortMode: '', sortDir: 'desc', customOrder: [] },
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
    _partsOptions: null,
    serialPicker: { show: false, itemIdx: null, partNo: '', options: [], selected: [], loading: false, error: '' },

    // ── 案件財務總覽（應收應付，2026-09-09）──
    // 後端一支 /finance-summary 端點算完，不在前端把 contractorVouchers /
    // paymentItems() 等既有陣列再加總一次——同一個案件的「還有多少沒收/沒付」
    // 若在前後端各算一份，遲早會因為其中一邊漏改（例如 taxExempt 沖銷折算）
    // 而對不起來，見 helpers/quotations.py::summarize_payment_items() 說明。
    financeSummary: null,
    financeSummaryLoading: false,
    finShowRecvDetail: false,
    finShowPayDetail: false,
    finShowExtraDetail: false,

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

    // ── 開票申請憑據 ──
    invoiceVouchers: [],
    invoiceVouchersLoading: false,
    ivSortPref: { sortMode: '', sortDir: 'desc', customOrder: [] },
    ivPreviewModal: false,
    ivPreviewBlobUrl: '',
    ivPreviewVoucher: null,
    ivPreviewFetching: false,
    ivCreateModal: false,
    ivRemaining: null,
    ivRemainingLoading: false,
    ivMode: 'amount',
    ivAmountInput: 0,
    ivItemSelections: {},
    ivSubmitting: false,

    // ── 請款單 ──（建立/編輯/簽核/PDF 已整頁化，見 payment-request-form.html，
    // 這裡只保留清單載入與排序）
    paymentRequests: [],
    paymentRequestsLoading: false,
    prListSortPref: { sortMode: '', sortDir: 'desc', customOrder: [] },
    _subSortables: {},

    canSeeFinancial() {
      const m = this.session.modules || []
      return m.includes('financial_view') || ['superadmin','admin','sales'].includes(this.session.role)
    },

    caseSettlement()    { return this.selected?.data?.settlement || null },
    caseSettleStatus()  { return this.caseSettlement()?.status || '' },
    caseSettleSummary() { return this.caseSettlement()?.summary || {} },
    caseSettleItems()   { return this.caseSettlement()?.items   || [] },
    caseSettleExtras()  { return this.caseSettlement()?.extraItems || [] },
    caseSettleMemo()    { return this.caseSettlement()?.memo || '' },
    caseSettleFmt(n)    { return 'NT$ ' + (Math.round(n || 0)).toLocaleString() },

    // ── 應收應付總覽（2026-09-09）──────────────────────────────────────────
    async loadFinanceSummary(quoteNo) {
      if (!quoteNo) return
      this.financeSummaryLoading = true
      this.financeSummary = null
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/finance-summary`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.financeSummary = await r.json()
      } catch {}
      this.financeSummaryLoading = false
    },
    finReceivable()  { return this.financeSummary?.receivable || null },
    finPayable()     { return this.financeSummary?.payable || null },
    finRelatedDocs() { return this.financeSummary?.relatedDocuments || { invoiceVouchers: [], paymentRequests: [] } },
    finExtrasTotal() { return this.financeSummary?.settlementExtras?.total || 0 },
    // 精算額外支出逐筆（含 2026-09-09 新增的單號）：資料源就是精算頁「二、額外
    // 支出」那張表，精算不論草稿或已完結都會列出來——使用者的作業順序是支出
    // 當下就先填、案件結束才做精算完結，只列已完結的等於當月看不到剛花的錢
    finExtraItems()  { return this.financeSummary?.settlementExtras?.items || [] },
    // 未收款項清單：只給總覽的展開明細用，已收的那些在「案件資訊」Tab 的款項
    // 明細本來就看得到，這裡重複列一次只會讓畫面變長
    finOutstandingItems() { return (this.finReceivable()?.items || []).filter(it => !it.received) },
    finUnpaidVouchers()   { return (this.finPayable()?.vouchers || []).filter(v => v.status === '已核准' && !v.isPaid) },

    async init() {
      window.addEventListener('resize', () => { this.isMobileView = window.innerWidth <= 767 })
      const s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      if (!s.token) { location.href = 'login.html'; return }
      this.session = s
      try {
        const r = await fetch('/api/auth/me', { headers: { Authorization: 'Bearer ' + s.token } })
        if (!r.ok) { location.href = 'login.html'; return }
        const me = await r.json()
        this.session.displayName = me.displayName
        this.session.id = me.userId
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
      this.caseSortPref = await loadListPref(s.token, 'case_list')
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
      this.loadStageBoardSummary()
    },

    // 視覺化改版（2026-08-23）：摘要總覽卡片的「已逾期階段」數字需要跨案件的
    // 階段到期資訊，這份資料 case-stage-board.html 已經在用（stage_board() 回傳
    // 的 items 就含 dueDate/done/overdue），這裡直接重用同一支既有 API，不用
    // 新增後端端點。只在案件管理頁載入時抓一次，不影響既有的 cases/filterCases。
    async loadStageBoardSummary() {
      try {
        const r = await fetch('/api/quotations/stage-board', {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.stageBoardItems = (await r.json()).items || []
      } catch {}
    },

    summaryTotal()   { return this.cases.length },
    summaryActive()  { return this.cases.filter(c => c.deal_tag === '已成案').length },
    summaryOverdue() { return this.stageBoardItems.filter(i => i.overdue).length },
    summarySettling(){ return this.cases.filter(c => c.settle_status === 'draft').length },

    // 看板檢視分欄：跟清單分頁的定義完全一致，只是同時攤開而非切換——待精算優先
    // （呼應既有「待精算」分頁的定義，settle_status 是跟 deal_tag 獨立的另一個軸，
    // 一個案件可能同時是「已成案」又「待精算」，看板需要互斥分欄，所以待精算優先
    // 分類，其餘才依 deal_tag 分成進行中/已結案）。
    boardColumns() {
      const q = this.search.trim().toLowerCase()
      let pool = !q ? this.cases : this.cases.filter(c =>
        (c.quote_no || '').toLowerCase().includes(q) ||
        (c.customer_name || '').toLowerCase().includes(q) ||
        (c.project_name  || '').toLowerCase().includes(q)
      )
      if (this.unreadOnly) pool = pool.filter(c => this.isUnread(c))
      const settling = [], active = [], closed = []
      for (const c of pool) {
        if (c.settle_status === 'draft') settling.push(c)
        else if (c.deal_tag === '已結案') closed.push(c)
        else active.push(c)
      }
      return [
        { key: '待精算', label: '待精算', dot: '#FCD34D', items: settling },
        { key: '進行中', label: '進行中', dot: '#4ADE80', items: active },
        { key: '已結案', label: '已結案', dot: '#C4B5FD', items: closed },
      ]
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
      this.filteredCases = applyListSort(list, this.caseSortPref, {
        quote_date:    c => c.quote_date || c.created_at || '',
        total:         c => c.total || 0,
        customer_name: c => c.customer_name || '',
      }, c => c.quote_no)
      this.$nextTick(() => this.initCaseSortable())
    },

    async setCaseSortMode(mode) {
      this.caseSortPref.sortMode = mode
      this.filterCases()
      await saveListPref(this.session.token, 'case_list', this.caseSortPref)
    },
    async toggleCaseSortDir() {
      this.caseSortPref.sortDir = this.caseSortPref.sortDir === 'asc' ? 'desc' : 'asc'
      this.filterCases()
      await saveListPref(this.session.token, 'case_list', this.caseSortPref)
    },
    initCaseSortable() {
      const body = this.$refs.caseListBody
      if (!body || typeof Sortable === 'undefined') return
      if (this._caseSortable) { this._caseSortable.destroy(); this._caseSortable = null }
      if (this.caseSortPref.sortMode !== 'custom') return
      this._caseSortable = Sortable.create(body, {
        animation: 150,
        handle: '.drag-handle',
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        onEnd: async () => {
          const visibleIds = [...body.querySelectorAll('.cm-card[data-quote-no]')].map(el => el.dataset.quoteNo)
          const rest = this.caseSortPref.customOrder.filter(id => !visibleIds.includes(id))
          this.caseSortPref.customOrder = [...visibleIds, ...rest]
          await saveListPref(this.session.token, 'case_list', this.caseSortPref)
        }
      })
    },

    // ── 案件內單據子清單排序（出貨單/開票憑據/請款單，2026-08-24）───────────────
    // 三個子清單的排序偏好各自獨立，list_key 帶上 quote_no 前綴（見 loadShippingNotes
    // /loadInvoiceVouchers/loadPaymentRequests 載入時機），避免跨案件互相污染。
    _subListMeta: {
      sn:     { pref: 'snSortPref',     dataKey: 'shippingNotes',   ref: 'snListBody', idField: 'noteNo',
                fields: { shipDate: n => n.shipDate || '', createdAt: n => n.createdAt || '' } },
      iv:     { pref: 'ivSortPref',     dataKey: 'invoiceVouchers', ref: 'ivListBody', idField: 'voucherNo',
                fields: { createdAt: v => v.createdAt || '', totalAmount: v => v.totalAmount || 0 } },
      prList: { pref: 'prListSortPref', dataKey: 'paymentRequests', ref: 'prListBody', idField: 'requestNo',
                fields: { createdAt: v => v.createdAt || '', amount: v => v.amount || 0 } },
    },
    _sortedSubList(kind) {
      const meta = this._subListMeta[kind]
      return applyListSort(this[meta.dataKey] || [], this[meta.pref], meta.fields, item => item[meta.idField])
    },
    sortedShippingNotes()   { return this._sortedSubList('sn') },
    sortedInvoiceVouchers() { return this._sortedSubList('iv') },
    sortedPaymentRequests() { return this._sortedSubList('prList') },

    async setSubListSortMode(kind, mode) {
      const meta = this._subListMeta[kind]
      this[meta.pref].sortMode = mode
      this.$nextTick(() => this._initSubListSortable(kind))
      await saveListPref(this.session.token, `${kind}:${this.selected.quote_no}`, this[meta.pref])
    },
    async toggleSubListSortDir(kind) {
      const meta = this._subListMeta[kind]
      this[meta.pref].sortDir = this[meta.pref].sortDir === 'asc' ? 'desc' : 'asc'
      await saveListPref(this.session.token, `${kind}:${this.selected.quote_no}`, this[meta.pref])
    },
    _initSubListSortable(kind) {
      const meta = this._subListMeta[kind]
      const body = this.$refs[meta.ref]
      if (!body || typeof Sortable === 'undefined') return
      if (this._subSortables[kind]) { this._subSortables[kind].destroy(); this._subSortables[kind] = null }
      if (this[meta.pref].sortMode !== 'custom') return
      this._subSortables[kind] = Sortable.create(body, {
        animation: 150,
        handle: '.drag-handle',
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        onEnd: async () => {
          const visibleIds = [...body.querySelectorAll('[data-item-id]')].map(el => el.dataset.itemId)
          const rest = (this[meta.pref].customOrder || []).filter(id => !visibleIds.includes(id))
          this[meta.pref].customOrder = [...visibleIds, ...rest]
          await saveListPref(this.session.token, `${kind}:${this.selected.quote_no}`, this[meta.pref])
        }
      })
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
        // 分頁/檢視狀態必須在任何 await 之前就重設完（2026-09-09 修）：
        // this.selected 一設定，分頁列就立刻渲染給使用者點；但下面
        // _seedDefaultStagesIfEmpty() 對全新案件會連打 5 次建立階段的 API，
        // 這段期間如果使用者已經切到別的分頁（例如「財務」），原本寫在 await
        // 之後的 activeTab='biz' 會把人硬彈回「案件資訊」——階段建立越慢、
        // 被彈回的機率越高。這幾個都是純檢視狀態，提前重設沒有副作用。
        this.activeTab = 'biz'
        this.execSubTab = 'progress'
        this.cr.dealTag = data.data?.dealTag || data.deal_tag || '已成案'
        this.cr.caseRecord = data.data?.caseRecord || null
        await this.ensureCaseRecord()
        await this._seedDefaultStagesIfEmpty()
        this.dirty = false
        this.saveStatus = ''
        this.saveMsg = ''
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
        this.caseActionItems = []
        this.assignedUserIds = data.assigned_user_ids || []
        this.caseTasks = []
        this.caseUpdates = []
        this.newComment = ''
        this.shippingNotes = []
        this.showShippingModal = false
        this._shippingLogOpen = {}
        this.shippingContactOptions = []
        this.showShippingContactPicker = false
        this.closeShippingPreview()
        this.contractorVouchers = []
        this.closeContractorVoucherPreview()
        this.invoiceVouchers = []
        this.closeInvoiceVoucherPreview()
        this.paymentRequests = []
        this.financeSummary = null
        this.finShowRecvDetail = false
        this.finShowPayDetail = false
        this._loadCaseTasks(quoteNo)
        this.loadDispatches(quoteNo)
        this.loadContractorVouchers(quoteNo)
        this.loadInvoiceVouchers(quoteNo)
        this.loadPaymentRequests(quoteNo)
        this.loadFinanceSummary(quoteNo)
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

    // ── 代辦事項（2026-08-26 專案管理併入案件管理，取代原本跳去 projects.html
    //    的 goToProject()/createProjectFromCase()）──
    async loadCaseActionItems() {
      if (!this.selected) return
      this.caseActionItemsLoading = true
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/action-items`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.caseActionItems = (await r.json()).items || []
      } catch {}
      this.caseActionItemsLoading = false
    },

    async addActionItem() {
      const text = this.newActionItemText.trim()
      if (!text || !this.selected) return
      this.addingActionItem = true
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/action-items`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ text })
        })
        if (!r.ok) { alert('新增失敗：' + (await r.json()).detail); return }
        this.newActionItemText = ''
        await this.loadCaseActionItems()
      } catch(e) {
        alert('發生錯誤：' + e.message)
      } finally {
        this.addingActionItem = false
      }
    },

    async deleteActionItem(itemId) {
      if (!this.selected || !confirm('確定刪除此代辦事項？')) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/action-items/${itemId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert('刪除失敗：' + (await r.json()).detail); return }
        await this.loadCaseActionItems()
      } catch(e) {
        alert('發生錯誤：' + e.message)
      }
    },

    async approveActionItem(itemId, stage) {
      if (!this.selected) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/action-items/${itemId}/approve`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ stage })
        })
        if (!r.ok) { alert('確認失敗：' + (await r.json()).detail); return }
        await this.loadCaseActionItems()
      } catch(e) {
        alert('發生錯誤：' + e.message)
      }
    },

    actionItemStatusLabel(item) {
      if (item.status === 'done') return '✓ 已完成'
      if (item.status === 'stage1_done') return '工程已確認，待業務確認'
      return '待確認'
    },

    // ── 專案資訊（成員分配，取代原 PATCH /api/projects/{id}/assigned-users）──
    toggleAssignedUser(userId) {
      const i = this.assignedUserIds.indexOf(userId)
      if (i >= 0) this.assignedUserIds.splice(i, 1)
      else this.assignedUserIds.push(userId)
    },

    async saveAssignedUsers() {
      if (!this.selected) return
      this.assignedUsersSaving = true
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/assigned-users`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ user_ids: this.assignedUserIds })
        })
        if (!r.ok) { alert('儲存失敗：' + (await r.json()).detail); return }
      } catch(e) {
        alert('發生錯誤：' + e.message)
      } finally {
        this.assignedUsersSaving = false
      }
    },

    // ── 專案執行報告匯出 ──
    async exportProjectReport() {
      if (!this.selected || this.exportingProjectReport) return
      this.exportingProjectReport = true
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/project-report-pdf`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert('匯出失敗：' + (await r.json()).detail); return }
        const blob = await r.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${this.selected.quote_no}_專案執行報告.pdf`
        a.click()
        URL.revokeObjectURL(url)
      } catch(e) {
        alert('發生錯誤：' + e.message)
      } finally {
        this.exportingProjectReport = false
      }
    },

    ensureCaseRecord() {
      if (!this.cr.caseRecord) {
        this.cr.caseRecord = {
          // stages 正規化 Phase 3b（2026-08-23）：不再本地寫死 5 個帶假 id 的階段物件——
          // 一旦切到 stages 專屬端點，假 id 對伺服器來說根本不存在，操作會 404。真正的
          // 5 個預設階段改由 _seedDefaultStagesIfEmpty() 透過 API 建立，取得真實 id。
          stages: [],
          payment: { items: [
            { id: 1, type: '訂金款', pct: 30, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
            { id: 2, type: '交貨款', pct: 30, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
            { id: 3, type: '驗收款', pct: 40, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
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
          { id: 1, type: '訂金款', pct: 30, amount: null, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          { id: 2, type: '交貨款', pct: 30, amount: null, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          { id: 3, type: '驗收款', pct: 40, amount: null, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
        ], note: '' }
      } else if (!this.cr.caseRecord.payment.items) {
        this.cr.caseRecord.payment = { items: [
          { id: 1, type: '訂金款', pct: 30, amount: null, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          { id: 2, type: '交貨款', pct: 30, amount: null, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          { id: 3, type: '驗收款', pct: 40, amount: null, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
        ], note: this.cr.caseRecord.payment.note || '' }
      }
    },

    // stages 正規化 Phase 3b（2026-08-23）：案件目前完全沒有階段時（新案件、或早期
    // 資料從未經過 quotation-form.html／case-management.html 任何一份預設模板寫入
    // 過），透過 stages 端點依序建立 5 個預設階段，取得真實 id。selectCase() 載入完
    // 成後呼叫一次；ensureCaseRecord() 補齊其他欄位形狀之後才會執行到這裡。
    async _seedDefaultStagesIfEmpty() {
      if (!this.selected || !this.cr.caseRecord) return
      if ((this.cr.caseRecord.stages || []).length > 0) return
      const labels = ['訂單確認', '叫料出貨', '施工安裝', '客戶驗收', '尾款結清']
      for (const label of labels) {
        try {
          const r = await fetch(`/api/quotations/${this.selected.quote_no}/stages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({ label })
          })
          if (r.ok) this.cr.caseRecord.stages.push(await r.json())
        } catch {}
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
      items.push({ id: Date.now(), type: '進度款', pct: 0, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' })
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
      if (this.cr.dealTag === '已結案' && !this.selected.case_semi_unlocked) {
        // 已結案且未解鎖：後端會直接 403，這裡先擋下避免每次 @input 觸發的
        // 防抖自動存檔都跑一趟網路請求、又跳出令人困惑的「儲存失敗」。
        this.dirty = false
        this.saveStatus = 'error'
        this.saveMsg = '案件已結案並鎖定，請先解鎖'
        return
      }
      this.saving = true
      try {
        const r = await fetch('/api/quotations/' + this.selected.quote_no + '/case-record', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ case_record: this.cr.caseRecord })
        })
        if (r.ok) {
          this.dirty = false
          const res = await r.json().catch(() => ({}))
          if (res.pending) {
            // 已結案案件半解鎖期間：此次存檔不會立即生效，已排隊等最高管理員審核
            // （見 backend/routers/quotations.py::_gate_case_edit()）。
            this.saveStatus = 'dirty'
            this.saveMsg = '已送出，待最高管理員審核後套用'
            this.saving = false
            return
          }
          const conflicts = res.stockConflicts || []
          if (conflicts.length) {
            // 序號已登載到案件，但庫存系統裡這些序號其實卡在別的狀態（已出貨/已安裝於
            // 別案件等）——不擋存檔，但要讓使用者看到，不然庫存跟案件記錄會無聲分岔
            this.saveStatus = 'dirty'
            this.saveMsg = `已儲存，但 ${conflicts.length} 個序號庫存狀態衝突（${conflicts.map(c => c.sn + ':' + c.stockStatus).join('、')}）`
          } else {
            this.saveStatus = 'saved'
            this.saveMsg = '已儲存'
            setTimeout(() => { if (!this.dirty) { this.saveStatus = ''; this.saveMsg = '' } }, 2000)
          }
          // 款項明細（勾已收款/實收金額/手續費）就是在這支存的，財務 Tab 的
          // 應收應付總覽必須跟著重算，否則會停在存檔前的舊數字
          this.loadFinanceSummary(this.selected?.quote_no)
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
        } else {
          // 完結案防呆機制（2026-08-25/26）擋下時會回 400 + 說明未達成的前置
          // 條件，不能靜默吞掉，不然使用者只會看到「完結案」按鈕沒反應。
          const err = await r.json().catch(() => ({}))
          alert(err.detail || '操作失敗，請稍後再試')
        }
      } catch {
        alert('網路錯誤，請稍後再試')
      }
    },

    async unlockCase() {
      if (!this.selected) return
      if (!confirm('確認解鎖此已結案案件？\n\n解鎖後將進入「半解鎖」狀態，之後對案件記錄的變更/上傳需最高管理員於簽核佇列審核通過後才會套用。')) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/case-unlock`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) {
          this.selected.case_semi_unlocked = 1
        } else {
          alert((await r.json().catch(() => ({}))).detail || '解鎖失敗')
        }
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async lockCase() {
      if (!this.selected) return
      if (!confirm('確認重新上鎖此案件？\n\n上鎖後將無法再變更案件記錄，需再次解鎖才能繼續編輯（既有待審核項目不受影響）。')) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/case-lock`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) {
          this.selected.case_semi_unlocked = 0
        } else {
          alert((await r.json().catch(() => ({}))).detail || '上鎖失敗')
        }
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    caseProgressPct() {
      const stages = this.cr.caseRecord?.stages || []
      if (!stages.length) return 0
      return Math.round(stages.filter(s => s.done).length / stages.length * 100)
    },

    _firstUndoneStageId() {
      const stages = this.cr.caseRecord?.stages || []
      const s = stages.find(s => !s.done)
      return s ? s.id : null
    },
    stageSegClass(st) {
      if (st.done) return 'stage-segbar__seg--done'
      if (this.stageIsOverdue(st)) return 'stage-segbar__seg--overdue'   // 逾期優先於「目前/未來」
      if (st.id === this._firstUndoneStageId()) return 'stage-segbar__seg--current'
      return 'stage-segbar__seg--future'
    },
    stageSegTooltip(st) {
      const status = st.done
        ? ('已完成' + (st.doneAt ? '（' + st.doneAt + '）' : ''))
        : (this.stageIsOverdue(st)
            ? ('已逾期' + (st.dueDate ? '（到期 ' + st.dueDate + '）' : ''))
            : (st.dueDate ? ('到期日 ' + st.dueDate) : '未設定到期日'))
      return (st.label || '（未命名階段）') + ' — ' + status
    },

    // stages 正規化 Phase 3b（2026-08-23）：以下階段相關函式改成直接呼叫 stages 專屬
    // 端點即時送出，不再靠本地陣列變更 + setDirty() 整包 debounce 存檔。成功後用伺服器
    // 回應 Object.assign 覆蓋本地物件，確保跟資料庫一致；失敗用 alert()（比照本檔既有
    // 慣例，例如 createProjectFromCase()）。materials/devices/payment/contract/roles
    // 等其他 caseRecord 欄位不受影響，仍走 setDirty()/saveCaseRecord() 整包存檔。
    _stagesApiBase() { return `/api/quotations/${this.selected.quote_no}/stages` },
    _authHeaders(json) {
      const h = { Authorization: 'Bearer ' + this.session.token }
      if (json) h['Content-Type'] = 'application/json'
      return h
    },

    async addStage() {
      if (!this.selected) return
      await this.ensureCaseRecord()
      try {
        const r = await fetch(this._stagesApiBase(), {
          method: 'POST', headers: this._authHeaders(true), body: JSON.stringify({ label: '新階段' })
        })
        if (!r.ok) { alert('新增階段失敗'); return }
        this.cr.caseRecord.stages.push(await r.json())
      } catch (e) { alert('發生錯誤：' + e.message) }
    },
    async removeStage(idx) {
      const stages = this.cr.caseRecord.stages
      const st = stages[idx]
      if (!st) return
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}`, { method: 'DELETE', headers: this._authHeaders() })
        if (!r.ok) { alert('刪除失敗'); return }
        stages.splice(idx, 1)
        stages.forEach(s => { if (s.dependsOn) s.dependsOn = s.dependsOn.filter(id => id !== st.id) })
      } catch (e) { alert('發生錯誤：' + e.message) }
    },

    toggleStageDetail(id) { this._openStageDetail[id] = !this._openStageDetail[id] },

    stageIsOverdue(st) {
      if (st.done || !st.dueDate) return false
      return st.dueDate < new Date().toISOString().slice(0,10)
    },

    otherStages(stageId) {
      return (this.cr.caseRecord?.stages || []).filter(s => s.id !== stageId)
    },

    // 通用階段欄位更新（label/done/doneAt/startDate/dueDate），取代原本靠 setDirty() 觸發
    // 的整包存檔；成功後額外呼叫 _checkAllStagesDone()（原本是 setDirty() 順帶觸發的）。
    async updateStage(st, fields) {
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}`, {
          method: 'PUT', headers: this._authHeaders(true), body: JSON.stringify(fields)
        })
        if (!r.ok) { alert('儲存失敗'); return }
        Object.assign(st, await r.json())
        this._checkAllStagesDone()
      } catch (e) { alert('發生錯誤：' + e.message) }
    },

    async addStageAssignee(st, username) {
      if (!username) return
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/assignees`, {
          method: 'POST', headers: this._authHeaders(true), body: JSON.stringify({ username })
        })
        if (r.ok) Object.assign(st, await r.json())
      } catch {}
    },
    async removeStageAssignee(st, username) {
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/assignees/${encodeURIComponent(username)}`, {
          method: 'DELETE', headers: this._authHeaders()
        })
        if (r.ok) Object.assign(st, await r.json())
      } catch {}
    },

    wouldCreateCycle(stageId, candidateId) {
      // 若讓 stageId 依賴 candidateId，順著 dependsOn 追下去會不會繞回 stageId 自己。
      // 純前端快速預檢，伺服器端 toggle_stage_dependency 仍是最終權威判斷（見下方 400 處理）。
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

    async toggleStageDependency(st, candidateId) {
      const has = (st.dependsOn || []).includes(candidateId)
      if (!has && this.wouldCreateCycle(st.id, candidateId)) {
        alert('這樣設定會讓階段之間互相循環依賴，請重新選擇前置階段')
        return
      }
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/depends-on/${candidateId}`, {
          method: 'POST', headers: this._authHeaders()
        })
        if (!r.ok) {
          const err = await r.json().catch(() => ({}))
          alert(err.detail || '設定失敗')
          return
        }
        Object.assign(st, await r.json())
      } catch (e) { alert('發生錯誤：' + e.message) }
    },

    switchToTimeline() {
      this.stageView = 'timeline'
      this.$nextTick(() => this.renderGantt())
    },

    _userDisplay(username) {
      return (this.selectableUsers.find(u => u.username === username)?.display_name) || username
    },

    _ganttTasks() {
      const stages = this.cr.caseRecord?.stages || []
      const byId   = Object.fromEntries(stages.map(s => [String(s.id), s]))
      const today  = new Date().toISOString().slice(0,10)
      const addDays = (dateStr, n) => {
        const d = new Date(dateStr + 'T00:00:00')
        d.setDate(d.getDate() + n)
        return d.toISOString().slice(0,10)
      }
      return stages.map(st => {
        // 日期來源優先順序（2026-08-24）：
        // 1. 「前往日期」visits 記錄的最早～最晚——施工類階段常有好幾筆前往記錄，
        //    這是最能反映真實施作期間的來源，已完成的話終點改用完成日期（可能
        //    比最後一次前往晚幾天才正式結案）。
        // 2. 完成日期 doneAt（單日）——使用者實際會填、最準確的次要來源。
        // 3. 起始/到期日期 startDate/dueDate——實務上幾乎沒人填，只靠它們會讓
        //    已完成的階段全部退回「今天」擠成一團（跨案時間軸同一個問題的根因，
        //    這裡是同一套邏輯的單案版）。
        const visitDates = (st.visits || []).map(v => v.visitDate).filter(Boolean).sort()
        let start, end
        if (visitDates.length) {
          start = visitDates[0]
          end   = (st.done && st.doneAt) ? st.doneAt : visitDates[visitDates.length - 1]
        } else if (st.done && st.doneAt) {
          start = st.doneAt
          end   = st.doneAt
        } else {
          start = st.startDate || st.dueDate || today
          end   = st.dueDate   || st.startDate || addDays(start, 1)
        }
        if (end < start) end = start
        if (start === end) end = addDays(start, 1)
        const assignedTo  = st.assignedTo || []
        const primary     = assignedTo[0] || ''
        // 依主要負責人（assignedTo 第一位）hash 出固定色階 index，供 CSS .stage-c0~c7 上色
        const idx = primary ? _GANTT_COLORS.indexOf(_avatarColor(primary)) : -1
        const classes = [
          idx >= 0 ? ('stage-c' + idx) : 'stage-unassigned',
          st.done ? 'stage-done' : '',
          (!st.done && this.stageIsOverdue(st)) ? 'stage-overdue' : '',
        ].filter(Boolean).join(' ')
        return {
          id:           String(st.id),
          name:         st.label || '（未命名階段）',
          start, end,
          progress:     st.done ? 100 : 0,
          dependencies: (st.dependsOn || []).map(String).join(','),
          custom_class: classes,
          _assignedNames: assignedTo.map(u => this._userDisplay(u)),
          _dependsNames:  (st.dependsOn || []).map(id => byId[String(id)]?.label).filter(Boolean),
          _done: !!st.done,
          _overdue: !st.done && this.stageIsOverdue(st),
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
          this.updateStage(st, { startDate: fmt(start), dueDate: fmt(end) })
        },
        custom_popup_html: (task) => {
          const statusChip = task._done
            ? '<span class="gantt-pop-chip gantt-pop-chip--done">已完成</span>'
            : (task._overdue ? '<span class="gantt-pop-chip gantt-pop-chip--overdue">已逾期</span>' : '')
          const assignees = (task._assignedNames && task._assignedNames.length)
            ? task._assignedNames.map(n => `<span class="gantt-pop-av">${n}</span>`).join('')
            : '<span class="gantt-pop-empty">尚未指派</span>'
          const depends = (task._dependsNames && task._dependsNames.length)
            ? `<div class="gantt-pop-row"><span class="gantt-pop-lbl">前置階段</span>${task._dependsNames.map(n => `<span class="gantt-pop-av">${n}</span>`).join('')}</div>`
            : ''
          return `
            <div class="gantt-pop">
              <div class="gantt-pop-title">${task.name}${statusChip}</div>
              <div class="gantt-pop-row"><span class="gantt-pop-lbl">日期</span>${task.start} ~ ${task.end}</div>
              <div class="gantt-pop-row"><span class="gantt-pop-lbl">負責人</span>${assignees}</div>
              ${depends}
            </div>`
        },
      })
    },
    async addVisit(stageIdx) {
      const st = this.cr.caseRecord.stages[stageIdx]
      if (!st) return
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/visits`, {
          method: 'POST', headers: this._authHeaders(true), body: JSON.stringify({})
        })
        if (!r.ok) { alert('新增記錄失敗'); return }
        Object.assign(st, await r.json())
      } catch (e) { alert('發生錯誤：' + e.message) }
    },
    async removeVisit(stageIdx, visitIdx) {
      const st = this.cr.caseRecord.stages[stageIdx]
      const visit = st?.visits?.[visitIdx]
      if (!st || !visit) return
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/visits/${visit.id}`, {
          method: 'DELETE', headers: this._authHeaders()
        })
        if (!r.ok) { alert('刪除失敗'); return }
        st.visits.splice(visitIdx, 1)
      } catch (e) { alert('發生錯誤：' + e.message) }
    },
    async updateVisit(st, visit) {
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/visits/${visit.id}`, {
          method: 'PUT', headers: this._authHeaders(true),
          body: JSON.stringify({ visitDate: visit.visitDate, visitPeople: visit.visitPeople, note: visit.note })
        })
        if (r.ok) Object.assign(st, await r.json())
      } catch {}
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
    async dragEnd() {
      this.dragFromIdx = null
      const stages = this.cr.caseRecord?.stages || []
      if (!this.selected || !stages.length) return
      try {
        await fetch(`${this._stagesApiBase()}/reorder`, {
          method: 'PATCH', headers: this._authHeaders(true),
          body: JSON.stringify({ orderedIds: stages.map(s => s.id) })
        })
      } catch {}
    },

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
      this.feedCalMode = false
      this.feedCalSelDate = ''
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/updates`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.caseUpdates = await r.json()
      } catch {}
      this.updatesLoading = false
    },

    // ── 動態 Tab：月曆總覽（依已載入的 caseUpdates 統計每日筆數，點日期篩選） ──
    toggleFeedCalMode() {
      this.feedCalMode = !this.feedCalMode
      if (!this.feedCalMode) this.feedCalSelDate = ''
    },
    feedCalPrevMonth() {
      this.feedCalMonth--
      if (this.feedCalMonth < 1) { this.feedCalMonth = 12; this.feedCalYear-- }
    },
    feedCalNextMonth() {
      this.feedCalMonth++
      if (this.feedCalMonth > 12) { this.feedCalMonth = 1; this.feedCalYear++ }
    },
    feedCalDays() {
      const year = this.feedCalYear, month = this.feedCalMonth
      const _ld = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
      const todayStr = _ld(new Date())
      const first    = new Date(year, month - 1, 1)
      const daysInM  = new Date(year, month, 0).getDate()
      const startDow = first.getDay()
      const startPad = startDow === 0 ? 6 : startDow - 1
      const cells = []
      for (let i = startPad; i > 0; i--) {
        const d = new Date(year, month - 1, 1 - i)
        cells.push({ date: _ld(d), day: d.getDate(), inMonth: false, isToday: false })
      }
      for (let i = 1; i <= daysInM; i++) {
        const s = `${year}-${String(month).padStart(2,'0')}-${String(i).padStart(2,'0')}`
        cells.push({ date: s, day: i, inMonth: true, isToday: s === todayStr })
      }
      let nxt = 1
      while (cells.length < 42) {
        const d = new Date(year, month, nxt++)
        cells.push({ date: _ld(d), day: d.getDate(), inMonth: false, isToday: false })
      }
      return cells
    },
    feedCalCount(date) {
      return this.caseUpdates.filter(it => (it.created_at || '').replace('T',' ').slice(0,10) === date).length
    },
    filteredFeedItems() {
      if (!this.feedCalSelDate) return this.caseUpdates
      return this.caseUpdates.filter(it => (it.created_at || '').replace('T',' ').slice(0,10) === this.feedCalSelDate)
    },

    onCommentPhotosSelected(e) {
      this.newCommentPhotos = Array.from(e.target.files || [])
    },

    // 工作日誌照片簽章 URL（跟 projects.html 既有的 photoUrl()/_ptCache 同一套
    // 作法：短效期 pt token，抓回來前先回 1x1 透明圖，避免完整 session token
    // 外洩到網址列/瀏覽器歷史）。
    photoUrl(path) {
      if (!path) return ''
      const now = Math.floor(Date.now() / 1000)
      const cached = this._ptCache[path]
      if (cached && cached.exp > now) {
        return `/api/uploads/${path}?pt=${cached.pt}`
      }
      if (!this._ptCache[path + '_fetching']) {
        this._ptCache[path + '_fetching'] = true
        fetch(`/api/photo-token?path=${encodeURIComponent(path)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        }).then(r => r.ok ? r.json() : null).then(d => {
          if (d && d.token) {
            this._ptCache = {
              ...this._ptCache,
              [path]: { pt: d.token, exp: now + (d.ttl || 3600) - 60 },
              [path + '_fetching']: false,
            }
          }
        }).catch(() => { this._ptCache[path + '_fetching'] = false })
      }
      return 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBTAA7'
    },

    // 聯絡事項選單非「其他」時直接用選項文字，選「其他」時用自訂輸入
    resolvedContactType() {
      return this.newCommentContactType === '其他'
        ? this.newCommentContactTypeCustom.trim()
        : this.newCommentContactType
    },

    async postComment() {
      const content = this.newComment.trim()
      if (!content || this.postingComment) return
      // 有選照片、填執行時數、選聯絡事項類型、改過日期、或指定記錄對象 → 當成
      // 工作日誌（結構化欄位＋可上傳照片），走 work_logs；純文字 → 維持原本
      // 輕量留言（case_updates，含「標記為重要」＋ Google 行事曆同步），
      // 2026-08-26 新增結構化欄位，2026-08-30 補上日期／記錄對象兩個觸發條件。
      const isBackdated = this.newCommentLogDate !== new Date().toISOString().slice(0, 10)
      if (this.newCommentPhotos.length > 0 || this.newCommentHours || this.newCommentContactType ||
          isBackdated || this.newCommentUserId) {
        await this.postWorkLogEntry(content)
        return
      }
      this.postingComment = true
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(this.selected.quote_no)}/updates`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token, 'Content-Type': 'application/json' },
          body: JSON.stringify({ content, important: this.newCommentImportant })
        })
        if (r.ok) {
          const item = await r.json()
          this.caseUpdates.unshift(item)
          this.newComment = ''
          this.newCommentImportant = false
        }
      } catch {}
      this.postingComment = false
    },

    async postWorkLogEntry(content) {
      this.postingComment = true
      try {
        const uid = this.newCommentUserId ? Number(this.newCommentUserId) : this.session.id
        const r = await fetch('/api/work-logs', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            log_date: this.newCommentLogDate || new Date().toISOString().slice(0, 10),
            user_id: uid, content,
            hours: this.newCommentHours || 8, case_no: this.selected.quote_no,
            contact_type: this.resolvedContactType(),
          })
        })
        if (!r.ok) { alert('新增工作日誌失敗：' + (await r.json()).detail); return }
        const { id } = await r.json()
        if (this.newCommentPhotos.length > 0) {
          const fd = new FormData()
          this.newCommentPhotos.forEach(f => fd.append('files', f))
          const rp = await fetch(`/api/work-logs/${id}/photos`, {
            method: 'POST',
            headers: { Authorization: 'Bearer ' + this.session.token },
            body: fd
          })
          if (!rp.ok) alert('照片上傳失敗：' + (await rp.json()).detail)
        }
        this.newComment = ''
        this.newCommentImportant = false
        this.newCommentPhotos = []
        this.newCommentHours = ''
        this.newCommentContactType = ''
        this.newCommentContactTypeCustom = ''
        this.newCommentLogDate = new Date().toISOString().slice(0, 10)
        this.newCommentUserId = ''
        await this.loadCaseUpdates(this.selected.quote_no)
      } catch(e) {
        alert('發生錯誤：' + e.message)
      } finally {
        this.postingComment = false
      }
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
        payable_date: '',
        status: this._quoteStatusToDispatch(this.selected?.status || ''),
        tax_rate: 0.05,
        items: [],
        personnel: []
      }
    },

    // 本地日期字串（YYYY-MM-DD），不要用 new Date().toISOString().slice(0,10)——
    // toISOString() 是 UTC 時間，台灣 UTC+8 在本地每天 00:00–08:00 之間會被
    // 誤判成前一天（比照 static/sidebar.js::_localISOString() 同款修法）。
    _localDateStr(d) {
      d = d || new Date()
      const tz = d.getTimezoneOffset() * 60000
      return new Date(d.getTime() - tz).toISOString().slice(0, 10)
    },

    // 2026-08-31（財務/出納權限分工）：是否具備指定模組——session.modules 是
    // 登入當下 /api/auth/login、/api/auth/me 回傳的已解析陣列（不是 JSON 字串）。
    hasModule(key) {
      return (this.session.modules || []).includes(key)
    },

    canMarkPayment() {
      return ['superadmin', 'admin'].includes(this.session.role) || this.hasModule('cashier')
    },

    // ── Modal 誤觸關閉保護（2026-08-31 新增）：backdrop 點外面／Esc／× 這三個
    // 「容易誤觸」的關閉路徑，改成先跳原生 confirm() 警示，取消就留在原本
    // 填寫到一半的頁面，不會直接歸零關閉；表單底部明確標示「取消」的按鈕
    // 維持原樣不用二次確認（那本來就是使用者主動放棄的明確意圖）。
    _confirmDiscardForm() {
      return confirm('表單尚未儲存，確定要關閉嗎？目前輸入的內容將會遺失。')
    },
    closeDispatchModalGuarded() {
      if (this._confirmDiscardForm()) this.showDispatchModal = false
    },
    closeWriteoffModalGuarded() {
      if (this._confirmDiscardForm()) this.writeoffModal.open = false
    },
    closeShippingModalGuarded() {
      if (this._confirmDiscardForm()) this.showShippingModal = false
    },
    closePayVoucherModalGuarded() {
      if (this._confirmDiscardForm()) this.payVoucherModal = false
    },
    closeCreateVoucherModalGuarded() {
      if (this._confirmDiscardForm()) this.createVoucherModal = false
    },
    closeInvoiceVoucherModalGuarded() {
      if (this._confirmDiscardForm()) this.closeInvoiceVoucherModal()
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
        invoice_no: this.dispatchForm.invoice_no || '',
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
      this.snSortPref = await loadListPref(this.session.token, `sn:${quoteNo}`)
      try {
        const r = await fetch(`/api/shipping-notes?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.shippingNotes = await r.json()
      } catch {}
      this.shippingNotesLoading = false
      this.$nextTick(() => this._initSubListSortable('sn'))
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

    async _loadPartsOptions() {
      if (this._partsOptions) return this._partsOptions
      try {
        const r = await fetch('/api/parts', { headers: { Authorization: 'Bearer ' + this.session.token } })
        this._partsOptions = r.ok ? ((await r.json()).items || []) : []
      } catch { this._partsOptions = [] }
      return this._partsOptions
    },

    async openSerialPicker(idx) {
      const it = this.shippingForm.items[idx]
      this.serialPicker = {
        show: true, itemIdx: idx, partNo: it.part_no || '',
        options: [], selected: [...(it.serials || [])], loading: false, error: ''
      }
      await this._loadPartsOptions()
      if (this.serialPicker.partNo) await this._loadSerialOptions()
    },

    async _loadSerialOptions() {
      if (!this.serialPicker.partNo) { this.serialPicker.options = []; return }
      this.serialPicker.loading = true; this.serialPicker.error = ''
      try {
        const r = await fetch(`/api/inventory/stock-items?part_no=${encodeURIComponent(this.serialPicker.partNo)}&status=in_stock`,
          { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) { const d = await r.json(); this.serialPicker.options = d.items || [] }
        else { this.serialPicker.error = '讀取庫存序號失敗' }
      } catch { this.serialPicker.error = '網路錯誤' }
      this.serialPicker.loading = false
    },

    onSerialPickerPartChange() {
      this.serialPicker.selected = []
      this._loadSerialOptions()
    },

    toggleSerialPick(sn) {
      const i = this.serialPicker.selected.indexOf(sn)
      if (i >= 0) this.serialPicker.selected.splice(i, 1)
      else this.serialPicker.selected.push(sn)
    },

    applySerialPicker() {
      const it = this.shippingForm.items[this.serialPicker.itemIdx]
      if (this.serialPicker.partNo && this.serialPicker.selected.length) {
        it.part_no = this.serialPicker.partNo
        it.serials = [...this.serialPicker.selected]
        it.qty = this.serialPicker.selected.length
      } else {
        delete it.part_no
        delete it.serials
      }
      this.serialPicker.show = false
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

    async revokeShippingApproval(n) {
      const note = prompt(`撤銷出貨單「${n.noteNo}」的核准？將退回草稿，且已扣的庫存序號會自動歸還可出貨狀態。\n\n可填寫撤銷原因（選填）：`)
      if (note === null) return
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/revoke-approval`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note })
        })
        if (!r.ok) { alert((await r.json()).detail || '撤銷失敗'); return }
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

    closingReportDownloading: false,
    async downloadClosingReportPdf() {
      if (!this.selected) return
      const quoteNo = this.selected.quote_no
      this.closingReportDownloading = true
      try {
        const r = await fetch(`/api/quotations/${quoteNo}/closing-report-pdf`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '結案報表產生失敗'); return }
        const blob = await r.blob()
        const url  = URL.createObjectURL(blob)
        const a    = document.createElement('a')
        a.href     = url
        a.download = `${quoteNo}_結案報表.pdf`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      } catch (e) { alert('下載失敗：' + e.message) }
      finally { this.closingReportDownloading = false }
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

    // ── 承攬商匯款申請 ──────────────────────────────────────────────────────────

    async loadContractorVouchers(quoteNo) {
      if (!quoteNo) return
      this.contractorVouchersLoading = true
      this.contractorVouchers = []
      try {
        const r = await fetch(`/api/contractor-vouchers?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.contractorVouchers = await r.json()
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
        if (!r.ok) { alert((await r.json()).detail || '建立失敗'); this.createVoucherSaving = false; return }
        this.createVoucherModal = false
        this.createVoucherDispatch = null
        await this.loadDispatches(this.selected?.quote_no)
        await this.loadContractorVouchers(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
      this.createVoucherSaving = false
    },

    async deleteContractorVoucher(v) {
      if (!confirm(`確定刪除匯款申請「${v.voucherNo}」？`)) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) await this.loadContractorVouchers(this.selected?.quote_no)
        else alert((await r.json()).detail || '刪除失敗')
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async submitContractorVoucher(v) {
      if (!confirm(`確定送出匯款申請「${v.voucherNo}」進行簽核？`)) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/submit`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json()).detail || '送出失敗'); return }
        await this.loadContractorVouchers(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async approveContractorVoucher(v) {
      if (!confirm(`確定簽核匯款申請「${v.voucherNo}」？`)) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({})
        })
        if (!r.ok) { alert((await r.json()).detail || '簽核失敗'); return }
        await this.loadContractorVouchers(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async rejectContractorVoucher(v) {
      const note = prompt(`退回匯款申請「${v.voucherNo}」，可填寫退回原因（選填）：`)
      if (note === null) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/reject`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note })
        })
        if (!r.ok) { alert((await r.json()).detail || '退回失敗'); return }
        await this.loadContractorVouchers(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async revokeContractorVoucherApproval(v) {
      const note = prompt(`撤銷匯款申請「${v.voucherNo}」的核准？將退回草稿。\n\n可填寫撤銷原因（選填）：`)
      if (note === null) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/revoke-approval`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note })
        })
        if (!r.ok) { alert((await r.json()).detail || '撤銷失敗'); return }
        await this.loadContractorVouchers(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
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
      if (!confirm(`確定取消匯款申請「${v.voucherNo}」的已匯款標記？`)) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/paid-toggle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ action: 'unpay', note: '' })
        })
        if (!r.ok) { alert((await r.json()).detail || '操作失敗'); return }
        await this.loadContractorVouchers(this.selected?.quote_no)
        this.loadFinanceSummary(this.selected?.quote_no)   // 已付/未付數字會變
      } catch (e) { alert('網路錯誤：' + e.message) }
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
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗'); return }
        const blob = await r.blob()
        const url  = URL.createObjectURL(blob)
        const a    = document.createElement('a')
        a.href     = url
        a.download = `${v.voucherNo}.pdf`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      } catch (e) { alert('下載失敗：' + e.message) }
    },

    async previewContractorVoucherPdf(v) {
      this.cvPreviewFetching = true
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗'); this.cvPreviewFetching = false; return }
        const blob = await r.blob()
        this.cvPreviewBlobUrl = URL.createObjectURL(blob)
        this.cvPreviewVoucher = v
        this.cvPreviewModal = true
      } catch (e) { alert('預覽失敗：' + e.message) }
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

    // ── 開票申請憑據 ────────────────────────────────────────────────────────────

    async loadInvoiceVouchers(quoteNo) {
      if (!quoteNo) return
      this.invoiceVouchersLoading = true
      this.invoiceVouchers = []
      this.ivSortPref = await loadListPref(this.session.token, `iv:${quoteNo}`)
      try {
        const r = await fetch(`/api/invoice-vouchers?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.invoiceVouchers = await r.json()
      } catch {}
      this.invoiceVouchersLoading = false
      this.$nextTick(() => this._initSubListSortable('iv'))
    },

    async openInvoiceVoucherModal() {
      if (this.dirty) { alert('款項明細有未儲存的修改，請先儲存後再申請開票憑據'); return }
      this.ivMode = 'amount'
      this.ivAmountInput = 0
      this.ivItemSelections = {}
      this.ivRemaining = null
      this.ivCreateModal = true
      this.ivRemainingLoading = true
      try {
        const r = await fetch(`/api/invoice-vouchers/remaining?quote_no=${encodeURIComponent(this.selected.quote_no)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.ivRemaining = await r.json()
        else { alert((await r.json()).detail || '載入額度失敗'); this.ivCreateModal = false }
      } catch (e) { alert('網路錯誤：' + e.message); this.ivCreateModal = false }
      this.ivRemainingLoading = false
    },

    closeInvoiceVoucherModal() {
      this.ivCreateModal = false
    },

    async openNetworkPlan() {
      const quoteNo = this.selected.quote_no
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/network-plan`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) {
          const d = await r.json()
          location.href = `network-plan-form.html?id=${d.id}`
          return
        }
        if (r.status !== 404) { alert((await r.json().catch(() => ({}))).detail || '查詢失敗'); return }
      } catch (e) { alert('網路錯誤：' + e.message); return }

      const mods = this.session.modules || []
      const canEdit = ['superadmin', 'admin'].includes(this.session.role) || mods.indexOf('netplan_edit') >= 0
      if (!canEdit) { alert('此案件尚無網路架構規劃書'); return }
      if (!confirm('此案件尚無網路架構規劃書，是否建立一份？')) return
      try {
        const cr = await fetch('/api/network-plans', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ quoteNo })
        })
        if (!cr.ok) { alert((await cr.json().catch(() => ({}))).detail || '建立失敗'); return }
        const d = await cr.json()
        location.href = `network-plan-form.html?id=${d.id}`
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    ivToggleItem(it) {
      if (this.ivItemSelections[it.itemId]) {
        delete this.ivItemSelections[it.itemId]
      } else {
        const qty = it.remainingQty
        this.ivItemSelections[it.itemId] = { qty, amount: Math.round(qty * (it.unitPrice || 0)) }
      }
    },

    ivItemQtyChanged(it) {
      const sel = this.ivItemSelections[it.itemId]
      if (!sel) return
      if (sel.qty > it.remainingQty) sel.qty = it.remainingQty
      if (sel.qty < 0) sel.qty = 0
      sel.amount = Math.round(sel.qty * (it.unitPrice || 0))
    },

    // 按品項模式下，使用者輸入的金額比照報價單品項本身的慣例是「未稅」，
    // 跟「剩餘可申請金額」（含稅，來自 quoteTotal）不是同一個基準，比較前
    // 必須先用這張報價單自己的稅率（quoteTotal/quotePretax）換算成含稅。
    _ivTaxRatio() {
      const p = this.ivRemaining?.quotePretax || 0
      return p > 0 ? (this.ivRemaining.quoteTotal / p) : 1
    },

    ivAmountPretax() {
      const ratio = this._ivTaxRatio()
      return ratio > 0 ? Math.round((this.ivAmountInput || 0) / ratio) : (this.ivAmountInput || 0)
    },
    ivAmountTax() {
      return (this.ivAmountInput || 0) - this.ivAmountPretax()
    },

    ivSelectedTotal() {
      // 未稅小計（品項金額欄位本身的加總）
      return Object.values(this.ivItemSelections).reduce((sum, s) => sum + (Number(s.amount) || 0), 0)
    },
    ivSelectedGrossTotal() {
      // 含稅小計，才能跟剩餘可申請金額（含稅）比較
      return Math.round(this.ivSelectedTotal() * this._ivTaxRatio())
    },
    ivSelectedTax() {
      return this.ivSelectedGrossTotal() - this.ivSelectedTotal()
    },

    async submitInvoiceVoucherCreate() {
      if (!this.ivRemaining) return
      let body
      if (this.ivMode === 'amount') {
        if (!this.ivAmountInput || this.ivAmountInput <= 0) { alert('請輸入申請金額'); return }
        if (this.ivAmountInput > this.ivRemaining.remainingAmount) { alert('超過剩餘可申請金額'); return }
        body = { quote_no: this.selected.quote_no, scope: 'amount', amount: this.ivAmountInput }
      } else {
        const items = Object.entries(this.ivItemSelections).map(([itemId, sel]) => ({
          itemId: Number(itemId), qty: sel.qty, amount: sel.amount
        }))
        if (items.length === 0) { alert('請至少選擇一項品項'); return }
        if (this.ivSelectedGrossTotal() > this.ivRemaining.remainingAmount) { alert('超過剩餘可申請金額'); return }
        body = { quote_no: this.selected.quote_no, scope: 'items', items }
      }
      if (!confirm('確定送出建立開票申請憑據？')) return
      this.ivSubmitting = true
      try {
        const r = await fetch('/api/invoice-vouchers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(body)
        })
        if (!r.ok) { alert((await r.json()).detail || '建立失敗'); this.ivSubmitting = false; return }
        this.ivCreateModal = false
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
      this.ivSubmitting = false
    },

    async deleteInvoiceVoucher(v) {
      if (!confirm(`確定刪除開票申請憑據「${v.voucherNo}」？`)) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) await this.loadInvoiceVouchers(this.selected?.quote_no)
        else alert((await r.json()).detail || '刪除失敗')
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async submitInvoiceVoucher(v) {
      if (!confirm(`確定送出開票申請憑據「${v.voucherNo}」進行簽核？`)) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/submit`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json()).detail || '送出失敗'); return }
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async approveInvoiceVoucher(v) {
      if (!confirm(`確定簽核開票申請憑據「${v.voucherNo}」？`)) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({})
        })
        if (!r.ok) { alert((await r.json()).detail || '簽核失敗'); return }
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async rejectInvoiceVoucher(v) {
      const note = prompt(`退回開票申請憑據「${v.voucherNo}」，可填寫退回原因（選填）：`)
      if (note === null) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/reject`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note })
        })
        if (!r.ok) { alert((await r.json()).detail || '退回失敗'); return }
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async revokeInvoiceVoucherApproval(v) {
      const note = prompt(`撤銷開票申請憑據「${v.voucherNo}」的核准？將退回草稿。\n\n可填寫撤銷原因（選填）：`)
      if (note === null) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/revoke-approval`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note })
        })
        if (!r.ok) { alert((await r.json()).detail || '撤銷失敗'); return }
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async downloadInvoiceVoucherPdf(v) {
      try {
        fetch(`/api/invoice-vouchers/${v.voucherNo}/export?mode=external`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        }).catch(() => {})
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗'); return }
        const blob = await r.blob()
        const url  = URL.createObjectURL(blob)
        const a    = document.createElement('a')
        a.href     = url
        a.download = `${v.voucherNo}.pdf`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      } catch (e) { alert('下載失敗：' + e.message) }
    },

    async previewInvoiceVoucherPdf(v) {
      this.ivPreviewFetching = true
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗'); this.ivPreviewFetching = false; return }
        const blob = await r.blob()
        this.ivPreviewBlobUrl = URL.createObjectURL(blob)
        this.ivPreviewVoucher = v
        this.ivPreviewModal = true
      } catch (e) { alert('預覽失敗：' + e.message) }
      this.ivPreviewFetching = false
    },

    closeInvoiceVoucherPreview() {
      if (this.ivPreviewBlobUrl) URL.revokeObjectURL(this.ivPreviewBlobUrl)
      this.ivPreviewBlobUrl = ''
      this.ivPreviewModal = false
      this.ivPreviewVoucher = null
    },

    _ivStatusLabel(s) {
      return { '草稿': '草稿', '待審核': '待審核', '簽核中': '簽核中', '已核准': '已核准' }[s] || s
    },

    _ivStatusClass(s) {
      return { '草稿': 'badge--draft', '待審核': 'badge--pending', '簽核中': 'badge--signing', '已核准': 'badge--approved' }[s] || ''
    },

    // ── 附件（回簽/已開立檔案）共用 helper ──────────────────────────────────
    // 點擊即時在新分頁開啟（瀏覽器原生顯示圖片/PDF），不用另外刻預覽元件；
    // 連結需要簽名短效 token 才能通過 /api/uploads 的存取檢查。
    async previewAttachmentFile(file) {
      try {
        const r = await fetch(`/api/photo-token?path=${encodeURIComponent(file.path)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert('取得檔案連結失敗'); return }
        const { token } = await r.json()
        window.open(`/api/uploads/${file.path}?pt=${encodeURIComponent(token)}`, '_blank')
      } catch (e) { alert('開啟檔案失敗：' + e.message) }
    },

    async uploadShippingSignedFiles(note, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      try {
        const r = await fetch(`/api/shipping-notes/${note.noteNo}/signed-files`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '上傳失敗'); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { alert('上傳失敗：' + e.message) }
      evt.target.value = ''
    },

    async deleteShippingSignedFile(note, fileId) {
      if (!confirm('確定刪除此附件？')) return
      try {
        const r = await fetch(`/api/shipping-notes/${note.noteNo}/signed-files/${fileId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '刪除失敗'); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { alert('刪除失敗：' + e.message) }
    },

    async uploadInvoiceVoucherIssuedFiles(v, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/issued-files`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '上傳失敗'); return }
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { alert('上傳失敗：' + e.message) }
      evt.target.value = ''
    },

    async uploadPaymentItemInvoiceFiles(idx, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/payment/${idx}/invoice-files`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '上傳失敗'); return }
        const body = await r.json()
        if (body.pending) { alert(body.message || '已送出，待最高管理員審核後套用'); return }
        const item = this.paymentItems()[idx]
        if (item) {
          if (!item.invoiceFiles) item.invoiceFiles = []
          item.invoiceFiles.push(...body.files)
        }
      } catch (e) { alert('上傳失敗：' + e.message) }
      evt.target.value = ''
    },

    async deletePaymentItemInvoiceFile(idx, fileId) {
      if (!confirm('確定刪除此附件？')) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/payment/${idx}/invoice-files/${fileId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '刪除失敗'); return }
        const body = await r.json()
        if (body.pending) { alert(body.message || '已送出，待最高管理員審核後套用'); return }
        const item = this.paymentItems()[idx]
        if (item && item.invoiceFiles) item.invoiceFiles = item.invoiceFiles.filter(f => f.id !== fileId)
      } catch (e) { alert('刪除失敗：' + e.message) }
    },

    async uploadMaterialFiles(idx, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/materials/${idx}/files`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '上傳失敗'); return }
        const body = await r.json()
        if (body.pending) { alert(body.message || '已送出，待最高管理員審核後套用'); return }
        const mat = (this.cr.caseRecord.materials || [])[idx]
        if (mat) {
          if (!mat.files) mat.files = []
          mat.files.push(...body.files)
        }
      } catch (e) { alert('上傳失敗：' + e.message) }
      evt.target.value = ''
    },

    async deleteMaterialFile(idx, fileId) {
      if (!confirm('確定刪除此附件？')) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/materials/${idx}/files/${fileId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '刪除失敗'); return }
        const body = await r.json()
        if (body.pending) { alert(body.message || '已送出，待最高管理員審核後套用'); return }
        const mat = (this.cr.caseRecord.materials || [])[idx]
        if (mat && mat.files) mat.files = mat.files.filter(f => f.id !== fileId)
      } catch (e) { alert('刪除失敗：' + e.message) }
    },

    async uploadMaterialInvoiceFiles(idx, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/materials/${idx}/invoice-files`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '上傳失敗'); return }
        const body = await r.json()
        if (body.pending) { alert(body.message || '已送出，待最高管理員審核後套用'); return }
        const mat = (this.cr.caseRecord.materials || [])[idx]
        if (mat) {
          if (!mat.invoiceFiles) mat.invoiceFiles = []
          mat.invoiceFiles.push(...body.files)
        }
      } catch (e) { alert('上傳失敗：' + e.message) }
      evt.target.value = ''
    },

    async deleteMaterialInvoiceFile(idx, fileId) {
      if (!confirm('確定刪除此發票附件？')) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/materials/${idx}/invoice-files/${fileId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '刪除失敗'); return }
        const body = await r.json()
        if (body.pending) { alert(body.message || '已送出，待最高管理員審核後套用'); return }
        const mat = (this.cr.caseRecord.materials || [])[idx]
        if (mat && mat.invoiceFiles) mat.invoiceFiles = mat.invoiceFiles.filter(f => f.id !== fileId)
      } catch (e) { alert('刪除失敗：' + e.message) }
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
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '上傳失敗'); return }
        const body = await r.json()
        if (!d.files) d.files = []
        d.files.push(...body.files)
      } catch (e) { alert('上傳失敗：' + e.message) }
      evt.target.value = ''
    },

    async deleteDispatchFile(d, fileId) {
      if (!confirm('確定刪除此報價附件？')) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/files/${fileId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '刪除失敗'); return }
        if (d.files) d.files = d.files.filter(f => f.id !== fileId)
      } catch (e) { alert('刪除失敗：' + e.message) }
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
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '上傳失敗'); return }
        const body = await r.json()
        if (!d.invoiceFiles) d.invoiceFiles = []
        d.invoiceFiles.push(...body.files)
      } catch (e) { alert('上傳失敗：' + e.message) }
      evt.target.value = ''
    },

    async deleteDispatchInvoiceFile(d, fileId) {
      if (!confirm('確定刪除此廠商發票？')) return
      try {
        const r = await fetch(`/api/contractor-dispatches/${d.id}/invoice-files/${fileId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '刪除失敗'); return }
        if (d.invoiceFiles) d.invoiceFiles = d.invoiceFiles.filter(f => f.id !== fileId)
      } catch (e) { alert('刪除失敗：' + e.message) }
    },

    async deleteInvoiceVoucherIssuedFile(v, fileId) {
      if (!confirm('確定刪除此附件？')) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/issued-files/${fileId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '刪除失敗'); return }
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { alert('刪除失敗：' + e.message) }
    },

    // ── 請款單 ──────────────────────────────────────────────────────────────
    async loadPaymentRequests(quoteNo) {
      if (!quoteNo) return
      this.paymentRequestsLoading = true
      this.paymentRequests = []
      this.prListSortPref = await loadListPref(this.session.token, `prList:${quoteNo}`)
      try {
        const r = await fetch(`/api/payment-requests?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.paymentRequests = await r.json()
      } catch {}
      this.paymentRequestsLoading = false
      this.$nextTick(() => this._initSubListSortable('prList'))
    },

    _prStatusLabel(s) {
      return { '草稿': '草稿', '待審核': '待審核', '簽核中': '簽核中', '已核准': '已核准' }[s] || s
    },

    _prStatusClass(s) {
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
