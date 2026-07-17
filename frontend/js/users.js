  const ROLE_MODULES = {
    superadmin: ['dashboard','quotation','customer','sales','procurement','inventory','equipment','finance','settings','project_manage','project_approve_eng','project_approve_biz','financial_view'],
    admin:      ['dashboard','quotation','customer','sales','procurement','inventory','equipment','finance','project_manage','project_approve_eng','project_approve_biz','financial_view'],
    sales:      ['dashboard','quotation','customer','financial_view','project_approve_biz'],
    engineer:   ['dashboard','project_manage','project_approve_eng','equipment'],
    viewer:     ['dashboard'],
  }

  function usersPage() {
    return {
      session:   {},
      users:     [],
      showModal: false,
      editingId: null,
      formError: '',
      form: { username:'', displayName:'', email:'', phone:'', role:'sales', password:'', confirmPassword:'', modules:[], unlockPassword:'', confirmUnlockPassword:'' },
      allModules: [
        {key:'dashboard',            label:'儀表板',       group:'基本'},
        {key:'quotation',            label:'報價單',       group:'業務'},
        {key:'customer',             label:'客戶',         group:'業務'},
        {key:'sales',                label:'銷售',         group:'業務'},
        {key:'financial_view',       label:'財務（金額可視）', group:'財務'},
        {key:'finance',              label:'應收帳款',     group:'財務'},
        {key:'procurement',          label:'採購',         group:'採購'},
        {key:'inventory',            label:'庫存',         group:'採購'},
        {key:'equipment',            label:'設備',         group:'設備'},
        {key:'project_manage',       label:'專案管理',     group:'專案'},
        {key:'project_approve_eng',  label:'工程主管確認', group:'專案'},
        {key:'project_approve_biz',  label:'業務確認',     group:'專案'},
        {key:'settings',             label:'系統設定',     group:'系統'},
      ],

      get isSuperAdmin() { return this.session.role === 'superadmin' },

      _headers() {
        return {
          'Content-Type':  'application/json',
          'Authorization': 'Bearer ' + (this.session.token || '')
        }
      },

      roleLabel(r) {
        return {superadmin:'超級管理員', admin:'管理員', sales:'業務', engineer:'工程師', viewer:'檢視者'}[r] || r
      },

      hasAccess(user, mod) {
        return (user.modules || ROLE_MODULES[user.role] || []).includes(mod)
      },

      formatDate(iso) {
        if (!iso) return '—'
        return new Date(iso).toLocaleDateString('zh-TW', {year:'numeric',month:'2-digit',day:'2-digit'})
      },

      applyRoleDefaults() {
        this.form.modules = [...(ROLE_MODULES[this.form.role] || [])]
      },

      toggleModule(key) {
        const idx = this.form.modules.indexOf(key)
        if (idx >= 0) this.form.modules.splice(idx, 1)
        else           this.form.modules.push(key)
      },

      openCreate() {
        this.editingId = null
        this.form = { username:'', displayName:'', email:'', phone:'', role:'sales',
                      password:'', confirmPassword:'', modules: [...ROLE_MODULES.sales],
                      unlockPassword:'', confirmUnlockPassword:'' }
        this.formError = ''
        this.showModal = true
      },

      openEdit(user) {
        if (!this.isSuperAdmin) return
        this.editingId = user.id
        this.form = {
          username:               user.username,
          displayName:            user.displayName || '',
          email:                  user.email || '',
          phone:                  user.phone || '',
          role:                   user.role,
          password:               '',
          confirmPassword:        '',
          modules:                [...(user.modules || ROLE_MODULES[user.role] || [])],
          unlockPassword:         '',
          confirmUnlockPassword:  '',
        }
        this.formError = ''
        this.showModal = true
      },

      closeModal() {
        this.showModal = false; this.editingId = null; this.formError = ''
      },

      async saveUser() {
        this.formError = ''
        if (!this.form.displayName)              { this.formError = '請填寫顯示名稱'; return }
        if (!this.editingId && !this.form.username) { this.formError = '請填寫帳號'; return }
        if (!this.editingId && !this.form.password) { this.formError = '請設定密碼'; return }
        if (this.form.password && this.form.password.length < 8) { this.formError = '密碼至少 8 碼'; return }
        if (this.form.password && this.form.password !== this.form.confirmPassword) {
          this.formError = '兩次密碼不一致'; return
        }
        if (this.form.unlockPassword) {
          if (this.form.unlockPassword.length < 8) { this.formError = '解鎖密碼至少 8 碼'; return }
          if (this.form.unlockPassword !== this.form.confirmUnlockPassword) {
            this.formError = '解鎖密碼與確認密碼不一致'; return
          }
        }

        const payload = {
          display_name: this.form.displayName,
          email:        this.form.email,
          phone:        this.form.phone,
          role:         this.form.role,
          modules:      this.form.modules,
        }
        if (this.form.password) payload.password = this.form.password

        let res
        if (this.editingId) {
          res = await fetch(`/api/users/${this.editingId}`, {
            method: 'PUT', headers: this._headers(), body: JSON.stringify(payload)
          })
        } else {
          payload.username = this.form.username.trim()
          res = await fetch('/api/users', {
            method: 'POST', headers: this._headers(), body: JSON.stringify(payload)
          })
        }
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          this.formError = err.detail || '操作失敗'; return
        }
        if (this.editingId && this.form.unlockPassword) {
          const ur = await fetch(`/api/users/${this.editingId}/unlock-password`, {
            method: 'PATCH', headers: this._headers(),
            body: JSON.stringify({ unlock_password: this.form.unlockPassword })
          })
          if (!ur.ok) {
            const ue = await ur.json().catch(() => ({}))
            this.formError = ue.detail || '解鎖密碼設定失敗'; return
          }
        }
        await this.loadUsers()
        this.closeModal()
        this.toast(this.editingId ? '已儲存變更' : '帳號已建立')
      },

      async toggleActive(user) {
        if (!this.isSuperAdmin || user.username === 'jeff') return
        await fetch(`/api/users/${user.id}/active`, {
          method: 'PATCH', headers: this._headers()
        })
        await this.loadUsers()
      },

      async deleteUser(user) {
        if (!this.isSuperAdmin) return
        if (user.username === 'jeff') { alert('不可刪除超級管理員帳號'); return }
        if (!confirm(`確定要刪除帳號「${user.username}」？此操作無法復原。`)) return
        const res = await fetch(`/api/users/${user.id}`, {
          method: 'DELETE', headers: this._headers()
        })
        if (!res.ok) { alert((await res.json().catch(()=>({}))).detail || '刪除失敗'); return }
        await this.loadUsers()
        this.toast('帳號已刪除')
      },

      async loadUsers() {
        const res = await fetch('/api/users', { headers: this._headers() })
        if (res.ok) this.users = await res.json()
      },

      logout() {
        fetch('/api/auth/logout', { method:'POST', headers: this._headers() }).catch(()=>{})
        localStorage.removeItem('motrix_session')
        window.location.href = 'login.html'
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
        try {
          this.session = JSON.parse(s)
          if (!this.session.token) { window.location.href = 'login.html'; return }
        } catch(e) { window.location.href = 'login.html'; return }

        const res = await fetch('/api/auth/me', {
          headers: {'Authorization': 'Bearer ' + this.session.token}
        })
        if (!res.ok) {
          localStorage.removeItem('motrix_session')
          window.location.href = 'login.html'; return
        }
        await this.loadUsers()
      }
    }
  }
