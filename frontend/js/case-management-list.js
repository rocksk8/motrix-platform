// case-management-list.js — 案件管理頁：左側清單：清單／看板／矩陣、篩選、分頁、多選、未讀
// CM12 P1（2026-09-24）：由 case-management.js 原樣搬出，成員文字未改；組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({
      isMobileView: window.innerWidth <= 767,
    session: {},
    loading: true,
    cases: [],
    filteredCases: [],
    caseSortPref: { sortMode: '', sortDir: 'desc', customOrder: [] },
    _caseSortable: null,
    listTab: 'all',
    caseViewMode: 'list',   // 'list' | 'board' | 'matrix'
    // ═══ 關卡矩陣（2026-09-14）══════════════════════════════════════════
    // 五項結案前置條件（§5.2）原本散在五個頁籤，而且只有在按下「結案」
    // 被 400 擋下來時才看得到。資料來自 /api/quotations/gate-matrix，那支
    // 端點跟擋下結案用的是同一份判定（_case_close_gates），所以矩陣上的
    // 「5/5 可結案」等於「現在按下去不會被擋」。
    gateMatrix: [],
    gmLoaded: false,
    gmSort: 'ready',     // 'ready' | 'stuck' | 'amount'
    gmFilter: '',        // '' | 'ready' | 'settling' | 'mine'
    gmDue: '',           // '' | 'overdue' | 'today' | 'week' | 'month' | 'none'
    today: new Date().toISOString().slice(0, 10),

    gateHeads: [
      { key: 'progress',     label: '進度', hint: '階段完成' },
      { key: 'payment',      label: '收款', hint: '款項收齊' },
      { key: 'documents',    label: '單據', hint: '簽核完成' },
      { key: 'settlement',   label: '精算', hint: '已完結' },
      { key: 'extraExpense', label: '變更', hint: '無送審中' },
    ],

    // 切到矩陣時才抓。**刻意不在 loadCases() 就一起抓**：矩陣是另一個檢視，
    // 多數時候不會用到，而它每件案子要跑十幾次查詢。
    async switchToMatrix() {
      this.caseViewMode = 'matrix'
      if (!this.gmLoaded) await this.loadGateMatrix()
    },

    async loadGateMatrix() {
      try {
        const r = await fetch('/api/quotations/gate-matrix', {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) {
          const d = await r.json()
          this.gateMatrix = d.items || []
          if (d.today) this.today = d.today
        }
      } catch (_e) {}
      // 放在 finally 之外刻意寫成「不管成功失敗都標記載入過」——否則失敗時
      // 表格會永遠停在「載入中…」，比空清單更難判斷發生什麼事。
      this.gmLoaded = true
    },

    // 燈號：關卡的三種狀態直接對應色階。na 是「這件案子沒有這一關」，
    // 畫成空心灰而不是紅燈——舊案件沒有階段/款項/精算資料是正常的。
    // 2026-09-14 修正：blocked 一律是琥珀，不是紅。共通語彙裡 crit 的定義是
    // 「逾期／退回」，「未達成」是 warn——一個做到 2/5 階段的案子是進行中，
    // 不是異常。只有真的有逾期階段時，進度那一關才轉紅。
    // （原本寫成 progress/extraExpense 一律 crit，違反自己訂的色階規則。）
    gateTone(g, row) {
      if (!g) return 'idle'
      if (g.state === 'ok') return 'ok'
      if (g.state === 'na') return 'idle'
      if (g.key === 'progress' && row && row.stageOverdue > 0) return 'crit'
      return 'warn'
    },

    // 整列不染色，只在最左緣留一條脊，取這一列最嚴重的訊號
    rowSpine(row) {
      if (!row) return 'var(--border-light)'
      if (row.stageOverdue > 0) return 'var(--danger)'
      if (row.canClose) return 'var(--success)'
      return row.blockedCount > 0 ? 'var(--warning)' : 'var(--border-light)'
    },

    readyText(row) {
      if (!row) return ''
      if (row.canClose) return row.readyCount + '/5 可結案'
      if (row.blockedCount === 1) return '差 ' + row.blockedLabels[0]
      return row.readyCount + '/5'
    },

    dueText(row) {
      if (!row) return '—'
      if (row.stageOverdue > 0) {
        return row.nextDue ? row.nextDue.slice(5) + ' 逾期 ' + row.stageOverdue + ' 項'
                           : '逾期 ' + row.stageOverdue + ' 項'
      }
      if (!row.nextDue) return '—'
      if (row.nextDue === this.today) return row.nextDue.slice(5) + ' 今日'
      return row.nextDue.slice(5) + (row.nextDueLabel ? ' ' + row.nextDueLabel : '')
    },

    _dueBucket(row) {
      if (row.stageOverdue > 0) return 'overdue'
      if (!row.nextDue) return 'none'
      if (row.nextDue === this.today) return 'today'
      const days = Math.round((new Date(row.nextDue) - new Date(this.today)) / 86400000)
      if (days < 0) return 'overdue'
      return days <= 7 ? 'week' : days <= 30 ? 'month' : 'none'
    },

    get matrixDue() {
      const def = [
        { key: 'overdue', k: '已逾期', l: '件' },
        { key: 'today',   k: '今日到期', l: '件' },
        { key: 'week',    k: '7 天內', l: '件' },
        { key: 'month',   k: '8–30 天', l: '件' },
        { key: 'none',    k: '無排定到期', l: '件' },
      ]
      return def.map(b => ({
        ...b,
        n: this.gateMatrix.filter(r => this._dueBucket(r) === b.key).length,
      }))
    },

    get matrixRows() {
      const me = this.session.displayName || this.session.username || ''
      let rows = this.gateMatrix.filter(r => {
        if (this.gmDue && this._dueBucket(r) !== this.gmDue) return false
        if (this.gmFilter === 'ready' && !r.canClose) return false
        if (this.gmFilter === 'mine' && r.salesPerson !== me) return false
        if (this.gmFilter === 'settling') {
          const s = (r.gates || []).find(g => g.key === 'settlement')
          if (!s || s.state !== 'blocked') return false
        }
        const q = (this.search || '').trim().toLowerCase()
        if (q && !(r.quoteNo || '').toLowerCase().includes(q)
              && !(r.customerName || '').toLowerCase().includes(q)
              && !(r.projectName || '').toLowerCase().includes(q)) return false
        return true
      })
      const by = {
        // 預設排序。這是既有畫面完全給不出、而且最會改變行動順序的資訊：
        // 先把差一步的收掉，再去處理卡住的。
        ready:  (a, b) => (b.canClose - a.canClose) || (b.readyCount - a.readyCount)
                          || (a.blockedCount - b.blockedCount),
        stuck:  (a, b) => (b.stageOverdue - a.stageOverdue) || (b.blockedCount - a.blockedCount),
        amount: (a, b) => (b.total || 0) - (a.total || 0),
      }
      return rows.slice().sort(by[this.gmSort] || by.ready)
    },

    // 點關卡格 ⇒ 開案件並停在該關的分頁（沿用深連結 ?tab= 的 _pendingUrlTab，選案件重設分頁後才套）
    async openFromMatrix(quoteNo, gate) {
      this.caseViewMode = 'list'
      if (gate) this._pendingUrlTab = this._gateTab(gate)
      await this.selectCase(quoteNo)
    },
    stageBoardItems: [],
    search: '',
    unreadOnly: false,
    readAt: null,
    caseActivity: {},

    // ── CM6（2026-09-24）：清單由伺服器搜尋／篩選／排序／分頁 ────────────────
    // 原本一次拉 limit=500 在前端篩 ⇒ 第 501 件以後看不到也搜不到。現在頁籤、搜尋、排序都送到
    // 伺服器，一頁 casePageSize 件，「載入更多」往後接；摘要數字另打一次 counts（全部案件）。
    // 「只看有新動態」與「自訂（拖曳）排序」仍只作用在已載入的案件上。
    casePageSize: 100,
    // CM7：常用篩選（可疊加，送伺服器）
    caseQuick: { mine: false, stage_overdue: false, recv_overdue: false, missing_docs: false },
    quickFilterDefs: [
      { key: 'mine',          label: '我負責的', count: 'mine' },
      { key: 'stage_overdue', label: '逾期階段', count: 'stageOverdueCases' },
      { key: 'recv_overdue',  label: '應收逾期', count: 'recvOverdue' },
      { key: 'missing_docs',  label: '缺單據',   count: 'missingDocs',
        hint: '缺發票（已收款未登錄發票號碼），或執行階段全部完成卻沒有任何完工單與出貨單' },
    ],
    caseTotal: 0,
    caseCounts: null,
    caseLoadingMore: false,
    _casesSeq: 0,
    _searchTimer: null,

    _caseQuery(offset) {
      const qs = new URLSearchParams({ limit: String(this.casePageSize), offset: String(offset) })
      const board = this.caseViewMode === 'board'
      if (board) qs.set('deal_tag', '已成案,已結案')
      else if (this.listTab === '已結案') qs.set('deal_tag', '已結案')
      else if (this.listTab === '待精算') { qs.set('deal_tag', '已成案,已結案'); qs.set('settle', 'draft') }
      else qs.set('deal_tag', '已成案')        // 「全部」與「已成案」：未結案的案件
      const q = (this.search || '').trim()
      if (q) qs.set('q', q)
      for (const [k, on] of Object.entries(this.caseQuick)) if (on) qs.set(k, '1')
      if (this.unreadOnly) qs.set('unread', '1')
      const mode = this.caseSortPref?.sortMode
      if (mode && mode !== 'custom') { qs.set('sort', mode); qs.set('dir', this.caseSortPref.sortDir || 'desc') }
      return qs
    },

    async loadCases() {
      const seq = ++this._casesSeq
      this.loading = true
      try {
        const r = await fetch('/api/quotations?' + this._caseQuery(0), {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (seq !== this._casesSeq) return          // 較新的查詢已送出（連續打字／切頁籤）
        if (r.ok) {
          const data = await r.json()
          if (seq !== this._casesSeq) return
          this.cases = data.items || []
          this.caseTotal = data.total || 0
        }
      } catch {}
      if (seq !== this._casesSeq) return
      this.loading = false
      this.filterCases()
      this.loadCaseActivity()
      this.loadCaseCounts()
    },

    async loadMoreCases() {
      if (this.caseLoadingMore || this.cases.length >= this.caseTotal) return
      const seq = this._casesSeq
      this.caseLoadingMore = true
      try {
        const r = await fetch('/api/quotations?' + this._caseQuery(this.cases.length), {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok && seq === this._casesSeq) {
          const data = await r.json()
          if (seq === this._casesSeq) {
            const have = new Set(this.cases.map(c => c.quote_no))
            this.cases = this.cases.concat((data.items || []).filter(c => !have.has(c.quote_no)))
            this.caseTotal = data.total || 0
            this.filterCases()
            this.loadCaseActivity()
          }
        }
      } catch {}
      this.caseLoadingMore = false
    },

    // 摘要與頁籤徽章：全部已成案／已結案案件（不受搜尋與分頁影響）
    async loadCaseCounts() {
      try {
        const qs = new URLSearchParams({ deal_tag: '已成案,已結案', counts: '1', limit: '0' })
        const r = await fetch('/api/quotations?' + qs, { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) this.caseCounts = (await r.json()).counts || null
      } catch {}
    },

    onCaseSearchInput() {
      clearTimeout(this._searchTimer)
      this._searchTimer = setTimeout(() => this.loadCases(), 300)
    },

    setListTab(tab) {
      this.listTab = tab
      this.loadCases()
    },

    // ── CM10（2026-09-24）：批次操作 ─────────────────────────────────────────
    // 多選模式下卡片出現勾選框；批次改執行負責／成員（管理員以上，只改進行中的案件）、批次匯出 Excel。
    batchMode: false,
    batchSel: {},
    batchExec: '',
    batchMember: '',
    batchBusy: false,
    batchMsg: '',

    canBatchAssign() { return ['superadmin', 'admin'].includes(this.session.role) },
    batchCount() { return Object.keys(this.batchSel).length },
    batchNos() { return Object.keys(this.batchSel) },
    isBatchSel(c) { return !!this.batchSel[c.quote_no] },

    toggleBatchMode() {
      this.batchMode = !this.batchMode
      this.batchSel = {}
      this.batchMsg = ''
    },
    toggleBatch(c) {
      const m = { ...this.batchSel }
      if (m[c.quote_no]) delete m[c.quote_no]
      else m[c.quote_no] = true
      this.batchSel = m
    },
    batchSelectPage() {
      const m = { ...this.batchSel }
      for (const c of this.filteredCases) m[c.quote_no] = true
      this.batchSel = m
    },

    async batchAssign(kind) {
      const nos = this.batchNos()
      if (!nos.length || this.batchBusy) return
      const body = { quote_nos: nos }
      if (kind === 'executor') {
        if (!this.batchExec) { this.batchMsg = '請先選擇執行負責'; return }
        body.executor = this.batchExec === '__clear__' ? '' : this.batchExec
      } else {
        if (!this.batchMember) { this.batchMsg = '請先選擇成員'; return }
        body[kind === 'add' ? 'add_members' : 'remove_members'] = [Number(this.batchMember)]
      }
      this.batchBusy = true
      this.batchMsg = ''
      try {
        const r = await fetch('/api/case-batch/assign', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(body),
        })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { this.batchMsg = (typeof d.detail === 'string' && d.detail) || '批次變更失敗'; return }
        const sk = d.skipped || []
        this.batchMsg = `已變更 ${(d.updated || []).length} 件` + (sk.length
          ? `；略過 ${sk.length} 件（${sk.map(s => s.quoteNo + '：' + s.reason).join('、')}）` : '')
        // 目前開著的案件也在名單裡且沒有未存變更 ⇒ 重新載入，畫面才看得到新的負責人／成員
        if (this.selected && (d.updated || []).includes(this.selected.quote_no) && !this.dirty) {
          this.selectCase(this.selected.quote_no)
        }
        this.loadCases()
      } catch {
        this.batchMsg = '網路錯誤，請稍後再試'
      } finally {
        this.batchBusy = false
      }
    },

    async batchExport() {
      const nos = this.batchNos()
      if (!nos.length || this.batchBusy) return
      this.batchBusy = true
      this.batchMsg = ''
      try {
        const r = await fetch('/api/case-batch/export', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ quote_nos: nos }),
        })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this.batchMsg = (typeof d.detail === 'string' && d.detail) || '匯出失敗'
          return
        }
        const blob = await r.blob()
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = '案件匯出.xlsx'
        document.body.appendChild(a)
        a.click()
        a.remove()
        setTimeout(() => URL.revokeObjectURL(a.href), 5000)
      } catch {
        this.batchMsg = '網路錯誤，請稍後再試'
      } finally {
        this.batchBusy = false
      }
    },

    toggleQuick(key) {
      this.caseQuick = { ...this.caseQuick, [key]: !this.caseQuick[key] }
      this.loadCases()
    },

    toggleUnreadOnly() {
      this.unreadOnly = !this.unreadOnly
      this.loadCases()
    },

    // 卡片上標出缺哪一種單據
    missingDocTags(c) {
      const t = []
      if (c.missing_invoice) t.push('缺發票')
      if (c.missing_notes) t.push('缺完工／出貨單')
      return t
    },

    // 視覺化改版（2026-08-23）：摘要總覽卡片的「已逾期階段」數字需要跨案件的
    // 階段到期資訊，這份資料 case-stage-board.html 已經在用（stage_board() 回傳
    // 的 items 就含 dueDate/done/overdue），這裡直接重用同一支既有 API，不用
    // 新增後端端點。只在案件管理頁載入時抓一次，不影響既有的 cases/filterCases。
    async loadStageBoardSummary() {
      try {
        const r = await fetch('/api/quotations/stage-board', {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.stageBoardItems = (await r.json()).items || []
      } catch {}
    },

    // 件數是另一支非同步請求；還沒到之前回 null（不可以退回已載入那一頁的件數冒充總數）
    summaryTotal()   { return this.caseCounts ? this.caseCounts.all : null },
    summaryActive()  { return this.caseCounts ? this.caseCounts.active : 0 },
    summaryClosed()  { return this.caseCounts ? this.caseCounts.closed : 0 },
    summaryOverdue() { return this.caseCounts ? this.caseCounts.overdueStages : 0 },
    summarySettling(){ return this.caseCounts ? this.caseCounts.settling : 0 },

    // 看板檢視分欄：跟清單分頁的定義完全一致，只是同時攤開而非切換——待精算優先
    // （呼應既有「待精算」分頁的定義，settle_status 是跟 deal_tag 獨立的另一個軸，
    // 一個案件可能同時是「已成案」又「待精算」，看板需要互斥分欄，所以待精算優先
    // 分類，其餘才依 deal_tag 分成進行中/已結案）。
    boardColumns() {
      const q = this.search.trim().toLowerCase()
      let pool = !q ? this.cases : this.cases.filter(c =>
        (c.quote_no || '').toLowerCase().includes(q) ||
        (c.customer_name || '').toLowerCase().includes(q) ||
        (c.project_name  || '').toLowerCase().includes(q)
      )
      const settling = [], active = [], closed = []
      for (const c of pool) {
        if (c.settle_status === 'draft') settling.push(c)
        else if (c.deal_tag === '已結案') closed.push(c)
        else active.push(c)
      }
      return [
        { key: '待精算', label: '待精算', dot: '#FCD34D', items: settling },
        { key: '進行中', label: '進行中', dot: '#4ADE80', items: active },
        { key: '已結案', label: '已結案', dot: '#C4B5FD', items: closed },
      ]
    },

    // UR1：`caseActivity` 改存「伺服器判斷的未讀案件」`{quote_no: true}`
    //   （同三個來源：案件動態／工作日誌／每日工作完成，但**依作者排除本人**、逐筆已讀）。
    //   原本是每筆的最後動態時間 vs 整個清單一個 localStorage 時間戳。
    // ⚠️ 先渲染再非同步載入＝競態：查詢送出之後、回應抵達之前使用者點了某一筆，
    //    伺服器算這份回應時還沒有那筆已讀 ⇒ 不可以讓它把剛點過的那一筆蓋回未讀。
    async loadCaseActivity() {
      const quoteNos = this.cases.map(c => c.quote_no).filter(Boolean)
      if (!quoteNos.length || !window.MotrixReads) { this.caseActivity = {}; return }
      const t0 = Date.now()
      const got = await window.MotrixReads.unread('case', quoteNos)
      const m = {}
      got.forEach(k => { if (!((this._readAtLocal || {})[k] >= t0)) m[k] = true })
      this.caseActivity = m
    },

    isUnread(c) {
      return !!(c && this.caseActivity[c.quote_no])
    },

    /** 真的切換到這一筆之後才呼叫：當下先清標記，再送出（不等回應）。 */
    _markCaseRead(quoteNo) {
      if (!quoteNo || !this.caseActivity[quoteNo]) return
      const m = { ...this.caseActivity }
      delete m[quoteNo]
      this.caseActivity = m
      this._readAtLocal = { ...(this._readAtLocal || {}), [quoteNo]: Date.now() }
      if (window.MotrixReads) window.MotrixReads.mark('case', quoteNo)
    },

    // CM7：未讀件數是全部案件（伺服器），不是已載入的那一頁
    unreadCount() {
      return this.caseCounts ? (this.caseCounts.unread || 0) : this.cases.filter(c => this.isUnread(c)).length
    },

    async markAllRead() {
      // 全部未讀（不只已載入的）：先向伺服器要清單再逐筆標記
      let keys = Object.keys(this.caseActivity)
      try {
        const qs = new URLSearchParams({ deal_tag: '已成案,已結案', unread: '1', limit: '500' })
        const r = await fetch('/api/quotations?' + qs, { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) keys = [...new Set(keys.concat(((await r.json()).items || []).map(c => c.quote_no)))]
      } catch {}
      this.caseActivity = {}
      const now = Date.now()
      this._readAtLocal = { ...(this._readAtLocal || {}), ...Object.fromEntries(keys.map(k => [k, now])) }
      if (window.MotrixReads) keys.forEach(k => window.MotrixReads.mark('case', k))
      this.unreadOnly = false
      if (this.caseCounts) this.caseCounts = { ...this.caseCounts, unread: 0 }
      this.loadCases()
    },

    filterCases() {
      let list = this.cases
      if (this.listTab === '待精算') {
        list = list.filter(c => c.settle_status === 'draft')
      } else if (this.listTab === 'all') {
        list = list.filter(c => c.deal_tag !== '已結案')
      } else {
        list = list.filter(c => c.deal_tag === this.listTab)
      }
      // CM7：「只看有新動態」由伺服器篩（全部案件）；這裡不再用 caseActivity 過濾——
      //      它是之後才非同步載入的，先過濾會把伺服器回來的那幾筆濾掉
      if (this.search.trim()) {
        const q = this.search.trim().toLowerCase()
        list = list.filter(c =>
          (c.quote_no || '').toLowerCase().includes(q) ||
          (c.customer_name || '').toLowerCase().includes(q) ||
          (c.project_name  || '').toLowerCase().includes(q)
        )
      }
      this.filteredCases = applyListSort(list, this.caseSortPref, {
        quote_date:    c => c.quote_date || c.created_at || '',
        total:         c => c.total || 0,
        customer_name: c => c.customer_name || '',
      }, c => c.quote_no)
      this.$nextTick(() => this.initCaseSortable())
    },

    async setCaseSortMode(mode) {
      this.caseSortPref.sortMode = mode
      this.loadCases()
      await saveListPref(this.session.token, 'case_list', this.caseSortPref)
    },
    async toggleCaseSortDir() {
      this.caseSortPref.sortDir = this.caseSortPref.sortDir === 'asc' ? 'desc' : 'asc'
      this.loadCases()
      await saveListPref(this.session.token, 'case_list', this.caseSortPref)
    },
    initCaseSortable() {
      const body = this.$refs.caseListBody
      if (!body || typeof Sortable === 'undefined') return
      if (this._caseSortable) { this._caseSortable.destroy(); this._caseSortable = null }
      if (this.caseSortPref.sortMode !== 'custom') return
      this._caseSortable = Sortable.create(body, {
        animation: 150,
        handle: '.drag-handle',
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        onEnd: async () => {
          const visibleIds = [...body.querySelectorAll('.cm-card[data-quote-no]')].map(el => el.dataset.quoteNo)
          const rest = this.caseSortPref.customOrder.filter(id => !visibleIds.includes(id))
          this.caseSortPref.customOrder = [...visibleIds, ...rest]
          await saveListPref(this.session.token, 'case_list', this.caseSortPref)
        }
      })
    },
}))
