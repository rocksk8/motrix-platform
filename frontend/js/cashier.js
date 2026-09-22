/* global Alpine */
// 出納（`UI9`，2026-09-23）：從 `reports.html` 的「出納」頁籤**拆回獨立頁面**。
//
// ## 🔴 這份碼是從**現在的** `reports.js` 抽出來的，不是從 git 還原舊版
//
// 2026-08-31 出納併進營運報表時，原本的 `cashier.html`（457 行）退役成
// 一個 1,198 bytes 的轉址存根。而**舊版與現在的面板不一樣**：
// ```
// 舊 cashier.html        457 行
// 併入後的出納面板        270 行
// 而那 270 行從併入到現在  **一個字都沒變**（差異 0 行）
// ```
// ⇒ 還原舊版會把 2026-08-31 之後的東西倒回去；從現在的檔抽**不會遺失任何修正**。
//
// ## ⚠️ 這裡有四份是**刻意複製**的，不是忘了抽共用
//
// `fmt()`／`_token()`／`_role()`／`_modules()`／`isAdminPlus()`／
// `_localDateStr()`／`t100BankAccounts` 的載入 —— 抽共用會讓這一次的 diff
// 同時涵蓋「拆頁」與「跨四檔重構」，而那兩件事出問題時要分開查。
// 📌 A 已就 `t100BankAccounts` 發 `FE1` 排 `NEXT` —— **是一筆有號碼的欠帳，
//    不是假裝沒看到**。
//
// ## 🔴 應收／應付只能來自出納佇列那兩個端點
//
// `reports.js` 的註解記著這個 bug 發生過：
// > 「一開始應收接的是 `activeOutstandingTotal` —— 那是應收報表的期別範圍
// >   數字，跟出納的應收帳款是兩回事，畫面上會變成**快照說 0、上方 KPI 卡
// >   說一百多萬**。」
// ⇒ 這一頁與 `reports.html` 的「資金水位」**必須讀同一組端點**。

function cashierApp() {
  return {
    // ── 頁面狀態 ───────────────────────────────────────────
    ready: false,
    error: '',

    // ── 出納（2026-08-31 併入營運報表，原獨立的 cashier.html/cashier.js 頁面
    // 退役成頁內「出納」頁籤，內容/邏輯完全比照原本，只有跟本檔案既有狀態
    // 衝突的名稱做了改名，見下方各區塊註解）────────────────────────────────────
    cashierSub:    'payable',   // payable/receivable/history/bank，出納頁籤內部子頁籤
    cashierLoaded: false,       // 出納頁籤第一次打開時 payable+receivable+history 一次性彙整載入 guard

    payable:    [],
    receivable: [],   // status=all，含已收+未收全部歷史（併入 receivables.html 用途）

    receivableSearch:    '',
    receivableFilterTab: 'unreceived',   // all / unreceived / received / uninvoiced

    payVoucherModal:   false,
    payVoucherTarget:  null,
    payVoucherDate:    '',
    payVoucherNote:    '',
    payVoucherBankAcctCode: '',
    payVoucherSaving:  false,

    receiveModal:         false,
    receiveTarget:        null,
    receiveDate:          '',
    receiveActualAmount:  null,
    receiveFeeAmount:     0,
    receiveNote:          '',
    receiveBankAcctCode:  '',
    receiveSaving:        false,
    // T100 傳票匯出設定裡的銀行帳戶清單（2026-09-01 新增），標記已收款/已匯款
    // 時挑選要用哪個帳戶；每次開啟標記 Modal 都重抓最新清單，見
    // loadT100BankAccounts()
    t100BankAccounts:     [],
    t100DefaultBankAcctCode: '',   // 2026-09-02 新增：系統預設銀行帳戶，見 _resolveDefaultBankAccount()

    invoiceModal: { show: false, item: null, no: '' },

    // 原 cashier.js 的 historyStart/historyEnd/... 改加 cashier 前綴，避免在
    // 這支已經很大的共用檔案裡跟「執行歷史」以外的概念混淆
    cashierHistoryStart:        '',
    cashierHistoryEnd:          '',
    cashierHistoryLoading:      false,
    cashierHistoryOutgoing:     [],
    cashierHistoryIncoming:     [],
    cashierHistoryOutgoingTotal: 0,
    cashierHistoryIncomingTotal: 0,
    // 原 cashier.js 叫 exporting，這裡本來就有同名的「exporting」給財務報表
    // 匯出用（見 exportFile()），改名避免互踩
    cashierExporting: false,

    bankReconciling: false,
    bankResult:      null,
    bankPayModal:    false,
    bankPayRow:      null,
    bankPayDate:     '',
    bankPaySaving:   false,

    fmt(n) {
      return 'NT$ ' + (Math.round(n || 0)).toLocaleString()
    },
    _token() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.token || ''
    },
    _role() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.role || ''
    },
    _modules() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.modules || []
    },
    isAdminPlus() {
      var r = this._role()
      return r === 'admin' || r === 'superadmin'
    },
    hasCashierAccess() {
      return this.isAdminPlus() || this._modules().includes('cashier') || this._modules().includes('finance')
    },
    canExecuteCashier() {
      return this.isAdminPlus() || this._modules().includes('cashier')
    },
    _localDateStr(d) {
      d = d || new Date()
      const tz = d.getTimezoneOffset() * 60000
      return new Date(d.getTime() - tz).toISOString().slice(0, 10)
    },
    // ── 出納頁籤（2026-08-31 併入本頁，原 frontend/js/cashier.js 內容原封不動
    // 搬過來，只改了跟本檔案既有狀態衝突的名稱，見上方 state 區塊註解）────────

    get kpiPayableTotal() {
      return this.payable.reduce((s, v) => s + (v.grandTotal || 0), 0)
    },
    get kpiPayableOverdue() {
      return this.payable.filter(v => this.isOverdue(v.payableDate)).length
    },
    get kpiReceivableTotal() {
      return this.receivable.filter(i => !i.received).reduce((s, i) => s + (i.amount || 0), 0)
    },
    get kpiReceivableOverdue() {
      return this.receivable.filter(i => i.overdue).length
    },
    get filteredReceivable() {
      let list = this.receivable
      if (this.receivableFilterTab === 'unreceived') list = list.filter(i => !i.received)
      if (this.receivableFilterTab === 'received')   list = list.filter(i => i.received)
      if (this.receivableFilterTab === 'uninvoiced') list = list.filter(i => !i.invoiceNo)
      const q = this.receivableSearch.trim().toLowerCase()
      if (q) list = list.filter(i =>
        (i.quoteNo || '').toLowerCase().includes(q) ||
        (i.customer || '').toLowerCase().includes(q) ||
        (i.type || '').toLowerCase().includes(q) ||
        (i.invoiceNo || '').toLowerCase().includes(q)
      )
      return list
    },
    get receivableUninvoicedCount() {
      return this.receivable.filter(i => !i.invoiceNo).length
    },

    isOverdue(dateStr) {
      return !!dateStr && dateStr < this._localDateStr()
    },
    isDueSoon(dateStr) {
      if (!dateStr || this.isOverdue(dateStr)) return false
      const soon = new Date()
      soon.setDate(soon.getDate() + 7)
      return dateStr <= this._localDateStr(soon)
    },

    async showCashierTab() {
      this.activeTab = 'cashier'
      if (this.cashierLoaded) return
      const today = new Date()
      this.cashierHistoryStart = this._localDateStr(new Date(today.getFullYear(), today.getMonth(), 1))
      this.cashierHistoryEnd = this._localDateStr(today)
      await Promise.all([this.loadPayable(), this.loadReceivable(), this.loadCashierHistory()])
      this.cashierLoaded = true
    },

    async loadPayable() {
      try {
        const r = await fetch('/api/cashier/payable-queue', { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) this.payable = await r.json()
        else if (r.status === 403) this.error = '僅管理員、出納或財務可存取出納功能'
      } catch (e) { console.error(e) }
    },

    async loadReceivable() {
      try {
        const r = await fetch('/api/cashier/receivable-queue?status=all', { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) this.receivable = await r.json()
        else if (r.status === 403) this.error = '僅管理員、出納或財務可存取出納功能'
      } catch (e) { console.error(e) }
    },

    async loadCashierHistory() {
      this.cashierHistoryLoading = true
      try {
        const qs = `?start=${this.cashierHistoryStart}&end=${this.cashierHistoryEnd}`
        const r = await fetch('/api/cashier/execution-history' + qs, { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) {
          const d = await r.json()
          this.cashierHistoryOutgoing = d.outgoing || []
          this.cashierHistoryIncoming = d.incoming || []
          this.cashierHistoryOutgoingTotal = d.outgoingTotal || 0
          this.cashierHistoryIncomingTotal = d.incomingTotal || 0
        }
      } catch (e) { console.error(e) }
      this.cashierHistoryLoading = false
    },

    async exportCashierHistory() {
      this.cashierExporting = true
      try {
        const qs = `?start=${this.cashierHistoryStart}&end=${this.cashierHistoryEnd}`
        const r = await fetch('/api/cashier/export' + qs, { headers: { Authorization: 'Bearer ' + this._token() } })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '匯出失敗'); this.cashierExporting = false; return }
        const blob = await r.blob()
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = `MOTRIX_出納執行紀錄_${this.cashierHistoryStart}_${this.cashierHistoryEnd}.xlsx`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(a.href)
      } catch (e) { alert('匯出失敗：' + e.message) }
      this.cashierExporting = false
    },

    async loadT100BankAccounts() {
      // 2026-09-02：改成每次開啟標記 Modal 都重抓（不再 cache-once），確保跟
      // 案件管理／庫存管理三處標記畫面共用同一份最新清單，見
      // case-management.js::loadT100BankAccounts() 同款註解。
      try {
        const r = await fetch('/api/settings/t100-export-config', { headers: { Authorization: 'Bearer ' + this._token() } })
        if (r.ok) {
          const d = await r.json()
          this.t100BankAccounts = d.bankAccounts || []
          this.t100DefaultBankAcctCode = d.defaultBankAccountCode || ''
        }
      } catch {}
    },

    _t100BankName(code) {
      return (this.t100BankAccounts.find(b => b.acctCode === code) || {}).name || ''
    },

    // 銀行帳戶預設值（2026-09-02 新增）：①這個對象上次標記用的帳戶 ②系統
    // 預設帳戶 ③兩者都沒有就空白。lastUsedUrl 由呼叫端組好（各自對象不同）。
    async _resolveDefaultBankAccount(lastUsedUrl) {
      if (lastUsedUrl) {
        try {
          const r = await fetch(lastUsedUrl, { headers: { Authorization: 'Bearer ' + this._token() } })
          if (r.ok) {
            const d = await r.json()
            if (d.acctCode) return d.acctCode
          }
        } catch {}
      }
      return this.t100DefaultBankAcctCode || ''
    },

    async openPayVoucherModal(v) {
      this.payVoucherTarget = v
      this.payVoucherBankAcctCode = ''
      this.payVoucherDate = v.payableDate || this._localDateStr()
      this.payVoucherNote = ''
      this.payVoucherModal = true
      await this.loadT100BankAccounts()
      const url = v.vendorId ? `/api/contractor-vouchers/last-paid-bank-account?vendor_id=${v.vendorId}` : ''
      this.payVoucherBankAcctCode = await this._resolveDefaultBankAccount(url)
    },

    async confirmPayVoucher() {
      const v = this.payVoucherTarget
      if (!v || !this.payVoucherDate) return
      this.payVoucherSaving = true
      try {
        const r = await fetch(`/api/contractor-vouchers/${v.voucherNo}/paid-toggle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({
            action: 'pay', paid_at: this.payVoucherDate, note: this.payVoucherNote,
            bankAccountCode: this.payVoucherBankAcctCode, bankAccountName: this._t100BankName(this.payVoucherBankAcctCode),
          })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); this.payVoucherSaving = false; return }
        this.payVoucherModal = false
        this.payVoucherTarget = null
        await Promise.all([this.loadPayable(), this.loadCashierHistory()])
      } catch (e) { alert('標記已匯款失敗：' + e.message) }
      this.payVoucherSaving = false
    },

    async openReceiveModal(it) {
      this.receiveTarget = it
      this.receiveDate = this._localDateStr()
      this.receiveActualAmount = it.amount
      this.receiveFeeAmount = 0
      this.receiveNote = ''
      this.receiveBankAcctCode = ''
      this.receiveModal = true
      await this.loadT100BankAccounts()
      const url = it.customer ? `/api/quotations/last-received-bank-account?customerName=${encodeURIComponent(it.customer)}` : ''
      this.receiveBankAcctCode = await this._resolveDefaultBankAccount(url)
    },

    async confirmReceive() {
      const it = this.receiveTarget
      if (!it || !this.receiveDate) return
      this.receiveSaving = true
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(it.quoteNo)}/payment/${it.idx}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({
            received: true, receivedAt: this.receiveDate, receivedBy: this._displayName(),
            actualAmount: this.receiveActualAmount, feeAmount: this.receiveFeeAmount || 0, note: this.receiveNote,
            bankAccountCode: this.receiveBankAcctCode, bankAccountName: this._t100BankName(this.receiveBankAcctCode),
          })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); this.receiveSaving = false; return }
        this.receiveModal = false
        this.receiveTarget = null
        await Promise.all([this.loadReceivable(), this.loadCashierHistory()])
      } catch (e) { alert('標記已收款失敗：' + e.message) }
      this.receiveSaving = false
    },

    async toggleReceived(item, received) {
      if (!confirm(received ? '標記此款項為已收？' : '取消此款項的收款紀錄？')) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(item.quoteNo)}/payment/${item.idx}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ received, receivedAt: '', receivedBy: '' })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); return }
        await this.loadReceivable()
      } catch (e) { alert('更新收款狀態失敗：' + e.message) }
    },

    openInvoiceModal(item) {
      this.invoiceModal = { show: true, item, no: item.invoiceNo || '', date: item.invoiceDate || '' }
    },

    async confirmInvoice() {
      const item = this.invoiceModal.item
      if (!item) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(item.quoteNo)}/payment/${item.idx}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ invoiceNo: this.invoiceModal.no.trim(), invoiceDate: this.invoiceModal.date || '' })
        })
        if (!r.ok) { alert((await r.json().catch(() => ({}))).detail || '操作失敗'); return }
        item.invoiceNo = this.invoiceModal.no.trim()
        item.invoiceDate = this.invoiceModal.date || ''
        this.invoiceModal.show = false
      } catch (e) { alert('登錄發票號碼失敗：' + e.message) }
    },

    async uploadBankCsv(evt) {
      var file = evt.target.files[0]
      if (!file) return
      this.bankReconciling = true
      this.bankResult = null
      try {
        var fd = new FormData()
        fd.append('file', file)
        var res = await fetch('/api/reports/bank-reconcile', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this._token() },
          body: fd,
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '比對失敗')
        }
        this.bankResult = await res.json()
      } catch (e) {
        alert('銀行對帳比對失敗：' + (e.message || e))
      } finally {
        this.bankReconciling = false
        evt.target.value = ''
      }
    },

    _guessDateFromBankText(raw) {
      const s = (raw || '').trim()
      if (!s) return ''
      let m = s.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/)
      if (m) return this._normalizeYmd(+m[1], +m[2], +m[3])
      m = s.match(/^(\d{4})(\d{2})(\d{2})(\d{0,6})?$/)
      if (m) return this._normalizeYmd(+m[1], +m[2], +m[3])
      // 民國年（台灣銀行常見，例如 115/08/20 = 2026/08/20）
      m = s.match(/^(\d{2,3})[-/.](\d{1,2})[-/.](\d{1,2})$/)
      if (m && +m[1] >= 1 && +m[1] <= 200) return this._normalizeYmd(+m[1] + 1911, +m[2], +m[3])
      return ''
    },

    _normalizeYmd(y, mo, d) {
      if (mo < 1 || mo > 12 || d < 1 || d > 31) return ''
      const dt = new Date(y, mo - 1, d)
      if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return ''
      return y + '-' + String(mo).padStart(2, '0') + '-' + String(d).padStart(2, '0')
    },

    openBankPayModal(row) {
      if (!row || !row.match) return
      this.bankPayRow = row
      this.bankPayDate = this._guessDateFromBankText(row.date) || this._localDateStr()
      this.bankPayModal = true
    },

    async confirmBankPay() {
      const row = this.bankPayRow
      if (!row || !row.match || !this.bankPayDate) return
      const voucherNo = row.match.voucherNo
      this.bankPaySaving = true
      try {
        var res = await fetch('/api/contractor-vouchers/' + voucherNo + '/paid-toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ action: 'pay', paid_at: this.bankPayDate, note: '銀行對帳單比對後標記' }),
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '標記失敗')
        }
        row.match._paid = true
        this.bankPayModal = false
        this.bankPayRow = null
        await Promise.all([this.loadPayable(), this.loadCashierHistory()])
      } catch (e) {
        alert('標記失敗：' + (e.message || e))
      }
      this.bankPaySaving = false
    },


    // ── T100（鼎新）傳票批次匯出 ──────────────────────────────────────────────
    async loadT100Config() {
      if (this.t100ConfigLoaded) return
      try {
        var res = await fetch('/api/settings/t100-export-config', {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (res.ok) {
          this.t100Config = await res.json()
          this.t100ConfigLoaded = true
        }
      } catch (e) { /* 靜默失敗，畫面仍可用預設空白值操作 */ }
    },

    toggleT100Config() {
      this.t100ConfigOpen = !this.t100ConfigOpen
      if (this.t100ConfigOpen) this.loadT100Config()
    },

    async saveT100Config() {
      if (this._role() !== 'superadmin') return
      this.t100ConfigSaving = true
      try {
        var res = await fetch('/api/settings/t100-export-config', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify(this.t100Config),
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '儲存失敗')
        }
        alert('已儲存 T100 科目代號設定')
      } catch (e) {
        alert('儲存失敗：' + (e.message || e))
      } finally {
        this.t100ConfigSaving = false
      }
    },

    async exportT100Vouchers() {
      if (!this.t100Start || !this.t100End || this.t100Start > this.t100End) {
        alert('請確認起訖日期區間正確')
        return
      }
      this.t100Exporting = true
      try {
        var qs = 'start=' + this.t100Start + '&end=' + this.t100End
        var res = await fetch('/api/reports/t100-export/vouchers?' + qs, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '匯出失敗')
        }
        var blob = await res.blob()
        var a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = 'MOTRIX_T100傳票匯出_' + this.t100Start + '_' + this.t100End + '.xlsx'
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(a.href)
      } catch (e) {
        alert('T100 傳票匯出失敗：' + (e.message || e))
      } finally {
        this.t100Exporting = false
      }
    },

    async loadT100Preview() {
      if (!this.t100Start || !this.t100End || this.t100Start > this.t100End) {
        alert('請確認起訖日期區間正確')
        return
      }
      this.t100Previewing = true
      try {
        var qs = 'start=' + this.t100Start + '&end=' + this.t100End
        var res = await fetch('/api/reports/t100-export/preview?' + qs, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '預覽失敗')
        }
        this.t100Preview = await res.json()
      } catch (e) {
        alert('T100 預覽失敗：' + (e.message || e))
      } finally {
        this.t100Previewing = false
      }
    },

    // 財務人員實際到 T100 匯入後，回來按這顆按鈕標記整批已匯入——標記後這些
    // 事件會從之後所有匯出/預覽自動排除，避免重複匯入
    async confirmT100Imported() {
      if (!this.t100Preview || !this.t100Preview.count) {
        alert('目前沒有可確認的事件，請先預覽')
        return
      }
      if (!confirm('確認這 ' + this.t100Preview.count + ' 筆事件已經實際匯入 T100？確認後將自動從之後的匯出/預覽排除，避免重複匯入。')) return
      this.t100Confirming = true
      try {
        var res = await fetch('/api/reports/t100-export/confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ start: this.t100Start, end: this.t100End }),
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '確認失敗')
        }
        var result = await res.json()
        alert('已標記 ' + result.confirmedCount + ' 筆事件為已匯入')
        this.loadT100Preview()
        this.loadT100Confirmed()
      } catch (e) {
        alert('確認已匯入失敗：' + (e.message || e))
      } finally {
        this.t100Confirming = false
      }
    },
    // 🔴 `UI9` 第三次補件：這兩支是 **JS 內部呼叫**的，而我前兩次的掃描
    //    都掃不到它們 ——
    // ```
    // ① 樣板 → JS    @click 的 handler 在不在      （這兩支樣板沒用到）
    // ② JS → 樣板    狀態有沒有對應的 UI            （這兩支不需要 UI）
    // ③ **JS → JS**  this.x() 呼叫的在不在同一個檔  ← **漏掉的是這個方向**
    // ```
    // ☠️ 使用者實際踩到的是 `_displayName`：按「標記已收款」的確定會丟
    //    `TypeError`，而 `confirmReceive` 的 catch 把它印成「**網路錯誤**」
    //    ⇒ 前半句是假的、後半句是真的，**而人會先讀前半句**。
    _displayName() {
      var s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
      return s.displayName || s.username || ''
    },
    async loadT100Confirmed() {
      this.t100ConfirmedLoading = true
      try {
        var qs = '?start=' + this.t100Start + '&end=' + this.t100End
        var res = await fetch('/api/reports/t100-export/confirmed' + qs, {
          headers: { Authorization: 'Bearer ' + this._token() }
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '載入失敗')
        }
        this.t100Confirmed = await res.json()
      } catch (e) {
        alert('已確認清單載入失敗：' + (e.message || e))
      } finally {
        this.t100ConfirmedLoading = false
      }
    },

    // ── T100（鼎新）傳票批次匯出（`FN3`，2026-09-23 從營運報表搬過來）──
    //
    // 🔑 **這不是搬家，是團圓**：T100 的流程本來就跨在兩邊 ——
    //    出納那一半（標記已收／已付）隨著 `UI9` 已經搬過來了，
    //    而匯出這一半還留在報表頁。
    // 📌 而它在概念上屬於這裡：`accounting_export.py:8` 逐字寫著
    //    「設計採**現金基礎**：只匯出『錢真的有進出』的事件」
    //    ⇒ **現金基礎就是出納的領域。**
    t100Start:        new Date(new Date().getFullYear(), new Date().getMonth(), 1).toISOString().slice(0, 10),
    t100End:          new Date().toISOString().slice(0, 10),
    t100Exporting:    false,
    t100ConfigOpen:   false,
    t100Config:       null,
    t100ConfigLoaded: false,
    t100ConfigSaving: false,
    t100Preview:      null,   // {count, totalAmount, events:[...]}，未確認事件預覽
    t100Previewing:   false,
    t100Confirming:   false,
    t100Confirmed:        [],
    t100ConfirmedLoading: false,
    t100ConfirmedOpen:    false,
    t100Unconfirming:     '',   // 正在反確認的 sourceType:sourceKey

    get t100ConfigComplete() {
      const c = this.t100Config
      if (!c) return false
      const coreFilled = c.salesRevenueAccount && c.outputTaxAccount && c.contractorExpenseAccount
      const hasBank = c.bankAccounts && c.bankAccounts.length > 0 && c.bankAccounts.every(b => b.name && b.acctCode)
      return !!(coreFilled && hasBank)
    },

    async unconfirmT100(row) {
      if (!confirm('撤銷這筆的「已匯入 T100」標記？\n\n' + row.date + '　' + row.summary +
                   '\n\n撤銷後它會在下次涵蓋這個日期的匯出／預覽重新出現，' +
                   '如果 T100 那邊其實已經匯入過，會造成重複匯入。')) return
      this.t100Unconfirming = row.sourceType + ':' + row.sourceKey
      try {
        var res = await fetch('/api/reports/t100-export/unconfirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() },
          body: JSON.stringify({ sourceType: row.sourceType, sourceKey: row.sourceKey }),
        })
        if (!res.ok) {
          var j = await res.json().catch(function () { return {} })
          throw new Error(j.detail || '撤銷失敗')
        }
        await this.loadT100Confirmed()
        this.loadT100Preview()
      } catch (e) {
        alert('撤銷已匯入標記失敗：' + (e.message || e))
      } finally {
        this.t100Unconfirming = ''
      }
    },

    // 🔑 原本是 `showT100Tab()`（報表頁的頁籤）。這裡改成出納的**子頁籤**，
    //    而**載入邏輯一行沒改** —— 只是換了觸發它的那個狀態。
    // ⚠️ 三個 `if` 是懶載：切進來才抓，而切回去再切回來不會重抓。
    async showT100Sub() {
      this.cashierSub = 't100'
      if (!this.t100Preview) this.loadT100Preview()
      if (!this.t100Config) this.loadT100Config()
      if (!this.t100Confirmed.length) this.loadT100Confirmed()
    },

    // ── 進入點 ─────────────────────────────────────────────
    // 🔑 原本是 `showCashierTab()`（切到頁籤時才載）。獨立頁之後**進來就載**，
    //    而那個函式的內容一行都沒改 —— 只是換了一個呼叫的時機。
    // ⚠️ 權限擋在這裡：`canExecuteCashier()` 是「能不能執行付款/收款」，
    //    而能不能**看**這一頁是 `hasCashierAccess()`（含 finance）。
    //    兩者刻意不同，照抄 `reports.js` 的那條界線。
    async init() {
      if (!this.hasCashierAccess()) {
        this.error = '沒有出納模組的權限'
        this.ready = true
        return
      }
      await this.showCashierTab()
      this.ready = true
    },
  }
}
