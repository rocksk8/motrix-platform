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
