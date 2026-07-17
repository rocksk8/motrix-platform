  const API = '/api'
  // ── 報價單模板版本：調整版型/設計/UI 時手動更新此值 ──
  const FORM_VERSION = 'V1.1'

  function quotationForm() {
    return {
      API,
      showCostCols: true,
      isDirty: false,
      lastSaved: null,
      previewMode: null,
      needsApproval: false,
      approvalReasons: [],
      autoSaveTimer: null,
      isNewRecord: true,
      session: {},
      backendOnline: false,
      customers: [],
      suppliers: [],
      showCustomerDrop: false,
      customerSuggestions: [],
      customerDropIdx: 0,
      contactOptions: [],
      showContactPicker: false,
      showNavModal: false,
      pendingNav: null,
      unlocked: false,
      showUnlockModal: false,
      unlockPwd: '',
      unlockError: '',
      approvalNote: '',
      unlockLoading: false,
      showExportHistory: false,

      q: {
        quoteNo: '',
        quoteDate: new Date().toISOString().slice(0,10),
        validDays: 30,
        version: 1,
        status: '草稿',

        salesPerson: '',
        salesPhone:  '',
        salesEmail:  '',

        pdfShow: { taxId:true, contactName:true, contactPhone:true, contactEmail:true, contactFax:false, deliveryAddress:true },
        customerId: null,
        supplierId: null,
        customerName: '', customerTaxId: '', contactName: '',
        contactPhone: '', contactEmail: '', contactFax: '',
        deliveryAddress: '',

        projectName: '', deliveryLocation: '',

        items: [
          { id: 1, description: '', brand: '', qty: 1, unit: '台',
            cost: null, margin: 0.30, unitPrice: null, unitPriceOverride: false,
            amount: 0, notes: '' }
        ],

        discount: 0, showDiscount: false, freight: 0,
        taxRate: 5,
        approval: null,

        paymentTerms: `本專案總價款分三期給付，本報價不含運費與關稅，前述相關衍生費用由買方另行負擔。
第一期：定金款（總價款50%），買方給付本期款項後，本專案即確認執行，賣方應開立憑證予買方。
第二期：交貨款（總價款30%），設備運抵買方指定地點並完成硬體點交後，賣方得開立憑證請款，付款方式為賣方提交憑證之次月份25日支付。
第三期：驗收款（總價款20%），設備安裝、系統設定及缺失改善完成，並經買方驗收合格後，賣方得開立憑證請款，付款方式為賣方提交憑證之次月份25日支付。`,
        deliveryTerms: '送達買方指定地點；特殊地點或時段另計。',
        acceptanceTerms: `設備硬體自運抵交貨當日起即進行外觀與數量之點交；系統與安裝之最終驗收，依報價單雙方確認之規格與缺改清單辦理。
若因非可歸責於賣方之現場因素（如買方場地未備妥、裝潢延宕、原廠及代理商物件/設備到貨延宕等），致部分項目未能即時完成設定或測試，不影響已交付設備及已完成安裝部分之驗收效力。針對不影響系統主要運作功能之輕微瑕疵、文件補正或教育訓練補充，買方不得拒絕簽認驗收單。買賣標的物之利益及危險，自交付時起，均由買受人承受負擔。
賣方完成設備安裝與基礎設定並通知買方後，買受人應按物之性質，依通常程序從速檢查其所受領之物。如買方對完成內容有疑義，應於賣方通知之日起七日內以書面具體提出；逾期未辦理驗收或怠於為通知者，視為承認其所受領之物並驗收合格。此外，設備或系統若未經正式驗收程序，但買方已逕行投入實際業務營運或使用者，亦視同驗收完成。`,
        warrantyTerms: '設備依原廠保固公告內容為主。保固期間內之硬體故障，賣方將協助買方聯繫原廠進行處理；惟若屬非設備本身硬體瑕疵（如人為損壞、天災、不當使用、買方自行變更設定、架構等）或需賣方派員至現場排解之技術服務，賣方得另行收取檢修與出勤服務費用。',
        afterSales: '上班時段電話/E-mail技術支援；到場服務依當時報價計費。',

        indirectLogistics: 0, indirectInstallation: 0,
        indirectTravel: 0,   indirectWarranty: 0, indirectOther: 0,
        assumedTaxRate: 0,

        exportCount: 0,
        exportLog: [],
        dealTag: '',
        caseRecord: null,
      },

      tot: {
        subtotal:0, pretax:0, tax:0, total:0,
        totalCost:0, inputVat:0, directProfit:0,
        directMarginPct:0, adminCost:0, charityDonation:0, totalIndirect:0,
        netProfit:0, netMarginPct:0,
      },

      /* ── 定義公式 ── */
      calcUnitPrice(cost, margin) {
        if (!cost || cost <= 0 || margin >= 1) return 0
        const base = Math.ceil(cost * 1.05 / (1 - margin) / 5) * 5
        const rem  = base % 100
        if (rem > 50) return Math.ceil(base / 100) * 100
        if (rem > 0)  return Math.ceil(base / 100) * 100 - 50
        return base
      },

      calcItem(item) {
        if (!item.unitPriceOverride && item.cost > 0) {
          item.unitPrice = this.calcUnitPrice(item.cost, item.margin)
        }
        item.amount = Math.round((item.qty || 0) * (item.unitPrice || 0))
        this.calcTotals()
      },

      calcTotals() {
        const items = this.q.items
        const subtotal   = items.reduce((s,i) => s + (i.amount||0), 0)
        const totalCost  = items.reduce((s,i) => s + (i.qty||0)*(i.cost||0), 0)
        const inputVat   = Math.round(totalCost * 0.05)
        const pretax     = subtotal - (this.q.discount||0) + (this.q.freight||0)
        const salesTaxRate = (this.q.taxRate !== undefined ? this.q.taxRate : 5) / 100
        const tax        = Math.round(pretax * salesTaxRate)
        const total      = pretax + tax
        const directProfit    = pretax - totalCost - inputVat
        const directMarginPct = pretax > 0 ? directProfit / pretax * 100 : 0
        const adminCost       = Math.round(pretax * 0.10)
        const charityDonation = Math.round(directProfit * 0.01)
        const totalIndirect   = adminCost + charityDonation +
          (this.q.indirectLogistics||0) + (this.q.indirectInstallation||0) +
          (this.q.indirectTravel||0)    + (this.q.indirectWarranty||0)    +
          (this.q.indirectOther||0)
        const netProfit    = directProfit - totalIndirect
        const netMarginPct = pretax > 0 ? netProfit / pretax * 100 : 0

        this.tot = { subtotal, pretax, tax, total,
          totalCost, inputVat, directProfit,
          directMarginPct: Math.round(directMarginPct*10)/10,
          adminCost, charityDonation, totalIndirect,
          netProfit: Math.round(netProfit),
          netMarginPct: Math.round(netMarginPct*10)/10,
        }
      },

      addItem() {
        const id = Date.now()
        this.q.items.push({ id, description:'', brand:'', qty:1, unit:'台',
          cost:null, margin:0.30, unitPrice:null, unitPriceOverride:false, amount:0, notes:'' })
        this.setDirty()
      },

      removeItem(idx) {
        if (this.q.items.length === 1) { alert('至少保留一項'); return }
        this.q.items.splice(idx, 1)
        this.calcTotals()
        this.setDirty()
      },

      checkApproval() {
        if (this.q.approval?.status === 'approved') {
          this.needsApproval = false
          this.approvalReasons = []
          return
        }
        const reasons = []
        if (this.q.validDays > 30)
          reasons.push(`有效期限 ${this.q.validDays} 天（超過 30 天）`)
        this.q.items.forEach((item, i) => {
          if (item.cost > 0 && item.margin < 0.30)
            reasons.push(`第 ${i+1} 項毛利率 ${(item.margin*100).toFixed(2)}% 低於 30%`)
        })
        if (this.q.showDiscount && this.q.discount > 0)
          reasons.push(`含折讓（NT$${this.q.discount.toLocaleString()}）`)
        const taxRate = this.q.taxRate !== undefined ? this.q.taxRate : 5
        if (taxRate < 5)
          reasons.push(`調整營業稅額為 ${taxRate}%（標準 5%）`)
        this.approvalReasons = reasons
        this.needsApproval = reasons.length > 0
      },

      setDirty() {
        this.isDirty = true
        clearTimeout(this.autoSaveTimer)
        this.autoSaveTimer = setTimeout(() => this.autoSave(), 60000) // 60s auto
      },

      /* ── API helpers ── */
      buildTermsHtml() {
        const esc = s => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>')
        const ts = 'font-size:10px;color:#999;font-weight:600;margin-bottom:3px'
        const vs = 'font-size:11px;color:#555;line-height:1.7'
        const block = t => `<div style="margin-bottom:10px"><div style="${ts}">${t.title}</div><div style="${vs}">${esc(t.text)}</div></div>`
        const pair = (a, b) => {
          const aOk = (a.text||'').trim(), bOk = (b.text||'').trim()
          if (!aOk && !bOk) return ''
          if (!aOk) return block(b)
          if (!bOk) return block(a)
          const useTwoCols = (a.text||'').length <= 300 && (b.text||'').length <= 300
          if (useTwoCols)
            return `<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:4px"><div>${block(a)}</div><div>${block(b)}</div></div>`
          return block(a) + block(b)
        }
        let html = ''
        if ((this.q.paymentTerms||'').trim()) html += block({ title: '付款條件', text: this.q.paymentTerms })
        html += pair({ title: '交貨條件', text: this.q.deliveryTerms }, { title: '驗收標準', text: this.q.acceptanceTerms })
        html += pair({ title: '保固條件', text: this.q.warrantyTerms }, { title: '售後服務', text: this.q.afterSales })
        return html
      },

      async apiSave(isNew) {
        const payload = { quote_no: this.q.quoteNo, status: this.q.status, data: { ...this.q, tot: this.tot }, created_by: this.session?.username }
        try {
          const method = isNew ? 'POST' : 'PUT'
          const url    = isNew ? `${this.API}/quotations` : `${this.API}/quotations/${this.q.quoteNo}`
          const res    = await fetch(url, { method, headers:{'Content-Type':'application/json', Authorization:'Bearer '+this.session.token}, body: JSON.stringify(payload) })
          if (!res.ok) throw new Error(await res.text())
          if (isNew) {
            // Backend may have assigned a different number if provisional was taken
            const d = await res.json()
            if (d.quote_no && d.quote_no !== this.q.quoteNo) {
              this.q.quoteNo = d.quote_no
              history.replaceState(null, '', '?id=' + d.quote_no)
            }
          }
          return true
        } catch(e) {
          console.warn('API 儲存失敗（後端未啟動）', e.message)
          return false
        }
      },

      autoSave() {
        this.apiSave(this.isNewRecord).then(ok => {
          if (ok) {
            this.isNewRecord = false
            sessionStorage.removeItem('motrix_new_quote_no')
          }
        })
        this.isDirty = false
        const now = new Date()
        this.lastSaved = now.toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit'})
      },

      get _isAdmin() {
        const r = this.session.role || ''
        return r === 'admin' || r === 'superadmin'
      },

      _allCombined() {
        const cs = this.customers.map(c => ({...c, _type: 'customer'}))
        const ss = this._isAdmin ? this.suppliers.map(s => ({...s, _type: 'supplier'})) : []
        return [...cs, ...ss]
      },

      onCustomerInput() {
        const kw = (this.q.customerName || '').trim().toLowerCase()
        if (!kw) { this.showAllCustomers(); return }
        this.customerSuggestions = this._allCombined()
          .filter(c => c.name && c.name.toLowerCase().includes(kw)).slice(0, 20)
        this.customerDropIdx = 0
        this.showCustomerDrop = this.customerSuggestions.length > 0
      },

      showAllCustomers() {
        const all = this._allCombined()
        if (!all.length) { this.showCustomerDrop = false; return }
        this.customerSuggestions = all.slice(0, 25)
        this.customerDropIdx = 0
        this.showCustomerDrop = true
      },

      toggleCustomerList() {
        if (this.showCustomerDrop) { this.showCustomerDrop = false; return }
        this.showAllCustomers()
      },

      selectCustomer(c) {
        this.q.customerName = c.name
        if (c._type === 'supplier') {
          this.q.supplierId = c.id
          this.q.customerId = null
        } else {
          this.q.customerId  = c.id
          this.q.supplierId  = null
        }
        if (c.taxId && !this.q.customerTaxId) this.q.customerTaxId = c.taxId
        const addr = c.deliveryAddress || c.invoiceAddress || c.address || ''
        if (addr && !this.q.deliveryAddress) this.q.deliveryAddress = addr

        // 建立聯絡人快選清單
        const opts = []
        if (c.phone || c.email || c.fax) {
          opts.push({ _display: '公司主線', name: '', phone: c.phone || '', email: c.email || '', fax: c.fax || '' })
        }
        for (const ct of (c.contacts || [])) {
          if (!ct.name && !ct.phone && !ct.email) continue
          opts.push({
            _display: [ct.name, ct.title].filter(Boolean).join(' · '),
            name: ct.name || '', phone: ct.phone || '', email: ct.email || '', fax: ''
          })
        }
        this.contactOptions = opts
        this.showContactPicker = false

        // 換公司時清空舊聯絡人，填入新公司第一筆
        this.q.contactName  = ''
        this.q.contactPhone = ''
        this.q.contactEmail = ''
        this.q.contactFax   = ''
        if (c.phone) this.q.contactPhone = c.phone
        const ct = c.contacts && c.contacts[0]
        if (ct) {
          if (ct.name)  this.q.contactName  = ct.name
          if (ct.phone) this.q.contactPhone  = ct.phone
          if (ct.email) this.q.contactEmail  = ct.email
        }
        this.showCustomerDrop = false
        this.setDirty()
      },

      applyContact(ct) {
        if (ct.name)  this.q.contactName  = ct.name
        if (ct.phone) this.q.contactPhone = ct.phone
        if (ct.email) this.q.contactEmail = ct.email
        if (ct.fax)   this.q.contactFax   = ct.fax
        this.showContactPicker = false
        this.setDirty()
      },

      async checkAndCreateCustomer() {
        const name = (this.q.customerName || '').trim()
        if (!name) return
        if (this.q.customerId || this.q.supplierId) return
        // Auto-link if exact name match exists
        const match = this.customers.find(c => (c.name || '').trim() === name)
        if (match) { this.q.customerId = match.id; return }
        // Prompt to create
        if (!confirm(`「${name}」在客戶管理中尚無資料，是否建立客戶檔案？`)) return
        try {
          const body = {
            name,
            tax_id: this.q.customerTaxId || '',
            phone:  this.q.contactPhone  || '',
            data: {
              contacts: this.q.contactName ? [{
                name:  this.q.contactName,
                phone: this.q.contactPhone || '',
                email: this.q.contactEmail || ''
              }] : [],
              invoiceAddress: this.q.deliveryAddress || ''
            }
          }
          const res = await fetch(`${this.API}/customers`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify(body)
          })
          if (res.ok) {
            const nc = await res.json()
            this.q.customerId = nc.id
            this.customers.push({ id: nc.id, name, taxId: body.tax_id, phone: body.phone, contacts: body.data.contacts })
            this.toast('✓ 客戶「' + name + '」已建立至客戶管理')
          }
        } catch(e) { console.warn('建立客戶失敗', e) }
      },

      onDealTagChange(newTag) {
        // 未成案/已成案 限管理員以上
        if (['未成案', '已成案'].includes(newTag)) {
          const role = this.session?.role || ''
          if (!['superadmin', 'admin'].includes(role)) {
            this._showToast('僅管理員以上可標記「未成案」或「已成案」', 2500)
            this.$nextTick(() => { this.q.dealTag = this.q.dealTag }) // revert select
            return
          }
        }
        if (newTag === '已成案') {
          if (!confirm(`確認將報價單標記為「已成案」？\n\n確認後案件進度將鎖定，僅能透過「案件管理」頁面完結案件。\n此操作將記錄操作紀錄。`)) {
            return
          }
          this.ensureCaseRecord()
        }
        const oldTag = this.q.dealTag || ''
        this.q.dealTag = newTag
        this.isDirty = true
        if (this.q.status === '已送出') {
          this.saveDraft().then(() => {
            // also record log entry via deal-tag endpoint
            const entry = { at: new Date().toISOString(), user: this.session?.displayName || '', from: oldTag, to: newTag }
            fetch(`/api/quotations/${this.q.quoteNo}/deal-tag`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ deal_tag: newTag, log_entry: entry })
            }).catch(() => {})
          })
        }
      },

      async saveDraft() {
        if (!this.q.quoteNo) {
          const ym  = new Date().toISOString().slice(0,7).replace('-','')
          this.q.quoteNo = `MQ-${ym}-001`
        }
        if (!new URLSearchParams(window.location.search).has('id')) {
          history.replaceState(null, '', '?id=' + this.q.quoteNo)
        }
        const wasNew = this.isNewRecord
        this.isNewRecord = false
        sessionStorage.removeItem('motrix_new_quote_no')
        const wasUnlocked = this.unlocked
        if (wasUnlocked) this.q._isUnlockEdit = true
        const res = await this.apiSave(wasNew).catch(() => null)
        delete this.q._isUnlockEdit
        if (!res) { alert('儲存失敗，請確認後端伺服器是否在線'); return }
        this.isDirty = false
        if (this.unlocked) this.unlocked = false

        // Unlock-edit → backend forces status back to 待審核
        if (wasUnlocked) {
          this.q.status = '待審核'
          this.q.approval = this.q.approval || { status: 'pending', isEditApproval: true }
        }

        const now = new Date()
        this.lastSaved = now.toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit'})
        const msg = document.createElement('div')
        msg.textContent = wasUnlocked
          ? '✓ 報價單修改已送出審核，等待主管簽核通過'
          : '✓ 草稿已儲存'
        msg.style.cssText = 'position:fixed;bottom:32px;left:50%;transform:translateX(-50%);background:#0A0A0A;color:#F5F4F0;padding:10px 22px;border-radius:8px;font-size:13px;z-index:99999;font-family:Inter,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.3);letter-spacing:.02em'
        document.body.appendChild(msg)
        setTimeout(() => { msg.style.opacity='0'; msg.style.transition='opacity .4s'; setTimeout(() => msg.remove(), 400) }, wasUnlocked ? 3500 : 2200)
        await this.checkAndCreateCustomer()
      },

      openPreview(mode) {
        this.previewMode = mode
        this.$nextTick(() => this._applyPreviewScale())
      },

      _applyPreviewScale() {
        const wrap = document.querySelector('.preview-wrap')
        const page = document.getElementById('pdf-preview-content')
        if (!wrap || !page) return
        const available = wrap.clientWidth - 32  // 16px padding each side
        const s = Math.min(1, available / 800)
        page.style.zoom = s < 0.999 ? s.toFixed(4) : ''
      },


      exportPDF(mode) {
        const isInternal = mode === 'internal'
        if (this.backendOnline && this.q.quoteNo) {
          // Record export with user info first, then use server's authoritative counts
          fetch(`${this.API}/quotations/${this.q.quoteNo}/export?mode=${mode}`, {
            method: 'POST', headers: { Authorization: 'Bearer ' + this.session.token }
          }).then(r => r.ok ? r.json() : null).then(data => {
            if (data) {
              this.q.exportCount = data.export_count
              this.q.exportLog = data.log
            }
          }).catch(() => {})
          // 後端 Edge Headless 產生 PDF 下載：對外版 + 內部版均走此路徑
          // 避免瀏覽器 popup 在 macOS 系統 PDF 路徑產生日期/about:blank 頁首
          const url = `${this.API}/quotations/${this.q.quoteNo}/pdf-download?internal=${isInternal}`
          fetch(url, { headers: { Authorization: 'Bearer ' + this.session.token } })
          .then(r => { if (!r.ok) throw new Error(r.status); return r.blob() })
          .then(blob => {
            const fname = isInternal ? `${this.q.quoteNo}_內部.pdf` : `${this.q.quoteNo}.pdf`
            const a = document.createElement('a')
            a.href = URL.createObjectURL(blob)
            a.download = fname
            document.body.appendChild(a)
            a.click()
            document.body.removeChild(a)
            URL.revokeObjectURL(a.href)
          })
          .catch(() => alert('PDF 產生失敗，請確認伺服器狀態後重試'))
        } else {
          alert('尚未存檔或伺服器離線，請先儲存報價單再匯出 PDF')
        }
      },

      canApproveCurrentTier() {
        if (!['待審核', '簽核中'].includes(this.q.status)) return false
        const appr  = this.q.approval || {}
        const tiers = appr.tiers || []
        const ct    = appr.currentTier ?? 0
        if (tiers.length > 0 && ct < tiers.length) {
          const tier = tiers[ct]
          const approvers = tier.approvers || []
          const me = approvers.find(a => a.username === this.session.username)
          return !!(me && me.status !== 'approved')
        }
        // 無流程設定：superadmin 且非申請人
        return this.session.role === 'superadmin' && appr.requestedBy !== this.session.username
      },

      hasAlreadyApproved() {
        if (!['待審核', '簽核中'].includes(this.q.status)) return false
        const tiers = (this.q.approval || {}).tiers || []
        return tiers.some(tier =>
          (tier.approvers || []).some(a => a.username === this.session.username && a.status === 'approved')
        )
      },

      currentTierPendingText() {
        const appr  = this.q.approval || {}
        const tiers = appr.tiers || []
        const ct    = appr.currentTier ?? 0
        if (ct < tiers.length) {
          const pending = (tiers[ct].approvers || []).filter(a => a.status !== 'approved')
          if (!pending.length) return ''
          const names = pending.map(a => a.displayName || a.username).join('、')
          return `第 ${ct + 1} 層待簽核：${names}`
        }
        return ''
      },

      get displayStatus() {
        const s   = this.q.status
        const tag = this.q.dealTag || ''
        if (s === '已送出') {
          if (tag === '已成案') return '執行中'
          if (tag === '已結案') return '已結案'
          if (tag === '未成案') return '未成案'
        }
        return s
      },

      get displayStatusClass() {
        const ds = this.displayStatus
        const map = {
          '草稿':  'badge--draft',
          '待審核': 'badge--pending',
          '簽核中': 'badge--signing',
          '已核准': 'badge--approved',
          '已送出': 'badge--sent',
          '已拒絕': 'badge--rejected',
          '執行中': 'badge--running',
          '已結案': 'badge--settled',
          '未成案': 'badge--lost',
        }
        return map[ds] || ''
      },

      async returnQuote() {
        const note = this.approvalNote.trim()
        const req  = this.q.approval || {}
        const who  = req.requestedByDisplay || req.requestedBy || '（未知）'
        if (!confirm(`退回此報價單給申請人重新修改？\n\n申請人：${who}\n退回後單號將自動升版（加 -Rn 後綴），申請人可修改後重新送審。\n\n${note ? '退回原因：' + note : '（未填退回原因）'}`)) return
        try {
          const r = await fetch(`${this.API}/quotations/${this.q.quoteNo}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({ note, approvedByDisplay: this.session.displayName || this.session.username })
          })
          if (!r.ok) throw new Error(await r.text())
          const data = await r.json()
          this.previewMode  = null
          this.approvalNote = ''
          const newNo = data.new_quote_no
          this._showToast(`↩ 已退回，單號更新為 ${newNo}`)
          setTimeout(() => { window.location.href = `quotation-form.html?id=${newNo}` }, 1000)
        } catch(e) {
          alert('退回失敗：' + (e.message || '請重試'))
        }
      },

      async rejectFinalQuote() {
        const note = this.approvalNote.trim()
        const req  = this.q.approval || {}
        const who  = req.requestedByDisplay || req.requestedBy || '（未知）'
        if (!confirm(`確定拒絕並永久結案此報價單？\n\n申請人：${who}\n${note ? '拒絕原因：' + note : '（未填拒絕原因）'}\n\n⚠ 此操作不可逆，報價單將永久鎖定。`)) return
        try {
          const r = await fetch(`${this.API}/quotations/${this.q.quoteNo}/reject-final`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({ note, approvedByDisplay: this.session.displayName || this.session.username })
          })
          if (!r.ok) throw new Error(await r.text())
          this.previewMode  = null
          this.approvalNote = ''
          this.q.status     = '已拒絕'
          this.q.rejection  = {
            rejectedBy:        this.session.username,
            rejectedByDisplay: this.session.displayName || this.session.username,
            rejectedAt:        new Date().toISOString(),
            note
          }
          this._showToast('✗ 報價單已拒絕結案')
        } catch(e) {
          alert('拒絕操作失敗：' + (e.message || '請重試'))
        }
      },

      _showToast(msg, duration = 2500) {
        const el = document.createElement('div')
        el.textContent = msg
        el.style.cssText = 'position:fixed;bottom:32px;left:50%;transform:translateX(-50%);background:#0A0A0A;color:#F5F4F0;padding:10px 22px;border-radius:8px;font-size:13px;z-index:99999;font-family:Inter,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.3)'
        document.body.appendChild(el)
        setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .4s'; setTimeout(() => el.remove(), 400) }, duration)
      },

      openExportHistory() {
        this.showExportHistory = true
      },

      fmtExportAt(isoStr) {
        if (!isoStr) return ''
        const d = new Date(isoStr)
        return d.toLocaleDateString('zh-TW') + ' ' + d.toLocaleTimeString('zh-TW', { hour:'2-digit', minute:'2-digit', second:'2-digit' })
      },

      async approveQuote() {
        if (!this.canApproveCurrentTier()) {
          alert('您目前沒有此簽核層的審核權限')
          return
        }
        const req        = this.q.approval || {}
        const tiers      = req.tiers || []
        const ct         = req.currentTier ?? 0
        const totalTiers = tiers.length
        const reqTime    = req.requestedAt ? new Date(req.requestedAt).toLocaleString('zh-TW') : ''
        const reasonList = (req.reasons || []).map(r => '  · ' + r).join('\n')
        const tierInfo   = totalTiers > 1 ? `\n簽核層：第 ${ct + 1} 層 / 共 ${totalTiers} 層` : ''
        if (!confirm(
          `確認簽核此報價單？${tierInfo}\n\n申請人：${req.requestedByDisplay || req.requestedBy || ''}\n申請時間：${reqTime}${reasonList ? '\n\n審核原因：\n' + reasonList : ''}`
        )) return
        try {
          const r = await fetch(`${this.API}/quotations/${this.q.quoteNo}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({
              note: this.approvalNote.trim(),
              approvedByDisplay: this.session.displayName || this.session.username
            })
          })
          if (!r.ok) throw new Error(await r.text())
          const data = await r.json()
          this.approvalNote = ''
          this.previewMode  = null
          // Reload from server to get the actual post-approve state
          const res2 = await fetch(`${this.API}/quotations/${this.q.quoteNo}`, {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (res2.ok) {
            const row = await res2.json()
            Object.assign(this.q, row.data)
            this.q.quoteNo = this.q.quoteNo  // keep ref
          }
          this.needsApproval   = false
          this.approvalReasons = []
          if (data.allDone) {
            this._showToast('✓ 所有層簽核完成，報價單已送出')
          } else {
            this._showToast(`✓ 第 ${ct + 1} 層簽核完成，等待下一層審核`)
          }
        } catch(e) {
          alert('簽核失敗：' + (e.message || '請重試'))
        }
      },

      async submitQuote() {
        if (!this.q.customerName) { alert('請填寫客戶名稱'); return }
        if (!this.q.projectName)  { alert('請填寫案件名稱'); return }
        const reasons = this.approvalReasons.length > 0
          ? [...this.approvalReasons]
          : ['標準報價單送出']
        const warningText = this.approvalReasons.length > 0
          ? `\n\n⚠ 含特殊條件，需主管確認：\n${reasons.map(r => '  · ' + r).join('\n')}`
          : ''
        if (!confirm(`申請送出報價單 ${this.q.quoteNo} 給 ${this.q.customerName}？\n\n送出後需由主管簽核，簽核通過後報價單狀態將更新為「已送出」。${warningText}`)) return
        this.q.status = '待審核'
        this.q.approval = {
          requestedBy: this.session.username,
          requestedByDisplay: this.session.displayName || this.session.username,
          requestedByRole: this.session.role,
          requestedAt: new Date().toISOString(),
          approvedBy: null,
          approvedByDisplay: null,
          approvedAt: null,
          status: 'pending',
          reasons
        }
        const saved = await this.apiSave(this.isNewRecord)
        if (!saved) {
          this.q.status   = '草稿'
          this.q.approval = null
          this._showToast('❌ 送審失敗，請確認後端伺服器是否在線', 3000)
          return
        }
        this.isNewRecord = false
        this.isDirty = false
        // 重新從伺服器載入，確保 tiers 等後端補齊的欄位同步到前端
        if (this.backendOnline && this.q.quoteNo) {
          try {
            const res = await fetch(`${this.API}/quotations/${this.q.quoteNo}`, {
              headers: { Authorization: 'Bearer ' + this.session.token }
            })
            if (res.ok) { const row = await res.json(); Object.assign(this.q, row.data || {}) }
          } catch (_) {}
        }
        const msg = document.createElement('div')
        msg.textContent = '✓ 已送出審核申請，等待主管簽核'
        msg.style.cssText = 'position:fixed;bottom:32px;left:50%;transform:translateX(-50%);background:#0A0A0A;color:#F5F4F0;padding:10px 22px;border-radius:8px;font-size:13px;z-index:99999;font-family:Inter,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.3)'
        document.body.appendChild(msg)
        setTimeout(() => { msg.style.opacity='0'; msg.style.transition='opacity .4s'; setTimeout(() => msg.remove(), 400) }, 2800)
      },

      async copyToNew() {
        let newNo = ''
        if (this.backendOnline) {
          try {
            const r = await fetch(`${this.API}/next-quote-no`, { headers: { Authorization: 'Bearer ' + this.session.token } })
            if (r.ok) newNo = (await r.json()).quote_no
          } catch {}
        }
        if (!newNo) {
          const m = new Date()
          newNo = `MQ-${m.getFullYear()}${String(m.getMonth()+1).padStart(2,'0')}-???`
        }
        const template = {
          ...this.q,
          quoteNo: newNo,
          quoteDate: new Date().toISOString().slice(0,10),
          status: '草稿',
          approval: null,
          exportCount: 0,
          exportLog: [],
          version: 1,
        }
        template.items = (this.q.items || []).map(it => ({...it, id: Date.now() + Math.random()}))
        sessionStorage.setItem('motrix_copy_template', JSON.stringify(template))
        sessionStorage.setItem('motrix_new_quote_no', newNo)
        window.location.href = `quotation-form.html?id=${newNo}`
      },

      /* ─── 案件追蹤 ───────────────────────────────────── */
      ensureCaseRecord() {
        if (!this.q.caseRecord) {
          this.q.caseRecord = {
            stages: [
              { id: 1, label: '訂單確認', done: false, doneAt: '' },
              { id: 2, label: '叫料到貨', done: false, doneAt: '' },
              { id: 3, label: '施工安裝', done: false, doneAt: '' },
              { id: 4, label: '客戶驗收', done: false, doneAt: '' },
              { id: 5, label: '尾款結清', done: false, doneAt: '' },
            ],
            payment: { received: 0, invoiced: false, invoiceNo: '', note: '' },
            materials: [],
            devices: [],
            warrantyNote: '',
            notes: '',
          }
        }
        if (!this.q.caseRecord.stages)  this.q.caseRecord.stages  = []
        if (!this.q.caseRecord.payment) this.q.caseRecord.payment  = { received: 0, invoiced: false, invoiceNo: '', note: '' }
        if (!this.q.caseRecord.materials) this.q.caseRecord.materials = []
        if (!this.q.caseRecord.devices)   this.q.caseRecord.devices   = []
      },

      sidebarClick(e) {
        const a = e.target.closest('a[href]')
        if (!a) return
        const href = a.getAttribute('href')
        if (!href || href === '#') return
        if (!this.isDirty) return
        e.preventDefault()
        e.stopPropagation()
        this.pendingNav = a.href
        this.showNavModal = true
      },

      navGuard(url) {
        if (!this.isDirty) { window.location.href = url; return }
        this.pendingNav = url
        this.showNavModal = true
      },

      navSave() {
        this.saveDraft()
        const url = this.pendingNav
        this.showNavModal = false
        this.pendingNav = null
        setTimeout(() => { window.location.href = url }, 300)
      },

      navDiscard() {
        this.isDirty = false
        const url = this.pendingNav
        this.showNavModal = false
        this.pendingNav = null
        window.location.href = url
      },

      navCancel() {
        this.showNavModal = false
        this.pendingNav = null
      },

      async doUnlock() {
        if (!this.unlockPwd) { this.unlockError = '請輸入解鎖密碼'; return }
        this.unlockLoading = true
        this.unlockError = ''
        try {
          const res = await fetch('/api/auth/verify-unlock', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (this.session?.token || '') },
            body: JSON.stringify({ password: this.unlockPwd, ref: this.q.quoteNo })
          })
          if (res.ok) {
            this.unlocked = true
            this.showUnlockModal = false
            this.unlockPwd = ''
          } else {
            const d = await res.json().catch(() => ({}))
            this.unlockError = d.detail || '解鎖密碼不正確'
          }
        } catch(e) {
          this.unlockError = '連線失敗，請確認後端服務'
        } finally {
          this.unlockLoading = false
        }
      },

      async init() {
        // ── Session guard ──
        const s = localStorage.getItem('motrix_session')
        if (!s) { window.location.href = 'login.html'; return }
        try {
          this.session = JSON.parse(s)
        } catch(e) { window.location.href = 'login.html'; return }

        // ── 帶入業務員資料（從後端 API 取最新顯示名稱），同時以回應結果判斷後端是否在線 ──
        try {
          const ur = await fetch(`${this.API}/users`, {
            headers: { 'Authorization': `Bearer ${this.session.token}` }
          })
          this.backendOnline = true
          if (ur.status === 401) { this.logout && this.logout(); return }
          if (ur.ok) {
              const users = await ur.json()
              const me = users.find(u => u.username === this.session.username)
              if (me) {
                this._me = me
                this.q.salesPerson = me.displayName || me.username
                this.q.salesPhone  = me.phone  || ''
                this.q.salesEmail  = me.email  || ''
                /* 同步更新 session 快取 */
                if (me.displayName && me.displayName !== this.session.displayName) {
                  this.session.displayName = me.displayName
                  try {
                    const ss = JSON.parse(localStorage.getItem('motrix_session') || '{}')
                    ss.displayName = me.displayName
                    localStorage.setItem('motrix_session', JSON.stringify(ss))
                  } catch {}
                }
              }
            }
          } catch(e) { this.backendOnline = false }
        if (!this.q.salesPerson && this.session.displayName) {
          this.q.salesPerson = this.session.displayName
        }

        // ── 載入客戶 & 供應商資料（後端為唯一來源）──
        try {
          const rc = await fetch(`${this.API}/customers`, { headers: { Authorization: 'Bearer ' + this.session.token } })
          if (rc.ok) this.customers = await rc.json()
        } catch(e) {}
        // 供應商下拉僅限管理員以上
        if (this._isAdmin) {
          try {
            const rs = await fetch(`${this.API}/suppliers`, { headers: { Authorization: 'Bearer ' + this.session.token } })
            if (rs.ok) this.suppliers = await rs.json()
          } catch(e) {}
        }

        // ── 從 URL 讀取報價單號 ──
        const params  = new URLSearchParams(window.location.search)
        const editNo  = params.get('id')

        // ── 複製模式：從 sessionStorage 載入繼承內容 ──
        const copyTemplate = sessionStorage.getItem('motrix_copy_template')
        if (editNo && copyTemplate) {
          try {
            const t = JSON.parse(copyTemplate)
            if (t.quoteNo === editNo) {
              sessionStorage.removeItem('motrix_copy_template')
              sessionStorage.removeItem('motrix_new_quote_no')
              Object.assign(this.q, t)
              this.isNewRecord = true
              this.isDirty = true
              this.calcTotals()
              this.checkApproval()
              return
            }
          } catch(e) {}
        }

        if (editNo) {
          // ── 編輯模式：優先從後端載入 ──
          this.q.quoteNo   = editNo
          this.isNewRecord = false
          let loaded = false
          try {
            const res  = await fetch(`${this.API}/quotations/${editNo}`, { headers: { Authorization: 'Bearer ' + this.session.token } })
            if (res.ok) {
              const row = await res.json()
              Object.assign(this.q, row.data)
              this.q.quoteNo = editNo
              // 舊報價單若 salesPerson 是過期硬編碼預設值，改用當前登入者
              const _OLD = ['Corbin Chang', 'corbin chang', '']
              if (_OLD.includes((this.q.salesPerson || '').trim()) && this._me) {
                this.q.salesPerson = this._me.displayName || this._me.username
                this.q.salesPhone  = this._me.phone || ''
                this.q.salesEmail  = this._me.email || ''
              }
              loaded = true
            } else if (res.status === 401) { this.logout && this.logout(); return }
          } catch(e) {}
          if (!loaded) {
            this.toast('載入失敗，請確認後端伺服器連線')
          }
        } else {
          // ── 新增模式：同月已預留則沿用，否則向系統申請新號（後端同步更新 quote_seq）──
          const curMonth = new Date().toISOString().slice(0, 7).replace('-', '')
          const cached   = sessionStorage.getItem('motrix_new_quote_no')
          if (cached && cached.startsWith(`MQ-${curMonth}-`)) {
            this.q.quoteNo = cached
          } else {
            try {
              const _nc = new AbortController()
              setTimeout(() => _nc.abort(), 3000)
              const res = await fetch(`${this.API}/next-quote-no`, { signal: _nc.signal, headers: { Authorization: 'Bearer ' + this.session.token } })
              if (res.ok) {
                const d = await res.json()
                this.q.quoteNo = d.quote_no
                sessionStorage.setItem('motrix_new_quote_no', d.quote_no)
              }
            } catch(e) {}
          }
          if (!this.q.quoteNo) {
            this.toast('無法取得報價單號，請確認後端連線')
          }
          this.isNewRecord = true
        }

        this.calcTotals()
        this.checkApproval()
        if (this.q.dealTag === '已成案') this.ensureCaseRecord()

        if (this.lastSaved) {
          const now = new Date()
          this.lastSaved = now.toLocaleTimeString('zh-TW',{hour:'2-digit',minute:'2-digit'})
        }

        window.addEventListener('resize', () => {
          if (this.previewMode) this._applyPreviewScale()
        })
      },

      logout() {
        fetch(`${this.API}/auth/logout`, { method:'POST', headers:{ Authorization:'Bearer '+(this.session.token||'') } }).catch(()=>{})
        localStorage.removeItem('motrix_session'); window.location.href = 'login.html'
      }
    }
  }
