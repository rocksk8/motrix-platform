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
  // 模組建構器的即時預覽（BUILDER-UX §3.3，custom-records.html?preview=1）：不驗證、不打 API、不轉登入頁
  if (window.MOTRIX_PREVIEW) return;
  var raw = null;
  try { raw = localStorage.getItem('motrix_session'); } catch (e) {}
  var session = null;
  try { session = raw ? JSON.parse(raw) : null; } catch (e) { session = null; }

  // frontend/index.html 用 static/auth-guard.js（無 ../），
  // frontend/pages/*.html 用 ../static/auth-guard.js（有 /pages/ 這一層）
  var loginPath = location.pathname.indexOf('/pages/') >= 0 ? 'login.html' : 'pages/login.html';

  // 轉去登入頁之前記下「原本要去的網址」（含 ?q=／?id= 等查詢字串），登入成功後 login.html 會回到它
  // （通知連結、信件連結在未登入時打開，登入後才會落在原本那一頁；否則一律掉到首頁）。
  // sessionStorage＝只限這個分頁；login.html 端會再驗證成「同站路徑」才採用。
  // 硬化（第46班）：① 框架內的頁面（window.top !== window）不寫——sessionStorage 與最上層文件共用，框架不該改寫分頁的回去目標；
  // ② 太長（> 2000 字）不寫；③ 存成 JSON {p: 路徑, t: 時間戳}：login.html 超過 30 分鐘就不採用（放著不管的過期分頁，換人登入時不會被帶到上一位的最後頁面）。
  function rememberReturn() {
    try {
      if (window.top && window.top !== window) return;
      if (/\/login(-qr-approve)?\.html$/.test(location.pathname)) return;
      var p = location.pathname + location.search + location.hash;
      if (p.length > 2000) return;
      sessionStorage.setItem('motrix_return_to', JSON.stringify({ p: p, t: Date.now() }));
    } catch (e) {}
  }
  // 已登入的頁面正常載入 ⇒ 任何殘留的回去目標都已過時（明確登出前一定有過這種載入）：清掉
  function forgetReturn() { try { sessionStorage.removeItem('motrix_return_to'); } catch (e) {} }

  if (!session || !session.token) {
    rememberReturn();
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
        forgetReturn();
        reveal();
      } else {
        try { localStorage.removeItem('motrix_session'); } catch (e) {}
        rememberReturn();
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
