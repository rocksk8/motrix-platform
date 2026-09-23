# 待辦移交清單（2026-09-23 晚，hichan-0a 彙整）

> 用途：把「原本待完成的事項」交給另一個視窗接手；本視窗改做平台化盤點。
> 量測時 HEAD＝`6e09acc`。**正式機＝`c5b1e84`（2026-09-22 18:56:07 套用，使用者確認）**；09-23 的 654 個 commit 皆未上正式機，當日沒有建過包。每一項的權威細節在「來源」欄那份檔，**以那份為準**，本檔只做索引與分派。
> 協定照 `MULTIWIN-PROTOCOL.md`：§3 檔案歸屬、§6b 停手回報、§5u `git -C <絕對路徑>`。

---

## 甲、視窗可以直接接手（不需要使用者裁示）

| # | 事項 | 現況（量的） | 來源 | 歸屬 |
|---|---|---|---|---|
| T1 | **建包被規格覆蓋率守門擋下 ⇒ 升級檔沒有匯出** | 守門列 31 個編號：丁 9（撞名，登記 `AMBIGUOUS_ACK`）／丙 9（題名不帶編號，**要逐支打開驗**）／乙 5（真欠帳，**不可登記掉，要補題**）／甲 8（沒做） | `docs/windows/GATE-BLOCK-2026-09-23.md` | 登記與補題＝C；甲類要不要做＝A |
| T2 | T1 解除後重跑 `build_deploy_package.ps1`，**只到匯出升級檔為止，不部署** | 最後一次成功建包之後又有大量 commit | `HANDOVER-2026-09-23.md` §0 ① | A 派、D 量 |
| T3 | `test_navigation_destination_2026_09_23.py` 4 支紅（EM10） | HEAD 上就紅（基準見 `TEST-BASELINE-2026-09-23.md:66`）；母體 144 vs 規格 46 的洞還沒驗 | `STATE.md` 搜 `EM10`、`SPEC-EM10` | 實作＝B；驗母體＝C |
| T4 | `test_homoglyphs_in_docs` 紅：`docs/windows/KNOWN-GAPS.md:173`、`:176` 有一個簡體字（U+5265）應改為繁體「剝」（U+525D） | 2 處，HEAD 上就紅 | 測試輸出 | A（文件） |
| T5 | **變更摘要斷檔**：`docs/quick/changelog.md` 最新一則是 09-16，而 09-17 起有 1,319 個 commit | `git log --since=2026-09-17 --oneline \| wc -l` | QUICK 維護規則 | A（changelog） |
| ~~T5 原文~~ | ~~`version_manifest.json` 最新一筆是 09-14；… 沒進任何一份~~ ⇒ **更正（同日）：錯**。manifest 是新→舊排列，我讀的是檔尾（最舊）。實測第一筆 `2026-09-23e`、376 筆 ⇒ manifest **沒有斷檔**，只有 changelog 斷 | `json.load` 後印 `e[0]` 與 `max()` | — | manifest 那半刪除 |
| T6 | `HANDOVER-2026-09-23.md` 標著「編寫中」，有「待補」節 | 第 8 行 | 該檔 | A |
| T7 | `NEXT-SESSION.md` 停在 2026-09-12（寫的是 v76→v77 部署），**已過期但檔頭寫著「開工第一份要讀」** | 第 1 行 | 該檔 | A：改寫或標註過期並指向 HANDOVER |
| T8 | `MOTRIX-ERP-QUICK.md` 檔頭「文件版本 2026-09-16」過期 | 第 4 行 | — | A，併 T5 一起做 |
| T10 | **登入頁版本號錯**：`GET /api/system/version`（`backend/routers/auth.py:288-308`）取 `entries[0]` 當「最新」，而 `version_manifest.json` **沒有排序保證** ⇒ 正式機 `c5b1e84` 回 `2026-09-22c`，同檔實際最新是 `2026-09-22g`（第 46 行）。HEAD 第一筆剛好是最大值 `2026-09-23e`＝**碰巧對**，下一次插入順序不同就會再錯 | `curl https://172.16.10.177:666/api/system/version` ⇒ `2026-09-22c`；`git show c5b1e84:backend/version_manifest.json` 第 4 行 22c、第 46 行 22g；HEAD `sorted desc? False` | 使用者確認正式機＝`c5b1e84`（09-22 18:56:07） | 修＝B（取 `max(version)` 或讀取時排序，不要依賴檔案順序）；題＝C，**用一份刻意亂序的 manifest** 當輸入 |
| T9 | 🔴 **產品缺陷**：`POST /api/contractor-dispatches/{did}/import-to-quote`（`backend/routers/vendor_contractors.py:768`）①`:837` 呼叫 `save_quotation_json()` 後**沒有 `conn.commit()`** 就 `conn.close()` ⇒ UPDATE 被回滾、端點回成功而**資料庫沒寫入**；②同一行第 4 個位置參數傳 `user["username"]`，而簽名第 4 個是 `status`（`helpers/quotations.py:427-433`）⇒ **只修①會讓報價單狀態變成使用者名稱** | `get_db()` 是預設 isolation 的 `sqlite3.connect`（`db.py:163-176`）；與 `routers/material_orders.py:66-70` 09-10 修過的①②**同一型** | 2026-09-23 平台化盤點時撿到（後端 Explore agent），本視窗已讀原始碼確認 | 修＝B（①②**必須一起修**）；回歸題＝C，觀測點打在資料庫的 `data_json.items` 與 `status` 欄，先證明它會紅 |

建議順序：**T9（實際缺陷）→ T4 → T1 → T2**（T4 一分鐘，且讓全套測試少一支已知紅燈；T2 依賴 T1）；T5～T8 可以跟 T1 並行。

## 🟢 派工（2026-09-23 使用者：「派吧，至少要安全上正式機」）→ 執行者 hichan-61

**目標＝產出一個可以安全套用到正式機的升級檔。部署是使用者自己的動作，本派工不含部署、不碰正式機。**

| 步 | 內容 | 驗收（全部要附輸出，不寫結論） |
|---|---|---|
| 1 | **T9**：先寫回歸題，在未修的碼上證明它紅，再修 ①commit ②status 參數 | 題在修前紅、修後綠（兩段輸出都貼）；觀測點＝資料庫的 `data_json.items` 與 `status` 欄 |
| 2 | **T1**：依 `GATE-BLOCK-2026-09-23.md` 處理覆蓋率守門。丁類登記 `AMBIGUOUS_ACK`；丙類**逐支打開**確認後登記；乙類**補題，不可登記掉**；甲類列出來回報，不自己決定做不做 | `test_spec_coverage_2026_09_21.py` 全綠；回報每一類實際處理了哪幾個編號 |
| 3 | **T2**：跑 `build_deploy_package.ps1` 到匯出為止 | 建包全部關卡通過；**打開產出的包**：`docs/windows/`、`backend/tests/`、`MOTRIX-ERP-QUICK.md`、`docs/quick/` 皆 0 筆，`backend/main.py` 1 筆（對照組）；紅燈數不高於 `TEST-BASELINE-2026-09-23.md` 的基準，逐支列出 |

界線：
- 不部署、不連正式機、不刪舊的兩個包（`deploy_packages/20260922_*`，含內部文件，**不可使用**）。
- 甲類要不要做、任何需要放寬守門的地方 ⇒ 停下來回報，不自行裁。
- 建包期間是凍結期：開跑前 `git status --porcelain` 完整輸出、跑完再一次（協定 §6b）。
- T10（版本號）不在本派工必要範圍；1～3 完成後有餘力再做，做的話同樣先證明題會紅。

## 🟢 路線裁示（2026-09-24 使用者，表單作答）

- **先甲、再做乙**。甲＝以正式機 `c5b1e84` 為底的修補包（T9＋出貨排除清單），由 hichan-0a 在 worktree `hotfix/2026-09-24-t9` 建包；乙＝整個 HEAD 上線，由 hichan-61 清紅燈。
- 甲建包時「版本紀錄反方向檢查」擋下 4 筆（`2026-09-23a`～`d`，皆在 master 清單內）⇒ 使用者裁：**worktree 內的資料庫副本刪掉這 4 筆後建包**；真正的開發機資料庫與檢查本身不動。
- 乙的「功能沒做」紅題：

| 項目 | 裁示 |
|---|---|
| 整體 | **全部做完**（不以 xfail 放行），唯一例外見 WD1 |
| BN4 改名（62 處） | **現在做完**；白名單逐檔改，驗收＝該改的 0、不該改的沒動 |
| BN3 手動人員來源、BN17 TRIGGER | **這輪做完**；BN17 動 `db.py` 要先宣告 |
| WD1／GW1／GW2（`wording.py`） | **唯一例外：`xfail(strict=True)`，併入平台化「內容層」設計**，註明規格編號 |
| 覆蓋率守門甲類（約 15 個） | 依「全部做完」；先逐項列出工作量回報，太大的再回來問 |
| L 級（EM2／EM7／EM13／JV22） | **2026-09-24 表單原文：「JV22 做，其餘下一輪」** ⇒ JV22 本輪做完（含 TRIGGER、send_back 寫 edit_log、GET edit-log、前端區塊）；EM2／EM7／EM13 移 NEXT（規格與題一起移） |
| M 級（BN12／EM1／PX1） | 不屬「太大」，依「全部做完」本輪做 |
| JV6 | 依 `e8108b7` 使用者原話（09-23 20:35）移 NEXT |

## ✅ 甲 修補包產出（2026-09-24 00:25，hichan-0a）

```
路徑    deploy_packages\20260924_002556_ab0d5de   209 檔／33MB
樹雜湊  5763da77f9e55f5b49b19d87867440f1df8c23120dd58870caf185fb679f6ba5（find|sort|sha256sum 再 sha256）
分支    hotfix/2026-09-24-t9 = c5b1e84 + 4d3872a(T9) + dfccb9b(.gitattributes) + ab0d5de(manifest 2026-09-24a)
測試    非 e2e 1821 passed / 53 skipped / 0 failed
        e2e 52 passed / 1 failed：test_admin_without_module_loses_both_item_and_group_name
            ⇒ 09-22 以 c5b1e84 建包時同一支就紅（STATE.md:16205），非本次修補引入
驗包    docs/windows、docs/quick、backend/tests、QUICK/PROTOCOL/CHANGELOG 皆 0；backend/main.py 1（對照）
        與 20260922_184908_c5b1e84 逐檔比對：內容不同的只有 .gitattributes、vendor_contractors.py、
        version_manifest.json、deploy_manifest.json；新增 0 檔；少掉的＝內部文件＋14 支開發工具
        apply_update.ps1 Step 3「只加不刪，絕不 /MIR」⇒ 正式機上既有的開發工具不會被刪
直譯器  hermes-agent venv 3.11.15（建包腳本自選）
```
- 版本反方向檢查依使用者裁示，用 worktree 內資料庫副本刪 4 筆（23a～d）後通過。
- **部署是使用者的動作**：`apply_update.ps1 -PackagePath <複製過去的路徑>`。
- 舊的兩個包（`20260922_*`）含內部文件，仍**不可使用**。

## 🔴 T11 正式機每日備份自 09-22 起每天必定不合格（2026-09-24，使用者裁：出第二個修補包）

**成因（已重現）**：BK10 身分對照 `snapshot_content_ok()` 以 `快照筆數 < 彙總筆數 ⇒ 不合格`（`archive.py` @c5b1e84 `snapshot_content_ok`）。
而 `_snapshot_sqlite()` 拍完快照後**立刻寫一筆 `backup.sqlite_snapshot` 稽核**，之後 `_daily_backup()` 才匯出 JSON
⇒ 彙總的「稽核紀錄」永遠 ≥ 快照＋1 ⇒ **每天必定判不合格、不寫 `.done`**。同日重跑時沿用本機已存在的快照 ⇒ 差距只會變大。

```
雲端副本重現（c5b1e84 的判準）：
09-22 快照 audit 2998 ／彙總 2999  FAIL      （22:56 重跑那一輪，BK10 已上線）
09-23 快照 3027 ／彙總 3086；報價單 35／36  FAIL
09-24 快照 3088 ／彙總 3091  FAIL；多出的 3 筆 = 3089 backup.sqlite_snapshot、3090 backup.daily_snapshot_mismatch、3091 backup.alert（全是備份自己寫的）
```
因果時序：BK10 部署 09-22 18:56 ＜ 第一次失敗 09-22 22:56。
實際風險：09-23／09-24 的 JSON 與 `.db` **都在雲端**，只是沒有 `.done`；手動跑 `backup_job.py` 會撞同一關，無效。

**派工 → hichan-61（暫停乙）**，在 `hotfix/2026-09-24-t9` 上修，同一修正 cherry-pick 進 master：
| 驗收 | 內容 |
|---|---|
| ① 先紅 | 題：正常快照＋快照之後再寫入稽核／新報價 ⇒ 在**現行碼上紅**（貼輸出） |
| ② 保護不退 | 題：空庫／他庫快照（08-30 型：表都在、資料沒有）⇒ **仍判不合格**；並突變拿掉新判準證明它會紅 |
| ③ 同日重跑 | 第二輪沿用早上的快照 ⇒ 不因中間的寫入被判不合格 |
| ④ 觀測點 | 雲端（測試裡的替身）`每日備份/<日>/.done` 真的被寫出來，不是只看函式回傳 |
| ⑤ 版本紀錄 | 取 master 上下一個未用的 `2026-09-24x`，**兩邊逐字相同** |
- 修補分支在 hichan-0a 的 worktree（scratchpad `wt_hotfix`）；交給 hichan-61 期間我不動它。完成後由 hichan-0a 建包驗包。
- 界線：只改判準，不改匯出順序以外的備份流程；不動正式機；不刪雲端任何檔。

## ✅ T11 第二修補包產出（2026-09-24 01:28，hichan-0a）

```
路徑    deploy_packages\20260924_012847_d1acd33   209 檔
樹雜湊  3ddc405ef75c51579e4b8fc642109335e3fed39d5132ce5e6583f196044af25d
分支    hotfix/2026-09-24-t9 = 第一修補包 ab0d5de + 51ca45a(T11 判準) + d1acd33(題改名去掉 T11)
測試    非 e2e 1825 passed / 0 failed；e2e 52 passed / 1 failed（同第一包，09-22 起就紅）
驗包    內部文件 0；與 20260924_002556_ab0d5de 比：新增 0、刪除 0、內容變動＝archive.py、version_manifest.json、deploy_manifest.json
版本    /api/system/version 仍回 2026-09-24a（說明併入既有 21a，VR3）⇒ 部署後以 deployed-version 的 commit d1acd33 驗證
```
- 第一次建包被覆蓋率守門擋：題名 `test_t11_*` 把工作編號當成規格編號 ⇒ 改名（hotfix `d1acd33`、master `1c3e9bd`）。

## ✅ 乙 產出（2026-09-24 02:19，hichan-0a）—— 使用者裁「現在這包先上」

```
路徑    deploy_packages\20260924_021932_5f04d04   231 檔
樹雜湊  1cc11bccbd03880767f9519a30d1b954d16993f0ee03afccd540eb2d1ef035bf
基底    master 5f04d04（detached worktree 建包 ⇒ deploy_manifest 的 branch 顯示 "HEAD"，commit 正確）
測試    非 e2e 2571 passed / 53 skipped / 3 xfailed(WD1) / 0 failed；e2e 79 passed / 0 failed
驗包    docs/windows、docs/quick、docs/reference、backend/tests、QUICK、PROTOCOL、平台化盤點、ASK-ACCOUNTANT 皆 0；main.py／apply_update 在
DB      v91（正式機 c5b1e84 系）→ v109；T9 與 T11 修正皆在包內
```

### 🔴 套用失敗 → 重建（2026-09-24 02:44）
- 使用者在正式機套用 `20260924_021932_5f04d04`：`status=migration_dryrun_failed`，正式庫未觸碰。
- 成因：乾跑其實成功（輸出有 `DRYRUN_OK`），但 m103 的 `logger.warning` 走 stderr，被 PS 5.1 包成 NativeCommandError ⇒ `$dryRunOutput` 成為 2 元素陣列；`apply_update.ps1` 以 `$dryRunOutput -notmatch "DRYRUN_OK"` 判斷，對陣列回傳「不符合的元素」＝非空＝真 ⇒ 誤判。db 備份的 `BACKUP_OK` 判斷同形。
- 修正 `46dc6ae`（hichan-61，PS 5.1 真跑 a/b/c 三情境）；重建 ⇒ **`deploy_packages\20260924_024414_46dc6ae`**（231 檔，樹雜湊 `9063f7b3…c0ea`；非 e2e 2571／e2e 79 全過；與上一包差異只有 `apply_update.ps1`、`.build_commit`、`deploy_manifest.json`）。
- ⚠️ 正式機 V9.0 上的 `apply_update.ps1` 仍是舊版 ⇒ **這一次必須執行包內那支**（`$ProdRoot` 寫死 V9.0，從包內執行一樣作用於正式機）。
- `20260924_021932_5f04d04` 作廢。

### ✅ 乙 已上正式機（2026-09-24 02:46:15，使用者部署並確認「功能也有」）
```
deployed-version  46dc6ae（branch 欄顯示 HEAD＝detached 建包，內容即 master 46dc6ae）
/api/system/version  2026-09-24c
每日備份 09-24 .done  01:32（第二修補包後恢復）
```
- 待使用者決定是否刪除：`deploy_packages\20260922_184908_c5b1e84`、`20260922_200604_7bc1fb8`（含內部文件）、`20260924_021932_5f04d04`（作廢）。
- 下一輪：T12（更新紀錄頁）、T10（版本端點取 entries[0]）、EM2／EM7／EM13、WD1（併入平台化）、KNOWN-GAPS ③（admin 產不出分潤單無說明）、平台化 §0 三件重裁。

### 🟠 T12（下一輪）：PK1 精簡 manifest 造成「系統更新紀錄」頁安靜降級
- `build_deploy_package.ps1` Step 5.6（`2f1e4a3`）把 `version_manifest.json` 精簡成單筆 `{version,date}`。
- PK1 規格（`SCOPE.md:1091`）只查了 `GET /api/system/version` 這個讀者；**漏了 `helpers/startup.py:_sync_module_versions()`**——它開機時把 manifest 寫進 `module_versions`，給 `module-versions.html` 顯示。無 `module` 的條目被 `:487` 略過 ⇒ 正式機收不到任何新說明，**不報錯**。
- 可回復：日後帶完整 manifest 的包一上，`INSERT OR IGNORE` 會把缺的全部補進去。
- 修法方向：精簡時保留使用者可見欄位（`module/version/date/time/content`），說明文字本來就是寫給使用者的；並在 `verify_package` 加一條「manifest 每筆都有 `module`」。
- 使用者 2026-09-24 表單原文：「現在這包先上」。

## 乙、要使用者裁示（視窗不可代裁，只能整理選項）

| 事項 | 數量 | 來源 |
|---|---|---|
| 出貨阻擋 IA1／IA2／WL7／JV27 | 4 | `HANDOVER-2026-09-23.md` §0b |
| 待裁示（每條已附預設決定，只回不同意的） | 18 | `PENDING-RULINGS.md` |
| 只有使用者在正式機上查得到的 | 11（共 21 條） | `KNOWN-GAPS.md` |

> `HANDOVER` §0a（出貨包含內部文件）：`.gitattributes` 的 `**` 寫法已生效——
> 2026-09-23 `git check-attr export-ignore` 對 `docs/windows/STATE.md`、`backend/tests/conftest.py`、`docs/quick/changelog.md` 皆回 `set`；
> `git archive ced0ae8` 實測包內 `docs/quick`＋`MOTRIX-ERP-QUICK.md` 0 筆（對照組 `backend/main.py` 1 筆）。
> **仍待**：打開真正由 `build_deploy_package.ps1` 產出的包驗 `STATE.md` 不在（隨 T2 一起做）。

## 丙、我沒查什麼

- 丙類 9 個、甲類 8 個的逐項真偽：沒查，照 GATE-BLOCK 的分類轉列。
- `PENDING-RULINGS` 18 條的內容：沒讀，只轉列數量。
- T5 的 1,319 個 commit 中有多少是功能變更（相對於文件）：沒分。

## 🟡 傳票 JV29～34 之後的排程（2026-09-24 使用者表單：「傳票做完再說」）

來源：hichan-0a 三路唯讀檢視（簽核權限／金流／報價與案件），重點項皆讀碼確認。

| 組 | 使用者勾選 | 內容（file:line 為 HEAD 3370d74 附近） |
|---|---|---|
| 簽核 | 額外支出退回權限 | `case_extra_expenses.py:499`、`:1019` 呼叫 `check_reject_permission` 但丟掉結果（approve 側 09-15 已修同型） |
| 金流 | 收款資料驗證 | `cashier.js:331` 送 `receivedAt:''`、`quotations.py:3113` 不驗 ⇒ 已收款但無日期，所有收入報表漏算；`actualAmount`／`feeAmount` 不驗型別（清空 ⇒ 報表 500）；`receivedBy` 由伺服器記 |
| 金流 | 防業務改已收款期別 | `quotations.py:2209-2226` 批次存檔只比對部分欄位（可刪除／改日期已收款期別、改 taxExempt）；`mark_payment` 以陣列位置 `idx` 定位（`:3075`）無併發鎖 |
| 金流 | 稅額算法與收支基準統一 | 稅額三種算法（`reports.py:2619`、`helpers/quotations.py:199`、`payment_requests.py:265`）；收入按收款日、支出按派工日。⚠️ **基準要會計決定**，動工前用表單問使用者 |
| 報價案件 | 資料遺失類 | `case-management.js:1324` `selectCase()` 取消待存計時器後直接 `dirty=false`（已確認）；`window.motrixIsDirty` 未接；刪除無確認 |
| 報價案件 | 輸入解析 | 金額 `type=number` 貼「12,000」成 0；毛利率清空 ⇒ NaN 該行當 0 且跳過需審核 |
| 報價案件 | 清單與標籤 | 單號搜尋大小寫（`quotations.html:587`）、篩選不保留、狀態標籤矛盾、案件連結沒帶單號、鍵盤新增品項 |
| 報價案件 | 預覽與 PDF 統一 | 9 處可見差異（預覽寫死公司抬頭、項次編號不同…）⇒ 預覽改用伺服器版面 |

未勾選（記錄在此，不做）：全單據禁止自己核准、獎金分潤單走共用檢查、稅額沖銷自核、T100 匯出三項（其中「每月 1 號承攬商付款漏匯」**已讀碼確認**：`accounting_export.py:233-237` 以 `>= 'YYYY-MM-DDT00:00:00'` 比對純日期 `paid_at`）。

## 🟡 字級「特」時選單／簽核視窗／側邊清單超出畫面（2026-09-24，使用者：「傳票全部做完再做」）

使用者：「部分使用者在字型用特大情況下，左右列表會無法閱讀，簽核跟選單在頁面外無法拖動」。

**成因（已實測）**：`sidebar.js:61-70,114-117` 字級按鈕以 `document.documentElement.style.zoom`（小 0.85／標 1／大 1.15／特 1.3）放大；
根元素 zoom 會把 `vh`／`dvh` 一起乘上倍率 ⇒ 以視窗高度限高的 fixed 元素超出畫面，fixed 不隨頁捲動 ⇒ 拖不到。
```
Chromium 151, viewport 1366×768（scratchpad zoomtest.html）
              zoom 1   zoom 1.3
max-height:90vh 彈窗底邊   730      948  ← 超出 180px
calc(100vh-20px) 側欄     748      972
100dvh                   768      998
改成 calc(Nvh / var(--fz,1)) 後：0.85/1/1.15/1.3 ⇒ 724/730/735/741、742～751、768 —— 全在畫面內
```
**修法**：①`motrixSetZoom` 與初始化同時設 `--fz`；②前端 52 檔 132 處 `Nvh`／`Ndvh` ⇒ `calc(Nvh / var(--fz,1))`（白名單逐檔、驗收「該改的 0／不該改的沒動」，vendor 除外）；③`.mnav__panel`（`style.css` 約 :475）加 `max-height:calc(100dvh / var(--fz,1) - var(--topbar-h))`＋`overflow-y:auto`；④e2e：四段字級 × 1366×768，量選單面板、簽核彈窗、側邊清單底邊 ≤ innerHeight，HEAD 在「特」先紅。

## 🟢 並行派工（2026-09-24 使用者表單：「加開，用獨立 worktree 並行」）

| 視窗 | 範圍 | 檔案領域 |
|---|---|---|
| hichan-61 | 傳票 JV32→JV35→JV29→JV31→JV33→JV34（`SPEC-JV28-ATTACHMENT-PREVIEW.md`） | `vouchers.py`、`helpers/voucher*.py`、`voucher.html`、`voucher.js`、`approval-queue.html` 傳票列、`quotations.py` 的 `_REASSIGN_TABLES`／reassign（JV35） |
| **新視窗** | 本檔「🟡 傳票 JV29～34 之後的排程」中：①額外支出退回權限 ②收款資料驗證 ③防業務改已收款期別 ④報價案件：資料遺失類 → 輸入解析 → 清單與標籤 → 預覽與 PDF 統一 | `case_extra_expenses.py`、`quotations.py`（收款／批次存檔段，**不含** reassign 段）、`cashier.js`／`cashier.html`、`case-management.*`、`quotation-form.html`、`quotations.html`、`pdf_gen.py` 報價段 |
| hichan-0a | 派工、核對、建包驗包；只寫 `.md` | — |

仍排後：字級「特」（會動 52 檔含 `voucher.html`，等傳票完成）、稅額與收支基準（待會計決定，動工前表單問使用者）。

**並行規則**（違反任一條即停手回報）：
1. 新視窗一律在**自己的 git worktree＋分支**工作（例：`feat/money-quote-2026-09-24`），不在共用工作樹寫檔；完成一項就 rebase 到最新 master、全量綠、再 fast-forward 合回並 push。
2. `quotations.py` 兩邊都會碰：hichan-61 只動 reassign 段（約 :5717-5830），新視窗不碰那段；合回時衝突一律回報，不自行取捨對方的改動。
3. 鎖定檔（`db.py`、`main.py`、`sidebar.js`、`helpers/__init__.py`）動前向 hichan-0a 宣告。
4. 題名**不帶工作編號**（今晚 `test_t11_*` 撞名的教訓）；每支新題先在 master 上證明會紅。
5. 突變一律在 worktree 內做；使用者可見的改動附頁面實測。
6. 版本紀錄：同模組同期間併入既有條目（VR3），新模組才新增；合回前確認不與 master 撞號。
7. 不建包；建包由 hichan-0a 在兩邊都合回後統一做，上線與否由使用者決定。
