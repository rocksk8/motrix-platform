// 會計科目樹（`FN1`）。
//
// 🔴 樹是**後端用 parent_code 建好**才送過來的，前端一個字元的前綴都不推。
//    實算：547 筆裡有 232 筆（42%）的 parent_code 不是自己的前綴 ——
//    不只是「11-12」這種範圍代號，連 `3220` 的父是 `321` 也是
//    （四級編號跑到 3219 之後**進位**，直接跨出父的前綴）。
//
// 🔑 第一眼**預設展開到第二層**（28 列，約一個螢幕）。兩端都不好：
//    全展開 547 列是一面牆；全收合只有 8 列，使用者會以為只有 8 筆科目。
//    ⇒ 收合的節點標「N 項」＋ 頁首標總數，**讓畫面自己說出底下還有東西**。

function accountItemsPage() {
  return {
    loaded: false,
    loadError: '',
    tree: [],
    counts: {},
    total: 0,
    bySource: {},
    open: {},
    q: '',

    sourceOrder: ['statutory', 'system_default', 'custom'],
    // ⚠️ 三態要分得出來。把 `system_default` 併進「自訂」的話，使用者會在
    //    自己的清單裡看到一個他從來沒建過的項目，**而他不敢刪**。
    sourceLabel: {
      statutory: '法定',
      system_default: '系統預設',
      custom: '自訂',
    },

    async init() {
      try {
        const r = await fetch('/api/account-items', {
          headers: { Authorization: 'Bearer ' + (localStorage.getItem('token') || '') },
        })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        const d = await r.json()
        this.tree = d.tree || []
        this.counts = d.counts || {}
        this.total = d.total || 0
        this.bySource = d.by_source || {}
        this.expandTo(2)
        this.loaded = true
      } catch (e) {
        // 🔑 說出是哪一支壞了，不要只說「網路錯誤」——
        //    使用者回報時那句話是唯一的線索。
        this.loadError = '會計科目載入失敗（' + e.message + '）。請重新整理，若持續發生請回報。'
      }
    },

    // ── 展開／收合 ──────────────────────────────────────────────
    _walk(nodes, fn, depth) {
      for (const n of nodes || []) {
        fn(n, depth || 1)
        this._walk(n.children, fn, (depth || 1) + 1)
      }
    },

    expandTo(level) {
      const open = {}
      this._walk(this.tree, (n) => {
        if ((n.level || 0) < level && (n.children || []).length) open[n.code] = true
      })
      this.open = open
    },

    expandAll() {
      const open = {}
      this._walk(this.tree, (n) => {
        if ((n.children || []).length) open[n.code] = true
      })
      this.open = open
    },

    toggle(code) {
      // ⚠️ 用展開後重新指派整個物件，Alpine 才會重繪（直接改屬性不會）。
      this.open = Object.assign({}, this.open, { [code]: !this.open[code] })
    },

    // ── 攤平成畫面上的列 ────────────────────────────────────────
    get visibleRows() {
      const q = this.q.trim().toLowerCase()
      const rows = []

      if (q) {
        // 🔑 搜尋時**忽略展開狀態**，直接列出命中的那些（含它們的代號路徑）。
        //    ☠️ 只在已展開的節點裡搜的話，使用者搜得到的東西取決於他之前點過
        //       哪些節點 —— 而那看起來像「搜尋壞了」。
        this._walk(this.tree, (n) => {
          const hit = (n.code || '').toLowerCase().includes(q)
            || (n.name || '').toLowerCase().includes(q)
            || (n.name_en || '').toLowerCase().includes(q)
          if (hit) rows.push(this._row(n))
        })
        return rows
      }

      const push = (nodes) => {
        for (const n of nodes || []) {
          rows.push(this._row(n))
          if (this.open[n.code]) push(n.children)
        }
      }
      push(this.tree)
      return rows
    },

    _row(n) {
      return {
        code: n.code,
        level: n.level || 1,
        name: n.name || '',
        name_en: n.name_en || '',
        source: n.source || 'custom',
        // 🔑 子孫數用後端算好的那一份（§37a 同源同單位）——
        //    前端自己數一次的話，日後匯出會出現第三個數字。
        kids: this.counts[n.code] || 0,
      }
    },

    get matchHint() {
      const n = this.visibleRows.length
      return n ? ('找到 ' + n + ' 筆') : '沒有符合的科目'
    },
  }
}
