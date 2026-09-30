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
      } catch (e) { this.error = e.message }
      this.loaded = true
    },
    async selectTab(key) {
      this.tab = key
      if (key === 'engine_drafts') await this.engLoad()
      if (key === 'tax401') await this.taxLoad()
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
    async taxExport() {
      const t = this.tax
      t.error = ''
      try {
        const r = await fetch('/api/ledger/tax401/export?year=' + encodeURIComponent(t.year) + '&period=' + encodeURIComponent(t.period),
          { headers: { Authorization: 'Bearer ' + (this._session().token || '') } })
        if (!r.ok) { let d = {}; try { d = await r.json() } catch (e) { d = {} } throw new Error(typeof d.detail === 'string' ? d.detail : '匯出失敗（' + r.status + '）') }
        const url = URL.createObjectURL(await r.blob())
        const a = document.createElement('a')
        a.href = url
        a.download = '營業稅401_' + t.year + '年第' + t.period + '期.xlsx'
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
        t.notice = '已產生稅額結轉草稿 ' + r.voucher_no + '（應實繳 ' + this.fmt(r.payable) + '、新留抵 ' + this.fmt(r.carry_new) + '）；請到傳票頁送審過帳。'
        await this.taxLoad()
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
