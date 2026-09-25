/* custom-layout.js — 自訂模組的版面（CUSTOMIZATION-SPEC §8.1 ③）：表單分組與列表欄位。
 *
 * 建構器（module-builder.html）與執行頁（custom-records.html）共用同一份規則，
 * 所以「建構器看到的樣子」與「使用者看到的樣子」只有一個來源。
 *
 * 版面存在定義的 `ui` 鍵（引擎不讀它）：
 *   ui.form.groups  = [{title, fields:[欄位 key…]}]   表單的分組與欄位順序
 *   ui.list.columns = ['$recordNo', '$status', 'qty', …] 列表要顯示的欄位與順序（$ 開頭＝系統欄）
 *
 * 📌 P9 共用排版元件之後要從這裡抽出：本檔只有純函式（不碰 DOM、不綁 Alpine），
 *    抽離時搬檔即可，兩個呼叫端不用改寫。
 */
;(function () {
  //: 列表可用的系統欄（值來自單據本身，不是欄位）
  var SYSTEM_COLUMNS = [
    { key: '$recordNo', label: '編號' },
    { key: '$status', label: '狀態' },
    { key: '$createdBy', label: '建立者' },
    { key: '$createdAt', label: '建立時間' },
  ]

  function fieldsOf(def) {
    return (def && Array.isArray(def.fields)) ? def.fields.filter(function (f) { return f && f.key }) : []
  }

  function uiOf(def) {
    var ui = (def && def.ui && typeof def.ui === 'object') ? def.ui : {}
    return ui
  }

  /** 表單分組：[{title, fields:[欄位物件…]}]。沒有分到組的欄位依欄位順序放在最後一組「其他」
   *  （完全沒設分組 ⇒ 一組、沒有標題）。已刪除的欄位 key 自動略過。 */
  function formSections(def) {
    var fields = fieldsOf(def)
    var byKey = {}
    fields.forEach(function (f) { byKey[f.key] = f })
    var groups = ((uiOf(def).form || {}).groups) || []
    var used = {}
    var out = []
    groups.forEach(function (g) {
      var fs = (g.fields || []).filter(function (k) { return byKey[k] && !used[k] }).map(function (k) { used[k] = true; return byKey[k] })
      out.push({ title: g.title || '', fields: fs })
    })
    var rest = fields.filter(function (f) { return !used[f.key] })
    if (rest.length) out.push({ title: out.length ? '其他' : '', fields: rest })
    return out.filter(function (s) { return s.fields.length })
  }

  /** 列表欄：[{key, label, system}]。沒設定 ⇒ 編號、狀態、前三個欄位、建立時間。 */
  function listColumns(def) {
    var fields = fieldsOf(def)
    var labels = {}
    SYSTEM_COLUMNS.forEach(function (c) { labels[c.key] = c.label })
    fields.forEach(function (f) { labels[f.key] = f.label || f.key })
    var cols = ((uiOf(def).list || {}).columns)
    if (!Array.isArray(cols) || !cols.length) {
      cols = ['$recordNo', '$status'].concat(fields.slice(0, 3).map(function (f) { return f.key })).concat(['$createdAt'])
    }
    return cols.filter(function (k) { return labels[k] !== undefined }).map(function (k) {
      return { key: k, label: labels[k], system: k.charAt(0) === '$' }
    })
  }

  /** 列表儲存格的值：系統欄取單據本身，其餘取 data。 */
  function cellValue(rec, key, stateLabels) {
    if (!rec) return ''
    if (key === '$recordNo') return rec.record_no || ''
    if (key === '$status') return (stateLabels && stateLabels[rec.status]) || rec.status || ''
    if (key === '$createdBy') return rec.created_by || ''
    if (key === '$createdAt') return (rec.created_at || '').slice(0, 16).replace('T', ' ')
    var v = (rec.data || {})[key]
    if (v === null || v === undefined) return ''
    if (v === true) return '是'
    if (v === false) return '否'
    return String(v)
  }

  /** 陣列內移動一格（dir＝-1 上移、+1 下移）；超出邊界就不動。回傳新陣列。 */
  function move(arr, index, dir) {
    var a = arr.slice()
    var j = index + dir
    if (index < 0 || index >= a.length || j < 0 || j >= a.length) return a
    var t = a[index]; a[index] = a[j]; a[j] = t
    return a
  }

  window.MotrixCustomLayout = {
    SYSTEM_COLUMNS: SYSTEM_COLUMNS,
    formSections: formSections,
    listColumns: listColumns,
    cellValue: cellValue,
    move: move,
  }
})()
