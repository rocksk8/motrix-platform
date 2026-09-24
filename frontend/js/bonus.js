// 獎金分潤（以案件為中心）——SPEC-BONUS §十一／§11.7（2026-09-24 重新設計）
//
// 使用者：「獎金分潤像是案件管理的頁面……幾個狀態，未精算、已精算、草稿、待審核、待撥放、已撥放」。
// 左側案件清單（搜尋／狀態篩選），右側該案的獎金明細。
// 後端：/api/bonus/cases（routers/bonus.py）。算式在後端（helpers/bonus_case.py），這裡只顯示
// 後端算好的結果，不自己重算金額——算兩份就會有兩個答案。
// BN22（2026-09-25）：改比例／人員時「即時」重算＝打 POST /preview（同一個 allocate()、不存檔），
// 不是在這裡複製算式。草稿與待審核（簽核中）可改；待審核已有人簽 ⇒ 存檔會作廢那些簽核、需重簽。
//
// ⚠️ 舊的「獎金項目＋分潤單」流程已停用（使用者：舊單「直接作廢」），本頁不顯示舊單。

var BN_STATUSES = ['未精算', '已精算', '草稿', '待審核', '待發放', '已發放']
var BN_CATS = ['sales', 'project', 'admin']

function bnPct(bp) {           // 基點 → 「50」「33.33」
  if (bp === null || bp === undefined) return ''
  var v = bp / 100
  return (Math.round(v * 100) / 100).toString()
}
function bnBp(pctText) {       // 「50」「33.33」→ 基點；不合法回 null
  var s = String(pctText == null ? '' : pctText).trim()
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null
  return Math.round(parseFloat(s) * 100)
}

function bonusPage() {
  return {
    moduleDisabled: false,
    loaded: false,
    loadError: '',
    isSuper: false,
    items: [],
    statusFilter: '',
    search: '',
    selectedNo: '',
    detail: null,
    detailError: '',
    busy: false,
    msg: '',
    // 草稿編輯（只有最高管理者）
    draft: null,          // { ratePct, split: {cat: pct}, members: {cat: [{username, pct, source}]}, custom: {cat: bool} }
    users: [],
    groups: [],
    addPick: { sales: '', project: '', admin: '' },
    addGroup: { sales: '', project: '', admin: '' },
    returnReason: '',
    rejectReason: '',
    // BN22 即時重算
    preview: null,        // POST /preview 的結果（與存檔同一個算式）
    previewError: '',
    previewPending: false,
    _previewSeq: 0,
    _previewTimer: null,
    replacePick: {},      // { 'cat:i': username } 換人下拉
    settings: null,       // { ratePct, split }
    settingsOpen: false,
    // `AC3`：傳票科目設定（最高管理者）、出納選的銀行科目、T100 設定頁維護的銀行帳戶清單
    voucherAccounts: null,  // { accounts: {expense, payable, withholding, bank}, problems, labels }
    voucherAcctEdit: {},
    bankAccounts: [],
    payBank: '',
    statuses: BN_STATUSES,
    cats: BN_CATS,
    catLabels: { sales: '業務', project: '專案', admin: '後勤' },

    _token() {
      try { return (JSON.parse(localStorage.getItem('motrix_session') || '{}') || {}).token || '' } catch (e) { return '' }
    },
    _auth() { return { Authorization: 'Bearer ' + this._token() } },
    _jsonAuth() { return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + this._token() } },

    // 🔴 Alpine 3 看到資料物件有 init() 就會自己叫一次，body 上的 x-init 會再叫一次 ⇒ 守衛。
    _initDone: false,

    async init() {
      if (this._initDone) return
      this._initDone = true
      try {
        const s = JSON.parse(localStorage.getItem('motrix_session') || '{}') || {}
        this.isSuper = s.role === 'superadmin'
      } catch (e) {}
      try {
        const r = await fetch('/api/system/bonus-module-status', { headers: this._auth() })
        const d = r.ok ? await r.json() : null
        if (d && !d.enabled) { this.moduleDisabled = true; this.loaded = true; return }
      } catch (e) { /* 查不到就照常載入——不要因為這支旗標打不到而把整個模組擋掉 */ }
      await this.loadList()
      if (this.isSuper) { this.loadUsers(); this.loadGroups(); this.loadSettings(); this.loadVoucherAccounts() }
      // 任何一個編輯欄位變動 ⇒ 重算預覽（Alpine $watch 對物件是深層比對）
      if (this.$watch) this.$watch('draft', () => this._schedulePreview())
      const q = new URLSearchParams(location.search).get('q')
      if (q) await this.select(q)
    },

    async loadList() {
      this.loadError = ''
      try {
        const p = new URLSearchParams()
        if (this.statusFilter) p.set('status', this.statusFilter)
        if (this.search.trim()) p.set('q', this.search.trim())
        const r = await fetch('/api/bonus/cases?' + p.toString(), { headers: this._auth() })
        if (!r.ok) throw new Error('HTTP ' + r.status)
        this.items = (await r.json()).items || []
      } catch (e) { this.loadError = '案件清單載入失敗（' + e.message + '）' }
      this.loaded = true
    },

    async loadUsers() {
      try {
        const r = await fetch('/api/users', { headers: this._auth() })
        if (r.ok) this.users = ((await r.json()) || []).filter(u => u.active)
      } catch (e) {}
    },
    async loadGroups() {
      try {
        const r = await fetch('/api/bonus/groups', { headers: this._auth() })
        if (r.ok) this.groups = ((await r.json()).groups || []).filter(g => g.is_active !== 0 && g.is_active !== false)
      } catch (e) {}
    },
    async loadSettings() {
      try {
        const r = await fetch('/api/bonus/cases/settings', { headers: this._auth() })
        if (r.ok) {
          const d = await r.json()
          this.settings = { ratePct: bnPct(d.rate_bp), split: {} }
          BN_CATS.forEach(c => { this.settings.split[c] = bnPct(d.split_bp[c]) })
        }
      } catch (e) {}
    },

    // `AC3`：獎金分潤產生傳票時用的科目（不寫死；設定值不存在／已停用 ⇒ 後端擋）
    async loadVoucherAccounts() {
      try {
        const r = await fetch('/api/bonus/cases/voucher-accounts', { headers: this._auth() })
        if (r.ok) {
          this.voucherAccounts = await r.json()
          this.voucherAcctEdit = Object.assign({}, this.voucherAccounts.accounts)
        }
      } catch (e) {}
    },
    async saveVoucherAccounts() {
      try {
        const r = await fetch('/api/bonus/cases/voucher-accounts', { method: 'PUT', headers: this._jsonAuth(),
          body: JSON.stringify(this.voucherAcctEdit) })
        const d = await r.json().catch(() => ({}))
        this.msg = r.ok ? '已儲存傳票科目' : ('傳票科目儲存失敗：' + (d.detail || r.status))
        if (r.ok) await this.loadVoucherAccounts()
      } catch (e) { this.msg = '網路錯誤：' + e.message }
    },
    // 出納標記已發放時選銀行：清單由獎金明細 API 在待發放時帶出（T100 設定頁那一份；
    // 不直接打 t100-export-config——那支只給 admin+，非 admin 的出納會 403）
    loadBankAccounts() {
      this.bankAccounts = (this.detail && this.detail.bankAccounts) || []
      this.payBank = (this.detail && this.detail.defaultBankAccountCode) || ''
    },
    voucherKindLabel(k) { return { accrual: '應付（轉帳）', payment: '發放（支出）' }[k] || k },
    // 後端回的 notice（科目有問題沒產生、已送審不動…）一定要讓人看到
    _withNotice(okMsg, d) {
      const parts = [okMsg]
      if (d && d.voucher && d.voucher.voucher_no) parts.push('已產生傳票草稿 ' + d.voucher.voucher_no)
      if (d && d.notice) parts.push(d.notice)
      return parts.join('。')
    },

    userLabel(u) {
      const hit = this.users.find(x => x.username === u)
      return hit ? (hit.displayName || u) + '（' + u + '）' : u
    },
    money(n) { return 'NT$ ' + Number(n || 0).toLocaleString() },
    pct(bp) { return bnPct(bp) },
    badgeClass(st) {
      return { '未精算': 'st-gray', '已精算': 'st-blue', '草稿': 'st-amber', '待審核': 'st-orange',
               '待發放': 'st-green', '已發放': 'st-purple' }[st] || 'st-gray'
    },

    async select(no) {
      this.selectedNo = no
      this.detail = null
      this.detailError = ''
      this.msg = ''
      this.draft = null
      this.preview = null
      this.previewError = ''
      this._previewSeq++          // 還在路上的舊預覽一律作廢
      this.returnReason = ''
      this.rejectReason = ''
      try {
        const r = await fetch('/api/bonus/cases/' + encodeURIComponent(no), { headers: this._auth() })
        if (!r.ok) {
          const e = await r.json().catch(() => ({}))
          throw new Error(e.detail || ('HTTP ' + r.status))
        }
        this.detail = await r.json()
        if (this.detail.status === '草稿' && this.isSuper) this._startDraft()
      } catch (e) { this.detailError = e.message }
    },

    // ── 草稿 ──────────────────────────────────────────────────────────────
    _startDraft() {
      const a = this.detail.award
      const d = { ratePct: bnPct(a.rate_bp), split: {}, members: {}, custom: {} }
      BN_CATS.forEach(c => {
        d.split[c] = bnPct((a.split_bp || {})[c] || 0)
        const ls = (this.detail.lines || []).filter(l => l.category === c)
        d.custom[c] = ls.some(l => l.person_bp !== null && l.person_bp !== undefined)
        d.members[c] = ls.map(l => ({ username: l.username, pct: bnPct(l.person_bp), source: l.source }))
      })
      this.draft = d
    },
    // 待審核（簽核中）也可改：按「修改」才進入編輯，簽核鈕照常在
    canEdit() { return this.isSuper && this.detail && this.detail.award && this.detail.scope === 'all' &&
                       (this.detail.status === '草稿' || this.detail.status === '待審核') },
    startEdit() { if (this.canEdit()) this._startDraft() },
    cancelEdit() { this.draft = null; this.preview = null; this.previewError = ''; this._previewSeq++ },
    // 已完成的簽核（顯示名稱）：存檔會作廢它們
    signedApprovers() {
      const appr = (this.detail && this.detail.award && this.detail.award.approval) || {}
      const out = []
      ;(appr.tiers || []).forEach(t => (t.approvers || []).forEach(a => {
        if (a.status === 'approved' || a.approvedAt) out.push(a.approvedBy || a.displayName || a.display_name || a.username)
      }))
      return out
    },

    // ── BN22 即時重算：debounce → POST /preview；晚到的舊回應丟掉 ─────────────
    _schedulePreview() {
      if (!this.draft) return
      clearTimeout(this._previewTimer)
      this._previewTimer = setTimeout(() => this._runPreview(), 300)
    },
    async _runPreview() {
      if (!this.draft) return
      const seq = ++this._previewSeq
      const p = this._draftPayload()
      if (p.err) { this.preview = null; this.previewError = p.err; return }
      this.previewPending = true
      try {
        const r = await fetch('/api/bonus/cases/' + encodeURIComponent(this.selectedNo) + '/preview', {
          method: 'POST', headers: this._jsonAuth(), body: JSON.stringify(p.body) })
        const d = await r.json().catch(() => ({}))
        if (seq !== this._previewSeq) return
        if (!r.ok) { this.preview = null; this.previewError = d.detail || ('試算失敗（HTTP ' + r.status + '）'); return }
        this.preview = d
        this.previewError = ''
      } catch (e) {
        if (seq === this._previewSeq) { this.preview = null; this.previewError = '網路錯誤：' + e.message }
      } finally {
        if (seq === this._previewSeq) this.previewPending = false
      }
    },
    // 編輯中顯示預覽的金額；不在編輯中顯示存下去的
    previewAmount(cat, username) {
      if (!this.preview) return null
      const l = ((this.preview.categories || {})[cat] || { lines: [] }).lines.find(x => x.username === username)
      return l ? l.amount : null
    },
    previewCatAmount(cat) {
      if (!this.preview) return null
      return ((this.preview.categories || {})[cat] || {}).amount
    },
    replacePerson(cat, i) {
      const key = cat + ':' + i
      const u = this.replacePick[key]
      this.replacePick[key] = ''
      if (!u || this.draft.members[cat].some(m => m.username === u)) return
      const m = this.draft.members[cat][i]
      this.draft.members[cat].splice(i, 1, { username: u, pct: m.pct, source: 'manual' })
    },
    logLabel(a) {
      return { create: '建立', edit: '修改', submit: '送審', approve: '簽核', reject: '駁回', 'return': '退回',
               reset_approvals: '簽核作廢（修改後需重簽）', mark_paid: '標記已發放' }[a] || a
    },
    // 變更紀錄的內容摘要：前後名單／比率／比例
    logDetail(g) {
      let c
      try { c = JSON.parse(g.changes_json || 'null') } catch (e) { return '' }
      if (!c) return ''
      if (g.action === 'reset_approvals') return '作廢：' + (c.voided || []).join('、')
      if (!Array.isArray(c)) return ''
      const who = list => (list || []).map(x => this.userLabel(Array.isArray(x) ? x[0] : x)).join('、') || '（無）'
      return c.map(ch => {
        if (ch.field === 'members') return BN_CATS.filter(k => JSON.stringify((ch.old || {})[k]) !== JSON.stringify((ch.new || {})[k]))
          .map(k => this.catLabels[k] + '：' + who((ch.old || {})[k]) + ' → ' + who((ch.new || {})[k])).join('；')
        if (ch.field === 'rate_bp') return '獎金比率 ' + bnPct(ch.old) + '% → ' + bnPct(ch.new) + '%'
        if (ch.field === 'split_bp') return '分配 ' + BN_CATS.map(k => bnPct((ch.old || {})[k])).join('/') + ' → ' +
          BN_CATS.map(k => bnPct((ch.new || {})[k])).join('/')
        if (ch.field === 'net_profit') return '淨利 ' + ch.old + ' → ' + ch.new
        return ch.field
      }).filter(Boolean).join('；')
    },
    linesOf(cat) { return ((this.detail && this.detail.lines) || []).filter(l => l.category === cat) },
    catAmount(cat) { return this.linesOf(cat).reduce((s, l) => s + (l.amount || 0), 0) },
    addPerson(cat) {
      const u = this.addPick[cat]
      if (!u || this.draft.members[cat].some(m => m.username === u)) { this.addPick[cat] = ''; return }
      this.draft.members[cat].push({ username: u, pct: '', source: 'manual' })
      this.addPick[cat] = ''
    },
    addGroupMembers(cat) {
      const g = this.groups.find(x => String(x.id) === String(this.addGroup[cat]))
      this.addGroup[cat] = ''
      if (!g) return
      ;(g.members || []).forEach(u => {
        if (!this.draft.members[cat].some(m => m.username === u))
          this.draft.members[cat].push({ username: u, pct: '', source: 'group:' + g.id })
      })
    },
    removePerson(cat, i) { this.draft.members[cat].splice(i, 1) },

    _draftPayload() {
      const rate = bnBp(this.draft.ratePct)
      if (rate === null) return { err: '獎金比率請填 0～100 的數字（最多兩位小數）' }
      const split = {}
      for (const c of BN_CATS) {
        const v = bnBp(this.draft.split[c])
        if (v === null) return { err: this.catLabels[c] + '比例請填數字（最多兩位小數）' }
        split[c] = v
      }
      const members = {}
      for (const c of BN_CATS) {
        members[c] = []
        for (const m of this.draft.members[c]) {
          let bp = null
          if (this.draft.custom[c]) {
            bp = bnBp(m.pct)
            if (bp === null) return { err: this.catLabels[c] + '「' + m.username + '」的個人比例請填數字' }
          }
          members[c].push({ username: m.username, person_bp: bp, source: m.source })
        }
      }
      return { body: { rate_bp: rate, split_bp: split, members } }
    },

    async _post(path, body, method) {
      this.busy = true
      this.msg = ''
      try {
        const r = await fetch('/api/bonus/cases/' + encodeURIComponent(this.selectedNo) + path, {
          method: method || 'POST', headers: this._jsonAuth(), body: JSON.stringify(body || {}) })
        const d = await r.json().catch(() => ({}))
        if (!r.ok) { this.msg = d.detail || ('操作失敗（HTTP ' + r.status + '）'); return false }
        return d   // `AC3`：回傳內容（notice／voucher）給呼叫端；物件仍是 truthy，既有判斷不變
      } catch (e) { this.msg = '網路錯誤：' + e.message; return false }
      finally { this.busy = false }
    },
    async _refresh(okMsg) {
      const no = this.selectedNo
      await this.loadList()
      await this.select(no)
      if (okMsg) this.msg = okMsg
    },

    async createDraft() { if (await this._post('', {})) await this._refresh('已建立草稿') },
    async saveDraft() {
      const p = this._draftPayload()
      if (p.err) { this.msg = p.err; return }
      const body = p.body
      if (this.detail.status === '待審核') {
        const signed = this.signedApprovers()
        if (signed.length) {
          const ok = await MotrixUI.confirm(
            '已有 ' + signed.length + ' 位完成簽核（' + signed.join('、') + '）。\n儲存這次修改會作廢這些簽核，需要重新簽核。',
            { title: '修改會作廢已完成的簽核', okText: '儲存並作廢簽核', danger: true })
          if (!ok) return
          body.confirmResetApprovals = true
        }
      }
      const d = await this._post('', body, 'PUT')
      if (d) await this._refresh(d.voidedCount ? '已儲存；已作廢 ' + d.voidedCount + ' 位簽核，需重新簽核' : '已儲存')
    },
    async submitDraft() {
      const p = this._draftPayload()
      if (p.err) { this.msg = p.err; return }
      if (!(await this._post('', p.body, 'PUT'))) return
      if (await this._post('/submit', {})) await this._refresh('已送審')
    },
    async approve() {
      const d = await this._post('/approve', {})
      if (d) await this._refresh(this._withNotice('已核准', d))
    },
    async reject() {
      if (!this.rejectReason.trim()) { this.msg = '請填寫駁回原因'; return }
      if (await this._post('/reject', { reason: this.rejectReason })) await this._refresh('已駁回，回到草稿')
    },
    async returnToDraft() {
      if (!this.returnReason.trim()) { this.msg = '請填寫退回原因'; return }
      const d = await this._post('/return', { reason: this.returnReason })
      if (d) await this._refresh(this._withNotice('已退回草稿', d))
    },
    async markPaid() {
      const d = await this._post('/mark-paid', this.payBank ? { bank_account_code: this.payBank } : {})
      if (d) await this._refresh(this._withNotice('已標記發放', d))
    },

    async saveSettings() {
      const rate = bnBp(this.settings.ratePct)
      const split = {}
      for (const c of BN_CATS) split[c] = bnBp(this.settings.split[c])
      if (rate === null || BN_CATS.some(c => split[c] === null)) { this.msg = '預設比例請填數字'; return }
      try {
        const r = await fetch('/api/bonus/cases/settings', { method: 'PUT', headers: this._jsonAuth(),
          body: JSON.stringify({ rate_bp: rate, split_bp: split }) })
        const d = await r.json().catch(() => ({}))
        this.msg = r.ok ? '已儲存預設' : (d.detail || '儲存失敗')
        if (r.ok) this.settingsOpen = false
      } catch (e) { this.msg = '網路錯誤：' + e.message }
    },
  }
}

if (typeof module !== 'undefined' && module.exports) module.exports = { bnPct, bnBp }
