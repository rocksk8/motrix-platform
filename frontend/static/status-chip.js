// 單據狀態 → 晶片顏色類別的唯一對照（第 51 班），並（S-X2）接上『狀態顯示名稱與顏色』表。CSS 在 css/style.css 的 `.st-chip`／`.st-chip--*`（全用語意 token）。
// 用法（Alpine）：<span :class="MotrixStatus.chipClass(e.status)" x-text="MotrixStatus.label(e.status)"></span>
// 未知狀態 ⇒ 只回基底 `st-chip`（中性），不會誤上色；要新增狀態只改這張表（並補 backend/tests/test_status_chip_t51.py 的詞彙）。
//
// S-X2：旗標 builder_status_display.enabled 關（預設）或表還沒載入 ⇒ chipClass 用 MAP、label 照頁面的 fallback／原值——唯一例外是 DEFAULTS 內建改名（待審核→待簽核，UX P1）。
// 旗標開且管理者改過某個狀態的字或色 ⇒ 只有『被改過的欄位』覆寫畫面原本的做法（server 回的 changed 清單），沒改的欄位維持畫面自己的字與色。
// 邏輯（x-show／篩選／權限）永遠用原始狀態值，不要用 label() 的結果判斷。
(function () {
  var MAP = {
    '草稿': 'draft',
    '待審核': 'pending', '待核准': 'pending',
    '簽核中': 'signing',
    '已核准': 'approved',
    '已駁回': 'rejected', '已退回': 'rejected', '已拒絕': 'rejected',
    '已付款': 'paid', '已匯款': 'paid',
    '已作廢': 'void', '已取消': 'void', '已撤回': 'void', '已撤銷': 'void'
  }
  // badge--* 家族（寫死 hex 的舊色表）對應：色調 → class；neutral/沒有對應 ⇒ 空字串（呼叫端自己的 class 不被覆寫）
  var BADGE = { draft: 'badge--draft', pending: 'badge--pending', signing: 'badge--signing', approved: 'badge--approved', rejected: 'badge--rejected', paid: 'badge--done', 'void': 'badge--lost' }

  // 內建預設顯示名（旗標關閉、或表還沒載入時也生效）。2026-11-13 使用者裁示：『待審核』畫面一律顯示『待簽核』（資料鍵不變）。
  // 必須與 backend/helpers/status_display.py 的 _LABEL0／_NAMES0 一致——由 backend/tests/test_status_display_default_parity_2026_11_13.py 守住。
  // 只列『有改名』的鍵；其他鍵仍照頁面自己的 fallback（今天的做法）。管理者在名稱表改過的字仍優先於這裡。
  var DEFAULTS = {
    '待審核': { label: '待簽核', names: { quote_list: '待簽核', voucher: '待審核' } },     // 會計傳票維持「審核」（PM 裁示 2026-11-13）
    '差額待審核': { label: '差額待簽核', names: {} }
  }

  var state = { table: null, changed: {}, ver: 0, loading: null }

  // 反應式持有者：Alpine 存在時就建立（腳本載入時、alpine:init、以及第一次被讀取時——讀取發生在 Alpine 的 effect 裡，所以第一次繪製就會登記相依，
  // 載入完成後同一個位置會重畫）。沒有 Alpine（node 測試、舊頁面）就退回普通計數。
  function ensureReactive() {
    try { if (!state._r && typeof window !== 'undefined' && window.Alpine && window.Alpine.reactive) state._r = window.Alpine.reactive({ v: state.ver }) } catch (e) { /* 維持普通計數 */ }
  }
  function bump() {
    state.ver++
    ensureReactive()
    if (state._r) state._r.v = state.ver
  }
  function dep() { ensureReactive(); return state._r ? state._r.v : state.ver }    // 讀取就登記相依
  ensureReactive()
  if (typeof document !== 'undefined' && document.addEventListener) document.addEventListener('alpine:init', ensureReactive)

  function key(status) { return String(status == null ? '' : status).trim() }

  function tone(status) {
    var k = key(status)
    return Object.prototype.hasOwnProperty.call(MAP, k) ? MAP[k] : ''
  }

  function own(o, k) { return !!o && typeof o === 'object' && Object.prototype.hasOwnProperty.call(o, k) }
  function changedFields(k) { dep(); return own(state.changed, k) && Array.isArray(state.changed[k]) ? state.changed[k] : [] }
  function entry(k) { dep(); return own(state.table, k) ? state.table[k] : null }

  // 覆寫後的色調（沒有被改過 ⇒ null，呼叫端用自己原本的）
  function overrideTone(status) {
    var k = key(status), e = entry(k)
    if (!e || changedFields(k).indexOf('tone') < 0) return null
    return e.tone === 'neutral' ? '' : e.tone
  }

  function chipClass(status) {
    var o = overrideTone(status)
    var t = o === null ? tone(status) : o
    return t ? 'st-chip st-chip--' + t : 'st-chip'
  }

  // 給用 badge--* 的頁面：被管理者改過色調才回新 class；否則回 fallbackClass（頁面原本的 class）
  function badgeClass(status, fallbackClass) {
    var o = overrideTone(status)
    if (o === null) return fallbackClass == null ? '' : fallbackClass
    return o ? (BADGE[o] || fallbackClass || '') : (fallbackClass || '')
  }

  // 顯示名稱。ctx＝情境（quote_list／quote_form／case／cashier／report／settlement）；fallback＝畫面原本會印的字（省略 ⇒ 原值）
  function label(status, ctx, fallback) {
    var k = key(status), base = fallback == null ? (status == null ? '' : String(status)) : fallback
    if (own(DEFAULTS, k)) {      // 內建預設改名優先於頁面舊的 fallback（頁面的 fallback 可能還是舊字）
      var d = DEFAULTS[k]
      base = ctx && d.names && d.names[ctx] ? d.names[ctx] : d.label
    }
    var e = entry(k)
    if (!e) return base
    var ch = changedFields(k)
    if (ctx && ch.indexOf('names.' + ctx) >= 0 && e.names && e.names[ctx]) return e.names[ctx]
    if (ch.indexOf('label') >= 0 && !(ctx && e.names && e.names[ctx])) return e.label
    return base
  }

  // 載入表（一頁一次；旗標關 ⇒ {enabled:false}，什麼都不改）。失敗一律靜默維持預設。
  function load(opts) {
    if (state.loading) return state.loading
    opts = opts || {}
    var token = opts.token
    try { token = token || JSON.parse(localStorage.getItem('motrix_session') || '{}').token } catch (e) { /* 無痕視窗等 */ }
    if (!token || typeof fetch !== 'function') return Promise.resolve(false)
    state.loading = fetch('/api/status-display', { headers: { Authorization: 'Bearer ' + token } })
      .then(function (r) { return r.ok ? r.json() : null })
      .then(function (d) { return apply(d) })
      .catch(function () { return false })
    return state.loading
  }

  function apply(d) {
    if (!d || d.enabled !== true || !d.statuses || typeof d.statuses !== 'object') return false
    state.table = d.statuses
    state.changed = d.changed && typeof d.changed === 'object' ? d.changed : {}
    bump()
    return true
  }

  function reset() { state.table = null; state.changed = {}; state.loading = null; bump() }

  // 頁面一行啟用：讀公開旗標 builder_status_display，開了才載入表（關 ⇒ 什麼都不改；讀不到 ⇒ 維持預設）。每頁只會做一次。
  var initOnce = null
  function init(opts) {
    if (initOnce) return initOnce
    opts = opts || {}
    initOnce = (async function () {
      try {
        if (typeof window === 'undefined' || !window.MotrixPublicFlags) return false
        var g = opts.flags || await window.MotrixPublicFlags.read(['builder_status_display'], opts.token ? { token: opts.token } : undefined)      // opts.flags：頁面已用同一次請求讀好時直接用（出納頁）
        if (!g || !g.builder_status_display || g.builder_status_display.enabled !== 1) return false
        return await load(opts)
      } catch (e) { return false }
    })()
    return initOnce
  }

  var api = { chipClass: chipClass, badgeClass: badgeClass, label: label, tone: tone, load: load, init: init, apply: apply, reset: reset, MAP: MAP, BADGE: BADGE, DEFAULTS: DEFAULTS }
  if (typeof window !== 'undefined') window.MotrixStatus = api
  if (typeof module !== 'undefined' && module.exports) module.exports = api
})()
