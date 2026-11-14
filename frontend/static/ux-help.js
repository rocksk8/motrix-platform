/* ux-help.js — 「？」情境說明抽屜（A5）＋「第一次來？」橫幅（A4）＋名詞解釋（E2）
 *
 * 2026-11-11 UX 提案 A4／A5／E2。**全站只有這一份內容表**：
 *   - 要加／改某一頁的說明、橫幅文字、名詞定義 ⇒ 只改下面的 PAGES／TERMS，不用動各頁 html。
 *   - 由 sidebar.js 在頂欄建好後載入；頂欄的「？」鈕（#ux-help-btn）由 sidebar.js 放，這裡接事件。
 *
 * 規則：
 *   - 橫幅只在 PAGES[檔名].hint 有寫的頁面出現；關掉後記在 localStorage（每個帳號各自記），
 *     從抽屜裡的「重看首次使用導覽」可以重新打開。localStorage 讀不到／寫不進去時橫幅每次都顯示（寧可多顯示，不當掉）。
 *   - 沒寫內容的頁面，抽屜顯示通用說明（頁名＋怎麼找功能＋名詞解釋），不留空白。
 *   - 這裡只放「畫面導讀」；不放任何會隨設定改變的數字或規則（那些由各頁自己顯示），避免說明與實際不符。
 */
(function () {
  'use strict'

  // ── 名詞解釋（E2）：id → [名稱, 白話定義] ────────────────────────────────
  var TERMS = {
    quote_no:    ['報價單號', '每張報價單的編號，系統依年月自動編，例如 MQ-202611-001。'],
    approval:    ['簽核', '送出後由指定的主管依序審核；核准前通常不能再修改。流程由「簽核流程設定」決定。'],
    won:         ['已成案', '客戶確定採用這份報價、轉成正式案件。需要先完成簽核才能標記。'],
    discount:    ['折讓', '成交後對客戶的價格減讓（例如抹零、客訴補償），會留下紀錄。'],
    internal:    ['內部成本與利潤', '只給公司內部看的成本與利潤區塊，不是給客戶看的內容。'],
    gross:       ['毛利率', '（售價 − 成本）÷ 售價。數字越高，代表這筆案件留在公司的利潤比例越高。'],
    overhead:    ['管銷分攤', '把公司共同的管理與銷售費用，依比例分攤至每個案件，才能判斷扣掉這些之後是否仍有獲利。'],
    tax_id:      ['統一編號', '8 碼數字，最後一碼是檢查碼；輸入錯誤時系統會提示。'],
    backlog:     ['待辦清單（BACKLOG）', '已經提出、尚未開始做的事項。'],
  }

  // ── 各頁說明內容 ─────────────────────────────────────────────────────────
  // purpose：這頁做什麼（一句話）｜steps：最常見的做法（3–4 步）｜hint：橫幅文字（沒寫＝這頁不出橫幅）
  // anchor：橫幅插入的容器（CSS selector，插在容器最前面）；找不到就不顯示（不硬塞到會破版的地方）
  // terms：名詞解釋要列哪幾個
  var PAGES = {
    'index.html': {
      purpose: '營運總覽：待辦、進行中的案件與本期數字都從這裡看。',
      steps: ['先看「上手清單」，依序完成建立客戶、第一張報價單、簽核流程。', '上方選單進入各功能。', '找不到功能時，請使用上方搜尋框輸入關鍵字。'],
    },
    'quotations.html': {
      purpose: '所有報價單與估價單的清單：依狀態分頁、搜尋、複製或開新單。',
      steps: ['按「新增報價單」開一張新單。', '用上方狀態分頁看「草稿／已送出／已成案」。', '點任一筆進入表單檢視或修改。'],
      hint: '初次使用？這裡列出所有報價單與估價單。如需建立新單，請按右上方的「新增報價單」或「新增估價單」；已建立的單據按一下即可開啟。',
      anchor: 'main.main',
      terms: ['quote_no', 'approval', 'won'],
    },
    'quotation-form.html': {
      purpose: '填寫單張報價單：客戶、品項、價格與條款都在這一頁。',
      steps: ['先選客戶，再逐列加入品項與數量單價。', '右側「內部成本與利潤」區塊僅供公司內部查看，並非提供客戶的內容。', '存成草稿隨時可以回來改；確認後再「申請送出簽核」。'],
      hint: '初次使用？由上而下填：客戶 → 品項 → 價格與條款。草稿可隨時儲存，確認無誤再送出簽核。',
      anchor: '.form-left',
      terms: ['internal', 'gross', 'overhead', 'approval', 'won', 'discount'],
    },
    'case-management.html': {
      purpose: '案件的工作台：左邊挑案件，右邊看進度、文件、派工與帳務。',
      steps: ['案件通常由報價單「成案」後產生；先到報價單把案子標記為已成案。', '在左側清單點選案件。', '右側依分頁處理進度、文件與費用。'],
      hint: '初次使用？案件多半從報價單「成案」而來。請於左側選擇案件，右側將顯示其進度、文件與費用。',
      anchor: '.cm-placeholder',   // 只在「還沒選案件」的空白區顯示：選了案件後詳情區的版面一動就會頂到頁面底部的提醒（test_e2e_notice_banners）
      terms: ['won'],
    },
    'approval-queue.html': {
      purpose: '輪到您簽核的單據都在這裡。',
      steps: ['左欄「待我簽核」逐筆展開查看內容。', '核准、退回或加上意見。', '處理完的會移到「已處理」。'],
      hint: '初次使用？「待我簽核」為輪到您處理的單據；開啟單據可查看內容，再選擇核准或退回。',
      anchor: '.aq-layout',
      terms: ['approval'],
    },
    'approval-settings.html': {
      purpose: '決定哪些單據、什麼條件需要誰簽核。',
      steps: ['先選要設定的單據類型。', '設定每一關的簽核人與條件。', '儲存前確認「影響」說明；已在簽核中的單據不受新規則影響。'],
      hint: '初次使用？這頁決定「誰要簽什麼」。可以先用系統預設的流程，之後再依公司需要調整。',
      anchor: '.pg',
      terms: ['approval'],
    },
    'customers.html': {
      purpose: '客戶資料庫：報價單與案件都會從這裡選客戶。',
      steps: ['按「新增客戶」建立第一筆。', '填公司名稱即可先存，其他資料之後補。', '到報價單選這個客戶。'],
      terms: ['tax_id'],
    },
    'system-hub.html': {
      purpose: '系統管理入口：帳號、流程、通知、資料與稽核。',
      steps: ['左邊選分類。', '右邊挑要設定的項目。', '找不到時用上方搜尋框。'],
    },
    'company-profile-settings.html': {
      purpose: '本公司的名稱、統一編號、聯絡方式與品牌；輸出的報價單、請款單等文件會使用這些資料。',
      steps: ['確認公司名稱、統一編號、電話或 Email。', '需要時再設定 Logo、據點與收款帳戶。'],
      terms: ['tax_id'],
    },
  }

  var GENERIC_STEPS = [
    '上方選單依「客戶與業務／案件／採購與庫存／報表／財務會計…」分類；找不到功能時，請使用上方搜尋框輸入關鍵字。',
    '多數列表頁右上角有「新增」按鈕；列表空白代表尚無資料，並非故障。',
    '不熟悉的名詞，可在下方「名詞解釋」查詢。',
  ]

  // ── 小工具 ───────────────────────────────────────────────────────────────
  function esc(t) {
    return String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
  }
  var file = (window.location.pathname.split('/').pop() || 'index.html')
  var sess = {}
  try { sess = JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) { sess = {} }
  var who = String(sess.username || sess.userId || sess.displayName || 'u')
  function hintKey(f) { return 'motrix_ux_hint_' + who + '_' + (f || file) }
  function hintDismissed(f) { try { return localStorage.getItem(hintKey(f)) === '1' } catch (e) { return false } }
  function setHintDismissed(on, f) { try { if (on) localStorage.setItem(hintKey(f), '1'); else localStorage.removeItem(hintKey(f)) } catch (e) {} }
  // 上手清單（index.html）需要知道「有沒有看過簽核流程設定」；只記下面這幾頁，不記瀏覽歷史
  var VISIT_TRACK = ['approval-settings.html']
  if (VISIT_TRACK.indexOf(file) >= 0) {
    try {
      var vk = 'motrix_ux_visited_' + who
      var seen = JSON.parse(localStorage.getItem(vk) || '[]')
      if (seen.indexOf(file) < 0) { seen.push(file); localStorage.setItem(vk, JSON.stringify(seen)) }
    } catch (e) {}
  }
  function pageTitle() {
    var t = document.title || ''
    var i = t.indexOf('—'); if (i < 0) i = t.indexOf(' - ')
    return (i >= 0 ? t.slice(0, i) : t).trim() || '本頁'
  }

  // ── 橫幅（A4）：沿用系統頁 .first-hint／.hint-x 的樣式（style.css） ─────────
  function renderHint() {
    var cfg = PAGES[file]
    if (!cfg || !cfg.hint) return
    if (document.getElementById('ux-first-hint')) return
    if (hintDismissed()) return
    var anchor = cfg.anchor ? document.querySelector(cfg.anchor) : null
    // Alpine 頁面的容器可能晚一點才出現：最多等 6 秒（每 300ms 一次）；仍沒有就不顯示，不硬塞到別處
    if (!anchor) { if ((renderHint._n = (renderHint._n || 0) + 1) < 20) setTimeout(renderHint, 300); return }
    var box = document.createElement('div')
    box.className = 'first-hint ux-first-hint'
    box.id = 'ux-first-hint'
    box.setAttribute('data-testid', 'ux-first-hint')
    box.innerHTML = '<span>' + esc(cfg.hint) + '</span>'
      + '<span class="ux-first-hint__btns">'
      + '<button type="button" class="hint-x" data-ux="more">查看說明</button>'
      + '<button type="button" class="hint-x" data-ux="dismiss" aria-label="我知道了，不再顯示">我知道了</button>'
      + '</span>'
    box.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('[data-ux]')
      if (!b) return
      if (b.getAttribute('data-ux') === 'dismiss') { setHintDismissed(true); box.remove() }
      else openHelp()
    })
    anchor.insertBefore(box, anchor.firstChild)
  }

  // ── 抽屜（A5） ──────────────────────────────────────────────────────────
  var drawer, lastFocus
  function buildDrawer() {
    if (drawer) return drawer
    var cfg = PAGES[file] || {}
    var termIds = cfg.terms || []
    var h = '<div class="ux-drawer__scrim" data-ux="close"></div>'
      + '<aside class="ux-drawer__panel" role="dialog" aria-modal="true" aria-labelledby="ux-drawer-title" tabindex="-1">'
      + '<div class="ux-drawer__head"><div><div class="ux-drawer__eyebrow">本頁說明</div><h2 id="ux-drawer-title">' + esc(pageTitle()) + '</h2></div>'
      + '<button type="button" class="ux-drawer__x" data-ux="close" aria-label="關閉說明">×</button></div>'
      + '<div class="ux-drawer__body">'
      + '<section><h3>這頁在做什麼</h3><p>' + esc(cfg.purpose || '請從上方選單與搜尋框找到您要用的功能；這一頁的內容依您的權限顯示。') + '</p></section>'
      + '<section><h3>最常見的做法</h3><ol>' + (cfg.steps || GENERIC_STEPS).map(function (s) { return '<li>' + esc(s) + '</li>' }).join('') + '</ol></section>'
    if (termIds.length) {
      h += '<section><h3>名詞解釋</h3><dl>' + termIds.map(function (id) {
        var t = TERMS[id]; return t ? '<dt>' + esc(t[0]) + '</dt><dd>' + esc(t[1]) + '</dd>' : ''
      }).join('') + '</dl></section>'
    }
    h += '<section class="ux-drawer__foot">'
    if (cfg.hint) h += '<button type="button" class="hint-x" data-ux="replay">重看首次使用導覽</button> '
    if (file === 'index.html') h += '<button type="button" class="hint-x" data-ux="checklist">重新開啟上手清單</button> '
    h += '<button type="button" class="hint-x" data-ux="terms">全部名詞解釋</button>'
    h += '<div data-ux-all style="display:none;margin-top:12px"><dl>' + Object.keys(TERMS).map(function (id) {
      return '<dt>' + esc(TERMS[id][0]) + '</dt><dd>' + esc(TERMS[id][1]) + '</dd>'
    }).join('') + '</dl></div></section>'
    h += '</div></aside>'
    drawer = document.createElement('div')
    drawer.className = 'ux-drawer'
    drawer.id = 'ux-drawer'
    drawer.setAttribute('data-testid', 'ux-drawer')
    drawer.hidden = true
    drawer.innerHTML = h
    drawer.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('[data-ux]')
      if (!b) return
      var a = b.getAttribute('data-ux')
      if (a === 'close') closeHelp()
      else if (a === 'replay') {
        setHintDismissed(false); var old = document.getElementById('ux-first-hint'); if (old) old.remove()
        closeHelp(); renderHint()
      } else if (a === 'checklist') {
        try { localStorage.removeItem('motrix_onboarding_banner_dismissed') } catch (e) {}
        window.dispatchEvent(new CustomEvent('motrix-checklist-reopen')); closeHelp()
      } else if (a === 'terms') {
        var all = drawer.querySelector('[data-ux-all]'); all.style.display = all.style.display === 'none' ? 'block' : 'none'
      }
    })
    document.body.appendChild(drawer)
    return drawer
  }
  function openHelp() {
    buildDrawer()
    lastFocus = document.activeElement
    drawer.hidden = false
    var p = drawer.querySelector('.ux-drawer__panel'); if (p) p.focus()
    var btn = document.getElementById('ux-help-btn'); if (btn) btn.setAttribute('aria-expanded', 'true')
  }
  function closeHelp() {
    if (!drawer || drawer.hidden) return
    drawer.hidden = true
    var btn = document.getElementById('ux-help-btn'); if (btn) btn.setAttribute('aria-expanded', 'false')
    if (lastFocus && lastFocus.focus) { try { lastFocus.focus() } catch (e) {} }
  }
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeHelp() })
  // 頂欄是 sidebar.js 動態重建的（角色版面套用後會重畫）⇒ 用事件委派，不綁死按鈕節點
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('#ux-help-btn')
    if (b) { e.preventDefault(); if (drawer && !drawer.hidden) closeHelp(); else openHelp() }
  })

  window.MotrixUX = { openHelp: openHelp, closeHelp: closeHelp, resetHints: function () { setHintDismissed(false) }, TERMS: TERMS, PAGES: PAGES }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', renderHint)
  else renderHint()
})()
