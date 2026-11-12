/* 角色代碼 → 畫面用中文名（2026-11-13，選單去工程師化批 0）。
   畫面上任何地方要顯示「角色」都走這支，不直接印 superadmin／admin 這類內部代碼。
   公司自訂的角色顯示名稱（使用者管理 → 角色名稱）若存在，由各頁自己覆蓋；這裡只放系統預設名稱。
   認不得的代碼原樣回傳（自訂角色已經是中文名稱）。 */
(function () {
  var NAMES = { superadmin: '最高管理者', admin: '管理員', sales: '業務', engineer: '工程師', finance: '財務', user: '一般使用者', viewer: '檢視者' }
  window.MotrixRole = { label: function (code) { return NAMES[code] || code || '' }, names: NAMES }
})()
