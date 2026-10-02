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
    // 清單頁籤：approved＝已核准＋舊單＋尚未送審的草稿（預設）／review／returned／cancelled／all
    mlTab: 'approved',
    _mlReq: 0,            // mlOpen 的請求代號（只有最新一次、且仍是同一案件的回應才落地）
    _mlTabOfRow: {},      // 上一次載入時各列所在的頁籤：列的狀態變了（送審、核准、撤回…）就讓目前頁籤跟著它走，不然操作完那一列會憑空消失
    mlTick: 0,            // 讓 Alpine 在清單重載後重新計算（比照 moBusy 類計數器）

    // 切換案件時重設（core 的 _resetCaseScoped 依模組清單呼叫 _reset_<模組>）；不重設就會殘留前一件的清單／頁籤／筆數
    _reset_mlink(phase) {
      if (phase !== 'early') return
      this.mlStatus = {}; this.mlItems = []; this.mlPoLines = []; this.mlPanel = ''; this.mlPick = {}
      this.mlLoadingList = false; this.mlMsg = ''; this.mlTab = 'approved'; this._mlTabOfRow = {}; this.mlTick = 0
      this._mlReq = 0                                               // 切換前還在路上的 mlOpen 回應：代號對不上（且案件不同）⇒ 丟掉
    },

    _mlHeaders() { return { Authorization: 'Bearer ' + this.session.token } },
    _mlBase() { return `/api/quotations/${encodeURIComponent(this.selected?.quote_no || '')}` },

    // 連結判定：只在載入／儲存後取一次（徽章用）；失敗＝不顯示徽章（不阻擋其他功能）
    async mlLoadStatus(quoteNo) {
      if (!quoteNo) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/material-link-status`, { headers: this._mlHeaders() })
        if (r.ok && this.selected?.quote_no === quoteNo) this.mlStatus = (await r.json()).statuses || {}
      } catch {}
      this._mlFollowMovedRow()
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
      const quoteNo = this.selected?.quote_no
      const token = this._mlReq = this._mlReq + 1       // 只有最新一次開啟的回應算數；切換案件後晚到的回應也丟掉（c7 預審）
      const live = () => this._mlReq === token && this.selected?.quote_no === quoteNo
      try {
        if (kind === 'quote') {
          const r = await fetch(base + '/purchase-items', { headers: this._mlHeaders() })
          const d = r.ok ? await r.json() : null
          if (!live()) return
          if (d) this.mlItems = d.items || []
          else this.mlMsg = '無法讀取報價單品項'
        } else {
          const r = await fetch(base + '/material-po-lines', { headers: this._mlHeaders() })
          const d = r.ok ? await r.json() : null
          if (!live()) return
          if (d) this.mlPoLines = d.lines || []
          else this.mlMsg = '無法讀取採購單明細'
        }
      } catch { if (!live()) return; this.mlMsg = '讀取失敗，請稍後再試' }
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

    // 頁籤：舊單（沒有審核列）、已核准、尚未送審的草稿同列（預設）；尚未儲存的新列在每個頁籤都顯示
    // 該列目前屬於哪個頁籤（單一來源；_mlTabOf 也用它）
    _mlKeyOf(m) {
      const a = (this.moApprovals || {})[m.itemId] || {}
      const st = a.legacy ? '' : (a.status || '')
      if (st === '待審核' || st === '簽核中') return 'review'
      if (st === '已退回') return 'returned'
      if (st === '已取消') return 'cancelled'
      return 'approved'                                                   // 舊單、已核准、尚未送審的草稿
    },
    _mlFollowMovedRow() {
      const now = {}
      let moved = ''
      for (const m of this.materialOrders) {
        if (m._saved === false) continue
        now[m.itemId] = this._mlKeyOf(m)
        const was = this._mlTabOfRow[m.itemId]
        if (!moved && was && was !== now[m.itemId] && this.mlTab !== 'all' && this.mlTab === was) moved = now[m.itemId]
      }
      this._mlTabOfRow = now
      if (moved) this.mlTab = moved
    },
    mlTabOk(m) { return this._mlTabOf(m, this.mlTab) },
    _mlTabOf(m, tab) {
      if (tab === 'all' || m._saved === false) return true
      return this._mlKeyOf(m) === tab
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
