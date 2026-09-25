// 法規金額的捨入（L1；稽核 D-1，2026-09-26）。後端唯一來源：backend/helpers/legal_params.py
// `round_half_up`／`floor_amount`，這裡是同一套算法的前端版本（畫面試算用；存檔以後端為準）。
//
// 🔴 不可以寫 Math.round(gross * rate)：浮點乘積會把 x.5 算成 x.4999…（或反過來），
//    而 Python 內建 round() 又是銀行家捨入 ⇒ 前後端各錯各的（35,000 × 2.11%：畫面 739、存檔 738）。
// ⇒ 金額與費率都轉成「整數／10 的次方」再用 BigInt 做整數運算，結果與後端 Decimal 完全相同。
// 全域比對題：tests/test_e2e_legal_round_d1_2026_09_26.py（20,000～2,000,000 逐元比對後端）。
(function () {
  // 數字 → [分子 BigInt, 分母 BigInt]；用 JS 的最短十進位表示（與 Python repr(float) 相同的值）
  function ratio(x) {
    const s = String(x).trim().toLowerCase()
    const m = /^(-?)(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/.exec(s)
    if (!m) throw new Error('法規金額的數值格式不正確：' + s)
    const frac = m[3] || ''
    let num = BigInt(m[2] + frac)
    let scale = frac.length - (m[4] ? parseInt(m[4], 10) : 0)
    let den = 1n
    if (scale >= 0) den = 10n ** BigInt(scale)
    else num = num * (10n ** BigInt(-scale))
    return [m[1] === '-' ? -num : num, den]
  }

  function product(amount, rate) {
    const [an, ad] = ratio(amount)
    const [rn, rd] = ratio(rate == null ? 1 : rate)
    return [an * rn, ad * rd]
  }

  // amount × rate 四捨五入到元（角以下 4 捨 5 入；負數遠離 0，同 Decimal ROUND_HALF_UP）
  function halfUp(amount, rate) {
    const [n, d] = product(amount, rate)
    const q = n >= 0n ? (2n * n + d) / (2n * d) : -((2n * -n + d) / (2n * d))
    return Number(q)
  }

  // amount × rate 元以下捨去（向負無限大，同 Decimal ROUND_FLOOR）
  function floor(amount, rate) {
    const [n, d] = product(amount, rate)
    const q = n >= 0n ? n / d : -((-n + d - 1n) / d)
    return Number(q)
  }

  // 台北時間的今天（YYYY-MM-DD）。稽核 S-1／S-2：toISOString() 是 UTC，台灣 00:00～07:59 會變成前一天
  function taipeiToday(now) {
    return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' })
      .format(now || new Date())
  }

  window.MotrixLegalRound = { halfUp: halfUp, floor: floor, taipeiToday: taipeiToday }
})()
