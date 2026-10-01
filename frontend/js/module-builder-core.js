// module-builder-core.js — 狀態、開啟／存檔、問題標示、基本、導覽（拆自 module-builder.html）
(function () {
  window.MotrixMB.parts.push(function (MB) {
    var KEY_RE = MB.KEY_RE, FIELD_KEY_RE = MB.FIELD_KEY_RE, TYPE_LABELS = MB.TYPE_LABELS, BLOCK_LABELS = MB.BLOCK_LABELS, PARAM_LABELS = MB.PARAM_LABELS,
        FORMAT_LABELS = MB.FORMAT_LABELS, NAV = MB.NAV, TYPE_ICONS = MB.TYPE_ICONS, TYPE_ICON_GENERIC = MB.TYPE_ICON_GENERIC, STEPS = MB.STEPS, clone = MB.clone
    return {
        L: window.MotrixCustomLayout, STEPS: STEPS, NAV: NAV, DEFAULT_GROUP: '自訂模組',
        navAnchor: '', thumbTick: 0, previewMissing: false, liveMsg: '',
        ready: false, errMsg: '', me: {}, catalog: {}, users: [], orgTree: [], published: [], menuGroups: ['自訂模組'], mountPoints: [], mountMax: 8,
        keyInput: '', keyErr: '', key: '', def: null, latestVersion: 0, versions: [],
        step: 1, tab: 'info', drawer: false, sel: null, dragOver: false,
        dirty: false, saving: false, saveState: 'idle', savedAt: '', _saveTimer: null, _loading: false, _inflight: null, flushLimitMs: 10000,
        draftProblems: [], publishProblems: [],
        numExample: '', numProblems: [], _numTimer: null,
        fxProblems: {}, fxState: {}, _fxTimers: {}, whenProblems: {}, whenState: {}, _whenTimers: {},
        previewHtml: '', previewProblems: [], previewState: '', previewBusy: false,
        diff: [], diffLoaded: false, publishNote: '', busy: false, _initDone: false, defReview: { mode: 'auto', active: false, reason: '', reviewers: [] },
        defs: [], defsLoaded: false, pdfBusy: false, pdfState: '', pdfBytes: 0,

        _hdr() {
          var s = {}
          try { s = JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) {}
          return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + (s.token || '') }
        },
        async api(method, url, body) {
          var r = await fetch(url, { method: method, headers: this._hdr(), body: body === undefined ? undefined : JSON.stringify(body) })
          var text = await r.text()
          var data = null
          try { data = text ? JSON.parse(text) : null } catch (e) { data = text }
          return { ok: r.ok, status: r.status, data: data }
        },
        defUrl() { return '/api/definitions/custom_module/' + encodeURIComponent(this.key) },

        async init() {
          if (this._initDone) return
          this._initDone = true
          this.loadPreviewLib()
          try { this.me = JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) { this.me = {} }
          if (this.me.role !== 'superadmin') { this.errMsg = '模組建構器僅限超級管理員使用'; return }
          var cat = await this.api('GET', '/api/custom-modules/catalog')
          if (!cat.ok) { this.errMsg = '讀取能力目錄失敗：' + ((cat.data && cat.data.detail) || cat.status); return }
          this.catalog = cat.data
          this.defReview = cat.data.defReview || this.defReview
          var res = await Promise.all([this.api('GET', '/api/users'), this.api('GET', '/api/org/tree'), this.api('GET', '/api/custom-modules')])
          this.users = res[0].ok ? (res[0].data || []).filter(function (u) { return u.active !== 0 }) : []
          this.orgTree = res[1].ok ? (res[1].data || []) : []
          this.published = res[2].ok ? (res[2].data || []) : []
          this.menuGroups = this.readMenuGroups()
          var mp = await this.api('GET', '/api/platform/mount-points')       // 掛載目標下拉；失敗＝清單空（欄位仍可用於已存的目標）
          if (mp.ok && mp.data) { this.mountPoints = mp.data.points || []; this.mountMax = mp.data.maxTabs || 8 }
          this.$watch('def', () => this.onDefChange())
          window.addEventListener('beforeunload', () => { if (this.dirty) this.saveDraft(true) })
          this.ready = true
          var k = new URLSearchParams(location.search).get('key')
          if (k) await this.openKey(k)
          else await this.loadDefs()
        },
        // ── 首頁：全部模組（含只有草稿的）與刪草稿（缺口 #5）──
        async loadDefs() {
          var r = await this.api('GET', '/api/definitions/custom_module')
          if (r.ok) this.defs = (r.data || []).filter(function (d) { return d.scope === 'company' })
          else this.errMsg = '讀取模組清單失敗：' + ((r.data && r.data.detail) || r.status)
          this.defsLoaded = true
        },
        moduleName(k) { var m = this.published.find(function (x) { return x.key === k }); return m ? (m.name || '') : '' },
        async deleteDraft(m) {
          if (this.busy || !m.hasDraft) return
          var msg = m.latestVersion
            ? '刪除「' + m.key + '」的草稿？未發布的修改會消失；已發布的第 ' + m.latestVersion + ' 版不受影響。'
            : '刪除「' + m.key + '」的草稿？這個模組從未發布，刪除後整個模組會從清單消失。'
          var ok = window.MotrixUI ? await window.MotrixUI.confirm(msg, { danger: true, okText: '刪除草稿' }) : window.confirm(msg)
          if (!ok) return
          this.busy = true; this.errMsg = ''
          try {
            var r = await this.api('DELETE', '/api/definitions/custom_module/' + encodeURIComponent(m.key) + '/draft?scope=company')
            if (!r.ok) { this.errMsg = '刪除草稿失敗：' + ((r.data && r.data.detail) || r.status); return }
            window.MotrixUI && window.MotrixUI.toast('已刪除 ' + m.key + ' 的草稿', { kind: 'ok' })
          } finally {
            this.busy = false
            this.defsLoaded = false
            await this.loadDefs()
          }
        },
        // 刪整個模組（所有版本）。有單據時後端回 409＋單據數，再二次確認才連單據一併刪
        async deleteModule(m) {
          if (this.busy) return
          var ui = window.MotrixUI
          var ask = async (msg, okText) => ui ? await ui.confirm(msg, { danger: true, okText: okText }) : window.confirm(msg)
          if (!await ask('刪除模組「' + m.key + '」？所有版本與草稿都會消失，無法復原。', '刪除模組')) return
          this.busy = true; this.errMsg = ''
          try {
            var url = '/api/definitions/custom_module/' + encodeURIComponent(m.key)
            var r = await this.api('DELETE', url)
            if (!r.ok && r.status === 409 && r.data && r.data.records) {
              if (!await ask('「' + m.key + '」已有 ' + r.data.records + ' 筆單據。連同單據一併刪除？（已入帳的模組仍會被拒絕）', '連同單據一併刪除')) return
              r = await this.api('DELETE', url + '?with_records=1')
            }
            if (!r.ok) { this.errMsg = '刪除模組失敗：' + ((r.data && r.data.detail) || r.status); return }
            ui && ui.toast('已刪除模組 ' + m.key, { kind: 'ok' })
            this.published = this.published.filter(function (x) { return x.key !== m.key })
          } finally {
            this.busy = false
            this.defsLoaded = false
            await this.loadDefs()
          }
        },
        readMenuGroups() {
          // 選單位置＝既有分組的顯示名稱（core/menu.py merge_custom 以名稱併組）。來源：伺服器宣告的 MOTRIX_MENU.groups
          // （與使用者版面無關、不等側欄渲染），再補側欄 DOM、已發布自訂模組用到的分組；最後一定有「自訂模組」。
          var out = []
          var add = function (t) { t = (t || '').trim(); if (t && out.indexOf(t) < 0) out.push(t) }
          var decl = (window.MOTRIX_MENU && window.MOTRIX_MENU.groups) || []
          decl.forEach(function (g) { add(g.label) })
          document.querySelectorAll('#app-mainnav .mnav__in > .mnav__grp > .mnav__top').forEach(function (el) { add(el.textContent) })
          ;(this.published || []).forEach(function (m) { add((m.menu || {}).group) })
          add(this.DEFAULT_GROUP)
          return out
        },
        // 下拉選項：目前模組已存的分組若已不在清單（分組改名／停用）仍要列出並標示，不可悄悄變成別組
        groupOptions() {
          var cur = ((this.def && this.def.menu) || {}).group || this.DEFAULT_GROUP
          return this.menuGroups.indexOf(cur) < 0 ? this.menuGroups.concat([cur]) : this.menuGroups
        },
        groupMissing() {
          var cur = ((this.def && this.def.menu) || {}).group || this.DEFAULT_GROUP
          return this.menuGroups.indexOf(cur) < 0
        },

        // ── 開啟模組 ──
        blankDef(key) {
          return {
            name: '', icon: '', menu: { group: this.DEFAULT_GROUP, order: 10 }, permission: 'custom.' + key,
            numbering: { prefix: '', date: (this.catalog.numberingDateFormats || ['YYYYMMDD'])[0], digits: 4 },
            fields: [],
            workflow: { initial: 'draft', states: [{ key: 'draft', label: '草稿' }, { key: 'done', label: '完成', final: true }],
                        transitions: [{ key: 'submit', label: '送出', from: 'draft', to: 'done' }] },
            ui: { form: { groups: [] }, list: { columns: [] } },
          }
        },
        normalize(d) {
          d.menu = d.menu || { group: this.DEFAULT_GROUP, order: 10 }
          d.numbering = d.numbering || { prefix: '', date: 'YYYYMMDD', digits: 4 }
          if (d.numbering.date === undefined) d.numbering.date = 'YYYYMMDD'
          if (d.numbering.digits === undefined) d.numbering.digits = 4
          d.fields = Array.isArray(d.fields) ? d.fields : []
          d.fields.forEach(function (f) { if (!f.dataClass) f.dataClass = 'T1' })
          d.workflow = d.workflow || { initial: '', states: [], transitions: [] }
          d.workflow.states = d.workflow.states || []
          d.workflow.transitions = d.workflow.transitions || []
          d.ui = d.ui || {}
          return d
        },
        async openKey(k) {
          this.keyErr = ''; this.errMsg = ''
          k = String(k || '').trim()
          if (!KEY_RE.test(k)) { this.keyErr = '代號只能用小寫英文、數字與底線，英文開頭（2～40 字）'; return }
          var r = await this.api('GET', '/api/definitions/custom_module/' + encodeURIComponent(k))
          if (!r.ok) { this.keyErr = '讀取定義失敗：' + ((r.data && r.data.detail) || r.status); return }
          if (!r.data.draft && !r.data.latest) { this.tplKey = k; this.tplChoice = true; return }      // 新模組：先挑範本（或空白）
          this._loading = true
          this.key = k
          this.latestVersion = r.data.latest ? r.data.latest.version : 0
          this.versions = r.data.versions || []
          var body = r.data.draft ? r.data.draft.body : r.data.latest.body
          this.destroyPreviews()
          this.def = this.normalize(clone(body))
          this.sel = null; this.step = 1; this.tab = 'info'; this.drawer = false; this.formMode = 'edit'; this.sideTab = 'props'
          this.draftProblems = []; this.publishProblems = []; this.fxProblems = {}; this.whenProblems = {}
          this.dirty = false; this.saveState = r.data.draft ? 'saved' : 'idle'
          try { var q = new URLSearchParams(location.search); q.set('key', k); history.replaceState(null, '', location.pathname + '?' + q.toString()) } catch (e) {}
          this.$nextTick(() => { this._loading = false; this.queueNumbering(); this.checkAllFormulas() })
          if (r.data.draft) this.validateNow()
        },
        // 新模組：以範本（body 給了）或空白開始；套用後與範本脫鉤，之後一切照草稿走
        async startBlank(k, body) {
          this.tplChoice = false
          var d = body ? clone(body) : this.blankDef(k)
          d.permission = 'custom.' + k
          this._loading = true
          this.destroyPreviews()
          this.key = k; this.latestVersion = 0; this.versions = []
          this.def = this.normalize(d)
          this.sel = null; this.step = 1; this.tab = 'info'; this.drawer = false; this.formMode = 'edit'; this.sideTab = 'props'
          this.draftProblems = []; this.publishProblems = []; this.fxProblems = {}; this.whenProblems = {}
          this.dirty = false; this.saveState = 'idle'
          try { var q = new URLSearchParams(location.search); q.set('key', k); history.replaceState(null, '', location.pathname + '?' + q.toString()) } catch (e) {}
          this.$nextTick(() => {
            this._loading = false; this.queueNumbering(); this.checkAllFormulas()
            this.dirty = true; this.saveState = 'dirty'; this.saveDraft()          // 範本／空白開始就先存成草稿
          })
        },
        cancelTemplate() { this.tplChoice = false; this.tplKey = ''; this.keyInput = '' },
        async closeModule() {
          var pending = this.dirty ? this.saveDraft() : null
          this.destroyPreviews()
          this.def = null; this.key = ''; this.keyInput = ''
          try { history.replaceState(null, '', location.pathname) } catch (e) {}
          this.defsLoaded = false
          if (pending) await pending
          await this.loadDefs()
        },

        // ── 自動存檔 ──
        onDefChange() {
          if (this._loading || !this.def) return
          this.dirty = true
          this.saveState = 'dirty'
          clearTimeout(this._saveTimer)
          this._saveTimer = setTimeout(() => this.saveDraft(), 700)
          this.queueNumbering()
          if (this.tab === 'info') this.queuePreview()
          if (this.drawer) this.diffLoaded = false
        },
        // 回傳「這一次存檔」的 Promise；已有一次在路上 ⇒ 排下一次，並回傳路上那一次
        saveDraft(keepalive) {
          if (!this.def || !this.key) return Promise.resolve()
          clearTimeout(this._saveTimer)
          if (this._inflight) { this._saveTimer = setTimeout(() => this.saveDraft(), 300); return this._inflight }
          var p = this._putDraft(keepalive)
          this._inflight = p
          p.then(() => { if (this._inflight === p) this._inflight = null })
          return p
        },
        async _putDraft(keepalive) {
          var snapshot = JSON.stringify(this.def)
          this.saving = true
          try {
            var r = await fetch(this.defUrl() + '/draft', { method: 'PUT', headers: this._hdr(), keepalive: !!keepalive,
                                                            body: JSON.stringify({ body: JSON.parse(snapshot) }) })
            var d = null
            try { d = await r.json() } catch (e) {}
            if (!r.ok) { this.saveState = 'error'; this.errMsg = '草稿存檔失敗：' + ((d && d.detail) || r.status); return }
            this.draftProblems = (d && d.problems) || []
            this.savedAt = new Date().toTimeString().slice(0, 8)
            // 存檔期間又改了 ⇒ 仍是 dirty，再排一次
            if (JSON.stringify(this.def) === snapshot) { this.dirty = false; this.saveState = 'saved' }
            else this._saveTimer = setTimeout(() => this.saveDraft(), 300)
          } catch (e) {
            this.saveState = 'error'
          } finally { this.saving = false }
        },
        // 發布／還原／看差異前把草稿存完：等「進行中那一次存檔」的回應（不輪詢）；
        // 上限 flushLimitMs（伺服器不回、或使用者一直在改）⇒ 標成存檔失敗，不默默放行
        async flushSave() {
          var deadline = Date.now() + this.flushLimitMs
          while (this.dirty || this._inflight) {
            var left = deadline - Date.now()
            if (left <= 0) {
              this.saveState = 'error'
              this.errMsg = '草稿存檔超過 ' + Math.round(this.flushLimitMs / 1000) + ' 秒沒有完成，已停止；請確認連線後再試'
              return false
            }
            var p = this._inflight || this.saveDraft()
            var timer = null
            await Promise.race([p, new Promise(function (res) { timer = setTimeout(res, left) })])
            clearTimeout(timer)
            if (this.saveState === 'error') return false
          }
          return this.saveState !== 'error'
        },
        async validateNow() {
          var r = await this.api('POST', this.defUrl() + '/validate', { body: this.def })
          if (r.ok) this.draftProblems = r.data.problems || []
        },
        saveLabel() {
          if (this.saveState === 'error') return '草稿存檔失敗'
          if (this.saving) return '存檔中…'
          if (this.dirty) return '有未存的修改'
          if (this.saveState === 'saved') return '草稿已自動存檔' + (this.savedAt ? '（' + this.savedAt + '）' : '')
          return '尚無草稿'
        },

        // ── 問題標示 ──
        allProblems() { return this.publishProblems.length ? this.publishProblems : this.draftProblems },
        stepOf(path) {
          path = String(path || '')
          if (/^fields/.test(path)) return 2
          if (/^ui/.test(path)) return 2                    // 版面與欄位同一步（② 表單）
          if (/^workflow/.test(path)) return 4
          if (/^output/.test(path)) return 5
          return 1
        },
        stepName(n) { var s = STEPS.find(function (x) { return x.n === n }); return s ? s.label : '' },
        stepProblems(n) { var self = this; return this.allProblems().filter(function (p) { return self.stepOf(p.path) === n }) },
        stepProblemCount(n) { return this.stepProblems(n).length },
        hasProblem(prefix) {
          return this.allProblems().some(function (p) {
            var path = String(p.path || '')
            return path === prefix || path.indexOf(prefix + '.') === 0 || path.indexOf(prefix + '[') === 0
          })
        },
        hasProblemExact(path) { return this.allProblems().some(function (p) { return p.path === path }) },
        problemsUnder(prefix) {
          return this.allProblems().filter(function (p) { var path = String(p.path || ''); return path === prefix || path.indexOf(prefix + '.') === 0 })
        },
        jumpTo(path) {
          this.drawer = false
          this.step = this.stepOf(path); this.tab = this.TAB_OF_STEP[this.step] || 'info'
          if (this.tab === 'form') this.sideTab = 'props'
          var m = /^fields\[(\d+)\]/.exec(path || '')
          if (m) this.sel = Number(m[1])
          this.$nextTick(() => {
            var sel = null
            var fm = /^fields\[(\d+)\]/.exec(path || ''), sm = /^workflow\.states\[(\d+)\]/.exec(path || ''), tm = /^workflow\.transitions\[(\d+)\]/.exec(path || '')
            if (fm) sel = '[data-field-index="' + fm[1] + '"]'
            else if (sm) sel = '[data-state-index="' + sm[1] + '"]'
            else if (tm) sel = '[data-transition-index="' + tm[1] + '"]'
            var el = sel ? document.querySelector(sel) : document.getElementById('mb-step-' + this.step)
            if (el && el.scrollIntoView) el.scrollIntoView({ block: 'center' })
          })
        },
        // 三個頁籤（作業資訊＝基本＋輸出、表單設計、流程設計＝流程＋簽核＋通知）＋頂列「發布」抽屜（同頁）。
        // 內部步驟號（1、2、4、5、6）保留為區段 id（#mb-step-N）與問題歸屬；沒有第 3 步。
        TAB_OF_STEP: { 1: 'info', 5: 'info', 2: 'form', 4: 'flow' },
        TAB_STEPS: { info: [1, 5], form: [2], flow: [4] },
        async goStep(n) {
          this.step = n
          if (n === 6) { this.drawer = true; await this.flushSave(); await this.loadDiff(); await this.reloadVersions(); return }
          this.tab = this.TAB_OF_STEP[n] || 'info'
          if (this.tab === 'info') this.previewOutput()
          if (this.tab === 'form') this.$nextTick(() => this.syncPreviews(JSON.stringify(this.def), this.sel, 2))
        },
        async goTab(t) { this.drawer = false; await this.goStep(t === 'form' ? 2 : (t === 'flow' ? 4 : 1)) },
        closeDrawer() { this.drawer = false },
        tabProblems(t) { var self = this; return (this.TAB_STEPS[t] || []).reduce(function (a, n) { return a.concat(self.stepProblems(n)) }, []) },
        tabProblemCount(t) { return this.tabProblems(t).length },
        totalProblemCount() { return this.allProblems().length },

        // ── ① 基本 ──
        // ── 掛載到內建頁面（方案 B）：掛載點清單來自 GET /api/platform/mount-points（只有最高管理者；已載入模組宣告的點）──
        mountPointId() { return ((this.def && this.def.mount) || {}).point || '' },
        mountDef() { var id = this.mountPointId(); return this.mountPoints.find(function (p) { return p.id === id }) || null },
        mountMissing() { return !!this.mountPointId() && !this.mountDef() },
        mountOptions() {
          // 已存的目標不在清單（模組停用／點被移除）⇒ 仍列出並標示，不悄悄換掉或清掉
          var id = this.mountPointId()
          return id && !this.mountDef() ? this.mountPoints.concat([{ id: id, label: '（目標不存在）', context: [] }]) : this.mountPoints
        },
        setMountPoint(id) {
          if (!id) { this.def.mount = undefined; return }
          var old = this.def.mount || {}
          var pt = this.mountPoints.find(function (p) { return p.id === id })
          // 換目標時 contextField 不一定仍適用 ⇒ 清空（label 沿用）
          var m = { point: id }
          if (old.label) m.label = old.label
          if (pt && pt.context && pt.context.length && old.contextField) m.contextField = old.contextField
          this.def.mount = m
        },
        setMount(k, v) {
          var m = Object.assign({}, this.def.mount || {}); m[k] = v
          if (k === 'label' && !v) delete m.label
          if (k === 'contextField' && !v) delete m.contextField
          this.def.mount = m
        },
        setMenu(k, v) { var m = Object.assign({}, this.def.menu || {}); m[k] = v; this.def.menu = m },
        dateLabel(d) { return d === '' ? '不分期（不含日期）' : (d === 'YYYYMM' ? '年月（每月重新計）' : (d === 'YYYYMMDD' ? '年月日（每日重新計）' : d)) },
        queueNumbering() {
          clearTimeout(this._numTimer)
          this._numTimer = setTimeout(() => this.previewNumbering(), 250)
        },
        async previewNumbering() {
          if (!this.def) return
          var r = await this.api('POST', '/api/custom-modules/numbering/preview', { numbering: this.def.numbering })
          if (r.ok) { this.numExample = r.data.example; this.numProblems = [] }
          else { this.numExample = ''; this.numProblems = (r.data && r.data.problems) || [{ message: (r.data && r.data.detail) || '預覽失敗' }] }
        },

        // ── 縮圖導覽／預覽（BUILDER-UX）──
        navOn(it) { return this.step === it.step && (it.step !== 4 || (this.navAnchor || 'mb-sec-workflow') === it.anchor) },
        async goNav(it) {
          this.navAnchor = it.anchor || ''
          if (this.step !== it.step) await this.goStep(it.step)
          if (it.anchor) this.$nextTick(function () {
            var el = document.getElementById(it.anchor)
            if (el && el.scrollIntoView) el.scrollIntoView({ block: 'start' })
          })
        },
        loadPreviewLib() {
          if (window.MotrixFormPreview) return
          var self = this
          var sc = document.createElement('script')
          sc.src = '../static/form-preview.js'
          sc.onload = function () { self.previewMissing = !window.MotrixFormPreview; self.destroyPreviews(); self.thumbTick++; self.syncPreviews(JSON.stringify(self.def), self.sel, self.step) }
          sc.onerror = function () { self.previewMissing = true }
          document.head.appendChild(sc)
        },
        drawThumb(el, kind, _tick) {
          // A 的 thumb() 畫；元件還沒載入 ⇒ 空白（不丟例外）
          var P = window.MotrixFormPreview
          if (!P || !P.thumb || !this.def) return
          try { P.thumb(el, JSON.parse(JSON.stringify(this.def)), { step: kind }) } catch (e) { /* 縮圖失敗不擋編輯 */ }
        },
        syncPreviews(json, sel, step) {
          // 草稿一變就同時更新右側的輸出預覽與列表預覽（A 的 render：mode 'output'／'list'，同頁兩個實例各自更新；節流 250ms）；
          // 只用 update()／setHighlight()——不重建 iframe、不搶畫布的焦點。表單不另外預覽：畫布就是表單
          if (step !== 2 || !this.def) return
          var P = window.MotrixFormPreview
          if (!P || !P.render) { if (P === undefined) return; this.previewMissing = true; return }
          var oh = document.getElementById('mb-output-host'), lh = document.getElementById('mb-list-host')
          if (!oh || !lh) return
          var hl = sel !== null && this.def.fields[sel] ? this.def.fields[sel].key : null
          clearTimeout(this._pvsTimer)
          this._pvsTimer = setTimeout(() => {
            try {
              var draft = JSON.parse(json)
              if (!this._pvOut) this._pvOut = P.render(oh, draft, { mode: 'output', key: this.key })
              else this._pvOut.update(draft)
              if (!this._pvList) this._pvList = P.render(lh, draft, { mode: 'list', highlight: hl })
              else { this._pvList.update(draft); if (this._pvList.setHighlight) this._pvList.setHighlight(hl) }
              this.thumbTick++
            } catch (e) { this.previewMissing = true }
          }, 250)
        },
        destroyPreviews() {
          clearTimeout(this._pvsTimer)
          ;[this._pvOut, this._pvList].forEach(function (p) { try { if (p && p.destroy) p.destroy() } catch (e) {} })
          this._pvOut = null; this._pvList = null
        },
        announce(msg) { this.liveMsg = ''; this.$nextTick(() => { this.liveMsg = msg }) },

    }
  })
})()

/** Alpine 元件：把各零件（core／form／flow／output）合併成一個物件（含 getter，用屬性描述子複製）。 */
function moduleBuilderPage() {
  var MB = window.MotrixMB
  var out = {}
  MB.parts.forEach(function (p) { Object.defineProperties(out, Object.getOwnPropertyDescriptors(p(MB))) })
  return out
}
