// module-builder-output.js — ⑤ 輸出、⑥ 發布（拆自 module-builder.html）
(function () {
  window.MotrixMB.parts.push(function (MB) {
    var KEY_RE = MB.KEY_RE, FIELD_KEY_RE = MB.FIELD_KEY_RE, TYPE_LABELS = MB.TYPE_LABELS, BLOCK_LABELS = MB.BLOCK_LABELS, PARAM_LABELS = MB.PARAM_LABELS,
        FORMAT_LABELS = MB.FORMAT_LABELS, NAV = MB.NAV, TYPE_ICONS = MB.TYPE_ICONS, TYPE_ICON_GENERIC = MB.TYPE_ICON_GENERIC, STEPS = MB.STEPS, clone = MB.clone
    return {
        // ── ⑤ 輸出 ──
        hasCustomOutput() { return !!(this.def.output && this.def.output.template) },
        // 主題、欄位格式、輸出格式、積木與參數：全部取自目錄（沒有前端後備值；目錄沒給就沒有選項）
        outputThemes() { return this.catalog.outputThemes || [] },
        fieldFormats() { return this.catalog.fieldFormats || [] },
        canPdf() { return (this.catalog.outputFormats || []).indexOf('pdf') >= 0 },
        formatLabel(f) { return FORMAT_LABELS[f] || f },
        blockSpec(t) { return ((this.catalog.outputBlockSpecs || {})[t]) || { params: {} } },
        itemSpec(name) { return ((this.catalog.outputBlockItemSpecs || {})[name]) || {} },
        paramKeys(params) { return Object.keys(params || {}) },
        ps(t, k) { return (this.blockSpec(t).params || {})[k] || {} },
        isp(item, k) { return this.itemSpec(item)[k] || {} },
        //: `list:<子項>` ⇒ 子項名稱（`list:text` 是字串清單，不是子項）
        itemName(type) { type = String(type || ''); return type.indexOf('list:') === 0 && type !== 'list:text' ? type.slice(5) : '' },
        li(t, k) { return this.itemName(this.ps(t, k).type) },
        li2(t, k, ik) { return this.itemName(this.isp(this.li(t, k), ik).type) },
        isScalar(type) { return ['text', 'int', 'bool', 'path'].indexOf(type) >= 0 },
        //: 資料列（field）的 format 用目錄的 fieldFormats 下拉；其他子項的 format（例：表格欄另有 index）照目錄說明手填
        isFormatSelect(item, k) { return item === 'field' && k === 'format' },
        paramLabel(k) { return PARAM_LABELS[k] || k },
        val(o, k) { return !o || o[k] === undefined || o[k] === null ? '' : o[k] },
        setParam(o, k, v, sp) {
          if ((v === '' || v === null || v === undefined || (typeof v === 'number' && isNaN(v))) && !(sp && sp.required)) { delete o[k]; return }
          o[k] = (v === null || v === undefined || (typeof v === 'number' && isNaN(v))) ? '' : v
        },
        setCond(b, k, part, v) {
          var c = Object.assign({}, b[k] || {})
          if (v === '') delete c[part]; else c[part] = v
          if (!c.path && c.equals === undefined) delete b[k]; else b[k] = c
        },
        defaultValue(type, k, blockType) {
          if (type === 'text') return (blockType === 'identity_header' && k === 'title') ? (this.def.name || '') : ''
          if (type === 'path') return k === 'source' ? '' : 'recordNo'
          if (type === 'int') return 0
          if (type === 'bool') return false
          if (type === 'blocks' || type === 'list:text') return []
          var item = this.itemName(type)
          if (item) return [this.defaultItem(item)]
          return undefined
        },
        defaultItem(item) {
          var o = {}, spec = this.itemSpec(item), self = this
          Object.keys(spec).forEach(function (k) {
            if (!spec[k].required) return
            var v = self.defaultValue(spec[k].type, k, '')
            if (v !== undefined) o[k] = v
          })
          return o
        },
        defaultBlock(t) {
          var o = { type: t }, params = this.blockSpec(t).params || {}, self = this
          Object.keys(params).forEach(function (k) {
            if (!params[k].required) return
            var v = self.defaultValue(params[k].type, k, t)
            if (v !== undefined) o[k] = v
          })
          return o
        },
        addItem(o, k, item) { if (!Array.isArray(o[k])) o[k] = []; o[k].push(this.defaultItem(item)) },
        //: 可加入的積木＝目錄 outputBlocks 裡有參數規格、而且沒有巢狀積木參數的（巢狀積木建構器暫不提供編輯）
        editableBlocks() {
          var self = this
          return (this.catalog.outputBlocks || []).filter(function (t) {
            var sp = (self.catalog.outputBlockSpecs || {})[t]
            if (!sp) return false
            var ps = sp.params || {}
            return !Object.keys(ps).some(function (k) { return ps[k].type === 'blocks' })
          })
        },
        blockLabel(t) { return BLOCK_LABELS[t] || t },
        viewPaths() {
          var out = [{ value: 'recordNo', label: '編號' }, { value: 'statusLabel', label: '狀態' }, { value: 'createdBy', label: '建立者' },
                     { value: 'createdAt', label: '建立時間' }, { value: 'moduleName', label: '模組名稱' }]
          this.def.fields.forEach(function (f) { out.push({ value: 'fields.' + f.key, label: '欄位：' + (f.label || f.key) }) })
          return out
        },
        useGenericOutput() {
          if (!this.hasCustomOutput()) return
          var d = Object.assign({}, this.def)
          delete d.output
          this.def = d
          this.previewOutput()
        },
        useCustomOutput() {
          if (this.hasCustomOutput()) return
          var d = this.def
          var ff = this.fieldFormats()
          var fmt = function (f) {
            var want = f.type === 'date' ? 'date10' : (f.type === 'text' || f.type === 'select' ? 'text' : 'str')
            return ff.indexOf(want) >= 0 ? want : undefined
          }
          var row = function (label, path, format) { var r = { label: label, path: path }; if (format && ff.indexOf(format) >= 0) r.format = format; return r }
          var blocks = []
          var avail = this.editableBlocks()
          if (avail.indexOf('identity_header') >= 0) blocks.push(this.defaultBlock('identity_header'))
          if (avail.indexOf('meta') >= 0) blocks.push({ type: 'meta', fields: [row('編號', 'recordNo', 'text'), row('狀態', 'statusLabel', 'text'),
            row('建立者', 'createdBy', 'text'), row('建立時間', 'createdAt', 'date10')]
            .concat(d.fields.map(function (f) { return row(f.label || f.key, 'fields.' + f.key, fmt(f)) })) })
          if (avail.indexOf('approval_sign') >= 0) blocks.push({ type: 'approval_sign' })
          if (avail.indexOf('identity_footer') >= 0) blocks.push({ type: 'identity_footer' })
          this.def.output = { template: { key: 'custom_' + this.key, version: 1, theme: this.outputThemes()[0],
                                          title: { path: 'recordNo', suffix: ' ' + (d.name || '') }, blocks: blocks } }
          this.previewOutput()
        },
        addBlock(t) {
          if (!t || this.editableBlocks().indexOf(t) < 0) return
          this.def.output.template.blocks.push(this.defaultBlock(t))
        },
        moveBlock(bi, dir) { this.def.output.template.blocks = this.L.move(this.def.output.template.blocks, bi, dir) },
        queuePreview() {
          clearTimeout(this._pvTimer)
          this._pvTimer = setTimeout(() => this.previewOutput(), 600)
        },
        async previewOutput() {
          if (!this.def) return
          this.previewBusy = true; this.previewState = 'pending'
          try {
            var r = await fetch('/api/custom-modules/' + encodeURIComponent(this.key) + '/output/preview',
                                { method: 'POST', headers: this._hdr(), body: JSON.stringify({ body: this.def }) })
            if (r.ok) { this.previewHtml = await r.text(); this.previewProblems = []; this.previewState = 'ok' }
            else {
              var d = null
              try { d = await r.json() } catch (e) {}
              this.previewProblems = (d && d.problems) || [{ path: '', message: (d && d.detail) || ('預覽失敗（' + r.status + '）') }]
              this.previewState = 'bad'
            }
          } finally { this.previewBusy = false }
        },

        async previewPdf() {
          if (!this.def || this.pdfBusy) return
          // 先開分頁（在使用者點擊的當下開，才不會被擋），PDF 回來再把網址換過去
          var w = window.open('', '_blank')
          this.pdfBusy = true; this.pdfState = 'pending'; this.pdfBytes = 0
          try {
            var r = await fetch('/api/custom-modules/' + encodeURIComponent(this.key) + '/output/preview?format=pdf',
                                { method: 'POST', headers: this._hdr(), body: JSON.stringify({ body: this.def }) })
            var ct = r.headers.get('content-type') || ''
            if (r.ok && ct.indexOf('application/pdf') === 0) {
              var blob = await r.blob()
              this.pdfBytes = blob.size
              var url = URL.createObjectURL(blob)
              if (w) w.location.href = url
              else { var a = document.createElement('a'); a.href = url; a.download = (this.key || 'preview') + '.pdf'; document.body.appendChild(a); a.click(); a.remove() }
              setTimeout(function () { URL.revokeObjectURL(url) }, 60000)
              this.pdfState = 'ok'
            } else {
              if (w) w.close()
              var d = null
              try { d = await r.json() } catch (e) {}
              this.previewProblems = (d && d.problems) || [{ path: '', message: (d && d.detail) || ('PDF 預覽失敗（' + r.status + '）') }]
              this.pdfState = 'bad'
            }
          } catch (e) {
            if (w) w.close()
            this.pdfState = 'bad'
          } finally { this.pdfBusy = false }
        },

        // ── ⑥ 發布 ──
        async loadDiff() {
          this.diffLoaded = false
          var r = await this.api('GET', this.defUrl() + '/diff?a=latest&b=draft')
          this.diff = r.ok ? (r.data.changes || []) : []
          this.diffLoaded = true
        },
        diffGroups() { var self = this; return this.diff.slice().sort(function (a, b) { return self.stepOf(a.path) - self.stepOf(b.path) }) },
        opLabel(op) { return op === 'add' ? '新增' : (op === 'remove' ? '刪除' : '變更') },
        short(v) { var s = typeof v === 'string' ? v : JSON.stringify(v); return s && s.length > 120 ? s.slice(0, 117) + '…' : s },
        async reloadVersions() {
          var r = await this.api('GET', this.defUrl())
          if (r.ok) { this.versions = r.data.versions || []; this.latestVersion = r.data.latest ? r.data.latest.version : 0 }
        },
        async publish() {
          if (this.busy) return
          this.busy = true; this.publishProblems = []; this.errMsg = ''
          try {
            if (!(await this.flushSave())) { this.errMsg = '未發布：' + (this.errMsg || '草稿存檔失敗'); return }
            var r = await this.api('POST', this.defUrl() + '/publish', { note: this.publishNote })
            if (r.status === 422) {
              this.publishProblems = (r.data && r.data.problems) || []
              return
            }
            if (!r.ok) { this.errMsg = '發布失敗：' + ((r.data && r.data.detail) || r.status); return }
            this.publishNote = ''
            this.draftProblems = []
            this.saveState = 'idle'
            window.MotrixUI && window.MotrixUI.toast('已發布第 ' + r.data.version + ' 版', { kind: 'ok' })
            await this.reloadVersions()
            await this.loadDiff()
            var p = await this.api('GET', '/api/custom-modules')
            if (p.ok) this.published = p.data || []
          } finally { this.busy = false }
        },
        async restore(v) {
          if (this.busy) return
          var ok = window.MotrixUI ? await window.MotrixUI.confirm('把第 ' + v + ' 版的內容再發布成新的一版？（歷史不會被改）', { okText: '還原' }) : true
          if (!ok) return
          this.busy = true; this.publishProblems = []; this.errMsg = ''
          try {
            if (!(await this.flushSave())) { this.errMsg = '未還原：' + (this.errMsg || '草稿存檔失敗'); return }
            var r = await this.api('POST', this.defUrl() + '/restore/' + v, { note: '' })
            if (r.status === 422) { this.publishProblems = (r.data && r.data.problems) || []; return }
            if (!r.ok) { this.errMsg = '還原失敗：' + ((r.data && r.data.detail) || r.status); return }
            window.MotrixUI && window.MotrixUI.toast('已還原成第 ' + r.data.version + ' 版', { kind: 'ok' })
            // 草稿改成還原後的內容（否則畫面上的草稿仍是舊的編輯，下一次發布會把還原蓋掉）
            this._loading = true
            this.def = this.normalize(clone(r.data.body))
            this.$nextTick(() => { this._loading = false })
            await this.saveDraft()
            await this.reloadVersions()
            await this.loadDiff()
          } finally { this.busy = false }
        },
    }
  })
})()
