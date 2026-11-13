/* 角色代碼 → 畫面用中文名（2026-11-13，選單去工程師化批 0）。
   畫面上任何地方要顯示「角色」都走這支，不直接印 superadmin／admin 這類內部代碼。
   名稱來源：①系統設定 role_labels（使用者管理 →「角色名稱」，公司自訂；GET /api/settings/role-labels，同一個登入期間只抓一次，存在 sessionStorage）
   ②程式內的預設名稱。認不得的代碼原樣回傳（自訂角色本身已經是中文名稱）。
   ⚠ 已知限制（提案「後續批次」L4）：目前全站仍有數份各自的對照表，之後要收斂成單一來源；第一次載入的頁面可能先顯示預設名稱，下一頁起才套用公司自訂名稱。 */
(function () {
  var NAMES = { superadmin: '最高管理者', admin: '管理員', sales: '業務', engineer: '工程師', finance: '財務', user: '一般使用者', viewer: '檢視者' }
  var KEY = 'motrix_role_labels'
  var custom = {}
  try { custom = JSON.parse(sessionStorage.getItem(KEY) || '{}') || {} } catch (e) { custom = {} }
  function load() {
    try {
      var s = JSON.parse(localStorage.getItem('motrix_session') || 'null')
      if (!s || !s.token || sessionStorage.getItem(KEY)) return
      fetch('/api/settings/role-labels', { headers: { Authorization: 'Bearer ' + s.token } })
        .then(function (r) { return r.ok ? r.json() : null })
        .then(function (d) {
          if (!d || typeof d !== 'object') return
          custom = d
          try { sessionStorage.setItem(KEY, JSON.stringify(d)) } catch (e) { /* 存不了就算了，只是每頁多抓一次 */ }
        })
        .catch(function () { /* 抓不到就用預設名稱 */ })
    } catch (e) { /* 沒有 session：用預設名稱 */ }
  }
  window.MotrixRole = {
    label: function (code) { return (custom && custom[code]) || NAMES[code] || code || '' },
    names: NAMES,
    reload: function () { try { sessionStorage.removeItem(KEY) } catch (e) { } load() }
  }
  load()
})()
