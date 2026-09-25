# MOTRIX-PLATFORM 共用核心規格（草案 v0.1，2026-09-25）

> 基準：`c83dae6e`（V9 原版）。本 repo 是下一代產品；V9 原版只維護。
> 狀態：草案。模組分組待 `DEPENDENCY-MAP.md`（視窗 A）後由使用者裁示。

## 1. 目標與驗收

| 目標 | 驗收標準 |
|---|---|
| 模組可拆 | 移除任一 L2 模組資料夾，伺服器照常啟動、其餘模組測試全綠；只少功能不報錯 |
| 不重複開發 | 認證、DB、簽核、輸出、通知、上傳只存在 L1 一份；L2 之間 `import` 為 0（守門測試） |
| 測試縮小 | 改一個 L2 模組只跑「該模組＋L1 契約」；全量只在打包前（`tools/platform/modtest.py`） |
| 可自訂（第二階段） | 所有模組端點由 L1 端點登錄表對外公開，頁面建構器只透過登錄表綁定 |

## 2. 分層

```
L0 平台   app 啟動、模組載入器、授權、設定、log          platform/
L1 核心   認證權限、DB＋migration、簽核、輸出(PDF/Excel/Email)、  core/
          通知、上傳、稽核紀錄、端點登錄表、連接器匯流排
L2 模組   報價、案件、承攬商…（分組待裁示）                  modules/<key>/
```

相依方向只能往下：L2 → L1 → L0。L2 需要另一個 L2 的能力 ⇒ 下沉到 L1，或走連接器（§5）。

## 3. 模組目錄結構

```
modules/<key>/
  module.json        模組宣告（§4）
  api/               router（只 import core.* 與本模組）
  service/           業務邏輯（純函式優先，可單測）
  migrations/        本模組擁有的表，檔名 NNNN_<desc>.py
  pages/             前端頁面與 JS
  widgets/           第二階段：可放進自訂頁面的元件宣告
  tests/             本模組測試（modtest 以此為邊界）
```

## 4. module.json（模組宣告）

```json
{
  "key": "quotation",
  "name": "報價單",
  "version": "1.0.0",
  "core": ">=1.0,<2.0",
  "permissions": ["quotation", "financial_view"],
  "tables": ["quotations", "quotation_items"],
  "provides": {"endpoints": ["GET /api/quotations", "..."], "events": ["quotation.approved"]},
  "consumes": {"events": ["customer.updated"], "optional": true},
  "pages": [{"path": "quotations.html", "menu": "業務/報價單"}],
  "widgets": []
}
```

- `core` 用範圍宣告，不列舉版本；不相容 ⇒ 模組不載入並在系統頁顯示原因，不猜。
- `tables`：只有擁有者可寫；其他模組讀取必須透過擁有者公開的端點或 L1 查詢介面。
- 權限 key 沿用 `helpers/module_registry.py` 的 `MODULES`（已是唯一來源），授權沿用 `helpers/licensing.py` 的 `modules` 清單。

## 5. 模組間串接（連接器）

兩種形式，都經 L1：

1. **事件**：`core.events.publish("quotation.approved", payload)`；訂閱方不在 ⇒ 事件無人接收，發佈方不受影響。
2. **端點呼叫**：`core.registry.call("customer.get", id=…)`；對方未安裝 ⇒ 回 `ModuleUnavailable`，呼叫方必須處理成「少一個功能」。

每個串接節點登記六件事：形式／語法／回傳／對方不在時／契約版本／守門。登記表：`docs/platform/INTEGRATION-POINTS.md`，由守門測試驗證與程式碼一致。

## 6. 資料庫

- 單一 SQLite（WAL），`core.db` 提供連線與交易。
- migration 改為每模組獨立版本號：表 `schema_versions(module, version)`；模組未安裝 ⇒ 不建表。
- V9 既有 `db.py` 的 v1~v84 歷史凍結為 `core` 的基準 migration（不回溯改寫，凍住的歷史不呼叫活的程式碼）；新 schema 從各模組 migration 開始。
- 跨模組共用資料（客戶、使用者、組織）歸 L1 或單一擁有模組，由盤點結果決定。

## 7. 端點登錄表（第二階段的基礎）

- 載入模組時收集 `provides.endpoints`，對照 FastAPI 實際路由；宣告了卻不存在、存在卻未宣告 ⇒ 啟動記 ERROR、守門測試紅。
- `GET /api/platform/endpoints`：列出已啟用模組的端點、參數與回傳 schema、所需權限 ⇒ 頁面建構器只從這裡挑資料來源。

## 8. 測試分層

| 層 | 位置 | 何時跑 |
|---|---|---|
| L1 契約測試 | `core/tests/` | 改 core 或任何模組時 |
| 模組測試 | `modules/<key>/tests/` | 改該模組時 |
| 邊界守門 | `tests/platform/`（L2 互 import、登錄表一致、串接總表） | 每次 |
| 整合／e2e 全量 | `tests/`（既有） | 打包發行前 |

暫存：basetemp 指到本次專屬資料夾，結束即刪。

## 9. 遷移步驟（每個模組相同）

1. 依 `DEPENDENCY-MAP.md` 定成員與擁有的表
2. 把跨模組相依改成 L1 或連接器（先改、先測，再搬）
3. 搬檔到 `modules/<key>/`，寫 `module.json`
4. 模組測試＋L1 契約全綠；行為不變（既有 API 回應比對）
5. 反向控制：刪掉該模組資料夾，伺服器啟動＋其餘模組測試全綠

## 10. 環境

- 開發 port 預設 **667**（避免與 V9 開發機 666 衝突）
- 開發 DB 為測試資料，不上傳任何正式機
- 資料位置唯一來源 `backend/core/paths.py`（錨點＝安裝根目錄，值＝V9 原位置）；產品碼不可自行用 `__file__` 算資料路徑
- 主庫不存在 ⇒ 拒絕啟動（`core.paths.require_db`，只守預設位置）。全新安裝／新開發目錄：設 **`MOTRIX_CREATE_NEW_DB=1`** 啟動一次，建好後移除（旗標仍在時每次啟動記 WARNING）
- 勞報單存檔目錄設定鍵 `payslip_archive_path`（預設 `backend/export_archive`），與 6 個 `*_pdf_base_path` 同規則

## 使用者裁示（2026-09-25）

| 項目 | 裁示 |
|---|---|
| 模組分組 | 採 `DEPENDENCY-MAP.md` §2 提案，**拿掉 M09 選型知識庫**，其餘 11 個 L2 模組照提案 |
| 選型知識庫 | 直接遺棄：從新版刪除 7 個選型導覽的 router／種子／頁面／權限 key／測試；表只留在凍結的 V9 migration，不刪既有資料 |
| 共用主檔 | 客戶（`customers`）與料號（`parts`）下沉 L1；業務開發 CRM 仍是 M02 |
| 疑似廢棄表 | `projects`／`project_stages`／`project_logs`／4 張 `*_templates` 不帶進新模組，只留在凍結 migration |
| 試拆模組 | M11 標案雷達（M09 已遺棄） |
| 測試選題 | `tables_named` 一律算入（保守）；L2 拆開後再評估縮小 |
| 分組的機器可讀來源 | `docs/platform/modules.json`（唯一來源；守門測試與 modtest 讀它） |
| 正式機既有資料 | **原地讀取**：資料位置不動，所有路徑經 L1 路徑解析層 `core.paths`（錨點＝安裝根目錄，不是呼叫者 `__file__`）；日後逐項可選搬遷，不做升級時一次搬。依據 `DATA-COMPAT.md` §4 |
| 全新安裝建表 | 基準＝V9 migration v1~v116 原封建出全部 V9 表（含未安裝模組、已遺棄選型的空表）；「模組未安裝不建表」只適用 v116 之後各模組自有的新表 |
| V9 維護期 schema | V9 新增的 migration（v117+）必須**同號同內容**追進新版；新版遇到比基準新而不認得的版本 ⇒ 拒絕升級並說明原因（不是 WARNING） |
| 模組版本表 | 名稱 `module_schema_versions`（避免與 V9 的 `schema_version` 只差一個 s） |
| 正式機判定 | 禁止以安裝路徑（`\V9.0\`）判定正式機；改明確旗標（DATA-COMPAT §0-3） |
| 通知信預設 | **預設寄信**；開發機以安裝根目錄 `.no_email_send` 或 `MOTRIX_EMAIL_SEND=off` 擋信（標記永不進部署包） |
| 案件可見範圍 | 全站搜尋、儀表板動態牆**對齊報價列表**（被指派者、cashier 可見）；規則集中於 L1 `helpers/row_access.py`，各模組登錄；未登錄的 kind 一律 fail closed |
| 測試範圍期望 | 改 L2 模組 ⇒ 只跑該模組＋契約；改 L1（main／system／db／共用 helper）⇒ 接近全量是結構性的（寫的是幾乎每支 router 都讀的表），接受全量 |

§6 更正：原文「V9 既有 `db.py` 的 v1~v84」→ 實際基準為 **v116**（`db.py:133`，DATA-COMPAT §3）。
