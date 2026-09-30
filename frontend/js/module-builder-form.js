// module-builder-form.js — ② 表單：欄位、區塊、畫布、屬性（拆自 module-builder.html）
(function () {
  window.MotrixMB.parts.push(function (MB) {
    var KEY_RE = MB.KEY_RE, FIELD_KEY_RE = MB.FIELD_KEY_RE, TYPE_LABELS = MB.TYPE_LABELS, BLOCK_LABELS = MB.BLOCK_LABELS, PARAM_LABELS = MB.PARAM_LABELS,
        FORMAT_LABELS = MB.FORMAT_LABELS, NAV = MB.NAV, TYPE_ICONS = MB.TYPE_ICONS, TYPE_ICON_GENERIC = MB.TYPE_ICON_GENERIC, STEPS = MB.STEPS, clone = MB.clone
    return {
        // ── ② 欄位 ──
        typeLabel(t) { return TYPE_LABELS[t] || this.elementLabel(t) },
        typeIcon(t) { return TYPE_ICONS[t] || TYPE_ICON_GENERIC },
        setHelp(i, v) {
          // 選填：清空就拿掉這個鍵（沒填的定義與舊版一樣）
          var f = this.def.fields[i]
          if (!f) return
          if (String(v).trim() === '') { delete f.help; this.def.fields = this.def.fields.slice() } else f.help = v
        },
        fxReadableLine(i) {
          // 使用者 2026-09-27：公式要看得懂——可讀式子；有錯就用人話說明（沿用公式檢查的結果）
          var f = this.def.fields[i]
          if (!f || f.type !== 'formula') return ''
          var probs = this.fxProblems[i] || []
          if (probs.length) return '公式有誤：第 ' + (probs[0].pos + 1) + ' 個字附近——' + probs[0].message
          if (!String(f.formula || '').trim()) return '（還沒寫公式）'
          return this.L.formulaReadable(this.def, f)
        },
        moveFieldKb(i, dir) {
          // 鍵盤替代（Alt＋↑／↓）：同一區塊內移一格，到邊界移到相鄰區塊；焦點跟著卡片走、念出新位置
          var f = this.def.fields[i]
          if (!f) return
          var j = this.moveField(i, dir)
          if (j < 0) return
          this.announce((f.label || f.key) + ' 移到' + this.posText(this.sectionOf(f.key)))
          this.$nextTick(function () {
            var el = document.querySelector('#mb-canvas .mb-fc[data-field-index="' + j + '"]')
            if (el) el.focus()
          })
        },
        async removeFieldKb(i) {
          var f = this.def.fields[i]
          var n = this.def.fields.length
          await this.removeField(i)
          if (this.def.fields.length === n) return          // 取消了
          this.announce('已刪除 ' + (f.label || f.key))
          var k = Math.min(i, this.def.fields.length - 1)
          this.$nextTick(function () {
            var el = k >= 0 ? document.querySelector('#mb-canvas .mb-fc[data-field-index="' + k + '"]') : document.getElementById('mb-palette')
            if (el) el.focus()
          })
        },
        nextKey(t) {
          var base = t === 'formula' ? 'calc' : (t === 'ref' ? 'ref' : (t === 'table' ? 'tbl' : 'field'))
          var keys = this.def.fields.map(function (f) { return f.key })
          for (var i = 1; ; i++) { if (keys.indexOf(base + '_' + i) < 0) return base + '_' + i }
        },
        addField(t, gi, index, preset) {
          // 新欄位放進區塊 gi（-1＝沒分組）的第 index 個（null ⇒ 最後）；回傳它在 def.fields 的位置。
          // `preset`＝目錄元件的預設屬性（例：日期時間 withTime、單選的預設選項、明細表的預設欄）
          if ((this.catalog.fieldTypes || []).indexOf(t) < 0) return -1
          var f = { key: this.nextKey(t), label: '', type: t, dataClass: (this.catalog.dataClasses || ['T1'])[0] }
          if (t !== 'formula') f.required = false
          if (t === 'formula') f.formula = ''
          if (t === 'ref') f.target = ''
          if (t === 'select') f.options = []
          if (preset && typeof preset === 'object') {
            var p = clone(preset)
            Object.keys(p).forEach(function (k) { f[k] = p[k] })
            if (t === 'table') f.columns = (f.columns || []).map(function (c, n) { return Object.assign({ key: 'c' + (n + 1) }, c) })
          }
          this.def.fields.push(f)
          return this.applyPlacement(f.key, gi === undefined ? -1 : gi, index)
        },
        addFieldHere(t) {
          // 點一下／Enter：加到目前選中欄位所在的區塊的最後（沒選 ⇒ 沒分組的最後）
          var j = this.addField(t, this.currentGroup(), null)
          if (j < 0) return
          this.announce('已加入 ' + this.typeLabel(t) + '，' + this.posText(this.sectionOf(this.def.fields[j].key)))
        },
        // ── ② 表單：區塊與位置（規則在 custom-layout.js：editorSections／placeField／sectionOrder）──
        applyPlacement(key, gi, index) {
          var r = this.L.placeField(this.def, key, gi, index)
          this.def.ui = r.ui
          this.def.fields = r.fields
          this.sel = this.fieldIndex(key)
          this.fxProblems = {}; this.checkAllFormulas()
          return this.sel
        },
        fieldIndex(key) { return this.def.fields.findIndex(function (f) { return f.key === key }) },
        sectionOf(key) {
          var secs = this.L.editorSections(this.def)
          for (var si = 0; si < secs.length; si++) {
            var p = secs[si].items.findIndex(function (x) { return x.key === key })
            if (p >= 0) return { si: si, gi: secs[si].gi, pos: p, secs: secs }
          }
          return null
        },
        posText(s) {
          if (!s) return ''
          var t = s.secs[s.si].title
          return (t ? '「' + t + '」' : '') + '第 ' + (s.pos + 1) + ' 個'
        },
        currentGroup() {
          var f = this.sel !== null ? this.def.fields[this.sel] : null
          var s = f ? this.sectionOf(f.key) : null
          return s ? s.gi : -1
        },
        dropOn(ev, gi, beforeKey) {
          // 拖放：type:<型別>＝新欄位；field:<key>＝搬欄位；group:<gi>＝搬區塊。放在卡片上 ⇒ 插在那張之前；放在區塊空白處 ⇒ 區塊最後
          this.dragOver = false
          var d = ev.dataTransfer ? ev.dataTransfer.getData('text/plain') : ''
          if (d.indexOf('group:') === 0) {
            var from = Number(d.slice(6))
            if (isNaN(from) || gi < 0 || from === gi) return
            this.def.ui = this.L.moveGroupTo(this.def, from, gi)
            this.syncFieldOrder()
            return
          }
          var moving = d.indexOf('field:') === 0 ? d.slice(6) : null
          var idx = null
          if (beforeKey) {
            if (moving === beforeKey) return
            var s = this.sectionOf(beforeKey)
            idx = s ? s.secs[s.si].items.map(function (x) { return x.key }).filter(function (k) { return k !== moving }).indexOf(beforeKey) : null
          }
          if (d.indexOf('type:') === 0) { this.addField(d.slice(5), gi, idx); return }
          if (d.indexOf('element:') === 0) {
            var el = this.elements().find(function (x) { return x.id === d.slice(8) })
            if (el) this.addField(el.type, gi, idx, el.preset)
            return
          }
          if (moving && this.fieldIndex(moving) >= 0) this.applyPlacement(moving, gi, idx)
        },
        moveField(i, dir) {
          // 同一區塊內移一格；到區塊邊界 ⇒ 移到相鄰區塊（往上＝上一塊的最後，往下＝下一塊的最前）。回傳新位置（不能移 ⇒ -1）
          var f = this.def.fields[i]
          var s = f ? this.sectionOf(f.key) : null
          if (!s) return -1
          var sec = s.secs[s.si], p = s.pos + dir
          if (p >= 0 && p < sec.items.length) return this.applyPlacement(f.key, sec.gi, p)
          var nb = s.secs[s.si + dir]
          if (!nb) return -1
          return this.applyPlacement(f.key, nb.gi, dir < 0 ? nb.items.length : 0)
        },
        syncFieldOrder() {
          // 區塊重排／刪除之後，def.fields 跟著畫布順序（沒分組的欄位順序＝fields 順序）
          var selKey = this.sel !== null && this.def.fields[this.sel] ? this.def.fields[this.sel].key : null
          var fields = this.L.sectionOrder(this.def)
          var k = function (f) { return f && f.key }
          if (fields.map(k).join('|') !== this.def.fields.map(k).join('|')) { this.def.fields = fields; this.fxProblems = {}; this.checkAllFormulas() }
          if (selKey) this.sel = this.fieldIndex(selKey)
        },
        addGroupAt() {
          this.def.ui = this.L.addGroup(this.def, '')
          var n = this.layoutGroups().length
          this.announce('已新增區塊，第 ' + n + ' 個')
          this.$nextTick(function () { var el = document.querySelector('[data-group-title="' + (n - 1) + '"]'); if (el) el.focus() })
        },
        moveGroupBy(gi, dir) { this.def.ui = this.L.moveGroup(this.def, gi, dir); this.syncFieldOrder() },
        async removeGroupAt(gi) {
          var g = this.layoutGroups()[gi]
          if (!g) return
          if ((g.fields || []).length && window.MotrixUI) {
            var ok = await window.MotrixUI.confirm('刪除區塊「' + (g.title || '未命名') + '」？裡面的欄位會移到「其他」。', { danger: true, okText: '刪除' })
            if (!ok) return
          }
          this.def.ui = this.L.removeGroup(this.def, gi)
          this.syncFieldOrder()
        },
        async removeField(i) {
          var f = this.def.fields[i]
          var ok = window.MotrixUI ? await window.MotrixUI.confirm('刪除欄位「' + (f.label || f.key) + '」？', { danger: true, okText: '刪除' }) : true
          if (!ok) return
          this.def.fields.splice(i, 1)
          this.def.ui = this.L.renameFieldKey(this.def, f.key, '')
          this.sel = null
          this.fxProblems = {}; this.checkAllFormulas()
        },
        renameField(i, k) {
          var old = this.def.fields[i].key
          if (k === old) return
          if (!FIELD_KEY_RE.test(k)) { window.MotrixUI && window.MotrixUI.toast('欄位代號只能用小寫英文、數字與底線，英文開頭', { kind: 'error' }); return }
          if (this.def.fields.some(function (f, j) { return j !== i && f.key === k })) { window.MotrixUI && window.MotrixUI.toast('欄位代號重複：' + k, { kind: 'error' }); return }
          this.def.fields[i].key = k
          this.def.ui = this.L.renameFieldKey(this.def, old, k)
          this.checkAllFormulas()
        },
        setDefault(i, v) {
          var f = Object.assign({}, this.def.fields[i])
          if (v === null || v === undefined || v === '') delete f.default
          else f.default = v
          this.def.fields.splice(i, 1, f)
        },
        otherKeys(i) { var k = this.def.fields[i] && this.def.fields[i].key; return this.def.fields.map(function (f) { return f.key }).filter(function (x) { return x && x !== k }) },
        insertFx(i, s) {
          var f = this.def.fields[i]
          f.formula = (f.formula || '') + ((f.formula && !/[\s(]$/.test(f.formula)) ? ' ' : '') + s
          this.queueFormulaCheck(i)
        },
        queueFormulaCheck(i) {
          clearTimeout(this._fxTimers[i])
          this.fxState = Object.assign({}, this.fxState, { [i]: 'pending' })
          this._fxTimers[i] = setTimeout(() => this.checkFormula(i), 300)
        },
        async checkFormula(i) {
          var f = this.def.fields[i]
          if (!f || f.type !== 'formula') return
          var formula = f.formula
          var r = await this.api('POST', '/api/custom-modules/formula/check', { formula: formula, fields: this.otherKeys(i), tables: this.tableColumnsMap() })
          if (!this.def.fields[i] || this.def.fields[i].formula !== formula) return   // 已經又改了
          var probs = r.ok ? (r.data.problems || []) : [{ pos: 0, message: '檢查失敗（' + r.status + '）' }]
          this.fxProblems = Object.assign({}, this.fxProblems, { [i]: probs })
          this.fxState = Object.assign({}, this.fxState, { [i]: probs.length ? 'bad' : 'ok' })
        },
        checkAllFormulas() {
          var self = this
          if (!this.def) return
          this.def.fields.forEach(function (f, i) { if (f.type === 'formula') self.queueFormulaCheck(i) })
        },
        refTargetOptions() {
          var out = []
          var rt = this.catalog.refTargets || {}
          var names = { users: '使用者', customers: '客戶' }
          Object.keys(rt).forEach(function (k) { out.push({ value: k, label: (names[k] || k) + '（' + k + '）' }) })
          var self = this
          this.published.forEach(function (m) { if (m.key !== self.key) out.push({ value: 'custom:' + m.key, label: '自訂模組：' + (m.name || m.key) }) })
          return out
        },

        // ── ③ 版面 ──
        layoutGroups() { return ((this.def.ui || {}).form || {}).groups || [] },
        listColumnKeys() { return this.L.listColumns(this.def).map(function (c) { return c.key }) },
        fieldLabel(k) { var f = this.def.fields.find(function (x) { return x.key === k }); return f ? (f.label || f.key) : k },

    }
  })
})()
