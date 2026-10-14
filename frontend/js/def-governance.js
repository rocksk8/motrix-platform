/* def-governance.js — BP-1 定義治理面板：版本帳本、比較任兩版、一鍵還原、發布前影響預覽。
 *
 * 獨立元件（不依賴 Alpine）；編輯器只要呼叫：
 *   MotrixDefGovernance.available(kind)                  ⇒ Promise<boolean>（旗標關閉或不是最高管理者 ⇒ false，編輯器不顯示入口；kind 預設 layout）
 *   MotrixDefGovernance.open({ kind, key, scope, title, tab, readonly, onRestored })   ⇒ 開面板（tab: ledger｜impact；readonly:true ⇒ 不顯示還原，編輯器自己有還原流程時用）
 *   MotrixDefGovernance.preview({ kind, key, scope })    ⇒ Promise<{ok, hash, data}>：發布前影響預覽（只取資料；會留一筆『看過預覽』稽核）
 *   MotrixDefGovernance.review({ kind, key, scope, title }) ⇒ Promise<string|null>：開預覽面板讓使用者確認；按『確認並發布』⇒ 草稿戳（發布時帶 preview_hash）；取消／驗證不過 ⇒ null
 *   待核准的放寬變更（T60 S2b）：後端 /api/def-pipeline/pending 存在（旗標開、最高管理者）⇒ 面板多一個「待核准變更」分頁，列出全部待核准項，
 *   可核准／套用（核准票夠、確認期間已過才成功）／撤銷；每個動作都在畫面上兩段確認，不用原生對話框。
 *   （伺服端 T60 S1：旗標開、名單內的 kind，發布沒帶『看過的』preview_hash 一律 409，沒有後門）
 * 旗標 builder_governance.enabled 預設關：後端對三條 /api/def-governance/… 一律 404，本檔不出現任何畫面。
 * 還原沿用既有 POST /api/definitions/{kind}/{key}/restore/{version}（新版本、歷史不改、現行驗證器）。
 * e2e 等待點：#dg-panel 的 data-busy（'0'／'1'）與 data-state（idle／restored／error）。
 */
;(function () {
  if (window.MotrixDefGovernance) return

  function hdr() {
    var s = {}
    try { s = JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) {}
    return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + (s.token || '') }
  }
  function enc(x) { return encodeURIComponent(x) }
  function base(o, tail) { return '/api/def-governance/' + enc(o.kind) + '/' + enc(o.key) + tail + '?scope=' + enc(o.scope || 'company') }
  async function call(method, url, payload) {
    var r = await fetch(url, { method: method, headers: hdr(), body: payload === undefined ? undefined : JSON.stringify(payload) })
    var d = await r.json().catch(function () { return null })
    return { ok: r.ok, status: r.status, data: d }
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] }) }

  var CSS = [
    '#dg-panel{position:fixed;top:0;right:0;bottom:0;width:420px;max-width:100vw;z-index:1300;background:var(--bg-card,#fff);color:var(--text-primary,#222);',
    'border-left:1px solid var(--border-light,#ddd);box-shadow:-8px 0 24px rgba(0,0,0,.1);display:flex;flex-direction:column;font-size:13px}',
    '#dg-panel .dg-head{padding:12px 14px;border-bottom:1px solid var(--border-light,#ddd);display:flex;gap:8px;align-items:center}',
    '#dg-panel .dg-head b{flex:1}#dg-panel .dg-body{flex:1;overflow:auto;padding:10px 14px}',
    '#dg-panel .dg-tabs{display:flex;gap:6px;padding:8px 14px 0}#dg-panel .dg-tab{padding:4px 10px;border:1px solid var(--border-light,#ddd);border-radius:6px;background:none;color:inherit;cursor:pointer}',
    '#dg-panel .dg-tab[aria-selected=true]{background:var(--bg-hover,#eef);font-weight:600}',
    '#dg-panel .dg-row{display:flex;gap:6px;align-items:center;padding:6px 0;border-bottom:1px solid var(--border-light,#eee)}',
    '#dg-panel .dg-row .dg-grow{flex:1}#dg-panel .dg-dim{color:var(--text-dim,#888);font-size:12px}',
    '#dg-panel .dg-warn{margin:6px 0;padding:6px 8px;border:1px solid var(--warning,#c80);border-radius:6px;font-size:12px}',
    '#dg-panel .dg-live{color:var(--success,#1a7f37);font-weight:600}#dg-panel .dg-bad{color:var(--danger,#c00)}',
    '#dg-panel button.dg-btn{padding:3px 9px;border:1px solid var(--border-light,#ccc);border-radius:6px;background:var(--bg-card,#fff);color:inherit;cursor:pointer}',
    '#dg-panel pre{white-space:pre-wrap;word-break:break-all;font-size:12px;margin:4px 0}'
  ].join('')

  var st = null     // { o, tab, busy, state, ledger, diff, impact, err, cmp:[a,b] }

  function setState(s) { var p = document.getElementById('dg-panel'); if (p) p.setAttribute('data-state', s) }
  function setBusy(b) { if (!st) return; st.busy = b; var p = document.getElementById('dg-panel'); if (p) p.setAttribute('data-busy', b ? '1' : '0') }

  var OPS = { add: '新增', remove: '移除', change: '修改' }
  function show(v) { return v === undefined ? '（無）' : esc(JSON.stringify(v)) }
  function changeLine(c) {
    return '<div class="dg-row"><div class="dg-grow"><code>' + esc(c.path || '(根)') + '</code> <span class="dg-dim">' + esc(OPS[c.op] || c.op) + '</span>' +
      '<pre>' + show(c.old) + ' ⇒ ' + show(c['new']) + '</pre></div></div>'
  }

  function render() {
    var p = document.getElementById('dg-panel')
    if (!p || !st) return
    var h = '<div class="dg-head"><b>' + esc(st.o.title || (st.o.kind + ' / ' + st.o.key)) + '</b><button class="dg-btn" data-dg="close">關閉</button></div>'
    h += '<div class="dg-tabs" role="tablist">' +
      '<button class="dg-tab" role="tab" data-dg="tab:ledger" aria-selected="' + (st.tab === 'ledger') + '">版本帳本</button>' +
      '<button class="dg-tab" role="tab" data-dg="tab:impact" aria-selected="' + (st.tab === 'impact') + '">發布前影響預覽</button>' +
      (st.pipe ? '<button class="dg-tab" role="tab" data-dg="tab:pending" aria-selected="' + (st.tab === 'pending') + '">待核准變更' + (st.pending && st.pending.length ? '（' + st.pending.length + '）' : '') + '</button>' : '') + '</div>'
    h += '<div class="dg-body">'
    if (st.err) h += '<div class="dg-bad" role="alert">' + esc(st.err) + '</div>'
    if (st.tab === 'ledger') h += renderLedger()
    else if (st.tab === 'pending') h += renderPending()
    else h += renderImpact()
    h += '</div>'
    if (st.o.review) {
      var I = st.impact, ok = !!(I && I.hasDraft && I.validation && I.validation.ok)
      h += '<div class="dg-head" style="border-top:1px solid var(--border-light,#ddd);border-bottom:0"><b class="dg-dim">' + (ok ? '確認後才會發布' : '目前不能發布') + '</b>' +
        '<button class="dg-btn" data-dg="review-cancel">取消</button>' +
        '<button class="dg-btn" data-dg="review-ok"' + (ok ? '' : ' disabled') + '>確認並發布</button></div>'
    }
    p.innerHTML = h
  }

  function renderLedger() {
    var L = st.ledger
    if (!L) return '<div class="dg-dim">讀取中…</div>'
    if (!L.versions.length) return '<div class="dg-dim">還沒有發布過的版本。</div>' + (L.hasDraft ? '<div class="dg-dim">有一份草稿。</div>' : '')
    var h = (L.warnings || []).map(function (w) { return '<div class="dg-warn" role="note">' + esc(w) + '</div>' }).join('')
    h += '<div class="dg-dim">目前生效：第 ' + esc(L.live) + ' 版' + (L.hasDraft ? '；另有一份草稿' : '') + (L.pendingReview ? '；有送審中的版本' : '') + '</div>'
    L.versions.forEach(function (v) {
      h += '<div class="dg-row"><div class="dg-grow"><b>第 ' + esc(v.version) + ' 版</b> ' + (v.isLive ? '<span class="dg-live">目前生效</span>' : '') +
        '<div class="dg-dim">' + esc(v.by) + '　' + esc(v.at) + (v.note ? '　' + esc(v.note) : '') + '</div></div>' +
        '<button class="dg-btn" data-dg="cmp:' + esc(v.version) + '">與目前比較</button>' +
        (v.restorable && v.validNow === false ? '<span class="dg-bad" data-dg-invalid="' + esc(v.version) + '">現行驗證不通過，無法還原</span>' : '') +
        (v.restorable && v.validNow !== false && !st.o.readonly ? (st.confirming === String(v.version)
          ? '<span class="dg-bad">還原成新的一版？</span><button class="dg-btn" data-dg="restore-yes:' + esc(v.version) + '">確定</button><button class="dg-btn" data-dg="restore-no">取消</button>'
          : '<button class="dg-btn" data-dg="restore:' + esc(v.version) + '">還原</button>') : '') + '</div>'
    })
    if (st.diff) {
      h += '<h4>第 ' + esc(st.diff.a) + ' 版 ⇒ ' + esc(st.diff.b) + '</h4>'
      h += st.diff.changes.length ? st.diff.changes.map(changeLine).join('') : '<div class="dg-dim">沒有差異。</div>'
    }
    return h
  }

  var VERBS = { approve: '核准', activate: '套用', cancel: '撤銷' }
  function renderPending() {
    var P = st.pending
    if (!P) return '<div class="dg-dim">讀取中…</div>'
    if (!P.length) return '<div class="dg-dim">目前沒有待核准的放寬變更。</div>'
    return '<div class="dg-dim">放寬限制的變更要另一位最高管理者核准，並等確認期間過後才能套用；期間內任何最高管理者都能撤銷。</div>' + P.map(function (c) {
      var key = String(c.id)
      var btns = ['approve', 'activate', 'cancel'].map(function (v) {
        if (st.pconfirm === v + ':' + key) {
          return '<span class="dg-bad">確定' + VERBS[v] + '？</span><button class="dg-btn" data-dg="pact-yes:' + v + ':' + key + '">確定</button><button class="dg-btn" data-dg="pact-no">取消</button>'
        }
        var dis = v === 'activate' && !c.ready
        return '<button class="dg-btn" data-dg="pact:' + v + ':' + key + '"' + (dis ? ' disabled title="還沒核准或確認期間未過"' : '') + '>' + VERBS[v] + '</button>'
      }).join('')
      return '<div class="dg-row" data-change="' + esc(c.id) + '"><div class="dg-grow"><b>' + esc(c.kind) + ' / ' + esc(c.key) + '</b>（' + esc(c.scope) + '，第 ' + esc(c.version) + ' 版）' +
        '<div class="dg-dim">' + esc(c.by) + '　' + esc(c.at) + '　核准 ' + esc((c.approvals || []).length) + '／' + esc(c.approvalsRequired) + '　可套用時間 ' + esc(c.effectiveAt) +
        (c.ready ? '　<span class="dg-live">可套用</span>' : '') + '</div>' + (c.reason ? '<div class="dg-dim">' + esc(c.reason) + '</div>' : '') + '<div>' + btns + '</div></div></div>'
    }).join('')
  }

  async function loadPending() {
    var r = await call('GET', '/api/def-pipeline/pending')
    if (!st) return
    if (r.ok) { st.pipe = true; st.pending = (r.data && r.data.items) || [] } else if (r.status === 404) { st.pipe = false; st.pending = null }
    else { st.err = (r.data && r.data.detail) || ('讀取失敗（' + r.status + '）') }
  }
  async function pipeAct(verb, id) {
    st.pconfirm = ''
    setBusy(true)
    var r = await call('POST', '/api/def-pipeline/changes/' + enc(id) + '/' + verb, {})
    setBusy(false)
    if (!st) return                                  // 等待期間面板已被關掉
    if (r.ok) { st.err = ''; setState('pipeline-' + verb) } else {
      var d = r.data || {}
      st.err = (d.detail || (VERBS[verb] + '失敗（' + r.status + '）')) + (Array.isArray(d.problems) && d.problems.length ? '：' + d.problems.map(function (x) { return x.message }).join('；') : '')
      setState('error')
    }
    await loadPending()
  }

  function renderImpact() {
    var I = st.impact
    if (!I) return '<div class="dg-dim">讀取中…</div>'
    if (!I.hasDraft) return '<div class="dg-dim">目前沒有草稿，沒有要發布的內容。</div>'
    var h = '<div>將從第 ' + esc(I.liveVersion == null ? '—' : I.liveVersion) + ' 版發布為第 ' + esc(I.nextVersion) + ' 版，共 ' + esc(I.changeCount) + ' 處變更。</div>'
    h += I.validation.ok ? '<div class="dg-live">驗證通過</div>' : '<div class="dg-bad">驗證不通過（' + I.validation.problems.length + ' 個問題），發布會被拒絕：' +
      I.validation.problems.map(function (x) { return '<div>' + esc((x.path ? x.path + '：' : '') + x.message) + '</div>' }).join('') + '</div>'
    h += '<h4>會影響哪裡</h4><div>' + esc(I.declared.screens) + (I.declared.customerVisible ? '（客戶看得到的輸出）' : '') + '</div>'
    if (I.otherScopes.length) h += '<div class="dg-dim">同一份定義另有：' + I.otherScopes.map(function (s) { return esc(s.scope) + ' 第 ' + esc(s.latestVersion) + ' 版' }).join('、') +
      (I.declared.roleOverridesPresent ? '。這些角色若有自己的版本，看到的不一定會跟著改。' : '') + '</div>'
    if (I.frozenRecords != null) h += '<div>目前有 <b>' + esc(I.frozenRecords) + '</b> 張單據凍結在生效中的第 ' + esc(I.liveVersion) + ' 版，發布新版後它們仍用舊版。</div>'
    h += '<div class="dg-dim">' + esc(I.note) + '</div>'
    h += '<h4>變更內容</h4>' + (I.changes.length ? I.changes.map(changeLine).join('') : '<div class="dg-dim">沒有差異。</div>')
    return h
  }

  async function loadLedger() {
    setBusy(true)
    var r = await call('GET', base(st.o, '/ledger'))
    setBusy(false)
    if (!st) return                                  // 等待期間面板已被關掉
    if (r.ok) { st.ledger = r.data; st.err = '' } else { st.err = (r.data && r.data.detail) || ('讀取失敗（' + r.status + '）'); setState('error') }
  }
  async function loadImpact() {
    setBusy(true)
    var r = await call('GET', base(st.o, '/impact'))
    setBusy(false)
    if (!st) return                                  // 等待期間面板已被關掉
    if (r.ok) { st.impact = r.data; st.err = '' } else { st.err = (r.data && r.data.detail) || ('讀取失敗（' + r.status + '）'); setState('error') }
  }
  async function compare(v) {
    setBusy(true)
    var r = await call('GET', base(st.o, '/diff') + '&a=' + enc(v) + '&b=live')
    setBusy(false)
    if (!st) return                                  // 等待期間面板已被關掉
    if (r.ok) { st.diff = r.data; st.err = '' } else { st.err = (r.data && r.data.detail) || ('比較失敗（' + r.status + '）'); setState('error') }
  }
  async function restore(v) {
    st.confirming = ''                                  // 不用原生 confirm()（會擋住整頁事件）；畫面上兩段式確認，歷史不改、可再還原回來
    setBusy(true)
    var rb = { note: '還原第 ' + v + ' 版' }
    var rp = await call('GET', base(st.o, '/impact') + '&version=' + enc(v))             // T62：還原也要先看過『這一版』的預覽（伺服端在強制範圍內會檢查）；面板的確認就是看過的那一步
    if (rp.ok && rp.data && rp.data.previewHash) rb.preview_hash = rp.data.previewHash
    var r = await call('POST', '/api/definitions/' + enc(st.o.kind) + '/' + enc(st.o.key) + '/restore/' + enc(v) + '?scope=' + enc(st.o.scope || 'company'), rb)
    setBusy(false)
    if (!st) return                                  // 等待期間面板已被關掉
    if (r.ok) {
      st.err = ''; st.diff = null; setState('restored')
      if (typeof st.o.onRestored === 'function') { try { st.o.onRestored(r.data) } catch (e) { /* 編輯器自己的刷新失敗不影響帳本 */ } }
      await loadLedger()
    } else {
      var d = r.data || {}
      st.err = (d.detail || '還原失敗') + (Array.isArray(d.problems) && d.problems.length ? '：' + d.problems.map(function (x) { return x.message }).join('；') : '')
      setState('error')
    }
  }

  function close(result) {
    var p = document.getElementById('dg-panel')
    if (p) p.remove()
    var res = st && st.o._resolve
    st = null
    if (res) res(typeof result === 'string' ? result : null)      // 審閱模式：關掉＝取消（null）；確認＝草稿戳
  }

  async function onClick(ev) {
    var t = ev.target.closest && ev.target.closest('[data-dg]')
    if (!t || !st) return
    var a = t.getAttribute('data-dg')
    if (a === 'close' || a === 'review-cancel') return close()
    if (a === 'review-ok') {
      var I = st.impact
      if (I && I.hasDraft && I.validation && I.validation.ok && I.previewHash) return close(I.previewHash)
      return
    }
    if (a.indexOf('tab:') === 0) {
      st.tab = a.slice(4); render()
      if (st.tab === 'impact') { await loadImpact() } else if (st.tab === 'pending') { await loadPending() } else { await loadLedger() }
      return render()
    }
    if (a.indexOf('pact:') === 0) { st.pconfirm = a.slice(5); return render() }
    if (a === 'pact-no') { st.pconfirm = ''; return render() }
    if (a.indexOf('pact-yes:') === 0) { var pp = a.slice(9).split(':'); await pipeAct(pp[0], pp[1]); return render() }
    if (a.indexOf('cmp:') === 0) { await compare(a.slice(4)); return render() }
    if (a.indexOf('restore:') === 0) { st.confirming = a.slice(8); return render() }
    if (a === 'restore-no') { st.confirming = ''; return render() }
    if (a.indexOf('restore-yes:') === 0) { await restore(a.slice(12)); return render() }
  }

  window.MotrixDefGovernance = {
    async available(kind) {
      try {
        var r = await fetch('/api/def-governance/' + enc(kind || 'layout') + '/_probe/ledger?scope=company', { headers: hdr() })
        return r.status !== 404 && r.status !== 401 && r.status !== 403      // 旗標開：通過把關後 400/200 都算可用；關：404
      } catch (e) { return false }
    },
    async open(o) {
      if (!o || !o.kind || !o.key) return
      close()
      if (!document.getElementById('dg-style')) {
        var s = document.createElement('style'); s.id = 'dg-style'; s.textContent = CSS; document.head.appendChild(s)
      }
      var p = document.createElement('div')
      p.id = 'dg-panel'; p.setAttribute('role', 'dialog'); p.setAttribute('aria-label', '版本帳本與影響預覽'); p.setAttribute('data-busy', '0'); p.setAttribute('data-state', 'idle')
      p.addEventListener('click', onClick)
      document.body.appendChild(p)
      st = { o: o, tab: o.tab === 'impact' ? 'impact' : 'ledger', busy: false, confirming: '', pipe: false, pending: null, pconfirm: '', ledger: null, diff: null, impact: null, err: '' }
      render()
      if (st.tab === 'impact') await loadImpact()
      else await loadLedger()
      render()
      if (!o.review) { await loadPending(); render() }                       // 待核准分頁只在有後端、且不是『發布前審閱』時出現
    },
    review(o) {
      return new Promise(function (resolve) {
        window.MotrixDefGovernance.open(Object.assign({}, o, { tab: 'impact', readonly: true, review: true, _resolve: resolve }))
      })
    },
    async previewRestore(o, v) {                         // T62：⇒ 還原用的預覽雜湊（沒有治理／失敗 ⇒ null，編輯器照舊送出）
      var r = await call('GET', base(o, '/impact') + '&version=' + enc(v))
      return r.ok && r.data && r.data.previewHash ? r.data.previewHash : null
    },
    async preview(o) {
      var r = await call('GET', base(o, '/impact'))
      return { ok: r.ok, hash: r.ok ? r.data.previewHash : '', data: r.data }
    }
  }
})()
