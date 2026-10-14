# BP-4 設計筆記：儲存／上傳插槽與通知動作（宣告式、白名單、遮蔽優先、走既有治理層）

> 日期：2026-10-14　作者：hichan-3c　狀態：**§1 盤點完成；§2 以後為設計草稿（僅文件，未動程式）**。
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
