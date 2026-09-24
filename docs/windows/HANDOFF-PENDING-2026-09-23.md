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

## 🌙 夜間授權（2026-09-24 使用者睡前表單）
| 事項 | 裁示 |
|---|---|
| 規格沒寫到的小決定 | **hichan-0a 按預設裁、標「待使用者確認」**，記在本檔下方「待確認清單」；**金額計算、權限放寬、刪除資料一律停下等使用者** |
| 傳票做完後 | 字級「特」**接著做**（hichan-61） |
| 全部做完後 | **建包驗包備妥，不部署** |
| 開發機 | 完成後**啟動開發機伺服器**（https://127.0.0.1:666）並附操作清單 |

### 待確認清單（夜間由 hichan-0a 代裁，早上請使用者過目）
| # | 項目 | 代裁內容 | 若不同意要改哪裡 |
|---|---|---|---|
| N1 | 收款驗證範圍 | 已收款的後端驗證補在「出納標記收款」與「半解鎖審核後重播」兩處；案件頁批次存檔只驗**本次有改動**的已收期別，舊資料不擋 | 改成批次存檔全驗 ⇒ 舊資料有缺日期的案件會存不下去，需先清資料 |
| N2 | 收款日期 | 已收款必須有合法日期；未來日期不擋 | 要擋未來日期可加 |
| N3 | 實收金額 | 不填＝沿用現行「以應收金額計」；填了空字串、非數字、負數一律擋下；出納頁欄位空白不能按確認 | — |
| N4 | 手續費 | 空白視為 0（維持現行）；非數字、負數擋下 | — |
| N5 | 收款人 | 一律由系統記錄操作者，不接受畫面傳入；半解鎖送審路徑記「提出申請的人」 | 若要記審核人要改 |
| N6 | 傳票類別能否手動改 | 09-23 JV20 使用者原話「傳票不需要有類別的選項」與 09-24 表單「自動判斷，可手動改」衝突 ⇒ 先做**自動判斷＋只顯示「收入／支出／轉帳傳票」＋PDF 印名稱**（符合準則 §6），**不放選單、不動 db.py** | 要手動改 ⇒ 加 `category_manual` 欄位（db.py migration）＋翻面 JV20 守門題 |
| N7 | 平台化「不改原碼」的界線 | hichan-bf 的 `docs/PLATFORM-FOUNDATION.md` §5.0 指出：任何新模組都要在既有登記表加一列（main.py 掛載、db.py 展示清單、archive 備份、users.html、sidebar、manifest），完全不碰原碼連掛載都做不到 ⇒ **建議**：「附加登記」（A 類）視為允許；「修改既有行為」（B 類）逐點問使用者。**夜間不代裁**（屬於重新詮釋使用者的硬約束） | 由使用者選 |
| N8 | 附帶發現（hichan-bf，未處理） | ①獎金分潤單的簽核流程在設定頁設不到（`bonus.py:1171` 讀 `bonus_approval_flow`，`approval-settings.html:448` 清單沒有 bonus）②沒有測試守「寫入端點要呼叫 `_audit`」③`helpers/uploads.py:63` 未檢查 doc_no 目錄穿越（可利用性未確認：呼叫端多半先查單據存在）④無覆蓋率門檻 ⑤`tools/check_approval_queue_coverage.py` 無人呼叫 | 要不要排程 |
| N9 | 已收款期別的修改限制（③） | 非管理且非出納：已收款期別整期凍結，只能改發票號碼／日期／發票檔；不能刪除；**任何期別都不能改或新增「免稅／沖銷」標記**（原本業務可直接設 taxExempt 讓應收變小，繞過沖銷簽核）；出納收款加併發鎖與期別 id 比對；存檔失敗顯示原因 | 若業務需要自己更正已收款期別或設零稅率期別 ⇒ 放寬 E1／E3 |
| N10 | 舊期別擋住整張案件存檔 | **現況（已由題釘住）**：案件裡若有「沒有期別 id 的已收款舊期別」，業務存檔時會被當成新增已收款而整筆 403，連不相關的欄位都存不了。hichan-8d 原想「內容完全相同就放行」，但那相對現況是**放寬**，依夜間規則停下 ⇒ 維持現況 | 要放行 ⇒ 業務可在不動那一期的前提下存其他欄位（或一次性補上舊期別 id） |
| N11 | 案件頁防資料遺失（④） | ①切換案件時先等上一張存完；存檔失敗會問「上一張沒有存成功（原因），仍要切換並放棄變更？」②有未存變更時，側欄換頁與關分頁會警告 ③刪除階段、拜訪紀錄、付款期別、材料、設備前先確認，訊息寫出要刪的名稱（叫料品項、表單內品項、切換負責人不加，因為可復原或另有儲存鈕） | 要加或減確認範圍 |
| N12 | 傳票摘要面板「連金額一起帶入」 | JV33 面板：點摘要同時列出本傳票已上傳檔案與支出項，點一下把名稱帶進摘要（空白則填入、非空以「；」接續）；**「連金額一起帶入」按鈕這一輪不做**——它會決定金額填借方（建議：支出項屬費用／成本 ⇒ 借方），屬金額相關，依夜間規則停下 | 要做 ⇒ 支出項金額帶入該行借方，限借貸都空白的行 |
| N13 | 報價單特殊條件由前端決定（hichan-8d 發現，hichan-0a 讀碼定性） | 每張報價單送出都會進「待審核」（`quotation-form.html:3349`），**簽核本身繞不過**；但「低毛利／有效期超過 30 天／有折讓／稅率低於 5%」這些**提醒簽核人的特殊條件**是前端算好附上的，後端不重算 ⇒ 直接呼叫 API 可以不附，簽核人看到「標準報價單送出」 | 要不要讓後端重算特殊條件並覆蓋前端送來的內容 |
| N14 | 報價單數字輸入（④ 輸入解析） | 品項數量／成本／單價、運費、折讓改成接受「12,000」與全形數字，解析不了就標紅不存；毛利率清空時失焦還原上一個值（不當 0）；內部成本區與案件款項金額不在這次範圍 | 要擴大範圍 |
| N15 | 🔴 hichan-8d 的 push 被權限擋下 | hichan-8d 執行 `git push` 被它 session 的自動權限分類器拒絕（Modify Shared Resources）。**hichan-0a 不代推**（等於繞過你的權限設定）⇒ 金流＋報價案件的成果全部停在本地分支（最終 tip 在 `feat/money-quote-2026-09-24-rebased`），**不會進今晚的包** | (a) 放行 hichan-8d 的 push ／ (b) 你自己推或指示 hichan-0a 推；推上去後重建一次包 |
| N15 補 | hichan-8d 鏈的測試狀態 | 鏈 tip `4b88396`（本地分支 `feat/money-quote-2026-09-24-rebased`）：全量 3 紅逐一追查 ⇒ jv33「不是它造成」（master 既有競態，已由 hichan-61 `d4e82ba` 修）、ql24「不是它造成」（題的競態，已派 hichan-61）、**額外支出變更申請 e2e「判定不了」**（全量時 tip 紅 1 次、基準 0 次；壓力比對 20 輪兩邊皆 0；讀碼無交集） | 放行推送 ⇒ 建包全量若再紅就回頭追這條鏈 |
| N16 | 報價單「狀態」與「成案標記」兩套標籤 | 清單上兩套標籤並排（狀態：草稿／待審核／已核准／已送出／已確認；成案：未提供／已提供／已成案／未成案／已結案），摘要卡「已確認」數狀態、「本月金額（已成案）」數成案標記。這一輪只做：分頁「全部(不含未成案)」改名「進行中」、加標籤說明、「已成案」灰掉時顯示原因；**兩套標籤的定義與「確認」用語統一不改**（業務語意） | 要不要統一「確認／成案」的說法 |
| N17 | 報價預覽與 PDF 統一後，草稿不能直接列印 | 預覽改成顯示伺服器產生的正式版面（和下載的 PDF 同一份，9 處差異消失）；列印改成下載伺服器 PDF ⇒ **未存檔的報價單列印鈕停用，要先存檔**；原本斷線時用前端版面列印的備援也一起移除 | 若業務需要列印未存檔的草稿 ⇒ 另做「以目前表單內容產 PDF」 |
| — | N17 更正 | hichan-8d 讀碼：前端列印函式 `exportPDF()` 在畫面上**沒有任何呼叫端** ⇒「草稿不能列印」**實際上不改變現在的作業方式**，N17 可視為告知即可。預覽改成伺服器版面已完成（4b88396，本地未推送）：預覽與 PDF 交給 Edge 的 HTML 逐字相同 | — |
| — | ~~「`window.motrixIsDirty` 未接」~~ | **更正**（hichan-8d 讀碼、hichan-0a 複讀 `sidebar.js:1025-1031`）：旗標在輸入時本來就會設成 true；真正缺陷是**任何一次成功的寫入請求都會把它清掉**，而同時編輯提示每 8～15 秒送一次心跳 ⇒ 打完字最多 15 秒警告就失效，**所有有同時編輯提示的頁面都受影響**。修法：心跳請求與自行管理旗標的頁面不清（改 sidebar.js 約 6 行，已准） | — |
| — | ~~收款驗證「清空實收金額 ⇒ 報表 500」~~ | **更正**：hichan-8d 端到端未重現（測試案件未被報表撈到，原因未查）；讀碼推論成立但未證實 ⇒ 未留報表題。原說法出自 hichan-0a 轉述的檢視 agent 讀碼推論 | — |

## ☀️ 早上給使用者：開發機實測清單（http://127.0.0.1:666，master d4e82ba）

開發機用開發資料庫，通知信全部擋下不會寄出。依序操作，覺得不順手的地方直接說：

| # | 操作 | 應該看到 |
|---|---|---|
| 1 | 傳票 → 新增傳票，第 1 行科目欄輸入「1113」或「銀行」 | 下拉選單可搜尋，選到「1113 銀行存款」，科目名稱欄唯讀 |
| 2 | 借方輸入「1,000」、第 2 行貸方輸入「１０００」（全形） | 都存成 1000；輸入「12.5」會紅字說明不可有小數 |
| 3 | 在最後一行按 Enter | 自動新增一行 |
| 4 | 故意讓借貸不平，點空白行的「補平差額」 | 差額填進較少的那一側 |
| 5 | 點任一行摘要 | 右側面板同時列出本傳票已上傳檔案與支出項；先選案件才有支出項；點一項帶入摘要，再點一項以「；」接在後面 |
| 6 | 上傳一張圖片與一個 PDF，點檔名與縮圖 | 同頁預覽（不開新分頁）；SVG 等只給下載 |
| 7 | 看傳票上方 | 顯示「收入傳票／支出傳票／轉帳傳票」（依分錄自動判斷，無選單） |
| 8 | 送審 → 用非該層簽核人的帳號按核准 | 被擋並說明該層簽核人是誰；製票人在該層名單內可自簽 |
| 9 | 簽核佇列（最高管理者）選這張傳票 → 轉簽 | 原因必填；轉簽後新的人可核准、原本的人不行 |
| 10 | 過帳後匯出 PDF | 標題是傳票名稱、簽章欄有「記帳」、表頭有「附件 N 張」、頁尾「第 1/N 頁」 |
| 11 | 傳票清單上方 | 關鍵字、日期區間、狀態篩選 |
| 12 | 作廢時勾「作廢並重開」 | 直接打開一張新草稿 |
| 13 | 右上字級切到「特」，打開簽核佇列的彈窗 | 彈窗完整在畫面內（案件管理、出納、報價單三頁尚未修） |

已知限制：頁碼需要 Edge 131 以上；報價與金流（hichan-8d）的成果還在本地，等 N15 決定後才會進開發機與升級包。

## ✅ 夜間最終包（2026-09-24 07:31，hichan-0a）—— 備妥，**未部署**

```
路徑    deploy_packages\20260924_073129_d4e82ba   231 檔
樹雜湊  4938c4fc5e45b410ea2901d4a59b419bae2c842f738d70502301bd004201aa52
內容    master d4e82ba：傳票 JV28～35、字級「特」、JV33 載入中修正（正式機 46dc6ae 之後的全部 hichan-61 成果）
測試    非 e2e 2609 passed / 3 xfailed(WD1) / 0 failed；e2e 104 passed / 0 failed
驗包    內部文件（docs/windows、docs/quick、docs/reference、backend/tests、QUICK、兩份平台化文件）皆 0；
        backend/main.py、apply_update.ps1 在（對照）；apply_update 乾跑判斷已是修正版
DB      CURRENT_VERSION 109（與正式機 46dc6ae 相同）⇒ 這次沒有資料庫升級
```
- ⚠ 驗包第一次跑時我擷取包名的指令壞掉、路徑為空 ⇒ 那一輪的「0 筆」量的是不存在的路徑，**不採信**；以明確包名重跑的結果如上。
- `20260924_065113_218d810` 為中途驗證包，不用。
- **不含** hichan-8d 的金流＋報價案件（N15）。N15 放行後需重建。
- 部署：`powershell -ExecutionPolicy Bypass -File <包>\backend\tools\apply_update.ps1 -PackagePath <包>`；正式機現有的 apply_update 已是修正版，也可用正式機那支。

## ☀️ 使用者晨間裁示（2026-09-24，第 1 批表單）
| 項目 | 裁示 |
|---|---|
| N15 | **指示 hichan-0a 推送** hichan-8d 的鏈（使用者明示，非代為繞過） |
| 最終包 | **等 N15 合進 master 後一起上**（重建一包、一次部署） |
| N6 | **要能手動改**傳票類別 ⇒ 推翻 09-23 JV20「傳票不需要有類別的選項」；加 `category_manual` 欄位（db.py migration）＋選單＋翻面 JV20 選單守門題（docstring 記兩次原話與日期） |
| N12 | **要**：摘要面板點支出項「連金額一起帶入」，限該行借貸都空白、帶入借方 |

## ☀️ 使用者晨間裁示（第 2 批表單）
| 項目 | 裁示 |
|---|---|
| N7 | **附加登記允許、改行為逐點問**（平台化約束的界線） |
| N9 | **可以**（業務對已收款期別只能改發票欄位、不能刪、不能設免稅／沖銷） |
| N10 | **放行：不動那期就能存**（使用者明示放寬；舊的無 id 已收款期別內容未變時，業務可存其他欄位） |
| N13 | **要，後端重算**報價單特殊條件（簽核人看到的原因由後端算，覆蓋前端送來的） |
| N10 補 | **更正**（hichan-8d）：夜間說「整筆擋」不完全對——保留那期時會擋，但**整期刪除無 id 的已收款期別反而放行**（E1 刪除檢查略過 id 為 None）。`64aa837` 一併補上：內容未變放行、刪除或變動仍 403 |
| JV33 | **使用者更正需求** ⇒ 改為 JV36（見 `SPEC-JV28-ATTACHMENT-PREVIEW.md` 檔尾）：連帶檔案「只顯示、勾選才帶入」，舊面板「改成新行為」 |

## 📌 已知限制（使用者裁示接受）
- **N13-R2**：報價單「低毛利」特殊條件在後端重算時**只看毛利率欄位**（照前端移植）；毛利率欄位可被假造，搭配真實的低單價仍可隱瞞低毛利。使用者 2026-09-24 表單原文「只看毛利率欄位」——**接受此限制**。
- **N13-R3**：「第 i+1 項」的項次含區段標題位置，和 PDF 項次（不含區段標題）不一致；照移植不改。
- **FORM_VERSION**：9084c28 系列 3 個 commit 與 N13 改了 `quotation-form.html` 卻沒 bump（違反維護規則）⇒ 由 hichan-8d 補 V2.0 → V3.0（預覽改流程 +1）。

## 🟢 UR1 未讀紅點逐筆已讀、存伺服器（2026-09-24 使用者；執行者 hichan-bf，解除「只寫文件」限制）
使用者：「目前很多使用者反應，我點選選進某些未讀的，點選後紅色未讀沒有即時消失」；三種都要修（選單紅色數字、右上鈴鐺、清單未讀標記）；表單「逐筆已讀，存在伺服器」「讓 hichan-bf 寫碼」。

**成因（讀碼確認，origin/master）**：
- 選單數字：「看過」只在**下一頁載入時**寫入（`sidebar.js:1104-1114`）且用**用戶端時鐘**與伺服器 `audit_log.at` 字串比較；無輪詢、無 `pageshow`／`storage` 監聽 ⇒ 上一頁與其他分頁不更新；以模組為單位（`_FILE_MODULE`）；`tender_radar` 不在 `modBadge`／`_MODULE_ACTION_PREFIXES` ⇒ 永不亮。
- 鈴鐺：只呼叫 `read-all`（`notif.js:219`），打開下拉才全部已讀、await 後才歸零；`PATCH /api/notifications/{id}/read`（`system.py:322`）無呼叫端；下拉項目不可點。
- 清單標記：dev-crm（`isUnread` 比 `motrix_devcrm_read_at`）、案件管理（`case-management.js:1200-1216`）、每日工作（`prev_seen`）皆**模組層時間**，開單筆不清；自己的修改也算未讀；全存 localStorage。

**做法**：
1. 新表 `item_reads(username, kind, item_key TEXT, read_at)`，主鍵 (username, kind, item_key)；read_at 用**伺服器時間**。migration **v113**（v111＝JV36、v112＝獎金；以合回時 master 為準、撞號順延、db.py 先宣告）。DM1 分類、每日 JSON 匯出一併登記。
2. API：`POST /api/reads`（標記單筆，伺服器蓋時間）、`GET /api/reads?kind=`；模組數字端點改用伺服器端「看過」時間（新增 `module_seen` 也存伺服器，或併入 item_reads 的 kind='module'），**排除本人造成的事件**。
3. 前端：點選單項目／清單項目**當下**先清 UI 再送請求（`keepalive`），不等回應；`pageshow`（persisted）與 `storage` 事件觸發重抓；鈴鐺下拉改列真通知、點一則標那一則；`tender_radar` 補進兩處對照。
4. 清單標記改為「該筆 updated_at（排除本人）＞ 該筆 read_at」。
5. 舊 localStorage 鍵：首次載入時一次性上傳遷移（不遺失既有已讀），之後停用。

**界線**：`sidebar.js` 為鎖定檔——動前向 hichan-0a 宣告範圍；hichan-61 另有字級（約 :69、:116）與 hichan-8d 的 dirty 清除（:1023-1034）改動，避開這兩段。在自己的 worktree；題先紅；使用者可見的改動附頁面實測（至少：點一筆 ⇒ 該筆紅點立即消失、上一頁回來仍消失、另一分頁在 pageshow／storage 後同步）。

## 🟢 MP 地圖優化（2026-09-24 使用者勾選；執行者 hichan-61，MP0 緊接 JV36，其餘排在字級＋FORM_VERSION 守門之後）
盤點（Explore agent 讀 origin/master，重點項 hichan-0a 複讀）：端點 `GET /api/map/points`（`routers/map_points.py:375`）、`helpers/geo.py`、`frontend/pages/map.html`。

| 編號 | 項目 | 依據／做法 |
|---|---|---|
| **MP0 🔴 必修** | 彈出視窗 XSS | `map.html:915` 把 `p.name`／`p.org`／`p.address` 直接拼進 `bindPopup` HTML（hichan-0a 已讀碼確認）；標案資料來自**外部網站** ⇒ 一律 `_esc`（`:900` 據點彈窗已有 `_esc` 可照做）；題：名稱含 `<img src=x onerror=…>` ⇒ 彈窗內為純文字 |
| **MP0b 🔴 條款** | Google 經緯度快取 ≤ 30 天 | `geo.py:383` `GEOCODE_CACHE_TTL_DAYS=180` 對所有來源一體適用；Google SST §14.3 經緯度最多 30 天 ⇒ `source=google` 的列 30 天過期（其他來源維持 180）；只在有設 Google 金鑰時相關 |
| MP1 | 點位連到單據 | 回傳帶記錄 id；彈窗與表格可點開客戶／供應商／標案／出貨單；單據頁加「在地圖上看」（`map.html?focus=kind:key`） |
| MP2 | 粗精度變淡＋群聚 | `precisionIsCoarse` 的點用淡色／空心 pin；重疊點群聚（Leaflet.markercluster 自架於 vendor，照 leaflet 的 PROVENANCE 模式） |
| MP3 | 標案依截止日上色＋篩選 | 未截止／7 天內截止／已截止三色；篩選預設「未截止」 |
| MP4 | 清單與地圖連動＋搜尋＋導航 | 點表格列 ⇒ 地圖平移並開彈窗；關鍵字搜尋；「附近 N 筆」；Google 導航**只給 URL 連結**（不存 Google 資料） |
| MP5 | 全螢幕與手機版 | 高度隨視窗（配合 `--fz`）；全螢幕鈕；手機斷點 |
| MP6 | 案件地點圖層 | 報價／案件的交貨地點（`deliveryAddress`／`deliveryLocation`）成新 dataset；權限比照 shipping（case_manage 或 quotation）；走既有地址定位階梯與背景預熱 |

不做（條款）：預先下載 OSM 圖磚；儲存 Google 回傳的店名／地址。
界線：`map_points.py` 的 dataset 權限不放寬；新 dataset 加進背景預熱時注意每日 120 筆上限；每項題先紅、頁面實測。

### MP 追加（2026-09-24 使用者：「地圖模組每次使用者都要載入一次，讓流量很快卡死，並且地圖模組內使用者看到的文字太口語」）
| 編號 | 項目 | 依據／做法 |
|---|---|---|
| **MP8 🔴 緊急** | 開地圖不再同步查外部定位 | 讀碼確認：`map_points.py:641` 每次請求有 6 秒預算、同步呼叫 `geo.locate_cached()`（:689）查未定位地址（Nominatim 每 1.1 秒一次）；查不到的只記在行程記憶體（重啟即忘）⇒ 每位使用者每次開啟都重查；回應無快取；每次切篩選重抓（`map.html:664`）。做法：①請求路徑**只讀快取、不查外部**，未定位的列入 `pendingGeocode` 交背景預熱（§3v）②伺服器端回應快取（依使用者可見 dataset 組合為鍵，短 TTL，資料異動失效）③前端一次抓回可見的全部 dataset，切篩選在前端過濾 ④移除「繼續定位」鈕（或限最高管理者手動觸發背景預熱）⑤題：開地圖期間外部定位呼叫次數＝0（替身計數）；同一使用者連開兩次第二次命中快取 |
| **MP7** | 地圖文字改正式精簡 | `map.html`、`tender-radar.html` 地圖相關的使用者可見文字（提示、警告、彈窗、按鈕、空狀態）改為正式、簡潔的用語，去掉口語、驚嘆與冗長說明；註解不動。改完列出新舊對照給 hichan-0a 核對 |

順序：JV36 → **MP0／MP0b／MP8** → 字級 3 頁 → FORM_VERSION 守門 → MP7 → MP1～MP6。
- **MP0c／MP0d（使用者表單）**：「加每日自動刪除」⇒ 每日刪 `geocode_cache` 中 source='google' 且超過 30 天的列（只刪快取、記 system_audit）；「更正為 30 天」⇒ Google 用量計算器依來源實際有效期估算。

## ☀️ 使用者裁示（2026-09-24 午，第 3～5 批表單）
| 項目 | 裁示 | 執行者 |
|---|---|---|
| 部署 | **全部排程做完再上**（含字級 3 頁、FORM_VERSION 守門、地圖全部） | hichan-0a 最後建包 |
| B4 | 條件簽核**第一版只給平台自訂單據** | 平台化 |
| **B7** | 權限模組清單**整併成一份**（目前散在 users.html、auth.py、sidebar.js、db.py v84、system.py…） | hichan-bf，**先交計畫** |
| B8 | `save_document_files` 的 doc_no 穿越檢查**補在共用函式** | hichan-bf |
| N8 | ①守門：寫入資料的端點必須呼叫 `_audit`／`_system_audit` ②`tools/check_approval_queue_coverage.py` 接進建包（或改寫成測試） | hichan-bf |
| N1～N5、N16 | 維持現做法（N16 兩套標籤只加說明） | — |
| **N11** | 刪除確認**全部都加**（含叫料品項、派工／出貨表單內品項、負責人切換） | hichan-8d（獎金後） |
| **N14** | 金額輸入解析**擴大到內部成本區與案件款項金額** | hichan-8d（獎金後） |
| 會計師題 | 「**先按照台灣稅法跟會計法，有需要再修改**」⇒ 稅額算法、收支認列基準、獎金入帳科目依法規預設實作 | hichan-0a 先查法規條文定規格 |
| 舊待裁（出貨阻擋 4、PENDING 18、KNOWN-GAPS 11） | **先擱著** | — |

## 🚶 使用者外出（2026-09-24 午，表單：「沿用夜間規則」）
- 小決定由 hichan-0a 裁、記入「待確認清單（外出期間）」；**金額計算、權限放寬、刪除資料**停下等使用者（該項暫停，其他照做）。
- 會計預設（稅額、收支基準、獎金入帳）：使用者先前「先按照台灣稅法跟會計法」且**未選**「會計預設也先停」⇒ 照法規預設推進，規格註明條文。
- 全部排程完成 ⇒ 建包驗包備妥，**不部署**。

### 待確認清單（外出期間）
| 項目 | 使用者回覆（遠端表單） |
|---|---|
| UR1 無已讀紀錄的基準時間（以第一次使用時間為準） | 可以 |
| UR1 點後立刻換頁、其他分頁要重整才同步 | **要再優化** ⇒ 派 hichan-bf（樂觀同步＋單筆合併，不輪詢） |
| JV36 勾選前預覽來源檔（新讀取路徑，範圍同帶入） | 可以 |

## 🟢 AC 會計預設依台灣法規（2026-09-24，使用者：「先按照台灣稅法跟會計法，有需要再修改」；外出期間未選暫停）
法規查證（general agent，law.moj.gov.tw；標「摘要」者未逐字核對）；科目代號 hichan-0a 以系統內 `backend/data/account_items_112.json`（官方 112 年版 PDF 解析）核對。

| 編號 | 內容 | 依據 | 做法（**只新增、不拆既有畫面**） |
|---|---|---|---|
| **AC1** 稅額算法統一 | 目前三種算法（`reports.py:2619` 分期逐期 `amt - amt/1.05`、`helpers/quotations.py:199` 報價 pretax/total 比、`payment_requests.py:265`）；免稅／零稅率報價仍被算 5% | 營業稅法 §14 I（逐字）：「…分別按第七條或第十條規定計算其銷項稅額，尾數不滿通用貨幣一元者，按四捨五入計算」；§32 III B2B 銷售額與稅額分別載明；§7 零稅率、§8 免稅；統一發票使用辦法 §18（摘要）分期「應於約定收取各期價款時開立」 | 新增唯一 helper：`tax_for_invoice(sales_amount, tax_type)` ＝ `round_half_up(sales × 稅率)`，tax_type ∈ 應稅5%／零稅率／免稅；分期：該期銷售額＝`round_half_up(報價未稅 × 期別比例)`、稅額照上式；三處改呼叫它。**題：免稅報價 ⇒ 稅額 0（現況 5% ⇒ 紅）；三處同一筆資料結果相同** |
| **AC2** 權責發生制報表 | 目前收入按收款日（現金）、支出按派工日／建檔日，口徑不一 | 商業會計法 §10 I（逐字）：「商業會計基礎採用權責發生制；在平時採用現金收付制者，俟決算時，應照權責發生制予以調整」；§10 II 收益確定應收時、費用確定應付時入帳 | 營運報表／儀表板**新增**「損益（權責發生制）」口徑：收入＝發票開立（確定應收）月份、支出＝確定應付（派工完成／進貨／額外支出核准）月份；**既有「現金收支」口徑保留**並明確標名；預設顯示權責，一鍵切換。工程完工比例法等會計師判斷事項**不寫死** |
| **AC3** 獎金入帳傳票 | 獎金分潤目前只記狀態 | 科目：6111 薪資支出、2191 應付薪資（本系統官方表核對）；扣繳：各類所得扣繳率標準（摘要，門檻金額未核對） | 見 `SPEC-BONUS §11.8` |

⚠ 需會計師判斷、不寫死：長期工程收入認列方法；小規模商業（§82，摘要）是否適用簡易記帳；扣繳門檻當年度金額。
⚠ 未逐字核對：施行細則 §32-1、統一發票使用辦法 §18、扣繳相關條文 ⇒ 規格與程式註解標「摘要」。
執行者：hichan-8d（接在獎金、N11、N14 之後），順序 AC1 → AC3 → AC2。

## 🟢 CM 案件管理調整（2026-09-24 使用者表單：12 項全選）
檢視（Explore agent 讀 origin/master，#1 hichan-0a 複讀確認）。

| 編號 | 項目 | 依據 | 執行 |
|---|---|---|---|
| **CM1 🔴** | 同時編輯不再蓋掉對方 | `case-management.js:1873` 存檔只送 `{case_record}`、**不送 `_expectedUpdatedAt`**；後端支援樂觀鎖（`quotations.py:2289`）但沒收到就整份取代（`:2366`）⇒ 後存者靜默覆蓋前者，上傳的發票檔也會被舊頁面的自動存檔丟掉。做法：送 `_expectedUpdatedAt`，**每個會改 updated_at 的回應都更新它**（含上傳檔、階段呼叫）；409 ⇒ 提示重新載入／合併；第二步改成各分頁分段存（payment／materials／devices／roles）。題：兩個 context 同時改不同分頁 ⇒ 後存者 409、兩人的改動都不遺失 | hichan-8d，**最優先** |
| **CM2 🔴** | 收款／材料／沖銷改用期別 id 定位 | `/payment/{idx}`（py:3219）、`/payment/{idx}/invoice-files`、`/materials/{idx}/files`、沖銷；期別已有 `id`（js:1808） | hichan-8d |
| CM3 | 角色改存帳號 | 三個角色存顯示名稱（html:1141-1164）⇒ 改名／同名時獎金帶入、業績歸屬、案件可見性出錯。做法：存 `{username, display}`，一次性依使用者表轉換舊資料；**查不到或同名的不猜、保留原值並列出清單** | hichan-8d |
| CM6 | 清單不再限 500 件 | `loadCases()` `limit=500`（js:1124）、前端篩選；開清單還拉 stage-board 與 gate-matrix（每案約 15 次查詢）。做法：伺服器端搜尋／篩選／分頁；`edit_last` 用 json_extract；gate 批次計算 | hichan-8d |
| CM4＋5 | 結案前先列出五關、可點過去修 | `closeCaseAction()`（js:1978）先確認後檢查；gate-matrix 格子不可點。做法：確認前顯示五關與「前往」鈕（`_pendingUrlTab`）；存檔失敗就中止；單據關顯示待簽核人；非 superadmin 不顯示結案鈕 | hichan-61 |
| CM7 | 清單常用篩選 | 我負責的、逾期階段、應收逾期（`expectedReceiptDate`）、缺單據；「全部」分頁改名「進行中」 | hichan-61（依 CM6 的伺服器篩選） |
| CM9 | 案件健康總覽 | 案件資訊頁上方：五關狀態＋逾期應收＋待簽核 | hichan-61 |
| CM11 | 跨模組連結 | 加獎金分配、地圖（MP6）、傳票（JV36 來源）連結；結案後留在案件、不跳保固頁 | hichan-61 |
| CM8 | 開案件請求合併 | 目前約 16 個請求（js:1415-1428）⇒ `case-bundle` 端點＋分頁延後載入 | hichan-8d（CM6 後） |
| CM10 | 批次操作 | 多選：批次改執行負責／成員、批次匯出 | hichan-61（CM7 後） |
| CM12 | 前端拆分重構 | 566KB 單一元件、`selectCase` 手動重設約 100 個狀態。**必須最後做**，且開工時其他視窗暫停碰案件管理，避免衝突；純重構不改行為，全部既有題須維持綠 | 最後排定 |

順序：hichan-8d：**CM1 → CM2** → N11 → extra_expenses 追查 → CM3 → CM6 → CM8 → N14 → AC1 → AC3 → AC2。hichan-61：案件管理字級 e2e → MP7 → MP1～MP6 → CM4＋5 → CM7 → CM9 → CM11 → CM10。CM12 最後。

## 🟢 CU 案件管理 UI/UX（2026-09-24 使用者表單；執行者 hichan-61，排在 CM10 之後；CM1/CM2 已動的檔先 rebase）
| # | 項目 | 內容 |
|---|---|---|
| CU1 | 顏色語意＋不只靠顏色 | 「目前階段」不用紅（紅只給逾期）；逾期顯示「逾期 N」文字；看板補「有新動態」標籤；階段條可鍵盤操作 |
| CU2 | 錯字與用詞統一 | 代辦→待辦、備注→備註、＋／+ 統一、完結案→結案、承攬商／點工人員定義一致 |
| CU3 | 存檔回饋明顯化 | 成功提示；錯誤／衝突常駐橫幅（與 CM1 的 409 橫幅共用樣式） |
| CU4 | 全部階段完成不彈視窗 | 改內嵌提示條「全部階段已完成 → 結案」 |
| CU5 | 標頭整理＋分頁改名 | 第一列客戶名＋狀態；主鈕只留「儲存」，其餘收進「更多」；「專案資訊」→「成員」；收款移到財務分頁 |
| CU6 | 標明即時儲存／按儲存 | 區塊標題標註；即時儲存成功閃 ✓ |
| CU7 | 表單標籤與必填 | label 綁欄位、必填 *、勾已收款當下提示填日期 |
| CU8 | 手機／窄螢幕不溢出 | 款項明細、拜訪紀錄窄螢幕兩欄；分頁列捲動提示 |
| — | 共用提示／對話框、按鈕樣式＋深色模式、字級規範（下限 11px） | **併入 CM12 前端拆分**，不單獨做 |

## 🟢 其他裁示（2026-09-24 使用者表單）
- B7 第三階段：**做**，後端只驗「這次新增的」模組 key（未知 → 400）；既有帳號身上的舊 key 照放行。
- UR1 追加：選單紅點數字與鈴鐺也做跨分頁即時更新（hichan-bf）。
- hichan-0a 代裁（待確認）：UR1 網路錯誤不還原（keepalive 可能已送達）——同意。CM1 改為「分段存＋分段比對基準」——同意（整張單一個 updated_at 會讓不同分頁互擋，達不到 CM 規格的目的）。
- NEXT：module-counts 索引（v114 以後）；`static/vendor/leaflet/` 目錄不帶版本，升版會被一年快取卡住 ⇒ 改帶版本目錄（hichan-61 於 MP 完成後）。
- master spec-coverage 紅（N11 撞名）：hichan-0a 的 `test_n11_remaining_…` 改名解除（eaf1209）。

## 🔴 CM13 案件金額欄位後端遮蔽（2026-09-24 使用者表單：「要，後端移除金額欄位」；執行者 hichan-8d，排在 CM2 之後）
- 實查（origin/master 4e0072f）：`GET /api/quotations`（quotations.py:699）回 `total／pretax／direct_margin_pct／net_margin_pct` 給任何看得到該案件的人；結案檢核清單（:1041 `"total"`）同；`GET /api/quotations/{quote_no}` 回整份 data_json（含品項單價與成本）。`can_see_financial()` 只套在財務總覽三支（auth.py:201 docstring 明寫）。
- 裁示：沒有 `can_see_financial()` 的帳號，後端**不回**金額、毛利、單價、成本欄位；畫面顯示「—」。順序：清單 → 結案檢核 → 案件內容。
- ⚠ 簽核人例外照舊（quotations.py:5649 的既有規則）；⚠ 案件內容回寫時，被遮蔽的欄位不可被空值蓋掉（伺服器以 DB 現值補回）——這是本項最大風險，要有題。
- ⚠ 題：viewer／engineer 拿不到欄位（先在 master 證明紅）；sales／admin／financial_view 照舊拿到；engineer 存檔後 DB 金額不變。

## 🟢 重新分派（2026-09-24 12:50，使用者表單：「不加」視窗）
- AC1、AC3、AC2（AC2 先交對照表）從 hichan-8d 移給 **hichan-bf**，排在 B7 之後；接著 T12（更新紀錄頁安靜降級）、T10（版本端點 entries[0]）。
- hichan-8d：CM2 → CM13 → CM3 → CM6 → CM8 → N14。
- 預估：各視窗約 20:00 完成 → CM12 → 建包驗包，9/25 約 00:00（最晚 02:00）。
