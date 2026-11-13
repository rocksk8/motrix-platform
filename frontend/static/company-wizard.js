/* 公司設定精靈（T84，2026-11-13）：把「本公司資料」拆成 5 個短步驟，每步各自儲存、可中途離開、回來接著做。
 *
 * 不新增資料、不新增端點：只用 GET／PUT /api/settings/company-profile、GET／PUT／DELETE /api/settings/branding/{kind}、
 * GET /api/settings/company-setup/status（本公司資料未確認時的 428 閘門只放行這幾支，見 main.py::_COMPANY_SETUP_ALLOWED）。
 * 進度不另存：每一步「做完沒有」由已儲存的欄位算出來（名稱＋統編、電話或 Email、收款帳戶、Logo），回來時從第一個沒做完的步驟接著做。
 * 所有文字都用 textContent 輸出（不拼 HTML 字串）。
 *
 * 已知限制（h11 N2）：舊的「公司資料設定」頁存檔時整包 PUT，開著過期分頁再存一次，可能蓋掉精靈剛存的欄位；精靈自己只送這一步改到的欄位（並先重讀據點），不會蓋別人的。
 * 請求都帶 X-Motrix-Ui: wizard，稽核 detail 才分得出「精靈存的」與「設定頁存的」。
 *
 * 「？」說明：欄位旁放空的 <span class="hint" data-hint='{…}' data-hint-label="…">，等 hint-popover.js／css 合併後（批次 9）自動長出「？」；
 * 沒載入時是看不見的空殼，欄位下方另有一行白話說明，所以不依賴它。
 */
(function () {
  'use strict'

  var STEP_TITLES = ['基本資料', '聯絡方式', '收款帳戶', 'Logo', '確認']
  var SEEN_KEY = 'motrix_cw_seen'
  // 欄位在「主要據點」（locations[0]）裡的同名欄：後端的身分是「主要據點有填就優先、頂層只是後備」，
  // 所以讀要讀生效的那一份、寫要頂層一定寫、據點[0] 已經有填同一欄時一併改（沒填的不去動它）。
  var LOC_KEY = { name: 'company_name', company_name_en: 'company_name_en', tax_id: 'tax_id', phone: 'phone', email: 'email',
                  bank_name: 'bank_name', bank_branch: 'bank_branch', bank_account_name: 'bank_account_name', bank_account_number: 'bank_account_number' }

  var FIELDS = {
    name: { step: 1, label: '公司名稱（中文）', req: true, ph: '例：範例科技股份有限公司', auto: 'organization',
            note: '照公司登記的全名填寫。',
            hint: { what: '公司登記的中文全名。', when: '第一次設定時填；公司改名時回來修改。', impact: '會印在報價單、請款單與寄給客戶的信件抬頭。', suggest: '照經濟部登記資料填寫，不要簡稱。' } },
    company_name_en: { step: 1, label: '公司英文名稱（選填）', ph: '例：Example Technology Co., Ltd.', auto: 'off',
               note: '有英文文件才需要，沒有可以留空。',
               hint: { what: '公司的英文名稱。', when: '要開英文報價單或對外英文文件時。', impact: '只會出現在有用到英文抬頭的文件上。', suggest: '沒有英文名稱就留空。' } },
    tax_id: { step: 1, label: '統一編號', req: true, ph: '8 碼數字，例：12345678', inputmode: 'numeric', max: 12, auto: 'off',
              note: '8 碼數字；系統會即時檢查檢查碼。',
              hint: { what: '公司的統一編號（8 碼）。', when: '第一次設定時填。', impact: '印在報價單與請款單上；改了需要重新確認本公司資料。', suggest: '請填貴公司自己的統編；00000000 是示範用，不能使用。' } },
    phone: { step: 2, label: '電話', ph: '例：02-1234-5678', auto: 'tel',
             note: '電話與 Email 至少填一項。',
             hint: { what: '公司對外的聯絡電話。', when: '第一次設定時填。', impact: '印在報價單與請款單的抬頭。', suggest: '填客戶打得通的總機或業務專線。' } },
    email: { step: 2, label: 'Email', ph: '例：service@example.com', auto: 'email',
             note: '這是印在文件上的聯絡信箱，不是系統寄信用的信箱。',
             hint: { what: '公司對外的聯絡信箱。', when: '第一次設定時填。', impact: '印在報價單與請款單的抬頭。', suggest: '填客戶回信會有人看的信箱。' } },
    contact_info: { step: 2, label: '其他聯絡資訊（選填）', ph: '例：傳真 02-1234-5679、營業時間週一至週五 9:00–18:00', auto: 'off', area: true,
                    note: '想一起印在文件上的其他資訊，沒有可以留空。',
                    hint: { what: '想一起印在文件抬頭的其他聯絡資訊。', when: '有傳真、營業時間等要補充時。', impact: '會原文印在報價單與請款單上。', suggest: '一兩行就好。' } },
    bank_name: { step: 3, label: '收款銀行', ph: '例：第一銀行', auto: 'off',
                 note: '客戶匯款用的銀行；報價單與請款單會印出來。',
                 hint: { what: '客戶匯款的銀行名稱。', when: '要開請款單前。', impact: '印在請款單的收款資訊上。', suggest: '填公司的主要收款帳戶。' } },
    bank_branch: { step: 3, label: '分行', ph: '例：台中分行', auto: 'off', note: '選填。',
                   hint: { what: '收款銀行的分行名稱。', when: '銀行要求註明分行時。', impact: '印在請款單的收款資訊上。', suggest: '沒有特別要求可以留空。' } },
    bank_account_name: { step: 3, label: '戶名', ph: '例：範例科技股份有限公司', auto: 'off',
                         note: '通常與公司名稱相同。',
                         hint: { what: '銀行帳戶的戶名。', when: '要開請款單前。', impact: '客戶匯款時會核對戶名。', suggest: '照存摺上的戶名填寫。' } },
    bank_account_number: { step: 3, label: '帳號', ph: '例：123-456-789012', inputmode: 'numeric', auto: 'off',
                           note: '填錯會讓客戶匯錯地方，請再核對一次。',
                           hint: { what: '收款的銀行帳號。', when: '要開請款單前。', impact: '印在請款單上，客戶會照這個帳號匯款。', suggest: '填完請對照存摺再核對一次。' } },
  }
  var STEP_FIELDS = { 1: ['name', 'company_name_en', 'tax_id'], 2: ['phone', 'email', 'contact_info'], 3: ['bank_name', 'bank_branch', 'bank_account_name', 'bank_account_number'] }

  var session = {}
  try { session = JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) { session = {} }
  var AUTH = { Authorization: 'Bearer ' + (session.token || ''), 'X-Motrix-Ui': 'wizard' }   // X-Motrix-Ui：只讓稽核分得出「精靈存的」與「設定頁存的」

  var st = {
    profile: null,      // GET company-profile 的回應（遮蔽字原樣，不回寫）
    setup: null,        // GET company-setup/status
    brand: {},          // GET branding 的 assets
    draft: {},          // 這個步驟還沒儲存的修改（欄位 key ⇒ 值）
    step: 1,
    busy: false,
    msg: '',
    msgBad: false,
    confirmed: false,   // 這一次載入內剛按過「確認」
    needReconfirm: false,
    ack: false,
  }
  var root, seq = 0

  // ── 小工具 ─────────────────────────────────────────────────────────────
  function el(tag, cls, text) {
    var n = document.createElement(tag)
    if (cls) n.className = cls
    if (text != null) n.textContent = text
    return n
  }
  function ubnValid(s) {                       // 與 helpers/company_setup.py::ubn_valid 同一條規則；後端仍是最終判定
    if (!/^\d{8}$/.test(s)) return false
    var w = [1, 2, 1, 2, 1, 2, 4, 1], total = 0
    for (var i = 0; i < 8; i++) { var p = Number(s[i]) * w[i]; total += Math.floor(p / 10) + (p % 10) }
    return total % 5 === 0 || (s[6] === '7' && (total + 1) % 5 === 0)
  }
  function primaryLoc() { var l = st.profile && st.profile.locations; return l && l.length ? l[0] : null }
  function saved(k) {                           // 已儲存、生效的值
    if (!st.profile) return ''
    var loc = primaryLoc(), lk = LOC_KEY[k]
    var v = loc && lk ? String(loc[lk] == null ? '' : loc[lk]).trim() : ''
    return v ? String(loc[lk]) : String(st.profile[k] == null ? '' : st.profile[k])
  }
  function val(k) { return Object.prototype.hasOwnProperty.call(st.draft, k) ? st.draft[k] : saved(k) }
  function taxDigits() { return String(val('tax_id') || '').replace(/\D/g, '') }
  function taxState() {
    var s = taxDigits()
    if (!s) return { cls: '', text: '' }
    if (s.length < 8) return { cls: '', text: '統一編號為 8 碼數字（目前 ' + s.length + ' 碼）' }
    if (s.length > 8) return { cls: 'bad', text: '統一編號只有 8 碼，請再核對' }
    if (s === '00000000') return { cls: 'bad', text: '00000000 是系統保留的示範統編，請填貴公司的統一編號' }
    return ubnValid(s) ? { cls: 'ok', text: '✓ 統編格式正確' } : { cls: 'bad', text: '統編檢查碼不符，請再核對' }
  }
  // 已儲存的必要欄位齊不齊：以伺服器的判定為準（status 的 missing＝後端 required_problems；舊資料靠別名／聯絡方式後備算出的身分，畫面上的欄位看不到）
  function serverMissing() { return (st.setup && Array.isArray(st.setup.missing)) ? st.setup.missing : [] }
  function missingHas(word) { return serverMissing().some(function (m) { return String(m).indexOf(word) >= 0 }) }
  function touched(keys) { return keys.some(function (k) { return Object.prototype.hasOwnProperty.call(st.draft, k) }) }
  function stepOk(n) {                           // 這一步的必要條件齊了嗎（步驟 3、4 沒有必要條件）；改過欄位看畫面上的值，沒改就看伺服器的判定
    if (n === 1) {
      if (touched(['name', 'tax_id'])) return !!String(val('name') || '').trim() && taxState().cls === 'ok'
      return stepDone(1)
    }
    if (n === 2) {
      if (touched(['phone', 'email'])) return !!(String(val('phone') || '').trim() || String(val('email') || '').trim())
      return stepDone(2)
    }
    return true
  }
  function stepDone(n) {                         // 已儲存的資料看起來做完了嗎（決定步驟條上的 ✓ 與回來時從哪一步接著做）
    if (!st.profile) return false
    if (n === 1) return !missingHas('公司名稱') && !missingHas('統一編號')
    if (n === 2) return !missingHas('電話')
    if (n === 3) return !!(saved('bank_account_number').trim() && saved('bank_name').trim())
    if (n === 4) return !!(st.brand.logo && st.brand.logo.custom)
    return st.confirmed || !!(st.setup && st.setup.configured === true)
  }
  function seen() { try { return JSON.parse(sessionStorage.getItem(SEEN_KEY) || '[]') || [] } catch (e) { return [] } }
  function markSeen(n) { var s = seen(); if (s.indexOf(n) < 0) { s.push(n); try { sessionStorage.setItem(SEEN_KEY, JSON.stringify(s)) } catch (e) { /* 忽略 */ } } }
  function firstStep() {                         // 回來時：第一個必要的沒做完 ⇒ 停在那；否則第一個沒做完又沒看過的選填步驟；都沒有 ⇒ 確認
    for (var n = 1; n <= 2; n++) if (!stepDone(n)) return n
    var sn = seen()
    for (var m = 3; m <= 4; m++) if (!stepDone(m) && sn.indexOf(m) < 0) return m
    return 5
  }
  function hash() { var m = /^#s([1-5])$/.exec(location.hash || ''); return m ? Number(m[1]) : 0 }

  function say(text, bad) { st.msg = text || ''; st.msgBad = !!bad; render() }

  // ── 對伺服器 ───────────────────────────────────────────────────────────
  function toLogin() { try { location.replace('login.html') } catch (e) { /* 忽略 */ } }
  function api(method, url, body) {
    var opt = { method: method, headers: Object.assign({}, AUTH) }
    if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = JSON.stringify(body) }
    return fetch(url, opt).then(function (r) {
      if (r.status === 401) { toLogin(); return { ok: false, status: 401, data: {} } }
      return r.json().catch(function () { return {} }).then(function (d) { return { ok: r.ok, status: r.status, data: d } })
    })
  }
  function loadAll() {
    var mine = ++seq
    // 先只讀 status：非最高管理者（canFix 不是 true／被擋）⇒ 不顯示表單，也**不去讀公司資料**；確定可以改才讀公司資料與 Logo
    return api('GET', '/api/settings/company-setup/status').then(function (rs) {
      if (mine !== seq) return
      if (rs.status === 401) return
      if (rs.status === 403 || (rs.ok && rs.data && rs.data.canFix === false)) { st.denied = true; render(); return }
      if (!rs.ok) { st.failed = true; render(); return }
      return Promise.all([api('GET', '/api/settings/company-profile'), api('GET', '/api/settings/branding')]).then(function (rr) {
        if (mine !== seq) return
        if (rr[0].status === 401 || rr[1].status === 401) return
        if (rr[0].status === 403 || rr[1].status === 403) { st.denied = true; render(); return }
        if (!rr[0].ok) { st.failed = true; render(); return }
        st.profile = rr[0].data
        st.setup = rs.data
        st.brand = (rr[1].ok && rr[1].data && rr[1].data.assets) || {}
        st.loaded = true
        var h = hash()
        st.step = h || firstStep()
        render()
      })
    }).catch(function () { st.failed = true; render() })
  }

  // 這一步要送出的內容：頂層欄位；據點[0] 已經有填同一欄的一併改（只在有需要時才送 locations）
  function buildPayload(fields) {
    var payload = {}, loc = primaryLoc(), touchLoc = false
    var locs = loc ? JSON.parse(JSON.stringify(st.profile.locations)) : null
    fields.forEach(function (k) {
      if (!Object.prototype.hasOwnProperty.call(st.draft, k)) return
      var v = st.draft[k]
      payload[k] = v
      var lk = LOC_KEY[k]
      if (locs && lk && String(locs[0][lk] == null ? '' : locs[0][lk]).trim()) { locs[0][lk] = v; touchLoc = true }
    })
    if (touchLoc) payload.locations = locs
    return payload
  }
  function mergeSaved(payload) {
    Object.keys(payload).forEach(function (k) { st.profile[k] = payload[k] })
    Object.keys(payload).forEach(function (k) { if (k !== 'locations') delete st.draft[k] })
  }

  // 送 locations 之前先重讀一次最新的（避免兩位最高管理者同時改時蓋掉對方的據點修改）；讀失敗就用手上的
  function freshLocations() {
    if (!primaryLoc()) return Promise.resolve()
    return api('GET', '/api/settings/company-profile').then(function (r) {
      if (r.ok && r.data && Array.isArray(r.data.locations)) st.profile.locations = r.data.locations
    }).catch(function () {})
  }

  // 儲存這一步（不帶確認旗標：只存欄位，不寫確認紀錄）。ok ⇒ true
  function saveStep(n) {
    var fields = STEP_FIELDS[n] || []
    if (!fields.some(function (k) { return Object.prototype.hasOwnProperty.call(st.draft, k) })) return Promise.resolve(true)
    st.busy = true; render()
    return freshLocations().then(function () {
      var payload = buildPayload(fields)
      return sendStep(n, payload)
    })
  }
  function sendStep(n, payload) {
    if (!Object.keys(payload).length) { st.busy = false; return Promise.resolve(true) }
    return api('PUT', '/api/settings/company-profile', payload).then(function (r) {
      st.busy = false
      if (r.ok) { mergeSaved(payload); if (payload.locations) st.profile.locations = payload.locations; return loadSetupOnly().then(function () { return true }) }
      var d = r.data || {}
      if (r.status === 409 && d.detail && d.detail.code === 'company_setup_reconfirm') {
        // 公司資料已經確認過，這次改到必要欄位 ⇒ 要在最後一步「儲存並確認」一起送出（修改先留在畫面上，不丟）
        st.needReconfirm = true
        markSeen(n)
        st.step = 5
        say('這次修改了本公司的必要欄位，需要重新確認：請在這一步核對後按「儲存並確認本公司資料」，修改才會生效。', false)
        return false
      }
      say((d.detail && d.detail.message) || (typeof d.detail === 'string' ? d.detail : '') || '儲存失敗，請稍後再試。', true)
      return false
    }).catch(function () { st.busy = false; say('連線異常，這一步沒有儲存。', true); return false })
  }

  function confirmAll() {
    var fields = [].concat(STEP_FIELDS[1], STEP_FIELDS[2], STEP_FIELDS[3])
    var payload
    st.busy = true; render()
    return freshLocations().then(function () {
      payload = buildPayload(fields)
      payload.confirmIdentity = true
      return api('PUT', '/api/settings/company-profile', payload)
    }).then(function (r) {
      st.busy = false
      if (r.ok) {
        delete payload.confirmIdentity
        mergeSaved(payload); if (payload.locations) st.profile.locations = payload.locations
        st.confirmed = true; st.needReconfirm = false; st.ack = false
        try { if (window.MotrixWizard && window.MotrixWizard.finish && !window.MotrixWizard.isSuper) window.MotrixWizard.finish() } catch (e) { /* 確認已經成功；外殼的收尾出錯不要當成連線異常 */ }
        render()
        return loadSetupOnly()
      }
      var d = r.data || {}
      say((d.detail && d.detail.message) || (typeof d.detail === 'string' ? d.detail : '') || '確認失敗，請稍後再試。', true)
    }).catch(function () { st.busy = false; say('連線異常，沒有完成確認。', true) })
  }
  function loadSetupOnly() {
    return api('GET', '/api/settings/company-setup/status').then(function (r) { if (r.ok) { st.setup = r.data; render() } })
  }

  function uploadLogo(kind, input) {
    var file = input.files && input.files[0]
    if (!file) return
    st.busy = true; render()
    var fd = new FormData()
    fd.append('file', file)
    fetch('/api/settings/branding/' + encodeURIComponent(kind), { method: 'PUT', headers: Object.assign({}, AUTH), body: fd })
      .then(function (r) { if (r.status === 401) { toLogin(); return { ok: false, unauth: true, data: {} } } return r.json().catch(function () { return {} }).then(function (d) { return { ok: r.ok, data: d } }) })
      .then(function (r) {
        st.busy = false
        if (r.unauth) return
        if (r.ok) { st.brand = r.data.assets || st.brand; say('已更換：' + ((st.brand[kind] && st.brand[kind].label) || '圖檔'), false) }
        else say(typeof r.data.detail === 'string' ? r.data.detail : '上傳失敗，請換一張圖再試。', true)
      })
      .catch(function () { st.busy = false; say('連線異常，沒有上傳成功。', true) })
  }

  // ── 畫面 ───────────────────────────────────────────────────────────────
  function go(n) {
    if (st.busy) return
    st.step = n; st.msg = ''; st.skipAsk = 0
    try { history.replaceState(null, '', '#s' + n) } catch (e) { /* 忽略 */ }
    render()
    var h = root.querySelector('[data-testid="cw-title"]')
    if (h) { h.setAttribute('tabindex', '-1'); h.focus() }
  }

  function fieldRow(k) {
    var f = FIELDS[k]
    var wrap = el('div', 'cw-field')
    var lab = el('label', 'cw-label', f.label)
    lab.setAttribute('for', 'cw-' + k)
    if (f.req) { var star = el('span', 'cw-req', '＊'); star.setAttribute('aria-hidden', 'true'); lab.appendChild(star) }
    var tip = el('span', 'hint')                                  // 空殼：hint-popover.js 載入後長出「？」
    tip.setAttribute('data-hint', JSON.stringify(f.hint))
    tip.setAttribute('data-hint-label', f.label.replace(/（.*?）/g, ''))
    lab.appendChild(tip)
    wrap.appendChild(lab)
    var inp = el(f.area ? 'textarea' : 'input', 'cw-input')
    if (!f.area) inp.type = 'text'; else inp.rows = 2
    inp.id = 'cw-' + k
    inp.setAttribute('data-testid', 'cw-field-' + k)
    inp.value = val(k)
    inp.placeholder = f.ph || ''
    if (f.inputmode) inp.setAttribute('inputmode', f.inputmode)
    if (f.max) inp.maxLength = f.max
    inp.setAttribute('autocomplete', f.auto || 'off')
    var noteId = 'cw-note-' + k
    inp.setAttribute('aria-describedby', noteId)
    inp.addEventListener('input', function () {
      st.draft[k] = inp.value
      refreshNav()
      if (k === 'tax_id') refreshTax()
      refreshPreview()
    })
    wrap.appendChild(inp)
    var note = el('div', 'cw-note', f.note)
    note.id = noteId
    wrap.appendChild(note)
    if (k === 'tax_id') {
      var m = el('div', 'cw-note cw-tax')
      m.setAttribute('data-testid', 'cw-tax-msg'); m.setAttribute('role', 'status')
      wrap.appendChild(m)
    }
    return wrap
  }
  function refreshTax() {
    var m = root.querySelector('[data-testid="cw-tax-msg"]')
    if (!m) return
    var t = taxState()
    m.textContent = t.text
    m.className = 'cw-note cw-tax' + (t.cls ? ' ' + t.cls : '')
  }
  function refreshNav() {
    var nx = root.querySelector('[data-testid="cw-next"]')
    if (nx) nx.disabled = st.busy || !stepOk(st.step)
  }

  function previewBox() {
    var box = el('div', 'cw-preview')
    box.setAttribute('data-testid', 'cw-preview')
    box.appendChild(el('div', 'cw-preview-cap', '報價單、請款單的抬頭會長這樣'))
    var head = el('div', 'cw-pv-head')
    var line1 = el('div', 'cw-pv-name'); line1.setAttribute('data-pv', 'name')
    var line2 = el('div', 'cw-pv-en'); line2.setAttribute('data-pv', 'name_en')
    var line3 = el('div', 'cw-pv-line'); line3.setAttribute('data-pv', 'ids')
    var line4 = el('div', 'cw-pv-line'); line4.setAttribute('data-pv', 'contact')
    var line5 = el('div', 'cw-pv-line'); line5.setAttribute('data-pv', 'other')
    ;[line1, line2, line3, line4, line5].forEach(function (n) { head.appendChild(n) })
    box.appendChild(head)
    return box
  }
  function refreshPreview() {
    var box = root.querySelector('[data-testid="cw-preview"]')
    if (!box) return
    function set(key, text, fallback) {
      var n = box.querySelector('[data-pv="' + key + '"]')
      if (!n) return
      n.textContent = text || fallback || ''
      n.style.display = (text || fallback) ? '' : 'none'
    }
    set('name', String(val('name') || '').trim(), '（公司名稱）')
    set('name_en', String(val('company_name_en') || '').trim(), '')
    var tax = taxDigits()
    set('ids', tax ? '統一編號 ' + tax : '', '（統一編號）')
    var c = []
    if (String(val('phone') || '').trim()) c.push('電話 ' + String(val('phone')).trim())
    if (String(val('email') || '').trim()) c.push(String(val('email')).trim())
    set('contact', c.join('　'), '（電話、Email）')
    set('other', String(val('contact_info') || '').trim(), '')
  }

  function stepBar() {
    var ol = el('ol', 'cw-steps')
    ol.setAttribute('aria-label', '設定步驟'); ol.setAttribute('data-testid', 'cw-steps')
    STEP_TITLES.forEach(function (t, i) {
      var n = i + 1
      var li = el('li', 'cw-step' + (n === st.step ? ' is-cur' : '') + (stepDone(n) ? ' is-done' : ''))
      if (n === st.step) li.setAttribute('aria-current', 'step')
      var b = el('button', 'cw-stepbtn')
      b.type = 'button'
      b.setAttribute('data-testid', 'cw-step-' + n)
      var no = el('span', 'cw-no', stepDone(n) && n !== st.step ? '✓' : String(n))
      b.appendChild(no)
      b.appendChild(el('span', 'cw-stept', t))
      b.addEventListener('click', function () { go(n) })
      li.appendChild(b)
      ol.appendChild(li)
    })
    return ol
  }

  var MINUTES = { 1: 2, 2: 2, 3: 2, 4: 1, 5: 1 }
  var INTRO = {
    1: { title: '先填公司的名稱與統一編號', why: '報價單、請款單與寄給客戶的信件，抬頭都會用這兩項。照公司登記的資料填就好。' },
    2: { title: '客戶要怎麼聯絡到你們', why: '電話與 Email 至少填一項；它們會印在文件抬頭，讓客戶知道怎麼聯絡。系統自己寄信用的信箱不在這裡設定，做完這一步後再到「開始使用」的寄信步驟處理。' },
    3: { title: '客戶要把錢匯到哪裡', why: '請款單會印出收款帳戶。現在還不開請款單可以先略過，之後隨時回來補。報價單的編號由系統自動產生，格式固定如下，不需要設定。' },
    4: { title: '放上公司 Logo', why: 'Logo 會印在報價單等文件上，也會顯示在系統頂端。沒有圖檔可以先略過，之後隨時回來換。' },
    5: { title: '最後確認', why: '請核對下面的資料。按下確認後，系統所有功能才會開放給同仁使用。' },
  }

  function navRow(n) {
    var row = el('div', 'cw-nav')
    if (n > 1) {
      var back = el('button', 'cw-btn', '上一步')
      back.type = 'button'; back.setAttribute('data-testid', 'cw-back')
      back.addEventListener('click', function () { go(n - 1) })
      row.appendChild(back)
    }
    var optional = n === 3 || n === 4
    if (optional) {
      var skip = el('button', 'cw-btn', '先略過')
      skip.type = 'button'; skip.setAttribute('data-testid', 'cw-skip')
      skip.addEventListener('click', function () {
        var pend = (STEP_FIELDS[n] || []).filter(function (k) { return Object.prototype.hasOwnProperty.call(st.draft, k) })
        // 重新確認（409）後留在畫面上、還沒生效的修改：略過會丟掉它，先講清楚、要再按一次才丟
        if (pend.length && st.needReconfirm && st.skipAsk !== n) { st.skipAsk = n; say('這一步有尚未生效的修改（等著在最後一步確認）。再按一次「先略過」會捨棄這些修改。', true); return }
        st.skipAsk = 0
        markSeen(n)
        pend.forEach(function (k) { delete st.draft[k] })      // 只丟這一步的未存內容，別步的修改不動
        go(n + 1)
      })
      row.appendChild(skip)
    }
    var next = el('button', 'cw-btn cw-btn--main', n === 4 ? '下一步' : '儲存並繼續')
    next.type = 'button'; next.setAttribute('data-testid', 'cw-next')
    next.disabled = st.busy || !stepOk(n)
    next.addEventListener('click', function () {
      saveStep(n).then(function (ok) { if (ok) { markSeen(n); go(n + 1) } })
    })
    row.appendChild(next)
    return row
  }

  function stepBody(n) {
    var body = el('div', 'cw-body')
    if (n <= 3) {
      STEP_FIELDS[n].forEach(function (k) { body.appendChild(fieldRow(k)) })
      if (n === 3) {
        var fmt = el('div', 'cw-fixed')
        fmt.setAttribute('data-testid', 'cw-numbering')
        fmt.appendChild(el('div', 'cw-fixed-t', '報價單編號（系統自動產生）'))
        fmt.appendChild(el('div', 'cw-fixed-v', 'MQ-年月-流水號，例如 MQ-202611-001'))
        fmt.appendChild(el('div', 'cw-note', '每個月的流水號從 001 重新開始。這是固定格式，目前不能修改。'))
        body.appendChild(fmt)
      }
      if (n === 1 || n === 2) body.appendChild(previewBox())
    } else if (n === 4) {
      ;[['logo', '文件用 Logo（印在報價單、請款單上）'], ['logo-dark', '系統頂端用 Logo（深色背景版）']].forEach(function (p) {
        var kind = p[0]
        var wrap = el('div', 'cw-field')
        wrap.appendChild(el('div', 'cw-label', p[1]))
        var cur = st.brand[kind]
        var status = el('div', 'cw-note', cur && cur.custom ? '已上傳。想換的話再選一張新的。' : '目前使用系統預設圖。')
        status.setAttribute('data-testid', 'cw-logo-status-' + kind)
        var inp = el('input', 'cw-file')
        inp.type = 'file'; inp.accept = 'image/png,image/jpeg,image/webp'
        inp.id = 'cw-' + kind
        inp.setAttribute('data-testid', 'cw-upload-' + kind)
        inp.setAttribute('aria-label', p[1])
        inp.addEventListener('change', function () { uploadLogo(kind, inp) })
        wrap.appendChild(inp)
        wrap.appendChild(status)
        body.appendChild(wrap)
      })
      body.appendChild(el('div', 'cw-note', '圖檔格式：PNG、JPG 或 WEBP，2 MB 以內。'))
      body.appendChild(previewBox())
    } else {
      body.appendChild(confirmBody())
    }
    return body
  }

  function confirmBody() {
    var box = el('div')
    var dl = el('dl', 'cw-sum'); dl.setAttribute('data-testid', 'cw-summary')
    function row(k, v) { dl.appendChild(el('dt', null, k)); dl.appendChild(el('dd', null, v || '（未填）')) }
    row('公司名稱', String(val('name') || '').trim())
    row('統一編號', taxDigits())
    row('電話', String(val('phone') || '').trim())
    row('Email', String(val('email') || '').trim())
    row('收款帳戶', [val('bank_name'), val('bank_account_name'), val('bank_account_number')].map(function (x) { return String(x || '').trim() }).filter(Boolean).join('　'))
    row('Logo', st.brand.logo && st.brand.logo.custom ? '已上傳' : '使用系統預設圖')
    box.appendChild(dl)
    box.appendChild(previewBox())
    var okReq = stepOk(1) && stepOk(2)
    if (!okReq) {
      var miss = el('div', 'cw-warn', '還有必要的資料沒填好：' + (stepOk(1) ? '' : '公司名稱與統一編號（第 1 步）') + (!stepOk(1) && !stepOk(2) ? '、' : '') + (stepOk(2) ? '' : '電話或 Email（第 2 步）') + '。請先回去補上。')
      miss.setAttribute('data-testid', 'cw-missing'); miss.setAttribute('role', 'alert')
      box.appendChild(miss)
    }
    var lab = el('label', 'cw-ack')
    var cb = el('input'); cb.type = 'checkbox'; cb.checked = st.ack; cb.setAttribute('data-testid', 'cw-ack')
    cb.disabled = !okReq
    cb.addEventListener('change', function () { st.ack = cb.checked; refreshConfirmBtn() })
    lab.appendChild(cb)
    lab.appendChild(el('span', null, '以上是本公司的資料（輸出的文件會使用這些資料）'))
    box.appendChild(lab)
    var go5 = el('button', 'cw-btn cw-btn--main cw-confirm', st.needReconfirm || (st.setup && st.setup.configured === true) ? '儲存並確認本公司資料' : '確認本公司資料')
    go5.type = 'button'; go5.setAttribute('data-testid', 'cw-confirm')
    go5.disabled = !(okReq && st.ack) || st.busy
    go5.addEventListener('click', function () { confirmAll() })
    box.appendChild(go5)
    return box
  }
  function refreshConfirmBtn() {
    var b = root.querySelector('[data-testid="cw-confirm"]')
    if (b) b.disabled = !(stepOk(1) && stepOk(2) && st.ack) || st.busy
  }

  function doneCard() {
    var card = el('div', 'cw-card cw-done')
    card.setAttribute('data-testid', 'cw-done')
    card.appendChild(el('h2', 'cw-h', '✓ 本公司資料已確認，系統功能已開放'))
    var w = window.MotrixWizard
    var totp = !!(w && w.isSuper && w.counted)
    card.appendChild(el('p', 'cw-why', totp ? '下一步：建議啟用兩步驟驗證（約 1 分鐘，也可以先略過）。寄信、備份等項目，之後在「開始使用」清單繼續。'
                                            : '接下來建議設定「系統寄信的信箱」，再到「開始使用」清單照順序做備份等項目。據點等進階設定，隨時可以回到公司資料設定頁補上。'))
    var act = el('div', 'cw-nav')
    function link(text, href, main, tid, onClick) {
      var a = el('a', 'cw-btn' + (main ? ' cw-btn--main' : ''), text)
      a.href = href; a.setAttribute('data-testid', tid)
      if (onClick) a.addEventListener('click', onClick)
      act.appendChild(a)
    }
    var fin = function () { if (w && w.finish) w.finish() }
    if (totp) {
      link('下一步：兩步驟驗證', 'change-password.html?wizard=totp', true, 'wizard-next')
      link('略過，到「開始使用」清單', 'getting-started.html', false, 'wizard-skip', fin)
    } else {
      link('到「開始使用」清單', 'getting-started.html', true, 'wizard-next', fin)
      link('繼續補充進階設定', 'company-profile-settings.html', false, 'wizard-more-settings', fin)
    }
    // 系統寄信的信箱不在本精靈內（PM 裁示）：連到既有的通知設定頁（寄信精靈合併後改指向它）
    link('設定系統寄信的信箱', 'notification-settings.html', false, 'wizard-email', fin)
    card.appendChild(act)
    return card
  }

  // 非最高管理者：不顯示任何表單、也不讀公司資料；文字與側欄的「沒有權限」頁一致
  function deniedCard() {
    var sub = document.querySelector('[data-testid="cw-subtitle"]')
    if (sub) sub.style.display = 'none'
    var box = el('div', 'cw-card'); box.setAttribute('data-testid', 'cw-denied'); box.style.textAlign = 'center'
    box.appendChild(el('div', '', '🔒')); box.firstChild.style.fontSize = '40px'
    box.appendChild(el('h2', 'cw-h', '你沒有這個頁面的權限'))
    box.appendChild(el('p', 'cw-why', '本公司資料只有最高管理者可以設定。請請最高管理者登入後完成設定，或洽系統管理員。'))
    return box
  }

  function render() {
    if (!root) return
    root.textContent = ''
    if (st.denied) { root.appendChild(deniedCard()); return }
    if (st.failed) { root.appendChild(el('div', 'cw-warn', '暫時讀不到公司資料，請重新整理頁面再試。')); return }
    if (!st.loaded) { root.appendChild(el('div', 'cw-note', '讀取中…')); return }
    if (st.confirmed) { root.appendChild(doneCard()); return }
    root.appendChild(stepBar())
    var n = st.step
    var card = el('div', 'cw-card'); card.setAttribute('data-testid', 'cw-card')
    var cap = el('div', 'cw-cap', '第 ' + n + '／5 步　約 ' + MINUTES[n] + ' 分鐘')
    card.appendChild(cap)
    var h = el('h2', 'cw-h', INTRO[n].title); h.setAttribute('data-testid', 'cw-title')
    card.appendChild(h)
    card.appendChild(el('p', 'cw-why', INTRO[n].why))
    if (st.msg) {
      var m = el('div', st.msgBad ? 'cw-warn' : 'cw-okmsg', st.msg)
      m.setAttribute('data-testid', 'cw-msg'); m.setAttribute('role', st.msgBad ? 'alert' : 'status')
      card.appendChild(m)
    }
    card.appendChild(stepBody(n))
    if (n < 5) card.appendChild(navRow(n))
    else {
      var back = el('div', 'cw-nav'); var b = el('button', 'cw-btn', '上一步')
      b.type = 'button'; b.setAttribute('data-testid', 'cw-back'); b.addEventListener('click', function () { go(4) })
      back.appendChild(b); card.appendChild(back)
    }
    root.appendChild(card)
    refreshTax(); refreshPreview()
    if (window.MotrixHint && window.MotrixHint.scan) { try { window.MotrixHint.scan(root) } catch (e) { /* 忽略 */ } }
  }

  function start() {
    root = document.getElementById('cw-root')
    if (!root) return
    if (!session.token) { location.replace('login.html'); return }
    render()
    window.addEventListener('hashchange', function () { var h = hash(); if (h && st.loaded && !st.confirmed && h !== st.step) { st.step = h; render() } })
    loadAll()
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start()
})()
