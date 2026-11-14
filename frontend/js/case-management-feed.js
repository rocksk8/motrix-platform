// case-management-feed.js — 案件管理頁：動態分頁：案件動態、工作日誌、今日工作
// CM12 P1（2026-09-24）：由 case-management.js 原樣搬出，成員文字未改；組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({

    caseTasks: [],
    caseTasksLoading: false,
    caseTasksOpen: true,

    // ── 今日相關任務 回報 ──
    caseTaskEditing: { taskId: null, text: '' },
    caseTaskEditSubmitting: false,
    caseTaskEditLogs: {},
    caseTaskLogsOpen: {},

    // ── 動態 Tab ──
    caseUpdates: [],
    updatesLoading: false,
    newComment: '',
    newCommentImportant: false,
    newCommentPhotos: [],
    newCommentHours: '',
    newCommentContactType: '',
    newCommentContactTypeCustom: '',
    newCommentLogDate: MotrixDate.today(),
    newCommentUserId: '',   // 空字串＝記錄人＝目前登入者，見 postWorkLogEntry()
    postingComment: false,

    // ── T86 案件 UX #4：統一的「新增記錄」編輯器（記錄類型）──
    // note＝留言／工作日誌（原發文框；填執行時數／聯絡事項才記成工作日誌）；visit＝某階段的出勤記錄（日期、人次、工作內容）；
    // task＝每日工作事項（另一個頁面，這裡只給前往連結）。三種各自照原本的端點與權限寫入，這裡只是同一個入口。
    composeType: 'note',
    composeStageId: '',
    composeVisitDate: MotrixDate.today(),
    composeVisitPeople: 1,
    // 目前實際生效的類型：選過的類型在這個案件／這個人身上不可用時（例如換到沒有階段的案件）退回「留言／工作日誌」
    composeKind() { return this.composeTypes().some(t => t.key === this.composeType) ? this.composeType : 'note' },
    composeTypes() {
      const out = [{ key: 'note', label: '留言／工作日誌' }]
      if (this.tShown('exec') && this.sShown('progress') && ((this.cr && this.cr.caseRecord && this.cr.caseRecord.stages) || []).length) out.push({ key: 'visit', label: '階段出勤' })
      if (this.canLogTask()) out.push({ key: 'task', label: '每日工作事項' })
      return out
    },
    setComposeType(kind) {
      if (!this.composeTypes().some(t => t.key === kind)) kind = 'note'
      this.composeType = kind
      if (kind !== 'visit') return
      const stages = (this.cr && this.cr.caseRecord && this.cr.caseRecord.stages) || []
      if (!stages.some(st => String(st.id) === String(this.composeStageId))) {
        const cur = stages.find(st => !st.done) || stages[0]
        this.composeStageId = cur ? String(cur.id) : ''
      }
      this._composeVisitDefaults()
    },
    _composeVisitDefaults() {
      const st = ((this.cr && this.cr.caseRecord && this.cr.caseRecord.stages) || []).find(x => String(x.id) === String(this.composeStageId))
      const last = ((st && st.visits) || []).filter(v => Number(v.visitPeople) > 0).slice(-1)[0]
      this.composeVisitDate = MotrixDate.today()
      this.composeVisitPeople = last ? Number(last.visitPeople) : 1
    },
    _composePeopleOk() { const n = Number(this.composeVisitPeople); return Number.isInteger(n) && n >= 1 && n <= 99 },
    composeSendDisabled() {
      if (this.postingComment) return true
      if (this.composeKind() === 'visit') return !this.composeStageId || !this._composePeopleOk()
      return !this.newComment.trim() && this.newCommentPhotos.length === 0
    },
    composeSendHint() {
      if (this.postingComment) return ''
      if (this.composeKind() === 'visit') return !this.composeStageId ? '請先選擇階段。' : (!this._composePeopleOk() ? '人次請填 1 到 99 的整數。' : '')
      return (!this.newComment.trim() && this.newCommentPhotos.length === 0) ? '請先填寫內容或附加檔案。' : ''
    },
    composeSubmit() {
      return this.composeKind() === 'visit' ? this.postVisitFromFeed() : this.postComment()
    },
    async postVisitFromFeed() {
      const st = ((this.cr && this.cr.caseRecord && this.cr.caseRecord.stages) || []).find(x => String(x.id) === String(this.composeStageId))
      if (!st || this.composeSendDisabled()) return
      this.postingComment = true
      try {
        const r = await fetch(`${this._stagesApiBase()}/${st.id}/visits`, {
          method: 'POST', headers: this._authHeaders(true),
          body: JSON.stringify({ visitDate: this.composeVisitDate || MotrixDate.today(), visitPeople: Number(this.composeVisitPeople), note: this.newComment.trim() })
        })
        if (!r.ok) {
          let why = ''
          try { const j = await r.json(); why = typeof j.detail === 'string' ? j.detail : '' } catch {}
          MotrixUI.toast(why ? '新增出勤記錄失敗：' + why : '新增出勤記錄失敗，請稍後再試。', {kind: 'error'}); return
        }
        Object.assign(st, await r.json())
        this.newComment = ''
        // 出勤記錄不會出現在動態清單，在階段卡裡看：給一個直接過去的按鈕
        MotrixUI.toast(`已在「${st.label || '未命名階段'}」新增出勤記錄。`, {ms: 8000, action: { label: '在執行進度查看', onClick: () => { this.activeTab = 'exec'; this.execSubTab = 'progress' } }})
        this._composeVisitDefaults()
      } catch (e) { MotrixUI.toast('發生錯誤：' + e.message, {kind: 'error'}) }
      finally { this.postingComment = false }
    },
    _ptCache: {},
    feedCalMode:    false,
    feedCalYear:    new Date().getFullYear(),
    feedCalMonth:   new Date().getMonth() + 1,
    feedCalSelDate: '',

    async _loadCaseTasks(quoteNo) {
      if (!quoteNo) return
      // T86 F①：後端要 daily_task 或 case_manage 模組（最高管理者直通）；沒有就一定 403 ⇒ 不送
      if (this.session.role !== 'superadmin' && !this.hasModule('daily_task') && !this.hasModule('case_manage')) { this.caseTasks = []; this.caseTasksLoading = false; return }
      const live = this._selectLive()
      this.caseTasksLoading = true
      try {
        const today = MotrixDate.today()
        const r = await fetch(`/api/daily-tasks?date=${today}&case_no=${encodeURIComponent(quoteNo)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? (await r.json()).items || [] : null
        if (!live()) return
        if (r.ok) this.caseTasks = body
      } catch {}
      this.caseTasksLoading = false
    },

    // ── 承攬商派發 methods ──────────────────────────────────────────────────────

    // ── 動態 Tab ──────────────────────────────────────────────────────────────

    async loadCaseUpdates(quoteNo, pre) {
      if (!quoteNo) return
      const live = this._selectLive()
      this.updatesLoading = true
      this.caseUpdates = []
      this.feedCalMode = false
      this.feedCalSelDate = ''
      try {
        const r = pre ? this._preResp(pre) : await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/updates`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        const body = r.ok ? await r.json() : null
        if (!live()) return
        if (r.ok) this.caseUpdates = body
      } catch {}
      this.updatesLoading = false
    },

    // ── 動態 Tab：月曆總覽（依已載入的 caseUpdates 統計每日筆數，點日期篩選） ──
    toggleFeedCalMode() {
      this.feedCalMode = !this.feedCalMode
      if (!this.feedCalMode) this.feedCalSelDate = ''
    },
    feedCalPrevMonth() {
      this.feedCalMonth--
      if (this.feedCalMonth < 1) { this.feedCalMonth = 12; this.feedCalYear-- }
    },
    feedCalNextMonth() {
      this.feedCalMonth++
      if (this.feedCalMonth > 12) { this.feedCalMonth = 1; this.feedCalYear++ }
    },
    feedCalDays() {
      const year = this.feedCalYear, month = this.feedCalMonth
      const _ld = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
      const todayStr = _ld(new Date())
      const first    = new Date(year, month - 1, 1)
      const daysInM  = new Date(year, month, 0).getDate()
      const startDow = first.getDay()
      const startPad = startDow === 0 ? 6 : startDow - 1
      const cells = []
      for (let i = startPad; i > 0; i--) {
        const d = new Date(year, month - 1, 1 - i)
        cells.push({ date: _ld(d), day: d.getDate(), inMonth: false, isToday: false })
      }
      for (let i = 1; i <= daysInM; i++) {
        const s = `${year}-${String(month).padStart(2,'0')}-${String(i).padStart(2,'0')}`
        cells.push({ date: s, day: i, inMonth: true, isToday: s === todayStr })
      }
      let nxt = 1
      while (cells.length < 42) {
        const d = new Date(year, month, nxt++)
        cells.push({ date: _ld(d), day: d.getDate(), inMonth: false, isToday: false })
      }
      return cells
    },
    // T86 案件 UX #5：階段勾選完成時，系統會自動記一筆「案件管理勾選「X」完成」（backend/modules/case/case_stage_tasks.py，
    // 內容文字以 AUTO_STAGE_PREFIX 開頭）。這類機械記錄預設摺疊，避免稀釋人寫的動態；可按「顯示」展開。
    feedShowAuto: false,
    AUTO_STAGE_PREFIX: '案件管理勾選「',
    isAutoFeedItem(it) {
      return it.source === 'daily_task' && String(it.content || '').startsWith(this.AUTO_STAGE_PREFIX)
    },
    feedBadgeCount() { return this._feedBase().length },      // 分頁角標＝目前看得到的則數（摺疊的系統自動記錄不算）
    autoFeedCount() { return this.caseUpdates.filter(it => this.isAutoFeedItem(it)).length },
    _feedBase() {
      return this.feedShowAuto ? this.caseUpdates : this.caseUpdates.filter(it => !this.isAutoFeedItem(it))
    },
    feedCalCount(date) {
      return this._feedBase().filter(it => (it.created_at || '').replace('T',' ').slice(0,10) === date).length
    },
    filteredFeedItems() {
      if (!this.feedCalSelDate) return this._feedBase()
      return this._feedBase().filter(it => (it.created_at || '').replace('T',' ').slice(0,10) === this.feedCalSelDate)
    },

    onCommentPhotosSelected(e) {
      this.newCommentPhotos = Array.from(e.target.files || [])
    },

    // 工作日誌照片簽章 URL（跟 projects.html 既有的 photoUrl()/_ptCache 同一套
    // 作法：短效期 pt token，抓回來前先回 1x1 透明圖，避免完整 session token
    // 外洩到網址列/瀏覽器歷史）。
    photoUrl(path) {
      if (!path) return ''
      const now = Math.floor(Date.now() / 1000)
      const cached = this._ptCache[path]
      if (cached && cached.exp > now) {
        return `/api/uploads/${path}?pt=${cached.pt}`
      }
      if (!this._ptCache[path + '_fetching']) {
        this._ptCache[path + '_fetching'] = true
        fetch(`/api/photo-token?path=${encodeURIComponent(path)}`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
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
      return 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBTAA7'
    },

    // 聯絡事項選單非「其他」時直接用選項文字，選「其他」時用自訂輸入
    resolvedContactType() {
      return this.newCommentContactType === '其他'
        ? this.newCommentContactTypeCustom.trim()
        : this.newCommentContactType
    },

    async postComment() {
      const content = this.newComment.trim()
      if (!content || this.postingComment) return
      // 填執行時數、選聯絡事項類型、改過日期、或指定記錄對象 → 當成工作日誌
      // （那些是工作日誌才有的結構化欄位），走 work_logs；否則維持輕量留言
      // （case_updates，含「標記為重要」＋ Google 行事曆同步）。
      //
      // 2026-09-14：**照片不再是觸發條件**。在那之前只要選了照片就會被改存成
      // 工作日誌——附件本身跟「這是不是一筆工時記錄」無關，卻悄悄換掉了紀錄
      // 種類，而且換過去就失去「標記為重要」與行事曆同步。case_updates 現在
      // 自己支援附件（DB v82），這個轉向沒有必要了。
      const isBackdated = this.newCommentLogDate !== MotrixDate.today()
      if (this.newCommentHours || this.newCommentContactType ||
          isBackdated || this.newCommentUserId) {
        await this.postWorkLogEntry(content)
        return
      }
      this.postingComment = true
      try {
        // multipart：文字與附件同一個請求送出，不會有「留言貼了、圖沒上去」
        // 的半完成狀態。不要自己設 Content-Type——boundary 要讓瀏覽器帶。
        const fd = new FormData()
        fd.append('content', content)
        fd.append('important', this.newCommentImportant ? 'true' : 'false')
        this.newCommentPhotos.forEach(f => fd.append('files', f))
        const r = await fetch(`/api/quotations/${encodeURIComponent(this.selected.quote_no)}/updates`, {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token },
          body: fd
        })
        if (r.ok) {
          const item = await r.json()
          this.caseUpdates.unshift(item)
          this.newComment = ''
          this.newCommentImportant = false
          this.newCommentPhotos = []
          if (this.$refs.commentPhotoInput) this.$refs.commentPhotoInput.value = ''
        } else {
          const err = await r.json().catch(() => ({}))
          MotrixUI.toast('留言失敗：' + (err.detail || r.status), {kind: 'error'})
        }
      } catch (e) {
        MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'})
      }
      this.postingComment = false
    },

    // 附件刪除限 admin+（2026-09-14 使用者裁示）——抽掉附件是只改證據、
    // 留下文字，跟「刪掉自己整則留言」不是同一件事。
    canDeleteAttachment() {
      return ['superadmin', 'admin'].includes(this.session.role)
    },
    async deleteCommentFile(update, file) {
      if (!this.canDeleteAttachment()) return
      if (!(await MotrixUI.confirm(`確定刪除附件「${file.filename}」？此動作無法復原。`, {danger: true}))) return
      try {
        const r = await fetch(
          `/api/quotations/${encodeURIComponent(this.selected.quote_no)}/updates/${update.id}/files/${file.id}`,
          { method: 'DELETE', headers: { Authorization: 'Bearer ' + this.session.token } })
        if (r.ok) {
          update.files = (await r.json()).files || []
        } else {
          const err = await r.json().catch(() => ({}))
          MotrixUI.toast('刪除失敗：' + (err.detail || r.status), {kind: 'error'})
        }
      } catch (e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
    },
    // fileUrl() 已移除（2026-09-15）：它把 **session token** 當成 `pt` 送給
    // /api/uploads/，而 `pt` 是 routers/uploads.py 用 HMAC 簽出來的短效簽章
    // （先跟 `/api/photo-token` 換），兩者形狀不同、必定驗不過——動態附件從
    // 上線起每一張都是 403。同頁其他附件（回簽／憑據）本來就走
    // previewAttachmentFile()，工作日誌照片走 photoUrl()，這裡改為沿用同兩支，
    // 不再留一支容易誤用的同義函式。業務開發記錄（dev-crm.html）同一個 commit
    // 犯了同樣的錯，已一起修。
    isImageFile(f) {
      return /\.(jpe?g|png)$/i.test(f.filename || f.path || '')
    },

    async postWorkLogEntry(content) {
      this.postingComment = true
      try {
        const uid = (this.newCommentUserId && this.session.role === 'superadmin') ? Number(this.newCommentUserId) : this.session.id   // 只有最高管理者能替別人記錄（伺服器也擋）
        const r = await fetch('/api/work-logs', {
          method: 'POST',
          headers: { Authorization: 'Bearer ' + this.session.token, 'Content-Type': 'application/json' },
          body: JSON.stringify({
            log_date: this.newCommentLogDate || MotrixDate.today(),
            user_id: uid, content,
            hours: this.newCommentHours || 8, case_no: this.selected.quote_no,
            contact_type: this.resolvedContactType(),
          })
        })
        if (!r.ok) { MotrixUI.toast('新增工作日誌失敗：' + (await r.json()).detail, {kind: 'error'}); return }
        const { id } = await r.json()
        if (this.newCommentPhotos.length > 0) {
          const fd = new FormData()
          this.newCommentPhotos.forEach(f => fd.append('files', f))
          const rp = await fetch(`/api/work-logs/${id}/photos`, {
            method: 'POST',
            headers: { Authorization: 'Bearer ' + this.session.token },
            body: fd
          })
          if (!rp.ok) MotrixUI.toast('照片上傳失敗：' + (await rp.json()).detail, {kind: 'error'})
        }
        this.newComment = ''
        this.newCommentImportant = false
        this.newCommentPhotos = []
        this.newCommentHours = ''
        this.newCommentContactType = ''
        this.newCommentContactTypeCustom = ''
        this.newCommentLogDate = MotrixDate.today()
        this.newCommentUserId = ''
        await this.loadCaseUpdates(this.selected.quote_no)
      } catch(e) {
        MotrixUI.toast('發生錯誤：' + e.message, {kind: 'error'})
      } finally {
        this.postingComment = false
      }
    },

    async deleteUpdate(uid) {
      if (!(await MotrixUI.confirm('確定刪除這則更新？', {danger: true}))) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(this.selected.quote_no)}/updates/${uid}`, {
          method: 'DELETE',
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (r.ok) this.caseUpdates = this.caseUpdates.filter(x => x.id !== uid)
      } catch {}
    },

    fmtFeedTime(ts) {
      if (!ts) return ''
      try {
        const d = new Date(ts.replace(' ', 'T'))
        const now = new Date()
        const diff = Math.floor((now - d) / 1000)
        if (diff < 60) return '剛剛'
        if (diff < 3600) return Math.floor(diff / 60) + ' 分鐘前'
        if (diff < 86400) return Math.floor(diff / 3600) + ' 小時前'
        if (diff < 86400 * 3) return Math.floor(diff / 86400) + ' 天前'
        return ts.slice(0, 10)
      } catch { return ts.slice(0, 10) }
    },

    // ── 今日相關任務 回報 helpers ──────────────────────────────────────────────
    _caseMyComp(t) {
      return (t.completions || []).find(c => c.username === this.session.username)
    },

    _caseTaskStartEdit(t) {
      const comp = this._caseMyComp(t)
      this.caseTaskEditing = { taskId: t.id, text: comp?.report || '' }
    },

    async _caseTaskSubmitReport(taskId) {
      const text = this.caseTaskEditing.text.trim()
      if (!text) { MotrixUI.toast('請填寫回報內容', {kind: 'error'}); return }
      this.caseTaskEditSubmitting = true
      try {
        const today = MotrixDate.today()
        const r = await fetch(`/api/daily-tasks/${taskId}/complete`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({ completed: true, report: text, occurrence_date: today })
        })
        if (!r.ok) { const e = await r.json().catch(() => ({})); MotrixUI.toast(e.detail || '送出失敗', {kind: 'error'}); return }
        this.caseTaskEditing = { taskId: null, text: '' }
        await this._loadCaseTasks(this.selected?.quote_no)
      } catch(e) { MotrixUI.toast('網路錯誤：' + e.message, {kind: 'error'}) }
      this.caseTaskEditSubmitting = false
    },

    async _caseTaskToggleLog(taskId) {
      this.caseTaskLogsOpen = { ...this.caseTaskLogsOpen, [taskId]: !this.caseTaskLogsOpen[taskId] }
      if (this.caseTaskLogsOpen[taskId] && !this.caseTaskEditLogs[taskId]) {
        try {
          const r = await fetch(`/api/daily-tasks/${taskId}/edit-log`, {
            headers: { Authorization: 'Bearer ' + this.session.token }
          })
          if (r.ok) {
            const d = await r.json()
            this.caseTaskEditLogs = { ...this.caseTaskEditLogs, [taskId]: d.items || [] }
          } else {
            this.caseTaskEditLogs = { ...this.caseTaskEditLogs, [taskId]: [] }
          }
        } catch {
          this.caseTaskEditLogs = { ...this.caseTaskEditLogs, [taskId]: [] }
        }
      }
    },

    // CM12 P2：切換案件時重設本模組的案件層級狀態（時點見 core 的 _resetCaseScoped）
    _reset_feed(phase, data) {
      if (phase === 'early') {
        this.caseTasks = []
        this.caseTasksLoading = true
      }
      if (phase === 'late') {
        this.caseUpdates = []
        this.newComment = ''
      }
    },
}))
