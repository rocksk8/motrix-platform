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
 *       { id: 'who', type: 'html', label: '人員', render: r => '<b>' + SettingsMatrix.esc(r.name) + '</b>', raw: true, show: r => r.enabled, cardHide: false },
 *       { id: 'qty', type: 'number', label: '數量', min: 0, max: 99, step: 1, get: r => r.qty, set: (r, v) => api(...), validate: (v, r) => v > 9 ? '不能超過 9' : null },
 *       { id: 'note', type: 'text', label: '備註', maxlength: 40, placeholder: '…', get: r => r.note, set: (r, v) => api(...) },
 *       { id: 'info', type: 'text-view', label: '說明', get: r => r.info },                // 唯讀文字（自動跳脫）
 *     ],
 *     filters: [{ id: 'on', label: '已開啟', test: r => r.enabled }],           // 篩選晶片（「全部」內建）
 *     searchText: r => r.name + ' ' + r.key,                                      // 搜尋比對的文字
 *     groupSummary: (name, rows) => '已開 3／共 8',                              // 群組列的說明（選填）
 *     batch: {
 *       actions: [{ id: 'off', label: '關閉', run: (keys, ctx) => api(...),      // ctx.confirmed＝使用者勾過的確認（見 confirm）
 *                   confirm: keys => [{ title, html, okLabel, danger }] }],         // 回 0 個以上確認視窗（可回 Promise；回 null＝取消）；全部按「套用」才會執行
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
 *   // 資格：columns 之外可加 eligible: '頁面代號'（要先 registerEligibleOverride 登記，見下方「能不能批次」）；rows 帶 risk／requires_pending／loosen／pending／sensitive 時預設不能批次
 *   // ⚠️ 安全規則（host 必讀）：
 *   //   · type:'html' 欄位的 render() 回傳值**預設會被跳脫**（當純文字）；要放標籤必須明確寫 `raw: true`（或讓 render 回 `SettingsMatrix.raw(html)`）。
 *   //     raw 的內容由 host 自己負責：**所有動態值（名稱、備註、使用者輸入…）一律先 `SettingsMatrix.esc()`**，核心不會替 raw 內容跳脫。
 *   //     同理 openDialog／批次 confirm 的 `html` 欄位、a.confirm 回傳的 `html` 都是 raw，動態值要自己 esc。其餘（列名稱、rowSub、tags、chips 標籤、選項文字）核心一律跳脫。
 *   //   · batch.snapshot(keys) 必須回**物件**（{key: 狀態}）：復原用 Object.keys(snap) 計數；回 null／非物件＝這一批不提供復原（會在 console 警告）。
 *   // 欄位狀態：每個 switch／select／number／text／chips 欄位可帶 disabled(row)（布林或「原因字串」→ 反灰＋tooltip）、readonly(row)（看得到值、不能改）；
 *   //   列層級：row.selectable === false 或 cfg.rowSelectable(row)===false ⇒ 勾選框反灰、批次／全選／群組動作一律略過（原因：row.selectableReason）。
 *   // 文案：cfg.labels = { …只寫要換的鍵… }，預設值見 DEFAULT_LABELS（含 aria-label）；含 {n}／{name}／{g}／{col}／{reason}／{k} 的是樣板。
 *   // 生命週期：mx.destroy() 移除本元件加的所有事件監聽（元件容器、window beforeunload、document click）並清空容器；之後所有 api 呼叫都是空操作。
 *   // 寫入中（S.busy）的格子修改**不會被丟掉**：排進佇列，前一筆寫完後依序套用（草稿模式＝依序併入草稿；儲存中改的格子不會被儲存後的清空吃掉）。
 *   // 重新繪製會還原焦點（依 data-mx／data-key／data-col／data-val／data-g 找回同一個控制項，文字框連游標位置）。
 *   // 草稿：draft: { apply, same, confirm, save, afterSave }（見 mount 內的說明）；欄位用 draft(row, value) 取代 set／toggle，批次動作用 draft(keys) 取代 run
 *   // S1b 新增（全部選填；沒給＝畫面與行為完全不變）：
 *   //   cfg.help(row)→{what,when,impact,recommend}：名稱旁的「?」，點開四段說明（空段略過、全空不畫；文字跳脫）。
 *   //   cfg.source(row)→{kind:'default'|'company'|'pending'|'legacy'|'personal', by, at, reason, until}：來源徽章＋「來源：…」一行（'personal' 只給真的有個人層的欄位）。
 *   //   cfg.diff={isDefault(row), defaultText(row), reset(row,ctx), draft(row), canReset(row), confirm(row)}：「與預設不同」標記＋篩選晶片＋「預設：X［還原預設］」（只在不同時顯示）。
 *   //   欄位 colSelect={draft(row,on,itemValue), run(keys,on,itemValue,ctx), confirm(keys,on,itemValue)}（switch／chips 欄）：欄頭核取方塊，整欄一次開／關（略過不能批次或鎖住的列）。
 *   //   cfg.notifyPreview({kind,keys,changes,action,skipped})→raw html：確認視窗最後加「通知預覽」。
 *   // 群組快捷鈕總開關：batch.groupActionsEnabled: false（設定中心不開放「全部開啟」）
 *   mx.setRows(rows)  mx.refresh()  mx.selection()  mx.clearSelection()  mx.toast(msg, { undo })  mx.stage(key, patch)  mx.draftCount()  mx.discard()  mx.save()  mx.destroy()
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

  // 明確標示「這段 HTML 是 host 已經跳脫好的」：html 欄位的 render() 可回傳 SettingsMatrix.raw('<b>…</b>')
  function raw(html) { return { __mxRaw: true, html: String(html == null ? '' : html) } }

  // 可替換的文案（cfg.labels 只需要寫要換的鍵）；{n}／{name}／{g}／{col}／{reason}／{k} 是樣板
  var DEFAULT_LABELS = {
    all: '全部', allGroups: '全部群組', groupFilterAria: '只看某個群組', expand: '展開全部', collapse: '收合全部',
    search: '搜尋', nameCol: '項目', empty: '沒有符合條件的項目',
    batchAria: '批次操作', selected: '已選 {n} 項', clearSel: '取消選取', selAllAria: '全選目前列出的列',
    selectRow: '選取 {name}', selectGroupAria: '選取「{g}」全部列出的列（不能批次的列會略過）',
    cellAria: '{name}：{col}', switchDefault: '開關', chipOn: '（是）', chipOff: '（否）',
    draftBar: '你有 {n} 項未儲存的修改', draftDiscard: '放棄', draftSave: '儲存', draftTag: '未儲存', saved: '已儲存',
    staged: '已加入草稿 {n} 項（尚未儲存）', stagedSkipped: '，略過 {k} 項（不能批次）',
    noBatchTag: '不能批次', noBatchTitle: '不能批次：{reason}', notSelectable: '這一列不能選取',
    skippedBox: '已略過 {n} 項（不能批次，請逐項設定）：', skippedAll: '選取的項目都不能批次，請逐項設定', noneSelected: '沒有選取任何項目',
    partialTitle: '部分項目不能批次', partialBody: '將套用 {n} 項。', apply: '套用', cancel: '取消',
    undo: '復原這一批', undone: '已復原這一批（{n} 項）', updated: '已更新', turnedOn: '已開啟', turnedOff: '已關閉', failed: '失敗', invalidNumber: '請輸入數字',
    help: '說明', helpTitle: '{name}：說明', helpWhat: '這是什麼', helpWhen: '什麼時候要改', helpImpact: '改了會影響什麼', helpRecommend: '建議值', close: '關閉',
    srcLine: '來源：', srcDefault: '預設', srcCompany: '公司', srcPending: '等待生效', srcLegacy: '舊位置', srcPersonal: '個人',
    srcDefaultText: '系統預設', srcCompanyText: '公司設定', srcPendingText: '等待生效', srcLegacyText: '舊位置（唯讀提示）', srcPersonalText: '個人設定',
    diffTag: '與預設不同', diffFilter: '與預設不同', diffDefault: '預設：{v}', diffReset: '還原預設', diffResetTitle: '還原「{name}」為預設值',
    colSelAria: '整欄選取：{col}', colSelStaged: '已加入草稿 {n} 項（尚未儲存）', colSelSkipped: '，略過 {k} 項（不能批次或欄位已鎖定）', colSelNone: '沒有可套用的列',
    previewTitle: '通知預覽',
    leaveTitle: '離開這一頁？', leaveBody: '你有 {n} 項未儲存的修改，離開後會遺失。', stay: '留在這一頁', leave: '放棄修改並離開',
  }
  function fmt(tpl, vars) {
    return String(tpl).replace(/\{(\w+)\}/g, function (m, k) { return vars && vars[k] != null ? vars[k] : m })
  }

  // ── 「能不能批次」的判定（SPEC §4）：預設規則＋頁面覆寫**必須登記** ──────────────────────────────────────────
  // 預設：risk ∈ {security, money, legal}、requires_pending、loosen、pending、sensitive 的列不能批次（勾選框反灰、附原因；全選與群組動作自動略過）。
  // 頁面要放寬／改原因，一律 `SettingsMatrix.registerEligibleOverride(頁面代號, fn(row, 預設結果), 理由)`，再用 `mount({ eligible: '頁面代號' })`；沒登記的覆寫會直接丟錯。
  // 已登記清單看 `SettingsMatrix.eligibleOverrides()`（守門用）。目前只有 LINE 事件頁的「重要」告警（使用者 2026-11-13 裁示：可批次關閉，但要二次確認）。
  var ELIGIBLE_REG = {}
  function registerEligibleOverride(id, fn, why) {
    if (!id || typeof fn !== 'function' || !why) throw new Error('registerEligibleOverride 需要 (頁面代號, 函式, 理由)')
    ELIGIBLE_REG[id] = { fn: fn, why: String(why) }
  }
  function eligibleOverrides() { return Object.keys(ELIGIBLE_REG).map(function (k) { return { id: k, why: ELIGIBLE_REG[k].why } }) }
  var RISK_TEXT = { security: '資安／權限相關', money: '涉及金額', legal: '涉及法規' }
  function defaultEligible(r) {
    if (RISK_TEXT[r.risk]) return { ok: false, reason: '影響大（' + RISK_TEXT[r.risk] + '），請逐項設定' }
    if (r.requires_pending) return { ok: false, reason: '需要等待期或核准才會生效，請逐項設定' }
    if (r.loosen) return { ok: false, reason: '放寬規則的變更，請逐項設定' }
    if (r.pending) return { ok: false, reason: '已有待生效的變更' }
    if (r.sensitive) return { ok: false, reason: '高敏感項目，請逐項設定' }
    return { ok: true, reason: '' }
  }

  // ── C6「?」說明／C7 來源／C8 與預設不同（純函式，可單獨測試；內容由 host 從登錄表的 field_views 傳入，核心不自己編文案）──────
  // 說明四段：{ what, when, impact, recommend }（來自 SettingDef 的 question／help、when、impact／risk_text、recommended；SPEC §6）。空段不顯示；全空＝不畫「?」。
  // 文字一律跳脫（純文字）；要換行請用 \n（轉成 <br>）。
  var HELP_PARTS = [['what', 'helpWhat'], ['when', 'helpWhen'], ['impact', 'helpImpact'], ['recommend', 'helpRecommend']]
  function textHtml(t) { return esc(t).replace(/\n/g, '<br>') }
  function helpParts(h, labels) {
    if (!h || typeof h !== 'object') return []
    var out = []
    HELP_PARTS.forEach(function (p) {
      var v = h[p[0]]
      if (v == null || String(v).trim() === '') return
      out.push({ id: p[0], title: (labels || DEFAULT_LABELS)[p[1]] || DEFAULT_LABELS[p[1]], text: String(v) })
    })
    return out
  }
  function helpHtml(h, labels) {
    return helpParts(h, labels).map(function (p) {
      return '<section class="mx-help-sec" data-part="' + p.id + '"><h4>' + esc(p.title) + '</h4><p>' + textHtml(p.text) + '</p></section>'
    }).join('')
  }
  // 來源徽章只有五種（SPEC §2.3）：預設／公司／等待生效／舊位置／個人。「個人」只該出現在真的有個人層的欄位——核心不判斷，host 只在有個人層時才回 kind:'personal'。
  var SRC_KINDS = { 'default': { b: 'srcDefault', t: 'srcDefaultText', tone: 'mute' }, company: { b: 'srcCompany', t: 'srcCompanyText', tone: 'info' },
    pending: { b: 'srcPending', t: 'srcPendingText', tone: 'warn' }, legacy: { b: 'srcLegacy', t: 'srcLegacyText', tone: 'mute' }, personal: { b: 'srcPersonal', t: 'srcPersonalText', tone: 'good' } }
  // s：{kind, by, at, reason, until}；回 {badge, tone, text}（text＝「來源」那一行的純文字），kind 不認得 ⇒ null
  function sourceInfo(s, labels) {
    if (!s || typeof s !== 'object') return null
    var k = SRC_KINDS[s.kind]
    if (!k) return null
    var LBL = labels || DEFAULT_LABELS
    var bits = [LBL[k.t] || DEFAULT_LABELS[k.t]]
    var who = [s.by, s.at].filter(function (x) { return x != null && String(x) !== '' }).join(' ')
    if (who) bits.push(who)
    if (s.kind === 'pending' && s.until) bits.push(String(s.until))
    if (s.reason) bits.push(String(s.reason))
    return { badge: LBL[k.b] || DEFAULT_LABELS[k.b], tone: k.tone, text: bits.join(' · ') }
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
    Array.prototype.slice.call(document.querySelectorAll('.mx-toast')).forEach(function (o) { if (o.parentNode) o.parentNode.removeChild(o) })     // 同時只留一則（新的取代舊的）
    var t = document.createElement('div')
    t.className = 'mx-toast' + (opts.error ? ' mx-toast-error' : '')
    t.setAttribute('role', opts.error ? 'alert' : 'status')
    t.innerHTML = '<span data-testid="mx-toast-text">' + esc(msg) + '</span>' + (opts.undo ? '<button type="button" data-testid="mx-undo">' + esc(opts.undoLabel || DEFAULT_LABELS.undo) + '</button>' : '')
    var timer = null
    function gone() { clearTimeout(timer); if (t.parentNode) t.parentNode.removeChild(t) }
    if (opts.undo) t.querySelector('button').onclick = function () { gone(); opts.undo() }
    document.body.appendChild(t)
    timer = setTimeout(gone, opts.error ? 9000 : 6500)
    return gone
  }

  // ── 主元件 ───────────────────────────────────────────────────────────────────────────────────────────
  var globalToast = toast
  function mount(el, cfg) {
    var S = { rows: cfg.rows || [], q: '', f: 'all', g: '', collapsed: {}, sel: {}, last: null, shift: false, busy: false, draft: {} }
    var Q = []                                                      // 寫入中收到的格子修改（依序套用，不丟）
    var dead = false
    var LB = Object.assign({}, DEFAULT_LABELS, cfg.labels || {})
    function T(key, vars) { return fmt(LB[key] != null ? LB[key] : key, vars) }
    var toast = function (msg, o) { return globalToast(msg, Object.assign({ undoLabel: LB.undo }, o || {})) }       // 本元件的提示用 cfg.labels 的「復原」字樣
    var warned = {}
    function warnOnce(k, msg) { if (!warned[k]) { warned[k] = 1; try { console.warn('[SettingsMatrix] ' + msg) } catch (e) { /* ignore */ } } }
    // 草稿模式（opt-in：mount({ draft: {...} })，使用者規則 2026-11-13「點選只算草稿，要儲存才生效」；SPEC §13）：
    //   欄位的 draft(row, value…) ／批次動作的 draft(keys) 回一份「改動 patch」（或 Promise；null＝不動；丟 {cancelled:true}＝取消），核心只把 patch 記在草稿裡、不寫入；
    //   頂端黏住「你有 N 項未儲存的修改［放棄］［儲存］」；儲存＝先 draft.confirm(changes)（確認視窗，可回 Promise）、再 draft.save(changes, ctx)；成功才清草稿、才有「復原這一批」；
    //   有草稿時關閉／重新整理頁面、點站內連結都會警告。draft = { apply(row, patch)→顯示用的列, same(rawRow, mergedPatch)→true 表示等於原狀（自動移出草稿）,
    //   confirm(changes), save(changes, ctx), afterSave(res, changes) }；changes = [{ key, patch, row（伺服器原值）}]。
    var D = cfg.draft || null
    var elig = null
    if (cfg.eligible != null) {
      if (typeof cfg.eligible !== 'string' || !ELIGIBLE_REG[cfg.eligible]) throw new Error('eligible 覆寫沒有登記：先呼叫 SettingsMatrix.registerEligibleOverride')
      elig = ELIGIBLE_REG[cfg.eligible]
    }
    function eligibleOf(r) {
      if (r.selectable === false || (cfg.rowSelectable && cfg.rowSelectable(r) === false)) return { ok: false, reason: r.selectableReason || T('notSelectable') }
      var d = defaultEligible(r)
      if (!elig) return d
      var o = elig.fn(r, d)
      if (o === true) return { ok: true, reason: '' }
      if (o === false) return { ok: false, reason: d.reason || elig.why }
      return o && typeof o === 'object' ? { ok: !!o.ok, reason: o.reason || '' } : d
    }
    var rk = cfg.rowKey || function (r) { return r.key }
    var rn = cfg.rowName || function (r) { return r.name }
    var rg = cfg.rowGroup || function (r) { return r.group }
    var cols = cfg.columns || []
    // C8 與預設不同：cfg.diff = { isDefault(row)→bool, defaultText(row)→「預設：X」的 X, reset(row, ctx)→Promise（立即模式）, draft(row)→patch（草稿模式）, canReset(row)→bool（選填，false＝不給還原鈕）, confirm(row)→確認視窗（選填） }
    var DF = cfg.diff || null
    function differs(r) { return !!DF && DF.isDefault(r) === false }
    var filters = (cfg.filters || []).slice()
    if (DF && !filters.some(function (f) { return f.id === '__diff' })) filters.push({ id: '__diff', label: LB.diffFilter, test: differs })
    var batch = cfg.batch || { actions: [] }
    var groups = (cfg.groups || []).slice()

    function vr(r) {
      var pt = S.draft[rk(r)]
      if (!pt) return r
      return D && D.apply ? D.apply(r, pt) : Object.assign({}, r, pt)
    }
    function VR() { return S.rows.map(vr) }
    function groupOrder() {
      var seen = {}
      var all = VR()
      var out = groups.filter(function (g) { seen[g] = 1; return all.some(function (r) { return rg(r) === g }) })
      all.forEach(function (r) { var g = rg(r) || '其他'; if (!seen[g]) { seen[g] = 1; out.push(g) } })
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
      var vrows = VR()
      return groupOrder().map(function (g) {
        var all = vrows.filter(function (r) { return (rg(r) || '其他') === g })
        return { g: g, all: all, rows: all.filter(visible) }
      }).filter(function (x) { return x.rows.length })
    }
    function isClosed(g) { return S.collapsed[g] && !S.q }
    function visKeys() {
      var o = []
      view().forEach(function (x) { if (!isClosed(x.g)) x.rows.forEach(function (r) { o.push(rk(r)) }) })
      return o
    }
    function rawByKey(k) { return S.rows.filter(function (r) { return rk(r) === k })[0] }
    function rowByKey(k) { var r = rawByKey(k); return r ? vr(r) : r }
    function canBatch(k) { var r = rowByKey(k); return !!r && eligibleOf(r).ok }
    function selKeys() { return Object.keys(S.sel).filter(function (k) { return S.sel[k] && canBatch(k) }) }
    // 不能批次的列：{key, name, reason}（確認視窗與吐司列出「已略過」）
    function skippedOf(keys) {
      return keys.map(rowByKey).filter(function (r) { return r && !eligibleOf(r).ok }).map(function (r) { return { key: rk(r), name: rn(r), reason: eligibleOf(r).reason } })
    }
    function skippedHtml(sk) {
      return sk.length ? '<div class="mx-danger-box" data-testid="mx-skipped">' + esc(T('skippedBox', { n: sk.length })) + '<ul>' + sk.slice(0, 8).map(function (x) { return '<li>' + esc(x.name) + '：' + esc(x.reason) + '</li>' }).join('') + '</ul></div>' : ''
    }
    function dirtyCount() { return Object.keys(S.draft).length }
    function colShown(c, r) { return c.show ? !!c.show(r) : true }

    // ── 渲染 ──
    function tags(r) {
      var extra = []
      if (S.draft[rk(r)]) extra.push({ text: T('draftTag'), tone: 'warn' })
      var el = eligibleOf(r)
      if (!el.ok) extra.push({ text: T('noBatchTag'), tone: 'mute', title: el.reason })
      if (differs(r)) extra.push({ text: '● ' + T('diffTag'), tone: 'warn' })
      var si = srcOf(r)
      if (si) extra.push({ text: si.badge, tone: si.tone, title: si.text })
      return (cfg.rowTags ? cfg.rowTags(r) : []).concat(extra).map(function (t) { return ' <span class="mx-pill ' + (TONES[t.tone] || '') + '"' + (t.title ? ' title="' + esc(t.title) + '"' : '') + '>' + esc(t.text) + '</span>' }).join('')
    }
    function ckAttrs(r) {
      var el = eligibleOf(r)
      return el.ok ? '' : ' disabled title="' + esc(T('noBatchTitle', { reason: el.reason })) + '"'
    }
    function srcOf(r) { return cfg.source ? sourceInfo(cfg.source(r), LB) : null }
    function helpOf(r) { return cfg.help ? cfg.help(r) : null }
    function helpBtn(r) {
      return helpParts(helpOf(r), LB).length ? ' <button type="button" class="mx-help" data-mx="help" data-key="' + esc(rk(r)) + '" aria-label="' + esc(T('help') + '：' + rn(r)) + '" title="' + esc(T('help')) + '">?</button>' : ''
    }
    // 「預設：X［還原預設］」只在與預設不同時才顯示（SPEC §2.1-4）；來源那一行只在 host 有提供 source 時顯示
    function metaLines(r) {
      var h = ''
      var si = srcOf(r)
      if (si) h += '<div class="mx-src" data-testid="mx-src">' + esc(T('srcLine')) + esc(si.text) + '</div>'
      if (differs(r) && DF.defaultText) {
        h += '<div class="mx-dflt" data-testid="mx-dflt">' + esc(T('diffDefault', { v: DF.defaultText(r) })) +
          ((DF.reset || DF.draft) && !(DF.canReset && DF.canReset(r) === false) ? ' <button type="button" class="mx-btn mx-btn-sm" data-mx="dreset" data-key="' + esc(rk(r)) + '" title="' + esc(T('diffResetTitle', { name: rn(r) })) + '">' + esc(T('diffReset')) + '</button>' : '') + '</div>'
      }
      return h
    }
    function nameCell(r) {
      return '<span class="mx-nm">' + esc(rn(r)) + '</span>' + helpBtn(r) + tags(r) + (cfg.rowSub ? '<div class="mx-sub">' + esc(cfg.rowSub(r)) + '</div>' : '') + metaLines(r)
    }
    // 每格的狀態：disabled（反灰，可帶原因字串）／readonly（看得到值、不能改）。伺服器端永遠是最後防線；這裡的判斷在事件處理時會再查一次。
    function stateOf(c, r) {
      var d = c.disabled ? c.disabled(r) : false
      var ro = c.readonly ? c.readonly(r) : false
      return { dis: !!d, ro: !!ro, why: typeof d === 'string' ? d : (typeof ro === 'string' ? ro : '') }
    }
    function locked(c, r) { var st = stateOf(c, r); return st.dis || st.ro }
    function cell(c, r, k) {
      var attrs = ' data-col="' + esc(c.id) + '" data-key="' + esc(k) + '"'
      if (!colShown(c, r)) return c.type === 'switch' ? '' : '<span class="mx-dash">—</span>'
      var st = stateOf(c, r)
      var aria = esc(T('cellAria', { name: rn(r), col: c.label || (c.type === 'switch' ? T('switchDefault') : '') }))
      var lockAttrs = (st.dis || st.ro ? ' disabled' : '') + (st.ro ? ' aria-readonly="true"' : '') + (st.why ? ' title="' + esc(st.why) + '"' : '')
      var lockCls = (st.dis ? ' mx-dis' : '') + (st.ro ? ' mx-ro' : '')
      if (c.type === 'switch') {
        var on = !!c.get(r)
        return '<button type="button" class="mx-sw' + lockCls + '" role="switch" data-mx="switch"' + attrs + ' aria-checked="' + on + '" aria-label="' + aria + '"' + lockAttrs + '></button>'
      }
      if (c.type === 'select') {
        var v = c.get(r)
        return '<select class="mx-select' + lockCls + '" data-mx="select"' + attrs + ' aria-label="' + aria + '"' + lockAttrs + '>' + c.options.map(function (o) {
          return '<option value="' + esc(o.value) + '"' + (String(o.value) === String(v) ? ' selected' : '') + '>' + esc(o.label) + '</option>'
        }).join('') + '</select>'
      }
      if (c.type === 'number' || c.type === 'text') {
        var iv = c.get ? c.get(r) : ''
        var extra = ''
        if (c.type === 'number') {
          if (c.min != null) extra += ' min="' + esc(c.min) + '"'
          if (c.max != null) extra += ' max="' + esc(c.max) + '"'
          if (c.step != null) extra += ' step="' + esc(c.step) + '"'
        } else if (c.maxlength != null) extra += ' maxlength="' + esc(c.maxlength) + '"'
        if (c.placeholder) extra += ' placeholder="' + esc(c.placeholder) + '"'
        return '<input class="mx-input' + lockCls + '" type="' + (c.type === 'number' ? 'number' : 'text') + '" data-mx="input"' + attrs + ' value="' + esc(iv == null ? '' : iv) + '"' + extra +
          ' aria-label="' + aria + '"' + (st.dis ? ' disabled' : '') + (st.ro ? ' readonly aria-readonly="true"' : '') + (st.why ? ' title="' + esc(st.why) + '"' : '') + '>'
      }
      if (c.type === 'html') {
        var o = c.render(r)
        if (o && o.__mxRaw) return o.html
        if (c.raw === true) return o == null ? '' : String(o)
        if (c.render.length >= 0 && o != null && /[<>&]/.test(String(o))) warnOnce('html:' + c.id, "type:'html' 欄位「" + c.id + "」的內容含 HTML 字元但沒有 raw:true，已當純文字顯示；要放標籤請設 raw:true 並自行 esc() 動態值")
        return esc(o)
      }
      return esc(c.get ? c.get(r) : (c.render ? c.render(r) : ''))
    }
    function chipCell(c, r, k, it, asChip) {
      if (!colShown(c, r)) return asChip ? '' : ''
      var cur = c.get(r)
      var on = cur == null ? true : cur.indexOf(it.value) >= 0                       // null＝所有項目都亮（不篩選）
      var tone = c.tone ? c.tone(r) : 'a'
      var st = stateOf(c, r)
      var dis = st.dis || st.ro
      var cls = (asChip ? 'mx-chip' : 'mx-rc') + (on ? ' on ' + tone : '') + (dis ? ' dis' : '') + (st.ro ? ' mx-ro' : '')
      return '<button type="button" class="' + cls + '" data-mx="chip" data-col="' + esc(c.id) + '" data-key="' + esc(k) + '" data-val="' + esc(it.value) + '" aria-pressed="' + on + '" aria-label="' +
        esc(rn(r) + '：' + it.label + (on ? T('chipOn') : T('chipOff'))) + '"' + (dis ? ' disabled' : '') + (st.ro ? ' aria-readonly="true"' : '') + (st.why ? ' title="' + esc(st.why) + '"' : '') + '>' + (asChip ? esc(it.label) : '✓') + '</button>'
    }
    // C11 欄頭選取：欄定義帶 colSelect:{ draft(row, on, itemValue)→patch（草稿模式，逐列算）, run(keys, on, itemValue, ctx)→Promise（立即模式）, confirm(keys, on, itemValue)→確認視窗（選填） }
    //   的 switch／chips 欄，欄頭多一個核取方塊：勾＝把「目前列出、可批次、該格沒鎖」的列全設成開；取消勾＝全設成關；有開有關＝半選。
    function csHead(c, it) {
      if (!c.colSelect || (c.type !== 'switch' && c.type !== 'chips')) return ''
      var val = it ? it.value : ''
      return '<input type="checkbox" class="mx-csel" data-mx="csel" data-col="' + esc(c.id) + '"' + (it ? ' data-val="' + esc(val) + '"' : '') + ' aria-label="' + esc(T('colSelAria', { col: it ? it.label : (c.label || '') })) + '">'
    }
    function headCells() {
      var h = ''
      cols.forEach(function (c) {
        if (c.type === 'chips') c.items.forEach(function (it) { h += '<th class="mx-th-chip" title="' + esc(it.label) + '">' + esc(it.short || it.label) + csHead(c, it) + '</th>' })
        else h += '<th' + (c.width ? ' style="width:' + c.width + 'px"' : '') + '>' + esc(c.label || '') + csHead(c, null) + '</th>'
      })
      return h
    }
    function cellOn(c, r, val) {
      if (c.type === 'chips') { var cur = c.get(r); return cur == null ? true : cur.indexOf(val) >= 0 }
      return !!c.get(r)
    }
    // 欄頭選取的對象：目前列出（群組沒收合）、可批次、該格顯示且沒鎖的列
    function colTargets(c) {
      return visKeys().filter(function (k) { var r = rowByKey(k); return r && eligibleOf(r).ok && colShown(c, r) && !locked(c, r) })
    }
    function syncColSelect() {
      Array.prototype.slice.call(el.querySelectorAll('input[data-mx=csel]')).forEach(function (b) {
        var c = cols.filter(function (x) { return x.id === b.getAttribute('data-col') })[0]
        if (!c) return
        var val = b.getAttribute('data-val')
        var ks = colTargets(c)
        var n = ks.filter(function (k) { return cellOn(c, rowByKey(k), val) }).length
        b.disabled = !ks.length
        b.checked = ks.length > 0 && n === ks.length
        b.indeterminate = n > 0 && n < ks.length
      })
    }
    function rowTable(r) {
      var k = rk(r), tds = ''
      cols.forEach(function (c) {
        if (c.type === 'chips') c.items.forEach(function (it) { tds += '<td>' + chipCell(c, r, k, it, false) + '</td>' })
        else tds += '<td>' + cell(c, r, k) + '</td>'
      })
      return '<tr class="mx-row' + (S.sel[k] ? ' sel' : '') + (S.draft[k] ? ' mx-draft' : '') + (differs(r) ? ' mx-changed' : '') + '" data-testid="mx-row-' + esc(k) + '"><td class="mx-ck"><input type="checkbox" data-mx="sel" data-key="' + esc(k) + '"' + (S.sel[k] ? ' checked' : '') + ckAttrs(r) +
        ' aria-label="' + esc(T('selectRow', { name: rn(r) })) + '"></td><td class="mx-name">' + nameCell(r) + '</td>' + tds + '</tr>'
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
      return '<div class="mx-card-row' + (S.sel[k] ? ' sel' : '') + (S.draft[k] ? ' mx-draft' : '') + (differs(r) ? ' mx-changed' : '') + '"><div class="mx-card-top"><input type="checkbox" data-mx="sel" data-key="' + esc(k) + '"' + (S.sel[k] ? ' checked' : '') + ckAttrs(r) +
        ' aria-label="' + esc(T('selectRow', { name: rn(r) })) + '"><div class="mx-card-name">' + nameCell(r) + '</div>' + sw + '</div>' + body + '</div>'
    }
    function groupHead(x, asCard) {
      var closed = isClosed(x.g)
      var okRows = x.rows.filter(function (r) { return eligibleOf(r).ok })
      var allsel = okRows.length > 0 && okRows.every(function (r) { return S.sel[rk(r)] })
      var sum = cfg.groupSummary ? cfg.groupSummary(x.g, x.all, x.rows) : ''
      // 群組快捷鈕（全開／全關…）的總開關：batch.groupActionsEnabled === false 或個別項目 hidden:true ⇒ 不顯示（設定中心不開放「全部開啟」，SPEC §4.3）
      var acts = (batch.groupActionsEnabled === false ? [] : (batch.groupActions || []).filter(function (a) { return !a.hidden })).map(function (a) {
        return '<button type="button" class="mx-btn mx-btn-sm" data-mx="gact" data-act="' + esc(a.action) + '" data-g="' + esc(x.g) + '">' + esc(a.label) + '</button>'
      }).join(' ')
      var ck = '<input type="checkbox" data-mx="gsel" data-g="' + esc(x.g) + '"' + (allsel ? ' checked' : '') + (okRows.length ? '' : ' disabled') + ' aria-label="' + esc(T('selectGroupAria', { g: x.g })) + '">'
      if (asCard) return '<div class="mx-ghead" data-mx="gtoggle" data-g="' + esc(x.g) + '">' + ck + '<span class="mx-gname">' + (closed ? '▸ ' : '▾ ') + esc(x.g) + ' <span class="mx-mute">' + esc(sum) + '</span></span>' + acts + '</div>'
      var span = 1
      cols.forEach(function (c) { span += c.type === 'chips' ? c.items.length : 1 })
      return '<tr class="mx-grp" data-mx="gtoggle" data-g="' + esc(x.g) + '"><td class="mx-ck">' + ck + '</td><td class="mx-gname">' + (closed ? '▸ ' : '▾ ') + esc(x.g) +
        ' <span class="mx-mute">' + esc(sum) + '</span></td><td colspan="' + (span - 1) + '" class="mx-gacts">' + acts + '</td></tr>'
    }
    // 重新繪製會換掉整段 DOM ⇒ 先記下焦點在哪個控制項（以 data-* 辨識）、繪完找回（表格與卡片各有一份，挑看得見的那個）
    var FOCUS_ATTRS = ['data-mx', 'data-key', 'data-col', 'data-val', 'data-g', 'data-f', 'data-act']
    function captureFocus() {
      var a = document.activeElement
      if (!a || !a.getAttribute || !el.contains(a) || !a.getAttribute('data-mx')) return null
      var f = { sel: {}, s: null, e: null }
      FOCUS_ATTRS.forEach(function (n) { var v = a.getAttribute(n); if (v != null) f.sel[n] = v })
      try { f.s = a.selectionStart; f.e = a.selectionEnd } catch (x) { /* checkbox／button 沒有 selection */ }
      return f
    }
    function restoreFocus(f) {
      if (!f) return
      var q = Object.keys(f.sel).map(function (n) { return '[' + n + '="' + String(f.sel[n]).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"]' }).join('')
      var all
      try { all = el.querySelectorAll(q) } catch (x) { return }
      var pick = null
      for (var i = 0; i < all.length; i++) { if (all[i].offsetParent !== null && !all[i].disabled) { pick = all[i]; break } }
      if (!pick) return
      try { pick.focus({ preventScroll: true }) } catch (x) { try { pick.focus() } catch (y) { /* ignore */ } }
      if (f.s != null) { try { pick.setSelectionRange(f.s, f.e) } catch (x) { /* ignore */ } }
    }
    function render() {
      if (dead) return
      var v = view()
      var chipF = '<button type="button" class="mx-fchip" data-mx="filter" data-f="all" aria-pressed="' + (S.f === 'all') + '">' + esc(T('all')) + '</button>' + filters.map(function (f) {
        return '<button type="button" class="mx-fchip" data-mx="filter" data-f="' + esc(f.id) + '" aria-pressed="' + (S.f === f.id) + '"' + (f.title ? ' title="' + esc(f.title) + '"' : '') + '>' + esc(f.label) + '</button>'
      }).join('')
      var gsel = '<select class="mx-select" data-mx="gsel-filter" aria-label="' + esc(T('groupFilterAria')) + '"><option value="">' + esc(T('allGroups')) + '</option>' + groupOrder().map(function (g) {
        return '<option' + (S.g === g ? ' selected' : '') + '>' + esc(g) + '</option>'
      }).join('') + '</select>'
      var dn = dirtyCount()
      var dbar = D && dn ? '<div class="mx-draftbar" role="status" data-testid="mx-draftbar"><span data-testid="mx-draft-count">' + esc(T('draftBar', { n: '\u0001' })).replace('\u0001', '<b>' + dn + '</b>') + '</span><span class="mx-grow"></span>' +
        '<button type="button" class="mx-btn" data-mx="ddiscard" data-testid="mx-draft-discard">' + esc(T('draftDiscard')) + '</button><button type="button" class="mx-btn mx-btn-primary" data-mx="dsave" data-testid="mx-draft-save">' + esc(T('draftSave')) + '</button></div>' : ''
      var tb = '<div class="mx-sticky">' + dbar + '<div class="mx-toolbar"><input type="search" class="mx-search" data-mx="search" placeholder="' + esc(cfg.searchPlaceholder || T('search')) + '" value="' + esc(S.q) + '" aria-label="' + esc(T('search')) + '">' + chipF + gsel +
        '<button type="button" class="mx-btn" data-mx="expand">' + esc(T('expand')) + '</button><button type="button" class="mx-btn" data-mx="collapse">' + esc(T('collapse')) + '</button></div></div>'
      var table = '<div class="mx-wrap"><table class="mx-table"><thead><tr><th class="mx-ck"><input type="checkbox" data-mx="selall" aria-label="' + esc(T('selAllAria')) + '"></th><th class="mx-name">' + esc(cfg.nameLabel || T('nameCol')) + '</th>' + headCells() + '</tr></thead><tbody>'
      var cards = '<div class="mx-cards">'
      if (!v.length) { table += '<tr><td colspan="40" class="mx-empty">' + esc(T('empty')) + '</td></tr>'; cards += '<div class="mx-empty">' + esc(T('empty')) + '</div>' }
      v.forEach(function (x) {
        table += groupHead(x, false)
        cards += '<div class="mx-gcard">' + groupHead(x, true)
        if (!isClosed(x.g)) x.rows.forEach(function (r) { table += rowTable(r); cards += rowCard(r) })
        cards += '</div>'
      })
      table += '</tbody></table></div>'
      cards += '</div>'
      var n = selKeys().length
      var bar = '<div class="mx-batch' + (n ? '' : ' mx-hide') + '" role="toolbar" aria-label="' + esc(T('batchAria')) + '" data-testid="mx-batch"><b data-testid="mx-batch-count">' + esc(T('selected', { n: n })) + '</b>' +
        (batch.actions || []).map(function (a) {
          return (a.dividerBefore ? '<span class="mx-sep"></span>' : '') + (a.caption ? '<span class="mx-cap">' + esc(a.caption) + '</span>' : '') +
            '<button type="button" class="mx-btn" data-mx="bact" data-act="' + esc(a.id) + '" data-testid="mx-batch-' + esc(a.id) + '">' + esc(a.label) + '</button>'
        }).join('') + '<span class="mx-sep"></span><button type="button" class="mx-btn" data-mx="bclear" data-testid="mx-batch-clear">' + esc(T('clearSel')) + '</button></div>'
      el.classList.add('mx-root')
      el.classList.toggle('mx-busy', S.busy)
      var fo = captureFocus()
      el.innerHTML = tb + table + cards + bar
      restoreFocus(fo)
      var sa = el.querySelector('[data-mx=selall]')
      if (sa) { var ks = visKeys().filter(canBatch); sa.checked = ks.length > 0 && ks.every(function (k) { return S.sel[k] }) }
      syncColSelect()
    }

    // ── 寫入（單格／批次共用）：鎖住 → 寫 → 重讀 → 提示＋復原；失敗 ⇒ 顯示原因並回到伺服器的狀態 ──
    function fail(e) {
      if (dead) return
      if (cfg.onError) cfg.onError(e)
      else toast((e && e.message) || T('failed'), { error: true })
    }
    function reloadAfter() {
      return Promise.resolve(cfg.reload ? cfg.reload() : null).then(function (rows) { if (rows) S.rows = rows }).catch(fail)
    }
    // 「復原這一批」：只有批次動作（勾選列的批次列、群組全開／全關）會有；單格操作沒有（單項改了就改了，要還原請再改一次）。
    // restore(snap, res)：res＝批次動作 run() 的回傳值（頁面可從中取套用後的版本資訊）；頁面在有人於這之間改過時丟出帶說明的 Error ⇒ 整批不復原。
    function undoer(snap, label, res) {
      if (!batch.snapshot || !batch.restore || snap == null) return null
      if (typeof snap !== 'object') { warnOnce('snap', 'batch.snapshot(keys) 必須回物件（{key: 狀態}），目前回了 ' + typeof snap + '，這一批不提供復原'); return null }
      return function () {
        S.busy = true; render()
        Promise.resolve(batch.restore(snap, res)).then(function () { return reloadAfter() }).then(function () { S.busy = false; render(); toast(T('undone', { n: Object.keys(snap).length })); drain() })
          .catch(function (e) { S.busy = false; fail(e); return reloadAfter().then(function () { render(); drain() }) })
      }
    }
    // opts.undo：成功後給「復原這一批」；opts.draft：這是「儲存草稿」——成功才清草稿；失敗**保留**草稿也**不重新載入**（重載會換掉載入時的版本，之後重試就蓋掉別人的修改）
    function perform(label, keys, fn, opts) {
      if (S.busy) return Promise.resolve()
      var snap = batch.snapshot ? batch.snapshot(keys) : null
      S.busy = true; render()
      return Promise.resolve().then(fn).then(function (res) {
        if (opts && opts.draft) S.draft = {}
        return reloadAfter().then(function () {
          S.busy = false; render()
          var msg = (res && res.message) || label
          var u = opts && opts.undo ? undoer(snap, label, res) : null
          toast(msg, u ? { undo: u } : {})
          if (opts && opts.after) { try { opts.after(res) } catch (e) { /* 通知失敗不影響已儲存的結果 */ } }
          drain()
        })
      }).catch(function (e) {
        S.busy = false
        if (!(e && e.cancelled)) fail(e)
        if (opts && opts.draft) { render(); drain(); return }
        return reloadAfter().then(function () { render(); drain() })
      })
    }
    // 依序跳出確認視窗（每一個都要按「套用」才繼續；任何一個取消 ⇒ false）
    function askAll(dialogs) {
      var chain = Promise.resolve(true)
      dialogs.forEach(function (d) {
        chain = chain.then(function (ok) {
          if (!ok) return false
          return openDialog({ title: d.title, html: d.html, buttons: [{ label: T('cancel'), value: false }, { label: d.okLabel || T('apply'), value: true, kind: d.danger ? 'danger' : 'primary' }] }).then(function (v) { return v === true })
        })
      })
      return chain
    }
    // 確認視窗的「通知預覽」：cfg.notifyPreview({ kind:'batch'|'draft'|'colselect'|'reset', keys, changes, action, skipped })→raw html（或 Promise；回空＝不顯示）；
    //   接在最後一個確認視窗後面（沒有確認視窗就補一個）。html 是 raw——動態值（人名、信件主旨…）host 要先 esc()。預覽失敗不擋儲存。
    function withPreview(dialogs, info) {
      if (!cfg.notifyPreview) return Promise.resolve(dialogs)
      return Promise.resolve().then(function () { return cfg.notifyPreview(info) }).catch(function () { return '' }).then(function (html) {
        if (!html) return dialogs
        var box = '<div class="mx-preview" data-testid="mx-preview"><b>' + esc(T('previewTitle')) + '</b><div>' + html + '</div></div>'
        var out = dialogs.slice()
        if (out.length) out[out.length - 1] = Object.assign({}, out[out.length - 1], { html: (out[out.length - 1].html || '') + box })
        else out.push({ title: T('previewTitle'), html: box, okLabel: T('apply') })
        return out
      })
    }
    // a.confirm(keys)：回確認視窗陣列，或回 Promise（例如先向伺服器要預覽）；回 null／false ⇒ 使用者在前置步驟取消、靜默放棄；丟錯 ⇒ 顯示錯誤、不執行
    function runAction(a, requested) {
      if (S.busy) return Promise.resolve()
      var sk = skippedOf(requested)
      var keys = requested.filter(canBatch)
      if (!keys.length) { toast(sk.length ? T('skippedAll') : T('noneSelected'), { error: true }); return Promise.resolve() }
      if (D && a.draft) {                                           // 草稿模式：只把改動記進草稿，不寫入、不跳確認（確認在「儲存」）
        return Promise.resolve().then(function () { return a.draft(keys) }).then(function (patch) {
          if (!patch) return
          keys.forEach(function (k) { stage(k, patch) })
          S.sel = {}
          render()
          toast(T('staged', { n: keys.length }) + (sk.length ? T('stagedSkipped', { k: sk.length }) : ''))
        }).catch(function (e) { if (!(e && e.cancelled)) fail(e) })
      }
      return Promise.resolve().then(function () { return a.confirm ? a.confirm(keys, sk) : [] }).then(function (dialogs) {
        if (dialogs === null || dialogs === false) return
        dialogs = (dialogs || []).slice()
        if (sk.length) {                                              // 確認視窗列出「已略過」的項目與原因
          if (dialogs.length) dialogs[0] = Object.assign({}, dialogs[0], { html: skippedHtml(sk) + (dialogs[0].html || '') })
          else dialogs.push({ title: T('partialTitle'), html: esc(T('partialBody', { n: keys.length })) + skippedHtml(sk), okLabel: T('apply') })
        }
        return withPreview(dialogs, { kind: a.previewKind || 'batch', keys: keys, action: a, skipped: sk }).then(function (ds) { dialogs = ds; return askAll(dialogs) }).then(function (ok) {
          if (!ok) return
          return perform(a.doneLabel || a.label, keys, function () { return a.run(keys, { confirmed: dialogs.length > 0, skipped: sk }) }, { undo: true })
        })
      }).catch(fail)
    }
    // 草稿：把 patch 併進該列的草稿；併完等於伺服器原值 ⇒ 自動移出草稿
    function stage(key, patch) {
      var raw = rawByKey(key)
      if (!raw) return
      var merged = Object.assign({}, S.draft[key] || {}, patch)
      if (D.same ? D.same(raw, merged) : Object.keys(merged).every(function (f) { return JSON.stringify(merged[f]) === JSON.stringify(raw[f]) })) delete S.draft[key]
      else S.draft[key] = merged
    }
    function stageCell(key, produce) {
      return Promise.resolve().then(produce).then(function (patch) { if (patch) { stage(key, patch); render() } else render() })
        .catch(function (e) { if (!(e && e.cancelled)) fail(e); render() })
    }
    function saveDraft() {
      if (S.busy || !dirtyCount()) return Promise.resolve()
      var changes = Object.keys(S.draft).map(function (k) { return { key: k, patch: S.draft[k], row: rawByKey(k) } }).filter(function (c) { return c.row })
      var keys = changes.map(function (c) { return c.key })
      return Promise.resolve().then(function () { return D.confirm ? D.confirm(changes) : [] }).then(function (dialogs) {
        if (dialogs === null || dialogs === false) return
        return withPreview(dialogs || [], { kind: 'draft', keys: keys, changes: changes }).then(function (ds) { dialogs = ds; return askAll(dialogs) }).then(function (ok) {
          if (!ok) return
          return perform(T('saved'), keys, function () { return D.save(changes, { confirmed: dialogs.length > 0 }) }, { undo: true, draft: true, after: function (res) { if (D.afterSave) D.afterSave(res, changes) } })
        })
      }).catch(fail)
    }
    function discardDraft() {
      if (!dirtyCount()) return
      S.draft = {}
      reloadAfter().then(render)                                    // 重新讀取：順便換成最新的版本
    }
    // C8 還原預設（單列）：草稿模式＝把 diff.draft(row) 併進草稿；立即模式＝diff.confirm（選填）→ diff.reset(row, ctx)（走 perform，失敗回到伺服器狀態）
    function resetRow(key) {
      var r = rowByKey(key)
      if (!DF || !r || !differs(r) || (DF.canReset && DF.canReset(r) === false)) return Promise.resolve()
      if (D && DF.draft) return stageCell(key, function () { return DF.draft(r) })
      if (!DF.reset) return Promise.resolve()
      var dialogs = DF.confirm ? (DF.confirm(r) || []) : []
      return askAll(dialogs).then(function (ok) {
        if (!ok) return
        return perform(rn(r) + '：' + T('diffReset'), [key], function () { return DF.reset(r, { confirmed: dialogs.length > 0 }) })
      })
    }
    // C11 欄頭選取（on＝true 全開／false 全關）；val＝chips 欄的項目值。略過的列（不能批次／該格鎖住／不顯示）一律不動並在提示裡計數。
    function colSelect(c, val, on) {
      var targets = colTargets(c)
      var all = visKeys().length
      var skipped = all - targets.length
      if (!targets.length) { toast(T('colSelNone'), { error: true }); return render() }
      var cs = c.colSelect
      if (D && cs.draft) {
        return Promise.resolve().then(function () {
          var n = 0
          return targets.reduce(function (p, k) {
            return p.then(function () { return cs.draft(rowByKey(k), on, val) }).then(function (patch) { if (patch) { stage(k, patch); n++ } })
          }, Promise.resolve()).then(function () { render(); toast(T('colSelStaged', { n: n }) + (skipped ? T('colSelSkipped', { k: skipped }) : '')) })
        }).catch(function (e) { if (!(e && e.cancelled)) fail(e); render() })
      }
      if (!cs.run) { render(); return Promise.resolve() }
      return runAction({ id: 'colsel:' + c.id, label: (c.label || '') + (on ? '：全部勾選' : '：全部取消'), previewKind: 'colselect',
        confirm: function (keys) { return cs.confirm ? cs.confirm(keys, on, val) : [] },
        run: function (keys, ctx) { return cs.run(keys, on, val, ctx) } }, targets)
    }
    // 單格操作：column.confirm(row, value) 可回確認視窗（例如關閉「重要」告警）；set／toggle 丟出 {cancelled:true} ⇒ 靜默放棄、畫面回原狀
    function runCell(label, key, col, r, value, fn) {
      if (D) return Promise.resolve()                                // 草稿模式不走這條（見 stageCell）
      var dialogs = col.confirm ? (col.confirm(r, value) || []) : []
      return askAll(dialogs).then(function (ok) {
        if (!ok) return render()
        return perform(label, [key], function () { return fn({ confirmed: dialogs.length > 0 }) })
      })
    }
    // 格子修改的統一入口：{kind: switch|select|input|chip, key, col, value, val(chip 的項目)}。寫入中 ⇒ 排隊（不丟）；欄位被鎖（disabled／readonly）⇒ 放棄。
    function edit(e) {
      if (dead) return Promise.resolve()
      if (S.busy) { Q.push(e); return Promise.resolve() }
      return doEdit(e)
    }
    function doEdit(e) {
      var col = e.col, r = rowByKey(e.key)
      if (!col || !r) return render()                                   // 排隊期間那一列不見了（別人刪了／重載後不存在）
      if (locked(col, r)) return render()                              // 排隊期間欄位被鎖了
      if (e.kind === 'chip') {
        if (D && col.draft) return stageCell(e.key, function () { return col.draft(r, e.val, e.value) })
        return runCell(rn(r) + '：' + T('updated'), e.key, col, r, e.value, function (ctx) { return col.toggle(r, e.val, e.value, ctx) })
      }
      var v = e.value
      if (e.kind === 'input') {
        if (col.type === 'number') {
          if (v === '' || v == null) v = null
          else { v = Number(v); if (!isFinite(v)) { toast(T('invalidNumber'), { error: true }); return render() } }
        }
        var bad = col.validate ? col.validate(v, r) : null
        if (bad) { toast(String(bad), { error: true }); return render() }
        if (String(v == null ? '' : v) === String(col.get ? (col.get(r) == null ? '' : col.get(r)) : '')) return render()      // 沒改
      }
      if (D && col.draft) return stageCell(e.key, function () { return col.draft(r, v) })
      var label = e.kind === 'switch' ? rn(r) + '：' + (v ? T('turnedOn') : T('turnedOff')) : rn(r) + '：' + T('updated')
      return runCell(label, e.key, col, r, v, function (ctx) { return col.set(r, v, ctx) })
    }
    function drain() {
      if (dead || S.busy) return
      var e = Q.shift()
      if (!e) return
      Promise.resolve(doEdit(e)).then(function () { if (!S.busy) drain() })
    }

    // ── 事件 ──
    function onClick(e) {
      if (dead) return
      var t = e.target.closest('[data-mx]')
      if (!t || !el.contains(t)) return
      var m = t.getAttribute('data-mx')
      if (m === 'sel') { S.shift = e.shiftKey; return }
      if (m === 'gsel' || m === 'select' || m === 'search' || m === 'selall' || m === 'gsel-filter' || m === 'input' || m === 'csel') return
      if (m === 'help') {                                                    // C6：只讀的說明視窗，寫入中也能開
        var hr = rowByKey(t.getAttribute('data-key'))
        var hh = hr ? helpHtml(helpOf(hr), LB) : ''
        if (hh) openDialog({ title: T('helpTitle', { name: rn(hr) }), html: hh, buttons: [{ label: T('close'), value: null, kind: 'primary' }] })
        return
      }
      var cellKinds = { 'switch': 1, chip: 1 }
      if (S.busy && m !== 'gtoggle' && !cellKinds[m]) return
      var key = t.getAttribute('data-key'), col = cols.filter(function (c) { return c.id === t.getAttribute('data-col') })[0]
      if (m === 'gtoggle') {
        if (e.target.closest('button,input,select')) return
        var g = t.getAttribute('data-g'); S.collapsed[g] = !S.collapsed[g]; render(); return
      }
      if (m === 'dreset') { resetRow(key); return }
      if (m === 'ddiscard') { discardDraft(); return }
      if (m === 'dsave') { saveDraft(); return }
      if (m === 'switch') {
        var r = rowByKey(key)
        if (!col || !r || locked(col, r)) return
        edit({ kind: 'switch', key: key, col: col, value: !col.get(r) })                                  // 目標值在點下去的當下決定（排隊也照這個值）
        return
      }
      if (m === 'chip') {
        var r2 = rowByKey(key), val = t.getAttribute('data-val')
        if (!col || !r2 || locked(col, r2)) return
        var cur = col.get(r2)
        edit({ kind: 'chip', key: key, col: col, val: val, value: !(cur == null ? true : cur.indexOf(val) >= 0) })
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
        if (a2 && ks.length && !(batch.groupActionsEnabled === false)) runAction(a2, ks)
      }
    }
    function onChange(e) {
      if (dead) return
      var t = e.target.closest('[data-mx]')
      if (!t) return
      var m = t.getAttribute('data-mx'), key = t.getAttribute('data-key')
      if (m === 'sel') {
        if (S.shift && S.last) {
          var ks = visKeys(), i = ks.indexOf(S.last), j = ks.indexOf(key)
          if (i >= 0 && j >= 0) for (var x = Math.min(i, j); x <= Math.max(i, j); x++) if (canBatch(ks[x])) S.sel[ks[x]] = t.checked
        } else S.sel[key] = t.checked
        S.last = key; render(); return
      }
      if (m === 'gsel') { var g = t.getAttribute('data-g'); view().filter(function (x) { return x.g === g })[0].rows.forEach(function (r) { if (eligibleOf(r).ok) S.sel[rk(r)] = t.checked }); render(); return }
      if (m === 'selall') { visKeys().forEach(function (k) { if (canBatch(k)) S.sel[k] = t.checked }); render(); return }
      if (m === 'gsel-filter') { S.g = t.value; render(); return }
      if (m === 'csel') {
        var cc = cols.filter(function (c) { return c.id === t.getAttribute('data-col') })[0]
        if (!cc || !cc.colSelect) { render(); return }
        if (S.busy) { render(); return }
        colSelect(cc, t.getAttribute('data-val'), t.checked)
        return
      }
      if (m === 'select' || m === 'input') {
        var col = cols.filter(function (c) { return c.id === t.getAttribute('data-col') })[0], r = rowByKey(key)
        if (!col || !r || locked(col, r)) { render(); return }
        edit({ kind: m, key: key, col: col, value: t.value })
      }
    }
    function onInput(e) {
      if (dead) return
      var t = e.target
      if (t.getAttribute && t.getAttribute('data-mx') === 'search') { S.q = t.value.trim(); render() }
    }
    el.addEventListener('click', onClick)
    el.addEventListener('change', onChange)
    el.addEventListener('input', onInput)
    // 離開警告：有未儲存的草稿時，關閉／重新整理頁面（beforeunload）與點站內連結都要攔
    function onBeforeUnload(e) {
      if (dead || !dirtyCount()) return
      e.preventDefault()
      e.returnValue = ''
      return ''
    }
    function onDocClick(e) {
        if (dead || !dirtyCount() || e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
        var a = e.target && e.target.closest ? e.target.closest('a[href]') : null
        if (!a || (a.target && a.target !== '_self') || a.hasAttribute('download')) return
        var h = a.getAttribute('href') || ''
        if (!h || h.charAt(0) === '#' || /^(javascript|mailto|tel):/i.test(h)) return
        e.preventDefault()
        e.stopPropagation()
        openDialog({ title: T('leaveTitle'), html: esc(T('leaveBody', { n: '\u0001' })).replace('\u0001', '<b>' + dirtyCount() + '</b>'), buttons: [{ label: T('stay'), value: false, kind: 'primary' }, { label: T('leave'), value: true, kind: 'danger' }] }).then(function (v) {
          if (v === true) { S.draft = {}; location.href = a.href }
        })
    }
    if (D) {
      window.addEventListener('beforeunload', onBeforeUnload)
      document.addEventListener('click', onDocClick, true)
    }
    // 拆掉：移除本元件加的所有監聽、清空容器；之後 api 都是空操作（頁面切換／重新 mount 前呼叫，避免舊實例的監聽留在 window／document 上）
    function destroy() {
      if (dead) return
      dead = true
      Q.length = 0
      S.draft = {}
      el.removeEventListener('click', onClick)
      el.removeEventListener('change', onChange)
      el.removeEventListener('input', onInput)
      window.removeEventListener('beforeunload', onBeforeUnload)
      document.removeEventListener('click', onDocClick, true)
      el.innerHTML = ''
      el.classList.remove('mx-root', 'mx-busy')
    }

    render()
    var api = {
      setRows: function (rows) { S.rows = rows || []; render() },
      refresh: function () { return reloadAfter().then(render) },
      selection: selKeys,
      clearSelection: function () { S.sel = {}; render() },
      toast: toast,
      state: function () { return S },
      perform: perform,
      stage: function (key, patch) { if (D) { stage(key, patch); render() } },
      draftCount: dirtyCount,
      discard: discardDraft,
      save: saveDraft,
      destroy: destroy,
    }
    return api
  }

  global.SettingsMatrix = global.MxTable = { mount: mount, openDialog: openDialog, closeDialog: closeDialog, toast: toast, esc: esc,
    registerEligibleOverride: registerEligibleOverride, raw: raw, defaultLabels: DEFAULT_LABELS, eligibleOverrides: eligibleOverrides, defaultEligible: defaultEligible,
    helpParts: helpParts, helpHtml: helpHtml, sourceInfo: sourceInfo }
})(window)
