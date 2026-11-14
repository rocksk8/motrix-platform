/* onepipe.js — 物料流程「一條龍」各批次的開關（群組 onepipe）。
 *
 *   MotrixOnepipe.flags() ⇒ Promise<{ links: boolean, timeline: boolean, entryUnify: boolean, receiveWizard: boolean, shipDeviceWarranty: boolean }>   讀不到一律 false（＝畫面與今天相同）；同一頁只讀一次。
 *
 * 讀的是既有的 GET /api/settings-center/public?groups=onepipe（登入即可）。永不丟例外。
 */
;(function () {
  var cache = null
  function session() { try { return JSON.parse(localStorage.getItem('motrix_session') || '{}') || {} } catch (e) { return {} } }
  function flags() {
    if (cache) return cache
    cache = (async function () {
      var off = { links: false, timeline: false, entryUnify: false, receiveWizard: false, shipDeviceWarranty: false }
      try {
        var token = session().token
        if (!token) return off
        var r = await (window.motrixBootFetch || fetch)('/api/settings-center/public?groups=onepipe', { headers: { Authorization: 'Bearer ' + token } })
        if (!r.ok) return off
        var g = ((await r.json()).groups || {}).onepipe || {}
        return { links: Number(g.links) === 1, timeline: Number(g.timeline) === 1, entryUnify: Number(g.entry_unify) === 1, receiveWizard: Number(g.receive_wizard) === 1, shipDeviceWarranty: Number(g.ship_device_warranty) === 1 }
      } catch (e) { return off }
    })()
    return cache
  }
  // 序號歷史的一行文字（案件頁、庫存頁共用）：異動與狀態用中文，不顯示英文代碼；不認得的代碼原樣顯示（不丟例外）
  var EV = { receive: '入庫', ship: '出貨', revoke_ship: '撤銷出貨', install: '安裝', release: '釋放', 'delete': '刪除', 'void': '作廢', return_to_stock: '退回庫存' }
  var ST = { in_stock: '庫存中', shipped: '已出貨', installed: '已安裝', 'void': '已作廢' }
  function eventLine(e, withActor) {
    e = e || {}
    var st = (e.fromStatus || e.toStatus) ? '（' + (ST[e.fromStatus] || e.fromStatus || '') + ' → ' + (ST[e.toStatus] || e.toStatus || '') + '）' : ''
    return (e.at || '').slice(0, 10) + '　' + (EV[e.event] || e.event || '') + st + (e.quoteNo ? '　' + e.quoteNo : '') + (withActor && e.actor ? '　' + e.actor : '')
  }
  window.MotrixOnepipe = { flags: flags, eventLine: eventLine }
})()
