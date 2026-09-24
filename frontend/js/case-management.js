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
    caseViewMode: 'list',   // 'list' | 'board' | 'matrix'
    // ═══ 關卡矩陣（2026-09-14）══════════════════════════════════════════
    // 五項結案前置條件（§5.2）原本散在五個頁籤，而且只有在按下「結案」
    // 被 400 擋下來時才看得到。資料來自 /api/quotations/gate-matrix，那支
    // 端點跟擋下結案用的是同一份判定（_case_close_gates），所以矩陣上的
    // 「5/5 可結案」等於「現在按下去不會被擋」。
    gateMatrix: [],
    gmLoaded: false,
    gmSort: 'ready',     // 'ready' | 'stuck' | 'amount'
    gmFilter: '',        // '' | 'ready' | 'settling' | 'mine'
    gmDue: '',           // '' | 'overdue' | 'today' | 'week' | 'month' | 'none'
    today: new Date().toISOString().slice(0, 10),

    gateHeads: [
      { key: 'progress',     label: '進度', hint: '階段完成' },
      { key: 'payment',      label: '收款', hint: '款項收齊' },
      { key: 'documents',    label: '單據', hint: '簽核完成' },
      { key: 'settlement',   label: '精算', hint: '已完結' },
      { key: 'extraExpense', label: '變更', hint: '無送審中' },
    ],

    // 切到矩陣時才抓。**刻意不在 loadCases() 就一起抓**：矩陣是另一個檢視，
    // 多數時候不會用到，而它每件案子要跑十幾次查詢。
    async switchToMatrix() {
      this.caseViewMode = 'matrix'
      if (!this.gmLoaded) await this.loadGateMatrix()
    },

    async loadGateMatrix() {
      try {
        const r = await fetch('/api/quotations/gate-matrix', {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) {
          const d = await r.json()
          this.gateMatrix = d.items || []
          if (d.today) this.today = d.today
        }
      } catch (_e) {}
      // 放在 finally 之外刻意寫成「不管成功失敗都標記載入過」——否則失敗時
      // 表格會永遠停在「載入中…」，比空清單更難判斷發生什麼事。
      this.gmLoaded = true
    },

    // 燈號：關卡的三種狀態直接對應色階。na 是「這件案子沒有這一關」，
    // 畫成空心灰而不是紅燈——舊案件沒有階段/款項/精算資料是正常的。
    // 2026-09-14 修正：blocked 一律是琥珀，不是紅。共通語彙裡 crit 的定義是
    // 「逾期／退回」，「未達成」是 warn——一個做到 2/5 階段的案子是進行中，
    // 不是異常。只有真的有逾期階段時，進度那一關才轉紅。
    // （原本寫成 progress/extraExpense 一律 crit，違反自己訂的色階規則。）
    gateTone(g, row) {
      if (!g) return 'idle'
      if (g.state === 'ok') return 'ok'
      if (g.state === 'na') return 'idle'
      if (g.key === 'progress' && row && row.stageOverdue > 0) return 'crit'
      return 'warn'
    },

    // 整列不染色，只在最左緣留一條脊，取這一列最嚴重的訊號
    rowSpine(row) {
      if (!row) return 'var(--border-light)'
      if (row.stageOverdue > 0) return 'var(--danger)'
      if (row.canClose) return 'var(--success)'
      return row.blockedCount > 0 ? 'var(--warning)' : 'var(--border-light)'
    },

    readyText(row) {
      if (!row) return ''
      if (row.canClose) return row.readyCount + '/5 可結案'
      if (row.blockedCount === 1) return '差 ' + row.blockedLabels[0]
      return row.readyCount + '/5'
    },

    dueText(row) {
      if (!row) return '—'
      if (row.stageOverdue > 0) {
        return row.nextDue ? row.nextDue.slice(5) + ' 逾期 ' + row.stageOverdue + ' 項'
                           : '逾期 ' + row.stageOverdue + ' 項'
      }
      if (!row.nextDue) return '—'
      if (row.nextDue === this.today) return row.nextDue.slice(5) + ' 今日'
      return row.nextDue.slice(5) + (row.nextDueLabel ? ' ' + row.nextDueLabel : '')
    },

    _dueBucket(row) {
      if (row.stageOverdue > 0) return 'overdue'
      if (!row.nextDue) return 'none'
      if (row.nextDue === this.today) return 'today'
      const days = Math.round((new Date(row.nextDue) - new Date(this.today)) / 86400000)
      if (days < 0) return 'overdue'
      return days <= 7 ? 'week' : days <= 30 ? 'month' : 'none'
    },

    get matrixDue() {
      const def = [
        { key: 'overdue', k: '已逾期', l: '件' },
        { key: 'today',   k: '今日到期', l: '件' },
        { key: 'week',    k: '7 天內', l: '件' },
        { key: 'month',   k: '8–30 天', l: '件' },
        { key: 'none',    k: '無排定到期', l: '件' },
      ]
      return def.map(b => ({
        ...b,
        n: this.gateMatrix.filter(r => this._dueBucket(r) === b.key).length,
      }))
    },

    get matrixRows() {
      const me = this.session.displayName || this.session.username || ''
      let rows = this.gateMatrix.filter(r => {
        if (this.gmDue && this._dueBucket(r) !== this.gmDue) return false
        if (this.gmFilter === 'ready' && !r.canClose) return false
        if (this.gmFilter === 'mine' && r.salesPerson !== me) return false
        if (this.gmFilter === 'settling') {
          const s = (r.gates || []).find(g => g.key === 'settlement')
          if (!s || s.state !== 'blocked') return false
        }
        const q = (this.search || '').trim().toLowerCase()
        if (q && !(r.quoteNo || '').toLowerCase().includes(q)
              && !(r.customerName || '').toLowerCase().includes(q)
              && !(r.projectName || '').toLowerCase().includes(q)) return false
        return true
      })
      const by = {
        // 預設排序。這是既有畫面完全給不出、而且最會改變行動順序的資訊：
        // 先把差一步的收掉，再去處理卡住的。
        ready:  (a, b) => (b.canClose - a.canClose) || (b.readyCount - a.readyCount)
                          || (a.blockedCount - b.blockedCount),
        stuck:  (a, b) => (b.stageOverdue - a.stageOverdue) || (b.blockedCount - a.blockedCount),
        amount: (a, b) => (b.total || 0) - (a.total || 0),
      }
      return rows.slice().sort(by[this.gmSort] || by.ready)
    },

    // 點一列回到既有的五頁籤詳情頁——矩陣是它的上層索引，不是取代它
    //: 據點 id -> 名字。**只有一個據點（或讀不到）時回空字串**，
    //  那一行就不顯示 —— 一個永遠一樣的標籤不是資訊，它只是佔位置。
    //  QL15：多據點之後兩個分公司的案子混在同一張表裡，而「這是誰的案子」
    //  是使用者每天都要問的第一個問題。
    locations: [],
    locationName(id) {
      if (!id || !this.locations || this.locations.length < 2) return ''
      const hit = this.locations.find(l => l && l.id === id)
      return hit ? (hit.name || '') : ''
    },

    //: 讀公司資料裡的據點清單。讀不到就留空 => 那一行不顯示，其餘照常。
    async loadLocations() {
      try {
        const r = await fetch(`${this.API}/settings/company-profile`, {
          headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) return
        const d = await r.json()
        this.locations = (d.locations || []).filter(l => l && l.id)
      } catch (_e) { /* 讀不到就不顯示據點 */ }
    },

    // 點關卡格 ⇒ 開案件並停在該關的分頁（沿用深連結 ?tab= 的 _pendingUrlTab，選案件重設分頁後才套）
    async openFromMatrix(quoteNo, gate) {
      this.caseViewMode = 'list'
      if (gate) this._pendingUrlTab = this._gateTab(gate)
      await this.selectCase(quoteNo)
    },

    // 關卡 ⇒ 要去修的分頁。單據關依第一類待簽單據決定。
    _gateTab(g) {
      const byTable = {
        shipping_notes: 'shipping', completion_notes: 'completion',
        contractor_payment_vouchers: 'dispatch', invoice_vouchers: 'fin',
        payment_requests: 'fin', quotations: 'biz',
      }
      // CU5：收款（款項明細、請款單、開票申請）搬到「財務」分頁
      let t = { progress: 'exec', payment: 'fin', settlement: 'fin', extraExpense: 'xexp' }[g && g.key]
      if (g && g.key === 'documents') t = byTable[((g.pendingDocs || [])[0] || {}).table] || 'biz'
      // 財務分頁的「收款」人人看得到；其餘財務區塊（精算）與額外支出只給 canSeeFinancial
      const paymentish = g && (g.key === 'payment' || (g.key === 'documents' && t === 'fin'
        && ['payment_requests', 'invoice_vouchers'].includes(((g.pendingDocs || [])[0] || {}).table)))
      if (!this.canSeeFinancial() && (t === 'xexp' || (t === 'fin' && !paymentish))) t = 'biz'
      return t || 'biz'
    },
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
    // CM1（2026-09-24）：caseRecord 各頂層分段在伺服器上的值（JSON 字串），存檔只送與它
    // 不同的分段並附上它當基準；segConflict＝上次存檔被擋下的分段名稱。
    _segBase: {},
    _segFill: {},
    segConflict: null,
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

    // ── 待辦事項（2026-08-26 專案管理併入案件管理）──
    caseActionItems: [],
    caseActionItemsLoading: false,
    newActionItemText: '',
    addingActionItem: false,

    // ── 專案資訊（成員分配）──
    assignedUserIds: [],
    assignedUsersSaving: false,
    exportingProjectReport: false,
    headerMoreOpen: false,   // CU5：標頭「更多」選單

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

    // ── 叫料（材料訂購，前端 2026-09-11 補上）──
    // 後端端點 2026-09-10 就上線，但一直沒有任何呼叫點，見
    // routers/material_orders.py 檔頭與 WEEKLY-AUDIT §E-1。
    // 存檔刻意走專屬端點而不是併進 saveCase()：saveCase() 會覆蓋整份
    // data_json，兩邊同時存會互相蓋掉；且叫料的權限與已結案規則由後端
    // 那支端點自己守，跟案件整包存檔不一樣。
    materialOrders: [],
    // 預設 true：面板只在 !moLoading 時才渲染「尚無叫料項目」，一旦預設 false，
    // 任何「還沒開始載入」的瞬間都會對使用者說「沒有資料」——那是還沒查就先
    // 回答。額外支出的 xe.loading 本來就是 true，這裡跟它對齊。
    moLoading: true,
    moSaving: false,
    moDirty: false,
    moMsg: '',
    moMsgError: false,

    // ── 額外支出（2026-09-11，從精算頁搬過來）──
    // 資料在 case_extra_expenses 表（DB v75），不再是 settlement.extraItems。
    // loading 預設 true：分頁列在 selected 一設好就出現，若預設 false 會先閃一下
    // 空狀態再跳載入中——叫料那一區踩過同一個坑。
    xe: {
      loading: true, busy: false, items: [], categories: [],
      totalAmount: 0, totalPending: 0, pendingCount: 0,
      msg: '', msgError: false,
    },


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
      const live = this._selectLive()
      this.financeSummaryLoading = true
      this.financeSummary = null
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/finance-summary`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? await r.json() : null
        if (!live()) return
        if (r.ok) this.financeSummary = body
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

    // ── 額外支出（2026-09-11）────────────────────────────────────────────────
    async loadExtraExpenses(quoteNo) {
      if (!quoteNo) return
      const live = this._selectLive()
      // 比照 loadMaterialOrders()：發請求當下記住是哪張單，回應抵達時再比對。
      // 沒有這道守門，使用者在回應飛行途中新增的那一列會被蓋掉（同一天內
      // 在叫料與系統設定兩處各踩過一次）
      this._xeReqFor = quoteNo
      this.xe.loading = true
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/extra-expenses`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        if (this._xeReqFor !== quoteNo) return
        if (r.ok) {
          const d = await r.json()
          // 有未存檔的新列（id 為 null）就不要整包覆蓋，保留使用者打到一半的東西
          const drafts = this.xe.items.filter(i => !i.id)
          const prev = Object.fromEntries(this.xe.items.filter(i => i.id).map(i => [i.id, i]))
          this.xe.items = (d.items || []).map(i => {
            const p = prev[i.id]
            // 變更申請面板：伺服器上還沒有這筆變更申請（changeStatus 空）、但使用者
            // 正在本機填 → 保留他打到一半的內容。少了這道守門，任何一次背景重載
            // 都會把輸入中的東西清空，而且畫面上不會有任何錯誤（同一天內已經在
            // 叫料與系統設定兩處各踩過一次同樣的競態）
            if (p && p._editing && !i.changeStatus) {
              return { ...i, _dirty: false, _editing: true, change: p.change, _changeDirty: p._changeDirty }
            }
            return { ...i, _dirty: false, _editing: !!i.changeStatus, _changeDirty: false }
          }).concat(drafts)
          this.xe.categories = d.categories || []
          this.xe.totalAmount = d.totalAmount || 0
          this.xe.totalPending = d.totalPending || 0
          this.xe.pendingCount = d.pendingCount || 0
        }
      } catch {}
      this.xe.loading = false
    },

    // 可編輯狀態：草稿與已駁回。已核准的金額已經進了成本與報表，簽核中的改了
    // 簽核就失去意義——後端也會擋，這裡擋是為了不要讓人填完才被退回
    xeEditable(x) { return !x.id || x.status === '草稿' || x.status === '已駁回' },

    xeStatusStyle(status) {
      if (status === '已核准') return 'background:#DCFCE7;color:#15803D'
      if (status === '已駁回') return 'background:#FEE2E2;color:#B91C1C'
      if (status === '草稿')   return 'background:#F3F4F6;color:#6B7280'
      return 'background:#FEF3C7;color:#92400E'   // 待審核／簽核中
    },

    xeDirty(i) { this.xe.items[i]._dirty = true; this.xe.msg = '' },

    // 小計只算給畫面即時顯示用；真正的值以後端算的為準（後端不吃前端傳的金額）
    xeRecalc(i) {
      const x = this.xe.items[i]
      x.totalCost = Math.round((Number(x.qty) || 0) * (Number(x.unitCost) || 0) * 100) / 100
      this.xeDirty(i)
    },

    // 支出人「可選可自由文字」：打的字剛好等於某位使用者的顯示名就一併記下
    // username（之後才做得了「某人代墊多少」的彙總），否則只留純文字
    xePayerInput(i) {
      const x = this.xe.items[i]
      const hit = (this.selectableUsers || []).find(
        u => (u.display_name || u.username) === (x.payerName || '').trim())
      x.payerUsername = hit ? hit.username : ''
      this.xeDirty(i)
    },

    xeAdd() {
      this.xe.items.push({
        id: null, category: (this.xe.categories[0] || '其他'), description: '',
        qty: 1, unit: '', unitCost: 0, totalCost: 0, note: '',
        expenseDate: new Date().toISOString().slice(0, 10), docNo: '',
        payerUsername: '', payerName: '',
        createdByName: this.session.displayName || this.session.username || '',
        createdByInferred: false, createdAt: '', updatedAt: '', updatedByName: '',
        status: '草稿', approval: {}, _dirty: true,
      })
      this.xe.msg = ''
    },

    _xeBody(x) {
      return {
        category: x.category, description: (x.description || '').trim(),
        qty: Number(x.qty) || 0, unit: (x.unit || '').trim(),
        unitCost: Number(x.unitCost) || 0, note: (x.note || '').trim(),
        expenseDate: x.expenseDate || '', docNo: (x.docNo || '').trim(),
        payerUsername: x.payerUsername || '', payerName: (x.payerName || '').trim(),
      }
    },

    _xeFail(msg) { this.xe.msgError = true; this.xe.msg = msg; this.xe.busy = false },

    // `AC2`：額外支出的發票日期／付款日（'' ＝清除），專用端點，任何狀態都可以登
    async xeSetDates(x, fields) {
      const quoteNo = this.selected?.quote_no
      if (!quoteNo || !x.id) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/extra-expenses/${x.id}/dates`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(fields)
        })
        const j = await r.json().catch(() => ({}))
        if (!r.ok) { this._xeFail(j.detail || '日期儲存失敗'); return }
        if ('invoiceDate' in j) x.invoiceDate = j.invoiceDate
        if ('paidDate' in j) x.paidDate = j.paidDate
        if (j.updatedAt) x.updatedAt = j.updatedAt
      } catch (e) { this._xeFail('網路錯誤：' + e.message) }
    },

    async xeSave(i) {
      const x = this.xe.items[i]
      if (!(x.description || '').trim()) { this._xeFail('請先填品項說明'); return }
      const quoteNo = this.selected?.quote_no
      if (!quoteNo) return
      this.xe.busy = true; this.xe.msg = ''
      const base = `/api/quotations/${encodeURIComponent(quoteNo)}/extra-expenses`
      try {
        const r = await fetch(x.id ? `${base}/${x.id}` : base, {
          method: x.id ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(this._xeBody(x)),
        })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('儲存失敗：' + (d.detail || r.status)); return
        }
        this.xe.msgError = false; this.xe.msg = '已儲存'
        setTimeout(() => { if (this.xe.msg === '已儲存') this.xe.msg = '' }, 2500)
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(quoteNo)
    },

    async xeSubmit(i) {
      const x = this.xe.items[i]
      if (!x.id) { this._xeFail('請先儲存再送審'); return }
      if (!confirm(`確定送審這筆額外支出？\n\n${x.description}　NT$ ${Math.round(x.totalCost || 0).toLocaleString()}\n\n送審後在簽核完成前不能修改。`)) return
      const quoteNo = this.selected?.quote_no
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(
          `/api/quotations/${encodeURIComponent(quoteNo)}/extra-expenses/${x.id}/submit`,
          { method: 'POST', headers: { Authorization: 'Bearer ' + this.session.token } })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { this._xeFail('送審失敗：' + (d.detail || r.status)); return }
        this.xe.msgError = false
        this.xe.msg = d.autoApproved ? '未設定簽核層，已直接核准' : '已送審'
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(quoteNo)
    },

    async xeUploadFiles(i, evt) {
      const x = this.xe.items[i]
      const files = evt?.target?.files
      if (!x.id || !files || !files.length) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(
          `/api/quotations/${encodeURIComponent(this.selected.quote_no)}/extra-expenses/${x.id}/files`,
          { method: 'POST', headers: { Authorization: 'Bearer ' + this.session.token }, body: fd })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('上傳失敗：' + (d.detail || r.status)); return
        }
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      evt.target.value = ''   // 清掉才能重複選同一個檔案
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    async xeDeleteFile(i, fileId) {
      const x = this.xe.items[i]
      if (!x.id || !confirm('確定刪除這個附件？')) return
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(
          `/api/quotations/${encodeURIComponent(this.selected.quote_no)}/extra-expenses/${x.id}/files/${fileId}`,
          { method: 'DELETE', headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('刪除失敗：' + (d.detail || r.status)); return
        }
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    async xeDelete(i) {
      const x = this.xe.items[i]
      if (!x.id) { this.xe.items.splice(i, 1); return }   // 還沒存過，直接移除
      if (!confirm(`確定刪除「${x.description}」？`)) return
      const quoteNo = this.selected?.quote_no
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(
          `/api/quotations/${encodeURIComponent(quoteNo)}/extra-expenses/${x.id}`,
          { method: 'DELETE', headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('刪除失敗：' + (d.detail || r.status)); return
        }
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(quoteNo)
    },

    // ── 額外支出：已核准之後的變更申請（2026-09-11）──────────────────────────
    //
    // 使用者交辦：已核准後附件上鎖，要改內容得按「編輯」走審核，而且**原核准金額
    // 不動、核准後才生效**。所以這裡刻意分成兩區：上面那排欄位永遠顯示「目前生效
    // 的值」（唯讀），變更申請是另一塊面板，填的是「提議的新值」。使用者一眼就能
    // 對照改了什麼——如果直接讓人在原欄位上改，畫面看起來就像已經生效了。

    xeCanModify(x) {
      // 後端才是最終權威（_can_modify）；這裡擋是為了不要讓人填完才被 403 退回
      if (['superadmin', 'admin'].includes(this.session.role)) return true
      return !!x.createdBy && x.createdBy === this.session.username
    },

    // 附件上鎖：已核准就不能再上傳/刪除。要補憑證請走變更申請的「待核准附件」
    xeFilesLocked(x) { return x.status === '已核准' },

    xeInChange(x)        { return !!x._editing || !!x.changeStatus },
    xeChangeEditable(x)  { return !x.changeStatus || x.changeStatus === '草稿' || x.changeStatus === '已駁回' },
    xeChangeFiles(x)     { return (x.change && x.change.addFiles) || [] },

    xeChangeStatusStyle(s) {
      if (s === '已駁回') return 'background:#FEE2E2;color:#B91C1C'
      if (s === '草稿')   return 'background:#F3F4F6;color:#6B7280'
      return 'background:#FEF3C7;color:#92400E'   // 待審核／簽核中
    },

    xeStartEdit(i) {
      const x = this.xe.items[i]
      if (!this.xeCanModify(x)) { this._xeFail('只有填寫人本人或管理員可以提出變更申請'); return }
      if (!x.change || !Object.keys(x.change).length) {
        // 從目前生效的值開一份提議，使用者只要改動到的欄位
        x.change = {
          category: x.category, description: x.description, qty: x.qty, unit: x.unit,
          unitCost: x.unitCost, totalCost: x.totalCost, note: x.note,
          expenseDate: x.expenseDate, docNo: x.docNo,
          payerUsername: x.payerUsername, payerName: x.payerName, addFiles: [],
        }
      }
      x._editing = true
      x._changeDirty = false
      this.xe.msg = ''
    },

    xeChangeDirty(i) { this.xe.items[i]._changeDirty = true; this.xe.msg = '' },

    xeChangeRecalc(i) {
      const c = this.xe.items[i].change
      c.totalCost = Math.round((Number(c.qty) || 0) * (Number(c.unitCost) || 0) * 100) / 100
      this.xeChangeDirty(i)
    },

    xeChangePayerInput(i) {
      const c = this.xe.items[i].change
      const hit = (this.selectableUsers || []).find(
        u => (u.display_name || u.username) === (c.payerName || '').trim())
      c.payerUsername = hit ? hit.username : ''
      this.xeChangeDirty(i)
    },

    _xeChangeBase(x) {
      return `/api/quotations/${encodeURIComponent(this.selected.quote_no)}/extra-expenses/${x.id}/change-request`
    },

    async xeSaveChange(i) {
      const x = this.xe.items[i]
      const c = x.change || {}
      if (!(c.description || '').trim()) { this._xeFail('請先填品項說明'); return }
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(this._xeChangeBase(x), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({
            category: c.category, description: (c.description || '').trim(),
            qty: Number(c.qty) || 0, unit: (c.unit || '').trim(),
            unitCost: Number(c.unitCost) || 0, note: (c.note || '').trim(),
            expenseDate: c.expenseDate || '', docNo: (c.docNo || '').trim(),
            payerUsername: c.payerUsername || '', payerName: (c.payerName || '').trim(),
          }),
        })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('儲存失敗：' + (d.detail || r.status)); return
        }
        this.xe.msgError = false; this.xe.msg = '變更申請已存草稿，按「送審」才會進簽核'
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    async xeSubmitChange(i) {
      const x = this.xe.items[i]
      const c = x.change || {}
      if (x._changeDirty) { this._xeFail('請先儲存變更申請再送審'); return }
      if (!x.changeStatus) { this._xeFail('請先儲存變更申請再送審'); return }
      const oldA = Math.round(x.totalCost || 0).toLocaleString()
      const newA = Math.round(c.totalCost || 0).toLocaleString()
      if (!confirm(`確定送審這筆變更申請？\n\n${c.description}\nNT$ ${oldA} → NT$ ${newA}\n\n`
                 + `核准之前，這筆額外支出維持原本的 NT$ ${oldA}，報表數字不會變動。`)) return
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(`${this._xeChangeBase(x)}/submit`, {
          method: 'POST', headers: { Authorization: 'Bearer ' + this.session.token } })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { this._xeFail('送審失敗：' + (d.detail || r.status)); return }
        this.xe.msgError = false
        this.xe.msg = d.autoApproved ? '未設定簽核層，變更已直接生效' : '變更申請已送審'
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    async xeCancelChange(i) {
      const x = this.xe.items[i]
      // 還沒送到後端的，純粹關掉面板就好
      if (!x.changeStatus) { x._editing = false; x.change = {}; x._changeDirty = false; return }
      if (!confirm('確定撤銷這筆變更申請？已上傳的待核准附件會一併刪除。')) return
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(this._xeChangeBase(x), {
          method: 'DELETE', headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('撤銷失敗：' + (d.detail || r.status)); return
        }
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    async xeUploadChangeFiles(i, evt) {
      const x = this.xe.items[i]
      const files = evt?.target?.files
      if (!files || !files.length) return
      if (!x.changeStatus) { this._xeFail('請先按「儲存變更」建立草稿，再上傳待核准附件'); evt.target.value = ''; return }
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(`${this._xeChangeBase(x)}/files`, {
          method: 'POST', headers: { Authorization: 'Bearer ' + this.session.token }, body: fd })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('上傳失敗：' + (d.detail || r.status)); return
        }
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      evt.target.value = ''   // 清掉才能重複選同一個檔案
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    async xeDeleteChangeFile(i, fileId) {
      const x = this.xe.items[i]
      if (!confirm('確定刪除這個待核准附件？')) return
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(`${this._xeChangeBase(x)}/files/${fileId}`, {
          method: 'DELETE', headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('刪除失敗：' + (d.detail || r.status)); return
        }
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    // ── 完工單（2026-09-12）────────────────────────────────────────────────
    //
    // 使用者交辦：「在案件管理內增加完工單的選項，參考出貨單的形式跟內容建立完工單，
    // 一樣走流程申請完工。」所以這一整段刻意比照上面的出貨單：同一套狀態機、同一套
    // 分層簽核、同一套回簽。欄位差異與理由見 backend/db.py::_m077_completion_notes()。
    //
    // ⚠️ 後端 list 端點回的是 `{items: [...]}`（新端點的慣例），不是出貨單那種裸陣列，
    //    照抄 `= await r.json()` 會拿到一個物件、畫面永遠空白且沒有任何錯誤。
    // 清單在案件管理、填寫在獨立頁面 completion-note-form.html（比照報價單清單與
    // 報價單表單的分工）。所以這裡**只留清單與狀態動作**，不再有表單狀態。
    completionNotes: [],
    completionNotesLoading: false,
    completionPreviewFetching: false,

    async loadCompletionNotes(quoteNo) {
      if (!quoteNo) return
      const live = this._selectLive()
      // 比照 loadExtraExpenses()：記住發請求當下是哪張單，回應抵達時再比對。
      // 少了這道守門，切案件切太快就會把 A 案的完工單畫在 B 案底下
      this._cnReqFor = quoteNo
      this.completionNotesLoading = true
      try {
        const r = await fetch(`/api/completion-notes?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        if (this._cnReqFor !== quoteNo) return
        const body = r.ok ? (await r.json()).items || [] : null
        if (!live()) return
        if (r.ok) this.completionNotes = body
      } catch {}
      this.completionNotesLoading = false
    },

    async deleteCompletionNote(n) {
      if (!confirm(`確定刪除完工單「${n.noteNo}」？`)) return
      await this._cnAction(n, '', 'DELETE', '刪除失敗')
    },

    async submitCompletionNote(n) {
      const unfinished = n.unfinishedCount || 0
      const warn = unfinished
        ? `\n\n⚠️ 這張單有 ${unfinished} 項未完成，請確認「遺留事項」已寫清楚。`
        : ''
      if (!confirm(`確定送出完工單「${n.noteNo}」申請完工？${warn}`)) return
      await this._cnAction(n, '/submit', 'POST', '送出失敗')
    },

    async approveCompletionNote(n) {
      // 同一人連任多層時一次簽完（2026-09-15，見 static/approval-cascade.js）。
      // 清單資料沒帶 approval.tiers 時算出來是空陣列，行為跟以前一樣。
      const _appr = n.approval || {}
      const _casc = window.MotrixApproval.selfCascadeTiers(
        _appr.tiers || [], _appr.currentTier ?? 0, this.session.username, [])
      if (!confirm(`確定簽核完工單「${n.noteNo}」？` + window.MotrixApproval.cascadeNote(_casc))) return
      await this._cnAction(n, '/approve', 'POST', '簽核失敗', { cascade: _casc.length > 0 })
    },

    async rejectCompletionNote(n) {
      const note = prompt(`退回完工單「${n.noteNo}」，可填寫退回原因（選填）：`)
      if (note === null) return
      await this._cnAction(n, '/reject', 'POST', '退回失敗', { note })
    },

    async revokeCompletionApproval(n) {
      const note = prompt(`撤銷完工單「${n.noteNo}」的核准？將退回草稿。\n\n可填寫撤銷原因（選填）：`)
      if (note === null) return
      await this._cnAction(n, '/revoke-approval', 'POST', '撤銷失敗', { note })
    },

    async toggleCompletionSigned(n, action) {
      const msg = action === 'sign'
        ? `確定標記完工單「${n.noteNo}」客戶已驗收簽回？`
        : `確定取消完工單「${n.noteNo}」的驗收標記？`
      if (!confirm(msg)) return
      const note = action === 'sign' ? (prompt('備註（選填，例如驗收人姓名或方式）：') || '') : ''
      await this._cnAction(n, '/signed-toggle', 'POST', '操作失敗', { action, note })
    },

    // 六個動作的差別只有路徑與 body，抽出來免得複製六份各自漂移
    async _cnAction(n, path, method, failMsg, body) {
      try {
        const opts = { method, headers: { Authorization: 'Bearer ' + this.session.token } }
        if (body !== undefined) {
          opts.headers['Content-Type'] = 'application/json'
          opts.body = JSON.stringify(body)
        }
        const r = await fetch(`/api/completion-notes/${n.noteNo}${path}`, opts)
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || failMsg); return }
        await this.loadCompletionNotes(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async previewCompletionPdf(n) {
      this.completionPreviewFetching = true
      try {
        const r = await fetch(`/api/completion-notes/${n.noteNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗'); return }
        const blob = await r.blob()
        const url = URL.createObjectURL(blob)
        window.open(url, '_blank')
        setTimeout(() => URL.revokeObjectURL(url), 60000)
        fetch(`/api/completion-notes/${n.noteNo}/export?mode=preview`, {
          method: 'POST', headers: { Authorization: 'Bearer ' + this.session.token }
        }).catch(() => {})
      } catch (e) { alert('網路錯誤：' + e.message) }
      this.completionPreviewFetching = false
    },

    _completionStatusLabel(s) { return s || '草稿' },
    _completionStatusClass(s) {
      if (s === '已核准') return 'badge-green'
      if (s === '待審核' || s === '簽核中') return 'badge-amber'
      return 'badge-gray'
    },

    // ── 叫料（材料訂購）────────────────────────────────────────────────────
    async loadMaterialOrders(quoteNo) {
      if (!quoteNo) return
      const live = this._selectLive()
      // 發出請求的當下就記住是哪張單，回應抵達時再比對一次——比照 reports.js
      // 的 loadExpenses()／loadReceivables() 競態修法（§12 2026-09-10「更晚」）。
      // 這裡實測抓到過同一類問題：財務分頁一打開就發 GET，使用者在回應回來前
      // 按「＋ 新增項目」，回應抵達時 this.materialOrders = [...] 會把剛新增的
      // 那一列整個蓋掉，而且畫面上不會有任何錯誤，人只會覺得「按了沒反應」。
      // 刻意不在這裡清空 materialOrders／moDirty：切換案件時 selectCase() 已經
      // 清過一次，這裡再清一次的話，「載入尚未回來就被呼叫第二次」會在使用者
      // 已經打字之後同步把畫面清掉，連下面的 moDirty 守門都來不及擋
      this._moReqFor = quoteNo
      this.moLoading = true
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/material-orders`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        // 已經切到別的案件：這份回應過期，丟掉（不然會把別張單的叫料貼上來）
        if (this._moReqFor !== quoteNo) return
        // 使用者已經動手編輯：保留他打的東西，不要用伺服器版本覆蓋
        if (r.ok && this.moDirty) { this.moLoading = false; return }
        if (r.ok) {
          // 這份清單是自由格式 JSON（早期資料或人工改過的 data_json 不保證
          // 欄位齊全），跟後端 GET 端點同款作法：每個欄位都給預設值，
          // 不然 x-model 綁到 undefined 會讓整列輸入框變成不受控
          this.materialOrders = ((await r.json()).materialOrders || []).map(o => ({
            itemId:     o.itemId || this._moNewId(),
            itemName:   o.itemName || '',
            quantity:   Number(o.quantity) || 0,
            unit:       o.unit || '',
            unitPrice:  Number(o.unitPrice) || 0,
            totalPrice: Number(o.totalPrice) || 0,
            paidStatus: ['pending', 'partial', 'paid'].includes(o.paidStatus) ? o.paidStatus : 'pending',
            paidAmount: Number(o.paidAmount) || 0,
            paidDate:   o.paidDate || '',
            notes:      o.notes || '',
            invoiceDate: o.invoiceDate || ''   // `AC2`
          }))
        }
      } catch {}
      this.moLoading = false
    },

    // crypto.randomUUID() 在 HTTP 明文頁面下不存在（非安全上下文），正式機是
    // HTTPS 但開發機偶爾用 http://localhost 開，所以留一條退路
    _moNewId() {
      if (window.crypto && crypto.randomUUID) return crypto.randomUUID()
      return 'mo-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10)
    },

    // 權限條件跟後端 PATCH 端點一致（admin+ 或 project_manage 模組），外加
    // 已結案擋下來。前端擋不是安全機制，是不要讓使用者填完才被退回
    moCanEdit() {
      if (this.cr?.dealTag === '已結案') return false
      const m = this.session.modules || []
      return ['superadmin', 'admin'].includes(this.session.role) || m.includes('project_manage')
    },

    moTotals() {
      let total = 0, paid = 0
      for (const m of this.materialOrders) {
        total += Number(m.totalPrice) || 0
        paid  += Number(m.paidAmount) || 0
      }
      return { total, paid, unpaid: total - paid }
    },

    moAddItem() {
      this.materialOrders.push({
        itemId: this._moNewId(), itemName: '', quantity: 1, unit: '', unitPrice: 0,
        totalPrice: 0, paidStatus: 'pending', paidAmount: 0, paidDate: '', notes: '', invoiceDate: ''
      })
      this.moDirty = true
      this.moMsg = ''
    },

    // 2026-09-24（N11，使用者裁示「刪除確認全部都加」）：叫料品項、派工／出貨表單品項列、
    // 負責人移除也要先確認；訊息寫出要刪的名稱。
    moRemoveItem(i) {
      const m = this.materialOrders[i]
      if (!confirm(`確定要刪除叫料品項「${(m && m.itemName) || '未命名'}」？\n\n按「儲存」之後才會寫入。`)) return
      this.materialOrders.splice(i, 1)
      this.moDirty = true
      this.moMsg = ''
    },

    // 小計一律由這裡算、使用者不能手填——後端會用
    // abs(totalPrice - 數量×單價) > 0.01 直接回 400。
    // 刻意不把 m.quantity / m.unitPrice 正規化寫回去：使用者打到一半的
    // 「1.」會被改成「1」，游標跳掉很難打字；正規化留到 moSave() 送出前做
    moRecalc(i) {
      const m = this.materialOrders[i]
      const q = Number(m.quantity) || 0
      const p = Number(m.unitPrice) || 0
      m.totalPrice = Math.round(q * p * 100) / 100
      if (m.paidStatus === 'paid') m.paidAmount = m.totalPrice
      else if (m.paidStatus === 'pending') { m.paidAmount = 0; m.paidDate = '' }
      this.moDirty = true
    },

    moOnStatusChange(i) {
      const m = this.materialOrders[i]
      const today = new Date().toISOString().slice(0, 10)
      if (m.paidStatus === 'pending') { m.paidAmount = 0; m.paidDate = '' }
      else {
        if (!m.paidDate) m.paidDate = today
        if (m.paidStatus === 'paid') m.paidAmount = Number(m.totalPrice) || 0
      }
      this.moDirty = true
    },

    // `AC2`：只登一筆叫料的發票日期（專用端點；任何案件狀態都可以，不動金額）
    async moSetInvoiceDate(m) {
      const quoteNo = this.selected?.quote_no
      if (!quoteNo || !m.itemId) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/material-orders/${encodeURIComponent(m.itemId)}/invoice-date`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ invoiceDate: m.invoiceDate || '' })
        })
        const d = await r.json().catch(() => ({}))
        this.moMsgError = !r.ok
        this.moMsg = r.ok ? '發票日期已儲存' : ('發票日期儲存失敗：' + (d.detail || r.status))
        if (r.ok) m.invoiceDate = d.invoiceDate
      } catch (e) {
        this.moMsgError = true
        this.moMsg = '網路錯誤：' + e.message
      }
    },

    async moSave() {
      if (this.moSaving) return
      const quoteNo = this.selected?.quote_no
      if (!quoteNo) return

      // 送出前正規化＋先擋一次。後端這些規則都會再驗一次，這裡擋只是為了
      // 給看得懂的中文訊息（後端回的 detail 會指名項目，但撞到才看到）
      const payload = []
      for (const m of this.materialOrders) {
        const name = (m.itemName || '').trim()
        if (!name) { this.moMsgError = true; this.moMsg = '有項目還沒填名稱'; return }
        const quantity  = Math.max(0, Number(m.quantity) || 0)
        const unitPrice = Math.max(0, Number(m.unitPrice) || 0)
        const totalPrice = Math.round(quantity * unitPrice * 100) / 100
        let paidAmount = 0
        let paidDate = null
        if (m.paidStatus === 'paid') {
          paidAmount = totalPrice
          paidDate = m.paidDate || ''
        } else if (m.paidStatus === 'partial') {
          paidAmount = Math.round((Number(m.paidAmount) || 0) * 100) / 100
          paidDate = m.paidDate || ''
          if (paidAmount > totalPrice) { this.moMsgError = true; this.moMsg = `「${name}」的已付金額大於小計`; return }
        }
        if (m.paidStatus !== 'pending' && !paidDate) {
          this.moMsgError = true; this.moMsg = `「${name}」標為已付，必須填已付日期`; return
        }
        payload.push({
          itemId: m.itemId || this._moNewId(), itemName: name,
          quantity, unit: (m.unit || '').trim(), unitPrice, totalPrice,
          paidStatus: m.paidStatus, paidAmount,
          paidDate: m.paidStatus === 'pending' ? null : paidDate,
          notes: (m.notes || '').trim(),
          // `AC2`：整份覆寫的端點——少帶這一鍵，已登錄的發票日期就會在下次存檔時被抹掉
          invoiceDate: m.invoiceDate || ''
        })
      }

      this.moSaving = true
      this.moMsg = ''
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/material-orders`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ materialOrders: payload })
        })
        if (r.ok) {
          this.moDirty = false
          this.moMsgError = false
          this.moMsg = '已儲存'
          setTimeout(() => { if (!this.moDirty) this.moMsg = '' }, 2500)
        } else {
          const d = await r.json().catch(() => ({}))
          this.moMsgError = true
          this.moMsg = '儲存失敗：' + (d.detail || r.status)
        }
      } catch (e) {
        this.moMsgError = true
        this.moMsg = '網路錯誤：' + e.message
      }
      this.moSaving = false
    },

    // ── 分頁狀態進 URL（2026-09-14）───────────────────────────────────
    // 原本重新整理或把連結貼給同事，都會跳回第一個分頁。營運報表已經有
    // ?tab= 的深連結模式，這裡比照。
    // 刻意不改那 8 個 inline @click（每個都還帶自己的載入呼叫，逐一改容易漏），
    // 改用 $watch 集中處理。
    _pendingUrlTab: null,
    _initTabFromUrl() {
      var t = new URLSearchParams(location.search).get('tab')
      var valid = ['biz','exec','dispatch','shipping','completion','feed','fin','xexp']
      // 只記下來，不直接套：選案件時會把 activeTab 重設成 'biz'（那行是刻意的，
      // 見 selectCase 的註解），所以要在重設之後才套，而且只套第一次。
      if (t && valid.indexOf(t) >= 0) this._pendingUrlTab = t
      var self = this
      this.$watch('activeTab', function (v) {
        var u = new URL(location.href)
        u.searchParams.set('tab', v)
        history.replaceState(null, '', u)
      })
    },

    async init() {
      // 2026-09-24：離頁警告（sidebar.js）跟著主表單的 dirty 走：setDirty() 設 true，
      // 存檔成功（dirty 轉 false）時清掉。
      this.$watch('dirty', v => { window.motrixIsDirty = !!v })
      this._initTabFromUrl()
      // QL15：據點清單。不 await —— 它只決定一行小字要不要顯示，
      // 而這一頁的主體（案件矩陣）不應該等它。
      this.loadLocations()
      // Alpine 3 會自動呼叫資料物件上的 init()，而 case-management.html 的
      // <body> 又寫了一次 x-init="init()"，所以整個 init() 每次開頁都跑兩遍：
      // 所有 API 都發兩次，並且第二次 selectCase() 會把第一次已經載好的狀態
      // 整個重置。先前看不出來是因為這頁的子清單全部是唯讀的，重載一次
      // 看不出差別；2026-09-11 新增可編輯的叫料清單後才暴露——使用者在兩次
      // init 中間按「＋新增項目」，那一列會被第二次載入默默抹掉。
      // 這裡只修本頁；全站共 50 個頁面有同樣的 x-init 寫法，屬於独立課題。
      if (this._initDone) return
      this._initDone = true
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
      // UR1：已讀改存伺服器（逐筆、排除本人）。上一頁回來／其他分頁標了已讀 ⇒ 重抓。
      //   舊的 `motrix_casemgmt_read_at` 由 notif.js 一次性遷移成伺服器端的清單基準。
      window.addEventListener('motrix:reads-changed', () => this.loadCaseActivity())
      // 跨分頁樂觀已讀：只合併那一筆，不整包重抓；伺服器拒絕時還原。
      window.addEventListener('motrix:item-read', e => {
        if (e.detail.kind !== 'case' || !this.caseActivity[e.detail.key]) return
        const m = { ...this.caseActivity }
        delete m[e.detail.key]
        this.caseActivity = m
        this._readAtLocal = { ...(this._readAtLocal || {}), [e.detail.key]: Date.now() }
      })
      window.addEventListener('motrix:item-read-failed', e => {
        if (e.detail.kind !== 'case') return
        const k = e.detail.key
        if (!(this.cases.some(c => c.quote_no === k))) return
        const loc = { ...(this._readAtLocal || {}) }
        delete loc[k]
        this._readAtLocal = loc
        this.caseActivity = { ...this.caseActivity, [k]: true }
      })
      this.caseSortPref = await loadListPref(s.token, 'case_list')
      await this.loadCases()
      this.loadVendors()
      const _qp = new URLSearchParams(location.search).get('q')
      if (_qp) {
        // CM6：清單分頁後，目標可能不在第一頁 ⇒ 用同一支清單端點（同一套權限）精確找那一件。
        // `AC2`：已結案案件的連結（營運報表「待補登」清單會連過來）要切到「已結案」頁籤。
        const _found = await this._findCase(_qp)
        if (_found && _found.deal_tag === '已結案' && this.listTab !== '已結案') {
          this.listTab = '已結案'
          this.loadCases()
        }
        if (_found) await this.selectCase(_found.quote_no)
      }
    },

    async _findCase(quoteNo) {
      try {
        const qs = new URLSearchParams({ deal_tag: '已成案,已結案', q: quoteNo, limit: '20' })
        const r = await fetch('/api/quotations?' + qs, { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) return null
        return ((await r.json()).items || []).find(c => c.quote_no === quoteNo) || null
      } catch { return null }
    },

    // ── CM6（2026-09-24）：清單由伺服器搜尋／篩選／排序／分頁 ────────────────
    // 原本一次拉 limit=500 在前端篩 ⇒ 第 501 件以後看不到也搜不到。現在頁籤、搜尋、排序都送到
    // 伺服器，一頁 casePageSize 件，「載入更多」往後接；摘要數字另打一次 counts（全部案件）。
    // 「只看有新動態」與「自訂（拖曳）排序」仍只作用在已載入的案件上。
    casePageSize: 100,
    // CM7：常用篩選（可疊加，送伺服器）
    caseQuick: { mine: false, stage_overdue: false, recv_overdue: false, missing_docs: false },
    quickFilterDefs: [
      { key: 'mine',          label: '我負責的', count: 'mine' },
      { key: 'stage_overdue', label: '逾期階段', count: 'stageOverdueCases' },
      { key: 'recv_overdue',  label: '應收逾期', count: 'recvOverdue' },
      { key: 'missing_docs',  label: '缺單據',   count: 'missingDocs',
        hint: '缺發票（已收款未登錄發票號碼），或執行階段全部完成卻缺完工單／出貨單' },
    ],
    caseTotal: 0,
    caseCounts: null,
    caseLoadingMore: false,
    _casesSeq: 0,
    _searchTimer: null,

    _caseQuery(offset) {
      const qs = new URLSearchParams({ limit: String(this.casePageSize), offset: String(offset) })
      const board = this.caseViewMode === 'board'
      if (board) qs.set('deal_tag', '已成案,已結案')
      else if (this.listTab === '已結案') qs.set('deal_tag', '已結案')
      else if (this.listTab === '待精算') { qs.set('deal_tag', '已成案,已結案'); qs.set('settle', 'draft') }
      else qs.set('deal_tag', '已成案')        // 「全部」與「已成案」：未結案的案件
      const q = (this.search || '').trim()
      if (q) qs.set('q', q)
      for (const [k, on] of Object.entries(this.caseQuick)) if (on) qs.set(k, '1')
      if (this.unreadOnly) qs.set('unread', '1')
      const mode = this.caseSortPref?.sortMode
      if (mode && mode !== 'custom') { qs.set('sort', mode); qs.set('dir', this.caseSortPref.sortDir || 'desc') }
      return qs
    },

    async loadCases() {
      const seq = ++this._casesSeq
      this.loading = true
      try {
        const r = await fetch('/api/quotations?' + this._caseQuery(0), {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (seq !== this._casesSeq) return          // 較新的查詢已送出（連續打字／切頁籤）
        if (r.ok) {
          const data = await r.json()
          if (seq !== this._casesSeq) return
          this.cases = data.items || []
          this.caseTotal = data.total || 0
        }
      } catch {}
      if (seq !== this._casesSeq) return
      this.loading = false
      this.filterCases()
      this.loadCaseActivity()
      this.loadCaseCounts()
    },

    async loadMoreCases() {
      if (this.caseLoadingMore || this.cases.length >= this.caseTotal) return
      const seq = this._casesSeq
      this.caseLoadingMore = true
      try {
        const r = await fetch('/api/quotations?' + this._caseQuery(this.cases.length), {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok && seq === this._casesSeq) {
          const data = await r.json()
          if (seq === this._casesSeq) {
            const have = new Set(this.cases.map(c => c.quote_no))
            this.cases = this.cases.concat((data.items || []).filter(c => !have.has(c.quote_no)))
            this.caseTotal = data.total || 0
            this.filterCases()
            this.loadCaseActivity()
          }
        }
      } catch {}
      this.caseLoadingMore = false
    },

    // 摘要與頁籤徽章：全部已成案／已結案案件（不受搜尋與分頁影響）
    async loadCaseCounts() {
      try {
        const qs = new URLSearchParams({ deal_tag: '已成案,已結案', counts: '1', limit: '0' })
        const r = await fetch('/api/quotations?' + qs, { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) this.caseCounts = (await r.json()).counts || null
      } catch {}
    },

    onCaseSearchInput() {
      clearTimeout(this._searchTimer)
      this._searchTimer = setTimeout(() => this.loadCases(), 300)
    },

    setListTab(tab) {
      this.listTab = tab
      this.loadCases()
    },

    // ── CM10（2026-09-24）：批次操作 ─────────────────────────────────────────
    // 多選模式下卡片出現勾選框；批次改執行負責／成員（管理員以上，只改進行中的案件）、批次匯出 Excel。
    batchMode: false,
    batchSel: {},
    batchExec: '',
    batchMember: '',
    batchBusy: false,
    batchMsg: '',

    canBatchAssign() { return ['superadmin', 'admin'].includes(this.session.role) },
    batchCount() { return Object.keys(this.batchSel).length },
    batchNos() { return Object.keys(this.batchSel) },
    isBatchSel(c) { return !!this.batchSel[c.quote_no] },

    toggleBatchMode() {
      this.batchMode = !this.batchMode
      this.batchSel = {}
      this.batchMsg = ''
    },
    toggleBatch(c) {
      const m = { ...this.batchSel }
      if (m[c.quote_no]) delete m[c.quote_no]
      else m[c.quote_no] = true
      this.batchSel = m
    },
    batchSelectPage() {
      const m = { ...this.batchSel }
      for (const c of this.filteredCases) m[c.quote_no] = true
      this.batchSel = m
    },

    async batchAssign(kind) {
      const nos = this.batchNos()
      if (!nos.length || this.batchBusy) return
      const body = { quote_nos: nos }
      if (kind === 'executor') {
        if (!this.batchExec) { this.batchMsg = '請先選擇執行負責'; return }
        body.executor = this.batchExec === '__clear__' ? '' : this.batchExec
      } else {
        if (!this.batchMember) { this.batchMsg = '請先選擇成員'; return }
        body[kind === 'add' ? 'add_members' : 'remove_members'] = [Number(this.batchMember)]
      }
      this.batchBusy = true
      this.batchMsg = ''
      try {
        const r = await fetch('/api/case-batch/assign', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(body),
        })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { this.batchMsg = (typeof d.detail === 'string' && d.detail) || '批次變更失敗'; return }
        const sk = d.skipped || []
        this.batchMsg = `已變更 ${(d.updated || []).length} 件` + (sk.length
          ? `；略過 ${sk.length} 件（${sk.map(s => s.quoteNo + '：' + s.reason).join('、')}）` : '')
        // 目前開著的案件也在名單裡且沒有未存變更 ⇒ 重新載入，畫面才看得到新的負責人／成員
        if (this.selected && (d.updated || []).includes(this.selected.quote_no) && !this.dirty) {
          this.selectCase(this.selected.quote_no)
        }
        this.loadCases()
      } catch {
        this.batchMsg = '網路錯誤，請稍後再試'
      } finally {
        this.batchBusy = false
      }
    },

    async batchExport() {
      const nos = this.batchNos()
      if (!nos.length || this.batchBusy) return
      this.batchBusy = true
      this.batchMsg = ''
      try {
        const r = await fetch('/api/case-batch/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ quote_nos: nos }),
        })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this.batchMsg = (typeof d.detail === 'string' && d.detail) || '匯出失敗'
          return
        }
        const blob = await r.blob()
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = '案件匯出.xlsx'
        document.body.appendChild(a)
        a.click()
        a.remove()
        setTimeout(() => URL.revokeObjectURL(a.href), 5000)
      } catch {
        this.batchMsg = '網路錯誤，請稍後再試'
      } finally {
        this.batchBusy = false
      }
    },

    toggleQuick(key) {
      this.caseQuick = { ...this.caseQuick, [key]: !this.caseQuick[key] }
      this.loadCases()
    },

    toggleUnreadOnly() {
      this.unreadOnly = !this.unreadOnly
      this.loadCases()
    },

    // 卡片上標出缺哪一種單據
    missingDocTags(c) {
      const t = []
      if (c.missing_invoice) t.push('缺發票')
      if (c.missing_completion) t.push('缺完工單')
      if (c.missing_shipping) t.push('缺出貨單')
      return t
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

    // 件數是另一支非同步請求；還沒到之前回 null（不可以退回已載入那一頁的件數冒充總數）
    summaryTotal()   { return this.caseCounts ? this.caseCounts.all : null },
    summaryActive()  { return this.caseCounts ? this.caseCounts.active : 0 },
    summaryClosed()  { return this.caseCounts ? this.caseCounts.closed : 0 },
    summaryOverdue() { return this.caseCounts ? this.caseCounts.overdueStages : 0 },
    summarySettling(){ return this.caseCounts ? this.caseCounts.settling : 0 },

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

    // UR1：`caseActivity` 改存「伺服器判斷的未讀案件」`{quote_no: true}`
    //   （同三個來源：案件動態／工作日誌／每日工作完成，但**依作者排除本人**、逐筆已讀）。
    //   原本是每筆的最後動態時間 vs 整個清單一個 localStorage 時間戳。
    // ⚠️ 先渲染再非同步載入＝競態：查詢送出之後、回應抵達之前使用者點了某一筆，
    //    伺服器算這份回應時還沒有那筆已讀 ⇒ 不可以讓它把剛點過的那一筆蓋回未讀。
    async loadCaseActivity() {
      const quoteNos = this.cases.map(c => c.quote_no).filter(Boolean)
      if (!quoteNos.length || !window.MotrixReads) { this.caseActivity = {}; return }
      const t0 = Date.now()
      const got = await window.MotrixReads.unread('case', quoteNos)
      const m = {}
      got.forEach(k => { if (!((this._readAtLocal || {})[k] >= t0)) m[k] = true })
      this.caseActivity = m
    },

    isUnread(c) {
      return !!(c && this.caseActivity[c.quote_no])
    },

    /** 真的切換到這一筆之後才呼叫：當下先清標記，再送出（不等回應）。 */
    _markCaseRead(quoteNo) {
      if (!quoteNo || !this.caseActivity[quoteNo]) return
      const m = { ...this.caseActivity }
      delete m[quoteNo]
      this.caseActivity = m
      this._readAtLocal = { ...(this._readAtLocal || {}), [quoteNo]: Date.now() }
      if (window.MotrixReads) window.MotrixReads.mark('case', quoteNo)
    },

    // CM7：未讀件數是全部案件（伺服器），不是已載入的那一頁
    unreadCount() {
      return this.caseCounts ? (this.caseCounts.unread || 0) : this.cases.filter(c => this.isUnread(c)).length
    },

    async markAllRead() {
      // 全部未讀（不只已載入的）：先向伺服器要清單再逐筆標記
      let keys = Object.keys(this.caseActivity)
      try {
        const qs = new URLSearchParams({ deal_tag: '已成案,已結案', unread: '1', limit: '500' })
        const r = await fetch('/api/quotations?' + qs, { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) keys = [...new Set(keys.concat(((await r.json()).items || []).map(c => c.quote_no)))]
      } catch {}
      this.caseActivity = {}
      const now = Date.now()
      this._readAtLocal = { ...(this._readAtLocal || {}), ...Object.fromEntries(keys.map(k => [k, now])) }
      if (window.MotrixReads) keys.forEach(k => window.MotrixReads.mark('case', k))
      this.unreadOnly = false
      if (this.caseCounts) this.caseCounts = { ...this.caseCounts, unread: 0 }
      this.loadCases()
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
      // CM7：「只看有新動態」由伺服器篩（全部案件）；這裡不再用 caseActivity 過濾——
      //      它是之後才非同步載入的，先過濾會把伺服器回來的那幾筆濾掉
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
      this.loadCases()
      await saveListPref(this.session.token, 'case_list', this.caseSortPref)
    },
    async toggleCaseSortDir() {
      this.caseSortPref.sortDir = this.caseSortPref.sortDir === 'asc' ? 'desc' : 'asc'
      this.loadCases()
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

    // 連點兩件時，只有最後點的那一件可以落地（先點的回應較晚抵達時丟掉）。
    // _selectLive() 回傳「這次載入還算數嗎」：之後又選了案件就回 false。selectCase 與它
    // 發出的每支子載入在每個 await 之後都先問它，前一件的後段不會寫進目前這一件的畫面與存檔。
    _selectSeq: 0,
    _selectLive() {
      const seq = this._selectSeq
      return () => seq === this._selectSeq
    },

    async selectCase(quoteNo) {
      // 2026-09-24：有未存的變更時先存完再切換。原本這裡直接取消待存計時器、
      // 下面再 dirty=false ⇒ 打完字 1.5 秒內切換案件，剛打的內容就消失。
      clearTimeout(this._autoSaveTimer)
      if (this.dirty && this.selected) {
        while (this.saving) await new Promise(res => setTimeout(res, 50))
        if (this.dirty) await this.saveCaseRecord()
        if (this.dirty && !confirm(`上一張案件（${this.selected.quote_no}）沒有存成功：${this.saveMsg || '未儲存'}\n\n仍要切換並放棄這些變更？`)) {
          return
        }
      }
      // 確定要切換才遞增：使用者取消切換時，目前這一件進行中的載入仍算數
      ++this._selectSeq
      const live = this._selectLive()
      try {
        const r = await fetch('/api/quotations/' + quoteNo, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) return
        const data = await r.json()
        if (!live()) return
        this.selected = data
        // UR1：放在「真的切換過去」之後——上面取消切換（存檔失敗選「否」）時 return，
        //      那一筆的未讀標記必須還在。
        this._markCaseRead(quoteNo)
        this.loadCaseHealth(quoteNo)
        this.loadCaseLinks(quoteNo)
        // 同時編輯警示（2026-09-14）：切換案件時自動釋放前一張、回報這一張
        if (window.MotrixPresence) window.MotrixPresence.start('case', quoteNo)
        // 分頁/檢視狀態必須在任何 await 之前就重設完（2026-09-09 修）：
        // this.selected 一設定，分頁列就立刻渲染給使用者點；但下面
        // _seedDefaultStagesIfEmpty() 對全新案件會連打 5 次建立階段的 API，
        // 這段期間如果使用者已經切到別的分頁（例如「財務」），原本寫在 await
        // 之後的 activeTab='biz' 會把人硬彈回「案件資訊」——階段建立越慢、
        // 被彈回的機率越高。這幾個都是純檢視狀態，提前重設沒有副作用。
        this.activeTab = 'biz'
        // 深連結 ?tab=：只在載入後第一次選案件時套用，之後切案件維持回到「案件資訊」
        if (this._pendingUrlTab) { this.activeTab = this._pendingUrlTab; this._pendingUrlTab = null }
        this.execSubTab = 'progress'
        // 叫料的狀態也屬於「必須在 await 之前重設完」那一類（2026-09-14 修）：
        // selected 一設定分頁列就渲染出來，使用者可以立刻點「財務」，而下面
        // ensureCaseRecord()／_seedDefaultStagesIfEmpty() 是會發網路請求的 await
        // ——原本 moLoading 要等到那之後才立起來，這段空窗期點進財務分頁就會看到
        // 「尚無叫料項目」，接著才跳成「載入中…」。全套測試偶發的紅燈就是它
        // （test_e2e_material_orders_2026_09_11.py，約 1/5 機率）。
        this.materialOrders = []
        this.moDirty = false
        this.moMsg = ''
        this.moLoading = true
        this.cr.dealTag = data.data?.dealTag || data.deal_tag || '已成案'
        this.cr.caseRecord = data.data?.caseRecord || null
        // 基準取伺服器原值（ensureCaseRecord 補上的預設分段會被當成改動送出）
        this._segBase = this._snapSegments(data.data?.caseRecord)
        this.segConflict = null
        this.badNum = {}
        await this.ensureCaseRecord()
        if (!live()) return
        this._segFill = this._fillOnly(this._segBase)
        await this._seedDefaultStagesIfEmpty()
        if (!live()) return
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
        this.completionNotes = []
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
        // 叫料的四個旗標已經在 await 之前重設過了（見上面），這裡不再重複
        this.xe = { ...this.xe, loading: true, items: [], totalAmount: 0,
                    totalPending: 0, pendingCount: 0, msg: '', busy: false }
        this._loadCaseTasks(quoteNo)
        this.loadDispatches(quoteNo)
        // 2026-09-14：這三個原本是「點分頁才載」，但分頁上的數量徽章要在沒點過
        // 之前就正確——沒載入時綁 .length 會顯示 0，看起來像「這案子沒有出貨單」，
        // 比沒有徽章更糟。兩個 loader 都是單純 GET、無副作用（不會標記已讀），
        // 這裡本來就已經並行打 8 個端點，多這三個是邊際成本。
        this.loadShippingNotes(quoteNo)
        this.loadCompletionNotes(quoteNo)
        this.loadCaseUpdates(quoteNo)
        this.loadContractorVouchers(quoteNo)
        this.loadInvoiceVouchers(quoteNo)
        this.loadPaymentRequests(quoteNo)
        this.loadFinanceSummary(quoteNo)
        this.loadMaterialOrders(quoteNo)
        this.loadExtraExpenses(quoteNo)
      } catch {}
    },

    async _loadCaseTasks(quoteNo) {
      if (!quoteNo) return
      const live = this._selectLive()
      this.caseTasksLoading = true
      try {
        const today = new Date().toISOString().slice(0, 10)
        const r = await fetch(`/api/daily-tasks?date=${today}&case_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? (await r.json()).items || [] : null
        if (!live()) return
        if (r.ok) this.caseTasks = body
      } catch {}
      this.caseTasksLoading = false
    },

    // ── 待辦事項（2026-08-26 專案管理併入案件管理，取代原本跳去 projects.html
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
      if (!this.selected || !confirm('確定刪除此待辦事項？')) return
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
      if (!filled.length) { alert('報價單上沒有可帶入的欄位，或案件這邊都已經有值了。'); return }
      this._fillContractFromQuote(c)
      this.setDirty && this.setDirty()
      this.dirty = true
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
        // 第一次建立時從報價單帶入（2026-09-14 使用者交辦「合約資訊要能根據
        // 報價單內容連動」）。**單向、只帶一次**：案件成立後現場條件本來就
        // 可能跟報價當時不同，雙向同步會讓改案件反過來改到已經簽核的報價單；
        // 每次開啟都覆蓋則會把現場修正洗掉。已存在的案件用下面那顆
        // pullContractFromQuote() 手動帶，不在載入時偷偷補寫。
        this._fillContractFromQuote(this.cr.caseRecord.contract)
      }
      if (!this.cr.caseRecord.roles) {
        this.cr.caseRecord.roles = { filler: '', sales: '', executor: '' }
      }
      if (!this.cr.caseRecord.projectTimeline) {
        this.cr.caseRecord.projectTimeline = { startDate: '', endDate: '', status: 'on_track' }
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
      const live = this._selectLive()
      const labels = ['訂單確認', '叫料出貨', '施工安裝', '客戶驗收', '尾款結清']
      for (const label of labels) {
        if (!live()) return
        try {
          const r = await fetch(`/api/quotations/${this.selected.quote_no}/stages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({ label })
          })
          const st = r.ok ? await r.json() : null
          if (!live()) return
          if (st) this.cr.caseRecord.stages.push(st)
        } catch {}
      }
    },

    paymentItems() { return this.cr.caseRecord?.payment?.items || [] },

    // CM13（2026-09-24）：後端對沒有財務檢視權的帳號遮蔽金額（selected.moneyMasked）。
    // 這時 total／amount 都是空的，任何換算都會算出 0 並自動存回去 ⇒ 會改金額的動作一律不做。
    moneyMasked() { return !!this.selected?.moneyMasked },

    // N14（2026-09-24）：款項金額改用文字框——type=number 貼上「12,000」時瀏覽器給空值，
    // 含稅／未稅的 +value 就變成 0。解析規則與 quotation-form.html::parseNumInput() 相同：
    // 接受千分位與全形數字；空白＝空值；解析不了 ⇒ 標紅（badNum），數值不更新、不存檔。
    badNum: {},
    parseNumInput(raw) {
      const s = String(raw == null ? '' : raw)
        .replace(/[０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))
        .replace(/．/g, '.').replace(/[,，\s]/g, '')
      if (s === '') return ''
      if (!/^\d+(\.\d*)?$/.test(s)) return null
      return parseFloat(s)
    },
    _markNum(badKey, bad) {
      if (bad) { this.badNum = { ...this.badNum, [badKey]: true }; return }
      if (this.badNum[badKey]) { const b = { ...this.badNum }; delete b[badKey]; this.badNum = b }
    },
    setNumField(obj, key, badKey, raw) {
      const v = this.parseNumInput(raw)
      this._markNum(badKey, v === null)
      if (v === null) return false
      obj[key] = v
      return true
    },
    // 聚焦中或標紅時保留使用者打的字，不被數值改寫；失焦（blur=true）才改回數值
    numShown(v, el, badKey, blur) {
      if (el && this.badNum[badKey]) return el.value
      if (!blur && el && document.activeElement === el) return el.value
      return v == null ? '' : v
    },
    onAmountTextChange(idx, kind, raw) {
      const item = this.paymentItems()[idx]
      if (!item) return
      const v = this.parseNumInput(raw)
      this._markNum(kind + '-' + item.id, v === null)
      if (v === null) return
      if (kind === 'wt') this.onAmountWithTaxChange(idx, v === '' ? 0 : v)
      else this.onAmountPretaxChange(idx, v === '' ? 0 : v)
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

    // CM14b（2026-09-24）：不是案件成員、靠 cashier 模組讀到的 ⇒ 除收款外全唯讀（後端另擋寫入）
    caseReadOnly() { return !!this.selected?.cashierReadOnly },

    // AC1：發票未稅／稅額（選填）。空＝沒填（null／''／undefined）；0 是有填（免稅的稅額就是 0）。
    _invoiceEmpty(v) { return v === null || v === undefined || v === '' },
    invoiceHalfFilled(item) {
      return this._invoiceEmpty(item.invoicePretax) !== this._invoiceEmpty(item.invoiceTax)
    },
    /** 兩欄都填而合計 ≠ 該期應收 ⇒ 回提示文字（只提示、不擋：發票可能與約定金額差 ±1）；否則 '' */
    invoiceMismatch(item, idx) {
      if (this._invoiceEmpty(item.invoicePretax) || this._invoiceEmpty(item.invoiceTax)) return ''
      const sum = (+item.invoicePretax || 0) + (+item.invoiceTax || 0)
      const due = Math.round(this.itemAmountReceivable(idx))
      return sum === due ? '' : '發票合計 NT$ ' + sum.toLocaleString() + ' 與這一期金額 NT$ '
        + due.toLocaleString() + ' 不同，請確認（不影響存檔）。'
    },

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
      if (this.moneyMasked()) return
      // 規範值：直接存含稅整數，pct 作為百分比 input 顯示用
      const total = this.totalWithTax()
      items[idx].amount = Math.round(withTax)
      items[idx].pct    = total > 0 ? Math.round(withTax / total * 10000) / 100 : 0
    },

    _syncLast(items) {
      if (this.moneyMasked()) return
      // 讓最後一筆含稅 = 合約總額 − Σ其他，確保合計精確
      const total   = this.totalWithTax()
      const lastIdx = items.length - 1
      const othersAmount = items.reduce((s, p, i) => i === lastIdx ? s : s + (p.amount ?? Math.round(total * (+p.pct || 0) / 100)), 0)
      this._setItemAmount(items, lastIdx, Math.max(0, total - othersAmount))
    },

    onPctChange(idx) {
      if (this.moneyMasked()) return
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
      if (this.moneyMasked()) return
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
      if (this.moneyMasked()) return
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
      if (this.moneyMasked()) return
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
      if (this.moneyMasked()) return
      const items = this.cr.caseRecord.payment.items
      items.push({ id: Date.now(), type: '進度款', pct: 0, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' })
      this.setDirty()
    },
    removePaymentItem(idx) {
      if (this.moneyMasked()) return
      if (this.cr.caseRecord.payment.items.length <= 1) return
      const pi = this.cr.caseRecord.payment.items[idx]
      if (!confirm(`確定要刪除款項期別「${pi?.type || '第' + (idx + 1) + '期'}」？\n\n刪除後會自動存檔，無法復原。`)) return
      this.cr.caseRecord.payment.items.splice(idx, 1)
      if (this.cr.caseRecord.payment.items.length === 1) {
        this.cr.caseRecord.payment.items[0].pct = 100
      }
      this.setDirty()
    },

    setDirty() {
      this.dirty = true
      window.motrixIsDirty = true
      this.saveStatus = 'dirty'
      this.saveMsg = '未儲存'
      clearTimeout(this._autoSaveTimer)
      this._autoSaveTimer = setTimeout(() => this.saveCaseRecord(), 1500)
      this._checkAllStagesDone()
    },

    _checkAllStagesDone() {
      if (this.cr.dealTag !== '已成案') return
      // 2026-09-13：結案限最高管理者，其他人跳這個提示只會得到 403，
      // 按了失敗比沒看到提示更令人困惑。
      if ((this.session?.role || '') !== 'superadmin') return
      const stages = this.cr.caseRecord?.stages || []
      if (!stages.length) return
      if (!stages.every(s => s.done)) { this._allDonePrompted = false; return }
      if (this._allDonePrompted) return
      this._allDonePrompted = true
      setTimeout(() => {
        if (confirm('所有執行進度已完成！\n\n是否現在結案並進入保固追蹤期？\n（可稍後在「更多」選單按「結案」）')) {
          this.closeCaseAction()
        }
      }, 300)
    },

    // ensureCaseRecord 替伺服器上沒有的分段補的預設值（使用者還沒動過）
    _fillOnly(base) {
      const out = {}
      for (const [k, v] of Object.entries(this._snapSegments(this.cr.caseRecord))) {
        if (base[k] === undefined) out[k] = v
      }
      return out
    },

    _snapSegments(cr) {
      const out = {}
      for (const [k, v] of Object.entries(cr || {})) {
        if (k !== 'stages' && v !== undefined) out[k] = JSON.stringify(v)
      }
      return out
    },

    // 自己在頁面上經由專屬端點改了伺服器上的某一段（附件上傳／刪除、沖銷）：
    // 同一個改動要同時套在畫面與基準上，否則下一次存檔會把自己擋下（或把附件蓋掉）。
    _applyToBoth(seg, fn) {
      if (this.cr.caseRecord) fn(this.cr.caseRecord)
      if (this._segBase[seg] === undefined) return
      const b = { [seg]: JSON.parse(this._segBase[seg]) }
      fn(b)
      this._segBase[seg] = JSON.stringify(b[seg])
    },

    _segLabel(k) {
      return ({ payment: '收款', materials: '材料', devices: '設備', contract: '合約資訊', roles: '角色',
        projectTimeline: '專案時程', materialOrders: '叫料', warrantyNote: '保固備註', notes: '備註' })[k] || k
    },

    // 衝突處理：reload＝放棄我的改動、改看伺服器現值；keep＝以伺服器現值為基準重存（明知並覆蓋那幾段）
    async resolveConflict(mode) {
      if (!this.selected || !this.segConflict) return
      const r = await fetch('/api/quotations/' + this.selected.quote_no, {
        headers: { Authorization: 'Bearer ' + this.session.token }
      })
      if (!r.ok) return
      const srv = (await r.json()).data?.caseRecord || {}
      const fresh = this._snapSegments(srv)
      if (mode === 'reload') {
        const stages = this.cr.caseRecord?.stages || []
        this.cr.caseRecord = { ...srv, stages }
        this._segBase = fresh
        this.ensureCaseRecord()
        this._segFill = this._fillOnly(fresh)
        this.segConflict = null
        this.dirty = false
        window.motrixIsDirty = false
        this.saveStatus = ''
        this.saveMsg = ''
        return
      }
      for (const k of this.segConflict) {
        if (fresh[k] === undefined) delete this._segBase[k]
        else this._segBase[k] = fresh[k]
      }
      this.segConflict = null
      await this.saveCaseRecord()
    },

    async saveCaseRecord() {
      if (!this.selected) return
      if (Object.keys(this.badNum).length) {
        // N14：標紅的數字欄位（無法辨識）存在時不送——送出去的是上一個有效值，畫面卻寫著別的字
        this.saveStatus = 'error'
        this.saveMsg = '有數字欄位無法辨識（標紅處），請修正後再存檔'
        return
      }
      if (this.cr.dealTag === '已結案' && !this.selected.case_semi_unlocked) {
        // 已結案且未解鎖：後端會直接 403，這裡先擋下避免每次 @input 觸發的
        // 防抖自動存檔都跑一趟網路請求、又跳出令人困惑的「儲存失敗」。
        this.dirty = false
        this.saveStatus = 'error'
        this.saveMsg = '案件已結案並鎖定，請先解鎖'
        return
      }
      // 驗證：已收款項必須填入收款日期
      const payItems = this.cr.caseRecord.payment?.items || []
      for (const item of payItems) {
        if (item.received && !item.receivedAt) {
          this.saveStatus = 'error'
          this.saveMsg = `${item.type || '款項'}：已標記收款但未填入收款日期，請補填`
          return
        }
      }
      // CM1：只送改到的分段；快照在送出前取，存檔途中又改的部分下一次再送
      const sent = this._snapSegments(this.cr.caseRecord)
      const segments = {}
      const base = {}
      const defaults = {}
      for (const k of new Set([...Object.keys(sent), ...Object.keys(this._segBase)])) {
        if (sent[k] === this._segBase[k]) continue
        // CM14b：唯讀（非成員出納）只送收款——ensureCaseRecord 對既有分段補的欄位不是他的改動，
        // 送出去整筆會被後端 403
        if (this.caseReadOnly() && k !== 'payment') continue
        if (this._segBase[k] === undefined && sent[k] === this._segFill[k]) {
          defaults[k] = JSON.parse(sent[k])
          continue
        }
        segments[k] = sent[k] === undefined ? null : JSON.parse(sent[k])
        base[k] = this._segBase[k] === undefined ? null : JSON.parse(this._segBase[k])
      }
      this.saving = true
      try {
        const r = await fetch('/api/quotations/' + this.selected.quote_no + '/case-record', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ segments, base, defaults })
        })
        if (r.ok) {
          this.dirty = false
          this.segConflict = null
          const res = await r.json().catch(() => ({}))
          if (res.pending) {
            // 已結案案件半解鎖期間：此次存檔不會立即生效，已排隊等最高管理員審核
            // （見 backend/routers/quotations.py::_gate_case_edit()）。
            this.saveStatus = 'dirty'
            this.saveMsg = '已送出，待最高管理員審核後套用'
            this.saving = false
            return
          }
          for (const k of Object.keys(segments)) {
            if (sent[k] === undefined) delete this._segBase[k]
            else this._segBase[k] = sent[k]
          }
          const adopted = res.adopted || {}
          for (const k of Object.keys(defaults)) {
            delete this._segFill[k]
            if (!(k in adopted)) { this._segBase[k] = sent[k]; continue }
            // 別人先存了這一段：改用資料庫的值（我這邊只是預設值；存檔途中已被改動就留著當改動）
            this._segBase[k] = JSON.stringify(adopted[k])
            if (JSON.stringify(this.cr.caseRecord[k]) === sent[k]) this.cr.caseRecord[k] = adopted[k]
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
          // 收款／階段等改動會影響五關，總覽跟著更新
          this.loadCaseHealth(this.selected?.quote_no)
          // 款項明細（勾已收款/實收金額/手續費）就是在這支存的，財務 Tab 的
          // 應收應付總覽必須跟著重算，否則會停在存檔前的舊數字
          this.loadFinanceSummary(this.selected?.quote_no)
        } else {
          // 2026-09-24：顯示後端給的原因（例如已收款期別不可刪除），不再只寫「儲存失敗」
          const err = await r.json().catch(() => ({}))
          this.saveStatus = 'error'
          if (r.status === 409 && err.detail?.code === 'segment_conflict') {
            // 不重試、不合併：讓使用者選「重新載入」或「保留我的變更再試」
            this.segConflict = err.detail.segments || []
            this.saveMsg = `這個案件的〈${this.segConflict.map(k => this._segLabel(k)).join('、')}〉已被他人更新`
          } else {
            this.saveMsg = typeof err.detail === 'string' && err.detail ? '儲存失敗：' + err.detail : '儲存失敗'
          }
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

    // CM2（2026-09-24）：單筆端點帶項目 id，伺服器以 id 找列（idx 只是舊資料沒有 id 時的後備）
    _itemQs(item) {
      return item && item.id != null ? `?itemId=${encodeURIComponent(item.id)}` : ''
    },

    // 單筆操作前先把未存的改動存掉：剛新增、還沒存的那一列在伺服器上不存在（會被 409）
    async _flushBeforeItemOp() {
      if (!this.dirty) return true
      clearTimeout(this._autoSaveTimer)
      await this.saveCaseRecord()
      if (this.dirty) { alert('請先存檔成功後再操作（' + (this.saveMsg || '尚未儲存') + '）'); return false }
      return true
    },

    async _postWriteoff(idx, path, body) {
      const quoteNo = this.selected.quote_no
      if (!(await this._flushBeforeItemOp())) return { ok: false, msg: '尚未儲存' }
      const qs = this._itemQs(this.paymentItems()[idx])
      const r = await fetch(`/api/quotations/${quoteNo}/payment/${idx}/${path}${qs}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
        body: JSON.stringify(body || {})
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        return { ok: false, msg: err.detail || '操作失敗' }
      }
      const res = await r.json().catch(() => ({}))
      if (res.item) {
        const keys = ['writeOffStatus', 'writeOffReason', 'writeOffRequestedBy', 'writeOffRequestedAt',
          'writeOffApprovedBy', 'writeOffApprovedAt', 'writeOffRejectReason', 'taxExempt']
        this._applyToBoth('payment', cr => {
          const it = (cr.payment?.items || [])[idx]
          if (!it) return
          for (const k of keys) {
            if (res.item[k] === undefined) delete it[k]
            else it[k] = res.item[k]
          }
        })
      }
      return { ok: true, synced: !!res.item }
    },

    async submitWriteoffModal() {
      const { idx, mode, reason } = this.writeoffModal
      if (!reason.trim()) return
      const item = this.paymentItems()[idx]
      const me = this.session.displayName || this.session.username || ''
      let res
      if (mode === 'request') {
        res = await this._postWriteoff(idx, 'request-writeoff', { reason })
        if (res.ok && !res.synced) {
          item.writeOffStatus = 'pending'
          item.writeOffReason = reason
          item.writeOffRequestedBy = me
          item.writeOffRequestedAt = new Date().toISOString()
        }
      } else {
        res = await this._postWriteoff(idx, 'approve-writeoff', { approve: false, reject_reason: reason })
        if (res.ok && !res.synced) {
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
        if (!res.synced) for (const k of ['writeOffStatus', 'writeOffReason', 'writeOffRequestedBy', 'writeOffRequestedAt']) delete item[k]
      } else {
        alert(res.msg)
      }
    },

    async approveWriteoff(idx) {
      const item = this.paymentItems()[idx]
      const me = this.session.displayName || this.session.username || ''
      const res = await this._postWriteoff(idx, 'approve-writeoff', { approve: true })
      if (res.ok && !res.synced) {
        item.writeOffStatus = 'approved'
        item.taxExempt = true
        item.writeOffApprovedBy = me
        item.writeOffApprovedAt = new Date().toISOString()
      } else if (!res.ok) {
        alert(res.msg)
      }
    },

    // ── 結案前檢查（2026-09-24）─────────────────────────────────────────
    // 原本先 confirm、再存檔（失敗照樣送結案）、最後才被 400 擋下並列一串理由。
    // 改成：先存檔，失敗就中止；再列出五關（與擋結案同一份判定），未過的有「前往」；
    // 五關全過才能按確認。
    closeCheck: { open: false, gates: [], canClose: false },

    async closeCaseAction() {
      if (!this.selected) return
      clearTimeout(this._autoSaveTimer)
      while (this.saving) await new Promise(res => setTimeout(res, 50))
      await this.saveCaseRecord()
      if (this.saveStatus === 'error' || this.segConflict) {
        alert('案件沒有存成功，已停止結案：' + (this.saveMsg || '儲存失敗'))
        return
      }
      try {
        const r = await fetch('/api/quotations/' + this.selected.quote_no + '/close-gates', {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { alert(d.detail || '無法取得結案條件'); return }
        this.closeCheck = { open: true, gates: d.gates || [], canClose: !!d.canClose }
      } catch {
        alert('網路錯誤，請稍後再試')
      }
    },

    closeCheckGoto(g) {
      this.closeCheck.open = false
      this.gotoGate(g)
    },

    gotoGate(g) {
      const t = this._gateTab(g)
      this.activeTab = t
      if (t === 'exec') this.execSubTab = 'progress'
      if (t === 'shipping') this.loadShippingNotes(this.selected.quote_no)
      if (t === 'completion') this.loadCompletionNotes(this.selected.quote_no)
    },

    // ── 案件健康總覽（2026-09-24）────────────────────────────────────────
    // 案件資訊頁上方：五關（/close-gates，與擋結案同一份判定）＋逾期應收＋待簽核。
    // 回應可能在使用者已切到別的案件後才抵達 ⇒ 只收「目前選的那一件」的回應。
    caseHealth: { quoteNo: '', gates: [] },

    async loadCaseHealth(quoteNo) {
      if (!quoteNo) return
      try {
        const r = await fetch('/api/quotations/' + encodeURIComponent(quoteNo) + '/close-gates', {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) return
        const d = await r.json()
        if (this.selected?.quote_no !== quoteNo) return
        this.caseHealth = { quoteNo, gates: d.gates || [] }
      } catch {}
    },

    healthDocs() {
      if (this.caseHealth.quoteNo !== this.selected?.quote_no) return null
      return (this.caseHealth.gates || []).find(g => g.key === 'documents' && g.state === 'blocked') || null
    },

    // 未收款且預計收款日已過（今天到期不算逾期）
    overdueReceivables() {
      const today = new Date().toISOString().slice(0, 10)
      return this.paymentItems().filter(it => !it.received && it.expectedReceiptDate && it.expectedReceiptDate < today)
    },

    async confirmCloseCase() {
      if (!this.closeCheck.canClose) return
      this.closeCheck.open = false
      const entry = { at: new Date().toISOString(), user: this.session.displayName || '', from: '已成案', to: '已結案' }
      await this.updateDealTag('已結案', entry)
      // 結案後留在案件頁（原本 800ms 後跳保固頁）
      if (this.cr.dealTag === '已結案') {
        this.saveStatus = 'saved'
        this.saveMsg = '已結案，保固追蹤已開始'
      }
    },

    // ── 跨模組連結（2026-09-24）─────────────────────────────────────────
    // 地圖（MP6 案件圖層）、獎金分配（bonus.js 的 ?q=）、相關傳票（分錄來源指向本案）。
    // 看不到該頁的人不顯示連結；回應晚到時只收目前選的那一件。
    caseLinks: { quoteNo: '', vouchers: [], bonusEnabled: false },

    _hasModule(k) {
      if (this.session.role === 'superadmin') return true
      let m = this.session.modules || []
      if (typeof m === 'string') { try { m = JSON.parse(m) } catch { m = [] } }
      return Array.isArray(m) && m.includes(k)
    },

    caseMapUrl() {
      if (!this.selected || !this._hasModule('map')) return ''
      const addr = this.cr.caseRecord?.contract?.deliveryAddress || this.selected.data?.deliveryLocation || ''
      if (!addr.trim()) return ''
      return 'map.html?focus=' + encodeURIComponent('cases:' + this.selected.quote_no)
    },

    async loadCaseLinks(quoteNo) {
      if (!quoteNo) return
      const auth = { Authorization: 'Bearer ' + this.session.token }
      const out = { quoteNo, vouchers: [], bonusEnabled: false }
      const jobs = []
      if (this._hasModule('cashier') || this._hasModule('finance')) {
        jobs.push(fetch('/api/vouchers/by-case/' + encodeURIComponent(quoteNo), { headers: auth })
          .then(r => r.ok ? r.json() : null).then(d => { out.vouchers = (d && d.vouchers) || [] }).catch(() => {}))
      }
      if (this.session.role === 'superadmin') {
        jobs.push(fetch('/api/system/bonus-module-status', { headers: auth })
          .then(r => r.ok ? r.json() : null).then(d => { out.bonusEnabled = !!(d && d.enabled) }).catch(() => {}))
      }
      await Promise.all(jobs)
      if (this.selected?.quote_no !== quoteNo) return
      this.caseLinks = out
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
          this.loadCaseCounts()
          this.filterCases()
        } else {
          // 結案防呆機制（2026-08-25/26）擋下時會回 400 + 說明未達成的前置
          // 條件，不能靜默吞掉，不然使用者只會看到「結案」按鈕沒反應。
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
      if (!confirm(`確定要刪除執行階段「${st.label || '未命名'}」？\n\n階段內的拜訪紀錄會一併刪除，無法復原。`)) return
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
    // `AC2`：階段收入比例。存基點（1/10000）；空白＝未設（null，不是 0——0 是「這個階段不認列」）
    stageRatioPct(st) { return st.ratioBp === null || st.ratioBp === undefined ? '' : st.ratioBp / 100 },
    setStageRatio(st, v) {
      const bp = (v === '' || v === null || v === undefined) ? null : Math.round(Number(v) * 100)
      if (bp !== null && (!Number.isFinite(bp) || bp < 0 || bp > 10000)) { alert('比例需為 0～100%'); return }
      this.updateStage(st, { ratioBp: bp })
    },
    stageRatioSummary() {
      const ss = this.cr.caseRecord?.stages || []
      const set = ss.filter(s => s.ratioBp !== null && s.ratioBp !== undefined)
      if (!set.length) return { warn: false, text: '收入比例未設定：權責口徑於全部階段完成的月份一次認列。' }
      const total = set.reduce((a, s) => a + s.ratioBp, 0)
      const pct = (total / 100).toLocaleString()
      return total === 10000
        ? { warn: false, text: '收入比例合計 100%：各階段於完成月份依比例認列（未稅）。' }
        : { warn: true, text: '收入比例合計 ' + pct + '%，不等於 100%：報表照比例認列、不補差，並列入待補登。' }
    },

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
      const u = (this.selectableUsers || []).find(x => x.username === username)
      if (!confirm(`確定要把「${(u && u.display_name) || username}」從階段「${st.label || '未命名'}」的負責人移除？`)) return
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
        // 2026-09-14：標籤前面加上起日（MM/DD）。甘特圖被縮放貼進簡報或
        // 列印時，時間軸刻度往往先糊掉，標籤自己帶日期才讀得出來。
        const _md = (d) => (d || '').slice(5, 10).replace('-', '/')
        return {
          id:           String(st.id),
          name:         (_md(start) ? _md(start) + ' ' : '') + (st.label || '（未命名階段）'),
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

    // ── 甘特圖檔位（2026-09-14）────────────────────────────────────────
    // 原本 view_mode 寫死 'Day'：跨半年的案件會拉出好幾千 px 寬，只能一直
    // 橫向捲、看不到全貌。改成依實際跨幅自動選，使用者可手動覆寫。
    ganttView: 'auto',
    _ganttSpanDays(tasks) {
      if (!tasks || !tasks.length) return 0
      let min = null, max = null
      tasks.forEach(t => {
        const s = new Date(t.start), e = new Date(t.end)
        if (!min || s < min) min = s
        if (!max || e > max) max = e
      })
      return Math.round((max - min) / 86400000)
    },
    // 【可調】檔位切換門檻。想讓它更早/更晚跳到週或月檔位，改這兩個數字就好，
    // 其餘邏輯不用動。判斷依據是「所有階段的最早起日到最晚迄日」的天數跨幅。
    //   Day  約 30px/天 → 45 天上限約 1400px，還放得進一般螢幕
    //   Week 約 156px/週 → 180 天上限約 4000px，需要橫向捲但仍讀得出來
    _autoGanttMode(tasks) {
      const d = this._ganttSpanDays(tasks)
      if (d <= 45)  return 'Day'
      if (d <= 180) return 'Week'
      return 'Month'
    },
    get ganttEffectiveMode() {
      if (this.ganttView !== 'auto') return this.ganttView
      return this._autoGanttMode(this._ganttTasks())
    },
    setGanttView(v) {
      this.ganttView = v
      this.renderGantt()
    },

    renderGantt() {
      const el = this.$refs.ganttContainer
      if (!el || typeof Gantt === 'undefined') return
      const tasks = this._ganttTasks()
      el.innerHTML = ''
      if (!tasks.length) return
      const mode = this.ganttView === 'auto' ? this._autoGanttMode(tasks) : this.ganttView
      this._ganttInstance = new Gantt(el, tasks, {
        view_mode: mode,
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
    // ── 甘特圖匯出 PNG / JPG（2026-09-14）──────────────────────────────
    // Frappe Gantt 畫的是 SVG，但顏色與字體全部來自外部 CSS。直接
    // XMLSerializer 序列化出來的 SVG 沒有那些樣式，畫到 canvas 上會變成
    // 沒有顏色的黑白線稿——**必須把 computed style 逐一 inline 回克隆節點**。
    // 這是整件事唯一的難處，不是多寫幾行 canvas 就好。
    //
    // 深色模式下匯出的仍是淺色版：整站深色是繪製階段的 invert 濾鏡，
    // getComputedStyle 讀到的是作者值。對匯出圖來說這正是我們要的。
    _SVG_STYLE_PROPS: ['fill','fill-opacity','stroke','stroke-width','stroke-dasharray',
                       'opacity','font-family','font-size','font-weight','text-anchor',
                       'dominant-baseline','visibility'],
    async exportGanttImage(fmt) {
      const el = this.$refs.ganttContainer
      const svg = el && el.querySelector('svg')
      if (!svg) { this.toast && this.toast('目前沒有可匯出的甘特圖'); return }
      this.ganttExporting = true
      try {
        const rect = svg.getBoundingClientRect()
        const fullW = Math.ceil(svg.getAttribute('width')  || rect.width)
        const h = Math.ceil(svg.getAttribute('height') || rect.height)
        const TITLE_H = 46

        // 裁掉左右空白（2026-09-14）
        // Frappe Gantt 的 setup_gantt_dates() 會自己把日期範圍撐開：
        // 週／日檔位前後各加 1 個月、月檔位往前補到年初再往後加 1 整年。
        // 所以一張 60 天的案件會畫成 2600px 以上，中間大半是空網格。
        // 壓縮的正解是裁掉那段空白，而不是把整張圖縮小——縮小會連日期
        // 刻度一起糊掉，那正是要避免的事。
        let cropX = 0, cropW = fullW, cropH = h
        if (this.ganttTrim) {
          const bars = svg.querySelectorAll('.bar-wrapper .bar, .bar-wrapper .bar-invalid')
          let minX = null, maxX = null, maxY = null
          bars.forEach(b => {
            const x  = parseFloat(b.getAttribute('x') || 'NaN')
            const y  = parseFloat(b.getAttribute('y') || 'NaN')
            const bw = parseFloat(b.getAttribute('width')  || '0')
            const bh = parseFloat(b.getAttribute('height') || '0')
            if (!isNaN(x)) {
              if (minX === null || x < minX) minX = x
              if (maxX === null || x + bw > maxX) maxX = x + bw
            }
            if (!isNaN(y) && (maxY === null || y + bh > maxY)) maxY = y + bh
          })
          if (minX !== null && maxX !== null && maxX > minX) {
            // 左右留白刻意不對稱：長條的 x/width 只涵蓋長條本身，**不含畫在
            // 右側的標籤文字**，所以右邊要多留，否則最後一個階段的標籤會被切。
            const PAD_L = 60, PAD_R = 240
            cropX = Math.max(0, Math.floor(minX - PAD_L))
            cropW = Math.min(fullW - cropX, Math.ceil(maxX - minX + PAD_L + PAD_R))
          }
          // SVG 高度是「列數 × 列高」的固定值，兩三個階段的案件下方會留一大片
          // 空列，一起裁掉。
          if (maxY !== null) cropH = Math.min(h, Math.ceil(maxY + 40))
        }
        const w = cropW

        const clone = svg.cloneNode(true)
        const src = svg.querySelectorAll('*')
        const dst = clone.querySelectorAll('*')
        for (let i = 0; i < src.length; i++) {
          const cs = getComputedStyle(src[i])
          let css = ''
          for (const prop of this._SVG_STYLE_PROPS) {
            const v = cs.getPropertyValue(prop)
            if (v) css += prop + ':' + v + ';'
          }
          dst[i].setAttribute('style', css)
        }
        clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
        clone.setAttribute('width', fullW)
        clone.setAttribute('height', h)

        const data = new XMLSerializer().serializeToString(clone)
        const img = new Image()
        await new Promise((res, rej) => {
          img.onload = res; img.onerror = rej
          img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(data)
        })

        // 2 倍取樣，列印或貼進簡報才不會糊
        const SCALE = 2
        const cv = document.createElement('canvas')
        cv.width  = w * SCALE
        cv.height = (cropH + TITLE_H) * SCALE
        const ctx = cv.getContext('2d')
        ctx.scale(SCALE, SCALE)
        ctx.fillStyle = '#FFFFFF'
        ctx.fillRect(0, 0, w, cropH + TITLE_H)

        // 抬頭：匯出的圖要自己說得清楚是哪張案子、哪天匯出的
        const sel = this.selected || {}
        ctx.fillStyle = '#1A1D21'
        ctx.font = '600 15px "LINE Seed TW_OTF", system-ui, sans-serif'
        ctx.fillText((sel.customer_name || '') + '　' + (sel.quote_no || ''), 16, 24)
        ctx.fillStyle = '#767676'
        ctx.font = '11px "LINE Seed TW_OTF", system-ui, sans-serif'
        const modeLabel = { Day: '日', Week: '週', Month: '月' }[this.ganttEffectiveMode] || ''
        ctx.fillText('執行進度甘特圖・' + modeLabel + '檔位'
                     + '・匯出於 ' + new Date().toLocaleString('zh-TW'), 16, 39)

        // 只畫裁切範圍那一段（來源 x 從 cropX 起算）
        ctx.drawImage(img, cropX, 0, cropW, cropH, 0, TITLE_H, cropW, cropH)

        const mime = fmt === 'jpg' ? 'image/jpeg' : 'image/png'
        const blob = await new Promise(r => cv.toBlob(r, mime, 0.92))
        const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '')
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = '甘特圖_' + (sel.quote_no || 'case') + '_' + stamp + '.' + fmt
        document.body.appendChild(a); a.click(); a.remove()
        setTimeout(() => URL.revokeObjectURL(a.href), 4000)
      } catch (e) {
        console.error('gantt export:', e)
      }
      this.ganttExporting = false
    },
    ganttExporting: false,
    ganttTrim: true,   // 匯出時裁掉前後空白。固定啟用：沒有人會想要一張大半是空白的圖，
                       // 不用多一個選項去問

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
      if (!confirm(`確定要刪除這筆拜訪紀錄${visit.visitDate ? '（' + visit.visitDate + '）' : ''}？\n\n刪除後無法復原。`)) return
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
    removeMaterial(idx) {
      const m = this.cr.caseRecord.materials[idx]
      if (!confirm(`確定要刪除材料「${m?.name || '未命名'}」？\n\n刪除後會自動存檔，無法復原。`)) return
      this.cr.caseRecord.materials.splice(idx, 1); this.setDirty()
    },
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
    // 刪除設備會在自動存檔時同步序號庫存（_sync_device_stock），存完無法復原
    _confirmRemoveDevice(dev) {
      return confirm(`確定要刪除設備「${dev?.name || '未命名'}${dev?.sn ? '／' + dev.sn : ''}」？\n\n刪除後會自動存檔並同步序號庫存，無法復原。`)
    },
    removeDevice(idx) {
      if (!this._confirmRemoveDevice(this.cr.caseRecord.devices[idx])) return
      this.cr.caseRecord.devices.splice(idx, 1); this.setDirty()
    },
    removeDeviceByObj(dev) {
      const devs = this.cr.caseRecord.devices
      const idx = devs.findIndex(d => d.id === dev.id)
      if (idx === -1 || !this._confirmRemoveDevice(dev)) return
      devs.splice(idx, 1); this.setDirty()
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

    daysUntilDeadline() {
      const endDate = this.cr.caseRecord?.projectTimeline?.endDate
      if (!endDate) return 0
      const deadline = new Date(endDate)
      const today = new Date()
      today.setHours(0, 0, 0, 0)
      deadline.setHours(0, 0, 0, 0)
      return Math.round((deadline - today) / 86400000)
    },

    // ── 承攬商派發 methods ──────────────────────────────────────────────────────

    // ── 動態 Tab ──────────────────────────────────────────────────────────────

    async loadCaseUpdates(quoteNo) {
      if (!quoteNo) return
      const live = this._selectLive()
      this.updatesLoading = true
      this.caseUpdates = []
      this.feedCalMode = false
      this.feedCalSelDate = ''
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/updates`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? await r.json() : null
        if (!live()) return
        if (r.ok) this.caseUpdates = body
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
      // 填執行時數、選聯絡事項類型、改過日期、或指定記錄對象 → 當成工作日誌
      // （那些是工作日誌才有的結構化欄位），走 work_logs；否則維持輕量留言
      // （case_updates，含「標記為重要」＋ Google 行事曆同步）。
      //
      // 2026-09-14：**照片不再是觸發條件**。在那之前只要選了照片就會被改存成
      // 工作日誌——附件本身跟「這是不是一筆工時記錄」無關，卻悄悄換掉了紀錄
      // 種類，而且換過去就失去「標記為重要」與行事曆同步。case_updates 現在
      // 自己支援附件（DB v82），這個轉向沒有必要了。
      const isBackdated = this.newCommentLogDate !== new Date().toISOString().slice(0, 10)
      if (this.newCommentHours || this.newCommentContactType ||
          isBackdated || this.newCommentUserId) {
        await this.postWorkLogEntry(content)
        return
      }
      this.postingComment = true
      try {
        // multipart：文字與附件同一個請求送出，不會有「留言貼了、圖沒上去」
        // 的半完成狀態。不要自己設 Content-Type——boundary 要讓瀏覽器帶。
        const fd = new FormData()
        fd.append('content', content)
        fd.append('important', this.newCommentImportant ? 'true' : 'false')
        this.newCommentPhotos.forEach(f => fd.append('files', f))
        const r = await fetch(`/api/quotations/${encodeURIComponent(this.selected.quote_no)}/updates`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (r.ok) {
          const item = await r.json()
          this.caseUpdates.unshift(item)
          this.newComment = ''
          this.newCommentImportant = false
          this.newCommentPhotos = []
          if (this.$refs.commentPhotoInput) this.$refs.commentPhotoInput.value = ''
        } else {
          const err = await r.json().catch(() => ({}))
          alert('留言失敗：' + (err.detail || r.status))
        }
      } catch (e) {
        alert('網路錯誤：' + e.message)
      }
      this.postingComment = false
    },

    // 附件刪除限 admin+（2026-09-14 使用者裁示）——抽掉附件是只改證據、
    // 留下文字，跟「刪掉自己整則留言」不是同一件事。
    canDeleteAttachment() {
      return ['superadmin', 'admin'].includes(this.session.role)
    },
    async deleteCommentFile(update, file) {
      if (!this.canDeleteAttachment()) return
      if (!confirm(`確定刪除附件「${file.filename}」？此動作無法復原。`)) return
      try {
        const r = await fetch(
          `/api/quotations/${encodeURIComponent(this.selected.quote_no)}/updates/${update.id}/files/${file.id}`,
          { method: 'DELETE', headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) {
          update.files = (await r.json()).files || []
        } else {
          const err = await r.json().catch(() => ({}))
          alert('刪除失敗：' + (err.detail || r.status))
        }
      } catch (e) { alert('網路錯誤：' + e.message) }
    },
    // fileUrl() 已移除（2026-09-15）：它把 **session token** 當成 `pt` 送給
    // /api/uploads/，而 `pt` 是 routers/uploads.py 用 HMAC 簽出來的短效簽章
    // （先跟 `/api/photo-token` 換），兩者形狀不同、必定驗不過——動態附件從
    // 上線起每一張都是 403。同頁其他附件（回簽／憑據）本來就走
    // previewAttachmentFile()，工作日誌照片走 photoUrl()，這裡改為沿用同兩支，
    // 不再留一支容易誤用的同義函式。業務開發記錄（dev-crm.html）同一個 commit
    // 犯了同樣的錯，已一起修。
    isImageFile(f) {
      return /\.(jpe?g|png)$/i.test(f.filename || f.path || '')
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
      const live = this._selectLive()
      this.dispatchesLoading = true
      this.dispatches = []
      try {
        const r = await fetch(`/api/contractor-dispatches?quote_no=${encodeURIComponent(quoteNo)}`, {
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

    removeDispatchPersonnel(idx) {
      const p = this.dispatchForm.personnel[idx]
      if (!confirm(`確定要刪除派工人員「${(p && p.name) || '未命名'}」這一列？`)) return
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
      const it = this.dispatchForm.items[idx]
      if (!confirm(`確定要刪除派工品項「${(it && it.description) || '未命名'}」這一列？`)) return
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
        if (!r.ok) { alert(j.detail || '發票日期儲存失敗'); return }
        d.invoiceDate = j.invoiceDate
        if (j.updated_at) d.updatedAt = j.updated_at
      } catch (e) { alert('網路錯誤：' + e.message) }
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
      const live = this._selectLive()
      this.shippingNotesLoading = true
      this.shippingNotes = []
      this.snSortPref = await loadListPref(this.session.token, `sn:${quoteNo}`)
      if (!live()) return
      try {
        const r = await fetch(`/api/shipping-notes?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? await r.json() : null
        if (!live()) return
        if (r.ok) this.shippingNotes = body
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
      const it = this.shippingForm.items[idx]
      if (!confirm(`確定要刪除出貨品項「${(it && it.description) || '未命名'}」這一列？`)) return
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
      // 同一人連任多層時一次簽完（2026-09-15，見 static/approval-cascade.js）。
      // 清單資料沒帶 approval.tiers 時算出來是空陣列，行為跟以前一樣。
      const _appr = n.approval || {}
      const _casc = window.MotrixApproval.selfCascadeTiers(
        _appr.tiers || [], _appr.currentTier ?? 0, this.session.username, [])
      if (!confirm(`確定簽核出貨單「${n.noteNo}」？` + window.MotrixApproval.cascadeNote(_casc))) return
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ cascade: _casc.length > 0 })
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
      // 同一人連任多層時一次簽完（2026-09-15，見 static/approval-cascade.js）。
      // 清單資料沒帶 approval.tiers 時算出來是空陣列，行為跟以前一樣。
      const _appr = v.approval || {}
      const _casc = window.MotrixApproval.selfCascadeTiers(
        _appr.tiers || [], _appr.currentTier ?? 0, this.session.username, [])
      if (!confirm(`確定簽核匯款申請「${v.voucherNo}」？` + window.MotrixApproval.cascadeNote(_casc))) return
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ cascade: _casc.length > 0 })
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
      const live = this._selectLive()
      this.invoiceVouchersLoading = true
      this.invoiceVouchers = []
      this.ivSortPref = await loadListPref(this.session.token, `iv:${quoteNo}`)
      if (!live()) return
      try {
        const r = await fetch(`/api/invoice-vouchers?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? await r.json() : null
        if (!live()) return
        if (r.ok) this.invoiceVouchers = body
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
      // 同一人連任多層時一次簽完（2026-09-15，見 static/approval-cascade.js）。
      // 清單資料沒帶 approval.tiers 時算出來是空陣列，行為跟以前一樣。
      const _appr = v.approval || {}
      const _casc = window.MotrixApproval.selfCascadeTiers(
        _appr.tiers || [], _appr.currentTier ?? 0, this.session.username, [])
      if (!confirm(`確定簽核開票申請憑據「${v.voucherNo}」？` + window.MotrixApproval.cascadeNote(_casc))) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ cascade: _casc.length > 0 })
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
      if (!(await this._flushBeforeItemOp())) { evt.target.value = ''; return }
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/payment/${idx}/invoice-files${this._itemQs(this.paymentItems()[idx])}`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '上傳失敗'); return }
        const body = await r.json()
        if (body.pending) { alert(body.message || '已送出，待最高管理員審核後套用'); return }
        this._applyToBoth('payment', cr => {
          const item = (cr.payment?.items || [])[idx]
          if (item) {
            if (!item.invoiceFiles) item.invoiceFiles = []
            item.invoiceFiles.push(...body.files)
          }
        })
      } catch (e) { alert('上傳失敗：' + e.message) }
      evt.target.value = ''
    },

    async deletePaymentItemInvoiceFile(idx, fileId) {
      if (!confirm('確定刪除此附件？')) return
      if (!(await this._flushBeforeItemOp())) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/payment/${idx}/invoice-files/${fileId}${this._itemQs(this.paymentItems()[idx])}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '刪除失敗'); return }
        const body = await r.json()
        if (body.pending) { alert(body.message || '已送出，待最高管理員審核後套用'); return }
        this._applyToBoth('payment', cr => {
          const item = (cr.payment?.items || [])[idx]
          if (item && item.invoiceFiles) item.invoiceFiles = item.invoiceFiles.filter(f => f.id !== fileId)
        })
      } catch (e) { alert('刪除失敗：' + e.message) }
    },

    async uploadMaterialFiles(idx, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      if (!(await this._flushBeforeItemOp())) { evt.target.value = ''; return }
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/materials/${idx}/files${this._itemQs((this.cr.caseRecord.materials || [])[idx])}`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '上傳失敗'); return }
        const body = await r.json()
        if (body.pending) { alert(body.message || '已送出，待最高管理員審核後套用'); return }
        this._applyToBoth('materials', cr => {
          const mat = (cr.materials || [])[idx]
          if (mat) {
            if (!mat.files) mat.files = []
            mat.files.push(...body.files)
          }
        })
      } catch (e) { alert('上傳失敗：' + e.message) }
      evt.target.value = ''
    },

    async deleteMaterialFile(idx, fileId) {
      if (!confirm('確定刪除此附件？')) return
      if (!(await this._flushBeforeItemOp())) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/materials/${idx}/files/${fileId}${this._itemQs((this.cr.caseRecord.materials || [])[idx])}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '刪除失敗'); return }
        const body = await r.json()
        if (body.pending) { alert(body.message || '已送出，待最高管理員審核後套用'); return }
        this._applyToBoth('materials', cr => {
          const mat = (cr.materials || [])[idx]
          if (mat && mat.files) mat.files = mat.files.filter(f => f.id !== fileId)
        })
      } catch (e) { alert('刪除失敗：' + e.message) }
    },

    async uploadMaterialInvoiceFiles(idx, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      if (!(await this._flushBeforeItemOp())) { evt.target.value = ''; return }
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/materials/${idx}/invoice-files${this._itemQs((this.cr.caseRecord.materials || [])[idx])}`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '上傳失敗'); return }
        const body = await r.json()
        if (body.pending) { alert(body.message || '已送出，待最高管理員審核後套用'); return }
        this._applyToBoth('materials', cr => {
          const mat = (cr.materials || [])[idx]
          if (mat) {
            if (!mat.invoiceFiles) mat.invoiceFiles = []
            mat.invoiceFiles.push(...body.files)
          }
        })
      } catch (e) { alert('上傳失敗：' + e.message) }
      evt.target.value = ''
    },

    async deleteMaterialInvoiceFile(idx, fileId) {
      if (!confirm('確定刪除此發票附件？')) return
      if (!(await this._flushBeforeItemOp())) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/materials/${idx}/invoice-files/${fileId}${this._itemQs((this.cr.caseRecord.materials || [])[idx])}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '刪除失敗'); return }
        const body = await r.json()
        if (body.pending) { alert(body.message || '已送出，待最高管理員審核後套用'); return }
        this._applyToBoth('materials', cr => {
          const mat = (cr.materials || [])[idx]
          if (mat && mat.invoiceFiles) mat.invoiceFiles = mat.invoiceFiles.filter(f => f.id !== fileId)
        })
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
      const live = this._selectLive()
      this.paymentRequestsLoading = true
      this.paymentRequests = []
      this.prListSortPref = await loadListPref(this.session.token, `prList:${quoteNo}`)
      if (!live()) return
      try {
        const r = await fetch(`/api/payment-requests?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? await r.json() : null
        if (!live()) return
        if (r.ok) this.paymentRequests = body
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
