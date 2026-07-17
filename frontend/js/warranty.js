  function warrantyPage() {
    return {
      session: {},
      devices: [],
      loading: true,
      search: '',
      statusTab: '',
      expanded: {},

      async init() {
        const s = JSON.parse(localStorage.getItem('motrix_session') || 'null')
        if (!s?.token) { location.href = '../index.html'; return }
        this.session = s
        await this.load()
        // auto-expand customers that have urgent items
        const g = this.grouped
        const auto = {}
        for (const grp of g) {
          if (grp.expiredCnt > 0 || grp.soonCnt > 0) auto[grp.customer] = true
        }
        if (Object.keys(auto).length === 0 && g.length > 0) {
          // no urgent — expand first customer
          auto[g[0].customer] = true
        }
        this.expanded = auto
      },

      async load() {
        this.loading = true
        try {
          const r = await fetch('/api/devices', {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (r.status === 401) { this.logout(); return }
          const data = await r.json()
          // 保固追蹤：已成案 + 已結案 皆納入，未成案排除
          this.devices = (data.items || []).filter(d =>
            d.dealTag === '已成案' || d.dealTag === '已結案'
          )
        } catch {
          this.devices = []
        } finally {
          this.loading = false
        }
      },

      get stats() {
        const out = { expired: 0, soon: 0, ok: 0, none: 0 }
        for (const d of this.devices) out[this.wbKey(d)]++
        return out
      },

      get filtered() {
        let list = this.devices
        if (this.statusTab) list = list.filter(d => this.wbKey(d) === this.statusTab)
        const q = this.search.trim().toLowerCase()
        if (q) list = list.filter(d =>
          ['name','sn','mac','customer','location','quoteNo','projectName']
            .some(k => (d[k] || '').toLowerCase().includes(q))
        )
        return list
      },

      get grouped() {
        const custMap = {}
        for (const d of this.filtered) {
          const cust = d.customer || ''
          if (!custMap[cust]) custMap[cust] = {}
          const qno = d.quoteNo || '—'
          if (!custMap[cust][qno]) {
            custMap[cust][qno] = {
              quoteNo: qno,
              projectName: d.projectName || '',
              dealTag: d.dealTag || '',
              devices: []
            }
          }
          custMap[cust][qno].devices.push(d)
        }
        return Object.entries(custMap).map(([customer, cases]) => {
          const allDev = Object.values(cases).flatMap(c => c.devices)
          const expiredCnt = allDev.filter(d => d.daysLeft !== null && d.daysLeft !== undefined && d.daysLeft < 0).length
          const soonCnt    = allDev.filter(d => d.daysLeft !== null && d.daysLeft !== undefined && d.daysLeft >= 0 && d.daysLeft <= 30).length
          return {
            customer,
            cases: Object.values(cases),
            totalDevices: allDev.length,
            expiredCnt,
            soonCnt,
            _worst: expiredCnt > 0 ? 0 : soonCnt > 0 ? 1 : allDev.some(d => (d.daysLeft ?? null) > 30) ? 2 : 3
          }
        }).sort((a, b) => a._worst - b._worst || a.customer.localeCompare(b.customer, 'zh-Hant'))
      },

      toggle(customer) {
        this.expanded = { ...this.expanded, [customer]: !this.expanded[customer] }
      },
      expandAll() {
        const e = {}
        for (const g of this.grouped) e[g.customer] = true
        this.expanded = e
      },
      collapseAll() { this.expanded = {} },

      wbKey(d) {
        const dl = d.daysLeft
        if (dl === null || dl === undefined) return 'none'
        if (dl < 0)   return 'expired'
        if (dl <= 30) return 'soon'
        return 'ok'
      },
      wbLabel(d) {
        const dl = d.daysLeft
        if (dl === null || dl === undefined) return '無紀錄'
        if (dl < 0)   return '已過期 ' + Math.abs(dl) + ' 天'
        if (dl <= 30) return dl + ' 天後到期'
        return '保固中'
      },

      logout() {
        fetch('/api/auth/logout', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        }).finally(() => {
          localStorage.removeItem('motrix_session')
          location.href = '../index.html'
        })
      }
    }
  }
