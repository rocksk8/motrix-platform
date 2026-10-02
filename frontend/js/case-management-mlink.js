// case-management-mlink.js — 案件管理頁：材料申請的「報價單品項／採購單明細」連結（32-S4d）
// 規格 docs/platform/plans/MATERIAL-ORDER-LINK-SPEC.md；用字照 docs/platform/plans/MATERIAL-REQUEST-WORDING.md（鍵名仍是 materialOrders／quoteItemId…）。
// 獨立成檔：不與 case-management-exec.js 的 31-C 材料申請審核／匯款區塊改同一段；組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({
    // 連結判定（後端 material_link_status 的唯一口徑）：itemId → {state:'linked'|'none'|'exempt', reason, stale, text}
    mlStatus: {},
    mlItems: [],          // 報價單品項挑選器（剩餘可申請量）
    mlPoLines: [],        // 採購單明細（尚未被有效連結用掉的）
    mlPanel: '',          // '' | 'quote' | 'po'：目前開著哪個匯入面板
    mlPick: {},           // 匯入面板勾選：key → true
    mlLoadingList: false,
    mlMsg: '',
    // 清單頁籤：approved＝已核准＋舊單（預設）／review／draft／cancelled／all
    mlTab: 'approved',
    mlTick: 0,            // 讓 Alpine 在清單重載後重新計算（比照 moBusy 類計數器）

    _mlHeaders() { return { Authorization: 'Bearer ' + this.session.token } },
    _mlBase() { return `/api/quotations/${encodeURIComponent(this.selected?.quote_no || '')}` },

    // 連結判定：只在載入／儲存後取一次（徽章用）；失敗＝不顯示徽章（不阻擋其他功能）
    async mlLoadStatus(quoteNo) {
      if (!quoteNo) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/material-orders/link-status`, { headers: this._mlHeaders() })
        if (r.ok && this.selected?.quote_no === quoteNo) this.mlStatus = (await r.json()).statuses || {}
      } catch {}
      this.mlTick++
    },

    // 開／關匯入面板；打開時才取清單（品項的剩餘量與採購單明細都以伺服器當下為準）
    async mlOpen(kind) {
      if (this.mlPanel === kind) { this.mlPanel = ''; return }
      this.mlPanel = kind
      this.mlPick = {}
      this.mlMsg = ''
      this.mlLoadingList = true
      const base = this._mlBase()
      try {
        if (kind === 'quote') {
          const r = await fetch(base + '/purchase-items', { headers: this._mlHeaders() })
          if (r.ok) this.mlItems = (await r.json()).items || []
          else this.mlMsg = '無法讀取報價單品項'
        } else {
          const r = await fetch(base + '/material-po-lines', { headers: this._mlHeaders() })
          if (r.ok) this.mlPoLines = (await r.json()).lines || []
          else this.mlMsg = '無法讀取採購單明細'
        }
      } catch { this.mlMsg = '讀取失敗，請稍後再試' }
      this.mlLoadingList = false
    },

    // 報價品項：剩餘 0 ⇒ 不列出（預先扣除已申請完成的）；本頁尚未儲存的列也要扣，避免同一筆重複帶入
    mlQuoteChoices() {
      void this.mlTick
      const pending = {}
      for (const m of this.materialOrders) {
        if (m._saved === false && m.quoteItemId && !m.poDocCode) pending[m.quoteItemId] = (pending[m.quoteItemId] || 0) + (Number(m.quantity) || 0)
      }
      return this.mlItems
        .map(i => ({ ...i, left: Math.max((Number(i.remainingQty) || 0) - (pending[i.itemId] || 0), 0) }))
        .filter(i => i.left > 1e-9)
    },
    mlPoChoices() {
      void this.mlTick
      const used = new Set(this.materialOrders.filter(m => m.poDocCode && m.poLine).map(m => m.poDocCode + '#' + m.poLine))
      return this.mlPoLines.filter(l => !used.has(l.poDocCode + '#' + l.poLine))
    },

    mlPickedCount() { return Object.keys(this.mlPick).filter(k => this.mlPick[k]).length },

    // 把勾選的品項／明細帶成新的材料申請列（仍是草稿：要選供應商、按儲存、再送審）
    mlImport() {
      let n = 0
      if (this.mlPanel === 'quote') {
        for (const i of this.mlQuoteChoices()) {
          if (!this.mlPick['q:' + i.itemId]) continue
          this._mlPush({ itemName: i.description, quantity: i.left, unit: i.unit, unitPrice: Number(i.planUnitCost) || 0, quoteItemId: i.itemId })
          n++
        }
      } else if (this.mlPanel === 'po') {
        for (const l of this.mlPoChoices()) {
          if (!this.mlPick['p:' + l.poDocCode + '#' + l.poLine]) continue
          this._mlPush({ itemName: l.summary, quantity: l.qty, unit: l.unit, unitPrice: Number(l.unitCost) || 0,
                         quoteItemId: l.quoteItemId || '', poDocCode: l.poDocCode, poLine: l.poLine })
          n++
        }
      }
      if (!n) { this.mlMsg = '請先勾選要帶入的項目'; return }
      this.mlPick = {}
      this.mlPanel = ''
      this.mlTab = 'approved'
      this.mlMsg = `已帶入 ${n} 筆（草稿）：請選供應商後儲存，再送審`
    },
    _mlPush(o) {
      const quantity = Number(o.quantity) || 0
      const unitPrice = Number(o.unitPrice) || 0
      this.materialOrders.push({
        itemId: this._moNewId(), itemName: o.itemName || '', quantity, unit: o.unit || '', unitPrice,
        totalPrice: MotrixLegalRound.halfUp(quantity * unitPrice, 100) / 100, paidStatus: 'pending', paidAmount: 0, paidDate: '', notes: '',
        invoiceDate: '', supplierId: null, quoteItemId: o.quoteItemId || '', poDocCode: o.poDocCode || '', poLine: o.poLine || null,
        overPlanReason: '', _saved: false, _recvDate: ''
      })
      this.moDirty = true
      this.moMsg = ''
    },

    // 頁籤：舊單（沒有審核列）與已核准同列；尚未儲存的新列在每個頁籤都顯示（不然按了「帶入」會看不到）
    mlTabOk(m) { return this._mlTabOf(m, this.mlTab) },
    _mlTabOf(m, tab) {
      if (tab === 'all' || m._saved === false) return true
      const a = (this.moApprovals || {})[m.itemId] || {}
      const st = a.legacy ? '' : (a.status || '')
      switch (tab) {
        case 'approved': return st === '' || st === '已核准'
        case 'review': return st === '待審核' || st === '簽核中'
        case 'draft': return st === '草稿' || st === '已退回'
        case 'cancelled': return st === '已取消'
      }
      return true
    },
    mlTabCount(tab) { return this.materialOrders.filter(m => m._saved !== false && this._mlTabOf(m, tab)).length },

    // 徽章：伺服器判定為「未連採購單」才標；舊單、$0 不標；尚未儲存的新列以本頁欄位即時判（不叫伺服器）
    mlBadge(m) {
      void this.mlTick
      if (m._saved === false) {
        if (m.poDocCode || !(Number(m.totalPrice) > 0)) return ''
        return this._mlNoPo
      }
      const s = this.mlStatus[m.itemId]
      return s && s.state === 'none' ? s.text : ''
    },
    _mlNoPo: '該材料申請未申請採購單',
    mlLinkedText(m) {
      const s = this.mlStatus[m.itemId]
      return s && s.state === 'linked' ? `已對應採購單 ${m.poDocCode}${m.poLine ? '（第 ' + m.poLine + ' 列）' : ''}` : ''
    },

    // 超出報價計畫量：品項剩餘量以最近一次取得的清單為準；沒取過清單 ⇒ 不即時判（送審時後端必擋，要填原因）
    mlOverBy(m) {
      if (!m.quoteItemId || m.poDocCode) return 0
      const it = this.mlItems.find(i => i.itemId === m.quoteItemId)
      if (!it) return 0
      return Math.max((Number(m.quantity) || 0) - (Number(it.remainingQty) || 0), 0)
    },
    mlShowReason(m) { return !!(m.quoteItemId && !m.poDocCode && (m.overPlanReason || this.mlOverBy(m) > 1e-9)) },
    mlQuoteName(id) { const it = this.mlItems.find(i => i.itemId === id); return it ? it.description : id }
}))
