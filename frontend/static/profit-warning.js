/* T64 A：利潤顏色門檻（設定中心 profit_warning.*）。預設＝各畫面原本寫死的數字；讀不到／不合法 ⇒ 整組用預設。純顯示，不擋任何動作。
   用法：頁面資料物件放 `pw: MotrixProfitWarning.defaults()`，init 時 `MotrixProfitWarning.load().then(b => { this.pw = b })`。 */
(function () {
  const DEF = { quote_form_low: 12, quote_form_good: 20, report_low: 10, report_good: 20, case_floor: 0, case_good: 20, settlement_good: 20 }
  const PAIRS = [['quote_form_low', 'quote_form_good'], ['report_low', 'report_good'], ['case_floor', 'case_good']]
  function normalise(d) {
    const out = {}
    for (const k of Object.keys(DEF)) {
      const v = d && d[k]
      if (typeof v !== 'number' || !Number.isFinite(v) || v < -100 || v > 100) return Object.assign({}, DEF)
      out[k] = v
    }
    for (const [lo, hi] of PAIRS) if (out[lo] > out[hi]) return Object.assign({}, DEF)
    return out
  }
  let _p = null
  async function _fetch() {
    try {
      const s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      if (!s.token) return Object.assign({}, DEF)
      const r = await fetch('/api/profit-warning/config', { headers: { Authorization: 'Bearer ' + s.token } })
      if (!r.ok) return Object.assign({}, DEF)
      return normalise(await r.json())
    } catch (e) { return Object.assign({}, DEF) }
  }
  function load() { return _p || (_p = _fetch().then(b => Object.assign({}, b))) }      // 同一頁面只打一次 API（頁面 init 可能跑兩次）；每次回傳獨立副本
  window.MotrixProfitWarning = { defaults: () => Object.assign({}, DEF), normalise, load }
})()
