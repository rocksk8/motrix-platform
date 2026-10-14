// 單據狀態 → 晶片顏色類別的唯一對照（第 51 班），並（S-X2）接上『狀態顯示名稱與顏色』表。CSS 在 css/style.css 的 `.st-chip`／`.st-chip--*`（全用語意 token）。
// 用法（Alpine）：<span :class="MotrixStatus.chipClass(e.status)" x-text="MotrixStatus.label(e.status)"></span>
// 未知狀態 ⇒ 只回基底 `st-chip`（中性），不會誤上色；要新增狀態只改這張表（並補 backend/tests/test_status_chip_t51.py 的詞彙）。
//
// S-X2：旗標 builder_status_display.enabled 關（預設）或表還沒載入 ⇒ 下面所有函式回傳與過去完全相同的值（label 原值照印、chipClass 用 MAP）。
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

  var state = { table: null, changed: {}, ver: 0, loading: null }

  function bump() {
    state.ver++
    try { if (typeof window !== 'undefined' && window.Alpine && window.Alpine.reactive && !state._r) { state._r = window.Alpine.reactive({ v: 0 }) } } catch (e) { /* 沒有 Alpine 就不做反應式 */ }
    if (state._r) state._r.v = state.ver
  }
  function dep() { return state._r ? state._r.v : state.ver }    // 讀取就登記相依：載入完成後用到的地方會重畫

  function key(status) { return String(status == null ? '' : status).trim() }

  function tone(status) {
    var k = key(status)
    return Object.prototype.hasOwnProperty.call(MAP, k) ? MAP[k] : ''
  }

  function changedFields(k) { dep(); return (state.changed && state.changed[k]) || [] }
  function entry(k) { return state.table && state.table[k] ? state.table[k] : null }

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

  var api = { chipClass: chipClass, badgeClass: badgeClass, label: label, tone: tone, load: load, apply: apply, reset: reset, MAP: MAP, BADGE: BADGE }
  if (typeof window !== 'undefined') window.MotrixStatus = api
  if (typeof module !== 'undefined' && module.exports) module.exports = api
})()
