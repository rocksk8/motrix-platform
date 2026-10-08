// 報價單／精算的利潤規則（第 48 班 S1）。後端唯一來源：backend/helpers/profit_rules.py，這裡是同一套算法的前端版本。
// 等值測試：backend/tests/test_profit_rules_t48.py（同一份黃金向量 tests/data/profit_rules_vectors.json，node 載入本檔比對）。
// 需先載入 static/legal-round.js（MotrixLegalRound.halfUp）。
// 口徑：ver 1＝管銷 稅前×10%（舊）；ver 2＝管銷 max(直接毛利,0)×pct%（預設 25）。S1 的 ACTIVE_VER 仍是 1（零行為變更）。
(function () {
  var LEGACY_VER = 1, FORMULA_VER = 2
  var ACTIVE_VER = LEGACY_VER            // S2 改成 FORMULA_VER（唯一的切換點）
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

  function charity(directProfit) { return Math.max(0, halfUp(directProfit, CHARITY_RATE)) }

  // 報價單損益；indirectItems＝[運輸物流, 安裝施工, 差異項, 保固預估, 其他費用]；回傳未進位的原始值
  function quote(pretax, totalCost, inputVat, indirectItems, pct, ver) {
    var direct = pretax - totalCost - inputVat
    var directPct = pretax > 0 ? direct / pretax * 100 : 0
    var admin = adminCost(pretax, direct, pct, ver)
    var ch = charity(direct)
    var totalIndirect = admin + ch
    ;(indirectItems || []).forEach(function (x) { totalIndirect = totalIndirect + (x || 0) })
    var net = direct - totalIndirect
    var netPct = pretax > 0 ? net / pretax * 100 : 0
    return { directProfit: direct, directMarginPct: directPct, adminCost: admin, charityDonation: ch,
             totalIndirect: totalIndirect, netProfit: net, netMarginPct: netPct }
  }

  // 精算損益（實際側）；frozenCharity＝已完結精算的存檔公益金（null/undefined ⇒ 重算）
  function settlement(pretax, actualCost, pct, ver, frozenCharity) {
    var gross = pretax - actualCost
    var grossPct = pretax > 0 ? gross / pretax * 100 : 0
    var admin = adminCost(pretax, gross, pct, ver)
    var ch = frozenCharity != null ? frozenCharity : charity(gross)
    var net = gross - admin - ch
    var netPct = pretax > 0 ? net / pretax * 100 : 0
    return { grossProfit: gross, grossMarginPct: grossPct, adminCost: admin, charityDonation: ch,
             netProfit: net, netMarginPct: netPct }
  }

  // 報表／PDF／畫面上管銷分攤那一列的標籤：舊口徑『管銷分攤（10%）』；新口徑『管銷分攤（毛利 N%）』
  function adminLabel(ver, pct) {
    if (ver !== FORMULA_VER) return '管銷分攤（10%）'
    return '管銷分攤（毛利 ' + String(pct == null ? DEFAULT_OVERHEAD_PCT : pct) + '%）'
  }

  var api = { LEGACY_VER: LEGACY_VER, FORMULA_VER: FORMULA_VER, ACTIVE_VER: ACTIVE_VER, DEFAULT_OVERHEAD_PCT: DEFAULT_OVERHEAD_PCT,
              TARGET_MARGIN_PCT: TARGET_MARGIN_PCT, pctRate: pctRate, adminLabel: adminLabel, adminCost: adminCost, charity: charity, quote: quote, settlement: settlement }
  if (typeof window !== 'undefined') window.MotrixProfitRules = api
  if (typeof module !== 'undefined' && module.exports) module.exports = api
})()
