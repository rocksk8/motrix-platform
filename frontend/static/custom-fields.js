/* custom-fields.js — 內建畫面的自訂欄位（T61 S5；設計：docs/platform/plans/T61-S5-FIELD-CATALOG-DESIGN.md）。
 *
 * 兩部分，同一個檔：
 * ① 執行時（Alpine store 'cf'）：頁面啟動時 `MotrixCustomFields.init({ recordType: 'case_info' })` 讀 GET /api/custom-fields/<類型>
 *    ⇒ { enabled, fields }。旗標關閉 ⇒ enabled=false、fields=[]，頁面什麼都不畫（唯一多出的動作就是這一個 GET）。
 *    頁面用 `$store.cf.enabled` 決定畫不畫「自訂欄位」區塊，用 `$store.cf.list()` 取欄位（編輯器開啟時＝草稿，其餘＝已發布）。
 * ② 欄位編輯器（僅超級管理員；旗標開啟才掛上）：側邊面板，新增／改名／排序／停用欄位，草稿即時畫在頁面上（預覽），
 *    存草稿、看差異、發布、版本還原；發布與還原前先在頁內兩段式確認（不用原生對話框）；治理旗標開啟時放寬的發布會回
 *    {pending:true}，面板如實說「已送出，待第二位最高管理者核准」。發布走 /api/definitions/custom_fields/<類型>/…（既有定義文件庫）。
 *
 * 第一版型別：文字、日期、單選、勾選（沒有金額、數字、必填、預設值）。欄位只給內部人員看，不進客戶版文件。
 * e2e 等待點：#cf-editor 的 data-busy（'0'／'1'）與 data-state（idle／saved／problems／published／restored／pending）。
 */
;(function () {
  var cfg = null
  var TYPES = [['text', '文字'], ['date', '日期'], ['select', '單選'], ['checkbox', '勾選']]

  function session() { try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) { return {} } }
  function headers() { return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + (session().token || '') } }
  function clone(x) { return JSON.parse(JSON.stringify(x)) }
  function S() { return (window.Alpine && window.Alpine.store && window.Alpine.store('cf')) || raw }

  var raw = {
    recordType: '', loaded: false, failed: false, error: '', enabled: false,
    fields: [],              // 已發布、未停用的欄位（目前使用者看到的）
    view: null,              // 編輯器開啟時＝草稿欄位
    mode: 'live', previewLabel: '',
    /** 頁面要畫的欄位。 */
    list: function () { return this.view || this.fields },
  }

  async function load() {
    var s = S()
    try {
      var r = await fetch('/api/custom-fields/' + encodeURIComponent(cfg.recordType), { headers: headers() })
      if (!r.ok) throw new Error('HTTP ' + r.status)
      var d = await r.json()
      s = S()
      s.enabled = d.enabled === true
      s.fields = Array.isArray(d.fields) ? d.fields : []
      s.failed = false
      s.error = ''
      s.loaded = true
      if (s.enabled && session().role === 'superadmin') mountEditor()
    } catch (e) {
      s = S()
      s.failed = true
      s.enabled = false
      s.error = '自訂欄位載入失敗（' + (e && e.message || e) + '）'
    }
  }

  // ── 編輯器 ─────────────────────────────────────────────────────────────
  var CSS = [
    '[x-cloak]{display:none!important}',
    '#cf-editor{position:fixed;top:0;right:0;bottom:0;width:400px;z-index:1200;background:var(--bg-card,#fff);',
    'border-left:1px solid var(--border-light,#ddd);box-shadow:-8px 0 24px rgba(0,0,0,.08);display:flex;flex-direction:column;font-size:12px}',
    '#cf-editor .cf-head{padding:12px 14px;border-bottom:1px solid var(--border-light,#ddd);display:flex;flex-direction:column;gap:8px}',
    '#cf-editor .cf-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}',
    '#cf-editor .cf-body{flex:1;overflow:auto;padding:10px 14px}#cf-editor .cf-foot{padding:10px 14px;border-top:1px solid var(--border-light,#ddd)}',
    '#cf-editor .cf-sub{color:var(--text-dim,#888);font-size:11px}#cf-editor .cf-h{font-weight:600;margin:8px 0 4px}',
    '#cf-editor .cf-item{border:1px solid var(--border-light,#e5e5e5);border-radius:6px;padding:6px 8px;margin:6px 0;background:var(--bg,#fafafa)}',
    '#cf-editor .cf-item.is-off{opacity:.55}#cf-editor .cf-item.is-bad{border-color:var(--danger,#dc2626);background:var(--danger-light,#fef2f2)}',
    '#cf-editor input[type=text],#cf-editor select,#cf-editor textarea{font-size:12px;padding:2px 6px;border:1px solid var(--border-light,#ddd);border-radius:4px}',
    '#cf-editor .cf-item input[type=text]{flex:1;min-width:0}#cf-editor button.cf-b{border:1px solid var(--border-light,#ddd);background:none;border-radius:4px;cursor:pointer;padding:0 6px}',
    '#cf-editor .cf-prob{color:var(--danger,#dc2626);font-size:11px;margin-top:3px}',
    '#cf-editor .cf-banner{background:var(--warning-light,#fffbeb);color:var(--warning,#b45309);padding:6px 8px;border-radius:6px}',
    '#cf-editor .cf-ver{display:flex;justify-content:space-between;gap:6px;padding:3px 0;border-bottom:1px dashed var(--border-light,#eee)}',
    'body.cf-editing .app-shell,body.cf-editing .page-main{margin-right:400px}',
  ].join('')

  function tpl() {
    var typeOpts = TYPES.map(function (t) { return '<option value="' + t[0] + '">' + t[1] + '</option>' }).join('')
    return '' +
'<div id="cf-editor" x-data="MotrixCustomFields.component()" x-show="open" x-cloak :data-busy="(busy || loading) ? \'1\' : \'0\'" :data-state="state">' +
' <div class="cf-head">' +
'  <div class="cf-row" style="justify-content:space-between"><strong>自訂欄位</strong>' +
'   <button type="button" class="btn btn-ghost btn-sm" data-testid="cf-close" @click="close()">關閉</button></div>' +
'  <div class="cf-sub" x-text="\'單據類型：\' + typeLabel()"></div>' +
'  <div class="cf-sub">看得到的人：能開啟這筆單據的內部人員。欄位不會出現在報價單、客戶版文件或回簽頁。第一版只有文字、日期、單選、勾選，沒有金額。</div>' +
'  <div class="cf-banner" data-testid="cf-ask" role="alertdialog" x-show="askBar" x-cloak><span x-text="askBar && askBar.text"></span> ' +
'   <button type="button" class="btn btn-primary btn-sm" data-testid="cf-ask-yes" @click="answer(true)">確定</button> ' +
'   <button type="button" class="btn btn-ghost btn-sm" data-testid="cf-ask-no" @click="answer(false)">取消</button></div>' +
'  <div class="cf-banner" x-show="loadError" x-text="loadError"></div>' +
' </div>' +
' <div class="cf-body" x-show="!loading" x-effect="$el.inert = busy">' +
'  <div class="cf-sub" x-show="!work.length">還沒有欄位。按「新增欄位」開始；畫面上會即時出現預覽，發布之後才會讓大家看到。</div>' +
'  <template x-for="(f, i) in work" :key="f.key">' +
'   <div class="cf-item" :class="{\'is-off\': f.disabled, \'is-bad\': !!probs[i]}" :data-field-index="i">' +
'    <div class="cf-row"><input type="text" data-testid="cf-label" x-model="f.label" @input="sync()" placeholder="顯示名稱（例：現場工頭）" maxlength="30">' +
'     <button type="button" class="cf-b" title="上移" @click="mv(i, -1)">↑</button><button type="button" class="cf-b" title="下移" @click="mv(i, 1)">↓</button></div>' +
'    <div class="cf-row" style="margin-top:4px"><label>型別</label>' +
'     <select data-testid="cf-type" x-model="f.type" @change="sync()" :disabled="!isNew(f)">' + typeOpts + '</select>' +
'     <span class="cf-sub" x-show="!isNew(f)">已發布，型別不能改</span>' +
'     <label style="margin-left:auto"><input type="checkbox" x-model="f.disabled" @change="onDisable(f)"> 停用</label>' +
'     <button type="button" class="cf-b" x-show="isNew(f)" title="移除（還沒發布過）" @click="remove(i)">移除</button></div>' +
'    <div class="cf-row" style="margin-top:4px" x-show="f.type === \'select\'"><label>選項（一行一個）</label>' +
'     <textarea rows="3" style="width:100%" data-testid="cf-options" x-model="f.optionsText" @input="sync()"></textarea></div>' +
'    <div class="cf-row" style="margin-top:4px" x-show="f.type === \'text\'"><label>最多字數</label>' +
'     <input type="text" style="max-width:70px" x-model="f.maxLengthText" @input="sync()" placeholder="200"></div>' +
'    <div class="cf-row" style="margin-top:4px"><label>說明</label><input type="text" x-model="f.help" @input="sync()" maxlength="100" placeholder="（選填）填寫時顯示的提示"></div>' +
'    <div class="cf-sub" data-testid="cf-usage" x-show="!isNew(f) && usage[f.key]" x-text="\'已有 \' + usage[f.key] + \' 筆單據填了這個欄位\'"></div>' +
'    <div class="cf-prob" x-show="probs[i]" x-text="probs[i]"></div>' +
'   </div></template>' +
'  <div class="cf-row" style="margin-top:8px"><button type="button" class="btn btn-ghost btn-sm" data-testid="cf-add" @click="add()" :disabled="work.length >= max">＋ 新增欄位</button>' +
'   <span class="cf-sub" x-text="work.length + \' / \' + max"></span></div>' +
'  <div x-show="diffShown" data-testid="cf-diff"><div class="cf-h">與目前發布版的差異</div><div class="cf-sub" x-show="!diffLines.length">沒有差異。</div>' +
'   <ul><template x-for="d in diffLines"><li x-text="d"></li></template></ul></div>' +
'  <div data-testid="cf-versions"><div class="cf-h">版本</div><div class="cf-sub" x-show="!published().length">還沒有發布過。</div>' +
'   <template x-for="v in published()" :key="v.version"><div class="cf-ver" :data-version="v.version">' +
'    <span x-text="\'第 \' + v.version + \' 版 \' + (v.published_at || \'\').slice(0, 16).replace(\'T\', \' \') + (v.note ? \'・\' + v.note : \'\')"></span>' +
'    <button type="button" class="btn btn-ghost btn-sm" @click="restore(v.version)" :disabled="busy || loading">還原</button></div></template></div>' +
' </div>' +
' <div class="cf-foot"><div class="cf-row">' +
'  <button type="button" class="btn btn-ghost btn-sm" data-testid="cf-save" @click="saveDraft()" :disabled="busy || loading">存草稿</button>' +
'  <button type="button" class="btn btn-ghost btn-sm" data-testid="cf-diff-btn" @click="showDiff()" :disabled="busy || loading">看差異</button>' +
'  <button type="button" class="btn btn-primary btn-sm" data-testid="cf-publish" @click="publish()" :disabled="busy || loading">發布</button>' +
'  <button type="button" class="btn btn-ghost btn-sm" x-show="defs.draft" @click="discard()" :disabled="busy || loading">捨棄草稿</button></div>' +
'  <div class="cf-row" style="margin-top:6px"><input type="text" data-testid="cf-note" x-model="note" placeholder="發布說明（選填）" style="flex:1"></div>' +
'  <div style="margin-top:6px" data-testid="cf-msg" x-text="msg"></div></div>' +
'</div>'
  }

  function component() {
    return {
      open: false, busy: false, loading: false, state: 'idle', msg: '', note: '', loadError: '', max: 20,
      askBar: null, _askRes: null, defs: { draft: null, latest: null, versions: [] },
      work: [], probs: {}, diffShown: false, diffLines: [], usage: {},

      _key: function () { return cfg.recordType },
      _base: function () { return '/api/definitions/custom_fields/' + encodeURIComponent(this._key()) },
      typeLabel: function () { return cfg.label || this._key() },
      async _j(url, opt) {
        var r = await fetch(url, Object.assign({ headers: headers() }, opt || {}))
        var d = await r.json().catch(function () { return {} })
        return { ok: r.ok, status: r.status, d: d }
      },

      // 兩段式確認／提示（不用原生 confirm／alert）
      _ask: function (text) {
        var self = this
        if (this._askRes) this._askRes(false)
        return new Promise(function (res) { self.askBar = { text: text }; self._askRes = res })
      },
      answer: function (ok) {
        var r = this._askRes
        this._askRes = null
        this.askBar = null
        if (r) r(!!ok)
      },

      // ── 欄位的畫面狀態 ⇄ 定義 body ──
      isNew: function (f) {
        var pub = ((this.defs.latest || {}).body || {}).fields || []
        return !pub.some(function (x) { return x.key === f.key })
      },
      _fromBody: function (body) {
        return ((body || {}).fields || []).map(function (f) {
          return { key: f.key, label: f.label || '', type: f.type || 'text', disabled: !!f.disabled, help: f.help || '',
                   optionsText: (f.options || []).join('\n'), maxLengthText: f.maxLength ? String(f.maxLength) : '' }
        })
      },
      _body: function () {
        // 只送定義認得的鍵（畫面專用的 optionsText／maxLengthText 不送）
        return { fields: this.work.map(function (f) {
          var o = { key: f.key, label: String(f.label || '').trim(), type: f.type }
          if (f.disabled) o.disabled = true
          if (String(f.help || '').trim()) o.help = String(f.help).trim()
          if (f.type === 'select') {
            var seen = {}, opts = []
            String(f.optionsText || '').split('\n').forEach(function (x) { x = x.trim(); if (x && !seen[x]) { seen[x] = 1; opts.push(x) } })
            o.options = opts
          }
          if (f.type === 'text' && String(f.maxLengthText || '').trim() !== '') o.maxLength = parseInt(f.maxLengthText, 10)
          return o
        }) }
      },
      _nextKey: function () {
        var n = 0
        this.work.forEach(function (f) { var m = /^f(\d+)$/.exec(f.key); if (m) n = Math.max(n, +m[1]) })
        return 'f' + (n + 1)
      },
      // 預覽用：已停用的欄位不畫；畫面專用欄位轉成頁面看得懂的形狀
      _view: function () {
        return this._body().fields.filter(function (f) { return !f.disabled }).map(function (f) {
          return { key: f.key, label: f.label || '（未命名）', type: f.type, options: f.options, maxLength: f.maxLength, help: f.help }
        })
      },
      // 停用前讓人知道有多少筆單據填了這個欄位（資料不會被刪，只是畫面不再顯示、也不能再改）
      onDisable: function (f) {
        this.sync()
        var n = this.usage[f.key] || 0
        if (f.disabled && n) this.msg = '「' + (f.label || f.key) + '」已有 ' + n + ' 筆單據填了；停用後畫面不再顯示、也不能再改，資料仍會保留，重新啟用就會再出現。'
      },
      async loadUsage() {
        try {
          var r = await this._j('/api/custom-fields/' + encodeURIComponent(this._key()) + '/usage')
          this.usage = (r.ok && r.d && r.d.counts) || {}
        } catch (e) { this.usage = {} }
      },
      sync: function () { if (this.open) window.MotrixCustomFields.show(this._view(), 'edit', '預覽（草稿，尚未發布）') },
      add: function () {
        if (this.work.length >= this.max) return
        this.work.push({ key: this._nextKey(), label: '', type: 'text', disabled: false, help: '', optionsText: '', maxLengthText: '' })
        this.sync()
      },
      remove: function (i) { if (this.isNew(this.work[i])) { this.work.splice(i, 1); this.probs = {}; this.sync() } },
      mv: function (i, dir) {
        var j = i + dir
        if (j < 0 || j >= this.work.length) return
        var t = this.work[i]; this.work.splice(i, 1); this.work.splice(j, 0, t)
        this.probs = {}
        this.sync()
      },
      published: function () { return (this.defs.versions || []).filter(function (v) { return v.status === 'published' }) },

      // ── 載入／開關 ──
      async start() {
        this.open = true
        document.body.classList.add('cf-editing')
        await this.load()
      },
      close() {
        if (this._askRes) { var r0 = this._askRes; this._askRes = null; this.askBar = null; r0(false) }
        this.open = false
        document.body.classList.remove('cf-editing')
        window.MotrixCustomFields.show(null)
      },
      async load() {
        this.loading = true
        this.loadError = ''
        this.probs = {}; this.diffShown = false; this.msg = ''
        try {
          var r = await this._j(this._base() + '?scope=company')
          if (!r.ok) throw new Error('HTTP ' + r.status)
          this.defs = r.d
          var src = r.d.draft ? r.d.draft.body : (r.d.latest ? r.d.latest.body : { fields: [] })
          this.work = this._fromBody(src)
          this.msg = r.d.draft ? '從草稿繼續' : (r.d.latest ? '從第 ' + r.d.latest.version + ' 版開始' : '還沒有欄位')
          this.loading = false
          this.sync()
          this.loadUsage()
        } catch (e) {
          this.loadError = '讀取欄位定義失敗（' + (e && e.message || e) + '），編輯已鎖定；關閉後再打開重試'
        }
      },

      // ── 存草稿／差異／發布／還原 ──
      _guard: async function (fn, unknown) {
        try { return await fn() }
        catch (e) { this.state = 'error'; this.msg = unknown + '（' + (e && e.message || e) + '）'; return false }
        finally { this.busy = false }
      },
      saveDraft: function () { var self = this; return this._guard(function () { return self._saveDraft() }, '存草稿失敗：連線中斷，請再按一次') },
      publish: function () { var self = this; return this._guard(function () { return self._publish() }, '發布結果不明：伺服器可能已經處理，請關閉再打開、看版本清單確認') },
      restore: function (v) { var self = this; return this._guard(function () { return self._restore(v) }, '還原結果不明：請關閉再打開、看版本清單確認') },
      discard: function () { var self = this; return this._guard(function () { return self._discard() }, '捨棄草稿結果不明：請關閉再打開確認') },
      _mark: function (problems) {
        // path 形如 fields[2].label ⇒ 標在第 2 列
        var probs = {}
        ;(problems || []).forEach(function (p) {
          var m = /^fields\[(\d+)\]/.exec(p.path || '')
          var i = m ? +m[1] : -1
          probs[i] = (probs[i] ? probs[i] + '；' : '') + p.message
        })
        this.probs = probs
        return probs
      },
      async _saveDraft() {
        this.busy = true
        var r = await this._j(this._base() + '/draft?scope=company', { method: 'PUT', body: JSON.stringify({ body: this._body() }) })
        if (!r.ok) { this.msg = '存草稿失敗：' + (r.d.detail || r.status); this.busy = false; return false }
        this._mark(r.d.problems)
        var bad = (r.d.problems || []).length
        this.state = bad ? 'problems' : 'saved'
        this.msg = bad ? '草稿已存，但有 ' + bad + ' 個問題（發布前要修正）' : '草稿已存'
        var v = await this._j(this._base() + '?scope=company')
        if (v.ok) this.defs = v.d
        this.busy = false
        return !bad
      },
      showDiff() {
        var latest = (this.defs.latest ? this.defs.latest.body.fields : []) || []
        var now = this._body().fields
        var byKey = function (a) { var o = {}; a.forEach(function (f) { o[f.key] = f }); return o }
        var a = byKey(latest), b = byKey(now), lines = []
        now.forEach(function (f) {
          if (!a[f.key]) lines.push('新增欄位「' + (f.label || f.key) + '」（' + f.type + '）')
          else {
            var o = a[f.key]
            if (o.label !== f.label) lines.push('「' + o.label + '」改名為「' + f.label + '」')
            if (!!o.disabled !== !!f.disabled) lines.push('「' + f.label + '」' + (f.disabled ? '停用' : '重新啟用'))
            if (JSON.stringify(o.options || []) !== JSON.stringify(f.options || [])) lines.push('「' + f.label + '」的選項有變')
          }
        })
        latest.forEach(function (f) { if (!b[f.key]) lines.push('移除欄位「' + f.label + '」') })
        var oa = latest.map(function (f) { return f.key }).filter(function (k) { return b[k] }).join()
        var ob = now.map(function (f) { return f.key }).filter(function (k) { return a[k] }).join()
        if (oa !== ob) lines.push('欄位順序有變')
        this.diffLines = lines
        this.diffShown = true
      },
      // 治理旗標開啟時，放寬的發布／還原不會立刻生效，後端回 {pending:true, version, effectiveAt, reasons[]}
      _pendingText: function (d, what) {
        var reasons = (d.reasons || []).map(function (x) { return typeof x === 'string' ? x : ((x && (x.message || x.text)) || '') }).filter(Boolean)
        var at = d.effectiveAt ? String(d.effectiveAt).replace('T', ' ').slice(0, 16) : ''
        return '已送出' + what + '，待第二位最高管理者核准' + (d.version ? '（第 ' + d.version + ' 版）' : '') + '；核准前不會生效'
          + (at ? '，生效時間 ' + at + ' 之後' : '') + (reasons.length ? '。原因：' + reasons.join('；') : '')
      },
      async _publish() {
        this.showDiff()
        if (!(await this._saveDraft())) return
        this.busy = true
        var v = await this._j(this._base() + '/validate', { method: 'POST', body: JSON.stringify({ body: this._body() }) })
        if (!v.ok || (v.d.problems || []).length) {
          this._mark(v.d.problems || [])
          this.msg = '有問題，沒有發布'
          this.busy = false
          return
        }
        if (!(await this._ask('發布後，所有內部人員在這個畫面就會看到這些欄位。確定要發布嗎？'))) { this.busy = false; return }
        // T62：治理旗標開時，看過的影響預覽雜湊 preview_hash 隨發布送出（管理者開啟強制時沒帶會被擋）；旗標關／未載入 ⇒ 請求本體只有 note，與先前相同
        var pubBody = { note: this.note }
        if (window.MotrixDefGovernance && await window.MotrixDefGovernance.available('custom_fields')) {
          var pvh = await window.MotrixDefGovernance.review({ kind: 'custom_fields', key: this._key(), scope: 'company', title: '發布前影響預覽' })
          if (!pvh) { this.msg = '已取消發布'; this.busy = false; return }
          pubBody.preview_hash = pvh
        }
        var r = await this._j(this._base() + '/publish?scope=company', { method: 'POST', body: JSON.stringify(pubBody) })
        if (!r.ok) { this._mark(r.d.problems || []); this.msg = '發布失敗：' + (r.d.detail || r.status); this.busy = false; return }
        this.note = ''
        var pend = r.d && r.d.pending === true
        if (!pend) await window.MotrixCustomFields.reload()
        await this.load()
        this.busy = false
        if (this.loadError) return
        if (pend) { this.msg = this._pendingText(r.d, '發布'); this.state = 'pending'; return }
        this.msg = '已發布第 ' + r.d.version + ' 版'
        this.state = 'published'
      },
      async _restore(version) {
        this.busy = true
        if (!(await this._ask('要還原第 ' + version + ' 版嗎？' + (this.defs.draft ? '目前的草稿會被捨棄。' : '')))) { this.busy = false; return }
        // T62：治理旗標開時，還原也要帶『看過這一版內容』的預覽雜湊（強制範圍內沒帶會 409）；沒有治理／取不到 ⇒ 請求本體仍是 {}
        var restBody = {}
        if (window.MotrixDefGovernance && window.MotrixDefGovernance.previewRestore && await window.MotrixDefGovernance.available('custom_fields')) {
          var rvh = await window.MotrixDefGovernance.previewRestore({ kind: 'custom_fields', key: this._key(), scope: 'company' }, version)
          if (rvh) restBody.preview_hash = rvh
        }
        var r = await this._j(this._base() + '/restore/' + version + '?scope=company', { method: 'POST', body: JSON.stringify(restBody) })
        if (!r.ok) { this._mark(r.d.problems || []); this.msg = '還原失敗：' + (r.d.detail || r.status); this.busy = false; return }
        var pend = r.d && r.d.pending === true
        if (!pend && this.defs.draft) await this._j(this._base() + '/draft?scope=company', { method: 'DELETE' })
        if (!pend) await window.MotrixCustomFields.reload()
        await this.load()
        this.busy = false
        if (this.loadError) return
        if (pend) { this.msg = this._pendingText(r.d, '還原第 ' + version + ' 版'); this.state = 'pending'; return }
        this.msg = '已把第 ' + version + ' 版還原成第 ' + r.d.version + ' 版'
        this.state = 'restored'
      },
      async _discard() {
        this.busy = true
        await this._j(this._base() + '/draft?scope=company', { method: 'DELETE' })
        await this.load()
        this.busy = false
        if (this.loadError) return
        this.msg = '草稿已捨棄'
      },
    }
  }

  function mountEditor() {
    if (document.getElementById('cf-editor')) return
    if (!document.getElementById('cf-editor-css')) {
      var st = document.createElement('style'); st.id = 'cf-editor-css'; st.textContent = CSS
      document.head.appendChild(st)
    }
    var wrap = document.createElement('div')
    wrap.innerHTML = tpl()
    document.body.appendChild(wrap.firstChild)
  }

  window.MotrixCustomFields = {
    /** 頁面啟動時呼叫一次：{ recordType, label }。讀已發布的欄位；旗標關閉 ⇒ enabled=false。 */
    init: function (c) {
      cfg = c
      raw.recordType = c.recordType
      document.addEventListener('alpine:init', function () { window.Alpine.store('cf', raw) })
      // deferred：只登記 store，不發任何請求；旗標開啟時由頁面（已經在讀設定的那一次請求裡看到旗標）呼叫 start()。
      // 旗標關閉 ⇒ 整個頁面載入期間不多打任何一個請求（OFF 的網路清單與舊版相同）。
      return c.deferred ? Promise.resolve() : load()
    },
    start: function () { return cfg ? load() : Promise.resolve() },
    reload: load,
    config: function () { return cfg },
    _state: function () { return S() },          // 測試用
    component: component,
    /** 編輯器：畫面換成草稿欄位（edit）；null ⇒ 回到已發布的。 */
    show: function (fields, mode, label) {
      var s = S()
      if (!fields) { s.mode = 'live'; s.previewLabel = ''; s.view = null; return }
      s.mode = mode || 'edit'
      s.previewLabel = label || ''
      s.view = fields
    },
    /** 頁面上的「編輯自訂欄位」按鈕呼叫。 */
    openEditor: function () {
      var el = document.getElementById('cf-editor')
      if (!el || !window.Alpine) return
      window.Alpine.$data(el).start()
    },
  }
})()
