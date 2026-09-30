// module-builder-flow.js — ④ 流程：狀態、轉換、簽核、通知（拆自 module-builder.html）
(function () {
  window.MotrixMB.parts.push(function (MB) {
    var KEY_RE = MB.KEY_RE, FIELD_KEY_RE = MB.FIELD_KEY_RE, TYPE_LABELS = MB.TYPE_LABELS, BLOCK_LABELS = MB.BLOCK_LABELS, PARAM_LABELS = MB.PARAM_LABELS,
        FORMAT_LABELS = MB.FORMAT_LABELS, NAV = MB.NAV, TYPE_ICONS = MB.TYPE_ICONS, TYPE_ICON_GENERIC = MB.TYPE_ICON_GENERIC, STEPS = MB.STEPS, clone = MB.clone
    return {
        // ── ④ 流程 ──
        addState() {
          var keys = this.def.workflow.states.map(function (s) { return s.key })
          var n = 1
          while (keys.indexOf('state_' + n) >= 0) n++
          this.def.workflow.states.push({ key: 'state_' + n, label: '' })
        },
        async removeState(si) {
          var s = this.def.workflow.states[si]
          var ok = window.MotrixUI ? await window.MotrixUI.confirm('刪除狀態「' + (s.label || s.key) + '」？用到它的轉換請一併調整。', { danger: true, okText: '刪除' }) : true
          if (ok) this.def.workflow.states.splice(si, 1)
        },
        renameState(si, k) {
          var wf = this.def.workflow
          var old = wf.states[si].key
          if (k === old || !k) return
          wf.states[si].key = k
          if (wf.initial === old) wf.initial = k
          wf.transitions.forEach(function (t) {
            if (Array.isArray(t.from)) t.from = t.from.map(function (x) { return x === old ? k : x })
            else if (t.from === old) t.from = k
            if (t.to === old) t.to = k
          })
          wf.states.forEach(function (s) {
            if (s.approval) {
              if (s.approval.on_approved === old) s.approval.on_approved = k
              if (s.approval.on_rejected === old) s.approval.on_rejected = k
            }
          })
        },
        setNotify(si, k, v) {
          var s = this.def.workflow.states[si]
          var n = Object.assign({}, s.notify || {})
          if (v) n[k] = v; else delete n[k]
          if (Object.keys(n).length) s.notify = n; else delete s.notify
          this.def.workflow.states.splice(si, 1, Object.assign({}, s))
        },
        addNotifyUser(si, u) {
          if (!u) return
          var s = this.def.workflow.states[si]
          var users = ((s.notify && s.notify.users) || []).slice()
          if (users.indexOf(u) < 0) users.push(u)
          this.setNotify(si, 'users', users)
        },
        removeNotifyUser(si, u) {
          var s = this.def.workflow.states[si]
          var users = ((s.notify && s.notify.users) || []).filter(function (x) { return x !== u })
          this.setNotify(si, 'users', users.length ? users : null)
        },
        userLabel(u) { var x = this.users.find(function (y) { return y.username === u }); return x ? x.displayName : u },
        toggleApproval(si, on) {
          var s = Object.assign({}, this.def.workflow.states[si])
          if (on) s.approval = s.approval || { tiers: [{ approvers: [this.newApprover('user')] }], on_approved: '', on_rejected: '' }
          else delete s.approval
          this.def.workflow.states.splice(si, 1, s)
        },
        // 簽核人來源一律取自目錄 approverSources（sourceType 空字串＝指定帳號）
        approverSources() {
          return (this.catalog.approverSources || []).map(function (x) { return { value: x.sourceType || 'user', label: x.label || x.sourceType, params: x.params || [] } })
        },
        approverKind(a) { return (a && a.sourceType) || 'user' },
        approverParams(a) {
          var k = this.approverKind(a)
          var src = this.approverSources().find(function (x) { return x.value === k })
          return src ? src.params : []
        },
        newApprover(kind) {
          var src = this.approverSources().find(function (x) { return x.value === kind })
          if (!src || src.value === 'user') return { username: '' }
          var o = { sourceType: src.value }
          src.params.forEach(function (p) { o[p] = null })
          return o
        },
        setApproverUser(tier, ai, username) {
          var u = this.users.find(function (x) { return x.username === username })
          tier.approvers.splice(ai, 1, u ? { username: u.username, displayName: u.displayName, userId: u.id } : { username: '' })
        },
        departments() {
          var out = []
          this.orgTree.forEach(function (dv) { (dv.departments || []).forEach(function (d) { out.push({ id: d.id, label: dv.name + '／' + d.name }) }) })
          return out
        },
        setWhen(tier, v) { if (v.trim()) tier.when = v; else delete tier.when },
        queueWhenCheck(si, ti) {
          var k = si + ':' + ti
          clearTimeout(this._whenTimers[k])
          this.whenState = Object.assign({}, this.whenState, { [k]: 'pending' })
          this._whenTimers[k] = setTimeout(() => this.checkWhen(si, ti), 300)
        },
        async checkWhen(si, ti) {
          var k = si + ':' + ti
          var tier = ((this.def.workflow.states[si] || {}).approval || { tiers: [] }).tiers[ti]
          if (!tier) return
          var expr = tier.when || ''
          if (!expr) { this.whenProblems = Object.assign({}, this.whenProblems, { [k]: [] }); this.whenState = Object.assign({}, this.whenState, { [k]: 'ok' }); return }
          var r = await this.api('POST', '/api/custom-modules/formula/check', { formula: expr, fields: this.def.fields.map(function (f) { return f.key }) })
          if ((tier.when || '') !== expr) return
          var probs = r.ok ? (r.data.problems || []) : [{ pos: 0, message: '檢查失敗（' + r.status + '）' }]
          this.whenProblems = Object.assign({}, this.whenProblems, { [k]: probs })
          this.whenState = Object.assign({}, this.whenState, { [k]: probs.length ? 'bad' : 'ok' })
        },
        addTransition() {
          var keys = this.def.workflow.transitions.map(function (t) { return t.key })
          var n = 1
          while (keys.indexOf('action_' + n) >= 0) n++
          this.def.workflow.transitions.push({ key: 'action_' + n, label: '', from: [], to: '' })
        },
        fromList(t) { return Array.isArray(t.from) ? t.from : (t.from ? [t.from] : []) },
        toggleFrom(t, k) {
          var l = this.fromList(t).slice()
          var i = l.indexOf(k)
          if (i >= 0) l.splice(i, 1); else l.push(k)
          t.from = l.length === 1 ? l[0] : l
        },

    }
  })
})()
