/* motrix-format.js — 共用顯示格式器（T64 切片 B／D2）。金額、數字、日期、狀態名稱只在這裡決定怎麼印。
 *
 *   MotrixFormat.num(x)                 ⇒ 等同 x.toLocaleString()（不帶語系：跟著瀏覽器，與過去逐字相同）
 *   MotrixFormat.num(x, {locale:'en-US', maxFrac:4})   ⇒ x.toLocaleString('en-US', {maximumFractionDigits:4})
 *   MotrixFormat.money(x)               ⇒ 同 num（幣別字首 'NT$ ' 仍由呼叫端寫，避免改動既有版面）
 *   MotrixFormat.date(d)                ⇒ d.toLocaleDateString('zh-TW')
 *   MotrixFormat.dt(d, 'plain'|'full'|'short'|'sec') ⇒ d.toLocaleString('zh-TW'[, 四種既有選項之一])
 *   MotrixFormat.status(v)              ⇒ 預設原值；有 setStatusLabels(map) 才換顯示名（邏輯一律用原值）
 *
 * 設定（設定中心群組 ui_format：enabled／thousands／decimals／date_style 皆整數、0＝照目前；**全部預設＝今天的輸出**；讀不到／旗標關／值不認得 ⇒ 預設）。下面是格式器內部的字串寫法：
 *   thousands : 'default' | 'none'          千分位（none ⇒ 不加逗號）
 *   decimals  : 'default' | '0' | '2'       固定小數位（只套在 num／money，不改被格式化的數值本身；四捨五入仍是 MotrixLegalRound.halfUp 的事）
 *   dateStyle : 'default' | 'iso' | 'slash' 日期（default ⇒ zh-TW；iso ⇒ YYYY-MM-DD；slash ⇒ YYYY/MM/DD）
 * 設定在頁面載入時從 localStorage 快取同步取得，`init()` 再讀一次公開設定並更新快取（下次載入生效；本頁不重畫）。
 * 輸入值是 null／undefined ⇒ 回空字串（過去會丟 TypeError，畫面等同空白）；格式化途中出錯 ⇒ 回原值的字串（絕不空白）。永不丟例外。
 */
;(function () {
  var KEY = 'motrix_ui_format'
  var DEFAULTS = { thousands: 'default', decimals: 'default', dateStyle: 'default' }
  var ALLOWED = {
    thousands: ['default', 'none'],
    decimals: ['default', '0', '2'],
    dateStyle: ['default', 'iso', 'slash']
  }
  var DT = {
    plain: undefined,
    full: { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' },
    short: { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' },
    sec: { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }
  }
  var cfg = clean(load())
  var labels = {}

  function load() { try { return JSON.parse(localStorage.getItem(KEY) || '{}') || {} } catch (e) { return {} } }

  function clean(raw) {
    var out = {}
    Object.keys(DEFAULTS).forEach(function (k) {
      var v = raw && raw[k] != null ? String(raw[k]) : DEFAULTS[k]
      out[k] = ALLOWED[k].indexOf(v) >= 0 ? v : DEFAULTS[k]
    })
    return out
  }

  function isDefaultNum() { return cfg.thousands === 'default' && cfg.decimals === 'default' }
  function pad(n) { return (n < 10 ? '0' : '') + n }

  function num(x, opt) {
    if (x == null) return ''
    try {
      opt = opt || {}
      if (isDefaultNum() || typeof x !== 'number' && typeof x !== 'bigint') {
        return opt.locale || opt.maxFrac != null
          ? x.toLocaleString(opt.locale, opt.maxFrac != null ? { maximumFractionDigits: opt.maxFrac } : undefined)
          : x.toLocaleString()
      }
      var o = {}
      if (cfg.thousands === 'none') o.useGrouping = false
      if (cfg.decimals !== 'default') { o.minimumFractionDigits = +cfg.decimals; o.maximumFractionDigits = +cfg.decimals }
      else if (opt.maxFrac != null) o.maximumFractionDigits = opt.maxFrac
      return x.toLocaleString(opt.locale, o)
    } catch (e) { return String(x) }
  }

  function date(d) {
    if (d == null) return ''
    try {
      if (cfg.dateStyle === 'default' || !(d instanceof Date) || isNaN(d)) return d.toLocaleDateString('zh-TW')
      var sep = cfg.dateStyle === 'iso' ? '-' : '/'
      return d.getFullYear() + sep + pad(d.getMonth() + 1) + sep + pad(d.getDate())
    } catch (e) { return String(d) }
  }

  function dt(d, shape) {
    if (d == null) return ''
    try { return d.toLocaleString('zh-TW', shape === 'plain' ? undefined : (DT[shape] || DT.full)) } catch (e) { return String(d) }
  }

  function status(v) { return Object.prototype.hasOwnProperty.call(labels, v) ? labels[v] : v }

  async function init() {
    try {
      if (!window.MotrixPublicFlags) return
      var g = await window.MotrixPublicFlags.read(['ui_format'])
      var grp = (g || {}).ui_format
      if (!grp || grp.enabled !== 1) { localStorage.removeItem(KEY); return }
      var pick = function (v, names) { return names[v] != null ? names[v] : 'default' }   // 設定中心存整數：0＝照目前
      localStorage.setItem(KEY, JSON.stringify(clean({
        thousands: pick(grp.thousands, { 1: 'none' }),
        decimals: pick(grp.decimals, { 1: '0', 2: '2' }),
        dateStyle: pick(grp.date_style, { 1: 'iso', 2: 'slash' })
      })))
    } catch (e) { /* 讀不到 ⇒ 維持目前設定 */ }
  }

  try { window.addEventListener('load', function () { init() }) } catch (e) { /* 非瀏覽器環境（測試） */ }

  window.MotrixFormat = {
    num: num, money: num, date: date, dt: dt, status: status, init: init,
    setStatusLabels: function (m) { labels = m && typeof m === 'object' ? m : {} },
    _config: function () { return Object.assign({}, cfg) },
    _configure: function (raw) { cfg = clean(raw) }            // 測試用
  }
})()
