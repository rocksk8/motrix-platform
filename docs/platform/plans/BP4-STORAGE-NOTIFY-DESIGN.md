# BP-4 設計筆記：儲存／上傳插槽與通知動作（宣告式、白名單、遮蔽優先、走既有治理層）

> 日期：2026-10-14　作者：hichan-3c　狀態：**§1 盤點＋§2–§8 設計完成（僅文件，未動程式）**。
> 依據：`FRAMEWORK-10DAY-ROADMAP-T56.md` §0B.1／§0B.3（BP-4＝儲存／上傳插槽＋位置代號、完工單附件、通知動作）、`PLATFORM-BUILDER-ARCHITECTURE-T57.md` §2.5、§2.6、§3.3、§3.4b（儲存白名單、遮蔽優先、通知不是規則輸出）。
> 行號以 `origin/train/t60-int`（1fd62b612）為準。

## 1. 盤點：現況每一個上傳／存檔位置與每一個通知發送器

### 1.1 上傳根目錄與共用函式（單一入口）
| 項目 | 位置 | 現況 |
|---|---|---|
| 上傳根目錄 | `backend/core/paths.py:60` `UPLOADS_ROOT = realpath(root("uploads"))`；`:61-63` `PROJECT_PHOTOS_DIR`／`DEMO_PROJECT_PHOTOS_DIR`／`DEMO_UPLOADS_DIR` | 寫死為安裝根目錄下 `uploads/`；沒有設定鍵可改 |
| 通用存檔函式 | `backend/helpers/uploads.py:170` `save_document_files(subfolder, doc_no, files, uploaded_by, watermark_by, existing_count)` | 存到 `uploads/{subfolder}/{doc_no}/{uuid}{ext}`（demo 帳號導向 `_demo_uploads/`，`:129` `_effective_subfolder`）；整批全存或全不存 |
| 路徑安全 | `helpers/uploads.py:139` `_safe_save_dir`（單段 doc_no、子夾每段檢查、realpath 必須在根內） | 已有；穿越檢查在共用函式 |
| 副檔名白名單 | `helpers/uploads.py:32` `_ALLOWED_EXTS={.jpg,.jpeg,.png,.pdf}`；`:36` `_EXTRA_EXTS_BY_SUBFOLDER`（voucher_attachments＝docx/xlsx/doc/xls、case_extra_expense＝heic/heif） | **程式常數**，依子夾名查表 |
| 數量／大小上限 | `helpers/uploads.py:42` `UPLOAD_LIMITS_BY_SUBFOLDER`（只有 case_extra_expense：10 個、50MB）；`:48` `limits_for`、`:59` `max_file_bytes`（設定中心 `uploads` 群組） | 部分可由設定中心改 |
| 檔頭檢查 | `helpers/uploads.py:108` `_check_upload_magic`（`__l1_public__` 公開，勞報單回簽、工作日誌照片也呼叫） | 無條件 |
| 讀取授權 | `helpers/uploads.py:432` `upload_readable` → `registry` 的 `uploads.path_access` 提供者；沒有提供者＝讀不到（fail closed）；`routers/uploads.py:171` `GET /api/uploads/{path}`、`:127/:160` 簽名 token（`_make_photo_token` TTL 3600s） | 已有，fail closed |

### 1.2 呼叫 `save_document_files` 的上傳端點（子夾名＝目前寫死的「位置」）
| 子夾（`subfolder`） | 端點／位置 | 擁有者與讀取規則（path_access 提供者） |
|---|---|---|
| `quotations` | `modules/case/api/quotations.py:1493` 報價單回簽 | `modules/case/attachments.py:184` `_CasePathAccess` |
| `quotation_payment_items` | `quotations.py:4243`（待核准變更暫存 `_pending_case_changes/{id}`：`:4236`） | 同上 |
| `quotation_materials` | `quotations.py:4322`（暫存 `:4315`） | 同上 |
| `quotation_materials_invoices` | `quotations.py:4388`（暫存 `:4381`） | 同上 |
| `case_updates`（案件動態附件） | `quotations.py:5456`（`watermark_by` 圖片加浮水印） | 同上 |
| `case_extra_expense` | `modules/case/api/case_extra_expenses.py:1229`、`:1526` | 同上；舊版 `quotation_settlement_extra` 只讀（`case/attachments.py` `LEGACY_EXTRA_FOLDER`） |
| `completion_notes` | `modules/case/api/completion_notes.py:920`（完工單簽回） | 同上（`case_documents_readable`） |
| `shipping_notes` | `modules/supply/api/shipping_notes.py:858` | `shipping_notes.py:209` `_ShippingPathAccess` |
| `invoice_vouchers` | `modules/arap/api/invoice_vouchers.py:824` | `invoice_vouchers.py:974` `_InvoiceVoucherPathAccess` |
| `contractor_dispatches`、`contractor_dispatch_invoices` | `modules/subcontract/api/vendor_contractors.py:787`、`:1080` | `modules/subcontract/attachments.py:120` `_SubcontractPathAccess` |
| `dev_logs`（業務開發記錄） | `modules/crm/api.py:908` | `crm/api.py:119` `_DevLogPathAccess` |
| `custom_records`（自訂模組檔案欄） | `routers/custom_records.py:347` | `helpers/custom_files.py:210` `CustomFilesAccess`（`FOLDER="custom_records"`，`:26`） |
| `voucher_attachments`（傳票附件） | `modules/accounting/api/vouchers.py:1266`；複製 `modules/accounting/voucher_attachments.py:276`（`shutil.copyfile`） | 各自端點（沒有 path_access 提供者） |
| `payslip` 簽回檔 | `modules/payroll/api/payslips.py:786`（自有 `open(...,"wb")`）；`:558` 勞報單歸檔 | 自有端點 |

### 1.3 不走 `save_document_files` 的其他寫檔位置
| 項目 | 位置 | 備註 |
|---|---|---|
| 工作日誌／專案照片 | `routers/system.py:760-795`（`upload_work_log_photos`，`photos.py:23` `_photo_root`）；`routers/system.py:843` `_WorkLogPhotoAccess`（`FOLDERS=("projects",)`） | 自有副檔名清單（含 gif/webp/heic）、`_process_project_photo` 加浮水印／GPS |
| 品牌圖檔 | `routers/system.py:3280` → `helpers/branding.py:171`（tmp＋`os.replace`） | 僅超級管理員；自有大小／格式上限 |
| PDF 存檔目錄（7 種） | `core/paths.py:67-76` `PDF_ARCHIVES`（系統設定鍵 `pdf_base_path`、`shipping_pdf_base_path`…`payslip_archive_path`）＋ `pdf_gen.py:183-205` 解析 | **已經是可設定的外部路徑**（可指到網路磁碟），沒有白名單；demo 版另有 `DEMO_*_ARCHIVE_DIR`（`paths.py:78-84`） |
| 備份／雲端存檔 | `core/paths.py:87` `LOCAL_DB_BACKUP_DIR`；`archive.py:77-126`（`_archive_base`、`_uploads_mirror_dir`、`_pdf_mirror_dir`）；`routers/system.py:2485-2505` 雲端備份目標設定 | 超級管理員設定；非 BP-4 範圍（備份＝基礎設施） |
| 資源回收桶隔離區 | `modules/recyclebin/quarantine.py:82-86` | 內部搬移 |
| 升級包搬檔 | `core/upgrade.py:468…1011` | 內部 |
| 未存檔、只讀入記憶體 | `modules/arap/api/cashier.py:833` 銀行對帳匯入、`modules/netplan/api.py` Excel 匯入、`modules/analytics/api/reports.py`、`modules/subcontract/api/contractors.py` | 不落地 |

### 1.4 通知發送器（現況＝三條通道＋行事曆）
| 通道 | 位置 | 現況 |
|---|---|---|
| **站內通知** | `helpers/audit.py:128` `_notify(username, type, ref_id, ref_label, message, link)`（寫 `notifications` 表；金額文字對收件人無財務權限時改「（金額略）」`:_mask_money`；`link` 只收同站頁面檔名；核准類同 (type,ref_id,username) 只留一列）；保留 90 天 `:177 purge_old_notifications` | **呼叫端遍布各模組**（`_notify(`／`notify_module_activity(` 約 200+ 處：`modules/case/api/quotations.py` 28、`subcontract/api/vendor_contractors.py` 13、`crm/api.py` 13、`routers/system.py` 12、`case/api/case_extra_expenses.py` 12 …） |
| **電子郵件** | `helpers/email_notify.py:333` `_send` → `:355-399` SMTP（`smtplib.SMTP`，標頭組裝、`SEND_*` 結果碼、開發機擋寄 `:81 _smtp_send_blocked`）；約 50 個 `notify_*` 函式（`:509…:1030`：報價單／出貨單／承攬商匯款／開票憑據／請款單／自訂模組單據與定義／獎金…）；`:1820 notify_module_activity`（audience＝admins） | 每種信由 `helpers/mail_types.py:54 register()` 登記（key、分類 business／approval／system、預設群組、事件收件人、影響、建議處理）；登記者：core（`mail_types.py` 38 筆、`core/migrations.py` 10 筆）＋模組 `accounting/notify.py`、`case/expense_notify.py`、`case/material_notify.py`、`case/payable_reminders.py`、`payroll/bonus_notify.py`、`payroll/payslip_notify.py`、`subcontract/dispatch_notify.py`、`tender_radar/notify.py` |
| **收件人政策（已宣告式）** | `helpers/mail_types.py:15-26`（`GROUPS`：none／admins／superadmins／finance；`MODES`：default／superadmin_only／custom；覆寫存 `system_settings.mail_recipient_overrides`）、`helpers/email_notify.py:182-300`（`_mail_off`、`_custom_emails`、`_group_emails`、`_with_event_recipients`、`_lookup_emails`）；個人退訂 `helpers/notification_prefs.py`（`users.notification_muted`，`EVENT_GROUPS` 為事件鍵單一來源）；`helpers/notify_matrix.py`（信件×行事曆關聯、關閉鎖定） | **「誰收哪種信」今天就已是超管可調的設定**（設定頁「信件與通知收件設定」）；事件本身（何時觸發）與信件內容是程式寫死 |
| **自訂模組狀態通知** | `helpers/custom_modules.py:1397` `_notify_state`（狀態可宣告 `notify:{requester,users[]}`）＋ `notices.notify/mail`；轉換事件 `:1385` `events.publish(EVENT_TRANSITIONED)` | 唯一一處「使用者宣告何時通知誰」的既有機制（自訂模組內） |
| 定義審核通知 | `helpers/custom_def_review.py:175` `_notify`；`helpers/config_ledger.py:125` `_notify_others`（設定變更通知其他最高管理者） | 治理層既有 |
| 行事曆回寫 | `modules/case/api/quotations.py` `_calendar_writeback_quotation`（IP-6 `calendar.writeback`） | 非通知，列入 `notify_matrix` |
| 其他通道 | 全 repo 搜尋 webhook／LINE／SMS／推播：僅 `core/system_hub.py` 提及字樣，**沒有任何出站 webhook／簡訊通道** | BP-4 不新增（架構筆記 §2.5「本版不開放使用者自訂 Webhook／任意 URL」） |

### 1.5 盤點結論（對設計的限制）
1. **上傳「位置」今天＝寫在各端點的字串常數（子夾名）**；根目錄單一（`UPLOADS_ROOT`），不可設定。讀取授權已經是「位置→擁有模組提供者」且 fail closed——這正是架構筆記要求的 provider 規則，**插槽必須掛在既有提供者上，不可繞過**。
2. **白名單／上限散在三張表**（`_EXTRA_EXTS_BY_SUBFOLDER`、`UPLOAD_LIMITS_BY_SUBFOLDER`、各端點自己的副檔名清單：工作日誌照片、勞報單簽回、傳票附件），插槽要把它們收斂成一份「位置代號登錄表」，且**只能縮小**。
3. **PDF 存檔目錄已經可由系統設定指到任意路徑**（含網路磁碟）。BP-4 的白名單根目錄概念要和它對齊：PDF 存檔列為獨立的「輸出根目錄」，BP-4 不放寬、也不替它加 UI 新增根目錄。
4. **通知的「收件人類別」已宣告式**；缺的是「事件→通知」的宣告（今天各端點手寫 `_notify`／`notify_*`）。自訂模組已有 `notify:{requester,users}` 先例，BP-4 的通知動作可沿用同形狀。
5. **站內通知內建金額遮蔽（`_mask_money`）**——通知動作必須經這支唯一出口，不得另開寫 `notifications` 的路徑。

(§2 起為設計，見下。)

---

## 2. 目標、非目標、共通原則

**目標**：管理者不改程式就能 ①為某種單據宣告「附件種類」並選擇它存在哪個**位置代號**、哪個子資料夾、收哪些副檔名／多大；②宣告「某事件發生時，通知誰、說什麼」；兩者都有**發布前預覽**（「這個新上傳路徑／新通知，對這幾筆樣本單據會發生什麼事」），並走既有治理層（草稿→預覽→發布→版本帳本→還原；放寬須第二位最高管理者核准）。

**非目標（本班不做）**：新增儲存根目錄的 UI；出站 webhook／LINE／簡訊／任意 URL；自由文字腳本或運算式當通知條件（條件重用 BP-2 規則引擎，本班先不接）；改備份／雲端存檔設定；搬動既有檔案。

**共通原則（沿用五條硬護欄）**
1. **宣告式**：定義只能挑「引擎登錄表裡已有的東西」（位置代號、單據類型、事件、收件人類別、占位符），沒有路徑字串、沒有 SQL 識別字、沒有程式。
2. **旗標預設關、關＝與今天逐位元相同**：`builder_slots.enabled`、`builder_notify.enabled`（設定中心，預設 0）。關閉時註冊表由**今天的常數**種出（見 §3.6 同一性測試），端點、路徑、信件全部不變。
3. **遮蔽優先**：附件與通知內容只能**收窄**可見性；金額／內部欄位不進通知文字給無權者；附件檔名、插槽標籤不得是金額欄位。
4. **只能縮小的白名單**：插槽的 `accept`／上限必須落在位置代號的上限內，位置代號落在平台硬底線內。
5. **走單一發布管線**：`attachment_slot`、`notify_action` 兩種定義 kind 一律經 `POST /api/definitions/{kind}/{key}/publish`（受管 kind 守門、`preview_hash`、`def_pipeline` 分級），不另開路。位置代號本身（`storage_location`）只有開發能改（登錄表），UI 唯讀。

## 3. 儲存／上傳插槽

### 3.1 三層模型
```
根目錄 root        部署設定宣告（程式白名單 + 安裝設定檔），UI 不能新增。BP-4 只有 `uploads`（= UPLOADS_ROOT）。
  └ 位置代號 code   平台登錄表的一列：{code, root, folder(實體資料夾名,固定), provider(path_access 提供者), accept⊂硬白名單,
                      maxFileMb, maxFiles, maxRequestMb, retired}。由程式與升級種出（盤點 §1.2 的 17 個子夾＝17 個內建代號，
                      值逐一等於今天的常數）。管理者只能「選用」，不能新增代號（新增代號＝開發加登錄表一行＋provider）。
      └ 插槽 slot     管理者的宣告：{docType, slotKey, label, code, subfolder?, accept?, maxFileMb?, maxFiles?,
                      uploaders(角色/模組權限，只能收窄), required?, order}。這是 BP-4 新增的定義 kind `attachment_slot`（key＝`doc:<docType>`）。
```
- **docType 與代號對應**來自引擎登錄表（例：`completion_note → code completion_notes`），**不接受使用者輸入**（架構筆記 §3.3 末條）。
- **子資料夾** `subfolder`：單層、`^[A-Za-z0-9_\-一-鿿]{1,40}$`，另擋 Windows 保留名（CON、PRN、AUX、NUL、COM1-9、LPT1-9）、尾端點／空白、全形斜線、`..`；NFC 正規化後比對、大小寫不敏感去重。**不接受任何路徑字串**。
- 落地路徑＝`realpath(root / folder / [subfolder] / doc_no / 系統產生檔名)`，並斷言在 `realpath(root)` 內（沿用 `_safe_save_dir`，補第三層）；檔名＝uuid＋白名單副檔名，原檔名只存 DB 當顯示名（輸出走 `download_name`）。
- **舊檔不搬**：檔案 metadata 的 `path` 是實際相對路徑；讀取永遠依 metadata 的路徑解析（再斷言在根內），**與插槽現在的設定無關**——所以改插槽、退役插槽都不會讓舊檔讀不到。

### 3.2 硬底線（寫死，插槽與代號都不能放寬）
- 副檔名：全域白名單（今天的 `_ALLOWED_EXTS` ∪ `_EXTRA_EXTS_BY_SUBFOLDER` 的聯集上限＝jpg/jpeg/png/pdf/heic/heif/docx/xlsx/doc/xls；**不含** html/htm/svg/js/exe/bat/ps1/py/php/aspx/dll/lnk/壓縮檔）；雙副檔名（`a.pdf.exe`）一律拒絕。
- 檔頭（magic）檢查無條件（`_check_upload_magic`）；單檔上限不超過 `uploads.max_file_mb`（現為 20MB）。
- 回傳一律 `Content-Disposition: attachment`＋`X-Content-Type-Options: nosniff`，不從靜態路由直出（現況 `routers/uploads.py:171` 已是簽名 URL 服務；本班補斷言）。
- demo 帳號仍導向 `_demo_uploads/`（`_effective_subfolder` 不動）。
- 容量防護：每張單據每個插槽的 `maxFiles` ≤ 代號上限（預設 10）；整次請求合計 ≤ 代號 `maxRequestMb`。滿了＝明確 400，不影響單據本身的存取或儲存。

### 3.3 讀取授權（不可繞過）
- **每個位置代號必須有 provider**（`uploads.path_access`，今天 6 個類別 `case/attachments.py:184`、`shipping_notes.py:209`、`invoice_vouchers.py:974`、`subcontract/attachments.py:120`、`crm/api.py:119`、`custom_files.py:210`，加 `routers/system.py:843` 照片）。沒有 provider＝讀不到（fail closed，現況）。
- 有子資料夾的新插槽，路徑多一層：`rest` 變成 `subfolder/doc_no/檔名`。**provider 介面小幅擴充**（L1，只增）：提供者宣告 `SLOT_AWARE = True` 才會被餵 3 段 `rest`；未宣告的提供者碰到帶子夾的路徑一律拒絕（fail closed）。完工單附件是第一個使用者，由 `case` 模組實作。
- 插槽的 `uploaders` 只能**收窄**：實際上傳權限＝端點既有守門 ∧ 插槽 `uploaders`；讀取權限＝provider 既有規則（插槽無法放寬）。刪除沿用端點既有規則（`delete_document_file`，`helpers/uploads.py:252`）。
- 附件**永遠是內部資料**：不會自動進客戶版 PDF／回簽頁；要進客戶通道必須是範本明確引用（BP-3 範本，另有 `internal` 欄位禁入規則）。

### 3.4 完工單附件（第一個新插槽）
- docType `completion_note`，代號 `completion_notes`（既有 provider：完工單讀取＝`case_documents_readable`）。出貨時內建預設插槽 `signed`（簽回單，**等於今天的行為**：`completion_notes.py:920`，jpg/png/pdf、20MB）；管理者可再加如「現場照片」「驗收單」「保固書」，各自 accept／上限／上傳者。
- 檔案 metadata 加 `slot`（additive；舊讀取端忽略），`files_json` 內以 `slot` 分組顯示；上傳端點 `POST …/attachments?slot=<key>`（新端點，沿用 `save_document_files`，多一個 `policy` 參數＝§3.5）。
- 完工單簽核流程、金額與狀態語意**完全不動**；附件不參與簽核綁內容（H3），也不影響狀態轉換。需要「必須有某種附件才能送出」屬流程狀態機（BP-5），本班只提供 `required` 旗標的**提示**（標紅，不阻擋）。

### 3.5 唯一出口（程式結構）
- 新 `helpers/storage_slots.py`（L1）：`policy(doc_type, slot_key, viewer)` → 不可變 `SlotPolicy`（解析後的 code、folder、subfolder、accept、上限、uploaders 檢查）；`builtin_policies()`＝由今天的常數種出的內建表。OFF 或找不到宣告 ⇒ 回內建值。
- `save_document_files(…, policy=None)`：`policy` 為 None＝今天的行為（簽章只增一個選填參數；`__l1_public__` 介面快照要升版，屬 L1 只增）。給了 policy 才套用 accept∩硬底線、上限、子夾。各端點改成 `policy=storage_slots.policy("completion_note","signed",user)` 是**逐端點的小遷移**，BP-4 只遷完工單；其餘 16 個呼叫點維持現狀（登錄表先以唯讀方式列出，遷移排在 BP-6 的「遷移第二波」）。
- 不受插槽管理的例外（登錄表「不受插槽管理」欄並說明原因）：工作日誌照片（`routers/system.py:760`，有 GPS／浮水印處理）、傳票附件（自有端點）、勞報單簽回（`payslips.py:786` 自有 `open`）、品牌圖檔。

### 3.6 OFF 同一性與回退
- `builder_slots.enabled=0`：`policy()` 只回內建表；`save_document_files(policy=None)` 路徑與今天相同。測試：①內建表逐列等於 `_ALLOWED_EXTS`／`_EXTRA_EXTS_BY_SUBFOLDER`／`UPLOAD_LIMITS_BY_SUBFOLDER`／`limits_for()` 的現值；②對 17 個子夾各存一個樣本檔，OFF 與舊程式的磁碟路徑逐位元相同（路徑黃金表）；③OFF 時 `attachment_slot` 路由 404。
- 回退：關旗標即回內建；已存的檔因 metadata 帶實際路徑，不受影響。

### 3.7 治理分級（接 `def_pipeline.classify`）
| 變更 | 分級 |
|---|---|
| 新增插槽但 accept／上限／上傳者都不寬於「同代號現有最嚴插槽」；縮小 accept／上限／上傳者；停用插槽；改標籤／順序 | 收緊或中性（立即生效） |
| 新增副檔名、提高單檔／件數／合計上限、**擴大上傳者**、改子資料夾、改選另一個位置代號 | **放寬（security）**：待第二位最高管理者核准＋確認期間；原因寫入帳本 |
| 無法解析／未知欄位 | 放寬（同 user_buttons 的保守規則） |
- 每次發布前自動快照（BP-1 治理層已有）；`preview_hash` 與 restore 把關沿用 T62。

### 3.8 預覽（「新上傳路徑會怎樣」）
管理者在插槽編輯器選：樣本單據（最近 N 張，只列有權限看的）＋ 模擬檔案（檔名、大小、副檔名、可選「正常／偽裝」檔頭範例）。後端**純函式、不寫檔**回：
- 判定：收／不收＋白話原因（副檔名不在 accept、超大小、超件數、檔頭不符、被硬底線擋）。
- 若會存：**顯示用相對路徑**（`uploads/completion_notes/驗收單/MQ-0001/〈系統產生〉.pdf`，不含根目錄的磁碟路徑）、由哪個 provider 控制讀取、**誰能看**（依 provider 規則對各角色逐一判定的矩陣，使用者名單只給人數）、這張單據該插槽已有幾個／上限。
- 與已發布版本並排差異（新增了哪些副檔名、上限變多少）＋放寬的紅色橫幅與影響範圍（既有單據不受影響、僅新上傳）。
- 預覽記稽核（`definitions.previewed`），不記內容；不寫任何檔案／目錄（含不建空資料夾）。

## 4. 通知動作

### 4.1 與現況的關係（不重做已有的）
- **內建通知與收件人覆寫保持原樣**（`mail_types` 登記＋`mail_recipient_overrides`＋個人退訂）。BP-4 新增的是「**額外通知**」：管理者宣告「當事件 E 發生，額外通知 R，內容 T」。**不能**關掉或改寫內建信件、系統技術類、稽核類通知（要調內建收件人，仍用既有的「信件與通知收件設定」）。
- 事件來源＝`core/events.py` 事件匯流排（發佈在 commit 之後、訂閱者失敗不外拋）。今天只有自訂模組發 `custom_module.transitioned`（`helpers/custom_modules.py:1394`）與 `custom_record.finance_posted/reversed`；BP-4 新增事件的方式＝**開發端對既有寫入點加一行 `events.declare/publish`**（宣告含欄位清單與權限標記），管理者只能挑已宣告的事件。首批事件（皆在 commit 後發）：`completion_note.attachment_added`（插槽上傳成功，payload 含 slot）、`completion_note.state_changed`、`custom_module.transitioned`（既有）、`case.deadline_near`（重用 `case_deadlines`）。其餘事件隨需求逐個宣告。

### 4.2 定義 kind `notify_action`（key＝動作 id）
```
{ id, label, enabled,
  event:      <已宣告事件名>,
  when:       可選，簡單條件：事件 payload 的「欄位 ∈ 值集合」（最多 3 條 AND；欄位限事件宣告為 filterable 的非金額欄位）,
  channels:   ["in_app"] | ["in_app","email"],
  recipients: [ {kind: "requester"|"owner"|"current_approver"|"role"|"user"|"group", value?}, … ] （≤ 8 項）,
  template:   { title ≤ 60 字, body ≤ 400 字, 占位 {name} 只能取事件宣告的 `fields`, 不收 HTML/連結 },
  throttle:   { dedupeMinutes: 1..1440, maxPerRecipientPerDay: 1..20 } }
```
- 收件人類別來自**固定目錄**：`role` 值限 `mail_types.ROLES`；`user` 值必須是**現有啟用帳號**（從目錄挑，存 username，不存 email）；`group` 值限 `mail_types.GROUPS`。**不接受 email 位址、不接受任意 URL**。
- 條件**不是腳本**：只有「欄位 ∈ 集合」；進階條件待 BP-2 規則引擎穩定後再評估接入（通知仍是註冊動作，不是規則的輸出——架構筆記 §3.4b）。
- 連結：通知的 `link` 由**事件宣告的頁面模板**決定（同站頁面檔名＋單號），沿用 `_notify` 的 `_LINK_RE` 檢查，動作定義不能指定連結。

### 4.3 派發器（唯一出口）
`helpers/notify_actions.py::dispatch(event, payload)`，由事件匯流排訂閱；**絕不影響原交易**（已 commit；例外只記 ERROR 與 `recent_failures`）。對每個啟用且符合 `when` 的動作：
1. 展開收件人 → 去重 → **逐人過濾**：必須有權限開啟該單據（以事件宣告的 `readable(conn, payload, user)` 判斷，對應 row_access／provider）；無權限者**丟棄並計數**（稽核記「N 人因無權限未通知」，不洩漏誰）。
2. **逐收件人渲染範本**：占位符若屬 `money`／`internal` 標記，收件人沒有對應權限（`quote_money_visible`／角色）⇒ 以「（略）」代替；站內通知另經既有 `_mask_money`。**遮蔽以收件人為準，不以動作作者為準**。條件所引用的欄位若是金額／內部欄位，「命中」本身也不得透過通知文字洩漏——此類欄位不列入 filterable 目錄（沿用 U13：衍生旗標不得推論被隱藏金額）。
3. 寫出：站內通知走 `helpers/audit._notify`（唯一寫 `notifications` 的路徑）；電子郵件走 `email_notify._send`＋**單一登記類型** `user_notice`（`mail_types.register`，分類 business、群組 none），標頭、主旨前綴 `【MOTRIX 系統通知】`、`SEND_*` 結果碼、開發機擋寄全部沿用；個人可退訂（`notification_muted` 的事件鍵＝`na:<id>`）。
4. 上限（寫死）：每動作每次觸發 ≤ 25 位收件人；每動作每小時 ≤ 200 封；**通知不再觸發事件**（無連鎖、無遞迴）；訂閱者逾時 ≤ 2 秒預算，超過降級＋記稽核（「通知降級」），不阻擋業務寫入。
5. 稽核：每次派發寫一筆彙總稽核（動作 id、事件、收件人數、丟棄數、通道），不記範本內容與收件人明細。

### 4.4 治理分級
| 變更 | 分級 |
|---|---|
| 縮小收件人／停用／加嚴節流／改文字（不新增占位符） | 收緊或中性 |
| 新增動作、**新增或擴大收件人（含 role/group）**、新增通道 email、放寬節流、範本新增占位符、`when` 放寬 | **放寬（security）**：待核准（「擴大了知情範圍」） |
- 理由：通知是資訊揭露面；放寬＝更多人收到更多東西。預覽（§4.5）＋ `preview_hash` 把關沿用 T62。

### 4.5 預覽（「新通知會對這幾筆樣本發生什麼事」）
管理者選動作＋樣本（最近 N 筆該事件相關單據，只列看得到的）。後端以**試跑**回，**不寄信、不寫 `notifications`、不發事件**：
- 對每筆樣本：會不會命中 `when`；展開後的收件人**人數與類別**（只有超級管理員可展開成姓名）；因無權限而被丟棄的人數；
- **逐角色渲染結果**：以 admin／sales／finance／engineer／viewer 的視角各渲染一份標題＋內文（顯示金額被「（略）」的位置），讓作者看到「無權者看到什麼」；
- 節流／上限試算（例如「依最近 30 天此事件次數，預計每日 ≈ X 封」）；
- 與已發布版本的差異＋放寬橫幅。預覽記稽核，不計入任何節流計數。

## 5. 管理者介面（BP-1 編輯器框架重用）
- 設定中心新增兩個旗標群組：`builder_slots`、`builder_notify`（各 `enabled`，預設關；`risk=ops`）。頁面讀旗標沿用 `MotrixPublicFlags`（併入既有設定請求，OFF 不多打請求）。
- 兩個側邊面板編輯器（沿用 `custom-fields.js`／`user-buttons.js` 的結構：草稿即時預覽、存草稿、差異、發布前審閱面板 `MotrixDefGovernance.review`、版本與還原〔`previewRestore`〕、頁內兩段式確認、待核准如實顯示）：
  - **附件插槽編輯器**：入口放在單據頁（先做完工單頁）的「附件」區旁（超級管理員）；列出內建與自訂插槽、可新增／停用／調整、右側「模擬上傳」預覽。
  - **通知動作編輯器**：入口放在設定中心「通知」區；事件、收件人、範本、節流表單＋「對樣本試跑」。
- OFF：兩個入口與路由全部不出現（404／x-if），頁面不多打請求。

## 6. 測試與驗收（設計時就列，避免事後補）
1. **OFF 同一性**：內建表＝今天常數；17 子夾路徑黃金表；`save_document_files(policy=None)` 位元組相同；兩旗標關時路由 404、頁面零新增請求；設定部署基準以文字插入。
2. **白名單只能縮小**：accept 超出代號／硬底線 ⇒ 驗證 422；`..`、`/`、`\`、保留名、尾點、NFC 變體、超長、符號連結／junction 指向根外 ⇒ 全部拒絕（突變：拿掉 realpath 斷言測試必須紅）。
3. **讀取 fail closed**：沒有 provider 的代號／提供者未宣告 `SLOT_AWARE` 的子夾路徑 ⇒ 讀不到；改插槽後舊檔仍讀得到。
4. **遮蔽正反對照**：通知逐角色渲染（有／無金額權限）；無權收件人被丟棄不洩漏；站內通知經 `_mask_money`；filterable 目錄不含金額／內部欄位（掃描式測試）。
5. **派發器隔離**：訂閱者丟例外不影響業務寫入；通知不連鎖；上限（收件人數、每小時）生效；開發機擋寄沿用。
6. **治理**：放寬分級（擴大上傳者、新增收件人 role/group…）全部進待核准；收緊立即；`preview_hash`／restore 把關測試（沿用 T62 夾具）。
7. **預覽純淨**：預覽不寫檔／不建資料夾／不寫 `notifications`／不寄信（以檔案系統與表快照比對）。
8. **備份涵蓋**：新子夾位於 `UPLOADS_ROOT` 之下，既有 `archive.py` 的 uploads 鏡像自動涵蓋（測試以暫存根驗證新路徑被鏡像清單包含）。

## 7. 切片與工量（估，非承諾）
| 切片 | 內容 | 估 |
|---|---|---|
| S1 | `storage_slots.py` 內建表＋OFF 同一性測試＋硬底線＋`policy` 參數（只增）＋唯讀登錄表 API | 2.5 pd |
| S2 | `attachment_slot` kind（驗證器、分級、預覽／模擬上傳）＋完工單 `signed` 預設插槽遷移＋`SLOT_AWARE` provider（case） | 3 pd |
| S3 | 附件插槽編輯器（完工單頁）＋模擬上傳預覽 | 2 pd |
| S4 | 事件宣告（首批 4 個）＋`notify_action` kind＋派發器＋`user_notice` 類型＋上限 | 3.5 pd |
| S5 | 通知動作編輯器＋試跑預覽＋逐角色渲染 | 2.5 pd |
| 合計 | | 約 13.5 pd（與架構筆記附件／儲存插槽 8～12 pd 相近；通知動作原列於流程掛鉤） |

## 8. 風險與需要決定的事
1. **（需 L0/L1 決定）`save_document_files` 加選填 `policy`、`uploads.path_access` 提供者加 `SLOT_AWARE`**：皆為「只增」，需 `core_bump` 快照與 CHANGELOG；沒有現有呼叫端行為變動。**請 b4 確認可進 L1**（確認前不動 core）。
2. **事件宣告散在各模組**：首批 4 個事件需要 `case`／其他模組負責人各加一行 `events.publish`——屬跨模組小改，需協調（不由我直接動 `modules/case/api/*`）。
3. **子資料夾的實際需求**：多數情境「位置代號」已足夠；子資料夾會讓 provider 路徑解析多一層。建議**第一版只對新插槽開放**，內建 17 個代號一律不帶子夾（降低風險）。請使用者確認是否仍要子資料夾（架構筆記 P7 寫了「代號＋子夾名」）。
4. **多根目錄／網路磁碟**（日後才有）：根不可達時上傳**明確失敗**，絕不 fallback 到別的根；根的備份涵蓋要在部署宣告 `backup: true`，否則上傳 UI 顯示「此位置不在備份範圍」警語。BP-4 v1 只有 `uploads`，不啟用。
5. **`user_notice` 的個人退訂**：使用者可關掉所有額外通知；對「必須知道」的情境，管理者應改用內建簽核／待辦機制。是否允許動作標記「不可退訂」？建議**不允許**（避免繞過個人通知偏好；符合 `notification_prefs` 現行設計）。
6. **與 BP-2 規則引擎的邊界**：本設計的 `when` 只是欄位∈集合；若要「毛利低於 X 才通知」需 BP-2 的條件語言——等 BP-2 穩定後以 `when: {rule: <ruleId>}` 接入（規則只回布林，通知仍是註冊動作）。
