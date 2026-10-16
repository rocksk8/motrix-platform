/* display-labels.js — 小模組狀態／單位／用語的顯示名稱（C7；設定中心群組 netplan_labels／procurement_labels／lodging_labels／trail_labels）。
   預設＝各畫面原本寫死的字；讀不到／不合法 ⇒ 整組用預設。只換『看到的字』，狀態值（規劃中／suggested／per_night…）與邏輯一律用原值。
   用法：頁面資料物件放 `lb: MotrixLabels.defaults()`，init 時 `MotrixLabels.load().then(m => { this.lb = m })`；畫面用 `lb.netplan_labels.planning`。 */
(function () {
  const DEF = {
    netplan_labels: { planning: '規劃中', confirmed: '已確認', delivered: '已交付' },
    procurement_labels: { suggested: '待下單', ordered: '已下單', received: '已到貨' },
    lodging_labels: { per_night: '每晚', per_person: '每人', phone: '電話', website: '官網', onsite: '現場', other: '其他' },
    trail_labels: {
      view: '檢視', change: '變更', delete: '刪除', approve: '簽核', export: '匯出',
      ok: '成功', created: '已建立', not_modified: '沒有變更', bad_request: '資料有誤', unauthorized: '需要重新登入',
      forbidden: '沒有權限（被擋下）', not_found: '找不到資料', conflict: '有人剛改過（衝突）', too_large: '檔案太大',
      invalid: '資料格式有誤', rate_limited: '操作太頻繁'
    }
  }
  const NETPLAN_KEY = { '規劃中': 'planning', '已確認': 'confirmed', '已交付': 'delivered' }
  function clone() { const o = {}; for (const g of Object.keys(DEF)) o[g] = Object.assign({}, DEF[g]); return o }
  function normalise(raw) {
    const out = clone()
    for (const g of Object.keys(DEF)) {
      const vals = raw && raw[g]
      if (!vals || typeof vals !== 'object') continue
      const next = {}
      let ok = true
      for (const k of Object.keys(DEF[g])) {
        const v = vals[k]
        if (typeof v !== 'string' || !v.trim() || v.length > 12) { ok = false; break }
        next[k] = v
      }
      if (ok) out[g] = next
    }
    return out
  }
  let _p = null
  async function _fetch() {
    try {
      const s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      if (!s.token) return clone()
      const r = await fetch('/api/settings-center/public?groups=' + Object.keys(DEF).join(','), { headers: { Authorization: 'Bearer ' + s.token } })
      if (!r.ok) return clone()
      return normalise((await r.json()).groups)
    } catch (e) { return clone() }
  }
  function load() { return _p || (_p = _fetch()) }              // 同一頁面只打一次 API（頁面 init 可能跑兩次）
  window.MotrixLabels = {
    defaults: clone, normalise, load,
    netplan: (m, v) => { const k = NETPLAN_KEY[v]; return k ? (m && m.netplan_labels && m.netplan_labels[k]) || v : (v || '') }
  }
})()
