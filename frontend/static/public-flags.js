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
 */
;(function () {
  function session() { try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) { return {} } }

  async function one(names, token, timeoutMs) {
    var ctl = typeof AbortController === 'function' ? new AbortController() : null
    var timer = ctl && timeoutMs ? setTimeout(function () { ctl.abort() }, timeoutMs) : null
    try {
      var r = await fetch('/api/settings-center/public?groups=' + names.join(','),
        Object.assign({ headers: { Authorization: 'Bearer ' + token } }, ctl ? { signal: ctl.signal } : {}))
      if (!r.ok) return null
      var d = await r.json()
      return d && d.groups && typeof d.groups === 'object' ? d.groups : null
    } catch (e) { return null } finally { if (timer) clearTimeout(timer) }
  }

  async function read(names, opt) {
    opt = opt || {}
    var token = opt.token || session().token
    if (!token || !names || !names.length) return {}
    var all = await one(names, token, opt.timeoutMs || 8000)
    if (all) return all
    if (names.length === 1) return {}                      // 單一群組已經失敗：沒有東西可以再拆
    var out = {}
    var parts = await Promise.all(names.map(function (g) { return one([g], token, opt.timeoutMs || 8000) }))
    parts.forEach(function (p) { if (p) Object.keys(p).forEach(function (k) { out[k] = p[k] }) })
    return out
  }

  window.MotrixPublicFlags = { read: read }
})()
