  const API  = '/api'

  /* 帶 timeout 的 fetch（相容舊版瀏覽器）*/
  async function fetchT(url, opts = {}, ms = 10000) {
    const ctrl  = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), ms)
    try {
      const r = await fetch(url, { ...opts, signal: ctrl.signal })
      clearTimeout(timer)
      return r
    } catch(e) { clearTimeout(timer); throw e }
  }

  function customersPage() {
    return {
      session: {},
      backendOnline: false,
      customers: [],
      search: '',
      filterType: '',
      filterIndustry: '',
      showModal: false,
      isDirty: false,
      editingId: null,
      selectedId: null,
      formError: '',
      salesUsers: [],
      form: {},
      // 統編 / 公司名查詢
      taxIdSearch: '',
      nameSearch: '',
      suggestions: [],
      showSuggest: false,
      lookingUp: false,
      lookupTarget: '',   // 'taxId' | 'name'
      lookupMsg: '',
      lookupOk: false,
      _nameDebounce: null,
      tagInput: '',
      tagPresets: [],
      showAddPreset: false,
      newPreset: '',
      showImportModal: false,
      importing: false,
      importResults: null,
      contactDragFromIdx: null,
      contactDragOverIdx: null,

      /* ── 統編查詢（走後端 Proxy，避免 CORS）── */
      async lookupByTaxId() {
        const id = this.taxIdSearch.replace(/\D/g, '')
        if (!/^\d{8}$/.test(id)) { this.lookupMsg = '請輸入完整 8 碼統編'; this.lookupOk = false; return }
        this.lookingUp = true; this.lookupTarget = 'taxId'; this.lookupMsg = ''; this.lookupOk = false
        this.suggestions = []; this.showSuggest = false
        try {
          const r = await fetchT(`${API}/company/tax/${id}`,
            { headers: { Authorization: 'Bearer ' + this.session.token } }, 12000)
          if (r.ok) {
            const d = await r.json()
            this.applyGovDataNorm(d)
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

      /* ── 公司名稱模糊查詢 ── */
      debounceNameSearch() {
        clearTimeout(this._nameDebounce)
        this._nameDebounce = setTimeout(() => {
          if (this.nameSearch.trim().length >= 2) this.lookupByName()
        }, 650)
      },

      async lookupByName() {
        const kw = this.nameSearch.trim()
        if (!kw || kw.length < 2) { this.suggestions = []; this.showSuggest = false; return }
        this.lookingUp = true; this.lookupTarget = 'name'; this.lookupMsg = ''; this.showSuggest = false
        try {
          const r = await fetchT(`${API}/company/search?q=${encodeURIComponent(kw)}`,
            { headers: { Authorization: 'Bearer ' + this.session.token } }, 15000)
          if (r.ok) {
            const rows = await r.json()
            if (rows.length > 0) {
              this.suggestions = rows.map(d => ({ ...d, id: d.taxId || String(Math.random()), _norm: true }))
              this.showSuggest = true
              this.lookupMsg = `找到 ${rows.length} 筆，點選帶入`
              this.lookupOk = true
            } else {
              this.suggestions = []; this.showSuggest = false
              this.lookupMsg = '查無相符公司，請試試更短的關鍵字或直接輸入'; this.lookupOk = false
            }
          } else if (r.status === 401) {
            this.logout()
          } else {
            this.lookupMsg = '政府資料庫查詢失敗，請稍後再試'; this.lookupOk = false
          }
        } catch(e) {
          this.lookupMsg = '查詢逾時，請確認網路連線'; this.lookupOk = false
        }
        this.lookingUp = false
      },

      /* 帶入已正規化的資料（後端 Proxy 格式：{name, taxId, findbizUrl}）*/
      applyGovDataNorm(d) {
        const name = d.name || ''
        this.form.name   = name
        this.form.taxId  = d.taxId || ''
        this.taxIdSearch = this.form.taxId
        if (!this.form.industry && name) {
          if (/科技|電子|半導體|軟體|資訊|網路/.test(name)) this.form.industry = '科技業'
          else if (/製造|機械|模具|五金|鑄造|精密/.test(name)) this.form.industry = '製造業'
          else if (/建設|開發|營造|建築/.test(name)) this.form.industry = '建設業'
          else if (/流通|物流|倉儲|貿易|進出口/.test(name)) this.form.industry = '流通業'
        }
        this.lookupMsg = `已帶入：${name}`
        this.lookupOk  = true
      },

      applySuggestion(s) {
        this.applyGovDataNorm(s)
        this.showSuggest = false
        this.nameSearch  = ''
      },

      exportExcel() {
        const rows = this.customers.map(c => ({
          '公司名稱': c.name||'', '英文名稱': c.nameEn||'', '統一編號': c.taxId||'',
          '電話': c.phone||'', '傳真': c.fax||'', 'Email': c.email||'', '網站': c.website||'',
          '地址': c.invoiceAddress||'', '送貨地址': c.deliveryAddress||'',
          '產業別': c.industry||'', '客戶類型': c.type||'一般', '負責業務': c.ownerName||'',
          '付款條件': c.paymentMethod||'',
          '內部標籤': (c.tags||[]).join(',') || (c.alias||''),
          '主要聯絡人': c.contacts?.[0]?.name||'', '聯絡人職稱': c.contacts?.[0]?.title||'',
          '聯絡人電話': c.contacts?.[0]?.phone||'', '聯絡人Email': c.contacts?.[0]?.email||'',
          '備註': c.notes||''
        }))
        const ws = XLSX.utils.json_to_sheet(rows)
        ws['!cols'] = [20,16,10,14,14,22,22,24,22,10,10,10,14,18,10,10,14,22,20].map(w=>({wch:w}))
        const wb = XLSX.utils.book_new()
        XLSX.utils.book_append_sheet(wb, ws, '客戶')
        XLSX.writeFile(wb, `MOTRIX_客戶_${new Date().toISOString().slice(0,10)}.xlsx`)
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
              const obj = this._parseCustomerRow(rows[i])
              if (!obj.name) { results.failed++; results.errors.push(`第 ${i+2} 行：公司名稱不可空白`); continue }
              const match = this.customers.find(c => (obj.taxId && c.taxId && c.taxId===obj.taxId) || c.name===obj.name)
              const { name, taxId, phone, ...dataFields } = obj
              const body = { name, tax_id: taxId||'', phone: phone||'', data: dataFields }
              const r = await fetch(match ? `${API}/customers/${match.id}` : `${API}/customers`, {
                method: match ? 'PUT' : 'POST',
                headers: { 'Content-Type':'application/json', Authorization:`Bearer ${this.session.token}` },
                body: JSON.stringify(body)
              })
              if (r.ok) { match ? results.updated++ : results.created++ }
              else { results.failed++; results.errors.push(`${obj.name}：${match?'更新':'新增'}失敗 (${r.status})`) }
            } catch(e) { results.failed++; results.errors.push(`第 ${i+2} 行：${e.message}`) }
          }
          const res = await fetch(`${API}/customers`, { headers: { Authorization:`Bearer ${this.session.token}` } })
          if (res.ok) this.customers = await res.json()
        } catch(e) { results.failed++; results.errors.push('檔案解析失敗：' + e.message) }
        this.importResults = results; this.importing = false
      },

      _parseCustomerRow(row) {
        const n = {}
        for (const [k, v] of Object.entries(row)) n[k.trim()] = String(v ?? '').trim()
        const tags = n['內部標籤'] ? n['內部標籤'].split(/[,，、]/).map(t=>t.trim()).filter(Boolean) : []
        const ct = {}
        if (n['主要聯絡人']) { ct.id=Date.now(); ct.name=n['主要聯絡人']; ct.title=n['聯絡人職稱']||''; ct.phone=n['聯絡人電話']||''; ct.email=n['聯絡人Email']||n['聯絡人email']||'' }
        return {
          name: n['公司名稱']||n['名稱']||'', nameEn: n['英文名稱']||'',
          taxId: (n['統一編號']||n['統編']||'').replace(/\D/g,''),
          phone: n['電話']||'', fax: n['傳真']||'', email: n['Email']||n['email']||'',
          website: n['網站']||'', invoiceAddress: n['地址']||n['發票地址']||'',
          deliveryAddress: n['送貨地址']||'', industry: n['產業別']||'',
          type: n['客戶類型']||'一般', ownerName: n['負責業務']||'',
          paymentMethod: n['付款條件']||'', notes: n['備註']||'',
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
        let list = this.customers
        const q  = this.search.toLowerCase().trim()
        if (q) list = list.filter(c =>
          (c.name||'').toLowerCase().includes(q) ||
          (c.taxId||'').includes(q) ||
          (c.alias||'').toLowerCase().includes(q) ||
          (c.tags||[]).some(t => t.toLowerCase().includes(q)) ||
          (c.contacts||[]).some(ct => (ct.name||'').toLowerCase().includes(q))
        )
        if (this.filterType) list = list.filter(c => c.type === this.filterType || (!c.active && this.filterType === '停用'))
        if (this.filterIndustry) list = list.filter(c => c.industry === this.filterIndustry)
        return list
      },

      get selectedCustomer() {
        return this.customers.find(c => c.id === this.selectedId) || null
      },

      selectCustomer(c) { this.selectedId = c.id },

      blankForm() {
        /* 優先用 API 拉回的 salesUsers 找自己的顯示名稱，避免 session 快取過時 */
        const me = this.salesUsers.find(u => u.username === this.session.username)
        return {
          name:'', nameEn:'', tags:[], taxId:'', industry:'', type:'一般',
          ownerName: me?.displayName || this.session.displayName || '',
          paymentMethod:'月結 30 天',
          phone:'', fax:'', email:'', website:'',
          invoiceAddress:'', deliveryAddress:'',
          contacts:[], notes:'', active: true
        }
      },

      openCreate() {
        this.editingId     = null
        this.form          = this.blankForm()
        this.formError     = ''
        this.isDirty       = false
        this.taxIdSearch   = ''
        this.nameSearch    = ''
        this.lookupMsg     = ''
        this.suggestions   = []
        this.tagInput      = ''
        this.newPreset     = ''
        this.showAddPreset = false
        this.loadTagPresets()
        this.showModal     = true
      },

      openEdit(c) {
        this.editingId   = c.id
        this.form        = JSON.parse(JSON.stringify(c))
        if (!this.form.contacts) this.form.contacts = []
        // 舊 alias 字串遷移至 tags 陣列
        if (!Array.isArray(this.form.tags)) {
          this.form.tags = this.form.alias ? [this.form.alias] : []
        }
        delete this.form.alias
        this.formError     = ''
        this.isDirty       = false
        this.taxIdSearch   = c.taxId || ''
        this.nameSearch    = ''
        this.lookupMsg     = ''
        this.suggestions   = []
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
        this.editingId = null
        this.formError = ''
      },

      addContact() {
        this.form.contacts.push({ id: Date.now(), name:'', title:'', phone:'', email:'' })
        this.isDirty = true
      },

      contactDragStart(idx) {
        this.contactDragFromIdx = idx
      },
      contactDragOver(e, idx) {
        this.contactDragOverIdx = idx
      },
      contactDragEnd() {
        const from = this.contactDragFromIdx
        const to   = this.contactDragOverIdx
        if (from !== null && to !== null && from !== to) {
          const [moved] = this.form.contacts.splice(from, 1)
          this.form.contacts.splice(to, 0, moved)
          this.isDirty = true
        }
        this.contactDragFromIdx = null
        this.contactDragOverIdx = null
      },

      async saveCustomer() {
        this.formError = ''
        if (!this.form.name.trim()) { this.formError = '請填寫公司名稱'; return }
        if (!this.backendOnline) { this.formError = '後端伺服器離線，無法儲存'; return }
        const savingId = this.editingId
        const now      = new Date().toLocaleDateString('zh-TW')
        const { name, taxId, phone, id, createdAt, updatedAt, quoteCount, lastContact, ...dataFields } = this.form
        const body = { name: (name||'').trim(), tax_id: taxId||'', phone: phone||'', data: dataFields }
        try {
          if (savingId) {
            const r = await fetch(`${API}/customers/${savingId}`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${this.session.token}` },
              body: JSON.stringify(body)
            })
            if (!r.ok) throw new Error(await r.text())
            const idx = this.customers.findIndex(c => c.id === savingId)
            if (idx >= 0) this.customers[idx] = { ...this.customers[idx], ...this.form, updatedAt: now }
          } else {
            const r = await fetch(`${API}/customers`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${this.session.token}` },
              body: JSON.stringify(body)
            })
            if (!r.ok) throw new Error(await r.text())
            const { id: dbId } = await r.json()
            this.customers.unshift({ ...this.form, id: dbId, createdAt: now, updatedAt: now, quoteCount: 0, lastContact: now })
          }
          this.isDirty = false
          this.closeModal()
          this.toast(savingId ? '客戶資料已更新' : '客戶已建立')
        } catch(e) {
          this.formError = '儲存失敗：' + (e.message || '請重試')
        }
      },

      async deleteCustomer() {
        if (!confirm(`確定刪除「${this.form.name}」？`)) return
        if (!this.backendOnline) { alert('後端伺服器離線，無法刪除'); return }
        const idToDelete = this.editingId
        try {
          const r = await fetch(`${API}/customers/${idToDelete}`, {
            method: 'DELETE',
            headers: { Authorization: `Bearer ${this.session.token}` }
          })
          if (!r.ok) throw new Error(await r.text())
          this.customers = this.customers.filter(c => c.id !== idToDelete)
          if (this.selectedId === idToDelete) this.selectedId = null
          this.isDirty = false
          this.closeModal()
          this.toast('客戶已刪除')
        } catch(e) {
          alert('刪除失敗：' + (e.message || '請重試'))
        }
      },

      async copyToSupplier(c) {
        if (!c || !this.backendOnline) { alert('後端伺服器離線'); return }
        try {
          const rs = await fetch(`${API}/suppliers`, { headers: { Authorization: 'Bearer ' + this.session.token } })
          if (!rs.ok) throw new Error()
          const suppliers = await rs.json()
          let existingId = null
          const found = c.taxId
            ? suppliers.find(s => s.taxId === c.taxId)
            : suppliers.find(s => s.name === c.name)
          if (found) {
            if (!confirm(`供應商管理中已存在「${found.name}」（統編：${found.taxId || '無'}），是否覆蓋更新資料？`)) return
            existingId = found.id
          }
          const body = {
            name: c.name,
            tax_id: c.taxId || '',
            phone: c.phone || '',
            data: {
              nameEn: c.nameEn || '',
              tags: c.tags || [],
              fax: c.fax || '',
              email: c.email || '',
              website: c.website || '',
              address: c.invoiceAddress || c.deliveryAddress || '',
              contacts: (c.contacts || []).map(ct => ({
                id: ct.id || String(Date.now()), name: ct.name || '',
                title: ct.title || '', phone: ct.phone || '',
                email: ct.email || '', line: '', note: ct.note || ''
              })),
              notes: c.notes || '',
              active: true
            }
          }
          const method = existingId ? 'PUT' : 'POST'
          const url = existingId ? `${API}/suppliers/${existingId}` : `${API}/suppliers`
          const r = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify(body)
          })
          if (r.ok) {
            this.toast(existingId ? '✓ 已更新至供應商管理' : '✓ 已複製至供應商管理')
          } else {
            alert('操作失敗，請重試')
          }
        } catch(e) { alert('連線失敗') }
      },

      logout() {
        fetch('/api/auth/logout', { method:'POST', headers:{ Authorization:'Bearer '+(this.session.token||'') } }).catch(()=>{})
        localStorage.removeItem('motrix_session'); window.location.href = 'login.html'
      },

      toast(msg) {
        const el = document.createElement('div')
        el.textContent = msg
        el.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#0A0A0A;color:#F5F4F0;padding:8px 18px;border-radius:6px;font-size:12px;z-index:999;font-family:Inter,sans-serif;box-shadow:0 4px 12px rgba(0,0,0,.2)'
        document.body.appendChild(el)
        setTimeout(() => el.remove(), 2500)
      },

      async init() {
        const s = localStorage.getItem('motrix_session')
        if (!s) { window.location.href = 'login.html'; return }
        try { this.session = JSON.parse(s) } catch(e) { window.location.href = 'login.html'; return }
        this.loadTagPresets()

        // 載入業務帳號
        try {
          const ur = await fetch(`${API}/users`, {
            headers: { 'Authorization': `Bearer ${this.session.token}` }
          })
          if (ur.status === 401) { this.logout(); return }
          if (ur.ok) {
            const users = await ur.json()
            this.salesUsers = users.filter(u => u.active)
            this.backendOnline = true
            const me = users.find(u => u.username === this.session.username)
            if (me && me.displayName && me.displayName !== this.session.displayName) {
              this.session.displayName = me.displayName
              try {
                const s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
                s.displayName = me.displayName
                localStorage.setItem('motrix_session', JSON.stringify(s))
              } catch {}
            }
          }
        } catch(e) {}

        // 載入客戶資料（後端為唯一來源）
        try {
          const res = await fetch(`${API}/customers`, {
            headers: { Authorization: `Bearer ${this.session.token}` }
          })
          if (res.status === 401) { this.logout(); return }
          if (res.ok) this.customers = await res.json()
        } catch(e) {}

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
      }
    }
  }
