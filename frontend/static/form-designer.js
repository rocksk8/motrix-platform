// form-designer.js — 共用「表單設計器」元件（模組建構器、請款類型編輯頁共用）。
// 三欄：左＝加入欄位（大圖示按鈕）、中＝真正的表單（所見即所得）、右＝選到的欄位的白話設定。
// 資料就是現行定義 JSON（見 form-designer-model.js）；不動就輸出相同的 JSON。
// 規格與用語：docs/platform/plans/FORM-DESIGNER-DESIGN.md（R3：每個設定都要有白話標題＋一句說明＋例子）。
//
// 用法：
//   var fd = FormDesigner.init(el, { def, caps, onChange(def) {} })
//   fd.getDef()  fd.setDef(def)  fd.setProblems([{path, message}])  fd.focus(key)  fd.getFieldIndexMap()  fd.on('select'|'change', fn)  fd.destroy()
// caps（全部選填）：
//   elements       目錄的 fieldElements（[{id,type,group,label,preset}]）——左欄只會出現目錄有的元件
//   specs          目錄的 fieldTypeSpecs（右欄「更多設定」依它列出該種類的其他屬性）
//   prefillSources GET /api/platform/prefill-sources 的清單（自動帶入選單的唯一來源）；沒給就只用既有三種（今天／現在／申請人本人）
//   hasCase        表單有沒有「案件」情境（有才出現「這個案件的客戶／專案」）
//   isSuper        最高管理者才看得到「進階」摺疊（內部代碼、舊公式）
//   fixedTypeKeys  {key: type}：保留字欄位，種類固定、刪除前要確認
//   extraPalette   [{title, items:[{id,label,desc,icon,field:{…整個欄位物件}}]}]：額外的現成欄位（請款常用欄位）
//   onlyOneTable   'lines'：明細表只能有一個且代碼固定
//   columnPresets  [{label, desc, cols:[完整欄物件]}]：明細表「加入常用欄」（欄代碼固定的欄，例如 數量＋單價、發票號碼）
//   requiredColumns / pairColumns / cashierKeys / bannedWords(RegExp) / maxRows / publishedKeys / titleEditable / titleFallback
(function () {
  'use strict'
  var M = window.FDModel
  if (!M) throw new Error('form-designer.js 需要先載入 form-designer-model.js')

  var uidSeq = 0
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] }) }
  function $(s, r) { return (r || document).querySelector(s) }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)) }

  // ── 圖示（線條，currentColor）──
  var P = {
    text: 'M5 7V5h14v2M12 5v14M9 19h6', lines: 'M4 6h16M4 11h16M4 16h16M4 21h10', hash: 'M5 9h15M4 15h15M10 4 8 20M16 4l-2 16',
    coin: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM9 8l3 4 3-4M9 12h6M9 15h6M12 12v6',
    cal: 'M5.5 5h13a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM3.5 10h17M8 3v4M16 3v4',
    clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2',
    range: 'M4.5 5h5a1.5 1.5 0 0 1 1.5 1.5v11A1.5 1.5 0 0 1 9.5 19h-5A1.5 1.5 0 0 1 3 17.5v-11A1.5 1.5 0 0 1 4.5 5zM14.5 5h5A1.5 1.5 0 0 1 21 6.5v11a1.5 1.5 0 0 1-1.5 1.5h-5a1.5 1.5 0 0 1-1.5-1.5v-11A1.5 1.5 0 0 1 14.5 5zM11 12h2',
    select: 'M5 6h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2zM9 11l3 3 3-3',
    radio: 'M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7z',
    multi: 'M4 7l2 2 3-3M4 17l2 2 3-3M12 8h8M12 18h8', check: 'M7 4h10a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H7a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3zM8 12.5l3 3 5-6',
    clip: 'M20 11.5l-7.7 7.7a5 5 0 0 1-7-7L13 4.5a3.3 3.3 0 0 1 4.7 4.7L10 17a1.7 1.7 0 0 1-2.4-2.4L14.5 8',
    image: 'M5.5 4.5h13a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2zM9 8.4a1.6 1.6 0 1 0 0 3.2 1.6 1.6 0 0 0 0-3.2zM4 17l5-4.5 4 3.5 3-2.5 4 3.5',
    user: 'M12 4.8a3.7 3.7 0 1 0 0 7.4 3.7 3.7 0 0 0 0-7.4zM4.5 20c.8-4 3.6-6 7.5-6s6.7 2 7.5 6',
    users: 'M9 5a3.2 3.2 0 1 0 0 6.4A3.2 3.2 0 0 0 9 5zM3 19c.6-3.4 3-5 6-5s5.4 1.6 6 5M17 6.2a2.8 2.8 0 0 1 0 5.4M18 14.2c1.9.6 2.8 2.2 3 4.8',
    dept: 'M6.5 3.5h11a1.5 1.5 0 0 1 1.5 1.5v14a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 5 19V5a1.5 1.5 0 0 1 1.5-1.5zM9 8h2M13 8h2M9 12h2M13 12h2M10 20.5v-4h4v4',
    calc: 'M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2zM8 7h8M9 12h.01M12 12h.01M15 12h.01M9 16h.01M12 16h.01M15 16h.01',
    table: 'M5.5 5h13a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM3.5 10h17M9.5 5v14M15 5v14',
    plus: 'M12 5v14M5 12h14', trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3', up: 'M12 19V6M6 11l6-6 6 6', down: 'M12 5v13M6 13l6 6 6-6',
    copy: 'M10 8h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-8a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2zM16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2',
    grip: 'M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01', undo: 'M9 3 4 8l5 5M4 8h10a6 6 0 0 1 0 12', redo: 'M15 3l5 5-5 5M20 8H10a6 6 0 0 0 0 12',
    click: 'M9 4l1 5M5 8l4 2M14 14l6 3-3 1.5L15.5 22zM6 3.5l3 3', warn: 'M12 4 2.5 20h19L12 4zM12 10v4M12 17h.01', done: 'M5 12.5l4.5 4.5L19 7.5', lock: 'M7 11h10a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1zM8.5 11V8a3.5 3.5 0 0 1 7 0v3'
  }
  function ic(n, cls) { return '<svg class="fd-ic ' + (cls || '') + '" viewBox="0 0 24 24" aria-hidden="true"><path d="' + P[n] + '"/></svg>' }

  // ── 左欄：元件的白話名稱／說明／圖示（只列目錄有的元件；目錄沒有的不會出現）──
  var FRIENDLY = {
    text: ['文字', '一行短文字，例如地點', 'text', 'common'], textarea: ['長文字', '可以寫很多行，例如備註', 'lines', 'common'],
    number: ['數字', '只能輸入數字，例如數量', 'hash', 'common'], money: ['金額', '錢的數字，不能是負的', 'coin', 'common'],
    date: ['日期', '選一天', 'cal', 'common'], datetime: ['日期加時間', '選一天和幾點', 'clock', 'common'], daterange: ['日期區間', '從哪天到哪天', 'range', 'common'],
    select: ['單選選單', '從清單裡選一個', 'select', 'pick'], radio: ['單選圓點', '選項全部攤開，點一個', 'radio', 'pick'],
    checkboxes: ['多選打勾', '選項全部攤開，可勾好幾個', 'multi', 'pick'], multiselect: ['多選選單', '從清單裡選好幾個', 'multi', 'pick'],
    checkbox: ['勾選', '只有「是」或「否」', 'check', 'pick'],
    user: ['選人員', '從系統裡選一位同事', 'user', 'pick'], users: ['選多位人員', '從系統裡選好幾位同事', 'users', 'pick'],
    dept: ['選部門', '從系統裡選一個部門', 'dept', 'pick'], depts: ['選多個部門', '從系統裡選好幾個部門', 'dept', 'pick'],
    file: ['檔案上傳', '附上檔案，例如發票', 'clip', 'other'], image: ['圖片', '附上照片', 'image', 'other'],
    formula: ['自動計算', '系統幫你算，例如加總', 'calc', 'other'], table: ['明細表', '很多列的表格，例如費用明細', 'table', 'other']
  }
  var PAL_GROUPS = [['common', '常用'], ['pick', '讓人選'], ['other', '其他']]
  // 內建的後備元件（呼叫端沒給 caps.elements 時；與目錄的 fieldElements 同形）
  var DEFAULT_ELEMENTS = ['text', 'textarea', 'number', 'date', 'daterange', 'select', 'radio', 'checkboxes', 'multiselect', 'checkbox', 'file', 'image', 'formula', 'table'].map(function (t) { return { id: t, type: t, preset: ['select', 'radio', 'checkboxes', 'multiselect'].indexOf(t) >= 0 ? { options: ['選項一', '選項二'] } : {} } })
    .concat([{ id: 'user', type: 'ref', preset: { target: 'users' } }, { id: 'dept', type: 'ref', preset: { target: 'departments' } }])

  // ── 右欄：目錄屬性的白話用語（R3；目錄有而這裡沒有的屬性，只在「進階」出現）──
  var ATTR_COPY = {
    placeholder: ['提示文字', '欄位還沒填時，框裡顯示的淡淡灰字。', '「請輸入地點」'],
    maxLength: ['最多幾個字', '超過就不能再輸入。', '備註最多 200 字'],
    unique: ['不可重複', '同一個欄位的內容，不能和以前的單子一樣。', '「發票號碼」不能填兩次'],
    min: ['最小值', '小於這個數字就不能送出。', '金額最小 0'], max: ['最大值', '大於這個數字就不能送出。', '折扣最大 100'],
    allowOther: ['允許自己輸入「其他」', '使用者可以不選清單裡的，自己打一個。', '選單外加一個「其他：＿＿」'],
    withTime: ['要選時間', '除了日期，還要選幾點幾分。', '2026/10/01 14:30'],
    multiple: ['可以選好幾個', '開起來，使用者可選多位人員或多個部門。', '會議出席：選 5 位同事'],
    accept: ['可以上傳哪些檔案', '填副檔名，用逗號隔開；留白代表都可以。', 'pdf, jpg, png'],
    maxFiles: ['最多幾個檔案', '超過就不能再加。', '最多 3 個'],
    minRows: ['最少幾列', '表格至少要填這麼多列才能送出。', '至少 1 列'], maxRows: ['最多幾列', '表格最多可以有幾列（上限 200）。', '最多 20 列'],
    addLabel: ['新增按鈕的字', '表格下方「新增一列」那顆按鈕上的字。', '「新增一筆費用」'],
    minSelect: ['最少選幾個', '至少要選這麼多個才能送出。', '至少選 1 個'], maxSelect: ['最多選幾個', '最多只能選這麼多個。', '最多選 3 個']
  }
  var HANDLED_ATTRS = { options: 1, default: 1, columns: 1 }
  var COL_TYPES = [['text', '文字'], ['number', '數字'], ['date', '日期'], ['select', '選單'], ['formula', '自動計算']]
  var BUILTIN_FILLS = [
    { token: 'today', label: '今天日期', why: '打開表單的那一天。', example: '2026/10/01', applies_to: [['date', null]], lockable: true },
    { token: 'now', label: '現在的日期和時間', why: '打開表單的那一刻。', example: '2026/10/01 14:30', applies_to: [['date', null]], lockable: true },
    { token: 'requester', label: '申請人本人', why: '填表的人是誰就帶誰。', example: '王小明', applies_to: [['ref', 'users']], lockable: true }
  ]

  function FD(el, opts) {
    var self = this
    opts = opts || {}
    this.uid = ++uidSeq
    this.root = el
    this.caps = opts.caps || {}
    this.onChange = opts.onChange || function () {}
    this.def = M.clone(opts.def || { fields: [] })
    this.sel = ''
    this.mode = 'edit'
    this.pane = 'center'
    this.drag = null
    this.problems = []
    this.localProblems = []
    this.map = []
    this.hist = [JSON.stringify(this.def)]; this.at = 0
    this.listeners = { change: [], select: [] }
    this.typeTimer = null
    this.root.classList.add('fd')
    this.root.innerHTML = '<div class="fd-bar"></div><div class="fd-panes" data-pane="center"><aside class="fd-pane fd-left" aria-label="加入欄位"></aside>' +
      '<section class="fd-pane fd-center" aria-label="表單預覽"></section><aside class="fd-pane fd-right" aria-label="欄位設定"></aside></div>' +
      '<nav class="fd-tabs" aria-label="切換區域"><button type="button" data-pane="left">' + ic('plus') + '加入欄位</button><button type="button" data-pane="center" aria-selected="true">' + ic('lines') + '表單</button><button type="button" data-pane="right">' + ic('click') + '設定</button></nav>' +
      '<div class="fd-toasts" aria-live="polite"></div>'
    this.els = { bar: $('.fd-bar', el), panes: $('.fd-panes', el), left: $('.fd-left', el), center: $('.fd-center', el), right: $('.fd-right', el), tabs: $('.fd-tabs', el), toasts: $('.fd-toasts', el) }
    this._bind()
    this._remap()
    this.localProblems = M.localProblems(this.def, this.caps)
    this.renderAll()
  }
  var proto = FD.prototype
  proto.id = function (n) { return 'fd' + this.uid + '-' + n }
  proto.cur = function () { return M.fieldByKey(this.def, this.sel) }
  proto.registry = function () { return (this.caps.prefillSources && this.caps.prefillSources.length) ? this.caps.prefillSources : BUILTIN_FILLS }
  proto.on = function (ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn) }
  proto.emit = function (ev, a) { (this.listeners[ev] || []).forEach(function (f) { f(a) }) }
  proto.getDef = function () { return M.strip(this.def) }
  proto._remap = function () { this.map = (this.def.fields || []).map(function (f) { return f.key }) }
  proto.setDef = function (def) { this.def = M.clone(def || { fields: [] }); this.hist = [JSON.stringify(this.def)]; this.at = 0; if (!M.fieldByKey(this.def, this.sel)) this.sel = ''; this._remap(); this.localProblems = M.localProblems(this.def, this.caps); this.renderAll() }
  proto.getFieldIndexMap = function () { return this.map.slice() }
  proto.setProblems = function (list) { this.problems = (list || []).map(function (p) { return { path: p.path, message: p.message } }); this.renderBar(); this.renderCenter(); this.renderRight() }
  proto.destroy = function () { clearTimeout(this.typeTimer); this.root.innerHTML = ''; this.root.classList.remove('fd') }
  proto.focus = function (key) {
    if (!M.fieldByKey(this.def, key)) return false
    this.select(key); this.showPane('right-if-narrow')
    var n = $('.fd-fld[data-key="' + key + '"]', this.els.center)
    if (n) { if (n.scrollIntoView) n.scrollIntoView({ block: 'center' }); n.focus() }
    return true
  }
  /** 問題路徑 ⇒ 欄位代碼（用最近一次輸出的 index→key 表；對不到的回 ''）。 */
  proto.keyOfPath = function (path) {
    var m = /^fields\[(\d+)\]/.exec(String(path || ''))
    if (m) return this.map[+m[1]] || ''
    return ''
  }
  proto.allProblems = function () { return this.problems.map(function (p) { return Object.assign({}, p, { key: this.keyOfPath(p.path) }) }, this).concat(this.localProblems) }
  proto.problemsOf = function (key) { return this.allProblems().filter(function (p) { return p.key === key }) }

  // ───────────── 歷史（復原／重做）與輸出 ─────────────
  proto.commit = function () {
    clearTimeout(this.typeTimer)
    var s = JSON.stringify(this.def)
    if (s === this.hist[this.at]) return
    this.hist = this.hist.slice(0, this.at + 1); this.hist.push(s); if (this.hist.length > 100) this.hist.shift(); this.at = this.hist.length - 1
    this._changed()
  }
  proto.commitSoon = function () { var s = this; clearTimeout(this.typeTimer); this.typeTimer = setTimeout(function () { s.commit(); s.renderBar() }, 500); this._emitOnly() }
  proto._emitOnly = function () { this._remap(); this.onChange(this.getDef()); this.emit('change', this.getDef()) }
  proto._changed = function () { this.localProblems = M.localProblems(this.def, this.caps); this._emitOnly(); this.renderBar() }
  proto.undo = function () { clearTimeout(this.typeTimer); this.commit(); if (this.at > 0) { this.at--; this._restore() } }
  proto.redo = function () { if (this.at < this.hist.length - 1) { this.at++; this._restore() } }
  proto._restore = function () { this.def = JSON.parse(this.hist[this.at]); if (!M.fieldByKey(this.def, this.sel)) this.sel = ''; this._changed(); this.renderAll() }
  proto.toast = function (msg, label, fn) {
    var t = document.createElement('div'); t.className = 'fd-toast'
    t.innerHTML = '<span>' + esc(msg) + '</span>' + (label ? '<button type="button">' + esc(label) + '</button>' : '')
    if (label) t.querySelector('button').onclick = function () { fn(); t.remove() }
    this.els.toasts.appendChild(t); setTimeout(function () { t.remove() }, 6000)
  }
  proto.ask = function (title, body, okLabel) {   // 確認對話框；okLabel 為空 ⇒ 只有「知道了」
    var self = this
    return new Promise(function (res) {
      var d = document.createElement('dialog'); d.className = 'fd-dlg'
      d.innerHTML = '<h3>' + esc(title) + '</h3><div class="fd-dlg__b">' + body + '</div><div class="fd-dlg__f">' +
        (okLabel ? '<button type="button" class="fd-btn" data-r="0">取消</button><button type="button" class="fd-btn fd-btn--danger" data-r="1">' + esc(okLabel) + '</button>' : '<button type="button" class="fd-btn fd-btn--primary" data-r="0">知道了</button>') + '</div>'
      self.root.appendChild(d)
      d.addEventListener('click', function (e) { var b = e.target.closest('[data-r]'); if (b) { d.close(); d.remove(); res(b.dataset.r === '1') } })
      d.addEventListener('cancel', function () { d.remove(); res(false) })
      d.showModal()
    })
  }

  // ───────────── 動作 ─────────────
  proto.select = function (key) { this.sel = key || ''; this.renderCenter(); this.renderRight(); this.emit('select', this.sel) }
  proto.showPane = function (p) {
    if (p === 'right-if-narrow') { if (this.root.clientWidth <= 960) p = 'right'; else return }
    this.pane = p; this.els.panes.setAttribute('data-pane', p)
    $$('button', this.els.tabs).forEach(function (b) { b.setAttribute('aria-selected', String(b.dataset.pane === p)) })
  }
  proto.paletteEntry = function (id) {
    var els = this.caps.elements || DEFAULT_ELEMENTS
    return els.find(function (e) { return e.id === id }) || null
  }
  proto.addEntry = function (entry, at) {
    var d = this.def, f
    if (entry.field) {                                   // 現成欄位（請款常用）：代碼固定
      if (M.fieldByKey(d, entry.field.key)) { this.focus(entry.field.key); return }
      f = M.clone(entry.field)
      M.addField(d, { id: f.type, type: f.type, preset: {} }, f.label, at, this.sel)
      var created = d.fields[d.fields.length - 1] || null
      // addField 會自己產生代碼：改回固定代碼，並把區塊／清單裡的舊代碼換掉
      var oldKey = created && created.key
      Object.assign(created, f)
      this._renameKey(oldKey, f.key)
      this.sel = f.key
    } else {
      var el = entry.el, label = entry.label
      if (el.id === 'money') { el = { id: 'number', type: 'number', preset: { min: 0 } } }
      if (el.type === 'table' && this.caps.onlyOneTable && d.fields.some(function (x) { return x.type === 'table' })) { this.toast('這張表單只能有一個明細表。'); return }
      this.sel = M.addField(d, el, label, at, this.sel)
      if (el.type === 'table' && this.caps.onlyOneTable) { var tf = M.fieldByKey(d, this.sel); this._renameKey(tf.key, this.caps.onlyOneTable); tf.key = this.caps.onlyOneTable; this.sel = tf.key }
    }
    this.commit(); this.renderAll(); this.showPane('right-if-narrow')
    var n = $('.fd-fld[data-key="' + this.sel + '"]', this.els.center); if (n && n.scrollIntoView) n.scrollIntoView({ block: 'nearest' })
    var inp = $('[data-fd="label"]', this.els.right); if (inp) { inp.focus(); inp.select() }
  }
  proto._renameKey = function (from, to) {
    var d = this.def
    ;((d.ui && d.ui.form && d.ui.form.groups) || []).forEach(function (g) { g.fields = (g.fields || []).map(function (k) { return k === from ? to : k }) })
    var cols = M.listColumns(d); for (var i = 0; i < cols.length; i++) if (cols[i] === from) cols[i] = to
  }
  proto.removeFieldConfirm = function (key) {
    var self = this, f = M.fieldByKey(this.def, key); if (!f) return
    var uses = M.usedBy(this.def, key)
    if (uses.length) return this.ask('先不要刪「' + (f.label || key) + '」', '<p>下面這些地方還在用它，請先改掉：</p><ul>' + uses.map(function (u) { return '<li>' + esc(u.text) + '</li>' }).join('') + '</ul>')
    var protectedKey = (this.caps.fixedTypeKeys && this.caps.fixedTypeKeys[key]) || (this.caps.publishedKeys || []).indexOf(key) >= 0
    var go = function () {
      var before = JSON.stringify(self.def)
      M.removeField(self.def, key); if (self.sel === key) self.sel = ''
      self.commit(); self.renderAll()
      self.toast('已刪除「' + (f.label || key) + '」', '復原', function () { self.def = JSON.parse(before); self.commit(); self.renderAll() })
    }
    if (protectedKey) return this.ask('確定要刪除「' + (f.label || key) + '」？', '<p>這個欄位' + ((this.caps.fixedTypeKeys && this.caps.fixedTypeKeys[key]) ? '是請款單的固定欄位，系統其他地方會用到它。' : '已經在發布的版本裡，舊單據用得到它。') + '刪掉後，重新整理頁面就無法復原了。</p>', '確定刪除').then(function (ok) { if (ok) go() })
    go()
  }

  // ───────────── 畫面 ─────────────
  proto.renderAll = function () { this.renderBar(); this.renderLeft(); this.renderCenter(); this.renderRight() }
  proto.renderBar = function () {
    var n = this.allProblems().length
    this.els.bar.innerHTML = '<button type="button" class="fd-btn fd-btn--icon" data-fd-act="undo" title="復原（Ctrl+Z）" aria-label="復原"' + (this.at <= 0 ? ' disabled' : '') + '>' + ic('undo') + '</button>' +
      '<button type="button" class="fd-btn fd-btn--icon" data-fd-act="redo" title="重做（Ctrl+Y）" aria-label="重做"' + (this.at >= this.hist.length - 1 ? ' disabled' : '') + '>' + ic('redo') + '</button>' +
      '<span class="fd-grow"></span><button type="button" class="fd-btn" data-fd-act="check" title="把每個設定的白話標題、一句說明和例子列成一張表，方便檢查字句">用語檢查表</button>' + (n ? '<button type="button" class="fd-btn fd-btn--warn" data-fd-act="problems">' + ic('warn') + n + ' 個地方要改</button>' : '<span class="fd-ok">' + ic('done') + '目前沒有要改的地方</span>') +
      '<div class="fd-seg" role="group" aria-label="檢視"><button type="button" data-fd-mode="edit" aria-pressed="' + (this.mode === 'edit') + '">編輯</button><button type="button" data-fd-mode="final" aria-pressed="' + (this.mode === 'final') + '">看成品</button></div>'
  }
  proto.renderLeft = function () {
    var self = this, els = this.caps.elements || DEFAULT_ELEMENTS, byId = {}, h = ''
    els.forEach(function (e) { byId[e.id] = e })
    var money = byId.number ? { id: 'money', type: 'number', preset: { min: 0 } } : null
    var entries = []   // {id,name,desc,icon,group,el}
    Object.keys(FRIENDLY).forEach(function (id) {
      var e = id === 'money' ? money : byId[id]
      if (e) entries.push({ id: id, name: FRIENDLY[id][0], desc: FRIENDLY[id][1], icon: FRIENDLY[id][2], group: FRIENDLY[id][3], el: e, label: FRIENDLY[id][0] })
    })
    els.forEach(function (e) { if (!FRIENDLY[e.id] && e.id !== e.type) return; if (!FRIENDLY[e.id] && e.type !== 'ref') entries.push({ id: e.id, name: e.label || e.id, desc: '', icon: 'text', group: 'other', el: e, label: e.label || e.id }) })
    this._entries = {}
    entries.forEach(function (x) { self._entries[x.id] = x })
    var hasTable = (this.def.fields || []).some(function (f) { return f.type === 'table' })
    h += '<h2>加入欄位</h2><p class="fd-hint">點一下加到表單裡，或拖到中間想放的位置。</p>'
    ;(this.caps.extraPalette || []).forEach(function (g, gi) {
      h += '<div class="fd-gt">' + esc(g.title) + '</div><div class="fd-tiles">' + g.items.map(function (it, ii) {
        var have = M.fieldByKey(self.def, it.field.key)
        self._entries['x' + gi + '_' + ii] = { field: it.field, label: it.label }
        return '<button type="button" class="fd-tile" draggable="true" data-add="x' + gi + '_' + ii + '">' + ic(it.icon || 'text') + '<b>' + esc(it.label) + '</b><small>' + esc(have ? '已加入（點一下找到它）' : it.desc || '') + '</small></button>'
      }).join('') + '</div>'
    })
    PAL_GROUPS.forEach(function (g) {
      var list = entries.filter(function (x) { return x.group === g[0] }); if (!list.length) return
      h += '<div class="fd-gt">' + g[1] + '</div><div class="fd-tiles">' + list.map(function (x) {
        var dis = x.el.type === 'table' && self.caps.onlyOneTable && hasTable
        return '<button type="button" class="fd-tile" draggable="' + !dis + '" data-add="' + esc(x.id) + '"' + (dis ? ' disabled' : '') + '>' + ic(x.icon) + '<b>' + esc(x.name) + '</b><small>' + esc(dis ? '這張表單已經有明細表了' : x.desc) + '</small></button>'
      }).join('') + '</div>'
    })
    this.els.left.innerHTML = h
  }

  function money(f) { return f.type === 'number' && f.min === 0 }
  proto.fillLabel = function (f) {
    var s = M.fillSelection(f); if (!s) return ''
    if (s.charAt(0) === '*') return s === '*option' ? '指定的選項' : '你填的內容'
    var r = this.registry().find(function (x) { return x.token === s }); return r ? r.label : s
  }
  proto.fillExample = function (f) {
    var d = f.default
    if (d && typeof d === 'object' && d.$) { var r = this.registry().find(function (x) { return x.token === d.$ }); return r ? r.example : '' }
    return typeof d === 'string' ? d : ''
  }
  proto.calcOf = function (f) { if (f._calc === undefined) f._calc = M.parseCalcExact(f.formula); return f._calc }
  proto.formulaText = function (f) {
    var c = this.calcOf(f)
    if (c === null) return '進階公式'
    if (!c.p) return '還沒選要算什麼'
    var meta = M.CALCS.find(function (x) { return x.id === c.p }).name
    return meta
  }
  function fmtNum(n) { return Number(n).toLocaleString('en-US') }
  proto.control = function (f) {
    var kind = M.kindOf(f), opts = f.options || [], dv = this.fillExample(f)
    var val = function (t, ph) { return '<span class="' + (t ? 'fd-val' : '') + '">' + esc(t || ph) + '</span>' }
    switch (f.type) {
      case 'text': return '<div class="fd-ctl">' + val(dv, f.placeholder || '請輸入') + '</div>'
      case 'textarea': return '<div class="fd-ctl fd-ctl--tall">' + val(dv, f.placeholder || '請輸入…') + '</div>'
      case 'number': return '<div class="fd-ctl">' + val(dv, f.placeholder || '0') + (money(f) ? '<span class="fd-end">元</span>' : '') + '</div>'
      case 'date': return '<div class="fd-ctl">' + ic(f.withTime ? 'clock' : 'cal') + val(dv, f.withTime ? '選擇日期和時間' : '選擇日期') + '</div>'
      case 'daterange': return '<div class="fd-ctl">' + ic('range') + '<span>開始</span><span>→</span><span>結束</span></div>'
      case 'select': case 'multiselect': return '<div class="fd-ctl">' + val(dv, '請選擇') + '<span class="fd-end">▾</span></div>'
      case 'radio': case 'checkboxes':
        return '<div class="fd-choices">' + (opts.length ? opts.slice(0, 5).map(function (o) { return '<span><i class="' + (f.type === 'radio' ? 'round' : '') + (o === f.default ? ' on' : '') + '"></i>' + esc(o) + '</span>' }).join('') + (opts.length > 5 ? '<span class="fd-dim">…還有 ' + (opts.length - 5) + ' 個</span>' : '') : '<span class="fd-dim">（還沒有選項）</span>') + '</div>'
      case 'checkbox': return '<div class="fd-choices"><span><i></i>是</span></div>'
      case 'file': return '<div class="fd-drop">' + ic('clip') + '選擇檔案，或把檔案拖到這裡</div>'
      case 'image': return '<div class="fd-drop">' + ic('image') + '選擇圖片，或把圖片拖到這裡</div>'
      case 'ref': return '<div class="fd-ctl">' + ic(f.target === 'departments' ? 'dept' : 'user') + val(dv, f.target === 'departments' ? (f.multiple ? '選擇部門（可多選）' : '選擇部門') : (f.multiple ? '選擇人員（可多選）' : '選擇人員')) + '</div>'
      case 'formula':
        var c = this.calcOf(f), r = c ? M.calcResult(this.def, c) : null
        return '<div class="fd-ctl fd-ctl--sum">' + ic('calc') + '<span class="fd-val">' + esc(this.formulaText(f)) + '</span><span class="fd-end">' + (r == null ? '—' : esc(fmtNum(r)) + (c.p === 'days' ? ' 天' : '')) + '</span></div>'
      case 'table':
        return '<table class="fd-mt"><thead><tr>' + (f.columns || []).map(function (c) { return '<th>' + esc(c.label) + '</th>' }).join('') + '</tr></thead><tbody><tr>' + (f.columns || []).map(function (c) { return '<td class="' + (c.type === 'formula' ? 'auto' : '') + '">' + (c.type === 'formula' ? '自動' : '') + '</td>' }).join('') + '</tr></tbody></table><div class="fd-dim fd-addrow">＋ ' + esc(f.addLabel || '新增一列') + '</div>'
    }
    return '<div class="fd-ctl">' + esc(f.type) + '</div>'
  }
  function isWide(f) { return ['textarea', 'table', 'file', 'image', 'radio', 'checkboxes', 'daterange', 'multiselect'].indexOf(f.type) >= 0 }
  proto.renderCenter = function () {
    var self = this, d = this.def, view = M.groupsOf(d), explicit = M.hasExplicitGroups(d), final = this.mode === 'final'
    var h = '<div class="fd-paper' + (final ? ' is-final' : '') + '"><div class="fd-head"><div class="fd-title">' + esc(d.name || this.caps.titleFallback || '（未命名的表單）') + '</div><p>' +
      (final ? '這就是使用者會看到的樣子。' : '中間就是使用者會看到的表單。點任何一個欄位，右邊會出現它的設定。') + '</p></div>'
    if (!(d.fields || []).length) h += '<div class="fd-bigempty">' + ic('lines') + '<h3>還沒有任何欄位</h3><p>從左邊點一個欄位（例如「文字」），它就會出現在這張表單上。</p></div>'
    view.forEach(function (g, gi) {
      var real = !g.virtual && !g.other
      h += '<section class="fd-sec' + (g.other ? ' is-other' : '') + '" data-sec="' + gi + '">'
      if (!g.virtual) {
        h += '<div class="fd-sechead">' + (real ? '<input value="' + esc(g.title) + '" data-fd-sectitle="' + gi + '" aria-label="區塊名稱"' + (final ? ' readonly' : '') + '>' +
          '<span class="fd-sectools"><button type="button" class="fd-mini" data-sec-up="' + gi + '" title="區塊往上移" aria-label="區塊往上移"' + (gi === 0 ? ' disabled' : '') + '>' + ic('up') + '</button>' +
          '<button type="button" class="fd-mini" data-sec-down="' + gi + '" title="區塊往下移" aria-label="區塊往下移"' + (gi >= self._realCount(view) - 1 ? ' disabled' : '') + '>' + ic('down') + '</button>' +
          '<button type="button" class="fd-mini fd-del" data-sec-del="' + gi + '" title="刪除這個區塊" aria-label="刪除這個區塊">' + ic('trash') + '</button></span>'
          : '<b class="fd-sectitle">其他</b><span class="fd-dim">還沒放進任何區塊的欄位，使用者會在「其他」看到。拖到上面的區塊就會歸位。</span>') + '</div>'
      }
      h += '<div class="fd-grid">'
      if (!g.keys.length) h += '<div class="fd-slot fd-empty" data-slot data-g="' + gi + '" data-i="0"><b>這個區塊還是空的</b>把左邊的欄位拖到這裡，或在左邊點一下。</div>'
      g.keys.forEach(function (k, i) {
        var f = M.fieldByKey(d, k); if (!f) return
        var probs = self.problemsOf(k), cashier = f.editableBy === 'cashier'
        h += '<div class="fd-slot" data-slot data-g="' + gi + '" data-i="' + i + '"></div>'
        h += '<div class="fd-fld' + (isWide(f) ? ' is-wide' : '') + (self.sel === k ? ' is-sel' : '') + (probs.length ? ' is-bad' : '') + '" data-key="' + esc(k) + '" draggable="' + !final + '" tabindex="0" role="button" aria-label="欄位：' + esc(f.label) + '">' +
          '<div class="fd-fbar"><span class="fd-mini fd-grip" title="拖著走">' + ic('grip') + '</span>' +
          '<button type="button" class="fd-mini" data-act="up" title="往上移（Alt+↑）" aria-label="往上移">' + ic('up') + '</button>' +
          '<button type="button" class="fd-mini" data-act="down" title="往下移（Alt+↓）" aria-label="往下移">' + ic('down') + '</button>' +
          '<button type="button" class="fd-mini" data-act="dup" title="複製" aria-label="複製">' + ic('copy') + '</button>' +
          '<button type="button" class="fd-mini" data-act="del" title="刪除（Delete）" aria-label="刪除">' + ic('trash') + '</button></div>' +
          '<label>' + esc(f.label) + (f.required ? '<span class="fd-req" aria-hidden="true">*</span>' : '') + (cashier ? '<span class="fd-chip">只有出納填</span>' : '') + (f.locked ? '<span class="fd-chip">自動帶入</span>' : '') + (probs.length ? '<span class="fd-chip fd-chip--bad" title="' + esc(probs.map(function (p) { return p.message }).join('；')) + '">要修改</span>' : '') + '</label>' +
          self.control(f) + (f.help ? '<div class="fd-help">' + esc(f.help) + '</div>' : '') + '</div>'
      })
      if (g.keys.length) h += '<div class="fd-slot" data-slot data-g="' + gi + '" data-i="' + g.keys.length + '"></div>'
      h += '</div></section>'
    })
    h += '<button type="button" class="fd-addsec" data-fd-act="addsec">＋ 新增區塊</button></div>'
    this.els.center.innerHTML = h
  }
  proto._realCount = function (view) { return view.filter(function (g) { return !g.virtual && !g.other }).length }

  // ── 右欄 ──
  function sw(id, on, title, why, ex, disabled) {
    return '<div class="fd-switch"><div class="fd-txt"><b>' + title + '</b><small>' + why + '</small><small class="fd-ex">例：' + ex + '</small></div><button type="button" class="fd-sw" role="switch" data-sw="' + id + '" aria-checked="' + on + '" aria-label="' + esc(title) + '"' + (disabled ? ' disabled' : '') + '></button></div>'
  }
  proto.itemList = function (arr, id, addText) {
    return '<ul class="fd-items" data-items="' + id + '">' + arr.map(function (v, i) {
      return '<li draggable="true" data-i="' + i + '"><span class="fd-handle" title="拖著排順序">' + ic('grip') + '</span><input class="fd-in" data-item="' + id + ':' + i + '" value="' + esc(v) + '" aria-label="第 ' + (i + 1) + ' 個"><button type="button" class="fd-mini fd-del" data-item-del="' + id + ':' + i + '" aria-label="刪除這一個">✕</button></li>'
    }).join('') + '</ul><button type="button" class="fd-additem" data-item-add="' + id + '">＋ ' + addText + '（或在最後一格按 Enter）</button>'
  }
  proto.renderRight = function () {
    var f = this.cur(), el = this.els.right, self = this
    if (!f) {
      var ps = this.allProblems()
      el.innerHTML = '<div class="fd-guide">' + ic('click') + '<h3>先點一個欄位</h3><p>點中間表單裡的任何一個欄位，<br>它的設定會出現在這裡。</p></div>' +
        (ps.length ? '<div class="fd-box fd-box--warn"><h3>' + ic('warn') + '要修改的地方</h3><ul class="fd-plist">' + ps.map(function (p, i) { return '<li><button type="button" data-prob="' + i + '">' + esc(p.message) + '</button></li>' }).join('') + '</ul></div>' : '')
      this._probList = ps
      return
    }
    var T = this.kindName(f), h = '', fixed = this.caps.fixedTypeKeys && this.caps.fixedTypeKeys[f.key]
    var probs = this.problemsOf(f.key)
    h += '<h2>這個欄位</h2><div class="fd-convert"><span class="fd-tag">' + esc(T) + '</span>'
    var conv = ['text', 'textarea', 'select', 'radio', 'multiselect', 'checkboxes']
    if (!fixed && conv.indexOf(f.type) >= 0) {
      h += '<label class="fd-dim" for="' + this.id('conv') + '">想改成：</label><select class="fd-in fd-in--auto" id="' + this.id('conv') + '" data-fd="conv">' + conv.filter(function (t) { return self.paletteEntry(t) }).map(function (t) { return '<option value="' + t + '"' + (t === f.type ? ' selected' : '') + '>' + FRIENDLY[t][0] + '</option>' }).join('') + '</select>'
    } else if (fixed) h += '<span class="fd-dim">固定欄位，種類不能改</span>'
    h += '</div>'
    if (probs.length) h += '<div class="fd-box fd-box--warn"><ul class="fd-plist">' + probs.map(function (p) { return '<li>' + esc(p.message) + '</li>' }).join('') + '</ul></div>'
    h += '<div class="fd-box"><div class="fd-row"><label for="' + this.id('label') + '">欄位名稱</label><input class="fd-in" id="' + this.id('label') + '" data-fd="label" value="' + esc(f.label) + '"><div class="fd-why">表單上顯示給使用者看的字。例：「出差地點」。</div></div>'
    h += '<div class="fd-row"><label for="' + this.id('help') + '">說明文字（選填）</label><input class="fd-in" id="' + this.id('help') + '" data-fd="help" value="' + esc(f.help || '') + '" placeholder="例如：請填發票上的金額"><div class="fd-why">會用小字顯示在欄位下面。例：欄位下方出現灰色小字「請填發票上的金額」。</div></div>'
    if (f.type !== 'formula' && f.type !== 'table') h += sw('required', !!f.required, '一定要填', '開起來，使用者沒填就不能送出。', '「地點」開起來 ⇒ 沒填地點，按送出會跳出提醒。')
    h += '</div>'
    if (M.OPTION_TYPES[f.type]) h += '<div class="fd-box"><h3>選項（使用者可以選哪些）</h3>' + this.itemList(f.options || [], 'opt', '新增一個選項') + '<div class="fd-why">打字後按 Enter 就會多一格；也可以一次貼上很多行。例：「國內」Enter「國外」⇒ 兩個選項。</div></div>'
    if (f.type === 'formula') h += '<div class="fd-box"><h3>自動計算</h3>' + this.calcUI(f, f) + '</div>'
    if (f.type === 'table') h += this.tableUI(f)
    h += this.fillUI(f)
    h += '<div class="fd-box"><h3>誰能填、怎麼顯示</h3>'
    var cashierOk = !this.caps.cashierKeys || this.caps.cashierKeys.indexOf(f.key) >= 0
    if (f.type !== 'formula') h += sw('cashier', f.editableBy === 'cashier', '只有出納能修改', cashierOk ? '其他人看得到，但不能填；只有出納可以改。' : '這個設定只有付款相關的欄位（付款條件、匯款日、付款日）能用。', '「付款日」：業務只看得到，出納才能填。', !cashierOk && f.editableBy !== 'cashier')
    var hasFill = M.fillSelection(f) !== '', lk = M.canLock(f, this.registry())
    if (f.type !== 'formula' && f.type !== 'table') h += sw('locked', !!f.locked, hasFill ? '「' + esc(this.fillLabel(f)) + '」不能改' : '帶入的內容不能改', !hasFill ? '要先在上面選好「自動帶入」才能開。' : (lk.ok ? '使用者看得到這一格，但不能自己改掉。' : '這個帶入來源每次可能不一樣，所以不能鎖住。'), hasFill ? '「申請人」自動帶入王小明，別人不能改成別人。' : '先選「申請人本人」，這裡才會能開。', !lk.ok && !f.locked)
    h += sw('listed', M.isListed(this.def, f.key), '在清單中顯示', '開起來，這個欄位會出現在「單據清單」的表格裡。', '開起來 ⇒ 清單多一欄「' + esc(f.label) + '」。')
    h += '</div>'
    h += this.moreUI(f)
    if (this.caps.isSuper) h += '<details class="fd-adv"><summary>進階設定（只有最高管理者看得到）</summary><div class="fd-row"><label>系統內部代碼</label><input class="fd-in" value="' + esc(f.key) + '" readonly aria-readonly="true"><div class="fd-why">自動產生，發布後不能改（舊單據靠它找資料）。改「欄位名稱」不會動它。例：place。</div></div>' +
      (f.type === 'formula' && this.calcOf(f) === null ? '<div class="fd-row"><label>舊的文字公式</label><input class="fd-in" value="' + esc(f.formula) + '" readonly><div class="fd-why">這是用文字寫的公式，只有在這裡看得到；選上面的計算器就會取代它。例：round_half_up(qty * unitCost)。</div></div>' : '') + '</details>'
    h += '<button type="button" class="fd-dangerbtn" data-fd-act="delsel">' + ic('trash') + ' 刪除這個欄位</button>'
    el.innerHTML = h
  }
  proto.kindName = function (f) {
    var k = M.kindOf(f)
    if (f.type === 'number' && money(f)) return '金額'
    var map = { user: 'user', users: 'users', dept: 'dept', depts: 'depts', datetime: 'datetime' }
    return (FRIENDLY[map[k] || f.type] || [f.type])[0]
  }

  // 自動帶入
  proto.fillUI = function (f) {
    var self = this, k = f.type
    if (['text', 'textarea', 'number', 'date', 'select', 'radio', 'checkbox', 'ref'].indexOf(k) < 0) return ''
    var val = M.fillSelection(f), list = M.fillsFor(f, this.registry(), !!this.caps.hasCase), extra = '', info = ''
    var h = '<div class="fd-box"><div class="fd-row"><label for="' + this.id('fill') + '">自動帶入</label><select class="fd-in" id="' + this.id('fill') + '" data-fd="fill"><option value="">不帶入（讓使用者自己填）</option>'
    list.forEach(function (s) { h += '<option value="' + esc(s.token) + '"' + (val === s.token ? ' selected' : '') + '>' + esc(s.label) + '</option>' })
    if (['text', 'textarea', 'number', 'date', 'checkbox'].indexOf(k) >= 0) h += '<option value="*custom"' + (val === '*custom' ? ' selected' : '') + '>' + (k === 'date' ? '固定某一天' : k === 'checkbox' ? '先勾起來' : '固定的內容（我自己打）') + '</option>'
    if (k === 'select' || k === 'radio') h += '<option value="*option"' + (val === '*option' ? ' selected' : '') + '>先選好某一個選項</option>'
    h += '</select>'
    if (val === '*custom' && k !== 'checkbox') extra = '<input class="fd-in fd-mt6" data-fd="fillText" ' + (k === 'date' ? 'type="date"' : '') + ' value="' + esc(f.default) + '" placeholder="要預先填好的內容">'
    if (val === '*option') extra = '<select class="fd-in fd-mt6" data-fd="fillOpt">' + (f.options || []).map(function (x) { return '<option' + (x === f.default ? ' selected' : '') + '>' + esc(x) + '</option>' }).join('') + '</select>'
    var reg = this.registry().find(function (x) { return x.token === val })
    if (val === '') info = '欄位一開始是空的。<br>使用者會看到：（空白）'
    else if (reg) info = '<b>' + esc(reg.label) + '</b>：' + esc(reg.why) + '<br>使用者會看到：' + esc(reg.example)
    else if (val.charAt(0) === '*') info = '使用者會看到你預先填好的內容。'
    else info = '這個帶入來源目前系統不認得（' + esc(val) + '），原樣保留。'
    return h + extra + '<div class="fd-why fd-exbox">' + info + '</div></div></div>'
  }

  // 計算器（f＝存 formula 的物件：欄位或明細表的欄；scope 決定能選哪些欄）
  proto.calcScope = function (owner) {
    var d = this.def
    if (owner.type === 'formula' && d.fields.indexOf(owner) >= 0) {
      return { nums: d.fields.filter(function (x) { return x.type === 'number' && x !== owner }).map(function (x) { return [x.key, x.label] }),
        dates: d.fields.filter(function (x) { return x.type === 'date' }).map(function (x) { return [x.key, x.label] }),
        tbls: [].concat.apply([], d.fields.filter(function (x) { return x.type === 'table' }).map(function (t) { return (t.columns || []).filter(function (c) { return c.type === 'number' || c.type === 'formula' }).map(function (c) { return [t.key + '|' + c.key, t.label + ' ➜ 每一列的「' + c.label + '」'] }) })), inTable: false }
    }
    return null
  }
  function sel(dataKey, val, opts, ph, extra) {
    return '<select class="fd-in" data-fd="' + dataKey + '"' + (extra || '') + '><option value="">' + ph + '</option>' + opts.map(function (o) { return '<option value="' + esc(o[0]) + '"' + (o[0] === val ? ' selected' : '') + '>' + esc(o[1]) + '</option>' }).join('') + '</select>'
  }
  proto.calcUI = function (f, owner, colScope) {
    var c = owner._calc === undefined ? (owner._calc = M.parseCalcExact(owner.formula)) : owner._calc
    var scope = colScope || this.calcScope(owner)
    var allowed = colScope ? ['mul', 'sub', 'pct', 'sum'] : M.CALCS.map(function (x) { return x.id })
    var h = ''
    if (c === null) h += '<div class="fd-row"><span class="fd-tag">進階公式</span><div class="fd-why">這是用文字寫的舊公式，系統原樣保留。想換成現成的計算器，選下面任何一個就會取代它。例：round_half_up(qty * unitCost) ＝「數量 × 單價」四捨五入。</div></div>'
    c = c || { p: '' }
    var scopeAttr = colScope ? ' data-col="' + colScope.colIndex + '"' : ''
    h += '<div class="fd-row"><span class="fd-lbl">選一個計算器</span><div class="fd-pick" role="radiogroup" aria-label="計算器">' + M.CALCS.filter(function (x) { return allowed.indexOf(x.id) >= 0 }).map(function (x) {
      return '<label class="fd-calc"><input type="radio" name="' + (colScope ? 'calc' + colScope.colIndex : 'calc') + '" data-fd="calc" value="' + x.id + '"' + scopeAttr + (c.p === x.id ? ' checked' : '') + '><b>' + x.name + '</b><span>' + x.why + '<br>例：' + x.ex + '</span></label>'
    }).join('') + '</div></div>'
    if (!c.p) return h
    var nums = scope.nums, dates = scope.dates || [], tbls = scope.tbls || []
    var data = function (k) { return 'data-fd="cp' + k + '"' + scopeAttr }
    h += '<div class="fd-box fd-box--in"><h3>' + M.CALCS.find(function (x) { return x.id === c.p }).name + '：設定</h3>'
    var S = function (k, v, o, ph) { return '<select class="fd-in" ' + data(k) + '><option value="">' + ph + '</option>' + o.map(function (x) { return '<option value="' + esc(x[0]) + '"' + (x[0] === v ? ' selected' : '') + '>' + esc(x[1]) + '</option>' }).join('') + '</select>' }
    if (c.p === 'sumtable') h += '<div class="fd-row"><label>加哪一欄？</label>' + S('T', c.tbl && c.col ? c.tbl + '|' + c.col : '', tbls, '請選擇…') + '<div class="fd-why">例：費用明細每一列的「小計」。</div></div>'
    if (c.p === 'sum') h += '<div class="fd-row"><span class="fd-lbl">勾選要加起來的欄位</span><div class="fd-pick">' + (nums.length ? nums.map(function (n) { return '<label class="fd-opt"><input type="checkbox" ' + data('Key') + ' value="' + esc(n[0]) + '"' + ((c.keys || []).indexOf(n[0]) >= 0 ? ' checked' : '') + '>' + esc(n[1]) + '</label>' }).join('') : '<div class="fd-why">表單裡還沒有數字欄位，先在左邊加一個「數字」或「金額」。</div>') + '</div><div class="fd-why">例：勾「機票」和「住宿」，這格就是兩個加起來。</div></div>'
    if (c.p === 'mul' || c.p === 'sub') h += '<div class="fd-row"><label>' + (c.p === 'mul' ? '第一個數字' : 'A（被減的數字）') + '</label>' + S('A', c.a, nums, '請選擇…') + '<div class="fd-why">' + (c.p === 'mul' ? '例：「數量」。' : '例：「預算」。') + '</div></div><div class="fd-row"><label>' + (c.p === 'mul' ? '第二個數字' : 'B（要減掉的數字）') + '</label>' + S('B', c.b, nums, '請選擇…') + '<div class="fd-why">' + (c.p === 'mul' ? '例：「單價」。' : '例：「已用」。') + '</div></div>'
    if (c.p === 'pct') h += '<div class="fd-row"><label>拿哪個金額來算？</label>' + S('A', c.a, nums, '請選擇…') + '<div class="fd-why">例：「總額」。</div></div><div class="fd-row"><label>要幾 %？</label><input class="fd-in" ' + data('Pct') + ' type="number" min="0" max="100" value="' + esc(c.pct == null ? '' : c.pct) + '" placeholder="例如 30"><div class="fd-why">例：填 30 就是 30%（訂金常用）。</div></div>'
    if (c.p === 'days') h += '<div class="fd-row"><label>開始日期</label>' + S('A', c.a, dates, '請選擇…') + '<div class="fd-why">例：「出發日」。</div></div><div class="fd-row"><label>結束日期</label>' + S('B', c.b, dates, '請選擇…') + '<div class="fd-why">例：「返回日」。</div></div>'
    if (c.p === 'tax') {
      h += '<div class="fd-row"><label>金額是哪一欄？</label>' + S('A', c.a, nums, '請選擇…') + '<div class="fd-why">例：「未稅金額」。</div></div>'
      h += '<div class="fd-row"><label>你輸入的金額是</label><select class="fd-in" ' + data('Mode') + '><option value="net"' + (c.mode !== 'split' ? ' selected' : '') + '>未稅（算出稅）</option><option value="split"' + (c.mode === 'split' ? ' selected' : '') + '>含稅（拆出稅）</option></select><div class="fd-why">例：發票上寫的是不含稅的價錢 ⇒ 選「未稅」。</div></div>'
      if (c.mode !== 'split') h += '<div class="fd-row"><label>要算出</label><select class="fd-in" ' + data('Out') + '><option value="tax"' + (c.out !== 'gross' ? ' selected' : '') + '>稅額</option><option value="gross"' + (c.out === 'gross' ? ' selected' : '') + '>含稅金額</option></select><div class="fd-why">例：要看稅是多少 ⇒ 選「稅額」；要看總共付多少 ⇒ 選「含稅金額」。</div></div>'
      h += '<div class="fd-row"><label>稅率</label><select class="fd-in" ' + data('Rate') + '><option value="5"' + (!c.rate || c.rate === '5' ? ' selected' : '') + '>5%（一般營業稅）</option><option value="free"' + (c.rate === 'free' ? ' selected' : '') + '>免稅</option><option value="custom"' + (c.rate === 'custom' ? ' selected' : '') + '>自己填</option></select>' + (c.rate === 'custom' ? '<input class="fd-in fd-mt6" ' + data('Custom') + ' type="number" min="0" max="100" value="' + esc(c.custom || '') + '" placeholder="稅率 %">' : '') + '<div class="fd-why">例：一般營業稅選 5%；外銷選免稅；其他稅率自己填（填 3 代表 3%）。</div></div>'
    }
    var r = M.calcResult(this.def, c)
    return h + '<div class="fd-why fd-strong">範例結果：' + (r == null ? '（先把上面選好）' : fmtNum(r) + (c.p === 'days' ? ' 天' : '')) + '</div></div>'
  }
  proto.applyCalc = function (owner, target, attr, value, checked, scopeIdx) {
    var c = owner._calc === undefined ? M.parseCalcExact(owner.formula) : owner._calc
    c = c || { p: '' }
    if (attr === 'calc') c = { p: value, keys: [], rate: '5' }
    else if (attr === 'cpT') { var p = value.split('|'); c.tbl = p[0] || ''; c.col = p[1] || '' }
    else if (attr === 'cpA') c.a = value
    else if (attr === 'cpB') c.b = value
    else if (attr === 'cpPct') c.pct = value
    else if (attr === 'cpMode') c.mode = value
    else if (attr === 'cpOut') c.out = value
    else if (attr === 'cpRate') c.rate = value
    else if (attr === 'cpCustom') c.custom = value
    else if (attr === 'cpKey') { var set = (c.keys || []).slice(); var i = set.indexOf(value); if (checked && i < 0) set.push(value); if (!checked && i >= 0) set.splice(i, 1); c.keys = set }
    owner._calc = c; owner.formula = M.buildCalc(c)
  }

  // 明細表
  proto.tableUI = function (f) {
    var self = this, cols = f.columns || [], reqCols = this.caps.requiredColumns || [], max = this.caps.maxRows || 200
    var h = '<div class="fd-box"><h3>明細表的設定</h3>'
    h += '<div class="fd-row fd-two"><div><label>最少幾列</label><input class="fd-in" type="number" min="0" max="' + max + '" data-fd="minRows" value="' + esc(f.minRows == null ? '' : f.minRows) + '"></div><div><label>最多幾列</label><input class="fd-in" type="number" min="0" max="' + max + '" data-fd="maxRows" value="' + esc(f.maxRows == null ? '' : f.maxRows) + '"></div><div class="fd-why fd-span">表格至少／最多可以有幾列（上限 ' + max + '）。例：最少 1 列、最多 20 列。</div></div>'
    h += '<div class="fd-row"><label>新增按鈕的字</label><input class="fd-in" data-fd="addLabel" value="' + esc(f.addLabel || '') + '" placeholder="新增一列"><div class="fd-why">表格下方那顆按鈕上的字。例：「新增一筆費用」。</div></div>'
    h += '<div class="fd-lbl">表格的欄位</div><ul class="fd-cols">' + cols.map(function (c, i) {
      var must = reqCols.indexOf(c.key) >= 0
      var open = self._colOpen === f.key + ':' + i
      var body = ''
      if (open) {
        body += '<div class="fd-colbody"><div class="fd-row"><label>這一欄是什麼種類</label><select class="fd-in" data-fd="colType" data-col="' + i + '"' + (must && c.key !== 'amount' ? ' disabled' : '') + '>' + COL_TYPES.map(function (t) { return '<option value="' + t[0] + '"' + (t[0] === c.type ? ' selected' : '') + '>' + t[1] + '</option>' }).join('') + '</select><div class="fd-why">例：「數量」選數字、「小計」選自動計算。</div></div>'
        body += sw('colReq:' + i, !!c.required, '這一欄一定要填', '開起來，每一列這格沒填就不能送出。', '「品名」每一列都要填。')
        if (c.type === 'select') body += '<div class="fd-row"><span class="fd-lbl">選項</span>' + (c.optionsFrom ? '<div class="fd-why">選項來自系統設定（' + esc(c.optionsFrom) + '），在這裡不能改。例：費用類別。</div>' : self.itemList(c.options || [], 'col' + i, '新增一個選項') + '<div class="fd-why">例：「交通」「住宿」「餐費」。</div>') + '</div>'
        if (c.type === 'number') body += '<div class="fd-row"><label>最小值</label><input class="fd-in" type="number" data-fd="colMin" data-col="' + i + '" value="' + esc(c.min == null ? '' : c.min) + '"><div class="fd-why">小於這個數字就不能送出。例：數量最小 1。</div></div>'
        if (c.type === 'formula') body += self.calcUI(f, c, { nums: cols.filter(function (x, j) { return j !== i && (x.type === 'number') }).map(function (x) { return [x.key, x.label] }), dates: [], tbls: [], colIndex: i })
        body += '</div>'
      }
      return '<li class="' + (open ? 'is-open' : '') + '"><div class="fd-colhead"><button type="button" class="fd-colname" data-col-open="' + i + '" aria-expanded="' + open + '">' + esc(c.label) + (must ? '<span class="fd-chip">必要</span>' : '') + '<span class="fd-dim">' + esc((COL_TYPES.find(function (t) { return t[0] === c.type }) || [0, c.type])[1]) + '</span></button>' +
        '<button type="button" class="fd-mini" data-col-up="' + i + '" aria-label="往上移"' + (i === 0 ? ' disabled' : '') + '>' + ic('up') + '</button><button type="button" class="fd-mini" data-col-down="' + i + '" aria-label="往下移"' + (i === cols.length - 1 ? ' disabled' : '') + '>' + ic('down') + '</button>' +
        '<button type="button" class="fd-mini fd-del" data-col-del="' + i + '" aria-label="刪除這一欄"' + (must ? ' disabled title="這一欄是必要的"' : '') + '>✕</button></div>' + body + '</li>'
    }).join('') + '</ul><button type="button" class="fd-additem" data-col-add="1">＋ 新增一欄</button>' + this.colPresetUI(f) + '<div class="fd-why">點欄名展開它的設定。標「必要」的欄不能刪。例：「數量」「單價」「發票號碼」。</div></div>'
    return h
  }
  // 常用欄（呼叫端用 caps.columnPresets 提供：[{label, desc, cols:[完整的欄物件…]}]；欄代碼固定，所以從這裡加）
  proto.colPresetUI = function (f) {
    var list = this.caps.columnPresets || [], have = (f.columns || []).map(function (c) { return c.key })
    var todo = list.map(function (p, i) { return { p: p, i: i } }).filter(function (x) { return x.p.cols.some(function (c) { return have.indexOf(c.key) < 0 }) })
    if (!todo.length) return ''
    return '<div class="fd-lbl fd-mt6">加入常用欄</div><div class="fd-presets">' + todo.map(function (x) {
      return '<button type="button" class="fd-btn" data-col-preset="' + x.i + '" title="' + esc(x.p.desc || '') + '">＋ ' + esc(x.p.label) + '</button>'
    }).join('') + '</div>'
  }
  proto.moreUI = function (f) {
    var specs = ((this.caps.specs || {})[f.type] || {}).attrs || [], h = ''
    var items = specs.filter(function (a) { return !HANDLED_ATTRS[a.key] && a.kind !== 'options' && a.kind !== 'columns' && !(f.type === 'table' && ['minRows', 'maxRows', 'addLabel'].indexOf(a.key) >= 0) && !(f.type === 'ref' && a.key === 'multiple' && false) })
    var rows = items.filter(function (a) { return ATTR_COPY[a.key] })
    if (!rows.length) return ''
    rows.forEach(function (a) {
      var c = ATTR_COPY[a.key], v = f[a.key]
      if (a.kind === 'bool') h += sw('attr:' + a.key, !!v, c[0], c[1], c[2])
      else if (a.kind === 'exts') h += '<div class="fd-row"><label>' + c[0] + '</label><input class="fd-in" data-fd="attr" data-attr="' + a.key + '" data-kind="exts" value="' + esc(Array.isArray(v) ? v.join(', ') : (v || '')) + '"><div class="fd-why">' + c[1] + ' 例：' + c[2] + '</div></div>'
      else h += '<div class="fd-row"><label>' + c[0] + '</label><input class="fd-in" data-fd="attr" data-attr="' + a.key + '" data-kind="' + a.kind + '" ' + (a.kind === 'int' || a.kind === 'number' ? 'type="number"' : '') + ' value="' + esc(v == null ? '' : v) + '"><div class="fd-why">' + c[1] + ' 例：' + c[2] + '</div></div>'
    })
    return '<div class="fd-box"><h3>更多設定</h3>' + h + '</div>'
  }

  // ───────────── 用語檢查表：每個設定的白話標題＋一句說明＋例子（計算器、自動帶入、目錄屬性取自畫面實際用的資料，改字就同步）─────────────
  var GENERAL_COPY = [
    ['欄位名稱', '表單上顯示給使用者看的字。', '「出差地點」'], ['說明文字（選填）', '會用小字顯示在欄位下面。', '「請填發票上的金額」'],
    ['一定要填', '開起來，使用者沒填就不能送出。', '「地點」開起來 ⇒ 沒填地點，按送出會跳出提醒。'],
    ['想改成', '把這個欄位換成相近的種類。', '文字 ⇒ 單選選單'],
    ['選項（使用者可以選哪些）', '一格一個；Enter 新增下一格，可貼多行、拖曳排序、✕ 刪除。', '「國內」Enter「國外」⇒ 兩個選項'],
    ['自動帶入', '使用者打開表單時，這一格已經填好什麼。', '申請人本人 ⇒ 王小明'],
    ['「○○」不能改', '自動帶入的內容使用者看得到但不能自己改。', '「申請人本人」不能改'],
    ['只有出納能修改', '其他人看得到，但不能填；只有出納可以改。', '「付款日」'],
    ['在清單中顯示', '開起來，這個欄位會出現在「單據清單」的表格裡。', '清單多一欄「地點」'],
    ['明細表的設定', '最少／最多幾列、新增按鈕的字；每一欄可展開設定種類、是否必填、選項、計算。', '最少 1 列、最多 20 列'],
    ['區塊名稱／＋ 新增區塊', '把欄位分成幾段；區塊可上下移、刪除。', '基本資料、出差資訊'],
    ['看成品', '隱藏編輯用的框線，看使用者實際看到的樣子。', '—'],
    ['復原／重做', '做錯可以回上一步（Ctrl+Z／Ctrl+Y）；刪除後 6 秒內也可按「復原」。', '—']
  ]
  proto.showChecklist = function () {
    var rows = GENERAL_COPY.map(function (r) { return ['一般設定', r[0], r[1], r[2]] })
    Object.keys(ATTR_COPY).forEach(function (k) { var c = ATTR_COPY[k]; rows.push(['更多設定', c[0], c[1], c[2]]) })
    M.CALCS.forEach(function (c) { rows.push(['自動計算', c.name, c.why, c.ex]) })
    this.registry().forEach(function (f) { rows.push(['自動帶入的選擇', f.label, f.why, f.example]) })
    var body = '<div class="fd-chk"><table><thead><tr><th>類別</th><th>白話標題</th><th>一句說明</th><th>例子</th></tr></thead><tbody>' + rows.map(function (r) {
      return '<tr><td>' + esc(r[0]) + '</td><td><b>' + esc(r[1]) + '</b></td><td>' + esc(r[2]) + '</td><td>' + esc(r[3] || '—') + '</td></tr>'
    }).join('') + '</tbody></table></div>'
    var d = document.createElement('dialog'); d.className = 'fd-dlg fd-dlg--wide'; d.setAttribute('data-fd-checklist', '1')
    d.innerHTML = '<h3>用語檢查表（共 ' + rows.length + ' 項）</h3><div class="fd-dlg__b">' + body + '</div><div class="fd-dlg__f"><button type="button" class="fd-btn fd-btn--primary" data-r="0">關閉</button></div>'
    this.root.appendChild(d)
    d.addEventListener('click', function (e) { if (e.target.closest('[data-r]')) { d.close(); d.remove() } })
    d.addEventListener('cancel', function () { d.remove() })
    d.showModal()
  }

  // ───────────── 事件 ─────────────
  proto._bind = function () {
    var self = this, L = this.els.left, C = this.els.center, R = this.els.right, B = this.els.bar
    B.addEventListener('click', function (e) {
      var m = e.target.closest('[data-fd-mode]'); if (m) { self.mode = m.dataset.fdMode; self.renderBar(); self.renderCenter(); return }
      var a = e.target.closest('[data-fd-act]'); if (!a) return
      if (a.dataset.fdAct === 'undo') self.undo(); else if (a.dataset.fdAct === 'redo') self.redo()
      else if (a.dataset.fdAct === 'problems') { self.select(''); self.showPane('right-if-narrow') }
      else if (a.dataset.fdAct === 'check') self.showChecklist()
    })
    this.els.tabs.addEventListener('click', function (e) { var b = e.target.closest('button'); if (b) self.showPane(b.dataset.pane) })
    L.addEventListener('click', function (e) { var b = e.target.closest('[data-add]'); if (b && !b.disabled) { var en = self._entries[b.dataset.add]; if (en && en.field && M.fieldByKey(self.def, en.field.key)) self.focus(en.field.key); else if (en) self.addEntry(en) } })
    L.addEventListener('dragstart', function (e) { var b = e.target.closest('[data-add]'); if (!b) return; self.drag = 'new:' + b.dataset.add; e.dataTransfer.setData('text/plain', self.drag); e.dataTransfer.effectAllowed = 'copy' })
    L.addEventListener('dragend', function () { self.drag = null })

    C.addEventListener('click', function (e) {
      if (e.target.closest('[data-fd-act="addsec"]')) { M.addSection(self.def); self.commit(); self.renderCenter(); var i = $$('[data-fd-sectitle]', C).pop(); if (i) { i.focus(); i.select() } return }
      var su = e.target.closest('[data-sec-up]'), sd = e.target.closest('[data-sec-down]'), sx = e.target.closest('[data-sec-del]')
      if (su || sd) { M.moveSection(self.def, +(su || sd).dataset[su ? 'secUp' : 'secDown'], su ? -1 : 1); self.commit(); self.renderCenter(); return }
      if (sx) { self._delSection(+sx.dataset.secDel); return }
      var f = e.target.closest('.fd-fld'); if (!f || self.mode === 'final') return
      var act = e.target.closest('[data-act]'), key = f.dataset.key
      if (act) {
        if (act.dataset.act === 'del') self.removeFieldConfirm(key)
        else if (act.dataset.act === 'dup') { self.sel = M.duplicateField(self.def, key) || self.sel; self.commit(); self.renderAll() }
        else { M.nudge(self.def, key, act.dataset.act === 'up' ? -1 : 1); self.commit(); self.renderCenter(); var n = $('.fd-fld[data-key="' + key + '"]', C); if (n) n.focus() }
        return
      }
      self.select(key); self.showPane('right-if-narrow')
    })
    C.addEventListener('input', function (e) {
      var s = e.target.closest('[data-fd-sectitle]'); if (!s) return
      var gi = +s.dataset.fdSectitle; self.def.ui.form.groups[gi].title = s.value; self.commitSoon()
    })
    C.addEventListener('keydown', function (e) {
      var f = e.target.closest('.fd-fld'); if (!f || e.target !== f) return
      var key = f.dataset.key
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); self.select(key); self.showPane('right-if-narrow') }
      else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); self.removeFieldConfirm(key) }
      else if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) { e.preventDefault(); M.nudge(self.def, key, e.key === 'ArrowUp' ? -1 : 1); self.commit(); self.renderCenter(); var n = $('.fd-fld[data-key="' + key + '"]', C); if (n) n.focus() }
    })
    C.addEventListener('dragstart', function (e) { var f = e.target.closest('.fd-fld'); if (!f) return; self.drag = 'field:' + f.dataset.key; e.dataTransfer.setData('text/plain', self.drag); e.dataTransfer.effectAllowed = 'move'; setTimeout(function () { f.classList.add('is-drag') }, 0) })
    C.addEventListener('dragend', function () { self.drag = null; $$('.is-drag', C).forEach(function (n) { n.classList.remove('is-drag') }); $$('.fd-slot.is-over', C).forEach(function (n) { n.classList.remove('is-over') }) })
    var nearest = function (e) {
      var f = e.target.closest('.fd-fld'); if (!f) return null
      var w = M.findKey(M.groupsOf(self.def), f.dataset.key); if (!w) return null
      var r = f.getBoundingClientRect(), after = e.clientY > r.top + r.height / 2
      return C.querySelector('.fd-slot[data-g="' + w.g + '"][data-i="' + (w.i + (after ? 1 : 0)) + '"]')
    }
    C.addEventListener('dragover', function (e) { if (!self.drag) return; var s = e.target.closest('.fd-slot') || nearest(e); if (!s) return; e.preventDefault(); $$('.fd-slot.is-over', C).forEach(function (n) { n.classList.remove('is-over') }); s.classList.add('is-over') })
    C.addEventListener('drop', function (e) {
      if (!self.drag) return
      var s = e.target.closest('.fd-slot') || nearest(e); if (!s) return
      e.preventDefault(); var d = self.drag; self.drag = null
      var at = { g: +s.dataset.g, i: +s.dataset.i }
      if (d.indexOf('new:') === 0) { var en = self._entries[d.slice(4)]; if (en) self.addEntry(en, at) }
      else if (d.indexOf('field:') === 0) { M.placeKey(self.def, d.slice(6), at.g, at.i); self.commit(); self.renderCenter() }
    })

    R.addEventListener('input', function (e) { self._onInput(e) })
    R.addEventListener('change', function (e) { self._onChange(e) })
    R.addEventListener('click', function (e) { self._onClick(e) })
    R.addEventListener('keydown', function (e) { self._onKey(e) })
    R.addEventListener('paste', function (e) { self._onPaste(e) })
    R.addEventListener('dragstart', function (e) { var li = e.target.closest('.fd-items li'); if (!li) return; self.drag = 'item:' + li.parentNode.dataset.items + ':' + li.dataset.i; e.dataTransfer.setData('text/plain', self.drag) })
    R.addEventListener('dragover', function (e) { var li = e.target.closest('.fd-items li'); if (li && self.drag && self.drag.indexOf('item:') === 0) { e.preventDefault(); $$('.fd-items li.is-over', R).forEach(function (n) { n.classList.remove('is-over') }); li.classList.add('is-over') } })
    R.addEventListener('drop', function (e) {
      var li = e.target.closest('.fd-items li'); if (!li || !self.drag || self.drag.indexOf('item:') !== 0) return
      e.preventDefault(); var p = self.drag.split(':'); self.drag = null
      var arr = self._itemArr(p[1]); if (!arr || li.parentNode.dataset.items !== p[1]) return
      var x = arr.splice(+p[2], 1)[0]; arr.splice(+li.dataset.i, 0, x); self.commit(); self.renderCenter(); self.renderRight()
    })
    this.root.addEventListener('keydown', function (e) {
      var mod = e.ctrlKey || e.metaKey, tag = (document.activeElement && document.activeElement.tagName) || ''
      if (mod && !/INPUT|TEXTAREA|SELECT/.test(tag)) {
        if (e.key.toLowerCase() === 'z' && !e.shiftKey) { e.preventDefault(); self.undo() }
        else if (e.key.toLowerCase() === 'y' || (e.key.toLowerCase() === 'z' && e.shiftKey)) { e.preventDefault(); self.redo() }
      } else if (e.key === 'Escape' && !e.defaultPrevented) { if (/INPUT|TEXTAREA|SELECT/.test(tag)) document.activeElement.blur(); else if (self.sel) self.select('') }
    })
  }
  proto._delSection = function (gi) {
    var self = this, view = M.groupsOf(this.def), g = view[gi]; if (!g || g.virtual || g.other) return
    var fields = g.keys.map(function (k) { return M.fieldByKey(self.def, k) }).filter(Boolean)
    var blocked = []; g.keys.forEach(function (k) { M.usedBy(self.def, k).filter(function (u) { return g.keys.indexOf(u.key) < 0 || u.where === 'output' }).forEach(function (u) { blocked.push(u.text) }) })
    if (blocked.length) return this.ask('先不要刪這個區塊', '<p>區塊裡的欄位還在被其他地方使用：</p><ul>' + blocked.map(function (t) { return '<li>' + esc(t) + '</li>' }).join('') + '</ul>')
    var go = function () {
      var before = JSON.stringify(self.def)
      M.removeSection(self.def, gi); if (!M.fieldByKey(self.def, self.sel)) self.sel = ''
      self.commit(); self.renderAll()
      self.toast('已刪除區塊「' + g.title + '」（含 ' + fields.length + ' 個欄位）', '復原', function () { self.def = JSON.parse(before); self.commit(); self.renderAll() })
    }
    var prot = fields.some(function (f) { return (self.caps.fixedTypeKeys && self.caps.fixedTypeKeys[f.key]) || (self.caps.publishedKeys || []).indexOf(f.key) >= 0 })
    if (prot || fields.length) this.ask('刪除區塊「' + g.title + '」？', '<p>區塊裡的 ' + fields.length + ' 個欄位會一起刪掉' + (prot ? '，其中有固定欄位或已發布版本裡的欄位' : '') + '。</p>', '確定刪除').then(function (ok) { if (ok) go() })
    else go()
  }
  proto._itemArr = function (id) {
    var f = this.cur(); if (!f) return null
    if (id === 'opt') return f.options = f.options || []
    var m = /^col(\d+)$/.exec(id); if (m) { var c = (f.columns || [])[+m[1]]; return c ? (c.options = c.options || []) : null }
    return null
  }
  proto._onInput = function (e) {
    var f = this.cur(); if (!f) return
    var t = e.target, k = t.dataset.fd
    if (k === 'label') { f.label = t.value; this.renderCenter(); this.commitSoon() }
    else if (k === 'help') { if (t.value) f.help = t.value; else delete f.help; this.renderCenter(); this.commitSoon() }
    else if (k === 'fillText') { f.default = t.value; this.renderCenter(); this.commitSoon() }
    else if (t.dataset.item) {
      var p = t.dataset.item.split(':'), arr = this._itemArr(p[0]); if (arr) { arr[+p[1]] = t.value; this.renderCenter(); this.commitSoon() }
    } else if (k === 'attr') this._setAttr(f, t)
    else if (k === 'minRows' || k === 'maxRows') { this._setNum(f, k, t.value) }
    else if (k === 'addLabel') { if (t.value) f.addLabel = t.value; else delete f.addLabel; this.renderCenter(); this.commitSoon() }
    else if (k === 'colMin') { var c = f.columns[+t.dataset.col]; if (t.value === '') delete c.min; else c.min = +t.value; this.commitSoon() }
    else if (k === 'cpPct' || k === 'cpCustom') { this._calcInput(f, t) }
  }
  proto._setNum = function (f, key, v) { if (v === '') delete f[key]; else { var n = Math.floor(+v); if (key === 'maxRows') n = Math.min(n, this.caps.maxRows || 200); f[key] = n }; this.commitSoon() }
  proto._setAttr = function (f, t) {
    var a = t.dataset.attr, v = t.value
    if (t.dataset.kind === 'exts') { var l = v.split(',').map(function (s) { return s.trim().replace(/^\./, '') }).filter(Boolean); if (l.length) f[a] = l; else delete f[a] }
    else if (t.dataset.kind === 'int' || t.dataset.kind === 'number') { if (v === '') delete f[a]; else f[a] = +v }
    else { if (v === '') delete f[a]; else f[a] = v }
    this.renderCenter(); this.commitSoon()
  }
  proto._calcOwner = function (f, t) { return t.dataset.col != null ? f.columns[+t.dataset.col] : f }
  proto._calcInput = function (f, t) {
    var o = this._calcOwner(f, t); this.applyCalc(o, f, t.dataset.fd, t.value); this.renderCenter(); this.commitSoon()
  }
  proto._onChange = function (e) {
    var f = this.cur(); if (!f) return
    var t = e.target, k = t.dataset.fd
    if (k === 'conv') {
      var T = t.value; f.type = T
      if (M.OPTION_TYPES[T]) f.options = f.options || ['選項一', '選項二']; else delete f.options
      this.commit(); this.renderAll()
    } else if (k === 'fill') {
      var v = t.value
      if (v === '') { delete f.default; delete f.locked }
      else if (v === '*option') f.default = (f.options || [])[0] || ''
      else if (v === '*custom') f.default = f.type === 'checkbox' ? true : ''
      else { f.default = { $: v }; if (M.canLock(f, this.registry()).ok === false) delete f.locked }
      this.commit(); this.renderCenter(); this.renderRight()
    } else if (k === 'fillOpt') { f.default = t.value; this.commit(); this.renderCenter() }
    else if (k === 'colType') { var c = f.columns[+t.dataset.col]; c.type = t.value; if (t.value === 'select') c.options = c.options || ['選項一', '選項二']; else if (t.value !== 'formula') delete c.formula; if (t.value !== 'select') { delete c.options } this.commit(); this.renderCenter(); this.renderRight() }
    else if (k && k.indexOf('cp') === 0 || k === 'calc') {
      var o = this._calcOwner(f, t)
      this.applyCalc(o, f, k, t.value, t.checked)
      this.commit(); this.renderCenter(); this.renderRight()
    }
  }
  proto._onClick = function (e) {
    var f = this.cur(), t = e.target, self = this
    var pr = t.closest('[data-prob]'); if (pr) { var p = this._probList[+pr.dataset.prob]; if (p && p.key) this.focus(p.key); return }
    if (!f) return
    var s = t.closest('.fd-sw')
    if (s && !s.disabled) {
      var on = s.getAttribute('aria-checked') !== 'true', id = s.dataset.sw
      if (id === 'required') { if (on) f.required = true; else delete f.required }
      else if (id === 'cashier') { if (on) f.editableBy = 'cashier'; else delete f.editableBy }
      else if (id === 'locked') { if (on) f.locked = true; else delete f.locked }
      else if (id === 'listed') M.setListed(this.def, f.key, on)
      else if (id.indexOf('attr:') === 0) { var a = id.slice(5); if (on) f[a] = true; else delete f[a] }
      else if (id.indexOf('colReq:') === 0) { var c = f.columns[+id.slice(7)]; if (on) c.required = true; else delete c.required }
      this.commit(); this.renderCenter(); this.renderRight()
      var again = $('[data-sw="' + id + '"]', this.els.right); if (again) again.focus()
      return
    }
    if (t.closest('[data-fd-act="delsel"]')) { this.removeFieldConfirm(f.key); return }
    var del = t.closest('[data-item-del]'); if (del) { var q = del.dataset.itemDel.split(':'), arr = this._itemArr(q[0]); if (arr) { arr.splice(+q[1], 1); this.commit(); this.renderCenter(); this.renderRight() } return }
    var add = t.closest('[data-item-add]'); if (add) { this._addItem(add.dataset.itemAdd, null, ''); return }
    var co = t.closest('[data-col-open]'); if (co) { var key = f.key + ':' + co.dataset.colOpen; this._colOpen = this._colOpen === key ? '' : key; this.renderRight(); return }
    var cp = t.closest('[data-col-preset]')
    if (cp) {
      var pr = (this.caps.columnPresets || [])[+cp.dataset.colPreset]
      if (pr) { pr.cols.forEach(function (c) { if (!f.columns.some(function (x) { return x.key === c.key })) f.columns.push(M.clone(c)) }); this.commit(); this.renderCenter(); this.renderRight() }
      return
    }
    var cu = t.closest('[data-col-up]'), cd = t.closest('[data-col-down]'), cx = t.closest('[data-col-del]'), ca = t.closest('[data-col-add]')
    if (cu || cd) { var i = +(cu || cd).dataset[cu ? 'colUp' : 'colDown'], j = i + (cu ? -1 : 1), cols = f.columns; var tmp = cols[i]; cols[i] = cols[j]; cols[j] = tmp; this._colOpen = ''; this.commit(); this.renderCenter(); this.renderRight(); return }
    if (cx && !cx.disabled) {
      var ci = +cx.dataset.colDel, col = f.columns[ci], uses = f.columns.filter(function (o, j) { return j !== ci && typeof o.formula === 'string' && new RegExp('(^|[^A-Za-z0-9_])' + col.key + '([^A-Za-z0-9_]|$)').test(o.formula) })
      if (uses.length) { this.ask('先不要刪這一欄', '<p>「' + esc(uses[0].label) + '」的計算還在用「' + esc(col.label) + '」，請先改掉。</p>'); return }
      f.columns.splice(ci, 1); this._colOpen = ''; this.commit(); this.renderCenter(); this.renderRight(); return
    }
    if (ca) {
      var nk = 'col_' + (f.columns.length + 1); while (f.columns.some(function (c2) { return c2.key === nk })) nk += '_'
      f.columns.push({ key: nk, label: '新欄位', type: 'text' }); this._colOpen = f.key + ':' + (f.columns.length - 1); this.commit(); this.renderCenter(); this.renderRight()
      var li = $('.fd-colbody', this.els.right); if (li) li.scrollIntoView({ block: 'nearest' })
    }
  }
  proto._addItem = function (id, at, text) {
    var arr = this._itemArr(id); if (!arr) return
    var idx = at == null ? arr.length : at
    arr.splice(idx, 0, text)
    this.commit(); this.renderCenter(); this.renderRight()
    var inp = $('[data-item="' + id + ':' + idx + '"]', this.els.right); if (inp) { inp.focus(); inp.select() }
  }
  proto._onKey = function (e) {
    var inp = e.target.closest('[data-item]'); if (!inp) return
    var p = inp.dataset.item.split(':'), arr = this._itemArr(p[0]), i = +p[1]; if (!arr) return
    if (e.key === 'Enter') { if (e.isComposing) return; e.preventDefault(); this._addItem(p[0], i + 1, '') }
    else if (e.key === 'Backspace' && inp.value === '' && arr.length > 1) { e.preventDefault(); arr.splice(i, 1); this.commit(); this.renderCenter(); this.renderRight(); var pv = $('[data-item="' + p[0] + ':' + Math.max(0, i - 1) + '"]', this.els.right); if (pv) pv.focus() }
    else if (e.key === 'ArrowDown') { var n = $('[data-item="' + p[0] + ':' + (i + 1) + '"]', this.els.right); if (n) { e.preventDefault(); n.focus() } }
    else if (e.key === 'ArrowUp') { var u = $('[data-item="' + p[0] + ':' + (i - 1) + '"]', this.els.right); if (u) { e.preventDefault(); u.focus() } }
  }
  proto._onPaste = function (e) {    // 貼上很多行 ⇒ 拆成很多格
    var inp = e.target.closest('[data-item]'); if (!inp) return
    var text = (e.clipboardData || window.clipboardData).getData('text'); if (!/\r?\n/.test(text)) return
    e.preventDefault()
    var lines = text.split(/\r?\n/).map(function (s) { return s.trim() }).filter(Boolean); if (!lines.length) return
    var p = inp.dataset.item.split(':'), arr = this._itemArr(p[0]), i = +p[1]; if (!arr) return
    if (arr[i] === '' || arr[i] === undefined) { arr.splice.apply(arr, [i, 1].concat(lines)) } else arr.splice.apply(arr, [i + 1, 0].concat(lines))
    this.commit(); this.renderCenter(); this.renderRight(); this.toast('已貼上，拆成 ' + lines.length + ' 個項目')
  }

  window.FormDesigner = { init: function (el, opts) { return new FD(el, opts) }, FRIENDLY: FRIENDLY, ATTR_COPY: ATTR_COPY, DEFAULT_ELEMENTS: DEFAULT_ELEMENTS }
})()
