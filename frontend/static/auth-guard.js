/* auth-guard.js — 同步防閃現登入驗證（2026-08-27）
 *
 * 必須以非 defer/非 async 的 <script src="..."> 方式，放在每個頁面 <head> 最前面
 * （Alpine CDN <script defer ...> 之前），在瀏覽器有機會解析/繪製 <body> 任何內容
 * 之前執行，才能真正擋下「session 過期時先閃過系統畫面才跳回登入頁」的問題。
 *
 * Alpine 的 [x-cloak] 只解決「Alpine 掛載前」的閃現，不會等 x-init="init()" 裡
 * await fetch('/api/auth/me') 這種非同步驗證完成才顯示內容——這支腳本才是真正
 * 在渲染前就先隱藏整頁、驗證完才顯示的機制。各頁面既有的 init() 內建檢查不用移除，
 * 當作備援（例如使用者清掉 localStorage 又手動改網址進來的極端情況）。
 */
(function () {
  var raw = null;
  try { raw = localStorage.getItem('motrix_session'); } catch (e) {}
  var session = null;
  try { session = raw ? JSON.parse(raw) : null; } catch (e) { session = null; }

  // frontend/index.html 用 static/auth-guard.js（無 ../），
  // frontend/pages/*.html 用 ../static/auth-guard.js（有 /pages/ 這一層）
  var loginPath = location.pathname.indexOf('/pages/') >= 0 ? 'login.html' : 'pages/login.html';

  if (!session || !session.token) {
    location.replace(loginPath);
    return;
  }

  var style = document.createElement('style');
  style.id = 'auth-guard-style';
  style.textContent = 'html{visibility:hidden}';
  document.head.appendChild(style);

  var revealed = false;
  function reveal() {
    if (revealed) return;
    revealed = true;
    var s = document.getElementById('auth-guard-style');
    if (s) s.remove();
  }

  // 5 秒安全逾時：伺服器無回應時也要放行，不能讓使用者永遠卡在空白頁
  var timeoutId = setTimeout(reveal, 5000);

  fetch('/api/auth/me', { headers: { Authorization: 'Bearer ' + session.token } })
    .then(function (r) {
      clearTimeout(timeoutId);
      if (r.ok) {
        reveal();
      } else {
        try { localStorage.removeItem('motrix_session'); } catch (e) {}
        location.replace(loginPath);
      }
    })
    .catch(function () {
      // 網路暫時錯誤（非 401），不是「未登入」——放行，避免整頁永遠白屏，
      // 後續各頁面自己的 API 呼叫會各自處理失敗情形
      clearTimeout(timeoutId);
      reveal();
    });
})();
