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
    // 34-S2：從材料申請帶入（出貨單連動；契約 SHIPPING-MATERIAL-LINK-CONTRACT-S1.md）
    msh: { open: false, loading: false, items: [], pick: {}, qty: {}, err: '' },
    itemShipped: { items: {}, materialToItem: {} },
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

    async loadItemShipped(quoteNo, live, excludeNote) {
      this.itemShipped = { items: {}, materialToItem: {} }
      try {
        // excludeNote：編輯中的那張單不計入（否則待審核／簽核中的單會把自己的占用算進「其他出貨單」）
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/item-shipped` + (excludeNote ? `?exclude_note=${encodeURIComponent(excludeNote)}` : ''), { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!live()) return
        if (r.ok) { const d = await r.json(); this.itemShipped = { items: d.items || {}, materialToItem: d.materialToItem || {} } }
      } catch {}
    },
    // 這一列對應的報價品項累計出貨：{shipped, ordered, reserved}；沒有對應（舊單、手動列、庫存列）⇒ null（畫面「—」）
    shipCum(it) {
      if (!it || it.type === 'header') return null
      const m = (this.itemShipped && this.itemShipped.materialToItem) || {}
      const qid = it.quoteItemId || (it.materialLink && m[String(it.materialLink.materialItemId)]) || ''
      const e = qid && this.itemShipped && this.itemShipped.items ? this.itemShipped.items[String(qid)] : null
      return e && e.attributed ? e : null
    },
    shipCumText(it) { const e = this.shipCum(it); const f = n => String(+(Number(n) || 0).toFixed(3)); return e ? f(e.shipped) + ' / ' + f(e.ordered) : '—' },

    _blankShippingForm() {
      const today = MotrixDate.today()
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
      this.msh = { open: false, loading: false, items: [], pick: {}, qty: {}, err: '' }
      this.loadItemShipped(this.selected?.quote_no, () => true)                     // 新單：不排除任何單（編輯別張單後可能留著排除的結果）
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
        this.loadItemShipped(d.quoteNo || this.selected?.quote_no, () => this.editShippingNoteNo === d.noteNo, d.noteNo)     // 第 43 班：已累計出貨不含這張單自己
        this.msh = { open: false, loading: false, items: [], pick: {}, qty: {}, err: '' }
      this.showShippingModal = true
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },

    // ── 34-S2：從材料申請帶入 ──────────────────────────────────────────
    _mshLinkedQty(id) {
      return (this.shippingForm.items || []).reduce((s, it) => s + ((it.materialLink && it.materialLink.materialItemId === id) ? (Number(it.materialLink.qty) || 0) : 0), 0)
    },
    async mshOpen() {
      if (this.msh.open) { this.msh = { open: false, loading: false, items: [], pick: {}, qty: {}, err: '' }; return }
      const quoteNo = this.shippingForm.quote_no
      this.msh = { open: true, loading: true, items: [], pick: {}, qty: {}, err: '' }
      try {
        const q = `quote_no=${encodeURIComponent(quoteNo)}` + (this.editShippingNoteNo ? `&note_no=${encodeURIComponent(this.editShippingNoteNo)}` : '')
        const r = await fetch('/api/shipping-notes/material-shippable?' + q, { headers: { Authorization: 'Bearer ' + this.session.token } })
        if (this.shippingForm.quote_no !== quoteNo || !this.msh.open) return          // 切案／關掉之後晚到的回應不落地
        if (!r.ok) { this.msh.err = '無法讀取材料申請'; this.msh.loading = false; return }
        const items = ((await r.json()).items || []).map(x => ({ ...x, left: Math.max(x.remaining - this._mshLinkedQty(x.materialItemId), 0) })).filter(x => x.left > 1e-9)
        if (this.shippingForm.quote_no !== quoteNo || !this.msh.open) return
        const qty = {}
        items.forEach(x => { qty[x.materialItemId] = x.left })
        this.msh.items = items; this.msh.qty = qty
      } catch { this.msh.err = '網路錯誤' }
      this.msh.loading = false
    },
    mshImport() {
      let n = 0
      for (const x of this.msh.items) {
        if (!this.msh.pick[x.materialItemId]) continue
        const q = Number(this.msh.qty[x.materialItemId])
        if (!(q > 0) || q > x.left + 1e-9) { this.msh.err = `「${x.name}」數量要大於 0 且不超過剩餘可出貨量 ${x.left}`; return }
        this.shippingForm.items.push({ id: Date.now() + Math.random(), description: x.name, brand: '', qty: q, unit: x.unit || '台', notes: '',
                                       materialLink: { materialItemId: x.materialItemId, docCode: x.docCode, qty: q } })
        n++
      }
      if (!n) { this.msh.err = '請先勾選要帶入的材料申請'; return }
      this.msh = { open: false, loading: false, items: [], pick: {}, qty: {}, err: '' }
    },
    syncLinkQty(it) { if (it && it.materialLink) it.materialLink.qty = Number(it.qty) || 0 },

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
            qty: it.qty || 1, unit: it.unit || '台', notes: '',
            // 第 43 班：記住這列對應哪個報價品項（加性欄位；舊單沒有 ⇒ 已出貨數量顯示「—」）。有 id 才記
            ...(it.id != null && String(it.id).trim() ? { quoteItemId: String(it.id).trim() } : {})
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
        const saved = await r.json().catch(() => ({}))
        const noteNo = this.editShippingNoteNo || saved.note_no
        // 收件人的個資告知（稽核 D PN-M1）：勾了「已告知」的，存檔後以單號記錄；記錄失敗就留在視窗，讓區塊顯示原因
        const waits = []
        window.dispatchEvent(new CustomEvent('shipping-saved', { detail: { noteNo, waits } }))
        if ((await Promise.all(waits)).some(ok => !ok)) {
          this.editShippingNoteNo = noteNo          // 單據已存；之後再按儲存是更新同一張
          this.shippingSaving = false
          await this.loadShippingNotes(this.selected?.quote_no)
          return
        }
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
      // 34-S2／E6：已到料且還有剩餘可出貨量、卻沒連到這張單的材料申請 ⇒ 送審前提醒（不擋）
      let warn = ''
      try {
        const w = await fetch(`/api/shipping-notes/${n.noteNo}/material-link-check`, { headers: { Authorization: 'Bearer ' + this.session.token } })
        const un = w.ok ? ((await w.json()).unlinked || []) : []
        if (un.length) warn = '\n\n提醒：以下已到料的材料申請還有剩餘可出貨量，但沒有連結到這張出貨單（不擋，仍可送出）：\n' + un.map(x => `・${x.docCode} ${x.name}（剩餘 ${x.remaining}）`).join('\n')
      } catch {}
      if (!(await MotrixUI.confirm(`確定送出出貨單「${n.noteNo}」進行簽核？` + warn))) return
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

    // 退回（列表按鈕與預覽裡的「退回修改」同一條路）：原因必填，後端也強制
    rejectShippingNote(n) {
      window.MotrixApprovalReturn.ask({
        title: `退回出貨單「${n.noteNo}」`,
        post: (reason) => fetch(`/api/shipping-notes/${n.noteNo}/reject`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note: reason })
        }),
        onDone: () => this.loadShippingNotes(this.selected?.quote_no),
      })
    },

    returnFromShippingPreview() {
      const n = this.shippingPreviewNote
      this.closeShippingPreview()
      if (n) this.rejectShippingNote(n)
    },

    // 撤銷核准（退回草稿）：原因必填，後端也強制
    revokeShippingApproval(n) {
      window.MotrixApprovalReturn.ask({
        title: `撤銷出貨單「${n.noteNo}」的核准`,
        hint: '撤銷後單據退回草稿。已扣的庫存序號會自動歸還可出貨狀態。撤銷原因必填，會寫進稽核並通知申請人。',
        post: (reason) => fetch(`/api/shipping-notes/${n.noteNo}/revoke-approval`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ note: reason })
        }),
        onDone: () => this.loadShippingNotes(this.selected?.quote_no),
      })
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
      await window.MotrixApprovalReturn.loadDelegators(this.session.token)   // 代理簽核人也要看得到「退回修改」
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
