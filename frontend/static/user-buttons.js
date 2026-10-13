/* user-buttons.js — 使用者自訂按鈕（T61 S6；設計：docs/platform/plans/T61-S6-ACTION-CATALOG-DESIGN.md）。
 *
 * ① 執行時（Alpine store 'ub'）：頁面啟動時 `MotrixUserButtons.init({ module:'supply', page:'suppliers.html' })` 讀
 *    GET /api/user-buttons/<模組>/<頁面> ⇒ { enabled, buttons }（伺服器已用這位使用者的權限逐顆過濾）。旗標關閉 ⇒ enabled=false、
 *    buttons=[]，頁面什麼都不畫（唯一多出的動作是這一個 GET）。頁面用 `$store.ub.list('toolbar')` 取某插槽的按鈕、`MotrixUserButtons.run(b)` 執行。
 *    按鈕只是入口、不授權：開頁＝導向目標頁（目標自己驗證）；匯出＝用**點擊者自己的 token** 呼叫目錄裡的 GET 端點（端點自己驗證、遮蔽、稽核）。
 *    端點路徑來自伺服器的目錄，不來自使用者存的定義。按鈕文字一律當純文字渲染（頁面用 x-text）。
 * ② 按鈕編輯器（僅超級管理員；旗標開啟才掛上）：側邊面板，新增／改文字／選動作與目標／排序／移除，草稿即時畫在頁面插槽上（預覽，不可點），
 *    「以某位使用者預覽」（伺服器用該使用者的真實權限算出哪些會出現、哪些不會與原因，唯讀）、存草稿、看差異、發布、版本還原；
 *    發布與還原前先在頁內兩段式確認（不用原生對話框）；治理旗標開啟時匯出類按鈕屬放寬，後端回 {pending:true}，面板如實說「已送出，待第二位最高管理者核准」。
 * e2e 等待點：#ub-editor 的 data-busy（'0'／'1'）與 data-state（idle／saved／problems／published／restored／pending）。
 */
;(function () {
  var cfg = null
  var SLOT_PAGE_SEP = '/'

  function session() { try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) { return {} } }
  function headers() { return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + (session().token || '') } }
  function S() { return (window.Alpine && window.Alpine.store && window.Alpine.store('ub')) || raw }

  var raw = {
    module: '', page: '', loaded: false, failed: false, error: '', enabled: false,
    buttons: [],             // 這位使用者看得到的已發布按鈕
    view: null,              // 編輯器開啟時＝草稿的呈現
    mode: 'live', previewLabel: '', msg: '', busy: false,
    /** 某插槽要畫的按鈕。 */
    list: function (slot) { return (this.view || this.buttons).filter(function (b) { return b.slot === slot }) },
  }

  async function load() {
    var s = S()
    try {
      var r = await fetch('/api/user-buttons/' + encodeURIComponent(cfg.module) + '/' + encodeURIComponent(cfg.page), { headers: headers() })
      if (!r.ok) throw new Error('HTTP ' + r.status)
      var d = await r.json()
      s = S()
      s.enabled = d.enabled === true
      s.buttons = Array.isArray(d.buttons) ? d.buttons : []
      s.failed = false
      s.error = ''
      s.loaded = true
      if (s.enabled && session().role === 'superadmin') mountEditor()
    } catch (e) {
      s = S()
      s.failed = true
      s.enabled = false
      s.error = '自訂按鈕載入失敗（' + (e && e.message || e) + '）'
    }
  }

  function filenameOf(resp, fallback) {
    var cd = resp.headers && resp.headers.get && resp.headers.get('Content-Disposition') || ''
    var m = /filename\*=UTF-8''([^;]+)/i.exec(cd)
    if (m) { try { return decodeURIComponent(m[1]) } catch (e) { /* 退回下一種 */ } }
    m = /filename="?([^";]+)"?/i.exec(cd)
    return m ? m[1] : fallback
  }

  async function run(b) {
    var s = S()
    if (!b || s.mode !== 'live') return                                  // 預覽中不執行任何動作
    if (b.type === 'navigate') {
      if (/^[a-z0-9][a-z0-9_-]*\.html$/.test(String(b.page || ''))) window.location.href = b.page
      return
    }
    var ep = String(b.endpoint || '')
    if (b.type !== 'export' || !/^\/api\/[A-Za-z0-9_\/.-]+$/.test(ep) || ep.indexOf('..') >= 0 || ep.indexOf('//') >= 0) return   // 只收 /api/ 底下單純的路徑（不含 .. 與 //）
    s.busy = true
    s.msg = ''
    try {
      var r = await fetch(ep, { headers: { Authorization: 'Bearer ' + (session().token || '') } })
      if (!r.ok) {
        var d = await r.json().catch(function () { return {} })
        s.msg = '匯出失敗：' + (typeof d.detail === 'string' ? d.detail : ('HTTP ' + r.status))
        return
      }
      var blob = await r.blob()
      var a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = filenameOf(r, (b.label || 'export') + '.' + (b.format || 'xlsx'))
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      setTimeout(function () { URL.revokeObjectURL(a.href) }, 4000)
    } catch (e) {
      s.msg = '匯出失敗：連線中斷'
    } finally {
      s.busy = false
    }
  }

  // ── 編輯器 ─────────────────────────────────────────────────────────────
  var CSS = [
    '[x-cloak]{display:none!important}',
    '#ub-editor{position:fixed;top:0;right:0;bottom:0;width:420px;z-index:1200;background:var(--bg-card,#fff);',
    'border-left:1px solid var(--border-light,#ddd);box-shadow:-8px 0 24px rgba(0,0,0,.08);display:flex;flex-direction:column;font-size:12px}',
    '#ub-editor .ub-head{padding:12px 14px;border-bottom:1px solid var(--border-light,#ddd);display:flex;flex-direction:column;gap:8px}',
    '#ub-editor .ub-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}',
    '#ub-editor .ub-body{flex:1;overflow:auto;padding:10px 14px}#ub-editor .ub-foot{padding:10px 14px;border-top:1px solid var(--border-light,#ddd)}',
    '#ub-editor .ub-sub{color:var(--text-dim,#888);font-size:11px}#ub-editor .ub-h{font-weight:600;margin:8px 0 4px}',
    '#ub-editor .ub-item{border:1px solid var(--border-light,#e5e5e5);border-radius:6px;padding:6px 8px;margin:6px 0;background:var(--bg,#fafafa)}',
    '#ub-editor .ub-item.is-bad{border-color:var(--danger,#dc2626);background:var(--danger-light,#fef2f2)}',
    '#ub-editor input[type=text],#ub-editor select{font-size:12px;padding:2px 6px;border:1px solid var(--border-light,#ddd);border-radius:4px}',
    '#ub-editor .ub-item input[type=text]{flex:1;min-width:0}#ub-editor button.ub-b{border:1px solid var(--border-light,#ddd);background:none;border-radius:4px;cursor:pointer;padding:0 6px}',
    '#ub-editor .ub-prob{color:var(--danger,#dc2626);font-size:11px;margin-top:3px}',
    '#ub-editor .ub-banner{background:var(--warning-light,#fffbeb);color:var(--warning,#b45309);padding:6px 8px;border-radius:6px}',
    '#ub-editor .ub-ver{display:flex;justify-content:space-between;gap:6px;padding:3px 0;border-bottom:1px dashed var(--border-light,#eee)}',
    'body.ub-editing .app-shell,body.ub-editing .page-main{margin-right:420px}',
  ].join('')

  function tpl() {
    return '' +
'<div id="ub-editor" x-data="MotrixUserButtons.component()" x-show="open" x-cloak :data-busy="(busy || loading) ? \'1\' : \'0\'" :data-state="state">' +
' <div class="ub-head">' +
'  <div class="ub-row" style="justify-content:space-between"><strong>自訂按鈕</strong>' +
'   <button type="button" class="btn btn-ghost btn-sm" data-testid="ub-close" @click="close()">關閉</button></div>' +
'  <div class="ub-sub">按鈕只是入口，不會讓任何人看到或匯出他本來不能的東西：每個人只看得到自己有權限的按鈕；目標頁面與匯出自己會再檢查。第一版只有「開啟頁面」和「執行匯出」，不會寫入任何資料。</div>' +
'  <div class="ub-banner" data-testid="ub-ask" role="alertdialog" x-show="askBar" x-cloak><span x-text="askBar && askBar.text"></span> ' +
'   <button type="button" class="btn btn-primary btn-sm" data-testid="ub-ask-yes" @click="answer(true)">確定</button> ' +
'   <button type="button" class="btn btn-ghost btn-sm" data-testid="ub-ask-no" @click="answer(false)">取消</button></div>' +
'  <div class="ub-banner" x-show="loadError" x-text="loadError"></div>' +
' </div>' +
' <div class="ub-body" x-show="!loading" x-effect="$el.inert = busy">' +
'  <div class="ub-sub" x-show="!work.length">還沒有按鈕。按「新增按鈕」開始；畫面上會即時出現預覽（預覽中的按鈕不能點），發布之後才會讓大家看到。</div>' +
'  <template x-for="(b, i) in work" :key="b.key">' +
'   <div class="ub-item" :class="{\'is-bad\': !!probs[i]}" :data-button-index="i">' +
'    <div class="ub-row"><input type="text" data-testid="ub-label" x-model="b.label" @input="sync()" placeholder="按鈕文字（最多 20 字）" maxlength="20">' +
'     <button type="button" class="ub-b" title="上移" @click="mv(i, -1)">↑</button><button type="button" class="ub-b" title="下移" @click="mv(i, 1)">↓</button>' +
'     <button type="button" class="ub-b" title="移除" @click="remove(i)">移除</button></div>' +
'    <div class="ub-row" style="margin-top:4px"><label>動作</label>' +
'     <select data-testid="ub-type" x-model="b.type" @change="b.target = \'\'; sync()"><option value="navigate">開啟頁面</option><option value="export">執行匯出</option></select>' +
'     <select data-testid="ub-target" x-model="b.target" @change="sync()" style="flex:1;min-width:0">' +
'      <option value="">— 選擇 —</option>' +
'      <template x-if="b.type === \'navigate\'"><template x-for="p in catalog.pages" :key="p.page"><option :value="p.page" x-text="p.label" :selected="b.target === p.page"></option></template></template>' +
'      <template x-if="b.type === \'export\'"><template x-for="e in catalog.exports" :key="e.id"><option :value="e.id" x-text="e.label + \'（\' + e.format + \'）\'" :selected="b.target === e.id"></option></template></template>' +
'     </select></div>' +
'    <div class="ub-sub" x-show="b.type === \'export\'">匯出會用「點擊的人自己」的身分執行，沒有權限的人看不到這顆按鈕、也匯不出。</div>' +
'    <div class="ub-prob" x-show="probs[i]" x-text="probs[i]"></div>' +
'   </div></template>' +
'  <div class="ub-row" style="margin-top:8px"><button type="button" class="btn btn-ghost btn-sm" data-testid="ub-add" @click="add()" :disabled="work.length >= max">＋ 新增按鈕</button>' +
'   <span class="ub-sub" x-text="work.length + \' / \' + max"></span></div>' +
'  <div class="ub-h">以某位使用者預覽</div>' +
'  <div class="ub-row"><input type="text" data-testid="ub-preview-user" x-model="previewUser" placeholder="帳號（留空＝我自己）" style="flex:1">' +
'   <button type="button" class="btn btn-ghost btn-sm" data-testid="ub-preview-btn" @click="previewAs()" :disabled="busy || loading">預覽</button></div>' +
'  <div data-testid="ub-preview" x-show="previewResult">' +
'   <div class="ub-sub" x-text="previewResult && (\'以「\' + previewResult.user + \'」（\' + previewResult.role + \'）的權限\')"></div>' +
'   <ul><template x-for="v in (previewResult ? previewResult.visible : [])" :key="v.key"><li x-text="\'看得到：\' + v.label"></li></template>' +
'    <template x-for="h in (previewResult ? previewResult.hidden : [])" :key="h.key"><li x-text="\'看不到：\' + h.label + \'（\' + h.reason + \'）\'"></li></template></ul></div>' +
'  <div x-show="diffShown" data-testid="ub-diff"><div class="ub-h">與目前發布版的差異</div><div class="ub-sub" x-show="!diffLines.length">沒有差異。</div>' +
'   <ul><template x-for="d in diffLines"><li x-text="d"></li></template></ul></div>' +
'  <div data-testid="ub-versions"><div class="ub-h">版本</div><div class="ub-sub" x-show="!published().length">還沒有發布過。</div>' +
'   <template x-for="v in published()" :key="v.version"><div class="ub-ver" :data-version="v.version">' +
'    <span x-text="\'第 \' + v.version + \' 版 \' + (v.published_at || \'\').slice(0, 16).replace(\'T\', \' \') + (v.note ? \'・\' + v.note : \'\')"></span>' +
'    <button type="button" class="btn btn-ghost btn-sm" @click="restore(v.version)" :disabled="busy || loading">還原</button></div></template></div>' +
' </div>' +
' <div class="ub-foot"><div class="ub-row">' +
'  <button type="button" class="btn btn-ghost btn-sm" data-testid="ub-save" @click="saveDraft()" :disabled="busy || loading">存草稿</button>' +
'  <button type="button" class="btn btn-ghost btn-sm" data-testid="ub-diff-btn" @click="showDiff()" :disabled="busy || loading">看差異</button>' +
'  <button type="button" class="btn btn-primary btn-sm" data-testid="ub-publish" @click="publish()" :disabled="busy || loading">發布</button>' +
'  <button type="button" class="btn btn-ghost btn-sm" x-show="defs.draft" @click="discard()" :disabled="busy || loading">捨棄草稿</button></div>' +
'  <div class="ub-row" style="margin-top:6px"><input type="text" data-testid="ub-note" x-model="note" placeholder="發布說明（選填）" style="flex:1"></div>' +
'  <div style="margin-top:6px" data-testid="ub-msg" x-text="msg"></div></div>' +
'</div>'
  }

  function component() {
    return {
      open: false, busy: false, loading: false, state: 'idle', msg: '', note: '', loadError: '', max: 6,
      askBar: null, _askRes: null, defs: { draft: null, latest: null, versions: [] },
      work: [], probs: {}, diffShown: false, diffLines: [], catalog: { pages: [], exports: [], slots: [] },
      previewUser: '', previewResult: null,

      _key: function () { return 'module:' + cfg.module },
      _base: function () { return '/api/definitions/user_buttons/' + encodeURIComponent(this._key()) },
      _slot: function () { return cfg.page + SLOT_PAGE_SEP + (cfg.slot || 'toolbar') },
      async _j(url, opt) {
        var r = await fetch(url, Object.assign({ headers: headers() }, opt || {}))
        var d = await r.json().catch(function () { return {} })
        return { ok: r.ok, status: r.status, d: d }
      },
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

      // ── 畫面狀態 ⇄ 定義 body ──
      _fromBody: function (body) {
        return ((body || {}).buttons || []).map(function (b) {
          var a = b.action || {}
          return { key: b.key, slot: b.slot, label: b.label || '', type: a.type === 'export' ? 'export' : 'navigate',
                   target: a.type === 'export' ? (a.export || '') : (a.page || '') }
        })
      },
      _body: function () {
        var slot = this._slot()
        return { buttons: this.work.map(function (b) {
          return { key: b.key, slot: b.slot || slot, label: String(b.label || '').trim(),
                   action: b.type === 'export' ? { type: 'export', export: b.target } : { type: 'navigate', page: b.target } }
        }) }
      },
      _nextKey: function () {
        var n = 0
        this.work.forEach(function (b) { var m = /^b(\d+)$/.exec(b.key); if (m) n = Math.max(n, +m[1]) })
        return 'b' + (n + 1)
      },
      // 預覽用：畫在頁面插槽上（不可點）；匯出的端點路徑不從這裡給
      _view: function () {
        var self = this
        return this.work.map(function (b) {
          return { key: b.key, slot: (b.slot || self._slot()).split('/').slice(1).join('/'), label: String(b.label || '').trim() || '（未命名）', type: b.type }
        })
      },
      sync: function () { if (this.open) window.MotrixUserButtons.show(this._view(), 'edit', '預覽（草稿，尚未發布）') },
      add: function () {
        if (this.work.length >= this.max) return
        this.work.push({ key: this._nextKey(), slot: this._slot(), label: '', type: 'navigate', target: '' })
        this.sync()
      },
      remove: function (i) { this.work.splice(i, 1); this.probs = {}; this.sync() },
      mv: function (i, dir) {
        var j = i + dir
        if (j < 0 || j >= this.work.length) return
        var t = this.work[i]; this.work.splice(i, 1); this.work.splice(j, 0, t)
        this.probs = {}
        this.sync()
      },
      published: function () { return (this.defs.versions || []).filter(function (v) { return v.status === 'published' }) },

      async start() {
        this.open = true
        document.body.classList.add('ub-editing')
        await this.load()
      },
      close() {
        if (this._askRes) { var r0 = this._askRes; this._askRes = null; this.askBar = null; r0(false) }
        this.open = false
        document.body.classList.remove('ub-editing')
        window.MotrixUserButtons.show(null)
      },
      async load() {
        this.loading = true
        this.loadError = ''
        this.probs = {}; this.diffShown = false; this.msg = ''; this.previewResult = null
        try {
          var c = await this._j('/api/user-buttons/catalog')
          if (!c.ok) throw new Error('目錄 HTTP ' + c.status)
          this.catalog = c.d
          var r = await this._j(this._base() + '?scope=company')
          if (!r.ok) throw new Error('HTTP ' + r.status)
          this.defs = r.d
          var src = r.d.draft ? r.d.draft.body : (r.d.latest ? r.d.latest.body : { buttons: [] })
          this.work = this._fromBody(src)
          this.msg = r.d.draft ? '從草稿繼續' : (r.d.latest ? '從第 ' + r.d.latest.version + ' 版開始' : '還沒有按鈕')
          this.loading = false
          this.sync()
        } catch (e) {
          this.loadError = '讀取按鈕定義失敗（' + (e && e.message || e) + '），編輯已鎖定；關閉後再打開重試'
        }
      },

      _guard: async function (fn, unknown) {
        try { return await fn() }
        catch (e) { this.state = 'error'; this.msg = unknown + '（' + (e && e.message || e) + '）'; return false }
        finally { this.busy = false }
      },
      saveDraft: function () { var self = this; return this._guard(function () { return self._saveDraft() }, '存草稿失敗：連線中斷，請再按一次') },
      publish: function () { var self = this; return this._guard(function () { return self._publish() }, '發布結果不明：伺服器可能已經處理，請關閉再打開、看版本清單確認') },
      restore: function (v) { var self = this; return this._guard(function () { return self._restore(v) }, '還原結果不明：請關閉再打開、看版本清單確認') },
      discard: function () { var self = this; return this._guard(function () { return self._discard() }, '捨棄草稿結果不明：請關閉再打開確認') },
      previewAs: function () { var self = this; return this._guard(function () { return self._previewAs() }, '預覽失敗') },
      _mark: function (problems) {
        var probs = {}
        ;(problems || []).forEach(function (p) {
          var m = /^buttons\[(\d+)\]/.exec(p.path || '')
          var i = m ? +m[1] : -1
          probs[i] = (probs[i] ? probs[i] + '；' : '') + p.message
        })
        this.probs = probs
        return probs
      },
      async _previewAs() {
        this.busy = true
        var r = await this._j('/api/user-buttons/' + encodeURIComponent(cfg.module) + '/' + encodeURIComponent(cfg.page) + '/preview',
                              { method: 'POST', body: JSON.stringify({ buttons: this._body().buttons, user: String(this.previewUser || '').trim() || undefined }) })
        if (!r.ok) {
          var probs = (r.d.detail && r.d.detail.problems) || []
          if (probs.length) { this._mark(probs); this.msg = '草稿有問題，無法預覽' } else this.msg = '預覽失敗：' + (typeof r.d.detail === 'string' ? r.d.detail : r.status)
          this.previewResult = null
          this.busy = false
          return
        }
        var label = {}
        this._body().buttons.forEach(function (b) { label[b.key] = b.label })
        r.d.hidden = (r.d.hidden || []).map(function (h) { return Object.assign({ label: label[h.key] || h.key }, h) })
        this.previewResult = r.d
        this.msg = '預覽完成（沒有執行任何動作）'
        this.busy = false
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
        var latest = (this.defs.latest ? this.defs.latest.body.buttons : []) || []
        var now = this._body().buttons
        var byKey = function (a) { var o = {}; a.forEach(function (b) { o[b.key] = b }); return o }
        var a = byKey(latest), b = byKey(now), lines = []
        var desc = function (x) { return x.action.type === 'export' ? '執行匯出 ' + x.action.export : '開啟 ' + x.action.page }
        now.forEach(function (x) {
          if (!a[x.key]) lines.push('新增按鈕「' + (x.label || x.key) + '」（' + desc(x) + '）')
          else {
            var o = a[x.key]
            if (o.label !== x.label) lines.push('「' + o.label + '」改名為「' + x.label + '」')
            if (JSON.stringify(o.action) !== JSON.stringify(x.action)) lines.push('「' + x.label + '」的動作改為 ' + desc(x))
          }
        })
        latest.forEach(function (x) { if (!b[x.key]) lines.push('移除按鈕「' + x.label + '」') })
        var oa = latest.map(function (x) { return x.key }).filter(function (k) { return b[k] }).join()
        var ob = now.map(function (x) { return x.key }).filter(function (k) { return a[k] }).join()
        if (oa !== ob) lines.push('按鈕順序有變')
        this.diffLines = lines
        this.diffShown = true
      },
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
        if (!(await this._ask('發布後，大家在這個畫面就會看到這些按鈕（每個人只看得到自己有權限的）。確定要發布嗎？'))) { this.busy = false; return }
        if (window.MotrixDefGovernance && await window.MotrixDefGovernance.available()) {
          var pv = await window.MotrixDefGovernance.preview({ kind: 'user_buttons', key: this._key(), scope: 'company' })
          if (pv.ok && pv.data && pv.data.changeCount && !(await this._ask('這次發布會變更 ' + pv.data.changeCount + ' 項設定（影響預覽已記錄），確定要發布？'))) {
            this.msg = '已取消發布'; this.busy = false; return
          }
        }
        var r = await this._j(this._base() + '/publish?scope=company', { method: 'POST', body: JSON.stringify({ note: this.note }) })
        if (!r.ok) { this._mark(r.d.problems || []); this.msg = '發布失敗：' + (r.d.detail || r.status); this.busy = false; return }
        this.note = ''
        var pend = r.d && r.d.pending === true
        if (!pend) await window.MotrixUserButtons.reload()
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
        var r = await this._j(this._base() + '/restore/' + version + '?scope=company', { method: 'POST', body: JSON.stringify({}) })
        if (!r.ok) { this._mark(r.d.problems || []); this.msg = '還原失敗：' + (r.d.detail || r.status); this.busy = false; return }
        var pend = r.d && r.d.pending === true
        if (!pend && this.defs.draft) await this._j(this._base() + '/draft?scope=company', { method: 'DELETE' })
        if (!pend) await window.MotrixUserButtons.reload()
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
    if (document.getElementById('ub-editor')) return
    if (!document.getElementById('ub-editor-css')) {
      var st = document.createElement('style'); st.id = 'ub-editor-css'; st.textContent = CSS
      document.head.appendChild(st)
    }
    var wrap = document.createElement('div')
    wrap.innerHTML = tpl()
    document.body.appendChild(wrap.firstChild)
  }

  window.MotrixUserButtons = {
    /** 頁面啟動時呼叫一次：{ module, page, slot? }。旗標關閉 ⇒ enabled=false。 */
    init: function (c) {
      cfg = c
      raw.module = c.module
      raw.page = c.page
      document.addEventListener('alpine:init', function () { window.Alpine.store('ub', raw) })
      return load()
    },
    reload: load,
    run: run,
    config: function () { return cfg },
    _state: function () { return S() },          // 測試用
    component: component,
    /** 編輯器：畫面換成草稿的呈現（edit，不可點）；null ⇒ 回到已發布的。 */
    show: function (buttons, mode, label) {
      var s = S()
      if (!buttons) { s.mode = 'live'; s.previewLabel = ''; s.view = null; return }
      s.mode = mode || 'edit'
      s.previewLabel = label || ''
      s.view = buttons
    },
    openEditor: function () {
      var el = document.getElementById('ub-editor')
      if (!el || !window.Alpine) return
      window.Alpine.$data(el).start()
    },
  }
})()
