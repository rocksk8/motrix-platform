// case-management-mlink.js — 案件管理頁：材料申請的「採購單明細」連結（32-S4d；33-M1：新申請只能從已核准的採購單明細帶入）
// 規格 docs/platform/plans/MATERIAL-ORDER-LINK-SPEC.md；用字照 docs/platform/plans/MATERIAL-REQUEST-WORDING.md（鍵名仍是 materialOrders／quoteItemId…）。
// 獨立成檔：不與 case-management-exec.js 的 31-C 材料申請審核／匯款區塊改同一段；組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({
    // 連結判定（後端 material_link_status 的唯一口徑）：itemId → {state:'linked'|'none'|'exempt', reason, stale, text}
    mlStatus: {},
    mlItems: [],          // 報價單品項挑選器（剩餘可申請量）
    mlGroups: [],         // 34：涵蓋分組（一個報價品項一組；額外採購以採購單為單位）——GET material-coverage
    mlPanel: '',          // '' | 'po'：目前開著哪個匯入面板（33-M1 起只有採購單明細）
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
      this.mlStatus = {}; this.mlItems = []; this.mlGroups = []; this.mlPanel = ''; this.mlPick = {}
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

    // 開／關匯入面板；打開時才取清單（採購單明細以伺服器當下為準）
    async mlOpen(kind) {
      kind = 'po'
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
        const r = await fetch(base + '/material-coverage', { headers: this._mlHeaders() })
        const d = r.ok ? await r.json() : null
        if (!live()) return
        if (d) this.mlGroups = d.groups || []
        else this.mlMsg = '無法讀取採購單明細'
      } catch { if (!live()) return; this.mlMsg = '讀取失敗，請稍後再試' }
      this.mlLoadingList = false
    },

    // 34（E4）：一個報價品項一筆材料申請，涵蓋該品項全部已核准採購單行（數量、金額由後端的涵蓋快照給，畫面不做金額運算）；
    // 額外採購（沒有報價品項）以採購單為單位各一筆（N1）。已有活的申請 ⇒ 不能再帶入，要追加走變更申請。
    mlGroupChoices() { void this.mlTick; return this.mlGroups },
    mlGroupBlock(g) {
      if (g.existing) return `已有材料申請 ${g.existing.docCode || ''}（${g.existing.status}）→ 要追加請用變更申請`
      const dup = this.materialOrders.some(m => m._saved === false && ((g.quoteItemId && m.quoteItemId === g.quoteItemId) || (!g.quoteItemId && !m.quoteItemId && m.poDocCode === g.poDocCode)))
      return dup ? '已帶入（尚未儲存）' : ''
    },
    mlGroupKey(g) { return 'g:' + g.key },
    mlGroupText(g) {
      const money = g.totalPrice != null ? '｜小計 ' + g.totalPrice : ''
      return `${g.quantity}${g.unit ? ' ' + g.unit : ''}${money}｜${g.docCodes.join('、')}（${g.lineCount} 行）`
    },

    mlPickedCount() { return Object.keys(this.mlPick).filter(k => this.mlPick[k]).length },

    // 把勾選的分組帶成新的材料申請列（仍是草稿：要選供應商、按儲存、再送審）；一組一列，內容＝涵蓋快照
    mlImport() {
      let n = 0
      for (const g of this.mlGroupChoices()) {
        if (!this.mlPick[this.mlGroupKey(g)] || this.mlGroupBlock(g)) continue
        if (g.totalPrice == null) { this.mlMsg = '看不到金額的帳號不能從採購單帶入材料申請（需要財務檢視權限）'; return }
        this._mlPush({ itemName: g.name, quantity: g.quantity, unit: g.unit, unitPrice: g.unitPrice, totalPrice: g.totalPrice,
                       quoteItemId: g.quoteItemId || '', poDocCode: g.poDocCode, poLine: g.poLine })
        n++
      }
      if (!n) { this.mlMsg = '請先勾選要帶入的項目（只能帶入已核准採購單的涵蓋內容；已有申請的品項請用變更申請）'; return }
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
        totalPrice: (o.totalPrice != null ? Number(o.totalPrice) : MotrixLegalRound.halfUp(quantity * unitPrice, 100) / 100), paidStatus: 'pending', paidAmount: 0, paidDate: '', notes: '',
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
    // 送審前提示（33-M1，後端 po_required 為準）：新的（非舊單）材料申請沒有採購單連結 ⇒ 先告訴使用者，不用等被擋
    mlSubmitHint(m) {
      if (!m || String(m.poDocCode || '').trim()) return ''
      const a = (this.moApprovals || {})[m.itemId] || {}
      if (m._saved !== false && !(m.itemId in (this.moApprovals || {}))) return ''      // 審核狀態還沒載入：不判斷（避免舊單閃一下提示）
      if (m._saved !== false && a.legacy) return ''                                    // 舊單不受影響
      if (!['', '草稿', '已退回'].includes(a.status || '')) return ''
      return '需先申請請購單，再申請採購單；採購單通過後，才能對應這筆材料申請。'
    },
    // 已全額付款的材料申請：數量／單價不能改（金額已付清，要調整請另開一筆）
    // 34（E7）：涵蓋採購單的材料申請，金額＝涵蓋行金額合計（唯讀）；數量只能往下調（單價隨數量換算，小計不變）
    moCovered(m) { return !!(m && String(m.poDocCode || '').trim() && m.poLine) },
    moCoveredHint: '金額＝涵蓋的採購單行金額合計，不能修改；數量只能往下調（單價隨數量換算）',
    moPaidFullHint: '已全額付款，金額不能修改；要調整請另開一筆材料申請',
    moPaidFull(m) { return !!m && m._saved !== false && m.paidStatus === 'paid' },
    mlQuoteName(id) { const it = this.mlItems.find(i => i.itemId === id); return it ? it.description : id }
}))
