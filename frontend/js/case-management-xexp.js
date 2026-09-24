// case-management-xexp.js — 案件管理頁：額外支出分頁
// CM12 P1（2026-09-24）：由 case-management.js 原樣搬出，成員文字未改；組合見 case-management-core.js 的 app()。
window.CM_PARTS = window.CM_PARTS || []
window.CM_PARTS.push(() => ({

    // ── 額外支出（2026-09-11，從精算頁搬過來）──
    // 資料在 case_extra_expenses 表（DB v75），不再是 settlement.extraItems。
    // loading 預設 true：分頁列在 selected 一設好就出現，若預設 false 會先閃一下
    // 空狀態再跳載入中——叫料那一區踩過同一個坑。
    xe: {
      loading: true, busy: false, items: [], categories: [],
      totalAmount: 0, totalPending: 0, pendingCount: 0,
      msg: '', msgError: false,
    },

    // ── 額外支出（2026-09-11）────────────────────────────────────────────────
    async loadExtraExpenses(quoteNo, pre) {
      if (!quoteNo) return
      const live = this._selectLive()
      // 比照 loadMaterialOrders()：發請求當下記住是哪張單，回應抵達時再比對。
      // 沒有這道守門，使用者在回應飛行途中新增的那一列會被蓋掉（同一天內
      // 在叫料與系統設定兩處各踩過一次）
      this._xeReqFor = quoteNo
      this.xe.loading = true
      try {
        const r = pre ? this._preResp(pre) : await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/extra-expenses`, {
          headers: { Authorization: 'Bearer ' + this.session.token }
        })
        if (!live()) return
        if (this._xeReqFor !== quoteNo) return
        if (r.ok) {
          const d = await r.json()
          // 有未存檔的新列（id 為 null）就不要整包覆蓋，保留使用者打到一半的東西
          const drafts = this.xe.items.filter(i => !i.id)
          const prev = Object.fromEntries(this.xe.items.filter(i => i.id).map(i => [i.id, i]))
          this.xe.items = (d.items || []).map(i => {
            const p = prev[i.id]
            // 變更申請面板：伺服器上還沒有這筆變更申請（changeStatus 空）、但使用者
            // 正在本機填 → 保留他打到一半的內容。少了這道守門，任何一次背景重載
            // 都會把輸入中的東西清空，而且畫面上不會有任何錯誤（同一天內已經在
            // 叫料與系統設定兩處各踩過一次同樣的競態）
            if (p && p._editing && !i.changeStatus) {
              return { ...i, _dirty: false, _editing: true, change: p.change, _changeDirty: p._changeDirty }
            }
            return { ...i, _dirty: false, _editing: !!i.changeStatus, _changeDirty: false }
          }).concat(drafts)
          this.xe.categories = d.categories || []
          this.xe.totalAmount = d.totalAmount || 0
          this.xe.totalPending = d.totalPending || 0
          this.xe.pendingCount = d.pendingCount || 0
        }
      } catch {}
      this.xe.loading = false
    },

    // 可編輯狀態：草稿與已駁回。已核准的金額已經進了成本與報表，簽核中的改了
    // 簽核就失去意義——後端也會擋，這裡擋是為了不要讓人填完才被退回
    xeEditable(x) { return !x.id || x.status === '草稿' || x.status === '已駁回' },

    xeStatusStyle(status) {
      if (status === '已核准') return 'background:var(--tone-success-bg-strong);color:var(--tone-success-fg)'
      if (status === '已駁回') return 'background:var(--tone-danger-bg-strong);color:var(--tone-danger-fg)'
      if (status === '草稿')   return 'background:var(--surface-neutral);color:var(--ink-secondary)'
      return 'background:var(--tone-warning-bg-strong);color:var(--tone-warning-fg)'   // 待審核／簽核中
    },

    xeDirty(i) { this.xe.items[i]._dirty = true; this.xe.msg = '' },

    // 小計只算給畫面即時顯示用；真正的值以後端算的為準（後端不吃前端傳的金額）
    xeRecalc(i) {
      const x = this.xe.items[i]
      x.totalCost = Math.round((Number(x.qty) || 0) * (Number(x.unitCost) || 0) * 100) / 100
      this.xeDirty(i)
    },

    // 支出人「可選可自由文字」：打的字剛好等於某位使用者的顯示名就一併記下
    // username（之後才做得了「某人代墊多少」的彙總），否則只留純文字
    xePayerInput(i) {
      const x = this.xe.items[i]
      const hit = (this.selectableUsers || []).find(
        u => (u.display_name || u.username) === (x.payerName || '').trim())
      x.payerUsername = hit ? hit.username : ''
      this.xeDirty(i)
    },

    xeAdd() {
      this.xe.items.push({
        id: null, category: (this.xe.categories[0] || '其他'), description: '',
        qty: 1, unit: '', unitCost: 0, totalCost: 0, note: '',
        expenseDate: new Date().toISOString().slice(0, 10), docNo: '',
        payerUsername: '', payerName: '',
        createdByName: this.session.displayName || this.session.username || '',
        createdByInferred: false, createdAt: '', updatedAt: '', updatedByName: '',
        status: '草稿', approval: {}, _dirty: true,
      })
      this.xe.msg = ''
    },

    _xeBody(x) {
      return {
        category: x.category, description: (x.description || '').trim(),
        qty: Number(x.qty) || 0, unit: (x.unit || '').trim(),
        unitCost: Number(x.unitCost) || 0, note: (x.note || '').trim(),
        expenseDate: x.expenseDate || '', docNo: (x.docNo || '').trim(),
        payerUsername: x.payerUsername || '', payerName: (x.payerName || '').trim(),
      }
    },

    _xeFail(msg) { this.xe.msgError = true; this.xe.msg = msg; this.xe.busy = false },

    // `AC2`：額外支出的發票日期／付款日（'' ＝清除），專用端點，任何狀態都可以登
    async xeSetDates(x, fields) {
      const quoteNo = this.selected?.quote_no
      if (!quoteNo || !x.id) return
      try {
        const r = await fetch(`/api/quotations/${encodeURIComponent(quoteNo)}/extra-expenses/${x.id}/dates`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(fields)
        })
        const j = await r.json().catch(() => ({}))
        if (!r.ok) { this._xeFail(j.detail || '日期儲存失敗'); return }
        if ('invoiceDate' in j) x.invoiceDate = j.invoiceDate
        if ('paidDate' in j) x.paidDate = j.paidDate
        this.flashSaved('xe-' + x.id)
        if (j.updatedAt) x.updatedAt = j.updatedAt
      } catch (e) { this._xeFail('網路錯誤：' + e.message) }
    },

    async xeSave(i) {
      const x = this.xe.items[i]
      if (!(x.description || '').trim()) { this._xeFail('請先填品項說明'); return }
      const quoteNo = this.selected?.quote_no
      if (!quoteNo) return
      this.xe.busy = true; this.xe.msg = ''
      const base = `/api/quotations/${encodeURIComponent(quoteNo)}/extra-expenses`
      try {
        const r = await fetch(x.id ? `${base}/${x.id}` : base, {
          method: x.id ? 'PATCH' : 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify(this._xeBody(x)),
        })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('儲存失敗：' + (d.detail || r.status)); return
        }
        this.xe.msgError = false; this.xe.msg = '已儲存'
        setTimeout(() => { if (this.xe.msg === '已儲存') this.xe.msg = '' }, 2500)
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(quoteNo)
    },

    async xeSubmit(i) {
      const x = this.xe.items[i]
      if (!x.id) { this._xeFail('請先儲存再送審'); return }
      if (!confirm(`確定送審這筆額外支出？\n\n${x.description}　NT$ ${Math.round(x.totalCost || 0).toLocaleString()}\n\n送審後在簽核完成前不能修改。`)) return
      const quoteNo = this.selected?.quote_no
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(
          `/api/quotations/${encodeURIComponent(quoteNo)}/extra-expenses/${x.id}/submit`,
          { method: 'POST', headers: { Authorization: 'Bearer ' + this.session.token } })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { this._xeFail('送審失敗：' + (d.detail || r.status)); return }
        this.xe.msgError = false
        this.xe.msg = d.autoApproved ? '未設定簽核層，已直接核准' : '已送審'
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(quoteNo)
    },

    async xeUploadFiles(i, evt) {
      const x = this.xe.items[i]
      const files = evt?.target?.files
      if (!x.id || !files || !files.length) return
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(
          `/api/quotations/${encodeURIComponent(this.selected.quote_no)}/extra-expenses/${x.id}/files`,
          { method: 'POST', headers: { Authorization: 'Bearer ' + this.session.token }, body: fd })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('上傳失敗：' + (d.detail || r.status)); return
        }
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      evt.target.value = ''   // 清掉才能重複選同一個檔案
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    async xeDeleteFile(i, fileId) {
      const x = this.xe.items[i]
      if (!x.id || !confirm('確定刪除這個附件？')) return
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(
          `/api/quotations/${encodeURIComponent(this.selected.quote_no)}/extra-expenses/${x.id}/files/${fileId}`,
          { method: 'DELETE', headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('刪除失敗：' + (d.detail || r.status)); return
        }
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    async xeDelete(i) {
      const x = this.xe.items[i]
      if (!x.id) { this.xe.items.splice(i, 1); return }   // 還沒存過，直接移除
      if (!confirm(`確定刪除「${x.description}」？`)) return
      const quoteNo = this.selected?.quote_no
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(
          `/api/quotations/${encodeURIComponent(quoteNo)}/extra-expenses/${x.id}`,
          { method: 'DELETE', headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('刪除失敗：' + (d.detail || r.status)); return
        }
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(quoteNo)
    },

    // ── 額外支出：已核准之後的變更申請（2026-09-11）──────────────────────────
    //
    // 使用者交辦：已核准後附件上鎖，要改內容得按「編輯」走審核，而且**原核准金額
    // 不動、核准後才生效**。所以這裡刻意分成兩區：上面那排欄位永遠顯示「目前生效
    // 的值」（唯讀），變更申請是另一塊面板，填的是「提議的新值」。使用者一眼就能
    // 對照改了什麼——如果直接讓人在原欄位上改，畫面看起來就像已經生效了。

    xeCanModify(x) {
      // 後端才是最終權威（_can_modify）；這裡擋是為了不要讓人填完才被 403 退回
      if (['superadmin', 'admin'].includes(this.session.role)) return true
      return !!x.createdBy && x.createdBy === this.session.username
    },

    // 附件上鎖：已核准就不能再上傳/刪除。要補憑證請走變更申請的「待核准附件」
    xeFilesLocked(x) { return x.status === '已核准' },

    xeInChange(x)        { return !!x._editing || !!x.changeStatus },
    xeChangeEditable(x)  { return !x.changeStatus || x.changeStatus === '草稿' || x.changeStatus === '已駁回' },
    xeChangeFiles(x)     { return (x.change && x.change.addFiles) || [] },

    xeChangeStatusStyle(s) {
      if (s === '已駁回') return 'background:var(--tone-danger-bg-strong);color:var(--tone-danger-fg)'
      if (s === '草稿')   return 'background:var(--surface-neutral);color:var(--ink-secondary)'
      return 'background:var(--tone-warning-bg-strong);color:var(--tone-warning-fg)'   // 待審核／簽核中
    },

    xeStartEdit(i) {
      const x = this.xe.items[i]
      if (!this.xeCanModify(x)) { this._xeFail('只有填寫人本人或管理員可以提出變更申請'); return }
      if (!x.change || !Object.keys(x.change).length) {
        // 從目前生效的值開一份提議，使用者只要改動到的欄位
        x.change = {
          category: x.category, description: x.description, qty: x.qty, unit: x.unit,
          unitCost: x.unitCost, totalCost: x.totalCost, note: x.note,
          expenseDate: x.expenseDate, docNo: x.docNo,
          payerUsername: x.payerUsername, payerName: x.payerName, addFiles: [],
        }
      }
      x._editing = true
      x._changeDirty = false
      this.xe.msg = ''
    },

    xeChangeDirty(i) { this.xe.items[i]._changeDirty = true; this.xe.msg = '' },

    xeChangeRecalc(i) {
      const c = this.xe.items[i].change
      c.totalCost = Math.round((Number(c.qty) || 0) * (Number(c.unitCost) || 0) * 100) / 100
      this.xeChangeDirty(i)
    },

    xeChangePayerInput(i) {
      const c = this.xe.items[i].change
      const hit = (this.selectableUsers || []).find(
        u => (u.display_name || u.username) === (c.payerName || '').trim())
      c.payerUsername = hit ? hit.username : ''
      this.xeChangeDirty(i)
    },

    _xeChangeBase(x) {
      return `/api/quotations/${encodeURIComponent(this.selected.quote_no)}/extra-expenses/${x.id}/change-request`
    },

    async xeSaveChange(i) {
      const x = this.xe.items[i]
      const c = x.change || {}
      if (!(c.description || '').trim()) { this._xeFail('請先填品項說明'); return }
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(this._xeChangeBase(x), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this.session.token },
          body: JSON.stringify({
            category: c.category, description: (c.description || '').trim(),
            qty: Number(c.qty) || 0, unit: (c.unit || '').trim(),
            unitCost: Number(c.unitCost) || 0, note: (c.note || '').trim(),
            expenseDate: c.expenseDate || '', docNo: (c.docNo || '').trim(),
            payerUsername: c.payerUsername || '', payerName: (c.payerName || '').trim(),
          }),
        })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('儲存失敗：' + (d.detail || r.status)); return
        }
        this.xe.msgError = false; this.xe.msg = '變更申請已存草稿，按「送審」才會進簽核'
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    async xeSubmitChange(i) {
      const x = this.xe.items[i]
      const c = x.change || {}
      if (x._changeDirty) { this._xeFail('請先儲存變更申請再送審'); return }
      if (!x.changeStatus) { this._xeFail('請先儲存變更申請再送審'); return }
      const oldA = Math.round(x.totalCost || 0).toLocaleString()
      const newA = Math.round(c.totalCost || 0).toLocaleString()
      if (!confirm(`確定送審這筆變更申請？\n\n${c.description}\nNT$ ${oldA} → NT$ ${newA}\n\n`
                 + `核准之前，這筆額外支出維持原本的 NT$ ${oldA}，報表數字不會變動。`)) return
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(`${this._xeChangeBase(x)}/submit`, {
          method: 'POST', headers: { Authorization: 'Bearer ' + this.session.token } })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { this._xeFail('送審失敗：' + (d.detail || r.status)); return }
        this.xe.msgError = false
        this.xe.msg = d.autoApproved ? '未設定簽核層，變更已直接生效' : '變更申請已送審'
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    async xeCancelChange(i) {
      const x = this.xe.items[i]
      // 還沒送到後端的，純粹關掉面板就好
      if (!x.changeStatus) { x._editing = false; x.change = {}; x._changeDirty = false; return }
      if (!confirm('確定撤銷這筆變更申請？已上傳的待核准附件會一併刪除。')) return
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(this._xeChangeBase(x), {
          method: 'DELETE', headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('撤銷失敗：' + (d.detail || r.status)); return
        }
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    async xeUploadChangeFiles(i, evt) {
      const x = this.xe.items[i]
      const files = evt?.target?.files
      if (!files || !files.length) return
      if (!x.changeStatus) { this._xeFail('請先按「儲存變更」建立草稿，再上傳待核准附件'); evt.target.value = ''; return }
      const fd = new FormData()
      for (const f of files) fd.append('files', f)
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(`${this._xeChangeBase(x)}/files`, {
          method: 'POST', headers: { Authorization: 'Bearer ' + this.session.token }, body: fd })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('上傳失敗：' + (d.detail || r.status)); return
        }
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      evt.target.value = ''   // 清掉才能重複選同一個檔案
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    async xeDeleteChangeFile(i, fileId) {
      const x = this.xe.items[i]
      if (!confirm('確定刪除這個待核准附件？')) return
      this.xe.busy = true; this.xe.msg = ''
      try {
        const r = await fetch(`${this._xeChangeBase(x)}/files/${fileId}`, {
          method: 'DELETE', headers: { Authorization: 'Bearer ' + this.session.token } })
        if (!r.ok) {
          const d = await r.json().catch(() => ({}))
          this._xeFail('刪除失敗：' + (d.detail || r.status)); return
        }
      } catch (e) { this._xeFail('網路錯誤：' + e.message); return }
      this.xe.busy = false
      await this.loadExtraExpenses(this.selected.quote_no)
    },

    // CM12 P2：切換案件時重設本模組的案件層級狀態（時點見 core 的 _resetCaseScoped）
    _reset_xexp(phase, data) {
      if (phase === 'late') {
        this.xe ={ ...this.xe, loading: true, items: [], totalAmount: 0,
                    totalPending: 0, pendingCount: 0, msg: '', busy: false }
      }
    },
}))
