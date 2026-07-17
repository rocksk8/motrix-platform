function loginPage() {
  return {
    username: '',
    password: '',
    showPw:   false,
    loading:  false,
    error:    '',

    async login() {
      this.error = ''
      if (!this.username || !this.password) {
        this.error = '請輸入帳號與密碼'; return
      }
      this.loading = true
      try {
        const res = await fetch('/api/auth/login', {
          method:  'POST',
          headers: {'Content-Type': 'application/json'},
          body:    JSON.stringify({ username: this.username.trim(), password: this.password })
        })
        if (!res.ok) {
          const err = await res.json().catch(() => ({}))
          this.error   = err.detail || '帳號或密碼錯誤'
          this.loading = false; return
        }
        const data = await res.json()
        localStorage.setItem('motrix_session', JSON.stringify({
          token:              data.token,
          userId:             data.userId,
          username:           data.username,
          displayName:        data.displayName,
          role:               data.role,
          modules:            data.modules,
          loginAt:            data.loginAt,
          mustChangePassword: !!data.mustChangePassword,
        }))
        if (data.mustChangePassword) {
          window.location.href = 'change-password.html?forced=1'
        } else {
          window.location.href = '../index.html'
        }
      } catch(e) {
        this.error   = '連線失敗，請確認伺服器是否啟動'
        this.loading = false
      }
    },

    async init() {
      const s = localStorage.getItem('motrix_session')
      if (!s) return
      try {
        const session = JSON.parse(s)
        if (!session.token) return
        const res = await fetch('/api/auth/me', {
          headers: {'Authorization': 'Bearer ' + session.token}
        })
        if (res.ok) {
          const me = await res.json()
          session.mustChangePassword = !!me.mustChangePassword
          localStorage.setItem('motrix_session', JSON.stringify(session))
          if (me.mustChangePassword) {
            window.location.href = 'change-password.html?forced=1'
          } else {
            window.location.href = '../index.html'
          }
        } else {
          localStorage.removeItem('motrix_session')
        }
      } catch(e) {}
    }
  }
}
