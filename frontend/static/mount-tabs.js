/* 掛載頁籤共用元件（建構器方案 B；設計 docs/platform/plans/BUILDER-B-DESIGN.md §5.2、§6）。
 *
 * 內建頁面把一塊區域標成掛載點（`data-mount-point="<模組key>.<key>"`），本元件負責：
 *   ① 向 `GET /api/platform/mounts?point=` 取「這位使用者看得到、掛在這個點上」的自訂模組頁籤（頁面不自己 fetch，守門 G-M2）；
 *   ② 頁籤被點到才建立同源 iframe（懶載入）：`custom-records.html?key=<模組>&embed=1`（可再附 `&ctx.<鍵>=<值>`）；
 *   ③ 內頁用 `postMessage({type:'motrix-embed-height', height})` 回報高度——這裡**同時**檢查 `event.origin`（必須同源）與
 *      `event.source`（必須是自己建立的某個 iframe），任一不符就忽略；高度夾在 [MIN_H, MAX_H]；
 *   ④ 失效保護：取頁籤失敗（網路／404／非 JSON）⇒ 不出頁籤、不彈窗、頁面其餘功能照常；iframe 8 秒沒載入 ⇒ 面板改顯示「載入失敗，請從選單開啟」連結。
 * 隱藏頁籤**不是**存取控制：嵌入的自訂模組各端點仍各自驗權限。
 *
 * 用法（頁面 Alpine，與頁面自己的資料並存；巢狀 x-data 可讀取外層的 activeTab／setTab）：
 *   <div x-data="motrixMountTabs('daily_tasks.daily-tasks')" data-mount-point="daily_tasks.daily-tasks" style="display:contents"> … </div>
 *   頁籤按鈕：<template x-for="t in mtTabs" :key="t.key"><button @click="mtSelect(t.key)" :class="{active: mtActive === t.key}" x-text="t.label"></button></template>
 *   面板：    <template x-for="t in mtTabs" :key="t.key"><div x-show="mtActive === t.key"><template x-if="mtOpened[t.key]"> … iframe … </template></div></template>
 */
(function () {
  var LOAD_TIMEOUT_MS = 8000
  var MIN_H = 160
  var MAX_H = 6000

  function token() {
    try { return (JSON.parse(localStorage.getItem('motrix_session') || '{}') || {}).token || '' } catch (e) { return '' }
  }

  function ctxQuery(ctx) {
    var out = ''
    if (ctx && typeof ctx === 'object') {
      Object.keys(ctx).forEach(function (k) {
        if (/^[A-Za-z][A-Za-z0-9_]{0,39}$/.test(k) && ctx[k] !== undefined && ctx[k] !== null && ctx[k] !== '') {
          out += '&ctx.' + encodeURIComponent(k) + '=' + encodeURIComponent(String(ctx[k]))
        }
      })
    }
    return out
  }

  window.motrixMountTabs = function (point, opts) {
    opts = opts || {}
    var state = {
      mtPoint: point,
      mtTabs: [],            // [{key, label, icon, href}]
      mtActive: '',          // 目前選中的自訂模組 key（''＝沒有選中任何掛載頁籤）
      mtOpened: {},          // key → true：已建立 iframe（懶載入）
      mtFailed: {},          // key → true：8 秒沒載入
      mtHeights: {},         // key → px
      _mtLoaded: {},
      mtReady: false,        // 取頁籤的請求結束了（成功或失敗）
      mtError: '',           // 失敗原因（只給除錯／測試看，不彈窗）
      _mtTimers: {},
      _mtOnMessage: null,

      init: function () {
        var self = this
        this._mtOnMessage = function (ev) {
          if (ev.origin !== location.origin) return                       // ① 同源
          var d = ev.data
          if (!d || typeof d !== 'object' || d.type !== 'motrix-embed-height') return
          var frames = (self.$root && self.$root.querySelectorAll) ? self.$root.querySelectorAll('iframe[data-mt-key]') : []
          for (var i = 0; i < frames.length; i++) {
            if (frames[i].contentWindow === ev.source) {                   // ② 來源必須是自己建立的 iframe
              var h = Math.max(MIN_H, Math.min(MAX_H, Math.ceil(Number(d.height) || 0)))
              if (Number(d.height) > 0) self.mtHeights[frames[i].getAttribute('data-mt-key')] = h
              return
            }
          }
        }
        window.addEventListener('message', this._mtOnMessage)
        this.mtLoad()
      },

      destroy: function () {
        if (this._mtOnMessage) window.removeEventListener('message', this._mtOnMessage)
        var t = this._mtTimers
        Object.keys(t).forEach(function (k) { clearTimeout(t[k]) })
      },

      mtLoad: function () {
        var self = this
        return fetch('/api/platform/mounts?point=' + encodeURIComponent(point), { headers: { Authorization: 'Bearer ' + token() } })
          .then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status)
            return r.json()
          })
          .then(function (d) {
            self.mtTabs = Array.isArray(d && d.tabs) ? d.tabs.filter(function (t) { return t && typeof t.key === 'string' && typeof t.href === 'string' }) : []
          })
          .catch(function (e) {
            self.mtTabs = []                                               // 失敗＝不出頁籤，其餘功能照常（設計 §6）
            self.mtError = String(e && e.message || e)
          })
          .then(function () { self.mtReady = true })
      },

      mtTab: function (key) {
        for (var i = 0; i < this.mtTabs.length; i++) if (this.mtTabs[i].key === key) return this.mtTabs[i]
        return null
      },

      // 選中一個掛載頁籤：第一次選才建立 iframe，並開始 8 秒計時
      mtSelect: function (key) {
        var tab = this.mtTab(key)
        if (!tab) return
        this.mtActive = key
        if (!this.mtOpened[key]) {
          this.mtOpened[key] = true
          var self = this
          this._mtTimers[key] = setTimeout(function () { if (!self._mtLoaded[key]) self.mtFailed[key] = true }, LOAD_TIMEOUT_MS)
        }
      },

      mtClear: function () { this.mtActive = '' },

      mtSrc: function (tab) {
        var ctx = typeof opts.getCtx === 'function' ? opts.getCtx() : null
        return tab.href + ctxQuery(ctx)
      },

      mtOnLoad: function (key) {
        this._mtLoaded[key] = true
        this.mtFailed[key] = false
        clearTimeout(this._mtTimers[key])
      },

      mtHeight: function (key) { return (this.mtHeights[key] || 480) + 'px' },

      mtFallbackHref: function (tab) { return tab.href.replace('&embed=1', '') },
    }
    return state
  }
})()
