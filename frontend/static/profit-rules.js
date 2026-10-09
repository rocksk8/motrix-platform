// 報價單／精算的利潤規則（第 48 班 S1）。後端唯一來源：backend/helpers/profit_rules.py，這裡是同一套算法的前端版本。
// 等值測試：backend/tests/test_profit_rules_t48.py（同一份黃金向量 tests/data/profit_rules_vectors.json，node 載入本檔比對）。
// 需先載入 static/legal-round.js（MotrixLegalRound.halfUp）。
// 口徑：ver 1＝管銷 稅前×10%（舊）；ver 2＝管銷 max(直接毛利,0)×pct%（預設 25）。S1 的 ACTIVE_VER 仍是 1（零行為變更）。
(function () {
  var LEGACY_VER = 1, FORMULA_VER = 2
  var ACTIVE_VER = LEGACY_VER            // S2 改成 FORMULA_VER（唯一的切換點）
  var CHARITY_DIRECT = 'direct', CHARITY_TOTAL = 'total'     // 第 52 班：公益捐款基數（direct＝直接毛利×1%、不為負；total＝報價含稅金額×1%、下限只設在含稅金額（負 ⇒ 0）、不看直接毛利，只在 ver 2 生效）
  var ACTIVE_CHARITY_BASIS = CHARITY_DIRECT
  var LEGACY_ADMIN_RATE = 0.10, DEFAULT_OVERHEAD_PCT = 25, CHARITY_RATE = 0.01, TARGET_MARGIN_PCT = 12

  function halfUp(a, r) { return MotrixLegalRound.halfUp(a, r) }

  // 百分比 → 費率字串（小數點左移兩位，不經浮點：7.1 → '0.071'）
  function pctRate(pct) {
    var m = /^(\d+)(?:\.(\d+))?$/.exec(String(pct).trim())
    if (!m) throw new Error('百分比格式不正確：' + pct)
    var frac = m[2] || '', digits = m[1] + frac, dec = frac.length + 2
    while (digits.length <= dec) digits = '0' + digits
    return digits.slice(0, digits.length - dec) + '.' + digits.slice(digits.length - dec)
  }

  function adminCost(pretax, directProfit, pct, ver) {
    ver = ver == null ? ACTIVE_VER : ver
    if (ver === LEGACY_VER) return halfUp(pretax, LEGACY_ADMIN_RATE)
    var p = pct == null ? DEFAULT_OVERHEAD_PCT : pct
    return halfUp(Math.max(directProfit, 0), pctRate(p))
  }

  // 實際採用的基數：只有 ver 2 才可能是 total
  function basisOf(ver, basis) {
    ver = ver == null ? ACTIVE_VER : ver
    var b = basis == null ? ACTIVE_CHARITY_BASIS : basis
    if (b !== CHARITY_DIRECT && b !== CHARITY_TOTAL) throw new Error('公益捐款基數只能是 direct 或 total：' + basis)
    return (b === CHARITY_TOTAL && ver !== LEGACY_VER) ? CHARITY_TOTAL : CHARITY_DIRECT
  }

  function charity(directProfit, total, basis) {
    if (basis === CHARITY_TOTAL) {
      if (total == null) throw new Error('公益捐款基數 total 需要報價含稅金額')
      return Math.max(0, halfUp(total, CHARITY_RATE))
    }
    return Math.max(0, halfUp(directProfit, CHARITY_RATE))
  }

  // 報價單損益；indirectItems＝[運輸物流, 安裝施工, 差異項, 保固預估, 其他費用]；回傳未進位的原始值
  function quote(pretax, totalCost, inputVat, indirectItems, pct, ver, total, charityBasis) {
    var direct = pretax - totalCost - inputVat
    var directPct = pretax > 0 ? direct / pretax * 100 : 0
    var admin = adminCost(pretax, direct, pct, ver)
    var ch = charity(direct, total, basisOf(ver, charityBasis))
    var totalIndirect = admin + ch
    var useIndirect = (ver == null ? ACTIVE_VER : ver) === LEGACY_VER       // 新口徑（ver 2）不再計入五項間接成本；舊口徑照舊
    ;(useIndirect ? (indirectItems || []) : []).forEach(function (x) { totalIndirect = totalIndirect + (x || 0) })
    var net = direct - totalIndirect
    var netPct = pretax > 0 ? net / pretax * 100 : 0
    return { directProfit: direct, directMarginPct: directPct, adminCost: admin, charityDonation: ch,
             totalIndirect: totalIndirect, netProfit: net, netMarginPct: netPct }
  }

  // 精算損益（實際側）；frozenCharity＝已完結精算的存檔公益金（null/undefined ⇒ 重算）
  function settlement(pretax, actualCost, pct, ver, frozenCharity, quotedTotal, charityBasis) {
    var gross = pretax - actualCost
    var grossPct = pretax > 0 ? gross / pretax * 100 : 0
    var admin = adminCost(pretax, gross, pct, ver)
    var ch = frozenCharity != null ? frozenCharity : charity(gross, quotedTotal, basisOf(ver, charityBasis))
    var net = gross - admin - ch
    var netPct = pretax > 0 ? net / pretax * 100 : 0
    return { grossProfit: gross, grossMarginPct: grossPct, adminCost: admin, charityDonation: ch,
             netProfit: net, netMarginPct: netPct }
  }

  var api = { LEGACY_VER: LEGACY_VER, FORMULA_VER: FORMULA_VER, ACTIVE_VER: ACTIVE_VER, DEFAULT_OVERHEAD_PCT: DEFAULT_OVERHEAD_PCT,
              TARGET_MARGIN_PCT: TARGET_MARGIN_PCT, CHARITY_DIRECT: CHARITY_DIRECT, CHARITY_TOTAL: CHARITY_TOTAL, ACTIVE_CHARITY_BASIS: ACTIVE_CHARITY_BASIS, basisOf: basisOf, pctRate: pctRate, adminCost: adminCost, charity: charity, quote: quote, settlement: settlement }
  if (typeof window !== 'undefined') window.MotrixProfitRules = api
  if (typeof module !== 'undefined' && module.exports) module.exports = api
})()
