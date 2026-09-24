// case-management-fin.js — 案件管理頁：財務分頁：收款、財務總覽、稅額沖銷、開票申請、請款單
// CM12 P1（2026-09-24）：由 case-management.js 原樣搬出，成員文字未改；組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({
    writeoffModal: { open: false, idx: null, mode: 'request', reason: '' },
    needReceivedDate: {},    // CU7：剛勾已收款、還沒填日期的期別（以 item.id 為鍵；不寫進 item，否則會跟著存進 data_json）

    // ── 案件財務總覽（應收應付，2026-09-09）──
    // 後端一支 /finance-summary 端點算完，不在前端把 contractorVouchers /
    // paymentItems() 等既有陣列再加總一次——同一個案件的「還有多少沒收/沒付」
    // 若在前後端各算一份，遲早會因為其中一邊漏改（例如 taxExempt 沖銷折算）
    // 而對不起來，見 helpers/quotations.py::summarize_payment_items() 說明。
    financeSummary: null,
    financeSummaryLoading: false,
    finShowRecvDetail: false,
    finShowPayDetail: false,
    finShowExtraDetail: false,

    // ── 開票申請憑據 ──
    invoiceVouchers: [],
    invoiceVouchersLoading: false,
    ivSortPref: { sortMode: '', sortDir: 'desc', customOrder: [] },
    ivPreviewModal: false,
    ivPreviewBlobUrl: '',
    ivPreviewVoucher: null,
    ivPreviewFetching: false,
    ivCreateModal: false,
    ivRemaining: null,
    ivRemainingLoading: false,
    ivMode: 'amount',
    ivAmountInput: 0,
    ivItemSelections: {},
    ivSubmitting: false,

    // ── 請款單 ──（建立/編輯/簽核/PDF 已整頁化，見 payment-request-form.html，
    // 這裡只保留清單載入與排序）
    paymentRequests: [],
    paymentRequestsLoading: false,
    prListSortPref: { sortMode: '', sortDir: 'desc', customOrder: [] },

    caseSettlement()    { return this.selected?.data?.settlement || null },
    caseSettleStatus()  { return this.caseSettlement()?.status || '' },
    caseSettleSummary() { return this.caseSettlement()?.summary || {} },
    caseSettleItems()   { return this.caseSettlement()?.items   || [] },
    caseSettleExtras()  { return this.caseSettlement()?.extraItems || [] },
    caseSettleMemo()    { return this.caseSettlement()?.memo || '' },
    caseSettleFmt(n)    { return 'NT$ ' + (Math.round(n || 0)).toLocaleString() },

    // ── 應收應付總覽（2026-09-09）──────────────────────────────────────────
    async loadFinanceSummary(quoteNo) {
      if (!quoteNo) return
      const live = this._selectLive()
      this.financeSummaryLoading = true
      this.financeSummary = null
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/finance-summary`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? await r.json() : null
        if (!live()) return
        if (r.ok) this.financeSummary = body
      } catch {}
      this.financeSummaryLoading = false
    },
    finReceivable()  { return this.financeSummary?.receivable || null },
    finPayable()     { return this.financeSummary?.payable || null },
    finRelatedDocs() { return this.financeSummary?.relatedDocuments || { invoiceVouchers: [], paymentRequests: [] } },
    finExtrasTotal() { return this.financeSummary?.settlementExtras?.total || 0 },
    // 精算額外支出逐筆（含 2026-09-09 新增的單號）：資料源就是精算頁「二、額外
    // 支出」那張表，精算不論草稿或已完結都會列出來——使用者的作業順序是支出
    // 當下就先填、案件結束才做精算完結，只列已完結的等於當月看不到剛花的錢
    finExtraItems()  { return this.financeSummary?.settlementExtras?.items || [] },
    // 未收款項清單：只給總覽的展開明細用，已收的那些在「案件資訊」Tab 的款項
    // 明細本來就看得到，這裡重複列一次只會讓畫面變長
    finOutstandingItems() { return (this.finReceivable()?.items || []).filter(it => !it.received) },
    finUnpaidVouchers()   { return (this.finPayable()?.vouchers || []).filter(v => v.status === '已核准' && !v.isPaid) },

    paymentItems() { return this.cr.caseRecord?.payment?.items || [] },

    // CM13（2026-09-24）：後端對沒有財務檢視權的帳號遮蔽金額（selected.moneyMasked）。
    // 這時 total／amount 都是空的，任何換算都會算出 0 並自動存回去 ⇒ 會改金額的動作一律不做。
    moneyMasked() { return !!this.selected?.moneyMasked },

    // N14（2026-09-24）：款項金額改用文字框——type=number 貼上「12,000」時瀏覽器給空值，
    // 含稅／未稅的 +value 就變成 0。解析規則與 quotation-form.html::parseNumInput() 相同：
    // 接受千分位與全形數字；空白＝空值；解析不了 ⇒ 標紅（badNum），數值不更新、不存檔。
    badNum: {},
    parseNumInput(raw) {
      const s = String(raw == null ? '' : raw)
        .replace(/[０-９]/g, c => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))
        .replace(/．/g, '.').replace(/[,，\s]/g, '')
      if (s === '') return ''
      if (!/^\d+(\.\d*)?$/.test(s)) return null
      return parseFloat(s)
    },
    _markNum(badKey, bad) {
      if (bad) { this.badNum = { ...this.badNum, [badKey]: true }; return }
      if (this.badNum[badKey]) { const b = { ...this.badNum }; delete b[badKey]; this.badNum = b }
    },
    setNumField(obj, key, badKey, raw) {
      const v = this.parseNumInput(raw)
      this._markNum(badKey, v === null)
      if (v === null) return false
      obj[key] = v
      return true
    },
    // 聚焦中或標紅時保留使用者打的字，不被數值改寫；失焦（blur=true）才改回數值
    numShown(v, el, badKey, blur) {
      if (el && this.badNum[badKey]) return el.value
      if (!blur && el && document.activeElement === el) return el.value
      return v == null ? '' : v
    },
    onAmountTextChange(idx, kind, raw) {
      const item = this.paymentItems()[idx]
      if (!item) return
      const v = this.parseNumInput(raw)
      this._markNum(kind + '-' + item.id, v === null)
      if (v === null) return
      if (kind === 'wt') this.onAmountWithTaxChange(idx, v === '' ? 0 : v)
      else this.onAmountPretaxChange(idx, v === '' ? 0 : v)
    },

    // AC1：發票未稅／稅額（選填）。空＝沒填（null／''／undefined）；0 是有填（免稅的稅額就是 0）。
    _invoiceEmpty(v) { return v === null || v === undefined || v === '' },
    invoiceHalfFilled(item) {
      return this._invoiceEmpty(item.invoicePretax) !== this._invoiceEmpty(item.invoiceTax)
    },
    /** 兩欄都填而合計 ≠ 該期應收 ⇒ 回提示文字（只提示、不擋：發票可能與約定金額差 ±1）；否則 '' */
    invoiceMismatch(item, idx) {
      if (this._invoiceEmpty(item.invoicePretax) || this._invoiceEmpty(item.invoiceTax)) return ''
      const sum = (+item.invoicePretax || 0) + (+item.invoiceTax || 0)
      const due = Math.round(this.itemAmountReceivable(idx))
      return sum === due ? '' : '發票合計 NT$ ' + sum.toLocaleString() + ' 與這一期金額 NT$ '
        + due.toLocaleString() + ' 不同，請確認（不影響存檔）。'
    },

    totalWithTax()  { return this.selected?.total    || 0 },
    totalPretax()   { return this.selected?.pretax   || 0 },
    totalTax()      { return this.totalWithTax() - this.totalPretax() },

    totalEnteredPct() {
      return this.paymentItems().reduce((s, p) => s + (+p.pct || 0), 0)
    },

    itemAmountWithTax(idx) {
      const items = this.paymentItems()
      if (items[idx]?.amount != null) return items[idx].amount
      return Math.round(this.totalWithTax() * (+items[idx]?.pct || 0) / 100)
    },

    // 未稅原價：不受沖銷影響，永遠是該筆款項依報價單稅率換算的未稅基準
    itemAmountPretax(idx) {
      const items  = this.paymentItems()
      const total  = this.totalWithTax()
      const pretax = this.totalPretax()
      if (items[idx]?.amount != null && total > 0)
        return Math.round(items[idx].amount * pretax / total)
      return Math.round(pretax * (+items[idx]?.pct || 0) / 100)
    },

    itemAmountTax(idx) {
      if (this.paymentItems()[idx]?.taxExempt) return 0
      return this.itemAmountWithTax(idx) - this.itemAmountPretax(idx)
    },

    // 該筆款項實際應收／已收金額：已核准沖銷免稅 → 客戶只付未稅價，稅額不再收取
    itemAmountReceivable(idx) {
      const items = this.paymentItems()
      return items[idx]?.taxExempt ? this.itemAmountPretax(idx) : this.itemAmountWithTax(idx)
    },

    _setItemAmount(items, idx, withTax) {
      if (this.moneyMasked()) return
      // 規範值：直接存含稅整數，pct 作為百分比 input 顯示用
      const total = this.totalWithTax()
      items[idx].amount = Math.round(withTax)
      items[idx].pct    = total > 0 ? Math.round(withTax / total * 10000) / 100 : 0
    },

    _syncLast(items) {
      if (this.moneyMasked()) return
      // 讓最後一筆含稅 = 合約總額 − Σ其他，確保合計精確
      const total   = this.totalWithTax()
      const lastIdx = items.length - 1
      const othersAmount = items.reduce((s, p, i) => i === lastIdx ? s : s + (p.amount ?? Math.round(total * (+p.pct || 0) / 100)), 0)
      this._setItemAmount(items, lastIdx, Math.max(0, total - othersAmount))
    },

    onPctChange(idx) {
      if (this.moneyMasked()) return
      const items   = this.paymentItems()
      const total   = this.totalWithTax()
      const lastIdx = items.length - 1
      if (items.length > 1 && idx !== lastIdx) {
        // cap：非尾款項目的 pct 不超過 100 − 其他非尾款加總
        const othersExclLast = items.reduce((s, p, i) => (i === idx || i === lastIdx) ? s : s + (+p.pct || 0), 0)
        if ((+items[idx].pct || 0) > Math.max(0, 100 - othersExclLast))
          items[idx].pct = Math.max(0, 100 - othersExclLast)
        items[idx].amount = Math.round(total * (+items[idx].pct || 0) / 100)
        this._syncLast(items)
      } else {
        const othersSum = items.reduce((s, p, i) => i === idx ? s : s + (+p.pct || 0), 0)
        if ((+items[idx].pct || 0) > Math.max(0, 100 - othersSum))
          items[idx].pct = Math.max(0, 100 - othersSum)
        items[idx].amount = Math.round(total * (+items[idx].pct || 0) / 100)
      }
      this.setDirty()
    },

    onAmountWithTaxChange(idx, val) {
      if (this.moneyMasked()) return
      const total = this.totalWithTax()
      if (!total || !isFinite(val) || val < 0) return
      const items   = this.paymentItems()
      const lastIdx = items.length - 1
      // 計算本項能用的最大含稅（其他非尾款已佔的部分之外）
      const othersTaken = items.reduce((s, p, i) => (i === idx || i === lastIdx) ? s
        : s + (p.amount ?? Math.round(total * (+p.pct || 0) / 100)), 0)
      const capped = Math.min(Math.round(val), Math.max(0, total - othersTaken))
      this._setItemAmount(items, idx, capped)
      if (items.length > 1 && idx !== lastIdx) this._syncLast(items)
      this.setDirty()
    },

    onAmountPretaxChange(idx, val) {
      if (this.moneyMasked()) return
      const pretax = this.totalPretax()
      const total  = this.totalWithTax()
      if (!pretax || !isFinite(val) || val < 0) return
      // 未稅 → 換算含稅後，同 onAmountWithTaxChange 邏輯
      const withTax = Math.round(val * total / pretax)
      const items   = this.paymentItems()
      const lastIdx = items.length - 1
      const othersTaken = items.reduce((s, p, i) => (i === idx || i === lastIdx) ? s
        : s + (p.amount ?? Math.round(total * (+p.pct || 0) / 100)), 0)
      const capped = Math.min(withTax, Math.max(0, total - othersTaken))
      this._setItemAmount(items, idx, capped)
      if (items.length > 1 && idx !== lastIdx) this._syncLast(items)
      this.setDirty()
    },

    balanceLastPayment() {
      if (this.moneyMasked()) return
      const items = this.paymentItems()
      if (items.length < 2) return
      this._syncLast(items)
      this.setDirty()
    },

    receivedTotal() {
      return this.paymentItems().reduce((s, p, i) => p.received ? s + this.itemAmountReceivable(i) : s, 0)
    },
    receivedPct() {
      return this.paymentItems().reduce((s, p) => p.received ? s + (+p.pct || 0) : s, 0)
    },
    feeTotal() {
      return this.paymentItems().reduce((s, p) => p.received ? s + (+p.feeAmount || 0) : s, 0)
    },
    netReceivedTotal() {
      return this.paymentItems().reduce((s, p, i) => {
        if (!p.received) return s
        const base = p.actualAmount != null ? +p.actualAmount : this.itemAmountReceivable(i)
        return s + base - (+p.feeAmount || 0)
      }, 0)
    },
    outstandingTotal() {
      return Math.max(0, this.paymentItems().reduce((s, p, i) => p.received ? s : s + this.itemAmountReceivable(i), 0))
    },
    outstandingPct()   { return Math.max(0, 100 - this.receivedPct()) },

    addPaymentItem() {
      if (this.moneyMasked()) return
      const items = this.cr.caseRecord.payment.items
      items.push({ id: Date.now(), type: '進度款', pct: 0, received: false, receivedAt: '', expectedReceiptDate: '', invoiceNo: '', invoiceDate: '', note: '', actualAmount: null, feeAmount: 0, feeNote: '' })
      this.setDirty()
    },
    async removePaymentItem(idx) {
      if (this.moneyMasked()) return
      if (this.cr.caseRecord.payment.items.length <= 1) return
      const pi = this.cr.caseRecord.payment.items[idx]
      if (!(await MotrixUI.confirm(`確定要刪除款項期別「${pi?.type || '第' + (idx + 1) + '期'}」？\n\n刪除後會自動存檔，無法復原。`, {danger: true}))) return
      this.cr.caseRecord.payment.items.splice(idx, 1)
      if (this.cr.caseRecord.payment.items.length === 1) {
        this.cr.caseRecord.payment.items[0].pct = 100
      }
      this.setDirty()
    },

    // CU7：勾「已收款」的當下還沒填收款日期 ⇒ 把游標帶到日期欄並框紅（不自動填：收到錢是人的判斷）
    onReceivedToggled(item) {
      const need = !!(item.received && !item.receivedAt)
      this.needReceivedDate = { ...this.needReceivedDate, [item.id]: need }
      if (!need) return
      this.$nextTick(() => {
        const el = document.getElementById('pay-' + item.id + '-received-at')
        if (el) { el.focus(); el.scrollIntoView({ block: 'nearest' }) }
      })
    },

    openWriteoffModal(idx, mode) {
      this.writeoffModal = { open: true, idx, mode, reason: '', msg: '' }
    },

    // CM2（2026-09-24）：單筆端點帶項目 id，伺服器以 id 找列（idx 只是舊資料沒有 id 時的後備）
    _itemQs(item) {
      return item && item.id != null ? `?itemId=${encodeURIComponent(item.id)}` : ''
    },

    // 單筆操作前先把未存的改動存掉：剛新增、還沒存的那一列在伺服器上不存在（會被 409）
    async _flushBeforeItemOp() {
      if (!this.dirty) return true
      clearTimeout(this._autoSaveTimer)
      await this.saveCaseRecord()
      if (this.dirty) { MotrixUI.toast('請先存檔成功後再操作（' + (this.saveMsg || '尚未儲存') + '）', {kind: 'error'}); return false }
      return true
    },

    async _postWriteoff(idx, path, body) {
      const quoteNo = this.selected.quote_no
      if (!(await this._flushBeforeItemOp())) return { ok: false, msg: '尚未儲存' }
      const qs = this._itemQs(this.paymentItems()[idx])
      const r = await fetch(`/api/quotations/${quoteNo}/payment/${idx}/${path}${qs}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
        body: JSON.stringify(body || {})
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        return { ok: false, msg: err.detail || '操作失敗' }
      }
      const res = await r.json().catch(() => ({}))
      if (res.item) {
        const keys = ['writeOffStatus', 'writeOffReason', 'writeOffRequestedBy', 'writeOffRequestedAt',
          'writeOffApprovedBy', 'writeOffApprovedAt', 'writeOffRejectReason', 'taxExempt']
        this._applyToBoth('payment', cr => {
          const it = (cr.payment?.items || [])[idx]
          if (!it) return
          for (const k of keys) {
            if (res.item[k] === undefined) delete it[k]
            else it[k] = res.item[k]
          }
        })
      }
      return { ok: true, synced: !!res.item }
    },

    async submitWriteoffModal() {
      const { idx, mode, reason } = this.writeoffModal
      if (!reason.trim()) return
      const item = this.paymentItems()[idx]
      const me = this.session.displayName || this.session.username || ''
      let res
      if (mode === 'request') {
        res = await this._postWriteoff(idx, 'request-writeoff', { reason })
        if (res.ok && !res.synced) {
          item.writeOffStatus = 'pending'
          item.writeOffReason = reason
          item.writeOffRequestedBy = me
          item.writeOffRequestedAt = new Date().toISOString()
        }
      } else {
        res = await this._postWriteoff(idx, 'approve-writeoff', { approve: false, reject_reason: reason })
        if (res.ok && !res.synced) {
          item.writeOffStatus = 'rejected'
          item.writeOffRejectReason = reason
        }
      }
      if (res.ok) {
        this.writeoffModal.open = false
      } else {
        this.writeoffModal.msg = res.msg
      }
    },

    async cancelWriteoff(idx) {
      const item = this.paymentItems()[idx]
      const res = await this._postWriteoff(idx, 'cancel-writeoff')
      if (res.ok) {
        if (!res.synced) for (const k of ['writeOffStatus', 'writeOffReason', 'writeOffRequestedBy', 'writeOffRequestedAt']) delete item[k]
      } else {
        MotrixUI.toast(res.msg, {kind: 'info'})
      }
    },

    async approveWriteoff(idx) {
      const item = this.paymentItems()[idx]
      const me = this.session.displayName || this.session.username || ''
      const res = await this._postWriteoff(idx, 'approve-writeoff', { approve: true })
      if (res.ok && !res.synced) {
        item.writeOffStatus = 'approved'
        item.taxExempt = true
        item.writeOffApprovedBy = me
        item.writeOffApprovedAt = new Date().toISOString()
      } else if (!res.ok) {
        MotrixUI.toast(res.msg, {kind: 'info'})
      }
    },

    // ── 開票申請憑據 ────────────────────────────────────────────────────────────

    async loadInvoiceVouchers(quoteNo) {
      if (!quoteNo) return
      const live = this._selectLive()
      this.invoiceVouchersLoading = true
      this.invoiceVouchers = []
      this.ivSortPref = await loadListPref(this.session.token, `iv:${quoteNo}`)
      if (!live()) return
      try {
        const r = await fetch(`/api/invoice-vouchers?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? await r.json() : null
        if (!live()) return
        if (r.ok) this.invoiceVouchers = body
      } catch {}
      this.invoiceVouchersLoading = false
      this.$nextTick(() => this._initSubListSortable('iv'))
    },

    async openInvoiceVoucherModal() {
      if (this.dirty) { MotrixUI.toast('款項明細有未儲存的修改，請先儲存後再申請開票憑據', {kind: 'error'}); return }
      this.ivMode = 'amount'
      this.ivAmountInput = 0
      this.ivItemSelections = {}
      this.ivRemaining = null
      this.ivCreateModal = true
      this.ivRemainingLoading = true
      try {
        const r = await fetch(`/api/invoice-vouchers/remaining?quote_no=${encodeURIComponent(this.selected.quote_no)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.ivRemaining = await r.json()
        else { MotrixUI.toast((await r.json()).detail || '載入額度失敗', {kind: 'error'}); this.ivCreateModal = false }
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}); this.ivCreateModal = false }
      this.ivRemainingLoading = false
    },

    closeInvoiceVoucherModal() {
      this.ivCreateModal = false
    },

    ivToggleItem(it) {
      if (this.ivItemSelections[it.itemId]) {
        delete this.ivItemSelections[it.itemId]
      } else {
        const qty = it.remainingQty
        this.ivItemSelections[it.itemId] = { qty, amount: Math.round(qty * (it.unitPrice || 0)) }
      }
    },

    ivItemQtyChanged(it) {
      const sel = this.ivItemSelections[it.itemId]
      if (!sel) return
      if (sel.qty > it.remainingQty) sel.qty = it.remainingQty
      if (sel.qty < 0) sel.qty = 0
      sel.amount = Math.round(sel.qty * (it.unitPrice || 0))
    },

    // 按品項模式下，使用者輸入的金額比照報價單品項本身的慣例是「未稅」，
    // 跟「剩餘可申請金額」（含稅，來自 quoteTotal）不是同一個基準，比較前
    // 必須先用這張報價單自己的稅率（quoteTotal/quotePretax）換算成含稅。
    _ivTaxRatio() {
      const p = this.ivRemaining?.quotePretax || 0
      return p > 0 ? (this.ivRemaining.quoteTotal / p) : 1
    },

    ivAmountPretax() {
      const ratio = this._ivTaxRatio()
      return ratio > 0 ? Math.round((this.ivAmountInput || 0) / ratio) : (this.ivAmountInput || 0)
    },
    ivAmountTax() {
      return (this.ivAmountInput || 0) - this.ivAmountPretax()
    },

    ivSelectedTotal() {
      // 未稅小計（品項金額欄位本身的加總）
      return Object.values(this.ivItemSelections).reduce((sum, s) => sum + (Number(s.amount) || 0), 0)
    },
    ivSelectedGrossTotal() {
      // 含稅小計，才能跟剩餘可申請金額（含稅）比較
      return Math.round(this.ivSelectedTotal() * this._ivTaxRatio())
    },
    ivSelectedTax() {
      return this.ivSelectedGrossTotal() - this.ivSelectedTotal()
    },

    async submitInvoiceVoucherCreate() {
      if (!this.ivRemaining) return
      let body
      if (this.ivMode === 'amount') {
        if (!this.ivAmountInput || this.ivAmountInput <= 0) { MotrixUI.toast('請輸入申請金額', {kind: 'error'}); return }
        if (this.ivAmountInput > this.ivRemaining.remainingAmount) { MotrixUI.toast('超過剩餘可申請金額', {kind: 'error'}); return }
        body = { quote_no: this.selected.quote_no, scope: 'amount', amount: this.ivAmountInput }
      } else {
        const items = Object.entries(this.ivItemSelections).map(([itemId, sel]) => ({
          itemId: Number(itemId), qty: sel.qty, amount: sel.amount
        }))
        if (items.length === 0) { MotrixUI.toast('請至少選擇一項品項', {kind: 'info'}); return }
        if (this.ivSelectedGrossTotal() > this.ivRemaining.remainingAmount) { MotrixUI.toast('超過剩餘可申請金額', {kind: 'error'}); return }
        body = { quote_no: this.selected.quote_no, scope: 'items', items }
      }
      if (!(await MotrixUI.confirm('確定送出建立開票申請憑據？'))) return
      this.ivSubmitting = true
      try {
        const r = await fetch('/api/invoice-vouchers', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(body)
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '建立失敗', {kind: 'error'}); this.ivSubmitting = false; return }
        this.ivCreateModal = false
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
      this.ivSubmitting = false
    },

    async deleteInvoiceVoucher(v) {
      if (!(await MotrixUI.confirm(`確定刪除開票申請憑據「${v.voucherNo}」？`, {danger: true}))) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) await this.loadInvoiceVouchers(this.selected?.quote_no)
        else MotrixUI.toast((await r.json()).detail || '刪除失敗', {kind: 'error'})
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async submitInvoiceVoucher(v) {
      if (!(await MotrixUI.confirm(`確定送出開票申請憑據「${v.voucherNo}」進行簽核？`))) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/submit`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '送出失敗', {kind: 'error'}); return }
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async approveInvoiceVoucher(v) {
      // 同一人連任多層時一次簽完（2026-09-15，見 static/approval-cascade.js）。
      // 清單資料沒帶 approval.tiers 時算出來是空陣列，行為跟以前一樣。
      const _appr = v.approval || {}
      const _casc = window.MotrixApproval.selfCascadeTiers(
        _appr.tiers || [], _appr.currentTier ?? 0, this.session.username, [])
      if (!(await MotrixUI.confirm(`確定簽核開票申請憑據「${v.voucherNo}」？` + window.MotrixApproval.cascadeNote(_casc)))) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ cascade: _casc.length > 0 })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '簽核失敗', {kind: 'error'}); return }
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async rejectInvoiceVoucher(v) {
      const note = (await MotrixUI.prompt(`退回開票申請憑據「${v.voucherNo}」，可填寫退回原因（選填）：`))
      if (note === null) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/reject`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '退回失敗', {kind: 'error'}); return }
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async revokeInvoiceVoucherApproval(v) {
      const note = (await MotrixUI.prompt(`撤銷開票申請憑據「${v.voucherNo}」的核准？將退回草稿。\n\n可填寫撤銷原因（選填）：`))
      if (note === null) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/revoke-approval`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '撤銷失敗', {kind: 'error'}); return }
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async downloadInvoiceVoucherPdf(v) {
      try {
        fetch(`/api/invoice-vouchers/${v.voucherNo}/export?mode=external`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        }).catch(() => {})
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗', {kind: 'error'}); return }
        const blob = await r.blob()
        const url  = URL.createObjectURL(blob)
        const a    = document.createElement('a')
        a.href     = url
        a.download = `${v.voucherNo}.pdf`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      } catch (e) { MotrixUI.toast('下載失敗：' + e.message, {kind: 'error'}) }
    },

    async previewInvoiceVoucherPdf(v) {
      this.ivPreviewFetching = true
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗', {kind: 'error'}); this.ivPreviewFetching = false; return }
        const blob = await r.blob()
        this.ivPreviewBlobUrl = URL.createObjectURL(blob)
        this.ivPreviewVoucher = v
        this.ivPreviewModal = true
      } catch (e) { MotrixUI.toast('預覽失敗：' + e.message, {kind: 'error'}) }
      this.ivPreviewFetching = false
    },

    closeInvoiceVoucherPreview() {
      if (this.ivPreviewBlobUrl) URL.revokeObjectURL(this.ivPreviewBlobUrl)
      this.ivPreviewBlobUrl = ''
      this.ivPreviewModal = false
      this.ivPreviewVoucher = null
    },

    _ivStatusLabel(s) {
      return { '草稿': '草稿', '待審核': '待審核', '簽核中': '簽核中', '已核准': '已核准' }[s] || s
    },

    _ivStatusClass(s) {
      return { '草稿': 'badge--draft', '待審核': 'badge--pending', '簽核中': 'badge--signing', '已核准': 'badge--approved' }[s] || ''
    },

    async uploadInvoiceVoucherIssuedFiles(v, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/issued-files`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '上傳失敗', {kind: 'error'}); return }
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('上傳失敗：' + e.message, {kind: 'error'}) }
      evt.target.value = ''
    },

    async uploadPaymentItemInvoiceFiles(idx, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      if (!(await this._flushBeforeItemOp())) { evt.target.value = ''; return }
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/payment/${idx}/invoice-files${this._itemQs(this.paymentItems()[idx])}`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '上傳失敗', {kind: 'error'}); return }
        const body = await r.json()
        if (body.pending) { MotrixUI.toast(body.message || '已送出，待最高管理員審核後套用', {kind: 'ok'}); return }
        this._applyToBoth('payment', cr => {
          const item = (cr.payment?.items || [])[idx]
          if (item) {
            if (!item.invoiceFiles) item.invoiceFiles = []
            item.invoiceFiles.push(...body.files)
          }
        })
      } catch (e) { MotrixUI.toast('上傳失敗：' + e.message, {kind: 'error'}) }
      evt.target.value = ''
    },

    async deletePaymentItemInvoiceFile(idx, fileId) {
      if (!(await MotrixUI.confirm('確定刪除此附件？', {danger: true}))) return
      if (!(await this._flushBeforeItemOp())) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/payment/${idx}/invoice-files/${fileId}${this._itemQs(this.paymentItems()[idx])}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '刪除失敗', {kind: 'error'}); return }
        const body = await r.json()
        if (body.pending) { MotrixUI.toast(body.message || '已送出，待最高管理員審核後套用', {kind: 'ok'}); return }
        this._applyToBoth('payment', cr => {
          const item = (cr.payment?.items || [])[idx]
          if (item && item.invoiceFiles) item.invoiceFiles = item.invoiceFiles.filter(f => f.id !== fileId)
        })
      } catch (e) { MotrixUI.toast('刪除失敗：' + e.message, {kind: 'error'}) }
    },

    async deleteInvoiceVoucherIssuedFile(v, fileId) {
      if (!(await MotrixUI.confirm('確定刪除此附件？', {danger: true}))) return
      try {
        const r = await fetch(`/api/invoice-vouchers/${v.voucherNo}/issued-files/${fileId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '刪除失敗', {kind: 'error'}); return }
        await this.loadInvoiceVouchers(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('刪除失敗：' + e.message, {kind: 'error'}) }
    },

    // ── 請款單 ──────────────────────────────────────────────────────────────
    async loadPaymentRequests(quoteNo) {
      if (!quoteNo) return
      const live = this._selectLive()
      this.paymentRequestsLoading = true
      this.paymentRequests = []
      this.prListSortPref = await loadListPref(this.session.token, `prList:${quoteNo}`)
      if (!live()) return
      try {
        const r = await fetch(`/api/payment-requests?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? await r.json() : null
        if (!live()) return
        if (r.ok) this.paymentRequests = body
      } catch {}
      this.paymentRequestsLoading = false
      this.$nextTick(() => this._initSubListSortable('prList'))
    },

    _prStatusLabel(s) {
      return { '草稿': '草稿', '待審核': '待審核', '簽核中': '簽核中', '已核准': '已核准' }[s] || s
    },

    _prStatusClass(s) {
      return { '草稿': 'badge--draft', '待審核': 'badge--pending', '簽核中': 'badge--signing', '已核准': 'badge--approved' }[s] || ''
    },

    // CM12 P2：切換案件時重設本模組的案件層級狀態（時點見 core 的 _resetCaseScoped）
    _reset_fin(phase, data) {
      if (phase === 'early') {
        this.invoiceVouchers = []
        this.paymentRequests = []
        this.financeSummary = null
        this.financeSummaryLoading = true
        this.invoiceVouchersLoading = true
        this.paymentRequestsLoading = true
      }
      if (phase === 'late') {
        this.closeInvoiceVoucherPreview()
        this.finShowRecvDetail = false
        this.finShowPayDetail = false
      }
    },
}))
