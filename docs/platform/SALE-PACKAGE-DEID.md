# 販售包去識別化——盤點與設計（H2 線，2026-09-28 19:04）

> 依據：CORE-SPEC 裁示表「販售包去識別化」（d6f196d7）與「本公司設定閘門的裁示（E4 Q1～Q6）」（Q5 併入本案；Q1 預設 LOGO／favicon 維持現狀＝例外）。
> 流程：本文件是「盤點＋設計」，交 D 審；審過再實作。**本文件不改產品碼。**
>
> 🔴 **本文件不含任何實際識別值**（公司名、統編、電話、email／網域、地址、座標、人員姓名、內網 IP、開發者代號、客戶／供應商名稱）。
> 一律寫「第 N 行含 ○○類字串」；需要舉例時用虛構值（例：`範例整合股份有限公司`、`02-0000-0000`、`user@example.com`）。
> 本文件自己也會進 repo（且在目前的包裡會隨 `docs/platform/**` 出貨），寫完已用 §1.1 的掃描器掃過本檔：0 命中。

## 0. 結論

| 項目 | 結論 |
|---|---|
| 盤點對象 | 最近一次完整包（full，549 檔）。逐檔分類＋兩層偵測（已知識別值清單、樣式規則），結果只記「路徑＋行號＋類別」。 |
| 有風險的檔 | **103 檔**／**本公司識別 49 行、人員 24 行、開發者代號 42 行、客戶／供應商 2 行、內網位址 28 行、開發環境路徑 225 行**（§1.3）。 |
| 資料層 | 已乾淨：包內沒有 .db、沒有 demo 存檔、`company_profile` 種子與 `DEFAULT_IDENTITY` 全空、範本（`output_templates/*.json`、`doc_template.py`、`voucher_template.py`）與種子（`migrations_frozen/`、`backend/data/`）0 命中。 |
| 最大的洞 | ①`docs/platform/**` 141 檔整包出貨（稽核報告、RUN-LOG、演練報告），且現行守門 `test_no_our_company_literals` **不掃 .md**；②`version_manifest.json` 425 筆內文全數隨包（含本公司聯絡資料、人員姓名、供應商名稱、81 筆提到正式機現況），頁面只是不顯示，檔案與 `module_versions` 表裡都在；③產品碼裡登記為 `ALLOWED` 的例外（凍結 migration、本公司升級回填、安全黑名單、演練資料）**全部照樣出貨**——登記解決的是「CI 不紅」，不是「包裡沒有」。 |
| 設計主軸 | 建包分兩種對象 `-Audience sale|own`（預設 sale）。sale：①建包後依 `sale` 清單剪掉內部文件、version_manifest 改投影 ②掃描守門（金鑰雜湊清單＋樣式規則）命中即拒絕 ③正對照（金絲雀）沒被抓到也拒絕。own：不剪不擋，只記錄，且只能套在 E4 認定為本公司的安裝。 |

## 1. 盤點

### 1.1 方法

- 對象：t17 演練建出的完整包（commit 3e061d6f、product=full、549 檔；唯讀）。
- 分類規則（依路徑）：`程式`（.py／.js）、`頁面`（frontend/pages、index.html、.css）、`種子／凍結 migration`（`backend/migrations_frozen/`、`backend/data/`）、`範本`（`output_templates`、`doc_template.py`、`voucher_template.py`）、`version_manifest`、`隨包文件`（.md／.txt、`docs/**`）、`工具／部署腳本`（.ps1／.bat／.vbs、`tools/`、`backend/tools/`、`backend/scripts/`）、`設定預設值／清單`（.json、.ini、.gitignore、.gitattributes、.build_commit、requirements.txt）、`二進位／第三方`（字型、圖片、`static/vendor/`，不掃文字）。demo 資料／demo 存檔：**包內 0 檔**（`.db`、`backend/_demo_*` 皆未追蹤，demo 庫每次登入由 `reset_demo_db()`＋`init_db()` 產生，內容＝種子）。
- 偵測器（掃描腳本與識別值清單放本 session 暫存區，**不進 repo**）：
  - **已知值**：本公司名（中／英／簡稱）、統編、新舊電話、email 網域、地址片段、座標、人員姓名、預設管理員帳號名、開發者代號、一家已知供應商名。比對前正規化（NFKC、轉小寫、去空白與 `-_.,:;|/()` 等分隔）。
  - **樣式**：email、台灣電話、8 碼且**檢查碼正確**的統編、`…股份有限公司／有限公司／企業社／工程行／商行`、門牌地址、帳號＋10～18 碼數字、私有 IP（172.16/12、192.168/16、10/8）、開發環境路徑（`X:\Users…`、`X:\MOTRIX…`、`G:\…`）。
  - 樣式命中再分三類：比對到**虛構清單**（`12345678`、`02-0000-0000`、`example.com`、`範例…` 等）＝虛構；人工確認非識別值＝誤判；其餘＝風險。
- ⚠ 工具陷阱（本輪實際踩到，列為 §3 正對照的理由）：Git Bash 的 `grep -i -F` 在此機 locale 下**對已知存在的字串回 0 筆**，改 `LC_ALL=C` 才正常。若沒有先讓「已知的那一個」亮起來，就會報「沒有」。

### 1.2 分類統計

| 檔案類別 | 檔數 | 有風險的檔 | 判斷 |
|---|---|---|---|
| 程式 | 191 | 17 | 本公司識別集中在 `core/upgrade.py`、`db.py`、`helpers/auth.py`（皆為 `ALLOWED` 登記過的例外，但會出貨）；人員＝預設管理員帳號名的相容邏輯與註解裡的開發者代號 |
| 隨包文件 | 168 | 65 | `docs/platform/**` 141 檔是內部開發紀錄，幾乎每份稽核報告開頭都有開發機路徑；另有本公司識別與人員 |
| 頁面 | 64 | 3 | placeholder 多數已是虛構值；風險：註解裡的開發者代號 1 處、通知設定頁內網 IP 2 處、儲存位置頁雲端硬碟路徑範例 3 處 |
| 工具／部署腳本 | 50 | 15 | 內網 IP（防火牆、HTTPS、passkey 腳本）、演練資料（本公司識別）、自動啟動腳本的路徑 |
| 設定預設值／清單 | 32 | 2 | `.gitattributes` 註解含網域；`deploy_manifest.json` 記了開發機直譯器路徑 |
| version_manifest | 1 | 1 | 425 筆；本公司識別 5 行、人員 2、開發者代號 3、客戶／供應商 2、內網 IP 4；另 81 筆提到正式機現況、31 筆「使用者回報／告知」（案件內容類敘述，規則偵測不到，只能靠投影處理，§2.3） |
| 種子／凍結 migration | 10 | 0 | 選型資料庫種子（公開產品規格）與會計科目表；無識別值 |
| 範本 | 4 | 0 | 無 |
| 二進位／第三方 | 29 | — | 不掃文字。`static/logo.png`、`logo-white.png`、`favicon.png` 圖中含本公司英文名＝**Q1 例外**（使用者裁示維持現狀，登記在 `_our_company_literals.KEPT_DEFAULT_IMAGES`）；字型與 vendor 以上游雜湊固定即可 |
| **合計** | **549** | **103** | |

依偵測類別（行數）：

| 檔案類別 | 本公司識別 | 人員 | 開發者代號 | 客戶／供應商 | 內網位址 | 開發環境路徑 | 虛構 | 誤判 |
|---|---|---|---|---|---|---|---|---|
| 程式 | 28 | 15 | 9 | | 6 | 1 | 6 | 5 |
| 隨包文件 | 11 | 7 | 26 | | 5 | 203 | 5 | 8 |
| 頁面 | | | 1 | | 2 | 3 | 22 | 8 |
| 工具／部署腳本 | 4 | | 3 | | 11 | 16 | 1 | 1 |
| 設定預設值／清單 | 1 | | | | | 1 | | |
| version_manifest | 5 | 2 | 3 | 2 | 4 | 1 | | 1 |
| **合計** | **49** | **24** | **42** | **2** | **28** | **225** | **34** | **23** |

誤判 23 行：8 碼毫秒常數、commit 雜湊、UUID 片段、裝飾器字串形似 email、稽核文件裡的虛構地址與虛構工程行。

### 1.3 位置清單（路徑：行號；括號＝檔案類別）

**本公司識別**

- `.gitattributes`（設定預設值／清單）：180
- `DR-SOP.md`（隨包文件）：127
- `backend/core/upgrade.py`（程式）：648, 649, 650, 651, 654, 655, 656, 657, 658, 686
- `backend/db.py`（程式）：768, 1062, 4719, 4724, 4726, 4727, 4738, 4746, 4763, 4789
- `backend/helpers/auth.py`（程式）：44
- `backend/version_manifest.json`（version_manifest）：749, 1512, 1519, 2051
- `docs/platform/audit/AUDIT-D-H-branding.md`（隨包文件）：35
- `docs/platform/audit/AUDIT-X-9b-upgrade-paths-pii.md`（隨包文件）：75
- `docs/platform/audit/AUDIT-X-C-batch1.md`（隨包文件）：116, 136, 176
- `tools/platform/upgrade_drill.py`（工具／部署腳本）：96, 97

**人員**

- `backend/core/CHANGELOG.md`（隨包文件）：64, 66
- `backend/db.py`（程式）：1034, 1035, 1062, 4894
- `backend/helpers/auth.py`（程式）：123, 127
- `backend/helpers/startup.py`（程式）：113, 115, 117, 127, 154, 156, 195, 216
- `backend/routers/auth.py`（程式）：1646
- `backend/version_manifest.json`（version_manifest）：1442, 1820
- `docs/platform/IMPROVEMENT-REPORT.md`（隨包文件）：103
- `docs/platform/ROADMAP.md`（隨包文件）：55
- `docs/platform/RUN-PLAN.md`（隨包文件）：212
- `docs/platform/audit/AUDIT-D-H-branding.md`（隨包文件）：16, 29

**人員（開發者代號）**

- `backend/db.py`（程式）：4445
- `backend/helpers/financial_mask.py`（程式）：21
- `backend/modules/analytics/api/dashboard.py`（程式）：352
- `backend/modules/case/api/case_extra_expenses.py`（程式）：379
- `backend/modules/case/api/material_orders.py`（程式）：169
- `backend/modules/case/api/quotations.py`（程式）：2193
- `backend/modules/case/quotations.py`（程式）：64
- `backend/modules/case/recognition.py`（程式）：4
- `backend/setup_backup_task.ps1`（工具／部署腳本）：8
- `backend/version_manifest.json`（version_manifest）：1981, 1995, 2030
- `docs/platform/D7-CHECKLIST.md`（隨包文件）：12, 47
- `docs/platform/FINAL-DRILL-REPORT.md`（隨包文件）：8, 502
- `docs/platform/PLAYBOOK.md`（隨包文件）：266
- `docs/platform/PROD-UPGRADE-RESULT-20260927.md`（隨包文件）：3
- `docs/platform/RETROSPECTIVE.md`（隨包文件）：45, 79
- `docs/platform/RUN-LOG.md`（隨包文件）：69, 76, 102, 105, 109, 116, 237
- `docs/platform/RUN-PLAN.md`（隨包文件）：4, 29, 61, 63, 95, 104, 177, 179, 188
- `docs/platform/audit/AUDIT-A-B41-payreq.md`（隨包文件）：45
- `docs/platform/audit/AUDIT-D-host-P6-voucher-rollback.md`（隨包文件）：102
- `frontend/js/case-management-core.js`（程式）：529
- `frontend/pages/approval-queue.html`（頁面）：1655
- `tools/platform/final_drill.py`（工具／部署腳本）：4, 46

**客戶／供應商**

- `backend/version_manifest.json`（version_manifest）：1442, 1722

**內網位址**

- `DR-SOP.md`（隨包文件）：121
- `HTTPS-DEPLOY-CHECKLIST.md`（隨包文件）：26, 35, 37, 45
- `backend/helpers/email_notify.py`（程式）：157
- `backend/main.py`（程式）：64, 69, 83
- `backend/routers/system.py`（程式）：1581, 2110
- `backend/tools/fetch_root_ca.ps1`（工具／部署腳本）：29
- `backend/tools/https_setup.ps1`（工具／部署腳本）：18, 23, 24, 43
- `backend/tools/setup_passkey_client.ps1`（工具／部署腳本）：20, 27
- `backend/version_manifest.json`（version_manifest）：1680, 1820, 1827
- `firewall_setup.bat`（工具／部署腳本）：20, 21, 28, 29
- `frontend/pages/notification-settings.html`（頁面）：294, 402

**開發環境路徑**

- `DEPLOY.md`（隨包文件）：87
- `DR-SOP.md`（隨包文件）：4
- `HTTPS-DEPLOY-CHECKLIST.md`（隨包文件）：9, 24
- `backend/autostart.bat`（工具／部署腳本）：19, 20, 23, 31, 32
- `backend/autostart_hidden.vbs`（工具／部署腳本）：2
- `backend/helpers/storage_locations.py`（程式）：181
- `backend/setup_autostart_task.ps1`（工具／部署腳本）：11
- `backend/setup_heartbeat_task.ps1`（工具／部署腳本）：13, 21
- `backend/tools/apply_update.ps1`（工具／部署腳本）：70
- `backend/tools/delivery.py`（工具／部署腳本）：42
- `backend/tools/rollback_update.ps1`（工具／部署腳本）：31
- `backend/tools/verify_package.py`（工具／部署腳本）：612
- `backend/version_manifest.json`（version_manifest）：1253
- `deploy_manifest.json`（設定預設值／清單）：38
- `docs/platform/D7-CHECKLIST.md`（隨包文件）：48, 49, 50
- `docs/platform/FINAL-DRILL-REPORT.md`（隨包文件）：1, 5, 6, 8, 9, 10, 32, 38, 64, 95, 127, 161 …（共 26 行）
- `docs/platform/IMPROVEMENT-REPORT.md`（隨包文件）：155, 198
- `docs/platform/PLAYBOOK.md`（隨包文件）：204, 276, 286
- `docs/platform/PROD-UPGRADE-RESULT-20260927.md`（隨包文件）：22, 23, 24, 25
- `docs/platform/RUN-LOG.md`（隨包文件）：5, 59, 67, 154, 185, 251, 252, 253
- `docs/platform/RUN-PLAN.md`（隨包文件）：29, 30, 158, 165, 166, 167, 173, 174, 175, 178, 181, 189 …（共 22 行）
- `docs/platform/audit/AUDIT-A-H12-apply.md`（隨包文件）：203
- `docs/platform/audit/AUDIT-B-host-O7.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-C-B-guards.md`（隨包文件）：16
- `docs/platform/audit/AUDIT-C-host-D3D5.md`（隨包文件）：6
- `docs/platform/audit/AUDIT-D-A-M10-M12.md`（隨包文件）：6
- `docs/platform/audit/AUDIT-D-A-M12-move.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-A-approval-parse.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-A-bonus-U4.md`（隨包文件）：6
- `docs/platform/audit/AUDIT-D-A-mail-settings.md`（隨包文件）：4, 5, 33
- `docs/platform/audit/AUDIT-D-B-C1-pages.md`（隨包文件）：5, 34
- `docs/platform/audit/AUDIT-D-B-D1b-scope.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-B-G1.md`（隨包文件）：6
- `docs/platform/audit/AUDIT-D-B-env-guards.md`（隨包文件）：10
- `docs/platform/audit/AUDIT-D-B-maps.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-B-o5-s1.md`（隨包文件）：9
- `docs/platform/audit/AUDIT-D-B-o6.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-B-rebasecheck.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-B41-payreq.md`（隨包文件）：66, 67, 68
- `docs/platform/audit/AUDIT-D-B54-warm-async.md`（隨包文件）：61
- `docs/platform/audit/AUDIT-D-C-D7-drill.md`（隨包文件）：5, 34
- `docs/platform/audit/AUDIT-D-C-M02-move.md`（隨包文件）：6
- `docs/platform/audit/AUDIT-D-C-M04-move.md`（隨包文件）：7
- `docs/platform/audit/AUDIT-D-C-M05-move.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-C-M07-move.md`（隨包文件）：6
- `docs/platform/audit/AUDIT-D-C-P4P5P8.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-C-case-access.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-C-ip14-paid.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-C-m01-s3.md`（隨包文件）：10
- `docs/platform/audit/AUDIT-D-C-tax-sink2.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-D7-drill.md`（隨包文件）：3
- `docs/platform/audit/AUDIT-D-H12-apply.md`（隨包文件）：27, 129, 130, 131, 139
- `docs/platform/audit/AUDIT-D-P1P3-catalog.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-R1-R3-legal.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-builder-chain.md`（隨包文件）：40, 41, 42
- `docs/platform/audit/AUDIT-D-host-P6-voucher-rollback.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-host-U14-hist.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-host-corered.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-D-pii-notice.md`（隨包文件）：6
- `docs/platform/audit/AUDIT-D-train14-r2.md`（隨包文件）：123, 136, 141
- `docs/platform/audit/AUDIT-D-train15-map.md`（隨包文件）：106, 241, 254
- `docs/platform/audit/AUDIT-D-update-delivery.md`（隨包文件）：4, 42, 48, 49, 50
- `docs/platform/audit/AUDIT-X-9b-upgrade-paths-pii.md`（隨包文件）：203, 225
- `docs/platform/audit/AUDIT-X-9c-module-select.md`（隨包文件）：5, 8, 117, 159, 170
- `docs/platform/audit/AUDIT-X-B-C4.md`（隨包文件）：5
- `docs/platform/audit/AUDIT-X-B-M08-move.md`（隨包文件）：5, 97
- `docs/platform/audit/AUDIT-X-C-batch1.md`（隨包文件）：16, 184
- `docs/platform/audit/AUDIT-X-IP1-4-row-access.md`（隨包文件）：174
- `docs/platform/audit/INVESTIGATION-D-O5-index-load.md`（隨包文件）：4
- `docs/platform/plans/GENERATED-FILES-PROPOSAL.md`（隨包文件）：5
- `docs/platform/states/STATES-PLATFORM.md`（隨包文件）：121
- `frontend/pages/storage-settings.html`（頁面）：88, 89, 90
- `tools/platform/final_drill.py`（工具／部署腳本）：4, 47

### 1.4 補充觀察（規則偵測以外）

| # | 位置 | 觀察 |
|---|---|---|
| a | `DR-SOP.md:127`、`version_manifest.json:2051` | 寫出 demo 帳號舊密碼＝本公司統編（程式已改為隨機臨時密碼，文件與紀錄仍在） |
| b | `helpers/auth.py:44` | 弱密碼黑名單以明文列出「本公司簡稱＋統編」組合 |
| c | `core/upgrade.py:683-686 _is_our_install` | 以統編相等**或名稱含兩字簡稱**判定本公司；簡稱是常見字組合，客戶公司名含同兩字即誤判為本公司並被回填本公司聯絡資料（E4 §2 ④已列） |
| d | `helpers/startup.py:113-216`、`routers/auth.py:1646`、`db.py:1034-1035` | 既有安裝的預設管理員帳號名＝本公司人員名；`db.py` 另有人員姓名（凍結 migration） |
| e | `backend/main.py`、`routers/system.py`、`helpers/email_notify.py`、`pages/notification-settings.html` | 正式機內網 IP 寫在程式預設值／提示文字 |
| f | `pages/company-profile-settings.html:244`、`pages/users.html:487`、`pages/network-plans.html:217` | placeholder 用了「真實存在的公家機關地址」、「可能為真實號碼的 02 市話」、「可能存在的公司名」——非本公司資料，但不是保證虛構；改用保留值（§2.1） |
| g | `.gitattributes:180` | 註解含本公司網域（此檔隨包出貨） |
| h | 選型資料庫種子、`version_manifest` | 多處外部網站網址（廠牌官網、政府網站）＝公開資訊，不列風險；其中一個經銷商網域出現 25 次，是否透露供應商關係待主持判斷（§5 T6） |

## 2. 設計

### 2.1 ① demo／範本／placeholder 改虛構資料

- **虛構值登記檔** `tools/platform/deid_fiction.json`（進 repo）：列保留的虛構值與樣式，掃描器把命中它的樣式結果歸為「虛構」。取值規則：
  - 統編：檢查碼正確（E4 Q6 表單會驗）但**以 GCIS 查詢確認查無登記**；登記檔記查詢日期，建包時不重查（不連網），每季由人工重查一次。
  - 電話：`02-0000-0000`～`02-0000-9999`、`0900-000-000` 段（未核配號段）。現有 `02-1234-5678`、`04-1234-5678`、`0912-345-678` 改為保留段。
  - email：只准 `example.com／example.org／*.test`（RFC 2606）。`company.com`、`supplier.com`、`gmail.com` placeholder 改 `example.com`。
  - 公司名：一律帶「範例／示範」字首；地址：`範例市示範區範例路 1 號`（不用真實公家機關地址）。
  - 人名：`示範甲`、`示範乙` 這類不像真名的寫法（避免與真實員工同名造成雜湊層誤判）。
- **demo 示範資料**（Q3＝虛構示範公司＋浮水印）：`reset_demo_db()` 之後載入 `backend/data/demo_fixture.json`（新檔，全部取自虛構登記檔；由 `tools/platform/deid_fiction.py gen` 產生，固定亂數種子，可重現）。demo 產出的 PDF 一律加浮水印（E4 設計已含，這裡只要求 fixture 內容通過 §2.2 掃描）。
- 範本（`output_templates/*.json` 等）目前 0 命中；新增範本的範例文字同樣只准用虛構登記檔的值。

### 2.2 ② 建包時掃描守門

**(a) 清單內容與產生**

- 來源：**本公司正式機的資料庫**（不在開發機；開發機只有測試資料）——`company_profile`、客戶、供應商、聯絡人、員工／使用者、承攬商、案件（名稱、地址、聯絡人）、銀行帳號欄位；再加一份人工補充檔（開發者代號、網域、內網 IP、舊電話、舊地址、預設管理員帳號名）。
- 產生工具 `tools/platform/deid_hashlist.py export --db <正式庫唯讀複本> --extra <人工補充檔> --key <金鑰檔> --out deid_hashlist.json`：在正式機上執行（讀每日備份的複本，不開正式庫），**只輸出雜湊**。明文不落地、不上傳。
- 雜湊：`HMAC-SHA256(key, kind + "|" + normalize(value))`，取前 16 bytes。**要金鑰（HMAC）不是公開鹽**：統編 8 碼、電話 10 碼的空間小，公開鹽＋SHA-256 可在分鐘內窮舉還原——等於明文。
- 金鑰：32 bytes 隨機，存開發機離線金鑰目錄（與交付簽章金鑰同一處、同規則：不讀進對話、不上雲）＋隨身碟備份；正式機執行 export 時由隨身碟提供，**不留在正式機**。清單檔本身沒有金鑰無法還原，可以放交付資料夾，但仍不進 repo、不進包。
- 清單檔頭：`{"v":1, "key_id": HMAC(key,"motrix-deid-keycheck")[:8], "created": ..., "source_counts": {kind: n}, "lengths": {...}, "anchors": [...], "hashes": [...]}`。`key_id` 讓掃描器驗證「手上的金鑰就是產生清單的那一把」，對不上 ⇒ 拒絕建包（不是略過）。
- 更新時機：每次出販售包前清單不得超過 30 天（檔頭 `created`）；超過 ⇒ 拒絕建販售包並提示到正式機重跑 export。

**(b) 正規化與比對**

- 文字抽取：每個文字檔掃三個視角——原文；JSON 檔再逐一掃**解析後的字串值**（`\uXXXX` 還原）；HTML 另掃 `html.unescape` 後的文字。二進位只做 PNG／JPEG metadata 文字段（tEXt／iTXt／EXIF）。
- 正規化：NFKC（全形→半形）、casefold、去掉空白與分隔符（`-_.,:;|/\()（）、，。｜` 等）、`+886` → `0`。
- 兩種值型態：
  - 數字型（統編、電話、帳號）：從文字取出**去分隔後的連續數字串**，對清單出現過的每種長度滑動取窗、雜湊比對。
  - 文字型（名稱、地址、姓名、網域）：清單另存每個值「前 3 個正規化字元」的 HMAC（截 4 bytes，`anchors`）；掃描時每個位置先算 3 字 anchor，命中才對該 anchor 登記過的長度算完整雜湊。成本≈每字元一次 HMAC（完整包約數千萬字元，估 1 分鐘內；實作時量測）。
  - 長度下限：數字型 ≥ 8、文字型 ≥ 3（正規化後）。**兩字簡稱**這類短值不進雜湊層（誤判太多），改由人工補充檔以「關鍵字＋鄰接字」規則（例：簡稱後接「整合」「公司」）登記，仍以 HMAC 存。
- 樣式層（不需金鑰，§1.1 同一套）：email（非 `example`／`.test`）、檢查碼正確的統編、台灣電話、私有 IP、開發環境路徑、門牌地址 ⇒ 不在虛構登記檔、不在誤判登記檔 ⇒ **命中即擋**（開發環境路徑建議擋，見 §5 T4）。

**(c) 命中處理與誤判**

- 命中 ⇒ 建包 `Fail`，印「路徑:行號:類別:值代碼」（值代碼＝HMAC 前 8 hex，**不印明文**，建包紀錄因此也不含明文）。
- 誤判登記 `tools/platform/deid_allow.json`（進 repo）：`{"path", "value_id", "count", "reason", "expires"}`；`value_id` 是 HMAC 代碼（沒有金鑰無法還原）。規則比照 `_our_company_literals.ALLOWED`：次數要一致、要寫理由、有期限、`frontend/` 底下不准登記。
- 🔴 誤判登記**不得用來放行本公司真實資料**：清單 kind 為 company／taxid／phone／email／person 的值不准登記（登記檔驗證時直接紅）；只有 kind=supplier／customer 的**同名公開機構**（例：政府機關、原廠）可以登記。

**(d) 本公司正式機的包：區分與豁免**

- `build_deploy_package.ps1` 新參數 `-Audience sale|own`，**預設 sale**（忘了給＝走嚴格那一邊）。`-License` 給了而授權對象不是本公司 ⇒ 強制 sale，給 `own` 直接中止。
- `own`：不剪、不擋；仍跑掃描，只記錄命中數到 `deploy_manifest.json`（`deid: {audience, hits, list_created, key_id}`），方便追蹤。
- `sale`：剪、投影、掃描、正對照全部過才產出；`deploy_manifest.json` 記 `audience: "sale"`、清單指紋、掃描題數、金絲雀結果；**不記開發機路徑**（現行 `python.path` 欄位在 sale 改記版本字串）。
- 套用端 `apply_update.ps1`：`audience=own` 的包只准套在 E4 認定為本公司的安裝（有效的開發者簽章確認檔，綁安裝識別檔）；否則拒絕並說明。`sale` 的包套在本公司安裝上照常可用（只是少了本公司專用的回填，見 §2.4）。
- `verify_package.py`：驗 `deid` 欄位存在、`audience` 合法；sale 包再跑一次樣式層（不需金鑰）當第二道。

### 2.3 sale 建包的剪裁與投影（掃描之前做）

- **剪裁清單** `product/sale_prune.json`（進 repo，建包在 `git archive`＋`product_select` 之後套用）：`docs/platform/**`（機器讀的 `modules.json`、`pii_forms.json` 等由實作時逐一確認後列 keep）、`tools/platform/` 內演練工具（`upgrade_drill.py`、`final_drill.py`；升級精靈要留）、`.gitattributes`、`.gitignore`、`backend/pytest.ini`。不用 export-ignore：own 包仍需要它們，而 export-ignore 對兩種對象一體適用。
- **隨包客戶文件**：`DEPLOY.md`、`DR-SOP.md`、`HTTPS-DEPLOY-CHECKLIST.md` 改寫為不含本公司環境的版本（內網 IP、路徑、demo 密碼改成 `<伺服器 IP>`、`<安裝目錄>`）；本公司專用段落搬到 export-ignore 的內部文件。這是 Q5「docs／根目錄文件的開發者資訊」的落點。
- **version_manifest 投影**（sale）：安裝基準（sale 包的 `install_baseline`）以前的條目保留 `module／version／date／time`，`content` 換成固定字串「安裝基準之前的紀錄」；之後的條目照原文，但要過掃描。原因：客戶畫面本來就不顯示基準前的紀錄，而 `_sync_module_versions()` 需要版本鍵（登入頁版號、VR3 重複判定）。**repo 裡的 version_manifest 一字不改**（已出貨條目不可改寫），投影只存在包裡。
- 基準後的條目若含識別值（不能改寫）：`backend/version_manifest_sale_overlay.json`（進 repo）以 `module+version` 為鍵給出去識別後的內文，投影時覆蓋；覆蓋檔本身也要過掃描。另在 PLAYBOOK §G5 加一列：「新寫版本紀錄內文不准含公司／客戶／人員名稱、正式機現況描述」，以樣式層＋雜湊層在 commit 前自查。

### 2.4 產品碼裡「會出貨的例外」怎麼處理

| 位置 | 現況 | 建議 |
|---|---|---|
| `core/upgrade.py:645-686`（V9 公司預設值、`_is_our_install`）＋`tools/platform/upgrade_drill.py:96-97` | 只在本公司安裝動作，但明文隨包 | 搬進 **own 專用** 的模組或檔（`sale_prune.json` 剪掉）；升級精靈在 sale 包裡找不到它 ⇒ 不回填（客戶本來就不該回填）。`_is_our_install` 的「含兩字簡稱」判準一併拿掉（§1.4c） |
| `helpers/auth.py:44`（弱密碼黑名單） | 明文 | 改存 `sha256(正規化密碼)`（黑名單只需「相等」判斷；雖可窮舉，但不再是可 grep 的明文）；或併入 E4 的開發者指紋同一套（§5 T3） |
| `helpers/startup.py`、`routers/auth.py`（既有安裝的預設管理員帳號名） | 明文 | 既有安裝判斷改讀庫內實際存在的最高管理員帳號，不寫死名字 |
| `db.py` 凍結 migration（統編判準、英文名回填、人員姓名與 email） | 明文，凍結不可改 | **待裁示**（§5 T1）：①行為等價改寫（字面值比較改 HMAC 比較，英文名回填改讀 own 專用檔）＋契約題證明新舊結果相同；②維持凍結、sale 包以登記例外放行（＝包內仍有明文）|
| 頁面／程式的內網 IP 預設值 | 明文 | 改讀設定或 `request.host`；提示文字用 `<伺服器 IP>` |
| `deploy_manifest.json` 直譯器路徑 | 開發機路徑 | sale 包不記路徑 |

### 2.5 ③ 正對照與反向控制

- **正對照（每次建 sale 包都跑，不是只在測試跑）**：建包時在暫存目錄（不是包本身）產生金絲雀檔，內容是金絲雀值的各種變形——原樣、全形數字、插入 `-`／空白、JSON `\u` 跳脫、HTML entity、跨 JSON 字串值。金絲雀值是**專用虛構值**（例：`金絲雀驗證有限公司`、一組保留段電話），在 export 時由人工補充檔加入清單。掃描器對金絲雀檔每一種變形都要命中，**任一沒中 ⇒ 拒絕建包**（掃描器壞了＝不能宣稱乾淨）。金絲雀檔不進包。
- **反向控制**（測試題，tests/platform）：
  1. 合成乾淨樹 ⇒ 0 命中（證明不是永遠紅）。
  2. 清單缺檔、空清單、`key_id` 不符、清單過期 ⇒ 拒絕（**不是略過**；略過條件不取自被檢查物本身，PLAYBOOK §G5 第 15 項）。
  3. 金絲雀只植入在 JSON 字串值裡／只植入在 `.md`／只植入在 `docs/platform` 以外的新目錄 ⇒ 都要命中（掃描範圍不是寫死清單）。
  4. 誤判登記：登記 kind=company 的值、次數不符、過期、登記 `frontend/` ⇒ 紅。
  5. 突變：拿掉 NFKC、拿掉 JSON 解析視角、anchor 長度改 4 ⇒ 正對照要紅（每道守門附一個會讓它轉紅的突變）。
  6. `-Audience` 沒給 ⇒ 走 sale；`-License` 對象非本公司＋`-Audience own` ⇒ 中止。
- 測試用的金鑰與清單在 `%TEMP%` 由題目自己產生（不碰真金鑰）；真金鑰只在建包時使用。

### 2.6 ④ 與 E4、version_manifest、現行守門的關係

- **E4（`wip/e-company-gate`，COMPANY-SETUP-GATE.md）**：E4 管「客戶安裝跑起來之後，輸出不可以回退到開發者資料」；本案管「包裡根本沒有開發者資料」。兩者互補，不重疊：
  - E4 §2 已列的回退路徑 ②（version_manifest）、③（docs／DR-SOP／.gitattributes）、④（`_is_our_install`）在本案 §2.3／§2.4 落地；E4 不必再處理。
  - own 包的套用限制（§2.2d）**依賴** E4 的安裝識別檔＋開發者簽章確認檔；E4 先合回，本案套用端才接得上。
  - ⚠ E4 §3.3 的「統編指紋」若是不加金鑰的 SHA-256，8 碼統編可被窮舉還原＝包內等同帶明文統編；需在 E4 側改為慢雜湊（scrypt，高成本參數）或接受（統編是公開登記資料）。列 §5 T3。
- **version_manifest「已出貨條目不可改寫」**：repo 內檔案不改；sale 投影與 overlay 是包內的衍生視圖（§2.3），不違反。own 包照舊帶完整內文。
- **現行守門 `_our_company_literals.py`／`test_no_our_company_literals.py`**：它在 repo 內以**明文**列出本公司識別樣式（測試檔 export-ignore，不進包，但進 repo）。與本案「明文不進 repo」衝突。建議（§5 T2）：改以同一份 HMAC 清單＋金鑰驗證；金鑰不在的機器 ⇒ 題目紅（不是略過）。git 歷史裡既有的明文無法收回，只能止於「不再新增」。
- **Q1（預設 LOGO／favicon）**：維持現狀，是本案唯一的預登記例外；掃描器對這三個檔跳過 metadata 以外的內容，並驗證其雜湊等於登記值（被換成別的圖要重新裁示）。

## 3. 步驟清單（實作順序）

| # | 步驟 | 產出 | 驗收 |
|---|---|---|---|
| S1 | 掃描器（L0 工具） | `tools/platform/deid_scan.py`：`normalize()`、`iter_text_views(path)`、`load_hashlist(path, key)`、`scan(pkg, hashlist, fiction, allow) -> list[Hit]`、`canary_check()`；CLI `scan --pkg --hashlist --key --audience` exit 0／3 | §2.5 反向控制 1～5 |
| S2 | 清單產生器 | `tools/platform/deid_hashlist.py export`（唯讀開庫、只輸出雜湊、檔頭 key_id） | 合成庫產生→掃合成包命中；輸出檔 grep 不到合成明文 |
| S3 | 虛構登記＋placeholder 更正 | `deid_fiction.json`；§1.4f 的 placeholder 改保留值；`demo_fixture.json` | 樣式層在 `frontend/` 0 風險 |
| S4 | 剪裁與投影 | `product/sale_prune.json`、version_manifest sale 投影、overlay 檔、客戶版 DEPLOY／DR-SOP／HTTPS 清單 | sale 包 `verify_package` 過、`apply_update` 在全新安裝演練過（含 `_sync_module_versions`、登入頁版號） |
| S5 | 產品碼例外外移 | §2.4 表（凍結 migration 依 T1 裁示） | 現行 `test_no_our_company_literals` 的 ALLOWED 只剩裁示保留項 |
| S6 | 建包接線 | `build_deploy_package.ps1 -Audience`、`deploy_manifest.deid`、金絲雀；`verify_package.py`、`apply_update.ps1` 檢查 audience | 反向控制 6；植入金絲雀的 sale 建包被拒 |
| S7 | 文件與規則 | MODULE-GUIDE §3.7 補「sale 包掃描」、PLAYBOOK §G5 補版本紀錄內文一列、DR-SOP 補金鑰保管與清單更新 | D 審 |

核心代碼方向（示意，非最終）：

```python
def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", html.unescape(s)).casefold().replace("+886", "0")
    return SEP_RE.sub("", s)

def hmac_id(key: bytes, kind: str, value: str) -> bytes:
    return hmac.new(key, f"{kind}|{normalize(value)}".encode(), "sha256").digest()[:16]

def scan_text(t: str, hl: HashList) -> Iterator[tuple[int, str]]:
    n = normalize(t)
    for run in DIGIT_RUN_RE.finditer(n):              # 數字型：滑動窗
        yield from hl.match_digits(run.group())
    for i in range(len(n) - 2):                        # 文字型：3 字 anchor → 完整長度
        for L in hl.lengths_for_anchor(n[i:i + 3]):
            if hl.has(n[i:i + L]): yield i, hl.kind_of(n[i:i + L])
```

## 4. 最大的三個風險

1. **內部文件整包出貨**：`docs/platform/**` 141 檔＋根目錄三份部署文件，含本公司識別、人員、開發者代號、內網 IP、開發機路徑；現行守門不掃 .md。
2. **version_manifest 全文出貨**：「已出貨不可改寫」讓 repo 內無法清，必須靠建包投影；規則偵測抓不到「正式機某張單卡死」這類案件敘述（81 筆），只能靠整段換掉。
3. **守門登記的例外照樣出貨＋明文清單在 repo**：`ALLOWED` 讓 CI 綠但包裡仍有明文；守門自己又以明文存樣式。雜湊清單＋sale 剪裁要同時解決兩件事，而凍結 migration 需要裁示才能動。

## 5. 待主持裁示

| # | 事項 | 建議 |
|---|---|---|
| T1 | 凍結 migration（`db.py`）內的本公司字面值 | ①行為等價改寫（HMAC 比較＋讀 own 專用檔），附新舊結果相同的契約題；凍結規則為此開一次例外 |
| T2 | 現行 `_our_company_literals.py` 的明文樣式 | 改 HMAC 清單；金鑰不在 ⇒ 題目紅；git 歷史不改寫 |
| T3 | E4 統編指紋與弱密碼黑名單的雜湊強度 | 改 scrypt 高成本（或接受：統編屬公開登記資料）——需與 E4 線一起定 |
| T4 | 樣式層「開發環境路徑」命中是擋還是警告 | 擋（sale 剪裁後預期只剩部署腳本數處，改成相對路徑即可歸零） |
| T5 | 清單產生地點與金鑰保管 | 正式機讀備份複本執行 export；金鑰離線存放＋隨身碟，不留正式機、不上雲；清單 30 天有效 |
| T6 | 經銷商／原廠網域（公開資訊但透露供應商關係）是否納入 | 不納入雜湊層；選型資料庫本來就是公開規格 |
| T7 | `-Audience` 預設值 | sale（忘記給時走嚴格的一邊） |
