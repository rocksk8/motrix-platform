// case-management-shipping.js — 案件管理頁：出貨單分頁
// CM12 P1（2026-09-24）：由 case-management.js 原樣搬出，成員文字未改；組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({

    // ── 出貨單 ──
    shippingNotes: [],
    shippingNotesLoading: false,
    shippingNotesNotice: '',          // IP-18：採購・庫存・出貨模組不在時的說明（取代「尚未建立任何出貨單」）
    snSortPref: { sortMode: '', sortDir: 'desc', customOrder: [] },
    showShippingModal: false,
    editShippingNoteNo: null,
    shippingSaving: false,
    shippingForm: {},
    shippingMsg: '',
    _shippingLogOpen: {},
    shippingContactOptions: [],
    showShippingContactPicker: false,
    shippingPreviewModal: false,
    shippingPreviewBlobUrl: '',
    shippingPreviewFetching: false,
    shippingPreviewNote: null,
    _partsOptions: null,
    serialPicker: { show: false, itemIdx: null, partNo: '', options: [], selected: [], loading: false, error: '' },

    // ── 出貨單 ────────────────────────────────────────────────────────────────

    async loadShippingNotes(quoteNo, pre) {
      if (!quoteNo) return
      const live = this._selectLive()
      this.shippingNotesLoading = true
      this.shippingNotes = []
      this.snSortPref = await loadListPref(this.session.token, `sn:${quoteNo}`)
      if (!live()) return
      try {
        const r = pre ? this._preResp(pre) : await fetch(`/api/shipping-notes?quote_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? await r.json() : null
        if (!live()) return
        if (r.ok) { this.shippingNotes = body; this.shippingNotesNotice = '' }
        // IP-18：整包帶來的 404 附說明；之後在分頁上重新載入時模組路由不在（404 沒有說明）⇒ 沿用那一句
        else if (r.status === 404) this.shippingNotesNotice = (pre && pre.detail) || this.shippingNotesNotice
      } catch {}
      this.shippingNotesLoading = false
      this.$nextTick(() => this._initSubListSortable('sn'))
    },

    _blankShippingForm() {
      const today = new Date().toISOString().slice(0, 10)
      return {
        quote_no: this.selected?.quote_no || '',
        ship_date: today,
        recipient: '',
        delivery_address: '',
        notes: '',
        items: []
      }
    },

    async _loadShippingContactOptions() {
      this.shippingContactOptions = []
      try {
        let customer = null
        const customerId = this.selected?.data?.customerId
        if (customerId) {
          const r = await fetch(`/api/customers/${customerId}`, {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (r.ok) customer = await r.json()
        } else {
          const targetName = (this.selected?.customer_name || '').trim()
          if (targetName) {
            const r = await fetch('/api/customers', {
              headers: { Authorization: 'Bearer ' + this.session.token }
            })
            if (r.ok) {
              const all = await r.json()
              customer = all.find(c => c.name && c.name.trim() === targetName) || null
            }
          }
        }
        this.shippingContactOptions = (customer?.contacts || [])
          .filter(ct => ct.name || ct.phone || ct.email)
          .map(ct => ({ name: ct.name || '', _display: [ct.name, ct.title].filter(Boolean).join(' · ') }))
      } catch {}
    },

    applyShippingContact(ct) {
      this.shippingForm.recipient = ct.name
      this.showShippingContactPicker = false
    },

    openNewShippingNote() {
      this.editShippingNoteNo = null
      this.shippingForm = this._blankShippingForm()
      this.shippingMsg = ''
      this.showShippingContactPicker = false
      this._loadShippingContactOptions()
      this.showShippingModal = true
    },

    async openEditShippingNote(n) {
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast('讀取出貨單失敗', {kind: 'error'}); return }
        const d = await r.json()
        this.editShippingNoteNo = d.noteNo
        this.shippingForm = {
          quote_no: d.quoteNo,
          ship_date: d.shipDate || '',
          recipient: d.recipient || '',
          delivery_address: d.deliveryAddress || '',
          notes: d.notes || '',
          items: JSON.parse(JSON.stringify(d.items || []))
        }
        this.shippingMsg = ''
        this.showShippingContactPicker = false
        this._loadShippingContactOptions()
        this.showShippingModal = true
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    importItemsFromQuote() {
      const srcItems = this.selected?.data?.items || []
      if (srcItems.length === 0) { MotrixUI.toast('此案件的報價單沒有品項可匯入', {kind: 'info'}); return }
      for (const it of srcItems) {
        if (it.type === 'header') {
          this.shippingForm.items.push({
            id: Date.now() + Math.random(), type: 'header', description: it.description || ''
          })
        } else {
          this.shippingForm.items.push({
            id: Date.now() + Math.random(),
            description: it.description || '', brand: it.brand || '',
            qty: it.qty || 1, unit: it.unit || '台', notes: ''
          })
        }
      }
    },

    addShippingItem() {
      this.shippingForm.items.push({
        id: Date.now() + Math.random(), description: '', brand: '', qty: 1, unit: '台', notes: ''
      })
    },

    addShippingHeader() {
      this.shippingForm.items.push({
        id: Date.now() + Math.random(), type: 'header', description: ''
      })
    },

    async removeShippingItem(idx) {
      const it = this.shippingForm.items[idx]
      if (!(await MotrixUI.confirm(`確定要刪除出貨品項「${(it && it.description) || '未命名'}」這一列？`, {danger: true}))) return
      this.shippingForm.items.splice(idx, 1)
    },

    async _loadPartsOptions() {
      if (this._partsOptions) return this._partsOptions
      try {
        const r = await fetch('/api/parts', { headers: { Authorization: 'Bearer ' + this.session.token } })
        this._partsOptions = r.ok ? ((await r.json()).items || []) : []
      } catch { this._partsOptions = [] }
      return this._partsOptions
    },

    async openSerialPicker(idx) {
      const it = this.shippingForm.items[idx]
      this.serialPicker = {
        show: true, itemIdx: idx, partNo: it.part_no || '',
        options: [], selected: [...(it.serials || [])], loading: false, error: ''
      }
      await this._loadPartsOptions()
      if (this.serialPicker.partNo) await this._loadSerialOptions()
    },

    async _loadSerialOptions() {
      if (!this.serialPicker.partNo) { this.serialPicker.options = []; return }
      this.serialPicker.loading = true; this.serialPicker.error = ''
      try {
        const r = await fetch(`/api/inventory/stock-items?part_no=${encodeURIComponent(this.serialPicker.partNo)}&status=in_stock`,
          { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) { const d = await r.json(); this.serialPicker.options = d.items || [] }
        else { this.serialPicker.error = '讀取庫存序號失敗' }
      } catch { this.serialPicker.error = '網路錯誤' }
      this.serialPicker.loading = false
    },

    onSerialPickerPartChange() {
      this.serialPicker.selected = []
      this._loadSerialOptions()
    },

    toggleSerialPick(sn) {
      const i = this.serialPicker.selected.indexOf(sn)
      if (i >= 0) this.serialPicker.selected.splice(i, 1)
      else this.serialPicker.selected.push(sn)
    },

    applySerialPicker() {
      const it = this.shippingForm.items[this.serialPicker.itemIdx]
      if (this.serialPicker.partNo && this.serialPicker.selected.length) {
        it.part_no = this.serialPicker.partNo
        it.serials = [...this.serialPicker.selected]
        it.qty = this.serialPicker.selected.length
      } else {
        delete it.part_no
        delete it.serials
      }
      this.serialPicker.show = false
    },

    async saveShippingNote() {
      this.shippingSaving = true; this.shippingMsg = ''
      const body = {
        quote_no: this.shippingForm.quote_no,
        ship_date: this.shippingForm.ship_date || '',
        recipient: this.shippingForm.recipient || '',
        delivery_address: this.shippingForm.delivery_address || '',
        notes: this.shippingForm.notes || '',
        items: this.shippingForm.items || []
      }
      const method = this.editShippingNoteNo ? 'PUT' : 'POST'
      const url    = this.editShippingNoteNo
        ? `/api/shipping-notes/${this.editShippingNoteNo}`
        : '/api/shipping-notes'
      try {
        const r = await fetch(url, {
          method,
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(body)
        })
        if (!r.ok) { this.shippingMsg = (await r.json()).detail || '儲存失敗'; this.shippingSaving = false; return }
        this.showShippingModal = false
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { this.shippingMsg = '網路錯誤：' + e.message }
      this.shippingSaving = false
    },

    async deleteShippingNote(n) {
      if (!(await MotrixUI.confirm(`確定刪除出貨單「${n.noteNo}」？`, {danger: true}))) return
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) await this.loadShippingNotes(this.selected?.quote_no)
        else MotrixUI.toast((await r.json()).detail || '刪除失敗', {kind: 'error'})
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async submitShippingNote(n) {
      if (!(await MotrixUI.confirm(`確定送出出貨單「${n.noteNo}」進行簽核？`))) return
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/submit`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '送出失敗', {kind: 'error'}); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async approveShippingNote(n) {
      // 同一人連任多層時一次簽完（2026-09-15，見 static/approval-cascade.js）。
      // 清單資料沒帶 approval.tiers 時算出來是空陣列，行為跟以前一樣。
      const _appr = n.approval || {}
      const _casc = window.MotrixApproval.selfCascadeTiers(
        _appr.tiers || [], _appr.currentTier ?? 0, this.session.username, [])
      if (!(await MotrixUI.confirm(`確定簽核出貨單「${n.noteNo}」？` + window.MotrixApproval.cascadeNote(_casc)))) return
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/approve`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ cascade: _casc.length > 0 })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '簽核失敗', {kind: 'error'}); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async rejectShippingNote(n) {
      const note = (await MotrixUI.prompt(`退回出貨單「${n.noteNo}」，可填寫退回原因（選填）：`))
      if (note === null) return
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/reject`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '退回失敗', {kind: 'error'}); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async revokeShippingApproval(n) {
      const note = (await MotrixUI.prompt(`撤銷出貨單「${n.noteNo}」的核准？將退回草稿，且已扣的庫存序號會自動歸還可出貨狀態。\n\n可填寫撤銷原因（選填）：`))
      if (note === null) return
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/revoke-approval`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '撤銷失敗', {kind: 'error'}); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async toggleSigned(n, action) {
      const msg = action === 'sign'
        ? `確定標記出貨單「${n.noteNo}」已回簽？`
        : `確定取消出貨單「${n.noteNo}」的已回簽標記？`
      if (!(await MotrixUI.confirm(msg))) return
      const note = action === 'sign' ? ((await MotrixUI.prompt('備註（選填，例如簽收人姓名或方式）：')) || '') : ''
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/signed-toggle`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ action, note })
        })
        if (!r.ok) { MotrixUI.toast((await r.json()).detail || '操作失敗', {kind: 'error'}); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    async downloadShippingPdf(n) {
      try {
        // 記錄匯出（fire-and-forget，不阻塞 PDF 下載）
        fetch(`/api/shipping-notes/${n.noteNo}/export?mode=external`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token }
        }).catch(() => {})

        const r = await fetch(`/api/shipping-notes/${n.noteNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗', {kind: 'error'}); return }
        const blob = await r.blob()
        const url  = URL.createObjectURL(blob)
        const a    = document.createElement('a')
        a.href     = url
        a.download = `${n.noteNo}.pdf`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      } catch (e) { MotrixUI.toast('下載失敗：' + e.message, {kind: 'error'}) }
    },

    async previewShippingPdf(n) {
      this.shippingPreviewFetching = true
      try {
        const r = await fetch(`/api/shipping-notes/${n.noteNo}/pdf-download`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || 'PDF 產生失敗', {kind: 'error'}); this.shippingPreviewFetching = false; return }
        const blob = await r.blob()
        this.shippingPreviewBlobUrl = URL.createObjectURL(blob)
        this.shippingPreviewNote = n
        this.shippingPreviewModal = true
      } catch (e) { MotrixUI.toast('預覽失敗：' + e.message, {kind: 'error'}) }
      this.shippingPreviewFetching = false
    },

    closeShippingPreview() {
      if (this.shippingPreviewBlobUrl) URL.revokeObjectURL(this.shippingPreviewBlobUrl)
      this.shippingPreviewBlobUrl = ''
      this.shippingPreviewModal = false
      this.shippingPreviewNote = null
    },

    _shippingStatusLabel(s) {
      return { '草稿': '草稿', '待審核': '待審核', '簽核中': '簽核中', '已核准': '已核准' }[s] || s
    },

    _shippingStatusClass(s) {
      return { '草稿': 'badge--draft', '待審核': 'badge--pending', '簽核中': 'badge--signing', '已核准': 'badge--approved' }[s] || ''
    },

    async uploadShippingSignedFiles(note, evt) {
      const files = evt?.target?.files
      if (!files || files.length === 0) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      try {
        const r = await fetch(`/api/shipping-notes/${note.noteNo}/signed-files`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '上傳失敗', {kind: 'error'}); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('上傳失敗：' + e.message, {kind: 'error'}) }
      evt.target.value = ''
    },

    async deleteShippingSignedFile(note, fileId) {
      if (!(await MotrixUI.confirm('確定刪除此附件？', {danger: true}))) return
      try {
        const r = await fetch(`/api/shipping-notes/${note.noteNo}/signed-files/${fileId}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) { MotrixUI.toast((await r.json().catch(() => ({}))).detail || '刪除失敗', {kind: 'error'}); return }
        await this.loadShippingNotes(this.selected?.quote_no)
      } catch (e) { MotrixUI.toast('刪除失敗：' + e.message, {kind: 'error'}) }
    },

    // CM12 P2：切換案件時重設本模組的案件層級狀態（時點見 core 的 _resetCaseScoped）
    _reset_shipping(phase, data) {
      if (phase === 'late') {
        this.shippingNotes = []
        this.showShippingModal = false
        this._shippingLogOpen = {}
        this.shippingContactOptions = []
        this.showShippingContactPicker = false
        this.closeShippingPreview()
      }
    },
}))
