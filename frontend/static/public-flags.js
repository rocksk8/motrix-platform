/* public-flags.js — 一次讀多個「公開設定群組」，其中某個群組讀不到時不拖垮其他群組（T61／04 稽核）。
 *
 * GET /api/settings-center/public?groups=a,b,c 只要有一個群組是 hidden／未登錄（404）或需要設定權限（403），整個呼叫就失敗。
 * 頁面要同時看好幾個旗標（版面、自訂欄位、自訂按鈕…）：一個群組被藏起來不能讓其他旗標跟著讀不到（版面編輯器就會無聲消失）。
 *
 *   MotrixPublicFlags.read(['builder_layout', 'builder_custom_fields'], { token, timeoutMs })
 *     ⇒ Promise<{ [group]: { field: value, … } }>   讀不到的群組不在結果裡（呼叫端把「沒有」當旗標關閉）
 *
 * 一般情況（全部讀得到）＝**一個請求**，網址與先前相同（群組名以逗號連接，順序照傳入）。
 * 只有合併請求失敗（非 2xx 或斷線）才逐組重試；單一群組的請求各自失敗各自略過。永不丟例外。
 *
 * T87（c2_personal_prefs 偶發）：**暫時性失敗**（逾時／斷線／5xx／408／429）不再靜默當成「旗標全關」——
 *   1. 每個請求最多再試 2 次（間隔 0.4 s、0.8 s）；404／403 是「這個群組不給你看」，不重試。整次 read 有總期限（預設 10 s，opt.deadlineMs）：
 *      逾期就不再重試，單次請求的逾時也不會超過剩餘時間（伺服器卡住時最壞約 10 s，不是 3×8 s 再乘上逐組重試）。
 *      合併請求是暫時性失敗（伺服器在掙扎）⇒ **不再逐組補打**（不放大負載），整批當作讀取失敗並通知；只有 404／403（某群組不給看）才逐組退路。
 *   2. 重試後仍是暫時性失敗 ⇒ 結果照舊不含該群組（呼叫端行為不變），但**使用者看得到**：
 *      window.MotrixFlagsFailed 記下群組（去重）、發 `motrix:flags-failed` 事件、跳一則提示（每頁一次）：有 MotrixUI.toast 用它；
 *      沒載入 ui.js 的頁面（報價單清單等 13 頁）改用內建的固定位置提示節點（role=alert、約 6 秒後消失）。
 */
;(function () {
  if (window.MotrixPublicFlags) return                    // 同一頁引入兩次時只啟用第一份（各自的 warned 旗標會讓提示出現兩次）
  function session() { try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) { return {} } }

  var RETRIES = 2
  function sleep(ms) { return new Promise(function (res) { setTimeout(res, ms) }) }

  // ⇒ { groups: {…}|null, transient: bool }；transient＝值得再試（逾時／斷線／5xx／408／429）
  async function once(names, token, timeoutMs) {
    var ctl = typeof AbortController === 'function' ? new AbortController() : null
    var timer = ctl && timeoutMs ? setTimeout(function () { ctl.abort() }, timeoutMs) : null
    try {
      var r = await (window.motrixBootFetch || fetch)('/api/settings-center/public?groups=' + names.join(','),
        Object.assign({ headers: { Authorization: 'Bearer ' + token } }, ctl ? { signal: ctl.signal } : {}))
      if (!r.ok) return { groups: null, transient: r.status >= 500 || r.status === 408 || r.status === 429 }
      var d = await r.json()
      return d && d.groups && typeof d.groups === 'object' ? { groups: d.groups, transient: false } : { groups: null, transient: false }
    } catch (e) { return { groups: null, transient: true } } finally { if (timer) clearTimeout(timer) }
  }

  // st.transientFail＝最後一次仍是暫時性失敗
  async function one(names, token, timeoutMs, st, deadline) {
    var res
    for (var i = 0; i <= RETRIES; i++) {
      var left = deadline - Date.now()
      res = await once(names, token, Math.max(500, Math.min(timeoutMs, left)))
      if (res.groups) return res.groups
      if (!res.transient) break
      if (i < RETRIES) {
        var wait = 400 * (i + 1)
        if (Date.now() + wait >= deadline) break                 // 總期限到了：不再重試
        await sleep(wait)
      }
    }
    st.transientFail = !!res.transient
    return null
  }

  var FAIL_TEXT = '部分設定讀取失敗，相關功能暫時關閉；請重新整理頁面'
  var warned = false
  // 沒有 ui.js 的頁面用的備援提示：固定在畫面下方、role=alert（讀屏會念）、約 6 秒後自己消失；沒有 document 的環境（測試／worker）略過
  function showNotice(text) {
    if (typeof document === 'undefined' || !document.body || typeof document.createElement !== 'function') return
    var el = document.createElement('div')
    el.setAttribute('role', 'alert')
    el.setAttribute('data-testid', 'flags-failed-notice')
    el.textContent = text
    el.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:99999;width:max-content;max-width:90vw;padding:10px 16px;border-radius:8px;' +
      'background:#991B1B;color:#fff;font:13px/1.5 system-ui,sans-serif;box-shadow:0 4px 16px rgba(0,0,0,.25)'
    document.body.appendChild(el)
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el) }, 6000)
  }
  function notifyFailed(names) {
    var seen = window.MotrixFlagsFailed || []
    window.MotrixFlagsFailed = seen.concat(names.filter(function (n) { return seen.indexOf(n) < 0 }))
    try {
      if (typeof CustomEvent === 'function' && typeof window.dispatchEvent === 'function') window.dispatchEvent(new CustomEvent('motrix:flags-failed', { detail: { groups: names } }))
    } catch (e) { /* 通知失敗不影響讀取 */ }
    if (warned) return
    warned = true
    try {
      if (window.MotrixUI && typeof window.MotrixUI.toast === 'function') window.MotrixUI.toast(FAIL_TEXT, { kind: 'error' })
      else showNotice(FAIL_TEXT)
    } catch (e) { /* 同上 */ }
  }

  async function read(names, opt) {
    opt = opt || {}
    var token = opt.token || session().token
    if (!token || !names || !names.length) return {}
    var timeoutMs = opt.timeoutMs || 8000
    var deadline = Date.now() + (opt.deadlineMs || 10000)
    var st = {}
    var all = await one(names, token, timeoutMs, st, deadline)
    if (all) return all
    if (names.length === 1 || st.transientFail) {          // 單一群組已經失敗，或伺服器在掙扎（暫時性）：不拆、不再補打
      if (st.transientFail) notifyFailed(names.slice())
      return {}
    }
    var out = {}, failed = []
    var parts = await Promise.all(names.map(function (g) {
      var s = {}
      return one([g], token, timeoutMs, s, deadline).then(function (p) { if (!p && s.transientFail) failed.push(g); return p })
    }))
    parts.forEach(function (p) { if (p) Object.keys(p).forEach(function (k) { out[k] = p[k] }) })
    if (failed.length) notifyFailed(failed)
    return out
  }

  window.MotrixPublicFlags = { read: read }
})()
