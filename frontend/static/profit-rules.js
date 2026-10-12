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

  // ── 專案毛利%（設計 QUOTE-PROJECT-GROSS-MARGIN-T56）：(未稅收入 − 未稅品項成本) ÷ 未稅收入 × 100，不扣進項稅／管銷／公益。
  // 後端孿生：helpers/profit_rules.py project_margin（同一份黃金向量 tests/data/project_margin_vectors.json）。
  // 以十進位字串轉 BigInt 做精確運算，四捨五入到 0.1、平手遠離零（12.25 → 12.3、−12.25 → −12.3）；pretax ≤ 0 或輸入不是有限數字 ⇒ pct = null（不是 0）。
  function isNum(x) { return typeof x === 'number' && isFinite(x) }
  function decParts(x) {
    var s = String(x)
    if (/e/i.test(s)) s = Number(x).toFixed(12)
    var neg = s.charAt(0) === '-'
    if (neg) s = s.slice(1)
    var p = s.split('.'), frac = p[1] || ''
    var n = BigInt(p[0] + frac)
    return { n: neg ? -n : n, scale: frac.length }
  }
  function pow10(k) { return BigInt('1' + new Array(k + 1).join('0')) }
  function uncostedItems(items) {
    var n = 0
    ;(items || []).forEach(function (i) {
      if (!i || typeof i !== 'object' || i.type === 'header') return
      if (!isNum(i.cost)) n++
    })
    return n
  }
  function projectMargin(pretax, totalCost, uncosted) {
    var out = { amount: null, pct: null, uncosted_items: uncosted || 0 }
    if (!isNum(pretax) || !isNum(totalCost)) return out
    var p = decParts(pretax), c = decParts(totalCost)
    var S = Math.max(p.scale, c.scale)
    var P = p.n * pow10(S - p.scale), C = c.n * pow10(S - c.scale)
    var A = P - C
    out.amount = Number(A) / Math.pow(10, S)
    if (P <= 0n) return out
    var neg = A < 0n, n = neg ? -A : A
    var tenths = (2n * n * 1000n + P) / (2n * P)
    out.pct = Number(neg ? -tenths : tenths) / 10
    return out
  }

  var api = { LEGACY_VER: LEGACY_VER, FORMULA_VER: FORMULA_VER, ACTIVE_VER: ACTIVE_VER, DEFAULT_OVERHEAD_PCT: DEFAULT_OVERHEAD_PCT,
              TARGET_MARGIN_PCT: TARGET_MARGIN_PCT, CHARITY_DIRECT: CHARITY_DIRECT, CHARITY_TOTAL: CHARITY_TOTAL, ACTIVE_CHARITY_BASIS: ACTIVE_CHARITY_BASIS, basisOf: basisOf, pctRate: pctRate, adminCost: adminCost, charity: charity, quote: quote, settlement: settlement, projectMargin: projectMargin, uncostedItems: uncostedItems }
  if (typeof window !== 'undefined') window.MotrixProfitRules = api
  if (typeof module !== 'undefined' && module.exports) module.exports = api
})()
