// 傳票版面（`VC4a` 骨架）。
//
// 版面照使用者提供的實例 `docs/reference/傳票-實例-20260330-006.pdf`
// （逐欄分析在 `STATE.md §103b`）—— **不是照我想像的傳票長相**。
//
// 🔴 這一輪是**骨架**：欄位與合計可以操作，而儲存／送審／過帳**還沒有 API**。
//    ⚠️ 所以畫面上明著寫「尚未提供」，不留一顆按了沒反應的按鈕 ——
//    ☠️ 點了沒反應在使用者眼中就是「壞了」，而那比「還沒做」難查得多。

function voucherPage() {
  return {
    company: '',
    voucherNo: '',        // 🔴 由後端產生，前端不發號
    voucherDate: '',
    status: '草稿',
    note: '',
    lines: [],
    signs: { maker: '', checker: '', manager: '' },
    loadError: '',

    // 只有草稿可編輯（`SPEC-VOUCHER.md §一`）。
    // ⚠️ 這裡是**畫面的方便**，不是防線：真正的擋關在後端 `can_edit(status)`。
    get canEdit() { return this.status === '草稿' },

    _token() {
      try {
        return (JSON.parse(localStorage.getItem('motrix_session') || '{}').token) || ''
      } catch (e) { return '' }
    },

    async init() {
      // 🔁 日期**可選，預設今天**（使用者 2026-09-23 改裁）。
      //    舊裁示「建檔當天且不可編輯」已被推翻 —— 月結補登是會計的日常。
      this.voucherDate = new Date().toLocaleDateString('sv-SE')   // YYYY-MM-DD（本地時區）
      for (let i = 0; i < 3; i++) this.addLine()
      await this.loadCompany()
    },

    async loadCompany() {
      // ⚠️ 抬頭從設定讀。**不要寫死** —— 這個 repo 已經寫死在 14 個檔、56 行。
      try {
        const r = await fetch('/api/settings/company-profile', {
          headers: { Authorization: 'Bearer ' + this._token() },
        })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        this.company = (await r.json()).name || ''
      } catch (e) {
        // 🔑 抬頭讀不到**不該讓整頁不能用** —— 它只是版面上的一行字。
        //    而它也不可以靜默：使用者要看得出來是「沒設定」還是「讀失敗」。
        this.loadError = '公司抬頭讀取失敗（' + e.message + '）。版面其餘部分仍可使用。'
      }
    },

    addLine() {
      // 🔑 金額預設是**空字串不是 0** —— 使用者的實例上，借方有數字時
      //    貸方那一格是**留白**的，不是印一個 0。
      //    ☠️ 印 0 的話，一張只有三行的傳票看起來像有六個金額；
      //       而「0」在會計上是一個**有意義的數字**，不等於「沒有填」。
      this.lines.push({ account_code: '', account_name: '', summary: '', debit: '', credit: '' })
    },

    async fillName(i) {
      // 輸入科目代號後帶出名稱。
      // ⚠️ 帶不出來時**不要清空使用者打的東西**，也不要擋他繼續打 ——
      //    代號對不對由後端在儲存時判（`validate_account_code`）。
      const code = (this.lines[i].account_code || '').trim()
      if (!code) { this.lines[i].account_name = ''; return }
      try {
        const r = await fetch('/api/account-items', {
          headers: { Authorization: 'Bearer ' + this._token() },
        })
        if (!r.ok) return
        const d = await r.json()
        const hit = this._find(d.tree || [], code)
        if (hit) this.lines[i].account_name = hit.name
      } catch (e) { /* 帶不出來就讓使用者自己填 */ }
    },

    _find(nodes, code) {
      for (const n of nodes) {
        if (n.code === code) return n
        const r = this._find(n.children || [], code)
        if (r) return r
      }
      return null
    },

    // 🔑 合計在前端即時算，**而它只是顯示** ——
    //    能不能過帳由後端 `check_balance()` 決定（A 明著交代）。
    //    ☠️ 前端自己判的話就是第二份判準，而它會在某天與後端不一致 ⇒
    //       使用者看到「畫面說可以，按下去被拒絕」。
    get totalDebit() { return this.lines.reduce((s, l) => s + (Number(l.debit) || 0), 0) },
    get totalCredit() { return this.lines.reduce((s, l) => s + (Number(l.credit) || 0), 0) },

    fmt(n) {
      if (n === undefined || n === null) return ''
      return Math.round(n).toLocaleString()
    },
  }
}
