/* layout-runtime.js — P9 執行時套用版面（CUSTOMIZATION-SPEC §3.10）。
 *
 * 頁面在 Alpine 之前呼叫一次：
 *   MotrixLayout.init({ module: 'tender_radar', page: 'tender-radar.html',
 *                       fallback: { lists: { tenders: ['org', 'caseNo', …] } } })
 * 之後頁面的模板只讀 Alpine store `$store.layout`（見下方「頁面用」），不自己算版面。
 *
 * 來源（優先順序由後端決定：角色 ＞ 公司 ＞ 程式預設）：GET /api/layout/{module} ⇒ {points, ops, source, dropped}
 *   ⇒ MotrixCustomLayout.applyOps(points, page, ops) ⇒ 畫面狀態；個人層（清單偏好）只在一般模式疊上去。
 * 失敗 ⇒ `failed`＋fallback（頁面自己的預設欄位順序；守門 test_p9_layout 比對它與 module.json 登記相同），
 *   並在 <html data-layout-state="failed"> 標出來（不假裝套用成功）。
 *
 * 模式：live（一般）／edit（排版器編輯中，畫面＝草稿）／preview（以某角色預覽已發布版面）。
 *   編輯與預覽只換 `view`，不動 `base`（目前使用者自己的版面）；離開就回到 base。
 *
 * e2e 等待點：<html data-layout-state="ready|failed" data-layout-source="company v2|role:admin v1|default">。
 */
;(function () {
  var L = window.MotrixCustomLayout
  var cfg = null

  function session() { try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) { return {} } }
  function headers() { return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + (session().token || '') } }

  var raw = {
    ready: false, failed: false, error: '', module: '', page: '', source: '', role: '',
    points: [], ops: [], dropped: [],
    base: null,          // 目前使用者（角色）的版面狀態
    view: null,          // 畫面正在顯示的狀態（live＝base；edit＝草稿；preview＝某角色）
    mode: 'live', previewLabel: '',
    personal: {},        // listKey ⇒ 清單偏好（個人層）
    fallback: { lists: {} },

    // ── 頁面用 ───────────────────────────────────────────────
    /** 列表要顯示的欄：[{field, label, core}]（已套公司／角色＋個人層；失敗 ⇒ 頁面的 fallback）。 */
    cols: function (listKey) {
      var v = this.view
      if (!v || !v.lists[listKey]) return (this.fallback.lists[listKey] || []).map(function (f) { return { field: f, label: '' } })
      var cols = v.lists[listKey].columns
      if (this.mode === 'live') cols = L.applyPersonal(cols, this.personal[listKey])
      return cols.filter(function (c) { return c.visible })
    },
    /** 列表欄的標題：有改名 ⇒ 新名；沒改 ⇒ 頁面自己的寫法（dflt）。 */
    colLabel: function (listKey, field, dflt) {
      var c = this._col(listKey, field)
      return (c && c.relabeled) ? c.label : dflt
    },
    _col: function (listKey, field) {
      var v = this.view, d = this._defaults
      if (!v || !v.lists[listKey]) return null
      var c = v.lists[listKey].columns.filter(function (x) { return x.field === field })[0]
      var o = d && d.lists[listKey] && d.lists[listKey].columns.filter(function (x) { return x.field === field })[0]
      return c ? { label: c.label, relabeled: !!(o && o.label !== c.label) } : null
    },
    /** 表單區塊：[{key, label, order, relabeled, fields:[…]}]（只含顯示的欄位）。 */
    sections: function (formKey) {
      var v = this.view, d = this._defaults
      if (!v || !v.forms[formKey]) return []
      var dsec = {}
      if (d && d.forms[formKey]) d.forms[formKey].sections.forEach(function (s) { dsec[s.id] = s })
      return v.forms[formKey].sections.map(function (s, i) {
        return { key: s.key, label: s.label, order: i * 100, relabeled: !!(dsec[s.id] && dsec[s.id].label !== s.label),
                 fields: s.fields.filter(function (f) { return f.visible }) }
      })
    },
    _field: function (formKey, field) {
      var v = this.view
      if (!v || !v.forms[formKey]) return null
      var hit = null
      v.forms[formKey].sections.forEach(function (s, si) {
        s.fields.forEach(function (f, fi) { if (f.field === field) hit = { f: f, order: si * 100 + fi + 1 } })
      })
      return hit
    },
    fieldShown: function (formKey, field) { var h = this._field(formKey, field); return !h || h.f.visible },
    fieldOrder: function (formKey, field) { var h = this._field(formKey, field); return h ? h.order : 0 },
    fieldLabel: function (formKey, field, dflt) {
      var h = this._field(formKey, field), d = this._defaults
      if (!h || !d || !d.forms[formKey]) return dflt
      var o = null
      d.forms[formKey].sections.forEach(function (s) { s.fields.forEach(function (f) { if (f.id === h.f.id) o = f }) })
      return (o && o.label !== h.f.label) ? h.f.label : dflt
    },
    _item: function (kind, key) {
      var v = this.view
      if (!v) return null
      var arr = { action: v.actions, menu: v.menus, 'export': v.exports }[kind] || []
      for (var i = 0; i < arr.length; i++) if (arr[i].key === key) return { x: arr[i], i: i }
      return null
    },
    /** 按鈕／選單／匯出：顯示與否、順序（CSS order）、標籤（沒改名 ⇒ dflt，dflt 可以是頁面的動態文字）。 */
    shown: function (kind, key) { var h = this._item(kind, key); return !h || !h.x.hidden },
    order: function (kind, key) { var h = this._item(kind, key); return h ? h.i : 0 },
    label: function (kind, key, dflt) {
      var h = this._item(kind, key), d = this._defaults
      if (!h || !d) return dflt
      var arr = { action: d.actions, menu: d.menus, 'export': d.exports }[kind] || []
      var o = arr.filter(function (x) { return x.key === key })[0]
      return (o && o.label !== h.x.label) ? h.x.label : dflt
    },
    /** 頁內選單的項目順序：按鈕 key ⇒ CSS order。 */
    itemOrder: function (menuKey, actionKey) {
      var h = this._item('menu', menuKey)
      if (!h) return 0
      var i = h.x.items.map(function (id) { return id.slice(id.lastIndexOf('/action:') + 8) }).indexOf(actionKey)
      return i < 0 ? 99 : i
    },
    _defaults: null,
  }

  function S() { return (window.Alpine && window.Alpine.store && window.Alpine.store('layout')) || raw }

  function mark(state, source) {
    var h = document.documentElement
    h.setAttribute('data-layout-state', state)
    h.setAttribute('data-layout-source', source || '')
  }

  async function loadPersonal(listKeys) {
    var out = {}
    await Promise.all(listKeys.map(async function (k) {
      try {
        var r = await fetch('/api/list-prefs/' + encodeURIComponent(L.personalKey(cfg.module, k)), { headers: headers() })
        if (r.ok) out[k] = await r.json()
      } catch (e) { /* 個人層讀不到 ⇒ 只是沒有個人設定 */ }
    }))
    return out
  }

  /** 讀目前使用者的版面（或 role 參數：超級管理員預覽）。回 {points, ops, source, dropped} 或丟例外。 */
  async function fetchLayout(role) {
    var url = '/api/layout/' + encodeURIComponent(cfg.module) + (role ? ('?role=' + encodeURIComponent(role)) : '')
    var r = await fetch(url, { headers: headers() })
    if (!r.ok) throw new Error('HTTP ' + r.status)
    return r.json()
  }

  async function load() {
    var s = S()
    try {
      var d = await fetchLayout(null)
      var personal = await loadPersonal(Object.keys(L.pageModel(d.points, cfg.page).lists))
      s = S()
      s.points = d.points
      s.ops = d.ops
      s.dropped = d.dropped || []
      s.source = d.source
      s.role = d.role
      s.error = d.error || ''
      s._defaults = L.pageModel(d.points, cfg.page)
      s.base = L.applyOps(d.points, cfg.page, d.ops).state
      s.personal = personal
      if (s.mode === 'live') s.view = s.base
      s.ready = true
      s.failed = false
      mark('ready', d.source)
    } catch (e) {
      s = S()
      s.failed = true
      s.error = '版面設定載入失敗（' + (e && e.message || e) + '），顯示程式預設'
      mark('failed', '')
    }
  }

  // ── 個人層面板：頁面放 <div data-layout-personal="<listKey>"></div>，在 Alpine 起來之前換成下面的面板 ──
  var PERSONAL_CSS = [
    '[x-cloak]{display:none!important}.ml-personal{position:relative;display:inline-block}',
    '.ml-pop{position:absolute;right:0;top:calc(100% + 4px);z-index:60;background:var(--bg-card,#fff);border:1px solid var(--border-light,#ddd);',
    'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.12);padding:10px 12px;width:260px;max-width:calc(100vw - 32px);font-size:12px}',
    '.ml-pop__t{font-weight:600;margin-bottom:6px}.ml-pop__hint{color:var(--text-dim,#888);font-size:11px;margin-bottom:6px}',
    '.ml-pop__row{display:flex;align-items:center;gap:6px;padding:3px 0}.ml-pop__row label{flex:1;display:flex;gap:6px;align-items:center}',
    '.ml-pop__row button{border:1px solid var(--border-light,#ddd);background:none;border-radius:4px;cursor:pointer;padding:0 6px}',
    '.ml-core{font-size:10px;color:var(--text-dim,#888)}.ml-pop__foot{display:flex;gap:6px;margin-top:8px;align-items:center;flex-wrap:wrap}',
    '.ml-layout-note{font-size:11px;color:var(--warning,#b45309);margin:4px 0}',
  ].join('')

  function personalHtml(listKey) {
    var k = JSON.stringify(listKey).replace(/"/g, '&quot;')
    return '<div class="ml-personal" x-data="MotrixLayout.personalPanel(' + k + ')" data-testid="ml-personal-' + listKey + '"'
      + ' :data-busy="busy ? \'1\' : \'0\'">'
      + '<button type="button" class="btn btn-ghost btn-sm" data-testid="ml-personal-open" @click="toggle()"'
      + ' x-show="$store.layout.ready && $store.layout.mode === \'live\'">欄位</button>'
      + '<div class="ml-pop" x-show="open" @click.outside="open = false" x-cloak>'
      + '<div class="ml-pop__t">我的欄位</div><div class="ml-pop__hint">只影響自己的畫面；核心欄位不能隱藏。管理者隱藏的欄位不會出現在這裡。</div>'
      + '<template x-for="(c, i) in cols" :key="c.field"><div class="ml-pop__row" :data-field="c.field">'
      + '<label><input type="checkbox" :checked="c.visible" :disabled="c.core" @change="c.visible = $event.target.checked"> <span x-text="c.label"></span></label>'
      + '<span class="ml-core" x-show="c.core">核心</span>'
      + '<button type="button" title="上移" @click="up(i)">↑</button><button type="button" title="下移" @click="down(i)">↓</button></div></template>'
      + '<div class="ml-pop__foot"><button type="button" class="btn btn-primary btn-sm" data-testid="ml-personal-save" @click="save()" :disabled="busy">儲存</button>'
      + '<button type="button" class="btn btn-ghost btn-sm" data-testid="ml-personal-reset" @click="reset()" :disabled="busy">恢復預設</button>'
      + '<span x-text="msg"></span></div></div></div>'
  }

  function personalPanel(listKey) {
    return {
      open: false, busy: false, msg: '', cols: [],
      toggle: function () { this.open = !this.open; if (this.open) { this.cols = window.MotrixLayout.personalColumns(listKey); this.msg = '' } },
      up: function (i) { this.cols = L.move(this.cols, i, -1) },
      down: function (i) { this.cols = L.move(this.cols, i, 1) },
      save: async function () {
        this.busy = true
        try { await window.MotrixLayout.savePersonal(listKey, this.cols); this.msg = '已儲存'; this.open = false }
        catch (e) { this.msg = '儲存失敗（' + e.message + '）' }
        this.busy = false
      },
      reset: async function () {
        this.busy = true
        try { await window.MotrixLayout.savePersonal(listKey, null); this.cols = window.MotrixLayout.personalColumns(listKey); this.msg = '已恢復預設' }
        catch (e) { this.msg = '恢復失敗（' + e.message + '）' }
        this.busy = false
      },
    }
  }

  function mountPersonal() {
    if (!document.getElementById('ml-personal-css')) {
      var st = document.createElement('style')
      st.id = 'ml-personal-css'
      st.textContent = PERSONAL_CSS
      document.head.appendChild(st)
    }
    document.querySelectorAll('[data-layout-personal]').forEach(function (el) {
      el.innerHTML = personalHtml(el.getAttribute('data-layout-personal'))
    })
  }

  window.MotrixLayout = {
    init: function (c) {
      cfg = c
      raw.module = c.module
      raw.page = c.page
      raw.fallback = c.fallback || { lists: {} }
      document.addEventListener('alpine:init', function () {
        window.Alpine.store('layout', raw)
        mountPersonal()
      })
      load()
    },
    personalPanel: personalPanel,
    config: function () { return cfg },
    headers: headers,
    session: session,
    fetchLayout: fetchLayout,
    /** 重新讀目前使用者的版面（發布、還原之後）。 */
    reload: load,
    /** 排版器：畫面換成草稿狀態（edit）或某角色的已發布狀態（preview）；null ⇒ 回到自己的版面。 */
    show: function (state, mode, label) {
      var s = S()
      if (!state) { s.mode = 'live'; s.previewLabel = ''; s.view = s.base; return }
      s.mode = mode || 'edit'
      s.previewLabel = label || ''
      s.view = state
    },
    /** 個人層存檔（清單偏好）；存完重新套。 */
    savePersonal: async function (listKey, columns) {
      var body = columns === null ? { sortMode: '', sortDir: 'desc', customOrder: [] } : L.personalPref(columns)
      var r = await fetch('/api/list-prefs/' + encodeURIComponent(L.personalKey(cfg.module, listKey)),
                          { method: 'PUT', headers: headers(), body: JSON.stringify(body) })
      if (!r.ok) throw new Error('HTTP ' + r.status)
      var s = S()
      var p = Object.assign({}, s.personal)
      p[listKey] = body
      s.personal = p
    },
    /** 個人設定面板用：上層（公司／角色）顯示的欄＋個人偏好，含被自己隱藏的欄。 */
    personalColumns: function (listKey) {
      var s = S()
      if (!s.base || !s.base.lists[listKey]) return []
      return L.applyPersonal(s.base.lists[listKey].columns, s.personal[listKey])
    },
  }
})()
