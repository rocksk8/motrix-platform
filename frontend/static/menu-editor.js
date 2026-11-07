/* menu-editor.js — 選單建構器（BP-1）：側欄項改名、換到另一個既有群組、調順序／隱藏，發布前預覽整份選單。
 *
 * 只在「設定 builder_menu.enabled 開啟 ＋ 最高管理者」時，由 sidebar.js 在 /api/platform/menu 回 builderMenu:true 後載入（關著 ⇒ 這支檔案不會被載入）。
 * 不碰頁面內排版器（layout-editor.js／layout-runtime.js 屬排版器）：這裡自己是一個浮動面板，資料經既有的版面定義（kind=layout，key=module:<模組>，
 * scope=company 或 role:<角色>）發布，所以版本、稽核、還原都沿用定義文件庫；非側欄的版面操作（排版器存的）原樣保留。
 *
 * 範圍（T78）：面板上方選「公司預設」或某個角色。套用順序＝角色層 ＞ 公司層 ＞ 程式預設，而且是『每個模組整份取代』（core.definitions.resolve）：
 * 某角色在某模組一旦有角色層，那個模組就只看角色層（公司層的改名／換群組／隱藏都不再套用給他）；沒有角色層的模組繼續跟公司層。
 * 所以角色層還沒有時，以『現行公司層』為起頭複製一份再改——只改了的模組才會建立角色層，沒動的模組繼續跟隨公司層。
 * 角色層的預覽必須指定一位該角色的在職帳號（模組勾選是每個人各自的）。
 *
 * 只是顯示：改名與換群組不改任何人的權限（href、perm 不變）；沒有權限的項目不會出現在預覽。
 * 發布前一定要先預覽「同一份」草稿（POST /api/platform/menu/preview）；草稿一改就要重新預覽。
 * 所有文字用 textContent 寫入（名稱是使用者輸入，不用 innerHTML）。
 */
;(function () {
  if (window.MotrixMenuEditor) return
  var LABEL_MAX = 20
  var st = { open: false, busy: false, state: 'idle', msg: '', msgBad: false, decl: [], base: {}, work: {}, order: {}, mods: {}, previewKey: '', preview: null, who: '',
    scope: 'company', roles: [], roleLayers: {}, users: [], touched: false }

  function session() {
    try { return JSON.parse(localStorage.getItem('motrix_session') || 'null') || {} } catch (e) { return {} }
  }
  function api(method, url, body) {
    var h = { Authorization: 'Bearer ' + (session().token || '') }
    if (body !== undefined) h['Content-Type'] = 'application/json'
    return fetch(url, { method: method, headers: h, body: body === undefined ? undefined : JSON.stringify(body) }).then(function (r) {
      return r.json().catch(function () { return {} }).then(function (j) {
        if (!r.ok) { var e = new Error(msgOf(j) || ('HTTP ' + r.status)); e.status = r.status; e.body = j; throw e }
        return j
      })
    })
  }
  function msgOf(j) {
    var d = j && (j.detail !== undefined ? j.detail : j)
    if (d && d.problems) return d.problems.map(function (p) { return (p.path ? p.path + '：' : '') + p.message }).join('；')
    if (j && j.problems && j.problems.length) return j.problems.map(function (p) { return (p.path ? p.path + '：' : '') + p.message }).join('；')
    return typeof d === 'string' ? d : ''
  }
  function el(tag, attrs, kids) {
    var n = document.createElement(tag)
    Object.keys(attrs || {}).forEach(function (k) {
      if (attrs[k] === null || attrs[k] === undefined) return
      if (k === 'text') n.textContent = attrs[k]
      else if (k.indexOf('on') === 0) n.addEventListener(k.slice(2), attrs[k])
      else n.setAttribute(k, attrs[k])
    })
    ;(kids || []).forEach(function (c) { if (c) n.appendChild(c) })
    return n
  }
  function pid(it) { return it.module ? it.module + ':' + it.href + '/sidebar' : null }
  function labelProblem(v) {
    if (!v.trim()) return '名稱不可空白'
    if (v.trim().length > LABEL_MAX) return '最多 ' + LABEL_MAX + ' 字'
    if (/[<>&"'`\\\x00-\x1f\x7f]/.test(v)) return '不可含 < > & 引號、反斜線'
    return ''
  }

  // ── 範圍（公司／角色）────────────────────────────────────────────────────────────────────────────────────
  function scopeQ() { return '?scope=' + encodeURIComponent(st.scope) }
  function roleKey() { return st.scope.indexOf('role:') === 0 ? st.scope.slice(5) : '' }
  function roleLabel(k) { var r = st.roles.filter(function (x) { return x.key === k })[0]; return r ? r.label : k }
  function scopeLabel() { return st.scope === 'company' ? '公司預設' : '角色「' + roleLabel(roleKey()) + '」' }
  function usersOfRole(k) {
    return st.users.filter(function (u) { return u && u.role === k && u.active !== 0 && u.active !== false })
  }
  // 角色層預覽身分：目前選的帳號若不是該角色的在職帳號 ⇒ 換成第一位；公司層 ⇒ 沿用使用者自己填的
  function fixWho() {
    var k = roleKey()
    if (!k) return
    var us = usersOfRole(k)
    if (!us.some(function (u) { return u.username === st.who })) st.who = us.length ? us[0].username : ''
  }
  // 讀角色名稱、已有角色層的角色、帳號清單（任何一項讀不到都不擋編輯：只是少了提示／預覽身分選單）
  function loadMeta() {
    var p = []
    if (!st.roles.length) {
      p.push(api('GET', '/api/settings/role-labels').then(function (l) {
        st.roles = Object.keys(l || {}).map(function (k) { return { key: k, label: String(l[k]) } })
      }).catch(function () {}))
    }
    p.push(api('GET', '/api/definitions/layout').then(function (rows) {
      st.roleLayers = {}
      ;(Array.isArray(rows) ? rows : []).forEach(function (r) {
        if (r && /^role:/.test(r.scope || '') && r.latestVersion) st.roleLayers[r.scope.slice(5)] = true
      })
    }).catch(function () {}))
    p.push(api('GET', '/api/users').then(function (u) { st.users = Array.isArray(u) ? u : [] }).catch(function () {}))
    return Promise.all(p)
  }
  // 讀某模組在目前範圍的版面操作。角色層還沒有（沒草稿也沒發布）⇒ 以『現行公司層』為起頭（copied），因為角色層一發布就整份取代公司層。
  // 公司層讀不到沿用舊行為（當空的）；角色層讀不到 ⇒ 整個讀取失敗（不能把空的當成起頭，否則發布後會把公司層的操作整份蓋掉）。
  function loadMod(m) {
    var url = '/api/definitions/layout/module:' + encodeURIComponent(m)
    return api('GET', url + scopeQ()).then(function (r) {
      var cur = r.draft || r.latest
      var own = { ops: (cur && cur.body && cur.body.ops) || [], etag: (r.draft && r.draft.etag) || '', copied: false }
      if (cur || st.scope === 'company') return own
      return api('GET', url + '?scope=company').then(function (c) {
        var live = c && c.latest
        return { ops: (live && live.body && live.body.ops) || [], etag: '', copied: true }
      })
    }).then(function (x) { st.mods[m] = x }, function (e) {
      if (st.scope !== 'company') throw e
      st.mods[m] = { ops: [], etag: '', copied: false }
    })
  }

  // ── 狀態：宣告版（base）＋ 已發布的側欄操作（目前範圍）⇒ 工作副本（work：每個群組的項目順序、名稱、隱藏）────────────────
  function load() {
    st.busy = true; st.msg = '讀取中…'; render()
    return loadMeta().then(function () { return api('GET', '/api/platform/menu') }).then(function (d) {
      st.decl = d.groups || []
      st.base = {}; st.order = {}; st.work = {}; st.mods = {}; st.touched = false; fixWho()
      st.decl.forEach(function (g) {
        st.order[g.key] = g.items.map(function (it) { return it.module ? pid(it) : 'l1:' + it.href })
        g.items.forEach(function (it) {
          var id = it.module ? pid(it) : 'l1:' + it.href
          st.base[id] = { id: id, group: g.key, label: it.label, href: it.href, module: it.module || null }
          st.work[id] = { label: it.label, hidden: false }
        })
      })
      var mods = {}
      Object.keys(st.base).forEach(function (id) { if (st.base[id].module) mods[st.base[id].module] = true })
      return Promise.all(Object.keys(mods).map(loadMod))
    }).then(function () {
      Object.keys(st.mods).forEach(function (m) { st.mods[m].ops.forEach(applyExisting) })
      st.busy = false; st.msg = ''; st.previewKey = ''; st.preview = null; render()
    }).catch(function (e) { st.busy = false; st.msg = '讀取失敗：' + e.message; st.msgBad = true; render() })
  }
  function applyExisting(op) {
    if (!op || typeof op.target !== 'string' || !/\/sidebar$/.test(op.target) || !st.work[op.target]) return
    var w = st.work[op.target]
    if (op.op === 'relabel') w.label = op.label
    else if (op.op === 'hide') w.hidden = true
    else if (op.op === 'show') w.hidden = false
    else if (op.op === 'move') {
      var to = typeof op.to === 'string' && op.to.indexOf('group:') === 0 ? op.to.slice(6) : st.base[op.target].group
      if (st.order[to]) {
        Object.keys(st.order).forEach(function (k) { st.order[k] = st.order[k].filter(function (x) { return x !== op.target }) })
        var idx = typeof op.index === 'number' ? Math.min(op.index, st.order[to].length) : st.order[to].length
        st.order[to].splice(idx, 0, op.target)
      }
    }
  }
  function groupOf(id) {
    var found = null
    Object.keys(st.order).forEach(function (k) { if (st.order[k].indexOf(id) >= 0) found = k })
    return found
  }

  // ── 工作副本 ⇒ 側欄 ops（對每個『最終順序與宣告不同』的群組，依最終順序發出每個模組項目的 move）─────────────────────
  function buildOps() {
    var ops = []
    Object.keys(st.base).forEach(function (id) {
      var b = st.base[id], w = st.work[id]
      if (!b.module) return
      if (w.label !== b.label) ops.push({ op: 'relabel', target: id, label: w.label })
      if (w.hidden) ops.push({ op: 'hide', target: id })
    })
    st.decl.forEach(function (g) {
      var finalIds = st.order[g.key]
      var declIds = g.items.map(function (it) { return it.module ? pid(it) : 'l1:' + it.href })
      if (finalIds.join('|') === declIds.join('|')) return
      finalIds.forEach(function (id, i) {
        var b = st.base[id]
        if (!b.module) return
        var op = { op: 'move', target: id, index: i }
        if (b.group !== g.key) op.to = 'group:' + g.key
        ops.push(op)
      })
    })
    return ops
  }
  function dirtyKey() { return JSON.stringify(buildOps()) }

  // ── 動作 ───────────────────────────────────────────────────────────────────────────────────────────────
  function doPreview() {
    var bad = Object.keys(st.work).filter(function (id) { return labelProblem(st.work[id].label) })
    if (bad.length) { st.msg = '「' + st.work[bad[0]].label + '」：' + labelProblem(st.work[bad[0]].label); st.msgBad = true; return render() }
    if (st.scope !== 'company' && !st.who.trim()) {
      st.msg = '沒有「' + roleLabel(roleKey()) + '」角色的在職帳號可以預覽——角色層的預覽要用該角色的帳號（模組勾選是每個人各自的），所以也無法發布。'; st.msgBad = true; return render()
    }
    var ops = buildOps(), key = JSON.stringify(ops)
    st.busy = true; st.msg = '產生預覽…'; st.msgBad = false; render()
    var body = { ops: ops }
    if (st.scope !== 'company') body.scope = st.scope                 // 公司層不帶 scope（請求與過去逐位元相同）
    if (st.who.trim()) body.user = st.who.trim()
    return api('POST', '/api/platform/menu/preview', body).then(function (d) {
      st.preview = d; st.previewKey = key; st.busy = false
      st.msg = d.skipped && d.skipped.length ? '有 ' + d.skipped.length + ' 項操作對這位使用者不適用（沒有權限或看不到目的群組），已略過。' : '預覽完成。'
      render()
    }).catch(function (e) { st.busy = false; st.msg = '預覽失敗：' + e.message; st.msgBad = true; render() })
  }
  // T62：把這個模組剛存好的版面草稿送去『影響預覽』（伺服端記一筆『看過』）⇒ 草稿戳；治理旗標關（404）或任何失敗 ⇒ null（不帶雜湊，與過去相同）
  function previewSeen(m, scope) {
    var gkey = 'module:' + encodeURIComponent(m)       // 版面定義的 key；寫成樣板字串讓 V3.3 掃描器看到 /api/def-governance/{kind}/{key}/impact
    return api('GET', `/api/def-governance/layout/${gkey}/impact?scope=${encodeURIComponent(scope || 'company')}`).then(function (d) {
      return d && typeof d.previewHash === 'string' && d.previewHash ? d.previewHash : null
    }).catch(function () { return null })
  }
  // 某模組發布後的整份版面操作：該模組既有的非側欄操作（排版器存的）原樣保留 ＋ 這次的側欄操作
  function nextOps(m, ops) {
    var mine = ops.filter(function (o) { return o.target.indexOf(m + ':') === 0 })
    var keep = st.mods[m].ops.filter(function (o) { return !(o && typeof o.target === 'string' && /\/sidebar$/.test(o.target) && o.target.indexOf(m + ':') === 0) })
    return keep.concat(mine)
  }
  // 兩份操作清單是不是『同一批操作』（不看清單順序、也不看單一操作的鍵順序）。是 ⇒ 沒有要變更的內容，保持目前生效版（也就是畫面顯示的那一版）：
  // 重新組出來時側欄操作會排在非側欄操作後面，或別的編輯器寫的操作鍵順序不同，都不代表使用者改了什麼；沒動的模組不可以因此被當成要發布（角色層會無端建立）。
  // 注意：這裡只判斷『要不要發布』，不宣稱不同順序的 move 套用結果相同（絕對位置的 move 結果取決於套用順序）。
  function sameOps(a, b) {
    var canon = function (v) {
      if (Array.isArray(v)) return v.map(canon)
      if (v && typeof v === 'object') { var o = {}; Object.keys(v).sort().forEach(function (k) { o[k] = canon(v[k]) }); return o }
      return v
    }
    var f = function (l) { return (l || []).map(function (o) { return JSON.stringify(canon(o)) }).sort().join('|') }
    return f(a) === f(b)
  }
  // 按下發布會寫入（建立或更新）哪些模組的版面：和 doPublish 同一個判準
  function willPublish() {
    var ops = buildOps()
    return Object.keys(st.mods).filter(function (m) { return !sameOps(nextOps(m, ops), st.mods[m].ops) })
  }
  function doPublish() {
    if (!st.preview || st.previewKey !== dirtyKey()) { st.msg = '草稿已變更，請先重新預覽'; st.msgBad = true; return render() }
    var ops = buildOps()
    var mods = Object.keys(st.mods)
    var q = scopeQ(), sc = st.scope, where = scopeLabel()            // 發布期間範圍選單是鎖住的；仍以開始當下的範圍為準
    st.busy = true; st.msg = '發布中…'; st.msgBad = false; render()
    var chain = Promise.resolve(), done = 0, pend = []
    mods.forEach(function (m) {
      var next = nextOps(m, ops)
      if (sameOps(next, st.mods[m].ops)) return
      chain = chain.then(function () {
        var url = '/api/definitions/layout/module:' + encodeURIComponent(m)
        return api('PUT', url + '/draft' + q, { body: { ops: next }, base_etag: st.mods[m].etag || undefined }).then(function (r) {
          return previewSeen(m, sc).then(function (pvh) {
            var pub = { note: '選單建構器', base_etag: r.etag }
            if (pvh) pub.preview_hash = pvh                       // T62：治理旗標開時才有；關＝請求與過去逐位元相同
            return api('POST', url + '/publish' + q, pub)
          })
        }).then(function (r2) {
          // T60 S2：治理旗標開啟時，放寬的發布可能回 {pending:true,…}（待第二位最高管理者核准、還沒生效）——不能說「已發布」
          if (r2 && r2.pending === true) pend.push(r2); else done++
        })
      })
    })
    chain.then(function () {
      st.busy = false; st.msgBad = false
      var text = pend.length ? pendingText(pend, done)
        : sc === 'company' ? '已發布（' + done + ' 個模組的版面）。重新整理頁面即可看到新的側欄。'
          : '已發布（' + done + ' 個模組的版面）到' + where + '的角色層。該角色的使用者重新整理頁面後即可看到；其他角色不受影響。'
      if (pend.length) { st.msg = text; st.state = 'pending'; render(); return }           // 待核准：選單沒有變，不重讀、不說已發布
      st.state = 'published'
      return load().then(function () { st.msg = text; st.state = 'published'; render() })
    }).catch(function (e) { st.busy = false; st.state = 'error'; st.msg = '發布失敗：' + e.message + '（已發布的模組不會回復，可在版本清單還原）'; st.msgBad = true; render() })
  }
  // 待核准的白話說明：已送出、待第二位最高管理者核准、核准前不會生效、最早生效時間、原因；有部分模組已直接發布也要說
  function pendingText(list, doneCount) {
    var d = list[0] || {}
    var reasons = []
    list.forEach(function (x) {
      ;(x.reasons || []).forEach(function (r) { var t = typeof r === 'string' ? r : ((r && (r.message || r.text)) || ''); if (t && reasons.indexOf(t) < 0) reasons.push(t) })
    })
    var at = d.effectiveAt ? String(d.effectiveAt).replace('T', ' ').slice(0, 16) : ''
    return '已送出發布（' + list.length + ' 個模組的版面），待第二位最高管理者核准；核准前不會生效'
      + (at ? '，生效時間 ' + at + ' 之後' : '') + (reasons.length ? '。原因：' + reasons.join('；') : '')
      + (doneCount ? '。另有 ' + doneCount + ' 個模組已直接發布。' : '。') + ''
  }
  function move(id, dir) {
    var g = groupOf(id), arr = st.order[g], i = arr.indexOf(id), j = i + dir
    if (j < 0 || j >= arr.length) return
    arr.splice(i, 1); arr.splice(j, 0, id); changed()
  }
  function toGroup(id, key) {
    var g = groupOf(id)
    if (g === key) return
    st.order[g] = st.order[g].filter(function (x) { return x !== id })
    st.order[key].push(id); changed()
  }
  function changed() { st.msg = ''; st.touched = true; render() }
  // 切換編輯範圍：放棄尚未發布的調整、重新讀該範圍的現況（角色層沒有時以公司層為起頭）
  function switchScope(v) {
    if (v === st.scope || st.busy) return render()
    if (st.touched && typeof confirm === 'function' && !confirm('切換範圍會放棄目前尚未發布的調整，確定嗎？')) return render()
    st.scope = v; st.who = ''; st.msg = ''; st.msgBad = false; st.state = 'idle'
    return load()
  }

  // ── 畫面 ───────────────────────────────────────────────────────────────────────────────────────────────
  var btn, panel
  function css() {
    if (document.getElementById('menu-editor-css')) return
    var s = el('style', { id: 'menu-editor-css', text:
      '#me-btn{position:fixed;left:12px;bottom:12px;z-index:1150;padding:6px 12px;font-size:12px}' +
      '#me-panel{position:fixed;top:0;right:0;bottom:0;width:420px;max-width:100vw;z-index:1190;background:var(--bg-card,#fff);border-left:1px solid var(--border-light,#ddd);box-shadow:-8px 0 24px rgba(0,0,0,.08);display:flex;flex-direction:column;font-size:12px}' +
      '#me-panel .me-h{padding:10px 14px;border-bottom:1px solid var(--border-light,#ddd);display:flex;gap:8px;align-items:center}' +
      '#me-panel .me-b{flex:1;overflow:auto;padding:10px 14px}#me-panel .me-f{padding:10px 14px;border-top:1px solid var(--border-light,#ddd);display:flex;gap:8px;flex-wrap:wrap}' +
      '#me-panel .me-g{font-weight:600;margin:10px 0 4px}#me-panel .me-i{display:flex;gap:4px;align-items:center;padding:3px 0}' +
      '#me-panel .me-i input[type=text]{flex:1;min-width:0}#me-panel .me-i.is-hidden{opacity:.5}#me-panel .me-msg{padding:6px 14px}#me-panel .me-bad{color:#c0392b}' +
      '#me-panel .me-pv{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px}#me-panel .me-pv ul{margin:2px 0 6px 16px;padding:0}#me-panel .me-chg{background:#fff3cd}' +
      '#me-panel .me-scope{border:1px solid var(--border-light,#ddd);border-radius:6px;padding:8px 10px;margin-bottom:8px}#me-panel .me-scope-row{display:flex;gap:6px;align-items:center}' +
      '#me-panel .me-scope-row select{flex:1;min-width:0}#me-panel .me-scope-now{font-weight:700;margin:6px 0 2px}' +
      '#me-panel .me-scope[data-scope^="role:"] .me-scope-now{color:#8a5a00;background:#fff3cd;padding:2px 6px;border-radius:4px}' +
      '#me-panel .me-scope-note{color:#666;line-height:1.5}#me-panel .me-scope-will{margin-top:6px;font-weight:600}' +
      '@media (max-width:1023px){#me-btn{display:none!important}}' })
    document.head.appendChild(s)
  }
  function groupSelect(id) {
    var cur = groupOf(id)
    var sel = el('select', { title: '群組', onchange: function (e) { toGroup(id, e.target.value) } })
    st.decl.forEach(function (g) {
      // T60：含 hub 項的群組（系統中心）導覽列會收成單一連結，搬進去看不到 ⇒ 不當目的地（項目本來就在裡面時才保留，免得下拉選不到現值）
      if (g.items.some(function (it) { return it.hub }) && g.key !== cur) return
      var o = el('option', { value: g.key, text: g.label }); if (g.key === cur) o.selected = true; sel.appendChild(o)
    })
    return sel
  }
  function itemRow(id) {
    var b = st.base[id], w = st.work[id]
    if (!b.module) return el('div', { class: 'me-i', 'data-id': id }, [el('span', { style: 'flex:1;color:#888', text: b.label + '（固定項目）' })])
    var inp = el('input', { type: 'text', maxlength: String(LABEL_MAX), value: w.label, title: '顯示名稱',
      onchange: function (e) { w.label = e.target.value; changed() } })
    var row = el('div', { class: 'me-i' + (w.hidden ? ' is-hidden' : ''), 'data-id': id }, [
      el('input', { type: 'checkbox', title: '顯示', onchange: function (e) { w.hidden = !e.target.checked; changed() } }),
      inp, groupSelect(id),
      el('button', { type: 'button', title: '上移', text: '↑', onclick: function () { move(id, -1) } }),
      el('button', { type: 'button', title: '下移', text: '↓', onclick: function () { move(id, 1) } })])
    row.firstChild.checked = !w.hidden
    var pr = labelProblem(w.label)
    if (pr) row.appendChild(el('span', { class: 'me-bad', text: pr }))
    return row
  }
  function groupsList(groups, ref) {
    var root = el('div')
    groups.forEach(function (g) {
      var refG = (ref || []).filter(function (x) { return x.key === g.key })[0]
      root.appendChild(el('div', { class: 'me-g', text: g.label }))
      var ul = el('ul')
      g.items.forEach(function (it) {
        var same = refG && refG.items.some(function (r) { return r.href === it.href && r.label === it.label && r.module === it.module })
        ul.appendChild(el('li', { class: ref && !same ? 'me-chg' : '', text: it.label }))
      })
      root.appendChild(ul)
    })
    return root
  }
  // 範圍列：選單（公司預設／各角色）＋『目前在編輯哪一層』的醒目標示＋套用順序說明
  function scopeBar() {
    var k = roleKey()
    var sel = el('select', { 'data-testid': 'me-scope-select', title: '編輯範圍', disabled: st.busy ? 'disabled' : null,
      onchange: function (e) { switchScope(e.target.value) } })
    var o0 = el('option', { value: 'company', text: '公司預設' }); if (st.scope === 'company') o0.selected = true; sel.appendChild(o0)
    var keys = st.roles.map(function (r) { return r.key })
    if (k && keys.indexOf(k) < 0) keys.push(k)                              // 角色表讀不到時，至少保留目前這一個
    keys.forEach(function (rk) {
      var o = el('option', { value: 'role:' + rk, text: '角色：' + roleLabel(rk) + (st.roleLayers[rk] ? '（已有角色層）' : '') })
      if (st.scope === 'role:' + rk) o.selected = true; sel.appendChild(o)
    })
    var box = el('div', { class: 'me-scope', 'data-testid': 'me-scope', 'data-scope': st.scope }, [
      el('div', { class: 'me-scope-row' }, [el('span', { text: '編輯範圍：' }), sel]),
      el('div', { class: 'me-scope-now', 'data-testid': 'me-scope-now', text: '目前編輯：' + scopeLabel() + (k ? '的角色層' : '（所有人的預設）') })])
    var note
    if (k) {
      var own = Object.keys(st.mods).filter(function (m) { return !st.mods[m].copied }).length
      var follow = Object.keys(st.mods).length - own
      note = '套用順序：角色層 ＞ 公司層。某個模組只要發布了「' + roleLabel(k) + '」的角色層，這個角色在該模組就整份改用角色層——公司層在該模組的改名、換群組、隱藏都不再套用給他（不是逐項合併）。'
        + '還沒有角色層的模組會先以現行公司層為起頭複製一份再改；只改項目名稱、隱藏或換群組時，只有被改到的模組會建立角色層；'
        + '但調整群組內的順序時，同一個群組裡的所有模組都會一併建立角色層（順序是位置式的）——建立後那些模組就不再跟公司層。'
        + '載入時：' + own + ' 個模組已有角色層、' + follow + ' 個跟隨公司層。'
        + '預覽要用一位「' + roleLabel(k) + '」角色的在職帳號。'
    } else {
      var layered = st.roles.filter(function (r) { return st.roleLayers[r.key] }).map(function (r) { return r.label })
      note = '公司預設會套用給所有沒有自己角色層的角色。'
        + (layered.length ? '已有角色層的角色（' + layered.join('、') + '）在有角色層的模組不會看到這裡的調整；到該角色的範圍去改。' : '')
    }
    box.appendChild(el('div', { class: 'me-scope-note', text: note }))
    var wp = willPublish()                                                  // 隨編輯即時更新：按發布會寫入哪些模組
    box.appendChild(el('div', { class: 'me-scope-will', 'data-testid': 'me-will-publish', 'data-count': String(wp.length),
      text: wp.length ? '按發布會' + (k ? '建立或更新「' + roleLabel(k) + '」角色層' : '更新公司層') + '的 ' + wp.length + ' 個模組：' + wp.join('、') : '目前沒有要發布的調整。' }))
    return box
  }
  // 預覽身分：公司層＝自由填帳號（空白＝我自己）；角色層＝只能選該角色的在職帳號
  function whoControl() {
    var k = roleKey()
    if (!k) return el('input', { type: 'text', placeholder: '預覽身分（帳號；空白＝我自己）', value: st.who, style: 'flex:1', onchange: function (e) { st.who = e.target.value; st.previewKey = ''; render() } })
    var us = usersOfRole(k)
    if (!us.length) return el('span', { class: 'me-bad', style: 'flex:1', 'data-testid': 'me-who-none', text: '沒有「' + roleLabel(k) + '」角色的在職帳號，無法預覽' })
    var sel = el('select', { 'data-testid': 'me-who', style: 'flex:1', title: '預覽身分（該角色的帳號）',
      onchange: function (e) { st.who = e.target.value; st.previewKey = ''; render() } })
    us.forEach(function (u) {
      var o = el('option', { value: u.username, text: (u.displayName || u.username) + '（' + u.username + '）' }); if (u.username === st.who) o.selected = true; sel.appendChild(o)
    })
    return sel
  }
  function render() {
    css()
    if (!btn) { btn = el('button', { id: 'me-btn', type: 'button', class: 'btn btn-ghost btn-sm', 'data-testid': 'me-open', text: '調整選單', onclick: function () { st.open = !st.open; if (st.open && !st.decl.length) load(); else render() } }); document.body.appendChild(btn) }
    if (panel) { panel.remove(); panel = null }
    if (!st.open) return
    var dirty = !!st.previewKey && st.previewKey === dirtyKey()
    var body = el('div', { class: 'me-b', inert: st.busy ? '' : null })     // 讀取／發布中不可編輯（否則改到的是即將被換掉的舊工作副本）
    body.appendChild(el('div', { style: 'color:#666;margin-bottom:6px', text: '只改側欄怎麼顯示，不改任何人的權限；沒有權限的項目不會出現在預覽。' }))
    body.appendChild(scopeBar())
    st.decl.forEach(function (g) {
      body.appendChild(el('div', { class: 'me-g', text: g.label }))
      ;(st.order[g.key] || []).forEach(function (id) { body.appendChild(itemRow(id)) })
    })
    if (st.preview) {
      body.appendChild(el('div', { class: 'me-g', text: '預覽（' + st.preview.user + '／' + st.preview.role + '）：左＝目前已發布，右＝套用草稿後（黃底＝有變）' }))
      body.appendChild(el('div', { class: 'me-pv', 'data-testid': 'me-preview' }, [groupsList(st.preview.current), groupsList(st.preview.preview, st.preview.current)]))
    }
    var who = whoControl()
    panel = el('div', { id: 'me-panel', 'data-busy': st.busy ? '1' : '0', 'data-state': st.state }, [
      el('div', { class: 'me-h' }, [el('b', { text: '調整選單' }), who, el('button', { type: 'button', text: '✕', onclick: function () { st.open = false; render() } })]),
      body,
      el('div', { class: 'me-msg' + (st.msgBad ? ' me-bad' : ''), text: st.msg }),
      el('div', { class: 'me-f' }, [
        el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-testid': 'me-preview-btn', text: '預覽', disabled: st.busy ? 'disabled' : null, onclick: doPreview }),
        el('button', { type: 'button', class: 'btn btn-primary btn-sm', 'data-testid': 'me-publish', text: '發布', title: dirty ? '' : '請先預覽同一份草稿', onclick: doPublish }),
        el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '重新載入', onclick: load })])])
    var pub = panel.querySelector('[data-testid=me-publish]')
    if (pub && (st.busy || !dirty)) pub.setAttribute('disabled', 'disabled')
    document.body.appendChild(panel)
  }

  window.MotrixMenuEditor = { _pendingText: pendingText, _publish: doPublish, open: function () { st.open = true; return load() }, _state: st, _buildOps: buildOps, _switchScope: switchScope, _preview: doPreview, _willPublish: willPublish }
  render()
})()
