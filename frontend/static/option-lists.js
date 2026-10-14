/* option-lists.js — 下拉選單的選項清單（census #4）
 *
 * 清單由管理者在後台發布（kind=option_list）；頁面不另外發請求：sidebar.js 在 /api/platform/menu 回 `optionLists` 時把它放在
 * window.MOTRIX_OPTION_LISTS（只在『自訂選項清單』開啟且該清單已發布時才有），並送出 `motrix-options` 事件。
 * 沒有這個變數（旗標關、或沒發布）⇒ 全部回傳頁面自己的預設（＝今天寫死的清單），畫面逐項相同。
 * 清單項目＝{ value（存進資料的字，不可改）, label（顯示名稱）, disabled（停用：新資料不能選，舊資料照常顯示） }。
 */
;(function () {
  if (window.MotrixOptions) return
  function lists() { return window.MOTRIX_OPTION_LISTS || null }
  function custom(id) { var l = lists(); return !!(l && l[id]) }
  window.MotrixOptions = {
    custom: custom,
    /* 所有項目（含停用）；沒有自訂 ⇒ defaults（[{value,label}]） */
    items: function (id, defaults) { return custom(id) ? lists()[id] : defaults },
    /* 可選的值（未停用，依清單順序）；沒有自訂 ⇒ defaults（[值]） */
    values: function (id, defaults) {
      return custom(id) ? lists()[id].filter(function (x) { return !x.disabled }).map(function (x) { return x.value }) : defaults
    },
    /* 給 <select> 用：未停用的項目；目前這筆資料的值如果不在其中（已停用或舊值）⇒ 也列出來（標註『已停用』），避免編輯時值被洗掉；沒有自訂清單時完全照 defaults，不加任何項目（與今天相同） */
    options: function (id, defaults, current) {
      var arr = (custom(id) ? lists()[id] : defaults).filter(function (x) { return !x.disabled })
      if (custom(id) && current && !arr.some(function (x) { return x.value === current })) {
        var hit = (custom(id) ? lists()[id] : defaults).filter(function (x) { return x.value === current })[0]
        arr = arr.concat([{ value: current, label: (hit ? hit.label : current) + (hit && hit.disabled ? '（已停用）' : '（舊值）') }])
      }
      return arr
    },
    /* 第一個未停用的值（預設單位用）；沒有自訂 ⇒ fallback */
    firstValue: function (id, fallback) {
      if (!custom(id)) return fallback
      var v = lists()[id].filter(function (x) { return !x.disabled })[0]
      return v ? v.value : fallback
    }
  }
})()
