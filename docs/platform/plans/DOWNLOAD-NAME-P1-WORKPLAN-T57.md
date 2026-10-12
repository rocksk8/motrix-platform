# A7 下載檔名第一期：工作計畫（程式；僅計畫短稿，隨首批 commit 推送）

> 日期：2026-10-13　作者：hichan-98　設計：`DOWNLOAD-FILENAME-CASE-T56.md` r6（`wip/t56-download-filename-r6` 051a2a0b1，0d PASS r4／r5）。
> 基底：`origin/train/m2-int-r9` c87079be2。分支：`wip/t57-download-name-p1-r1`。只跑**單檔目標測試**；不跑整套、不跑 e2e（由整合者閘門）。

## 範圍（第一期）
1. **後端 helper** `backend/helpers/download_name.py`（底層）：`build()`、`content_disposition()`、淨化（非法字元、Cf、保留名稱、NFC、位元組上限、尾點／空白）、RFC 8187 `filename*`、latin-1 安全 ASCII 退路、`user=None` 降級、受保護的設定查詢（取不到 ⇒ 常數預設）、任何例外 ⇒ 今日檔名。
2. **設定群組** `download_name`（`helpers/settings_groups.py`＋`tests/platform/settings_deploy_baseline.json`）：平鋪鍵、白話繁中、影響說明含「影響範圍：…」文字（`impact_scope` 結構化支援是 E-e，尚未存在，故先寫進影響說明）；預設＝使用者決定。
3. **前端** `frontend/static/download.js`（`MotrixDownload.save()` 讀 `Content-Disposition`，`filename*` 優先）；第一期案件頁面改用。
4. **第一期後端端點**：完工單、出貨單、請款單、開票申請、承攬商憑證、費用單據、獎金分配單、勞報單、會計傳票（9 個非報價單端點）＋**報價單 4 個文件端點**（`quotations.py` 5525／5635／5673／5706；與 5e 的 M3 同檔，見下）。
5. **掃描器登記**：`tests/test_company_setup_output_points_2026_09_28.py` (c) 表。
6. **測試**：純函式淨化表、範本／降級、權限（`case_page_readable` 真假、`user=None`、例外）、設定缺席、標頭 latin-1、每端點 `Content-Disposition` 斷言（單檔）、靜態守門。
7. **同一 commit**：CHANGELOG（模組與 `docs/quick/changelog.md`）、`backend/version_manifest.json`、必要的 L1 快照／整合點登錄；`FORM_VERSION` 若動到表單才升。

## 順序（小 commit）
C1 helper＋單元測試 → C2 設定群組＋基準＋守門 → C3 前端 `download.js`＋JS 純函式題 → C4 非報價單端點分批改接（每批附端點測試）→ C5 掃描器登記／快照／整合點／既有測試回歸 → C6 報價單 4 端點（等 5e 的 M3 合併後，或與 5e 約定同一次檔案修改）。

## 底層檔案清單（單一底層列車）
`backend/helpers/download_name.py`（新）、`backend/helpers/settings_groups.py`、`backend/tests/platform/settings_deploy_baseline.json`、`backend/tests/l1_interface_snapshot.json`（若有）、`backend/INTEGRATION-POINTS.md`（若有）、`frontend/static/download.js`（新）、`backend/modules/*/api/*.py` 內被改接的端點。`helpers/**` 為底層 ⇒ 整批走完整凍結樹閘門，與同班其他底層變更共用一次。

## 與他人協調
- **5e（M3）**：`quotations.py` 與 `pdf_gen.py` 熱檔；報價單 4 個文件端點等 M3 合併後接，或約同一次檔案修改。
- **設定群組集中檔**：`settings_groups.py` 會與 `quote_alt`、`completion_note`、`project_margin` 文字衝突；E-a（模組自行登錄）落地前，本群組追加在檔尾，列車順序由 5c 決定。
- 設定群組數量斷言（步驟檔 #19）由整合者同步。

## 風險／UNKNOWN（實作前核對）
叫料單下載端點（#14）、傳票與案件的關聯（#13）、`case_extra_expenses.kind` 種類（#6）——逐一核對，查不到則該端點維持現狀並記錄。

## 實作狀態與刻意保留舊標頭的下載點（0d S4；r1 實作後）

**已改（第一期）**：完工單、出貨單、請款單、開票申請、承攬商傳票、費用單據、獎金分配單、勞報單（含預覽存檔「第 N 次」）、會計傳票——後端 `download_name.build()`；前端 `case-management-dispatch/fin/shipping.js`、`voucher.js`、`payment-request-form.html`、`payslip-form.html`、`payslips.html` 讀伺服器檔名（`MotrixDownload.nameFrom`）。完工單目前只有預覽（無 `a.download`），其匯出走既有流程，不在本期。

**刻意保留舊標頭／舊檔名（非第一期，列清單供第二期逐點勾選）**
- 報價單四個文件端點（`quotations.py` 5525／5635／5673／5706）與前端 `quotation-form.html`（3206／3256／3310）、`case-management-close.js:230`、`case-management-core.js:401`：**等 5e 的 M3 合併後**（熱檔 `quotations.py`／`pdf_gen.py`）。
- 多案件／期間型：案件匯出（`quotations.py:6520`、`case-management-list.js:350`）、傳票匯出 T100（`accounting_export.py`、`cashier.js:897`）、財務報表／營業稅（`ledger_closing.py`、`ledger_tax.py`、`ledger-*.js`）、營運報表與銷項發票清單（`analytics/api/reports.py`、`reports.js`）、出納執行紀錄（`arap/api/cashier.py`、`cashier.js:562`）。
- 無案件或案件不固定：外包名冊（`contractors.py`、`contractors.html`）、住宿紀錄、每日任務歷程、自訂模組紀錄 PDF（`custom_records.py`、`custom-records.html`）、網路規劃表／書與拓樸圖（`netplan/api.py`、`network-plan-form.html`、`topology-quick.html`）、甘特圖（`case-management-exec.js`）、`module-builder-output.js`。
- 附件類（使用者上傳的原檔，名稱＝原檔名）：`routers/uploads.py`、`routers/attachments.py`、`accounting/api/vouchers.py` 附件、`arap/api/cashier.py` 附件、`file-preview.js`、`approval-queue.html`、`payment-request.html` 的檔案下載。
- 其他：`helpers/xlsx_out.py::_pdf_filename`（跟隨來源檔名）、`helpers/email_notify.py` 附件（呼叫端傳入檔名；已只送 `filename*`）、傳票 PDF 帶附件版（`with_attachments`）仍同一端點。
- 未核對 UNKNOWN（維持現狀）：叫料單下載端點、傳票與案件的關聯（目前傳票檔名不含案件）、`case_extra_expenses.kind` 種類。

## 環境與合併備註（0d S5／S6）
- **Node.js 相依**：`tests/test_download_js_2026_10_13.py` 的兩題用 `node` 跑 `static/download.js`；沒有 node 的機器會略過（⚠️ skip 不是驗過）。整合者的閘門機器有 node（`tests/test_cascade_self_tiers_records_signer_2026_09_25.py` 同一假設）。
- **底層列車（完整車道）**：`helpers/download_name.py`、`helpers/case_access.py`、`helpers/settings_groups.py`、`tests/platform/settings_deploy_baseline.json`、`core/CHANGELOG.md`（`(next:minor)` 佔位）、`tests/platform/l1_interface_snapshot.json`（`core_version: next`）、`docs/platform/modules.json`（`helper:download_name`、`js:static/download.js`）、`dep_graph.json`／`UNIT-INDEX.md`／`test_map.json`（重產）。版號與 `version_manifest.json` 的 `"version": "next"` 由列車 `train_number.py` 取號。
- **合併順序**：`settings_groups.py` 與基準 JSON 與 `quote_alt`／`completion_note`／`project_margin` 群組文字衝突（尾端追加）；基準 JSON 以文字插入（`download_name` 插在 `retention` 之前），整合者依列車順序重排；**先 `git add` 新測試檔**（`test_download_name_*`、`test_download_js_*`）再重產 `test_map`；產生檔（`dep_graph`、`UNIT-INDEX`、`test_map`、`l1_interface_snapshot`）由整合者在合併後重產，不手解衝突。
- 掃描器：`test_company_setup_output_points_2026_09_28.py` 的 `OUTPUT_PAT` 加入 `download_name.build`／`_dl_name(`，`NO_COMPANY_DATA` 登記 `download_name.build`、`download_name.headers`、`payslips._dl_name`（只組檔名，不產生內容）。

## 決定（1c，10-13）：報價單四個文件端點不在本列車
`quotations.py` 的 5525／5635／5673／5706 四個文件端點與其前端（`quotation-form.html`、`case-management-close.js`、`case-management-core.js`）**等 5e 的 M3 T9（sign／unsign，同檔大改）合併後**，以後續 commit 併入；本列車（`wip/t57-download-name-p1-r1`）不含它們，避免同檔衝突。M3 的分支是 `origin/wip/t57-m3-t1-r2`（頭在移動）。
