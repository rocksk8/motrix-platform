// case-management-close.js — 案件管理頁：結案：五關、結案前檢查、健康總覽、跨模組連結、成交狀態與鎖定
// CM12 P1（2026-09-24）：由 case-management.js 原樣搬出，成員文字未改；組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({

    // 關卡 ⇒ 要去修的分頁。單據關依第一類待簽單據決定。
    _gateTab(g) {
      const byTable = {
        shipping_notes: 'shipping', completion_notes: 'completion',
        contractor_payment_vouchers: 'dispatch', invoice_vouchers: 'fin',
        payment_requests: 'fin', quotations: 'biz',
      }
      // CU5：收款（款項明細、請款單、開票申請）搬到「財務」分頁
      let t = { progress: 'exec', payment: 'fin', settlement: 'fin', extraExpense: 'xexp' }[g && g.key]
      if (g && g.key === 'documents') t = byTable[((g.pendingDocs || [])[0] || {}).table] || 'biz'
      // 財務分頁的「收款」人人看得到；其餘財務區塊（精算）與額外支出只給 canSeeFinancial
      const paymentish = g && (g.key === 'payment' || (g.key === 'documents' && t === 'fin'
        && ['payment_requests', 'invoice_vouchers'].includes(((g.pendingDocs || [])[0] || {}).table)))
      if (!this.canSeeFinancial() && (t === 'xexp' || (t === 'fin' && !paymentish))) t = 'biz'
      return t || 'biz'
    },

    // CU4（2026-09-24）：全部階段完成不再彈 confirm（會打斷正在做的事），改由執行進度上方的
    // 提示條（allStagesDone()）反應式顯示。保留這個名字給既有呼叫端。
    _checkAllStagesDone() {},

    allStagesDone() {
      if (this.cr.dealTag !== '已成案') return false
      const stages = this.cr.caseRecord?.stages || []
      return stages.length > 0 && stages.every(s => s.done)
    },

    // ── 結案前檢查（2026-09-24）─────────────────────────────────────────
    // 原本先 confirm、再存檔（失敗照樣送結案）、最後才被 400 擋下並列一串理由。
    // 改成：先存檔，失敗就中止；再列出五關（與擋結案同一份判定），未過的有「前往」；
    // 五關全過才能按確認。
    closeCheck: { open: false, gates: [], canClose: false },

    async closeCaseAction() {
      if (!this.selected) return
      clearTimeout(this._autoSaveTimer)
      while (this.saving) await new Promise(res => setTimeout(res, 50))
      await this.saveCaseRecord()
      if (this.saveStatus === 'error' || this.segConflict) {
        MotrixUI.toast('案件沒有存成功，已停止結案：' + (this.saveMsg || '儲存失敗'), {kind: 'error'})
        return
      }
      try {
        const r = await fetch('/api/quotations/' + this.selected.quote_no + '/close-gates', {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { MotrixUI.toast(d.detail || '無法取得結案條件', {kind: 'error'}); return }
        this.closeCheck = { open: true, gates: d.gates || [], canClose: !!d.canClose }
      } catch {
        MotrixUI.toast('網路錯誤，請稍後再試', {kind: 'error'})
      }
    },

    closeCheckGoto(g) {
      this.closeCheck.open = false
      this.gotoGate(g)
    },

    gotoGate(g) {
      const t = this._gateTab(g)
      this.activeTab = t
      if (t === 'exec') this.execSubTab = 'progress'
      if (t === 'shipping') this.loadShippingNotes(this.selected.quote_no)
      if (t === 'completion') this.loadCompletionNotes(this.selected.quote_no)
    },

    // ── 案件健康總覽（2026-09-24）────────────────────────────────────────
    // 案件資訊頁上方：五關（/close-gates，與擋結案同一份判定）＋逾期應收＋待簽核。
    // 回應可能在使用者已切到別的案件後才抵達 ⇒ 只收「目前選的那一件」的回應。
    caseHealth: { quoteNo: '', gates: [] },

    async loadCaseHealth(quoteNo, pre) {
      if (!quoteNo) return
      try {
        const r = pre ? this._preResp(pre) : await fetch('/api/quotations/' + encodeURIComponent(quoteNo) + '/close-gates', {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) return
        const d = await r.json()
        if (this.selected?.quote_no !== quoteNo) return
        this.caseHealth = { quoteNo, gates: d.gates || [] }
      } catch {}
    },

    healthDocs() {
      if (this.caseHealth.quoteNo !== this.selected?.quote_no) return null
      return (this.caseHealth.gates || []).find(g => g.key === 'documents' && g.state === 'blocked') || null
    },

    // 未收款且預計收款日已過（今天到期不算逾期）
    overdueReceivables() {
      const today = new Date().toISOString().slice(0, 10)
      return this.paymentItems().filter(it => !it.received && it.expectedReceiptDate && it.expectedReceiptDate < today)
    },

    async confirmCloseCase() {
      if (!this.closeCheck.canClose) return
      this.closeCheck.open = false
      const entry = { at: new Date().toISOString(), user: this.session.displayName || '', from: '已成案', to: '已結案' }
      await this.updateDealTag('已結案', entry)
      // 結案後留在案件頁（原本 800ms 後跳保固頁）
      if (this.cr.dealTag === '已結案') {
        this.saveStatus = 'saved'
        this.saveMsg = '已結案，保固追蹤已開始'
      }
    },

    // ── 跨模組連結（2026-09-24）─────────────────────────────────────────
    // 地圖（MP6 案件圖層）、獎金分配（bonus.js 的 ?q=）、相關傳票（分錄來源指向本案）。
    // 看不到該頁的人不顯示連結；回應晚到時只收目前選的那一件。
    caseLinks: { quoteNo: '', vouchers: [], bonusEnabled: false },

    _hasModule(k) {
      if (this.session.role === 'superadmin') return true
      let m = this.session.modules || []
      if (typeof m === 'string') { try { m = JSON.parse(m) } catch { m = [] } }
      return Array.isArray(m) && m.includes(k)
    },

    caseMapUrl() {
      if (!this.selected || !this._hasModule('map')) return ''
      const addr = this.cr.caseRecord?.contract?.deliveryAddress || this.selected.data?.deliveryLocation || ''
      if (!addr.trim()) return ''
      return 'map.html?focus=' + encodeURIComponent('cases:' + this.selected.quote_no)
    },

    async loadCaseLinks(quoteNo, preVouchers) {
      if (!quoteNo) return
      const auth = { Authorization: 'Bearer ' + this.session.token }
      const out = { quoteNo, vouchers: [], bonusEnabled: false }
      const jobs = []
      if (preVouchers && (this._hasModule('cashier') || this._hasModule('finance'))) {
        out.vouchers = (preVouchers.ok && preVouchers.data && preVouchers.data.vouchers) || []
      } else if (this._hasModule('cashier') || this._hasModule('finance')) {
        jobs.push(fetch('/api/vouchers/by-case/' + encodeURIComponent(quoteNo), { headers: auth })
          .then(r => r.ok ? r.json() : null).then(d => { out.vouchers = (d && d.vouchers) || [] }).catch(() => {}))
      }
      if (this.session.role === 'superadmin') {
        jobs.push(fetch('/api/system/bonus-module-status', { headers: auth })
          .then(r => r.ok ? r.json() : null).then(d => { out.bonusEnabled = !!(d && d.enabled) }).catch(() => {}))
      }
      await Promise.all(jobs)
      if (this.selected?.quote_no !== quoteNo) return
      this.caseLinks = out
    },

    async updateDealTag(tag, logEntry) {
      if (!this.selected) return
      try {
        const body = { deal_tag: tag }
        if (logEntry) body.log_entry = logEntry
        const r = await fetch('/api/quotations/' + this.selected.quote_no + '/deal-tag', {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(body)
        })
        if (r.ok) {
          this.cr.dealTag = tag
          this.selected.deal_tag = tag
          if (!this.selected.data)             this.selected.data = {}
          if (!this.selected.data.statusLog)   this.selected.data.statusLog = []
          if (logEntry) this.selected.data.statusLog.push(logEntry)
          const idx = this.cases.findIndex(c => c.quote_no === this.selected.quote_no)
          if (idx !== -1) this.cases[idx].deal_tag = tag
          this.loadCaseCounts()
          this.filterCases()
        } else {
          // 結案防呆機制（2026-08-25/26）擋下時會回 400 + 說明未達成的前置
          // 條件，不能靜默吞掉，不然使用者只會看到「結案」按鈕沒反應。
          const err = await r.json().catch(() => ({}))
          MotrixUI.toast(err.detail || '操作失敗，請稍後再試', {kind: 'error'})
        }
      } catch {
        MotrixUI.toast('網路錯誤，請稍後再試', {kind: 'error'})
      }
    },

    async unlockCase() {
      if (!this.selected) return
      if (!(await MotrixUI.confirm('確認解鎖此已結案案件？\n\n解鎖後將進入「半解鎖」狀態，之後對案件記錄的變更/上傳需最高管理員於簽核佇列審核通過後才會套用。', {danger: true}))) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/case-unlock`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) {
          this.selected.case_semi_unlocked = 1
        } else {
          MotrixUI.toast((await r.json().catch(() => ({}))).detail || '解鎖失敗', {kind: 'error'})
        }
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async lockCase() {
      if (!this.selected) return
      if (!(await MotrixUI.confirm('確認重新上鎖此案件？\n\n上鎖後將無法再變更案件記錄，需再次解鎖才能繼續編輯（既有待審核項目不受影響）。', {danger: true}))) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/case-lock`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) {
          this.selected.case_semi_unlocked = 0
        } else {
          MotrixUI.toast((await r.json().catch(() => ({}))).detail || '上鎖失敗', {kind: 'error'})
        }
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    closingReportDownloading: false,
    async downloadClosingReportPdf() {
      if (!this.selected) return
      const quoteNo = this.selected.quote_no
      this.closingReportDownloading = true
      try {
        const r = await fetch(`/api/quotations/${quoteNo}/closing-report-pdf`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '結案報表產生失敗', {kind: 'error'}); return }
        const blob = await r.blob()
        const url  = URL.createObjectURL(blob)
        const a    = document.createElement('a')
        a.href     = url
        a.download = `${quoteNo}_結案報表.pdf`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      } catch (e) { MotrixUI.toast('下載失敗：' + e.message, {kind: 'error'}) }
      finally { this.closingReportDownloading = false }
    },
}))
