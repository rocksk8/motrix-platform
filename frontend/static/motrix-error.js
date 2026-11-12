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
    return status ? '伺服器回應錯誤（HTTP ' + status + '）' : '伺服器沒有說明原因';
  }

  // 讀取失敗 → 一句話。x＝HTTP 狀態碼（數字），或 fetch 丟出的例外（連不上伺服器）。
  function loadText(x) {
    if (typeof x !== 'number') return '連不上伺服器，請確認網路連線。';
    if (x === 401) return '登入已過期，請重新登入。';
    if (x === 403) return '你沒有權限查看這份資料。';
    if (x === 404) return '找不到這份資料（頁面與伺服器版本可能不一致）。';
    if (x === 429) return '操作太頻繁，請稍後再試。';
    if (x >= 500) return '伺服器暫時無法回應（HTTP ' + x + '）。';
    return '資料讀取失敗（HTTP ' + x + '）。';
  }

  window.MotrixError = { detailText: detailText, loadText: loadText };
})();
