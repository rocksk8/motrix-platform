/* record-link.js — 地圖點位 ↔ 單據頁的雙向連結（MP1，2026-09-24）
 *
 * - `recordUrl(p, session)`：地圖上的一個點 → 它的單據頁網址；**看不到那一頁的人回 null**
 *   （顯示純文字）。🔴 判準照各單據頁**自己的**入口檢查，不是照地圖的資料集權限——
 *   兩者不同（例：協力廠商頁限管理員，地圖上的協力廠商資料集只要模組），
 *   而一個點了會被「此頁面需要管理員權限」彈回來的連結，比沒有連結更糟。
 * - `focusKey(p)`：`<來源>:<記錄>`，地圖頁 `?focus=` 與單據頁「在地圖上看」共用同一種寫法。
 * - `param(name)`／`notFound(text)`：單據頁讀 deep link；找不到那一筆時**要說出來**，
 *   不可以靜靜停在清單上（使用者會以為連結壞了、或那筆資料不存在而其實只是被篩掉）。
 */
(function () {
  function mods(session) {
    var m = (session && session.modules) || []
    if (typeof m === 'string') { try { m = JSON.parse(m) } catch (_e) { m = [] } }
    return Array.isArray(m) ? m : []
  }
  function role(session) { return (session && session.role) || '' }

  //: 各單據頁的入口檢查（與頁面 `init()` 裡那一段一致）。沒有列的頁＝頁面本身不擋。
  var PAGE_GATE = {
    'contractors.html': function (s) {
      return role(s) === 'superadmin' || mods(s).indexOf('contractor_list') >= 0
    },
    'vendor-contractors.html': function (s) {
      return role(s) === 'superadmin' || role(s) === 'admin'
    },
    'tender-radar.html': function (s) {
      return role(s) === 'superadmin' || role(s) === 'admin' || mods(s).indexOf('dev_crm') >= 0
    },
  }

  function key(p) {
    if (!p) return null
    if (p.recordId !== null && p.recordId !== undefined) return String(p.recordId)
    if (p.caseNo) return String(p.caseNo)
    return null
  }

  function target(p) {
    var k = key(p)
    if (k === null) return null
    var enc = encodeURIComponent(k)
    switch (p.sourceKey) {
      case 'customers':          return 'customers.html?id=' + enc
      case 'suppliers':          return 'suppliers.html?id=' + enc
      case 'contractors':        return 'contractors.html?id=' + enc
      case 'vendor_contractors': return 'vendor-contractors.html?id=' + enc
      case 'tenders':            return 'tender-radar.html?case=' + enc
      case 'cases':
        // `MP6`：案件地點 ⇒ 案件頁（recordId 就是 quote_no）。
        return 'case-management.html?q=' + enc
      case 'shipping_notes':
        // 出貨單沒有自己的頁 ⇒ 落在所屬案件的「出貨」分頁。
        return p.quoteNo ? ('case-management.html?q=' + encodeURIComponent(p.quoteNo)
                            + '&tab=shipping') : null
    }
    return null
  }

  window.MotrixRecordLink = {
    focusKey: function (p) {
      var k = key(p)
      return (p && p.sourceKey && k !== null) ? (p.sourceKey + ':' + k) : null
    },
    recordUrl: function (p, session) {
      var url = target(p)
      if (!url) return null
      var page = url.split('?')[0]
      var gate = PAGE_GATE[page]
      if (gate && !gate(session)) return null
      // STATES-PLATFORM P-FE-06：頁面屬於這次沒有載入的模組（停用／未授權／失敗／不在安裝包）⇒ 不產生連結。
      //   狀態由 sidebar.js 取回（`MOTRIX_MODULE_AVAILABILITY`）；還沒取回（未知）⇒ 照舊產生，
      //   點了由該頁的提示頁接手（P-FE-03）。
      var mp = window.MOTRIX_MODULE_PAGES && window.MOTRIX_MODULE_PAGES[page]
      var av = window.MOTRIX_MODULE_AVAILABILITY
      if (mp && av && !(av[mp.key] && av[mp.key].state === 'loaded')) return null
      return url
    },
    mapUrl: function (sourceKey, recordKey) {
      return 'map.html?focus=' + encodeURIComponent(sourceKey + ':' + recordKey)
    },
    param: function (name) {
      try { return new URLSearchParams(location.search).get(name) } catch (_e) { return null }
    },
    notFound: function (text) {
      var el = document.createElement('div')
      el.className = 'motrix-deeplink-miss'
      el.setAttribute('role', 'status')
      el.textContent = text
      el.style.cssText = 'position:fixed;top:calc(var(--topbar-h,48px) + 8px);left:50%;'
        + 'transform:translateX(-50%);z-index:9999;background:var(--warning,#b45309);color:#fff;'
        + 'padding:8px 14px;border-radius:6px;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,.25);'
        + 'cursor:pointer'
      el.addEventListener('click', function () { el.remove() })
      document.body.appendChild(el)
      setTimeout(function () { el.remove() }, 8000)
    },
  }
})();
