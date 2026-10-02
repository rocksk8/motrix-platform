/* remit-kinds-settings.js — 匯款款別設定頁（31-B S0；最高管理者）
 * 款別放在定義文件庫（kind＝remit_kinds、key＝default）：草稿／驗證／發布／差異／版本／還原全走既有 /api/definitions/remit_kinds/default/…；
 * 目前生效的完整定義（含停用）讀 GET /api/remit-kinds/definition。伺服器端驗證為準，前端只把 [{path,message}] 列出來。
 * 規則（頁面上也寫給使用者看）：代碼建立後不能改、款別不能刪只能停用；改了只影響之後新開的匯款申請。 */
function remitKindsPage() {
  var KIND = 'remit_kinds', KEY = 'default'
  var BASE = '/api/definitions/' + KIND + '/' + KEY
  var CODE_RE = /^[a-z][a-z0-9_]{1,39}$/
  function clone(x) { return JSON.parse(JSON.stringify(x === undefined ? null : x)) }
  return {
    _initDone: false, loading: true, body: { kinds: [] }, meta: null, stages: [], savedCodes: [], isDefault: true, version: 0,
    problems: [], msg: '', err: '', busy: false, note: '', changes: null,

    _hdr: function () {
      var s = {}
      try { s = JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) {}
      return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + (s.token || '') }
    },
    async _call(method, url, payload) {
      var r = await fetch(url, { method: method, headers: this._hdr(), body: payload === undefined ? undefined : JSON.stringify(payload) })
      var d = await r.json().catch(function () { return null })
      return { ok: r.ok, status: r.status, data: d }
    },
    _fail: function (res, fallback) {
      var d = res.data || {}
      this.problems = Array.isArray(d.problems) ? d.problems : []
      this.err = d.detail ? String(d.detail) : (fallback + '（' + res.status + '）')
    },
    async init() {
      if (this._initDone) return                       // <body> 的 x-init 與 Alpine 自動呼叫 ⇒ 不守衛會跑兩遍
      this._initDone = true
      await this.reload()
    },
    async reload() {
      this.loading = true; this.err = ''
      try {
        var cur = await this._call('GET', '/api/remit-kinds/definition')
        if (!cur.ok) { this._fail(cur, '讀取失敗'); return }
        this.stages = cur.data.stages || []
        this.isDefault = !!cur.data.isDefault; this.version = cur.data.version
        var m = await this._call('GET', BASE)
        this.meta = m.ok ? m.data : { versions: [] }
        var src = (this.meta && this.meta.draft && this.meta.draft.body) || cur.data.body
        this.body = clone(src)
        // 已存在的代碼（目前生效版＋草稿以外的所有已發布版）：不能改、不能刪
        var codes = {}
        ;((cur.data.body || {}).kinds || []).forEach(function (k) { codes[k.code] = true })
        ;(this.meta.versions || []).forEach(function () { /* 版本列表不含內容；已發布過的代碼由伺服器驗證器擋「移除」 */ })
        this.savedCodes = Object.keys(codes)
        this.body.kinds.forEach(function (k) { if (!Array.isArray(k.stages)) k.stages = [] })
        this.problems = []
      } catch (e) { this.err = '網路連線失敗，請重新整理' } finally { this.loading = false }
    },
    get hasDraft() { return !!(this.meta && this.meta.draft) },
    isSaved: function (k) { return this.savedCodes.indexOf(k.code) >= 0 },
    stageOn: function (k, s) { return (k.stages || []).indexOf(s) >= 0 },
    toggleStage: function (k, s) {
      var i = k.stages.indexOf(s)
      if (i >= 0) k.stages.splice(i, 1); else k.stages.push(s)
      var order = this.stages.map(function (x) { return x.key })
      k.stages.sort(function (a, b) { return order.indexOf(a) - order.indexOf(b) })       // 依流程順序存，差異才看得懂
    },
    addKind: function () {
      var n = this.body.kinds.length
      this.body.kinds.push({ code: '', name: '', active: true, sort: (n + 1) * 10, stages: [], note: '' })
    },
    removeNew: function (k) { var i = this.body.kinds.indexOf(k); if (i >= 0 && !this.isSaved(k)) this.body.kinds.splice(i, 1) },
    codeProblem: function (k) {
      if (this.isSaved(k)) return ''
      if (!k.code) return '代碼必填（建立後不能改）'
      if (!CODE_RE.test(k.code)) return '代碼只能用小寫英文、數字與底線（英文開頭，2～40 字）'
      if (this.body.kinds.filter(function (x) { return x.code === k.code }).length > 1) return '代碼重複'
      return ''
    },
    pathLabel: function (p) {
      var self = this
      return String(p || '（整份）').replace(/kinds\[(\d+)\]/, function (m, i) {
        var k = (self.body.kinds || [])[+i]
        return '款別「' + ((k && (k.name || k.code)) || ('#' + (+i + 1))) + '」'
      })
    },
    async validate() {
      this.err = ''; this.msg = ''
      var r = await this._call('POST', BASE + '/validate', { body: this.body })
      if (!r.ok) { this._fail(r, '驗證失敗'); return false }
      this.problems = ((r.data || {}).problems || []).map(function (p) { return typeof p === 'string' ? { path: '', message: p } : p })
      this.msg = this.problems.length ? '' : '驗證通過'
      return this.problems.length === 0
    },
    async saveDraft() {
      if (this.busy) return
      this.err = ''; this.msg = ''; this.busy = true
      try {
        var r = await this._call('PUT', BASE + '/draft', { body: this.body })
        if (!r.ok) { this._fail(r, '儲存失敗'); return }
        var probs = ((r.data || {}).problems || []).map(function (p) { return typeof p === 'string' ? { path: '', message: p } : p })
        await this.reload()
        this.problems = probs
        this.msg = '草稿已儲存' + (probs.length ? '（還有 ' + probs.length + ' 項待修，見下方）' : '')
      } catch (e) { this.err = '網路連線失敗，請確認後再按一次' } finally { this.busy = false }
    },
    async publish() {
      if (this.busy) return
      this.err = ''; this.msg = ''; this.busy = true
      try {
        var s = await this._call('PUT', BASE + '/draft', { body: this.body })
        if (!s.ok) { this._fail(s, '儲存失敗'); return }
        var r = await this._call('POST', BASE + '/publish', { note: this.note })
        if (!r.ok) { this._fail(r, '發布失敗'); return }
        this.note = ''
        await this.reload()
        this.msg = '已發布第 ' + r.data.version + ' 版（只影響之後新開的匯款申請）'
      } catch (e) { this.err = '網路連線失敗，請確認後再按一次' } finally { this.busy = false }
    },
    async discardDraft() {
      if (this.busy || !this.hasDraft) return
      this.busy = true
      try {
        var r = await this._call('DELETE', BASE + '/draft')
        if (!r.ok) { this._fail(r, '丟棄草稿失敗'); return }
        await this.reload()
        this.msg = '草稿已丟棄，回到目前生效的版本'
      } finally { this.busy = false }
    },
    async showChanges() {
      this.err = ''
      var a = (this.meta && this.meta.latest) ? 'latest' : 'default'
      var r = await this._call('GET', BASE + '/diff?a=' + a + '&b=draft')
      if (!r.ok) { this._fail(r, '讀取差異失敗'); return }
      this.changes = r.data.changes || []
    },
    async restore(v) {
      if (this.busy) return
      this.busy = true; this.err = ''
      try {
        var r = await this._call('POST', BASE + '/restore/' + v, { note: '還原第 ' + v + ' 版' })
        if (!r.ok) { this._fail(r, '還原失敗'); return }
        await this.reload()
        this.msg = '已把第 ' + v + ' 版還原為第 ' + r.data.version + ' 版'
      } finally { this.busy = false }
    }
  }
}
