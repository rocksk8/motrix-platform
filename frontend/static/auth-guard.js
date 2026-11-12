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
  // （預覽時 notif.js／sidebar.js 也讓位，不會用到下面的啟動資料；呼叫端一律寫 `window.motrixBootFetch || fetch`）
  if (window.MOTRIX_PREVIEW) return;
  // ── 啟動資料（2026-11-13「外網載入效能」第二階段）────────────────────────────────────────────
  // 原本每一頁載入都各自打 auth/me、platform/menu、modules/availability、build-info、approval-queue/count、notifications/mine、
  // reads/module-counts、system/branding、online-users、totp/status…（外網每支約 1 s）。現在這支守門腳本在驗證登入（`auth/me`，放行頁面只看它）的**同時**並行打 **一支** `GET /api/bootstrap`
  // 取其餘啟動資料（不擋首繪），結果放在 `window.MotrixBoot`（Promise → bootstrap JSON；null＝不可用，各處退回打原端點）。
  //   window.motrixBootFetch(url, opts)：與 fetch 同簽章。**第一次**要某個啟動區段時（且在 20 秒內、同一個 token）回一個由 bootstrap 內容
  //     組成的 Response（r.ok／r.json() 與原端點完全相同），否則就是真的 fetch ⇒ 呼叫端只要把 fetch 換成它，其餘邏輯不用動；
  //     之後的重抓（輪詢、focus、reads-changed）一律是真的請求，不會拿到舊資料。
  //   window.motrixBoot(name)：Promise → 區段內容或 undefined（沒有／過期／已用過 ⇒ 呼叫端自己打原端點）。
  // 內容與原端點逐欄相同（後端是直接呼叫原端點的處理函式；守門 tests/test_bootstrap_bundle_2026_11_13.py）。
  var BOOT_TTL_MS = 20000;
  // 原端點路徑 → [bootstrap 區段, 這一頁最多可由 bootstrap 供應幾次（同一資料有兩個載入點的給 2）]
  var BOOT_SECTIONS = {
    '/api/auth/me': ['me', 2], '/api/platform/menu': ['menu', 1], '/api/system/branding': ['branding', 2],
    '/api/build-info': ['buildInfo', 1], '/api/system/bonus-module-status': ['bonusModuleStatus', 1],
    '/api/system/modules/availability': ['moduleAvailability', 1], '/api/approval-queue/count': ['approvalCount', 2],
    '/api/notifications/mine': ['notifications', 1], '/api/reads/module-counts': ['moduleCounts', 1],
    '/api/online-users': ['onlineUsers', 1], '/api/auth/totp/status': ['totp', 1]
  };
  var boot = { data: null, at: 0, token: '', hdr: null, used: {} };
  var bootResolve;
  window.MotrixBoot = new Promise(function (res) { bootResolve = res; });
  function bootValue(name, token) {
    var d = boot.data;
    if (!d || token !== boot.token || Date.now() - boot.at > BOOT_TTL_MS) return undefined;
    var v = d[name];
    return v === null ? undefined : v;
  }
  // 使用者動作造成的重抓（簽核處理完、標已讀…）一律要拿真資料：事件一來，整份啟動資料作廢
  if (window.addEventListener) {
    ['motrix:approval-changed', 'motrix:reads-changed', 'motrix:item-read', 'motrix:item-read-failed'].forEach(function (ev) {
      window.addEventListener(ev, function () { boot.data = null; });
    });
  }
  window.motrixBoot = function (name) {
    return window.MotrixBoot.then(function () {
      var tok = boot.token;
      var limit = 1;
      Object.keys(BOOT_SECTIONS).forEach(function (k) { if (BOOT_SECTIONS[k][0] === name) limit = BOOT_SECTIONS[k][1]; });
      if ((boot.used[name] || 0) >= limit) return undefined;
      var v = bootValue(name, tok);
      if (v !== undefined) boot.used[name] = (boot.used[name] || 0) + 1;
      return v;
    });
  };
  window.motrixBootFetch = function (url, opts) {
    var m = BOOT_SECTIONS[url];
    var method = String((opts && opts.method) || 'GET').toUpperCase();
    var auth = opts && opts.headers && (opts.headers.Authorization || opts.headers.authorization);
    if (!m || method !== 'GET' || !auth || !window.MotrixBoot) return fetch(url, opts);
    return window.MotrixBoot.then(function () {
      var v = (auth === 'Bearer ' + boot.token && (boot.used[m[0]] || 0) < m[1]) ? bootValue(m[0], boot.token) : undefined;
      if (v === undefined) return fetch(url, opts);
      boot.used[m[0]] = (boot.used[m[0]] || 0) + 1;
      // 橫幅標頭（授權／本公司資料設定）原本由真的回應帶來；第一次供應時補上同樣的標頭，notif.js 的橫幅邏輯才不會漏掉
      try { if (window.motrixApplyBanners && boot.hdr) window.motrixApplyBanners(boot.hdr); } catch (e) {}
      return new Response(JSON.stringify(v), { status: 200, headers: { 'Content-Type': 'application/json' } });
    });
  };

  var raw = null;
  try { raw = localStorage.getItem('motrix_session'); } catch (e) {}
  var session = null;
  try { session = raw ? JSON.parse(raw) : null; } catch (e) { session = null; }

  // frontend/index.html 用 static/auth-guard.js（無 ../），
  // frontend/pages/*.html 用 ../static/auth-guard.js（有 /pages/ 這一層）
  var loginPath = location.pathname.indexOf('/pages/') >= 0 ? 'login.html' : 'pages/login.html';
  var licensePath = location.pathname.indexOf('/pages/') >= 0 ? 'license-required.html' : 'pages/license-required.html';

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
    bootResolve(null);
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

  var authHeaders = { Authorization: 'Bearer ' + session.token };

  // 與改版前 `/api/auth/me` 的處理逐字相同（ok ⇒ 放行；402 ⇒ 授權說明頁；其他 ⇒ 清 session 轉登入頁）
  function handleStatus(r) {
    clearTimeout(timeoutId);
    if (r.ok) {
      forgetReturn();
      reveal();
    } else if (r.status === 402) {
      // 授權閘門（helpers/licensing.py，T80）：這不是「未登入」——不清 session、不轉登入頁（否則使用者以為被登出、
      // 重新登入又被擋，永遠看不到原因），導向「授權無法使用」說明頁。
      location.replace(licensePath);
    } else {
      try { localStorage.removeItem('motrix_session'); } catch (e) {}
      rememberReturn();
      location.replace(loginPath);
    }
  }
  function onNetworkError() {
    // 網路暫時錯誤（非 401），不是「未登入」——放行，避免整頁永遠白屏，
    // 後續各頁面自己的 API 呼叫會各自處理失敗情形
    clearTimeout(timeoutId);
    reveal();
  }
  function legacyMe() {
    return fetch('/api/auth/me', { headers: authHeaders }).then(handleStatus).catch(onNetworkError);
  }

  // 啟動資料等不到就不等：6 秒後讓 MotrixBoot 變 null，各處退回打原端點（與改版前一樣）
  var bootTimer = setTimeout(function () { bootResolve(null); }, 6000);

  // 首繪不可以比改版前慢（B1）：**放行只看快的 `auth/me`**（與改版前逐字相同的路徑），`/api/bootstrap` 同時並行發出、
  // 只負責供應資料——它慢（11 個區段）不會擋住頁面顯示；它失敗（401／403／428／404／5xx／逾時）只是 MotrixBoot＝null、各處退回打原端點。
  fetch('/api/bootstrap', { headers: authHeaders })
    .then(function (r) {
      if (r.status !== 200) { clearTimeout(bootTimer); bootResolve(null); return; }
      return r.json().then(function (d) {
        if (!d || !d.me) throw new Error('bootstrap without me');
        boot.data = d; boot.at = Date.now(); boot.token = session.token;
        boot.hdr = { license: r.headers.get('X-Motrix-License'), setup: r.headers.get('X-Motrix-Company-Setup') };
        clearTimeout(bootTimer); bootResolve(d);
      });
    })
    .catch(function () { clearTimeout(bootTimer); bootResolve(null); });
  legacyMe();
})();
