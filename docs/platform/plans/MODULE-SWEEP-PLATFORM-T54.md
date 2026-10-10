# 模組框架化盤點 — 小模組與共用平台：daily_tasks／filehub／netplan／tender_radar／recyclebin／通知／登入安全／首頁／系統設定（第 54 班；盤點，不含實作）

> 規則來源與格式同 `MODULE-SWEEP-FINANCE-T54.md`。基準：`wip/t54-n39-settings-s0s2`。路徑：BE＝`backend/`、FE＝`frontend/`。
> 宿主縮寫：SR＝設定中心、M＝權限矩陣(F3)、S＝狀態／標籤(F5)、FP＝欄位政策(F7，僅設計)、D1＝顯示偏好(新)、**P9**＝**已存在**的版面框架（`frontend/static/layout-runtime.js`＋`module.json` 的 `customization`；角色＞公司＞程式預設再疊個人；目前只有 tender_radar 頁用到）、**MT**＝**已存在**的信件類型覆寫（`helpers/mail_types.py` OVERRIDES＋`helpers/notify_matrix.py`）、locked＝鎖定（附理由）。
> **範圍事實**：此分支沒有 recyclebin；它在 `wip/t52-ab-recyclebin-design`（設計稿 `RECYCLE-BIN-DESIGN-T52.md`）與 `wip/t53-ab-recyclebin-p0`（程式 `backend/modules/recyclebin/*`、`helpers/recycle_bin.py`、`frontend/pages/recycle-bin.html`）；RB 區行號出自 t53 分支。

## 1. daily_tasks（`BE/modules/daily_tasks/api.py`；頁 `FE/pages/daily-tasks.html`）
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 宿主 | 工 |
|---|---|---|---|---|---|---|---|
| DT01 | 誰能建立／改／刪任務 | 僅 superadmin（另需模組 daily_task 或 case_manage） | api.py:418,471,551 | 角色集合 {superadmin} | security | M | S |
| DT02 | 誰能回報完成 | 只有被指派者（superadmin 也不能代報） | api.py:824 | **使用者裁示（2026-10-10）**：設定選項「最高管理者可代報」，預設關（僅被指派者）；開啟後必填原因、留稽核、通知被指派者；開啟屬放寬（雙人核准＋待生效） | ops | SR＋M | M |
| DT03 | 誰能看任務 | superadmin 全部；其他＝被指派者或負責主管 | api.py:233-246,409 | 範圍選項（現行） | ops | M | M |
| DT04 | 匯出歷史 CSV 權限 | 被指派者或 superadmin；**主管不能匯出**（但能看歷史） | api.py:742 vs 591 | **使用者裁示（2026-10-10）**：設定選項「主管可匯出所管成員歷史」，預設允許；範圍限所管成員，每次匯出留稽核 | ops | SR＋M | S |
| DT05 | 週期類型 | once／weekly／range；weekly 至少一天；range 必填截止日 | api.py:424-431,473-480 | 啟用的週期類型集合（三種全開） | none | S | M |
| DT06 | 優先級集合與預設 | 一般／重要／緊急，預設一般；前端 option 寫死 | api.py:52,442；daily-tasks.html:2301-2303 | 值清單＋預設 | none | S | S |
| DT07 | 優先級顏色 | 緊急紅 #DC2626、重要琥珀 #D97706、一般藍 #2563EB 其他灰 | daily-tasks.html:3060-3066 | 色票 | none | S | S |
| DT08 | 分類欄 | 自由文字；看板以分類分欄，未填「未分類」 | api.py:51；daily-tasks.html:1459,1485 | 受控詞表（可選）＋是否允許自由輸入 | none | FP | M |
| DT09 | 星期標籤 | 「每週一二三…」；歷史／差異用「週一…週日」 | api.py:43,218,252,642 | 格式選項 | none | D1 | S |
| DT10 | 逾期檢查日 | 只檢查「昨天」；once＝任務日；weekly＝該星期；range 不進此檢查 | api.py:882,926-941 | 回溯天數 N（1）；是否納入 range | ops | SR | M |
| DT11 | 逾期檢查時間 | 每天 08:00，其餘由啟動補跑 | BE/helpers/daily_checks.py:52-57；api.py:1052-1078 | 時（8） | ops | SR | S |
| DT12 | 逾期通知對象 | 未完成者本人＋任務負責主管；另通知該成員部門主管 | api.py:951-969 | 收件對象集合（三者） | ops | MT | M |
| DT13 | 逾期通知頻率 | 每個逾期日只寄一次；補跑第一次只處理昨天 | api.py:885-889,1064-1067 | 開關／重複次數（一次） | ops | SR | M |
| DT14 | 區間任務到期提醒 | 到期前 3 天及當天；已完成者不提醒 | api.py:985,1003-1008 | 天數清單 [3,0] | ops | SR | S |
| DT15 | 區間任務「完成」定義 | 該人任一日完成即算完成 | api.py:223-225,998-1002 | 規則選項（現行） | none | S | M |
| DT16 | 區間任務行事曆同步 | 預設關；全員完成／刪除／改日自動對帳 | api.py:1023-1046 | 開關（關；已由 google_calendar 設定承載） | none | 現有 | S |
| DT17 | 指派通知 | 新增／新加入的被指派者：站內＋信件 | api.py:455-463,522-532 | 開關（開）＋MT | none | MT | S |
| DT18 | 編輯通知 | 有欄位差異才寫 edit_log、寄給負責主管；追蹤欄位 8 個 | api.py:261-294,511-542 | 追蹤欄位集合 | none | S | M |
| DT19 | 完成通知 | 完成才通知主管；可反覆改回報，無鎖 | api.py:843-867 | 開關；回報事後修改次數上限（無上限） | ops | SR | M |
| DT20 | 刪除語意 | 軟刪（is_deleted），無還原、無清除 | api.py:561-568,584 | 保存期限天數（永久） | legal | 接回收筒 | M |
| DT21 | 列表預設與上限 | 無篩選時 once＋range 最近 200 筆 | api.py:376-390 | 筆數（200）、排序 | none | D1 | S |
| DT22 | 歷史分頁 | 預設每頁 20、上限 100 | api.py:576,626,637 | 每頁筆數（20） | none | D1 | S |
| DT23 | CSV 匯出欄位與字樣 | 7 欄；「已完成／未完成」 | api.py:789,798 | 欄位集合／標籤 | none | D1 | S |
| DT24 | 超管解鎖密碼閘 | superadmin 進頁需另一組「每日工作事項密碼」；解鎖存 sessionStorage | BE/routers/auth.py:1825-1868；daily-tasks.html:2584 | 開關（開）、有效期（本分頁工作階段）；鬆綁走雙人核准 | security | SR | M |
| DT25 | 頁面顯示模式 | 週別／區間／單次卡片、日曆、看板、報告；頭像最多 4 人 | daily-tasks.html:1507,1565-1740 | 預設檢視、頭像數 | none | D1／P9 | M |
| DT26 | 外部來源任務 | 案件階段完成寫入：優先級一般、once、無主管 | api.py:1109,1113-1120 | — | — | locked（IP-5 契約，欄位只准加） | - |
| DT27 | 模組權限鍵 | 讀寫皆需 daily_task 或 case_manage | api.py:308 | — | — | locked（授權鍵） | - |

## 2. filehub（`BE/modules/filehub/api.py`；頁 `FE/pages/file-center.html`）
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 宿主 | 工 |
|---|---|---|---|---|---|---|---|
| FH01 | 全域瀏覽權限 | 無 quote_no 需 file_center 模組或 superadmin；有 quote_no（案件頁）任何登入者可呼叫，結果由各提供者按原權限過濾 | api.py:52-53 | 角色集合（現行） | security | M | S |
| FH02 | 每頁筆數 | 預設 50、上限 50 | api.py:50 | 預設每頁（上限鎖 50） | none | D1 | S |
| FH03 | 翻頁上限 | 最多第 20 頁、MAX_TAKE=1050 | api.py:27,54；`BE/helpers/attachment_search.py:25` | — | — | locked（效能護欄） | - |
| FH04 | 排序 | 上傳時間新→舊，再依檔名、fileId | api.py:72 | 排序選項 | none | D1 | S |
| FH05 | 預設日期範圍 | 進頁預設近 90 天 | file-center.html:160,101-102 | 天數（90） | none | D1／SR | S |
| FH06 | 副檔名快捷 | 全部／PDF／圖片 | file-center.html:89-93 | 快捷群組清單 | none | D1 | S |
| FH07 | 表格欄位 | 檔名／類別／單號／客戶案名／上傳者／上傳日／大小／操作 | file-center.html:107 | 欄位顯示與順序 | none | P9 | M |
| FH08 | 預期擁有模組 | case／supply／arap／subcontract／crm／accounting／payroll 七類；缺席明說 unavailable | api.py:29-30 | — | — | locked（與模組登記一致，防誤導） | - |
| FH09 | 結果項目鍵 | 固定 ITEM_KEYS，不含 path；開檔走 attachments/open | attachment_search.py:23 | — | security | locked（資安邊界） | - |
| FH10 | 隱藏不可見 | 看不到的不列、不回個數（防以 q 探測） | api.py（模組 docstring） | — | security | locked | - |
| FH11 | 開檔行為 | 圖片／PDF 新分頁；其他走預覽窗 | file-center.html:202-215 | 開啟方式 | none | D1 | S |
| FH12 | 篩選器集合 | q／類型／副檔名／日期／上傳者／案件號／單號／客戶 | api.py:48-50 | 顯示哪些篩選 | none | D1 | S |
| FH13 | 類別目錄 | 由各模組 attachments.catalog 的 CATEGORIES 決定 | api.py:61-75 | 類別中文標籤 | none | S | S |
| FH14 | 上傳單檔大小／數量 | 屬 uploads 群組 | BE/helpers/settings_groups.py:51-66 | 已有 | ops | 現有 | - |
| FH15 | 副檔名白名單 | 設定中心註明不可調 | settings_groups.py:62-65 | — | security | locked | - |

## 3. netplan（`BE/modules/netplan/*`；頁 `network-plans.html`、`network-plan-form.html`、`topology-quick.html`）
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 宿主 | 工 |
|---|---|---|---|---|---|---|---|
| NP01 | 規劃書狀態集合 | 規劃中／已確認／已交付；任意狀態間可切換（無順序檢查） | api.py:58,189,243 | 狀態清單＋允許轉換 | ops | S | M |
| NP02 | 狀態顏色與副標 | 規劃中 warning、已確認 orange、已交付 success；副標「尚未定案／待交付／已完成」 | network-plans.html:93-106,336-337 | 色票／副標 | none | S | S |
| NP03 | 誰能編輯 | superadmin／admin／netplan_edit；檢視 netplan／netplan_edit／case_manage | api.py:48,57,159；form.html:628-632 | 角色集合 | security | M | S |
| NP04 | 誰能刪除 | 僅 superadmin 且僅「規劃中」；硬刪，不進暫存區 | api.py:270-282 | 可刪狀態集合、角色 | ops | M＋S，接回收筒 | M |
| NP05 | 編輯鎖定（前後端不一致） | 前端：僅規劃中／已確認可編輯；**後端 PUT 不檢查狀態** | form.html:633-635 vs api.py:209-236 | **使用者裁示（2026-10-10）：維持現狀，只有畫面擋、後端不變**；不開選項 | ops | — | - |
| NP06 | 編號格式 | `NP`＋流水（next_entity_code） | api.py:179 | 前綴／位數 | none | F5 編號框架 | M |
| NP07 | 一案一份 | 同 quote_no 只能一份（唯一索引→409） | api.py:172-174,196-198 | — | none | locked（DB 完整性） | - |
| NP08 | 綁案可見性 | 沿用逐案權限；案模組不在則僅 admin 以上 | api.py:61-74 | — | security | locked（第 49 班使用者裁示） | - |
| NP09 | 樂觀鎖 | `_expectedUpdatedAt` 不符 409 | api.py:215-218 | — | — | locked | - |
| NP10 | 修訂紀錄自動寫入 | 狀態變更、Excel 匯入各 append 一筆 | api.py:184,253-257,389-393 | 哪些動作自動寫修訂 | none | S | S |
| NP11 | 列表上限與排序 | updated_at 降冪，LIMIT 300 | api.py:119-123 | 筆數、排序 | none | D1 | S |
| NP12 | 列表欄位 | 編號／案場／綁定案件／狀態／最後更新／更新人 | network-plans.html:138-143 | 欄位顯示 | none | D1 | S |
| NP13 | 狀態分頁 | 全部＋三狀態計數與比例條 | network-plans.html:83-113 | 預設分頁 | none | D1 | S |
| NP14 | 表單分頁集合 | 總覽、拓樸圖＋10 個資料表，與匯出 SECTIONS 一一對應 | form.html:476-625；export.py:33 | 啟用的分頁 | none | FP／P9 | L |
| NP15 | 各表欄位 | 欄位清單在 DATA_TABS；匯入以表頭文字比對 | form.html:476-625；export.py:33-110 | 欄位顯示／標籤（匯入比對鍵鎖） | none | FP | L |
| NP16 | 列狀態選項 | 規劃中／已完成／待確認（與規劃書三態不同詞彙） | form.html:488,502,523 | 值清單 | none | S | S |
| NP17 | 下拉選項集合 | 設備類別、DHCP／PoE 模式、防火牆動作、規則類型、埠介質、SSID 開關等 | form.html:494,516,547,568,575-576,585,604 | 值清單 | none | S | M |
| NP18 | 拓樸圖限制 | 銅纜埠≤96、SFP≤32、埠標籤 6 字、標題 40 字… | topology.py:38-43 | 數值 | none | SR | S |
| NP19 | 拓樸圖外觀 | 色票、格寬 54×40 | topology.py:28-54 | 色票／尺寸 | none | D1 | S |
| NP20 | 匯出規則 | Excel／PDF；分頁名不得含「／」；檔名樣式 | api.py:322,345；export.py:20-32 | 檔名樣式 | none | S（輸出範本框架） | M |
| NP21 | Excel 匯入 | 辨識的分頁整批覆蓋，未辨識略過附 warnings；需編輯權 | api.py:352-403 | 覆蓋／合併模式，預設覆蓋 | ops | SR | M |
| NP22 | 個資告知 | 聯絡人需勾「已告知」，不勾不擋存檔 | api.py:406-435 | 是否強制（不強制） | legal | SR | S |
| NP23 | 快速拓樸圖權限 | 兩支端點刻意不檢查模組，只需登入；資料存瀏覽器 | api.py:456-492 | — | — | locked（無狀態繪圖工具） | - |

## 4. tender_radar（`BE/modules/tender_radar/*`；頁 `tender-radar.html`）
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 宿主 | 工 |
|---|---|---|---|---|---|---|---|
| TR01 | 總開關 | 出貨預設關；環境變數 MOTRIX_TENDER_RADAR=1 才開（對外連線）；字面值有守門測試 | source.py:76,79-98 | 布林（關）；風險欄須待生效，保留環境變數 | security | SR（requires_pending） | M |
| TR02 | 抓取時段 | 預設 9,12,15,18 時；空＝不抓 | source.py:140,1332-1365 | 時段清單 | ops | SR | S |
| TR03 | 寄信時段 | 預設 18 時；空＝不寄 | source.py:141,1397,1434 | 時段清單 | ops | SR | S |
| TR04 | 高頻確認門檻 | 超過 12 個時段要先確認 | source.py:153；api.py:406-423 | 整數 12 | none | SR | S |
| TR05 | 純記錄期 | 首次成功掃描起 7 天只抓不寄 | source.py:132-133 | 天數 7 | ops | SR | S |
| TR06 | 不寄信日 | 週六日＋國定假日不寄（補班日可寄） | source.py:1100-1104；calendar_tw.py | 規則集合 | ops | SR | M |
| TR07 | 假日表到期警告 | 涵蓋範圍最後一天起 60 天內記警告 | source.py:1107-1117 | 天數 60 | ops | SR | S |
| TR08 | 詳細頁每日上限／間隔 | 每日 20 筆、間隔 2 秒 | source.py:161-162 | 整數 20、秒 2；上限須夾住（對政府網站承諾） | legal | SR（max 夾住） | S |
| TR09 | 來源網站請求 | URL、User-Agent、逾時 15 秒、pageSize=100、每日一次承諾 | source.py:97-103,706-710 | — | legal | locked（對外承諾；逾時可 SR） | - |
| TR10 | 疑似改版判定 | 丟棄筆數 > 總數/2 ⇒ source_changed 告警 | source.py:441-450 | 比例 0.5 | ops | SR | S |
| TR11 | 日期合理性 | 與今天差超過 5 年視為壞資料 | source.py:115,271 | 年數 5 | none | SR | S |
| TR12 | 告警邊緣觸發 | 進入異常才寄一次，每天最多一封 | source.py:125-127,1097,1164；notify.py:152-210 | 重送政策 | ops | SR | M |
| TR13 | 驗證碼處置 | 偵測驗證碼即停抓詳細頁，隔天再試，不破解 | source.py:122-123 | — | legal | locked（法遵／倫理邊界） | - |
| TR14 | 異體字對照 | 僅「臺→台」 | match.py:43-45 | 對照表可擴充 | none | S（詞表） | S |
| TR15 | 比對規則 | 關鍵字任一命中於「名稱＋機關」；排除詞優先；機關完全相等；無預算標案而條件有金額⇒不命中 | match.py:78-110 | 比對模式（任一／全部、機關完全／包含）；無預算處置 | ops | SR（choices） | M |
| TR16 | 搜尋條件必填 | 名稱必填；至少一個關鍵字；預算不可負 | api.py:112-115,60-75 | — | — | locked（避免命中全部） | - |
| TR17 | 清單範圍與排序 | 顯示所有標案；截止日升冪、無截止日最後 | listing.py:118-121 | 預設排序／篩選 | none | D1 | S |
| TR18 | 清單欄位 | 標註／機關／案號／名稱… | module.json customization.lists；tender-radar.html:418-436 | 欄位顯示順序 | none | **P9 已承載** | - |
| TR19 | 搜尋條件欄位 | 名稱／狀態／關鍵字／排除詞／機關／預算 | module.json；tender-radar.html:332-339 | 欄位顯示 | none | **P9 已承載** | - |
| TR20 | 標註共享 | 一人標全員可見；任何有模組者可取消 | api.py:560-615 | 取消權限 | ops | M | S |
| TR21 | 模組權限 | 全部端點需 tender_radar 模組 | api.py:35-45 | — | — | locked | - |
| TR22 | 信件彙總 | 每日一封；信內最多 50 筆；「七日內截止」計數 | notify.py:84,90 | 筆數 50、臨近天數 7 | none | SR | S |
| TR23 | 信件類型登記 | tender_found（admins）；其餘 3 種 system 僅 superadmins | notify.py:12-24 | 收件人覆寫（已有） | ops | MT | - |
| TR24 | 無搜尋條件時 | 寄「未經篩選」清單並提醒設定排除詞 | notify.py:103-111 | 寄／不寄 | ops | SR | S |
| TR25 | 快取與暖機 | 回應預先計算、啟動 20 秒暖機、快取 64 | listing.py:35-37 | — | — | locked（效能內部） | - |
| TR26 | 測試重設端點 | 僅 MOTRIX_TENDER_RADAR=1 才有路由 | api.py:515-543 | — | security | locked | - |

## 5. recyclebin（僅在 `wip/t53-ab-recyclebin-p0`）
| id | 名稱 | 現況 | file:line（t53 分支） | 選項→預設 | 風險 | 宿主 | 工 |
|---|---|---|---|---|---|---|---|
| RB01 | 保存天數 | 固定 30 天，**使用者裁示 D4「不可設定」** | helpers/recycle_bin.py:39；service.py:33 | 若要開放須使用者重新裁示 | legal | locked（裁示）；候選 SR（下限 7？） | S |
| RB02 | 誰能看／還原／永久刪 | 全部端點 require_superadmin | api.py:26 | 角色集合 {superadmin} | security | M | S |
| RB03 | 永久刪二次確認 | `confirm=PURGE_CONFIRM` 否則 422 | api.py:109-113 | — | security | locked（防誤刪） | - |
| RB04 | 「刪除已核可」入口 | superadmin 專用，需 confirm＋輸入單據編號 | api.py:132-141 | 是否開放、確認句型 | money | SR＋M | M |
| RB05 | 快照大小上限 | 一般 5 MB、admin 50 MB；超過拒絕進暫存區 | helpers/recycle_bin.py:40-41；service.py:63 | 整數 MB | ops | SR | S |
| RB06 | 清除批次 | 每次最多 200 筆；凌晨 3 點後第一個週期跑 | service.py:24；jobs.py:20,77 | 批量、時 | ops | SR | S |
| RB07 | 容量告警 | 隔離區超 5 GB 告警，不提前清除 | service.py:23 | GB 5 | ops | SR | S |
| RB08 | 隔離目錄 | 預設 `<安裝根>\資源回收筒`，可設定（recyclebin_dir） | quarantine.py:23-31；api.py:173 | 路徑 | ops | 已有設定鍵 | S |
| RB09 | 敏感欄位遮罩 | 快照存原文，列表／詳情只回遮罩，深度≤6 | helpers/recycle_bin.py:44-48 | 遮罩欄位規則 | security | locked（個資）＋規則表 | M |
| RB10 | 還原狀態集 | in_bin／restored／purged／restore_failed | service.py:22 | — | — | locked（狀態機） | - |
| RB11 | 通知 | 還原／永久刪／刪已核可通知 superadmin；每日彙總 | api.py:35-40,101,123,156；jobs.py:67 | 收件人／開關 | ops | MT | S |
| RB12 | 列表分頁與篩選 | 預設狀態 in_bin、每頁 50 | api.py:42；recycle-bin.html:76-85 | 每頁筆數 | none | D1 | S |
| RB13 | 列表欄位 | 類型／單號名稱／刪除者／刪除時間／剩餘天數／附件／狀態／操作 | recycle-bin.html:85 | 欄位顯示 | none | P9 | S |
| RB14 | 納入刪除範圍 | adapter 登記制；現行「只有草稿能刪」不放寬；對方 adapter 不在⇒走舊硬刪並稽核註明 | RECYCLE-BIN-DESIGN §2.3,§5 D1 | 實體類型清單（第 1 期 10 類） | money | S | L |
| RB15 | 附件隔離 | os.replace 搬到隔離目錄，唯一直接刪檔處 | quarantine.py:10,25 | — | — | locked（資料完整性） | - |
| RB16 | 本分支內的刪除現況 | netplan 硬刪、daily_tasks 軟刪（無清除）、tender watches 硬刪；皆未接暫存區 | netplan/api.py:281；daily_tasks/api.py:561 | 接 adapter | legal | 接回收筒 | M |

## 6. 共用：通知與信件類型
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 宿主 | 工 |
|---|---|---|---|---|---|---|---|
| NT01 | 信件類別與預設收件群組 | 類別 業務／簽核／系統；群組 none／admins／superadmins／finance；系統類強制只 superadmins | BE/helpers/mail_types.py:25-30,57-60 | 覆寫模式（已有） | security | MT | - |
| NT02 | 不可關閉的信件 | backup_error／backup_stale／disk_space_low／cert_expiry／company_setup_alert／system_test_mail | notify_matrix.py:37-44 | — | security | locked（營運安全） | - |
| NT03 | 關信需確認的類別 | 關簽核類／系統類要確認警告 | notify_matrix.py（MAIL_OFF_CONFIRM_CATEGORIES） | 類別集合 | ops | MT | S |
| NT04 | 個人退訂 | users.notification_muted opt-out；只能退訂自己收得到的 | BE/helpers/notification_prefs.py:1-60 | — | none | locked（語意） | - |
| NT05 | 站內通知保留 | 90 天 | BE/helpers/audit.py:165-193 | 已在設定中心 | ops | 現有 | - |
| NT06 | 簽核催辦階段 | 工作日第 1、3、5 天，之後每 5 天；只排除週六日不排國定假日 | BE/helpers/system_checks.py:~500-526,596 | 階段清單 [1,3,5]、步距 5、是否排除國定假日（否） | ops | SR | M |
| NT07 | 催辦來源單據 | 報價單、匯款申請、開票申請憑據、出貨單、請款單 5 張表寫死 | system_checks.py:~470-500 | 納入的單據集合 | ops | S | M |
| NT08 | 保固到期預警 | 剩 30 天、7 天各一次；信件 ≤7 天紅 | modules/case/case_deadlines.py:218,248-251；email_notify.py:1538-1539 | 天數清單 [30,7]（與 C22 同一項） | ops | SR | S |
| NT09 | 憑證到期預警 | 手簽憑證門檻 0/7/21/60 天；ACME 0/1/7/21；過期後每 7 天重寄 | system_checks.py:50-52,141 | 兩組天數 | security | SR（下限＋risk） | S |
| NT10 | 備份停滯門檻 | 36 小時 | system_checks.py:~183 | 小時 36 | ops | SR | S |
| NT11 | 磁碟空間門檻 | 剩 <10% 且 <50 GB 才告警 | system_checks.py:184-189 | %、GB | ops | SR | S |
| NT12 | 測試暫存膨脹 | >20 GB 告警 | system_checks.py:194 | GB 20 | none | SR | S |
| NT13 | 每日檢查時刻 | 啟動補跑＋每日 08:00 | BE/helpers/daily_checks.py:52-75 | 時 8 | ops | SR | S |
| NT14 | 寄信逾時與等待 | SMTP 逾時 15 秒（附件 60）；寄送等待 45 秒；預設 smtp_port 587 | email_notify.py:382,415,1768；system.py:2532 | 秒數 | none | SR | S |
| NT15 | 主旨前綴 | 非正式機加「【開發機測試】」；正式「【MOTRIX 系統通知】」 | email_notify.py:161；mail_types.py:36 | — | none | locked（防誤認） | - |
| NT16 | 每月營運報表收件人 | 設定頁維護，儲存過一次後以名單為準 | mail_types.py:33；notification-settings.html:337-346 | 已有 | none | 現有 | - |
| NT17 | 行事曆×信件對照 | EVENT_LINKS 寫死；行事曆預設關 | notify_matrix.py:~47-65 | 已有雙勾選 | none | MT | - |
| NT18 | 通知文字 | 站內通知句型寫死 | daily_tasks/api.py:964；email_notify.py 各 notify_* | 文案範本 | none | S（輸出範本） | L |
| NT19 | 站內通知跳轉與樣式 | delete／reject 紅、payment.mark 琥珀、auth.login 灰；相對時間 | FE/static/notif.js:538-553 | D1 | none | D1 | S |
| NT20 | 兩個提醒橫幅 | 待簽核、兩步驟驗證提醒；7～9 秒淡出；待簽數 60 秒快取 | notif.js:253,297,558-635 | 開關／停留秒數 | none | D1 | S |
| NT21 | 收件人解析 | 沒登記的 key ⇒ ERROR＋只寄 superadmin（fail closed） | mail_types.py:15-17 | — | security | locked | - |
| NT22 | 通知設定頁收件人說明 | 「admin／superadmin 且有 Email」自動讀取 | notification-settings.html:311-316 | 與 NT01 合併 | none | MT | S |

## 7. 共用：登入、工作階段、密碼安全政策（放寬皆走雙人核准＋待生效；收緊立即生效）
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 宿主 | 工 |
|---|---|---|---|---|---|---|---|
| AU01 | 登入失敗鎖定 | 同 IP 連續 5 次失敗鎖 900 秒，寫 DB 可跨重啟 | BE/routers/auth.py:42-43,118-128 | 次數 5、秒 900 | security | SR（loosen） | S |
| AU02 | 鎖定維度 | 以來源 IP（X-Forwarded-For 第一段），非帳號 | auth.py:51-55 | 維度選項（IP） | security | locked（需設計） | - |
| AU03 | 閒置逾時 | 一般角色 8 小時；admin／superadmin 2 小時 | BE/main.py:212,217,559-575 | 小時 8／2，各角色一格 | security | SR（loosen） | S |
| AU04 | 工作階段絕對效期 | 登入後 30 天；demo 1 天 | auth.py:539,439 | 天數 30 | security | SR | S |
| AU05 | 活動時間節流 | last_active 超過 300 秒才寫 | main.py:577,~275 | — | none | locked（統計與效能） | - |
| AU06 | 最短密碼長度 | 8 碼；套用於改密碼、建立／重設使用者、解鎖密碼、每日任務密碼 | BE/helpers/auth.py:54；auth.py:1454,1519,1632,1799,1848 | 整數 8（下限程式內鎖） | security | SR（loosen 需雙人） | S |
| AU07 | 弱密碼判定 | 長度、舊弱密碼表、固定 4 組黑名單 | helpers/auth.py:109-117 | 詞表可增不可減 | security | SR | M |
| AU08 | 改密碼後行為 | 清除其他 session；不得與舊密碼相同 | auth.py:1456-1466 | 開關（登出其他裝置：開） | security | SR | S |
| AU09 | 強制改密碼白名單 | must_change_password=1 時僅放行 5 支 API | main.py:218-224 | — | security | locked | - |
| AU10 | 兩步驟(TOTP)挑戰 | 密碼通過後 300 秒內輸入；錯 5 次作廢 | auth.py:148-149,608-609 | 秒 300、次 5 | security | SR | S |
| AU11 | 兩步驟是否強制 | 今日僅提醒橫幅，不強制 | notif.js:297 | 強制範圍（無／superadmin／admin） | security | SR（新）＋M | M |
| AU12 | QR 登入核准 | challenge 走 header 不走網址 | auth.py:641-667,498-518 | — | security | locked | - |
| AU13 | Passkey 總開關 | 常數 PASSKEY_ENABLED=False，端點 404；挑戰 TTL 600 秒 | helpers/auth.py:60-83；auth.py:951 | 布林（關） | security | SR（risk security） | S |
| AU14 | 密碼雜湊 | PBKDF2-SHA256 260000 次 | helpers/auth.py:88-105 | — | security | locked（密碼學參數） | - |
| AU15 | 角色集合 | superadmin／admin／sales／engineer／viewer／finance | mail_types.py:31；module_versions.py:13 | — | security | locked（核心授權模型） | - |
| AU16 | 財務／出納權限 | 由角色推導；模式 off 則退回 has_finance_access | helpers/auth.py:372-386 | 模式（已有 _finance_mode） | money | M | M |
| AU17 | 模組權限判定 | superadmin 一律放行；其他看 users.modules JSON | helpers/auth.py:379-386 | 權限矩陣 | security | M | L |
| AU18 | 解鎖密碼 | 僅 superadmin 可設；規則同密碼政策 | auth.py:1797-1823 | 同 AU06 | security | SR | S |
| AU19 | 刪使用者／停用時 | 刪除其全部 session | auth.py:1703 | — | security | locked | - |
| AU20 | 初始帳號 | 全新安裝寫一次性憑證檔 | helpers/auth.py:120-140；auth.py:425-460 | — | security | locked | - |
| AU21 | 稽核保存 | audit_log_keep_days 1825，下限 365 | settings_groups.py:~35 | 已有 | legal | 現有 | - |
| AU22 | 操作軌跡保留 | request_log 90 天 | settings_groups.py:~46 | 已有 | ops | 現有 | - |

## 8. 共用：儀表板／首頁（`FE/index.html`；`BE/modules/analytics/api/dashboard.py`）
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 宿主 | 工 |
|---|---|---|---|---|---|---|---|
| HM01 | 首頁進入條件 | canDash＝superadmin／admin／finance／quotation／dashboard 任一 | FE/index.html:19-24 | 角色／模組集合 | security | M | S |
| HM02 | 問候語時段 | <5 晚安、<11 早安、<18 午安 | index.html:893-899 | 時段分界 | none | D1 | S |
| HM03 | 報價追蹤門檻 | 已送出且無 deal_tag，滿 14 天列入「待追蹤」 | dashboard.py:584 | 天數 14（與 ANA-04 同一項） | ops | SR | S |
| HM04 | 報價即將失效 | 有效天數預設 30，剩 1–3 天提醒 | dashboard.py:579-581,594 | 預設有效天數、提醒天數（與 Q1／ANA-04 同源） | money | SR | S |
| HM05 | 洽談中案件停滯 | 洽談中且 updated_at 滿 30 天 | dashboard.py:644,654 | 天數 30（與 CRM-02 同源） | ops | SR | S |
| HM06 | 出貨單卡關 | 待審核／簽核中且更新滿 5 天 | dashboard.py:668,693 | 天數 5（與 ANA-06 同一項） | ops | SR | S |
| HM07 | 保固預警視窗 | 後端 ≤90 天；前端顯示 0–30 天 | dashboard.py:152,239；index.html:624,1198 | 天數 90／30（與 ANA-01 同一項） | ops | SR | S |
| HM08 | 動態牆 | 預設 limit=8（API 30／上限 100）；各來源 LIMIT 40；篩選 7 組 | dashboard.py:801,842-978；index.html:561,859-868,1165 | 筆數、篩選群組 | none | D1 | S |
| HM09 | 動態牆來源權限 | 依角色／模組過濾，來源 7 類 | dashboard.py:809-812 | — | security | locked（行級權限） | - |
| HM10 | 卡片截斷數 | 待追蹤報價、停滯開發、卡關出貨各顯示 4 筆 | index.html:663,695,724 | 顯示筆數 4 | none | D1 | S |
| HM11 | 首頁區塊顯示 | KPI 格、Hero 一句話總結、運營警示三塊 | index.html:473-510 | 區塊開關／順序 | none | D1 | M |
| HM12 | 成交判定 | deal_tag 屬 已成案／已結案為贏，未成案為輸 | dashboard.py:336,563-606 | 標籤集合（與 ANA-07 同一項） | money | S | M |
| HM13 | 待簽核狀態集 | 報價單 待審核／簽核中 | dashboard.py:44,98 | 狀態集合 | money | S | S |
| HM14 | 財務摘要可見性 | 毛利、結算、應收摘要需 admin／財務模組且 can_see_financial | dashboard.py:61 | 角色集合 | money | M | S |
| HM15 | 部門篩選 | 首頁可依部門過濾動態牆 | index.html:1165 | — | none | D1 | S |
| HM16 | 金額顯示格式 | ≥1,000,000 顯示 `NT$ x.xxM`，≥1,000 顯示 `NT$ nnnK` | index.html:1185-1186 | 格式選項（D2） | none | D1 | S |
| HM17 | 營運分析缺席提示 | 模組不在顯示「—」並明說，不假裝 0 | index.html:504-510 | — | none | locked（缺席不可偽裝 0） | - |

## 9. 共用：系統設定頁
| id | 名稱 | 現況 | file:line | 選項→預設 | 風險 | 宿主 | 工 |
|---|---|---|---|---|---|---|---|
| SS01 | 設定中心可見性 | 全部端點 superadmin；寫入需 reason；風險欄待生效（可撤銷），放寬需另一位最高管理者核准 | BE/routers/settings_center.py:1-60；settings_registry.py:29,47-60 | — | security | locked（框架本體） | - |
| SS02 | 已登錄群組 | 僅 retention（8 欄）、uploads（3 欄） | settings_groups.py:16-66 | 逐步擴充（本盤點的 SR 項） | ops | SR | - |
| SS03 | 設定快取 | 15 秒行程內快取；`MOTRIX_SETTINGS_DEFAULTS_ONLY=1` 逃生口 | settings_registry.py:28 | — | — | locked | - |
| SS04 | 模組管理頁權限 | module_versions 需 admin 以上 | BE/routers/module_versions.py:13-19 | 角色集合 | security | M | S |
| SS05 | 系統設定頁誰能進 | 各設定頁權限散落在各 router | 各 settings 頁 | 統一入口與角色 | security | M | M |
| SS06 | SMTP 預設 | port 587 | system.py:2532；notification-settings.html:283,398 | 預設值 | none | SR | S |
| SS07 | 角色顯示名 | 寫死於頁面（mail-settings 與 daily-tasks 各一份 roleCn） | mail-settings.html:150；daily-tasks.html:3069 | 角色顯示名（集中） | none | S | S |
| SS08 | 設定頁分組與選單 | 設定中心 menu_l1 order 75 | core/menu_l1.json | 選單順序 | none | D1 | S |
| SS09 | 公司資料閘門 | 未設定公司資料時多數 API 回 428；72 小時暫時放行 | BE/main.py:226-262 | 暫時放行時數 72 | legal | SR（risk legal） | S |
| SS10 | 主題 | localStorage `motrix_theme` | 各頁 head | — | none | D1（已有） | - |
| SS11 | 列表偏好 | list_prefs 僅存排序，不含欄位／頁大小 | BE/routers/list_prefs.py:21-26 | 擴充 D1 欄位偏好 | none | D1 | M |
| SS12 | 預設組 | 設定中心預設組套用／預覽 | settings_center.py:10 | 已有 | ops | SR | - |

## 10. 注意事項
1. **版面框架 P9 已存在**（tender_radar 在用），daily_tasks／filehub／netplan 的 `customization.pages` 都是空的；欄位顯示類（D1）不需新機制，只要這三模組補登記。這修正了報價／案件範疇文件「需新建 D1」的前提：**D1 的欄位顯示與順序應優先走 P9，D1 新儲存只補 `list_prefs` 缺的欄位／頁大小／預設分頁**。（待下一版範疇文件對照修正。）
2. **前後端不一致三處已由使用者裁示（2026-10-10，見 `SWEEP-USER-QUESTIONS-T54.md`）**：NP05 維持現狀；DT04 做成設定、預設允許；DT02 做成設定、預設僅被指派者。
3. 信件與通知已有半套宿主 MT；天數／小時／百分比門檻（NT06–NT14、HM03–HM07、DT10–DT14）仍是常數，適合進 SR；安全項（AU01／03／04／06）依框架規定走 `loosen`＋待生效＋雙人核准。
4. 同一個數字在多處重複出現（保固 90／30、報價追蹤 14、停滯 30、卡關 5）：HM03／HM05／HM06／HM07 與 ANA、CRM、NT08/C22 是**同一項**，登錄時只建一個設定、各處引用。
5. recyclebin 保存 30 天是使用者裁示 D4「固定不可設定」，放進 SR 前必須重新裁示。行號已讀驗證，唯 `system_checks.py`（約 470–530）、`notify_matrix.py`（約 47–65）、`settings_groups.py`（約 35／46）、`main.py`（約 275）為近似；部分 locked 項（FH03／09／10、TR09／13、AU14）屬資安／法遵／對外承諾邊界，建議維持不開放。
