/* ux-wizard.js — 首次設定精靈外殼（A1，2026-11-11 UX 提案）
 *
 * 把「強制改密碼 → 確認公司資料 → 兩步驟驗證（可略過）→ 開始使用」串成一條有步驟條的路。
 * 不新增頁面：在既有的 my-account.html（舊名 change-password.html）／company-profile-settings.html 上
 *   ① 隱藏頂欄與選單（新手不該在這時候被 35 個目的地分心）；
 *   ② 在頁首放「步驟 n／N」＋步驟條＋「為什麼要做這步」一句話。
 *
 * 載入方式：這兩頁的 <head> 以同步 <script> 載入（要在畫面出現之前就把 <html> 標成 ux-wizard，否則會先閃一下頂欄）。
 *
 * 判定（只看網址與 session，不打任何 API——強制改密碼期間大部分 API 本來就會被擋）：
 *   my-account.html?forced=1              ⇒ 步驟「設新密碼」
 *   my-account.html?wizard=totp           ⇒ 步驟「兩步驟驗證」
 *   company-profile-settings.html?setup=1 ⇒ 步驟「確認公司資料」
 * 步驟數依角色：最高管理者 4 步（要確認公司資料）；其他人 2 步（改完密碼就能用）。
 *
 * 「步驟 n／N」只在**真的走過第 1 步**時顯示（sessionStorage 旗標 motrix_wizard，第 1 步載入時寫入）：
 * 之後某天因為「資料庫搬家需要重新確認公司資料」再被擋到閘門頁時，不會冒出一個沒頭沒尾的「步驟 2／4」，
 * 只是同一個精簡外殼、沒有步數。
 */
(function () {
  'use strict'
  var FLAG = 'motrix_wizard'
  var file = window.location.pathname.split('/').pop() || ''
  var q = new URLSearchParams(window.location.search)
  var mode = ''
  var onAccount = file === 'my-account.html' || file === 'change-password.html'   // 舊網址保留（會轉到 my-account.html，帶同樣的 query）
  if (onAccount && q.get('forced') === '1') mode = 'pw'
  else if (onAccount && q.get('wizard') === 'totp') mode = 'totp'
  else if (file === 'company-profile-settings.html' && q.get('setup') === '1') mode = 'company'
  if (!mode) { window.MotrixWizard = { mode: '' }; return }

  var sess = {}
  try { sess = JSON.parse(localStorage.getItem('motrix_session') || '{}') } catch (e) { sess = {} }
  var isSuper = sess.role === 'superadmin'
  var STEPS = isSuper
    ? ['設新密碼', '確認公司資料', '兩步驟驗證（可略過）', '開始使用']
    : ['設新密碼', '開始使用']
  var idx = mode === 'pw' ? 0 : mode === 'company' ? 1 : 2
  function flagGet() { try { return sessionStorage.getItem(FLAG) === '1' } catch (e) { return false } }
  function flagSet() { try { sessionStorage.setItem(FLAG, '1') } catch (e) {} }
  // 只有最高管理者後面還有步驟（公司資料、兩步驟驗證）才需要旗標；其他人改完密碼就結束，不留痕跡
  if (mode === 'pw' && isSuper) flagSet()
  var counted = mode === 'pw' || flagGet()          // 第 1 步本身一定顯示步數；之後要走過第 1 步才顯示

  var WHY = {
    pw: '這是系統（或管理員）給您的臨時密碼。為了帳號安全，請先設定一組只有您知道的新密碼；設好後會請您用新密碼重新登入。',
    company: '報價單、請款單等輸出文件會用這裡的公司名稱、統一編號與聯絡方式當抬頭。請確認是貴公司的資料；完成這一步，其他功能才會開放。',
    totp: '兩步驟驗證會在登入時多一道手機驗證碼，帳號更安全，建議啟用。現在不想設也可以：按「稍後再說」直接開始使用，之後隨時能到「修改密碼」頁開啟。',
  }
  var TITLE = { pw: '設新密碼', company: '確認公司資料', totp: '兩步驟驗證' }

  // 精靈裡已經有「兩步驟驗證」這一步，使用者做過選擇 ⇒ 不要在他按下「稍後再說」的同一秒，
  // 又從右下角跳出一張「尚未啟用兩步驟驗證」的橘色提醒（notif.js，每個分頁最多一次）。
  if (isSuper) { try { sessionStorage.setItem('motrix_totp_reminder_shown', '1') } catch (e) {} }

  document.documentElement.classList.add('ux-wizard')
  document.documentElement.setAttribute('data-ux-wizard', mode)

  function esc(t) { return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') }

  function mount() {
    if (document.getElementById('ux-wizard')) return
    var el = document.createElement('div')
    el.className = 'ux-wiz'
    el.id = 'ux-wizard'
    el.setAttribute('data-testid', 'ux-wizard')
    var h = '<div class="ux-wiz__brand"><span class="ux-wiz__logo"><img src="/api/system/branding/logo-dark" alt="" onerror="this.parentNode.style.display=\'none\'"></span><span>首次設定</span></div>'
    if (counted) {
      h += '<div class="ux-wiz__count" data-testid="ux-wizard-count" aria-live="polite">步驟 ' + (idx + 1) + '／' + STEPS.length + '：' + esc(TITLE[mode]) + '</div>'
      h += '<ol class="ux-wiz__steps" aria-label="設定步驟">'
      STEPS.forEach(function (s, i) {
        h += '<li class="' + (i < idx ? 'is-done' : i === idx ? 'is-cur' : '') + '"' + (i === idx ? ' aria-current="step"' : '') + '>'
          + (i < idx ? '✓ ' : (i + 1) + '. ') + esc(s) + '</li>'
      })
      h += '</ol>'
    } else {
      h += '<div class="ux-wiz__count">' + esc(TITLE[mode]) + '</div>'
    }
    h += '<p class="ux-wiz__why" data-testid="ux-wizard-why">' + esc(WHY[mode]) + '</p>'
    el.innerHTML = h
    document.body.insertBefore(el, document.body.firstChild)
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount)
  else mount()

  window.MotrixWizard = {
    mode: mode, step: idx + 1, total: STEPS.length, isSuper: isSuper, counted: counted,
    // 走完（或略過）整條路：清旗標，之後回到平常的樣子
    finish: function () { try { sessionStorage.removeItem(FLAG) } catch (e) {} },
  }
})()
