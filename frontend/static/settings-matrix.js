/* settings-matrix.js — 共用「矩陣設定表」元件（2026-11-13，LINE 事件矩陣票；LINE 事件頁是第一個使用者）。
 *
 * 一張表看完全部設定、點格子就切換、勾選多列一次套用、動作可以復原。不依賴 Alpine／任何函式庫；資料與寫入都由頁面（host）提供。
 * 樣式在 ../css/settings-matrix.css（用 style.css 的色彩變數，深色模式跟著走）。
 *
 * ── 用法 ──────────────────────────────────────────────────────────────────────────────────────────────────────
 *   const mx = SettingsMatrix.mount(document.getElementById('box'), {
 *     rows: [...], groups: ['群組甲', '群組乙'],               // groups＝顯示順序；沒對到的列放最後的「其他」
 *     rowKey: r => r.key, rowName: r => r.name, rowGroup: r => r.group,
 *     rowSub:  r => r.key,                                      // 名稱下面的小字（選填）
 *     rowTags: r => [{ text: '重要', tone: 'crit' }],           // 名稱旁的標籤；tone：good｜warn｜bad｜info｜crit｜mute
 *     columns: [                                                // 型別見下方
 *       { id: 'on',   type: 'switch', label: '開／關', get: r => r.enabled, set: (r, v) => api(...) },
 *       { id: 'mode', type: 'select', label: '對象', options: [{ value: 'a', label: 'A' }], get: r => r.mode, set: (r, v) => api(...), show: r => r.enabled },
 *       { id: 'roles', type: 'chips', label: '角色', items: [{ value: 'admin', label: '管理員', short: '管理' }],
 *         get: r => r.roles, toggle: (r, value, on) => api(...), tone: r => 'a' /* 'a'＝指定（綠）、'f'＝篩選（灰藍） *\/, show: r => r.enabled },
 *       { id: 'who', type: 'html', label: '人員', render: r => '<b>…</b>', show: r => r.enabled, cardHide: false },
 *     ],
 *     filters: [{ id: 'on', label: '已開啟', test: r => r.enabled }],           // 篩選晶片（「全部」內建）
 *     searchText: r => r.name + ' ' + r.key,                                      // 搜尋比對的文字
 *     groupSummary: (name, rows) => '已開 3／共 8',                              // 群組列的說明（選填）
 *     batch: {
 *       actions: [{ id: 'off', label: '關閉', run: (keys, ctx) => api(...),      // ctx.confirmed＝使用者勾過的確認（見 confirm）
 *                   confirm: keys => [{ title, html, okLabel, danger }] }],         // 回 0 個以上確認視窗；全部按「套用」才會執行
 *       groupActions: [{ action: 'on', label: '全開' }, { action: 'off', label: '全關' }],   // 群組列的快捷鈕（對群組內「目前列出的」列）
 *       snapshot: keys => ({...}),            // 套用前記下目前的狀態（復原用；格式自訂）
 *       restore: (snap, res) => Promise,      // 復原這一批：res＝該批 run() 的回傳；有人在這之間改過 ⇒ 丟帶說明的 Error（整批不復原）。單格操作沒有復原
 *     },
 *     reload: () => Promise<rows>,            // 每次寫入完成後重讀資料
 *     // 欄位另有 confirm: (row, newValue) => [{ title, html, okLabel, danger }]（單格操作前先確認）；set／toggle 丟 { cancelled: true } ⇒ 靜默放棄
 *     // html 欄位裡的按鈕寫 data-mx="act" data-act="動作代號" data-key="列代碼"，點了呼叫 onAction(動作代號, 列, api)
 *     onAction: (act, row, api) => {},
 *     onError: err => {},                     // 選填；預設用 toast 顯示 err.message
 *   })
 *   mx.setRows(rows)  mx.refresh()  mx.selection()  mx.clearSelection()  mx.toast(msg, { undo })
 *   SettingsMatrix.openDialog({ title, html, buttons: [{ label, value, kind: 'primary'|'danger'|'' }], onOpen(el) }) → Promise<value|null>
 *
 * ── 行為（所有套用這個元件的設定頁一致）──
 *   · 單格切換：立刻寫入、提示「已更新」（沒有復原，要還原請再改一次）；失敗顯示原因、畫面回到伺服器的狀態
 *   · 批次：勾選列（群組方塊＝整組、Shift 連選）→ 底部批次列 → 確認視窗 → 套用 → 「復原這一批」（提示停留 6 秒；能不能復原看版本，不看時間）
 *   · 搜尋＋篩選晶片＋群組下拉；搜尋時自動展開有結果的群組
 *   · ≤ 900px 自動變成「依群組的卡片」，資料與操作完全相同
 *   · 寫入進行中整張表鎖住（避免連點）
 */
(function (global) {
  'use strict'

  var TONES = { good: 'mx-pill-good', warn: 'mx-pill-warn', bad: 'mx-pill-bad', info: 'mx-pill-info', crit: 'mx-pill-crit', mute: '' }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] })
  }

  // ── 彈窗（供 host 自己的對話框與元件內建的確認視窗共用）──────────────────────────────────────────
  var _layer = null
  function openDialog(opts) {
    return new Promise(function (resolve) {
      closeDialog(null)
      var wrap = document.createElement('div')
      wrap.className = 'mx-modal'
      var btns = (opts.buttons || [{ label: '關閉', value: null }]).map(function (b, i) {
        return '<button type="button" class="mx-btn ' + (b.kind === 'primary' ? 'mx-btn-primary' : b.kind === 'danger' ? 'mx-btn-danger' : '') + '" data-mx-dlg="' + i + '"' + (b.disabled ? ' disabled' : '') + '>' + esc(b.label) + '</button>'
      }).join('')
      wrap.innerHTML = '<div class="mx-dlg" role="dialog" aria-modal="true" aria-label="' + esc(opts.title || '') + '"><h3>' + esc(opts.title || '') + '</h3>' +
        '<div class="mx-dlg-body">' + (opts.html || '') + '</div><div class="mx-dlg-actions">' + btns + '</div></div>'
      document.body.appendChild(wrap)
      _layer = { el: wrap, resolve: resolve, buttons: opts.buttons || [{ label: '關閉', value: null }] }
      wrap.addEventListener('click', function (e) {
        if (e.target === wrap) return closeDialog(null)
        var b = e.target.closest('[data-mx-dlg]')
        if (b && !b.disabled) closeDialog(_layer.buttons[+b.getAttribute('data-mx-dlg')].value)
      })
      var first = wrap.querySelector('.mx-btn-primary, .mx-btn-danger, .mx-btn')
      if (opts.onOpen) opts.onOpen(wrap.querySelector('.mx-dlg-body'), wrap)
      if (first) try { first.focus() } catch (e) { /* ignore */ }
    })
  }
  function closeDialog(value) {
    if (!_layer) return
    var l = _layer
    _layer = null
    if (l.el.parentNode) l.el.parentNode.removeChild(l.el)
    l.resolve(value === undefined ? null : value)
  }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && _layer) closeDialog(null) })

  // ── 提示（可帶「復原」）──────────────────────────────────────────────────────────────────────────────
  function toast(msg, opts) {
    opts = opts || {}
    var t = document.createElement('div')
    t.className = 'mx-toast' + (opts.error ? ' mx-toast-error' : '')
    t.setAttribute('role', opts.error ? 'alert' : 'status')
    t.innerHTML = '<span data-testid="mx-toast-text">' + esc(msg) + '</span>' + (opts.undo ? '<button type="button" data-testid="mx-undo">復原這一批</button>' : '')
    var timer = null
    function gone() { clearTimeout(timer); if (t.parentNode) t.parentNode.removeChild(t) }
    if (opts.undo) t.querySelector('button').onclick = function () { gone(); opts.undo() }
    document.body.appendChild(t)
    timer = setTimeout(gone, opts.error ? 9000 : 6500)
    return gone
  }

  // ── 主元件 ───────────────────────────────────────────────────────────────────────────────────────────
  function mount(el, cfg) {
    var S = { rows: cfg.rows || [], q: '', f: 'all', g: '', collapsed: {}, sel: {}, last: null, shift: false, busy: false }
    var rk = cfg.rowKey || function (r) { return r.key }
    var rn = cfg.rowName || function (r) { return r.name }
    var rg = cfg.rowGroup || function (r) { return r.group }
    var cols = cfg.columns || []
    var filters = cfg.filters || []
    var batch = cfg.batch || { actions: [] }
    var groups = (cfg.groups || []).slice()

    function groupOrder() {
      var seen = {}
      var out = groups.filter(function (g) { seen[g] = 1; return S.rows.some(function (r) { return rg(r) === g }) })
      S.rows.forEach(function (r) { var g = rg(r) || '其他'; if (!seen[g]) { seen[g] = 1; out.push(g) } })
      return out
    }
    function visible(r) {
      if (S.g && (rg(r) || '其他') !== S.g) return false
      if (S.f !== 'all') {
        var f = filters.filter(function (x) { return x.id === S.f })[0]
        if (f && !f.test(r)) return false
      }
      if (S.q) {
        var hay = (cfg.searchText ? cfg.searchText(r) : rn(r) + ' ' + rk(r)).toLowerCase()
        if (hay.indexOf(S.q.toLowerCase()) < 0) return false
      }
      return true
    }
    function view() {
      return groupOrder().map(function (g) {
        var all = S.rows.filter(function (r) { return (rg(r) || '其他') === g })
        return { g: g, all: all, rows: all.filter(visible) }
      }).filter(function (x) { return x.rows.length })
    }
    function isClosed(g) { return S.collapsed[g] && !S.q }
    function visKeys() {
      var o = []
      view().forEach(function (x) { if (!isClosed(x.g)) x.rows.forEach(function (r) { o.push(rk(r)) }) })
      return o
    }
    function rowByKey(k) { return S.rows.filter(function (r) { return rk(r) === k })[0] }
    function selKeys() { return Object.keys(S.sel).filter(function (k) { return S.sel[k] && rowByKey(k) }) }
    function colShown(c, r) { return c.show ? !!c.show(r) : true }

    // ── 渲染 ──
    function tags(r) {
      return (cfg.rowTags ? cfg.rowTags(r) : []).map(function (t) { return ' <span class="mx-pill ' + (TONES[t.tone] || '') + '">' + esc(t.text) + '</span>' }).join('')
    }
    function nameCell(r) {
      return '<span class="mx-nm">' + esc(rn(r)) + '</span>' + tags(r) + (cfg.rowSub ? '<div class="mx-sub">' + esc(cfg.rowSub(r)) + '</div>' : '')
    }
    function cell(c, r, k) {
      var attrs = ' data-col="' + esc(c.id) + '" data-key="' + esc(k) + '"'
      if (!colShown(c, r)) return c.type === 'switch' ? '' : '<span class="mx-dash">—</span>'
      if (c.type === 'switch') {
        var on = !!c.get(r)
        return '<button type="button" class="mx-sw" role="switch" data-mx="switch"' + attrs + ' aria-checked="' + on + '" aria-label="' + esc(rn(r) + '：' + (c.label || '開關')) + '"></button>'
      }
      if (c.type === 'select') {
        var v = c.get(r)
        return '<select class="mx-select" data-mx="select"' + attrs + ' aria-label="' + esc(rn(r) + '：' + (c.label || '')) + '">' + c.options.map(function (o) {
          return '<option value="' + esc(o.value) + '"' + (String(o.value) === String(v) ? ' selected' : '') + '>' + esc(o.label) + '</option>'
        }).join('') + '</select>'
      }
      if (c.type === 'html') return c.render(r)
      return esc(c.get ? c.get(r) : '')
    }
    function chipCell(c, r, k, it, asChip) {
      if (!colShown(c, r)) return asChip ? '' : ''
      var cur = c.get(r)
      var on = cur == null ? true : cur.indexOf(it.value) >= 0                       // null＝所有項目都亮（不篩選）
      var tone = c.tone ? c.tone(r) : 'a'
      var dis = c.disabled ? c.disabled(r) : false
      var cls = (asChip ? 'mx-chip' : 'mx-rc') + (on ? ' on ' + tone : '') + (dis ? ' dis' : '')
      return '<button type="button" class="' + cls + '" data-mx="chip" data-col="' + esc(c.id) + '" data-key="' + esc(k) + '" data-val="' + esc(it.value) + '" aria-pressed="' + on + '" aria-label="' +
        esc(rn(r) + '：' + it.label + (on ? '（是）' : '（否）')) + '"' + (dis ? ' disabled' : '') + '>' + (asChip ? esc(it.label) : '✓') + '</button>'
    }
    function headCells() {
      var h = ''
      cols.forEach(function (c) {
        if (c.type === 'chips') c.items.forEach(function (it) { h += '<th class="mx-th-chip" title="' + esc(it.label) + '">' + esc(it.short || it.label) + '</th>' })
        else h += '<th' + (c.width ? ' style="width:' + c.width + 'px"' : '') + '>' + esc(c.label || '') + '</th>'
      })
      return h
    }
    function rowTable(r) {
      var k = rk(r), tds = ''
      cols.forEach(function (c) {
        if (c.type === 'chips') c.items.forEach(function (it) { tds += '<td>' + chipCell(c, r, k, it, false) + '</td>' })
        else tds += '<td>' + cell(c, r, k) + '</td>'
      })
      return '<tr class="mx-row' + (S.sel[k] ? ' sel' : '') + '" data-testid="mx-row-' + esc(k) + '"><td class="mx-ck"><input type="checkbox" data-mx="sel" data-key="' + esc(k) + '"' + (S.sel[k] ? ' checked' : '') +
        ' aria-label="選取 ' + esc(rn(r)) + '"></td><td class="mx-name">' + nameCell(r) + '</td>' + tds + '</tr>'
    }
    function rowCard(r) {
      var k = rk(r), sw = '', body = ''
      cols.forEach(function (c) {
        if (c.cardHide) return
        if (c.type === 'switch') { sw = cell(c, r, k); return }
        if (!colShown(c, r)) return
        if (c.type === 'chips') body += '<div class="mx-chips">' + c.items.map(function (it) { return chipCell(c, r, k, it, true) }).join('') + '</div>'
        else body += '<div class="mx-crow">' + cell(c, r, k) + '</div>'
      })
      return '<div class="mx-card-row' + (S.sel[k] ? ' sel' : '') + '"><div class="mx-card-top"><input type="checkbox" data-mx="sel" data-key="' + esc(k) + '"' + (S.sel[k] ? ' checked' : '') +
        ' aria-label="選取 ' + esc(rn(r)) + '"><div class="mx-card-name">' + nameCell(r) + '</div>' + sw + '</div>' + body + '</div>'
    }
    function groupHead(x, asCard) {
      var closed = isClosed(x.g)
      var allsel = x.rows.every(function (r) { return S.sel[rk(r)] })
      var sum = cfg.groupSummary ? cfg.groupSummary(x.g, x.all, x.rows) : ''
      var acts = (batch.groupActions || []).map(function (a) {
        return '<button type="button" class="mx-btn mx-btn-sm" data-mx="gact" data-act="' + esc(a.action) + '" data-g="' + esc(x.g) + '">' + esc(a.label) + '</button>'
      }).join(' ')
      var ck = '<input type="checkbox" data-mx="gsel" data-g="' + esc(x.g) + '"' + (allsel ? ' checked' : '') + ' aria-label="選取「' + esc(x.g) + '」全部列出的列">'
      if (asCard) return '<div class="mx-ghead" data-mx="gtoggle" data-g="' + esc(x.g) + '">' + ck + '<span class="mx-gname">' + (closed ? '▸ ' : '▾ ') + esc(x.g) + ' <span class="mx-mute">' + esc(sum) + '</span></span>' + acts + '</div>'
      var span = 1
      cols.forEach(function (c) { span += c.type === 'chips' ? c.items.length : 1 })
      return '<tr class="mx-grp" data-mx="gtoggle" data-g="' + esc(x.g) + '"><td class="mx-ck">' + ck + '</td><td class="mx-gname">' + (closed ? '▸ ' : '▾ ') + esc(x.g) +
        ' <span class="mx-mute">' + esc(sum) + '</span></td><td colspan="' + (span - 1) + '" class="mx-gacts">' + acts + '</td></tr>'
    }
    function render() {
      var v = view()
      var chipF = '<button type="button" class="mx-fchip" data-mx="filter" data-f="all" aria-pressed="' + (S.f === 'all') + '">全部</button>' + filters.map(function (f) {
        return '<button type="button" class="mx-fchip" data-mx="filter" data-f="' + esc(f.id) + '" aria-pressed="' + (S.f === f.id) + '"' + (f.title ? ' title="' + esc(f.title) + '"' : '') + '>' + esc(f.label) + '</button>'
      }).join('')
      var gsel = '<select class="mx-select" data-mx="gsel-filter" aria-label="只看某個群組"><option value="">全部群組</option>' + groupOrder().map(function (g) {
        return '<option' + (S.g === g ? ' selected' : '') + '>' + esc(g) + '</option>'
      }).join('') + '</select>'
      var tb = '<div class="mx-toolbar"><input type="search" class="mx-search" data-mx="search" placeholder="' + esc(cfg.searchPlaceholder || '搜尋') + '" value="' + esc(S.q) + '" aria-label="搜尋">' + chipF + gsel +
        '<button type="button" class="mx-btn" data-mx="expand">展開全部</button><button type="button" class="mx-btn" data-mx="collapse">收合全部</button></div>'
      var table = '<div class="mx-wrap"><table class="mx-table"><thead><tr><th class="mx-ck"><input type="checkbox" data-mx="selall" aria-label="全選目前列出的列"></th><th class="mx-name">' + esc(cfg.nameLabel || '項目') + '</th>' + headCells() + '</tr></thead><tbody>'
      var cards = '<div class="mx-cards">'
      if (!v.length) { table += '<tr><td colspan="40" class="mx-empty">沒有符合條件的項目</td></tr>'; cards += '<div class="mx-empty">沒有符合條件的項目</div>' }
      v.forEach(function (x) {
        table += groupHead(x, false)
        cards += '<div class="mx-gcard">' + groupHead(x, true)
        if (!isClosed(x.g)) x.rows.forEach(function (r) { table += rowTable(r); cards += rowCard(r) })
        cards += '</div>'
      })
      table += '</tbody></table></div>'
      cards += '</div>'
      var n = selKeys().length
      var bar = '<div class="mx-batch' + (n ? '' : ' mx-hide') + '" role="toolbar" aria-label="批次操作" data-testid="mx-batch"><b data-testid="mx-batch-count">已選 ' + n + ' 項</b>' +
        (batch.actions || []).map(function (a) {
          return (a.dividerBefore ? '<span class="mx-sep"></span>' : '') + (a.caption ? '<span class="mx-cap">' + esc(a.caption) + '</span>' : '') +
            '<button type="button" class="mx-btn" data-mx="bact" data-act="' + esc(a.id) + '" data-testid="mx-batch-' + esc(a.id) + '">' + esc(a.label) + '</button>'
        }).join('') + '<span class="mx-sep"></span><button type="button" class="mx-btn" data-mx="bclear" data-testid="mx-batch-clear">取消選取</button></div>'
      el.classList.add('mx-root')
      el.classList.toggle('mx-busy', S.busy)
      // 保留搜尋框的游標：只有在搜尋框有焦點時才還原
      var focusSearch = document.activeElement && document.activeElement.getAttribute && document.activeElement.getAttribute('data-mx') === 'search'
      var pos = focusSearch ? document.activeElement.selectionStart : 0
      el.innerHTML = tb + table + cards + bar
      if (focusSearch) { var inp = el.querySelector('[data-mx=search]'); inp.focus(); try { inp.setSelectionRange(pos, pos) } catch (e) { /* ignore */ } }
      var sa = el.querySelector('[data-mx=selall]')
      if (sa) { var ks = visKeys(); sa.checked = ks.length > 0 && ks.every(function (k) { return S.sel[k] }) }
    }

    // ── 寫入（單格／批次共用）：鎖住 → 寫 → 重讀 → 提示＋復原；失敗 ⇒ 顯示原因並回到伺服器的狀態 ──
    function fail(e) {
      if (cfg.onError) cfg.onError(e)
      else toast((e && e.message) || '失敗', { error: true })
    }
    function reloadAfter() {
      return Promise.resolve(cfg.reload ? cfg.reload() : null).then(function (rows) { if (rows) S.rows = rows }).catch(fail)
    }
    // 「復原這一批」：只有批次動作（勾選列的批次列、群組全開／全關）會有；單格操作沒有（單項改了就改了，要還原請再改一次）。
    // restore(snap, res)：res＝批次動作 run() 的回傳值（頁面可從中取套用後的版本資訊）；頁面在有人於這之間改過時丟出帶說明的 Error ⇒ 整批不復原。
    function undoer(snap, label, res) {
      if (!batch.snapshot || !batch.restore || snap == null) return null
      return function () {
        S.busy = true; render()
        Promise.resolve(batch.restore(snap, res)).then(function () { return reloadAfter() }).then(function () { S.busy = false; render(); toast('已復原這一批（' + Object.keys(snap).length + ' 項）') })
          .catch(function (e) { S.busy = false; fail(e); return reloadAfter().then(render) })
      }
    }
    function perform(label, keys, fn, opts) {
      if (S.busy) return Promise.resolve()
      var snap = batch.snapshot ? batch.snapshot(keys) : null
      S.busy = true; render()
      return Promise.resolve().then(fn).then(function (res) {
        return reloadAfter().then(function () {
          S.busy = false; render()
          var msg = (res && res.message) || label
          var u = opts && opts.undo ? undoer(snap, label, res) : null
          toast(msg, u ? { undo: u } : {})
        })
      }).catch(function (e) {
        S.busy = false
        if (!(e && e.cancelled)) fail(e)
        return reloadAfter().then(render)
      })
    }
    // 依序跳出確認視窗（每一個都要按「套用」才繼續；任何一個取消 ⇒ false）
    function askAll(dialogs) {
      var chain = Promise.resolve(true)
      dialogs.forEach(function (d) {
        chain = chain.then(function (ok) {
          if (!ok) return false
          return openDialog({ title: d.title, html: d.html, buttons: [{ label: '取消', value: false }, { label: d.okLabel || '套用', value: true, kind: d.danger ? 'danger' : 'primary' }] }).then(function (v) { return v === true })
        })
      })
      return chain
    }
    function runAction(a, keys) {
      var dialogs = a.confirm ? (a.confirm(keys) || []) : []
      return askAll(dialogs).then(function (ok) {
        if (!ok) return
        return perform(a.doneLabel || a.label, keys, function () { return a.run(keys, { confirmed: dialogs.length > 0 }) }, { undo: true })
      })
    }
    // 單格操作：column.confirm(row, value) 可回確認視窗（例如關閉「重要」告警）；set／toggle 丟出 {cancelled:true} ⇒ 靜默放棄、畫面回原狀
    function runCell(label, key, col, r, value, fn) {
      var dialogs = col.confirm ? (col.confirm(r, value) || []) : []
      return askAll(dialogs).then(function (ok) {
        if (!ok) return render()
        return perform(label, [key], function () { return fn({ confirmed: dialogs.length > 0 }) })
      })
    }

    // ── 事件 ──
    el.addEventListener('click', function (e) {
      var t = e.target.closest('[data-mx]')
      if (!t || !el.contains(t)) return
      var m = t.getAttribute('data-mx')
      if (m === 'sel') { S.shift = e.shiftKey; return }
      if (m === 'gsel' || m === 'select' || m === 'search' || m === 'selall' || m === 'gsel-filter') return
      if (S.busy && m !== 'gtoggle') return
      var key = t.getAttribute('data-key'), col = cols.filter(function (c) { return c.id === t.getAttribute('data-col') })[0]
      if (m === 'gtoggle') {
        if (e.target.closest('button,input,select')) return
        var g = t.getAttribute('data-g'); S.collapsed[g] = !S.collapsed[g]; render(); return
      }
      if (m === 'switch') {
        var r = rowByKey(key), v = !col.get(r)
        runCell(rn(r) + '：' + (v ? '已開啟' : '已關閉'), key, col, r, v, function (ctx) { return col.set(r, v, ctx) })
        return
      }
      if (m === 'chip') {
        var r2 = rowByKey(key), val = t.getAttribute('data-val'), cur = col.get(r2), on = !(cur == null ? true : cur.indexOf(val) >= 0)
        runCell(rn(r2) + '：已更新', key, col, r2, on, function (ctx) { return col.toggle(r2, val, on, ctx) })
        return
      }
      if (m === 'act') { if (cfg.onAction) cfg.onAction(t.getAttribute('data-act'), rowByKey(key), api); return }
      if (m === 'filter') { S.f = t.getAttribute('data-f'); render(); return }
      if (m === 'expand') { S.collapsed = {}; render(); return }
      if (m === 'collapse') { groupOrder().forEach(function (g) { S.collapsed[g] = true }); render(); return }
      if (m === 'bclear') { S.sel = {}; render(); return }
      if (m === 'bact') { var a = (batch.actions || []).filter(function (x) { return x.id === t.getAttribute('data-act') })[0]; if (a) runAction(a, selKeys()); return }
      if (m === 'gact') {
        e.stopPropagation()
        var g2 = t.getAttribute('data-g'), a2 = (batch.actions || []).filter(function (x) { return x.id === t.getAttribute('data-act') })[0]
        var ks = view().filter(function (x) { return x.g === g2 })[0].rows.map(rk)
        if (a2 && ks.length) runAction(a2, ks)
      }
    })
    el.addEventListener('change', function (e) {
      var t = e.target.closest('[data-mx]')
      if (!t) return
      var m = t.getAttribute('data-mx'), key = t.getAttribute('data-key')
      if (m === 'sel') {
        if (S.shift && S.last) {
          var ks = visKeys(), i = ks.indexOf(S.last), j = ks.indexOf(key)
          if (i >= 0 && j >= 0) for (var x = Math.min(i, j); x <= Math.max(i, j); x++) S.sel[ks[x]] = t.checked
        } else S.sel[key] = t.checked
        S.last = key; render(); return
      }
      if (m === 'gsel') { var g = t.getAttribute('data-g'); view().filter(function (x) { return x.g === g })[0].rows.forEach(function (r) { S.sel[rk(r)] = t.checked }); render(); return }
      if (m === 'selall') { visKeys().forEach(function (k) { S.sel[k] = t.checked }); render(); return }
      if (m === 'gsel-filter') { S.g = t.value; render(); return }
      if (m === 'select') {
        var col = cols.filter(function (c) { return c.id === t.getAttribute('data-col') })[0], r = rowByKey(key), val = t.value
        runCell(rn(r) + '：已更新', key, col, r, val, function (ctx) { return col.set(r, val, ctx) })
      }
    })
    el.addEventListener('input', function (e) {
      var t = e.target
      if (t.getAttribute && t.getAttribute('data-mx') === 'search') { S.q = t.value.trim(); render() }
    })
    window.addEventListener('resize', function () { /* 表格與卡片由 CSS 切換，不需重畫 */ })

    render()
    var api = {
      setRows: function (rows) { S.rows = rows || []; render() },
      refresh: function () { return reloadAfter().then(render) },
      selection: selKeys,
      clearSelection: function () { S.sel = {}; render() },
      toast: toast,
      state: function () { return S },
      perform: perform,
    }
    return api
  }

  global.SettingsMatrix = global.MxTable = { mount: mount, openDialog: openDialog, closeDialog: closeDialog, toast: toast, esc: esc }
})(window)
