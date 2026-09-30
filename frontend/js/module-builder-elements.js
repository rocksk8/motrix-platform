// module-builder-elements.js — 建構器第三輪「表單設計」單頁：元件列（分組、搜尋）、屬性面板（依目錄的型別規格）、
// 明細表欄位編輯、預設值來源、金流性質、編輯／預覽切換、範本挑選。
// 型別、元件、屬性規格、範本一律來自 `GET /api/custom-modules/catalog`（fieldElements／fieldTypeSpecs／templates／…），頁面不寫死清單。
(function () {
  window.MotrixMB.parts.push(function (MB) {
    var clone = MB.clone
    var FIELD_KEY_RE = MB.FIELD_KEY_RE

    return {
      // ── 狀態 ──
      formMode: 'edit',          // 'edit'｜'preview'：畫布就地切成使用者填單視角（同一個畫布，不跳頁、不彈窗）
      sideTab: 'props',          // 右欄：'props'｜'output'｜'list'
      paletteQuery: '', groupClosed: {}, palOpen: false, sideOpen: false,
      previewRows: {},           // 預覽模式下明細表「新增一列」的假列數（只在畫面上，不進草稿）
      tplChoice: false, tplKey: '', tplBusy: false,

      // ── 編輯／預覽切換 ──
      setFormMode(m) {
        this.formMode = m === 'preview' ? 'preview' : 'edit'
        if (this.formMode === 'preview') { this.sideOpen = false; this.palOpen = false }
        this.announce(this.formMode === 'preview' ? '已切換到預覽（使用者填單的樣子）' : '已切換到編輯')
      },
      setSideTab(t) {
        this.sideTab = t
        if (t !== 'props') this.$nextTick(() => this.syncPreviews(JSON.stringify(this.def), this.sel, this.tab === 'form' ? 2 : 0))
      },
      selectField(i) { this.sel = i; this.sideTab = 'props'; if (window.innerWidth < 900) this.sideOpen = true },

      // ── 元件列（目錄的 fieldElements／elementGroups）──
      elements() { return this.catalog.fieldElements || [] },
      paletteGroups() {
        var q = String(this.paletteQuery || '').trim().toLowerCase()
        var els = this.elements().filter(function (e) { return !q || String(e.label).toLowerCase().indexOf(q) >= 0 || e.type.indexOf(q) >= 0 })
        return (this.catalog.elementGroups || []).map(function (g) {
          return { id: g.id, label: g.label, items: els.filter(function (e) { return e.group === g.id }) }
        }).filter(function (g) { return g.items.length })
      },
      isPrimaryElement(e) { return e.id === e.type },
      toggleGroup(id) { this.groupClosed = Object.assign({}, this.groupClosed, { [id]: !this.groupClosed[id] }) },
      addElementHere(id) {
        var e = this.elements().find(function (x) { return x.id === id })
        if (!e) return
        var j = this.addField(e.type, this.currentGroup(), null, e.preset)
        if (j < 0) return
        this.announce('已加入 ' + e.label + '，' + this.posText(this.sectionOf(this.def.fields[j].key)))
        this.sideTab = 'props'
      },
      elementLabel(t) {
        var e = this.elements().find(function (x) { return x.id === t }) || this.elements().find(function (x) { return x.type === t })
        return e ? e.label : (MB.TYPE_LABELS[t] || t)
      },

      // ── 畫布卡片的預覽模擬（編輯時停用；預覽模式可操作但不存）──
      mockKind(f) {
        var t = f.type
        if (t === 'formula') return 'ro'
        if (t === 'textarea') return 'textarea'
        if (t === 'radio') return 'radio'
        if (t === 'checkboxes') return 'checks'
        if (t === 'daterange') return 'range'
        if (t === 'table') return 'table'
        if (t === 'file' || t === 'image') return 'file'
        if (t === 'select' || t === 'multiselect' || t === 'checkbox' || t === 'ref') return 'select'
        return 'input'
      },
      mockInputType(f) { return f.type === 'number' ? 'number' : (f.type === 'date' ? (f.withTime ? 'datetime-local' : 'date') : 'text') },
      mockOptions(f) {
        if (f.type === 'checkbox') return ['是', '否']
        return (f.options && f.options.length) ? f.options : ['（選項）']
      },
      tableRows(f) { return Math.max(1, this.previewRows[f.key] || 1) },
      addPreviewRow(f) { this.previewRows = Object.assign({}, this.previewRows, { [f.key]: this.tableRows(f) + 1 }) },
      readableFx(f) { return this.L.formulaReadable(this.def, f) },

      // ── 屬性面板：依目錄型別規格產生（kind：text／int／number／bool／options／columns）──
      specOf(f) { return ((this.catalog.fieldTypeSpecs || {})[f.type] || {}).attrs || [] },
      genericAttrs(f) {
        // options／default／columns 各有專屬區塊；其餘照規格列
        return this.specOf(f).filter(function (a) { return ['options', 'default', 'columns'].indexOf(a.key) < 0 && a.kind !== 'options' && a.kind !== 'columns' })
      },
      hasOptions(f) { return this.specOf(f).some(function (a) { return a.kind === 'options' }) },
      attrValue(f, a) {
        var v = f[a.key]
        if (a.kind === 'bool') return v === true
        return v === undefined || v === null ? '' : v
      },
      setAttr(i, a, raw) {
        var f = Object.assign({}, this.def.fields[i])
        var v = raw
        if (a.kind === 'bool') v = raw === true ? true : null
        else if (a.kind === 'int' || a.kind === 'number') v = (raw === '' || raw === null || isNaN(Number(raw))) ? null : (a.kind === 'int' ? Math.trunc(Number(raw)) : Number(raw))
        else v = String(raw || '').trim() === '' ? null : raw
        if (v === null) delete f[a.key]; else f[a.key] = v
        this.def.fields.splice(i, 1, f)
      },
      // ── 誰看得到（欄位 access.visibleTo／選單 menu.visibleTo）：scope＝欄位索引（數字）或 'menu'；不勾＝所有人 ──
      visOf(scope) {
        var o = scope === 'menu' ? ((this.def.menu || {}).visibleTo) : (((this.def.fields[scope] || {}).access || {}).visibleTo)
        return { roles: (o && o.roles) || [], users: (o && o.users) || [] }
      },
      visHas(scope, kind, v) { return this.visOf(scope)[kind].indexOf(v) >= 0 },
      visSummary(scope) {
        var v = this.visOf(scope)
        if (!v.roles.length && !v.users.length) return '所有人（有這個模組權限的都看得到）'
        var self = this
        return '限：' + v.roles.map(function (r) { return self.roleLabel(r) }).concat(v.users.map(function (u) { return self.userLabel(u) })).join('、')
      },
      roleLabel(r) { return { superadmin: '最高管理者', admin: '管理員', sales: '業務', engineer: '工程師', viewer: '檢視者' }[r] || r },
      toggleVis(scope, kind, v, on) {
        var cur = this.visOf(scope)
        cur[kind] = cur[kind].filter(function (x) { return x !== v })
        if (on) cur[kind].push(v)
        var vis = (cur.roles.length || cur.users.length) ? { roles: cur.roles, users: cur.users } : null
        if (scope === 'menu') {
          var m = Object.assign({}, this.def.menu || {})
          if (vis) m.visibleTo = vis; else delete m.visibleTo
          this.def.menu = m
        } else {
          var f = Object.assign({}, this.def.fields[scope])
          var a = Object.assign({}, f.access || {})
          if (vis) a.visibleTo = vis; else delete a.visibleTo
          if (Object.keys(a).length) f.access = a; else delete f.access
          this.def.fields.splice(scope, 1, f)
        }
      },
      extChoices(f) { return f.type === 'image' ? ['jpg', 'png'] : ['jpg', 'png', 'pdf'] },
      toggleExt(i, e, on) {
        var f = Object.assign({}, this.def.fields[i])
        var cur = (f.accept || []).filter(function (x) { return x !== e })
        if (on) cur.push(e)
        if (cur.length) f.accept = cur; else delete f.accept
        this.def.fields.splice(i, 1, f)
      },
      optionsText(f) { return (f.options || []).join('\n') },
      setOptions(i, text) {
        var f = this.def.fields[i]
        f.options = String(text).split('\n').map(function (s) { return s.trim() }).filter(function (s, k, arr) { return s && arr.indexOf(s) === k })
      },

      // ── 預設值來源：固定值／填單當下（伺服器決定）／申請人 ──
      defaultTokens(f) {
        var out = []
        if (f.type === 'date') out.push({ v: 'today', l: f.withTime ? '填單當下（日期時間）' : '填單當下（今天）' })
        if (f.type === 'date' && f.withTime) { out = [{ v: 'now', l: '填單當下（日期時間）' }] }
        if (f.type === 'ref' && f.target === 'users') out.push({ v: 'requester', l: '申請人（自動帶入）' })
        return out
      },
      defaultMode(f) {
        var d = f.default
        if (d && typeof d === 'object' && d.$) return d.$
        return (d === undefined || d === null || d === '') ? 'none' : 'fixed'
      },
      setDefaultMode(i, mode) {
        var f = Object.assign({}, this.def.fields[i])
        if (mode === 'none') delete f.default
        else if (mode === 'fixed') { if (typeof f.default === 'object' || f.default === undefined) delete f.default }
        else f.default = { $: mode }
        this.def.fields.splice(i, 1, f)
      },

      // ── 複製（把手旁按鈕）──
      duplicateField(i) {
        var src = this.def.fields[i]
        if (!src) return
        var copy = clone(src)
        copy.key = this.nextKey(src.type)
        copy.label = (src.label || src.key) + ' 複本'
        if (copy.type === 'table') (copy.columns || []).forEach(function (c) { /* 列內欄 key 在表內唯一即可，沿用 */ })
        var s = this.sectionOf(src.key)
        this.def.fields.push(copy)
        var j = this.applyPlacement(copy.key, s ? s.gi : -1, s ? s.pos + 1 : null)
        this.announce('已複製「' + (src.label || src.key) + '」')
        return j
      },

      // ── 明細表（table）欄位編輯 ──
      tableColTypes() { return this.catalog.tableColumnTypes || [] },
      colTypeLabel(t) { return ({ text: '文字', number: '數字', date: '日期', select: '下拉', checkbox: '勾選', formula: '列內公式' })[t] || t },
      nextColKey(f) {
        var keys = (f.columns || []).map(function (c) { return c.key })
        for (var n = 1; ; n++) { if (keys.indexOf('c' + n) < 0) return 'c' + n }
      },
      addColumn(i, type) {
        var f = this.def.fields[i]
        if (!f || (f.columns || []).length >= 12) return
        var col = { key: this.nextColKey(f), label: '', type: type || 'text' }
        if (col.type === 'select') col.options = ['選項一', '選項二']
        if (col.type === 'formula') col.formula = ''
        f.columns = (f.columns || []).concat([col])
        this.checkAllFormulas()
      },
      removeColumn(i, ci) {
        var f = this.def.fields[i]
        f.columns = f.columns.filter(function (c, k) { return k !== ci })
        this.checkAllFormulas()
      },
      moveColumn(i, ci, dir) {
        var f = this.def.fields[i]
        f.columns = this.L.move(f.columns, ci, dir)
      },
      setColumn(i, ci, key, val) {
        var f = this.def.fields[i]
        var col = Object.assign({}, f.columns[ci])
        if (val === null || val === undefined || val === '' || val === false) delete col[key]; else col[key] = val
        f.columns = f.columns.map(function (c, k) { return k === ci ? col : c })
      },
      renameColumn(i, ci, k) {
        var f = this.def.fields[i]
        var old = f.columns[ci].key
        if (k === old) return
        if (!FIELD_KEY_RE.test(k) || f.columns.some(function (c, j) { return j !== ci && c.key === k })) {
          window.MotrixUI && window.MotrixUI.toast('欄位代號只能用小寫英文、數字與底線，且表內不可重複', { kind: 'error' })
          return
        }
        this.setColumn(i, ci, 'key', k)
        this.checkAllFormulas()
      },
      setColumnType(i, ci, t) {
        var f = this.def.fields[i]
        var col = { key: f.columns[ci].key, label: f.columns[ci].label, type: t }
        if (t === 'select') col.options = ['選項一', '選項二']
        if (t === 'formula') col.formula = ''
        f.columns = f.columns.map(function (c, k) { return k === ci ? col : c })
        this.checkAllFormulas()
      },
      colOptionsText(c) { return (c.options || []).join('\n') },
      setColOptions(i, ci, text) {
        this.setColumn(i, ci, 'options', String(text).split('\n').map(function (s) { return s.trim() }).filter(function (s, k, a) { return s && a.indexOf(s) === k }))
      },
      colSiblings(f, ci) { return (f.columns || []).filter(function (c, k) { return k !== ci }).map(function (c) { return c.key }) },
      // 公式檢查用：{表 key: [可加總數值欄]}
      tableColumnsMap() {
        var out = {}
        ;(this.def.fields || []).forEach(function (f) {
          if (f.type === 'table') out[f.key] = (f.columns || []).filter(function (c) { return c.type === 'number' || c.type === 'formula' }).map(function (c) { return c.key })
        })
        return out
      },
      tableKeys() { return (this.def.fields || []).filter(function (f) { return f.type === 'table' }).map(function (f) { return f.key }) },

      // ── 區塊欄數（網格）：1～4 欄；沒設＝依寬度自動 ──
      groupColumns(gi) { var g = this.layoutGroups()[gi]; return g && g.columns ? g.columns : 0 },
      setGroupColumns(gi, n) {
        var ui = clone(this.def.ui || {})
        var g = (((ui.form || {}).groups) || [])[gi]
        if (!g) return
        if (Number(n) >= 1 && Number(n) <= 4) g.columns = Number(n); else delete g.columns
        this.def.ui = ui
      },
      gridStyle(gi) { return this.L.gridStyle(this.groupColumns(gi)) },

      // ── 金流性質（附錄 B）──
      fin(f) { return f.finance && typeof f.finance === 'object' ? f.finance : {} },
      canFinance(f) { return f.type === 'number' || f.type === 'formula' },
      setFin(i, key, val) {
        var f = Object.assign({}, this.def.fields[i])
        var fin = Object.assign({}, f.finance || {})
        if (val === '' || val === null || val === undefined) delete fin[key]; else fin[key] = val
        if (!fin.kind || fin.kind === 'none') delete f.finance; else f.finance = fin
        this.def.fields.splice(i, 1, f)
      },
      fieldsOfType(types, exceptKey) {
        return (this.def.fields || []).filter(function (f) { return types.indexOf(f.type) >= 0 && f.key !== exceptKey })
      },
      financeFieldExists() { return (this.def.fields || []).some(function (f) { return f.finance && f.finance.kind && f.finance.kind !== 'none' }) },
      postStateList() { return (this.def.finance && this.def.finance.postStates) || [] },
      postStatesDerived() {
        var out = []
        ;(this.def.workflow.states || []).forEach(function (s) { if (s.approval && s.approval.on_approved && out.indexOf(s.approval.on_approved) < 0) out.push(s.approval.on_approved) })
        return out
      },
      togglePostState(key, on) {
        var cur = this.postStateList().slice()
        var at = cur.indexOf(key)
        if (on && at < 0) cur.push(key)
        if (!on && at >= 0) cur.splice(at, 1)
        var fin = Object.assign({}, this.def.finance || {})
        if (cur.length) fin.postStates = cur; else delete fin.postStates
        if (Object.keys(fin).length) this.def.finance = fin; else delete this.def.finance
      },

      // ── 範本挑選（新建模組時）──
      templates() { return this.catalog.templates || [] },
      async chooseTemplate(tkey) {
        if (this.tplBusy) return
        this.tplBusy = true
        try {
          var body = null
          if (tkey) {
            var r = await this.api('GET', '/api/custom-modules/templates/' + encodeURIComponent(tkey))
            if (!r.ok) { this.errMsg = '讀取範本失敗：' + ((r.data && r.data.detail) || r.status); return }
            body = r.data.body
          }
          await this.startBlank(this.tplKey, body)
        } finally { this.tplBusy = false }
      },
    }
  })
})()
