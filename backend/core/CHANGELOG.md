# L0／L1 底層 更新紀錄

> 底層穩定契約（MODULE-GUIDE §2）：同一主版號內只准新增。版本＝`core.registry.CORE_VERSION`。

## 1.21 — 2026-09-26（P9 拖曳排版器，wip/h-p9；⚠ 暫用號：列車上依 origin 重定）〔core_bump：暫用 1.99 → 1.21〕
> 只有新增。
- L1（新增）：定義文件庫 `layout` kind 的驗證器與程式預設（`routers/definitions.py`）——key＝`module:<模組>`、body＝`{"ops": [...]}`；發布／還原前經 `core.catalog.check_layout`（P3 排版守門第一個產品呼叫者），問題路徑 `ops[i].…`；程式預設＝`{"ops": []}`（模組未載入 ⇒ 沒有預設）
- L1（新增）：端點 `GET /api/layout/{module}`——任何登入者讀自己角色的版面（`resolve`：角色 ＞ 公司 ＞ 程式預設）＋該模組的可自訂點；`?role=` 僅超級管理員（排版器的「以某角色預覽」）；現在不合法的已發布操作不套用、列在 `dropped`；讀定義失敗 ⇒ 程式預設＋`error`
- L1（新增，前端）：`static/custom-layout.js` 排版模型（`MotrixCustomLayout.pageModel／applyOps／compileOps／describeDiff／applyPersonal`）、`static/layout-runtime.js`（Alpine store `layout`：執行時套用＋個人層）、`static/layout-editor.js`（同頁編輯模式）

## 1.20 — 2026-09-26（P1／P3，wip/cloud-p1p3＋稽核修正 wip/x-p1p3-fix；⚠ 暫用號：列車上依 origin 重定）〔core_bump：暫用 1.8 → 1.15〕〔core_bump：暫用 1.15 → 1.20〕
> `core.registry.CORE_VERSION` 1.19 → 1.20（只有新增）。
- L0（新增）：`core.customization`——module.json 可自訂點（P3）：`SCHEMA_VERSIONS`／`PAGE_KINDS`／`OPS_*`／`EXPORT_FORMATS`、`OP_KEYS`／`MOVE_DEST_KINDS`、`validate_manifest(manifest)`、`require_valid(manifest)`、`core_fields(manifest)`、`endpoint_parts(spec)`。攤平與排版檢查是私有的（`_raw_points`、`_check_ops`），對外只經 `core.catalog`（稽核 P-M1）
- L0（行為，相容擴充）：`core.loader.load_all()` 載入前呼叫 `customization.require_valid`；`customization` 格式錯誤 ⇒ 模組不載入（state＝failed，reason 帶前三項問題位置）。沒有 `customization` 鍵 ⇒ 照常載入
- L1（新增）：`core.catalog`——能力目錄（P1）：`CATALOG_VERSION`、`EXPECTED_SECTIONS`、`register_section(name, owner, fn)`、`section(name)`、`build()`、`module_endpoints(spec)`、`endpoint_problems`、`output_problems`；同一區段兩個擁有者 ⇒ ValueError；**可自訂點唯一入口** `layout_points(module_key=None)`（藏起引用不存在端點／版型的點、選單去掉被藏起的按鈕、未載入模組沒有點）與排版守門 `check_layout(module_key, ops)`（每種操作限定鍵、move 限定容器、select_template 限定程式提供的版型）
- L1（新增）：端點 `GET /api/platform/catalog`（僅超級管理員，唯讀；`routers/platform_catalog.py`，並把 `helpers.doc_template` 登記成 `outputs` 區段）

## 1.19 — 2026-09-26（A，信件稽核修正 wip/a-mail-fix；列車取號）〔core_bump：暫用 1.99 → 1.19〕
- L1（新增）：`helpers.mail_types.MANAGED_ELSEWHERE`——收件人由別處維護、不在信件設定頁覆寫的類型（每月營運報表；稽核 M-S3）

## 1.18 — 2026-09-26（C）〔core_bump：暫用 1.99 → 1.14〕〔core_bump：暫用 1.14 → 1.18〕
> C（P8 前端缺口 #3～#7、P2 開票憑據稅別依據、P2 第二份單據勞務報酬單＋R3 個資告知）。
- L1（新增）：串接點 IP-10 `approval.queue_items`——「待我簽核」佇列與角標收其他模組的待簽項目（M01 取用；L1 自訂模組引擎提供 `custom_modules.queue_items`）；自訂模組通知的 ref_id＝`custom:<模組>:<單號>`（`notify_ref`）
- L1（新增）：`core.definitions.list_definitions`／`delete_draft`；API `GET /api/definitions/{kind}`、`DELETE /api/definitions/{kind}/{key}/draft`
- L1（新增）：`helpers.doc_template.BLOCK_SPECS`／`BLOCK_ITEM_SPECS`／`FORMATS`／`COLUMN_FORMATS`（建構器的積木參數規格）；積木 `doc_header`、`section_title`、`part`、`kv_table`、`footer_text`、`text_page`；`sign_boxes` 的 `variant: named`；格式 `ntd`；條件 `present`；主題可自帶外框（`frame`）與 `after_root`；主題 `payslip`
- L1（新增）：`helpers.custom_modules.ref_options`／`APPROVER_SOURCES`；API `GET /api/custom/{key}/ref-options/{field}`；能力目錄補積木規格、主題、輸出格式、欄位格式、簽核人來源；自訂模組與輸出版型預覽可 `?format=pdf`
- L1（行為）：開票申請憑據印出零稅率／免稅依據（R2）；勞務報酬單改由版型產生（`helpers/output_templates/payslip.json`，可覆寫與預覽），並加個資蒐集告知（R3：已告知印時間與人員，否則附告知事項全文）

## 1.17 — 2026-09-26（C，D7）〔core_bump：暫用 1.99 → 1.14〕〔core_bump：暫用 1.14 → 1.17〕
> C（D7 預演抓到的升級阻擋點）。
- L0（新增）：`core.upgrade.RUNTIME_STATE_SETTINGS`——啟動時就會更新的執行期狀態（每日掃描的節流日期）；`settings_changes` 只在值是日期且沒有往回走時放行，其他鍵照舊逐一比對。原本真實庫的舊日期會讓新版啟動後的驗證判定「改寫既有設定」⇒ 正式機升級被判失敗而回滾

## 1.16 — 2026-09-26（B）〔core_bump：暫用 1.11 → 1.14〕〔core_bump：暫用 1.14 → 1.16〕
> 階段 C／C3：選單由登錄表產生。只有新增。
- L1（新增）：`core.menu`——`load_l1`／`module_items`／`validate`／`visible`／`build`／`denied`／`MENU_L1`／`ITEM_KEYS`；資料 `core/menu_l1.json`（群組固定鍵＋L1 選單項）；模組以 module.json `pages[].menu` 宣告自己的選單項
- L1（新增）：端點 `GET /api/platform/menu`（`routers/platform_menu.py`）——目前使用者看得到的選單；C3 期間與 sidebar.js 舊選單並行，對等守門 `tests/platform/test_menu_parity.py`
- L1（新增）：`core.pages.L1_PAGES_FILE`／`load_l1_pages()`、資料 `core/l1_pages.json`；`collect(…, l1_pages=None)`（相容擴充）——模組宣告 L1 頁面一律算衝突（稽核 D P-M1）

## 1.15 — 2026-09-26（X-R）〔core_bump：暫用 1.10 → 1.12〕〔core_bump：暫用 1.12 → 1.15〕
> 稽核 AUDIT-D-R1-R3-legal 的修正（D-1、D-2、S-1～S-6、O-3、O-4）。暫用 1.10：合回時依 origin 取下一號。只有新增；行為修正列在下面。
- L1（新增）：`helpers.legal_params.round_half_up(amount, rate=1)`（四捨五入到元，補充保費）、`floor_amount(amount, rate=1)`（元以下捨去，扣繳）——法規金額捨入的唯一來源（IP-7 契約 1.2）；前端 `static/legal-round.js`（`MotrixLegalRound.halfUp／floor／taipeiToday`）
- L1（新增）：`helpers.legal_params.ARTICLE_8_ITEMS`／`ARTICLE_8_SOURCE`／`ARTICLE_8_DELETED`／`LEGACY_TAX_BASIS_LABELS`；`TAX_BASIS_OPTIONS["exempt"]` 改成 §8 第 1～32 款逐字（代碼 `8-N`），`8` 移出選項（只剩顯示用的舊標籤）；`/api/legal-params/tax-basis-options` 多 `sources`
- L1（新增）：`helpers.privacy_notice.AcksCorrupted`、`TEXTS_KEY`、`archive_text(conn, text)`、`text_for_hash(h)`；端點 `GET /api/legal-params/privacy-notice/texts/{hash}`；設定鍵 `privacy_notice_texts`
- L1（修改行為，介面不變）：`record_ack`／`get_ack` 讀不懂設定值 ⇒ `AcksCorrupted`（原本當成空的整份覆寫）；`record_ack` 新紀錄同時存告知全文；`privacy-notice.js` 告知書日期改台北時間
- 勞報單（M07，行為修正）：補充保費四捨五入（原為銀行家捨入）；`update_payslip` 讀、改、寫在同一個 `write_txn`；新單日期預設台北時間

## 1.14 — 2026-09-26（A，信件與通知收件設定；合回時 core_bump 取號）〔core_bump：暫用 1.99 → 1.13〕〔core_bump：暫用 1.13 → 1.14〕
- L1（新增）：`helpers.mail_types` 信件類型登記表——`register`／`get`／`all_types`／`keys`／`subject`／`CATEGORIES`／`GROUPS`／`MODES`／`ROLES`／`OVERRIDES_KEY`／`SUBJECT_PREFIX`／`MailType`；模組可在載入時登記自己的信件類型
- L1（新增）：`helpers.email_notify._group_emails(key)`（群組收件人，依登記表與覆寫）；`_admin_emails`／`_superadmin_emails` 改為它的相容名稱；`_lookup_emails`／`_department_manager_emails`／每月報表收件人套用覆寫；未登記 key fail closed（只寄超級管理員）
- L1（修改，相容）：`helpers.email_notify._build_html(mail_key, …, impact=None, action=None)`——第一個參數改為信件類型 key，內文固定「事由、影響、建議處理、發送時間與來源」；主旨一律 `mail_types.subject(key, 事由)`
- L1（新增）：端點 `/api/mail-types`（GET）、`/api/mail-types/{key}/recipients`（PUT）、`/api/mail-types/receivable`（GET）；頁面 `mail-settings.html`
- 修正：`helpers.geo.notify_quota_warning` 原本呼叫 `_send_raising(subject, body)` 少了收件人參數，執行即 TypeError（額度警戒信從未寄出）

## 1.13 — 2026-09-26（B）〔core_bump：暫用 1.10 → 1.12〕〔core_bump：暫用 1.12 → 1.13〕
> rebase 時 1.8、1.9 已被 X-9b、A 使用 ⇒ 1.10（PLAYBOOK §C-7）。只有新增。
- L1（新增）：`core.pages` 頁面對照與提供（階段 C／C1，STAGE-C-DESIGN §3）——`collect`／`build_page_map`／`lookup`／`resolve`／`page_response`／`notice_kind`／`notice_html`／`read_manifests`／`check_and_register`／`valid_name`／`PageConflict`／`PAGE_NAME`／`NOTICE`
- L0（新增）：`core.paths.FRONTEND_PAGES_DIR`
- 行為（main.py）：`GET|HEAD /pages/{name}` 由 `core.pages` 提供（StaticFiles 之前）——模組已載入 ⇒ 檔案；沒有載入 ⇒ **HTTP 404＋伺服器提示頁**（停用／未授權／失敗／未安裝，裁示 D2 選項 A，與 P-FE-03 並存）；頁面衝突比照 P-LD-07：在 `mount_modules` 之前檢查，後到的模組整個記 failed、不掛
- L0（新增）：`core.source_tree.FRONTEND_PAGES`／`page_file(name)`／`page_files()`——讀頁面原始碼的唯一入口（C2，頁面搬進模組資料夾後照樣找得到；守門 tests/platform/test_page_paths_centralized.py）

## 1.12 — 2026-09-26（A，獎金分潤）〔core_bump：暫用 1.10 → 1.12〕
- L1（新增）：`helpers.email_notify.notify_bonus_submitted`（獎金分潤輪到的簽核人＋代理人）、`notify_bonus_payout_ready`（核准待發放 → 出納）；信中不含金額。通知設定新增 `bonus_submitted`、`bonus_payout_ready` 兩個可個別關閉的事件（CORE-SPEC「使用者裁示」獎金分潤：通知）
- 串接點（新增，L2 之間）：IP-8 `bonus.payouts`（M07 → M05 出納）、IP-9 `expense.entries`（M07 → M08 報表）；U4 經 IP-7 `helpers.legal_params` 依撥付日選版，讀不到或欄位不齊 ⇒ 拒絕撥付

## 1.11 — 2026-09-26〔core_bump：暫用 1.99 → 1.11〕
> C（P4／P5 定義文件庫＋自訂欄位、P8 自訂模組引擎、A8d branding、S-CC07 N-1；原排 1.5，合回時 1.5～1.9 已被使用，依 §C-7 取下一號）。
- L1（新增）：公開端點 `/api/system/branding`（公司名稱／簡稱；統編只在帶有效登入時回，ROADMAP A8d）
- L1（新增）：`helpers.module_registry.register_key_source`／`dynamic_modules`／`known_keys`——動態權限 key 來源（已發布的自訂模組各一個 `custom.<key>`）；權限目錄與 `refuse_unknown_new_keys` 都認得；來源失敗 ⇒ 擋下新授權
- L1（行為）：備份清理 S-CC07 N-1——最新一份（今天以外）距今天超過 2 天（週／月層 2 個週期）⇒ 暫停清理、寫 `.prune_hold`、每輪告警
- L1（新增）：`core.definitions`——定義文件庫（CUSTOMIZATION-SPEC §3.5；P5 版面、P2 輸出版型覆寫、P4 自訂欄位、P8 自訂模組共用）：`save_draft`／`get`／`versions`／`publish`（先過驗證器，不過不發布並回帶位置的問題）／`restore`（不改歷史，再發布成新版）／`resolve`（role＞company＞程式預設）／`diff`（JSON 路徑）／`validate`、`register_validator`、`register_default`、`KINDS`、`DefinitionError`；表 `ui_definitions`（T1，每日 JSON 匯出，demo 清空）
- L1（新增）：`core.migrations`——每模組獨立版本的 migration 執行器（CORE-SPEC §6）：`register`／`registered`／`current_version`／`run_all`（版本須從 1 連續；每支跑完立刻記版本，中途失敗停在上一版）；`init_db` 在 `module_schema_versions` 之後執行；`core` v1＝`ui_definitions`。V9 基準 v116 不動
- L1（新增）：`helpers.custom_fields`——自訂欄位命名空間（P4，§3.6）：`validate_definition`（帶位置；不可與核心欄位同名）、`clean`（型別正規化、必填、預設值；未定義的鍵丟掉並回報）、`TYPES`／`DATA_CLASSES`／`KEY_RE`
- L1（新增）：`helpers.doc_template.problems()`（同 `validate`，每一項帶 JSON 路徑）；開票申請憑據輸出改依「單據凍結的版本＞公司最新發布版＞程式預設」套版，讀定義失敗 ⇒ 程式預設＋WARNING
- L1（新增）：API `/api/definitions/{kind}/{key}`（GET、`/draft` PUT、`/validate`、`/publish`、`/versions/{v}`、`/diff`、`/restore/{v}`、`/resolve`）、`/api/definitions/output_template/{key}/preview`（樣本資料預覽）；僅超級管理員
- L1（新增）：`helpers.formula`——安全公式（`check` 回錯誤位置、`evaluate`、`references`、`evaluation_order` 循環偵測；空值不等於 0、除以 0 回報；不允許屬性／索引／次方／其他函式）
- L1（新增）：`helpers.custom_modules`——自訂模組引擎（P8）：`validate_module`（欄位、公式、參照、流程可達性、簽核層與條件、輸出版型，每項帶位置）、文件式單據 `create_record`／`update_record`（只限起始狀態）／`transition`／`decide`（分層簽核沿用 `helpers.tiered_approval`，層可帶條件公式）／`get_record`／`list_records`／`render_output`／`rebuild_index`（欄位索引不匯出，從單據重建）；單據凍結在建立時的定義版本；通知與事件 `custom_module.transitioned` 在 commit 之後才送；個資（F2）欄位在分流接上前一律拒絕；`register_ref_target`
- L1（新增）：core migration v2——`custom_records`／`custom_record_values`（欄位索引）／`custom_record_counters`／`custom_record_log`（T1，每日 JSON 匯出，demo 清空）；API `/api/custom-modules`（清單、能力目錄、公式檢查、編號預覽、輸出預覽）與 `/api/custom/{key}/…`（單據 CRUD、轉換、核准／退回、輸出 HTML／PDF）；`pdf_gen.html_to_pdf_bytes()`
- L1（新增）：自訂模組單據讀取帶回該版定義（`definition`）；`GET /api/custom/{key}/meta?version=`

## 1.10 — 2026-09-26
> 主持（稽核 D 主持份 H-M1／H-S1／H-S2 與確認時的 N-1／N-2）。介面不變，只有行為。
- L1（修改行為，介面不變）：`core.events.publish` 給每個訂閱者 JSON 來回的完整副本（原本 `dict(payload)` 是淺拷貝，巢狀資料會被訂閱者改掉，發佈方的物件也會）；payload 必須是 JSON 可序列化、而且來回不變的值（tuple、非字串的鍵都算違約）；同一條執行緒還開著 `begin_write` 的寫交易時發佈也算違約（測試 raise、產品記 ERROR 照送）；訂閱者超過 0.2 秒記 WARNING
- L1（修改行為，介面不變）：`core.txn.begin_write` 的交易狀態多記一個 `thread`（給 core.events 判斷用）

## 1.9 — 2026-09-26
> A（STATES-PLATFORM §9 修正：路由衝突、停用清單讀不到、模組入口與提示頁、地圖、授權變更提示）。
- L0（新增）：`core.loader.mount_modules(app)`——在所有 L1 router 之後掛模組路由；模組任一條路由會被既有路由（L1 或先掛的模組）完整接住 ⇒ 該模組整個不掛、記 failed＋原因（P-LD-07）；以 starlette `route.matches()` 探測，FastAPI 新舊版（0.133／0.141）都成立；router 讀不出路徑 ⇒ 不掛；`main.py` 的模組排程與啟動提示移到它之後
- L0（新增）：`core.registry.unload(key, reason)`、`set_disabled_list()`／`disabled_list()`（snapshot／restore 一併涵蓋）；`core.loader.ALL`、`DISABLED_REASON`、`load_all(…, disabled_reason=…)`（全部停用＋原因）
- L1（新增）：`core.paths.modules_disabled_cache(db_path)`（主庫旁 `<db>.modules_disabled.json`，F4）；`helpers.module_switches.read_disabled_list()` → `DisabledList(keys, all_disabled, source, message)`：讀不到 ⇒ 有上限重試 ⇒ 沿用快取 ⇒ 沒有快取就全部停用（P-SW-05）；內容壞掉同樣處理（P-SW-07）；`set_enabled` 同步更新快取；`read_disabled_at_startup()` 保留（讀不到且沒有快取時改回所有模組資料夾名，不再回空集合）
- L1（新增）：API `/api/system/modules/availability`（登入即可，`{key: {state, label, name}}`，不回原因）側欄改用它；舊的 `/api/system/modules/unavailable-pages` 保留相容（同一主版號內不刪，列不出不在安裝包的模組，新程式不要用）；`/api/system/modules` 加 `disabledList`、各列 `licenseChanged`／`licenseNote`（P-SW-03）
- L1（修改行為）：地圖在標案雷達未載入時不列標案，`sources` 標 `module_not_loaded`（P-DT-01）

## 1.8 — 2026-09-26
> rebase 時 1.7 已被 R 使用 ⇒ 1.8。稽核 X-9b O-9（使用者表單裁示）與 STATES-DATA-OPS S-CU12。介面不變，只有行為。
- L1（修改行為，介面不變）：`archive._F2_FIELDS` 加 `協力廠商`（`vendor_contractors.data_json` 的戶名／帳號／存摺影像），`承攬付款憑據` 另加 `snapshot_json` 最上層同三鍵——協力廠商（承攬商本身）的帳戶一律當個資：一般每日／月 JSON 拿掉，完整列只進個資資料夾（O-9）
- L0（修改行為，介面不變）：`core.upgrade.CONFIG_FILES` 拿掉 `.build_commit` ⇒ 歸類成程式：轉換隨新版包安裝、兩種回滾還原成 V9 那一份；原本轉換後版本端點仍回 V9 的 commit（S-CU12）

## 1.7 — 2026-09-25（R）
> `core.registry.CORE_VERSION` 1.6 → 1.7（G1 快照要求升次版號；R 對 `core/registry.py` 只改這一行）。
- L1（新增）：`helpers.legal_params` 法規參數服務（R1，CUSTOMIZATION-SPEC §9.1）——`load_versions`／`save_versions`／`rules_for_date`／`rules_by_version`／`validate_version(s)`／`frozen_changes`／`year_status`／`minimum_wage_mismatch`／`today`；零稅率／免稅依據 `TAX_BASIS_OPTIONS`／`tax_basis_error`／`tax_basis_label`（R2，§9.2）
- L1（新增）：`helpers.privacy_notice` 個資蒐集告知（R3，§9.3）——`TEMPLATE`／`template_for`／`notice_text`／`current_notice`／`notice_hash`／`merge_ack`／`get_ack`／`record_ack`
- L1（新增）：端點 `/api/legal-params/tax-rules`（GET／PUT）、`/api/legal-params/tax-basis-options`、`/api/legal-params/privacy-notice`；頁面 `legal-params.html`；前端元件 `static/privacy-notice.js`
- L1（新增欄位）：`company_profile.privacy_notice`；設定鍵 `tax_rules_versions`、`privacy_notice_acks`

## 1.6 — 2026-09-25
> 稽核 X-9b（AUDIT-X-9b-upgrade-paths-pii.md）與 X-C-batch1 B-2 的修正。只有新增與相容擴充（選填參數）。
- L0（新增）：`core.upgrade.settings_changes()`——轉換後驗證與新版啟動後比對共用的設定判準（補空值不算改寫，含「鍵在、值是空字串」）（M-1、B-2）
- L0（新增）：`core.upgrade.data_changes()`；`rollback(..., info=None)`／`verify_rollback(..., info=None)`（相容擴充）——回滾只核對備份時就在的資料檔，新增的列成資訊、本機快照輪替不算失敗（M-2）
- L0（新增）：`core.upgrade.PACKAGE_DEFAULT_CONFIG`、`sync_package_default_config()`；`core.paths.AUTOSTART_BAT`——`autostart.bat` 歸類為設定，轉換保留機器版本；`verify_conversion` 另比設定檔（M-4）
- L0（新增）：`core.upgrade.check_backup()`——轉換與回滾動手前重驗備份（安裝根目錄、逐檔雜湊、試還原）（S-1）；`TOOL_LOG_NAMES`（試還原可重跑）、demo 庫 integrity、讀不了的庫列成問題（S-2、O-7）
- L0（新增）：`core.upgrade.table_digests()`、`logical_digest()`、`record_post_conversion()`、`changes_since_conversion()`、`has_changes()`、`POST_CONVERT_NAME`——「只准新增」驗內容；完整回滾前列出轉換後才寫入的資料；完整回滾以備份時原檔的邏輯內容驗收（S-3、O-1）
- L0（新增）：`core.upgrade.manifest_sha256()`（O-2）；`replace_program()` 回傳多 `removed_without_replacement`（S-7）
- L1（新增）：`archive.PiiFolderMissing`；個資資料夾只准往下逐層建（`os.mkdir`），根目錄不在 ⇒ 失敗並告警，不建回來（S-5）
- L1（行為）：`archive._F2_FIELDS` 加 `承攬付款憑據`（`snapshot_json.personnel[]` 的外包人員帳戶），一般份拿掉、完整列進個資資料夾；`merge_general_and_pii` 支援（M-3）
- CLI `tools/platform/upgrade.py`：驗證不過印建議回滾與指令（不自動回滾）；回滾後自動啟動 V9 ping、只印結果（`--ping-port`／`--no-ping`；exit 6／7）（CORE-SPEC §9b 主持裁示）

## 1.5 — 2026-09-25
> X9（AUDIT-X-9c 修正：A-2 守門不綁 L2 模組、A-3 授權檢查未啟用要看得到、B-1～B-4、C-4）。
- L0（新增）：`core.loader.MODULES_PACKAGE`；`load_all()` 的 `modules_dir`／`package` 沒給時讀**呼叫當下**的 `MODULES_DIR`／`MODULES_PACKAGE`（原本綁在預設參數上，子行程守門換不掉）
- L0（新增）：`core.loader.start_schedulers()`——啟動已載入模組的排程、回傳呼叫數；`main.py` 在排程閘門內改呼叫它（子行程守門驗同一條路）
- L0（新增）：`core.registry.set_state(…, note=…)`；狀態多一個 `note` 欄位（不是問題但要讓人看到的狀態，例：`授權檢查未啟用`）。`reason` 維持「非空＝有問題」；`/api/system/modules` 每列帶 `note`，模組管理頁顯示在狀態格＋頂端提示
- L1（修改行為，介面不變）：`helpers.licensing.module_licensed()` 的金鑰 `modules` 不是 `list[str]` ⇒ 未授權（原本字串會變成子字串比對）
- L1（修改行為，介面不變）：`helpers.module_switches.set_enabled()` 讀改寫在同一個 `BEGIN IMMEDIATE` 交易裡（同時切換不會互相蓋掉）

## 1.4 — 2026-09-25
- L1（新增）：`helpers.doc_template`——輸出引擎（P2，CUSTOMIZATION-SPEC §3.4）：`render(template, view, parts)`、`render_blocks`、`load_default(key)`、`validate(template, sample_view)`、`BLOCKS`（積木目錄 v1）、`THEMES`、`TemplateError`；預設版型 `helpers/output_templates/invoice_voucher.json`；`pdf_gen._build_invoice_voucher_html(v, template=None)` 可吃覆寫版型

## 1.3 — 2026-09-25
> C（A11／STATES／A8c 合回，G1 快照要求升次版號）。
- L1（新增）：串接點 IP-5 `daily_task.external`（M12 提供，M01 取用）、IP-6 `calendar.writeback`（M01／M03／M05 提供，L1 `helpers.google_calendar` 取用）；L1 行事曆不再直接寫 L2 表（ROADMAP A11）
- L1（新增）：`db.quick_check(path)`、`core.upgrade.quick_check(path)`；每日快照與啟動做完整性檢查；備份清理「至少保留最新 7 份」（`archive.PRUNE_KEEP_NEWEST`）；月備份同日重試＋上月缺漏告警；備份告警管道各自獨立、寄成功才節流（STATES-DATA-OPS S-CD02／CC07／CC06／CN03／CU10）
- L1（新增）：`helpers.company_identity.contact_line`／`footer_line`／`name_pair`／`short_name`（`pdf_gen._short_name` 改為引用它，唯一來源）；報表與網路規劃不再寫死公司聯絡資料（ROADMAP A8c）
- L1（新增）：`helpers.company_identity.contact_info_parts()`；公司名別名加 `name`、電話／email 以設定頁「聯絡方式」為最後後備（設定頁最上方欄位原本讀不到）
- L0（新增）：`core.upgrade.fill_company_profile_blanks()`／`V9_COMPANY_DEFAULTS`（轉換時只補空值、只補本公司安裝）；`archive.PRUNE_KEEP_NEWEST`

## 1.2 — 2026-09-25
> `core.registry.CORE_VERSION` 1.1 → 1.2 由 A 在 9c 分支一併修改（主持裁示）。
- L0（新增）：`core.upgrade`——V9 → 新版升級轉換與回滾（預檢／備份＋試還原比對雜湊／轉換只准新增／驗證／完整回滾與只回程式）；CLI `tools/platform/upgrade.py`、演練 `tools/platform/upgrade_drill.py`；操作手冊 `docs/platform/UPGRADE-RUNBOOK.md`（CORE-SPEC §9b）；安裝目錄以外的 `*_pdf_base_path` 只記摘要（檔案數／大小／mtime），驗證只比不變少，連不到＝警告
- L1（新增）：`core.events` 事件匯流排（P6，CUSTOMIZATION-SPEC §6）——`declare`／`publish`／`subscribe`／`declarations`／`recent_failures`；訂閱者隔離、給副本、契約檢查（測試嚴格、產品記 ERROR 照送）；`snapshot`／`restore` 供測試
- L0（新增）：`core.registry.snapshot()`／`restore()`——測試夾具保存與還原整份登錄表（不自己列舉內部表）
- L0（新增，CORE-SPEC §9c ②③）：`core.loader.load_all(license_check=…, disabled=…)`（優先順序：不在包內＞未授權＞管理者停用；②③ 都不 import 該模組）；`core.registry.set_state()`／`module_states()`／`STATES`（loaded／unlicensed／disabled／failed，附原因與頁面）
- L1（新增）：`helpers.licensing.module_licensed()`／`module_license_check()`（授權單位＝模組 `license_key`，`*` 全開；開關關閉＝不檢查）；`helpers.module_switches`（`system_settings.modules_disabled`，重啟後生效）；API `/api/system/modules`（superadmin）、`/api/system/modules/unavailable-pages`

## 1.1 — 2026-09-25
- L0（新增，MODULE-GUIDE §2 升次版號）：`core.registry.provide()`（尚未搬進 modules/ 的模組在匯入時登記提供者）、`single_provider()`（沒有 ⇒ None；多個 ⇒ RuntimeError）；首個串接點 IP-1 `dispatch.row`（INTEGRATION-POINTS.md）
- L0（修正，介面不變）：`core.source_tree.product_files()` 排除 backend 根目錄的 `conftest.py`（測試設定自 `tests/` 上移到 `backend/` 後，不可被當成產品碼掃描）

## 1.0 — 2026-09-25
- L0：模組載入器 `core.loader`、登錄表 `core.registry`（ModuleSpec／RuntimeSwitch／providers）、守門掃描範圍 `core.source_tree`（a150e52a）
- L1：寫入交易 `core.txn`（begin_write／write_txn／watch_reads）（7db88381）
- L1：路徑解析層 `core.paths`；主庫不存在即拒絕啟動，除非設 `MOTRIX_CREATE_NEW_DB=1`（bef3e25d、41151687）
- L1：V9 基準 v116 比對；`module_schema_versions`（c057832a）
- L1：資料列權限 `helpers.row_access`（ee5dab65、50e8c2cc、0411f818）
- L1：通知信旗標（`.no_email_send`／`MOTRIX_EMAIL_SEND`）（19fdae7e）
