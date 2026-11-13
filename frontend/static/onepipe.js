/* onepipe.js — 物料流程「一條龍」各批次的開關（群組 onepipe）。
 *
 *   MotrixOnepipe.flags() ⇒ Promise<{ links: boolean, timeline: boolean, entryUnify: boolean }>   讀不到一律 false（＝畫面與今天相同）；同一頁只讀一次。
 *
 * 讀的是既有的 GET /api/settings-center/public?groups=onepipe（登入即可）。永不丟例外。
 */
;(function () {
  var cache = null
  function session() { try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) { return {} } }
  function flags() {
    if (cache) return cache
    cache = (async function () {
      var off = { links: false, timeline: false, entryUnify: false }
      try {
        var token = session().token
        if (!token) return off
        var r = await fetch('/api/settings-center/public?groups=onepipe', { headers: { Authorization: 'Bearer ' + token } })
        if (!r.ok) return off
        var g = ((await r.json()).groups || {}).onepipe || {}
        return { links: Number(g.links) === 1, timeline: Number(g.timeline) === 1, entryUnify: Number(g.entry_unify) === 1 }
      } catch (e) { return off }
    })()
    return cache
  }
  window.MotrixOnepipe = { flags: flags }
})()
