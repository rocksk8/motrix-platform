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
  // T86 #10：案件管理頁首屏另外要的 8 支「登入即可讀」小請求（onepipe 旗標、版面與規則設定群組、利潤門檻、可選使用者、公司公開資料、
  // 清單排序偏好、兩支承攬商下拉）也併進同一支：只有這一頁才多帶 `?page=case`、才登記這些路徑（其他頁網址不在表內 ⇒ 照舊直接 fetch、不多等 bootstrap）。
  // 路徑要與後端 routers/bootstrap.PAGE_SECTIONS["case"] 逐字相同（守門：tests/test_bootstrap_page_case_2026_11_14.py）。
  var BOOT_PAGE = /\/case-management\.html$/.test(location.pathname) ? 'case' : '';
  if (BOOT_PAGE === 'case') {
    BOOT_SECTIONS['/api/settings-center/public?groups=onepipe'] = ['onepipeFlags', 1];
    BOOT_SECTIONS['/api/settings-center/public?groups=builder_layout,builder_custom_fields,builder_rules,builder_slots,builder_status_display,builder_stage_templates,ui_format,list_view'] = ['builderGroups', 1];
    BOOT_SECTIONS['/api/profit-warning/config'] = ['profitWarning', 1];
    BOOT_SECTIONS['/api/users/selectable'] = ['usersSelectable', 1];
    BOOT_SECTIONS['/api/settings/company-profile/public'] = ['companyProfilePublic', 1];
    BOOT_SECTIONS['/api/list-prefs/case_list'] = ['listPrefCase', 1];
    BOOT_SECTIONS['/api/vendor-contractors/selectable'] = ['vendorsSelectable', 1];
    BOOT_SECTIONS['/api/contractors/selectable'] = ['contractorsSelectable', 1];
    // 這一頁有兩個載入點的全站區段：側欄＋案件頁各一次（模組可用性、承攬商分頁的獎金模組狀態）
    BOOT_SECTIONS['/api/system/modules/availability'] = ['moduleAvailability', 2];
    BOOT_SECTIONS['/api/system/bonus-module-status'] = ['bonusModuleStatus', 2];
  }
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
      var mine = auth === 'Bearer ' + boot.token && (boot.used[m[0]] || 0) < m[1];
      var v = mine ? bootValue(m[0], boot.token) : undefined;
      if (v === undefined) {
        // T86 U5：bootstrap 剛問過這支原端點、它回 403／404（這個人沒有這項權限／這項功能沒開）⇒ 20 秒內再問一次只會得到同一個答案
        // （權限不會在 20 秒內自己變）⇒ 直接給同狀態碼的回應、不再送一個注定被擋的請求（也不在伺服器端多留一筆被拒紀錄）。500／428 等不算：照舊真的送。
        var es = mine && boot.data && boot.data.errors && Date.now() - boot.at <= BOOT_TTL_MS ? boot.data.errors[m[0]] : 0;
        if (es === 403 || es === 404) {
          boot.used[m[0]] = (boot.used[m[0]] || 0) + 1;
          return new Response(JSON.stringify({ detail: es === 403 ? '沒有權限' : '不存在' }), { status: es, headers: { 'Content-Type': 'application/json' } });
        }
        return fetch(url, opts);
      }
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
    try { localStorage.removeItem('motrix_prefs'); localStorage.removeItem('motrix_font_zoom'); localStorage.removeItem('motrix_theme'); sessionStorage.removeItem('motrix_prefs_synced'); sessionStorage.removeItem('motrix_home_done') } catch (e) {}   // 沒登入（含各頁自己登出的路徑）：個人偏好快取一併清掉
    bootResolve(null);
    rememberReturn();
    location.replace(loginPath);
    return;
  }

  // ── 個人偏好（「我的帳號」票，2026-11-13）：字級／深色模式／登入後首頁 ──────────────────────────
  // 先套用本機快取（避免閃一下），每個登入期間再向伺服器同步一次（換裝置也保留）。偏好只影響自己看到的畫面。
  // 字級偏好與頂欄「小／標／大／特」共用同一套（motrix_font_zoom／--fz／motrixSetZoom），不另開第二套 zoom：
  // 偏好值 → 倍率；頂欄改倍率時反過來把偏好寫回伺服器（saveFont），兩邊永遠一致，換頁、換裝置都保留。
  var ZOOM = { small: 0.85, normal: 1, large: 1.15, xlarge: 1.3 };
  function setZoom(z) {
    try {
      localStorage.setItem('motrix_font_zoom', String(z));
      if (typeof window.motrixSetZoom === 'function') { window.motrixSetZoom(z, true); return; }   // sidebar.js 已載入：連頂欄按鈕狀態一起更新
      document.documentElement.style.zoom = z;
      document.documentElement.style.setProperty('--fz', String(z));
    } catch (e) {}
  }
  function zoomToPref(z) {
    var best = 'normal', d = 9;
    for (var k in ZOOM) { if (Math.abs(ZOOM[k] - z) < d) { d = Math.abs(ZOOM[k] - z); best = k; } }
    return best;
  }
  // force：使用者剛在「我的帳號」明確改了字級 ⇒ 一定套用。同步（非 force）時：伺服器值和上次快取相同 ⇒ 不動這台裝置的目前倍率
  // （使用者可能剛在頂欄改過）；沒有快取且是預設值 ⇒ 也不動（舊使用者只用過頂欄，不該被預設值重設）。
  function applyPrefs(p, force) {
    try {
      if (!p) return;
      if (p.font_size in ZOOM) {
        var prev = null; try { prev = JSON.parse(localStorage.getItem('motrix_prefs') || 'null'); } catch (e) {}
        var changed = prev ? prev.font_size !== p.font_size : p.font_size !== 'normal';
        if (force || changed) setZoom(ZOOM[p.font_size]);
      }
      if (p.theme === 'dark' || p.theme === 'light') {
        // 同字級：伺服器值「有變」才套用（頂欄切換是這台電腦當下的選擇，不能被沒變的舊偏好蓋回去）；「我的帳號」存檔時 force 一定套用
        var prevT = null; try { prevT = JSON.parse(localStorage.getItem('motrix_prefs') || 'null'); } catch (e) {}
        var changedT = prevT ? prevT.theme !== p.theme : p.theme !== 'light';
        if (force || changedT) {
          if (p.theme === 'dark') { document.documentElement.setAttribute('data-theme', 'dark'); localStorage.setItem('motrix_theme', 'dark'); }
          else { document.documentElement.removeAttribute('data-theme'); localStorage.removeItem('motrix_theme'); }
        }
      }
    } catch (e) {}
  }
  // 頂欄改字級 ⇒ 把對應的偏好值存回伺服器（失敗不影響畫面；下次同步以伺服器為準）
  function saveFont(z) {
    try {
      var v = zoomToPref(z);
      var cache = JSON.parse(localStorage.getItem('motrix_prefs') || '{}') || {};
      if (cache.font_size === v) return;
      cache.font_size = v;
      localStorage.setItem('motrix_prefs', JSON.stringify(cache));
      fetch('/api/auth/preferences', { method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + session.token },
        body: JSON.stringify({ font_size: v }) }).catch(function () {});
    } catch (e) {}
  }
  // 頂欄切深色／淺色 ⇒ 把對應的偏好值存回伺服器（同 saveFont；失敗不影響畫面）
  function saveTheme(dark) {
    try {
      var v = dark ? 'dark' : 'light';
      var cache = JSON.parse(localStorage.getItem('motrix_prefs') || '{}') || {};
      if (cache.theme === v) return;
      cache.theme = v;
      localStorage.setItem('motrix_prefs', JSON.stringify(cache));
      fetch('/api/auth/preferences', { method: 'PUT', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + session.token },
        body: JSON.stringify({ theme: v }) }).catch(function () {});
    } catch (e) {}
  }
  // 本機快取不再套用字級與外觀：兩者都由 sidebar.js 讀自己的本機值（motrix_font_zoom／motrix_theme）即時套用，頂欄切換才不會被舊快取蓋掉
  try { var _c = JSON.parse(localStorage.getItem('motrix_prefs') || 'null'); if (_c) { delete _c.font_size; delete _c.theme; applyPrefs(_c); } } catch (e) {}
  function syncPrefs() {
    try {
      var atHome = /(^|\/)(index\.html)?$/.test(location.pathname) && location.pathname.indexOf('/pages/') < 0;
      if (sessionStorage.getItem('motrix_prefs_synced') && !(atHome && !sessionStorage.getItem('motrix_home_done'))) return;
      fetch('/api/auth/preferences', { headers: { Authorization: 'Bearer ' + session.token } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || !d.prefs) return;
          sessionStorage.setItem('motrix_prefs_synced', '1');
          applyPrefs(d.prefs);
          localStorage.setItem('motrix_prefs', JSON.stringify(d.prefs));
          // 登入後的首頁：只在這個登入期間第一次落在儀表板時跳一次（之後使用者回儀表板不再被跳走）
          var hp = d.prefs.home_page;
          if (atHome && hp && hp !== 'index.html' && /^[a-z0-9-]+\.html$/.test(hp) && !sessionStorage.getItem('motrix_home_done')) {
            sessionStorage.setItem('motrix_home_done', '1');
            location.replace('pages/' + hp);
          } else if (atHome) { sessionStorage.setItem('motrix_home_done', '1'); }
        })
        .catch(function () {});
    } catch (e) {}
  }
  window.MotrixPrefs = { apply: function (p) { applyPrefs(p, true); }, sync: syncPrefs, saveFont: saveFont, saveTheme: saveTheme };

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
      syncPrefs();
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

  // 啟動資料等不到就不等：BOOT_WAIT_MS（1.5 秒）後讓 MotrixBoot 變 null，各處退回打原端點（與改版前一樣）。
  // 之前是 6 秒：bootstrap 卡住時，等它的頁面資料會卡 6 秒，比沒有 bootstrap 還糟。逾時後才到的 bootstrap 回應一律丟掉（呼叫端已經改打原端點了）。
  var BOOT_WAIT_MS = 1500, bootDead = false;
  var bootTimer = setTimeout(function () { bootDead = true; bootResolve(null); }, BOOT_WAIT_MS);

  // 首繪不可以比改版前慢（B1）：**放行只看快的 `auth/me`**（與改版前逐字相同的路徑），`/api/bootstrap` 同時並行發出、
  // 只負責供應資料——它慢（11 個區段）不會擋住頁面顯示；它失敗（401／403／428／404／5xx／逾時）只是 MotrixBoot＝null、各處退回打原端點。
  fetch(BOOT_PAGE ? '/api/bootstrap?page=' + BOOT_PAGE : '/api/bootstrap', { headers: authHeaders })
    .then(function (r) {
      if (r.status !== 200) { clearTimeout(bootTimer); bootResolve(null); return; }
      return r.json().then(function (d) {
        if (!d || !d.me) throw new Error('bootstrap without me');
        if (bootDead) return;
        boot.data = d; boot.at = Date.now(); boot.token = session.token;
        boot.hdr = { license: r.headers.get('X-Motrix-License'), setup: r.headers.get('X-Motrix-Company-Setup'), expiry: r.headers.get('X-Motrix-License-Expiry') };
        clearTimeout(bootTimer); bootResolve(d);
      });
    })
    .catch(function () { clearTimeout(bootTimer); bootResolve(null); });
  legacyMe();
})();
