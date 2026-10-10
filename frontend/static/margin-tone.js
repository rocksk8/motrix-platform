// 直接毛利率顏色門檻的唯一來源（第 55 班；原本報價單表單 30/40、報價單列表 30/35 各寫一份）。
// 用法（Alpine）：:class="'' + MotrixMargin.tone(tot.directMarginPct)" ／ :style="MotrixMargin.style(q.direct_margin_pct)"
// 門檻採較嚴的 40：直接毛利率 40% 也是管銷 25% 新口徑的打平點（OVERHEAD-25PCT-OPERATING-PROFIT-DESIGN-T48），低於 40% 就該提醒。
// 日後要讓管理者調整時，改成讀設定中心即可（讀取點只有這一處）。
(function () {
  var DANGER_BELOW = 30
  var WARN_BELOW = 40

  // pct：百分比數字（例 35.5）；回 'danger'｜'warning'｜'success'
  function tone(pct) {
    // 沿用舊行內算式的比較語意（null／空字串／0 ⇒ danger；undefined／非數字 ⇒ success），不另做轉換，避免換來源時悄悄改變行為
    return pct < DANGER_BELOW ? 'danger' : pct < WARN_BELOW ? 'warning' : 'success'
  }

  // 列表用的行內樣式（顏色變數同表單的語意色）
  function style(pct) {
    return 'color:var(--' + tone(pct) + ');font-weight:600'
  }

  var api = { DANGER_BELOW: DANGER_BELOW, WARN_BELOW: WARN_BELOW, tone: tone, style: style }
  if (typeof window !== 'undefined') window.MotrixMargin = api
  if (typeof module !== 'undefined' && module.exports) module.exports = api
})()
