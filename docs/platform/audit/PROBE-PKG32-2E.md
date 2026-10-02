# 第 32 包（745f3c2d）探針報告（2e；2026-10-02）

隔離庫、唯讀、單程序；Playwright 皆預設 headless（conftest `chromium.launch()` 不帶 headless=False），我沒有啟動任何新 console。

## 檔案比對（解包 payload `D:\MOTRIX-PLATFORM\deploy_packages\20261002_185238_745f3c2d` ↔ commit 樹）
- payload 837 檔：807 逐位相同、25 只差換行（CRLF；`.gitattributes`／.bat／.ps1／.vbs／pytest.ini／requirements.txt 等，預期）、**內容差異 1**＝`backend/version_manifest.json`（語意相同：481 筆、順序相同；其中 51 筆舊條目在 payload 多一個 `time` 鍵＝建包時補欄位；另有 BOM）、只在 payload 4 檔＝建包產生（`backend/.build_commit`、`backend/export_ignore.json`、`backend/modules.lock.json`、`deploy_manifest.json`）。
- commit 樹有而 payload 沒有（export_ignore）：backend/tests（687）、各模組 tests／SPEC.md、docs/windows、docs/quick 等；非測試的程式檔沒有缺漏（模組目錄只缺各模組 `SPEC.md`）。
- `.build_commit`＝745f3c2d6b1cf53755c053ad923bdd3546695c33。

## 探針（本分支 `backend/modules/case/tests/test_probe_pkg32_2e.py` 6 題、`backend/modules/subcontract/tests/test_probe_pkg32_dispatch_2e.py` 4 題；全綠）
(1) 材料申請連結：匯入扣量（採購單 2＋未連結已核准 4 ⇒ 已訂 6／剩 4；草稿 3 不佔、連到採購單者不重複）；`po_line_taken`（第二筆送審 400「已對應另一筆」）；存檔時壞連結（草稿採購單、不存在的單號）被擋 `bad_link`；已連採購單不可開匯款申請（409「不能另開匯款申請」）；有付款紀錄的列新增連結 400、既有列原樣存回 200；非財務檢視者看不到金額（purchase-items、material-po-lines、link-status 皆無金額）；他人案件三個端點 404；預設分頁含「尚未送審」由 e2e 驗（`test_e2e_material_link`／`test_e2e_material_unsent` 在本 commit 綠）。
(2) 尚未送審：草稿不進營運報表（權責／現金）、不進總帳 E12、不進簽核佇列、不佔額度、不可開匯款申請（409）；有正對照（同案已核准的一筆看得到）。
(3) 派發：舊單申請完工進佇列且補單號（兩筆同日單號不同、未申請的舊單 doc_code 仍空、退回後重送沿用同號、重複送審 409）；migration 0004 只動 doc_code、冪等、日期取送審日；舊單實質編輯維持舊單並寫 `vendor.dispatch.legacy_edit` 稽核（已核准的實質編輯仍回草稿）；完工審核中取消只關完工段、佇列與紅點清空、其後 approve 409。
(4) 改字：對 payload 掃描——frontend html/js 非註解行 0 筆「叫料」、backend py 字串常值（非 docstring）0 筆。

## 發現
1. **（中）連結失效後付款出口被關**：材料申請連到的採購單作廢後，連結判定回「未連結（stale）」、金額回到材料申請（權責口徑 3000 看得到，正確），但 `material_payment.create` 只看 `poDocCode` 有沒有填，仍回 409「已對應採購單…請走採購單的請款流程」；採購單已作廢也無法走採購單請款 ⇒ 這筆已核准的材料申請既不能匯款、連結欄位又是實質欄位不能改。建議：互斥判定改用 `_link_check` 的**有效**連結（失效連結不擋匯款）。第 33 班強制對應採購單規格（A.5）也要一併處理。
2. （低，探針自己踩到）案件存檔會依 `data_json.dealTag` 重算 `deal_tag`：只改 `deal_tag` 欄位的測試夾具在第一次 PATCH 後被重設，報表類斷言會假綠燈；本檔夾具改設 `dealTag`，並加正對照。
3. （低，觀察）`backend/version_manifest.json` 沒有第 32 班的使用者公告條目（最新仍是 2026-10-02e，第 31 包），也沒有 docs/platform/prod-tasks 的 train32 套用檔；若公告要用 version_manifest 對使用者說明（材料申請改名、尚未送審、派發完工進佇列），需補條目。
