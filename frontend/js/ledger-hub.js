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

    _initDone: false,
    async init() {
      if (this._initDone) return
      this._initDone = true
      this.isSuper = this._session().role === 'superadmin'
      await this.load()
    },
    _session() {
      try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) { return {} }
    },
    async _api(method, path, body) {
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
      } catch (e) { this.error = e.message }
      this.loaded = true
    },
    async toggle(f) {
      this.error = ''
      this.notice = ''
      try {
        await this._api('PUT', '/api/ledger/features/' + encodeURIComponent(f.key), { enabled: !f.enabled })
        this.notice = f.label + (f.enabled ? ' 已關閉' : ' 已開啟')
        await this.load()
      } catch (e) { this.error = e.message }
    },
  }
}
