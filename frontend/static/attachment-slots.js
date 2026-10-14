/* attachment-slots.js — 附件種類編輯器（BP-4 S3；設計 docs/platform/plans/BP4-STORAGE-NOTIFY-DESIGN.md §3、§5）。
 *
 * 只有編輯器，沒有執行時 store：頁面（案件管理頁的完工單分頁）在**已經送出的那一個設定請求**裡看到旗標 `builder_slots.enabled` 為 1
 * 才呼叫 `MotrixAttachmentSlots.mount({ docType: 'completion_note', label: '完工單' })`；旗標關閉 ⇒ 這個檔只是被載入、什麼都不做、不發任何請求。
 * 編輯器（僅超級管理員）：側邊面板，新增／改名／勾選可收的檔案類型（只列系統允許的 `slotExts`）／件數與大小上限／可上傳的人（只能收窄）／子資料夾，
 * 「模擬上傳」（呼叫 `POST /api/attachment-slots/<單據類型>/simulate`，唯讀：不寫檔、不建資料夾，只回收不收、顯示用路徑、誰能讀的人數）、
 * 存草稿、看差異、發布、版本還原。發布與還原前先走 `MotrixDefGovernance.review`（治理旗標開時帶 preview_hash）與頁內兩段式確認（不用原生對話框）；
 * 放寬類變更後端回 {pending:true}，面板如實說「已送出，待第二位最高管理者核准」。
 * 內建「簽回單」附件種類永遠存在、不可改（保留鍵 signed）。
 * e2e 等待點：#as-editor 的 data-busy（'0'／'1'）與 data-state（idle／saved／problems／published／restored／pending）。
 */
;(function () {
  var cfg = null

  function session() { try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) { return {} } }
  function headers() { return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + (session().token || '') } }

  var CSS = [
    '[x-cloak]{display:none!important}',
    '#as-editor{position:fixed;top:0;right:0;bottom:0;width:440px;z-index:1200;background:var(--bg-card,#fff);',
    'border-left:1px solid var(--border-light,#ddd);box-shadow:-8px 0 24px rgba(0,0,0,.08);display:flex;flex-direction:column;font-size:12px}',
    '#as-editor .as-head{padding:12px 14px;border-bottom:1px solid var(--border-light,#ddd);display:flex;flex-direction:column;gap:8px}',
    '#as-editor .as-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}',
    '#as-editor .as-body{flex:1;overflow:auto;padding:10px 14px}#as-editor .as-foot{padding:10px 14px;border-top:1px solid var(--border-light,#ddd)}',
    '#as-editor .as-sub{color:var(--text-dim,#888);font-size:11px}#as-editor .as-h{font-weight:600;margin:8px 0 4px}',
    '#as-editor .as-item{border:1px solid var(--border-light,#e5e5e5);border-radius:6px;padding:6px 8px;margin:6px 0;background:var(--bg,#fafafa)}',
    '#as-editor .as-item.is-bad{border-color:var(--danger,#dc2626);background:var(--danger-light,#fef2f2)}#as-editor .as-item.is-off{opacity:.6}',
    '#as-editor input[type=text],#as-editor input[type=number],#as-editor select{font-size:12px;padding:2px 6px;border:1px solid var(--border-light,#ddd);border-radius:4px}',
    '#as-editor input[type=number]{width:70px}#as-editor .as-item input[type=text]{flex:1;min-width:0}',
    '#as-editor button.as-b{border:1px solid var(--border-light,#ddd);background:none;border-radius:4px;cursor:pointer;padding:0 6px}',
    '#as-editor .as-prob{color:var(--danger,#dc2626);font-size:11px;margin-top:3px}',
    '#as-editor .as-banner{background:var(--warning-light,#fffbeb);color:var(--warning,#b45309);padding:6px 8px;border-radius:6px}',
    '#as-editor .as-ok{color:var(--success,#15803d)}#as-editor .as-no{color:var(--danger,#dc2626)}',
    '#as-editor .as-ver{display:flex;justify-content:space-between;gap:6px;padding:3px 0;border-bottom:1px dashed var(--border-light,#eee)}',
    '#as-editor label.as-chk{display:inline-flex;align-items:center;gap:3px;margin-right:6px}',
    'body.as-editing .app-shell,body.as-editing .page-main{margin-right:440px}',
  ].join('')

  function tpl() {
    return '' +
'<div id="as-editor" x-data="MotrixAttachmentSlots.component()" x-show="open" x-cloak :data-busy="(busy || loading) ? \'1\' : \'0\'" :data-state="state">' +
' <div class="as-head">' +
'  <div class="as-row" style="justify-content:space-between"><strong>附件種類</strong>' +
'   <button type="button" class="btn btn-ghost btn-sm" data-testid="as-close" @click="close()">關閉</button></div>' +
'  <div class="as-sub" x-text="\'單據：\' + label() + \'。內建的「簽回單」永遠存在、不能改。\'"></div>' +
'  <div class="as-sub">檔案類型、大小與誰能上傳都只能比系統底線更嚴；誰能「看」檔案仍由原本的單據權限決定，這裡改不了。只影響之後新上傳的檔案，已存的檔案不搬移。</div>' +
'  <div class="as-banner" data-testid="as-ask" role="alertdialog" x-show="askBar" x-cloak><span x-text="askBar && askBar.text"></span> ' +
'   <button type="button" class="btn btn-primary btn-sm" data-testid="as-ask-yes" @click="answer(true)">確定</button> ' +
'   <button type="button" class="btn btn-ghost btn-sm" data-testid="as-ask-no" @click="answer(false)">取消</button></div>' +
'  <div class="as-banner" x-show="loadError" x-text="loadError"></div>' +
' </div>' +
' <div class="as-body" x-show="!loading" x-effect="$el.inert = busy">' +
'  <div class="as-sub" x-show="!work.length">還沒有自訂的附件種類。按「新增附件種類」開始。</div>' +
'  <template x-for="(s, i) in work" :key="s.key">' +
'   <div class="as-item" :class="{\'is-bad\': !!probs[i], \'is-off\': s.disabled}" :data-slot-index="i">' +
'    <div class="as-row"><input type="text" data-testid="as-label" x-model="s.label" placeholder="名稱（最多 20 字）" maxlength="20">' +
'     <button type="button" class="as-b" title="上移" @click="mv(i, -1)">↑</button><button type="button" class="as-b" title="下移" @click="mv(i, 1)">↓</button>' +
'     <button type="button" class="as-b" title="移除" @click="remove(i)">移除</button></div>' +
'    <div class="as-row" style="margin-top:4px"><span>可收的檔案類型</span>' +
'     <template x-for="e in catalog.slotExts" :key="e"><label class="as-chk"><input type="checkbox" :data-ext="e" :checked="s.accept.indexOf(e) >= 0" @change="toggleExt(s, e, $event.target.checked)"> <span x-text="e"></span></label></template></div>' +
'    <div class="as-row" style="margin-top:4px">' +
'     <label>單檔 MB <input type="number" min="1" :max="catalog.platform.maxFileMb" data-testid="as-file-mb" x-model="s.maxFileMb" :placeholder="catalog.platform.maxFileMb"></label>' +
'     <label>件數 <input type="number" min="1" :max="catalog.platform.maxFiles" data-testid="as-files" x-model="s.maxFiles" placeholder="10"></label>' +
'     <label>一次合計 MB <input type="number" min="1" :max="catalog.platform.maxRequestMb" data-testid="as-req-mb" x-model="s.maxRequestMb" placeholder="50"></label></div>' +
'    <div class="as-row" style="margin-top:4px"><span>誰可以上傳</span>' +
'     <template x-for="r in catalog.roles" :key="r"><label class="as-chk"><input type="checkbox" :data-role="r" :checked="s.roles.indexOf(r) >= 0" @change="toggleRole(s, r, $event.target.checked)"> <span x-text="r"></span></label></template></div>' +
'    <div class="as-sub">一個都不勾＝維持原本的上傳權限；勾選只會「縮小」成這些角色（超級管理員一律可以）。</div>' +
'    <div class="as-row" style="margin-top:4px"><label>子資料夾 <input type="text" data-testid="as-sub" x-model="s.subfolder" maxlength="40" placeholder="（選填）" :disabled="!subfolderOk()"></label>' +
'     <span class="as-sub" x-show="!subfolderOk()">這個位置的讀取還不支援子資料夾</span></div>' +
'    <div class="as-row" style="margin-top:4px"><label class="as-chk"><input type="checkbox" x-model="s.required"> 提示必須有（只標紅，不擋）</label>' +
'     <label class="as-chk"><input type="checkbox" x-model="s.disabled" data-testid="as-disabled"> 停用</label></div>' +
'    <div class="as-prob" x-show="probs[i]" x-text="probs[i]"></div>' +
'   </div></template>' +
'  <div class="as-row" style="margin-top:8px"><button type="button" class="btn btn-ghost btn-sm" data-testid="as-add" @click="add()" :disabled="work.length >= catalog.platform.maxSlots">＋ 新增附件種類</button>' +
'   <span class="as-sub" x-text="work.length + \' / \' + catalog.platform.maxSlots"></span></div>' +
'  <div class="as-h">模擬上傳</div>' +
'  <div class="as-sub">只是試算，不會真的存任何檔案、也不會建資料夾。</div>' +
'  <div class="as-row"><select data-testid="as-sim-slot" x-model="sim.slot"><option value="signed">簽回單（內建）</option>' +
'    <template x-for="s in work" :key="s.key"><option :value="s.key" x-text="s.label || s.key"></option></template></select>' +
'   <input type="text" data-testid="as-sim-name" x-model="sim.filename" placeholder="檔名，例 驗收.pdf" style="flex:1;min-width:120px"></div>' +
'  <div class="as-row" style="margin-top:4px"><label>大小 KB <input type="number" min="0" data-testid="as-sim-kb" x-model="sim.kb"></label>' +
'   <label>已有幾個 <input type="number" min="0" data-testid="as-sim-existing" x-model="sim.existing"></label>' +
'   <label>單號（選填，算誰能讀） <input type="text" data-testid="as-sim-docno" x-model="sim.docNo" style="width:110px"></label>' +
'   <button type="button" class="btn btn-ghost btn-sm" data-testid="as-sim-run" @click="simulate()" :disabled="busy || loading">模擬</button></div>' +
'  <div data-testid="as-sim-result" x-show="simResult" style="margin-top:6px">' +
'   <div :class="simResult && simResult.ok ? \'as-ok\' : \'as-no\'" x-text="simResult && (simResult.ok ? \'會收這個檔案\' : \'不會收這個檔案\')"></div>' +
'   <ul><template x-for="r in (simResult ? simResult.reasons : [])"><li x-text="r"></li></template></ul>' +
'   <div class="as-sub" x-show="simResult && simResult.ok" x-text="simResult && (\'會存在：\' + simResult.displayPath)"></div>' +
'   <div class="as-sub" x-show="simResult && simResult.headerNote" x-text="simResult && simResult.headerNote"></div>' +
'   <div class="as-sub" x-show="simResult && !simResult.subfolderUsable">這個位置的讀取還不支援子資料夾，發布也用不了。</div>' +
'   <div class="as-sub" x-show="simResult && simResult.readers" data-testid="as-sim-readers"><span>誰能讀（帳號數）：</span>' +
'    <template x-for="role in readerRoles()" :key="role"><span x-text="role + \' \' + simResult.readers[role].canRead + \'/\' + simResult.readers[role].accounts + \'　\'"></span></template></div>' +
'   <div class="as-sub" x-show="simResult && !simResult.readers">填一張真實單號，才能算出各角色有幾個帳號讀得到。</div>' +
'   <div class="as-sub" x-text="simResult && simResult.note"></div></div>' +
'  <div x-show="diffShown" data-testid="as-diff"><div class="as-h">與目前發布版的差異</div><div class="as-sub" x-show="!diffLines.length">沒有差異。</div>' +
'   <ul><template x-for="d in diffLines"><li x-text="d"></li></template></ul></div>' +
'  <div data-testid="as-versions"><div class="as-h">版本</div><div class="as-sub" x-show="!published().length">還沒有發布過。</div>' +
'   <template x-for="v in published()" :key="v.version"><div class="as-ver" :data-version="v.version">' +
'    <span x-text="\'第 \' + v.version + \' 版 \' + (v.published_at || \'\').slice(0, 16).replace(\'T\', \' \') + (v.note ? \'・\' + v.note : \'\')"></span>' +
'    <button type="button" class="btn btn-ghost btn-sm" @click="restore(v.version)" :disabled="busy || loading">還原</button></div></template></div>' +
' </div>' +
' <div class="as-foot"><div class="as-row">' +
'  <button type="button" class="btn btn-ghost btn-sm" data-testid="as-save" @click="saveDraft()" :disabled="busy || loading">存草稿</button>' +
'  <button type="button" class="btn btn-ghost btn-sm" data-testid="as-diff-btn" @click="showDiff()" :disabled="busy || loading">看差異</button>' +
'  <button type="button" class="btn btn-primary btn-sm" data-testid="as-publish" @click="publish()" :disabled="busy || loading">發布</button>' +
'  <button type="button" class="btn btn-ghost btn-sm" x-show="defs.draft" @click="discard()" :disabled="busy || loading">捨棄草稿</button></div>' +
'  <div class="as-row" style="margin-top:6px"><input type="text" data-testid="as-note" x-model="note" placeholder="發布說明（選填）" style="flex:1"></div>' +
'  <div style="margin-top:6px" data-testid="as-msg" x-text="msg"></div></div>' +
'</div>'
  }

  function toInt(v) { var n = parseInt(v, 10); return isFinite(n) && String(v).trim() !== '' ? n : null }

  function component() {
    return {
      open: false, busy: false, loading: false, state: 'idle', msg: '', note: '', loadError: '',
      askBar: null, _askRes: null, defs: { draft: null, latest: null, versions: [] },
      work: [], probs: {}, diffShown: false, diffLines: [],
      catalog: { slotExts: [], roles: [], platform: { maxFileMb: 20, maxFiles: 20, maxRequestMb: 100, maxSlots: 10 }, docTypes: [] },
      sim: { slot: 'signed', filename: '', kb: 100, existing: 0, docNo: '' }, simResult: null,

      label: function () { return (cfg && cfg.label) || '單據' },
      _key: function () { return 'doc:' + cfg.docType },
      _base: function () { return '/api/definitions/attachment_slot/' + encodeURIComponent(this._key()) },
      subfolderOk: function () { var d = (this.catalog.docTypes || []).filter(function (x) { return x.docType === cfg.docType })[0]; return !!(d && d.subfolderSupported) },
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
        return ((body || {}).slots || []).map(function (s) {
          var up = s.uploaders || {}
          return { key: s.key, label: s.label || '', accept: (s.accept || []).slice(), maxFileMb: s.maxFileMb == null ? '' : s.maxFileMb,
                   maxFiles: s.maxFiles == null ? '' : s.maxFiles, maxRequestMb: s.maxRequestMb == null ? '' : s.maxRequestMb,
                   subfolder: s.subfolder || '', roles: (up.roles || []).slice(), modules: (up.modules || []).slice(),
                   required: !!s.required, disabled: !!s.disabled }
        })
      },
      _body: function () {
        return { slots: this.work.map(function (s) {
          var o = { key: s.key, label: String(s.label || '').trim(), accept: s.accept.slice() }
          ;[['maxFileMb', s.maxFileMb], ['maxFiles', s.maxFiles], ['maxRequestMb', s.maxRequestMb]].forEach(function (p) {
            var n = toInt(p[1]); if (n !== null) o[p[0]] = n
          })
          if (String(s.subfolder || '').trim()) o.subfolder = String(s.subfolder).trim()
          if ((s.roles && s.roles.length) || (s.modules && s.modules.length)) o.uploaders = { roles: s.roles.slice(), modules: (s.modules || []).slice() }
          if (s.required) o.required = true
          if (s.disabled) o.disabled = true
          return o
        }) }
      },
      _nextKey: function () {
        var n = 0
        this.work.forEach(function (s) { var m = /^slot(\d+)$/.exec(s.key); if (m) n = Math.max(n, +m[1]) })
        return 'slot' + (n + 1)
      },
      toggleExt: function (s, e, on) {
        var i = s.accept.indexOf(e)
        if (on && i < 0) s.accept.push(e)
        if (!on && i >= 0) s.accept.splice(i, 1)
      },
      toggleRole: function (s, r, on) {
        var i = s.roles.indexOf(r)
        if (on && i < 0) s.roles.push(r)
        if (!on && i >= 0) s.roles.splice(i, 1)
      },
      add: function () {
        if (this.work.length >= this.catalog.platform.maxSlots) return
        this.work.push({ key: this._nextKey(), label: '', accept: ['.pdf'], maxFileMb: '', maxFiles: '', maxRequestMb: '', subfolder: '', roles: [], modules: [], required: false, disabled: false })
      },
      remove: function (i) { this.work.splice(i, 1); this.probs = {} },
      mv: function (i, dir) {
        var j = i + dir
        if (j < 0 || j >= this.work.length) return
        var t = this.work[i]; this.work.splice(i, 1); this.work.splice(j, 0, t)
        this.probs = {}
      },
      readerRoles: function () { return this.simResult && this.simResult.readers ? Object.keys(this.simResult.readers) : [] },
      published: function () { return (this.defs.versions || []).filter(function (v) { return v.status === 'published' }) },

      async start() {
        this.open = true
        document.body.classList.add('as-editing')
        await this.load()
      },
      close() {
        if (this._askRes) { var r0 = this._askRes; this._askRes = null; this.askBar = null; r0(false) }
        this.open = false
        document.body.classList.remove('as-editing')
      },
      async load() {
        this.loading = true
        this.loadError = ''
        this.probs = {}; this.diffShown = false; this.msg = ''; this.simResult = null
        try {
          // 先打 catalog：旗標（含治理層）沒開 ⇒ 404；開了才讀定義（目錄請求同時讓伺服端把 attachment_slot 種類登記起來）
          var c = await this._j('/api/attachment-slots/catalog')
          if (c.status === 404) throw new Error('附件種類尚未開放（需要在設定中心同時開啟「自訂附件種類」與「版本帳本與影響預覽」）')
          if (!c.ok) throw new Error('目錄 HTTP ' + c.status)
          this.catalog = c.d
          var r = await this._j(this._base() + '?scope=company')
          if (!r.ok) throw new Error('HTTP ' + r.status)
          this.defs = r.d
          var src = r.d.draft ? r.d.draft.body : (r.d.latest ? r.d.latest.body : { slots: [] })
          this.work = this._fromBody(src)
          this.msg = r.d.draft ? '從草稿繼續' : (r.d.latest ? '從第 ' + r.d.latest.version + ' 版開始' : '還沒有自訂附件種類')
          this.loading = false
        } catch (e) {
          this.loadError = '讀取附件種類失敗（' + (e && e.message || e) + '），編輯已鎖定；關閉後再打開重試'
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
      simulate: function () { var self = this; return this._guard(function () { return self._simulate() }, '模擬失敗') },
      _mark: function (problems) {
        var probs = {}
        ;(problems || []).forEach(function (p) {
          var m = /^slots\[(\d+)\]/.exec(p.path || '')
          var i = m ? +m[1] : -1
          probs[i] = (probs[i] ? probs[i] + '；' : '') + p.message
        })
        this.probs = probs
        return probs
      },
      async _simulate() {
        this.busy = true
        var s = this.sim
        var r = await this._j('/api/attachment-slots/' + encodeURIComponent(cfg.docType) + '/simulate',
          { method: 'POST', body: JSON.stringify({ definition: this._body(), slot: s.slot, docNo: String(s.docNo || '').trim() || undefined,
                                                  sample: { filename: String(s.filename || ''), size: Math.round((toInt(s.kb) || 0) * 1024), existing: toInt(s.existing) || 0 } }) })
        if (!r.ok) {
          var probs = (r.d.detail && r.d.detail.problems) || []
          if (probs.length) { this._mark(probs); this.msg = '草稿有問題，無法模擬' } else this.msg = '模擬失敗：' + (typeof r.d.detail === 'string' ? r.d.detail : r.status)
          this.simResult = null
          this.busy = false
          return
        }
        this.simResult = r.d
        this.msg = '模擬完成（沒有存任何檔案）'
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
        var latest = (this.defs.latest ? this.defs.latest.body.slots : []) || []
        var now = this._body().slots
        var byKey = function (a) { var o = {}; a.forEach(function (b) { o[b.key] = b }); return o }
        var a = byKey(latest), b = byKey(now), lines = []
        now.forEach(function (x) {
          if (!a[x.key]) { lines.push('新增附件種類「' + (x.label || x.key) + '」（可收 ' + x.accept.join(' ') + (x.subfolder ? '，子資料夾 ' + x.subfolder : '') + '）'); return }
          var o = a[x.key]
          if (o.label !== x.label) lines.push('「' + o.label + '」改名為「' + x.label + '」')
          var add = x.accept.filter(function (e) { return (o.accept || []).indexOf(e) < 0 }), del = (o.accept || []).filter(function (e) { return x.accept.indexOf(e) < 0 })
          if (add.length) lines.push('「' + x.label + '」新增可收：' + add.join(' ') + '（放寬）')
          if (del.length) lines.push('「' + x.label + '」不再收：' + del.join(' '))
          ;['maxFileMb', 'maxFiles', 'maxRequestMb', 'subfolder', 'required', 'disabled'].forEach(function (f) {
            if (o[f] !== x[f]) lines.push('「' + x.label + '」' + f + '：' + (o[f] == null ? '預設' : o[f]) + ' → ' + (x[f] == null ? '預設' : x[f]))
          })
          if (JSON.stringify(o.uploaders || null) !== JSON.stringify(x.uploaders || null)) lines.push('「' + x.label + '」可上傳的人有變')
        })
        latest.forEach(function (x) { if (!b[x.key]) lines.push('移除附件種類「' + x.label + '」') })
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
        if (!(await this._ask('發布後，之後新上傳的檔案會依這些附件種類的規則收件與存放（已存的檔案不受影響）。確定要發布嗎？'))) { this.busy = false; return }
        // T62：治理旗標開時，看過的影響預覽雜湊 preview_hash 隨發布送出；旗標關／未載入 ⇒ 請求本體只有 note
        var pubBody = { note: this.note }
        if (window.MotrixDefGovernance && await window.MotrixDefGovernance.available('attachment_slot')) {
          var pvh = await window.MotrixDefGovernance.review({ kind: 'attachment_slot', key: this._key(), scope: 'company', title: '發布前影響預覽' })
          if (!pvh) { this.msg = '已取消發布'; this.busy = false; return }
          pubBody.preview_hash = pvh
        }
        var r = await this._j(this._base() + '/publish?scope=company', { method: 'POST', body: JSON.stringify(pubBody) })
        if (!r.ok) { this._mark(r.d.problems || []); this.msg = '發布失敗：' + (r.d.detail || r.status); this.busy = false; return }
        this.note = ''
        var pend = r.d && r.d.pending === true
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
        var restBody = {}
        if (window.MotrixDefGovernance && window.MotrixDefGovernance.previewRestore && await window.MotrixDefGovernance.available('attachment_slot')) {
          var rvh = await window.MotrixDefGovernance.previewRestore({ kind: 'attachment_slot', key: this._key(), scope: 'company' }, version)
          if (rvh) restBody.preview_hash = rvh
        }
        var r = await this._j(this._base() + '/restore/' + version + '?scope=company', { method: 'POST', body: JSON.stringify(restBody) })
        if (!r.ok) { this._mark(r.d.problems || []); this.msg = '還原失敗：' + (r.d.detail || r.status); this.busy = false; return }
        var pend = r.d && r.d.pending === true
        if (!pend && this.defs.draft) await this._j(this._base() + '/draft?scope=company', { method: 'DELETE' })
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
    if (document.getElementById('as-editor')) return
    if (!document.getElementById('as-editor-css')) {
      var st = document.createElement('style'); st.id = 'as-editor-css'; st.textContent = CSS
      document.head.appendChild(st)
    }
    var wrap = document.createElement('div')
    wrap.innerHTML = tpl()
    document.body.appendChild(wrap.firstChild)
  }

  window.MotrixAttachmentSlots = {
    /** 頁面在設定請求裡看到旗標開啟、且是最高管理者時呼叫一次。其他人／旗標關閉 ⇒ 不呼叫，這個檔什麼都不做。 */
    mount: function (c) {
      cfg = c
      if (session().role !== 'superadmin') return false
      mountEditor()
      return true
    },
    config: function () { return cfg },
    component: component,
    /** 頁面上的「附件種類」按鈕呼叫。 */
    openEditor: function () {
      var el = document.getElementById('as-editor')
      if (!el || !window.Alpine) return
      window.Alpine.$data(el).start()
    },
  }
})()
