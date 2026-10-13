# BP-1 選單建構器（側欄改名／換群組／整份預覽）— 實作筆記（t59，wip/t59-bp1-menus-r1）

設計出處：`PLATFORM-BUILDER-ARCHITECTURE-T57.md` §2.1 積木 5、§2.6（選單／按鈕的發布前預覽）。**旗標預設關＝今天的側欄與按鈕逐字不變。**

## 做了什麼（最高管理者，旗標開啟後）
- **A 改名**：側欄項目顯示名稱（最長 20 字；`< > & " ' \` \\` 與控制字元一律拒絕，不靠渲染端跳脫）。
- **B 換群組**：側欄項目移到另一個**既有**群組（`move.to = "group:<群組鍵>"`；群組本身固定，D4）；群組內順序／隱藏照舊。
- **C 整份預覽**：`POST /api/platform/menu/preview {user?, ops}`（唯讀、僅最高管理者、旗標關 ⇒ 404、ops 不合法 ⇒ 422）→ `{current, preview, skipped, opsHash, user, role}`；以指定使用者（預設＝自己）的權限先過 `core.menu.build`，所以沒有權限的項目兩份都不會出現。
- UI：`frontend/static/menu-editor.js`（新檔，浮動面板「調整選單」）；`sidebar.js` 只加一個載入鉤（`/api/platform/menu` 回 `builderMenu:true` 才載入——只有開啟＋最高管理者才有這個鍵）。
- 發布走**既有**版面定義（kind=`layout`，key=`module:<模組>`，scope=`company`）：版本／稽核／還原／3e 的快照照舊；排版器存的非側欄操作原樣保留。**沒有新增 kind、沒動 `core/definitions.py`。**

## 旗標
設定群組 `builder_menu`，欄位 `enabled`（int 0/1，預設 0，risk=ops；`helpers/settings_groups.py` 檔尾一個區塊）。關著時：
- 發布驗證（`routers/definitions._validate_layout`）擋 relabel／move.to（訊息 `helpers.menu_builder.OFF_REASON`）；
- 執行期 `/api/platform/menu` 走舊入口 `core.menu.apply_layout`（relabel 略過、move 的 `to` 被忽略）；回應不多任何鍵；
- 預覽端點 404；`menu-editor.js` 不會被載入。已發布的改名／換群組資料保留，關閉後停止套用。

## 遮蔽優先
`apply_layout_ex` 只認得選單上**已存在**的項目（build 已依使用者權限過濾）；對看不到的項目、看不到的目的群組的操作 ⇒ 略過並列在 `skipped`。改名與換群組不碰 href／perm／`denied`。測試：`tests/platform/test_menu_builder_bp1.py`。

## 已知缺口（誠實版）
1. **「發布前一定要先預覽同一份草稿」只在前端（menu-editor.js）強制**；伺服端強制要放在 `core/definitions.py`（3e 的檔），本班不碰。
2. 範圍只有 `company`（公司預設）；角色版面仍用頁面內排版器的 `relabel` 以外操作。執行期解析是角色 ＞ 公司，所以某角色若已有自己的 layout，會蓋過這裡的公司層改名。
3. 無法改名／換群組的項目：L1 項目（`core/menu_l1.json`，沒有側欄點）與自訂模組（資料，不是側欄點）。
4. 預覽不含自訂模組項目（它們不是側欄點）。
5. **新增按鈕（add_action）不在本班**：沒有動作目錄，允許的動作清單是安全決定，需使用者裁示。
6. 多個模組的發布是逐模組進行，中途失敗不會回復已發布的模組（可在版本清單還原）。
7. 沒跑瀏覽器 e2e（機器安靜期）；menu-editor.js 只做過語法檢查＋以 node 假 DOM 驗證 `buildOps` 輸出餵給 `apply_layout_ex` 得到預期順序。

## 生成物（合併時由列車重產）
`l1_interface_snapshot.json`（`--update --pending`，core_version=`next`）、`core/CHANGELOG.md` 的 `(next)` 段、`settings_deploy_baseline.json` 的 `builder_menu`、`docs/platform/modules.json`（3 個新單位）；`route_inventory.json`／write-golden 豁免清單（新路由 `POST /api/platform/menu/preview`）、`dep_graph.json`／`test_map.json`／`UNIT-INDEX.md` 由 46 在合併樹重產。
