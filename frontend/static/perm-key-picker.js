/* 權限鍵矩陣選擇器（設定矩陣 T86；取代 users.html「存取模組」手風琴：30 個鍵分 10 群、逐群展開逐一打勾）。
 *
 * 一組「已選的權限鍵」＋依群組分區的總覽：全部群組直接攤開（不用逐群展開）、每群一個總開關（全選／部分／全無）、篩選（名稱＋只看已選／未選）、
 * 批次勾選（全選目前列出的／全部取消）、儲存前的差異預覽（相對於「開啟當下」多了哪些、少了哪些）。鍵值與儲存格式不變：
 * 這個元件只改「怎麼勾」，不改「勾什麼」、也不寫入任何東西——真正的寫入仍是各視窗自己的「儲存」按鈕（＝確認），伺服器的原因／高敏感檢查照舊。
 *
 * 用法（兩個視窗各建一個實例，狀態互不干擾）：
 *   const picker = MotrixPermPicker.create({
 *     groups:   () => [{ group: '群組名', mods: [{ key, label }, …] }, …],     // 全部鍵（來源：GET /api/modules/catalog）
 *     selected: () => 目前已選鍵的陣列（即時讀）,
 *     set:      (keys) => 以新陣列取代已選（呼叫端自己指派並做後續連動，例如重新預覽生效權限）,
 *     inert:    (key) => 這個鍵不能勾（例如財務三鍵改由角色決定；選填）,
 *     inertOn:  (key) => 不能勾的鍵要顯示成「已有」還是「沒有」（選填）,
 *     high:     (key) => 高敏感鍵（顯示 ★；選填）,
 *   })
 *   picker.reset()   // 視窗開啟時呼叫：把目前的已選記成「開啟當下」，差異預覽以它為準
 * 畫面只用 x-text 顯示（權限名稱是使用者可編輯的內容，不用 x-html）。 */
(function () {
  if (!document.getElementById('pk-style')) {
    const st = document.createElement('style')
    st.id = 'pk-style'
    st.textContent = [
      '.pk-bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:6px 0}',
      '.pk-sum{font-size:12px;font-weight:600}',
      '.pk-grp{border:1px solid var(--border-light);border-radius:6px;margin-top:6px;overflow:hidden}',
      '.pk-head{display:flex;align-items:center;gap:8px;padding:6px 10px;background:var(--bg-secondary,#fafafa);font-size:12px;cursor:pointer}',
      '.pk-head input{margin:0}',
      '.pk-cnt{margin-left:auto;font-size:12px;color:var(--text-dim);font-weight:400}',
      '.pk-keys{display:flex;gap:6px;flex-wrap:wrap;padding:8px 10px}',
      '.pk-chip{display:flex;align-items:center;gap:5px;cursor:pointer;font-size:12px;padding:5px 10px;border:1px solid var(--border-light);border-radius:4px;background:#fff}',
      '.pk-chip.on{border-color:var(--accent);background:var(--accent-light);color:var(--accent)}',
      '.pk-chip.inert{cursor:default;opacity:.55;color:var(--text-dim);background:#f5f5f5}',
      '.pk-chip.add{box-shadow:0 0 0 2px #10b981 inset}',
      '.pk-chip.del{box-shadow:0 0 0 2px #ef4444 inset;text-decoration:line-through}',
      '.pk-diff{margin-top:8px;padding:8px 10px;border-radius:6px;background:#f3f4f6;font-size:12px;line-height:1.6}',
      '@media (max-width:767px){.pk-chip{min-height:40px}.pk-bar input,.pk-bar select{font-size:16px}}',
    ].join('')
    document.head.appendChild(st)
  }

  window.MotrixPermPicker = {
    create: function (cfg) {
      const inert = cfg.inert || function () { return false }
      const inertOn = cfg.inertOn || function () { return false }
      const high = cfg.high || function () { return false }
      return {
        q: '', show: 'all', base: [],
        reset() { this.base = [].concat(cfg.selected() || []); this.q = ''; this.show = 'all' },
        isOn(key) { return inert(key) ? !!inertOn(key) : cfg.selected().includes(key) },
        isInert(key) { return !!inert(key) },
        isHigh(key) { return !!high(key) },
        allKeys() { return cfg.groups().reduce((a, g) => a.concat(g.mods), []) },
        _label(key) { const m = this.allKeys().find(x => x.key === key); return m ? m.label : key },
        // 篩選後的群組（每群帶 total／selected：數字永遠是整群的，不隨篩選變）
        rows() {
          const q = (this.q || '').trim().toLowerCase(), sel = cfg.selected()
          return cfg.groups().map(g => {
            const mods = g.mods.filter(m => {
              if (q && !((m.label || '').toLowerCase().includes(q) || (g.group || '').toLowerCase().includes(q))) return false
              if (this.show === 'on') return this.isOn(m.key)
              if (this.show === 'off') return !this.isOn(m.key)
              return true
            })
            return { group: g.group, mods, total: g.mods.length, selected: g.mods.filter(m => this.isOn(m.key)).length }
          }).filter(g => g.mods.length)
        },
        // 群組總開關的狀態：只看「目前列出、而且能勾」的鍵
        state(g) {
          const t = g.mods.filter(m => !inert(m.key)), n = t.filter(m => this.isOn(m.key)).length
          return !t.length || n === 0 ? 'none' : (n === t.length ? 'all' : 'some')
        },
        summary() {
          const all = this.allKeys(), n = all.filter(m => this.isOn(m.key)).length
          return '已選 ' + n + ' / ' + all.length + ' 項'
        },
        toggle(key) {
          if (inert(key)) return
          const cur = cfg.selected(), i = cur.indexOf(key)
          cfg.set(i >= 0 ? cur.filter(k => k !== key) : cur.concat([key]))
        },
        // on===undefined ⇒ 群組總開關：全選過 → 全部取消；否則 → 全選（只動目前列出且能勾的鍵）
        toggleGroup(g, on) {
          const keys = g.mods.filter(m => !inert(m.key)).map(m => m.key)
          if (!keys.length) return
          this._bulk(keys, on === undefined ? this.state(g) !== 'all' : on)
        },
        // 全部列出的群組一起（「全選目前列出的」／「全部取消」：取消＝清掉所有已選，包含被篩選隱藏的，免得看不見的鍵還留著）
        selectVisible() { this._bulk([].concat.apply([], this.rows().map(g => g.mods.filter(m => !inert(m.key)).map(m => m.key))), true) },
        clearAll() { const all = this.allKeys().filter(m => !inert(m.key)).map(m => m.key); this._bulk(all, false) },
        _bulk(keys, on) {
          const set = new Set(cfg.selected())
          keys.forEach(k => on ? set.add(k) : set.delete(k))
          cfg.set(Array.from(set))
        },
        // 差異預覽：相對於 reset() 當下
        added() { return cfg.selected().filter(k => !this.base.includes(k) && !inert(k)) },
        removed() { return this.base.filter(k => !cfg.selected().includes(k) && !inert(k)) },
        hasDiff() { return this.added().length + this.removed().length > 0 },
        changeClass(key) { return this.added().includes(key) ? 'add' : (this.removed().includes(key) ? 'del' : '') },
        diffText() {
          const a = this.added().map(k => this._label(k)), r = this.removed().map(k => this._label(k))
          const cut = l => l.length > 8 ? l.slice(0, 8).join('、') + ' 等 ' + l.length + ' 項' : l.join('、')
          return '與開啟時相比：' + (a.length ? '新增 ' + a.length + ' 項（' + cut(a) + '）' : '無新增') + '、' + (r.length ? '取消 ' + r.length + ' 項（' + cut(r) + '）' : '沒有取消') + '。按「儲存」才會寫入。'
        },
      }
    }
  }
})()
