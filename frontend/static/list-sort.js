/* 清單排序偏好共用工具（2026-08-24）——供報價單列表／案件管理案件清單／案件內
 * 單據子清單（出貨單/開票憑據/請款單）共用。每個 list_key 對應後端
 * user_list_prefs 一筆紀錄（GET/PUT /api/list-prefs/{list_key}），純粹是
 * 個人化 UI 偏好：排序欄位＋正倒序，或拖曳自訂順序（sortMode='custom'，
 * customOrder 存項目 id 陣列）。呼叫端自行決定 list_key 的範圍（頂層清單用
 * 固定字串；案件內子清單要加上 quote_no 前綴避免跨案件互相污染）。
 */

async function loadListPref(token, listKey) {
  try {
    const r = await fetch(`/api/list-prefs/${encodeURIComponent(listKey)}`, {
      headers: { Authorization: 'Bearer ' + token }
    })
    if (r.ok) return await r.json()
  } catch {}
  return { sortMode: '', sortDir: 'desc', customOrder: [] }
}

async function saveListPref(token, listKey, pref) {
  try {
    await fetch(`/api/list-prefs/${encodeURIComponent(listKey)}`, {
      method: 'PUT',
      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sortMode: pref.sortMode || '',
        sortDir: pref.sortDir || 'desc',
        customOrder: pref.customOrder || [],
      })
    })
  } catch {}
}

/** items: 已篩選好的陣列；pref: {sortMode, sortDir, customOrder}；
 *  fieldGetters: { [sortMode]: item => 可比較值 }；idGetter: item => 唯一字串 id。
 *  回傳新陣列（不改動原陣列）。sortMode='custom' 時依 customOrder 排列，陣列裡
 *  沒出現過的項目（例如新建立的）一律排在最後，順序照原本清單順序。 */
function applyListSort(items, pref, fieldGetters, idGetter) {
  if (!pref || !items || !items.length) return items || []
  if (pref.sortMode === 'custom') {
    const order = pref.customOrder || []
    if (!order.length) return items
    const idx = new Map(order.map((id, i) => [id, i]))
    return [...items].sort((a, b) => {
      const ai = idx.has(idGetter(a)) ? idx.get(idGetter(a)) : Infinity
      const bi = idx.has(idGetter(b)) ? idx.get(idGetter(b)) : Infinity
      return ai - bi
    })
  }
  const getter = fieldGetters[pref.sortMode]
  if (!getter) return items
  const dir = pref.sortDir === 'asc' ? 1 : -1
  return [...items].sort((a, b) => {
    const av = getter(a), bv = getter(b)
    if (av < bv) return -1 * dir
    if (av > bv) return 1 * dir
    return 0
  })
}
