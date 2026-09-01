/* global Alpine */
// Chart.js 實例故意放在 Alpine reactive data 之外（見 initCharts() 註解說明原因）
const _reportCharts = {}

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
    t100Start:        new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().slice(0, 10),
    t100End:          new Date().toISOString().slice(0, 10),
    t100Exporting:    false,
    t100ConfigOpen:   false,
    t100Config:       null,
    t100ConfigLoaded: false,
    t100ConfigSaving: false,
    t100Preview:      null,   // {count, totalAmount, events:[...]}，未確認事件預覽
    t100Previewing:   false,
    t100Confirming:   false,

    // 銀行對帳單比對（連同標記已匯款 Modal）2026-08-31 搬到出納模組
    // frontend/js/cashier.js（財務/出納權限分工，見那邊同一輪改動），
    // 這裡不再重複維護一份。

    // ── Monthly trend
    trendData:    null,
    trendLoading: false,
    trendLoaded:  false,

    // ── 收支報表（原「月支出」，2026-08-30 重構為《當月收支》/《今年度收支》）──
    expensesScope:     'month', // month/year — 畫面上目前顯示哪個範圍
    expensesYear:      new Date().getFullYear(),
    expensesMonth:     new Date().toISOString().slice(0, 7),  // 'YYYY-MM'，當月範圍用
    expensesData:      null,
    expensesLoading:   false,
    expensesLoadedFor: null,   // 記錄已載入資料對應的年度+月份，切換時判斷要不要重打 API
    expensesFilter:    'all',  // all/contractor/equipment/material/other，支出明細的類別篩選 chip

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
    cashierSub:    'payable',   // payable/receivable/history/bank，出納頁籤內部子頁籤
    cashierLoaded: false,       // 出納頁籤第一次打開時 payable+receivable+history 一次性彙整載入 guard

    payable:    [],
    receivable: [],   // status=all，含已收+未收全部歷史（併入 receivables.html 用途）

    receivableSearch:    '',
    receivableFilterTab: 'unreceived',   // all / unreceived / received / uninvoiced

    payVoucherModal:   false,
    payVoucherTarget:  null,
    payVoucherDate:    '',
    payVoucherNote:    '',
    payVoucherBankAcctCode: '',
    payVoucherSaving:  false,

    receiveModal:         false,
    receiveTarget:        null,
    receiveDate:          '',
    receiveActualAmount:  null,
    receiveFeeAmount:     0,
    receiveNote:          '',
    receiveBankAcctCode:  '',
    receiveSaving:        false,
    // T100 傳票匯出設定裡的銀行帳戶清單（2026-09-01 新增），標記已收款/已匯款
    // 時挑選要用哪個帳戶；每次開啟標記 Modal 都重抓最新清單，見
    // loadT100BankAccounts()
    t100BankAccounts:     [],

    invoiceModal: { show: false, item: null, no: '' },

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
    cashierExporting: false,

    bankReconciling: false,
    bankResult:      null,
    bankPayModal:    false,
    bankPayRow:      null,
    bankPayDate:     '',
    bankPaySaving:   false,

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
    get periodItems()  { return (this.data || {}).periodItems || [] },
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
    get outstanding()  { return (this.data || {}).outstanding || [] },
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
    get yearIncomeItems()   { return (this.expensesData || {}).yearIncomeItems   || [] },
    get yearIncomeTotal()   { return (this.expensesData || {}).yearIncomeTotal   || 0 },
    // 目前選取範圍（當月/今年度）對應的收入/支出明細＋淨額，畫面統一透過這幾個 getter 讀取
    get activeIncomeItems() { return this.expensesScope === 'month' ? this.monthIncomeItems : this.yearIncomeItems },
    get filteredExpenseItems() {
      var items = this.expensesScope === 'month' ? this.monthExpenseItems : this.yearExpenseItemsAll
      if (this.expensesFilter === 'all') return items
      return items.filter(function(x) { return x.cat === this.expensesFilter }, this)
    },
    get netScopeAmount() {
      var income  = this.expensesScope === 'month' ? this.monthIncomeTotal  : this.yearIncomeTotal
      var expense = this.expensesScope === 'month' ? this.monthExpenseTotal : this.expensesTotals.total
      return income - (expense || 0)
    },
    expensesCatLabel(cat) {
      return { contractor: '承攬商派發', equipment: '設備進貨', material: '料件進貨', other: '其他支出' }[cat] || cat
    },
    get casesPeriod()  { return (this.data || {}).casesPeriod || [] },
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
    _displayName() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.displayName || s.username || ''
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
    canExecuteCashier() {
      return this.isAdminPlus() || this._modules().includes('cashier')
    },
    // 本地日期字串（YYYY-MM-DD），不用 toISOString()（UTC，台灣 UTC+8 每天
    // 00:00-08:00 之間會誤判成前一天，比照 case-management.js/cashier.js 同款修法）。
    _localDateStr(d) {
      d = d || new Date()
      const tz = d.getTimezoneOffset() * 60000
      return new Date(d.getTime() - tz).toISOString().slice(0, 10)
    },

    // ── Load preview data ─────────────────────────────────────────────────────
    async loadData() {
      if (!this.isAdminPlus()) {
        if (!this.hasCashierAccess()) this.error = '僅管理員以上可存取營運報表功能'
        return
      }
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
        this.data = await res.json()
        if (this.activeTab === 'expenses') this.loadExpenses()
      } catch (e) {
        this.error = e.message || '載入錯誤'
      } finally {
        this.loading = false
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
      var url = '/api/reports/financial/' + fmt + '?period=' + this.periodParam +
                '&expense_month=' + this.expensesMonth +
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

    activeTab: 'targets',

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
            legend: { position: 'bottom', labels: { font: { size: 11 }, padding: 14, usePointStyle: true } },
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

    async init() {
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
      this.loadData()
      this.loadOrgTree()
      if (this.activeTab === 'cashier') this.showCashierTab()
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
      var key = this.expensesYear + ':' + this.expensesMonth + ':' + (this.departmentId || '')
      if (this.expensesLoadedFor !== key) this.loadExpenses()
    },

    async loadExpenses() {
      this.expensesLoading = true
      try {
        var qs = '?year=' + this.expensesYear + '&month=' + this.expensesMonth +
                 (this.departmentId ? '&department_id=' + this.departmentId : '')
        var res = await fetch('/api/reports/expenses-monthly' + qs, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) throw new Error('支出明細載入失敗')
        this.expensesData      = await res.json()
        this.expensesLoadedFor = this.expensesYear + ':' + this.expensesMonth + ':' + (this.departmentId || '')
      } catch (e) {
        alert('支出明細載入失敗：' + (e.message || e))
      }
      this.expensesLoading = false
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

    async showT100Tab() {
      // 2026-09-02：T100 匯出從資金水位頁籤拆成獨立頁籤，切換進來時就先預覽
      // 本期待確認事件＋讀科目代號設定（不用展開設定面板才看得到 KPI 統計），
      // 不用再多按一次「預覽待確認事件」
      this.activeTab = 't100'
      if (!this.t100Preview) this.loadT100Preview()
      if (!this.t100Config) this.loadT100Config()
    },

    // 科目代號設定完成度（視覺化提示用，非阻擋匯出的硬性檢查）：核心科目
    // （銷貨收入/銷項稅額/承攬商費用）與至少一個銀行帳戶都設定了，才算「已設定」。
    // 料件分類科目代號允許部分留白（可能有些分類真的沒進貨過），不列入判斷。
    get t100ConfigComplete() {
      const c = this.t100Config
      if (!c) return false
      const coreFilled = c.salesRevenueAccount && c.outputTaxAccount && c.contractorExpenseAccount
      const hasBank = c.bankAccounts && c.bankAccounts.length > 0 && c.bankAccounts.every(b => b.name && b.acctCode)
      return !!(coreFilled && hasBank)
    },

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
    get kpiPayableOverdue() {
      return this.payable.filter(v => this.isOverdue(v.payableDate)).length
    },
    get kpiReceivableTotal() {
      return this.receivable.filter(i => !i.received).reduce((s, i) => s + (i.amount || 0), 0)
    },
    get kpiReceivableOverdue() {
      return this.receivable.filter(i => i.overdue).length
    },
    get filteredReceivable() {
      let list = this.receivable
      if (this.receivableFilterTab === 'unreceived') list = list.filter(i => !i.received)
      if (this.receivableFilterTab === 'received')   list = list.filter(i => i.received)
      if (this.receivableFilterTab === 'uninvoiced') list = list.filter(i => !i.invoiceNo)
      const q = this.receivableSearch.trim().toLowerCase()
      if (q) list = list.filter(i =>
        (i.quoteNo || '').toLowerCase().includes(q) ||
        (i.customer || '').toLowerCase().includes(q) ||
        (i.type || '').toLowerCase().includes(q) ||
        (i.invoiceNo || '').toLowerCase().includes(q)
      )
      return list
    },
    get receivableUninvoicedCount() {
      return this.receivable.filter(i => !i.invoiceNo).length
    },

    isOverdue(dateStr) {
      return !!dateStr && dateStr < this._localDateStr()
    },
    isDueSoon(dateStr) {
      if (!dateStr || this.isOverdue(dateStr)) return false
      const soon = new Date()
      soon.setDate(soon.getDate() + 7)
      return dateStr <= this._localDateStr(soon)
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

    async exportCashierHistory() {
      this.cashierExporting = true
      try {
        const qs = `?start=${this.cashierHistoryStart}&end=${this.cashierHistoryEnd}`
        const r = await fetch('/api/cashier/export' + qs, { headers: { Authorization: 'Bearer ' + this._token() } })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '匯出失敗'); this.cashierExporting = false; return }
        const blob = await r.blob()
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = `MOTRIX_出納執行紀錄_${this.cashierHistoryStart}_${this.cashierHistoryEnd}.xlsx`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(a.href)
      } catch (e) { alert('匯出失敗：' + e.message) }
      this.cashierExporting = false
    },

    async loadT100BankAccounts() {
      // 2026-09-02：改成每次開啟標記 Modal 都重抓（不再 cache-once），確保跟
      // 案件管理／庫存管理三處標記畫面共用同一份最新清單，見
      // case-management.js::loadT100BankAccounts() 同款註解。
      try {
        const r = await fetch('/api/settings/t100-export-config', { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) { const d = await r.json(); this.t100BankAccounts = d.bankAccounts || [] }
      } catch {}
    },

    _t100BankName(code) {
      return (this.t100BankAccounts.find(b => b.acctCode === code) || {}).name || ''
    },

    openPayVoucherModal(v) {
      this.payVoucherTarget = v
      this.payVoucherBankAcctCode = ''
      this.loadT100BankAccounts()
      this.payVoucherDate = v.payableDate || this._localDateStr()
      this.payVoucherNote = ''
      this.payVoucherModal = true
    },

    async confirmPayVoucher() {
      const v = this.payVoucherTarget
      if (!v || !this.payVoucherDate) return
      this.payVoucherSaving = true
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/paid-toggle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({
            action: 'pay', paid_at: this.payVoucherDate, note: this.payVoucherNote,
            bankAccountCode: this.payVoucherBankAcctCode, bankAccountName: this._t100BankName(this.payVoucherBankAcctCode),
          })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); this.payVoucherSaving = false; return }
        this.payVoucherModal = false
        this.payVoucherTarget = null
        await Promise.all([this.loadPayable(), this.loadCashierHistory()])
      } catch (e) { alert('網路錯誤：' + e.message) }
      this.payVoucherSaving = false
    },

    openReceiveModal(it) {
      this.receiveTarget = it
      this.receiveDate = this._localDateStr()
      this.receiveActualAmount = it.amount
      this.receiveFeeAmount = 0
      this.receiveNote = ''
      this.receiveBankAcctCode = ''
      this.loadT100BankAccounts()
      this.receiveModal = true
    },

    async confirmReceive() {
      const it = this.receiveTarget
      if (!it || !this.receiveDate) return
      this.receiveSaving = true
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(it.quoteNo)}/payment/${it.idx}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({
            received: true, receivedAt: this.receiveDate, receivedBy: this._displayName(),
            actualAmount: this.receiveActualAmount, feeAmount: this.receiveFeeAmount || 0, note: this.receiveNote,
            bankAccountCode: this.receiveBankAcctCode, bankAccountName: this._t100BankName(this.receiveBankAcctCode),
          })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); this.receiveSaving = false; return }
        this.receiveModal = false
        this.receiveTarget = null
        await Promise.all([this.loadReceivable(), this.loadCashierHistory()])
      } catch (e) { alert('網路錯誤：' + e.message) }
      this.receiveSaving = false
    },

    async toggleReceived(item, received) {
      if (!confirm(received ? '標記此款項為已收？' : '取消此款項的收款紀錄？')) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(item.quoteNo)}/payment/${item.idx}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ received, receivedAt: '', receivedBy: '' })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); return }
        await this.loadReceivable()
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    openInvoiceModal(item) {
      this.invoiceModal = { show: true, item, no: item.invoiceNo || '' }
    },

    async confirmInvoice() {
      const item = this.invoiceModal.item
      if (!item) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(item.quoteNo)}/payment/${item.idx}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ invoiceNo: this.invoiceModal.no.trim() })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); return }
        item.invoiceNo = this.invoiceModal.no.trim()
        this.invoiceModal.show = false
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async uploadBankCsv(evt) {
      var file = evt.target.files[0]
      if (!file) return
      this.bankReconciling = true
      this.bankResult = null
      try {
        var fd = new FormData()
        fd.append('file', file)
        var res = await fetch('/api/reports/bank-reconcile', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this._token() },
          body: fd,
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '比對失敗')
        }
        this.bankResult = await res.json()
      } catch (e) {
        alert('銀行對帳比對失敗：' + (e.message || e))
      } finally {
        this.bankReconciling = false
        evt.target.value = ''
      }
    },

    _guessDateFromBankText(raw) {
      const s = (raw || '').trim()
      if (!s) return ''
      let m = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/)
      if (m) return this._normalizeYmd(+m[1], +m[2], +m[3])
      m = s.match(/^(\d{4})(\d{2})(\d{2})(\d{0,6})?$/)
      if (m) return this._normalizeYmd(+m[1], +m[2], +m[3])
      // 民國年（台灣銀行常見，例如 115/08/20 = 2026/08/20）
      m = s.match(/^(\d{2,3})[-/.](\d{1,2})[-/.](\d{1,2})$/)
      if (m && +m[1] >= 1 && +m[1] <= 200) return this._normalizeYmd(+m[1] + 1911, +m[2], +m[3])
      return ''
    },

    _normalizeYmd(y, mo, d) {
      if (mo < 1 || mo > 12 || d < 1 || d > 31) return ''
      const dt = new Date(y, mo - 1, d)
      if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return ''
      return y + '-' + String(mo).padStart(2, '0') + '-' + String(d).padStart(2, '0')
    },

    openBankPayModal(row) {
      if (!row || !row.match) return
      this.bankPayRow = row
      this.bankPayDate = this._guessDateFromBankText(row.date) || this._localDateStr()
      this.bankPayModal = true
    },

    async confirmBankPay() {
      const row = this.bankPayRow
      if (!row || !row.match || !this.bankPayDate) return
      const voucherNo = row.match.voucherNo
      this.bankPaySaving = true
      try {
        var res = await fetch('/api/contractor-vouchers/' + voucherNo + '/paid-toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ action: 'pay', paid_at: this.bankPayDate, note: '銀行對帳單比對後標記' }),
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '標記失敗')
        }
        row.match._paid = true
        this.bankPayModal = false
        this.bankPayRow = null
        await Promise.all([this.loadPayable(), this.loadCashierHistory()])
      } catch (e) {
        alert('標記失敗：' + (e.message || e))
      }
      this.bankPaySaving = false
    },

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
    async loadT100Config() {
      if (this.t100ConfigLoaded) return
      try {
        var res = await fetch('/api/settings/t100-export-config', {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (res.ok) {
          this.t100Config = await res.json()
          this.t100ConfigLoaded = true
        }
      } catch (e) { /* 靜默失敗，畫面仍可用預設空白值操作 */ }
    },

    toggleT100Config() {
      this.t100ConfigOpen = !this.t100ConfigOpen
      if (this.t100ConfigOpen) this.loadT100Config()
    },

    async saveT100Config() {
      if (this._role() !== 'superadmin') return
      this.t100ConfigSaving = true
      try {
        var res = await fetch('/api/settings/t100-export-config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify(this.t100Config),
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '儲存失敗')
        }
        alert('已儲存 T100 科目代號設定')
      } catch (e) {
        alert('儲存失敗：' + (e.message || e))
      } finally {
        this.t100ConfigSaving = false
      }
    },

    async exportT100Vouchers() {
      if (!this.t100Start || !this.t100End || this.t100Start > this.t100End) {
        alert('請確認起訖日期區間正確')
        return
      }
      this.t100Exporting = true
      try {
        var qs = 'start=' + this.t100Start + '&end=' + this.t100End
        var res = await fetch('/api/reports/t100-export/vouchers?' + qs, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '匯出失敗')
        }
        var blob = await res.blob()
        var a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = 'MOTRIX_T100傳票匯出_' + this.t100Start + '_' + this.t100End + '.xlsx'
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(a.href)
      } catch (e) {
        alert('T100 傳票匯出失敗：' + (e.message || e))
      } finally {
        this.t100Exporting = false
      }
    },

    async loadT100Preview() {
      if (!this.t100Start || !this.t100End || this.t100Start > this.t100End) {
        alert('請確認起訖日期區間正確')
        return
      }
      this.t100Previewing = true
      try {
        var qs = 'start=' + this.t100Start + '&end=' + this.t100End
        var res = await fetch('/api/reports/t100-export/preview?' + qs, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '預覽失敗')
        }
        this.t100Preview = await res.json()
      } catch (e) {
        alert('T100 預覽失敗：' + (e.message || e))
      } finally {
        this.t100Previewing = false
      }
    },

    // 財務人員實際到 T100 匯入後，回來按這顆按鈕標記整批已匯入——標記後這些
    // 事件會從之後所有匯出/預覽自動排除，避免重複匯入
    async confirmT100Imported() {
      if (!this.t100Preview || !this.t100Preview.count) {
        alert('目前沒有可確認的事件，請先預覽')
        return
      }
      if (!confirm('確認這 ' + this.t100Preview.count + ' 筆事件已經實際匯入 T100？確認後將自動從之後的匯出/預覽排除，避免重複匯入。')) return
      this.t100Confirming = true
      try {
        var res = await fetch('/api/reports/t100-export/confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ start: this.t100Start, end: this.t100End }),
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '確認失敗')
        }
        var result = await res.json()
        alert('已標記 ' + result.confirmedCount + ' 筆事件為已匯入')
        this.loadT100Preview()
      } catch (e) {
        alert('確認已匯入失敗：' + (e.message || e))
      } finally {
        this.t100Confirming = false
      }
    },

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
