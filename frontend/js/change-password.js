function changePwPage() {
  return {
    session: {},
    form: { current: '', newPw: '', confirm: '' },
    submitting: false,
    errMsg: '',
    okMsg: '',
    forced: false,

    init() {
      const s = JSON.parse(localStorage.getItem('motrix_session') || 'null')
      if (!s?.token) { location.href = 'login.html'; return }
      this.session = s
      const params = new URLSearchParams(location.search)
      this.forced = params.get('forced') === '1' || !!s.mustChangePassword
    },

    async submit() {
      this.errMsg = ''
      if (this.form.newPw !== this.form.confirm) {
        this.errMsg = '新密碼與確認密碼不一致'
        return
      }
      if (this.form.newPw.length < 8) {
        this.errMsg = '新密碼至少需要 8 個字元'
        return
      }
      if (this.form.newPw === this.form.current) {
        this.errMsg = '新密碼不可與目前密碼相同'
        return
      }
      this.submitting = true
      try {
        const r = await fetch('/api/auth/change-password', {
          method: 'PATCH',
          headers: {
            'Content-Type': 'application/json',
            Authorization: 'Bearer ' + this.session.token
          },
          body: JSON.stringify({
            current_password: this.form.current,
            new_password: this.form.newPw
          })
        })
        const data = await r.json().catch(() => ({}))
        if (!r.ok) {
          this.errMsg = data.detail || '更新失敗，請稍後再試'
        } else {
          this.okMsg = '密碼已更新！2 秒後將重新登入…'
          setTimeout(() => {
            localStorage.removeItem('motrix_session')
            location.href = 'login.html'
          }, 2000)
        }
      } catch {
        this.errMsg = '連線異常，請稍後再試'
      } finally {
        this.submitting = false
      }
    },

    logout() {
      fetch('/api/auth/logout', {
        method: 'POST',
        headers: { Authorization: 'Bearer ' + this.session.token }
      }).finally(() => {
        localStorage.removeItem('motrix_session')
        location.href = 'login.html'
      })
    }
  }
}
