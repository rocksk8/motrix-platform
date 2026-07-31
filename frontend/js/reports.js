/* global Alpine */
function reportsApp() {
  return {
    // ── Period state ──────────────────────────────────────────────────────────
    periodType: 'month',
    year:       new Date().getFullYear(),
    month:      new Date().getMonth() + 1,
    quarter:    Math.ceil((new Date().getMonth() + 1) / 3),

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

    // ── Monthly trend
    trendData:    null,
    trendLoading: false,
    trendLoaded:  false,

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
    get outstanding()  { return (this.data || {}).outstanding || [] },
    get casesAll()     { return (this.data || {}).casesAll    || [] },
    get casesPeriod()  { return (this.data || {}).casesPeriod || [] },
    get salesPerf()    { return (this.data || {}).salesPerf   || [] },
    get marginCases()  { return (this.data || {}).marginCases || [] },
    get warranty()      { return (this.data || {}).warranty      || [] },
    get targets()       { return (this.data || {}).targets       || {} },
    get achievement()   { return (this.data || {}).achievement   || {} },
    get settleOverdue() { return (this.data || {}).settleOverdue || [] },

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

    // ── Load preview data ─────────────────────────────────────────────────────
    async loadData() {
      var role = this._role()
      if (role !== 'admin' && role !== 'superadmin') {
        this.error = '僅管理員以上可存取營運報表功能'
        return
      }
      this.loading = true
      this.error   = ''
      this.data    = null
      try {
        var res = await fetch('/api/reports/financial?period=' + this.periodParam, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '載入失敗')
        }
        this.data = await res.json()
      } catch (e) {
        this.error = e.message || '載入錯誤'
      } finally {
        this.loading = false
      }
    },

    // ── Export ────────────────────────────────────────────────────────────────
    async exportFile(fmt) {
      this.exporting  = true
      this.exportType = fmt
      var url = '/api/reports/financial/' + fmt + '?period=' + this.periodParam
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
    _charts:   {},

    // ── Charts (圖表分析) ──────────────────────────────────────────────────────
    initCharts() {
      Object.values(this._charts).forEach(function(c) { try { c.destroy() } catch(_) {} })
      this._charts = {}
      if (!this.data) return
      // Clear any lingering canvas state after destroy
      ;['rpt-chart-trend','rpt-chart-status','rpt-chart-sales','rpt-chart-target','rpt-chart-margin'].forEach(function(id) {
        var cv = document.getElementById(id)
        if (cv) { var ctx = cv.getContext('2d'); if (ctx) ctx.clearRect(0, 0, cv.width, cv.height) }
      })
      Chart.defaults.font.family = "'LINE Seed TW_OTF', sans-serif"
      Chart.defaults.font.size   = 11
      Chart.defaults.color       = '#6B7280'
      try { this._buildTrendChart()  } catch(e) { console.error('trend chart:', e) }
      try { this._buildStatusChart() } catch(e) { console.error('status chart:', e) }
      if (this.salesPerf.length > 0)
        try { this._buildSalesPerfChart() } catch(e) { console.error('sales chart:', e) }
      if (this.achievement && this.achievement.hasTargets)
        try { this._buildTargetChart() } catch(e) { console.error('target chart:', e) }
      if (this.marginCases.length > 0)
        try { this._buildMarginChart() } catch(e) { console.error('margin chart:', e) }
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

      if (this._charts.trend) {
        try { this._charts.trend.destroy() } catch(_) {}
      }
      this._charts.trend = new Chart(el, {
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
      this._charts.status = new Chart(el, {
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
      this._charts.sales = new Chart(el, {
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
      this._charts.target = new Chart(el, {
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
      this._charts.margin = new Chart(el, {
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
      var role = this._role()
      if (role !== 'admin' && role !== 'superadmin') {
        this.error = '僅管理員以上可存取營運報表功能'
        return
      }
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
            requestAnimationFrame(function() {
              try { self._buildTrendChart() } catch(e) { console.error('trend rebuild:', e) }
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

    // Called by the 圖表分析 tab button; uses rAF so layout is done before Chart.js measures canvas
    showChartsTab() {
      this.activeTab = 'charts'
      if (!this.data) return
      if (!this.trendLoaded && !this.trendLoading) this._loadTrendData()
      var self = this
      requestAnimationFrame(function() {
        requestAnimationFrame(function() {
          if (Object.keys(self._charts).length === 0) {
            self.initCharts()
          } else {
            Object.values(self._charts).forEach(function(c) { try { c.resize() } catch(_) {} })
          }
        })
      })
    }
  }
}
