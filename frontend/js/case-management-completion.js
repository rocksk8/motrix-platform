// case-management-completion.js — 案件管理頁：完工單分頁
// CM12 P1（2026-09-24）：由 case-management.js 原樣搬出，成員文字未改；組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({

    // ── 完工單（2026-09-12）────────────────────────────────────────────────
    //
    // 使用者交辦：「在案件管理內增加完工單的選項，參考出貨單的形式跟內容建立完工單，
    // 一樣走流程申請完工。」所以這一整段刻意比照上面的出貨單：同一套狀態機、同一套
    // 分層簽核、同一套回簽。欄位差異與理由見 backend/db.py::_m077_completion_notes()。
    //
    // ⚠️ 後端 list 端點回的是 `{items: [...]}`（新端點的慣例），不是出貨單那種裸陣列，
    //    照抄 `= await r.json()` 會拿到一個物件、畫面永遠空白且沒有任何錯誤。
    // 清單在案件管理、填寫在獨立頁面 completion-note-form.html（比照報價單清單與
    // 報價單表單的分工）。所以這裡**只留清單與狀態動作**，不再有表單狀態。
    completionNotes: [],
    completionNotesLoading: false,
    completionPreviewFetching: false,

    async loadCompletionNotes(quoteNo, pre) {
      if (!quoteNo) return
      const live = this._selectLive()
      // 比照 loadExtraExpenses()：記住發請求當下是哪張單，回應抵達時再比對。
      // 少了這道守門，切案件切太快就會把 A 案的完工單畫在 B 案底下
      this._cnReqFor = quoteNo
      this.completionNotesLoading = true
      try {
        const r = pre ? this._preResp(pre) : await fetch(`/api/completion-notes?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        if (this._cnReqFor !== quoteNo) return
        const body = r.ok ? (await r.json()).items || [] : null
        if (!live()) return
        if (r.ok) this.completionNotes = body
      } catch {}
      this.completionNotesLoading = false
    },

    async deleteCompletionNote(n) {
      if (!confirm(`確定刪除完工單「${n.noteNo}」？`)) return
      await this._cnAction(n, '', 'DELETE', '刪除失敗')
    },

    async submitCompletionNote(n) {
      const unfinished = n.unfinishedCount || 0
      const warn = unfinished
        ? `\n\n⚠️ 這張單有 ${unfinished} 項未完成，請確認「遺留事項」已寫清楚。`
        : ''
      if (!confirm(`確定送出完工單「${n.noteNo}」申請完工？${warn}`)) return
      await this._cnAction(n, '/submit', 'POST', '送出失敗')
    },

    async approveCompletionNote(n) {
      // 同一人連任多層時一次簽完（2026-09-15，見 static/approval-cascade.js）。
      // 清單資料沒帶 approval.tiers 時算出來是空陣列，行為跟以前一樣。
      const _appr = n.approval || {}
      const _casc = window.MotrixApproval.selfCascadeTiers(
        _appr.tiers || [], _appr.currentTier ?? 0, this.session.username, [])
      if (!confirm(`確定簽核完工單「${n.noteNo}」？` + window.MotrixApproval.cascadeNote(_casc))) return
      await this._cnAction(n, '/approve', 'POST', '簽核失敗', { cascade: _casc.length > 0 })
    },

    async rejectCompletionNote(n) {
      const note = prompt(`退回完工單「${n.noteNo}」，可填寫退回原因（選填）：`)
      if (note === null) return
      await this._cnAction(n, '/reject', 'POST', '退回失敗', { note })
    },

    async revokeCompletionApproval(n) {
      const note = prompt(`撤銷完工單「${n.noteNo}」的核准？將退回草稿。\n\n可填寫撤銷原因（選填）：`)
      if (note === null) return
      await this._cnAction(n, '/revoke-approval', 'POST', '撤銷失敗', { note })
    },

    async toggleCompletionSigned(n, action) {
      const msg = action === 'sign'
        ? `確定標記完工單「${n.noteNo}」客戶已驗收簽回？`
        : `確定取消完工單「${n.noteNo}」的驗收標記？`
      if (!confirm(msg)) return
      const note = action === 'sign' ? (prompt('備註（選填，例如驗收人姓名或方式）：') || '') : ''
      await this._cnAction(n, '/signed-toggle', 'POST', '操作失敗', { action, note })
    },

    // 六個動作的差別只有路徑與 body，抽出來免得複製六份各自漂移
    async _cnAction(n, path, method, failMsg, body) {
      try {
        const opts = { method, headers: { Authorization: 'Bearer ' + this.session.token } }
        if (body !== undefined) {
          opts.headers['Content-Type'] = 'application/json'
          opts.body = JSON.stringify(body)
        }
        const r = await fetch(`/api/completion-notes/${n.noteNo}${path}`, opts)
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || failMsg); return }
        await this.loadCompletionNotes(this.selected?.quote_no)
      } catch (e) { alert('網路錯誤：' + e.message) }
    },

    async previewCompletionPdf(n) {
      this.completionPreviewFetching = true
      try {
        const r = await fetch(`/api/completion-notes/${n.noteNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗'); return }
        const blob = await r.blob()
        const url = URL.createObjectURL(blob)
        window.open(url, '_blank')
        setTimeout(() => URL.revokeObjectURL(url), 60000)
        fetch(`/api/completion-notes/${n.noteNo}/export?mode=preview`, {
          method: 'POST', headers: { Authorization: 'Bearer ' + this.session.token }
        }).catch(() => {})
      } catch (e) { alert('網路錯誤：' + e.message) }
      this.completionPreviewFetching = false
    },

    _completionStatusLabel(s) { return s || '草稿' },
    _completionStatusClass(s) {
      if (s === '已核准') return 'badge-green'
      if (s === '待審核' || s === '簽核中') return 'badge-amber'
      return 'badge-gray'
    },

    // CM12 P2：切換案件時重設本模組的案件層級狀態（時點見 core 的 _resetCaseScoped）
    _reset_completion(phase, data) {
      if (phase === 'late') {
        this.completionNotes = []
      }
    },
}))
