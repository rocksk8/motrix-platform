/* users.html 的「批次調整權限」面板（設定矩陣 S3a；SPEC §12、§13；後端 POST /api/users/permissions/batch[/preview|/undo]）。
 *
 * 原則：
 *  1. 這個面板**不算權限**：每人實際會變什麼、略過什麼與原因、要不要原因，全由伺服器的預覽回答（與套用同一支函式）；前端只負責顯示與送出。
 *  2. 高敏感清單／批次拒絕清單／財務三鍵都讀 `GET /api/modules/catalog`（`highSensitiveKeys`／`batchGrantRefused`／`financeKeys`），前端不寫死任何一份。
 *  3. 先預覽、再確認、才寫入：預覽視窗逐人列出「取消 N 項／新增 N 項」、被略過的項目與原因；需要原因時（取消高敏感或影響大的權限）原因必填。
 *  4. 套用成功後留一條「復原這一批」：逐人比對，被別人改過的人不復原並說明（不覆蓋別人的修改）。
 *  5. 所有動態文字一律用 x-text 顯示（人名、角色名稱、權限名稱都是使用者可編輯的內容，不使用 x-html）。
 * 6. **§13 豁免（h4 確認；條件）**：本頁是「人×權限」多人操作，不套 SettingsMatrix 的草稿＋儲存列，改走「預覽→確認→套用」。條件：
 *    (1) 任何一次點擊都不寫入，只有確認視窗的「套用」才寫；(2) 確認視窗逐人點名角色／使用者，並列出「實際生效多了／少了」哪些權限；
 *    (3) 離開頁面時沒有東西會悄悄遺失：選人與勾選只在畫面上、**預覽之前完全沒有寫入任何東西**（所以不加離開警告），套用後可「復原這一批」。
 * 用法：usersPage() 回傳物件時 spread `...window.usersBatchMixin()`；`loadModuleCatalog` 把目錄的三份清單放進 `batchLists`。 */
(function () {
  window.usersBatchMixin = function () {
    return {
      batchLists: { high: [], refused: [], finance: [] },
      batch: { open: false, q: '', sel: {}, action: 'grant', keys: [], template: '', roleId: '', reason: '', roles: [],
               busy: false, error: '', plan: null, showPlan: false, result: null, undoBusy: false, undoMsg: '' },

      batchToggleOpen() {
        this.batch.open = !this.batch.open
        if (this.batch.open && !this.batch.roles.length) this.batchLoadRoles()
      },
      async batchLoadRoles() {
        try {
          const r = await fetch('/api/duty-roles', { headers: this._headers() })
          if (r.ok) this.batch.roles = ((await r.json()).roles || []).filter(x => x.active)
        } catch (e) { /* 沒有職責角色清單 ⇒ 只是不能選「綁定／解除角色」 */ }
      },

      // ── 選人 ──────────────────────────────────────────────────────────────
      batchPeople() {
        const q = (this.batch.q || '').trim().toLowerCase()
        return (this.users || []).filter(u => u.role !== 'superadmin' && u.active !== false &&
          (!q || (u.username || '').toLowerCase().includes(q) || (u.displayName || '').toLowerCase().includes(q)))
      },
      batchSelectedIds() { return Object.keys(this.batch.sel).filter(k => this.batch.sel[k]).map(Number) },
      // 「全選」只選目前列出的；「全部取消」清掉**所有**已選（包含被搜尋隱藏的），避免看不見的人仍留在送出的名單裡
      batchToggleAll(on) {
        if (!on) { this.batch.sel = {}; return }
        for (const u of this.batchPeople()) this.batch.sel[u.id] = true
      },
      batchHiddenSelectedCount() {
        const shown = new Set(this.batchPeople().map(u => u.id))
        return this.batchSelectedIds().filter(id => !shown.has(id)).length
      },
      batchSelectedText() {
        const n = this.batchSelectedIds().length, hid = this.batchHiddenSelectedCount()
        if (!n) return ''
        return '已選 ' + n + ' 位' + (hid ? '，其中 ' + hid + ' 位被搜尋隱藏' : '')
      },
      batchRoleNames(ids) {
        return (ids || []).map(id => { const r = (this.batch.roles || []).find(x => x.id === id); return r ? r.name : '職責角色 #' + id }).join('、')
      },

      // ── 選權限 ────────────────────────────────────────────────────────────
      batchSetAction(a) {
        Object.assign(this.batch, { action: a, keys: [], template: '', roleId: '', reason: '', plan: null, error: '' })
      },
      batchKeyLabel(k) {
        const m = (this.allModules || []).find(x => x.key === k)
        return m ? m.label : k
      },
      // 這個鍵在目前的動作下能不能勾；不能勾就說原因（清單來自伺服器）
      batchKeyState(k) {
        const L = this.batchLists
        if (L.finance.includes(k)) return { disabled: true, note: '由角色決定，批次不動' }
        const gated = L.high.includes(k) || L.refused.includes(k)
        if (this.batch.action === 'grant') return gated ? { disabled: true, note: '要逐人授予，不能批次' } : { disabled: false, note: '' }
        return gated ? { disabled: false, note: '取消要填原因' } : { disabled: false, note: '' }
      },
      batchToggleKey(k) {
        if (this.batchKeyState(k).disabled) return
        const i = this.batch.keys.indexOf(k)
        if (i >= 0) this.batch.keys.splice(i, 1); else this.batch.keys.push(k)
      },
      batchTemplates() {
        return (this.systemPresets || []).filter(p => p.key !== 'superadmin')
      },
      batchCanPreview() {
        const b = this.batch
        if (!this.batchSelectedIds().length || b.busy) return false
        if (b.action === 'grant' || b.action === 'revoke') return b.keys.length > 0
        if (b.action === 'template') return !!b.template
        return !!b.roleId
      },
      batchBody() {
        const b = this.batch, body = { userIds: this.batchSelectedIds() }
        if (b.action === 'grant') body.grant = b.keys
        else if (b.action === 'revoke') body.revoke = b.keys
        else if (b.action === 'template') body.template = b.template
        else if (b.action === 'bind') body.bindRoleIds = [Number(b.roleId)]
        else body.unbindRoleIds = [Number(b.roleId)]
        return body
      },
      async _batchPost(path, body) {
        const r = await fetch('/api/users/permissions/batch' + path, { method: 'POST', headers: this._headers(), body: JSON.stringify(body) })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : '操作失敗（' + r.status + '）')
        return d
      },

      // ── 預覽 → 確認 → 套用 ────────────────────────────────────────────────
      async batchPreview() {
        const b = this.batch
        b.busy = true; b.error = ''; b.result = null; b.undoMsg = ''
        try {
          b.plan = await this._batchPost('/preview', this.batchBody())
          b.reason = ''
          b.showPlan = true
        } catch (e) { b.error = e.message } finally { b.busy = false }
      },
      batchClosePlan() { this.batch.showPlan = false; this.batch.error = '' },
      batchCancelKeys(p) { return Array.from(new Set((p.removes || []).concat(p.subtractAdds || []))) },
      batchKeysText(keys) {
        const t = (keys || []).map(k => this.batchKeyLabel(k))
        return t.length > 6 ? t.slice(0, 6).join('、') + ' 等 ' + t.length + ' 項' : t.join('、')
      },
      batchSkipText(s) {
        const what = s.kind === 'bind' ? '職責角色「' + this.batchRoleNames([s.key]) + '」' : this.batchKeyLabel(s.key)
        return what + '：' + s.reason
      },
      batchPlanNote() {
        const p = this.batch.plan
        if (!p) return ''
        return this.batch.action === 'template'
          ? '他們目前的個別勾選會被範本取代；個人扣項與職責角色綁定不動（角色本來就給的權限仍然有效）。財務三鍵由角色決定，不會被動到；最高管理者不在批次範圍。「管理者範本」只含權限鍵，不含管理者角色本身的通行權。'
          : ''
      },
      batchSummaryText() {
        const s = (this.batch.plan || {}).summary
        if (!s) return ''
        return '將變更 ' + s.changed + ' 位、無變化 ' + s.unchanged + ' 位、略過 ' + s.skippedPeople + ' 位（另有 ' + s.skippedItems + ' 個項目被略過）'
      },
      async batchApply() {
        const b = this.batch
        if (!b.plan || b.busy) return
        b.busy = true; b.error = ''
        try {
          const body = Object.assign(this.batchBody(), { reason: b.reason, planHash: b.plan.planHash })
          b.result = await this._batchPost('', body)
          b.showPlan = false
          b.sel = {}                                         // 已套用：清掉選取，避免下一次預覽不小心又帶上同一批人
          this.toast('已套用：變更 ' + b.result.applied.length + ' 位')
          await this.loadUsers()
        } catch (e) { b.error = e.message } finally { b.busy = false }
      },
      batchResultChanges() { return ((this.batch.result || {}).people || []).filter(p => p.status === 'change') },
      async batchUndo() {
        const b = this.batch
        if (!b.result || b.undoBusy) return
        b.undoBusy = true; b.undoMsg = ''
        try {
          const d = await this._batchPost('/undo', { changes: this.batchResultChanges() })
          const bad = (d.conflicts || []).map(c => c.name + '（' + c.reason + '）')
          b.undoMsg = '已復原 ' + d.applied.length + ' 位' + (bad.length ? '；未復原 ' + bad.length + ' 位（別人在這之後改過，不覆蓋）：' + bad.join('；') : '')
          const skipped = (d.people || []).reduce((n, p) => n + (p.skipped || []).length, 0)
          if (skipped) b.undoMsg += '；有 ' + skipped + ' 個項目因屬高敏感或影響較大而未還原，請逐人處理'
          b.result = null
          await this.loadUsers()
        } catch (e) { b.undoMsg = '復原失敗：' + e.message } finally { b.undoBusy = false }
      },
    }
  }
})()
