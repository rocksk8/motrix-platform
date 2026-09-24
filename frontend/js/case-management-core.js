// case-management-core.js — 案件管理頁：核心：初始化、選案件（selectCase／_selectLive）、案件記錄存檔、共用小工具
// CM12 P1（2026-09-24）：由 case-management.js 原樣搬出，成員文字未改；組合見 case-management-core.js 的 app()。
// 依字串 hash 對應固定色盤，跟 daily-tasks.html 的 _avatarColor 用同一組色碼與演算法，
// 讓同一位負責人在甘特圖／每日工作事項月曆／看板三處的顏色一致。
const _GANTT_COLORS = ['#2563EB','#7C3AED','#DB2777','#D97706','#16A34A','#0891B2','#DC2626','#9333EA']
function _avatarColor(u) {
  let h = 0
  for (let i = 0; i < u.length; i++) h = (h * 31 + u.charCodeAt(i)) | 0
  return _GANTT_COLORS[Math.abs(h) % _GANTT_COLORS.length]
}

// 各分頁的成員各自登記一個工廠（回傳全新物件），app() 依載入順序組合。
// 用 getOwnPropertyDescriptors 而不是 Object.assign：後者會把 get matrixRows() 等 getter
// 在組合當下求值、變成定值。成員名稱不可重複（test_case_page_parts 守著）。
window.CM_PARTS = window.CM_PARTS || []
function app() {
  const o = {}
  for (const part of window.CM_PARTS) Object.defineProperties(o, Object.getOwnPropertyDescriptors(part()))
  return o
}

window.CM_PARTS.push(() => ({

    // 點一列回到既有的五頁籤詳情頁——矩陣是它的上層索引，不是取代它
    //: 據點 id -> 名字。**只有一個據點（或讀不到）時回空字串**，
    //  那一行就不顯示 —— 一個永遠一樣的標籤不是資訊，它只是佔位置。
    //  QL15：多據點之後兩個分公司的案子混在同一張表裡，而「這是誰的案子」
    //  是使用者每天都要問的第一個問題。
    locations: [],
    locationName(id) {
      if (!id || !this.locations || this.locations.length < 2) return ''
      const hit = this.locations.find(l => l && l.id === id)
      return hit ? (hit.name || '') : ''
    },

    //: 讀公司資料裡的據點清單。讀不到就留空 => 那一行不顯示，其餘照常。
    async loadLocations() {
      try {
        const r = await fetch(`${this.API}/settings/company-profile`, {
          headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) return
        const d = await r.json()
        this.locations = (d.locations || []).filter(l => l && l.id)
      } catch (_e) { /* 讀不到就不顯示據點 */ }
    },
    selected: null,
    activeTab: 'biz',
    execSubTab: 'progress',
    cr: { dealTag: '已成案', caseRecord: null },
    dirty: false,
    saving: false,
    saveStatus: '',
    saveMsg: '',
    _autoSaveTimer: null,
    // CM1（2026-09-24）：caseRecord 各頂層分段在伺服器上的值（JSON 字串），存檔只送與它
    // 不同的分段並附上它當基準；segConflict＝上次存檔被擋下的分段名稱。
    _segBase: {},
    _segFill: {},
    segConflict: null,
    selectableUsers: [],
    exportingProjectReport: false,
    headerMoreOpen: false,   // CU5：標頭「更多」選單
    savedFlash: {},          // CU6：即時儲存成功 ⇒ 區塊標題閃 ✓（鍵：case／stages／dispatch-<id>／xe-<id>／mo-<itemId>）
    _subSortables: {},

    canSeeFinancial() {
      const m = this.session.modules || []
      return m.includes('financial_view') || ['superadmin','admin','sales'].includes(this.session.role)
    },

    // ── 分頁狀態進 URL（2026-09-14）───────────────────────────────────
    // 原本重新整理或把連結貼給同事，都會跳回第一個分頁。營運報表已經有
    // ?tab= 的深連結模式，這裡比照。
    // 刻意不改那 8 個 inline @click（每個都還帶自己的載入呼叫，逐一改容易漏），
    // 改用 $watch 集中處理。
    _pendingUrlTab: null,
    _initTabFromUrl() {
      var t = new URLSearchParams(location.search).get('tab')
      var valid = ['biz','exec','dispatch','shipping','completion','feed','fin','xexp']
      // 只記下來，不直接套：選案件時會把 activeTab 重設成 'biz'（那行是刻意的，
      // 見 selectCase 的註解），所以要在重設之後才套，而且只套第一次。
      if (t && valid.indexOf(t) >= 0) this._pendingUrlTab = t
      var self = this
      this.$watch('activeTab', function (v) {
        var u = new URL(location.href)
        u.searchParams.set('tab', v)
        history.replaceState(null, '', u)
      })
    },

    async init() {
      // 2026-09-24：離頁警告（sidebar.js）跟著主表單的 dirty 走：setDirty() 設 true，
      // 存檔成功（dirty 轉 false）時清掉。
      this.$watch('dirty', v => { window.motrixIsDirty = !!v })
      this.$watch('activeTab', v => this.ensureTabData(v))      // CM8：分頁延後載入
      this._initTabFromUrl()
      // QL15：據點清單。不 await —— 它只決定一行小字要不要顯示，
      // 而這一頁的主體（案件矩陣）不應該等它。
      this.loadLocations()
      // Alpine 3 會自動呼叫資料物件上的 init()，而 case-management.html 的
      // <body> 又寫了一次 x-init="init()"，所以整個 init() 每次開頁都跑兩遍：
      // 所有 API 都發兩次，並且第二次 selectCase() 會把第一次已經載好的狀態
      // 整個重置。先前看不出來是因為這頁的子清單全部是唯讀的，重載一次
      // 看不出差別；2026-09-11 新增可編輯的叫料清單後才暴露——使用者在兩次
      // init 中間按「＋新增項目」，那一列會被第二次載入默默抹掉。
      // 這裡只修本頁；全站共 50 個頁面有同樣的 x-init 寫法，屬於独立課題。
      if (this._initDone) return
      this._initDone = true
      window.addEventListener('resize', () => { this.isMobileView = window.innerWidth <= 767 })
      const s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      if (!s.token) { location.href = 'login.html'; return }
      this.session = s
      try {
        const r = await fetch('/api/auth/me', { headers: { Authorization: 'Bearer ' + s.token } })
        if (!r.ok) { location.href = 'login.html'; return }
        const me = await r.json()
        this.session.displayName = me.displayName
        this.session.id = me.userId
      } catch {}
      try {
        const ru = await fetch('/api/users/selectable', { headers: { Authorization: 'Bearer ' + s.token } })
        if (ru.ok) this.selectableUsers = await ru.json()
      } catch {}
      // UR1：已讀改存伺服器（逐筆、排除本人）。上一頁回來／其他分頁標了已讀 ⇒ 重抓。
      //   舊的 `motrix_casemgmt_read_at` 由 notif.js 一次性遷移成伺服器端的清單基準。
      window.addEventListener('motrix:reads-changed', () => this.loadCaseActivity())
      // 跨分頁樂觀已讀：只合併那一筆，不整包重抓；伺服器拒絕時還原。
      window.addEventListener('motrix:item-read', e => {
        if (e.detail.kind !== 'case' || !this.caseActivity[e.detail.key]) return
        const m = { ...this.caseActivity }
        delete m[e.detail.key]
        this.caseActivity = m
        this._readAtLocal = { ...(this._readAtLocal || {}), [e.detail.key]: Date.now() }
      })
      window.addEventListener('motrix:item-read-failed', e => {
        if (e.detail.kind !== 'case') return
        const k = e.detail.key
        if (!(this.cases.some(c => c.quote_no === k))) return
        const loc = { ...(this._readAtLocal || {}) }
        delete loc[k]
        this._readAtLocal = loc
        this.caseActivity = { ...this.caseActivity, [k]: true }
      })
      this.caseSortPref = await loadListPref(s.token, 'case_list')
      await this.loadCases()
      this.loadVendors()
      const _qp = new URLSearchParams(location.search).get('q')
      if (_qp) {
        // CM6：清單分頁後，目標可能不在第一頁 ⇒ 用同一支清單端點（同一套權限）精確找那一件。
        // `AC2`：已結案案件的連結（營運報表「待補登」清單會連過來）要切到「已結案」頁籤。
        const _found = await this._findCase(_qp)
        if (_found && _found.deal_tag === '已結案' && this.listTab !== '已結案') {
          this.listTab = '已結案'
          this.loadCases()
        }
        if (_found) await this.selectCase(_found.quote_no)
      }
    },

    async _findCase(quoteNo) {
      try {
        const qs = new URLSearchParams({ deal_tag: '已成案,已結案', q: quoteNo, limit: '20' })
        const r = await fetch('/api/quotations?' + qs, { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) return null
        return ((await r.json()).items || []).find(c => c.quote_no === quoteNo) || null
      } catch { return null }
    },

    // ── 案件內單據子清單排序（出貨單/開票憑據/請款單，2026-08-24）───────────────
    // 三個子清單的排序偏好各自獨立，list_key 帶上 quote_no 前綴（見 loadShippingNotes
    // /loadInvoiceVouchers/loadPaymentRequests 載入時機），避免跨案件互相污染。
    _subListMeta: {
      sn:     { pref: 'snSortPref',     dataKey: 'shippingNotes',   ref: 'snListBody', idField: 'noteNo',
                fields: { shipDate: n => n.shipDate || '', createdAt: n => n.createdAt || '' } },
      iv:     { pref: 'ivSortPref',     dataKey: 'invoiceVouchers', ref: 'ivListBody', idField: 'voucherNo',
                fields: { createdAt: v => v.createdAt || '', totalAmount: v => v.totalAmount || 0 } },
      prList: { pref: 'prListSortPref', dataKey: 'paymentRequests', ref: 'prListBody', idField: 'requestNo',
                fields: { createdAt: v => v.createdAt || '', amount: v => v.amount || 0 } },
    },
    _sortedSubList(kind) {
      const meta = this._subListMeta[kind]
      return applyListSort(this[meta.dataKey] || [], this[meta.pref], meta.fields, item => item[meta.idField])
    },
    sortedShippingNotes()   { return this._sortedSubList('sn') },
    sortedInvoiceVouchers() { return this._sortedSubList('iv') },
    sortedPaymentRequests() { return this._sortedSubList('prList') },

    async setSubListSortMode(kind, mode) {
      const meta = this._subListMeta[kind]
      this[meta.pref].sortMode = mode
      this.$nextTick(() => this._initSubListSortable(kind))
      await saveListPref(this.session.token, `${kind}:${this.selected.quote_no}`, this[meta.pref])
    },
    async toggleSubListSortDir(kind) {
      const meta = this._subListMeta[kind]
      this[meta.pref].sortDir = this[meta.pref].sortDir === 'asc' ? 'desc' : 'asc'
      await saveListPref(this.session.token, `${kind}:${this.selected.quote_no}`, this[meta.pref])
    },
    _initSubListSortable(kind) {
      const meta = this._subListMeta[kind]
      const body = this.$refs[meta.ref]
      if (!body || typeof Sortable === 'undefined') return
      if (this._subSortables[kind]) { this._subSortables[kind].destroy(); this._subSortables[kind] = null }
      if (this[meta.pref].sortMode !== 'custom') return
      this._subSortables[kind] = Sortable.create(body, {
        animation: 150,
        handle: '.drag-handle',
        ghostClass: 'sortable-ghost',
        chosenClass: 'sortable-chosen',
        onEnd: async () => {
          const visibleIds = [...body.querySelectorAll('[data-item-id]')].map(el => el.dataset.itemId)
          const rest = (this[meta.pref].customOrder || []).filter(id => !visibleIds.includes(id))
          this[meta.pref].customOrder = [...visibleIds, ...rest]
          await saveListPref(this.session.token, `${kind}:${this.selected.quote_no}`, this[meta.pref])
        }
      })
    },

    // CM8（2026-09-24）：case-bundle 的一段 → 與 fetch 回應同形狀，loader 不必分兩條路
    _preResp(pre) {
      return { ok: !!pre.ok, status: pre.ok ? 200 : (pre.status || 500), json: async () => pre.data }
    },

    // CM8：開案件只打 case-bundle；下面這些改成「點到那個分頁才載入」（同一件只載一次，
    // 之後照原本各自的 reload）。載入前旗標先設 loading，畫面顯示「載入中」而不是「尚無資料」。
    _tabLoaded: {},
    ensureTabData(tab) {
      const no = this.selected?.quote_no
      if (!no || this._tabLoaded[tab] === no) return
      const loaders = {
        fin: () => { this.loadFinanceSummary(no); this.loadInvoiceVouchers(no); this.loadPaymentRequests(no); this.loadMaterialOrders(no) },
        dispatch: () => { this.loadContractorVouchers(no) },
        feed: () => { this._loadCaseTasks(no) },
      }
      if (!loaders[tab]) return
      this._tabLoaded = { ...this._tabLoaded, [tab]: no }
      loaders[tab]()
    },

    // CM12 P2（2026-09-24）：案件層級狀態的重設集中在各模組的 _reset_<模組>(phase, data)。
    // phase：'early'＝第一個 await 之前（分頁列一出現就可能被點，必須先重設完）；
    //        'late'＝建立預設階段之後（dirty 等要在 ensureCaseRecord 之後才清）。
    // 新增案件層級的狀態時，把重設寫進自己模組的 _reset_，不要寫回 selectCase。
    _resetCaseScoped(phase, data) {
      for (const m of ['core', 'list', 'close', 'biz', 'exec', 'dispatch', 'shipping', 'completion', 'feed', 'fin', 'xexp']) {
        const f = this['_reset_' + m]
        if (typeof f === 'function') f.call(this, phase, data)
      }
    },

    // 連點兩件時，只有最後點的那一件可以落地（先點的回應較晚抵達時丟掉）。
    // _selectLive() 回傳「這次載入還算數嗎」：之後又選了案件就回 false。selectCase 與它
    // 發出的每支子載入在每個 await 之後都先問它，前一件的後段不會寫進目前這一件的畫面與存檔。
    _selectSeq: 0,
    _selectLive() {
      const seq = this._selectSeq
      return () => seq === this._selectSeq
    },

    async selectCase(quoteNo) {
      // 2026-09-24：有未存的變更時先存完再切換。原本這裡直接取消待存計時器、
      // 下面再 dirty=false ⇒ 打完字 1.5 秒內切換案件，剛打的內容就消失。
      clearTimeout(this._autoSaveTimer)
      if (this.dirty && this.selected) {
        while (this.saving) await new Promise(res => setTimeout(res, 50))
        if (this.dirty) await this.saveCaseRecord()
        if (this.dirty && !confirm(`上一張案件（${this.selected.quote_no}）沒有存成功：${this.saveMsg || '未儲存'}\n\n仍要切換並放棄這些變更？`)) {
          return
        }
      }
      // 確定要切換才遞增：使用者取消切換時，目前這一件進行中的載入仍算數
      ++this._selectSeq
      const live = this._selectLive()
      try {
        const r = await fetch('/api/quotations/' + encodeURIComponent(quoteNo) + '/case-bundle', {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) return
        const bundle = await r.json()
        if (!live()) return
        const data = bundle.quotation
        const parts = bundle.parts || {}
        this.selected = data
        // UR1：放在「真的切換過去」之後——上面取消切換（存檔失敗選「否」）時 return，
        //      那一筆的未讀標記必須還在。
        this._markCaseRead(quoteNo)
        this.loadCaseHealth(quoteNo, parts.health)
        this.loadCaseLinks(quoteNo, parts.vouchers)
        // 同時編輯警示（2026-09-14）：切換案件時自動釋放前一張、回報這一張
        if (window.MotrixPresence) window.MotrixPresence.start('case', quoteNo)
        this._resetCaseScoped('early', data)
        await this.ensureCaseRecord()
        if (!live()) return
        this._segFill = this._fillOnly(this._segBase)
        await this._seedDefaultStagesIfEmpty()
        if (!live()) return
        this._resetCaseScoped('late', data)
        this.loadDispatches(quoteNo, parts.dispatches)
        // 2026-09-14：這三個原本是「點分頁才載」，但分頁上的數量徽章要在沒點過
        // 之前就正確——沒載入時綁 .length 會顯示 0，看起來像「這案子沒有出貨單」，
        // 比沒有徽章更糟。兩個 loader 都是單純 GET、無副作用（不會標記已讀），
        // 這裡本來就已經並行打 8 個端點，多這三個是邊際成本。
        this.loadShippingNotes(quoteNo, parts.shippingNotes)
        this.loadCompletionNotes(quoteNo, parts.completionNotes)
        this.loadCaseUpdates(quoteNo, parts.updates)
        this.loadExtraExpenses(quoteNo, parts.extraExpenses)
        this.ensureTabData(this.activeTab)
      } catch {}
    },

    // ── 專案執行報告匯出 ──
    async exportProjectReport() {
      if (!this.selected || this.exportingProjectReport) return
      this.exportingProjectReport = true
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/project-report-pdf`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert('匯出失敗：' + (await r.json()).detail); return }
        const blob = await r.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `${this.selected.quote_no}_專案執行報告.pdf`
        a.click()
        URL.revokeObjectURL(url)
      } catch(e) {
        alert('發生錯誤：' + e.message)
      } finally {
        this.exportingProjectReport = false
      }
    },

    ensureCaseRecord() {
      if (!this.cr.caseRecord) {
        this.cr.caseRecord = {
          // stages 正規化 Phase 3b（2026-08-23）：不再本地寫死 5 個帶假 id 的階段物件——
          // 一旦切到 stages 專屬端點，假 id 對伺服器來說根本不存在，操作會 404。真正的
          // 5 個預設階段改由 _seedDefaultStagesIfEmpty() 透過 API 建立，取得真實 id。
          stages: [],
          payment: { items: [
            { id: 1, type: '訂金款', pct: 30, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
            { id: 2, type: '交貨款', pct: 30, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
            { id: 3, type: '驗收款', pct: 40, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          ], note: '' },
          materials: [], devices: [], warrantyNote: '', notes: '',
        }
      }
      if (!this.cr.caseRecord.stages)    this.cr.caseRecord.stages    = []
      if (!this.cr.caseRecord.materials) this.cr.caseRecord.materials = []
      if (!this.cr.caseRecord.devices)   this.cr.caseRecord.devices   = []
      if (!this.cr.caseRecord.contract) {
        this.cr.caseRecord.contract = { deliveryAddress: '', deliveryTerms: '', contactPerson: '', contactPhone: '', contractNote: '' }
        // 第一次建立時從報價單帶入（2026-09-14 使用者交辦「合約資訊要能根據
        // 報價單內容連動」）。**單向、只帶一次**：案件成立後現場條件本來就
        // 可能跟報價當時不同，雙向同步會讓改案件反過來改到已經簽核的報價單；
        // 每次開啟都覆蓋則會把現場修正洗掉。已存在的案件用下面那顆
        // pullContractFromQuote() 手動帶，不在載入時偷偷補寫。
        this._fillContractFromQuote(this.cr.caseRecord.contract)
      }
      if (!this.cr.caseRecord.roles) {
        this.cr.caseRecord.roles = { filler: '', sales: '', executor: '' }
      }
      if (!this.cr.caseRecord.projectTimeline) {
        this.cr.caseRecord.projectTimeline = { startDate: '', endDate: '', status: 'on_track' }
      }

      this.cr.caseRecord.materials.forEach(mat => {
        if (!mat.devices) mat.devices = []
        if (!mat.model)   mat.model   = ''
        if (!mat.unit)    mat.unit    = '台'
      })

      this.cr.caseRecord.stages.forEach(st => {
        if (!st.visits) {
          st.visits = (st.visitDate || st.note)
            ? [{ id: Date.now() + Math.random(), visitDate: st.visitDate || '', visitPeople: st.visitPeople || '', note: st.note || '' }]
            : []
          delete st.visitDate; delete st.visitPeople; delete st.note
        }
        if (st.startDate  === undefined) st.startDate  = ''
        if (st.dueDate    === undefined) st.dueDate    = ''
        if (!st.assignedTo) st.assignedTo = []
        if (!st.dependsOn)  st.dependsOn  = []
      })

      if (!this.cr.caseRecord.payment) {
        this.cr.caseRecord.payment = { items: [
          { id: 1, type: '訂金款', pct: 30, amount: null, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          { id: 2, type: '交貨款', pct: 30, amount: null, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          { id: 3, type: '驗收款', pct: 40, amount: null, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
        ], note: '' }
      } else if (!this.cr.caseRecord.payment.items) {
        this.cr.caseRecord.payment = { items: [
          { id: 1, type: '訂金款', pct: 30, amount: null, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          { id: 2, type: '交貨款', pct: 30, amount: null, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
          { id: 3, type: '驗收款', pct: 40, amount: null, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' },
        ], note: this.cr.caseRecord.payment.note || '' }
      }
    },

    // stages 正規化 Phase 3b（2026-08-23）：案件目前完全沒有階段時（新案件、或早期
    // 資料從未經過 quotation-form.html／case-management.html 任何一份預設模板寫入
    // 過），透過 stages 端點依序建立 5 個預設階段，取得真實 id。selectCase() 載入完
    // 成後呼叫一次；ensureCaseRecord() 補齊其他欄位形狀之後才會執行到這裡。
    async _seedDefaultStagesIfEmpty() {
      if (!this.selected || !this.cr.caseRecord) return
      if ((this.cr.caseRecord.stages || []).length > 0) return
      const live = this._selectLive()
      const labels = ['訂單確認', '叫料出貨', '施工安裝', '客戶驗收', '尾款結清']
      for (const label of labels) {
        if (!live()) return
        try {
          const r = await fetch(`/api/quotations/${this.selected.quote_no}/stages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({ label })
          })
          const st = r.ok ? await r.json() : null
          if (!live()) return
          if (st) this.cr.caseRecord.stages.push(st)
        } catch {}
      }
    },

    // CM14b（2026-09-24）：不是案件成員、靠 cashier 模組讀到的 ⇒ 除收款外全唯讀（後端另擋寫入）
    caseReadOnly() { return !!this.selected?.cashierReadOnly },

    // CU6：即時儲存成功閃 ✓（1.6 秒後消失；連續存檔以最後一次為準）
    flashSaved(key) {
      const at = Date.now()
      this.savedFlash = { ...this.savedFlash, [key]: at }
      setTimeout(() => {
        if (this.savedFlash[key] !== at) return
        const next = { ...this.savedFlash }; delete next[key]; this.savedFlash = next
      }, 1600)
    },

    setDirty() {
      this.dirty = true
      window.motrixIsDirty = true
      this.saveStatus = 'dirty'
      this.saveMsg = '未儲存'
      clearTimeout(this._autoSaveTimer)
      this._autoSaveTimer = setTimeout(() => this.saveCaseRecord(), 1500)
      this._checkAllStagesDone()
    },

    // ensureCaseRecord 替伺服器上沒有的分段補的預設值（使用者還沒動過）
    _fillOnly(base) {
      const out = {}
      for (const [k, v] of Object.entries(this._snapSegments(this.cr.caseRecord))) {
        if (base[k] === undefined) out[k] = v
      }
      return out
    },

    _snapSegments(cr) {
      const out = {}
      for (const [k, v] of Object.entries(cr || {})) {
        if (k !== 'stages' && v !== undefined) out[k] = JSON.stringify(v)
      }
      return out
    },

    // 自己在頁面上經由專屬端點改了伺服器上的某一段（附件上傳／刪除、沖銷）：
    // 同一個改動要同時套在畫面與基準上，否則下一次存檔會把自己擋下（或把附件蓋掉）。
    _applyToBoth(seg, fn) {
      if (this.cr.caseRecord) fn(this.cr.caseRecord)
      if (this._segBase[seg] === undefined) return
      const b = { [seg]: JSON.parse(this._segBase[seg]) }
      fn(b)
      this._segBase[seg] = JSON.stringify(b[seg])
    },

    _segLabel(k) {
      return ({ payment: '收款', materials: '材料', devices: '設備', contract: '合約資訊', roles: '角色',
        projectTimeline: '專案時程', materialOrders: '叫料', warrantyNote: '保固備註', notes: '備註' })[k] || k
    },

    // 衝突處理：reload＝放棄我的改動、改看伺服器現值；keep＝以伺服器現值為基準重存（明知並覆蓋那幾段）
    async resolveConflict(mode) {
      if (!this.selected || !this.segConflict) return
      const r = await fetch('/api/quotations/' + this.selected.quote_no, {
        headers: { Authorization: 'Bearer ' + this.session.token }
      })
      if (!r.ok) return
      const srv = (await r.json()).data?.caseRecord || {}
      const fresh = this._snapSegments(srv)
      if (mode === 'reload') {
        const stages = this.cr.caseRecord?.stages || []
        this.cr.caseRecord = { ...srv, stages }
        this._segBase = fresh
        this.ensureCaseRecord()
        this._segFill = this._fillOnly(fresh)
        this.segConflict = null
        this.dirty = false
        window.motrixIsDirty = false
        this.saveStatus = ''
        this.saveMsg = ''
        return
      }
      for (const k of this.segConflict) {
        if (fresh[k] === undefined) delete this._segBase[k]
        else this._segBase[k] = fresh[k]
      }
      this.segConflict = null
      await this.saveCaseRecord()
    },

    // CU3：使用者按「儲存」⇒ 成功時跳明顯提示；自動存檔走 saveCaseRecord() 不跳
    saveToast: '',
    _saveToastTimer: null,
    async manualSave() {
      clearTimeout(this._autoSaveTimer)
      await this.saveCaseRecord()
      if (this.saveStatus === 'saved' || (this.saveStatus === 'dirty' && this.saveMsg && !this.dirty)) {
        this.saveToast = this.saveMsg || '已儲存'
        clearTimeout(this._saveToastTimer)
        this._saveToastTimer = setTimeout(() => { this.saveToast = '' }, 2500)
      }
    },

    // 🔴 存檔一律排隊（2026-09-24，hichan-0a 查到的產品競態）：
    //    自動存檔（1.5 秒防抖）在途時使用者按「儲存」、或切換案件／結案／附件操作前先存 ⇒ 兩次同時在途，
    //    第二次帶的 base 是第一次送出前的 _segBase（第一次回來才更新）⇒ 伺服器分段比對 409「已被他人更新」，
    //    而他人就是自己。
    //    ⇒ 在途時再呼叫**不另外送**，只標記「再存一次」並拿同一個 promise；前一次成功、基準更新之後，
    //       用最新的基準再送一次。某一次失敗（409／驗證不過）就停，不自動重送（交給使用者處理）。
    //    呼叫端 `await saveCaseRecord()` 會等到佇列清空。
    saveCaseRecord() {
      if (this._saveRun) {
        this._saveAgain = true
        return this._saveRun
      }
      this._saveRun = (async () => {
        try {
          let ok
          do {
            this._saveAgain = false
            ok = await this._saveCaseRecordOnce()
          } while (ok && this._saveAgain)
        } finally {
          this._saveRun = null
        }
      })()
      return this._saveRun
    },
    _saveRun: null,
    _saveAgain: false,

    async _saveCaseRecordOnce() {
      if (!this.selected) return false
      if (Object.keys(this.badNum).length) {
        // N14：標紅的數字欄位（無法辨識）存在時不送——送出去的是上一個有效值，畫面卻寫著別的字
        this.saveStatus = 'error'
        this.saveMsg = '有數字欄位無法辨識（標紅處），請修正後再存檔'
        return false
      }
      if (this.cr.dealTag === '已結案' && !this.selected.case_semi_unlocked) {
        // 已結案且未解鎖：後端會直接 403，這裡先擋下避免每次 @input 觸發的
        // 防抖自動存檔都跑一趟網路請求、又跳出令人困惑的「儲存失敗」。
        this.dirty = false
        this.saveStatus = 'error'
        this.saveMsg = '案件已結案並鎖定，請先解鎖'
        return false
      }
      // 驗證：已收款項必須填入收款日期
      const payItems = this.cr.caseRecord.payment?.items || []
      for (const item of payItems) {
        if (item.received && !item.receivedAt) {
          this.saveStatus = 'error'
          this.saveMsg = `${item.type || '款項'}：已標記收款但未填入收款日期，請補填`
          return false
        }
      }
      // CM1：只送改到的分段；快照在送出前取，存檔途中又改的部分下一次再送
      const sent = this._snapSegments(this.cr.caseRecord)
      const segments = {}
      const base = {}
      const defaults = {}
      for (const k of new Set([...Object.keys(sent), ...Object.keys(this._segBase)])) {
        if (sent[k] === this._segBase[k]) continue
        // CM14b：唯讀（非成員出納）只送收款——ensureCaseRecord 對既有分段補的欄位不是他的改動，
        // 送出去整筆會被後端 403
        if (this.caseReadOnly() && k !== 'payment') continue
        if (this._segBase[k] === undefined && sent[k] === this._segFill[k]) {
          defaults[k] = JSON.parse(sent[k])
          continue
        }
        segments[k] = sent[k] === undefined ? null : JSON.parse(sent[k])
        base[k] = this._segBase[k] === undefined ? null : JSON.parse(this._segBase[k])
      }
      let ok = false
      this.saving = true
      try {
        const r = await fetch('/api/quotations/' + this.selected.quote_no + '/case-record', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ segments, base, defaults })
        })
        if (r.ok) {
          ok = true
          this.dirty = false
          this.segConflict = null
          const res = await r.json().catch(() => ({}))
          if (res.pending) {
            // 已結案案件半解鎖期間：此次存檔不會立即生效，已排隊等最高管理員審核
            // （見 backend/routers/quotations.py::_gate_case_edit()）。
            this.saveStatus = 'dirty'
            this.saveMsg = '已送出，待最高管理員審核後套用'
            this.saving = false
            return true
          }
          for (const k of Object.keys(segments)) {
            if (sent[k] === undefined) delete this._segBase[k]
            else this._segBase[k] = sent[k]
          }
          const adopted = res.adopted || {}
          for (const k of Object.keys(defaults)) {
            delete this._segFill[k]
            if (!(k in adopted)) { this._segBase[k] = sent[k]; continue }
            // 別人先存了這一段：改用資料庫的值（我這邊只是預設值；存檔途中已被改動就留著當改動）
            this._segBase[k] = JSON.stringify(adopted[k])
            if (JSON.stringify(this.cr.caseRecord[k]) === sent[k]) this.cr.caseRecord[k] = adopted[k]
          }
          const conflicts = res.stockConflicts || []
          if (conflicts.length) {
            // 序號已登載到案件，但庫存系統裡這些序號其實卡在別的狀態（已出貨/已安裝於
            // 別案件等）——不擋存檔，但要讓使用者看到，不然庫存跟案件記錄會無聲分岔
            this.saveStatus = 'dirty'
            this.saveMsg = `已儲存，但 ${conflicts.length} 個序號庫存狀態衝突（${conflicts.map(c => c.sn + ':' + c.stockStatus).join('、')}）`
          } else {
            this.saveStatus = 'saved'
            this.saveMsg = '已儲存'
            this.flashSaved('case')
            setTimeout(() => { if (!this.dirty) { this.saveStatus = ''; this.saveMsg = '' } }, 2000)
          }
          // 收款／階段等改動會影響五關，總覽跟著更新
          this.loadCaseHealth(this.selected?.quote_no)
          // 款項明細（勾已收款/實收金額/手續費）就是在這支存的，財務 Tab 的
          // 應收應付總覽必須跟著重算，否則會停在存檔前的舊數字
          this.loadFinanceSummary(this.selected?.quote_no)
        } else {
          // 2026-09-24：顯示後端給的原因（例如已收款期別不可刪除），不再只寫「儲存失敗」
          const err = await r.json().catch(() => ({}))
          this.saveStatus = 'error'
          if (r.status === 409 && err.detail?.code === 'segment_conflict') {
            // 不重試、不合併：讓使用者選「重新載入」或「保留我的變更再試」
            this.segConflict = err.detail.segments || []
            this.saveMsg = `這個案件的〈${this.segConflict.map(k => this._segLabel(k)).join('、')}〉已被他人更新`
          } else {
            this.saveMsg = typeof err.detail === 'string' && err.detail ? '儲存失敗：' + err.detail : '儲存失敗'
          }
        }
      } catch {
        this.saveStatus = 'error'
        this.saveMsg = '網路錯誤'
      }
      this.saving = false
      return ok
    },

    // 本地日期字串（YYYY-MM-DD），不要用 new Date().toISOString().slice(0,10)——
    // toISOString() 是 UTC 時間，台灣 UTC+8 在本地每天 00:00–08:00 之間會被
    // 誤判成前一天（比照 static/sidebar.js::_localISOString() 同款修法）。
    _localDateStr(d) {
      d = d || new Date()
      const tz = d.getTimezoneOffset() * 60000
      return new Date(d.getTime() - tz).toISOString().slice(0, 10)
    },

    // 2026-08-31（財務/出納權限分工）：是否具備指定模組——session.modules 是
    // 登入當下 /api/auth/login、/api/auth/me 回傳的已解析陣列（不是 JSON 字串）。
    hasModule(key) {
      return (this.session.modules || []).includes(key)
    },

    canMarkPayment() {
      return ['superadmin', 'admin'].includes(this.session.role) || this.hasModule('cashier')
    },

    // ── Modal 誤觸關閉保護（2026-08-31 新增）：backdrop 點外面／Esc／× 這三個
    // 「容易誤觸」的關閉路徑，改成先跳原生 confirm() 警示，取消就留在原本
    // 填寫到一半的頁面，不會直接歸零關閉；表單底部明確標示「取消」的按鈕
    // 維持原樣不用二次確認（那本來就是使用者主動放棄的明確意圖）。
    // 2026-09-24（CM12 P4）：這 6 個視窗是 x-show，隱藏時 @keydown.escape.window 仍在監聽 ⇒ 在頁面
    // 任何地方按 Esc 都會連問最多 6 次「表單尚未儲存」。原生 confirm 被 e2e 自動按掉所以沒被看見；
    // 下面每個 close*ModalGuarded 先確認自己的視窗真的開著才問。
    async _confirmDiscardForm() {
      return MotrixUI.confirm('表單尚未儲存，確定要關閉嗎？目前輸入的內容將會遺失。')
    },
    async closeDispatchModalGuarded() {
      if (!this.showDispatchModal) return
      if ((await this._confirmDiscardForm())) this.showDispatchModal = false
    },
    async closeWriteoffModalGuarded() {
      if (!this.writeoffModal.open) return
      if ((await this._confirmDiscardForm())) this.writeoffModal.open = false
    },
    async closeShippingModalGuarded() {
      if (!this.showShippingModal) return
      if ((await this._confirmDiscardForm())) this.showShippingModal = false
    },
    async closePayVoucherModalGuarded() {
      if (!this.payVoucherModal) return
      if ((await this._confirmDiscardForm())) this.payVoucherModal = false
    },
    async closeCreateVoucherModalGuarded() {
      if (!this.createVoucherModal) return
      if ((await this._confirmDiscardForm())) this.createVoucherModal = false
    },
    async closeInvoiceVoucherModalGuarded() {
      if (!this.ivCreateModal) return
      if ((await this._confirmDiscardForm())) this.closeInvoiceVoucherModal()
    },

    // ── 附件（回簽/已開立檔案）共用 helper ──────────────────────────────────
    // 點擊即時在新分頁開啟（瀏覽器原生顯示圖片/PDF），不用另外刻預覽元件；
    // 連結需要簽名短效 token 才能通過 /api/uploads 的存取檢查。
    async previewAttachmentFile(file) {
      try {
        const r = await fetch(`/api/photo-token?path=${encodeURIComponent(file.path)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert('取得檔案連結失敗'); return }
        const { token } = await r.json()
        window.open(`/api/uploads/${file.path}?pt=${encodeURIComponent(token)}`, '_blank')
      } catch (e) { alert('開啟檔案失敗：' + e.message) }
    },

    logout() {
      fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + (this.session.token || '') } }).catch(() => {})
      localStorage.removeItem('motrix_session'); location.href = 'login.html'
    },

    // CM12 P2：切換案件時重設本模組的案件層級狀態（時點見 core 的 _resetCaseScoped）
    _reset_core(phase, data) {
      if (phase === 'early') {
        // 分頁/檢視狀態必須在任何 await 之前就重設完（2026-09-09 修）：
        // this.selected 一設定，分頁列就立刻渲染給使用者點；但下面
        // _seedDefaultStagesIfEmpty() 對全新案件會連打 5 次建立階段的 API，
        // 這段期間如果使用者已經切到別的分頁（例如「財務」），原本寫在 await
        // 之後的 activeTab='biz' 會把人硬彈回「案件資訊」——階段建立越慢、
        // 被彈回的機率越高。這幾個都是純檢視狀態，提前重設沒有副作用。
        this.activeTab = 'biz'
        // 深連結 ?tab=：只在載入後第一次選案件時套用，之後切案件維持回到「案件資訊」
        if (this._pendingUrlTab) { this.activeTab = this._pendingUrlTab; this._pendingUrlTab = null }
        this.execSubTab = 'progress'
        // CM8（2026-09-24）：延後載入（點分頁才載）的清單也屬於「必須在 await 之前重設完」那一類——
        // 下面 _seedDefaultStagesIfEmpty() 期間使用者就可能點開財務／承攬商／動態；重設若放在
        // await 之後，會把那次已載好的資料清掉、又重載一次（e2e 量到過整組請求發兩次）。
        this._tabLoaded = {}
        this.cr.dealTag = data.data?.dealTag || data.deal_tag || '已成案'
        this.cr.caseRecord = data.data?.caseRecord || null
        // 基準取伺服器原值（ensureCaseRecord 補上的預設分段會被當成改動送出）
        this._segBase = this._snapSegments(data.data?.caseRecord)
        this.segConflict = null
        this.badNum = {}
      }
      if (phase === 'late') {
        this.dirty = false
        this.saveStatus = ''
        this.saveMsg = ''
        this.showLog = false
      }
    },
}))
