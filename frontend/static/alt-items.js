// 擇一方案報價的「計入品項」（M3 T3；T57）。後端唯一來源：backend/modules/case/profit_guard.py 的 counted_items，這裡是同一套規則的前端版本。
// 等值測試：backend/tests/test_quote_alt_t3_2026_10_13.py（同一份黃金向量 tests/data/quote_alt_vectors.json，node 載入本檔比對）。
// 規則：非擇一項全部計入；每個擇一組只計入被選定的那一項（altPicks[組名]＝品項 id）；該組沒選 ⇒ 整組不計入。沒有任何 altGroup 的單與全部品項逐項相同。
// 前端只在畫面即時試算用；存檔後以伺服器重算為準。altPicks 由伺服器寫入，前端不得自行寫入。
(function () {
  function groupOf(i) {
    if (!i || typeof i !== 'object' || i.type === 'header') return ''
    return typeof i.altGroup === 'string' ? i.altGroup.trim() : ''
  }

  function normPicks(picks) {
    var out = {}
    if (!picks || typeof picks !== 'object' || Array.isArray(picks)) return out
    Object.keys(picks).forEach(function (k) {
      var v = picks[k]
      if (v !== null && v !== undefined && v !== '') out[String(k).trim()] = String(v)
    })
    return out
  }

  // picks 省略 ⇒ 取 q.altPicks；plan_view 類的假設選擇可由呼叫端傳入。不修改傳入的物件。
  function countedItems(q, picks) {
    var items = ((q && q.items) || []).filter(function (i) { return i && typeof i === 'object' })
    var p = normPicks(picks === undefined || picks === null ? (q && q.altPicks) : picks)
    return items.filter(function (i) {
      var g = groupOf(i)
      return !g || (p[g] !== undefined && p[g] === String(i.id))
    })
  }

  // 畫面標示用：未選定（不計入）的擇一項
  function isUncounted(q, item) {
    var g = groupOf(item)
    if (!g) return false
    var p = normPicks(q && q.altPicks)
    return !(p[g] !== undefined && p[g] === String(item.id))
  }

  // 尚未選定的組數（主合計列「尚有 N 組擇一未選」用）
  function unpickedGroupCount(q) {
    var p = normPicks(q && q.altPicks), seen = {}, n = 0
    ;((q && q.items) || []).forEach(function (i) {
      var g = groupOf(i)
      if (g && !seen[g]) { seen[g] = true; if (p[g] === undefined) n++ }
    })
    return n
  }

  var api = { groupOf: groupOf, countedItems: countedItems, isUncounted: isUncounted, unpickedGroupCount: unpickedGroupCount }
  if (typeof window !== 'undefined') window.MotrixAltItems = api
  if (typeof module !== 'undefined' && module.exports) module.exports = api
})()
