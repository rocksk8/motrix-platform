# M10 網路規劃（netplan）

網路架構規劃書（WAN／VLAN／IP／設備清單、拓樸圖、Excel 匯入匯出、PDF）與不建立規劃書的快速拓樸圖。

## 端點

- `/api/network-plans`、`/api/network-plans/{id}/…`（`api.py` 的 `router`）
- `/api/network-plans-quick/preview`、`/api/network-plans-quick/pdf`（`api.py`，同一支 router）
- `/api/quotations/{quote_no}/network-plan`：依案件查詢綁定的規劃書

權限 key：`netplan`（檢視）、`netplan_edit`（編輯）；案件管理（`case_manage`）也可讀。

## 資料（依 MODULE-GUIDE §3 分類）

| 名稱 | 類別 | 說明 |
|---|---|---|
| `network_plans` | T1 | 規劃書本體（選填綁定案件 quote_no） |

## 串接點

| 方向 | 串接點 | 說明 |
|---|---|---|
| 取用 | IP-12 `case.access`（M01 提供） | 依案件查詢時的逐案權限（`guard`）；建立時讀案件的客戶／專案名稱（`summary`） |

## 案件模組（M01）不在時

- 規劃書照常建立、編輯、匯出；**不能綁定案件**：建立時帶案件單號 ⇒ 400「案件模組未安裝：規劃書無法綁定案件」。
- `/api/quotations/{quote_no}/network-plan` ⇒ 404「案件模組未安裝：無法依案件查詢網路架構規劃書」。

## 第 46～51 班追加（文件同步 DOCSYNC-T52；細節與版本見 CHANGELOG）

- **逐案權限**（1.0.8～1.0.9，第 49 班可見範圍收緊）：綁定案件的規劃書，讀取（`GET /api/network-plans`、`/{id}`、Excel／PDF 匯出、拓樸預覽、個資告知查詢）與寫入（`PUT /api/network-plans/{id}`、`PATCH …/status`、`POST …/import/excel`、`POST …/privacy-notice/ack`）都套「依案件查詢」同一道逐案權限（IP-12 `case.access.allowed`）：看不到該案的人（不是該案業務／協作者、不是 admin 以上、沒有 case_manage）清單看不到、單筆讀取 404、寫入 404 且資料列不變；擁有者與沒綁案件的獨立規劃書照常。admin／最高管理者視為直通（案件列被刪掉時規劃書不會從 admin 眼前消失）；案件模組不在時，綁案件的規劃書只給 admin 以上。Excel／PDF 匯出與拓樸預覽要規劃書讀取模組（netplan／netplan_edit／case_manage）並套同一道逐案權限（原本只驗登入）。
- `module.json` `provides.routes` 明列 `/api/quotations/{quote_no}/network-plan`（落在案件模組的 `/api/quotations` 前綴底下；`modules.json` M10 同步）。

## 本模組不在時

`/api/network-plans*` 回 404；側欄三個入口隱藏（`module.json` 的 `pages`）。
