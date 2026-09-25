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
| 取用 | IP-11 `case.access`（M01 提供） | 依案件查詢時的逐案權限（`guard`）；建立時讀案件的客戶／專案名稱（`summary`） |

## 案件模組（M01）不在時

- 規劃書照常建立、編輯、匯出；**不能綁定案件**：建立時帶案件單號 ⇒ 400「案件模組未安裝：規劃書無法綁定案件」。
- `/api/quotations/{quote_no}/network-plan` ⇒ 404「案件模組未安裝：無法依案件查詢網路架構規劃書」。

## 本模組不在時

`/api/network-plans*` 回 404；側欄三個入口隱藏（`module.json` 的 `pages`）。
