  const API = '/api'

  /* ── Alpine 資料 ── */
  function dashboard() {
    return {
      today: '',
      now: '',
      session: {},
      stats: {
        totalQuotes: 0, pendingQuotes: 0, sentQuotes: 0,
        activeCases: 0, closedCases: 0, customerCount: 0,
        pendingList: [], paymentItems: [], warrantyWarnings: [],
        marginTop5: [], deviceSummary: {}, receivableSummary: {},
        marginComparison: [], settledSummary: {},
      },
      monthly: [],
      loading: true,

      get canFinance() {
        const r = this.session.role; const m = this.session.modules || []
        return r === 'superadmin' || r === 'admin' || m.includes('finance')
      },
      get canQuotation() {
        const r = this.session.role; const m = this.session.modules || []
        return r === 'superadmin' || r === 'admin' || m.includes('quotation')
      },

      get currentMonthAmount() {
        const now = new Date()
        const key = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0')
        const m = this.monthly.find(x => x.month === key)
        return m ? m.amount : 0
      },
      get receivedPct() {
        const rv = this.stats.receivableSummary || {}
        return rv.total > 0 ? Math.round(rv.received / rv.total * 100) : 0
      },
      get deviceTotal() { return (this.stats.deviceSummary || {}).total || 0 },

      async init() {
        const s = localStorage.getItem('motrix_session')
        if (!s) { window.location.href = 'pages/login.html'; return }
        try { this.session = JSON.parse(s) } catch(e) { window.location.href = 'pages/login.html'; return }

        // 無儀表板相關權限 → 導向專案頁面
        if (!this.canFinance && !this.canQuotation) {
          window.location.replace('pages/projects.html'); return
        }

        const d = new Date()
        const days = ['日','一','二','三','四','五','六']
        this.today = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} 週${days[d.getDay()]}`
        this.now   = this.today + ' ' + d.toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit'})

        await this.loadStats()
        this.monthly = await this.loadMonthly()
        this.loading = false
        this.$nextTick(() => initCharts(this.monthly, this.stats))
      },

      async loadStats() {
        try {
          const r = await fetch(`${API}/dashboard/stats`, {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (r.ok) this.stats = await r.json()
        } catch {}
      },

      async loadMonthly() {
        try {
          const r = await fetch(`${API}/dashboard/monthly`, {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (r.ok) { const d = await r.json(); return d.items || [] }
        } catch {}
        return []
      },

      fmtAmount(n) {
        if (!n) return '—'
        if (n >= 1000000) return 'NT$ ' + (n/1000000).toFixed(2) + 'M'
        if (n >= 1000)    return 'NT$ ' + Math.round(n/1000) + 'K'
        return 'NT$ ' + n.toLocaleString()
      },

      fmtAmountFull(n) {
        if (!n) return '—'
        return 'NT$ ' + Math.round(n).toLocaleString()
      },

      warrantyColor(w) {
        if (!w || w.daysLeft === null) return 'var(--text-dim)'
        if (w.daysLeft < 0)  return 'var(--danger)'
        if (w.daysLeft <= 30) return 'var(--warning)'
        return 'var(--success)'
      },
      warrantyLabel(w) {
        if (!w || w.daysLeft === null) return '—'
        if (w.daysLeft < 0)  return `已過期 ${Math.abs(w.daysLeft)} 天`
        if (w.daysLeft === 0) return '今日到期'
        return `${w.daysLeft} 天`
      },

      logout() {
        fetch(`${API}/auth/logout`, { method:'POST', headers:{ Authorization:'Bearer '+(this.session.token||'') } }).catch(()=>{})
        localStorage.removeItem('motrix_session')
        window.location.href = 'pages/login.html'
      }
    }
  }

  /* ── Chart.js 設定 ── */
  function initCharts(monthly, stats) {
    Chart.defaults.font.family = "Inter, 'Noto Sans TC', sans-serif"
    Chart.defaults.color = '#9A9A9A'

    const cream  = '#F5F4F0'
    const black  = '#0A0A0A'
    const accent = '#2563EB'
    const success= '#16A34A'
    const danger = '#DC2626'
    const warning= '#D97706'
    const orange = '#EA580C'
    const muted  = '#D1CFC9'

    /* ── KPI Sparklines ── */
    const sparkCfg = (color, data) => ({
      type: 'line',
      data: {
        labels: ['','','','','','',''],
        datasets: [{ data, borderColor: color, borderWidth: 1.5,
          fill: true,
          backgroundColor: ctx => {
            const g = ctx.chart.ctx.createLinearGradient(0,0,0,48)
            g.addColorStop(0, color + '30'); g.addColorStop(1, color + '00'); return g
          },
          pointRadius: 0, tension: .4 }]
      },
      options: { responsive:false, plugins:{legend:{display:false},tooltip:{enabled:false}},
        scales:{ x:{display:false}, y:{display:false} },
        animation: { duration: 800, easing: 'easeInOutQuart' }
      }
    })
    // sparkQuote: real monthly amounts (last 7 months); others: current value flat line
    const _mSlice = (monthly || []).slice(-7)
    const _pad    = Array(Math.max(0, 7 - _mSlice.length)).fill(0)
    const sparkQuoteData = [..._pad, ..._mSlice.map(m => m.amount)]
    const rv      = (stats.receivableSummary || {})
    const devTot  = (stats.deviceSummary     || {}).total || 0
    const warnCnt = (stats.warrantyWarnings  || []).length
    new Chart(document.getElementById('sparkQuote'),      sparkCfg(accent,  sparkQuoteData))
    new Chart(document.getElementById('sparkReceivable'), sparkCfg(success, Array(7).fill(rv.total || 0)))
    new Chart(document.getElementById('sparkStock'),      sparkCfg(warning, Array(7).fill(devTot)))
    new Chart(document.getElementById('sparkWarranty'),   sparkCfg(danger,  Array(7).fill(warnCnt)))

    /* ── 銷售趨勢折線面積圖 ── */
    const revCtx = document.getElementById('chartRevenue').getContext('2d')
    const revGrad = revCtx.createLinearGradient(0,0,0,200)
    revGrad.addColorStop(0, accent + '28')
    revGrad.addColorStop(1, accent + '00')
    const revLabels = (monthly && monthly.length) ? monthly.map(m => m.label) : ['—']
    const revData   = (monthly && monthly.length) ? monthly.map(m => m.amount) : [0]
    new Chart(revCtx, {
      type: 'line',
      data: {
        labels: revLabels,
        datasets: [{
          label: '報價金額',
          data: revData,
          borderColor: accent, borderWidth: 2,
          fill: true, backgroundColor: revGrad,
          pointRadius: 3, pointBackgroundColor: accent,
          pointHoverRadius: 5, tension: .4
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: {
            display: true, position: 'top', align: 'end',
            labels: { boxWidth: 10, boxHeight: 2, padding: 16, font: { size: 11 } }
          },
          tooltip: {
            backgroundColor: black, titleColor: cream, bodyColor: '#AAA',
            padding: 10, cornerRadius: 6,
            callbacks: {
              label: ctx => ' NT$ ' + ctx.raw.toLocaleString()
            }
          }
        },
        scales: {
          x: { grid: { color: '#F0EEE9' }, ticks: { font: { size: 10 } } },
          y: {
            grid: { color: '#F0EEE9' },
            ticks: {
              font: { size: 10 },
              callback: v => v >= 1000000 ? (v/1000000).toFixed(1)+'M' : (v/1000)+'K'
            }
          }
        },
        animation: { duration: 900, easing: 'easeInOutQuart' }
      }
    })

    /* ── 應收款圓環 ── */
    const rv = stats?.receivableSummary || {}
    const rvData = (rv.total > 0)
      ? [rv.received || 0, rv.unreceived || 0]
      : [1, 0]
    new Chart(document.getElementById('chartReceivable'), {
      type: 'doughnut',
      data: {
        labels: ['已收款', '未收款'],
        datasets: [{
          data: rvData,
          backgroundColor: [success, danger],
          borderWidth: 0, spacing: 2
        }]
      },
      options: {
        responsive: false, cutout: '72%',
        plugins: { legend: { display: false }, tooltip: {
          backgroundColor: black, bodyColor: cream, padding: 8, cornerRadius: 6,
          callbacks: { label: ctx => ' NT$ ' + ctx.raw.toLocaleString() }
        }},
        animation: { duration: 1000, easing: 'easeInOutQuart' }
      }
    })

    /* ── 設備狀態圓環 ── */
    const ds = stats?.deviceSummary || {}
    const dsData = [ds.ok || 0, ds.soon || 0, ds.expired || 0, ds.none || 0]
    new Chart(document.getElementById('chartDevice'), {
      type: 'doughnut',
      data: {
        labels: ['保固中', '30天到期', '已逾期', '無紀錄'],
        datasets: [{
          data: dsData,
          backgroundColor: [accent, orange, danger, muted],
          borderWidth: 0, spacing: 2
        }]
      },
      options: {
        responsive: false, cutout: '70%',
        plugins: { legend: { display: false }, tooltip: {
          backgroundColor: black, bodyColor: cream, padding: 8, cornerRadius: 6,
          callbacks: { label: ctx => ' ' + ctx.raw + ' 台' }
        }},
        animation: { duration: 1000, easing: 'easeInOutQuart' }
      }
    })

    /* ── 毛利率橫條圖 ── */
    const mgTop = (stats?.marginTop5 && stats.marginTop5.length)
      ? stats.marginTop5
      : [{ label: '尚無資料', margin: 0 }]
    new Chart(document.getElementById('chartMargin'), {
      type: 'bar',
      data: {
        labels: mgTop.map(m => m.label),
        datasets: [{
          label: '毛利率 %',
          data: mgTop.map(m => m.margin),
          backgroundColor: ctx => {
            const v = ctx.raw
            return v < 30 ? danger + 'CC' : v >= 40 ? success + 'CC' : warning + 'CC'
          },
          borderRadius: 4, borderSkipped: false
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: black, bodyColor: cream, padding: 8, cornerRadius: 6,
            callbacks: { label: ctx => ' 毛利率 ' + ctx.raw + '%' }
          }
        },
        scales: {
          x: {
            grid: { color: '#F0EEE9' },
            ticks: { font: { size: 10 }, callback: v => v + '%' },
            min: 0, max: 60
          },
          y: { grid: { display: false }, ticks: { font: { size: 10 } } }
        },
        animation: { duration: 800, easing: 'easeInOutQuart' }
      }
    })

    /* ── 實際 vs 預估毛利率對比（grouped bar）── */
    const mcEl = document.getElementById('chartMarginComparison')
    const mc   = stats?.marginComparison || []
    if (mcEl && mc.length > 0) {
      new Chart(mcEl, {
        type: 'bar',
        data: {
          labels: mc.map(m => m.projectName
            ? [m.customer || m.quoteNo, m.projectName]
            : (m.customer || m.quoteNo)),
          datasets: [
            {
              label: '預估毛利率',
              data: mc.map(m => m.estimatedMarginPct),
              backgroundColor: accent + '55',
              borderColor: accent,
              borderWidth: 1,
              borderRadius: 3,
            },
            {
              label: '實際毛利率',
              data: mc.map(m => m.actualMarginPct),
              backgroundColor: mc.map(m => {
                const v = m.actualMarginPct
                return (v < 30 ? danger : v >= 40 ? success : warning) + 'CC'
              }),
              borderRadius: 3,
            }
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: {
              display: true, position: 'top', align: 'end',
              labels: { boxWidth: 10, boxHeight: 2, padding: 16, font: { size: 11 } }
            },
            tooltip: {
              backgroundColor: black, titleColor: cream, bodyColor: '#AAA',
              padding: 10, cornerRadius: 6,
              callbacks: {
                label: ctx => ` ${ctx.dataset.label}: ${(ctx.raw || 0).toFixed(1)}%`,
                afterBody: items => {
                  const idx = items[0]?.dataIndex
                  if (idx == null) return []
                  const m    = mc[idx]
                  const diff = m.actualMarginPct - m.estimatedMarginPct
                  const sign = diff >= 0 ? '+' : ''
                  return [`差異: ${sign}${diff.toFixed(1)}%`, m.quoteNo]
                }
              }
            }
          },
          scales: {
            x: {
              grid: { color: '#F0EEE9' },
              ticks: {
                font: { size: 10 },
                maxRotation: 35,
                minRotation: 0,
                autoSkip: false,
              }
            },
            y: {
              grid: { color: '#F0EEE9' },
              ticks: { font: { size: 10 }, callback: v => v + '%' },
              min: 0, max: 60
            }
          },
          animation: { duration: 900, easing: 'easeInOutQuart' }
        }
      })
    }
  }
