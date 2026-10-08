/* users.html 編輯視窗的「職責角色／個人扣項／生效權限預覽」（R2 第 2 步，2a／2b；docs/platform/R2-STEPS-2-4-DESIGN.md §2）。
 *
 * 原則（設計 §2.3）：
 *  1. 畫面**只送原始勾選**：`form.modules`（寫回 users.modules）與預覽是兩份狀態；預覽（`duty.preview`）只讀、從不寫回 form.modules。
 *  2. 預覽由伺服器算（POST /api/duty-roles/preview，與真實生效路徑同一個函式）；這裡不自己算權限。
 *  3. 存檔順序：先「解除扣項」（要勾回的鍵不能還被扣著，否則舊 PUT 會 400）→ PUT /api/users（基本資料／原始勾選）→ 解除／新增角色綁定 → 新增扣項。
 *     沒有跨 API 交易：任何一步失敗就停下，並明講「已完成／未完成」。
 *  4. 一次存檔的多個動作共用同一個原因（伺服器逐筆寫入各自的 permission_changes）。高敏感差異必填原因（伺服器端仍強制）。
 * 用法：usersPage() 回傳物件時 spread `...window.usersDutyMixin()`；openEdit 呼叫 dutyOpen(user)，saveUser 在 PUT 前後呼叫 dutyBefore／dutyAfter。 */
(function () {
  const FIN_KEYS = ['cashier', 'finance', 'financial_view']

  window.usersDutyMixin = function () {
    return {
      duty: { visible: false, loaded: false, loading: false, roles: [], keys: [], hi: [], origRoleIds: [], origSubs: [],
              roleIds: [], subs: [], reason: '', preview: null, previewBusy: false, error: '', progress: '', _t: null, _userId: null },

      // ── 開啟（編輯既有、非 superadmin 的使用者才顯示；新增使用者沒有 id，不顯示）──────────────────────
      async dutyOpen(user) {
        const d = this.duty
        Object.assign(d, { visible: false, loaded: false, roles: [], origRoleIds: [], origSubs: [], roleIds: [], subs: [], reason: '',
                           preview: null, error: '', progress: '', doneBeforePut: [], _userId: user.id })
        if (!this.isSuperAdmin || !user || user.role === 'superadmin') return
        d.visible = true
        d.loading = true
        try {
          const h = this._headers()
          const [rr, ur] = await Promise.all([fetch('/api/duty-roles', { headers: h }), fetch('/api/duty-roles/users', { headers: h })])
          if (!rr.ok || !ur.ok) { d.error = '無法讀取職責角色資料（HTTP ' + (rr.ok ? ur.status : rr.status) + '）'; return }
          const rd = await rr.json(), ud = await ur.json()
          if (d._userId !== user.id) return                    // 使用者在等待期間換了人／關了視窗
          d.roles = (rd.roles || []).filter(r => r.active)
          d.keys = rd.keys || []
          d.hi = rd.highSensitiveKeys || []
          const me = (ud.users || []).find(u => u.id === user.id) || {}
          d.origRoleIds = (me.roles || []).map(r => r.id)
          d.origSubs = (me.subtracts || []).map(s => s.key)
          d.roleIds = [...d.origRoleIds]
          d.subs = [...d.origSubs]
          d.loaded = true
          await this.dutyRefresh()
        } catch (e) { d.error = '無法讀取職責角色資料' } finally { d.loading = false }
      },
      dutyClose() { this.duty.visible = false; this.duty._userId = null },

      // ── 名稱與候選 ───────────────────────────────────────────────────────────────────────────
      dutyKeyLabel(k) { const x = this.duty.keys.find(i => i.key === k); return x ? x.label : k },
      dutyRoleKeys(roleId) { const r = this.duty.roles.find(i => i.id === roleId); return (r && r.permissions) || [] },
      // 可以個人扣掉的鍵＝所選角色給的鍵，扣掉：財務三鍵（不開放）、目前勾選的鍵（同一個鍵只能有一種個人狀態）
      dutySubCandidates() {
        const set = new Set()
        for (const id of this.duty.roleIds) for (const k of this.dutyRoleKeys(id)) set.add(k)
        for (const k of this.duty.subs) set.add(k)
        // 已在個人扣項裡的鍵永遠列出（即使目前被勾選）：否則最高管理者無法在畫面上解除扣項，存檔時舊 PUT 會 400（稽核 #2 SHOULD-FIX 1）
        return [...set].filter(k => !FIN_KEYS.includes(k) && (this.duty.subs.includes(k) || !(this.form.modules || []).includes(k))).sort()
      },
      dutyIsHi(k) { return this.duty.hi.includes(k) },

      // ── 操作 ────────────────────────────────────────────────────────────────────────────────
      dutyToggleRole(id) {
        const a = this.duty.roleIds
        const i = a.indexOf(id)
        if (i >= 0) a.splice(i, 1); else a.push(id)
        // 角色拿掉後，已經不再被任何角色給的扣項沒有意義，但不自動清除（使用者看得到、可自行解除）
        this.dutySchedule()
      },
      dutyToggleSub(key) {
        const a = this.duty.subs
        const i = a.indexOf(key)
        if (i >= 0) a.splice(i, 1); else a.push(key)
        this.dutySchedule()
      },
      dutySchedule() {
        clearTimeout(this.duty._t)
        this.duty._t = setTimeout(() => this.dutyRefresh(), 150)
      },
      // 預覽：伺服器算；form.modules 是**原始勾選**（不是生效清單）
      async dutyRefresh() {
        const d = this.duty
        if (!d.visible || !d.loaded) return
        d.previewBusy = true
        try {
          const r = await fetch('/api/duty-roles/preview', {
            method: 'POST', headers: this._headers(),
            body: JSON.stringify({ userId: d._userId, modules: this.form.modules || [], roleIds: d.roleIds, subtracts: d.subs, role: this.form.role })
          })
          if (r.ok) { d.preview = await r.json(); d.error = '' }
          else d.error = (await r.json().catch(() => ({}))).detail || ('預覽失敗（HTTP ' + r.status + '）')
        } catch (e) { d.error = '預覽失敗' } finally { d.previewBusy = false }
      },

      // ── 差異與原因 ───────────────────────────────────────────────────────────────────────────
      dutyDiff() {
        const d = this.duty
        const bindAdd = d.roleIds.filter(i => !d.origRoleIds.includes(i))
        const bindRemove = d.origRoleIds.filter(i => !d.roleIds.includes(i))
        const subAdd = d.subs.filter(k => !d.origSubs.includes(k))
        const subRemove = d.origSubs.filter(k => !d.subs.includes(k))
        return { bindAdd, bindRemove, subAdd, subRemove }
      },
      dutyHasDiff() { const x = this.dutyDiff(); return !!(x.bindAdd.length || x.bindRemove.length || x.subAdd.length || x.subRemove.length) },
      dutyNeedsReason() {
        const x = this.dutyDiff()
        const roleHi = ids => ids.some(id => this.dutyRoleKeys(id).some(k => this.dutyIsHi(k)))
        return roleHi(x.bindAdd) || roleHi(x.bindRemove) || [...x.subAdd, ...x.subRemove].some(k => this.dutyIsHi(k))
      },
      dutySummary() {
        const x = this.dutyDiff()
        const nm = id => { const r = this.duty.roles.find(i => i.id === id); return r ? r.name : ('#' + id) }
        const out = []
        if (x.bindAdd.length) out.push('新增角色：' + x.bindAdd.map(nm).join('、'))
        if (x.bindRemove.length) out.push('解除角色：' + x.bindRemove.map(nm).join('、'))
        if (x.subAdd.length) out.push('新增扣項：' + x.subAdd.map(k => this.dutyKeyLabel(k)).join('、'))
        if (x.subRemove.length) out.push('解除扣項：' + x.subRemove.map(k => this.dutyKeyLabel(k)).join('、'))
        return out
      },

      // ── 存檔（saveUser 呼叫）─────────────────────────────────────────────────────────────────
      // 回傳 true＝可以繼續；false＝已把原因放進 this.formError
      dutyPrecheck() {
        const d = this.duty
        if (!d.visible || !d.loaded || !this.dutyHasDiff()) return true
        if (this.dutyNeedsReason() && (d.reason || '').trim().length < 4) { this.formError = '這次的職責角色／扣項變更涉及高敏感權限，請填寫變更原因（至少 4 個字）'; return false }
        return true
      },
      async _dutyPost(path, body) {
        const r = await fetch('/api/duty-roles' + path, { method: 'POST', headers: this._headers(), body: JSON.stringify(body) })
        if (r.ok) return null
        return (await r.json().catch(() => ({}))).detail || ('HTTP ' + r.status)
      },
      // 「解除扣項」要在 PUT 之前（要勾回的鍵還被扣著，舊 PUT 會 400）
      async dutyBefore() {
        const d = this.duty
        if (!d.visible || !d.loaded) return true
        // 勾選了某個模組、而它同時在個人扣項裡 ⇒ 自動解除該扣項（同一個鍵只能有一種個人狀態；舊 PUT 對被扣的鍵會 400）
        d.subs = d.subs.filter(k => !(this.form.modules || []).includes(k))
        const x = this.dutyDiff()
        const reason = (d.reason || '').trim()
        const done = []
        d.doneBeforePut = []
        for (const k of x.subRemove) {
          const err = await this._dutyPost('/subtracts/remove', { userId: d._userId, key: k, reason })
          if (err) { this.formError = '解除扣項「' + this.dutyKeyLabel(k) + '」失敗：' + err + (done.length ? '（已完成：' + done.join('、') + '）' : '') + '；基本資料尚未儲存'; return false }
          done.push('解除扣項 ' + this.dutyKeyLabel(k))
          d.origSubs = d.origSubs.filter(i => i !== k)
        }
        d.doneBeforePut = done      // 之後 PUT 若失敗，這些已經生效（沒有跨 API 交易）：saveUser 的錯誤訊息要明講
        return true
      },
      // PUT 成功之後：角色綁定（解除→新增）→ 新增扣項
      async dutyAfter() {
        const d = this.duty
        if (!d.visible || !d.loaded) return true
        const x = this.dutyDiff()
        const reason = (d.reason || '').trim()
        const done = ['基本資料／原始勾選已儲存']
        const steps = [
          ...x.bindRemove.map(id => ['/bindings/remove', { userId: d._userId, roleId: id, reason }, '解除角色 ' + ((d.roles.find(r => r.id === id) || {}).name || id)]),
          ...x.bindAdd.map(id => ['/bindings', { userId: d._userId, roleId: id, reason }, '新增角色 ' + ((d.roles.find(r => r.id === id) || {}).name || id)]),
          ...x.subAdd.map(k => ['/subtracts', { userId: d._userId, key: k, reason }, '新增扣項 ' + this.dutyKeyLabel(k)]),
        ]
        for (const [path, body, label] of steps) {
          const err = await this._dutyPost(path, body)
          if (err) {
            this.formError = label + ' 失敗：' + err + '。已完成：' + done.join('、') + '；未完成：' + label + ' 及其後的步驟（沒有跨 API 交易，請重新開啟檢視後再試）'
            return false
          }
          done.push(label)
        }
        d.progress = done.length > 1 ? done.join('、') : ''
        return true
      },
    }
  }
})()
