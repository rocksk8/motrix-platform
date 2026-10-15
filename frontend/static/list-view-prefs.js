/* T65 C1：清單檢視的個人偏好（欄位隱藏／順序、預設頁籤、每頁筆數）。只在設定中心 list_view 的對應選項開啟時才被載入。
   偏好存在 user_list_prefs（沿用 GET/PUT /api/list-prefs/{key}，不新增路由）：以專用 key（quotations.view）的 customOrder 存 "k=v" 字串。
   一律只能縮小或重排公司允許的集合：欄位限已知欄位、不可隱藏必要欄位、頁籤限頁面上有的、筆數限固定檔位；任何不合法的值退回預設。
   金額／毛利率欄位只能隱藏或調順序——被遮蔽者看到的內容仍由伺服端決定（這裡不碰資料）。 */
(function () {
  const SIZES = [25, 50, 100, 200]
  const COLS = ['quoteNo', 'customer', 'project', 'amount', 'margin', 'validDays', 'filler', 'status', 'dealTag', 'date']
  const FIXED = ['quoteNo', 'customer', 'status', 'dealTag']
  const empty = () => ({ hidden: [], order: COLS.slice(), tab: '', size: 0 })
  const csv = v => (v ? String(v).split(',').filter(Boolean) : [])

  function parse(p) {
    const o = empty(), arr = p && Array.isArray(p.customOrder) ? p.customOrder : []
    for (const s of arr) {
      if (typeof s !== 'string') continue
      const i = s.indexOf('=')
      if (i < 1) continue
      const k = s.slice(0, i), v = s.slice(i + 1)
      if (k === 'hide') o.hidden = csv(v)
      else if (k === 'order') o.order = csv(v)
      else if (k === 'tab') o.tab = v
      else if (k === 'size') o.size = parseInt(v, 10) || 0
    }
    return o
  }

  /** allow: { tabs: [頁籤 key…] }。回傳新物件，不改輸入。 */
  function sanitize(o, allow) {
    o = o || {}
    const seen = new Set(), order = []
    for (const k of (Array.isArray(o.order) ? o.order : [])) if (COLS.includes(k) && !seen.has(k)) { seen.add(k); order.push(k) }
    for (const k of COLS) if (!seen.has(k)) order.push(k)                                  // 沒提到的欄位接在後面（新欄位不會憑空消失）
    const hidden = (Array.isArray(o.hidden) ? o.hidden : []).filter((k, i, a) => COLS.includes(k) && !FIXED.includes(k) && a.indexOf(k) === i)
    const tabs = (allow && allow.tabs) || []
    return { hidden, order, tab: tabs.includes(o.tab) ? o.tab : '', size: SIZES.includes(o.size) ? o.size : 0 }
  }

  function serialize(o) {
    return { sortMode: 'view', sortDir: 'desc', customOrder: ['hide=' + o.hidden.join(','), 'order=' + o.order.join(','), 'tab=' + (o.tab || ''), 'size=' + (o.size || 0)] }
  }

  async function load(token, key) {
    try {
      const r = await fetch('/api/list-prefs/' + encodeURIComponent(key), { headers: { Authorization: 'Bearer ' + token } })
      if (r.ok) return parse(await r.json())
    } catch (e) { /* 讀不到 ⇒ 預設 */ }
    return empty()
  }

  async function save(token, key, o) {
    try {
      const r = await fetch('/api/list-prefs/' + encodeURIComponent(key), {
        method: 'PUT', headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }, body: JSON.stringify(serialize(o)) })
      return r.ok
    } catch (e) { return false }
  }

  /** 依 order 重排表格裡帶 data-col 的儲存格（表頭與每一列）；已經是該順序就不動（可重複呼叫、不會觸發無限更新）。 */
  function reorder(table, order) {
    if (!table) return
    const idx = k => { const i = order.indexOf(k); return i < 0 ? 999 : i }
    for (const tr of table.querySelectorAll('tr')) {
      const cells = Array.from(tr.children).filter(c => c.dataset && c.dataset.col)
      if (cells.length < 2) continue
      const want = cells.slice().sort((a, b) => idx(a.dataset.col) - idx(b.dataset.col))
      if (want.every((c, i) => c === cells[i])) continue
      const anchor = cells[cells.length - 1].nextSibling
      for (const c of want) tr.insertBefore(c, anchor)
    }
  }

  /** 表格長新列（Alpine x-for 重繪）時重新套用順序。getOrder() 回傳目前要套的順序；回傳停止函式。 */
  function watchOrder(table, getOrder) {
    if (!table || typeof MutationObserver !== 'function') return function () {}
    const run = () => reorder(table, getOrder())
    const mo = new MutationObserver(run)
    mo.observe(table, { childList: true, subtree: true })
    run()
    return function () { mo.disconnect() }
  }

  window.MotrixListView = { SIZES, COLS, FIXED, empty, parse, sanitize, serialize, load, save, reorder, watchOrder }
})()
