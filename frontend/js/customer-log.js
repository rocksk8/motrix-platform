  const API = '/api'

  function customerLogPage() {
    return {
      session: {},
      customer: null,
      visits: [],
      users: [],
      search: '',
      filterType: '',
      sortDir: 'desc',
      loading: true,
      showModal: false,
      editingId: null,
      saving: false,
      formError: '',
      form: { date: '', type: '現場拜訪', attendees: [], content: '', contactNotes: '', note: '' },

      visitTypes: [
        { key: '現場拜訪', label: '現場拜訪', color: '#2563EB' },
        { key: '電話聯繫', label: '電話聯繫', color: '#15803D' },
        { key: '視訊會議', label: '視訊會議', color: '#7C3AED' },
        { key: '電子郵件', label: '電子郵件', color: '#D97706' },
        { key: '其他',     label: '其他',     color: '#9CA3AF' },
      ],

      async init() {
        const s = JSON.parse(localStorage.getItem('motrix_session') || '{}')
        if (!s.token) { location.href = 'login.html'; return }
        this.session = s
        const params = new URLSearchParams(location.search)
        const cid = params.get('id')
        if (!cid) { location.href = 'customers.html'; return }
        await Promise.all([this.loadCustomer(cid), this.loadUsers()])
        this.loading = false
      },

      async loadCustomer(cid) {
        try {
          const r = await fetch(`${API}/customers`, { headers: { Authorization: 'Bearer ' + this.session.token } })
          if (!r.ok) return
          const list = await r.json()
          this.customer = list.find(c => String(c.id) === String(cid)) || null
          if (!this.customer) { location.href = 'customers.html'; return }
          document.title = this.customer.name + ' 日誌 — MOTRIX ERP'
          this.visits = (this.customer.visits || []).map(v => this.migrateVisit(v))
        } catch {}
      },

      async loadUsers() {
        try {
          const r = await fetch(`${API}/users`, { headers: { Authorization: 'Bearer ' + this.session.token } })
          if (r.ok) {
            const list = await r.json()
            this.users = list.filter(u => u.active !== false && u.displayName)
          }
        } catch {}
      },

      // Migrate old visit record format to new format
      migrateVisit(v) {
        if (v.attendees) return v
        return {
          ...v,
          date: v.date || v.visitDate || '',
          type: v.type || '現場拜訪',
          attendees: v.visitPeople
            ? v.visitPeople.split(/[、,，]/).map(s => s.trim()).filter(Boolean)
            : [],
        }
      },

      get filtered() {
        let list = this.visits
        if (this.filterType) list = list.filter(v => (v.type || '現場拜訪') === this.filterType)
        const q = (this.search || '').trim().toLowerCase()
        if (q) list = list.filter(v =>
          (v.content || '').toLowerCase().includes(q) ||
          (v.contactNotes || '').toLowerCase().includes(q) ||
          (v.note || '').toLowerCase().includes(q) ||
          (v.attendees || []).some(a => a.toLowerCase().includes(q)) ||
          (v.visitPeople || '').toLowerCase().includes(q)
        )
        const dir = this.sortDir === 'asc' ? 1 : -1
        return [...list].sort((a, b) => {
          const da = a.date || a.visitDate || ''
          const db = b.date || b.visitDate || ''
          return da > db ? dir : da < db ? -dir : 0
        })
      },

      get totalPeople() {
        return this.visits.reduce((s, v) => s + (v.attendees?.length || (v.visitPeople ? 1 : 0)), 0)
      },
      get totalVisitDays() {
        const days = new Set(this.visits.map(v => v.date || v.visitDate || '').filter(Boolean))
        return days.size
      },
      get lastContactDate() {
        const dates = this.visits.map(v => v.date || v.visitDate || '').filter(Boolean).sort()
        return dates.length ? dates[dates.length - 1] : '—'
      },

      // Style helpers
      badgeCls(type) {
        return { '現場拜訪': 'b-visit', '電話聯繫': 'b-call', '視訊會議': 'b-video', '電子郵件': 'b-email' }[type] || 'b-other'
      },
      dotCls(type) {
        return { '現場拜訪': 'd-visit', '電話聯繫': 'd-call', '視訊會議': 'd-video', '電子郵件': 'd-email' }[type] || 'd-other'
      },
      avCls(type) {
        return { '現場拜訪': 'av-visit', '電話聯繫': 'av-call', '視訊會議': 'av-video', '電子郵件': 'av-email' }[type] || 'av-other'
      },
      typeIcon(type) {
        const icons = {
          '現場拜訪': '<path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
          '電話聯繫': '<path d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21L8.5 10.5S9.5 13.5 13.5 15.5l1.113-1.724a1 1 0 011.21-.502l4.493 1.498A1 1 0 0121 15.72V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z"/>',
          '視訊會議': '<rect x="2" y="7" width="15" height="10" rx="2"/><path d="M17 9l5-2v10l-5-2"/>',
          '電子郵件': '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>',
        }
        return icons[type] || '<circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/>'
      },
      dowLabel(d) {
        if (!d) return ''
        const days = ['日', '一', '二', '三', '四', '五', '六']
        try { return '週' + days[new Date(d).getDay()] }
        catch { return '' }
      },

      // Modal
      openCreate() {
        this.editingId = null
        this.formError = ''
        this.form = {
          date: new Date().toISOString().slice(0, 10),
          type: '現場拜訪',
          attendees: this.session.displayName ? [this.session.displayName] : [],
          content: '',
          contactNotes: '',
          note: '',
        }
        this.showModal = true
      },

      openEdit(v) {
        this.editingId = v.id
        this.formError = ''
        this.form = {
          date: v.date || v.visitDate || '',
          type: v.type || '現場拜訪',
          attendees: v.attendees
            ? [...v.attendees]
            : (v.visitPeople ? v.visitPeople.split(/[、,，]/).map(s=>s.trim()).filter(Boolean) : []),
          content: v.content || '',
          contactNotes: v.contactNotes || '',
          note: v.note || '',
          _orig: v,
        }
        this.showModal = true
      },

      closeModal() { this.showModal = false; this.editingId = null },

      toggleAttendee(name) {
        const idx = this.form.attendees.indexOf(name)
        if (idx === -1) this.form.attendees.push(name)
        else this.form.attendees.splice(idx, 1)
      },

      async saveRecord() {
        this.formError = ''
        if (!this.form.date) { this.formError = '請填寫日期'; return }
        if (!this.form.content.trim()) { this.formError = '請填寫工作內容'; return }
        this.saving = true

        const entry = {
          id: this.editingId || Date.now(),
          date: this.form.date,
          type: this.form.type || '現場拜訪',
          attendees: [...this.form.attendees],
          content: this.form.content.trim(),
          contactNotes: this.form.contactNotes.trim(),
          note: this.form.note.trim(),
          createdAt: this.form._orig?.createdAt || new Date().toISOString(),
          createdBy: this.form._orig?.createdBy || (this.session.displayName || ''),
          updatedAt: this.editingId ? new Date().toISOString() : undefined,
          updatedBy: this.editingId ? (this.session.displayName || '') : undefined,
        }

        if (this.editingId) {
          const idx = this.visits.findIndex(v => v.id === this.editingId)
          if (idx !== -1) this.visits[idx] = entry
        } else {
          this.visits.push(entry)
        }

        await this.persist()
        this.saving = false
        this.closeModal()
      },

      async deleteRecord(v) {
        const label = (v.date || v.visitDate || '') + (v.type ? ' · ' + v.type : '')
        if (!confirm(`確認刪除此拜訪紀錄？\n${label}\n此操作無法復原。`)) return
        const idx = this.visits.findIndex(x => x.id === v.id)
        if (idx !== -1) this.visits.splice(idx, 1)
        await this.persist()
      },

      async persist() {
        if (!this.customer) return
        try {
          await fetch(`${API}/customers/${this.customer.id}/visits`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
            body: JSON.stringify({ visits: this.visits })
          })
        } catch {}
      },

      logout() {
        fetch('/api/auth/logout', { method:'POST', headers:{ Authorization:'Bearer '+(this.session.token||'') } }).catch(()=>{})
        localStorage.removeItem('motrix_session'); location.href = 'login.html'
      },
    }
  }
