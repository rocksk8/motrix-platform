// case-management-mtl.js — 案件管理頁：執行管理 › 材料申請「物料時間軸」（T86 第 3 項）
// 每個材料卡一列、五關（申請→採購→到貨→入庫→出貨）；目前這一關的主按鈕就地操作，沿用既有的材料／材料申請處理函式，不新增 API。
// 申請／採購／到貨取自材料卡與材料申請（materialOrders、moApprovals、poLink）；入庫／出貨是案件層級資料，取自既有的
// GET /api/quotations/{案號}/material-flow（旗標 onepipe.timeline；讀不到就只顯示前三關）。組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({
    mtlFlow: null,          // null＝尚未讀；false＝讀不到（旗標關／無權限）；否則 { stock, ship }（各為 cell 或 null）
    _mtlFor: '',            // 已為哪個案件讀過（同一件只讀一次）
    _mtlReq: 0,
    mtlOpen: {},            // 哪幾個材料的明細展開了（預設全部收合；新增品項會自動展開）
    _mtlPend: {},           // 在時間軸按了「確認到貨」、還沒存檔的材料（顯示「待儲存」）

    _reset_mtl(phase) {
      if (phase !== 'early') return
      this.mtlFlow = null; this._mtlFor = ''; this._mtlReq++; this._mtlPend = {}; this.mtlOpen = {}
    },

    // 材料申請分頁顯示時呼叫（x-effect）：補讀材料申請（原本只有財務分頁會讀）與物料流程摘要
    async mtlEnsure() {
      const no = this.selected && this.selected.quote_no
      if (!no || this._mtlFor === no) return
      this._mtlFor = no
      // 分頁按鈕／?sub=materials 已經讀過（或正在讀）就不再讀一次
      if (this.loadMaterialOrders && this._moReqFor !== no && !(this.materialOrders || []).length) this.loadMaterialOrders(no)
      // 入庫／出貨來自物料流程摘要：旗標 onepipe.timeline 關著就不問（避免多一筆 404）
      let on = false
      try { on = !!(window.MotrixOnepipe && (await window.MotrixOnepipe.flags()).timeline) } catch (e) { on = false }
      if (this._mtlFor !== no) return
      if (on) this.mtlLoadFlow(no)
      else this.mtlFlow = false
    },
    async mtlLoadFlow(no) {
      const req = ++this._mtlReq
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(no)}/material-flow`, { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (req !== this._mtlReq || !this.selected || this.selected.quote_no !== no) return
        if (!r.ok) { this.mtlFlow = false; return }
        const d = await r.json()
        const cell = k => (d.cells || []).find(c => c.key === k) || null
        const ok = c => (c && !c.forbidden && !c.unavailable ? c : null)
        this.mtlFlow = { stock: ok(cell('stock')), ship: ok(cell('ship')) }
      } catch (e) { if (req === this._mtlReq) this.mtlFlow = false }
    },

    // 存檔後（dirty 變回 false）清掉「待儲存」標記，之後別的編輯再讓 dirty 變 true 時不會誤把已存的列標回待儲存
    _mtlWatchSave() {
      if (this._mtlWatching) return
      this._mtlWatching = true
      this.$watch('dirty', v => { if (!v) this._mtlPend = {} })
    },
    mtlOrderOf(mat) { return (this.materialOrders || []).find(o => o.itemId && o.itemId === mat.orderItemId) || null },
    _mtlHasPo(mat, o) { return !!((mat.poLink && mat.poLink.key) || (o && o.poDocCode)) },
    _mtlPoCodes(mat, o) {
      const l = mat.poLink
      if (l && l.key) return (l.docCodes && l.docCodes.length ? l.docCodes : (l.poDocCode ? [l.poDocCode] : [])).join('、') || '已認列採購單'
      return (o && o.poDocCode) || ''
    },
    _mtlCase() { return encodeURIComponent((this.selected && this.selected.quote_no) || '') },

    // 一列的五個步驟：{ key, label, state: 'done'|'cur'|'todo', cap, late, act: {label, href?|run?} | null }
    mtlSteps(mat) {
      void this.moLoading; void this.mlTick
      const o = this.mtlOrderOf(mat)
      const a = o ? this.moAp(o) : null
      const po = !!(mat.poLink && mat.poLink.key)
      const canEdit = !!(this.moCanEdit && this.moCanEdit())
      const approved = po || !!(a && (a.legacy || a.status === '已核准'))
      const case_ = this._mtlCase()
      const steps = []

      // 申請
      const req = { key: 'req', label: '申請', state: 'todo', cap: '尚未申請', act: null }
      if (this.moLoading && !(this.materialOrders || []).length) req.cap = '載入中…'
      else if (this.moNoAccess && !po && !o) req.cap = '—／無權限'
      else if (po && !o) { req.state = 'done'; req.cap = '由採購單認列' }
      else if (!o) {
        const cands = this.mlCandidatesFor ? this.mlCandidatesFor(mat) : []
        if (cands.length === 1) req.act = { label: '帶入並連結', run: () => this.mlPickCandidate(mat, this.mlGroupKey(cands[0])) }
        else req.act = { label: '開請購單', href: 'payment-request.html?case=' + case_ + '&type=purchase_req' }
      } else if (a.legacy) { req.state = 'done'; req.cap = '舊單（未經審核）' }
      else if (a.status === '已核准') { req.state = 'done'; req.cap = (a.docCode || '') + '\n已核准' }
      else {
        req.cap = (a.docCode || '未送審') + '\n' + this.moApLabel(o)
        if (this.moIsUnsent(o) && canEdit && o._saved !== false) req.act = { label: '送審', run: () => this.moSubmit(o) }
        else if (a.status === '已退回') req.cap = (a.docCode || '') + '\n已退回'
      }
      steps.push(req)

      // 採購
      const hasPo = this._mtlHasPo(mat, o)
      const pur = { key: 'po', label: '採購', state: hasPo ? 'done' : 'todo', cap: hasPo ? this._mtlPoCodes(mat, o) : '—', act: null }
      if (!hasPo && approved) { pur.cap = '尚未對應採購單'; pur.act = { label: '開採購單', href: 'payment-request.html?case=' + case_ + '&type=purchase_order' } }
      steps.push(pur)

      // 到貨
      const arrived = !!mat.arrived || !!(o && this.moWizFull && this.moWizFull(o))
      const day = (o && a && a.receivedOn) || (mat.poLink && mat.poLink.arrivedOn) || ''
      const arr = { key: 'arrive', label: '到貨', state: arrived ? 'done' : 'todo', cap: arrived ? (day || '已到料') : '—', act: null, late: '' }
      if (arrived && this.dirty && this._mtlPend[mat.id]) arr.cap = (arr.cap === '—' ? '' : arr.cap + '\n') + '待儲存'
      if (!arrived && mat.ordered && mat.expectedDate) {
        arr.cap = '預計 ' + mat.expectedDate
        if (mat.expectedDate < MotrixDate.today()) arr.late = '已逾期'
      }
      if (!arrived && approved && canEdit) {
        if (o && a && a.status === '已核准' && this.moWizOn && this.moWizOn()) arr.act = { label: '到貨登載', run: () => { this.activeTab = 'fin'; this.$nextTick(() => this.moWizOpen(o, false)) } }
        else if (o && a && a.status === '已核准') arr.act = { label: '確認到貨', run: () => this.moReceive(o) }
        else if (po) arr.act = { label: '確認到貨', run: () => { mat.arrived = true; this.onMaterialArrived(mat); this._mtlPend = Object.assign({}, this._mtlPend, { [mat.id]: true }); MotrixUI.toast('已標記到貨，請按「儲存」'); this._mtlWatchSave() } }
      }
      steps.push(arr)

      // 入庫／出貨：案件層級資料（讀不到就不顯示）
      const f = this.mtlFlow
      if (f && f.stock) {
        const has = arrived && f.stock.state !== 'na'
        const stock = { key: 'stock', label: '入庫', state: has ? 'done' : 'todo', cap: !arrived ? '—' : (has ? '整案有入庫紀錄' : '尚無入庫紀錄'), act: null }
        steps.push(stock)
      }
      if (f && f.ship) {
        const sh = f.ship
        const ship = { key: 'ship', label: '出貨', state: arrived && sh.state === 'done' ? 'done' : 'todo', cap: arrived ? (sh.items && sh.items.length ? sh.items.map(i => i.noteNo).join('、') : '尚無出貨單') : '—', act: null }
        if (arrived && !(sh.items && sh.items.length)) ship.act = { label: this.shipCanCreate() ? '開出貨單' : '前往出貨單', run: () => this.shipOpenFromTimeline() }
        steps.push(ship)
      }

      // 目前這一關＝第一個未完成的關卡
      const cur = steps.findIndex(s => s.state !== 'done')
      steps.forEach((s, i) => { if (i === cur) s.state = 'cur' })
      return steps
    },

    mtlSummary() {
      const mats = (this.cr && this.cr.caseRecord && this.cr.caseRecord.materials) || []
      let arrived = 0, noPo = 0, late = 0
      const today = MotrixDate.today()
      mats.forEach(m => {
        const o = this.mtlOrderOf(m)
        if (m.arrived || (o && this.moWizFull && this.moWizFull(o))) arrived++
        else {
          if (!this._mtlHasPo(m, o)) noPo++
          if (m.ordered && m.expectedDate && m.expectedDate < today) late++
        }
      })
      return { total: mats.length, arrived, noPo, late }
    },
    mtlIsOpen(mat) { return !!this.mtlOpen[mat.id] },
    mtlToggle(mat) { this.mtlOpen = Object.assign({}, this.mtlOpen, { [mat.id]: !this.mtlOpen[mat.id] }) },
    mtlOpenLast() {      // 「新增品項」之後：新那一列直接展開，才能馬上填
      const ms = (this.cr && this.cr.caseRecord && this.cr.caseRecord.materials) || []
      const m = ms[ms.length - 1]
      if (m) this.mtlOpen = Object.assign({}, this.mtlOpen, { [m.id]: true })
    },
}))
