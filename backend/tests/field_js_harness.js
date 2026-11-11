// field_js_harness.js — tests/test_field_js_2026_11_12.py 用 node 跑的情境驅動（假 XHR、假計時器、假相機／定位）。
// 輸出一行 JSON：{情境名: 結果}。斷言在 Python 那邊。不依賴任何套件。
'use strict';
var path = require('path');
var F = require(path.join(__dirname, '..', '..', 'frontend', 'static', 'field.js'));

// ── 假時鐘：setTimeout 只在 drive() 推進時才會觸發 ─────────────────────────
function Clock() {
  var self = this;
  self.t = 0; self.seq = 0; self.timers = [];
  self.setTimeout = function (f, ms) { var id = ++self.seq; self.timers.push({ id: id, at: self.t + (ms || 0), f: f }); return id; };
  self.clearTimeout = function (id) { self.timers = self.timers.filter(function (x) { return x.id !== id; }); };
  self.sleeps = [];
}
function flush() { return new Promise(function (r) { setImmediate(r); }); }
// 驅動：反覆讓 microtask 跑完，沒結果就把時鐘推到下一個計時器
async function drive(clock, promise) {
  var done = false, val, err;
  promise.then(function (v) { done = true; val = v; }, function (e) { done = true; err = e; });
  for (var i = 0; i < 5000 && !done; i++) {
    await flush();
    if (done) break;
    if (!clock.timers.length) { await flush(); if (!clock.timers.length) break; }
    clock.timers.sort(function (a, b) { return a.at - b.at || a.id - b.id; });
    var nx = clock.timers.shift();
    var delta = nx.at - clock.t;
    if (delta > 0) clock.sleeps.push(delta);
    clock.t = Math.max(clock.t, nx.at);
    nx.f();
  }
  if (!done) throw new Error('drive: promise 沒有結束（卡住）');
  if (err) throw err;
  return val;
}

// ── 假 XHR：每次 new 取下一個腳本 ──────────────────────────────────────────
// 腳本：{type:'ok', status, body, headers} | {type:'neterr'} | {type:'hang'} | {type:'progress_then_hang', at:[ms...]}
function makeXhrFactory(clock, script, log) {
  var n = 0;
  return function () {
    var step = script[Math.min(n, script.length - 1)];
    n++;
    var x = {
      headers: {}, upload: {}, aborted: false,
      open: function (m, u) { x.method = m; x.url = u; },
      setRequestHeader: function (k, v) { x.headers[k] = v; },
      getResponseHeader: function (k) { return (step.headers && step.headers[k]) || null; },
      abort: function () { x.aborted = true; if (x.onabort) x.onabort(); },
      send: function (body) {
        log.push({ n: n, method: x.method, url: x.url, headers: JSON.parse(JSON.stringify(x.headers)), body: body, at: clock.t });
        if (step.type === 'ok') {
          clock.setTimeout(function () { x.status = step.status; x.responseText = JSON.stringify(step.body === undefined ? {} : step.body); x.onload(); }, 10);
        } else if (step.type === 'neterr') {
          clock.setTimeout(function () { x.onerror(); }, 10);
        } else if (step.type === 'progress_then_hang') {
          (step.at || []).forEach(function (ms) { clock.setTimeout(function () { if (!x.aborted) x.upload.onprogress({ lengthComputable: true, loaded: 1, total: 2 }); }, ms); });
        } // hang：什麼都不做
      }
    };
    return x;
  };
}

function FakeFormData() { this.entries = []; }
FakeFormData.prototype.append = function (name, value, filename) { this.entries.push({ name: name, value: (value && value.__blob) ? ('[blob ' + value.size + ']') : value, filename: filename || null, blob: value }); };

function mkStorage(init) {
  var d = Object.assign({}, init || {});
  return { getItem: function (k) { return k in d ? d[k] : null; }, setItem: function (k, v) { d[k] = String(v); }, removeItem: function (k) { delete d[k]; }, _d: d };
}

function mk(script, extra) {
  extra = extra || {};
  var clock = new Clock(), log = [], redirects = [];
  var ls = mkStorage({ motrix_session: JSON.stringify({ token: 'TOK123' }) });
  var deps = {
    xhr: makeXhrFactory(clock, script, log), setTimeout: clock.setTimeout, clearTimeout: clock.clearTimeout,
    localStorage: ls, sessionStorage: mkStorage(), redirect: function (u) { redirects.push(u); }, FormData: FakeFormData,
    createImageBitmap: null, geolocation: null, fetch: null
  };
  for (var k in extra) deps[k] = extra[k];
  return { F: F.create(deps), clock: clock, log: log, redirects: redirects, ls: ls, deps: deps };
}

var OUT = {};
function ok(status, body, headers) { return { type: 'ok', status: status || 200, body: body, headers: headers }; }
function upl(m, extra) {
  return m.F.uploadWithRetry(Object.assign({ url: '/api/x', key: 'KEY-0000001', makeBody: function () { return new FakeFormData(); } }, extra || {}));
}
function keysOf(log) { return log.map(function (l) { return l.headers['Idempotency-Key']; }); }

(async function () {
  // 1. 網路錯誤兩次後成功：同一把 key、間隔 2s／5s
  var m = mk([{ type: 'neterr' }, { type: 'neterr' }, ok(201, { id: 5 })]);
  var r = await drive(m.clock, upl(m));
  OUT.retry_network = { ok: r.ok, attempts: r.attempts, keys: keysOf(m.log), sleeps: m.clock.sleeps.filter(function (s) { return s >= 1000; }), auth: m.log[0].headers.Authorization };

  // 2. 4xx 不重試
  m = mk([ok(400, { detail: '格式不合' })]);
  r = await drive(m.clock, upl(m));
  OUT.no_retry_400 = { ok: r.ok, attempts: r.attempts, status: r.status, error: r.error, calls: m.log.length };
  m = mk([ok(422, { detail: 'key 用在不同請求' })]);
  r = await drive(m.clock, upl(m));
  OUT.no_retry_422 = { ok: r.ok, calls: m.log.length };

  // 3. 5xx 重試耗盡：1 + 3 次
  m = mk([ok(503, {})]);
  r = await drive(m.clock, upl(m));
  OUT.exhausted_503 = { ok: r.ok, attempts: r.attempts, exhausted: r.exhausted, calls: m.log.length, keys: keysOf(m.log), sleeps: m.clock.sleeps.filter(function (s) { return s >= 1000; }) };

  // 4. 409 帶 Retry-After:7 ⇒ 等 7 秒（> 預設 2 秒）；重播標記
  m = mk([ok(409, { detail: '處理中' }, { 'Retry-After': '7' }), ok(201, { id: 9 }, { 'Idempotent-Replay': 'true' })]);
  r = await drive(m.clock, upl(m));
  OUT.retry_409 = { ok: r.ok, replay: r.replay, attempts: r.attempts, sleeps: m.clock.sleeps.filter(function (s) { return s >= 1000; }) };
  m = mk([ok(409, {}, { 'Retry-After': '999' }), ok(201, {})]);
  r = await drive(m.clock, upl(m));
  OUT.retry_409_cap = { sleeps: m.clock.sleeps.filter(function (s) { return s >= 1000; }) };

  // 5. 60 秒沒進度 ⇒ 逾時並中止、重試；有進度就續命
  m = mk([{ type: 'hang' }, ok(201, { id: 1 })]);
  r = await drive(m.clock, upl(m));
  OUT.timeout_no_progress = { ok: r.ok, attempts: r.attempts, firstSleep: m.clock.sleeps[0], keys: keysOf(m.log) };
  m = mk([{ type: 'progress_then_hang', at: [30000, 55000, 100000] }, ok(201, { id: 1 })]);
  var t0 = m.clock.t;
  r = await drive(m.clock, upl(m));
  // 進度在 30s／55s／100s：每次重新計時，最後一次進度 100s 之後再 60s（＝160s）才逾時
  OUT.timeout_progress_resets = { ok: r.ok, attempts: r.attempts, firstAttemptEndedAt: m.log[1].at - 2000 };

  // 6. 401／402／428
  m = mk([ok(401, { detail: 'x' })]);
  r = await drive(m.clock, upl(m));
  OUT.gate_401 = { gated: r.gated, redirects: m.redirects, session: m.ls.getItem('motrix_session'), calls: m.log.length };
  m = mk([ok(402, { detail: 'x' })]);
  r = await drive(m.clock, upl(m));
  OUT.gate_402 = { gated: r.gated, redirects: m.redirects, session: m.ls.getItem('motrix_session') !== null };
  m = mk([ok(428, { code: 'company_setup_required', canFix: true })]);
  r = await drive(m.clock, upl(m));
  OUT.gate_428_fix = { gated: r.gated, redirects: m.redirects };
  m = mk([ok(428, { code: 'company_setup_required', canFix: false })]);
  r = await drive(m.clock, upl(m));
  OUT.gate_428_nofix = { redirects: m.redirects };
  m = mk([ok(428, { code: 'other' })]);
  r = await drive(m.clock, upl(m));
  OUT.gate_428_other = { gated: !!r.gated, redirects: m.redirects, calls: m.log.length };

  // 7. 縮圖
  function imgDeps(w, h, opt) {
    var calls = { bmp: [], canvases: [], toBlob: [] };
    var d = {
      createImageBitmap: function (f, o) { calls.bmp.push(o); return opt && opt.fail ? Promise.reject(new Error('heic')) : Promise.resolve({ width: w, height: h, close: function () { calls.closed = true; } }); },
      createCanvas: function (cw, ch) {
        var c = { width: cw, height: ch, getContext: function () { return { drawImage: function (b, x, y, dw, dh) { calls.draw = [dw, dh]; } }; },
          toBlob: function (cb, type, q) { calls.toBlob.push([type, q]); cb(opt && opt.noBlob ? null : { __blob: true, size: 1234 }); } };
        calls.canvases.push([cw, ch]);
        return c;
      }
    };
    return { d: d, calls: calls };
  }
  async function shrink(w, h, file, opt) {
    var s = imgDeps(w, h, opt); var mm = mk([ok(200)], s.d);
    var res = await mm.F.shrinkImage(file);
    return { res: { shrunk: res.shrunk, name: res.name, width: res.width, height: res.height, isBlob: !!(res.blob && res.blob.__blob) }, calls: s.calls };
  }
  OUT.shrink_big = await shrink(4000, 3000, { name: 'IMG_0001.JPG', type: 'image/jpeg' });
  OUT.shrink_portrait = await shrink(3000, 4000, { name: 'a.heic', type: 'image/heic' });
  OUT.shrink_small = await shrink(800, 600, { name: 'small.png', type: 'image/png' });
  OUT.shrink_fail = await shrink(0, 0, { name: 'x.heic', type: 'image/heic' }, { fail: true });
  OUT.shrink_noblob = await shrink(100, 100, { name: 'x.jpg', type: 'image/jpeg' }, { noBlob: true });
  OUT.shrink_gif = await shrink(100, 100, { name: 'x.gif', type: 'image/gif' });
  OUT.shrink_pdf = await shrink(100, 100, { name: 'x.pdf', type: 'application/pdf' });
  OUT.shrink_noapi = await (async function () { var mm = mk([ok(200)]); var f = { name: 'a.jpg', type: 'image/jpeg' }; var res = await mm.F.shrinkImage(f); return { shrunk: res.shrunk, same: res.blob === f }; })();

  // 8. 定位
  async function geo(behavior) {
    var mm = mk([ok(200)], { geolocation: { getCurrentPosition: function (ok2, err2, opts) { mm.geoOpts = opts; behavior(ok2, err2); } } });
    var res = await drive(mm.clock, mm.F.geoOnce());
    return { res: res, opts: mm.geoOpts };
  }
  OUT.geo_ok = await geo(function (okf) { okf({ coords: { latitude: 25.033, longitude: 121.5654, accuracy: 12.34 } }); });
  OUT.geo_denied = await geo(function (okf, errf) { errf({ code: 1 }); });
  OUT.geo_never = await geo(function () { /* 兩個 callback 都不呼叫 */ });
  OUT.geo_throw = await geo(function () { throw new Error('boom'); });
  OUT.geo_none = await (async function () { var mm = mk([ok(200)]); return { res: await mm.F.geoOnce() }; })();

  // 9. 冪等鍵格式
  var re = /^[A-Za-z0-9_-]{8,128}$/;
  OUT.keys = { fallback: (function () { var mm = mk([ok(200)], { random: function () { return 0.5; } }); var a = mm.F.newKey(), b = mm.F.newKey(); return { a: a, okFormat: re.test(a), same: a === b }; })(),
               real: (function () { var mm = mk([ok(200)]); var a = mm.F.newKey(), b = mm.F.newKey(); return { okFormat: re.test(a) && re.test(b), distinct: a !== b }; })() };

  // 10. 草稿
  m = mk([ok(200)]);
  m.F.saveDraft('MQ-1', '剛打的字');
  var got = m.F.loadDraft('MQ-1'); var other = m.F.loadDraft('MQ-2');
  m.F.clearDraft('MQ-1');
  OUT.draft = { got: got, other: other, after: m.F.loadDraft('MQ-1') };
  OUT.draft_nostorage = (function () { var mm = mk([ok(200)], { sessionStorage: { getItem: function () { throw new Error('x'); }, setItem: function () { throw new Error('x'); }, removeItem: function () { throw new Error('x'); } } }); mm.F.saveDraft('a', 'b'); return { load: mm.F.loadDraft('a') }; })();

  // 11. 形狀 B 全流程
  function photoFiles(n) { var a = []; for (var i = 0; i < n; i++) a.push({ name: 'p' + i + '.jpg', type: 'image/jpeg', size: 100 + i }); return a; }
  function bodyOf(l) { return l.body.entries.map(function (e) { return [e.name, e.value, e.filename]; }); }

  // 11a 正常：文字先、再逐張；各自一把 key；帶 geo
  var s = imgDeps(4000, 3000);
  m = mk([ok(201, { id: 77 }), ok(201, { ok: true, added: 1 }), ok(201, { ok: true, added: 1 })], s.d);
  var events = [];
  var h = m.F.postCaseUpdate({ quoteNo: 'MQ-202611-001', text: ' 到場了 ', important: false, files: photoFiles(2), geo: '25.033000,121.565400,10', onEvent: function (ev) { events.push(ev.type + (ev.index !== undefined ? ':' + ev.index : '')); } });
  var st = await drive(m.clock, h.promise);
  OUT.flow_ok = { urls: m.log.map(function (l) { return l.url; }), keys: keysOf(m.log), textBody: bodyOf(m.log[0]), photoBody0: bodyOf(m.log[1]), textStatus: st.text.status, photos: st.photos.map(function (p) { return p.status; }), updateId: st.updateId,
                  firstEvents: events.slice(0, 2), lastEvent: events[events.length - 1], progressSeen: events.some(function (e) { return e.indexOf('photo') === 0; }) };

  // 11b 沒打字只傳照片 ⇒ 文字用預設句
  m = mk([ok(201, { id: 3 }), ok(201, {})], imgDeps(10, 10).d);
  await drive(m.clock, m.F.postCaseUpdate({ quoteNo: 'Q', text: '   ', files: photoFiles(1) }).promise);
  OUT.flow_empty_text = { content: bodyOf(m.log[0]).filter(function (e) { return e[0] === 'content'; })[0][1] };

  // 11c 文字失敗（400）⇒ 照片不送
  m = mk([ok(400, { detail: '內容不合法' })]);
  h = m.F.postCaseUpdate({ quoteNo: 'Q', text: 'x', files: photoFiles(2) });
  st = await drive(m.clock, h.promise);
  OUT.flow_text_fail = { calls: m.log.length, text: st.text.status, photos: st.photos.map(function (p) { return p.status; }) };

  // 11d 一張失敗（400）不影響其他；retryFailed 只重傳失敗那張，同 key、同位元組
  m = mk([ok(201, { id: 5 }), ok(201, {}), ok(400, { detail: '壞檔' }), ok(201, {}), ok(201, {})], imgDeps(10, 10).d);
  h = m.F.postCaseUpdate({ quoteNo: 'Q', text: 'x', files: photoFiles(3) });
  st = await drive(m.clock, h.promise);
  var afterFirst = { statuses: st.photos.map(function (p) { return p.status; }), calls: m.log.length, keysFirst: keysOf(m.log) };
  var blobBefore = st.photos[1].blob;
  var keyBefore = st.photos[1].key;
  st = await drive(m.clock, h.retryFailed());
  OUT.flow_partial_retry = { afterFirst: afterFirst, afterRetry: { statuses: st.photos.map(function (p) { return p.status; }), calls: m.log.length, retryUrl: m.log[m.log.length - 1].url, retryKey: m.log[m.log.length - 1].headers['Idempotency-Key'], sameKey: m.log[m.log.length - 1].headers['Idempotency-Key'] === keyBefore, sameBlob: m.log[m.log.length - 1].body.entries[0].blob === blobBefore } };

  // 11e 文字失敗後重送：同一把文字 key
  m = mk([{ type: 'neterr' }, { type: 'neterr' }, { type: 'neterr' }, { type: 'neterr' }, ok(201, { id: 8 }), ok(201, {})], imgDeps(10, 10).d);
  h = m.F.postCaseUpdate({ quoteNo: 'Q', text: 'x', files: photoFiles(1) });
  st = await drive(m.clock, h.promise);
  var failedText = { text: st.text.status, calls: m.log.length, photoStatus: st.photos[0].status };
  st = await drive(m.clock, h.retryFailed());
  OUT.flow_text_retry = { failedText: failedText, after: { text: st.text.status, photo: st.photos[0].status, textKeys: keysOf(m.log).slice(0, 5), calls: m.log.length } };

  // 11f 401 在文字階段 ⇒ 導登入、不送照片
  m = mk([ok(401, {})]);
  h = m.F.postCaseUpdate({ quoteNo: 'Q', text: 'x', files: photoFiles(1) });
  st = await drive(m.clock, h.promise);
  OUT.flow_401 = { redirects: m.redirects, calls: m.log.length, gated: !!st.gated };

  // 11g 縮圖後送出去的是縮過的 blob 與 .jpg 檔名
  s = imgDeps(4000, 3000);
  m = mk([ok(201, { id: 1 }), ok(201, {})], s.d);
  await drive(m.clock, m.F.postCaseUpdate({ quoteNo: 'Q', text: 'x', files: [{ name: 'IMG_9.HEIC', type: 'image/heic', size: 5000000 }] }).promise);
  OUT.flow_shrunk_upload = { filename: m.log[1].body.entries[0].filename, blob: m.log[1].body.entries[0].value, canvas: s.calls.canvases[0] };

  // 11h 路徑跳脫
  m = mk([ok(201, { id: 1 })]);
  await drive(m.clock, m.F.postCaseUpdate({ quoteNo: 'MQ/../x y', text: 'x', files: [] }).promise);
  OUT.flow_url_encoded = { url: m.log[0].url };

  console.log(JSON.stringify(OUT));
})().catch(function (e) { console.log(JSON.stringify({ __error: String(e && e.stack || e) })); process.exit(1); });
