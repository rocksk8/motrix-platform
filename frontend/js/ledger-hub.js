// 總帳作業（功能旗標中樞）。各批功能（分錄草稿、存貨成本、營業稅 401、固定資產、發票折讓…）完成一項就開一項旗標，
// 頁籤自動出現；之後各批只改 accounting 模組的程式與這個頁面的頁籤內容，不需要再新增選單或全域設定。

function ledgerHubPage() {
  return {
    loaded: false,
    error: '',
    notice: '',
    features: [],
    tab: '',
    isSuper: false,

    // 來源憑證補登（source_annotations）
    an: { items: [], truncated: false, drafts: {}, busy: false, error: '', notice: '' },
    // 扣繳清單（C5：withholding）
    wh: { ym: '', data: null, selected: {}, date: '', voucherNo: '', unremitReason: '', busy: false, error: '', notice: '' },
    // 營業稅 401（C5：tax401）
    tax: { year: new Date().getFullYear(), period: Math.ceil((new Date().getMonth() + 1) / 2), data: null, busy: false, error: '', notice: '' },
    // 分錄草稿（C1：engine_drafts）
    eng: { start: '', end: '', events: [], counts: {}, selected: {}, run: null, busy: false, error: '', notice: '', results: null, filter: '' },

    _initDone: false,
    async init() {
      if (this._initDone) return
      this._initDone = true
      this.isSuper = this._session().role === 'superadmin'
      const t = new Date()
      const pad = n => String(n).padStart(2, '0')
      this.eng.start = t.getFullYear() + '-01-01'
      this.eng.end = t.getFullYear() + '-' + pad(t.getMonth() + 1) + '-' + pad(new Date(t.getFullYear(), t.getMonth() + 1, 0).getDate())
      await this.load()
    },
    _session() {
      try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) { return {} }
    },
    async _api(verb, path, body) {
      const method = typeof verb === 'string' ? verb : verb.method
      const opt = { method, headers: { Authorization: 'Bearer ' + (this._session().token || ''), 'Content-Type': 'application/json' } }
      if (body !== undefined) opt.body = JSON.stringify(body)
      const r = await fetch(path, opt)
      let data = {}
      try { data = await r.json() } catch (e) { data = {} }
      if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : (r.status === 403 ? '沒有權限執行這個動作' : '操作失敗（' + r.status + '）'))
      return data
    },
    get enabled() { return this.features.filter(f => f.enabled) },
    current() { return this.features.find(f => f.key === this.tab) },

    async load() {
      this.error = ''
      try {
        this.features = (await this._api('GET', '/api/ledger/features')).features
        if (!this.enabled.some(f => f.key === this.tab)) this.tab = this.enabled.length ? this.enabled[0].key : ''
        if (this.tab === 'engine_drafts') await this.engLoad()
        if (this.tab === 'tax401') await this.taxLoad()
        if (this.tab === 'withholding') await this.whLoad()
        if (this.tab === 'source_annotations') await this.anLoad()
      } catch (e) { this.error = e.message }
      this.loaded = true
    },
    async selectTab(key) {
      this.tab = key
      if (key === 'engine_drafts') await this.engLoad()
      if (key === 'tax401') await this.taxLoad()
      if (key === 'withholding') await this.whLoad()
      if (key === 'source_annotations') await this.anLoad()
    },
    async anLoad() {
      const a = this.an
      a.error = ''
      a.busy = true
      try {
        const d = await this._api('GET', '/api/ledger/annotations/pending')
        a.items = d.items
        a.truncated = d.truncated
        const dr = {}
        d.items.forEach(i => { dr[i.source_type + '|' + i.source_key] = { tax: i.input_tax, date: i.invoice_date } })
        a.drafts = dr
      } catch (e) { a.error = e.message; a.items = [] }
      a.busy = false
    },
    anKey(i) { return i.source_type + '|' + i.source_key },
    anKind(k) { return ({ estimated: '稅額為估計', unsplit: '來源未拆稅', annotated: '已補登' })[k] || k },
    async anSave(i) {
      const a = this.an
      a.error = ''
      a.notice = ''
      const d = a.drafts[this.anKey(i)] || {}
      const hasTax = String(d.tax === undefined ? '' : d.tax).trim() !== ''
      const hasDate = !!i.can_date && String(d.date || '').trim() !== ''
      if (!hasTax && !hasDate) { a.error = '請至少填入進項稅額' + (i.can_date ? '或發票日期' : ''); return }        // 兩格都空：不送、不顯示「已補登」
      let wrote = false
      try {
        if (hasTax) { await this._api({ method: 'PUT' }, '/api/ledger/annotations', { source_type: i.source_type, source_key: i.source_key, field: 'input_tax', value: String(d.tax) }); wrote = true }
        if (hasDate) { await this._api({ method: 'PUT' }, '/api/ledger/annotations', { source_type: i.source_type, source_key: i.source_key, field: 'invoice_date', value: d.date }); wrote = true }
        a.notice = '已補登 ' + i.source_key + '；下次執行「分錄草稿」時套用（草稿會重建，已過帳的會產生反向草稿與新草稿）。'
        await this.anLoad()
      } catch (e) {
        const msg = e.message
        if (wrote) { await this.anLoad(); a.error = '部分已補登（' + i.source_key + '），另一項失敗：' + msg }        // 部分成功後重讀，畫面與資料一致
        else a.error = msg
      }
    },
    async anClear(i) {
      const a = this.an
      a.error = ''
      a.notice = ''
      try {
        for (const id of [i.input_tax_id, i.invoice_date_id]) { if (id) await this._api({ method: 'DELETE' }, '/api/ledger/annotations/' + id) }
        a.notice = '已清除 ' + i.source_key + ' 的補登，之後回到來源值。'
        await this.anLoad()
      } catch (e) { a.error = e.message }
    },
    async whLoad() {
      const w = this.wh
      w.error = ''
      w.busy = true
      try {
        w.data = await this._api('GET', '/api/ledger/withholding' + (w.ym ? '?ym=' + encodeURIComponent(w.ym) : ''))
        w.selected = {}
      } catch (e) { w.error = e.message; w.data = null }
      w.busy = false
    },
    whIds() { return this.wh.data ? this.wh.data.items.filter(i => this.wh.selected[i.id] && !i.remitted_at).map(i => i.id) : [] },
    whKindLabel(k) { return k === 'income_tax' ? '代扣所得稅' : (k === 'nhi' ? '二代健保補充保費' : k) },
    async whRemit() {
      const w = this.wh
      w.error = ''
      w.notice = ''
      const ids = this.whIds()
      if (!ids.length) { w.error = '請先勾選尚未繳庫的項目'; return }
      if (!w.date) { w.error = '請填寫繳庫日'; return }
      w.busy = true
      try {
        const r = await this._api({ method: 'POST' }, '/api/ledger/withholding/remit', { ids, remitted_at: w.date, voucher_no: w.voucherNo })
        await this.whLoad()
        w.notice = r.updated ? '已登記繳庫 ' + r.updated + ' 筆' : '0 筆已登記：所選項目都已經繳庫過了'
      } catch (e) { w.error = e.message }
      w.busy = false
    },
    async whUnremit(i) {
      const w = this.wh
      w.error = ''
      w.notice = ''          // 不留上一個動作的綠色訊息
      if (!(w.unremitReason || '').trim()) { w.error = '取消繳庫要先在上方填原因'; return }
      try { await this._api({ method: 'POST' }, '/api/ledger/withholding/unremit', { ids: [i.id], reason: w.unremitReason }); await this.whLoad(); w.notice = '已取消繳庫登記（僅限最高管理者操作，已留稽核）。' } catch (e) { w.error = e.message }
    },
    async taxLoad() {
      const t = this.tax
      t.error = ''
      t.notice = ''
      t.busy = true
      try {
        t.data = await this._api('GET', '/api/ledger/tax401?year=' + encodeURIComponent(t.year) + '&period=' + encodeURIComponent(t.period))
      } catch (e) { t.error = e.message; t.data = null }
      t.busy = false
    },
    async taxExport(fmt) {
      const t = this.tax
      t.error = ''
      try {
        const r = await fetch('/api/ledger/tax401/export' + (fmt === 'pdf' ? '/pdf' : '') + '?year=' + encodeURIComponent(t.year) + '&period=' + encodeURIComponent(t.period),
          { headers: { Authorization: 'Bearer ' + (this._session().token || '') } })
        if (!r.ok) { let d = {}; try { d = await r.json() } catch (e) { d = {} } throw new Error(typeof d.detail === 'string' ? d.detail : '匯出失敗（' + r.status + '）') }
        const url = URL.createObjectURL(await r.blob())
        const a = document.createElement('a')
        a.href = url
        a.download = '營業稅401_' + t.year + '年第' + t.period + '期' + (fmt === 'pdf' ? '.pdf' : '.xlsx')
        a.click()
        URL.revokeObjectURL(url)
      } catch (e) { t.error = e.message }
    },
    async taxSettle() {
      const t = this.tax
      t.error = ''
      t.notice = ''
      t.busy = true
      try {
        const r = await this._api({ method: 'POST' }, '/api/ledger/tax401/settlement', { year: t.year, period: t.period })
        await this.taxLoad()          // 先重讀再設訊息：taxLoad() 開頭會清掉訊息
        t.notice = '已產生稅額結轉草稿 ' + r.voucher_no + '（應實繳 ' + this.fmt(r.payable) + '、新留抵 ' + this.fmt(r.carry_new) + '）；請到傳票頁送審過帳。'
      } catch (e) { t.error = e.message }
      t.busy = false
    },
    statusLabel(st) {
      return ({ drafted: '草稿待確認', posted: '已過帳', drift: '來源已變動', reversed: '已沖轉', superseded: '已被新版取代', orphan: '來源已消失',
        rejected: '已被作廢', native: '既有傳票（不重複產生）', blocked_closed: '期間已結帳（擋下）', blocked_no_account: '缺科目（擋下）', blocked_inventory: '在庫不足（擋下）' })[st] || st
    },
    fmt(n) { return (n || 0).toLocaleString('zh-TW') },
    engBad(e) { return ['drift', 'orphan', 'blocked_closed', 'blocked_no_account', 'blocked_inventory'].indexOf(e.status) >= 0 },
    async engLoad() {
      const g = this.eng
      g.error = ''
      try {
        const d = await this._api('GET', '/api/ledger/engine/events' + (g.filter ? '?status=' + encodeURIComponent(g.filter) : ''))
        g.events = d.events
        g.counts = d.counts
        g.selected = {}
      } catch (e) { g.error = e.message }
    },
    async engRun() {
      const g = this.eng
      g.error = ''
      g.notice = ''
      g.busy = true
      try {
        g.run = await this._api({ method: 'POST' }, '/api/ledger/engine/run', { start: g.start, end: g.end })
        g.notice = '掃描 ' + g.run.stats.scanned + ' 筆事件：新增草稿 ' + g.run.stats.created + '、來源變動 ' + g.run.stats.drift + '、擋下 ' + g.run.stats.blocked
        await this.engLoad()
      } catch (e) { g.error = e.message }
      g.busy = false
    },
    engSelectedIds() {
      const g = this.eng
      return g.events.filter(e => g.selected[e.id] && e.voucher_id).map(e => e.voucher_id)
    },
    engToggleAll(on) {
      const g = this.eng
      const sel = {}
      if (on) g.events.forEach(e => { if (e.voucher_id && e.status !== 'native' && e.voucher_status && e.voucher_status !== '已過帳') sel[e.id] = true })
      g.selected = sel
    },
    async engBatch(action) {
      const g = this.eng
      const ids = this.engSelectedIds()
      g.error = ''
      g.notice = ''
      g.results = null
      if (!ids.length) { g.error = '請先勾選要處理的草稿'; return }
      g.busy = true
      try {
        const r = await this._api({ method: 'POST' }, '/api/ledger/engine/batch', { voucher_ids: ids, action })
        g.results = r
        g.notice = '整批完成：成功 ' + r.ok + '、失敗 ' + r.failed
        await this.engLoad()
      } catch (e) { g.error = e.message }
      g.busy = false
    },

    async toggle(f) {
      this.error = ''
      this.notice = ''
      try {
        await this._api({ method: 'PUT' }, '/api/ledger/features/' + encodeURIComponent(f.key), { enabled: !f.enabled })
        this.notice = f.label + (f.enabled ? ' 已關閉' : ' 已開啟')
        await this.load()
      } catch (e) { this.error = e.message }
    },
  }
}
