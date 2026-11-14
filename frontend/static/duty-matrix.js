/* duty-matrix.js — 職責角色頁的「職責 × 權限」矩陣（T86；取代「角色編輯表單裡 30 顆權限 chip」）。
 *
 * 一張表：列＝權限（依群組）、欄＝職責角色；點格子＝加入草稿（頂端黏住儲存列）、欄頭＝整欄一次勾、群組列＝群組總開關、勾列後批次、
 * 篩選晶片＋搜尋。儲存＝先向伺服器要預覽（每個角色多／少哪些權限、影響幾位成員、要不要原因）→ 確認 → 套用 → 可「復原這一批」。
 * 鍵與值沒變：角色的 permissions 仍是同一份鍵清單；寫入是 POST /api/duty-roles/matrix/{preview,apply,undo}（後端 helpers/duty_role_matrix.py，
 * 內部逐角色走 duty_roles.update_role，原因規則與其他職責角色動作同一個檢查點）。
 *
 * 外框元件：static/settings-matrix.js（本檔只是把「角色×權限」轉成它的列／欄／草稿／儲存設定）。
 *
 * 用法：
 *   const dm = DutyMatrix.mount(document.getElementById('dm-box'), { onSaved: () => 外框重讀角色清單 })
 *   dm.reload()   // 角色清單在別處改過（新增角色、改名、停用）之後呼叫
 *   dm.destroy()
 *
 * 安全：角色名稱是使用者輸入的文字——一律經 SettingsMatrix 的跳脫（列名稱、chips 標籤、確認視窗裡自己拼的 html 都先 esc）。
 */
(function (root) {
  'use strict'
  var SM = root.SettingsMatrix
  var esc = function (s) { return SM.esc(s == null ? '' : s) }
  var ELIGIBLE = 'duty-roles'

  function hdr() {
    var s = {}
    try { s = JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) { s = {} }
    return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + (s.token || '') }
  }
  function call(method, url, body) {
    return fetch(url, { method: method, headers: hdr(), body: body === undefined ? undefined : JSON.stringify(body) }).then(function (r) {
      return r.json().catch(function () { return {} }).then(function (j) {
        if (!r.ok) {
          var e = new Error(typeof j.detail === 'string' ? j.detail : '操作失敗（' + r.status + '）')
          e.status = r.status
          throw e
        }
        return j
      })
    })
  }
  function cancelled() { var e = new Error('cancelled'); e.cancelled = true; return e }
  function rid(v) { return 'r' + v }                                    // chips 的項目值是字串（DOM attribute）：'r12'
  function ridNum(v) { return Number(String(v).slice(1)) }
  function uniq(a) { return a.filter(function (x, i) { return a.indexOf(x) === i }) }

  var registered = false
  function registerOnce() {
    if (registered) return
    registered = true
    SM.registerEligibleOverride(ELIGIBLE, function () { return true },
      '職責角色矩陣：高敏感權限也可以在矩陣裡調整（儲存前預覽、必填原因、伺服器共用檢查點、寫變更紀錄、可復原）；沒有「不能批次」的列')
  }

  function mount(box, opts) {
    opts = opts || {}
    registerOnce()
    var state = { roles: [], keys: [], high: [] }
    var rows = []
    var lastPlan = null, lastReason = ''
    var mx = null

    function finance(k) { return !!(state.keys.filter(function (x) { return x.key === k })[0] || {}).financeKey }
    function buildRows() {
      var byKey = {}
      state.roles.forEach(function (r) { (r.permissions || []).forEach(function (k) { (byKey[k] = byKey[k] || []).push(rid(r.id)) }) })
      var known = {}
      rows = state.keys.map(function (k) {
        known[k.key] = 1
        return { key: k.key, name: k.label, group: k.group || '其他', high: !!k.highSensitive, finance: !!k.financeKey, roles: (byKey[k.key] || []).slice() }
      })
      // 角色持有、但目前已不在登記表的舊鍵：照實列出（才能被取消），群組「已下架的權限」
      Object.keys(byKey).forEach(function (k) { if (!known[k]) rows.push({ key: k, name: k, group: '已下架的權限', high: false, finance: false, roles: byKey[k].slice(), legacy: true }) })
    }
    function roleItems() {
      return state.roles.map(function (r) {
        var nm = r.name + (r.active ? '' : '（停用）')
        return { value: rid(r.id), label: nm, short: nm.length > 6 ? nm.slice(0, 6) : nm }
      })
    }
    function groupOrder() {
      var g = uniq(state.keys.map(function (k) { return k.group || '其他' }))
      if (rows.some(function (r) { return r.legacy })) g.push('已下架的權限')
      return g
    }
    function roleName(v) { var r = state.roles.filter(function (x) { return rid(x.id) === v })[0]; return r ? r.name : v }
    function keyName(k) { var r = rows.filter(function (x) { return x.key === k })[0]; return r ? r.name : k }

    // 目前顯示的角色清單＝草稿（核心的 state().draft）優先，否則伺服器原值；批次動作要在既有勾選上疊加
    function curRoles(r) { var d = mx && mx.state().draft[r.key]; return ((d && d.roles) || r.roles || []).slice() }
    function setRoles(r, arr) { return { roles: arr } }
    function applyPatch(raw, patch) { var o = Object.assign({}, raw); if ('roles' in patch) o.roles = patch.roles.slice(); return o }
    function canon(arr) { return JSON.stringify((arr || []).slice().sort()) }
    function sameAsRaw(raw, patch) { return canon(applyPatch(raw, patch).roles) === canon(raw.roles) }
    function allRoleIds() { return state.roles.map(function (r) { return rid(r.id) }) }

    // ── 欄：每個角色一欄（chips 欄的每個項目就是一個表格欄） ──
    var columns = [{
      id: 'roles', type: 'chips', label: '職責角色', items: [], tone: function () { return 'a' },
      get: function (r) { return r.roles || [] },
      draft: function (r, val, on) {
        var cur = curRoles(r)
        var next = on ? (cur.indexOf(val) >= 0 ? cur : cur.concat([val])) : cur.filter(function (x) { return x !== val })
        return setRoles(r, next)
      },
      colSelect: {
        draft: function (r, on, val) {
          var cur = curRoles(r)
          if ((cur.indexOf(val) >= 0) === !!on) return null
          return setRoles(r, on ? cur.concat([val]) : cur.filter(function (x) { return x !== val }))
        },
      },
    }]

    // ── 批次（勾列後）：全部角色全給／全收、指定角色…（只改草稿）──
    function stageEach(keys, fn) {
      keys.forEach(function (k) {
        var r = rows.filter(function (x) { return x.key === k })[0]
        if (!r) return
        var next = fn(curRoles(r))
        if (next) mx.stage(k, setRoles(r, next))
      })
    }
    function pickRolesDialog(n) {
      var st = { mode: 'grant', roles: [] }
      var html = '<div><b>對選取的 ' + n + ' 項權限</b></div>' +
        '<label style="display:block;margin:4px 0"><input type="radio" name="dm-mode" value="grant" checked data-testid="dm-pick-grant"> 授予下列角色</label>' +
        '<label style="display:block;margin:4px 0"><input type="radio" name="dm-mode" value="revoke" data-testid="dm-pick-revoke"> 取消下列角色</label>' +
        '<div style="margin-top:8px"><b>角色</b></div><div style="display:flex;flex-wrap:wrap;gap:6px 14px">' +
        state.roles.map(function (r) { return '<label><input type="checkbox" data-role="' + esc(rid(r.id)) + '" data-testid="dm-pick-role-' + esc(r.id) + '"> ' + esc(r.name) + (r.active ? '' : '（停用）') + '</label>' }).join('') + '</div>' +
        '<div class="mx-mute" style="margin-top:8px">這裡只會加進草稿；按頂端的「儲存」才會預覽並寫入。</div>'
      return SM.openDialog({
        title: '指定角色', html: html,
        buttons: [{ label: '取消', value: null }, { label: '加入草稿', value: 'ok', kind: 'primary' }],
        onOpen: function (body) {
          body.addEventListener('change', function (e) {
            var t = e.target
            if (t.name === 'dm-mode') st.mode = t.value
            else if (t.getAttribute('data-role')) { var v = t.getAttribute('data-role'); st.roles = st.roles.filter(function (x) { return x !== v }); if (t.checked) st.roles.push(v) }
          })
        },
      }).then(function (v) { return v === 'ok' && st.roles.length ? st : null })
    }
    var batchCfg = {
      groupActions: [{ action: 'all', label: '全部角色都有' }, { action: 'none', label: '全部取消' }],
      groupActionsEnabled: true,                                        // 群組總開關：也只是草稿，儲存時才預覽、確認
      actions: [
        { id: 'all', label: '全部角色都有', draft: function (keys) { stageEach(keys, function () { return allRoleIds() }); mx.clearSelection(); return null } },
        { id: 'none', label: '全部取消', draft: function (keys) { stageEach(keys, function () { return [] }); mx.clearSelection(); return null } },
        { id: 'some', label: '指定角色…', dividerBefore: true,
          draft: function (keys) {
            return pickRolesDialog(keys.length).then(function (p) {
              if (!p) return null
              stageEach(keys, function (cur) { return p.mode === 'grant' ? uniq(cur.concat(p.roles)) : cur.filter(function (x) { return p.roles.indexOf(x) < 0 }) })
              mx.clearSelection()
              mx.toast('已加入草稿（' + keys.length + ' 項權限）')
              return null
            })
          } },
      ],
      snapshot: function (keys) {
        var o = {}
        keys.forEach(function (k) { var r = rows.filter(function (x) { return x.key === k })[0]; if (r) o[k] = r.roles.slice() })
        return o
      },
      restore: function (snap, res) { return undoLast(res) },
    }
    var filters = [
      { id: 'high', label: '高敏感', title: '變更時必須填寫原因', test: function (r) { return r.high } },
      { id: 'fin', label: '財務三鍵', test: function (r) { return r.finance } },
      { id: 'none', label: '沒有任何角色持有', test: function (r) { return !(r.roles || []).length } },
      { id: 'all', label: '所有角色都持有', test: function (r) { return state.roles.length > 0 && state.roles.every(function (x) { return (r.roles || []).indexOf(rid(x.id)) >= 0 }) } },
    ]

    // ── 草稿 → 後端請求 ──
    function requestOf(list) {
      var per = {}
      list.forEach(function (c) {
        var oldA = (c.row && c.row.roles) || [], newA = c.patch.roles || []
        newA.forEach(function (v) { if (oldA.indexOf(v) < 0) (per[v] = per[v] || { roleId: ridNum(v), grant: [], revoke: [] }).grant.push(c.key) })
        oldA.forEach(function (v) { if (newA.indexOf(v) < 0) (per[v] = per[v] || { roleId: ridNum(v), grant: [], revoke: [] }).revoke.push(c.key) })
      })
      return Object.keys(per).map(function (v) { return per[v] })
    }
    function labelList(keys) { return keys.map(function (k) { return '<span class="dm-k">' + esc(keyName(k)) + '</span>' }).join('、') }
    function planHtml(plan) {
      var s = plan.summary
      var html = '<div data-testid="dm-plan-summary">將調整 <b>' + s.changed + '</b> 個角色：多 <b>' + s.cellsAdded + '</b> 格、少 <b>' + s.cellsRemoved + '</b> 格' +
        (s.membersAffected ? '，影響 <b>' + s.membersAffected + '</b> 位成員（成員的實際權限會跟著變）' : '') + '。' +
        (s.unchanged ? '另有 ' + s.unchanged + ' 個角色本來就是這樣（略過）。' : '') + '</div>'
      plan.roles.forEach(function (p) {
        html += '<div style="border-top:1px solid var(--border-light,#e5e7eb);padding:8px 0;font-size:13px" data-testid="dm-plan-role-' + esc(p.roleId) + '"><b>' + esc(p.name || ('#' + p.roleId)) + '</b>' +
          (p.status === 'change' ? ' <span class="mx-mute">（' + p.members + ' 位成員' + (p.memberNames.length ? '：' + esc(p.memberNames.join('、')) + (p.members > p.memberNames.length ? ' 等' : '') : '') + '）</span>' : '')
        if (p.status === 'skipped') html += '<div class="mx-mute">略過：' + esc(p.note) + '</div>'
        if (p.status === 'nochange') html += '<div class="mx-mute">沒有需要變更的項目</div>'
        if (p.adds.length) html += '<div style="color:#047857">多了：' + labelList(p.adds) + '</div>'
        if (p.removes.length) html += '<div style="color:#B91C1C">少了：' + labelList(p.removes) + '</div>'
        p.notes.forEach(function (n) { html += '<div class="mx-mute">' + esc(n) + '</div>' })
        html += '</div>'
      })
      return html
    }
    // 確認視窗自己開（要收「變更原因」；核心的確認視窗沒有輸入框）：取消 ⇒ 靜默放棄（回 null）；確認 ⇒ 回 []（不再接其他視窗），原因記在 lastReason
    function confirmSave(list) {
      var changes = requestOf(list)
      if (!changes.length) throw new Error('這些修改和目前的設定一樣，沒有要儲存的')
      return call('POST', '/api/duty-roles/matrix/preview', { changes: changes }).then(function (plan) {
        if (!plan.summary.changed) throw new Error('這些修改和目前的設定一樣，沒有要儲存的')
        lastPlan = plan
        var html = planHtml(plan)
        if (plan.needsReason) {
          html += '<div style="margin-top:10px"><div style="font-size:12px;font-weight:600;margin-bottom:4px">變更原因（這次動到高敏感權限：' + esc(plan.gatedKeys.map(keyName).join('、')) + '，必填；至少 4 個不同的字）</div>' +
            '<input type="text" maxlength="200" style="width:100%;box-sizing:border-box;padding:6px 8px" value="' + esc(lastReason) + '" data-testid="dm-reason"></div>'
        } else {
          html += '<div style="margin-top:10px"><div style="font-size:12px;margin-bottom:4px">變更原因（選填）</div>' +
            '<input type="text" maxlength="200" style="width:100%;box-sizing:border-box;padding:6px 8px" value="' + esc(lastReason) + '" data-testid="dm-reason"></div>'
        }
        html += '<div class="mx-mute" style="margin-top:8px">儲存後會留下不可修改的變更紀錄，並可按「復原這一批」（被其他人改過的角色不會被復原）。</div>'
        return SM.openDialog({
          title: '儲存 ' + plan.summary.changed + ' 個角色的權限調整', html: html,
          buttons: [{ label: '取消', value: null }, { label: '套用', value: 'ok', kind: plan.gatedKeys.length ? 'danger' : 'primary' }],
          onOpen: function (body) {
            var inp = body.querySelector('[data-testid=dm-reason]')
            if (inp) inp.addEventListener('input', function () { lastReason = inp.value })
          },
        }).then(function (v) { return v === 'ok' ? [] : null })
      })
    }
    function save(list) {
      if (!lastPlan) return Promise.reject(new Error('請先預覽再儲存'))
      return call('POST', '/api/duty-roles/matrix/apply', { changes: requestOf(list), reason: lastReason, planHash: lastPlan.planHash }).then(function (res) {
        lastReason = ''
        return { res: res, message: '已儲存（' + res.applied.length + ' 個角色有變動）' }
      })
    }
    function undoLast(done) {
      var r = done && done.res
      if (!r || !r.roles) return Promise.reject(new Error('找不到這一批的套用紀錄，無法復原'))
      var changes = r.roles.filter(function (p) { return p.status === 'change' }).map(function (p) { return { roleId: p.roleId, adds: p.adds, removes: p.removes } })
      return call('POST', '/api/duty-roles/matrix/undo', { changes: changes, reason: '' }).then(function (u) {
        if (u.conflicts && u.conflicts.length) {
          var why = u.conflicts.map(function (c) { return (c.name || ('#' + c.roleId)) + '：' + c.reason }).join('；')
          if (!u.applied.length) throw new Error('無法復原：' + why + '（為了不覆蓋其他使用者的修改，這些角色沒有動）')
          mx.toast('已復原 ' + u.applied.length + ' 個角色；未復原：' + why)
        }
        return u
      })
    }

    function load() {
      return call('GET', '/api/duty-roles').then(function (a) {
        state.roles = a.roles || []
        state.keys = a.keys || []
        state.high = a.highSensitiveKeys || []
        buildRows()
        columns[0].items = roleItems()
        return rows
      })
    }
    function reload() { return load().then(function () { if (mx) { mx.setRows(rows); mx.render() } }) }

    function start() {
      return load().then(function () {
        mx = SM.mount(box, {
          rows: rows, groups: groupOrder(), eligible: ELIGIBLE,
          draft: { apply: applyPatch, same: sameAsRaw, confirm: confirmSave, save: save, afterSave: function (res) { if (opts.onSaved) opts.onSaved(res) } },
          rowKey: function (r) { return r.key }, rowName: function (r) { return r.name }, rowGroup: function (r) { return r.group }, rowSub: function (r) { return r.key },
          nameLabel: '權限', searchPlaceholder: '搜尋權限名稱或代碼',
          rowTags: function (r) {
            var t = []
            if (r.high) t.push({ text: '高敏感', tone: 'crit' })
            if (r.finance) t.push({ text: '財務三鍵', tone: 'warn' })
            if (r.legacy) t.push({ text: '已下架', tone: 'mute' })
            return t
          },
          searchText: function (r) { return r.name + ' ' + r.key + ' ' + r.group },
          groupSummary: function (g, all) { return '共 ' + all.length + ' 項・有角色持有 ' + all.filter(function (r) { return (r.roles || []).length }).length + ' 項' },
          columns: columns, filters: filters, batch: batchCfg,
          reload: function () { return load() },
          onError: function (e) { if (opts.onError) opts.onError(e) },
        })
        return api()
      })
    }
    function api() { return { reload: reload, destroy: function () { if (mx) mx.destroy() }, mx: function () { return mx }, rows: function () { return rows } } }
    return start()
  }

  root.DutyMatrix = { mount: mount }
})(window)
