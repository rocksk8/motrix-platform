function settlementPage() {
  return {
    API: '',
    session: null,
    quoteNo: '',
    customerName: '',
    projectName:  '',
    loading: true,
    saving:  false,
    showFinalizeModal: false,
    toasts: [],

    settlement: {
      status: 'draft',
      settlementDate: new Date().toISOString().slice(0, 10),
      finalizedAt:  '',
      finalizedBy:  '',
      items:      [],
      extraItems: [],
      memo: '',
    },

    summary: {
      quotedPretax:    0,
      quotedTotal:     0,
      origItemTotal:   0,
      origTotalCost:   0,
      origDirectProfit:0,
      origMarginPct:   0,
      itemActualTotal: 0,
      extraTotal:      0,
      totalActualCost: 0,
      grossProfit:     0,
      grossMarginPct:  0,
      adminCost:       0,
      charityDonation: 0,
      netProfit:       0,
      netMarginPct:    0,
      profitDiff:      0,
      origAdminCost:   0,
      origCharity:     0,
      origNetProfit:   0,
      origNetMarginPct:0,
    },

    fmt(n) {
      return Math.round(n || 0).toLocaleString()
    },

    async init() {
      const raw = localStorage.getItem('motrix_session')
      if (!raw) { location.href = 'login.html'; return }
      this.session = JSON.parse(raw)
      if (!this.session?.token) { location.href = 'login.html'; return }

      const params = new URLSearchParams(location.search)
      this.quoteNo = params.get('no') || ''
      if (!this.quoteNo) {
        this.toast('未指定報價單號'); this.loading = false; return
      }

      try {
        const res = await fetch(`${this.API}/api/quotations/${this.quoteNo}/settlement`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (res.status === 401) { location.href = 'login.html'; return }
        if (!res.ok) { this.toast('載入失敗'); this.loading = false; return }

        const d = await res.json()
        this.customerName = d.customerName || ''
        this.projectName  = d.projectName  || ''

        // 從報價單品項初始化精算 items
        const origItems = (d.items || []).map(it => ({
          id:              it.id,
          origDescription: it.description || '',
          origBrand:       it.brand       || '',
          origQty:         it.qty         || 0,
          origUnit:        it.unit        || '台',
          origUnitPrice:   it.unitPrice   || 0,
          origAmount:      it.amount      || 0,
          origCost:        it.cost        || 0,
          actualQty:       it.qty         || 0,
          actualUnitCost:  it.cost        || 0,
          actualTotalCost: Math.round((it.qty || 0) * (it.cost || 0)),
          note:            '',
        }))

        if (d.settlement) {
          // 已有精算資料：合併（保留實際成本欄；原始報價欄以最新報價為準）
          const saved = d.settlement
          this.settlement.status        = saved.status || 'draft'
          this.settlement.settlementDate= saved.settlementDate || new Date().toISOString().slice(0,10)
          this.settlement.finalizedAt   = saved.finalizedAt || ''
          this.settlement.finalizedBy   = saved.finalizedBy || ''
          this.settlement.memo          = saved.memo || ''
          this.settlement.extraItems    = saved.extraItems || []

          // 合併報價品項（若報價單有新增/刪除品項，以報價單為基準）
          const savedMap = {}
          ;(saved.items || []).forEach(si => { savedMap[si.id] = si })

          this.settlement.items = origItems.map(oi => {
            const si = savedMap[oi.id]
            if (si) {
              return {
                ...oi,
                actualQty:      si.actualQty      !== undefined ? si.actualQty      : oi.actualQty,
                actualUnitCost: si.actualUnitCost !== undefined ? si.actualUnitCost : oi.actualUnitCost,
                actualTotalCost:si.actualTotalCost|| oi.actualTotalCost,
                note:           si.note || '',
              }
            }
            return oi
          })
        } else {
          this.settlement.items = origItems
        }

        // 記錄原始 tot 資料用於比較
        this._origTot = d.tot || {}
        this.calcSummary()
      } catch(e) {
        this.toast('載入失敗：' + e.message)
      } finally {
        this.loading = false
      }
    },

    calcItemCost(item) {
      item.actualTotalCost = Math.round((item.actualQty || 0) * (item.actualUnitCost || 0))
    },

    calcExtraCost(ex) {
      ex.totalCost = Math.round((ex.qty || 0) * (ex.unitCost || 0))
    },

    calcSummary() {
      const tot = this._origTot || {}
      const quotedPretax = tot.pretax   || 0
      const quotedTotal  = tot.total    || 0
      const origItemTotal = this.settlement.items.reduce((s, i) => s + (i.origAmount || 0), 0)
      const origTotalCost = this.settlement.items.reduce((s, i) => s + (i.origQty || 0) * (i.origCost || 0), 0)
      const origDirectProfit = quotedPretax - origTotalCost
      const origMarginPct = quotedPretax > 0 ? origDirectProfit / quotedPretax * 100 : 0

      const itemActualTotal = this.settlement.items.reduce((s, i) => s + (i.actualTotalCost || 0), 0)
      const extraTotal      = this.settlement.extraItems.reduce((s, e) => s + (e.totalCost || 0), 0)
      const totalActualCost = itemActualTotal + extraTotal
      const grossProfit     = quotedPretax - totalActualCost
      const grossMarginPct  = quotedPretax > 0 ? grossProfit / quotedPretax * 100 : 0
      const adminCost       = Math.round(quotedPretax * 0.10)
      const charityDonation = Math.round(grossProfit * 0.01)
      const netProfit       = grossProfit - adminCost - charityDonation
      const netMarginPct    = quotedPretax > 0 ? netProfit / quotedPretax * 100 : 0

      const origAdminCost   = Math.round(quotedPretax * 0.10)
      const origCharity     = Math.round(origDirectProfit * 0.01)
      const origNetProfit   = origDirectProfit - origAdminCost - origCharity
      const origNetMarginPct = quotedPretax > 0 ? origNetProfit / quotedPretax * 100 : 0

      const profitDiff = netProfit - origNetProfit

      this.summary = {
        quotedPretax, quotedTotal,
        origItemTotal, origTotalCost, origDirectProfit,
        origMarginPct:    Math.round(origMarginPct * 10) / 10,
        origAdminCost, origCharity,
        origNetProfit:    Math.round(origNetProfit),
        origNetMarginPct: Math.round(origNetMarginPct * 10) / 10,
        itemActualTotal, extraTotal, totalActualCost,
        grossProfit:     Math.round(grossProfit),
        grossMarginPct:  Math.round(grossMarginPct * 10) / 10,
        adminCost, charityDonation,
        netProfit:       Math.round(netProfit),
        netMarginPct:    Math.round(netMarginPct * 10) / 10,
        profitDiff:      Math.round(profitDiff),
      }
    },

    addExtra() {
      this.settlement.extraItems.push({
        id:          Date.now(),
        category:    '工時',
        description: '',
        qty:         1,
        unit:        '人天',
        unitCost:    0,
        totalCost:   0,
        note:        '',
      })
    },

    removeExtra(idx) {
      this.settlement.extraItems.splice(idx, 1)
      this.calcSummary()
    },

    buildPayload() {
      return {
        status:          this.settlement.status,
        settlementDate:  this.settlement.settlementDate,
        finalizedAt:     this.settlement.finalizedAt,
        finalizedBy:     this.settlement.finalizedBy,
        memo:            this.settlement.memo,
        items:           this.settlement.items.map(i => ({
          id:             i.id,
          origDescription:i.origDescription,
          origBrand:      i.origBrand,
          origQty:        i.origQty,
          origUnit:       i.origUnit,
          origUnitPrice:  i.origUnitPrice,
          origAmount:     i.origAmount,
          origCost:       i.origCost,
          actualQty:      i.actualQty,
          actualUnitCost: i.actualUnitCost,
          actualTotalCost:i.actualTotalCost,
          note:           i.note,
        })),
        extraItems: this.settlement.extraItems,
        summary:    this.summary,
      }
    },

    async saveDraft() {
      this.saving = true
      try {
        this.calcSummary()
        const res = await fetch(`${this.API}/api/quotations/${this.quoteNo}/settlement`, {
          method:  'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body:    JSON.stringify({ settlement: this.buildPayload() }),
        })
        if (res.ok) this.toast('精算草稿已儲存')
        else        this.toast('儲存失敗')
      } catch(e) { this.toast('儲存失敗：' + e.message) }
      finally { this.saving = false }
    },

    async finalize() {
      this.saving = true
      this.settlement.status      = 'finalized'
      this.settlement.finalizedAt = new Date().toISOString()
      this.settlement.finalizedBy = this.session.displayName || this.session.username || ''
      try {
        this.calcSummary()
        const res = await fetch(`${this.API}/api/quotations/${this.quoteNo}/settlement`, {
          method:  'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body:    JSON.stringify({ settlement: this.buildPayload() }),
        })
        if (res.ok) {
          this.showFinalizeModal = false
          this.toast('精算已完結')
        } else {
          this.settlement.status      = 'draft'
          this.settlement.finalizedAt = ''
          this.settlement.finalizedBy = ''
          this.toast('完結失敗')
        }
      } catch(e) {
        this.settlement.status      = 'draft'
        this.settlement.finalizedAt = ''
        this.settlement.finalizedBy = ''
        this.toast('完結失敗：' + e.message)
      } finally { this.saving = false }
    },

    async reopenDraft() {
      if (!confirm('確認重新開啟精算並允許修改？')) return
      this.settlement.status      = 'draft'
      this.settlement.finalizedAt = ''
      this.settlement.finalizedBy = ''
      await this.saveDraft()
    },

    toast(msg) {
      const id = Date.now()
      this.toasts.push({ id, msg })
      setTimeout(() => { this.toasts = this.toasts.filter(t => t.id !== id) }, 3500)
    },
  }
}
