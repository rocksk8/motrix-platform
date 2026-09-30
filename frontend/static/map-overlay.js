/* 地圖覆蓋層（L1；串接點 IP-101 `map.overlay`；docs/platform/LODGING-NEARBY.md §3.6.1，D 稽核 LG-M1／LG2-S1～S3）。
 *
 * 模組的覆蓋層腳本（由 L1 依 module.json `map_overlays` 宣告載入，網址 `/map-overlays/<模組>/<檔名>`）**只准**用這裡的介面：
 *
 *   window.MotrixMapOverlay.register(key, { mount: function (api) {...}, unmount: function () {...} })
 *
 *   api.basemap()                      'google'｜'osm'（這一頁的底圖；查資料時帶給後端，後端只准收窄）
 *   api.center()                       地圖頁目前位置 {lat, lng, source:'device'}；沒有 ⇒ null
 *   api.panel(title)                   L1 給的側邊容器（HTMLElement）；覆蓋層只在裡面畫自己的 UI（用 textContent／createElement）
 *   api.onBasemapReady(cb)             地圖建好後呼叫（已建好 ⇒ 下一個 tick 呼叫）；只對「同一次 mount」呼叫（E3-S3）
 *   （已卸下或被新的一次 mount 取代的 api：addMarkers／addCircle 回 null、不畫）
 *   api.addMarkers(list, style)        ⇒ handle（**不透明字串**）。list：[{id, lat, lng, title, popup:{title, lines:[字串], links:[{label, href}]}}]
 *                                      style：{icon:'hotel'｜'homestay'｜'center', color:語意 token 名（例 'accent'）}
 *                                      大量標點由 L1 群聚（OSM＝markercluster、Google＝@googlemaps/markerclusterer）
 *   api.addCircle(center, radiusM, style) ⇒ handle
 *   api.clear(handle?)                 清掉該 handle；不給 ⇒ 清掉這個覆蓋層畫的全部
 *   api.fitTo(handle)                  視野框住該 handle 的點／圓
 *   api.focus(handle, id)              移到該點並開彈窗
 *   api.onMarkerClick(handle, cb(id))
 *
 * 🔴 地圖物件（Leaflet／Google）永遠只留在這支檔的閉包裡，不交給覆蓋層、也不存在 Alpine 元件上
 *    ⇒ 覆蓋層把 handle 存進自己的 Alpine 狀態再交回，不會變成 Proxy（第十五班 a-gm-raw 那一型，LG2-S1）。
 * 🔴 彈窗由 L1 以結構化欄位自己組 DOM（textContent）；href 只收同源相對路徑或 https:（LG2-S2）。
 * 🔴 覆蓋層不得讀寫 map.html 的內部欄位（_map／_layer／_cluster／_gm*／Alpine 狀態）——守門：tests/test_map_overlay_contract_2026_09_28.py。
 * 條款：Google 底圖時，覆蓋層面板在地圖外（map.html 的 #mp-overlay-panels），不蓋 Google 標誌與資料歸屬（GOOGLE-BASEMAP §3、§7.2 #1）。
 */
(function () {
  'use strict'

  var ICONS = { hotel: 1, homestay: 1, center: 1 }
  var TOKEN_RE = /^[a-z][a-z0-9-]{0,39}$/
  var _impls = {}          // key -> {mount, unmount}
  var _active = {}         // key -> {api, handles}
  var _comp = null         // map.html 的元件（只在這支檔內讀它的 _map／basemap／userPos）
  var _readyCbs = []
  var _seq = 0

  function raw(o) { return (o && window.Alpine && window.Alpine.raw) ? window.Alpine.raw(o) : o }
  function keepRaw(o) { try { o.__v_skip = true } catch (_e) { /* 凍結物件 */ } return o }
  function map() { return _comp ? raw(_comp._map) : null }
  function isGoogle() { return !!(_comp && _comp.basemap === 'google') }
  function tokenColor(name, fallback) {
    var n = TOKEN_RE.test(name || '') ? name : fallback
    var v = (getComputedStyle(document.documentElement).getPropertyValue('--' + n) || '').trim()
    return v || 'gray'
  }

  function safeHref(h) {
    if (typeof h !== 'string') return null
    if (/^\/(?![\/\\])/.test(h)) return h                     // 同源相對路徑（擋 //evil）
    if (/^https:\/\/[^\s]+$/i.test(h)) return h
    return null
  }

  function popupNode(p) {
    var d = document.createElement('div')
    d.className = 'mp-ov-pop'
    if (!p) return d
    if (p.title) {
      var b = document.createElement('strong')
      b.textContent = String(p.title)
      d.appendChild(b)
    }
    ;(Array.isArray(p.lines) ? p.lines : []).forEach(function (line) {
      var l = document.createElement('div')
      l.textContent = String(line)
      d.appendChild(l)
    })
    ;(Array.isArray(p.links) ? p.links : []).forEach(function (lk) {
      var href = safeHref(lk && lk.href)
      if (!href) return
      var a = document.createElement('a')
      a.href = href
      a.textContent = String(lk.label || href)
      a.target = '_blank'
      a.rel = 'noopener noreferrer'
      d.appendChild(a)
    })
    return d
  }

  function pinNode(style) {
    var icon = ICONS[style && style.icon] ? style.icon : 'hotel'
    var s = document.createElement('span')
    s.className = 'mp-ov-pin mp-ov-' + icon
    s.style.background = tokenColor(style && style.color, icon === 'center' ? 'danger' : 'accent')
    return s
  }

  // ── 兩種底圖的實作（只在這裡碰地圖物件） ────────────────────────────────────
  var LEAFLET = {
    markers: function (list, style, onClick) {
      var L = window.L
      var group = L.markerClusterGroup
        ? L.markerClusterGroup({ showCoverageOnHover: false, maxClusterRadius: 40, animate: false })
        : L.layerGroup()
      var byId = {}
      list.forEach(function (p) {
        var m = L.marker([p.lat, p.lng], { title: p.title || '',
          icon: L.divIcon({ className: 'mp-ov-divicon', html: pinNode(style), iconSize: [0, 0], iconAnchor: [0, 0] }) })
        m.bindPopup(function () { return popupNode(p.popup) })
        m.on('click', function () { onClick(p.id) })
        group.addLayer(m)
        byId[p.id] = m
      })
      group.addTo(map())
      return { kind: 'markers', group: group, byId: byId, pts: list.map(function (p) { return [p.lat, p.lng] }) }
    },
    circle: function (c, r, style) {
      var col = tokenColor(style && style.color, 'accent')
      var circ = window.L.circle([c.lat, c.lng], { radius: r, color: col, weight: 1, fillOpacity: 0.05 }).addTo(map())
      return { kind: 'circle', obj: circ }
    },
    remove: function (h) {
      var m = map()
      if (!m) return
      if (h.kind === 'markers') m.removeLayer(h.group)
      else m.removeLayer(h.obj)
    },
    fit: function (h) {
      var m = map()
      if (!m) return
      if (h.kind === 'circle') { m.fitBounds(h.obj.getBounds(), { padding: [20, 20] }); return }
      if (!h.pts.length) return
      m.fitBounds(window.L.latLngBounds(h.pts), { padding: [30, 30], maxZoom: 16 })
    },
    focus: function (h, id) {
      var mk = h.byId && h.byId[id]
      if (!mk) return
      if (h.group.zoomToShowLayer) h.group.zoomToShowLayer(mk, function () { mk.openPopup() })
      else { map().setView(mk.getLatLng(), 16); mk.openPopup() }
    },
  }

  var GOOGLE = {
    _info: null,
    info: function () {
      if (!this._info) this._info = keepRaw(new window.google.maps.InfoWindow())
      return this._info
    },
    open: function (mk, p) {
      var iw = this.info()
      iw.close()
      iw.setContent(popupNode(p.popup))
      iw.setPosition(mk.position)
      iw.open({ map: map() })
    },
    markers: function (list, style, onClick) {
      var g = window.google.maps
      var self = this
      var byId = {}
      var ms = list.map(function (p) {
        var mk = keepRaw(new g.marker.AdvancedMarkerElement({
          position: { lat: Number(p.lat), lng: Number(p.lng) }, content: pinNode(style), title: p.title || '',
          map: null, gmpClickable: true }))
        mk.addEventListener('gmp-click', function () { self.open(mk, p); onClick(p.id) })
        byId[p.id] = { mk: mk, p: p }
        return mk
      })
      var MC = window.markerClusterer && window.markerClusterer.MarkerClusterer
      var cluster = null
      if (MC) cluster = keepRaw(new MC({ map: map(), markers: ms }))
      else ms.forEach(function (mk) { mk.map = map() })
      return { kind: 'markers', ms: ms, cluster: cluster, byId: byId, pts: list.map(function (p) { return [p.lat, p.lng] }) }
    },
    circle: function (c, r, style) {
      var col = tokenColor(style && style.color, 'accent')
      var circ = keepRaw(new window.google.maps.Circle({ map: map(), center: { lat: c.lat, lng: c.lng }, radius: r,
        strokeColor: col, strokeWeight: 1, fillColor: col, fillOpacity: 0.05, clickable: false }))
      return { kind: 'circle', obj: circ, center: { lat: c.lat, lng: c.lng } }
    },
    remove: function (h) {
      if (h.kind === 'circle') { h.obj.setMap(null); return }
      if (h.cluster) { h.cluster.clearMarkers(); h.cluster.setMap && h.cluster.setMap(null) }
      h.ms.forEach(function (mk) { mk.map = null })
      if (this._info) this._info.close()
    },
    fit: function (h) {
      var m = map()
      if (!m) return
      if (h.kind === 'circle') {
        if (h.obj.getBounds) m.fitBounds(h.obj.getBounds(), 20)
        else { m.setCenter(h.center); m.setZoom(14) }
        return
      }
      if (!h.pts.length) return
      var b = new window.google.maps.LatLngBounds()
      h.pts.forEach(function (x) { b.extend({ lat: x[0], lng: x[1] }) })
      m.fitBounds(b, 30)
    },
    focus: function (h, id) {
      var hit = h.byId && h.byId[id]
      if (!hit) return
      var m = map()
      m.setCenter(hit.mk.position)
      m.setZoom(16)
      this.open(hit.mk, hit.p)
    },
  }

  function impl() { return isGoogle() ? GOOGLE : LEAFLET }

  function makeApi(key) {
    var st = { handles: {}, clicks: {}, panel: null }
    //: 這一次掛上的那一份（D 稽核 E3-S3）：就緒回呼與畫圖都要比對「還是不是同一次 mount」——
    //  地圖載入中快速卸下再掛，舊那次的回呼會拿舊 api 畫進舊 handles ⇒ 之後卸下清不掉。
    var self = {}
    function current() { return _active[key] === self }
    var api = {
      basemap: function () { return isGoogle() ? 'google' : 'osm' },
      center: function () {
        var u = _comp && _comp.userPos
        return u ? { lat: Number(u.lat), lng: Number(u.lon), source: 'device' } : null
      },
      panel: function (title) {
        if (st.panel) return st.panel.body
        var host = document.getElementById('mp-overlay-panels')
        if (!host) throw new Error('地圖頁沒有覆蓋層面板容器')
        var sec = document.createElement('section')
        sec.className = 'panel mp-ov-panel'
        sec.setAttribute('data-map-overlay-panel', key)
        var h = document.createElement('h3')
        h.className = 'mp-ov-title'
        h.textContent = String(title || key)
        var body = document.createElement('div')
        body.className = 'mp-ov-body'
        sec.appendChild(h)
        sec.appendChild(body)
        host.appendChild(sec)
        st.panel = { sec: sec, body: body }
        return body
      },
      onBasemapReady: function (cb) {
        if (map()) setTimeout(function () { if (current()) cb() }, 0)
        else _readyCbs.push(function () { if (current()) cb() })
      },
      addMarkers: function (list, style) {
        if (!current()) return null            // 已卸下（或被新的一次取代）⇒ 不畫，免得留下清不掉的標點
        if (!map()) throw new Error('地圖尚未建立（請在 onBasemapReady 之後畫）')
        var id = key + ':' + (++_seq)
        var clean = (Array.isArray(list) ? list : []).filter(function (p) {
          return p && isFinite(Number(p.lat)) && isFinite(Number(p.lng))
        }).map(function (p) {
          return { id: String(p.id), lat: Number(p.lat), lng: Number(p.lng), title: p.title, popup: p.popup }
        })
        st.handles[id] = impl().markers(clean, style || {}, function (pid) {
          var cb = st.clicks[id]
          if (cb) { try { cb(pid) } catch (e) { console.error('[map-overlay]', key, e) } }
        })
        return id
      },
      addCircle: function (c, radiusM, style) {
        if (!current()) return null
        if (!map()) throw new Error('地圖尚未建立（請在 onBasemapReady 之後畫）')
        var id = key + ':' + (++_seq)
        st.handles[id] = impl().circle({ lat: Number(c.lat), lng: Number(c.lng) }, Number(radiusM), style || {})
        return id
      },
      clear: function (h) {
        Object.keys(st.handles).forEach(function (id) {
          if (h && id !== h) return
          try { impl().remove(st.handles[id]) } catch (e) { console.error('[map-overlay]', key, e) }
          delete st.handles[id]
          delete st.clicks[id]
        })
      },
      fitTo: function (h) { var x = st.handles[h]; if (x) impl().fit(x) },
      focus: function (h, id) { var x = st.handles[h]; if (x) impl().focus(x, String(id)) },
      onMarkerClick: function (h, cb) { if (st.handles[h]) st.clicks[h] = cb },
    }
    self.api = api
    self.st = st
    return self
  }

  function unmountOne(key) {
    var a = _active[key]
    if (!a) return
    delete _active[key]
    try { if (_impls[key] && _impls[key].unmount) _impls[key].unmount() } catch (e) { console.error('[map-overlay]', key, e) }
    a.api.clear()
    if (a.st.panel) a.st.panel.sec.remove()
  }

  window.MotrixMapOverlay = {
    //: 模組腳本呼叫（唯一的註冊入口）
    register: function (key, impl) {
      if (typeof key !== 'string' || !impl || typeof impl.mount !== 'function') {
        console.error('[map-overlay] register 參數不對', key)
        return
      }
      _impls[key] = impl
    },
    isRegistered: function (key) { return !!_impls[key] },
    isActive: function (key) { return !!_active[key] },

    // ── 以下只給 L1 地圖頁（map.html）呼叫 ──
    _attach: function (comp) { _comp = comp },
    _mapReady: function () {
      var cbs = _readyCbs
      _readyCbs = []
      cbs.forEach(function (cb) { try { cb() } catch (e) { console.error('[map-overlay]', e) } })
    },
    _mapClosed: function () {
      Object.keys(_active).forEach(unmountOne)
      if (_comp) _comp.overlayOn = {}          // E3-S3：按鈕不可以還顯示「開著」
    },
    //: 掛上；mount 丟例外 ⇒ 面板說明「載入失敗」，其他覆蓋層與地圖照常。回傳是否成功。
    _mount: function (key, label) {
      if (_active[key] || !_impls[key]) return false
      var made = makeApi(key)
      _active[key] = made
      try {
        _impls[key].mount(made.api)
        return true
      } catch (e) {
        console.error('[map-overlay] mount 失敗', key, e)
        var body = made.api.panel(label || key)
        var msg = document.createElement('div')
        msg.className = 'mp-ov-error'
        msg.setAttribute('data-map-overlay-error', key)
        msg.textContent = (label || key) + '載入失敗'
        body.appendChild(msg)
        return false
      }
    },
    _unmount: function (key) { unmountOne(key) },
  }
})()
