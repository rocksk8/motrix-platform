# 第 32 包完整性稽核（d7；唯讀；2026-10-02）
包：`packages\20261002_185250_745f3c2d_full`（commit 745f3c2d6b1cf53755c053ad923bdd3546695c33；837 檔／35,777,616 bytes）。前一包：`20261002_134219_a5dea50c_full`。
## 結論：PASS（必修 0）
| 項 | 結果 | 證據 |
|---|---|---|
| package.sha256 本身的 SHA256 | 符合 | 3FC8CC99AAB6138309722DE53D5EB9C725B7005C3EC672788DBE64B65214BAAF（與主持回報一致） |
| 檔數／bytes／雜湊 | PASS | payload 837＝package.sha256 837 行＝delivery.files 837；bytes 實際＝delivery.bytes；837 檔 SHA256 重算 0 不符；檔名集合相同；format=1、kind=full、product=full |
| 簽章（Ed25519，簽 delivery.json＋NUL＋package.sha256） | PASS＋反向控制 | 真實簽章驗證 True；改 package.sha256 一位元組→False；改 delivery.json 一位元組→False；改簽章一位元組→False |
| 與 a5dea50c 包 diff | 預期內 | 新增 13、移除 0、變更 65。新增：`case/api/material_links.py`、`js/case-management-mlink.js`、`subcontract/migrations/0004_dispatch_doc_code_backfill.py`、docs 計畫文件與表單設計器預覽截圖 7 張。**每個差異檔都在 git diff a5dea50c..745f3c2d 內**（扣除 5 個建包產生檔）；git diff 的 120 檔中 46 個不在包內，**46 個全在 export_ignore 清單**（皆為測試檔），無遺漏、無多出 |
| 禁入內容掃描 | PASS（含正對照） | 正對照先植入 5 個禁入物（.db、__pycache__、.env、含 `D:\MOTRIX-KEYS` 的文件、私鑰區塊）必須全中且無多餘：PASS。包側命中 5 筆，**全為既有基線**：`D:\MOTRIX-KEYS` 路徑字串出現在 `backend/tools/delivery.py` 與 4 份文件（`COMPANY-SETUP-GATE.md`、`AUDIT-D-E4-company-gate.md`、`AUDIT-D-update-delivery.md`、`HANDOFF-HOST-20261001.md`），皆只是路徑文字，無金鑰內容；與第 31 包同樣 5 筆 |
| export_ignore | PASS | `git archive 745f3c2d`（遵守 export-ignore）833 檔；payload＝這 833 檔＋4 個建包產生檔（`.build_commit`＝745f3c2d…、`export_ignore.json`、`modules.lock.json`、`deploy_manifest.json`）；archive 內每檔雜湊與 payload 相同，**唯一例外 `backend/version_manifest.json`**（見下）；`export_ignore.json` 登記 1279＝`git ls-tree` 減 `git archive` 的 1279（3 筆僅是 git 輸出的非 ASCII 引號差異，已逐一核對相同），清單內無任何檔出現在 payload |
| `version_manifest.json` | 預期內 | 建包時重產（UTF-8 BOM；481 筆＝git 481 筆）；與 git 版本差別只在 51 筆多了 `"time": null`，去掉後集合與順序完全相同；前一包同樣 51 筆 |
| verify_package --expect-db-version 116 | PASS | 對 `deploy_packages\20261002_185238_745f3c2d` 執行：0 項 FAIL；db.py `CURRENT_VERSION=116`＝`len(_MIGRATIONS)`＝116＝最後一筆 `_m116_case_roles_username`；包與工作樹相同；產品 full 13 模組、modules.lock 與包內模組一致；Leaflet 5／5；版本紀錄 481 筆欄位齊全；autostart 開關 2／2 |
## 限制
唯讀，未安裝、未跑測試；簽章公鑰取自 `delivery.DELIVERY_PUBKEY_PEM`（工作樹）；`G:` 上的包與 `deploy_packages` 內的包是兩份（後者供 verify_package），兩者 commit 相同但**未逐檔比對這兩份之間的差異**（G: 那份已與 git archive 逐檔比對）。

---
# 重做（新第 32 包）：`20261002_200829_52033606_full`（commit 52033606580d419ca0705ae067b96bf04068ef30；837 檔／35,778,129 bytes）— PASS（必修 0）
前一包：745f3c2d。package.sha256 SHA256＝73606BD622106215BDFAC14A26323B7241C9EBECDDD6834DEA5CA6244DB2A0C3（與回報相符）。
| 項 | 結果 |
|---|---|
| 檔數／bytes／雜湊 | 837＝837＝delivery.files；bytes 相符；837 檔重算 0 不符 |
| 簽章 | 真實 True；改 sha／meta／簽章各一位元組皆 False（反向控制） |
| 與 745f3c2d 包差異 | 新增 0、移除 0、變更 7＝5 個建包產生檔（`.build_commit`、`export_ignore.json`、`modules.lock.json`、`deploy_manifest.json`，`version_manifest.json` 內容相同）＋**case 的 `CHANGELOG.md`、`material_payment_cashier.py`、`module.json`**；與 `git diff 745f3c2d 52033606`（4 檔：這 3 個＋1 個測試檔，測試檔在 export_ignore）完全吻合，無多無少 |
| 內容 | `git archive 52033606` 833 檔＋4 個產生檔＝payload；逐檔雜湊相同，唯一例外 `version_manifest.json`（建包重產，481 筆＝git 481 筆，去掉 51 筆 `time:null` 後順序與內容相同；與前一包同況） |
| export_ignore | 登記 1279＝`git ls-tree`−`git archive` 的 1279（差 0），commit 欄＝52033606，清單內檔無一出現在 payload；`.build_commit`＝52033606 |
| 禁入掃描 | 正對照 PASS；包側 5 筆＝既有基線（`D:\MOTRIX-KEYS` 路徑字串，同前兩包），無金鑰內容 |
| verify_package --expect-db-version 116 | 0 項 FAIL（對 `deploy_packages\20261002_200815_52033606`） |
修正內容確認：`material_payment_cashier.py` 差異只有一處——把 `"diff"` 那行行尾註解移到行首、還原被註解吞掉的 `"fee"`、`"paidAt"` 兩個鍵。
