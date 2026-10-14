/* rule-marks.js — BP-2 標示型規則的畫面疊加層（設計 docs/platform/plans/BP2-RULES-MARK-DESIGN-T62.md §7）。
 *
 * 只做一件事：對「宣告了規則插槽的頁面」，把伺服器算好的標示（GET /api/rules/marks）以屬性加在列／卡片上：
 *   data-rule-mark="red|yellow|info"（顏色條，見下方 CSS）與 title（提示文字）。**不新增、不移除任何節點，不改 class／style**
 *   （Alpine 的 :class／:style 會覆蓋，所以只用屬性；樣式由獨立的 <style> 以屬性選擇器套用）。
 * 關閉時完全不動：載入本檔不會做任何事（不送請求、不改畫面）；頁面在已讀到設定 builder_rules.enabled＝1 之後才呼叫 MotrixRuleMarks.start()。
 * start() 之後若頁面沒有登記在 PAGES、或伺服器對規則 API 回 404/401/403（治理旗標沒開、未登入）⇒ 不裝任何觀察器、不加任何東西。
 * 標示是『每位檢視者』的：伺服器以本人的可見欄位評估；看不到來源欄位的人，回應裡根本沒有那條規則的痕跡。
 * 提示文字一律用 setAttribute／textContent，不經 innerHTML。
 */
;(function () {
  if (window.MotrixRuleMarks) return

  //: 宣告了插槽的頁面：頁面檔名 ⇒ 主題、列元素選擇器、取得紀錄代號的屬性。新增一頁＝在這裡加一行（並確認該頁的列元素帶有穩定的代號屬性）。
  var PAGES = {
    'case-management.html': { entity: 'case', item: '.cm-card[data-quote-no]', idAttr: 'data-quote-no' }
  }
  var MAX_IDS = 200
  var RANK = { red: 3, yellow: 2, info: 1 }
  var CSS = [
    '[data-rule-mark="red"]{box-shadow:inset 4px 0 0 var(--danger,#c0392b)}',
    '[data-rule-mark="yellow"]{box-shadow:inset 4px 0 0 var(--warning,#d4a017)}',
    '[data-rule-mark="info"]{box-shadow:inset 4px 0 0 var(--text-dim,#8a8f98)}',
    '#rm-degraded{position:fixed;right:12px;bottom:12px;z-index:1100;padding:4px 10px;border:1px solid var(--border-light,#ddd);border-radius:6px;',
    'background:var(--bg-card,#fff);color:var(--text-dim,#666);font-size:12px}'
  ].join('')

  var cfg = null, timer = null, obs = null, lastKey = '', lastRes = null, lastAt = 0, state = 'idle', busy = false
  var FRESH_MS = 30000                                         // 同一組代號 30 秒內不重抓（Alpine 重畫會洗掉屬性，用快取的結果重新套上即可）

  function token() {
    try { return (JSON.parse(localStorage.getItem('motrix_session') || '{}') || {}).token || '' } catch (e) { return '' }
  }
  function get(url) {
    return fetch(url, { headers: { Authorization: 'Bearer ' + token() } }).then(function (r) {
      return r.json().catch(function () { return null }).then(function (d) { return { ok: r.ok, status: r.status, data: d } })
    })
  }
  function pageCfg() {
    var name = String(location.pathname || '').split('/').pop()
    return PAGES[name] || null
  }
  function setState(s) { state = s; if (document.documentElement) document.documentElement.setAttribute('data-rule-marks-state', s) }

  function items() {
    return Array.prototype.slice.call(document.querySelectorAll(cfg.item))
  }
  function top(marks) {
    var best = null
    ;(marks || []).forEach(function (m) { if (m && RANK[m.level] && (!best || RANK[m.level] > RANK[best.level])) best = m })
    return best
  }
  function clear(el) {
    if (el.hasAttribute('data-rule-mark')) el.removeAttribute('data-rule-mark')
    if (el.hasAttribute('data-rule-title')) { el.removeAttribute('data-rule-title'); el.removeAttribute('title') }
  }
  function apply(res) {
    var marks = (res && res.marks) || {}
    items().forEach(function (el) {
      var m = marks[el.getAttribute(cfg.idAttr)]
      var t = top(m)
      if (!t) return clear(el)
      el.setAttribute('data-rule-mark', t.level)
      el.setAttribute('title', m.map(function (x) { return x.text }).join('、'))
      el.setAttribute('data-rule-title', '1')                 // 只有我們設定過的 title 才會被我們清掉
    })
    var n = document.getElementById('rm-degraded')
    if (res && res.degraded) {
      if (!n) { n = document.createElement('div'); n.id = 'rm-degraded'; document.body.appendChild(n) }
      n.textContent = '部分提醒暫時無法顯示'
    } else if (n) n.remove()
  }

  function sync() {
    if (!cfg || busy) return
    var els = items(), ids = []
    els.forEach(function (el) { var id = el.getAttribute(cfg.idAttr); if (id && ids.indexOf(id) < 0 && ids.length < MAX_IDS) ids.push(id) })
    if (!ids.length) return
    var key = ids.join(',')
    if (key === lastKey && lastRes && Date.now() - lastAt < FRESH_MS) { apply(lastRes); return }
    busy = true
    get('/api/rules/marks?entity=' + encodeURIComponent(cfg.entity) + '&ids=' + encodeURIComponent(key)).then(function (r) {
      busy = false
      if (!r.ok) { if (r.status === 404 || r.status === 401 || r.status === 403) stop(); return }
      lastKey = key; lastRes = r.data; lastAt = Date.now()
      apply(r.data)
      setState('ready')
    }).catch(function () { busy = false })
  }
  function later() { clearTimeout(timer); timer = setTimeout(sync, 250) }

  function stop() {
    if (obs) { obs.disconnect(); obs = null }
    clearTimeout(timer)
    if (cfg) items().forEach(clear)
    var n = document.getElementById('rm-degraded'); if (n) n.remove()
    cfg = null
    setState('off')
  }

  function start() {
    cfg = pageCfg()
    if (!cfg || !token()) return
    // 探測：旗標關（404）、未登入（401）、非最高管理者之外的人仍可用（marks 對所有登入者開放）——只有 404／401 代表『不要做任何事』
    get('/api/rules/marks?entity=' + encodeURIComponent(cfg.entity) + '&ids=').then(function (r) {
      if (!r.ok) return stop()
      if (!document.getElementById('rm-style')) {
        var s = document.createElement('style'); s.id = 'rm-style'; s.textContent = CSS; document.head.appendChild(s)
      }
      setState('ready')
      obs = new MutationObserver(later)
      obs.observe(document.body, { childList: true, subtree: true })       // 只看節點增減；我們只改屬性，不會自己觸發自己
      later()
    }).catch(stop)
  }

  //: 不會自己啟動：由頁面在『已讀到設定 builder_rules.enabled＝1』之後才呼叫 start()（旗標關時這支檔案載入後完全惰性：不送請求、不裝觀察器、不改畫面）。
  window.MotrixRuleMarks = { start: function () { if (!cfg) start() }, refresh: function () { lastKey = ''; lastRes = null; sync() }, stop: stop, _PAGES: PAGES, _apply: apply }
})()
