/* motrix-error.js — 把「讀取失敗／儲存失敗」變成給人看的一句話（2026-11-13）。
 *
 * 為什麼有這支：
 *   ① 頁面載入失敗時各頁自己 `catch(e){}`，畫面停在「暫無紀錄」「無符合結果」，使用者以為是真的沒資料
 *      ⇒ 現在由頁面把 loadText() 的結果放進錯誤條，旁邊給「重試」。
 *   ② FastAPI 的 422 回的 `detail` 是**陣列**（每個欄位一筆物件），直接 `'儲存失敗：' + err.detail` 會變成
 *      「[object Object]」⇒ detailText() 把它轉成一句話，不管給它什麼都不會吐出 [object Object]。
 *
 * 用法（頁面要在 Alpine 之前載入，放在 auth-guard.js 後面）：
 *   MotrixError.loadText(r.status)            // 讀取失敗（給狀態碼，或 fetch 丟出的例外）
 *   MotrixError.detailText(body.detail, r.status)  // 儲存失敗（給後端 detail）
 *   MotrixError.sessionExpired()              // 401：登入過期 ⇒ 登出並導回登入頁（不顯示錯誤訊息）
 *
 * 使用者看到的訊息一律不含 HTTP 狀態碼（UX 規範：只給白話原因＋重試）；狀態碼只用來「挑哪一句白話」。
 */
(function () {
  function str(v) { return typeof v === 'string' ? v.trim() : '' }

  // pydantic 的英文訊息只翻最常見的幾句；翻不到就原樣保留（至少是可讀的字）。
  var EN = {
    'field required': '必填', 'Field required': '必填',
    'Input should be a valid string': '要填文字', 'Input should be a valid integer': '要填整數', 'Input should be a valid number': '要填數字',
    'Input should be a valid boolean': '要選是或否', 'Input should be a valid list': '格式不對', 'Input should be a valid dictionary or object to extract fields from': '格式不對'
  };

  function itemText(x) {
    if (typeof x === 'string') return str(x);
    if (!x || typeof x !== 'object') return '';
    var msg = str(x.msg) || str(x.message) || str(x.detail);
    msg = msg.replace(/^Value error,\s*/i, '');
    if (EN[msg]) msg = EN[msg];
    var loc = Array.isArray(x.loc) ? x.loc.filter(function (p) { return p !== 'body' && p !== 'query' && p !== 'path' && typeof p !== 'number'; }) : [];
    if (msg && loc.length) return loc.join('.') + '：' + msg;
    return msg;
  }

  // 後端 detail（字串｜陣列｜物件｜undefined）→ 一句話。永遠不會回 "[object Object]"。
  function detailText(detail, status) {
    var s = str(detail);
    if (s) return s;
    if (Array.isArray(detail)) {
      var parts = detail.map(itemText).filter(Boolean);
      if (parts.length) return parts.join('；');
    } else if (detail && typeof detail === 'object') {
      var one = itemText(detail);
      if (one) return one;
    }
    return '伺服器沒有說明原因，請稍後再試。';
  }

  // 讀取失敗 → 一句話（hichan-6 審查＋UX 規範：畫面不顯示 HTTP 狀態碼，代碼只進 console 給回報用）。
  // x＝HTTP 狀態碼（數字），或 fetch 丟出的例外（連不上系統）。
  function loadText(x) {
    try { console.warn('[MotrixError] load failed:', x); } catch (e) { /* ignore */ }
    if (typeof x !== 'number') return '連不上系統，請檢查網路後再試。';
    if (x === 401) return '登入已過期，請重新登入。';      // 頁面應改呼叫 sessionExpired()，這句只是保險
    if (x === 403) return '你沒有權限查看這一頁。';
    return '載入失敗，請重新整理，仍然失敗請聯絡系統管理者。';
  }

  // 登入過期（401）：與各頁既有的 logout() 同一套——通知伺服器登出（盡力而為）、清掉本機 session、回登入頁。
  function sessionExpired() {
    var token = '';
    try { token = (JSON.parse(localStorage.getItem('motrix_session') || '{}') || {}).token || ''; } catch (e) { token = ''; }
    if (token) { try { fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + token } }).catch(function () {}); } catch (e) { /* ignore */ } }
    try { localStorage.removeItem('motrix_session'); } catch (e) { /* ignore */ }
    location.href = (location.pathname.indexOf('/pages/') >= 0 ? '' : 'pages/') + 'login.html';
  }

  window.MotrixError = { detailText: detailText, loadText: loadText, sessionExpired: sessionExpired };
})();
