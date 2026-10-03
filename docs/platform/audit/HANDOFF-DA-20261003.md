# da（獨立稽核與探針線）交接檔 — 第33班A／第34班結案（2026-10-03）
視窗 hichan-da；不寫產品功能；規則：全機同時最多 2 組測試、單檔單程序不用 -n、basetemp 放 %TEMP%、用 D:\MOTRIX-PLATFORM\.venv312、無視窗、探針用完即刪、不碰簽章金鑰。

## 1. 已上線結果
- 第33班A 8ae8b8cc（04:32）：包級 PASS、drill_train33 全綠。第34班 6927e222（15:34）：包級 PASS、drill_train34 全綠（攔下 249d851a 的金額洩漏）。
- 稽核過的片（皆已回作者）：d7 M1／M2a／M2b／M2c／D7 鎖定／maskfix、c7 D12／M1 UI／K-2／refresh／ship-link／mlImport、2e 精算 A1–A5／B1／extras／coverage／ship-case／wire／wire2、a3 31-B S0–S5／cashier-kinds／drill 工具、nowindow。

## 2. 工具（本目錄 da-tools/，亦在 scratchpad）
- `pkgaudit.py`：包完整性唯讀稽核（雜湊／bytes／meta、簽章＋三項反向控制、與前包 diff 對 git diff、禁入掃描＋5物正對照、git archive 逐檔、export_ignore、.build_commit、verify_package、deploy↔G: 逐檔、版號數字＝CHANGELOG）。用法：`--pkg <G:\...\packages\NAME> --commit SHA --prev <前包> --prev-commit SHA --deploy <deploy_packages\時間_SHA>`（deploy 資料夾時間戳與包名不同）。
- `drill33_full.py`：包住 drill_train3x（`--drill-module drill_train34`），每個 record 另存全庫逐列雜湊並印基準→A→重啟→C→E→B 差異；掛鉤要換 `drill_train30._orig_record`。drill 指令與判讀見 drill/train33、drill/train34 的 RUNBOOK；埠 6760／D:\開發測試檔\drill-t29 由稽核線獨占，跑完要手動確認清空。
- `hyg.py`：測試衛生靜態盤點；`admin_scan.py`：admin 直通點掃描（第35班 admin 脫鉤前置）。

## 3. 探針清單與正對照（重用）
- 金額遮蔽：帳號 role=user、modules=[case_manage]、被指派案件（UPDATE quotations SET sales_person_id/assigned_user_ids）→ 打 changes／material-changes／change-proposal／material-coverage／material-orders，斷言回應無 amount／totalPrice／unitPrice 數值；正對照＝249d851a 漏（diff[poSnapshot]／uncoveredLines）、6927e222 為 0。**教訓：遮蔽守門若只測單元或只斷言 403/404 會漏；一定要用「有案件存取、無財務檢視」的帳號做 API 層斷言，且檢查巢狀結構（diff 新舊值、清單內行）。**
- 精算頁金額不變：合成案件（派發各狀態、匯款手續費已付／未付、額外支出各狀態）在舊／新頁各開一次比 summary；legacy 6 案（缺鍵草稿、存 0、缺說明／缺 id 品項、已完結）。
- PO 規則：舊單／規則前草稿／退回送審皆 200、規則後無 PO 400；PO_REQUIRED_FROM＝2026-10-04（使用者裁示維持）。
- M2：突變 7 種（base_version、預檢、出貨下限、below_paid、paid_in_full、套用寫回、version+1）；出貨下限 fails-closed（supply 載入但提供者缺席⇒拒）。
- 遷移 0005／0006：合成表升級兩次、schema 雜湊相同、無暫存表殘留。

## 4. 待辦
- 測試衛生第二版（audit/train33-da-hygiene@4b01cb90 以後；docs/platform/audit/AUDIT-DA-test-hygiene.md＋HYGIENE-D7.md）：需一次單程序 `-m "not e2e" -rsx --durations=30`（約 25–30 分、記憶體吃緊時先問）取得實際 60 skipped／3 xfailed 逐題清單與 e2e 最慢 30 檔；三件小事已轉作者（刪孤兒 _patch_entries、test_bonus_correction:279 `if False`、jv12 改 skip；pypdfium2 列開發需求）。
- 串接點孤兒盤點（bin-1c 交辦，未做）：登記表(47)對程式碼提供(48)，「提供了但靜態掃描找不到取用方」：attachments.catalog、gl.events、uploads.path_access（material.shippable 已由 ship-link 取用）。要查：動態名稱／f-string／registry.providers(變數)／工具腳本；預留 vs 過時孤兒；INTEGRATION-POINTS.md「消費方」欄與程式碼是否一致；並評估新增守門「提供了但無取用方且無『預留』標註」的正反面。
- 第35班 admin 脫鉤獨立盤點：admin_scan.py 掃出 212 處 admin 直通、94 處金流相關；central helpers：helpers/auth.can_see_financial（superadmin/admin/sales 或 financial_view）、financial_mask.money_visible（＋cashier）、各檔 _require_admin、row_access.ADMIN_ROLES、lodging _ADMIN_ROLES；前端 23 檔 `['superadmin','admin'].includes`。稽核重點：F 類全改？M 類誤改？superadmin 仍全通？無模組 admin 看不到金額／做不了出納（含 PDF／信／報表／匯出／API）、遮蔽一致、migration 無資料改動；突變＝F 類改回 admin 直通應有測試變紅。
- 已知開放小項：2e 精算存檔 0 語意（頁面 `||`）已修；c7 M1 UI nit（mlQuote* 殘留）；b2 e2e 不釘端點凍結（單元題涵蓋）。
