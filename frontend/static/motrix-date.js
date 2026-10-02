/* motrix-date.js — 本地日期的共用小工具（2026-10-01）
 *
 * 🔴 為什麼有這支：`new Date().toISOString().slice(0, 10)` 取的是 **UTC** 日期。台灣 UTC+8，
 *    每天 00:00–08:00 之間它會得到「前一天」——報價單 MQ-202610-002 在 10/01 01:03 建立、報價日期卻是 2026-09-30
 *    （使用者回報）。同一個寫法散在 30 幾個檔案當「今天」用。
 *    ⇒ 「今天／日期預設值／min／max／檔名日期／日期比較」一律走這裡，**用瀏覽器本地時區**（與使用者牆上的日期一致）。
 *
 * ⚠️ 只用於「日曆日期」。真正的時間戳（`at: new Date().toISOString()`、要送後端存的 ISO 時間）不要用它，照舊用 toISOString()。
 * ⚠️ 也不要用 `new Date('2026-10-01')` 來做日期運算：純日期字串會被當 UTC 午夜解析；用 `MotrixDate.parse()`（本地午夜）。
 * 守門：tests/test_frontend_local_date_2026_10_01.py（前端不准再有 toISOString().slice(0…) 的日期寫法，除非列進白名單並寫理由）。
 *
 *   MotrixDate.today()            'YYYY-MM-DD'（本地今天）
 *   MotrixDate.thisMonth()        'YYYY-MM'
 *   MotrixDate.nowIso()           'YYYY-MM-DDTHH:MM:SS'（本地、無時區；後端取前 10 碼當日期的時間戳用）
 *   MotrixDate.monthStart([d])    'YYYY-MM-01'（d 預設今天）
 *   MotrixDate.ymd(d)             Date（或毫秒數／'YYYY-MM-DD'）→ 'YYYY-MM-DD'（本地）
 *   MotrixDate.ym(d)              → 'YYYY-MM'
 *   MotrixDate.stamp([d])         → 'YYYYMMDD'（檔名用）
 *   MotrixDate.parse('YYYY-MM-DD')→ Date（本地午夜）；壞格式 ⇒ Invalid Date
 *   MotrixDate.addDays(x, n)      x＝'YYYY-MM-DD' 或 Date → 'YYYY-MM-DD'（本地日曆加減，跨月／跨年正確）
 */
(function (root) {
  'use strict'
  function pad(n) { return (n < 10 ? '0' : '') + n }
  function asDate(x) {
    if (x === undefined || x === null || x === '') return new Date()
    if (x instanceof Date) return x
    if (typeof x === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(x)) return MotrixDate.parse(x)
    return new Date(x)
  }
  var MotrixDate = {
    ymd: function (d) {
      d = asDate(d)
      return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
    },
    ym: function (d) {
      d = asDate(d)
      return d.getFullYear() + '-' + pad(d.getMonth() + 1)
    },
    today: function () { return MotrixDate.ymd(new Date()) },
    // 本地「現在」的 ISO 字串（無時區：YYYY-MM-DDTHH:MM:SS）——與後端 datetime.now().isoformat(timespec='seconds') 同格式。
    // 要送後端存、而後端會取前 10 碼當日期的時間（例：簽核 requestedAt）用這個，不要用 toISOString()（UTC、帶 Z）。
    nowIso: function () {
      var d = new Date()
      return MotrixDate.ymd(d) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds())
    },
    thisMonth: function () { return MotrixDate.ym(new Date()) },
    monthStart: function (d) { return MotrixDate.ym(asDate(d)) + '-01' },
    stamp: function (d) { return MotrixDate.ymd(d).replace(/-/g, '') },
    parse: function (s) {
      var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || ''))
      if (!m) return new Date(NaN)
      return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
    },
    addDays: function (x, n) {
      var d = new Date(asDate(x).getTime())
      d.setDate(d.getDate() + Number(n || 0))
      return MotrixDate.ymd(d)
    },
  }
  root.MotrixDate = MotrixDate
})(typeof window !== 'undefined' ? window : this)
