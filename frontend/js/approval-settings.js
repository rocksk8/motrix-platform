const API = ''

function approvalSettingsApp() {
  return {
    session:    {},
    tiers:      [],   // [{_id, order, approvers:[{_id, userId, username, displayName, role}]}]
    allUsers:   [],
    addUserId:  '',
    addToTier:  null,  // tier._id to add into; null = add new tier
    saving:     false,
    _idCounter: 0,

    get availableUsers() {
      const roleOrder = { superadmin: 0, admin: 1, sales: 2, engineer: 3, viewer: 4 }
      return this.allUsers
        .filter(u => u.active !== false && u.active !== 0)
        .sort((a, b) => {
          const ro = (roleOrder[a.role] ?? 9) - (roleOrder[b.role] ?? 9)
          if (ro !== 0) return ro
          return (a.displayName || a.username).localeCompare(b.displayName || b.username, 'zh-TW')
        })
    },

    get totalApprovers() {
      return this.tiers.reduce((s, t) => s + t.approvers.length, 0)
    },

    async init() {
      const s = JSON.parse(localStorage.getItem('motrix_session') || 'null')
      if (!s?.token) { location.href = 'login.html'; return }
      this.session = s
      await Promise.all([this.loadFlow(), this.loadUsers()])
    },

    async loadFlow() {
      try {
        const r = await fetch(`${API}/api/settings/approval-flow`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.status === 401) { location.href = 'login.html'; return }
        const d = await r.json()
        this.tiers = (d.tiers || []).map(t => ({
          _id:       ++this._idCounter,
          order:     t.order ?? 0,
          approvers: (t.approvers || []).map(a => ({ ...a, _id: ++this._idCounter })),
        }))
      } catch (e) {
        console.error('loadFlow', e)
      }
    },

    async loadUsers() {
      try {
        const r = await fetch(`${API}/api/users`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!r.ok) return
        const data = await r.json()
        this.allUsers = Array.isArray(data) ? data : (data.users || [])
        // Patch roles from live user data
        this.tiers = this.tiers.map(t => ({
          ...t,
          approvers: t.approvers.map(a => {
            const u = this.allUsers.find(u => u.id === a.userId)
            return u ? { ...a, role: u.role, displayName: u.displayName } : a
          }),
        }))
      } catch (e) {
        console.error('loadUsers', e)
      }
    },

    // ── Tier ops ──────────────────────────────────────────────────────────────
    addTier() {
      this.tiers.push({ _id: ++this._idCounter, order: this.tiers.length, approvers: [] })
    },

    removeTier(tierIdx) {
      if (!confirm(`確定要移除第 ${tierIdx + 1} 層？`)) return
      this.tiers.splice(tierIdx, 1)
    },

    moveTierUp(idx) {
      if (idx === 0) return
      ;[this.tiers[idx - 1], this.tiers[idx]] = [this.tiers[idx], this.tiers[idx - 1]]
    },

    moveTierDown(idx) {
      if (idx === this.tiers.length - 1) return
      ;[this.tiers[idx + 1], this.tiers[idx]] = [this.tiers[idx], this.tiers[idx + 1]]
    },

    // ── Approver ops ──────────────────────────────────────────────────────────
    addApprover(tierIdx) {
      if (!this.addUserId) return
      const uid  = Number(this.addUserId)
      const user = this.allUsers.find(u => u.id === uid)
      if (!user) return
      // check not already in this tier
      const tier = this.tiers[tierIdx]
      if (tier.approvers.some(a => a.userId === uid)) {
        alert(`${user.displayName} 已在第 ${tierIdx + 1} 層`)
        return
      }
      tier.approvers.push({
        _id:         ++this._idCounter,
        userId:      user.id,
        username:    user.username,
        displayName: user.displayName,
        role:        user.role,
      })
      this.addUserId = ''
      this.addToTier = null
    },

    removeApprover(tierIdx, apprIdx) {
      this.tiers[tierIdx].approvers.splice(apprIdx, 1)
    },

    resetToDefault() {
      if (!confirm('確定要清除所有層設定，還原為預設模式（任一超級管理員可簽核）？')) return
      this.tiers = []
    },

    // ── Save ──────────────────────────────────────────────────────────────────
    async saveFlow() {
      if (this.saving) return
      // validate: no empty tiers
      const emptyTier = this.tiers.findIndex(t => t.approvers.length === 0)
      if (emptyTier >= 0) {
        alert(`第 ${emptyTier + 1} 層尚未加入任何簽核人員，請先加人或移除此層`)
        return
      }
      this.saving = true
      try {
        const payload = {
          tiers: this.tiers.map((t, i) => ({
            order:     i,
            approvers: t.approvers.map(a => ({
              userId:      a.userId,
              username:    a.username,
              displayName: a.displayName,
            })),
          }))
        }
        const r = await fetch(`${API}/api/settings/approval-flow`, {
          method:  'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body:    JSON.stringify(payload),
        })
        if (!r.ok) {
          const err = await r.json().catch(() => ({}))
          alert('儲存失敗：' + (err.detail || r.status))
          return
        }
        this._toast(
          this.tiers.length > 0
            ? `✓ 已儲存 ${this.tiers.length} 層、共 ${this.totalApprovers} 位簽核人員`
            : '✓ 已還原為預設模式',
          '#15803D'
        )
      } catch (e) {
        alert('網路錯誤：' + e.message)
      } finally {
        this.saving = false
      }
    },

    roleLabel(role) {
      return { superadmin: '超管', admin: '管理員', sales: '業務', engineer: '工程師', viewer: '檢視者' }[role] || role
    },

    _toast(msg, bg = '#0A0A0A') {
      const el = document.createElement('div')
      el.textContent = msg
      el.style.cssText = `position:fixed;bottom:32px;left:50%;transform:translateX(-50%);background:${bg};color:#fff;padding:10px 22px;border-radius:8px;font-size:13px;z-index:99999;font-family:Inter,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.3)`
      document.body.appendChild(el)
      setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity .4s'; setTimeout(() => el.remove(), 400) }, 2400)
    },
  }
}
