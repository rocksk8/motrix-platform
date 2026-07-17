  const API = ''

  function projectsPage() {
    return {
      session:   {},
      projects:  [],
      selected:  null,
      logs:      [],
      openLogs:  [],
      allUsers:  [],
      tab:       'logs',
      filterStatus: '全部',
      searchQ:   '',
      newCaseNo: '',
      infoEdit:  {},

      // Modals
      showProjectModal: false,
      editingProjectId: null,
      pForm: { name:'', status:'規劃中', description:'' },

      showLogModal: false,
      editingLogId: null,
      lForm: { log_date:'', work_content:'', attendees:[], action_items:[], materials_used:[] },
      newAttendee: '', newAttendeeText: '', newItemText: '',

      lightboxPhoto: null,
      currentUploadLog: null,
      toastMsg: '',
      _toastTimer: null,
      _ptCache: {},
      isMobileView: window.innerWidth <= 767,
      pendingFiles: [],
      pendingFileNames: [],
      editLogPhotos: [],

      get filteredProjects() {
        const q = this.searchQ.toLowerCase()
        return this.projects.filter(p => {
          if (this.filterStatus !== '全部' && p.status !== this.filterStatus) return false
          if (q && !p.name.toLowerCase().includes(q) && !p.code.toLowerCase().includes(q)) return false
          return true
        })
      },

      async init() {
        const raw = localStorage.getItem('motrix_session')
        if (!raw) { location.href = 'login.html'; return }
        this.session = JSON.parse(raw)
        if (!this.session?.token) { location.href = 'login.html'; return }
        window.addEventListener('resize', () => { this.isMobileView = window.innerWidth <= 767 })

        // Pre-select from URL ?id=
        const urlId = new URLSearchParams(location.search).get('id')
        const urlCase = new URLSearchParams(location.search).get('caseNo')

        await Promise.all([this.loadProjects(), this.loadUsers()])

        if (urlId) {
          const p = this.projects.find(p => p.id == urlId)
          if (p) await this.selectProject(p)
        } else if (urlCase) {
          const p = this.projects.find(p => (p.linked_cases||[]).includes(urlCase))
          if (p) await this.selectProject(p)
          else this.filterStatus = '全部'
        }
      },

      _h() {
        return { 'Content-Type':'application/json', 'Authorization':'Bearer '+this.session.token }
      },

      canSee(mod) {
        const m = this.session.modules || []
        return m.includes(mod) || this.session.role === 'superadmin'
      },

      canManage() {
        const m = this.session.modules || []
        return m.includes('project_manage') || this.session.role === 'superadmin' || this.session.role === 'admin'
      },

      canApproveEng() {
        const m = this.session.modules || []
        return m.includes('project_approve_eng') || this.session.role === 'superadmin'
      },

      canApproveBiz() {
        const m = this.session.modules || []
        return m.includes('project_approve_biz') || this.session.role === 'superadmin'
      },

      async loadProjects() {
        const r = await fetch(`${API}/api/projects`, {headers: this._h()})
        const d = await r.json()
        this.projects = d.items || []
      },

      async loadUsers() {
        try {
          const r = await fetch(`${API}/api/users`, {headers: this._h()})
          const d = await r.json()
          this.allUsers = (Array.isArray(d) ? d : []).filter(u => u.active)
        } catch(e) {}
      },

      async selectProject(p) {
        this.selected = p
        this.tab = 'logs'
        this.openLogs = []
        this.infoEdit = { ...p.data_json }
        await this.loadLogs()
      },

      async loadLogs() {
        if (!this.selected) return
        const r = await fetch(`${API}/api/projects/${this.selected.id}/logs`, {headers: this._h()})
        const d = await r.json()
        this.logs = d.items || []
      },

      toggleLog(id) {
        const idx = this.openLogs.indexOf(id)
        if (idx >= 0) this.openLogs.splice(idx, 1)
        else this.openLogs.push(id)
      },

      statusClass(s) {
        return {
          '規劃中': 'st-planning', '進行中': 'st-inprogress', '暫停': 'st-paused',
          '驗收中': 'st-reviewing', '完工': 'st-done', '結案': 'st-closed', '取消': 'st-cancelled'
        }[s] || ''
      },

      itemStatusClass(s) {
        return { pending:'as-pending', stage1_done:'as-stage1', done:'as-done' }[s] || 'as-pending'
      },
      itemStatusLabel(s) {
        return { pending:'待確認', stage1_done:'待業務確認', done:'已完成' }[s] || '待確認'
      },

      fmtDate(iso) {
        if (!iso) return '—'
        return iso.slice(0,10)
      },
      fmtDateTime(iso) {
        if (!iso) return ''
        return iso.slice(0,16).replace('T',' ')
      },

      photoUrl(path) {
        if (!path) return ''
        const now = Math.floor(Date.now() / 1000)
        const cached = this._ptCache[path]
        if (cached && cached.exp > now) {
          return `${API}/api/uploads/${path}?pt=${cached.pt}`
        }
        if (!this._ptCache[path + '_fetching']) {
          this._ptCache[path + '_fetching'] = true
          fetch(`${API}/api/photo-token?path=${encodeURIComponent(path)}`, {
            headers: { 'Authorization': 'Bearer ' + this.session.token }
          }).then(r => r.ok ? r.json() : null).then(d => {
            if (d && d.token) {
              this._ptCache = {
                ...this._ptCache,
                [path]: { pt: d.token, exp: now + (d.ttl || 3600) - 60 },
                [path + '_fetching']: false,
              }
            }
          }).catch(() => { this._ptCache[path + '_fetching'] = false })
        }
        return `${API}/api/uploads/${path}?token=${this.session.token}`
      },

      // ── Project CRUD ──
      openCreateProject() {
        this.editingProjectId = null
        this.pForm = { name:'', status:'規劃中', description:'' }
        this.showProjectModal = true
      },

      openEditProject() {
        if (!this.selected) return
        this.editingProjectId = this.selected.id
        this.pForm = {
          name:        this.selected.name,
          status:      this.selected.status,
          description: this.selected.description || '',
        }
        this.showProjectModal = true
      },

      async saveProject() {
        if (!this.pForm.name.trim()) return
        const body = JSON.stringify(this.pForm)
        let r
        if (this.editingProjectId) {
          r = await fetch(`${API}/api/projects/${this.editingProjectId}`, {method:'PUT', headers:this._h(), body})
        } else {
          r = await fetch(`${API}/api/projects`, {method:'POST', headers:this._h(), body})
        }
        if (!r.ok) { this.toast('儲存失敗：' + (await r.json()).detail); return }
        this.showProjectModal = false
        await this.loadProjects()
        if (this.editingProjectId) {
          const p = this.projects.find(p => p.id === this.editingProjectId)
          if (p) await this.selectProject(p)
        }
        this.toast(this.editingProjectId ? '專案已更新' : '專案已建立')
      },

      async changeStatus(s) {
        if (!s || !this.selected) return
        const r = await fetch(`${API}/api/projects/${this.selected.id}/status`, {
          method:'PATCH', headers:this._h(), body: JSON.stringify({status:s})
        })
        if (!r.ok) { this.toast('狀態更新失敗'); return }
        this.selected.status = s
        await this.loadProjects()
        this.toast(`狀態已更新為「${s}」`)
      },

      async deleteProject() {
        if (!this.selected) return
        if (!confirm(`確定要刪除專案「${this.selected.name}」？`)) return
        const r = await fetch(`${API}/api/projects/${this.selected.id}`, {method:'DELETE', headers:this._h()})
        if (!r.ok) { this.toast('刪除失敗：' + (await r.json()).detail); return }
        this.selected = null
        this.logs = []
        await this.loadProjects()
        this.toast('專案已刪除')
      },

      // ── Case linking ──
      async linkCase() {
        const qno = this.newCaseNo.trim().toUpperCase()
        if (!qno || !this.selected) return
        const linked = [...(this.selected.linked_cases || [])]
        if (linked.includes(qno)) { this.toast('已關聯'); return }
        linked.push(qno)
        await this.saveLinkedCases(linked)
        this.newCaseNo = ''
        this.toast(`已關聯案件 ${qno}`)
      },

      async unlinkCase(qno) {
        if (!this.selected) return
        const linked = (this.selected.linked_cases || []).filter(c => c !== qno)
        await this.saveLinkedCases(linked)
        this.toast(`已移除關聯 ${qno}`)
      },

      async saveLinkedCases(linked) {
        const r = await fetch(`${API}/api/projects/${this.selected.id}`, {
          method:'PUT', headers:this._h(), body: JSON.stringify({linked_cases: linked})
        })
        if (!r.ok) { this.toast('儲存失敗'); return }
        this.selected.linked_cases = linked
        await this.loadProjects()
      },

      // ── Info save ──
      async saveInfo() {
        if (!this.selected) return
        await fetch(`${API}/api/projects/${this.selected.id}`, {
          method:'PUT', headers:this._h(),
          body: JSON.stringify({data_json: this.infoEdit})
        })
      },

      // ── Log CRUD ──
      openNewLog() {
        this.editingLogId = null
        this.pendingFiles = []
        this.pendingFileNames = []
        this.editLogPhotos = []
        this.lForm = {
          log_date:       new Date().toISOString().slice(0,10),
          work_content:   '',
          attendees:      [],
          action_items:   [],
          materials_used: [],
        }
        this.newAttendee = ''; this.newAttendeeText = ''; this.newItemText = ''
        this.showLogModal = true
      },

      openEditLog(log) {
        this.editingLogId = log.id
        this.pendingFiles = []
        this.pendingFileNames = []
        this.editLogPhotos = JSON.parse(JSON.stringify(log.photos || []))
        this.lForm = {
          log_date:       log.log_date,
          work_content:   log.work_content || '',
          attendees:      [...(log.attendees||[])],
          action_items:   JSON.parse(JSON.stringify(log.action_items||[])),
          materials_used: JSON.parse(JSON.stringify(log.materials_used||[])),
        }
        this.showLogModal = true
      },

      addAttendee() {
        if (this.newAttendee && !this.lForm.attendees.includes(this.newAttendee)) {
          this.lForm.attendees.push(this.newAttendee)
        }
        this.newAttendee = ''
      },
      addAttendeeText() {
        const t = this.newAttendeeText.trim()
        if (t && !this.lForm.attendees.includes(t)) this.lForm.attendees.push(t)
        this.newAttendeeText = ''
      },
      addActionItem() {
        const t = this.newItemText.trim()
        if (!t) return
        this.lForm.action_items.push({ id:'', text:t, status:'pending' })
        this.newItemText = ''
      },

      async saveLog() {
        if (!this.selected) return
        const body = JSON.stringify(this.lForm)
        let r
        if (this.editingLogId) {
          r = await fetch(`${API}/api/projects/${this.selected.id}/logs/${this.editingLogId}`, {method:'PUT', headers:this._h(), body})
        } else {
          r = await fetch(`${API}/api/projects/${this.selected.id}/logs`, {method:'POST', headers:this._h(), body})
        }
        if (!r.ok) { this.toast('儲存失敗'); return }
        const d = await r.json()
        const logId = this.editingLogId || d.id
        if (this.pendingFiles.length && logId) {
          this.toast('照片上傳中...')
          const fd = new FormData()
          for (const f of this.pendingFiles) fd.append('files', f)
          const pr = await fetch(`${API}/api/projects/${this.selected.id}/logs/${logId}/photos`, {
            method:'POST', headers:{'Authorization':'Bearer '+this.session.token}, body:fd
          })
          if (!pr.ok) { this.toast('照片上傳失敗，日誌已儲存') }
        }
        this.pendingFiles = []
        this.pendingFileNames = []
        this.showLogModal = false
        await this.loadLogs()
        if (!this.editingLogId && logId) this.openLogs.push(logId)
        this.toast('日誌已儲存')
      },

      async deleteLog(log) {
        if (!confirm('確定要刪除此日誌？')) return
        const r = await fetch(`${API}/api/projects/${this.selected.id}/logs/${log.id}`, {method:'DELETE', headers:this._h()})
        if (!r.ok) { this.toast('刪除失敗'); return }
        await this.loadLogs()
        this.toast('日誌已刪除')
      },

      // ── Action item approval ──
      async approveItem(log, item, stage) {
        const r = await fetch(`${API}/api/projects/${this.selected.id}/logs/${log.id}/items/${item.id}/approve`, {
          method:'PATCH', headers:this._h(), body: JSON.stringify({stage})
        })
        if (!r.ok) { this.toast('簽核失敗：' + (await r.json()).detail); return }
        const d = await r.json()
        const logIdx = this.logs.findIndex(l => l.id === log.id)
        if (logIdx >= 0) this.logs[logIdx].action_items = d.items
        this.toast(stage===1 ? '工程確認完成' : '業務確認完成，事項已完成')
      },

      handlePendingFiles(e) {
        const files = Array.from(e.target.files)
        this.pendingFiles.push(...files)
        this.pendingFileNames.push(...files.map(f => f.name))
        e.target.value = ''
      },

      removePendingFile(i) {
        this.pendingFiles.splice(i, 1)
        this.pendingFileNames.splice(i, 1)
      },

      async removeExistingPhoto(ph, idx) {
        if (!this.editingLogId || !this.selected) return
        const r = await fetch(`${API}/api/projects/${this.selected.id}/logs/${this.editingLogId}/photos/${ph.id}`, {
          method:'DELETE', headers:this._h()
        })
        if (r.ok) {
          this.editLogPhotos.splice(idx, 1)
          const logObj = this.logs.find(l => l.id === this.editingLogId)
          if (logObj) logObj.photos = logObj.photos.filter(p => p.id !== ph.id)
        } else {
          this.toast('刪除失敗')
        }
      },

      // ── Photo upload ──
      triggerPhotoUpload(log) {
        this.currentUploadLog = log
        document.getElementById('photo-upload-input').value = ''
        document.getElementById('photo-upload-input').click()
      },

      async handlePhotoUpload(event, log) {
        if (!log) return
        const files = event.target.files
        if (!files || !files.length) return
        const fd = new FormData()
        for (const f of files) fd.append('files', f)
        this.toast('上傳中，加水印處理...')
        const r = await fetch(`${API}/api/projects/${this.selected.id}/logs/${log.id}/photos`, {
          method:'POST',
          headers:{ 'Authorization':'Bearer '+this.session.token },
          body: fd,
        })
        if (!r.ok) { this.toast('上傳失敗'); return }
        const d = await r.json()
        const logObj = this.logs.find(l => l.id === log.id)
        if (logObj) logObj.photos = (logObj.photos || []).concat(d.photos)
        this.toast(`已上傳 ${d.added} 張照片`)
      },

      async deletePhoto(log, photo) {
        if (!confirm('確定刪除此照片？')) return
        const r = await fetch(`${API}/api/projects/${this.selected.id}/logs/${log.id}/photos/${photo.id}`, {
          method:'DELETE', headers:this._h()
        })
        if (!r.ok) { this.toast('刪除失敗'); return }
        const logObj = this.logs.find(l => l.id === log.id)
        if (logObj) logObj.photos = logObj.photos.filter(p => p.id !== photo.id)
        this.toast('照片已刪除')
      },

      toast(msg) {
        this.toastMsg = msg
        clearTimeout(this._toastTimer)
        this._toastTimer = setTimeout(() => { this.toastMsg = '' }, 3000)
      },
    }
  }
