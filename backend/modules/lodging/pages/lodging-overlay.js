/* 附近旅宿：地圖覆蓋層（模組 lodging；LODGING-NEARBY.md §3.2、§3.6）。
 *
 * 只經 L1 契約 `window.MotrixMapOverlay`（static/map-overlay.js）碰地圖：register／mount(api)／unmount。
 * 不讀寫地圖頁的內部欄位與地圖物件；畫面只用 textContent／createElement（守門掃描 innerHTML 等寫入點，白名單 0）。
 * 手動開啟：mount 時只讀本機資料狀態；按「查詢」才打 /api/lodging/search（只查本機快照，不對外連線）。
 * 底圖：查詢帶 api.basemap()；回應的 basemap 與頁面不一致 ⇒ 不畫、請重新整理（D 稽核 LG3-S1，同地圖頁 GB-M2）。
 */
(function () {
  'use strict'
  var KEY = 'lodging'
  var RECORDS_PAGE = '/pages/lodging-records.html'
  var st = null

  function token() {
    try { return (JSON.parse(localStorage.getItem('motrix_session') || '{}') || {}).token || '' } catch (_e) { return '' }
  }
  function headers() { return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token() } }

  function node(tag, attrs, text) {
    var e = document.createElement(tag)
    Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]) })
    if (text !== undefined && text !== null) e.textContent = String(text)
    return e
  }
  function money(v) { return v === null || v === undefined ? '—' : Number(v).toLocaleString('zh-TW') }
  function priceText(it) {
    if (it.priceLow === null && it.priceHigh === null) return '官方參考房價：未登記'
    var p = money(it.priceLow) + '～' + money(it.priceHigh) + ' 元'
    if (it.priceSuspect) return '參考房價異常（官方登記值：' + p + '）'
    return '官方參考房價 ' + p + (it.priceRegisteredAt ? '（業者登記於 ' + String(it.priceRegisteredAt).slice(0, 7) + '）' : '')
  }
  function distText(m) { return m === null || m === undefined ? '' : (m >= 1000 ? (m / 1000).toFixed(1) + ' km' : m + ' m') }

  function say(msg, kind) {
    st.msg.textContent = msg || ''
    st.msg.setAttribute('data-kind', kind || '')
  }

  function body() {
    var kinds = []
    if (st.kHotel.checked) kinds.push('hotel')
    if (st.kHome.checked) kinds.push('homestay')
    var b = { radiusM: Number(st.radius.value), kinds: kinds, sort: st.sort.value, basemap: st.api.basemap() }
    if (st.useAddr.checked) {
      b.center = { kind: 'address', address: st.addr.value.trim() }
    } else {
      var c = st.api.center()
      if (!c) return null
      b.center = { kind: 'device', lat: c.lat, lng: c.lng }
    }
    return b
  }

  function loadStatus() {
    return fetch('/api/lodging/status', { headers: headers() })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)) })
      .then(function (d) {
        if (!st) return
        if (!d.count) {
          st.status.textContent = '尚未下載旅宿資料' + (d.canRefresh ? '，請到「附近旅宿紀錄」頁按「更新旅宿資料」' : '，請聯絡最高管理者')
        } else {
          st.status.textContent = '官方資料 ' + d.count + ' 筆，資料日期 ' + String(d.datasetUpdatedAt).slice(0, 10)
            + (d.stale ? '（已超過 ' + d.staleDays + ' 天，可能過舊）' : '')
        }
      })
      .catch(function (e) { if (st) st.status.textContent = '讀取旅宿資料狀態失敗：' + e.message })
  }

  function draw(d) {
    var api = st.api
    api.clear()
    st.handles = {}
    var ctr = d.center
    var radius = d.radiusM
    st.handles.circle = api.addCircle({ lat: ctr.lat, lng: ctr.lng }, radius, { color: 'accent' })
    st.handles.center = api.addMarkers([{ id: 'center', lat: ctr.lat, lng: ctr.lng, title: '查詢中心',
      popup: { title: '查詢中心', lines: [ctr.label || '', ctr.precisionNote || ''].filter(Boolean) } }],
    { icon: 'center', color: 'danger' })
    ;['hotel', 'homestay'].forEach(function (k) {
      var list = d.items.filter(function (it) { return it.kind === k }).map(function (it) {
        var q = it.latestQuote
        var lines = [it.classLabel + (it.licenseNo ? '　' + it.licenseNo : ''), it.address, distText(it.distanceM), priceText(it)]
        if (q) lines.push('最近詢價 ' + q.quotedOn + ' ' + money(q.price) + ' 元／' + q.unitLabel)
        return { id: it.sourceId, lat: it.lat, lng: it.lng, title: it.name, popup: { title: it.name, lines: lines.filter(Boolean) } }
      })
      if (list.length) st.handles[k] = api.addMarkers(list, { icon: k, color: k === 'hotel' ? 'accent' : 'success' })
    })
    api.fitTo(st.handles.circle)
    renderList(d)
  }

  function renderList(d) {
    var ul = st.list
    while (ul.firstChild) ul.removeChild(ul.firstChild)
    d.items.forEach(function (it) {
      var li = node('li', { 'data-lodging-item': it.sourceId })
      var btn = node('button', { type: 'button', class: 'btn btn-ghost btn-sm' }, it.name)
      btn.addEventListener('click', function () { if (st.handles[it.kind]) st.api.focus(st.handles[it.kind], it.sourceId) })
      li.appendChild(btn)
      li.appendChild(node('span', { class: 'mp-ov-dim' }, '　' + it.classLabel + '　' + distText(it.distanceM) + '　' + priceText(it)))
      ul.appendChild(li)
    })
    st.attr.textContent = d.attribution || ''
  }

  function search(save) {
    var b = body()
    if (!b) { say('地圖尚未取得目前位置：請先按「使用我的位置」，或改用輸入地址', 'warn'); return }
    if (!b.kinds.length) { say('請至少勾選旅館或民宿其中一項', 'warn'); return }
    if (b.center.kind === 'address' && !b.center.address) { say('請輸入地址', 'warn'); return }
    say(save ? '儲存中…' : '查詢中…')
    var url = save ? '/api/lodging/records' : '/api/lodging/search'
    if (save) b.note = st.note.value.trim()
    // 儲存前先查一次：確認底圖一致才存（不一致 ⇒ 不畫也不存）
    fetch('/api/lodging/search', { method: 'POST', headers: headers(), body: JSON.stringify(b) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d } }) })
      .then(function (res) {
        if (!st) return null
        if (!res.ok) { say('查詢失敗：' + (res.d.detail || '請稍後再試'), 'err'); return null }
        var d = res.d
        if (d.basemap !== st.api.basemap()) {
          st.api.clear()
          say('地圖底圖設定已變更，請重新整理頁面後再查詢', 'err')
          return null
        }
        if (!d.available) { st.api.clear(); say(d.message, 'warn'); return null }
        draw(d)
        var head = '半徑 ' + (d.radiusM / 1000) + ' km 內 ' + d.count + ' 間'
        if (d.center.precisionNote) head += '；' + d.center.precisionNote
        if (d.stale) head += '；資料已超過 ' + d.staleDays + ' 天'
        say(head)
        if (!save) return null
        return fetch(url, { method: 'POST', headers: headers(), body: JSON.stringify(b) })
          .then(function (r) { return r.json().then(function (x) { return { ok: r.ok, x: x } }) })
          .then(function (res2) {
            if (!st) return
            if (!res2.ok) { say('儲存失敗：' + (res2.x.detail || '請稍後再試'), 'err'); return }
            say(head + '；已存成紀錄 #' + res2.x.id + '（可到「附近旅宿紀錄」頁回查、比較）', 'ok')
          })
      })
      .catch(function () { if (st) say('查詢失敗：連線不到伺服器', 'err') })
  }

  function build(panel) {
    var row1 = node('div', { class: 'mp-ov-row' })
    var gpos = node('label')
    var usePos = node('input', { type: 'radio', name: 'lodging-center', value: 'device', 'data-lodging-center': 'device' })
    usePos.checked = true
    gpos.appendChild(usePos)
    gpos.appendChild(document.createTextNode(' 目前位置　'))
    var gaddr = node('label')
    var useAddr = node('input', { type: 'radio', name: 'lodging-center', value: 'address', 'data-lodging-center': 'address' })
    gaddr.appendChild(useAddr)
    gaddr.appendChild(document.createTextNode(' 地址 '))
    var addr = node('input', { type: 'text', maxlength: '200', placeholder: '輸入地址', 'data-lodging-address': '' })
    addr.addEventListener('focus', function () { useAddr.checked = true })
    row1.appendChild(gpos)
    row1.appendChild(gaddr)
    row1.appendChild(addr)

    var row2 = node('div', { class: 'mp-ov-row' })
    var radius = node('select', { 'data-lodging-radius': '' })
    ;[1000, 3000, 5000, 10000].forEach(function (m) {
      var o = node('option', { value: String(m) }, (m / 1000) + ' km')
      if (m === 3000) o.selected = true
      radius.appendChild(o)
    })
    var kHotel = node('input', { type: 'checkbox', 'data-lodging-kind': 'hotel' })
    kHotel.checked = true
    var kHome = node('input', { type: 'checkbox', 'data-lodging-kind': 'homestay' })
    kHome.checked = true
    var sort = node('select', { 'data-lodging-sort': '' })
    sort.appendChild(node('option', { value: 'distance' }, '依距離'))
    sort.appendChild(node('option', { value: 'price' }, '依參考房價'))
    var go = node('button', { type: 'button', class: 'btn btn-primary btn-sm', 'data-lodging-search': '' }, '查詢')
    go.addEventListener('click', function () { search(false) })
    row2.appendChild(document.createTextNode('半徑 '))
    row2.appendChild(radius)
    var lh = node('label')
    lh.appendChild(kHotel)
    lh.appendChild(document.createTextNode(' 旅館 '))
    var lm = node('label')
    lm.appendChild(kHome)
    lm.appendChild(document.createTextNode(' 民宿 '))
    row2.appendChild(lh)
    row2.appendChild(lm)
    row2.appendChild(sort)
    row2.appendChild(go)

    var row3 = node('div', { class: 'mp-ov-row' })
    var note = node('input', { type: 'text', maxlength: '500', placeholder: '紀錄備註（選填）', 'data-lodging-note': '' })
    var save = node('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'data-lodging-save': '' }, '查詢並存成紀錄')
    save.addEventListener('click', function () { search(true) })
    var link = node('a', { href: RECORDS_PAGE, target: '_blank', rel: 'noopener' }, '附近旅宿紀錄')
    row3.appendChild(note)
    row3.appendChild(save)
    row3.appendChild(link)

    var status = node('div', { class: 'mp-ov-dim', 'data-lodging-status': '' })
    var msg = node('div', { class: 'mp-ov-msg', 'data-lodging-msg': '' })
    var list = node('ul', { class: 'mp-ov-list', 'data-lodging-list': '' })
    var attr = node('div', { class: 'mp-ov-dim', 'data-lodging-attribution': '' })
    var hint = node('div', { class: 'mp-ov-dim' },
      '價格為官方登記參考值（非即時）；距離為直線距離。')
    ;[row1, row2, row3, status, msg, list, hint, attr].forEach(function (e) { panel.appendChild(e) })
    return { usePos: usePos, useAddr: useAddr, addr: addr, radius: radius, kHotel: kHotel, kHome: kHome,
             sort: sort, note: note, status: status, msg: msg, list: list, attr: attr }
  }

  window.MotrixMapOverlay.register(KEY, {
    mount: function (api) {
      var panel = api.panel('附近旅宿')
      st = build(panel)
      st.api = api
      st.handles = {}
      loadStatus()
    },
    unmount: function () { st = null },
  })
})()
