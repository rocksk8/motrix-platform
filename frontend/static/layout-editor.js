/* layout-editor.js — P9 拖曳排版器（CUSTOMIZATION-SPEC §8.2；同頁編輯模式）。
 *
 * 頁面放一個 <span data-layout-editor-slot></span>（通常在標題旁）並先呼叫 MotrixLayout.init(...)。
 * 超級管理員才會看到「編輯版面」（後端 /api/definitions/… 另外守門）；按下去 ⇒ 同一頁右側出現排版面板，
 * 頁面本身即時顯示草稿的樣子（MotrixLayout.show(state, 'edit')）。
 *
 * 只能動 GET /api/layout/{模組} 帶回的可自訂點（catalog.layout_points，後端已過濾）——
 * 面板上每一個可以動的東西都來自 pageModel(points)，**程式沒提供的選項不會出現**。
 * 狀態 ⇒ 操作一律經 MotrixCustomLayout.compileOps（與執行時同一份規則）。
 *
 * 流程：選套用範圍（公司預設／某角色）⇒ 拖曳、隱藏、改名 ⇒ 存草稿 ⇒ 看差異 ⇒ 發布（先經後端 check_layout，
 * 問題依位置標回面板）⇒ 版本清單可以還原任一版。右上角「以角色預覽」看某角色目前的已發布版面。
 * 行動版：面板只在桌機（≥1024px）開；發布後的版面照常在手機上顯示。
 *
 * e2e 等待點：#ml-editor 的 data-busy（'0'／'1'）與 data-state（idle／saved／problems／published／restored）。
 */
;(function () {
  var L = window.MotrixCustomLayout
  var ML = function () { return window.MotrixLayout }

  var CSS = [
    '[x-cloak]{display:none!important}.ml-edit-btn{margin-left:10px;vertical-align:middle}',
    '@media (max-width:1023px){.ml-edit-btn{display:none!important}}',
    '#ml-editor{position:fixed;top:0;right:0;bottom:0;width:380px;z-index:1200;background:var(--bg-card,#fff);',
    'border-left:1px solid var(--border-light,#ddd);box-shadow:-8px 0 24px rgba(0,0,0,.08);display:flex;flex-direction:column;font-size:12px}',
    '.ml-ed__head{padding:12px 14px;border-bottom:1px solid var(--border-light,#ddd);display:flex;flex-direction:column;gap:8px}',
    '.ml-ed__row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.ml-ed__row label{color:var(--text-secondary,#666)}',
    '.ml-ed__body{flex:1;overflow:auto;padding:10px 14px}.ml-ed__foot{padding:10px 14px;border-top:1px solid var(--border-light,#ddd)}',
    '.ml-ed__sec{margin-bottom:14px}.ml-ed__h{font-weight:600;font-size:12px;margin:6px 0}.ml-ed__sub{color:var(--text-dim,#888);font-size:11px}',
    '.ml-ed__item{display:flex;align-items:center;gap:6px;padding:4px 6px;border:1px solid var(--border-light,#e5e5e5);border-radius:6px;',
    'margin:3px 0;background:var(--bg,#fafafa);cursor:grab}.ml-ed__item.is-hidden{opacity:.55}',
    '.ml-ed__item.is-bad{border-color:var(--danger,#dc2626);background:var(--danger-light,#fef2f2)}',
    '.ml-ed__item input[type=text]{flex:1;min-width:0;font-size:12px;padding:2px 6px;border:1px solid var(--border-light,#ddd);border-radius:4px}',
    '.ml-ed__item button{border:1px solid var(--border-light,#ddd);background:none;border-radius:4px;cursor:pointer;padding:0 6px}',
    '.ml-ed__prob{color:var(--danger,#dc2626);font-size:11px;margin:0 0 4px 6px}',
    '.ml-ed__drop{min-height:10px;border:1px dashed transparent;border-radius:6px;padding:2px}.ml-ed__drop.is-over{border-color:var(--accent,#2563eb)}',
    '.ml-ed__diff li{margin:2px 0}.ml-ed__ver{display:flex;justify-content:space-between;gap:6px;padding:3px 0;border-bottom:1px dashed var(--border-light,#eee)}',
    '.ml-ed__banner{background:var(--warning-light,#fffbeb);color:var(--warning,#b45309);padding:6px 8px;border-radius:6px}',
    'body.ml-editing .app-shell{margin-right:380px}',
  ].join('')

  function tpl() {
    return '' +
'<div id="ml-editor" x-data="MotrixLayoutEditor.component()" x-show="open" x-cloak :data-busy="(busy || loading) ? \'1\' : \'0\'" :data-state="state" :data-scope="scope" :data-loaded-scope="loadedScope" :data-loads-done="loadsDone" :data-load-error="loadError ? \'1\' : \'0\'">' +
' <div class="ml-ed__head">' +
'  <div class="ml-ed__row" style="justify-content:space-between"><strong>編輯版面</strong>' +
'   <span class="ml-ed__row"><label>以角色預覽</label><select data-testid="ml-preview-role" x-model="previewRole" @change="previewAs()" :disabled="loading">' +
'    <option value="">（編輯中的草稿）</option><template x-for="r in roles" :key="r.key"><option :value="r.key" x-text="r.label"></option></template></select>' +
'   <button type="button" class="btn btn-ghost btn-sm" data-testid="ml-close" @click="close()">關閉</button></span></div>' +
'  <div class="ml-ed__row"><label>套用範圍</label><select data-testid="ml-scope" x-model="scope" @change="loadScope()">' +
'   <option value="company">公司預設</option><template x-for="r in roles" :key="r.key"><option :value="\'role:\' + r.key" x-text="\'角色：\' + r.label"></option></template></select>' +
'   <span class="ml-ed__sub" x-text="startNote"></span></div>' +
'  <div class="ml-ed__banner" x-show="previewRole" x-text="\'以「\' + roleLabel(previewRole) + \'」預覽已發布的版面（唯讀）\'"></div>' +
' </div>' +
' <div class="ml-ed__body" x-show="work" x-effect="$el.inert = busy || loading" :aria-busy="String(busy || loading)">' +
'  <template x-if="generalProblems.length"><div class="ml-ed__prob" data-testid="ml-problems"><template x-for="p in generalProblems"><div x-text="p"></div></template></div></template>' +
// 列表
'  <template x-for="lk in listKeys()" :key="lk"><div class="ml-ed__sec" :data-testid="\'ml-list-\' + lk">' +
'   <div class="ml-ed__h" x-text="\'列表：\' + work.lists[lk].label"></div>' +
'   <div class="ml-ed__drop" @dragover.prevent @drop="drop(\'list:\' + lk, work.lists[lk].columns.length)">' +
'   <template x-for="(c, i) in work.lists[lk].columns" :key="c.id"><div>' +
'    <div class="ml-ed__item" draggable="true" :data-point-id="c.id" :data-field="c.field" :class="{\'is-hidden\': !c.visible, \'is-bad\': prob(c.id)}"' +
'         @dragstart="drag(\'list:\' + lk, i)" @dragover.prevent @drop.stop="drop(\'list:\' + lk, i)">' +
'     <input type="checkbox" title="顯示" :checked="c.visible" :disabled="c.core" @change="c.visible = $event.target.checked; sync()">' +
'     <template x-if="c.core"><span style="flex:1" x-text="c.label + \'（核心）\'"></span></template>' +
'     <template x-if="!c.core"><input type="text" :value="c.label" @change="relabel(c, $event.target.value)"></template>' +
'     <button type="button" title="上移" @click="mv(work.lists[lk].columns, i, -1)">↑</button><button type="button" title="下移" @click="mv(work.lists[lk].columns, i, 1)">↓</button></div>' +
'    <div class="ml-ed__prob" x-show="prob(c.id)" x-text="prob(c.id)"></div></div></template></div></div></template>' +
// 表單
'  <template x-for="fk in formKeys()" :key="fk"><div class="ml-ed__sec" :data-testid="\'ml-form-\' + fk">' +
'   <div class="ml-ed__h" x-text="\'表單：\' + work.forms[fk].label"></div>' +
'   <template x-for="(s, si) in work.forms[fk].sections" :key="s.id"><div style="margin:0 0 8px 0">' +
'    <div class="ml-ed__item" :data-point-id="s.id" :class="{\'is-bad\': prob(s.id)}" style="background:transparent">' +
'     <span class="ml-ed__sub">區塊</span><input type="text" :value="s.label" @change="relabel(s, $event.target.value)">' +
'     <button type="button" title="區塊上移" @click="mv(work.forms[fk].sections, si, -1)">↑</button><button type="button" title="區塊下移" @click="mv(work.forms[fk].sections, si, 1)">↓</button></div>' +
'    <div class="ml-ed__prob" x-show="prob(s.id)" x-text="prob(s.id)"></div>' +
'    <div class="ml-ed__drop" style="margin-left:14px" :data-section="s.key" @dragover.prevent @drop="drop(\'form:\' + fk + \':\' + si, s.fields.length)">' +
'    <template x-for="(f, i) in s.fields" :key="f.id"><div>' +
'     <div class="ml-ed__item" draggable="true" :data-point-id="f.id" :data-field="f.field" :class="{\'is-hidden\': !f.visible, \'is-bad\': prob(f.id)}"' +
'          @dragstart="drag(\'form:\' + fk + \':\' + si, i)" @dragover.prevent @drop.stop="drop(\'form:\' + fk + \':\' + si, i)">' +
'      <input type="checkbox" title="顯示" :checked="f.visible" :disabled="f.core" @change="f.visible = $event.target.checked; sync()">' +
'      <template x-if="f.core"><span style="flex:1" x-text="f.label + \'（核心）\'"></span></template>' +
'      <template x-if="!f.core"><input type="text" :value="f.label" @change="relabel(f, $event.target.value)"></template>' +
'      <button type="button" title="上移" @click="mv(s.fields, i, -1)">↑</button><button type="button" title="下移" @click="mv(s.fields, i, 1)">↓</button>' +
'      <select title="移到區塊" x-show="work.forms[fk].sections.length > 1" @change="toSection(fk, si, i, +$event.target.value); $event.target.value = \'\'">' +
'       <option value="">移到…</option><template x-for="(t, ti) in work.forms[fk].sections" :key="t.id"><option :value="ti" x-show="ti !== si" x-text="t.label"></option></template></select></div>' +
'     <div class="ml-ed__prob" x-show="prob(f.id)" x-text="prob(f.id)"></div></div></template></div></div></template></div></template>' +
// 按鈕、頁內選單、匯出
'  <template x-for="g in itemGroups()" :key="g.key"><div class="ml-ed__sec" :data-testid="\'ml-\' + g.key">' +
'   <div class="ml-ed__h" x-text="g.title"></div>' +
'   <div class="ml-ed__sub" x-show="!work[g.key].length" x-text="g.empty"></div>' +
'   <div class="ml-ed__drop" @dragover.prevent @drop="drop(g.key, work[g.key].length)">' +
'   <template x-for="(a, i) in work[g.key]" :key="a.id"><div>' +
'    <div class="ml-ed__item" draggable="true" :data-point-id="a.id" :class="{\'is-hidden\': a.hidden, \'is-bad\': prob(a.id)}"' +
'         @dragstart="drag(g.key, i)" @dragover.prevent @drop.stop="drop(g.key, i)">' +
'     <input type="checkbox" title="顯示" :checked="!a.hidden" @change="a.hidden = !$event.target.checked; sync()">' +
'     <input type="text" :value="a.label" @change="relabel(a, $event.target.value)">' +
'     <button type="button" title="上移" @click="mv(work[g.key], i, -1)">↑</button><button type="button" title="下移" @click="mv(work[g.key], i, 1)">↓</button></div>' +
'    <template x-if="g.key === \'menus\'"><div style="margin-left:14px"><template x-for="(it, j) in a.items" :key="it"><div class="ml-ed__item" :data-point-id="it">' +
'     <span style="flex:1" x-text="actionLabel(it)"></span><button type="button" @click="mv(a.items, j, -1)">↑</button><button type="button" @click="mv(a.items, j, 1)">↓</button></div></template></div></template>' +
'    <div class="ml-ed__prob" x-show="prob(a.id)" x-text="prob(a.id)"></div></div></template></div></div></template>' +
// 輸出版型
'  <div class="ml-ed__sec" data-testid="ml-outputs"><div class="ml-ed__h">輸出版型</div>' +
'   <div class="ml-ed__sub" x-show="!work.outputs.length">這個模組沒有登記輸出版型。</div>' +
'   <template x-for="o in work.outputs" :key="o.id"><div class="ml-ed__item" :data-point-id="o.id" :class="{\'is-bad\': prob(o.id)}"><span style="flex:1" x-text="o.label"></span>' +
'    <select x-model="o.template" @change="sync()"><template x-for="t in o.templates" :key="t"><option :value="t" x-text="t"></option></template></select></div></template></div>' +
// 側欄
'  <div class="ml-ed__sec" data-testid="ml-sidebar"><div class="ml-ed__h">側欄項目</div>' +
'   <div class="ml-ed__sub" x-show="!work.sidebar">這一頁沒有宣告側欄項目。</div>' +
'   <template x-if="work.sidebar"><div>' +
'    <div class="ml-ed__item" :data-point-id="work.sidebar.id" :class="{\'is-hidden\': work.sidebar.hidden, \'is-bad\': prob(work.sidebar.id)}">' +
'     <input type="checkbox" title="顯示" :checked="!work.sidebar.hidden" @change="work.sidebar.hidden = !$event.target.checked; sync()">' +
'     <span style="flex:1" x-text="work.sidebar.label"></span>' +
'     <select title="群組內位置" @change="work.sidebar.index = ($event.target.value === \'\' ? null : +$event.target.value); sync()">' +
'      <option value="" :selected="work.sidebar.index === null">原位置</option>' +
'      <template x-for="(it, j) in sidebarGroup" :key="j"><option :value="j" :selected="work.sidebar.index === j" x-text="\'第 \' + (j + 1) + \' 項\'"></option></template></select></div>' +
'    <div class="ml-ed__sub">預覽（群組「<span x-text="sidebarGroupLabel"></span>」）：實際側欄等選單改由 MOTRIX_MENU 產生（C4）後才會套用。</div>' +
'    <ol data-testid="ml-sidebar-preview" style="margin:4px 0 0 18px"><template x-for="it in sidebarPreview()" :key="it.href"><li x-text="it.label" :style="it.self ? \'font-weight:600\' : \'\'"></li></template></ol>' +
'   </div></template></div>' +
// 差異與版本
'  <div class="ml-ed__sec" x-show="diffShown" data-testid="ml-diff"><div class="ml-ed__h">與目前發布版的差異</div>' +
'   <div class="ml-ed__sub" x-show="!diffLines.length">沒有差異。</div><ul class="ml-ed__diff"><template x-for="d in diffLines"><li x-text="d"></li></template></ul></div>' +
'  <div class="ml-ed__sec" data-testid="ml-versions"><div class="ml-ed__h">版本（<span x-text="scopeLabel()"></span>）</div>' +
'   <div class="ml-ed__sub" x-show="!published().length">還沒有發布過（目前是程式預設）。</div>' +
'   <template x-for="v in published()" :key="v.version"><div class="ml-ed__ver" :data-version="v.version">' +
'    <span x-text="\'第 \' + v.version + \' 版 \' + (v.published_at || \'\').slice(0, 16).replace(\'T\', \' \') + (v.note ? \'・\' + v.note : \'\')"></span>' +
'    <button type="button" class="btn btn-ghost btn-sm" @click="restore(v.version)" :disabled="busy || loading">還原</button></div></template></div>' +
' </div>' +
' <div class="ml-ed__foot"><div class="ml-ed__row">' +
'  <button type="button" class="btn btn-ghost btn-sm" data-testid="ml-save" @click="saveDraft()" :disabled="busy || loading || !!previewRole">存草稿</button>' +
'  <button type="button" class="btn btn-ghost btn-sm" data-testid="ml-diff-btn" @click="showDiff()" :disabled="busy || loading">看差異</button>' +
'  <button type="button" class="btn btn-primary btn-sm" data-testid="ml-publish" @click="publish()" :disabled="busy || loading || !!previewRole">發布</button>' +
'  <button type="button" class="btn btn-ghost btn-sm" x-show="defs.draft" @click="discard()" :disabled="busy || loading">捨棄草稿</button></div>' +
'  <div class="ml-ed__row" style="margin-top:6px"><input type="text" data-testid="ml-note" x-model="note" placeholder="發布說明（選填）" style="flex:1;font-size:12px;padding:3px 6px">' +
'  </div><div style="margin-top:6px" data-testid="ml-msg" x-text="msg"></div></div>' +
'</div>'
  }

  function component() {
    return {
      open: false, busy: false, state: 'idle', msg: '', note: '', loadedScope: '', _scopeSeq: 0, loadsDone: 0, loading: false, loadError: '',
      scope: 'company', roles: [], previewRole: '', startNote: '',
      defs: { draft: null, latest: null, versions: [] },
      work: null, lastOps: [], probs: {}, generalProblems: [],
      diffShown: false, diffLines: [], sidebarGroup: [], sidebarGroupLabel: '', _drag: null,

      _key: function () { return 'module:' + ML().config().module },
      _base: function () { return '/api/definitions/layout/' + encodeURIComponent(this._key()) },
      _pts: function () { return this.$store.layout.points },
      _page: function () { return ML().config().page },
      async _j(url, opt) {
        var r = await fetch(url, Object.assign({ headers: ML().headers() }, opt || {}))
        var d = await r.json().catch(function () { return {} })
        return { ok: r.ok, status: r.status, d: d }
      },

      async start() {
        if (window.innerWidth < 1024) { alert('排版器只在桌機使用（畫面寬度至少 1024px）。發布後的版面在手機上照常顯示。'); return }
        if (!this.$store.layout.ready) { alert('版面設定還沒載入完成，稍後再試。'); return }
        this.open = true
        document.body.classList.add('ml-editing')
        if (!this.roles.length) {
          var r = await this._j('/api/settings/role-labels')
          var labels = r.ok ? r.d : {}
          this.roles = Object.keys(labels).map(function (k) { return { key: k, label: labels[k] } })
        }
        await this.loadSidebar()
        await this.loadScope()
      },
      close() {
        this.open = false
        this.previewRole = ''
        document.body.classList.remove('ml-editing')
        ML().show(null)
      },
      roleLabel(k) { var r = this.roles.filter(function (x) { return x.key === k })[0]; return r ? r.label : k },
      scopeLabel() { return this.scope === 'company' ? '公司預設' : '角色：' + this.roleLabel(this.scope.slice(5)) },
      published() { return (this.defs.versions || []).filter(function (v) { return v.status === 'published' }) },
      listKeys() { return this.work ? Object.keys(this.work.lists) : [] },
      formKeys() { return this.work ? Object.keys(this.work.forms) : [] },
      itemGroups() {
        return [{ key: 'actions', title: '按鈕', empty: '這一頁沒有登記按鈕。' },
                { key: 'menus', title: '頁內選單', empty: '這一頁沒有登記頁內選單。' },
                { key: 'exports', title: '匯出按鈕', empty: '這一頁沒有登記匯出按鈕。' }]
      },
      actionLabel(id) { var a = (this.work.actions || []).filter(function (x) { return x.id === id })[0]; return a ? a.label : id },
      prob(id) { return this.probs[id] || '' },

      async loadScope() {
        // O7：每次切換範圍取一個序號；較早發出、較晚回來的回應不可以蓋掉後來選的範圍（連切兩次時）。
        // 載入用自己的旗標 loading（不共用 busy，AUDIT-B-host-O7 M-1）；只有最新那一趟可以清掉它。
        // 讀不到（斷線、非 2xx）⇒ 明說並維持鎖定，不可以當成「沒有版面」顯示程式預設讓人照樣發布（S-1）。
        // e2e 等待終點：每一趟結束（含被較新的切換取代而放棄、含失敗）loadsDone 都 +1。
        var seq = ++this._scopeSeq
        var want = this.scope
        this.loading = true
        this.loadError = ''
        this.loadedScope = ''
        this.previewRole = ''
        this.probs = {}; this.generalProblems = []; this.diffShown = false; this.msg = ''
        try {
          var r = await this._j(this._base() + '?scope=' + encodeURIComponent(want))
          if (seq !== this._scopeSeq) return
          if (!r.ok) throw new Error('HTTP ' + r.status)
          var defs = r.d, ops = [], note
          if (defs.draft) { ops = defs.draft.body.ops || []; note = '從草稿繼續' }
          else if (defs.latest) { ops = defs.latest.body.ops || []; note = '從第 ' + defs.latest.version + ' 版開始' }
          else if (want !== 'company') {
            var c = await this._j(this._base() + '?scope=company')
            if (seq !== this._scopeSeq) return
            if (!c.ok) throw new Error('公司預設 HTTP ' + c.status)
            ops = c.d.latest ? (c.d.latest.body.ops || []) : []
            note = '這個角色還沒有覆寫：以公司預設為起點'
          } else note = '以程式預設為起點'
          this.defs = defs
          this.startNote = note
          this.work = L.applyOps(this._pts(), this._page(), ops).state
          this.sync()
          this.state = 'idle'
          this.loadedScope = want
          this.loading = false
        } catch (e) {
          if (seq !== this._scopeSeq) return
          this.state = 'error'
          this.loadError = '讀取「' + want + '」的版面失敗（' + (e && e.message || e) + '），編輯已鎖定；請重新選擇範圍再試'
          this.msg = this.loadError
          // loading 維持 true：編輯區保持 inert、發布不可按——讀不到不等於沒有
        } finally {
          this.loadsDone++
        }
      },
      sync() { if (!this.previewRole) ML().show(L.clone(this.work), 'edit') },
      mv(arr, i, dir) {
        var j = i + dir
        if (j < 0 || j >= arr.length) return
        var t = arr[i]; arr.splice(i, 1); arr.splice(j, 0, t)
        this.sync()
      },
      relabel(obj, text) {
        var v = (text || '').trim()
        if (!v) { this.msg = '標籤不可以是空白'; return }
        obj.label = v
        this.sync()
      },
      toSection(fk, si, i, ti) {
        if (isNaN(ti)) return
        var secs = this.work.forms[fk].sections
        var f = secs[si].fields.splice(i, 1)[0]
        secs[ti].fields.push(f)
        this.sync()
      },
      _arr(group) {
        var p = group.split(':')
        if (p[0] === 'list') return this.work.lists[p[1]].columns
        if (p[0] === 'form') return this.work.forms[p[1]].sections[+p[2]].fields
        return this.work[group]
      },
      drag(group, i) { this._drag = { group: group, i: i } },
      drop(group, i) {
        var d = this._drag
        this._drag = null
        if (!d) return
        var sameForm = d.group.split(':').slice(0, 2).join(':') === group.split(':').slice(0, 2).join(':')
        if (d.group !== group && !(group.indexOf('form:') === 0 && sameForm)) return   // 只能在同一個容器（表單內可跨區塊）
        var from = this._arr(d.group), to = this._arr(group)
        var x = from.splice(d.i, 1)[0]
        if (from === to && d.i < i) i -= 1
        to.splice(Math.min(i, to.length), 0, x)
        this.sync()
      },

      async loadSidebar() {
        var r = await this._j('/api/platform/menu')
        var page = this._page()
        var self = this
        ;((r.ok && r.d.groups) || []).forEach(function (g) {
          if (g.items.some(function (it) { return it.href === page })) { self.sidebarGroup = g.items; self.sidebarGroupLabel = g.label }
        })
      },
      sidebarPreview() {
        var page = this._page(), sb = this.work && this.work.sidebar
        var items = this.sidebarGroup.map(function (it) { return { href: it.href, label: it.label, self: it.href === page } })
        if (!sb) return items
        var me = items.filter(function (x) { return x.self })[0]
        var rest = items.filter(function (x) { return !x.self })
        if (!me || sb.hidden) return rest
        var at = sb.index === null ? items.indexOf(me) : Math.min(sb.index, rest.length)
        rest.splice(at, 0, me)
        return rest
      },

      _mark(problems) {
        var ops = this.lastOps, probs = {}, general = []
        ;(problems || []).forEach(function (p) {
          var m = /^ops\[(\d+)\]/.exec(p.path || '')
          var op = m ? ops[+m[1]] : null
          if (op && op.target) probs[op.target] = (probs[op.target] ? probs[op.target] + '；' : '') + p.message
          else general.push((p.path ? p.path + '：' : '') + p.message)
        })
        this.probs = probs
        this.generalProblems = general
        this.state = (problems && problems.length) ? 'problems' : this.state
      },
      async saveDraft() {
        this.busy = true
        this.lastOps = L.compileOps(this._pts(), this._page(), this.work)
        var r = await this._j(this._base() + '/draft?scope=' + encodeURIComponent(this.scope),
                              { method: 'PUT', body: JSON.stringify({ body: { ops: this.lastOps } }) })
        if (!r.ok) { this.msg = '存草稿失敗：' + (r.d.detail || r.status); this.busy = false; return false }
        this.defs.draft = r.d.draft
        this.probs = {}; this.generalProblems = []
        this.state = 'saved'
        this._mark(r.d.problems)
        this.msg = r.d.problems && r.d.problems.length ? '草稿已存，但有 ' + r.d.problems.length + ' 個問題（發布前要修正）' : '草稿已存'
        var v = await this._j(this._base() + '?scope=' + encodeURIComponent(this.scope))
        if (v.ok) this.defs = v.d
        this.busy = false
        return !(r.d.problems && r.d.problems.length)
      },
      showDiff() {
        var latest = this.defs.latest ? this.defs.latest.body.ops || [] : []
        this.diffLines = L.describeDiff(L.applyOps(this._pts(), this._page(), latest).state, this.work)
        this.diffShown = true
      },
      async publish() {
        this.showDiff()
        if (!(await this.saveDraft())) return
        this.busy = true
        // 發布前再問一次後端 check_layout（草稿存下去之後環境可能變了）
        var v = await this._j(this._base() + '/validate', { method: 'POST', body: JSON.stringify({ body: { ops: this.lastOps } }) })
        if (!v.ok || (v.d.problems || []).length) {
          this._mark(v.d.problems || [{ path: '', message: '驗證失敗（HTTP ' + v.status + '）' }])
          this.msg = '有問題，沒有發布'
          this.busy = false
          return
        }
        var r = await this._j(this._base() + '/publish?scope=' + encodeURIComponent(this.scope),
                              { method: 'POST', body: JSON.stringify({ note: this.note }) })
        if (!r.ok) {
          this._mark(r.d.problems || [])
          this.msg = '發布失敗：' + (r.d.detail || r.status)
          this.busy = false
          return
        }
        this.note = ''
        await ML().reload()
        await this.loadScope()
        this.busy = false               // loadScope 不再清 busy（它用自己的 loading）⇒ 動作自己解鎖
        if (this.loadError) return      // 發布成功但重新載入失敗：狀態留在 error（已說明），不標成已發布的乾淨狀態
        this.msg = '已發布第 ' + r.d.version + ' 版（' + this.scopeLabel() + '）'
        this.state = 'published'
      },
      async restore(version) {
        if (this.defs.draft && !confirm('還原會捨棄這個範圍目前的草稿，確定要還原第 ' + version + ' 版？')) return
        this.busy = true
        var r = await this._j(this._base() + '/restore/' + version + '?scope=' + encodeURIComponent(this.scope),
                              { method: 'POST', body: JSON.stringify({}) })
        if (!r.ok) { this._mark(r.d.problems || []); this.msg = '還原失敗：' + (r.d.detail || r.status); this.busy = false; return }
        if (this.defs.draft) await this._j(this._base() + '/draft?scope=' + encodeURIComponent(this.scope), { method: 'DELETE' })
        await ML().reload()
        await this.loadScope()
        this.busy = false
        if (this.loadError) return
        this.msg = '已把第 ' + version + ' 版還原成第 ' + r.d.version + ' 版'
        this.state = 'restored'
      },
      async discard() {
        this.busy = true
        await this._j(this._base() + '/draft?scope=' + encodeURIComponent(this.scope), { method: 'DELETE' })
        await this.loadScope()
        this.busy = false
        if (this.loadError) return
        this.msg = '草稿已捨棄'
      },
      async previewAs() {
        if (!this.previewRole) { this.sync(); return }
        this.busy = true
        try {
          var d = await ML().fetchLayout(this.previewRole)
          ML().show(L.applyOps(d.points, this._page(), d.ops).state, 'preview', this.roleLabel(this.previewRole) + '（' + d.source + '）')
          this.msg = '預覽：' + this.roleLabel(this.previewRole) + ' 目前套用 ' + d.source
        } catch (e) { this.msg = '預覽失敗（' + e.message + '）' }
        this.busy = false
      },
    }
  }

  window.MotrixLayoutEditor = { component: component }

  document.addEventListener('alpine:init', function () {
    var sess = window.MotrixLayout && window.MotrixLayout.session()
    if (!sess || sess.role !== 'superadmin') return          // 只有超級管理員看得到（後端另外守門）
    var slot = document.querySelector('[data-layout-editor-slot]')
    if (!slot) return
    var st = document.createElement('style')
    st.id = 'ml-editor-css'
    st.textContent = CSS
    document.head.appendChild(st)
    var wrap = document.createElement('div')
    wrap.innerHTML = tpl()
    document.body.appendChild(wrap.firstChild)
    slot.innerHTML = '<button type="button" class="btn btn-ghost btn-sm ml-edit-btn" data-testid="ml-edit-open" x-data'
      + ' x-show="$store.layout.ready" @click="Alpine.$data(document.getElementById(\'ml-editor\')).start()">編輯版面</button>'
  })
})()
