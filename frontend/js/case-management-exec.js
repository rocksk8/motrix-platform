// case-management-exec.js — 案件管理頁：執行管理分頁：階段、時間軸、拜訪、材料申請、設備、保固、待辦、成員
// CM12 P1（2026-09-24）：由 case-management.js 原樣搬出，成員文字未改；組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({
    dragFromIdx: null,
    _openStageDetail: {},
    _newStageAssignee: {},
    stageView: 'list',
    _ganttInstance: null,
    showImportModal: false,
    importMode: 'materials',
    importSelectedItems: {},
    showLog: false,
    _syncWarrantyDate: '',
    _syncWarrantyMonths: 12,
    _openDevGroups: {},
    _devDragId: null,        // device.id being dragged
    _devDragOverId: null,    // current hover target string ('dev_X' | 'group_X')
    _devInsertBeforeId: null,// where to show insert line ('dev_X' | 'end' | null)
    _devHoverGroupId: null,  // group ID when hovering group header → add-to-group mode
    _devHoverStart: 0,       // timestamp when we entered _devDragOverId
    _devGroupTarget: null,   // 'dev_X' confirmed for grouping after 900ms hover

    // ── 待辦事項（2026-08-26 專案管理併入案件管理）──
    caseActionItems: [],
    caseActionItemsLoading: false,
    newActionItemText: '',
    addingActionItem: false,

    // ── 專案資訊（成員分配）──
    assignedUserIds: [],
    assignedUsersSaving: false,

    // ── 材料申請（材料訂購，前端 2026-09-11 補上）──
    // 後端端點 2026-09-10 就上線，但一直沒有任何呼叫點，見
    // routers/material_orders.py 檔頭與 WEEKLY-AUDIT §E-1。
    // 存檔刻意走專屬端點而不是併進 saveCase()：saveCase() 會覆蓋整份
    // data_json，兩邊同時存會互相蓋掉；且材料申請的權限與已結案規則由後端
    // 那支端點自己守，跟案件整包存檔不一樣。
    materialOrders: [],
    // 預設 true：面板只在 !moLoading 時才渲染「尚無材料申請項目」，一旦預設 false，
    // 任何「還沒開始載入」的瞬間都會對使用者說「沒有資料」——那是還沒查就先
    // 回答。額外支出的 xe.loading 本來就是 true，這裡跟它對齊。
    moLoading: true,
    moSaving: false,
    moDirty: false,
    moMsg: '',
    moMsgError: false,
    // 材料申請審核（31-C）：itemId → 審核摘要 {status, legacy, docCode, currentApprovers, rejectReason, receivedOn, receivedBy…}
    moApprovals: {},
    moBusy: '',
    // 材料申請匯款申請（31-C）：itemId → {quota:{total,legacyPaid,committed,remaining}, payments:[…]}；供應商選單；開單表單（一次只開一張）
    moPay: {},
    moSuppliers: [],
    moPayForm: null,

    // ── 材料申請────────────────────────────────────────────────────
    async loadMaterialOrders(quoteNo) {
      if (!quoteNo) return
      const live = this._selectLive()
      // 發出請求的當下就記住是哪張單，回應抵達時再比對一次——比照 reports.js
      // 的 loadExpenses()／loadReceivables() 競態修法（§12 2026-09-10「更晚」）。
      // 這裡實測抓到過同一類問題：財務分頁一打開就發 GET，使用者在回應回來前
      // 按「＋ 新增項目」，回應抵達時 this.materialOrders = [...] 會把剛新增的
      // 那一列整個蓋掉，而且畫面上不會有任何錯誤，人只會覺得「按了沒反應」。
      // 刻意不在這裡清空 materialOrders／moDirty：切換案件時 selectCase() 已經
      // 清過一次，這裡再清一次的話，「載入尚未回來就被呼叫第二次」會在使用者
      // 已經打字之後同步把畫面清掉，連下面的 moDirty 守門都來不及擋
      this._moReqFor = quoteNo
      this.moLoading = true
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/material-orders`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        // 已經切到別的案件：這份回應過期，丟掉（不然會把別張單的材料申請貼上來）
        if (this._moReqFor !== quoteNo) return
        // 使用者已經動手編輯：保留他打的東西，不要用伺服器版本覆蓋
        if (r.ok && this.moDirty) { this.moLoading = false; return }
        if (r.ok) {
          // 這份清單是自由格式 JSON（早期資料或人工改過的 data_json 不保證
          // 欄位齊全），跟後端 GET 端點同款作法：每個欄位都給預設值，
          // 不然 x-model 綁到 undefined 會讓整列輸入框變成不受控
          this.materialOrders = ((await r.json()).materialOrders || []).map(o => ({
            itemId:     o.itemId || this._moNewId(),
            itemName:   o.itemName || '',
            quantity:   Number(o.quantity) || 0,
            unit:       o.unit || '',
            unitPrice:  Number(o.unitPrice) || 0,
            totalPrice: Number(o.totalPrice) || 0,
            paidStatus: ['pending', 'partial', 'paid'].includes(o.paidStatus) ? o.paidStatus : 'pending',
            paidAmount: Number(o.paidAmount) || 0,
            paidDate:   o.paidDate || '',
            notes:      o.notes || '',
            invoiceDate: o.invoiceDate || '',  // `AC2`
            supplierId: o.supplierId ?? null,  // 31-C：整份覆寫的端點——少帶這一鍵，已指定的供應商會在下次存檔被抹掉
            quoteItemId: o.quoteItemId || '', poDocCode: o.poDocCode || '', poLine: o.poLine || null, overPlanReason: o.overPlanReason || '',  // 32-S4：連結鍵同理（case-management-mlink.js）
            _saved: true,                      // 伺服器上已有這一列（才能送審）
            _recvDate: ''
          }))
          await this.loadMoApprovals(quoteNo)
          await this.loadMoPayments(quoteNo)
          if (this.mlLoadStatus) this.mlLoadStatus(quoteNo)     // 32-S4：連結徽章
          if (this.moCanEdit()) await this.moLoadSuppliers()
        }
      } catch {}
      this.moLoading = false
    },

    // ── 材料申請審核（31-C）──────────────────────────────────────────────
    async loadMoApprovals(quoteNo) {
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/material-order-approvals`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok && this._moReqFor === quoteNo) { this.moApprovals = (await r.json()).approvals || {}; if (this._mlFollowMovedRow) this._mlFollowMovedRow() }   // 32-S4d：列的狀態變了，頁籤跟著走
      } catch {}
    },
    // ── 材料申請匯款申請（31-C 匯款切片）：已付金額不再手填，只能經匯款申請（簽核→出納）登錄 ──
    async loadMoPayments(quoteNo) {
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/material-payments`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok && this._moReqFor === quoteNo) this.moPay = (await r.json()).orders || {}
      } catch {}
    },
    moPayOf(m) { return (m && this.moPay[m.itemId]) || { quota: null, payments: [] } },
    // 可以開匯款申請：已存檔、$0 以外、舊單或已核准、還有額度
    moCanRequestPay(m) {
      if (!m || m._saved === false || this.moDirty || !this.moCanEdit()) return false
      if (m.poDocCode) return false                              // 32-S4：已對應採購單 ⇒ 付款走採購單請款，不開匯款申請
      if (!['', '已核准'].includes(this.moAp(m).status)) return false
      const q = this.moPayOf(m).quota
      return !!q && Number(m.totalPrice) > 0 && q.remaining > 0
    },
    moPayTone(s) {
      if (s === '已核准') return 'color:var(--success)'
      if (s === '已退回' || s === '作廢') return 'color:var(--tone-danger-fg)'
      if (s === '待審核' || s === '簽核中') return 'color:var(--tone-warning-fg)'
      return 'color:var(--text-dim)'
    },
    // 供應商選單（只回 id／code／name；`GET /api/suppliers` 對非 admin 回空，所以走這支）
    async moLoadSuppliers() {
      if (this.moSuppliers.length) return
      try {
        const r = await fetch('/api/material-suppliers', { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) this.moSuppliers = (await r.json()).suppliers || []
      } catch {}
    },
    async moOpenPayForm(m) {
      await this.moLoadSuppliers()
      const q = this.moPayOf(m).quota
      this.moPayForm = { itemId: m.itemId, amount: q ? q.remaining : 0, supplierId: m.supplierId ?? '', bankCode: '', bankName: '', bankAccountName: '', bankAccountNumber: '', overCapReason: '', payeeNoticeAcked: false }
    },
    async _moPayCall(url, method, body, okMsg) {
      this.moMsg = ''
      try {
        const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token }, body: JSON.stringify(body || {}) })
        const d = await r.json().catch(() => ({}))
        this.moMsgError = !r.ok
        this.moMsg = r.ok ? okMsg(d) : String((d.detail && (d.detail.message || d.detail)) || r.status)
        if (r.ok) await this.loadMoPayments(this.selected?.quote_no)
        return r.ok
      } catch (e) {
        this.moMsgError = true
        this.moMsg = '網路錯誤：' + e.message
        return false
      }
    },
    async moCreatePay(m) {
      const f = this.moPayForm
      if (!f || f.itemId !== m.itemId) return
      if (!f.payeeNoticeAcked) { this.moMsgError = true; this.moMsg = '請先勾選「已告知收款人」（收款人戶名與帳號屬個人資料，須先告知蒐集目的）'; return }
      const body = { payeeNoticeAcked: true, amount: Number(f.amount) || 0, supplierId: f.supplierId === '' ? null : Number(f.supplierId), bankCode: f.bankCode, bankName: f.bankName,
                     bankAccountName: f.bankAccountName, bankAccountNumber: f.bankAccountNumber }
      if (f.overCapReason) body.overCapReason = f.overCapReason
      const ok = await this._moPayCall(`/api/quotations/${encodeURIComponent(this.selected.quote_no)}/material-orders/${encodeURIComponent(m.itemId)}/payments`, 'POST', body,
                                         d => `已建立匯款申請：${d.payment.docCode}（草稿，請送審）`)
      if (ok) this.moPayForm = null
    },
    async moPayAct(p, action) {
      let body = {}
      if (action === 'void') {
        const reason = await MotrixUI.prompt('作廢匯款申請需要填原因（額度會釋出，並留稽核紀錄）：', { title: '作廢匯款申請', required: true })
        if (!reason || !String(reason).trim()) return
        body = { reason: String(reason).trim() }
      }
      await this._moPayCall(`/api/material-payments/${p.id}/${action}`, 'POST', body, d => ({ submit: d.autoApproved ? '已核准（未設定簽核層）' : '已送審', withdraw: '已撤回（回草稿）', void: '已作廢' }[action] || '完成'))
    },
    moAp(m) { return (m && this.moApprovals[m.itemId]) || { status: '', legacy: true } },
    moApLabel(m) {
      const a = this.moAp(m)
      if (this.moIsUnsent(m)) return '尚未送審'
      return a.legacy ? '舊單（未經審核）' : a.status
    },
    // 尚未送審＝畫面上新增但還沒存的列，或已存成草稿的列（不計入報表／額度／簽核佇列）；舊單與已退回不算
    moIsUnsent(m) { return !!m && (m._saved === false || (!this.moAp(m).legacy && this.moAp(m).status === '草稿')) },
    moApTone(m) {
      const s = this.moAp(m).status
      if (this.moIsUnsent(m)) return 'color:var(--text-dim)'
      if (s === '已核准') return 'color:var(--success)'
      if (s === '已退回' || s === '已取消') return 'color:var(--tone-danger-fg)'
      if (s === '待審核' || s === '簽核中') return 'color:var(--tone-warning-fg)'
      return 'color:var(--text-dim)'
    },
    // 審核中、已取消：實質欄位不能改（後端閘也會擋；這裡先反灰並說明原因）
    moLocked(m) { return ['待審核', '簽核中', '已取消'].includes(this.moAp(m).status) },
    moShowSubmit(m) { return !!m && (m._saved === false || ['', '草稿', '已退回'].includes(this.moAp(m).status)) && !this.moLocked(m) && !(m._saved !== false && this.moAp(m).legacy && !this.moDirty) && !(this.caseReadOnly && this.caseReadOnly()) },
    moShowWithdraw(m) { return ['待審核', '簽核中'].includes(this.moAp(m).status) },
    moShowCancel(m) { return this.moAp(m).status === '已核准' && ['superadmin', 'admin'].includes(this.session.role) },
    async _moPost(m, action, body, okMsg) {
      const quoteNo = this.selected?.quote_no
      if (!quoteNo || !m.itemId || this.moBusy) return false
      this.moBusy = m.itemId
      this.moMsg = ''
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/material-orders/${encodeURIComponent(m.itemId)}/${action === 'receive-undo' ? 'receive' : action}`, {
          method: action === 'receive-undo' ? 'DELETE' : 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: action === 'receive-undo' ? undefined : JSON.stringify(body || {})
        })
        const d = await r.json().catch(() => ({}))
        this.moMsgError = !r.ok
        this.moMsg = r.ok ? okMsg(d) : String((d.detail && (d.detail.message || d.detail)) || r.status)
        await this.loadMoApprovals(quoteNo)
        this.moBusy = ''
        return r.ok
      } catch (e) {
        this.moMsgError = true
        this.moMsg = '網路錯誤：' + e.message
        this.moBusy = ''
        return false
      }
    },
    // 一鍵＝先儲存再送審：儲存被守門拒絕（或沒存成）就停，不送審；被拒的列由重新載入還原，不留殘列
    async moSubmit(m) {
      const id = m.itemId
      if (m._saved === false || this.moDirty) {
        if (!(await this.moSave(true))) return
        m = this.materialOrders.find(x => x.itemId === id)
        if (!m) return
      }
      await this._moSubmitPost(m)
      // 送審後那一列會離開「已核准／舊單／尚未送審」分頁（頁籤由 case-management-mlink.js 提供）：跟著切過去，使用者才看得到它
      if (typeof this.mlTab === 'string' && this.mlTab !== 'all') {
        const st = (this.moApprovals[id] || {}).status
        if (['待審核', '簽核中'].includes(st)) this.mlTab = 'review'
        else if (st === '已核准') this.mlTab = 'approved'
      }
    },
    async _moSubmitPost(m) { await this._moPost(m, 'submit', {}, d => d.autoApproved ? `已核准（未設定簽核層）：${d.docCode}` : `已送審：${d.docCode}`) },
    async moWithdraw(m) { await this._moPost(m, 'withdraw', {}, () => '已撤回（回草稿）') },
    async moCancel(m) {
      const reason = await MotrixUI.prompt('取消已核准的材料申請需要填原因（會留稽核紀錄）：', { title: '取消材料申請', required: true })
      if (!reason || !String(reason).trim()) return
      await this._moPost(m, 'cancel', { reason: String(reason).trim() }, () => '材料申請已取消')
    },
    async moReceive(m) {
      const day = m._recvDate || MotrixDate.today()
      await this._moPost(m, 'receive', { receivedOn: day }, d => `已確認到貨：${d.receivedOn}`)
    },
    async moUndoReceive(m) { await this._moPost(m, 'receive-undo', null, () => '已撤銷到貨確認') },
    // 物流旗標只能對著「已核准的材料申請」勾；已勾的可以取消勾選（後端閘同規則，這裡先反灰並說明）
    matCanTick(mat, flag) {
      if (mat[flag]) return true
      const a = this.moApprovals[mat.orderItemId || '']
      if (!a || a.status !== '已核准') return false
      return flag === 'ordered' || !!a.receivedOn
    },
    matTickHint(mat, flag) {
      if (this.matCanTick(mat, flag)) return ''
      const a = this.moApprovals[mat.orderItemId || '']
      if (!a) return '需先申請請購單，再申請採購單；採購單通過後，才能對應這筆材料申請。'
      if (a.status !== '已核准') return '這筆材料申請還沒核准。'
      return '需先在材料申請上確認到貨（日期與確認人）'
    },

    // crypto.randomUUID() 在 HTTP 明文頁面下不存在（非安全上下文），正式機是
    // HTTPS 但開發機偶爾用 http://localhost 開，所以留一條退路
    _moNewId() {
      if (window.crypto && crypto.randomUUID) return crypto.randomUUID()
      return 'mo-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10)
    },

    // 權限條件跟後端 PATCH 端點一致（admin+ 或 project_manage 模組），外加
    // 已結案擋下來。前端擋不是安全機制，是不要讓使用者填完才被退回
    moCanEdit() {
      if (this.cr?.dealTag === '已結案') return false
      const m = this.session.modules || []
      return ['superadmin', 'admin'].includes(this.session.role) || m.includes('project_manage')
    },

    moTotals() {
      let total = 0, paid = 0, unsent = 0
      for (const m of this.materialOrders) {
        if (this.moIsUnsent(m)) { unsent++; continue }     // 尚未送審的不計入
        total += Number(m.totalPrice) || 0
        paid  += Number(m.paidAmount) || 0
      }
      return { total, paid, unpaid: total - paid, unsent }
    },

    // 2026-09-24（N11，使用者裁示「刪除確認全部都加」）：材料申請品項、派工／出貨表單品項列、
    // 負責人移除也要先確認；訊息寫出要刪的名稱。
    async moRemoveItem(i) {
      const m = this.materialOrders[i]
      if (!(await MotrixUI.confirm(`確定要刪除材料申請品項「${(m && m.itemName) || '未命名'}」？\n\n按「儲存」之後才會寫入。`, {danger: true}))) return
      this.materialOrders.splice(i, 1)
      this.moDirty = true
      this.moMsg = ''
    },

    // 小計一律由這裡算、使用者不能手填——後端會用
    // abs(totalPrice - 數量×單價) > 0.01 直接回 400。
    // 刻意不把 m.quantity / m.unitPrice 正規化寫回去：使用者打到一半的
    // 「1.」會被改成「1」，游標跳掉很難打字；正規化留到 moSave() 送出前做
    moRecalc(i) {
      const m = this.materialOrders[i]
      const q = Number(m.quantity) || 0
      const p = Number(m.unitPrice) || 0
      // X-VAT（2026-09-26）：金額（元以下兩位）一律 static/legal-round.js 四捨五入
      m.totalPrice = MotrixLegalRound.halfUp(q * p, 100) / 100
      this.moDirty = true    // 31-C：已付金額／日期是匯款申請付款明細的投影，不再隨小計連動，也不能在這裡改
    },

    // `AC2`：只登一筆材料申請的發票日期（專用端點；任何案件狀態都可以，不動金額）
    async moSetInvoiceDate(m) {
      const quoteNo = this.selected?.quote_no
      if (!quoteNo || !m.itemId) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/material-orders/${encodeURIComponent(m.itemId)}/invoice-date`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ invoiceDate: m.invoiceDate || '' })
        })
        const d = await r.json().catch(() => ({}))
        this.moMsgError = !r.ok
        this.moMsg = r.ok ? '發票日期已儲存' : ('發票日期儲存失敗：' + (d.detail || r.status))
        if (r.ok) { m.invoiceDate = d.invoiceDate; this.flashSaved('mo-' + m.itemId) }
      } catch (e) {
        this.moMsgError = true
        this.moMsg = '網路錯誤：' + e.message
      }
    },

    async moSave(forSubmit = false) {
      if (this.moSaving) return false
      const quoteNo = this.selected?.quote_no
      if (!quoteNo) return false

      // 送出前正規化＋先擋一次。後端這些規則都會再驗一次，這裡擋只是為了
      // 給看得懂的中文訊息（後端回的 detail 會指名項目，但撞到才看到）
      const payload = []
      for (const m of this.materialOrders) {
        const name = (m.itemName || '').trim()
        if (!name) { this.moMsgError = true; this.moMsg = '有項目還沒填名稱'; return false }
        if (m._saved === false && !m.supplierId) { this.moMsgError = true; this.moMsg = `「${name}」還沒選供應商（新增材料申請必填）`; return false }
        const quantity  = Math.max(0, Number(m.quantity) || 0)
        const unitPrice = Math.max(0, Number(m.unitPrice) || 0)
        const totalPrice = MotrixLegalRound.halfUp(quantity * unitPrice, 100) / 100
        payload.push({
          itemId: m.itemId || this._moNewId(), itemName: name,
          quantity, unit: (m.unit || '').trim(), unitPrice, totalPrice,
          // 31-C：已付欄位唯讀（匯款申請付款明細的投影）——原值帶回，後端閘不接受這裡改它
          paidStatus: m.paidStatus, paidAmount: Number(m.paidAmount) || 0,
          paidDate: m.paidStatus === 'pending' ? null : (m.paidDate || ''),
          notes: (m.notes || '').trim(),
          // `AC2`：整份覆寫的端點——少帶這一鍵，已登錄的發票日期就會在下次存檔時被抹掉
          invoiceDate: m.invoiceDate || '',
          supplierId: m.supplierId ? Number(m.supplierId) : null,
          // 32-S4：連結鍵（空值後端不寫入；整份覆寫的端點，少帶就會被抹掉）
          quoteItemId: m.quoteItemId || null, poDocCode: m.poDocCode || null, poLine: m.poLine ? Number(m.poLine) : null,
          overPlanReason: (m.overPlanReason || '').trim() || null
        })
      }

      this.moSaving = true
      this.moMsg = ''
      let ok = false
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/material-orders`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ materialOrders: payload })
        })
        if (r.ok) {
          this.moDirty = false
          const d = await r.json().catch(() => ({}))
          if (d.rejected && d.rejected.length) {
            // 材料申請審核（31-C）：只拒有問題的項目，其餘已存——逐項說明，並重新載入以顯示伺服器現值
            this.moMsgError = true
            this.moMsg = '部分項目沒有儲存：' + [...new Set(d.rejected.map(x => x.message))].join('；')
          } else {
            ok = true
            this.moMsgError = false
            this.moMsg = '已儲存'
            setTimeout(() => { if (!this.moDirty) this.moMsg = '' }, 2500)
          }
          await this.loadMaterialOrders(quoteNo)
        } else {
          const d = await r.json().catch(() => ({}))
          this.moMsgError = true
          this.moMsg = '儲存失敗：' + (d.detail || r.status)
        }
      } catch (e) {
        this.moMsgError = true
        this.moMsg = '網路錯誤：' + e.message
      }
      this.moSaving = false
      return ok
    },

    // ── 待辦事項（2026-08-26 專案管理併入案件管理，取代原本跳去 projects.html
    //    的 goToProject()/createProjectFromCase()）──
    async loadCaseActionItems() {
      if (!this.selected) return
      this.caseActionItemsLoading = true
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/action-items`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.caseActionItems = (await r.json()).items || []
      } catch {}
      this.caseActionItemsLoading = false
    },

    async addActionItem() {
      const text = this.newActionItemText.trim()
      if (!text || !this.selected) return
      this.addingActionItem = true
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/action-items`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ text })
        })
        if (!r.ok) { MotrixUI.toast('新增失敗：' + (await r.json()).detail, {kind: 'error'}); return }
        this.newActionItemText = ''
        await this.loadCaseActionItems()
      } catch(e) {
        MotrixUI.toast('發生錯誤：' + e.message, {kind: 'error'})
      } finally {
        this.addingActionItem = false
      }
    },

    async deleteActionItem(itemId) {
      if (!this.selected || !(await MotrixUI.confirm('確定刪除此待辦事項？', {danger: true}))) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/action-items/${itemId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast('刪除失敗：' + (await r.json()).detail, {kind: 'error'}); return }
        await this.loadCaseActionItems()
      } catch(e) {
        MotrixUI.toast('發生錯誤：' + e.message, {kind: 'error'})
      }
    },

    async approveActionItem(itemId, stage) {
      if (!this.selected) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/action-items/${itemId}/approve`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ stage })
        })
        if (!r.ok) { MotrixUI.toast('確認失敗：' + (await r.json()).detail, {kind: 'error'}); return }
        await this.loadCaseActionItems()
      } catch(e) {
        MotrixUI.toast('發生錯誤：' + e.message, {kind: 'error'})
      }
    },

    actionItemStatusLabel(item) {
      if (item.status === 'done') return '✓ 已完成'
      if (item.status === 'stage1_done') return '工程已確認，待業務確認'
      return '待確認'
    },

    // ── 專案資訊（成員分配，取代原 PATCH /api/projects/{id}/assigned-users）──
    toggleAssignedUser(userId) {
      const i = this.assignedUserIds.indexOf(userId)
      if (i >= 0) this.assignedUserIds.splice(i, 1)
      else this.assignedUserIds.push(userId)
    },

    async saveAssignedUsers() {
      if (!this.selected) return
      this.assignedUsersSaving = true
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/assigned-users`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ user_ids: this.assignedUserIds })
        })
        if (!r.ok) { MotrixUI.toast('儲存失敗：' + (await r.json()).detail, {kind: 'error'}); return }
      } catch(e) {
        MotrixUI.toast('發生錯誤：' + e.message, {kind: 'error'})
      } finally {
        this.assignedUsersSaving = false
      }
    },

    caseProgressPct() {
      const stages = this.cr.caseRecord?.stages || []
      if (!stages.length) return 0
      return Math.round(stages.filter(s => s.done).length / stages.length * 100 /* 非金額 */)
    },

    _firstUndoneStageId() {
      const stages = this.cr.caseRecord?.stages || []
      const s = stages.find(s => !s.done)
      return s ? s.id : null
    },
    stageSegClass(st) {
      if (st.done) return 'stage-segbar__seg--done'
      if (this.stageIsOverdue(st)) return 'stage-segbar__seg--overdue'   // 逾期優先於「目前/未來」
      if (st.id === this._firstUndoneStageId()) return 'stage-segbar__seg--current'
      return 'stage-segbar__seg--future'
    },
    stageSegTooltip(st) {
      const status = st.done
        ? ('已完成' + (st.doneAt ? '（' + st.doneAt + '）' : ''))
        : (this.stageIsOverdue(st)
            ? ('已逾期' + (st.dueDate ? '（到期 ' + st.dueDate + '）' : ''))
            : (st.dueDate ? ('到期日 ' + st.dueDate) : '未設定到期日'))
      return (st.label || '（未命名階段）') + ' — ' + status
    },

    // stages 正規化 Phase 3b（2026-08-23）：以下階段相關函式改成直接呼叫 stages 專屬
    // 端點即時送出，不再靠本地陣列變更 + setDirty() 整包 debounce 存檔。成功後用伺服器
    // 回應 Object.assign 覆蓋本地物件，確保跟資料庫一致；失敗用 alert()（比照本檔既有
    // 慣例，例如 createProjectFromCase()）。materials/devices/payment/contract/roles
    // 等其他 caseRecord 欄位不受影響，仍走 setDirty()/saveCaseRecord() 整包存檔。
    _stagesApiBase() { return `/api/quotations/${this.selected.quote_no}/stages` },
    _authHeaders(json) {
      const h = { Authorization: 'Bearer ' + this.session.token }
      if (json) h['Content-Type'] = 'application/json'
      return h
    },

    async addStage() {
      if (!this.selected) return
      await this.ensureCaseRecord()
      try {
        const r = await fetch(this._stagesApiBase(), {
          method: 'POST', headers: this._authHeaders(true), body: JSON.stringify({ label: '新階段' })
        })
        if (!r.ok) { MotrixUI.toast('新增階段失敗', {kind: 'error'}); return }
        this.cr.caseRecord.stages.push(await r.json())
      } catch (e) { MotrixUI.toast('發生錯誤：' + e.message, {kind: 'error'}) }
    },
    async removeStage(idx) {
      const stages = this.cr.caseRecord.stages
      const st = stages[idx]
      if (!st) return
      if (!(await MotrixUI.confirm(`確定要刪除執行階段「${st.label || '未命名'}」？\n\n階段內的拜訪紀錄會一併刪除，無法復原。`, {danger: true}))) return
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}`, { method: 'DELETE', headers: this._authHeaders() })
        if (!r.ok) { MotrixUI.toast('刪除失敗', {kind: 'error'}); return }
        const j = await r.json().catch(() => ({}))
        if (j.notice) MotrixUI.toast(j.notice, {kind: 'info', ms: 8000})   // IP-5：每日任務模組不在時明說沒有收回
        stages.splice(idx, 1)
        stages.forEach(s => { if (s.dependsOn) s.dependsOn = s.dependsOn.filter(id => id !== st.id) })
      } catch (e) { MotrixUI.toast('發生錯誤：' + e.message, {kind: 'error'}) }
    },

    toggleStageDetail(id) { this._openStageDetail[id] = !this._openStageDetail[id] },

    stageIsOverdue(st) {
      if (st.done || !st.dueDate) return false
      return st.dueDate < MotrixDate.today()
    },

    otherStages(stageId) {
      return (this.cr.caseRecord?.stages || []).filter(s => s.id !== stageId)
    },

    // 通用階段欄位更新（label/done/doneAt/startDate/dueDate），取代原本靠 setDirty() 觸發
    // 的整包存檔；成功後額外呼叫 _checkAllStagesDone()（原本是 setDirty() 順帶觸發的）。
    // `AC2`：階段收入比例。存基點（1/10000）；空白＝未設（null，不是 0——0 是「這個階段不認列」）
    stageRatioPct(st) { return st.ratioBp === null || st.ratioBp === undefined ? '' : st.ratioBp / 100 },
    setStageRatio(st, v) {
      const bp = (v === '' || v === null || v === undefined) ? null : Math.round(Number(v) * 100 /* 非金額 */)
      if (bp !== null && (!Number.isFinite(bp) || bp < 0 || bp > 10000)) { MotrixUI.toast('比例需為 0～100%', {kind: 'info'}); return }
      this.updateStage(st, { ratioBp: bp })
    },
    stageRatioSummary() {
      const ss = this.cr.caseRecord?.stages || []
      const set = ss.filter(s => s.ratioBp !== null && s.ratioBp !== undefined)
      if (!set.length) return { warn: false, text: '收入比例未設定：權責口徑於全部階段完成的月份一次認列。' }
      const total = set.reduce((a, s) => a + s.ratioBp, 0)
      const pct = (total / 100).toLocaleString()
      return total === 10000
        ? { warn: false, text: '收入比例合計 100%：各階段於完成月份依比例認列（未稅）。' }
        : { warn: true, text: '收入比例合計 ' + pct + '%，不等於 100%：報表照比例認列、不補差，並列入待補登。' }
    },

    async updateStage(st, fields) {
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}`, {
          method: 'PUT', headers: this._authHeaders(true), body: JSON.stringify(fields)
        })
        if (!r.ok) { MotrixUI.toast('儲存失敗', {kind: 'error'}); return }
        const j = await r.json()
        const notice = j.notice
        delete j.notice
        Object.assign(st, j)
        if (notice) MotrixUI.toast(notice, {kind: 'info', ms: 8000})   // IP-5：每日任務模組不在時明說沒有建立／收回
        this.flashSaved('stages')
        this._checkAllStagesDone()
      } catch (e) { MotrixUI.toast('發生錯誤：' + e.message, {kind: 'error'}) }
    },

    async addStageAssignee(st, username) {
      if (!username) return
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/assignees`, {
          method: 'POST', headers: this._authHeaders(true), body: JSON.stringify({ username })
        })
        if (r.ok) { Object.assign(st, await r.json()); this.flashSaved('stages') }
      } catch {}
    },
    async removeStageAssignee(st, username) {
      const u = (this.selectableUsers || []).find(x => x.username === username)
      if (!(await MotrixUI.confirm(`確定要把「${(u && u.display_name) || username}」從階段「${st.label || '未命名'}」的負責人移除？`, {danger: true}))) return
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/assignees/${encodeURIComponent(username)}`, {
          method: 'DELETE', headers: this._authHeaders()
        })
        if (r.ok) { Object.assign(st, await r.json()); this.flashSaved('stages') }
      } catch {}
    },

    wouldCreateCycle(stageId, candidateId) {
      // 若讓 stageId 依賴 candidateId，順著 dependsOn 追下去會不會繞回 stageId 自己。
      // 純前端快速預檢，伺服器端 toggle_stage_dependency 仍是最終權威判斷（見下方 400 處理）。
      if (stageId === candidateId) return true
      const byId = Object.fromEntries((this.cr.caseRecord?.stages || []).map(s => [s.id, s]))
      const seen = new Set()
      const dfs = (id) => {
        if (id === stageId) return true
        if (seen.has(id)) return false
        seen.add(id)
        return ((byId[id]?.dependsOn) || []).some(dfs)
      }
      return dfs(candidateId)
    },

    async toggleStageDependency(st, candidateId) {
      const has = (st.dependsOn || []).includes(candidateId)
      if (!has && this.wouldCreateCycle(st.id, candidateId)) {
        MotrixUI.toast('這樣設定會讓階段之間互相循環依賴，請重新選擇前置階段', {kind: 'info'})
        return
      }
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/depends-on/${candidateId}`, {
          method: 'POST', headers: this._authHeaders()
        })
        if (!r.ok) {
          const err = await r.json().catch(() => ({}))
          MotrixUI.toast(err.detail || '設定失敗', {kind: 'error'})
          return
        }
        Object.assign(st, await r.json())
      } catch (e) { MotrixUI.toast('發生錯誤：' + e.message, {kind: 'error'}) }
    },

    switchToTimeline() {
      this.stageView = 'timeline'
      this.$nextTick(() => this.renderGantt())
    },

    _userDisplay(username) {
      return (this.selectableUsers.find(u => u.username === username)?.display_name) || username
    },

    _ganttTasks() {
      const stages = this.cr.caseRecord?.stages || []
      const byId   = Object.fromEntries(stages.map(s => [String(s.id), s]))
      const today  = MotrixDate.today()
      const addDays = (dateStr, n) => {
        const d = new Date(dateStr + 'T00:00:00')
        d.setDate(d.getDate() + n)
        return MotrixDate.ymd(d)
      }
      return stages.map(st => {
        // 日期來源優先順序（2026-08-24）：
        // 1. 「前往日期」visits 記錄的最早～最晚——施工類階段常有好幾筆前往記錄，
        //    這是最能反映真實施作期間的來源，已完成的話終點改用完成日期（可能
        //    比最後一次前往晚幾天才正式結案）。
        // 2. 完成日期 doneAt（單日）——使用者實際會填、最準確的次要來源。
        // 3. 起始/到期日期 startDate/dueDate——實務上幾乎沒人填，只靠它們會讓
        //    已完成的階段全部退回「今天」擠成一團（跨案時間軸同一個問題的根因，
        //    這裡是同一套邏輯的單案版）。
        const visitDates = (st.visits || []).map(v => v.visitDate).filter(Boolean).sort()
        let start, end
        if (visitDates.length) {
          start = visitDates[0]
          end   = (st.done && st.doneAt) ? st.doneAt : visitDates[visitDates.length - 1]
        } else if (st.done && st.doneAt) {
          start = st.doneAt
          end   = st.doneAt
        } else {
          start = st.startDate || st.dueDate || today
          end   = st.dueDate   || st.startDate || addDays(start, 1)
        }
        if (end < start) end = start
        if (start === end) end = addDays(start, 1)
        const assignedTo  = st.assignedTo || []
        const primary     = assignedTo[0] || ''
        // 依主要負責人（assignedTo 第一位）hash 出固定色階 index，供 CSS .stage-c0~c7 上色
        const idx = primary ? _GANTT_COLORS.indexOf(_avatarColor(primary)) : -1
        const classes = [
          idx >= 0 ? ('stage-c' + idx) : 'stage-unassigned',
          st.done ? 'stage-done' : '',
          (!st.done && this.stageIsOverdue(st)) ? 'stage-overdue' : '',
        ].filter(Boolean).join(' ')
        // 2026-09-14：標籤前面加上起日（MM/DD）。甘特圖被縮放貼進簡報或
        // 列印時，時間軸刻度往往先糊掉，標籤自己帶日期才讀得出來。
        const _md = (d) => (d || '').slice(5, 10).replace('-', '/')
        return {
          id:           String(st.id),
          name:         (_md(start) ? _md(start) + ' ' : '') + (st.label || '（未命名階段）'),
          start, end,
          progress:     st.done ? 100 : 0,
          dependencies: (st.dependsOn || []).map(String).join(','),
          custom_class: classes,
          _assignedNames: assignedTo.map(u => this._userDisplay(u)),
          _dependsNames:  (st.dependsOn || []).map(id => byId[String(id)]?.label).filter(Boolean),
          _done: !!st.done,
          _overdue: !st.done && this.stageIsOverdue(st),
        }
      })
    },

    // ── 甘特圖檔位（2026-09-14）────────────────────────────────────────
    // 原本 view_mode 寫死 'Day'：跨半年的案件會拉出好幾千 px 寬，只能一直
    // 橫向捲、看不到全貌。改成依實際跨幅自動選，使用者可手動覆寫。
    ganttView: 'auto',
    _ganttSpanDays(tasks) {
      if (!tasks || !tasks.length) return 0
      let min = null, max = null
      tasks.forEach(t => {
        const s = new Date(t.start), e = new Date(t.end)
        if (!min || s < min) min = s
        if (!max || e > max) max = e
      })
      return Math.round((max - min) / 86400000 /* 非金額 */)
    },
    // 【可調】檔位切換門檻。想讓它更早/更晚跳到週或月檔位，改這兩個數字就好，
    // 其餘邏輯不用動。判斷依據是「所有階段的最早起日到最晚迄日」的天數跨幅。
    //   Day  約 30px/天 → 45 天上限約 1400px，還放得進一般螢幕
    //   Week 約 156px/週 → 180 天上限約 4000px，需要橫向捲但仍讀得出來
    _autoGanttMode(tasks) {
      const d = this._ganttSpanDays(tasks)
      if (d <= 45)  return 'Day'
      if (d <= 180) return 'Week'
      return 'Month'
    },
    get ganttEffectiveMode() {
      if (this.ganttView !== 'auto') return this.ganttView
      return this._autoGanttMode(this._ganttTasks())
    },
    setGanttView(v) {
      this.ganttView = v
      this.renderGantt()
    },

    renderGantt() {
      const el = this.$refs.ganttContainer
      if (!el || typeof Gantt === 'undefined') return
      const tasks = this._ganttTasks()
      el.innerHTML = ''
      if (!tasks.length) return
      const mode = this.ganttView === 'auto' ? this._autoGanttMode(tasks) : this.ganttView
      this._ganttInstance = new Gantt(el, tasks, {
        view_mode: mode,
        on_date_change: (task, start, end) => {
          const st = (this.cr.caseRecord?.stages || []).find(s => String(s.id) === task.id)
          if (!st) return
          const fmt = d => MotrixDate.ymd(d)
          this.updateStage(st, { startDate: fmt(start), dueDate: fmt(end) })
        },
        custom_popup_html: (task) => {
          const statusChip = task._done
            ? '<span class="gantt-pop-chip gantt-pop-chip--done">已完成</span>'
            : (task._overdue ? '<span class="gantt-pop-chip gantt-pop-chip--overdue">已逾期</span>' : '')
          const assignees = (task._assignedNames && task._assignedNames.length)
            ? task._assignedNames.map(n => `<span class="gantt-pop-av">${n}</span>`).join('')
            : '<span class="gantt-pop-empty">尚未指派</span>'
          const depends = (task._dependsNames && task._dependsNames.length)
            ? `<div class="gantt-pop-row"><span class="gantt-pop-lbl">前置階段</span>${task._dependsNames.map(n => `<span class="gantt-pop-av">${n}</span>`).join('')}</div>`
            : ''
          return `
            <div class="gantt-pop">
              <div class="gantt-pop-title">${task.name}${statusChip}</div>
              <div class="gantt-pop-row"><span class="gantt-pop-lbl">日期</span>${task.start} ~ ${task.end}</div>
              <div class="gantt-pop-row"><span class="gantt-pop-lbl">負責人</span>${assignees}</div>
              ${depends}
            </div>`
        },
      })
    },
    // ── 甘特圖匯出 PNG / JPG（2026-09-14）──────────────────────────────
    // Frappe Gantt 畫的是 SVG，但顏色與字體全部來自外部 CSS。直接
    // XMLSerializer 序列化出來的 SVG 沒有那些樣式，畫到 canvas 上會變成
    // 沒有顏色的黑白線稿——**必須把 computed style 逐一 inline 回克隆節點**。
    // 這是整件事唯一的難處，不是多寫幾行 canvas 就好。
    //
    // 深色模式下匯出的仍是淺色版：整站深色是繪製階段的 invert 濾鏡，
    // getComputedStyle 讀到的是作者值。對匯出圖來說這正是我們要的。
    _SVG_STYLE_PROPS: ['fill','fill-opacity','stroke','stroke-width','stroke-dasharray',
                       'opacity','font-family','font-size','font-weight','text-anchor',
                       'dominant-baseline','visibility'],
    async exportGanttImage(fmt) {
      const el = this.$refs.ganttContainer
      const svg = el && el.querySelector('svg')
      if (!svg) { this.toast && this.toast('目前沒有可匯出的甘特圖'); return }
      this.ganttExporting = true
      try {
        const rect = svg.getBoundingClientRect()
        const fullW = Math.ceil(svg.getAttribute('width')  || rect.width)
        const h = Math.ceil(svg.getAttribute('height') || rect.height)
        const TITLE_H = 46

        // 裁掉左右空白（2026-09-14）
        // Frappe Gantt 的 setup_gantt_dates() 會自己把日期範圍撐開：
        // 週／日檔位前後各加 1 個月、月檔位往前補到年初再往後加 1 整年。
        // 所以一張 60 天的案件會畫成 2600px 以上，中間大半是空網格。
        // 壓縮的正解是裁掉那段空白，而不是把整張圖縮小——縮小會連日期
        // 刻度一起糊掉，那正是要避免的事。
        let cropX = 0, cropW = fullW, cropH = h
        if (this.ganttTrim) {
          const bars = svg.querySelectorAll('.bar-wrapper .bar, .bar-wrapper .bar-invalid')
          let minX = null, maxX = null, maxY = null
          bars.forEach(b => {
            const x  = parseFloat(b.getAttribute('x') || 'NaN')
            const y  = parseFloat(b.getAttribute('y') || 'NaN')
            const bw = parseFloat(b.getAttribute('width')  || '0')
            const bh = parseFloat(b.getAttribute('height') || '0')
            if (!isNaN(x)) {
              if (minX === null || x < minX) minX = x
              if (maxX === null || x + bw > maxX) maxX = x + bw
            }
            if (!isNaN(y) && (maxY === null || y + bh > maxY)) maxY = y + bh
          })
          if (minX !== null && maxX !== null && maxX > minX) {
            // 左右留白刻意不對稱：長條的 x/width 只涵蓋長條本身，**不含畫在
            // 右側的標籤文字**，所以右邊要多留，否則最後一個階段的標籤會被切。
            const PAD_L = 60, PAD_R = 240
            cropX = Math.max(0, Math.floor(minX - PAD_L))
            cropW = Math.min(fullW - cropX, Math.ceil(maxX - minX + PAD_L + PAD_R))
          }
          // SVG 高度是「列數 × 列高」的固定值，兩三個階段的案件下方會留一大片
          // 空列，一起裁掉。
          if (maxY !== null) cropH = Math.min(h, Math.ceil(maxY + 40))
        }
        const w = cropW

        const clone = svg.cloneNode(true)
        const src = svg.querySelectorAll('*')
        const dst = clone.querySelectorAll('*')
        for (let i = 0; i < src.length; i++) {
          const cs = getComputedStyle(src[i])
          let css = ''
          for (const prop of this._SVG_STYLE_PROPS) {
            const v = cs.getPropertyValue(prop)
            if (v) css += prop + ':' + v + ';'
          }
          dst[i].setAttribute('style', css)
        }
        clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
        clone.setAttribute('width', fullW)
        clone.setAttribute('height', h)

        const data = new XMLSerializer().serializeToString(clone)
        const img = new Image()
        await new Promise((res, rej) => {
          img.onload = res; img.onerror = rej
          img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(data)
        })

        // 2 倍取樣，列印或貼進簡報才不會糊
        const SCALE = 2
        const cv = document.createElement('canvas')
        cv.width  = w * SCALE
        cv.height = (cropH + TITLE_H) * SCALE
        const ctx = cv.getContext('2d')
        ctx.scale(SCALE, SCALE)
        ctx.fillStyle = '#FFFFFF'
        ctx.fillRect(0, 0, w, cropH + TITLE_H)

        // 抬頭：匯出的圖要自己說得清楚是哪張案子、哪天匯出的
        const sel = this.selected || {}
        ctx.fillStyle = '#1A1D21'
        ctx.font = '600 15px "LINE Seed TW_OTF", system-ui, sans-serif'
        ctx.fillText((sel.customer_name || '') + '　' + (sel.quote_no || ''), 16, 24)
        ctx.fillStyle = '#767676'
        ctx.font = '11px "LINE Seed TW_OTF", system-ui, sans-serif'
        const modeLabel = { Day: '日', Week: '週', Month: '月' }[this.ganttEffectiveMode] || ''
        ctx.fillText('執行進度甘特圖・' + modeLabel + '檔位'
                     + '・匯出於 ' + new Date().toLocaleString('zh-TW'), 16, 39)

        // 只畫裁切範圍那一段（來源 x 從 cropX 起算）
        ctx.drawImage(img, cropX, 0, cropW, cropH, 0, TITLE_H, cropW, cropH)

        const mime = fmt === 'jpg' ? 'image/jpeg' : 'image/png'
        const blob = await new Promise(r => cv.toBlob(r, mime, 0.92))
        const stamp = MotrixDate.today().replace(/-/g, '')
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = '甘特圖_' + (sel.quote_no || 'case') + '_' + stamp + '.' + fmt
        document.body.appendChild(a); a.click(); a.remove()
        setTimeout(() => URL.revokeObjectURL(a.href), 4000)
      } catch (e) {
        console.error('gantt export:', e)
      }
      this.ganttExporting = false
    },
    ganttExporting: false,
    ganttTrim: true,   // 匯出時裁掉前後空白。固定啟用：沒有人會想要一張大半是空白的圖，
                       // 不用多一個選項去問

    async addVisit(stageIdx) {
      const st = this.cr.caseRecord.stages[stageIdx]
      if (!st) return
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/visits`, {
          method: 'POST', headers: this._authHeaders(true), body: JSON.stringify({})
        })
        if (!r.ok) { MotrixUI.toast('新增記錄失敗', {kind: 'error'}); return }
        Object.assign(st, await r.json())
      } catch (e) { MotrixUI.toast('發生錯誤：' + e.message, {kind: 'error'}) }
    },
    async removeVisit(stageIdx, visitIdx) {
      const st = this.cr.caseRecord.stages[stageIdx]
      const visit = st?.visits?.[visitIdx]
      if (!st || !visit) return
      if (!(await MotrixUI.confirm(`確定要刪除這筆拜訪紀錄${visit.visitDate ? '（' + visit.visitDate + '）' : ''}？\n\n刪除後無法復原。`, {danger: true}))) return
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/visits/${visit.id}`, {
          method: 'DELETE', headers: this._authHeaders()
        })
        if (!r.ok) { MotrixUI.toast('刪除失敗', {kind: 'error'}); return }
        st.visits.splice(visitIdx, 1)
      } catch (e) { MotrixUI.toast('發生錯誤：' + e.message, {kind: 'error'}) }
    },
    async updateVisit(st, visit) {
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/visits/${visit.id}`, {
          method: 'PUT', headers: this._authHeaders(true),
          body: JSON.stringify({ visitDate: visit.visitDate, visitPeople: visit.visitPeople, note: visit.note })
        })
        if (r.ok) { Object.assign(st, await r.json()); this.flashSaved('stages') }
      } catch {}
    },
    stageTotalVisits(st) { return (st.visits || []).filter(v => v.visitDate || v.note).length },
    stageTotalPeople(st) { return (st.visits || []).reduce((s, v) => s + (+v.visitPeople || 0), 0) },

    dragStart(idx) { this.dragFromIdx = idx },
    dragOver(e, idx) {
      e.preventDefault()
      if (this.dragFromIdx === null || this.dragFromIdx === idx) return
      const stages = this.cr.caseRecord.stages
      const moved  = stages.splice(this.dragFromIdx, 1)[0]
      stages.splice(idx, 0, moved)
      this.dragFromIdx = idx
    },
    async dragEnd() {
      this.dragFromIdx = null
      const stages = this.cr.caseRecord?.stages || []
      if (!this.selected || !stages.length) return
      try {
        await fetch(`${this._stagesApiBase()}/reorder`, {
          method: 'PATCH', headers: this._authHeaders(true),
          body: JSON.stringify({ orderedIds: stages.map(s => s.id) })
        })
      } catch {}
    },

    addMaterial() {
      this.ensureCaseRecord()
      this.cr.caseRecord.materials.push({ id: Date.now(), name: '', model: '', qty: 1, unit: '台', ordered: false, arrived: false, devices: [], note: '' })
      this.setDirty()
    },
    async removeMaterial(idx) {
      const m = this.cr.caseRecord.materials[idx]
      if (!(await MotrixUI.confirm(`確定要刪除材料「${m?.name || '未命名'}」？\n\n刪除後會自動存檔，無法復原。`, {danger: true}))) return
      this.cr.caseRecord.materials.splice(idx, 1); this.setDirty()
    },
    addMaterialFromQuote(qi) {
      this.ensureCaseRecord()
      this.cr.caseRecord.materials.push({
        id: Date.now() + Math.random(),
        name: qi.description || '', model: qi.brand || '',
        qty: qi.qty || 1, unit: qi.unit || '台',
        ordered: false, arrived: false, devices: [], note: ''
      })
      this.setDirty()
    },
    quoteItemsForImport() {
      return (this.selected?.data?.items || []).filter(
        i => i.type !== 'header' && (i.description || '').trim()
      )
    },
    openImportModal(mode) {
      this.importMode = mode
      const items = this.quoteItemsForImport()
      if (!items.length) { MotrixUI.toast('報價單無可匯入的品項', {kind: 'info'}); return }
      const sel = {}
      items.forEach(function(_, i) { sel[i] = true })
      this.importSelectedItems = sel
      this.showImportModal = true
    },
    toggleImportItem(idx) {
      this.importSelectedItems = Object.assign({}, this.importSelectedItems, { [idx]: !this.importSelectedItems[idx] })
    },
    selectAllImportItems(val) {
      const sel = {}
      this.quoteItemsForImport().forEach(function(_, i) { sel[i] = val })
      this.importSelectedItems = sel
    },
    doImport() {
      const items = this.quoteItemsForImport()
      const selected = items.filter(function(_, i) { return this.importSelectedItems[i] }, this)
      if (!selected.length) { MotrixUI.toast('請至少選擇一個品項', {kind: 'info'}); return }
      if (this.importMode === 'materials') {
        selected.forEach(qi => this.addMaterialFromQuote(qi))
      } else {
        this.ensureCaseRecord()
        const base = Date.now()
        selected.forEach((item, ii) => {
          const groupId = 'grp_' + (base + ii).toString(36) + Math.random().toString(36).slice(2, 5)
          const qty = Math.min(Math.round(item.qty /* 非金額 */) || 1, 50)
          for (let i = 0; i < qty; i++) {
            this.cr.caseRecord.devices.push({
              id: base + Math.random(),
              name: item.description + (qty > 1 ? ` #${i + 1}` : ''),
              sn: '', mac: '', location: '', warrantyStart: '', warrantyMonths: 12, note: '',
              _groupId: groupId, _groupName: item.description, _groupIdx: i + 1, _groupTotal: qty
            })
          }
          this._openDevGroups = Object.assign({}, this._openDevGroups, { [groupId]: true })
        })
        this.setDirty()
      }
      this.showImportModal = false
    },
    onMaterialArrived(mat) {
      if (mat.arrived) {
        const need = mat.qty || 1
        if (!mat.devices) mat.devices = []
        while (mat.devices.length < need) mat.devices.push({ id: Date.now() + Math.random(), sn: '', mac: '' })
        if (mat.devices.length > need) mat.devices.splice(need)
      }
      this.setDirty()
    },
    syncMaterialsToDevices() {
      this.ensureCaseRecord()
      const mats     = (this.cr.caseRecord.materials || []).filter(m => m.arrived)
      const existing = this.cr.caseRecord.devices
      mats.forEach(mat => {
        (mat.devices || []).forEach((md, mi) => {
          let dev = existing.find(d => d._matId === mat.id && d._devIdx === mi)
          if (!dev) {
            const label = mat.name + ((mat.qty || 1) > 1 ? ` #${mi + 1}` : '')
            dev = { id: Date.now() + Math.random(), name: label, sn: md.sn || '', mac: md.mac || '', location: '', warrantyStart: '', warrantyMonths: 12, note: '', _matId: mat.id, _devIdx: mi }
            existing.push(dev)
          } else {
            if (md.sn)  dev.sn  = md.sn
            if (md.mac) dev.mac = md.mac
            if (!dev.name) dev.name = mat.name
          }
        })
      })
      this.activeTab = 'exec'
      this.execSubTab = 'devices'
      this.setDirty()
    },
    autoSyncDevice(mat, mi) {
      const md = mat.devices && mat.devices[mi]
      if (!md) { this.setDirty(); return }
      this.ensureCaseRecord()
      const devs = this.cr.caseRecord.devices
      let dev = devs.find(d => d._matId === mat.id && d._devIdx === mi)
      if (!dev) {
        const label = mat.name + ((mat.qty || 1) > 1 ? ` #${mi + 1}` : '')
        dev = { id: Date.now() + Math.random(), name: label, sn: md.sn || '', mac: md.mac || '', location: '', warrantyStart: '', warrantyMonths: 12, note: '', _matId: mat.id, _devIdx: mi }
        devs.push(dev)
      } else {
        dev.sn  = md.sn  !== undefined ? md.sn  : dev.sn
        dev.mac = md.mac !== undefined ? md.mac : dev.mac
        if (!dev.name) dev.name = mat.name
      }
      this.setDirty()
    },
    addDevice() {
      this.ensureCaseRecord()
      this.cr.caseRecord.devices.push({ id: Date.now(), name: '', sn: '', mac: '', location: '', warrantyStart: '', warrantyMonths: 12, note: '' })
      this.setDirty()
    },
    // 刪除設備會在自動存檔時同步序號庫存（_sync_device_stock），存完無法復原
    async _confirmRemoveDevice(dev) {
      return MotrixUI.confirm(`確定要刪除設備「${dev?.name || '未命名'}${dev?.sn ? '／' + dev.sn : ''}」？\n\n刪除後會自動存檔並同步序號庫存，無法復原。`, {danger: true})
    },
    async removeDevice(idx) {
      if (!(await this._confirmRemoveDevice(this.cr.caseRecord.devices[idx]))) return
      this.cr.caseRecord.devices.splice(idx, 1); this.setDirty()
    },
    async removeDeviceByObj(dev) {
      const devs = this.cr.caseRecord.devices
      const idx = devs.findIndex(d => d.id === dev.id)
      if (idx === -1 || !(await this._confirmRemoveDevice(dev))) return
      devs.splice(idx, 1); this.setDirty()
    },
    async removeDeviceGroup(groupId) {
      if (!(await MotrixUI.confirm('確定要刪除整個設備群組？', {danger: true}))) return
      this.cr.caseRecord.devices = this.cr.caseRecord.devices.filter(d => d._groupId !== groupId)
      this.setDirty()
    },
    toggleDevGroup(groupId) {
      this._openDevGroups = { ...this._openDevGroups, [groupId]: !this._openDevGroups[groupId] }
    },

    // ── 設備拖曳（自訂 ghost + insertion line + timestamp 計時，不依賴 setTimeout）──
    devDragStart(e, dev) {
      this._devDragId = dev.id
      e.dataTransfer.effectAllowed = 'move'
      // 自訂 ghost：克隆 → 定位至畫面外 → setDragImage → 下一 tick 移除
      const card = e.currentTarget
      const ghost = card.cloneNode(true)
      ghost.style.cssText = [
        'position:fixed','left:-9999px','top:0',
        `width:${card.offsetWidth}px`,
        'opacity:.88','pointer-events:none',
        'transform:rotate(1.5deg) scale(1.04)',
        'box-shadow:var(--shadow-popover)',
        'border-radius:8px','background:var(--surface)',
        'border:1px solid var(--tone-info-border)','z-index:9999'
      ].join(';')
      document.body.appendChild(ghost)
      e.dataTransfer.setDragImage(ghost, e.offsetX + 8, e.offsetY + 8)
      setTimeout(() => ghost.remove(), 0)
      this._devDragOverId = null
      this._devInsertBeforeId = null
      this._devHoverGroupId = null
      this._devGroupTarget = null
      this._devHoverStart = 0
    },

    devDragEnd() {
      this._devDragId = null
      this._devDragOverId = null
      this._devInsertBeforeId = null
      this._devHoverGroupId = null
      this._devGroupTarget = null
      this._devHoverStart = 0
    },

    devDragOver(e, targetId) {
      if (!this._devDragId) return
      const devs = this.cr.caseRecord?.devices || []
      const dragged = devs.find(d => d.id === this._devDragId)
      if (!dragged) return
      if (targetId === 'dev_' + String(dragged.id)) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      // 自動捲動設備 Tab 容器
      const scrollEl = document.querySelector('.cm-detail__body')
      if (scrollEl) {
        const ZONE = 70, SPD = 10, r = scrollEl.getBoundingClientRect()
        if (e.clientY < r.top + ZONE)      scrollEl.scrollTop -= SPD
        else if (e.clientY > r.bottom - ZONE) scrollEl.scrollTop += SPD
      }
      // 進入新目標：重置計時與狀態
      if (targetId !== this._devDragOverId) {
        this._devDragOverId = targetId
        this._devHoverStart = Date.now()
        this._devGroupTarget = null
        this._devInsertBeforeId = null
        this._devHoverGroupId = null
      }
      // 群組標頭 → add-to-group 模式（不顯示插入線）
      if (targetId.startsWith('group_')) {
        this._devHoverGroupId = targetId.slice(6)
        this._devInsertBeforeId = null
        return
      }
      this._devHoverGroupId = null
      // 設備卡片：900ms 後轉合併模式；否則以上/下半決定插入位置
      if (targetId.startsWith('dev_')) {
        if (!this._devGroupTarget && Date.now() - this._devHoverStart > 900)
          this._devGroupTarget = targetId
        if (this._devGroupTarget === targetId) { this._devInsertBeforeId = null; return }
        const rect = e.currentTarget.getBoundingClientRect()
        this._devInsertBeforeId = e.clientY < rect.top + rect.height / 2
          ? targetId
          : this._devNextId(parseInt(targetId.slice(4)))
      } else {
        this._devInsertBeforeId = 'end'
      }
    },

    devDragLeave(e) {
      if (e.relatedTarget && e.currentTarget.contains(e.relatedTarget)) return
      this._devDragOverId = null
      this._devHoverGroupId = null
      this._devGroupTarget = null
      this._devInsertBeforeId = 'end'
      this._devHoverStart = 0
    },

    // 取得 devId 在顯示順序中的「下一張」device（跳過自身），回傳 'dev_X' 或 'end'
    _devNextId(devId) {
      const list = this.deviceDisplayList()
      let found = false
      for (const entry of list) {
        if (entry.type === 'group') {
          for (const d of entry.devices) {
            if (found && d.id !== this._devDragId) return 'dev_' + d.id
            if (d.id === devId) found = true
          }
        } else if (entry.type === 'device') {
          if (found && entry.dev.id !== this._devDragId) return 'dev_' + entry.dev.id
          if (entry.dev.id === devId) found = true
        }
      }
      return 'end'
    },

    devDropOnDevice(e, targetDev) {
      e.preventDefault()
      const devs = this.cr.caseRecord.devices
      const dragged = devs.find(d => d.id === this._devDragId)
      if (!dragged || dragged.id === targetDev.id) { this.devDragEnd(); return }
      if (this._devGroupTarget === 'dev_' + targetDev.id) {
        // ── 合併成群組 ──
        const oldGid = dragged._groupId || ''
        if (targetDev._groupId) {
          dragged._groupId = targetDev._groupId; dragged._groupName = targetDev._groupName
          if (oldGid && oldGid !== targetDev._groupId) this._devReindex(devs, oldGid)
          this._devReindex(devs, targetDev._groupId)
        } else {
          const gid = 'grp_' + Date.now().toString(36)
          const gName = (targetDev.name || dragged.name || '設備群組').slice(0, 30)
          if (oldGid) { dragged._groupId = ''; this._devReindex(devs, oldGid) }
          targetDev._groupId = gid; targetDev._groupName = gName
          dragged._groupId   = gid; dragged._groupName   = gName
          this._devReindex(devs, gid)
          this._openDevGroups = { ...this._openDevGroups, [gid]: true }
        }
      } else {
        // ── 排序：依 _devInsertBeforeId 插入 ──
        const insertId = this._devInsertBeforeId
        const fromIdx = devs.indexOf(dragged)
        devs.splice(fromIdx, 1)
        if (!insertId || insertId === 'end') {
          devs.push(dragged)
        } else {
          const tid = parseInt(insertId.slice(4))
          const toIdx = devs.findIndex(d => d.id === tid)
          if (toIdx === -1) devs.push(dragged); else devs.splice(toIdx, 0, dragged)
        }
      }
      this.cr.caseRecord.devices = [...devs]
      this.devDragEnd()
      this.setDirty()
    },

    devDropOnGroup(e, groupId, groupName) {
      e.preventDefault()
      const devs = this.cr.caseRecord.devices
      const dragged = devs.find(d => d.id === this._devDragId)
      if (!dragged || dragged._groupId === groupId) { this.devDragEnd(); return }
      const oldGid = dragged._groupId || ''
      dragged._groupId = groupId; dragged._groupName = groupName
      if (oldGid) this._devReindex(devs, oldGid)
      this._devReindex(devs, groupId)
      this.cr.caseRecord.devices = [...devs]
      this.devDragEnd()
      this.setDirty()
    },

    devDropAtEnd(e) {
      e.preventDefault()
      const devs = this.cr.caseRecord.devices
      const dragged = devs.find(d => d.id === this._devDragId)
      if (!dragged) { this.devDragEnd(); return }
      const fromIdx = devs.indexOf(dragged)
      devs.splice(fromIdx, 1)
      devs.push(dragged)
      this.cr.caseRecord.devices = [...devs]
      this.devDragEnd()
      this.setDirty()
    },
    _devReindex(devs, groupId) {
      const members = devs.filter(d => d._groupId === groupId)
      if (members.length <= 1) {
        if (members[0]) { members[0]._groupId = ''; members[0]._groupName = ''; members[0]._groupIdx = 0; members[0]._groupTotal = 0 }
      } else {
        members.forEach((d, i) => { d._groupIdx = i + 1; d._groupTotal = members.length })
      }
    },
    devUngroupDevice(dev) {
      if (!dev._groupId) return
      const groupId = dev._groupId
      const devs = this.cr.caseRecord.devices
      dev._groupId = ''; dev._groupName = ''; dev._groupIdx = 0; dev._groupTotal = 0
      this._devReindex(devs, groupId)
      this.cr.caseRecord.devices = [...devs]
      this.setDirty()
    },

    deviceDisplayList() {
      const devices = this.cr.caseRecord?.devices || []
      const seenGroups = {}
      const groupOrder = []
      const groups = {}
      const ungrouped = []
      devices.forEach((dev, gi) => {
        if (dev._groupId) {
          if (!seenGroups[dev._groupId]) {
            seenGroups[dev._groupId] = true
            groupOrder.push(dev._groupId)
            groups[dev._groupId] = {
              id: 'group_' + dev._groupId,
              type: 'group',
              groupId: dev._groupId,
              groupName: dev._groupName || dev.name,
              groupTotal: dev._groupTotal || 0,
              devices: []
            }
          }
          groups[dev._groupId].devices.push(dev)
        } else {
          ungrouped.push({ id: 'dev_' + dev.id, type: 'device', dev, idx: gi })
        }
      })
      const result = []
      groupOrder.forEach(gid => result.push(groups[gid]))
      ungrouped.forEach(u => result.push(u))
      return result
    },
    syncAllWarranty() {
      if (!this._syncWarrantyDate) return
      const devs = this.cr.caseRecord?.devices || []
      devs.forEach(d => {
        d.warrantyStart   = this._syncWarrantyDate
        d.warrantyMonths  = this._syncWarrantyMonths
      })
      this.setDirty()
    },

    warrantyExpiry(start, months) {
      if (!start || !months) return ''
      const d = new Date(start)
      d.setMonth(d.getMonth() + (+months))
      return d.toLocaleDateString('zh-TW')
    },
    warrantyStatus(start, months) {
      if (!start || !months) return 'active'
      const expiry = new Date(start)
      expiry.setMonth(expiry.getMonth() + (+months))
      const daysLeft = Math.round((expiry - new Date()) / 86400000 /* 非金額 */)
      if (daysLeft < 0)  return 'expired'
      if (daysLeft < 90) return 'expiring'
      return 'active'
    },
    warrantyStatusLabel(start, months) {
      const s = this.warrantyStatus(start, months)
      if (s === 'expired')  return '已過保'
      if (s === 'expiring') return '即將到期'
      return '保固中'
    },

    daysUntilDeadline() {
      const endDate = this.cr.caseRecord?.projectTimeline?.endDate
      if (!endDate) return 0
      const deadline = new Date(endDate)
      const today = new Date()
      today.setHours(0, 0, 0, 0)
      deadline.setHours(0, 0, 0, 0)
      return Math.round((deadline - today) / 86400000 /* 非金額 */)
    },

    async openNetworkPlan() {
      const quoteNo = this.selected.quote_no
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/network-plan`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) {
          const d = await r.json()
          location.href = `network-plan-form.html?id=${d.id}`
          return
        }
        if (r.status !== 404) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '查詢失敗', {kind: 'error'}); return }
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}); return }

      const mods = this.session.modules || []
      const canEdit = ['superadmin', 'admin'].includes(this.session.role) || mods.indexOf('netplan_edit') >= 0
      if (!canEdit) { MotrixUI.toast('此案件尚無網路架構規劃書', {kind: 'info'}); return }
      if (!(await MotrixUI.confirm('此案件尚無網路架構規劃書，是否建立一份？'))) return
      try {
        const cr = await fetch('/api/network-plans', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ quoteNo })
        })
        if (!cr.ok) { MotrixUI.toast((await cr.json().catch(() => ({}))).detail || '建立失敗', {kind: 'error'}); return }
        const d = await cr.json()
        location.href = `network-plan-form.html?id=${d.id}`
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async uploadMaterialFiles(idx, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      if (!(await this._flushBeforeItemOp())) { evt.target.value = ''; return }
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/materials/${idx}/files${this._itemQs((this.cr.caseRecord.materials || [])[idx])}`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '上傳失敗', {kind: 'error'}); return }
        const body = await r.json()
        if (body.pending) { MotrixUI.toast(body.message || '已送出，待最高管理員審核後套用', {kind: 'ok'}); return }
        this._applyToBoth('materials', cr => {
          const mat = (cr.materials || [])[idx]
          if (mat) {
            if (!mat.files) mat.files = []
            mat.files.push(...body.files)
          }
        })
      } catch (e) { MotrixUI.toast('上傳失敗：' + e.message, {kind: 'error'}) }
      evt.target.value = ''
    },

    async deleteMaterialFile(idx, fileId) {
      if (!(await MotrixUI.confirm('確定刪除此附件？', {danger: true}))) return
      if (!(await this._flushBeforeItemOp())) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/materials/${idx}/files/${fileId}${this._itemQs((this.cr.caseRecord.materials || [])[idx])}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '刪除失敗', {kind: 'error'}); return }
        const body = await r.json()
        if (body.pending) { MotrixUI.toast(body.message || '已送出，待最高管理員審核後套用', {kind: 'ok'}); return }
        this._applyToBoth('materials', cr => {
          const mat = (cr.materials || [])[idx]
          if (mat && mat.files) mat.files = mat.files.filter(f => f.id !== fileId)
        })
      } catch (e) { MotrixUI.toast('刪除失敗：' + e.message, {kind: 'error'}) }
    },

    async uploadMaterialInvoiceFiles(idx, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      if (!(await this._flushBeforeItemOp())) { evt.target.value = ''; return }
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/materials/${idx}/invoice-files${this._itemQs((this.cr.caseRecord.materials || [])[idx])}`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '上傳失敗', {kind: 'error'}); return }
        const body = await r.json()
        if (body.pending) { MotrixUI.toast(body.message || '已送出，待最高管理員審核後套用', {kind: 'ok'}); return }
        this._applyToBoth('materials', cr => {
          const mat = (cr.materials || [])[idx]
          if (mat) {
            if (!mat.invoiceFiles) mat.invoiceFiles = []
            mat.invoiceFiles.push(...body.files)
          }
        })
      } catch (e) { MotrixUI.toast('上傳失敗：' + e.message, {kind: 'error'}) }
      evt.target.value = ''
    },

    async deleteMaterialInvoiceFile(idx, fileId) {
      if (!(await MotrixUI.confirm('確定刪除此發票附件？', {danger: true}))) return
      if (!(await this._flushBeforeItemOp())) return
      try {
        const r = await fetch(`/api/quotations/${this.selected.quote_no}/materials/${idx}/invoice-files/${fileId}${this._itemQs((this.cr.caseRecord.materials || [])[idx])}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '刪除失敗', {kind: 'error'}); return }
        const body = await r.json()
        if (body.pending) { MotrixUI.toast(body.message || '已送出，待最高管理員審核後套用', {kind: 'ok'}); return }
        this._applyToBoth('materials', cr => {
          const mat = (cr.materials || [])[idx]
          if (mat && mat.invoiceFiles) mat.invoiceFiles = mat.invoiceFiles.filter(f => f.id !== fileId)
        })
      } catch (e) { MotrixUI.toast('刪除失敗：' + e.message, {kind: 'error'}) }
    },

    // CM12 P2：切換案件時重設本模組的案件層級狀態（時點見 core 的 _resetCaseScoped）
    _reset_exec(phase, data) {
      if (phase === 'early') {
        // 材料申請的狀態也屬於「必須在 await 之前重設完」那一類（2026-09-14 修）：
        // selected 一設定分頁列就渲染出來，使用者可以立刻點「財務」，而下面
        // ensureCaseRecord()／_seedDefaultStagesIfEmpty() 是會發網路請求的 await
        // ——原本 moLoading 要等到那之後才立起來，這段空窗期點進財務分頁就會看到
        // 「尚無材料申請項目」，接著才跳成「載入中…」。全套測試偶發的紅燈就是它
        // （test_e2e_material_orders_2026_09_11.py，約 1/5 機率）。
        this.materialOrders = []
        this.moApprovals = {}; this.moPay = {}        // 31-C：審核摘要與匯款額度也是案件層級（沒重置會把前一件的狀態帶進這一件；c7 預審）
        this.moDirty = false
        this.moMsg = ''
        this.moLoading = true
      }
      if (phase === 'late') {
        this.showImportModal = false
        this._syncWarrantyDate = ''
        this._syncWarrantyMonths = 12
        this._openDevGroups = {}
        this.stageView = 'list'
        this._devDragId = null
        this._devDragOverId = null
        this._devInsertBeforeId = null
        this._devHoverGroupId = null
        this._devGroupTarget = null
        this._devHoverStart = 0
        this.caseActionItems = []
        this.assignedUserIds = data.assigned_user_ids || []
      }
    },
}))
