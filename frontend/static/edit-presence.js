/* edit-presence.js — 同時編輯警示（2026-09-14）
 *
 * 用途：一進入某份單據的編輯畫面就回報「我在這裡」，並在**有別人也在同一份單據上**
 * 時，於畫面頂端顯示一條警示。使用者要求：「如果有兩個人同時進入報價單、或是修改
 * 同一個表格的內容，需跳出警示，避免兩人同時修改損失一方資料」。
 *
 * 這是**第二道**防線。第一道早就在：存檔時比對 `updated_at`，對不上就 409
 * 「已被其他人更新，請重新載入後再存」（報價單／案件資料／款項／規劃書／業務開發案／
 * 派工單）。那道保證資料不會被無聲覆蓋，但使用者要等到按下存檔才知道白做了 20 分鐘；
 * 這一道讓他一進去就知道。
 *
 * 刻意做成 presence 而不是 lock：鎖一定要處理「誰來解鎖」（關分頁、當機、下班沒關），
 * 最後都要做強制解鎖，而強制解鎖又回到兩人同時編的原點。看得到彼此就足以先喊一聲。
 *
 * 用法（任何編輯頁）：
 *     <script src="../static/edit-presence.js"></script>
 *     MotrixPresence.start('quotation', quoteNo)     // 進入編輯
 *     MotrixPresence.stop()                          // 離開（選用；沒呼叫也會自然過期）
 *
 * `docId` 可以隨時改變（例如案件管理切換選取的案件）——重複呼叫 start() 即可，
 * 它會自動釋放前一份。
 */
(function () {
  var TYPE = null, ID = null, timer = null, bar = null, modal = null;
  // 已經對「這份資料的這個人」跳過提示了就不再跳——同一個人每 30 秒跳一次會變成噪音，
  // 而噪音的下場是使用者學會無視它，等於這個功能不存在。
  var notified = {};
  // 心跳間隔。原本 30 秒，2026-09-14 實測（e2e「編輯途中有人加入」）發現**先進來的
  // 那個人最久要等 30 秒才會知道有人加入**——而那正是最容易互相覆蓋的情境。改成 15 秒：
  // 每個開著的編輯頁每分鐘 4 次請求，內網個位數使用者完全可接受，換到的是使用者及時
  // 知道。後端 TTL 90 秒不變（掉個三四次才誤判離開，仍有很大緩衝）。
  var HEARTBEAT_MS = 15000;
  // 已經知道有人同時在編時，把間隔縮短：這時候「對方離開了沒」是使用者真正在等的
  // 資訊，而這種情況很少見，多打幾次請求的代價可以接受。
  var HEARTBEAT_BUSY_MS = 8000;

  function token() {
    try { return (JSON.parse(localStorage.getItem('motrix_session') || '{}') || {}).token || ''; }
    catch (e) { return ''; }
  }

  // W-1（2026-09-24）：提示條原本疊在內容上（position:fixed），第二個人開同一件時案件頁標頭的
  // 「儲存」「更多」被它蓋住。改成顯示時把它的高度加進 --topbar-h——全站內容都用這個變數讓出上方
  // 空間，所以 5 個有提示條的頁面一起往下讓；提示條本身用「加之前的原值」定位，隱藏時還原。
  var baseTopbar = null;
  function reserveSpace(on) {
    var root = document.documentElement;
    if (baseTopbar === null) {
      baseTopbar = getComputedStyle(root).getPropertyValue('--topbar-h').trim() || '54px';
      root.style.setProperty('--presence-top', baseTopbar);
    }
    if (on && bar) root.style.setProperty('--topbar-h', 'calc(' + baseTopbar + ' + ' + bar.offsetHeight + 'px)');
    else root.style.removeProperty('--topbar-h');
  }
  window.addEventListener('resize', function () {
    if (bar && bar.style.display !== 'none') reserveSpace(true);   // 窄螢幕換行時高度會變
  });

  function ensureBar() {
    if (bar) return bar;
    bar = document.createElement('div');
    bar.id = 'motrix-presence-bar';
    bar.style.cssText =
      'display:none;position:fixed;top:var(--presence-top,var(--topbar-h,54px));left:0;right:0;z-index:400;' +
      'background:#FEF3C7;border-bottom:1px solid #FDE68A;color:#92400E;' +
      'padding:9px 18px;font-size:13px;font-family:var(--font-zh, sans-serif);' +
      'display:flex;align-items:center;gap:10px;box-shadow:0 2px 8px rgba(0,0,0,.08)';
    bar.style.display = 'none';
    document.body.appendChild(bar);
    return bar;
  }

  function render(others) {
    var el = ensureBar();
    if (!others || !others.length) { el.style.display = 'none'; reserveSpace(false); return; }
    // §9 XSS 規範：displayName 是使用者可控字串，一律用 DOM API 插入，不用 innerHTML
    el.textContent = '';
    var icon = document.createElement('span');
    icon.style.fontSize = '15px';
    icon.textContent = '⚠️';
    var msg = document.createElement('span');
    var who = document.createElement('b');
    who.textContent = others.map(function (o) { return o.displayName; }).join('、');
    msg.appendChild(who);
    msg.appendChild(document.createTextNode(
      ' 目前也在編輯這一份。兩邊同時存檔時，後存的人會收到「已被其他人更新」'
      + '而必須重新載入——建議先確認由誰來改。'));
    el.appendChild(icon);
    el.appendChild(msg);
    el.style.display = 'flex';
    reserveSpace(true);
  }


  // ── 主動提示（2026-09-14 使用者要求「先跳出提示」）───────────────────────
  //
  // 原本只有頂端一條橫幅。橫幅是**被動**的：使用者盯著自己的欄位打字，根本不會
  // 注意到上面多了一條。改成進入時（已有人在編）與編輯途中（有人加入）都主動跳
  // 一次對話框，看過就不再跳同一個人——橫幅仍然留著當持續指示。
  //
  // 刻意**不擋輸入**：這是提示不是鎖（見檔頭）。真的兩邊都存，還有存檔時的 409。
  function showModal(names) {
    closeModal();
    modal = document.createElement('div');
    modal.id = 'motrix-presence-modal';
    modal.style.cssText =
      'position:fixed;inset:0;z-index:900;background:rgba(0,0,0,.38);' +
      'display:flex;align-items:center;justify-content:center;padding:20px';

    var box = document.createElement('div');
    box.style.cssText =
      'background:#fff;border-radius:12px;max-width:420px;width:100%;' +
      'box-shadow:0 20px 60px rgba(0,0,0,.22);font-family:var(--font-zh, sans-serif)';

    var head = document.createElement('div');
    head.style.cssText = 'padding:16px 20px;border-bottom:1px solid #E5E7EB;font-size:15px;font-weight:600';
    head.textContent = '⚠️ 有人同時在編輯這一份';

    var body = document.createElement('div');
    body.style.cssText = 'padding:18px 20px;font-size:13px;line-height:1.9;color:#374151';
    var who = document.createElement('b');
    who.textContent = names.join('、');          // 使用者可控字串 → 一律 textContent
    body.appendChild(who);
    body.appendChild(document.createTextNode(
      ' 目前也在這份資料裡。兩邊都改的話，先存的人會被後存的人覆蓋——'));
    var strong = document.createElement('b');
    strong.textContent = '系統會擋下後存的那一次並要求重新載入';
    body.appendChild(strong);
    body.appendChild(document.createTextNode(
      '，但你這段時間打的內容會需要重做。建議先確認由誰來改。'));

    var foot = document.createElement('div');
    foot.style.cssText = 'padding:12px 20px;border-top:1px solid #E5E7EB;display:flex;justify-content:flex-end;gap:8px';
    var ok = document.createElement('button');
    ok.className = 'btn btn-primary btn-sm';
    ok.textContent = '我知道了';
    ok.onclick = closeModal;
    foot.appendChild(ok);

    box.appendChild(head);
    box.appendChild(body);
    box.appendChild(foot);
    modal.appendChild(box);
    modal.addEventListener('click', function (e) { if (e.target === modal) closeModal(); });
    document.addEventListener('keydown', onEsc);
    document.body.appendChild(modal);
  }

  function onEsc(e) { if (e.key === 'Escape') closeModal(); }

  function closeModal() {
    document.removeEventListener('keydown', onEsc);
    if (modal && modal.parentNode) modal.parentNode.removeChild(modal);
    modal = null;
  }

  function retime(busy) {
    var want = busy ? HEARTBEAT_BUSY_MS : HEARTBEAT_MS;
    if (timer && timer._ms === want) return;
    if (timer) clearInterval(timer);
    timer = setInterval(beat, want);
    timer._ms = want;
  }

  function beat() {
    if (!TYPE || !ID) return;
    fetch('/api/edit-presence', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token() },
      body: JSON.stringify({ doc_type: TYPE, doc_id: String(ID) })
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d) return;
        render(d.others);
        retime((d.others || []).length > 0);
        // 只對「這一輪新出現的人」跳提示：進入時已經在的人算新的（這正是使用者
        // 要的「先跳出提示」），之後每有人加入也各跳一次。
        var key = TYPE + '/' + ID;
        notified[key] = notified[key] || {};
        var fresh = (d.others || []).filter(function (o) { return !notified[key][o.username]; });
        if (fresh.length) {
          fresh.forEach(function (o) { notified[key][o.username] = true; });
          showModal(fresh.map(function (o) { return o.displayName; }));
        }
      })
      .catch(function () { /* 網路瞬斷不該讓編輯頁跳錯誤，靜默重試下一輪 */ });
  }

  function release(type, id) {
    if (!type || !id) return;
    try {
      fetch('/api/edit-presence', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token() },
        body: JSON.stringify({ doc_type: type, doc_id: String(id) }),
        keepalive: true      // 關頁面時仍送得出去
      }).catch(function () {});
    } catch (e) {}
  }

  window.MotrixPresence = {
    start: function (docType, docId) {
      if (!docType || !docId) return;
      if (TYPE === docType && String(ID) === String(docId)) return;   // 同一份，不重來
      if (TYPE && ID) release(TYPE, ID);
      TYPE = docType; ID = docId;
      closeModal();
      render([]);
      beat();
      if (timer) clearInterval(timer);
      timer = setInterval(beat, HEARTBEAT_MS);
    },
    stop: function () {
      if (timer) { clearInterval(timer); timer = null; }
      closeModal();
      if (TYPE && ID) release(TYPE, ID);
      TYPE = ID = null;
      if (bar) { bar.style.display = 'none'; reserveSpace(false); }
    },
    // 存檔收到 409 時可以叫這個，立刻更新警示內容
    refresh: beat
  };

  window.addEventListener('beforeunload', function () {
    if (TYPE && ID) release(TYPE, ID);
  });

  // 切到背景分頁就不必再心跳（省請求）；切回來立刻補一次
  document.addEventListener('visibilitychange', function () {
    if (!TYPE || !ID) return;
    if (document.hidden) {
      if (timer) { clearInterval(timer); timer = null; }
    } else if (!timer) {
      beat();
      timer = setInterval(beat, HEARTBEAT_MS);
    }
  });
})();
