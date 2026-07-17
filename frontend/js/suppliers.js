  const API = '/api'

  async function fetchT(url, opts = {}, ms = 10000) {
    const ctrl  = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), ms)
    try {
      const r = await fetch(url, { ...opts, signal: ctrl.signal })
      clearTimeout(timer)
      return r
    } catch(e) { clearTimeout(timer); throw e }
  }

  function suppliersPage() {
    return {
      session: {},
      suppliers: [],
      search: '',
      filterCategory: '',
      showModal: false,
      isDirty: false,
      editingId: null,
      selectedId: null,
      formError: '',
      form: {},
      taxIdSearch: '',
      lookingUp: false,
      lookupMsg: '',
      lookupOk: false,
      tagInput: '',
      tagPresets: [],
      showAddPreset: false,
      newPreset: '',
      showImportModal: false,
      importing: false,
      importResults: null,

      async init() {
        const raw = localStorage.getItem('motrix_session')
        if (!raw) { location.href = '../pages/login.html'; return }
        this.session = JSON.parse(raw)
        if (!this.session.token) { location.href = '../pages/login.html'; return }
        this.loadTagPresets()
        await this.fetchSuppliers()

        // 離開頁面前警告（未儲存資料保護）
        window.addEventListener('beforeunload', e => {
          if (this.isDirty) { e.preventDefault(); e.returnValue = '' }
        })
        document.addEventListener('click', e => {
          if (!this.isDirty) return
          const link = e.target.closest('a[href]')
          if (!link) return
          const href = link.getAttribute('href') || ''
          if (!href || href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('mailto:')) return
          if (!confirm('有尚未儲存的內容，確定要離開此頁面？\n\n按「取消」可繼續編輯。')) e.preventDefault()
        }, true)
      },

      async fetchSuppliers() {
        try {
          const r = await fetch(`${API}/suppliers`, {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (r.status === 401) { this.logout(); return }
          if (r.ok) this.suppliers = await r.json()
        } catch(e) {}
      },

      async lookupByTaxId() {
        const id = this.taxIdSearch.replace(/\D/g, '')
        if (!/^\d{8}$/.test(id)) { this.lookupMsg = '請輸入完整 8 碼統編'; this.lookupOk = false; return }
        this.lookingUp = true; this.lookupMsg = ''; this.lookupOk = false
        try {
          const r = await fetchT(`${API}/company/tax/${id}`,
            { headers: { Authorization: 'Bearer ' + this.session.token } }, 12000)
          if (r.ok) {
            const d = await r.json()
            this.form.name    = d.name  || ''
            this.form.taxId   = d.taxId || ''
            this.taxIdSearch = this.form.taxId
            this.lookupMsg   = `已帶入：${d.name}`
            this.lookupOk    = true
          } else if (r.status === 404) {
            this.lookupMsg = '查無此統編登記資料，請手動輸入'; this.lookupOk = false
          } else if (r.status === 401) {
            this.logout()
          } else {
            this.lookupMsg = '政府資料庫查詢失敗，請稍後再試或手動輸入'; this.lookupOk = false
          }
        } catch(e) {
          this.lookupMsg = '查詢逾時，請確認網路連線'; this.lookupOk = false
        }
        this.lookingUp = false
      },

      exportExcel() {
        const rows = this.suppliers.map(s => ({
          '公司名稱': s.name||'', '英文名稱': s.nameEn||'', '統一編號': s.taxId||'',
          '電話': s.phone||'', '傳真': s.fax||'', 'Email': s.email||'', '網站': s.website||'',
          '地址': s.address||'', '供應商類型': s.category||'',
          '交易幣別': s.currency||'NTD', '付款條件': s.paymentTerms||'', '標準交期': s.leadTime||'',
          '內部標籤': (s.tags||[]).join(',') || (s.alias||''),
          '主要聯絡人': s.contacts?.[0]?.name||'', '聯絡人職稱': s.contacts?.[0]?.title||'',
          '聯絡人電話': s.contacts?.[0]?.phone||'', '聯絡人Email': s.contacts?.[0]?.email||'',
          '備註': s.notes||''
        }))
        const ws = XLSX.utils.json_to_sheet(rows)
        ws['!cols'] = [20,16,10,14,14,22,22,24,10,10,14,12,18,10,10,14,22,20].map(w=>({wch:w}))
        const wb = XLSX.utils.book_new()
        XLSX.utils.book_append_sheet(wb, ws, '供應商')
        XLSX.writeFile(wb, `MOTRIX_供應商_${new Date().toISOString().slice(0,10)}.xlsx`)
      },

      async handleImport(event) {
        const file = event.target.files[0]
        if (!file) return
        event.target.value = ''
        this.importing = true; this.showImportModal = true; this.importResults = null
        const results = { created: 0, updated: 0, failed: 0, errors: [] }
        try {
          const wb = XLSX.read(await file.arrayBuffer())
          const rows = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { defval: '' })
          for (let i = 0; i < rows.length; i++) {
            try {
              const obj = this._parseSupplierRow(rows[i])
              if (!obj.name) { results.failed++; results.errors.push(`第 ${i+2} 行：公司名稱不可空白`); continue }
              const match = this.suppliers.find(s => (obj.taxId && s.taxId && s.taxId===obj.taxId) || s.name===obj.name)
              const { name, taxId, phone, ...dataFields } = obj
              const body = { name, tax_id: taxId||'', phone: phone||'', data: dataFields }
              const r = await fetch(match ? `${API}/suppliers/${match.id}` : `${API}/suppliers`, {
                method: match ? 'PUT' : 'POST',
                headers: { 'Content-Type':'application/json', Authorization:`Bearer ${this.session.token}` },
                body: JSON.stringify(body)
              })
              if (r.ok) { match ? results.updated++ : results.created++ }
              else { results.failed++; results.errors.push(`${obj.name}：${match?'更新':'新增'}失敗 (${r.status})`) }
            } catch(e) { results.failed++; results.errors.push(`第 ${i+2} 行：${e.message}`) }
          }
          await this.fetchSuppliers()
        } catch(e) { results.failed++; results.errors.push('檔案解析失敗：' + e.message) }
        this.importResults = results; this.importing = false
      },

      _parseSupplierRow(row) {
        const n = {}
        for (const [k, v] of Object.entries(row)) n[k.trim()] = String(v ?? '').trim()
        const tags = n['內部標籤'] ? n['內部標籤'].split(/[,，、]/).map(t=>t.trim()).filter(Boolean) : []
        const ct = {}
        if (n['主要聯絡人']) { ct.id=Date.now(); ct.name=n['主要聯絡人']; ct.title=n['聯絡人職稱']||''; ct.phone=n['聯絡人電話']||''; ct.email=n['聯絡人Email']||n['聯絡人email']||''; ct.line='' }
        return {
          name: n['公司名稱']||n['名稱']||'', nameEn: n['英文名稱']||'',
          taxId: (n['統一編號']||n['統編']||'').replace(/\D/g,''),
          phone: n['電話']||'', fax: n['傳真']||'', email: n['Email']||n['email']||'',
          website: n['網站']||'', address: n['地址']||n['發票地址']||'',
          category: n['供應商類型']||n['客戶類型']||'',
          currency: n['交易幣別']||'NTD', paymentTerms: n['付款條件']||'',
          leadTime: n['標準交期']||'', notes: n['備註']||'',
          tags, contacts: ct.name ? [ct] : [], active: true
        }
      },

      loadTagPresets() {
        try { this.tagPresets = JSON.parse(localStorage.getItem('motrix_tag_presets') || '[]') } catch { this.tagPresets = [] }
      },
      saveTagPresets() {
        localStorage.setItem('motrix_tag_presets', JSON.stringify(this.tagPresets))
      },
      toggleTag(tag) {
        if (!Array.isArray(this.form.tags)) this.form.tags = []
        const idx = this.form.tags.indexOf(tag)
        if (idx >= 0) this.form.tags.splice(idx, 1)
        else this.form.tags.push(tag)
      },
      addTagFromInput() {
        const t = this.tagInput.trim()
        if (!Array.isArray(this.form.tags)) this.form.tags = []
        if (t && !this.form.tags.includes(t)) this.form.tags.push(t)
        this.tagInput = ''
      },
      addPreset() {
        const t = this.newPreset.trim()
        if (t && !this.tagPresets.includes(t)) { this.tagPresets.push(t); this.saveTagPresets() }
        this.newPreset = ''
      },
      removePreset(pi) {
        this.tagPresets.splice(pi, 1); this.saveTagPresets()
      },

      get filtered() {
        let list = this.suppliers
        const q  = this.search.toLowerCase().trim()
        if (q) list = list.filter(s =>
          (s.name||'').toLowerCase().includes(q) ||
          (s.taxId||'').includes(q) ||
          (s.alias||'').toLowerCase().includes(q) ||
          (s.tags||[]).some(t => t.toLowerCase().includes(q)) ||
          (s.contacts||[]).some(ct => (ct.name||'').toLowerCase().includes(q))
        )
        if (this.filterCategory) list = list.filter(s => s.category === this.filterCategory)
        return list
      },

      get selectedSupplier() {
        return this.suppliers.find(s => s.id === this.selectedId) || null
      },

      selectSupplier(s) { this.selectedId = s.id },

      blankForm() {
        return {
          name:'', nameEn:'', tags:[], taxId:'', category:'', active: true,
          currency:'NTD', paymentTerms:'', leadTime:'',
          phone:'', fax:'', email:'', website:'', address:'',
          contacts:[], notes:''
        }
      },

      openCreate() {
        this.editingId     = null
        this.form          = this.blankForm()
        this.formError     = ''
        this.isDirty       = false
        this.taxIdSearch   = ''
        this.lookupMsg     = ''
        this.tagInput      = ''
        this.newPreset     = ''
        this.showAddPreset = false
        this.loadTagPresets()
        this.showModal     = true
      },

      openEdit(s) {
        this.editingId   = s.id
        const { id, createdAt, updatedAt, ...fields } = s
        this.form        = { ...this.blankForm(), ...fields }
        // 舊 alias 字串遷移至 tags 陣列
        if (!Array.isArray(this.form.tags)) {
          this.form.tags = this.form.alias ? [this.form.alias] : []
        }
        delete this.form.alias
        this.taxIdSearch   = s.taxId || ''
        this.formError     = ''
        this.isDirty       = false
        this.lookupMsg     = ''
        this.tagInput      = ''
        this.newPreset     = ''
        this.showAddPreset = false
        this.loadTagPresets()
        this.showModal     = true
      },

      closeModal() {
        if (this.isDirty && !confirm('有尚未儲存的內容，確定要關閉？\n\n按「取消」可繼續編輯。')) return
        this.isDirty   = false
        this.showModal = false
      },

      addContact() {
        this.form.contacts.push({
          id: Date.now(), name:'', title:'', phone:'', email:'', line:'', note:''
        })
      },

      async saveSupplier() {
        if (!this.form.name.trim()) { this.formError = '請填寫公司名稱'; return }
        this.formError = ''
        const { name, taxId, phone, id, createdAt, updatedAt, ...dataFields } = this.form
        const body = { name: (name||'').trim(), tax_id: taxId||'', phone: phone||'', data: dataFields }
        try {
          const url = this.editingId ? `${API}/suppliers/${this.editingId}` : `${API}/suppliers`
          const method = this.editingId ? 'PUT' : 'POST'
          const r = await fetch(url, {
            method,
            headers: { 'Content-Type':'application/json', Authorization:'Bearer ' + this.session.token },
            body: JSON.stringify(body)
          })
          if (r.status === 401) { this.logout(); return }
          if (!r.ok) { const e = await r.json().catch(()=>{}); this.formError = e?.detail || '儲存失敗'; return }
          await this.fetchSuppliers()
          this.isDirty = false
          this.closeModal()
        } catch(e) { this.formError = '連線失敗，請稍後再試' }
      },

      async deleteSupplier() {
        if (!confirm(`確定刪除「${this.form.name}」？`)) return
        try {
          const r = await fetch(`${API}/suppliers/${this.editingId}`, {
            method: 'DELETE',
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (r.status === 401) { this.logout(); return }
          if (!r.ok) { alert('刪除失敗'); return }
          this.selectedId = null
          await this.fetchSuppliers()
          this.isDirty = false
          this.closeModal()
        } catch(e) { alert('連線失敗') }
      },

      toast(msg) {
        const el = document.createElement('div')
        el.textContent = msg
        el.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#0A0A0A;color:#F5F4F0;padding:8px 18px;border-radius:6px;font-size:12px;z-index:999;font-family:Inter,sans-serif;box-shadow:0 4px 12px rgba(0,0,0,.2)'
        document.body.appendChild(el)
        setTimeout(() => el.remove(), 2500)
      },

      async copyToCustomer(s) {
        if (!s) return
        try {
          const rc = await fetch(`${API}/customers`, { headers: { Authorization: 'Bearer ' + this.session.token } })
          if (!rc.ok) throw new Error()
          const customers = await rc.json()
          let existingId = null
          const found = s.taxId
            ? customers.find(c => c.taxId === s.taxId)
            : customers.find(c => c.name === s.name)
          if (found) {
            if (!confirm(`客戶管理中已存在「${found.name}」（統編：${found.taxId || '無'}），是否覆蓋更新資料？`)) return
            existingId = found.id
          }
          const body = {
            name: s.name,
            tax_id: s.taxId || '',
            phone: s.phone || '',
            data: {
              nameEn: s.nameEn || '',
              tags: s.tags || [],
              fax: s.fax || '',
              email: s.email || '',
              website: s.website || '',
              invoiceAddress: s.address || '',
              contacts: (s.contacts || []).map(ct => ({
                id: ct.id || String(Date.now()), name: ct.name || '',
                title: ct.title || '', phone: ct.phone || '',
                email: ct.email || '', note: ct.note || ''
              })),
              notes: s.notes || '',
              active: true
            }
          }
          const method = existingId ? 'PUT' : 'POST'
          const url = existingId ? `${API}/customers/${existingId}` : `${API}/customers`
          const r = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify(body)
          })
          if (r.ok) {
            this.toast(existingId ? '✓ 已更新至客戶管理' : '✓ 已複製至客戶管理')
          } else {
            alert('操作失敗，請重試')
          }
        } catch(e) { alert('連線失敗') }
      },

      logout() {
        fetch(`${API}/auth/logout`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + (this.session.token||'') }
        }).catch(()=>{})
        localStorage.removeItem('motrix_session')
        location.href = '../pages/login.html'
      }
    }
  }
