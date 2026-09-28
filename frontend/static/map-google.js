/* 地圖頁的 Google 底圖轉接層（第十五班 ②(b)，使用者裁示：有地圖金鑰 ⇒ Maps JavaScript API）。
 *
 * 用法：map.html 在 `/api/map/config` 回 `{basemap: 'google', browserKey, mapId}` 時載入本檔，
 *       呼叫 `MotrixGoogleMap.install(元件, cfg)`：載入 Maps JavaScript API（marker 函式庫）與群聚外掛，
 *       再把元件的「繪圖方法」換成 Google 版。**畫什麼**（點、據點、彈窗內容、?focus=、視野要框哪些點）
 *       仍由 map.html 決定（`_pinHtml`／`_popupHtml`／`_siteHtml`／`_fitAll` 的框選邏輯），兩種底圖不各寫一份。
 *
 * 條款（docs/platform/GOOGLE-BASEMAP.md）：
 *   - Google 標誌與資料歸屬由 API 自己畫在圖上，我們的元素不可以蓋住它、也不可以換成客戶品牌（ToS §3.2.3(b)、(d)(i)）。
 *   - 同一畫面不載 OSM（ToS §3.2.3(e)「with or near a non-Google Map」）⇒ 本檔不碰 Leaflet。
 *   - 標記用 AdvancedMarkerElement（google.maps.Marker 自 2024-02 deprecated），它需要 Map ID（cfg.mapId）。
 * 載入網址的 key 是「地圖（瀏覽器）金鑰」——伺服器定位那把永不送到前端（後端守門題）。
 */
(function () {
  'use strict'
  var API = 'https://maps.googleapis.com/maps/api/js'
  var CLUSTER_JS = '../static/vendor/markerclusterer-2.6.2/markerclusterer.min.js'
  var _loading = null

  function fail(msg) { var e = new Error(msg); e.motrixMsg = msg; return e }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var js = document.createElement('script')
      js.src = src
      js.async = true
      js.onload = resolve
      js.onerror = reject
      document.head.appendChild(js)
    })
  }

  //: 載入 Maps JavaScript API（只載一次）。金鑰被拒時 Google 呼叫全域 `gm_authFailure`——要說出來。
  function loadMaps(cfg, comp) {
    if (window.google && window.google.maps && window.google.maps.Map) return Promise.resolve()
    if (_loading) return _loading
    window.gm_authFailure = function () {
      comp.loadError = 'Google 地圖金鑰無法使用：請確認「地圖（瀏覽器）金鑰」已啟用 Maps JavaScript API，'
                     + '且 HTTP 參照網址限制包含本系統的網址。'
    }
    _loading = new Promise(function (resolve, reject) {
      window.__motrixGmReady = function () { resolve() }
      var q = '?key=' + encodeURIComponent(cfg.browserKey || '')
            + '&v=weekly&loading=async&libraries=marker&callback=__motrixGmReady'
      loadScript(API + q).catch(function () {
        _loading = null
        reject(fail('Google 地圖載入失敗：無法連線 maps.googleapis.com，或被瀏覽器安全政策阻擋。清單與距離不受影響。'))
      })
    })
    return _loading
  }

  function el(html) {
    // 內容是 map.html 的 `_pinHtml`／`_siteHtml` 產生的——每一段外部文字都已逐段跳脫（MP0）。
    var d = document.createElement('div')
    d.innerHTML = html
    return d.firstElementChild || d
  }

  function pos(lat, lon) { return { lat: Number(lat), lng: Number(lon) } }

  var methods = {
    closeMap: function () {
      this._gmClear()
      this._gmClearUser()
      if (this._gmInfo) { this._gmInfo.close(); this._gmInfo = null }
      this._map = null
      this._cluster = null
      this._focusMarker = null
      this._userLayer = null
      this.mapOpen = false
    },

    _draw: function () {
      if (!(window.google && window.google.maps)) return
      if (this._map) { this._redraw(); return }
      var pts = this.view.points
      var office = this.info && this.info.office
      var centre = office ? pos(office.lat, office.lon)
                          : (pts.length ? pos(pts[0].lat, pts[0].lon) : pos(23.9, 121.0))
      var g = window.google.maps
      this._map = new g.Map(document.getElementById('mp-canvas'), {
        center: centre, zoom: pts.length ? 8 : 7,
        mapId: this._gmCfg.mapId,
        clickableIcons: false, streetViewControl: false, fullscreenControl: false,
      })
      this._gmInfo = new g.InfoWindow()
      this._redraw()
    },

    _gmClear: function () {
      if (this._cluster && this._cluster.clearMarkers) { this._cluster.clearMarkers(); this._cluster.setMap && this._cluster.setMap(null) }
      ;(this._gmMarkers || []).forEach(function (m) { m.map = null })
      this._gmMarkers = []
      this._cluster = null
    },

    _gmMarker: function (lat, lon, html, popupHtml, zIndex, onMap) {
      var g = window.google.maps
      var m = new g.marker.AdvancedMarkerElement({
        position: pos(lat, lon), content: el(html), zIndex: zIndex || null,
        map: onMap ? this._map : null,
      })
      m.__motrixPopup = popupHtml
      var self = this
      m.addListener('click', function () { self._gmOpen(m) })
      this._gmMarkers.push(m)
      return m
    },

    _gmOpen: function (m) {
      if (!this._gmInfo) return
      this._gmInfo.close()
      this._gmInfo.setContent(m.__motrixPopup || '')
      // 位置開（不掛 anchor）：標記在群聚裡時它不在圖上，掛 anchor 會開不出來
      this._gmInfo.setPosition(m.position)
      this._gmInfo.open({ map: this._map })
      this._gmOpened = m
    },

    _redraw: function () {
      if (!this._map) return
      this._gmClear()
      var self = this
      this.locationsOf().forEach(function (loc) {
        self._gmMarker(loc.lat, loc.lon, self._siteHtml(loc), self._sitePopupHtml(loc), 500, true)
      })
      this._markerByKey = {}
      this._markerOf = new WeakMap()
      var data = []
      this.view.points.forEach(function (p) {
        var m = self._gmMarker(p.lat, p.lon, self._pinHtml(p), self._popupHtml(p), null, false)
        var fk = window.MotrixRecordLink ? window.MotrixRecordLink.focusKey(p) : null
        if (fk && !self._markerByKey[fk]) self._markerByKey[fk] = m
        self._markerOf.set(self._raw(p), m)
        data.push(m)
      })
      // `MP2`：資料點群聚；據點與「你」不群聚（參考點）。群聚外掛載不到 ⇒ 直接上圖（顯示輔助不擋畫面）。
      var MC = window.markerClusterer && window.markerClusterer.MarkerClusterer
      if (MC) {
        this._cluster = new MC({ map: this._map, markers: data })
      } else {
        data.forEach(function (m) { m.map = self._map })
      }
      this._drawUser()
      this._fitAll(!!this._focus)
      this._applyFocus()
      if (this._pendingRow) { var r = this._pendingRow; this._pendingRow = null; this._focusPoint(r) }
    },

    _drawUser: function () {
      this._removeUserLayer()
      if (!this._map || !this.userPos) return
      var me = this.userPos
      var g = window.google.maps
      var marker = new g.marker.AdvancedMarkerElement({
        position: pos(me.lat, me.lon), content: el('<span class="mp-me"></span>'), zIndex: 1000, map: this._map,
      })
      marker.__motrixPopup = '目前位置<br>' + this._esc(this.accuracyLabel() || '定位誤差不明')
      var self = this
      marker.addListener('click', function () { self._gmOpen(marker) })
      // 🔴 精度圓的半徑用真的那個數字（公尺）——寫死一個好看的圈比沒有更糟。
      var circle = new g.Circle({
        map: this._map, center: pos(me.lat, me.lon), radius: me.accuracy,
        strokeColor: '#DC2626', strokeWeight: 1, fillColor: '#DC2626', fillOpacity: 0.10, clickable: false,
      })
      this._userLayer = { marker: marker, circle: circle }
    },

    _removeUserLayer: function () { this._gmClearUser() },
    _gmClearUser: function () {
      if (this._userLayer) {
        this._userLayer.marker.map = null
        this._userLayer.circle.setMap(null)
      }
      this._userLayer = null
    },

    // Google 地圖自己跟著容器尺寸（不像 Leaflet 要 invalidateSize）。
    _ensureMapSize: function () {},
    _syncMapSize: function () { return false },
    _watchMapSize: function () {},

    _applyFit: function (box) {
      var g = window.google.maps
      if (box.length > 1) {
        var b = new g.LatLngBounds()
        box.forEach(function (x) { b.extend(pos(x[0], x[1])) })
        var map = this._map
        map.fitBounds(b, 30)
        // maxZoom 15（同 Leaflet 版）：兩個很近的點不要放到街道等級
        g.event.addListenerOnce(map, 'idle', function () { if (map.getZoom() > 15) map.setZoom(15) })
      } else if (box.length === 1) {
        this._map.setCenter(pos(box[0][0], box[0][1]))
        this._map.setZoom(14)
      }
    },

    _showFocus: function () {
      var m = this._focusMarker
      if (!m || !this._map) return
      this._map.setCenter(m.position)
      this._map.setZoom(17)
      this._gmOpen(m)
    },
  }

  window.MotrixGoogleMap = {
    methods: methods,
    //: 把元件換成 Google 版並載入 API。回 Promise（map.html 的 openMap 接著 `_draw()`）。
    install: function (comp, cfg) {
      comp._gmCfg = cfg || {}
      comp._gmMarkers = []
      Object.keys(methods).forEach(function (k) { comp[k] = methods[k] })
      return loadMaps(comp._gmCfg, comp)
        .then(function () { return loadScript(CLUSTER_JS).catch(function () {}) })
    },
  }
})()
