/* field.js — 外勤手機頁共用模組（T80c S3）。原生 JS、不依賴 Alpine／jQuery／notif.js，<40 KB。
 *
 * 給 `field-cases.html`／`field-case.html`（S4）用，也可單獨測：`MotrixField.create(deps)` 可注入所有瀏覽器相依（XHR、計時器、
 * createImageBitmap、canvas、sessionStorage…），單元題（tests/test_field_js_2026_11_12.py）用 node 假裝這些相依。
 *
 * 做的事（設計：T80c-field-pages-design-note §4）：
 *  1. 縮圖：createImageBitmap(file, {imageOrientation:'from-image'}) → canvas → JPEG（長邊 ≤ 1600、品質 ≈ 0.8）。
 *     這一步同時把 EXIF 方向「烤」進像素（伺服器端 Pillow 會丟掉 EXIF，不縮圖的路徑才靠伺服器修）。任何一步失敗 ⇒ 送原檔，不擋流程。
 *  2. 傳輸：XMLHttpRequest（才有上傳進度）；「60 秒內沒有任何進度」視為逾時並中止；失敗重試最多 3 次（間隔 2／5／10 秒），
 *     **每次重試沿用同一把 Idempotency-Key 與同一份位元組**（伺服器才認得「這個請求我做過」）；4xx（驗證失敗）不重試。
 *  3. 形狀 B：先 POST 文字（立刻成功、拿到留言 id），再逐張照片 POST …/updates/{id}/files（各自一把 key、各自進度與重試）。
 *     一張失敗不影響其他張；失敗的那張可以只重傳它（retryFailed）。表單內容與已選照片在成功前一直保留（呼叫端持有 handle）。
 *  4. 定位：盡力而為（5 秒逾時、可用 60 秒內的舊值），拿不到／拒絕就算了；只當檔案 metadata 送（`geo=lat,lng,accuracy`），不印在浮水印上。
 *  5. 401／402／428 導向（最小版；不載入 notif.js）：401 ⇒ 清 session 回登入頁；402 ⇒ 授權說明頁；428 ⇒ 公司資料設定說明頁。
 *
 * 不做：離線佇列（L0）、背景同步、service worker。
 */
(function (root) {
  'use strict';

  var DEFAULTS = {
    maxEdge: 1600,               // 縮圖長邊上限（px）
    quality: 0.8,                // JPEG 品質
    noProgressMs: 60000,         // 這麼久沒有任何上傳進度 ⇒ 逾時
    pendingTtlMs: 30 * 60 * 1000,   // 「這次送出」的 key 只在這段時間內沿用（放棄的舊送出不會讓日後同樣文字被當成重播）
    serverWaitMs: 120000,        // 位元組都送完、等伺服器處理（此時不再有進度事件）的容忍時間
    retryDelays: [2000, 5000, 10000],   // 失敗重試的間隔（長度＝最多重試次數）
    maxRetryAfterMs: 15000,      // 409／429／503 的 Retry-After 上限
    geoTimeoutMs: 5000,
    geoMaxAgeMs: 60000,
    emptyText: '（現場照片）',    // 沒打字只傳照片時，文字留言用這句（後端要求內容或檔案至少一個；形狀 B 文字先存）
    loginPage: 'login.html',
    licensePage: 'license-required.html',
    companySetupPage: 'company-setup-required.html',
    companyFixPage: 'company-profile-settings.html?setup=1'
  };

  // 可以重試的 HTTP 狀態：逾時、被限流、處理中（409＝同一把 key 還在處理）、伺服器錯誤。其餘 4xx（驗證失敗、無權限…）重試只會得到同樣的答案。
  function retryableStatus(s) {
    return s === 408 || s === 409 || s === 425 || s === 429 || s >= 500;
  }

  function create(deps) {
    deps = deps || {};
    var cfg = {};
    var k;
    for (k in DEFAULTS) cfg[k] = DEFAULTS[k];
    if (deps.config) for (k in deps.config) cfg[k] = deps.config[k];

    // ── 環境（全部可注入）────────────────────────────────────────────────
    var env = {
      xhr: deps.xhr || function () { return new XMLHttpRequest(); },
      setTimeout: deps.setTimeout || function (f, ms) { return root.setTimeout(f, ms); },
      clearTimeout: deps.clearTimeout || function (t) { return root.clearTimeout(t); },
      now: deps.now || function () { return Date.now(); },
      createImageBitmap: deps.createImageBitmap || (typeof root.createImageBitmap === 'function' ? function (f, o) { return root.createImageBitmap(f, o); } : null),
      createCanvas: deps.createCanvas || function (w, h) {
        var c = root.document.createElement('canvas');
        c.width = w; c.height = h;
        return c;
      },
      localStorage: deps.localStorage || (function () { try { return root.localStorage; } catch (e) { return null; } })(),
      sessionStorage: deps.sessionStorage || (function () { try { return root.sessionStorage; } catch (e) { return null; } })(),
      geolocation: deps.geolocation || (root.navigator && root.navigator.geolocation) || null,
      redirect: deps.redirect || function (url) { root.location.href = url; },
      fetch: deps.fetch || (typeof root.fetch === 'function' ? function (u, o) { return root.fetch(u, o); } : null),
      FormData: deps.FormData || root.FormData,
      random: deps.random || null
    };

    // ── session ───────────────────────────────────────────────────────────
    function session() {
      try { return JSON.parse(env.localStorage.getItem('motrix_session') || '{}') || {}; } catch (e) { return {}; }
    }
    function token() { return session().token || ''; }
    function authHeaders(extra) {
      var h = {};
      var t = token();
      if (t) h.Authorization = 'Bearer ' + t;
      if (extra) for (var k2 in extra) h[k2] = extra[k2];
      return h;
    }

    // ── 冪等鍵 ────────────────────────────────────────────────────────────
    // 後端規格：^[A-Za-z0-9_-]{8,128}$。每個請求（每次送出、每張照片）一把新的；只有「同一個請求的重試」沿用。
    function newKey() {
      var c = root.crypto;
      if (!deps.random && c && typeof c.randomUUID === 'function') return c.randomUUID();
      var hex = '';
      var i;
      if (!deps.random && c && typeof c.getRandomValues === 'function') {
        var a = new Uint8Array(16);
        c.getRandomValues(a);
        for (i = 0; i < a.length; i++) hex += ('0' + a[i].toString(16)).slice(-2);
      } else {
        var rnd = deps.random || Math.random;
        for (i = 0; i < 32; i++) hex += Math.floor(rnd() * 16).toString(16);
      }
      return 'f-' + hex;
    }

    // ── 401／402／428 ─────────────────────────────────────────────────────
    var redirecting = false;
    /** 看到這些狀態就導走；回傳 true＝已導走（呼叫端不要再往下做）。 */
    function handleGate(status, body) {
      if (redirecting) return true;
      if (status === 401) {
        redirecting = true;
        try { env.localStorage.removeItem('motrix_session'); } catch (e) { /* 沒有儲存空間也要導走 */ }
        env.redirect(cfg.loginPage);
        return true;
      }
      if (status === 402) {
        redirecting = true;
        env.redirect(cfg.licensePage);
        return true;
      }
      if (status === 428 && body && body.code === 'company_setup_required') {
        redirecting = true;
        env.redirect(body.canFix ? cfg.companyFixPage : cfg.companySetupPage);
        return true;
      }
      return false;
    }

    // ── JSON 請求（讀取類，fetch）────────────────────────────────────────
    function request(method, url, opts) {
      opts = opts || {};
      var headers = authHeaders(opts.headers);
      var init = { method: method, headers: headers };
      if (opts.json !== undefined) {
        headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(opts.json);
      }
      return env.fetch(url, init).then(function (r) {
        return r.text().then(function (txt) {
          var body = null;
          try { body = txt ? JSON.parse(txt) : null; } catch (e) { body = null; }
          var gated = handleGate(r.status, body);
          return { status: r.status, ok: r.status >= 200 && r.status < 300, body: body, gated: gated };
        });
      });
    }

    // ── 縮圖 ──────────────────────────────────────────────────────────────
    function jpegName(name) {
      var base = String(name || 'photo').replace(/\.[A-Za-z0-9]+$/, '');
      return (base || 'photo') + '.jpg';
    }
    function isImage(file) {
      var t = String((file && file.type) || '').toLowerCase();
      if (t.indexOf('image/') === 0) return t !== 'image/gif' && t !== 'image/svg+xml';   // gif／svg 縮成 JPEG 會壞掉
      return /\.(jpe?g|png|heic|heif|webp)$/i.test(String((file && file.name) || ''));
    }
    /**
     * 照片 → JPEG（長邊 ≤ maxEdge）。回 Promise<{blob, name, shrunk, width, height}>；任何失敗 ⇒ 回原檔（shrunk:false），不丟例外。
     * 小圖也重新編碼：createImageBitmap 的 'from-image' 會把 EXIF 方向套進像素，不重新編碼就留在（會被伺服器丟掉的）EXIF 裡。
     */
    function shrinkImage(file) {
      var orig = { blob: file, name: file && file.name, shrunk: false };
      if (!file || !env.createImageBitmap || !isImage(file)) return Promise.resolve(orig);
      return Promise.resolve().then(function () {
        return env.createImageBitmap(file, { imageOrientation: 'from-image' });
      }).then(function (bmp) {
        var w = bmp.width, h = bmp.height;
        if (!(w > 0 && h > 0)) throw new Error('empty bitmap');
        var scale = Math.min(1, cfg.maxEdge / Math.max(w, h));
        var tw = Math.max(1, Math.round(w * scale)), th = Math.max(1, Math.round(h * scale));
        var canvas = env.createCanvas(tw, th);
        var ctx = canvas.getContext('2d');
        if (typeof ctx.fillRect === 'function') { ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, tw, th); }   // JPEG 沒有 alpha：透明 PNG 不要變黑底
        ctx.drawImage(bmp, 0, 0, tw, th);
        if (typeof bmp.close === 'function') { try { bmp.close(); } catch (e) { /* ignore */ } }
        return new Promise(function (resolve, reject) {
          canvas.toBlob(function (blob) {
            if (!blob) return reject(new Error('toBlob failed'));
            resolve({ blob: blob, name: jpegName(file.name), shrunk: true, width: tw, height: th });
          }, 'image/jpeg', cfg.quality);
        });
      }).catch(function () {
        return orig;        // HEIC 讀不了、記憶體不足、toBlob 不支援…… ⇒ 送原檔
      });
    }

    // ── 定位（盡力而為）──────────────────────────────────────────────────
    /** 回 Promise<string>：'lat,lng,accuracy' 或 ''。必須在使用者手勢（點選照片／拍照）裡呼叫才會跳權限提示；拒絕／逾時 ⇒ ''。 */
    function geoOnce() {
      return new Promise(function (resolve) {
        if (!env.geolocation || typeof env.geolocation.getCurrentPosition !== 'function') return resolve('');
        var done = false;
        var guard = env.setTimeout(function () { finish(''); }, cfg.geoTimeoutMs + 1000);   // 有些瀏覽器兩個 callback 都不呼叫
        function finish(v) {
          if (done) return;
          done = true;
          env.clearTimeout(guard);
          resolve(v);
        }
        try {
          env.geolocation.getCurrentPosition(function (pos) {
            var c = pos && pos.coords;
            if (!c || typeof c.latitude !== 'number' || typeof c.longitude !== 'number') return finish('');
            var s = c.latitude.toFixed(6) + ',' + c.longitude.toFixed(6);
            if (typeof c.accuracy === 'number' && c.accuracy >= 0) s += ',' + Math.round(c.accuracy * 10) / 10;
            finish(s);
          }, function () { finish(''); }, { timeout: cfg.geoTimeoutMs, maximumAge: cfg.geoMaxAgeMs, enableHighAccuracy: false });
        } catch (e) { finish(''); }
      });
    }

    // ── 單次 XHR 上傳（有進度、無進度逾時）──────────────────────────────
    /**
     * 一次嘗試。resolve {status, body, retryAfterMs, replay}（任何 HTTP 狀態都 resolve）；
     * reject {kind:'timeout'|'network'|'abort'}。「60 秒內沒有任何進度」＝逾時並中止；每次收到 progress 就重新計時。
     */
    function xhrOnce(o) {
      return new Promise(function (resolve, reject) {
        var x = env.xhr();
        var timer = null;
        var settled = false;
        function arm(ms) {
          if (timer !== null) env.clearTimeout(timer);
          timer = env.setTimeout(function () {
            if (settled) return;
            settled = true;
            try { x.abort(); } catch (e) { /* ignore */ }
            reject({ kind: 'timeout' });
          }, ms || cfg.noProgressMs);
        }
        function end() { settled = true; if (timer !== null) env.clearTimeout(timer); }
        x.open(o.method || 'POST', o.url, true);
        var h = o.headers || {};
        for (var name in h) x.setRequestHeader(name, h[name]);
        if (x.upload) {
          x.upload.onprogress = function (e) {
            if (settled) return;
            arm();
            if (o.onProgress && e && e.lengthComputable) o.onProgress(e.loaded, e.total);
          };
          x.upload.onload = function () { if (!settled) arm(cfg.serverWaitMs); };   // 送完了：之後只等伺服器，不會再有進度事件
        }
        x.onload = function () {
          if (settled) return;
          end();
          var body = null;
          try { body = x.responseText ? JSON.parse(x.responseText) : null; } catch (e) { body = null; }
          var ra = 0;
          try { ra = parseInt(x.getResponseHeader('Retry-After') || '0', 10) * 1000 || 0; } catch (e2) { ra = 0; }
          var replay = false;
          try { replay = x.getResponseHeader('Idempotent-Replay') === 'true'; } catch (e3) { replay = false; }
          resolve({ status: x.status, body: body, retryAfterMs: ra, replay: replay });
        };
        x.onerror = function () { if (settled) return; end(); reject({ kind: 'network' }); };
        x.ontimeout = function () { if (settled) return; end(); reject({ kind: 'timeout' }); };
        x.onabort = function () { if (settled) return; end(); reject({ kind: 'abort' }); };
        var body;
        try { body = o.makeBody(); } catch (e4) { end(); reject({ kind: 'prepare' }); return; }   // 組不出請求內容：重試也一樣，不當成網路錯誤
        if (o.onXhr) o.onXhr(x);
        arm();
        x.send(body);
      });
    }

    function sleep(ms) {
      return new Promise(function (resolve) { env.setTimeout(resolve, ms); });
    }

    /**
     * 帶重試的上傳。`o`：{url, method, headers（不含 Authorization／Idempotency-Key，這裡加）, makeBody(), key, onProgress(loaded,total),
     * onRetry(n, why, delayMs), isCancelled()}。
     * **每次重試沿用同一把 key**；resolve {ok, status, body, replay, attempts, gated, error}（不 reject）。
     * 只重試：逾時、網路錯誤、408／409／425／429／5xx；4xx 其他（驗證失敗）立刻回傳；401／402／428 導走並回傳 gated。
     * 409／429／503 的 Retry-After 照辦（上限 maxRetryAfterMs）；`makeBody` 丟例外 ⇒ 不重試、error:'prepare_failed'；`onXhr(x)` 給呼叫端拿到進行中的 XHR（取消時 abort）。
     */
    function uploadWithRetry(o) {
      var headers = authHeaders(o.headers);
      headers['Idempotency-Key'] = o.key;
      var attempt = 0;
      function go() {
        attempt += 1;
        return xhrOnce({ url: o.url, method: o.method, headers: headers, makeBody: o.makeBody, onProgress: o.onProgress, onXhr: o.onXhr })
          .then(function (r) {
            if (r.status >= 200 && r.status < 300) return { ok: true, status: r.status, body: r.body, replay: r.replay, attempts: attempt };
            if (handleGate(r.status, r.body)) return { ok: false, gated: true, status: r.status, body: r.body, attempts: attempt };
            if (retryableStatus(r.status)) return again({ status: r.status, body: r.body, why: 'http_' + r.status }, r.retryAfterMs);
            return { ok: false, status: r.status, body: r.body, attempts: attempt, error: detail(r.body) };
          }, function (e) {
            if (e && e.kind === 'abort') return { ok: false, aborted: true, attempts: attempt, error: 'aborted' };
            if (e && e.kind === 'prepare') return { ok: false, attempts: attempt, error: 'prepare_failed' };
            return again({ status: 0, body: null, why: (e && e.kind) || 'network' }, 0);
          });
      }
      function again(last, retryAfterMs) {
        var i = attempt - 1;
        if (i >= cfg.retryDelays.length || (o.isCancelled && o.isCancelled())) {
          return { ok: false, status: last.status, body: last.body, attempts: attempt, error: last.why, exhausted: true };
        }
        var delay = cfg.retryDelays[i];
        if ((last.status === 409 || last.status === 429 || last.status === 503) && retryAfterMs > 0) delay = Math.max(delay, Math.min(retryAfterMs, cfg.maxRetryAfterMs));
        if (o.onRetry) o.onRetry(attempt, last.why, delay);
        return sleep(delay).then(function () {
          if (o.isCancelled && o.isCancelled()) return { ok: false, aborted: true, attempts: attempt, error: 'cancelled' };
          return go();
        });
      }
      return go();
    }
    function detail(body) {
      return body && (body.detail || body.message) ? String(body.detail || body.message) : '';
    }

    // ── 草稿（文字；頁面被重新整理時保留）───────────────────────────────
    function draftKey(quoteNo) { return 'motrix_field_draft:' + quoteNo; }
    function saveDraft(quoteNo, text) {
      try { env.sessionStorage.setItem(draftKey(quoteNo), String(text || '')); } catch (e) { /* 沒有儲存空間就沒有草稿 */ }
    }
    function loadDraft(quoteNo) {
      try { return env.sessionStorage.getItem(draftKey(quoteNo)) || ''; } catch (e) { return ''; }
    }
    function clearDraft(quoteNo) {
      try { env.sessionStorage.removeItem(draftKey(quoteNo)); } catch (e) { /* ignore */ }
      clearPending(quoteNo);        // 使用者放棄／成功送出：連「這次送出用的 key」一起丟
    }

    // ── 「這次送出」的冪等鍵（頁面重新整理後再按送出，要沿用同一把，否則伺服端認不出是同一次＝重複留言）──
    // 存 sessionStorage：{sig, textKey, photos:{身分:key}}。sig＝送出內容（文字＋important）；內容變了就不沿用。
    // 照片 key 綁檔案身分（名稱|大小|lastModified|geo）：換了檔案、換了定位值都是新請求，不得沿用。
    // 時效：savedAt 超過 pendingTtlMs（30 分鐘）就不沿用——否則使用者放棄後、日後再送同樣文字，會被伺服端當成重播舊留言（沒建立新的、也沒提示）。
    // 沿用時 'text-saved' 事件帶 replay:true（伺服端回的是舊結果），畫面可據此講「接續上次未完成的送出」。
    // 已知取捨：沿用的照片 key 遇 422（重縮圖位元組不同）會換新 key 重送；若第一次其實已在伺服端成功（回應丟了），這裡會多存一張（重複附件，非資料毀損）。
    function pendingKey(quoteNo) { return 'motrix_field_pending:' + quoteNo; }
    function photoIdent(f, geo) { return [f && f.name, f && f.size, f && f.lastModified, geo || ''].join('|'); }
    function loadPending(quoteNo, sig) {
      try {
        var v = JSON.parse(env.sessionStorage.getItem(pendingKey(quoteNo)) || 'null');
        if (v && v.sig === sig && typeof v.textKey === 'string' && typeof v.savedAt === 'number' && env.now() - v.savedAt <= cfg.pendingTtlMs) return v;
      } catch (e) { /* 壞掉當沒有 */ }
      return null;
    }
    function savePending(quoteNo, v) {
      try { env.sessionStorage.setItem(pendingKey(quoteNo), JSON.stringify(v)); } catch (e) { /* 沒有儲存空間：只剩同一次頁面生命的保護 */ }
    }
    function clearPending(quoteNo) {
      try { env.sessionStorage.removeItem(pendingKey(quoteNo)); } catch (e) { /* ignore */ }
    }

    // ── 形狀 B：先文字、再逐張照片 ───────────────────────────────────────
    function encode(s) { return encodeURIComponent(s); }

    /**
     * 新增動態（文字＋照片，形狀 B）。`o`：{quoteNo, text, important, files（File[]）, geo（'lat,lng,acc' 或 ''）, onEvent(ev)}。
     * 回 handle：{promise, state, retryFailed(), cancel()}——
     *  - `state`：{updateId, textKey, text:{status}, photos:[{name, status:'queued'|'shrinking'|'uploading'|'done'|'failed', progress(0..1), key, error, attempts}]}；
     *  - `promise` resolve 成 state（不 reject；文字失敗 ⇒ state.text.status==='failed'，照片不會送）；
     *  - 文字已存、部分照片失敗 ⇒ 呼叫 `retryFailed()` 只重傳失敗那幾張（同一把 key、同一份位元組），回新的 promise。
     * 事件（onEvent）：'text-saving'、'text-saved'、'text-failed'、'photo'（photo 狀態變了，帶 index）、'done'。
     */
    function postCaseUpdate(o) {
      var files = o.files || [];
      var sig = JSON.stringify([String(o.text || '').trim(), !!o.important]);
      var pending = (o.persist === false) ? null : loadPending(o.quoteNo, sig);
      var state = {
        updateId: null,
        textKey: o.textKey || (pending && pending.textKey) || newKey(),
        text: { status: 'queued', error: '' },
        photos: files.map(function (f) {
          var id = photoIdent(f, o.geo);
          var reused = !!(pending && pending.photos && typeof pending.photos[id] === 'string');
          return { name: f.name, status: 'queued', progress: 0, key: reused ? pending.photos[id] : newKey(), keyReused: reused, ident: id,
                   error: '', attempts: 0, blob: null, upName: null, file: f };
        })
      };
      var cancelled = false;
      var running = null;
      var curXhr = null;
      function persist() {
        if (o.persist === false) return;
        var ph = {};
        state.photos.forEach(function (p) { ph[p.ident] = p.key; });
        savePending(o.quoteNo, { sig: sig, textKey: state.textKey, photos: ph, savedAt: env.now() });
      }
      persist();
      function emit(type, extra) {
        if (!o.onEvent) return;
        var ev = { type: type, state: state };
        if (extra) for (var k3 in extra) ev[k3] = extra[k3];
        try { o.onEvent(ev); } catch (e) { /* 呼叫端的畫面錯誤不能中斷上傳 */ }
      }
      function isCancelled() { return cancelled; }

      function saveText() {
        if (state.updateId) return Promise.resolve(true);
        state.text.status = 'saving';
        emit('text-saving');
        var text = String(o.text || '').trim() || (files.length ? cfg.emptyText : '');
        return uploadWithRetry({
          url: '/api/quotations/' + encode(o.quoteNo) + '/updates',
          key: state.textKey,
          isCancelled: isCancelled,
          onXhr: function (x) { curXhr = x; },
          makeBody: function () {
            var fd = new env.FormData();
            fd.append('content', text);
            fd.append('important', o.important ? 'true' : '');
            return fd;
          }
        }).then(function (r) {
          if (r.ok && r.body && r.body.id) {
            state.updateId = r.body.id;
            state.text.status = 'done';
            emit('text-saved', { replay: !!r.replay });
            return true;
          }
          state.text.status = 'failed';
          state.text.error = r.error || ('http_' + r.status);
          if (r.gated) state.gated = true;
          emit('text-failed', { result: r });
          return false;
        });
      }

      function uploadPhoto(i) {
        var p = state.photos[i];
        if (p.status === 'done') return Promise.resolve();
        var prep = p.blob ? Promise.resolve() : (function () {
          p.status = 'shrinking';
          emit('photo', { index: i });
          return shrinkImage(p.file).then(function (s) { p.blob = s.blob; p.upName = s.name || p.name; });
        })();
        return prep.then(function () {
          p.status = 'uploading';
          p.progress = 0;
          p.error = '';
          emit('photo', { index: i });
          function send() {
            return uploadWithRetry({
              url: '/api/quotations/' + encode(o.quoteNo) + '/updates/' + encode(String(state.updateId)) + '/files',
              key: p.key,
              isCancelled: isCancelled,
              onXhr: function (x) { curXhr = x; },
              onProgress: function (loaded, total) { p.progress = total ? loaded / total : 0; emit('photo', { index: i }); },
              onRetry: function (n, why) { p.attempts = n; p.error = why; emit('photo', { index: i, retrying: true }); },
              makeBody: function () {
                var fd = new env.FormData();
                fd.append('files', p.blob, p.upName || p.name || 'photo.jpg');
                if (o.geo) fd.append('geo', o.geo);
                return fd;
              }
            });
          }
          return send().then(function (r) {
            // 沿用重整前的 key、但這次重新縮圖的位元組不同 ⇒ 伺服端 422（同 key 不同內容）：換一把新 key 重送一次
            if (!r.ok && r.status === 422 && p.keyReused) {
              p.key = newKey(); p.keyReused = false; persist();
              return send();
            }
            return r;
          }).then(function (r) {
            p.attempts = r.attempts;
            if (r.ok) { p.status = 'done'; p.progress = 1; p.error = ''; }
            else { p.status = 'failed'; p.error = r.error || ('http_' + r.status); if (r.gated) state.gated = true; }
            emit('photo', { index: i });
          });
        });
      }

      function photosSequentially() {
        var chain = Promise.resolve();
        state.photos.forEach(function (p, i) {
          chain = chain.then(function () {
            if (cancelled || p.status === 'done' || state.gated) return null;
            return uploadPhoto(i);
          });
        });
        return chain;
      }

      function run() {
        return saveText().then(function (ok) {
          if (!ok) return state;
          return photosSequentially().then(function () {
            if (o.persist !== false && state.photos.every(function (p) { return p.status === 'done'; })) clearPending(o.quoteNo);   // 全部成功：這次送出的 key 用完了
            emit('done');
            return state;
          });
        });
      }

      var handle = { state: state };
      function start() {
        running = run().then(function (st) { running = null; curXhr = null; return st; });
        handle.promise = running;
        return running;
      }
      start();
      handle.retryFailed = function () {
        if (running) return running;       // 進行中（連點）：回同一個 promise，不開第二條重試鏈
        cancelled = false;
        state.photos.forEach(function (p) { if (p.status === 'failed') p.status = 'queued'; });
        return start();                    // 文字還沒存成功時，這裡會先重存文字（同一把 key）
      };
      handle.cancel = function () {
        cancelled = true;
        if (curXhr) { try { curXhr.abort(); } catch (e) { /* ignore */ } }    // 傳輸中的也中止（不是等當前這張傳完）
      };
      return handle;
    }

    return {
      config: cfg,
      newKey: newKey,
      authHeaders: authHeaders,
      handleGate: handleGate,
      request: request,
      shrinkImage: shrinkImage,
      geoOnce: geoOnce,
      uploadWithRetry: uploadWithRetry,
      postCaseUpdate: postCaseUpdate,
      saveDraft: saveDraft,
      loadDraft: loadDraft,
      clearDraft: clearDraft,
      clearPending: clearPending
    };
  }

  var api = { create: create, DEFAULTS: DEFAULTS };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.MotrixFieldFactory = api;
  // 瀏覽器：預設實例
  if (root.document) root.MotrixField = create();
})(typeof window !== 'undefined' ? window : this);
