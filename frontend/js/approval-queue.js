  const API = ''

  function approvalQueueApp() {
    return {
    isMobileView: window.innerWidth <= 767,
      session: {},
      queue: [],
      totalPending: 0,
      selected: null,
      loading: true,
      actioning: false,
      rejectModalOpen: false,
      rejectNote: '',

      async init() {
    window.addEventListener('resize', () => { this.isMobileView = window.innerWidth <= 767 })
        const s = JSON.parse(localStorage.getItem('motrix_session') || 'null')
        if (!s?.token) { location.href = 'login.html'; return }
        this.session = s
        await this.loadQueue()
      },

      async loadQueue() {
        this.loading = true
        try {
          const r = await fetch(`${API}/api/approval-queue`, {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (r.status === 401) { location.href = 'login.html'; return }
          const d = await r.json()
          this.queue = d.queue || []
          this.totalPending = d.total || 0
          // Keep selection in sync
          if (this.selected) {
            const found = this.queue.flatMap(g => g.items).find(i => i.quoteNo === this.selected.quoteNo)
            this.selected = found || null
          }
        } catch (e) {
          console.error(e)
        } finally {
          this.loading = false
        }
      },

      selectItem(item) {
        this.selected = item
      },

      canApprove(item) {
        if (!item) return false
        const steps = item.steps || []
        if (steps.length > 0) {
          const cur = item.currentStep ?? 0
          if (cur >= steps.length) return false
          return steps[cur].username === this.session.username
        }
        // No steps: superadmin, not self
        return this.session.role === 'superadmin' && item.requestedBy !== this.session.username
      },

      waitingForText(item) {
        if (!item) return ''
        const steps = item.steps || []
        if (steps.length > 0) {
          const cur = item.currentStep ?? 0
          if (cur < steps.length) {
            const who = steps[cur].displayName || steps[cur].username
            return `等待 ${who} 簽核（步驟 ${cur + 1}/${steps.length}）`
          }
        }
        return ''
      },

      async doApprove() {
        if (!this.selected) return
        const item = this.selected
        const steps = item.steps || []
        const isMultiStep = steps.length > 0
        const isLastStep  = isMultiStep && (item.currentStep ?? 0) === steps.length - 1
        const willFinish  = !isMultiStep || isLastStep
        const confirmMsg  = willFinish
          ? `確認簽核通過 ${item.quoteNo}？\n\n客戶：${item.customer}\n金額：NT$ ${(item.total||0).toLocaleString()}\n\n簽核後報價單狀態將更新為「已送出」。`
          : `確認完成第 ${(item.currentStep ?? 0) + 1} 步驟簽核（共 ${steps.length} 步）？\n\n${item.quoteNo}｜${item.customer}`
        if (!confirm(confirmMsg)) return
        this.actioning = true
        try {
          const r = await fetch(`${API}/api/quotations/${encodeURIComponent(item.quoteNo)}/approve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({ approvedByDisplay: this.session.displayName || this.session.username })
          })
          if (!r.ok) {
            const err = await r.json().catch(() => ({}))
            alert('簽核失敗：' + (err.detail || r.status))
            return
          }
          const resp = await r.json()
          if (resp.allDone) {
            this._toast('✓ 簽核完成，報價單已送出', '#15803D')
            this.selected = null
          } else {
            this._toast('✓ 此步驟已簽核，等待下一位簽核人', '#4338CA')
            // Keep selection but refresh so steps update
          }
          await this.loadQueue()
        } catch (e) {
          alert('網路錯誤：' + e.message)
        } finally {
          this.actioning = false
        }
      },

      openRejectModal() {
        this.rejectNote = ''
        this.rejectModalOpen = true
      },

      async doReject() {
        if (!this.selected) return
        const item = this.selected
        this.actioning = true
        try {
          const r = await fetch(`${API}/api/quotations/${encodeURIComponent(item.quoteNo)}/reject`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({ note: this.rejectNote })
          })
          if (!r.ok) {
            const err = await r.json().catch(() => ({}))
            alert('退回失敗：' + (err.detail || r.status))
            return
          }
          this.rejectModalOpen = false
          this._toast('↩ 已退回草稿', '#B45309')
          this.selected = null
          await this.loadQueue()
        } catch (e) {
          alert('網路錯誤：' + e.message)
        } finally {
          this.actioning = false
        }
      },

      logout() {
        localStorage.removeItem('motrix_session')
        location.href = 'login.html'
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
