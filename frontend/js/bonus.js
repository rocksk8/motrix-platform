// 獎金分潤（`FN2`）。
//
// 🔴 可見性由**後端**決定，這裡不做任何過濾。
//    `§七`：管理者看全部／本人只看自己那一列／其他人看不到。
//    ☠️ 前端過濾是假的：值仍然在 API 回應裡，打開開發者工具就看得到
//       **全公司每個人領多少**。
//    ⇒ 這一支只負責「把後端給的東西畫出來」，而 `isManager` 也是後端說的。

function bonusPage() {
  return {
    loaded: false,
    loadError: '',
    awards: [],
    isManager: false,

    _token() {
      // ⚠️ token 存在 `motrix_session` 這個 JSON 裡，不是一個同名的獨立鍵。
      //    （2026-09-23 踩過一次：拿錯會靜默回 null ⇒ 401 ⇒ 整頁空白。）
      try {
        return (JSON.parse(localStorage.getItem('motrix_session') || '{}').token) || ''
      } catch (e) { return '' }
    },

    async init() {
      try {
        const r = await fetch('/api/bonus/awards', {
          headers: { Authorization: 'Bearer ' + this._token() },
        })
        if (r.status === 403) {
          this.loadError = '您沒有檢視獎金分潤的權限。若需要存取，請聯絡系統管理員。'
          return
        }
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const d = await r.json()
        this.awards = d.awards || []
        this.isManager = !!d.is_manager
        this.loaded = true
      } catch (e) {
        // 🔑 說出是哪一支壞了：使用者回報時那句話是唯一的線索。
        this.loadError = '獎金資料載入失敗（' + e.message + '）。請重新整理，若持續發生請回報。'
      }
    },

    fmt(n) {
      // ⚠️ `undefined` 與 `0` 是兩件事：後端對非管理者**不回** base_amount，
      //    而把它印成 0 會讓人以為那個案件沒有賺錢。
      if (n === undefined || n === null) return '—'
      return 'NT$ ' + Math.round(n).toLocaleString()
    },

    pct(bp) {
      // 比例存的是**基點**（1/10000）。畫面顯示成百分比，而算術一律在後端用整數做。
      // ☠️ 前端自己拿百分比再乘一次的話，就會出現「畫面上的數字加起來不等於總額」。
      return ((Number(bp) || 0) / 100).toFixed(2).replace(/\.00$/, '') + '%'
    },
  }
}
