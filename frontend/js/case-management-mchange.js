// case-management-mchange.js — 案件管理頁：材料申請「變更申請」面板（33-M2c；設計 docs/platform/plans/MATERIAL-CHANGE-REQUEST-DESIGN.md）
// 已核准的材料申請要改內容（追加採購單行、改數量）不能直接改（use_change_request），改在這裡發起「變更申請」走簽核；核准前原內容照常有效。
// 獨立成檔：與 case-management-mlink.js／exec.js 不改同一段；只靠 x-effect 觀察 selected／moApprovals，不動核心的重設清單與載入流程。
// 後端：modules/case/api/material_changes.py。金額與涵蓋採購單行由已核准的採購單決定，這裡只能填「數量」「備註」「原因」。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({
    mcChanges: [],        // 這個案件所有材料申請的變更申請（新到舊）
    mcFor: '',            // 目前載入的是哪一個案件
    mcLoaded: false,      // 這個案件的變更申請載入過了嗎（沒有任何有審核單的材料申請時不發請求）
    mcLoading: false,
    mcMsg: '',
    mcItemId: '',         // 發起：選哪一筆已核准的材料申請
    mcQty: '', mcNotes: '', mcReason: '',
    mcPreview: null,      // 預覽結果 {before, after, diff, uncoveredLines, problems}
    mcReviseId: null,     // 正在修改哪一張（null＝新建）
    mcBusy: false,

    _mcHeaders() { return { Authorization: 'Bearer ' + this.session.token, 'Content-Type': 'application/json' } },
    _mcBase(quoteNo) { return `/api/quotations/${encodeURIComponent(quoteNo || this.selected?.quote_no || '')}` },

    // x-effect 掛在面板容器：切換案件就重設；案件有「有審核單」的材料申請（moApprovals 載入後）才取變更申請（沒有就不發請求，開案件的請求數不變）
    mcSync() {
      const q = this.selected?.quote_no || ''
      const tracked = Object.values(this.moApprovals || {}).some(a => a && !a.legacy)
      if (q !== this.mcFor) {
        this.mcFor = q; this.mcLoaded = false
        this.mcChanges = []; this.mcMsg = ''; this.mcItemId = ''; this.mcQty = ''; this.mcNotes = ''; this.mcReason = ''
        this.mcPreview = null; this.mcReviseId = null; this.mcBusy = false
      }
      if (q && tracked && !this.mcLoaded) { this.mcLoaded = true; this.mcLoad(q) }
    },
    mcVisible() { return !!this.selected?.quote_no && (this.mcChanges.length > 0 || this.mcCandidates().length > 0) },

    async mcLoad(quoteNo) {
      quoteNo = quoteNo || this.selected?.quote_no
      if (!quoteNo) return
      this.mcLoading = true
      try {
        const r = await fetch(this._mcBase(quoteNo) + '/material-changes', { headers: this._mcHeaders() })
        const d = r.ok ? await r.json() : null
        if (this.selected?.quote_no !== quoteNo) return                                    // 晚到、或已切到別的案件的回應丟掉
        if (d) this.mcChanges = d.changes || []
      } catch {}
      this.mcLoading = false
    },

    // 可以發起變更的材料申請：已核准、不是舊單（舊單沒有審核單，直接改即可）、目前沒有進行中的變更
    mcCandidates() {
      return (this.materialOrders || []).filter(m => {
        const ap = this.moAp ? this.moAp(m) : { status: '', legacy: true }
        return m._saved !== false && !ap.legacy && ap.status === '已核准' && !this.mcLiveOf(m.itemId)
      })
    },
    mcLiveOf(itemId) { return this.mcChanges.find(c => c.itemId === itemId && ['草稿', '待審核', '簽核中'].includes(c.status)) || null },
    mcItemName(itemId) { const m = (this.materialOrders || []).find(x => x.itemId === itemId); return m ? (m.itemName || itemId) : itemId },

    mcStatusStyle(st) {
      const c = { '草稿': 'var(--text-dim)', '待審核': 'var(--warning)', '簽核中': 'var(--warning)', '已核准': 'var(--success)', '已退回': 'var(--danger)', '已撤回': 'var(--text-dim)' }[st] || 'var(--text-dim)'
      return `font-size:11px;padding:1px 8px;border-radius:10px;border:1px solid ${c};color:${c}`
    },
    mcFmt(v) {
      if (v === null || v === undefined || v === '') return '—'
      const n = Number(v)
      return Number.isFinite(n) ? n.toLocaleString('en-US', { maximumFractionDigits: 4 }) : String(v)
    },
    mcLines(v) { return (v || []).map(x => `${x.poDocCode} 第${x.line}列`).join('、') || '—' },
    // 差異一列的文字：數字去掉多餘小數；涵蓋行列出單號；被財務遮蔽的金額欄顯示「（金額已遮蔽）」
    mcDiffRows(diff) {
      const label = { quantity: '數量', unit: '單位', unitPrice: '單價', totalPrice: '小計', poSnapshot: '涵蓋採購單行', notes: '備註' }
      return (diff || []).map(d => {
        if (d.hidden) return { field: d.field, label: label[d.field] || d.field, text: '（金額已遮蔽）' }
        const f = d.field === 'poSnapshot' ? this.mcLines : (d.field === 'notes' || d.field === 'unit' ? (v => v || '—') : this.mcFmt)
        return { field: d.field, label: label[d.field] || d.field, text: `${f.call(this, d.old)} → ${f.call(this, d.new)}` }
      })
    },

    // ── 發起／預覽 ──
    _mcQuery() {
      const p = new URLSearchParams()
      if (String(this.mcQty).trim() !== '') p.set('quantity', String(this.mcQty).trim())
      if (this.mcNotes !== '') p.set('notes', this.mcNotes)
      const s = p.toString()
      return s ? '?' + s : ''
    },
    async mcDoPreview() {
      this.mcMsg = ''; this.mcPreview = null
      if (!this.mcItemId) { this.mcMsg = '請先選擇要變更的材料申請'; return }
      this.mcBusy = true
      try {
        const r = await fetch(`${this._mcBase()}/material-orders/${encodeURIComponent(this.mcItemId)}/change-proposal${this._mcQuery()}`, { headers: this._mcHeaders() })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { this.mcMsg = d.detail || '無法取得變更提案'; return }
        this.mcPreview = d
      } catch (e) { this.mcMsg = '讀取失敗：' + e.message } finally { this.mcBusy = false }
    },
    mcPreviewOk() { return !!this.mcPreview && (this.mcPreview.problems || []).length === 0 && String(this.mcReason).trim() !== '' },
    async mcSave() {
      if (!this.mcPreviewOk()) { this.mcMsg = String(this.mcReason).trim() === '' ? '請填變更原因' : '提案有問題，不能建立'; return }
      this.mcBusy = true
      try {
        const body = { reason: String(this.mcReason).trim() }
        if (String(this.mcQty).trim() !== '') body.quantity = Number(this.mcQty)
        if (this.mcNotes !== '') body.notes = this.mcNotes
        const url = this.mcReviseId
          ? `${this._mcBase()}/material-changes/${this.mcReviseId}/revise`
          : `${this._mcBase()}/material-orders/${encodeURIComponent(this.mcItemId)}/changes`
        const r = await fetch(url, { method: 'POST', headers: this._mcHeaders(), body: JSON.stringify(body) })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { MotrixUI.toast((this.mcReviseId ? '修改失敗：' : '建立失敗：') + (d.detail || r.status), { kind: 'error' }); return }
        MotrixUI.toast(this.mcReviseId ? `已修改 ${d.change.docCode}` : `已建立變更申請 ${d.change.docCode}（草稿）`)
        this.mcResetForm()
        await this.mcLoad()
      } catch (e) { MotrixUI.toast('發生錯誤：' + e.message, { kind: 'error' }) } finally { this.mcBusy = false }
    },
    mcResetForm() { this.mcItemId = ''; this.mcQty = ''; this.mcNotes = ''; this.mcReason = ''; this.mcPreview = null; this.mcReviseId = null; this.mcMsg = '' },
    mcStartRevise(c) {
      this.mcReviseId = c.id; this.mcItemId = c.itemId; this.mcQty = c.proposal?.quantity ?? ''; this.mcNotes = c.proposal?.notes || ''; this.mcReason = c.reason || ''
      this.mcPreview = null; this.mcMsg = ''
      this.mcDoPreview()
    },

    // ── 對一張變更申請的動作 ──
    _mcIsAdmin() { return ['superadmin', 'admin'].includes(this.session.role) },
    mcCanEditFlow() { return typeof this.moCanEdit === 'function' ? this.moCanEdit() : false },
    mcCanRevise(c) { return ['草稿', '已退回', '已撤回'].includes(c.status) && this.mcCanEditFlow() },
    mcCanWithdraw(c) { return ['草稿', '待審核', '簽核中'].includes(c.status) && (this._mcIsAdmin() || c.createdBy === this.session.username) },
    mcCanDecide(c) {
      if (!['待審核', '簽核中'].includes(c.status)) return false
      if (this.session.role === 'superadmin') return true
      const me = [this.session.username, this.session.display_name, this.session.displayName].filter(Boolean)
      return (c.currentApprovers || []).some(n => me.includes(n))
    },
    async _mcPost(c, action, body, okText) {
      this.mcBusy = true
      try {
        const r = await fetch(`${this._mcBase(c.quoteNo)}/material-changes/${c.id}/${action}`, { method: 'POST', headers: this._mcHeaders(), body: JSON.stringify(body || {}) })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { MotrixUI.toast('操作失敗：' + (d.detail || r.status), { kind: 'error' }); return false }
        MotrixUI.toast(okText(d))
        await this.mcLoad(c.quoteNo)
        if (d.applied || action === 'approve' || action === 'submit') {                 // 套用後材料申請內容與審核狀態變了：重載
          if (this.loadMaterialOrders) await this.loadMaterialOrders(c.quoteNo)
          if (this.loadMoApprovals) await this.loadMoApprovals(c.quoteNo)
        }
        return true
      } catch (e) { MotrixUI.toast('發生錯誤：' + e.message, { kind: 'error' }); return false } finally { this.mcBusy = false }
    },
    async mcSubmit(c) { await this._mcPost(c, 'submit', {}, d => d.autoApproved ? `已核准並套用（未設定簽核層）：${d.docCode}` : `已送審：${d.docCode}`) },
    async mcWithdraw(c) { await this._mcPost(c, 'withdraw', {}, () => '已撤回（原材料申請不受影響）') },
    async mcApprove(c) { await this._mcPost(c, 'approve', {}, d => d.applied ? `已核准並套用：${c.docCode}` : `已核准本層：${c.docCode}`) },
    async mcReject(c) {
      const reason = await MotrixUI.prompt('退回變更申請需要填原因：', { title: '退回變更申請', required: true })
      if (!reason || !String(reason).trim()) return
      await this._mcPost(c, 'reject', { reason: String(reason).trim() }, () => '已退回（原材料申請不受影響）')
    },
}))
