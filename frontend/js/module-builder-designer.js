// module-builder-designer.js — 把共用「表單設計器」（static/form-designer.js）接進建構器 ② 表單。
// 功能開關：頁面「新版設計器」按鈕（記在 localStorage.mb_designer）、或網址 ?designer=1／0；預設關（舊畫面照舊，新版通過 e2e 前不替換）。
// 設計器只改 fields／ui（欄位與版面）；其餘（流程、輸出、權限…）仍由建構器其他步驟編輯。自動存檔沿用建構器自己的流程（onDefChange）。
(function () {
  window.MotrixMB.parts.push(function (MB) {
    var clone = MB.clone
    return {
      useFD: false, _fd: null, fdSources: [], _publishedKeys: [],

      fdInitSwitch() {
        try {
          var q = new URLSearchParams(location.search).get('designer')
          this.useFD = q === '1' ? true : (q === '0' ? false : localStorage.getItem('mb_designer') === '1')
        } catch (e) {}
        this.$watch('tab', () => this.fdRefresh())
        this.$watch('useFD', () => this.fdRefresh())
        this.$watch('draftProblems', () => this.fdSyncProblems())
        this.$watch('publishProblems', () => this.fdSyncProblems())
        this.api('GET', '/api/platform/prefill-sources').then((r) => { this.fdSources = r.ok && Array.isArray(r.data) ? r.data : []; if (this._fd) this._fd.caps.prefillSources = this.fdSources })
      },
      toggleFD() {
        this.useFD = !this.useFD
        try { localStorage.setItem('mb_designer', this.useFD ? '1' : '0') } catch (e) {}
      },
      fdCaps() {
        return {
          elements: this.catalog.fieldElements || [], specs: this.catalog.fieldTypeSpecs || {}, prefillSources: this.fdSources,
          hasCase: false, isSuper: true, publishedKeys: this._publishedKeys || [], maxRows: 200, titleFallback: '（未命名的表單）'
        }
      },
      fdProblems() {
        return this.allProblems().filter(function (p) { return /^(fields|ui)/.test(String(p.path || '')) }).map(function (p) { return { path: p.path, message: p.message } })
      },
      // 進入 ② 表單、或切換開關時，用目前的 def 重建設計器（其他步驟可能改過 def）
      fdRefresh() {
        if (!this.useFD || this.tab !== 'form' || !this.def) return
        this.$nextTick(() => {
          var host = document.getElementById('mb-fd-host')
          if (!host || !window.FormDesigner) return
          if (!this._fd) {
            this._fd = window.FormDesigner.init(host, { def: clone(this.def), caps: this.fdCaps(), onChange: (d) => this.fdChanged(d) })
          } else {
            this._fd.caps = this.fdCaps()
            this._fd.setDef(clone(this.def))
          }
          this._fd.setProblems(this.fdProblems())
        })
      },
      fdChanged(d) {
        if (this._loading || !this.def) return
        this.def.fields = clone(d.fields || [])
        this.def.ui = Object.assign({}, this.def.ui || {}, clone(d.ui || {}))
      },
      fdSyncProblems() { if (this._fd) this._fd.setProblems(this.fdProblems()) }
    }
  })
})()
