/* global Alpine */
// Chart.js 實例故意放在 Alpine reactive data 之外（見 initCharts() 註解說明原因）
const _reportCharts = {}

// 金額縮寫。x 軸每個月份下面要印金額（2026-09-14 使用者交辦），
// 標籤空間只有一行字寬，完整數字會互相疊在一起。
function _shortMoney(v) {
  if (!v) return ''
  if (v >= 100000000) return (v / 100000000).toFixed(2) + ' 億'
  if (v >= 10000)     return (v / 10000).toFixed(1) + ' 萬'
  return Math.round(v).toLocaleString()
}

function reportsApp() {
  return {
    // ── Period state ──────────────────────────────────────────────────────────
    periodType: 'month',
    year:       new Date().getFullYear(),
    month:      new Date().getMonth() + 1,
    quarter:    Math.ceil((new Date().getMonth() + 1) / 3),

    // ── Department filter ────────────────────────────────────────────────────
    departmentId: '',   // '' = 不篩選
    orgTree:      [],

    // ── UI state ──────────────────────────────────────────────────────────────
    loading:    false,
    exporting:  false,
    exportType: '',
    error:      '',
    data:       null,

    // ── Customer history ─────────────────────────────────────────────────────
    custHistory:  [],
    custLoading:  false,
    custLoaded:   false,
    custSearch:   '',
    custSort:     'revenue',
    selectedCust: null,

    // ── AR aging
    arAging:   null,
    arLoading: false,
    arLoaded:  false,

    // ── 資金水位（應收帳齡 + 應付：承攬商已核准未匯款）
    cashPos:        null,
    cashPosLoading: false,
    cashPosLoaded:  false,

    // ── 稅務匯出（銷項發票清單）
    taxExportYear:  new Date().getFullYear(),
    taxExportMonth: '',   // '' = 整年
    taxExporting:   false,

    // ── T100（鼎新）傳票批次匯出（2026-09-01 新增，見 accounting_export.py）
    // 已確認清單＋反確認（2026-09-10 稽核補上）：後端 /t100-export/confirmed 與
    // /unconfirm 早就存在，unconfirm 的 docstring 自己寫著是「標記錯誤時的救援
    // 手段」，但畫面上一直沒有入口——使用者按下「確認已匯入」是批次操作，按錯
    // 之後只能改資料庫。這幾個狀態就是把那道門補上。

    // 銀行對帳單比對（連同標記已匯款 Modal）2026-08-31 搬到出納模組
    // frontend/js/cashier.js（財務/出納權限分工，見那邊同一輪改動），
    // 這裡不再重複維護一份。

    // ── Monthly trend
    trendData:    null,
    trendLoading: false,
    trendLoaded:  false,

    // ── 收支報表（原「月支出」，2026-08-30 重構為《當月收支》/《今年度收支》）──
    expensesScope:     'month', // month/quarter/year — 畫面上目前顯示哪個範圍
    expensesYear:      new Date().getFullYear(),
    expensesMonth:     new Date().toISOString().slice(0, 7),  // 'YYYY-MM'，當月範圍用
    expensesQuarter:   Math.ceil((new Date().getMonth() + 1) / 3),  // 1-4，季範圍用
    expensesData:      null,
    expensesLoading:   false,
    expensesLoadedFor: null,   // 記錄已載入資料對應的範圍+年+月+季，切換時判斷要不要重打 API
    expensesInflight:  null,   // 飛行中請求對應的同款鍵（避免同一期別被重複請求）
    // `AC2`：認列口徑（accrual＝權責，預設；cash＝現金）與「待補登」清單展開狀態
    expensesBasis:     'accrual',
    flagOpen:          {},
    expensesFilter:    'all',  // all/contractor/equipment/material/other，支出明細的類別篩選 chip

    // ── 應收報表（recv/out 分頁）。2026-09-09 一度改成完全獨立於 period-bar，
    //    2026-09-10 改回「預設跟隨 period-bar、分頁上的選擇器可臨時覆寫」──
    receivablesScope:     'month', // month/quarter/year
    receivablesYear:      new Date().getFullYear(),
    receivablesMonth:     new Date().toISOString().slice(0, 7),  // 'YYYY-MM'
    receivablesQuarter:   Math.ceil((new Date().getMonth() + 1) / 3),  // 1-4
    receivablesData:      null,
    receivablesLoading:   false,
    receivablesLoadedFor: null,
    receivablesInflight:  null,

    // ── 案件清單依月份區分（2026-08-26）─────────────────────────────────────
    caseListYear:         new Date().getFullYear(),
    caseListGroupByMonth: true,

    // ── Settlement modal ──────────────────────────────────────────────────────
    settlementModal:   false,
    settlementLoading: false,
    settlement:        null,

    // ── Target modal ──────────────────────────────────────────────────────────
    targetModal:  false,
    targetSaving: false,
    targetForm:   {
      year:     new Date().getFullYear(),
      annual:   { revenue: 0, newCases: 0, collectionAmount: 0, collectionRate: 0, avgNetMarginPct: 0, grossProfit: 0 },
      salesperson: []
    },

    // ── 出納（2026-08-31 併入營運報表，原獨立的 cashier.html/cashier.js 頁面
    // 退役成頁內「出納」頁籤，內容/邏輯完全比照原本，只有跟本檔案既有狀態
    // 衝突的名稱做了改名，見下方各區塊註解）────────────────────────────────────
    cashierLoaded: false,       // 出納頁籤第一次打開時 payable+receivable+history 一次性彙整載入 guard

    payable:    [],
    receivable: [],   // status=all，含已收+未收全部歷史（併入 receivables.html 用途）



    // T100 傳票匯出設定裡的銀行帳戶清單（2026-09-01 新增），標記已收款/已匯款
    // 時挑選要用哪個帳戶；每次開啟標記 Modal 都重抓最新清單，見
    // loadT100BankAccounts()


    // 原 cashier.js 的 historyStart/historyEnd/... 改加 cashier 前綴，避免在
    // 這支已經很大的共用檔案裡跟「執行歷史」以外的概念混淆
    cashierHistoryStart:        '',
    cashierHistoryEnd:          '',
    cashierHistoryLoading:      false,
    cashierHistoryOutgoing:     [],
    cashierHistoryIncoming:     [],
    cashierHistoryOutgoingTotal: 0,
    cashierHistoryIncomingTotal: 0,
    // 原 cashier.js 叫 exporting，這裡本來就有同名的「exporting」給財務報表
    // 匯出用（見 exportFile()），改名避免互踩


    // ── Helpers ───────────────────────────────────────────────────────────────
    get periodParam() {
      if (this.periodType === 'year')    return String(this.year)
      if (this.periodType === 'quarter') return this.year + '-Q' + this.quarter
      return this.year + '-' + String(this.month).padStart(2, '0')
    },
    get periodLabel() {
      if (!this.data) return ''
      return this.data.periodLabel || this.periodParam
    },
    get summary()      { return (this.data || {}).summary     || {} },
    get deptPerf()      { return (this.data || {}).deptPerf    || [] },
    get allDepartments() {
      var out = []
      for (var i = 0; i < this.orgTree.length; i++) {
        var div = this.orgTree[i]
        for (var j = 0; j < div.departments.length; j++) {
          var dept = div.departments[j]
          out.push({ id: dept.id, name: dept.name, divisionName: div.name })
        }
      }
      return out
    },
    get casesAll()     { return (this.data || {}).casesAll    || [] },

    // ── 案件清單依月份區分 ────────────────────────────────────────────────────
    get caseListYears() {
      var years = {}
      this.casesAll.forEach(function(c) { if (c.quoteDate) years[c.quoteDate.slice(0, 4)] = true })
      years[String(new Date().getFullYear())] = true
      return Object.keys(years).sort().reverse()
    },
    get casesByMonth() {
      var year = String(this.caseListYear)
      var buckets = []
      for (var m = 1; m <= 12; m++) {
        buckets.push({ month: m, label: m + '月', cases: [], total: 0, received: 0 })
      }
      this.casesAll.forEach(function(c) {
        if (!c.quoteDate || c.quoteDate.slice(0, 4) !== year) return
        var m = parseInt(c.quoteDate.slice(5, 7), 10)
        if (!buckets[m - 1]) return
        buckets[m - 1].cases.push(c)
        buckets[m - 1].total    += c.total || 0
        buckets[m - 1].received += c.receivedAmount || 0
      })
      return buckets
    },
    get caseListYearTotal() {
      return this.casesByMonth.reduce(function(s, b) { return s + b.cases.length }, 0)
    },

    // ── 收支報表 ──────────────────────────────────────────────────────────────
    get expensesMonthly() { return ((this.expensesData || {}).expenses || {}).monthly || [] },
    get expensesTotals()  { return ((this.expensesData || {}).expenses || {}).totals  || {} },
    // 今年度支出明細（逐筆，全部類別），供 filteredExpenseItems 在 expensesScope==='year' 時使用
    get yearExpenseItemsAll() {
      var d = ((this.expensesData || {}).expenses || {}).details || {}
      var cats = ['contractor', 'equipment', 'material', 'other']
      var out = []
      cats.forEach(function(cat) {
        (d[cat] || []).forEach(function(x) { out.push(Object.assign({ cat: cat }, x)) })
      })
      out.sort(function(a, b) { return (b.date || '').localeCompare(a.date || '') })
      return out
    },
    get monthExpenseItems() { return (this.expensesData || {}).monthExpenseItems || [] },
    get monthExpenseTotal() { return (this.expensesData || {}).monthExpenseTotal || 0 },
    get monthIncomeItems()  { return (this.expensesData || {}).monthIncomeItems  || [] },
    get monthIncomeTotal()  { return (this.expensesData || {}).monthIncomeTotal  || 0 },
    // 收款資料異常（2026-09-11）：刻意**不跟著 expensesScope 切換**——這些款項
    // 就是因為「已收款」與「收款日期」只填了一個而不屬於任何月份，再用期別去篩
    // 就又看不見了，那正是這一區要解決的問題本身
    get paymentAnomalies()    { return (this.expensesData || {}).paymentAnomalyItems || [] },
    // `AC2`：口徑說明、收入稅別字樣（權責＝未稅；現金＝含稅）、待補登清單（只列有數量的種類）
    get basisNote()        { return (this.expensesData || {}).basisNote || '' },
    get incomeTaxLabel()   { return (this.expensesData || {}).incomeTaxLabel || '' },
    get isAccrual()        { return ((this.expensesData || {}).basis || this.expensesBasis) === 'accrual' },
    get recognitionFlags() {
      var f = (this.expensesData || {}).recognitionFlags || {}
      return Object.keys(f).map(function (k) { return Object.assign({ kind: k }, f[k]) })
        .filter(function (x) { return x.count > 0 })
    },
    setBasis(b) { if (this.expensesBasis === b) return; this.expensesBasis = b; this.loadExpenses() },
    toggleFlag(kind) { this.flagOpen = Object.assign({}, this.flagOpen, { [kind]: !this.flagOpen[kind] }) },
    fmtMasked(v) { return v === null || v === undefined ? '—' : this.fmt(v) },
    get paymentAnomalyTotal() { return (this.expensesData || {}).paymentAnomalyTotal || 0 },
    get yearIncomeItems()   { return (this.expensesData || {}).yearIncomeItems   || [] },
    get yearIncomeTotal()   { return (this.expensesData || {}).yearIncomeTotal   || 0 },
    get quarterExpenseItems() { return (this.expensesData || {}).quarterExpenseItems || [] },
    get quarterExpenseTotal() { return (this.expensesData || {}).quarterExpenseTotal || 0 },
    get quarterIncomeItems()  { return (this.expensesData || {}).quarterIncomeItems  || [] },
    get quarterIncomeTotal()  { return (this.expensesData || {}).quarterIncomeTotal  || 0 },
    // 目前選取範圍（當月/本季/今年度）對應的收入/支出明細＋淨額，畫面統一透過這幾個
    // getter 讀取。三個範圍一律用 _scopePick() 選欄位，避免像先前只有兩種範圍時到處
    // 寫 ternary、加第三種就得逐處補（漏一處就是靜默顯示錯範圍的數字）。
    _scopePick(scope, m, q, y) {
      if (scope === 'quarter') return q
      if (scope === 'year')    return y
      return m
    },
    get scopeLabel() {
      return this._scopePick(this.expensesScope, '當月', '本季', '今年度')
    },
    get activeIncomeItems() {
      return this._scopePick(this.expensesScope, this.monthIncomeItems, this.quarterIncomeItems, this.yearIncomeItems)
    },
    get activeIncomeTotal() {
      return this._scopePick(this.expensesScope, this.monthIncomeTotal, this.quarterIncomeTotal, this.yearIncomeTotal)
    },
    get activeExpenseTotal() {
      return this._scopePick(this.expensesScope, this.monthExpenseTotal, this.quarterExpenseTotal, this.expensesTotals.total) || 0
    },
    get filteredExpenseItems() {
      var items = this._scopePick(this.expensesScope, this.monthExpenseItems, this.quarterExpenseItems, this.yearExpenseItemsAll)
      if (this.expensesFilter === 'all') return items
      return items.filter(function(x) { return x.cat === this.expensesFilter }, this)
    },
    get netScopeAmount() {
      return this.activeIncomeTotal - this.activeExpenseTotal
    },

    // ── 應收報表（recv/out 分頁，2026-09-09）───────────────────────────────────
    // 缺日期而不屬於任何月份的款項（2026-09-12）。已收款／未收款改用收款日期口徑
    // 之後，沒填日期的那些會從每一個月份都撈不到——固定顯示在分頁下方，不隨期別
    // 篩選，也刻意不併進上面的合計（併進去的話同一筆會在每個月被重複計算）
    get undatedCollectedItems()   { return (this.receivablesData || {}).undatedCollectedItems || [] },
    get undatedCollectedTotal()   { return (this.receivablesData || {}).undatedCollectedTotal || 0 },
    get undatedOutstandingItems() { return (this.receivablesData || {}).undatedOutstandingItems || [] },
    get undatedOutstandingTotal() { return (this.receivablesData || {}).undatedOutstandingTotal || 0 },

    get monthCollectedItems()   { return (this.receivablesData || {}).monthCollectedItems || [] },
    get monthOutstandingItems() { return (this.receivablesData || {}).monthOutstandingItems || [] },
    get yearCollectedItems()    { return (this.receivablesData || {}).yearCollectedItems || [] },
    get yearOutstandingItems()  { return (this.receivablesData || {}).yearOutstandingItems || [] },
    get quarterCollectedItems()   { return (this.receivablesData || {}).quarterCollectedItems || [] },
    get quarterOutstandingItems() { return (this.receivablesData || {}).quarterOutstandingItems || [] },
    get receivablesScopeLabel() {
      return this._scopePick(this.receivablesScope, '當月', '本季', '今年度')
    },
    get activeCollectedItems() {
      return this._scopePick(this.receivablesScope, this.monthCollectedItems, this.quarterCollectedItems, this.yearCollectedItems)
    },
    get activeOutstandingItems() {
      return this._scopePick(this.receivablesScope, this.monthOutstandingItems, this.quarterOutstandingItems, this.yearOutstandingItems)
    },
    // 「本期收支」KPI 區塊的未收款卡片：跟著同一個範圍走，不再固定讀 month*
    get activeOutstandingTotal() {
      var d = this.receivablesData || {}
      return this._scopePick(this.receivablesScope,
        d.monthOutstandingTotal, d.quarterOutstandingTotal, d.yearOutstandingTotal) || 0
    },

    expensesCatLabel(cat) {
      return { contractor: '承攬商派發', equipment: '設備進貨', material: '料件進貨', other: '其他支出' }[cat] || cat
    },
    get salesPerf()    { return (this.data || {}).salesPerf   || [] },
    get marginCases()  { return (this.data || {}).marginCases || [] },
    get warranty()      { return (this.data || {}).warranty      || [] },
    get targets()       { return (this.data || {}).targets       || {} },
    get achievement()   { return (this.data || {}).achievement   || {} },
    get settleOverdue() { return (this.data || {}).settleOverdue || [] },
    get casesWithoutPaymentItems() { return (this.data || {}).casesWithoutPaymentItems || [] },

    get filteredCusts() {
      var q = this.custSearch.trim().toLowerCase()
      var list = q
        ? this.custHistory.filter(function(c) {
            return c.customer.toLowerCase().includes(q) || (c.salesPerson || '').toLowerCase().includes(q)
          })
        : this.custHistory.slice()
      var sort = this.custSort
      list.sort(function(a, b) {
        if (sort === 'cases')    return b.quoteCount - a.quoteCount
        if (sort === 'winrate')  return (b.winRate || 0) - (a.winRate || 0)
        if (sort === 'activity') return b.lastActivity.localeCompare(a.lastActivity)
        return b.totalWonAmount - a.totalWonAmount
      })
      return list
    },

    fmt(n) {
      return 'NT$ ' + (Math.round(n || 0)).toLocaleString()
    },
    fmtDiff(n) {
      if (n == null) return '—'
      const v = Math.round(n)
      return (v >= 0 ? '+NT$ ' : '-NT$ ') + Math.abs(v).toLocaleString()
    },
    estGrossProfit(mc) {
      return Math.round((mc.pretax || 0) * (mc.netMarginPct || 0) / 100)
    },
    pct(n) {
      return (n || 0).toFixed(1) + '%'
    },

    // Achievement helpers
    acvGrade(rate) {
      if (rate === null || rate === undefined) return 'none'
      if (rate >= 95) return 'green'
      if (rate >= 80) return 'orange'
      return 'red'
    },
    acvColor(rate) {
      if (rate === null || rate === undefined) return '#9CA3AF'
      if (rate >= 95) return '#15803D'
      if (rate >= 80) return '#D97706'
      return '#DC2626'
    },
    acvBarPct(rate) {
      if (rate === null || rate === undefined) return 0
      return Math.min(Math.max(rate, 0), 100)
    },

    prevPeriod() {
      if (this.periodType === 'year') { this.year--; this.loadData(); return }
      if (this.periodType === 'month') {
        if (this.month === 1) { this.year--; this.month = 12 } else { this.month-- }
      } else {
        if (this.quarter === 1) { this.year--; this.quarter = 4 } else { this.quarter-- }
      }
      this.loadData()
    },
    nextPeriod() {
      if (this.periodType === 'year') { this.year++; this.loadData(); return }
      if (this.periodType === 'month') {
        if (this.month === 12) { this.year++; this.month = 1 } else { this.month++ }
      } else {
        if (this.quarter === 4) { this.year++; this.quarter = 1 } else { this.quarter++ }
      }
      this.loadData()
    },
    switchType(t) {
      this.periodType = t
      if (t === 'year') this.activeTab = 'targets'
      this.loadData()
    },

    // ── Auth ──────────────────────────────────────────────────────────────────
    _token() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.token || ''
    },
    _role() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.role || ''
    },
    _modules() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.modules || []
    },
    isAdminPlus() {
      var r = this._role()
      return r === 'admin' || r === 'superadmin'
    },
    // 2026-08-31：出納併入本頁後的准入判斷——cashier/finance 模組使用者（非
    // 管理職）只能看到「出納」頁籤，其餘 11 個財務報表頁籤仍只有 admin+ 看得到
    // （見 init()/showCashierTab()），這兩個 getter 就是那道區隔線。
    hasCashierAccess() {
      return this.isAdminPlus() || this._modules().includes('cashier') || this._modules().includes('finance')
    },
    // 本地日期字串（YYYY-MM-DD），不用 toISOString()（UTC，台灣 UTC+8 每天
    // 00:00-08:00 之間會誤判成前一天，比照 case-management.js/cashier.js 同款修法）。
    _localDateStr(d) {
      d = d || new Date()
      const tz = d.getTimezoneOffset() * 60000
      return new Date(d.getTime() - tz).toISOString().slice(0, 10)
    },

    // ── 期別同步 ──────────────────────────────────────────────────────────────
    // 頂部 period-bar（月/季/年）是全頁唯一的期別主控。「本期收支」KPI 區塊與
    // 「已收款／未收款／月支出」三個分頁各自有獨立資料流（/expenses-monthly、
    // /receivables-monthly），2026-09-09 那批改動只在 init() 同步過一次期別，
    // prevPeriod()/nextPeriod()/switchType() 以及 period-bar 的年/月/季下拉都
    // 沒跟上，導致上方期別怎麼切、下方金額都釘在真實當月不動（2026-09-10 回報）。
    // 同步點刻意放在 loadData() 開頭這一個地方——所有切期別的路徑最後都會走到
    // 這裡，往後新增觸發點也不必再記得補一次。使用者仍可用分頁上的選擇器臨時
    // 覆寫範圍，覆寫效力維持到下次動 period-bar 或部門篩選為止。
    _syncSubPeriods() {
      var scope = this.periodType === 'year' ? 'year'
                : this.periodType === 'quarter' ? 'quarter' : 'month'
      var mo = this.year + '-' + String(this.month).padStart(2, '0')
      this.expensesScope    = scope
      this.expensesYear     = this.year
      this.expensesMonth    = mo
      this.expensesQuarter  = this.quarter
      this.receivablesScope   = scope
      this.receivablesYear    = this.year
      this.receivablesMonth   = mo
      this.receivablesQuarter = this.quarter
    },
    // 快取鍵：三個呼叫點（loadExpenses/showExpensesTab/_ensureSubPeriodData）過去
    // 各自手拼一次字串，欄位一多就會漂移——收斂成單一來源。
    _expensesKey() {
      return [this.expensesScope, this.expensesYear, this.expensesMonth,
              this.expensesQuarter, this.departmentId || '', this.expensesBasis].join(':')
    },
    _receivablesKey() {
      return [this.receivablesScope, this.receivablesYear, this.receivablesMonth,
              this.receivablesQuarter, this.departmentId || ''].join(':')
    },
    // 兩支子資料流的載入守門。除了「已載入的期別」之外還要看「飛行中的期別」，
    // 否則同一個期別會被連打兩次（loadData 一次、切分頁再一次）。真正關鍵的是
    // 搭配 loadExpenses()/loadReceivables() 裡的過期回應丟棄機制，見那邊註解。
    _ensureSubPeriodData() {
      var ek = this._expensesKey()
      if (this.expensesLoadedFor !== ek && this.expensesInflight !== ek) this.loadExpenses()
      var rk = this._receivablesKey()
      if (this.receivablesLoadedFor !== rk && this.receivablesInflight !== rk) this.loadReceivables()
    },

    // ── Load preview data ─────────────────────────────────────────────────────
    async loadData() {
      if (!this.isAdminPlus()) {
        if (!this.hasCashierAccess()) this.error = '僅管理員以上可存取營運報表功能'
        return
      }
      this._syncSubPeriods()
      // 期別/部門連續切換時同樣會有兩個請求在飛，晚發早到的舊回應不能蓋掉新的
      // （理由與處理方式同 loadExpenses()）。
      var reqKey = this.periodParam + ':' + (this.departmentId || '')
      this.loading = true
      this.error   = ''
      this.data    = null
      try {
        var qs = 'period=' + this.periodParam + (this.departmentId ? '&department_id=' + this.departmentId : '')
        var res = await fetch('/api/reports/financial?' + qs, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '載入失敗')
        }
        var payload = await res.json()
        if (reqKey !== this.periodParam + ':' + (this.departmentId || '')) return
        this.data = payload
        // 「本期收支」KPI 區塊在任何分頁都看得到（不只 expenses 分頁），所以這兩份
        // 子資料流一律確保跟上目前期別，不再只在 expenses 分頁時才載入。
        this._ensureSubPeriodData()
      } catch (e) {
        if (reqKey === this.periodParam + ':' + (this.departmentId || '')) this.error = e.message || '載入錯誤'
      } finally {
        if (reqKey === this.periodParam + ':' + (this.departmentId || '')) this.loading = false
      }
    },

    async loadOrgTree() {
      try {
        var res = await fetch('/api/org/tree', { headers: { Authorization: 'Bearer ' + this._token() } })
        if (res.ok) this.orgTree = await res.json()
      } catch (_) {}
    },

    // ── Export ────────────────────────────────────────────────────────────────
    async exportFile(fmt) {
      this.exporting  = true
      this.exportType = fmt
      // 期別切在「季報」時多帶 quarter，匯出檔才會有「本季收支」那一頁／工作表
      // （不帶時輸出與先前完全一致）。expense_month 已由 _syncSubPeriods() 跟著
      // period-bar 同步，所以月報的匯出本來就會對到畫面上的月份。
      var url = '/api/reports/financial/' + fmt + '?period=' + this.periodParam +
                '&expense_month=' + this.expensesMonth +
                (this.expensesScope === 'quarter' ? '&quarter=' + this.expensesQuarter : '') +
                (this.departmentId ? '&department_id=' + this.departmentId : '')
      try {
        var res = await fetch(url, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '匯出失敗')
        }
        var blob = await res.blob()
        var ext  = fmt === 'excel' ? 'xlsx' : 'pdf'
        var fname = 'MOTRIX_營運報表_' + this.periodParam + '.' + ext
        var a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = fname
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(a.href)
      } catch (e) {
        alert('匯出失敗：' + (e.message || e))
      } finally {
        this.exporting  = false
        this.exportType = ''
      }
    },

    // ── Settlement modal ──────────────────────────────────────────────────────
    async openSettlement(quoteNo) {
      this.settlementModal   = true
      this.settlementLoading = true
      this.settlement        = null
      try {
        var res = await fetch('/api/quotations/' + quoteNo + '/settlement', {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) throw new Error('載入精算失敗')
        var d = await res.json()
        this.settlement = Object.assign({ quoteNo: quoteNo }, d)
      } catch (e) {
        alert('載入精算資料失敗：' + (e.message || e))
        this.settlementModal = false
      } finally {
        this.settlementLoading = false
      }
    },

    closeSettlement() {
      this.settlementModal = false
      this.settlement      = null
    },

    // helpers for settlement modal
    stlFmt(n) { return 'NT$ ' + (Math.round(n || 0)).toLocaleString() },
    stlSummary() { return (this.settlement && this.settlement.settlement && this.settlement.settlement.summary) || {} },
    stlItems()   { return (this.settlement && this.settlement.settlement && this.settlement.settlement.items)   || [] },
    stlExtras()  { return (this.settlement && this.settlement.settlement && this.settlement.settlement.extraItems) || [] },
    stlMemo()    { return (this.settlement && this.settlement.settlement && this.settlement.settlement.memo) || '' },
    stlStatus()  { return (this.settlement && this.settlement.settlement && this.settlement.settlement.status) || '' },
    stlFinAt()   { return (this.settlement && this.settlement.settlement && this.settlement.settlement.finalizedAt || '').slice(0,16).replace('T',' ') },
    stlFinBy()   { return (this.settlement && this.settlement.settlement && this.settlement.settlement.finalizedBy) || '' },
    stlCanOpen(c) { return c.settleStatus && c.settleStatus !== '' },

    // ── Target modal ──────────────────────────────────────────────────────────
    openTargetModal() {
      var ex = this.targets || {}
      this.targetForm = {
        year: ex.year || this.year,
        annual: Object.assign(
          { revenue: 0, newCases: 0, collectionAmount: 0, collectionRate: 0, avgNetMarginPct: 0, grossProfit: 0 },
          ex.annual || {}
        ),
        salesperson: JSON.parse(JSON.stringify(ex.salesperson || []))
      }
      this.targetModal = true
    },
    addSpTarget() {
      this.targetForm.salesperson.push({ name: '', revenue: 0, cases: 0 })
    },
    removeSpTarget(i) {
      this.targetForm.salesperson.splice(i, 1)
    },
    async saveTargets() {
      this.targetSaving = true
      try {
        var res = await fetch('/api/settings/operating-targets', {
          method:  'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body:    JSON.stringify(this.targetForm)
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '儲存失敗')
        }
        this.targetModal = false
        await this.loadData()
      } catch (e) {
        alert('儲存目標失敗：' + (e.message || e))
      } finally {
        this.targetSaving = false
      }
    },

    // 2026-09-14：預設從 'targets' 改成 'charts'。年度目標那一頁在沒設定
    // 目標時是空狀態，一進營運報表看到的是「尚未設定年度目標」。
    // 改成先看到圖表，其餘 12 個頁籤維持不動當細分用。
    activeTab: 'charts',

    // ── 圖表數值明細（2026-09-14 使用者交辦：「圖表也要顯示金額跟內容，
    //    目前只有圖表，沒有詳細資訊」）───────────────────────────────
    // 數字**不另外算一份**：每張圖的 _buildXChart() 在畫圖的同時把自己用的
    // 那組數字寫進這裡。另外寫一份彙總遲早會跟圖對不起來，而「表跟圖數字
    // 不一樣」是報表最傷信任的一種錯。
    // 形狀統一成 { cols, colors, rows:[{label, values[]}] }，五張圖共用同一段
    // 表格 markup。values 在這裡就格式化成字串——格式邏輯跟資料放一起。
    showChartData: true,

    // ── 本期財務快照（2026-09-14 使用者交辦：「營運報表圖表優先顯示當月的
    //    收入支出跟應收應付」）──────────────────────────────────────────
    // 收入/支出/未收 這三個主報表載入時就有了；**應付是例外**——payable 原本
    // 只在切到「出納」分頁時才抓（cashierLoaded guard）。不自己載的話這一格會
    // 顯示 NT$ 0，那比留白更糟：看起來像「這期沒有任何應付」。所以圖表分頁
    // 自己抓一次，而且用獨立的 flag，不去動出納分頁那條完整載入的路徑。
    // 沒有出納權限的人（/api/cashier/payable-queue 會回 403）顯示「無權限」，
    // 同樣不能假裝是 0。
    payableSnapLoaded: false,
    payableSnapDenied: false,

    async _loadPayableSnapshot() {
      if (this.payableSnapLoaded || this.cashierLoaded) return
      if (!this.hasCashierAccess()) { this.payableSnapDenied = true; return }
      // 應收與應付**必須取自同一個來源**（出納佇列）。這一頁在「資金水位」
      // 已經定義過「淨部位（應收 − 應付）」就是這兩個數字相減，快照沿用同一個
      // 定義才不會出現兩個都叫「應收」卻不一樣的數字。
      // （踩過：一開始應收接的是 activeOutstandingTotal——那是應收報表的期別
      //  範圍數字，跟出納的應收帳款是兩回事，畫面上會變成快照說 0、上方 KPI 卡
      //  說一百多萬。）
      try {
        const [rp, rr] = await Promise.all([
          fetch('/api/cashier/payable-queue',    { headers: { Authorization: 'Bearer ' + this._token() } }),
          fetch('/api/cashier/receivable-queue', { headers: { Authorization: 'Bearer ' + this._token() } }),
        ])
        if (rp.ok) this.payable = await rp.json()
        else if (rp.status === 403) this.payableSnapDenied = true
        if (rr.ok) this.receivable = await rr.json()
        else if (rr.status === 403) this.payableSnapDenied = true
      } catch (e) { console.error('payable snapshot:', e) }
      this.payableSnapLoaded = true
    },

    get netPosition() { return this.kpiReceivableTotal - this.kpiPayableTotal },
    get payableKnown() { return !this.payableSnapDenied && (this.payableSnapLoaded || this.cashierLoaded) },

    // 長條各自對「自己這一組」的最大值縮放。收支（流量）與應收應付（存量）
    // 是兩種不同量綱，共用同一個比例尺會讓其中一組永遠貼著邊——同一張圖上
    // 兩個尺度正是這一頁趨勢圖已經犯過的錯，不要再犯第二次。
    // 最小寬度 2% 是讓很小但非零的值看得見；**0 必須回 0**，
    // 畫一小截長條會被讀成「有一點點」，那是假資訊。
    _barPct(v, max) {
      if (!v) return 0
      return max > 0 ? Math.max(2, Math.round(Math.abs(v) / max * 100)) : 0
    },
    get flowMax()  { return Math.max(Math.abs(this.activeIncomeTotal || 0), Math.abs(this.activeExpenseTotal || 0)) },
    get stockMax() { return Math.max(Math.abs(this.kpiReceivableTotal || 0), Math.abs(this.kpiPayableTotal || 0)) },
    chartTables: {
      trend:  { cols: [], colors: [], rows: [] },
      status: { cols: [], colors: [], rows: [] },
      sales:  { cols: [], colors: [], rows: [] },
      target: { cols: [], colors: [], rows: [] },
      margin: { cols: [], colors: [], rows: [] },
    },
    _fmtMoney(v) { return (v == null) ? '—' : 'NT$ ' + Math.round(v).toLocaleString() },
    _fmtPct(v)   { return (v == null) ? '—' : (Math.round(v * 10) / 10) + '%' },
    _fmtInt(v)   { return (v == null) ? '—' : Math.round(v).toLocaleString() },

    // ── Charts (圖表分析) ──────────────────────────────────────────────────────
    // Chart.js 實例故意用模組層級的 _reportCharts（見檔案最上方），不放進這個
    // Alpine 元件的 reactive data：Alpine 會把 x-data 物件底下每個屬性遞迴包成
    // reactive Proxy，Chart.js 實例內部有大量 getter／循環參照／animation
    // registry，被 Proxy 包住後會讓內部渲染迴圈行為異常——實測現象是「近12月
    // 成案趨勢」這張混合長條+雙Y軸圖表，物件內部資料（datasets/scales）完全
    // 正確，但畫布實際畫出來的內容卻是舊的／不完整的，且對 proxy 包住的 chart
    // 實例呼叫方法會直接噴 RangeError: Maximum call stack size exceeded（Alpine
    // 的 reactive getter 對 Chart.js 內部循環結構遞迴到爆堆疊）。同樣邏輯下,
    // status/sales/target/margin 這幾張比較單純的圖恰好沒踩到會爆的內部程式
    // 路徑，只有這張最複雜的圖表現出來。frontend/index.html 的 Chart.js 用法
    // 從頭到尾都不把 chart 實例存進 Alpine data，是同一個坑的正確示範。
    initCharts() {
      Object.values(_reportCharts).forEach(function(c) { try { c.destroy() } catch(_) {} })
      Object.keys(_reportCharts).forEach(function(k) { delete _reportCharts[k] })
      if (!this.data) return
      // Clear any lingering canvas state after destroy
      ;['rpt-chart-trend','rpt-chart-status','rpt-chart-sales','rpt-chart-target','rpt-chart-margin'].forEach(function(id) {
        var cv = document.getElementById(id)
        if (cv) { var ctx = cv.getContext('2d'); if (ctx) ctx.clearRect(0, 0, cv.width, cv.height) }
      })
      Chart.defaults.font.family = "'LINE Seed TW_OTF', sans-serif"
      Chart.defaults.font.size   = 11
      Chart.defaults.color       = '#6B7280'
      // 關掉全域動畫：trend 這張圖在同一次分頁切換裡會被建立兩次（一次用
      // casesAll 退回值先畫，_loadTrendData() 抓到真實 receivedAt 資料後再重建
      // 一次），Chart.js 預設用 requestAnimationFrame 驅動的漸進動畫繪製，第一
      // 次建立的動畫還沒畫完，第二次 destroy() 就把它砍了，砍掉後那個還沒觸發
      // 的 rAF callback照樣會在下一影格嘗試繼續畫，此時 ctx 已經被清空，直接
      // 噴 Uncaught TypeError: Cannot read properties of null (reading 'save')
      // ——每次切到這個頁籤幾乎都會炸一次，只是不影響其他已經同步畫完的圖，
      // 不容易被發現。關掉動畫後 Chart.js 在建構/update 當下就同步畫完，不再
      // 有任何跨越多個影格的未完成繪製，從根本上排除這整類 race。
      Chart.defaults.animation = false
      try { this._buildTrendChart()  } catch(e) { console.error('trend chart:', e) }
      try { this._buildStatusChart() } catch(e) { console.error('status chart:', e) }
      if (this.salesPerf.length > 0)
        try { this._buildSalesPerfChart() } catch(e) { console.error('sales chart:', e) }
      if (this.achievement && this.achievement.hasTargets)
        try { this._buildTargetChart() } catch(e) { console.error('target chart:', e) }
      if (this.marginCases.length > 0)
        try { this._buildMarginChart() } catch(e) { console.error('margin chart:', e) }
      // 五張圖是在同一輪同步迴圈裡陸續建立的，每建一張、卡片版面就可能因為
      // 相鄰卡片高度變化再收斂一次，讓 Chart.js 建構當下量到的 canvas 尺寸
      // 過期（實測會出現座標軸畫對了、長條/線段卻沒畫上去的空白圖）。全部
      // 建完後再等下一個影格統一補一次 resize，用瀏覽器這時已經穩定的版面
      // 重新量一次，修正這種殘留的過期尺寸。
      var self = this
      requestAnimationFrame(function() {
        Object.values(_reportCharts).forEach(function(c) { try { c.resize() } catch(_) {} })
      })
    },

    _buildTrendChart() {
      var el = document.getElementById('rpt-chart-trend')
      if (!el) return

      // Use trendData (real collection by receivedAt) when loaded; fall back to casesAll aggregation
      var months = []
      if (this.trendData && this.trendData.length) {
        months = this.trendData.map(function(t) { return { key: t.key, label: t.label } })
      } else if (this.periodType === 'year') {
        for (var m = 1; m <= 12; m++) {
          months.push({ key: this.year + '-' + String(m).padStart(2, '0'), label: m + '月' })
        }
      } else {
        var endMo = this.periodType === 'quarter' ? this.quarter * 3 : this.month
        for (var i = 11; i >= 0; i--) {
          var d = new Date(this.year, endMo - 1 - i, 1)
          months.push({
            key:   d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0'),
            label: (d.getMonth() + 1) + '/' + String(d.getFullYear()).slice(2)
          })
        }
      }

      var counts = {}, revenues = {}, collected = {}
      months.forEach(function(m) { counts[m.key] = 0; revenues[m.key] = 0; collected[m.key] = null })

      if (this.trendData && this.trendData.length) {
        this.trendData.forEach(function(t) {
          if (t.key in counts) {
            counts[t.key]    = t.newCases
            revenues[t.key]  = t.revenue
            collected[t.key] = t.collected
          }
        })
      } else {
        this.casesAll.forEach(function(c) {
          var mk = (c.quoteDate || '').slice(0, 7)
          if (mk in counts) { counts[mk]++; revenues[mk] += (c.total || 0) }
        })
      }

      var hasTrend = this.trendData && this.trendData.length > 0
      var datasets = [
        {
          label: '成案件數',
          data:  months.map(function(m) { return counts[m.key] }),
          backgroundColor: 'rgba(37,99,235,0.75)',
          borderRadius: 4,
          yAxisID: 'yL',
          order: 3
        },
        {
          label: '合約金額',
          data:  months.map(function(m) { return revenues[m.key] }),
          type: 'line',
          borderColor: '#15803D',
          backgroundColor: 'rgba(21,128,61,0.08)',
          pointBackgroundColor: '#15803D',
          pointRadius: 3,
          tension: 0.4,
          fill: true,
          yAxisID: 'yR',
          order: 2
        }
      ]
      if (hasTrend) {
        datasets.push({
          label: '實收金額',
          data:  months.map(function(m) { return collected[m.key] }),
          type: 'line',
          borderColor: '#D97706',
          backgroundColor: 'rgba(217,119,6,0.05)',
          pointBackgroundColor: '#D97706',
          pointRadius: 3,
          borderDash: [4, 3],
          tension: 0.4,
          fill: false,
          yAxisID: 'yR',
          order: 1
        })
      }

      var self0 = this
      this.chartTables.trend = {
        cols:   hasTrend ? ['成案件數', '合約金額', '實收金額'] : ['成案件數', '合約金額'],
        colors: hasTrend ? ['#2563EB', '#15803D', '#D97706'] : ['#2563EB', '#15803D'],
        rows:   months.map(function(m) {
          var vals = [self0._fmtInt(counts[m.key]), self0._fmtMoney(revenues[m.key])]
          if (hasTrend) vals.push(self0._fmtMoney(collected[m.key]))
          return { label: m.label, values: vals }
        }),
      }

      if (_reportCharts.trend) {
        try { _reportCharts.trend.destroy() } catch(_) {}
      }
      _reportCharts.trend = new Chart(el, {
        type: 'bar',
        data: {
          labels:   months.map(function(m) { return m.label }),
          datasets: datasets
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          interaction: { mode: 'index', intersect: false },
          plugins: {
            legend: { position: 'top', labels: { font: { size: 11 }, padding: 12, usePointStyle: true } },
            tooltip: {
              callbacks: {
                label: function(ctx) {
                  if (ctx.dataset.label === '成案件數') return '成案數：' + ctx.raw + ' 件'
                  return ctx.dataset.label + '：NT$ ' + Math.round(ctx.raw || 0).toLocaleString()
                }
              }
            }
          },
          scales: {
            x: {
              ticks: {
                font: { size: 10 },
                autoSkip: false,
                callback: function(_v, idx) {
                  var m = months[idx]
                  if (!m) return ''
                  var amt = revenues[m.key] || 0
                  // 第二行是這個月的合約金額。0 元不印「NT$ 0」——一整排 0
                  // 只是噪音，空白本身就讀得出「這個月沒有」。
                  return amt ? [m.label, _shortMoney(amt)] : [m.label, '']
                }
              },
              grid: { display: false }
            },
            yL: {
              type: 'linear', position: 'left', beginAtZero: true,
              ticks: { stepSize: 1, font: { size: 10 } },
              grid: { color: 'rgba(0,0,0,0.05)' },
              title: { display: true, text: '件數', font: { size: 10 } }
            },
            yR: {
              type: 'linear', position: 'right', beginAtZero: true,
              grid: { display: false },
              ticks: {
                font: { size: 10 },
                callback: function(v) {
                  if (v >= 1000000) return (v / 1000000).toFixed(1) + 'M'
                  if (v >= 1000)    return (v / 1000).toFixed(0) + 'K'
                  return v
                }
              },
              title: { display: true, text: '金額', font: { size: 10 } }
            }
          }
        }
      })
    },

    _buildStatusChart() {
      var el = document.getElementById('rpt-chart-status')
      if (!el) return
      var s = this.summary
      var total = s.totalCases || 0
      var self1 = this
      this.chartTables.status = {
        cols:   ['件數', '佔比'],
        colors: ['#F59E0B', '#6B7280'],
        rows:   [
          { label: '進行中', values: [self1._fmtInt(s.activeCases || 0),
                                      self1._fmtPct(total ? (s.activeCases || 0) / total * 100 : 0)] },
          { label: '已結案', values: [self1._fmtInt(s.closedCases || 0),
                                      self1._fmtPct(total ? (s.closedCases || 0) / total * 100 : 0)] },
          { label: '合計',   values: [self1._fmtInt(total), '100%'] },
        ],
      }
      _reportCharts.status = new Chart(el, {
        type: 'doughnut',
        data: {
          labels: ['進行中', '已結案'],
          datasets: [{
            data: [s.activeCases || 0, s.closedCases || 0],
            backgroundColor: ['#F59E0B', '#6B7280'],
            hoverBackgroundColor: ['#D97706', '#4B5563'],
            borderWidth: 2,
            borderColor: '#fff'
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          cutout: '65%',
          plugins: {
            // 圖例直接帶件數與佔比：原本這兩個數字只活在 tooltip 裡，
            // 圖上就只有兩塊顏色配兩個純文字標籤，等於得滑過去才知道多少件。
            legend: {
              position: 'bottom',
              labels: {
                font: { size: 11 }, padding: 14, usePointStyle: true,
                generateLabels: function(chart) {
                  var ds = chart.data.datasets[0]
                  return chart.data.labels.map(function(lb, i) {
                    var v = ds.data[i] || 0
                    var pct = total > 0 ? Math.round(v / total * 100) : 0
                    return {
                      text: lb + '　' + v + ' 件（' + pct + '%）',
                      fillStyle: ds.backgroundColor[i],
                      strokeStyle: ds.backgroundColor[i],
                      pointStyle: 'circle',
                      index: i
                    }
                  })
                }
              }
            },
            tooltip: {
              callbacks: {
                label: function(ctx) {
                  var pct = total > 0 ? Math.round(ctx.raw / total * 100) : 0
                  return ctx.label + '：' + ctx.raw + ' 件 (' + pct + '%)'
                }
              }
            }
          }
        }
      })
    },

    _buildSalesPerfChart() {
      var el = document.getElementById('rpt-chart-sales')
      if (!el) return
      var sp = this.salesPerf.slice(0, 8)
      var self2 = this
      this.chartTables.sales = {
        cols:   ['件數', '合約總額', '已收款', '收款率', '平均毛利率'],
        colors: ['', '#2563EB', '#15803D', '', ''],
        rows:   sp.map(function(x) {
          return { label: x.salesPerson, values: [
            self2._fmtInt(x.caseCount),
            self2._fmtMoney(x.totalAmount),
            self2._fmtMoney(x.receivedAmount),
            self2._fmtPct(x.collectionRate),
            self2._fmtPct(x.avgMarginPct),
          ] }
        }),
      }
      _reportCharts.sales = new Chart(el, {
        type: 'bar',
        data: {
          labels: sp.map(function(s) { return s.salesPerson }),
          datasets: [
            {
              label: '合約總額',
              data:  sp.map(function(s) { return s.totalAmount }),
              backgroundColor: 'rgba(37,99,235,0.75)',
              borderRadius: 4
            },
            {
              label: '已收款',
              data:  sp.map(function(s) { return s.receivedAmount }),
              backgroundColor: 'rgba(21,128,61,0.75)',
              borderRadius: 4
            }
          ]
        },
        options: {
          indexAxis: 'y',
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: 'top', labels: { font: { size: 11 }, padding: 12, usePointStyle: true } },
            tooltip: {
              callbacks: {
                label: function(ctx) {
                  return ctx.dataset.label + '：NT$ ' + Math.round(ctx.raw || 0).toLocaleString()
                }
              }
            }
          },
          scales: {
            x: {
              beginAtZero: true,
              ticks: {
                font: { size: 10 },
                callback: function(v) {
                  if (v >= 1000000) return (v / 1000000).toFixed(1) + 'M'
                  if (v >= 1000)    return (v / 1000).toFixed(0) + 'K'
                  return v
                }
              },
              grid: { color: 'rgba(0,0,0,0.05)' }
            },
            y: { ticks: { font: { size: 11 } } }
          }
        }
      })
    },

    _buildTargetChart() {
      var el = document.getElementById('rpt-chart-target')
      if (!el) return
      var ann  = ((this.achievement || {}).annual) || {}
      var LBLS = ['年度合約總額', '新成案數', '年度收款金額', '收款率', '平均淨毛利率', '年度實際毛利']
      var KEYS = ['revenue', 'newCases', 'collectionAmt', 'collectionRate', 'avgMarginPct', 'grossProfit']
      var rates  = KEYS.map(function(k) { return (ann[k] && ann[k].rate != null) ? ann[k].rate : 0 })
      var colors = rates.map(function(r) {
        if (!r) return '#E5E7EB'
        return r >= 95 ? '#15803D' : r >= 80 ? '#D97706' : '#DC2626'
      })
      var self3 = this
      // 達成率圖上只有一條百分比，目標與實際到底是多少完全看不到——
      // 這一格正是使用者說「沒有詳細資訊」最明顯的地方。
      var PCT_KEYS = { collectionRate: 1, avgMarginPct: 1 }
      this.chartTables.target = {
        cols:   ['實績', '目標', '達成率'],
        colors: ['', '', ''],
        rows:   KEYS.map(function(k, i) {
          var d = ann[k] || {}
          var fmt = (k === 'newCases') ? self3._fmtInt
                  : PCT_KEYS[k]        ? self3._fmtPct
                  : self3._fmtMoney
          return { label: LBLS[i], values: [
            fmt.call(self3, d.actual),
            fmt.call(self3, d.target),
            self3._fmtPct(d.rate),
          ] }
        }),
      }
      _reportCharts.target = new Chart(el, {
        type: 'bar',
        data: {
          labels: LBLS,
          datasets: [
            {
              label: '達成率 %',
              data:  rates,
              backgroundColor: colors,
              borderRadius: 4
            },
            {
              label: '目標 100%',
              data:  LBLS.map(function() { return 100 }),
              type: 'line',
              borderColor: 'rgba(220,38,38,0.45)',
              borderWidth: 1.5,
              borderDash: [5, 3],
              pointRadius: 0,
              fill: false,
              tension: 0
            }
          ]
        },
        options: {
          indexAxis: 'y',
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: 'top', labels: { font: { size: 11 }, padding: 12, usePointStyle: true } },
            tooltip: {
              callbacks: {
                label: function(ctx) {
                  if (ctx.datasetIndex === 1) return '目標：100%'
                  return '達成率：' + (ctx.raw || 0).toFixed(1) + '%'
                }
              }
            }
          },
          scales: {
            x: {
              min: 0, max: 130,
              ticks: { font: { size: 10 }, callback: function(v) { return v + '%' } },
              grid: { color: 'rgba(0,0,0,0.05)' }
            },
            y: { ticks: { font: { size: 11 } } }
          }
        }
      })
    },

    _buildMarginChart() {
      var el = document.getElementById('rpt-chart-margin')
      if (!el) return
      var spMap = {}
      this.marginCases.forEach(function(mc) {
        var sp = mc.salesPerson || '未指定'
        if (!spMap[sp]) spMap[sp] = { est: [], act: [] }
        if (mc.netMarginPct    != null) spMap[sp].est.push(mc.netMarginPct)
        if (mc.actualMarginPct != null) spMap[sp].act.push(mc.actualMarginPct)
      })
      var labels    = Object.keys(spMap)
      var estimated = labels.map(function(sp) {
        var v = spMap[sp].est; return v.length ? v.reduce(function(a, b) { return a + b }, 0) / v.length : 0
      })
      var actual = labels.map(function(sp) {
        var v = spMap[sp].act; return v.length ? v.reduce(function(a, b) { return a + b }, 0) / v.length : null
      })
      var self4 = this
      this.chartTables.margin = {
        cols:   ['預估毛利率', '實際毛利率', '差異'],
        colors: ['#2563EB', '#15803D', ''],
        rows:   labels.map(function(lb, i) {
          var e = estimated[i], a = actual[i]
          return { label: lb, values: [
            self4._fmtPct(e),
            self4._fmtPct(a),
            // 沒有精算資料時差異不是 0，是「還不知道」——寫 0 會讓人以為準到不差
            (a == null) ? '—' : ((a - e >= 0 ? '+' : '') + self4._fmtPct(a - e)),
          ] }
        }),
      }
      _reportCharts.margin = new Chart(el, {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [
            { label: '預估毛利率',       data: estimated, backgroundColor: 'rgba(37,99,235,0.6)',  borderRadius: 4 },
            { label: '實際毛利率（精算）', data: actual,    backgroundColor: 'rgba(21,128,61,0.75)', borderRadius: 4 }
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: 'top', labels: { font: { size: 11 }, padding: 12, usePointStyle: true } },
            tooltip: {
              callbacks: {
                label: function(ctx) {
                  if (ctx.raw == null) return ctx.dataset.label + '：（無精算）'
                  return ctx.dataset.label + '：' + (ctx.raw || 0).toFixed(1) + '%'
                }
              }
            }
          },
          scales: {
            y: {
              beginAtZero: true,
              ticks: { font: { size: 10 }, callback: function(v) { return v + '%' } },
              grid: { color: 'rgba(0,0,0,0.05)' }
            },
            x: { ticks: { font: { size: 11 } } }
          }
        }
      })
    },

    // 🔴 Alpine 3 看到資料物件有 init() 就會**自己叫一次**，
    //    而 body 上那個明著呼叫初始化的屬性會再叫一次 ⇒ **跑兩遍**。
    // ☠️ 後果不只是 API 發兩次：第二次的回應晚一步抵達，
    //    會把使用者這段期間改過的欄位用伺服器上的舊值**無聲蓋回去**。
    _initDone: false,

    async init() {
      if (this._initDone) return
      this._initDone = true
      // 2026-08-31：出納模組併入本頁後的准入判斷放寬——admin+ 維持原行為
      // （全部 12 個財務報表頁籤＋出納頁籤都看得到）；純 cashier/finance 模組
      // 的非管理職使用者只開放出納頁籤，其餘財務報表資料完全不載入。
      if (!this.hasCashierAccess()) {
        this.error = '僅管理員以上可存取營運報表功能'
        return
      }
      if (!this.isAdminPlus()) {
        this.activeTab = 'cashier'
        await this.showCashierTab()
        return
      }
      // 極簡深連結支援：cashier.html 退役後改導向 reports.html?tab=cashier，
      // admin+ 使用者從那個連結進來時直接落在出納頁籤（其餘情況維持預設 targets）。
      var qsTab = new URLSearchParams(location.search).get('tab')
      if (qsTab === 'cashier') this.activeTab = 'cashier'
      try {
        var r = await fetch('/api/now')
        if (r.ok) {
          var t = await r.json()
          this.year    = t.year
          this.month   = t.month
          this.quarter = Math.ceil(t.month / 3)
        }
      } catch (_) {}
      // 期別同步＋子資料流載入都由 loadData() 內部統一處理（見 _syncSubPeriods()），
      // 這裡不再各自拼一次年月字串——原本那份手拼版本正是 2026-09-10 期別不同步
      // 的根因所在（只有 init 做了、切期別的路徑沒做）。年月一律用本地時區字串
      // 拼接，不用 toISOString()（UTC，台灣 UTC+8 每天 00:00-08:00 會誤判成前一天）。
      this.expensesLoadedFor    = null
      this.receivablesLoadedFor = null
      this.loadData()
      this.loadOrgTree()
      if (this.activeTab === 'cashier') this.showCashierTab()
      // 預設落在圖表頁時要主動觸發一次：圖表是懶建的（原本靠點頁籤才建），
      // 不呼叫的話畫布會是空的。
      if (this.activeTab === 'charts') this.showChartsTab()
      var self = this
      // Re-init charts when data changes and charts tab is active (e.g. period change)
      this.$watch('data', function(newData) {
        if (!newData || self.activeTab !== 'charts') return
        requestAnimationFrame(function() {
          requestAnimationFrame(function() { self.initCharts() })
        })
      })
    },

    showCustTab() {
      this.activeTab = 'cust'
      if (!this.custLoaded) this.loadCustHistory()
    },

    showExpensesTab() {
      this.activeTab = 'expenses'
      this._ensureSubPeriodData()
    },

    // 期別連續切換（例如 7 月 → 8 月按很快）會讓兩個請求同時在飛。快取鍵一定要在
    // 「發出請求當下」就算好並跟著這一次請求走：原本是在回應抵達時才算，若期別在
    // 飛行途中被切走，就會把 7 月的資料貼上 8 月的鍵，之後 _ensureSubPeriodData()
    // 看鍵相符便不再重載，畫面永遠卡在舊月份。這正是 e2e 測試偶發抓到的競態。
    async loadExpenses() {
      var key = this._expensesKey()
      var qs = '?year=' + this.expensesYear + '&month=' + this.expensesMonth +
               (this.expensesScope === 'quarter' ? '&quarter=' + this.expensesQuarter : '') +
               (this.departmentId ? '&department_id=' + this.departmentId : '') +
               '&basis=' + this.expensesBasis
      this.expensesInflight = key
      this.expensesLoading  = true
      try {
        var res = await fetch('/api/reports/expenses-monthly' + qs, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) throw new Error('支出明細載入失敗')
        var payload = await res.json()
        // 期別已經被切走 → 這份回應過期了，丟棄（切走的那一次自己會發新請求）
        if (key !== this._expensesKey()) return
        this.expensesData      = payload
        this.expensesLoadedFor = key
      } catch (e) {
        if (key === this._expensesKey()) alert('支出明細載入失敗：' + (e.message || e))
      } finally {
        if (this.expensesInflight === key) this.expensesInflight = null
        if (key === this._expensesKey()) this.expensesLoading = false
      }
    },

    showReceivablesTab(tab) {
      this.activeTab = tab
      this._ensureSubPeriodData()
    },

    // 過期回應丟棄機制同 loadExpenses()，理由見該函式註解。
    async loadReceivables() {
      var key = this._receivablesKey()
      var qs = '?year=' + this.receivablesYear + '&month=' + this.receivablesMonth +
               (this.receivablesScope === 'quarter' ? '&quarter=' + this.receivablesQuarter : '') +
               (this.departmentId ? '&department_id=' + this.departmentId : '')
      this.receivablesInflight = key
      this.receivablesLoading  = true
      try {
        var res = await fetch('/api/reports/receivables-monthly' + qs, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) throw new Error('應收明細載入失敗')
        var payload = await res.json()
        if (key !== this._receivablesKey()) return
        this.receivablesData      = payload
        this.receivablesLoadedFor = key
      } catch (e) {
        if (key === this._receivablesKey()) alert('應收明細載入失敗：' + (e.message || e))
      } finally {
        if (this.receivablesInflight === key) this.receivablesInflight = null
        if (key === this._receivablesKey()) this.receivablesLoading = false
      }
    },

    async showArTab() {
      this.activeTab = 'ar'
      if (this.arLoaded) return
      this.arLoading = true
      try {
        var res = await fetch('/api/reports/ar-aging', {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) throw new Error('帳齡載入失敗')
        this.arAging  = await res.json()
        this.arLoaded = true
      } catch (e) {
        alert('帳齡分析載入失敗：' + (e.message || e))
      } finally {
        this.arLoading = false
      }
    },


    // 已確認清單：預設帶目前日期區間，區間留空時後端回最近 500 筆

    // 反確認：撤銷單筆「已匯入」標記，該事件會在下次涵蓋其日期的匯出/預覽重新出現

    // 科目代號設定完成度（視覺化提示用，非阻擋匯出的硬性檢查）：核心科目
    // （銷貨收入/銷項稅額/承攬商費用）與至少一個銀行帳戶都設定了，才算「已設定」。
    // 料件分類科目代號允許部分留白（可能有些分類真的沒進貨過），不列入判斷。

    async showCashPosTab() {
      this.activeTab = 'cashpos'
      if (this.cashPosLoaded) return
      this.cashPosLoading = true
      try {
        var res = await fetch('/api/reports/cash-position', {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) throw new Error('資金水位載入失敗')
        this.cashPos       = await res.json()
        this.cashPosLoaded = true
      } catch (e) {
        alert('資金水位載入失敗：' + (e.message || e))
      } finally {
        this.cashPosLoading = false
      }
    },

    // ── 出納頁籤（2026-08-31 併入本頁，原 frontend/js/cashier.js 內容原封不動
    // 搬過來，只改了跟本檔案既有狀態衝突的名稱，見上方 state 區塊註解）────────

    get kpiPayableTotal() {
      return this.payable.reduce((s, v) => s + (v.grandTotal || 0), 0)
    },
    get kpiReceivableTotal() {
      return this.receivable.filter(i => !i.received).reduce((s, i) => s + (i.amount || 0), 0)
    },


    async showCashierTab() {
      this.activeTab = 'cashier'
      if (this.cashierLoaded) return
      const today = new Date()
      this.cashierHistoryStart = this._localDateStr(new Date(today.getFullYear(), today.getMonth(), 1))
      this.cashierHistoryEnd = this._localDateStr(today)
      await Promise.all([this.loadPayable(), this.loadReceivable(), this.loadCashierHistory()])
      this.cashierLoaded = true
    },

    async loadPayable() {
      try {
        const r = await fetch('/api/cashier/payable-queue', { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) this.payable = await r.json()
        else if (r.status === 403) this.error = '僅管理員、出納或財務可存取出納功能'
      } catch (e) { console.error(e) }
    },

    async loadReceivable() {
      try {
        const r = await fetch('/api/cashier/receivable-queue?status=all', { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) this.receivable = await r.json()
        else if (r.status === 403) this.error = '僅管理員、出納或財務可存取出納功能'
      } catch (e) { console.error(e) }
    },

    async loadCashierHistory() {
      this.cashierHistoryLoading = true
      try {
        const qs = `?start=${this.cashierHistoryStart}&end=${this.cashierHistoryEnd}`
        const r = await fetch('/api/cashier/execution-history' + qs, { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) {
          const d = await r.json()
          this.cashierHistoryOutgoing = d.outgoing || []
          this.cashierHistoryIncoming = d.incoming || []
          this.cashierHistoryOutgoingTotal = d.outgoingTotal || 0
          this.cashierHistoryIncomingTotal = d.incomingTotal || 0
        }
      } catch (e) { console.error(e) }
      this.cashierHistoryLoading = false
    },




    // 銀行帳戶預設值（2026-09-02 新增）：①這個對象上次標記用的帳戶 ②系統
    // 預設帳戶 ③兩者都沒有就空白。lastUsedUrl 由呼叫端組好（各自對象不同）。













    async exportTaxInvoices() {
      this.taxExporting = true
      try {
        var qs = 'year=' + this.taxExportYear + (this.taxExportMonth ? '&month=' + this.taxExportMonth : '')
        var res = await fetch('/api/reports/tax-export?' + qs, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '匯出失敗')
        }
        var blob = await res.blob()
        var label = this.taxExportYear + (this.taxExportMonth ? ('_' + String(this.taxExportMonth).padStart(2, '0')) : '')
        var a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = 'MOTRIX_銷項發票清單_' + label + '.xlsx'
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(a.href)
      } catch (e) {
        alert('稅務匯出失敗：' + (e.message || e))
      } finally {
        this.taxExporting = false
      }
    },

    // ── T100（鼎新）傳票批次匯出 ──────────────────────────────────────────────





    // 財務人員實際到 T100 匯入後，回來按這顆按鈕標記整批已匯入——標記後這些
    // 事件會從之後所有匯出/預覽自動排除，避免重複匯入

    async _loadTrendData() {
      this.trendLoading = true
      try {
        var res = await fetch('/api/reports/monthly-trend?months=12', {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (res.ok) {
          this.trendData   = await res.json()
          this.trendLoaded = true
          if (this.activeTab === 'charts') {
            var self = this
            this.$nextTick(function() {
              requestAnimationFrame(function() {
                try { self._buildTrendChart() } catch(e) { console.error('trend rebuild:', e) }
              })
            })
          }
        }
      } catch (_) {}
      this.trendLoading = false
    },

    async loadCustHistory() {
      this.custLoading = true
      try {
        var res = await fetch('/api/reports/customer-history', {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (res.ok) {
          var d = await res.json()
          this.custHistory = d.customers || []
          this.custLoaded  = true
        }
      } catch (_) {}
      this.custLoading = false
    },

    selectCust(c) {
      this.selectedCust = (this.selectedCust && this.selectedCust.customer === c.customer) ? null : c
    },

    custAmtFmt(n) {
      if (!n) return '—'
      return 'NT$ ' + Math.round(n).toLocaleString()
    },

    // Called by the 圖表分析 tab button. $nextTick waits for Alpine to finish
    // patching the DOM for this activeTab change (the x-show toggle that
    // actually reveals the chart cards) — the same pattern already used
    // elsewhere in this codebase (e.g. case-management.js's
    // this.$nextTick(() => this._initSubListSortable(...))) before touching
    // freshly-shown DOM with a third-party library. The extra rAF on top
    // waits for the browser to actually complete a layout pass, since
    // Chart.js reads the canvas's rendered size at construction time.
    showChartsTab() {
      this.activeTab = 'charts'
      this._loadPayableSnapshot()
      if (!this.data) return
      if (!this.trendLoaded && !this.trendLoading) this._loadTrendData()
      var self = this
      this.$nextTick(function() {
        requestAnimationFrame(function() {
          if (Object.keys(_reportCharts).length === 0) {
            self.initCharts()
          } else {
            Object.values(_reportCharts).forEach(function(c) { try { c.resize() } catch(_) {} })
          }
        })
      })
    }
  }
}
