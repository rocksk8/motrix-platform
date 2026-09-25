# 模組化路線圖（第一階段）

> 依據：DEPENDENCY-MAP.md（相依）、CORE-SPEC.md（裁示）。每一步完成的定義＝該步驟的測試通過＋反向控制（拆掉後其餘照常）。
> 順序原則：先切逆向依賴（L1→L2），再拆耦合最少的 L2；跨多檔的工作在各自 worktree 做。

## 階段 R：法規與參考設計（BENCHMARK.md §7；D8）

> 「法規必要」的項目全部要做；「強烈建議」的項目這一輪能做就做。需要公司政策或外部帳號的，列在 RUN-PLAN §4（U4～U9）。

| # | 項目 | 依據 | 負責 | 狀態 |
|---|---|---|---|---|
| R1 | 法規參數依**生效日**版本化（L1 法規參數服務）：勞報單扣繳、補充保費門檻、最低工資；舊單沿用建立時的版本；跨年前提示「新年度規則未設定」；加守門「兼職補充保費門檻＝當年最低工資」 | 扣繳率標準、健保署簡表、勞動部 | 子代理 | ⏳ |
| R2 | 零稅率、免稅必填依據或附件 | 營業稅法 §7、§8 | 子代理 | ⏳ |
| R3 | 個資蒐集告知：公司設定頁提供告知文字範本，承攬商與勞報單表單列印或勾選 | 個資法 §8 | 子代理 | ⏳ |
| R4 | 簽核積木：同層 `sequential／all／any`、條件分流（與 P8 公式共用安全運算式）、退回上一關或指定關、逾時通知組織鏈的上一層（走 P6） | NUEiP、Ragic、EasyFlow | A（P1／P3 之後） | ⏳ |
| R5 | 開票時限提醒：收款期別到期而沒有發票 ⇒ 進待辦並提醒 | 營業稅法 §32 | A（併入 A8b） | ⏳ |
| R6 | 單據轉傳票統一「預覽→產生」與科目對應記憶 | 鼎新 A1 | A（M06 搬遷時） | ⏳ |
| R7 | 跨模組待辦中心、簽核佇列／單據檢視／案件看板三頁的行動版、批次核准（同類型、低於門檻）、自動存檔抽成 L1 元件 | 使用者體驗、NUEiP | 主持＋B（階段 C） | ⏳ |
| R8 | 欄位層權限：可自訂點帶權限屬性，排版器與匯出都要遵守 | Ragic、NUEiP | C（P3／P4／P5） | ⏳ |
| R9 | 補充保費捨位規則：查到官方規則後，統一改成 `round_half_up` | 程式不一致 | 待官方依據 | ⏳ |

## 階段 P：自訂與獨立升級的底層串接點（CUSTOMIZATION-SPEC §5；2026-09-25 使用者核心方向）

> 與階段 A／B 並行：模組搬遷時要順手登記進能力目錄、描述可自訂點。每一項開工前先把規格細節寫進 CUSTOMIZATION-SPEC。

| # | 項目 | 依賴 | 狀態 |
|---|---|---|---|
| P1 | 能力目錄（擴充 §7 端點登錄表：端點、provider、輸出、事件、欄位型別，都帶契約版本）＋ `GET /api/platform/catalog` | — | ⏳ |
| P2 | 輸出引擎版型化（PDF／Excel 由版型定義＋資料產生）；先把一種單據改成版型化，並做位元組比對 | P1 | 🔄 C：第一種（開票申請憑據）✅ 逐位元組相同；其餘 7 種 PDF 與 Excel 版型待辦 |
| P3 | module.json 描述可自訂點（欄位、動作、列表欄位、輸出）＋守門 | P1 | ⏳ |
| P4 | 內建模組的 `customFields{}` 命名空間，送審時凍結 | P3 | ⏳ |
| P5 | 版面定義的儲存與套用（公司、角色、個人三層；有版本、可還原） | P3 | ⏳ |
| P6 | 事件匯流排（publish／subscribe；沒有訂閱者＝正常） | — | ⏳ |
| P7 | 模組更新包：單一模組打包、套用、回滾（儀表板接上） | 9c① | ✅ 工具與守門 B（module_update.py）；⏳ 儀表板串接（主持） |
| 9c①b | 產品演練自動跑「該組合的測試」（目前 product_drill 只做端點煙霧測試，組合測試手動在 worktree 跑；稽核 P-2） | 9c① | ⏳ |
| P7b | 模組自有 migration 的套用與回滾（P7 目前遇到 migrations/ 一律拒絕） | P7 | ⏳ |
| P8 | 自訂模組引擎（文件式儲存、通用 API、流程、輸出）與建構介面 | P1～P6 | ⏳ 第二階段 |
| P9 | 拖曳排版器（選單、列表、表單、按鈕、匯出、輸出版型） | P3、P5 | ⏳ 第二階段 |

## 階段 A：L1 清乾淨（逆向依賴歸零）

| # | 項目 | 來源 | 狀態 |
|---|---|---|---|
| A1 | 寫鎖下沉 `core/txn.py` | §0-4 | ✅ 7db88381 |
| A2 | 紅點常數改取 module_registry | §3 #4 | ✅ 7cdec57b |
| A3 | 案件／業務開發案可見性 → `helpers/row_access.py` | §3 #2 #3 #5 #6 | ✅ 50e8c2cc／0411f818 |
| A4 | 路徑解析層 `core/paths.py` | DATA-COMPAT | ✅ bef3e25d／41151687 |
| A5 | `pdf_gen` 的完工單樣板搬回 M01，L1 只留引擎 | §3 #1 | ✅ 4ba73907 |
| A6 | `recognition`／reports／vouchers 的 `_dispatch_row` → M04 公開連接器 | §3 #7 #8 #9 | 🔄 A |
| A7 | `bonus_vouchers` → M06「建立傳票草稿」連接器 | §3 #18 #19 | ⏳ |
| A8 | Excel 樣式與匯出速率限制下沉 L1 輸出（`helpers/xlsx_out.py`）；`_COMPANY` → company_identity；`PART_CATEGORIES` → `helpers/part_catalog.py` | §3 #10 #12 #13 #17 | ✅ C |
| A8b | 待辦：`_collect_tax_invoices`（→ M05 連接器）、`_collect_income_items`（→ M05 連接器）——資料擁有權，A8 未動 | §3 #11 #14 | ⏳ |
| A8c | 寫死的公司聯絡資料 `reports._COMPANY2`、`network_plan_export._COMPANY2` 與頁尾 → company_identity（`contact_line`／`footer_line`／`name_pair`／`short_name`） | A8 發現 | ✅ C |
| A8d | 待辦（A8c 盤點發現，不在 A8c 範圍）。🔴 **第一項（高，安全）**：`helpers/auth.py:29` 預設解鎖密碼含統編（可被推測）；其餘：前端寫死的公司名／統編（`frontend/index.html:827-828`、`pages/login.html:203,303`）；`helpers/startup.py:112,130` 初始帳號種子寫死特定人員 email；設定頁 placeholder 用本公司資料 | A8c 發現 | ⏳ |
| A9 | system 指名 L2（tender／bonus／quote_terms）→ 模組登錄表 | §3 #26 #27 #28 | 🔄 tender 已完成；bonus、quote_terms 尚未 |
| A10 | 案件聚合（vouchers_by_case、list_dispatches、list_shipping_notes）→ L1「案件關聯資料提供者」 | §3 #20–22 | ⏳ |
| A11 | google_calendar、case_stage_tasks 跨領域寫入 → 連接器 IP-5 `daily_task.external`、IP-6 `calendar.writeback` | §3.1 | ✅ C（L1 行事曆仍直接讀 5 張表，見 IP-6「尚未處理」） |
| A12 | 共用表直寫（stock_items、vouchers_all、dev_cases、system_settings、user_request_log）→ 擁有者連接器 | §4 | ⏳ |

## 階段 B：L2 逐一搬進 `modules/<key>/`

建議順序，理由是阻擋它的逆向依賴或共用表最少：

1. M11 標案雷達 — ✅ 後端完成；剩地圖 provider（等 M08）與前端頁面
2. M12 每日任務 — 需要 A11（case_stage_tasks）與 §4 的 system_settings、user_request_log
3. M10 網路規劃 — 依賴 M01 的路由前綴，需要 A10
4. M02 業務開發 — 需要 A3、§4 的 dev_cases
5. M04 外包工班 — 需要 A6
6. M05 應收應付 — 需要 A6、A8
7. M06 會計 — 需要 A7、A8
8. M07 薪資獎金 — 需要 A7、A9
9. M03 採購庫存出貨 — 需要 §4 的 stock_items
10. M08 分析（唯讀）— 改走各模組的讀取連接器；地圖 provider
11. M01 案件 — 最後搬，此時其他模組已不依賴它的內部實作

## 階段 G：準則的守門（MODULE-GUIDE 標「⚠ 未守門」的項目）

| # | 守門 | 狀態 |
|---|---|---|
| G1 | L1 公開介面快照：介面一有變動就紅，要求同時升 `CORE_VERSION` 並寫 `core/CHANGELOG.md` | ✅ B（test_l1_interface_snapshot.py） |
| G1b | G1 守不到的三項：L1 函式的回傳形狀、L1 router 的 HTTP 端點、L1 資料表欄位 | ⏳ |
| G2 | 每個模組都要有 `README.md`、`CHANGELOG.md`、`module.json` 的 `data` 與 `license_key`；CHANGELOG 最上面的版號＝`module.json` 的 version | ✅ B（test_module_package_files.py） |
| G3 | `module.json` 的 data 分類與備份匯出清單、表分類守門一致（T1 必須匯出、T3 不匯出、F2 不進一般鏡像） | ✅ B（test_module_data_classes.py） |
| G3b | T2 的祕密欄位確實從每日匯出排除（依 module.json 宣告） | ⏳ |
| G4 | 模組程式有改動，但 CHANGELOG 或版號沒更新 ⇒ 紅（依 git 歷史：版號條目要寫在最後一次程式改動之後） | ✅ B（test_module_changelog_follows_code.py） |
| G5 | 版本紀錄頁改由各模組 CHANGELOG 彙整產生；`version_manifest.json` 退場 | ⏳ |
| G6 | 勞報單（F2）上雲：獨立、權限更窄的資料夾 | ⏳ C（A8 之後） |

## 階段 S：系統狀態的處理（STATES 目錄）

> C 的目錄：`docs/platform/states/STATES-DATA-OPS.md`（資料／升級／部署／備份／通知，編號 S-C…）。A 的目錄（模組平台，編號 S-P…）由 A 合回時併入本節。
> 高且缺守門的項目先補（C：S-CD02、S-CC07、S-CC06、S-CN03、S-CU10；主持：S-CU01、S-CU06、S-CP01、S-CP02）；每一項註明 V9 是否同樣受影響，V9 修不修由使用者決定。

| # | 狀態 | 嚴重度 | 目前守門 | 狀態 |
|---|---|---|---|---|
| S-CU01 | WinRM 連線**掛住不回**（非斷線） | 高 | 缺 | 🔄 主持修、C 稽核 |
| S-CU02 | WinRM **斷線** | 中 | 缺 | ⏳ |
| S-CU03 | 儀表板重啟後輪詢不停 | 低 | 缺 | ⏳ |
| S-CU04 | 轉換中途斷電／磁碟滿（程式換到一半） | 中 | 缺（R2 未入測試） | ⏳ |
| S-CU05 | 備份中途失敗 | 低 | `test_backup_refuses_non_empty_dir` | ⏳ |
| S-CU06 | 精靈的備份時間戳隨頁面重整改變 | 高 | 缺 | 🔄 主持修、C 稽核 |
| S-CU07 | 回滾本身失敗（檔案被鎖） | 中 | 缺（R3 未入測試） | ⏳ |
| S-CU08 | 同一時間戳重跑、步驟亂序 | 中 | 缺 | ⏳ |
| S-CU09 | 預檢的磁碟判斷不足 | 中 | `test_preflight_rejects_low_disk`（只涵蓋 DB×3） | ⏳ |
| S-CU10 | **預檢放行損毀主庫** | 高 | 缺 | ✅ C（V9 同樣受影響：否） |
| S-CU11 | 正式機 PATH 上沒有 python | 中 | 缺 | ⏳ |
| S-CU12 | 升級後版本號仍顯示舊的 | 中 | 缺 | ⏳ |
| S-CU13 | 轉換後還能按「啟動服務」而驗證沒過 | 中 | 缺 | ⏳ |
| S-CC01 | 服務啟動時雲端碟還沒掛上 | 低 | 缺（「先未掛、後掛上」無測試） | ⏳ |
| S-CC02 | 碟符 G: → H: | 低 | `test_verdict_cache_is_keyed_by_archive_path` | ⏳ |
| S-CC03 | `系統存檔_個資` 被刪或改名 | 中 | `test_alert_is_edge_triggered` | ⏳ |
| S-CC04 | 個資資料夾權限被改寬 | 中 | 缺（無法自動） | ⏳ |
| S-CC05 | 雲端空間滿／單張表寫入失敗 | 中 | `test_partial_backup_failure_is_not_reported_as_ok`（只驗不報 ok） | ⏳ |
| S-CC06 | **月底最後一天月備份失敗** | 高 | 缺 | ✅ C（V9 同樣受影響：是） |
| S-CC07 | **系統時鐘往前跳** | 高 | 缺 | ✅ C（V9 同樣受影響：是） |
| S-CC08 | 系統時鐘倒退 | 中 | 缺 | ⏳ |
| S-CC09 | 兩台機器同一天寫雲端 | 低 | `test_archive_ownership_2026_09_14` 全檔、`test_unreadable_marker_fails_open` | ⏳ |
| S-CC10 | 排程工作與程式內排程同時跑備份 | 中 | 缺 | ⏳ |
| S-CC11 | 快照時本機碟滿 | 中 | `test_low_disk_alerts`（快照時碟滿：缺） | ⏳ |
| S-CC12 | 週備份時雲端不可用 | 低 | 缺 | ⏳ |
| S-CC13 | S3 後端的個資資料 | 低 | `test_object_storage_backend_does_not_upload_and_alerts` | ⏳ |
| S-CD01 | 主庫不存在 | 低 | `test_require_db_*` | ⏳ |
| S-CD02 | **主庫部分損毀仍啟動** | 高 | 缺 | ✅ C（V9 同樣受影響：是） |
| S-CD03 | WAL／SHM 殘留 | 低 | 缺（R6 未入測試） | ⏳ |
| S-CD04 | schema 比基準新 | 低 | `test_newer_than_baseline_is_refused`、`test_preflight_rejects_running_service_and_newer_schema` | ⏳ |
| S-CD05 | database is locked | 低 | `test_u9_a_locked_or_broken_database_raises_instead_of_reporting_zero` | ⏳ |
| S-CD06 | demo 庫損毀使正式服務起不來 | 中 | 缺 | ⏳ |
| S-CD07 | migration 中途失敗 | 低 | `test_u10_every_migration_can_be_run_twice`（中途失敗：缺） | ⏳ |
| S-CP01 | **部署／回滾結束時 NameError，歷史不寫** | 高 | 缺 | 🔄 主持修、C 稽核 |
| S-CP02 | **D1 健康檢查假綠燈** | 高 | 缺（`test_each_problem_blocks` 未涵蓋） | 🔄 主持修、C 稽核 |
| S-CP03 | 部署包不完整 | 中 | 缺 | ⏳ |
| S-CP04 | 部署包 SHA 與全量紀錄不符 | 中 | `test_build_blocked_when_full_is_for_another_commit`（部署端：缺） | ⏳ |
| S-CP05 | 開發機標記被帶上正式機 | 低 | 升級端 `test_preflight_each_check_can_fail`；打包端：缺 | ⏳ |
| S-CP06 | 人工放行留痕誤觸「上次失敗」 | 低 | 缺 | ⏳ |
| S-CN01 | SMTP 未設定 | 中 | 雷達：`test_n16_smtp_not_configured_does_not_mark`；設定頁狀態：缺 | ⏳ |
| S-CN02 | SMTP 寄送失敗 | 低 | `test_notify_marks_only_on_success_2026_09_22` | ⏳ |
| S-CN03 | **告警本身發不出去（告警的告警）** | 高 | 缺（只有新鮮度那一路的 `test_the_daily_guard_is_not_burned_when_the_alert_fails`） | ✅ C（V9 同樣受影響：是） |
| S-CN04 | 收件人查詢失敗與「沒有收件人」無法分辨 | 中 | 缺 | ⏳ |
| S-CN05 | heartbeat 的 ping_url 未設 | 中 | 缺 | ⏳ |
| S-CN06 | 正式機殘留 `.no_email_send` | 中 | `test_email_send_policy`（系統頁顯示：缺） | ⏳ |
| S-CN07 | 備份告警 WARN 等級不寄信且被下一輪清掉 | 中 | 缺 | ⏳ |

## 階段 C：前端跟著模組走（第二階段的前置）

- 模組頁面搬進 `modules/<key>/pages/`，由載入器掛載靜態路徑
- sidebar 選單改由登錄表產生（模組沒裝就不出現）
- 端點登錄表 `GET /api/platform/endpoints`（CORE-SPEC §7）
