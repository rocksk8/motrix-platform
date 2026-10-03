# 第 35b 班套用演練報告（d5；2026-10-04 03:0x）

**結論：PASS。** 工具 `tools/platform/drill_train35b.py`＋`drill_35b_tender_harness.py`（分支 `drill/train35b-d5`，由 `drill/train35a-d5` 改成 35b；**沒有改動共用工具**）。
基線＝git archive 326e6676（第 35a 班已上線）＋合成種子；新版＝35b 候選包 commit 345a34cd（full；db_version 116 不變）。演練在 `D:\開發測試檔\d5-drill35b-run\`、埠 6766（只綁 127.0.0.1）；
沒有碰正式機、`D:\MOTRIX-PLATFORM`、G: 雲端檔、正式金鑰、正式資料庫；沒有連真實標案網站（`urlopen` 替身計數＝0；`smtplib` 替身遇呼叫即丟例外；標案雷達開關關閉）。

## ⚠ 與正式機步驟的差異
- **簽章**：主持給的包是 build 產物（未簽）。演練用**拋棄式金鑰**簽發到演練專用交付資料夾（`D:\開發測試檔\d5-drill35b-deliv\`，私鑰不離開該資料夾），驗章用該演練公鑰；**正式金鑰簽章的驗證不在本演練範圍**（由正式機步驟 1 把關）。
- 基線資料是合成的（不是正式機資料庫副本）。
- 標案雷達的「程式層」檢查（空結果頁／不寄信日／驗證碼停抓）在**安裝後的程式**上以替身跑（`drill_35b_tender_harness.py`，只動資料庫副本）；fixtures 用標案分支工作樹的檔案，已與 int2 的同名檔逐檔雜湊比對相同（安裝包不含 tests/）。
- 比對「程式檔逐檔相同」排除執行期產物：logs、uploads、db_backups、`rollback_snapshots`、`backup_alerts`（演練庫沒有備份目標，備份告警檔是執行期產生的）。

## 指令與結果（A→C→E→B；之後再套用一次 R）
```
python tools\platform\drill_train35b.py --delivery-root D:\開發測試檔\d5-drill35b-deliv\root --name 20261004_025908_345a34cd_full --new-commit 345a34cd ^
   --pubkey-file D:\開發測試檔\d5-drill35b-deliv\keys\drill_pub.pem --drill-root D:\開發測試檔\d5-drill35b-run --port 6766 --runs A,C,E,B     → exit 0
```
1. 取包：`delivery.stage`／`verify_staged`（演練公鑰）⇒ verify_ok=true、problems 空；`verify_package.py <payload> --expect-db-version 116` ⇒ rc 0「✅ 全部通過（0 項 FAIL）」，產品 full、13 個模組。
2. 套用 A：`::RESULT:: v=2 status=success rolled_back=applied service=up exit=0`（21.7 秒；commit 345a34cd59c8…）。檢查 **43／43** 全過。
3. 資料庫回滾 C（僅演練）：`status=rollback_ok rolled_back=restored service=up exit=0`（14.2 秒）；commit＝基線、schema＝基線、舊資料不變。
4. 回滾後重套 E：`status=success`（18.9 秒）；檢查 **40／40** 全過（C 把資料庫還原成套用前的種子，所以 E 重做了一次完整的 35b 檢查，包含瀏覽器完結）。
5. 只回程式 B（`rollback_update.ps1 -SnapshotTimestamp <時間戳> -Yes`，不帶 `-IncludeDatabase`）：`status=rollback_ok rolled_back=restored service=up exit=0`（13.5 秒）；commit＝326e6676…、ping 200；
   **程式檔逐檔雜湊與基線相同（879／879，差異 0）**。
6. B 之後**再套用一次 R**：`status=success rolled_back=applied service=up`、commit 345a34cd、ping 200、舊的凍結案 dispatchTotal 仍 12500、無 traceback、單一監聽行程。

### 35b 專屬檢查（A 與 E 兩輪皆過）
- `35b_1` 財務使用者 GET settlement-actuals（種子：未稅 10000＋稅 5%＋外包人員 2000）：`dispatchTotal=12000`、`dispatchTax=500`、`dispatchGrandTotal=12500`、`dispatchBasis=pretax`；與套用前相比**只有 `/totals/dispatchTotal`（12500→12000）與 `/totals/totalActualCost`（23000→22500）改變**，沒有鍵消失；新增鍵：dispatchBasis／dispatchGrandTotal／dispatchTax／tax。
- `35b_2` 非財務使用者 ⇒ **403**，回應不含 dispatchTax／dispatchBasis／dispatchGrandTotal／totals。
- `35b_3` 舊的已凍結案（summary 沒有口徑標記）：`frozen=true`、`dispatchTotal=12500`，與套用前**沒有任何值改變、沒有鍵消失**（只多了新增的鍵）。
- `35b_4` **真實瀏覽器**（Chromium headless）在精算頁按「完結精算」→「確認完結」：PUT 200；存下 `dispatchTotal=12000／dispatchTax=500／dispatchGrandTotal=12500／dispatchBasis=pretax／totalActualCost=22500`，與草稿的總成本相同。
- `35b_5` 偽造完結：`dispatchTotal=0` 蓋 pretax 標記 ⇒ **409**（差異：承攬商派發成本頁面 0／系統 12000、實際總成本、淨利 888888）；含稅 12500 蓋 pretax 標記 ⇒ **409**；兩次都沒存檔（狀態仍非 finalized）；`35b_5b` 誠實 payload（正對照）⇒ 200。
- `35b_6` 重新開啟：沒有理由 ⇒ **422**、空白理由 ⇒ 422、狀態仍 finalized；有理由 ⇒ 200。`35b_6b` 理由 `機密理由XYZ金額99999` 對非財務帳號在 `GET /api/quotations/{no}`、`/case-bundle`、`/versions` **都看不到**（三支皆 200 但無理由文字）；財務帳號三支都看得到。
- `35b_7` 結案報表 PDF（Edge headless 真產生，pypdf 抽文字）：新完結案含「承攬商派發成本 12,000／承攬商：未稅 12,000／稅額 500（進項稅額，不計成本）／實際總成本 22,500」；舊案 PDF 文字與套用前**逐字相同**（831 字元，去掉時間戳後相同）。
- `35b_8` 案件頁含 `cm-tab-settlement`（檔案＋伺服器實際送出）；精算頁含重新開啟理由對話框與「原因僅財務人員可見」。
- `35b_t1` 空結果頁（無符合條件資料）：`parse_list`＝([],0,True)、`run_scan`⇒`recognised=True／suspect_redesign=False／list_state=empty_day`、fetch log `suspected=0`、**沒有** source_changed 信；`35b_t2` 正對照：十列壞九列仍 suspected、寄 source_changed（證明替身有效）。
- `35b_t3` 週六、週日不寄（記待寄）；`35b_t3b` 平日國定假日（2026-10-26 補假）不寄、記待寄，下一個上班日（10-27）條件仍成立才補寄 1 封，之後待寄清空（注入時鐘）。
- `35b_t4` `holidays_tw.json` 在安裝目錄（2400 bytes）、載入、涵蓋 2026-01-01～2027-12-31、距到期 452 天。
- `35b_t5` 驗證碼頁：`fetch_detail` 回 CAPTCHA_ERROR；詳細頁迴圈**只請求 1 次就停**（3 筆標案），同日再掃不再請求、隔日只試 1 次（累計 1／1／2）；標案照留、地點維持 NULL；掃描狀態 detail=captcha。
- `35b_t6` 狀態列（`GET /api/tender-radar/status` 的 notices）：empty_day；format_changed＋detail_captcha（皆純文字 notice；另有 no_mail_day，因演練當天是週日）。
- `35b_t7` 真瀏覽器：每列恰一個「前往來源網站明細」連結（`target=_blank`、`rel="noopener noreferrer"`、href 正確）；地點＋方式皆缺的列有兩句「地點與招標方式需在來源網站通過驗證碼後查看」、只缺方式的列一句、都有的列沒有。
- `35b_c` 13 個模組載入、`unexpected` 空；版本 case 1.0.121→**1.0.129**、tender_radar 1.5.4→**1.5.6**、analytics 1.0.28→**1.0.29**（只有這三個變）；schema case=6／subcontract=5、db 116 不變；log 無 traceback；單一監聽行程；重啟冪等。

### 略過的舊班次專屬題（`35b_0_stale_checks_skipped`，理由逐項寫在報告 json）
- `15_designer_default_off`：D12 設計器預設改開（34 班起）。
- `16_subcontract_schema_stays_3`：承攬商 schema 已是 5（本班判準改 case=6／subcontract=5）。
- `16_material_tables_exist_and_empty`：35a 起種子會寫材料申請審核列，表不再是空的。
- `9c_legacy_dispatch_untouched`：第 30 班專屬；基線已含兩段審核。

## 我在演練工具上踩到的坑（已改在 drill_train35b.py／harness，沒動共用工具）
- 精算頁「已對應」區塊在沒有未對應項目時是隱藏的：瀏覽器要等「完結精算」按鈕可見，不是等 `stl-unassigned`。
- 結案報表 PDF 端點只服務 `deal_tag=已結案` 的案件。
- 路徑字串在 heredoc 裡寫反斜線會被轉成控制字元（`\t`、`\b`）：改用正斜線。
- 「B 之後再套用」我加在清理前執行，**之後必須再停一次服務**才刪得掉目錄；第一次忘了停，埠與目錄被占住（已手動停掉自己的演練行程並清掉）。

## 未涵蓋
正式金鑰簽章／正式機真實資料形狀／正式機 Claude 權限分類器行為／真實標案網站（只在正式機以外不可驗）。
