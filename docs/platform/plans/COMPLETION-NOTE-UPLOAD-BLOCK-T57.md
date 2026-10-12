# 完工單附件上傳：做成「可調式積木」的設計筆記（僅文件，未跑任何測試）

> 日期：2026-10-13　作者：hichan-98　委託：hichan-1c（使用者新需求原文：「完工單沒有簽核完成的上傳功能，這部分框架化也可以進去，我的目標是模組化框架化，讓這個變成可調式積木」）
> 基底：`origin/platform` `33b84b332`（M2.1 已上線）。完工單核心由 c7 的堆疊負責（實作者＝c7）；本文是設計，不含程式。
> **r2（c7 事實更新，`completion_notes.py` @ `33b84b332` 與 `wip/t57-completion-r2` `9922b1777`）**：①同一份清單加「種類」（不另開第二份清單，回收桶 adapter 與讀取提供者不用改）；②完工單**沒有**「匯出後凍結」的概念，`lock_after_export` 改為 `lock_after_customer_signoff`（客戶驗收簽回後鎖定）；③上傳會更新 `updated_at`＝樂觀鎖權杖，編輯草稿的人會被誤擋 409，附件變動**不再更新** `updated_at`；④政策鍵放進 c7 已登錄的 `completion_note` 群組（前綴 `attach_`），不另開群組；⑤上傳授權比編輯寬（案件管理模組持有者都能傳）；⑥章戳的階段改為三段（核准前／已核准／已客戶簽回）。
> 標記：**UNKNOWN**＝沒有證據，不推測；pd 的「估」是我的粗估。

## 0. 結論（先看）

1. **後端其實已經有上傳端點，缺的是「畫面入口」和「政策」**：`POST／DELETE /api/completion-notes/{單號}/signed-files`（`completion_notes.py` 約 766／792 行）任何單據狀態都能傳（程式註解寫明刻意不限制）、檔案存 `uploads/completion_notes/<單號>/<uuid>.<副檔名>`、清單存 `completion_notes.signed_files_json`；**但完工單表單 `completion-note-form.html` 與 `case-management-completion.js` 完全沒有任何上傳／清單控制**（全前端 `signed-files` 只出現在出貨單、勞報單、報價單、出納等頁）。所以使用者看到的是「完工單沒有簽核完成的上傳功能」。
2. **做法＝重用，不另起子系統**：沿用 `helpers/uploads.py`（`save_document_files`、副檔名白名單、檔頭檢查、`limits_for`）、`uploads.path_access` 讀取提供者、`attachments.catalog`、回收桶 adapter、A7 的 `download_name`、設定中心 `uploads` 群組；新增的只有一個很小的 **「附件插槽（attachment slot）」宣告與政策檢查 helper**，以及一個**可重用的前端積木**。
3. **積木契約**：任何單據在模組的 `features[]`（脊柱 E-b 的宣告檔）宣告一個插槽（插槽代號、擁有單據類型、存放資料夾與清單欄位、附件種類、政策群組、事件名稱）；引擎替它做政策檢查、稽核、畫面。完工單是**第一個消費者**，出貨單、勞報單、報價單附件之後只要宣告就能用。
4. **管理者可調（預設＝建議值，設定中心）**：誰可以在核准後新增、允許哪些種類、核准後新增的檔是否只增不刪、數量／大小、新增是否讓核准重來（預設否）、無金額權限者能不能開、送審前是否一定要附檔（預設否）、新增時是否通知。放寬類走原因＋帳本＋第二位最高管理者核准＋確認期間，並顯示高影響橫幅。
5. **上線形態**：在功能狀態頁（E-b）先以灰色「規劃中（預計 MSn）」出現；政策群組**等程式真的做出來才登錄**（不出現沒有作用的選項）。
6. **工量（估）**：helper＋政策 1.0、設定群組 0.5、前端積木 1.25、完工單接線與測試 0.75、書面登記 0.25 ⇒ **約 3.75 pd**；第二個消費者再加約 0.5 pd。UNKNOWN：HEIC 支援與縮圖（見 §10）。

## 1. 現況盤點（已對 `33b84b332` 讀過）

| 面向 | 現況 | 來源 |
|---|---|---|
| 上傳端點 | `POST /api/completion-notes/{no}/signed-files`：先 `_readable_note`（同單筆 GET 的閘：案件成員／管理員以上／持案件管理模組者，看不到＝「完工單不存在」），再 `save_document_files("completion_notes", …)`，更新 `signed_files_json`，稽核 `completion.upload_signed_files`。**不限單據狀態**（刻意，註解：草稿階段先存現場照片是常態） | `completion_notes.py` ~766 |
| 刪除端點 | `DELETE …/signed-files/{file_id}`：**僅 admin 以上**，連實體檔一併刪除，稽核 `completion.delete_signed_file` | ~792 |
| 檔案類型／大小 | 預設只收 `.jpg .jpeg .png .pdf`（`_ALLOWED_EXTS`）；單檔上限＝設定中心 `uploads.max_file_mb`（20 MB）；檔頭（magic）檢查在 `save_document_files` 內，不符整批 400＋稽核；**完工單資料夾沒有數量／總量上限**（`UPLOAD_LIMITS_BY_SUBFOLDER` 只有 `case_extra_expense`；`limits_for` 對其他資料夾回 `{}`） | `helpers/uploads.py` 32–66 |
| 讀取授權 | `uploads.path_access` 提供者 `_CasePathAccess`，資料夾 `completion_notes`：`完工單號/檔名` ⇒ `case_documents_readable`（案件管理模組持有者） | `modules/case/attachments.py` ~185–216 |
| 清單位置 | 單一 JSON 欄 `signed_files_json`；後端回傳 `signedFiles` | `completion_notes.py` ~190 |
| 畫面 | **無**（表單與案件頁完工單區塊都沒有上傳／清單／刪除控制） | grep 全前端 |
| 狀態規則（c7 核對） | 編輯（PUT）只在草稿；`revoke-approval` 在 `is_signed=1` 時回 409；`signed-toggle` **僅 admin、且單據必須是「已核准」**（否則 409；已簽再簽、未簽取消皆 409），每次切換都在 `signed_log` 記使用者與備註——所以「已客戶簽回」只存在於已核准的單據，簽回歷史在 `signed_log`；**完工單沒有「匯出後凍結」**（匯出只增加 `export_count`／`export_log`，僅 admin）；上傳端點授權（`_readable_note`，案件管理模組持有者都可）**比編輯（`_require_admin`）寬** | `completion_notes.py` |
| 副作用（c7 核對） | **上傳／刪除都會更新 `updated_at`**＝畫面的樂觀鎖權杖 ⇒ 正在編輯草稿的人會因別人（或自己另一分頁）上傳而收到 409「已被別人更新」；核准／簽回後的單據也被悄悄改了 `updated_at`。上傳沒有通知；稽核動作沒有「種類」 | `completion_notes.py` ~781、~815 |
| 兩種「簽」 | ①核准（簽核完成，`status='已核准'`）②客戶驗收簽回（`is_signed`，`signed-toggle` 僅已核准可標）。使用者說的「簽核完成的上傳」＝**核准後（含客戶簽回後）仍能附驗收文件，並把「客戶簽回掃描」與「事後補件」分開**（c7 確認的解讀）；見 §10 Q1 | `completion_notes.py` ~714 |
| PDF | 完工單 PDF 只印「✓ 客戶已驗收簽回」字樣，**不嵌附件** | `completion_pdf.py` ~116 |
| 會計來源 | `EXCLUDED_SOURCES` 含 `completion_note`：完工單附件不會被傳票帶入 | `accounting/voucher_attachments.py` ~74 |
| 回收桶 | `recycle_adapter.py`（`entity_type="completion_note"`）把 `signed_files_json` 的檔案路徑一起打包／還原 | `modules/case/recycle_adapter.py` ~222–266 |
| 附件目錄 | `attachments.catalog` 有 `completion_note`（標籤「完工單回簽」） | `modules/case/attachments.py` ~286 |

## 2. 積木契約（可重用）

### 2.1 插槽宣告（`features[]`，E-b 驗證）
每個消費者在自己模組的宣告檔登錄一個插槽。**E-b 尚未落地前的暫行**：同樣內容寫在 `module.json` 新鍵 `attachment_slots`（唯讀載入、由 helper 驗證），E-b 落地後改為 `features[]` 投影，格式不變。

欄位（皆為宣告，不是程式）：

| 欄位 | 意義 | 完工單的值（提案） |
|---|---|---|
| `slot` | 插槽代號（唯一，`<模組>.<單據>.<用途>`） | `case.completion_note.attachments` |
| `doc_type` | 擁有單據類型鍵（同 A7 `DOC_TYPES` 鍵） | `completion` |
| `folder` | `uploads` 資料夾 | `completion_notes` |
| `list_column` | 單據上存檔案清單的 JSON 欄 | `completion_notes.signed_files_json` |
| `kinds[]` | 附件種類：`{key, label, exts?, required_before?}` | `acceptance_photo`（驗收照片）、`signed_scan`（簽回紙本掃描）、`test_report`（測試報告）、`other`（其他） |
| `states` | 各單據狀態可做的動作（由政策開關決定，宣告只列「有哪些狀態」） | 草稿、待審核、簽核中、已核准、已回簽 |
| `policy_group`＋`policy_prefix` | 政策所在的設定群組與鍵前綴（允許掛進單據既有的群組，不必每個插槽一個新群組） | `completion_note`＋`attach_` |
| `read_provider` | 讀取授權沿用的提供者 | `uploads.path_access`／`_CasePathAccess` |
| `events` | 稽核與通知事件名稱 | `completion.upload_signed_files`（沿用）、`completion.delete_signed_file`（沿用） |
| `recycle` | 回收桶是否一併處理清單欄 | 是（沿用既有 adapter） |
| `download` | 下載命名的文件類型鍵 | `completion`＋「附件」前綴（見 §6） |

### 2.2 引擎提供（一次做好）
- `helpers/attachment_slots.py`（L1，新）：`load_slots()`（讀宣告）、`check_upload(slot, doc_row, user, kind, existing, incoming)`、`check_delete(…)`、`stamp(file_meta, phase, kind, user)`；全部**純函式＋讀設定**，不碰資料庫寫入。
- `helpers/uploads.py::limits_for` 目前把 `case_extra_expense` 寫死（`if subfolder != 'case_extra_expense'`）：**需泛化成「由插槽政策給上限」**（引擎小改，屬底層；既有 `case_extra_expense` 行為與預設值不變，守門測試鎖定）。
- 前端 `static/attachment-block.js`（新）：Alpine 元件，讀 `GET` 插槽資訊（種類、可做的動作、上限、橫幅文字），列清單、拖放上傳、顯示被政策擋下的白話原因；**只負責畫面，權限與政策以後端為準**。
- 路由：完工單**沿用現有兩個端點**（不新增路由，避免路由 golden 變動）；第二個消費者出現時再決定是否加通用插槽路由。

### 2.3 完工單接線（c7）
`upload_completion_signed_files`／`delete_completion_signed_file` 在 `_readable_note` 之後加一道 `attachment_slots.check_*`；存檔成功才 `stamp`（見 §4）。其餘流程（magic 檢查、稽核、檔案存放）不動。

## 3. 政策設定（掛進 c7 已登錄的設定群組 `completion_note`，鍵前綴 `attach_`；平鋪鍵；預設＝建議值）

> 原則：**預設不改變今天已有的行為**（今天：任何能讀該完工單的人，任何狀態都能傳；admin 以上能刪）；新能力（核准後只增不刪、種類、通知…）預設取保守值。放寬＝調大權限／拿掉限制 ⇒ 高影響：原因＋變更帳本＋第二位最高管理者核准＋確認期間，並顯示紅色橫幅與影響範圍（E-e）。收緊即時生效並留帳本。

| 白話問句 | 鍵 | 預設 | 選項 | 影響（摘要） | 風險類／放寬方向 |
|---|---|---|---|---|---|
| 完工單核准後，誰可以新增附件？ | `attach_who_after_approval` | **能讀該完工單的人**（＝今天） | 無人（核准後不可新增）／管理員以上／財務角色與管理員以上／能讀該完工單的人 | 越寬，越多人能替已核准的單據補證據；「無人」＝核准後完全鎖定附件 | `ops`；往「更寬」是放寬 |
| 核准前（草稿～簽核中）誰可以新增附件？ | `attach_who_before_approval` | 能讀該完工單的人（＝今天） | 同上（不含「無人」） | 同上 | `ops` |
| 允許哪些種類？ | `attach_kind_acceptance_photo`、`attach_kind_signed_scan`、`attach_kind_test_report`、`attach_kind_other` | 全開 | 各自開／關 | 關掉的種類在畫面不出現、後端拒收；已存在的檔不受影響 | `ops` |
| 核准後新增的附件要「只增不刪」嗎？ | `attach_post_approval_append_only` | **是** | 是／否 | 是＝核准後新增的附件不能被刪除或替換（含管理員），只能由最高管理者經「還原／作廢」流程處理（UNKNOWN：流程見 §10 Q4）；否＝管理員以上可刪。**只適用於「核准後新增」的檔**，既有檔與核准前的檔維持今天的規則 | `security`／**往「否」是放寬（紅色橫幅）** |
| 每張完工單最多幾個附件？ | `attach_max_files` | 30（UNKNOWN：現況沒有上限，需查正式機最大值） | 5–100 | 超過就擋；調小不影響已存在的檔 | `ops` |
| 附件單檔大小 | （不新增鍵） | 沿用設定中心 `uploads.max_file_mb` | — | 同一個全站上限，不另開第二個數字 | — |
| 新增附件要讓核准重來嗎？ | `attach_reopen_approval_on_upload` | **否** | 否／是（新增後退回「待審核」重簽） | 是＝已核准的單據新增附件就失效重簽，會中斷已進行的下游；預設否＝附件是補充證據，不改變已核准內容 | `ops`／往「是」是收緊 |
| 沒有金額權限的角色能開附件嗎？ | `attach_money_hidden_can_view` | **能**（＝今天：附件走單筆 GET 的閘，不看金額權限） | 能／不能 | 「不能」＝沒有金額檢視權限者看不到檔名與內容；驗收掃描可能含報價金額時選「不能」 | `security`／往「能」是放寬 |
| 送審前一定要附檔嗎？ | `attach_required_before_submit` | **不用** | 不用／至少一個附件／至少一張驗收照片／至少一份簽回掃描 | 開啟＝缺附件不能送審，會顯示缺什麼；對既有草稿不溯及既往（只擋之後的送審動作） | `ops`／開啟是收緊 |
| 新增附件時要通知誰？ | `attach_notify_on_upload` | **不通知** | 不通知／站內通知申請人與簽核人／再加信件 | 信件需 E-c／E-d（通知範本與類型登錄）才會出現，在那之前選項顯示「尚未提供」 | `ops` |
| 客戶驗收簽回後，附件清單要鎖定嗎？ | `attach_lock_after_customer_signoff` | **否** | 否／是（`is_signed` 之後不能再新增、也不能刪） | 是＝簽回後附件清單完全凍結（含管理員）；完工單**沒有**「匯出後凍結」的概念（匯出只計次），所以鎖的時點是客戶簽回，不是匯出 | `ops`／往「是」是收緊 |

> 授權類（誰可新增）風險類＝`security`、`loosen`＝往「更寬」；預設「能讀該完工單的人」＝今天的行為（案件管理模組持有者，含工程師）——比「可編輯完工單的人（admin）」寬，這是現況，不是新放寬；想收緊可選「管理員以上」。

**寫死（系統運作不變式，附理由）**：①讀取一律先過 `_readable_note`／`uploads.path_access`（看不到＝不存在）；②檔頭（magic）檢查與副檔名白名單（安全底線，不可由設定關閉）；③實體檔絕不覆蓋、檔名用亂數（`save_document_files` 既有）；④每次新增／刪除都寫稽核；⑤附件與單據清單欄在**同一交易**更新，失敗時清掉剛存的實體檔；⑥路徑不可由使用者輸入決定（沿用 `_safe_save_dir`）。

## 4. 伺服器規則與授權順序

1. `_require_user` → `_readable_note`（讀取閘；失敗＝404「完工單不存在」）。
2. 上傳端點要把 **`existing_count`** 傳進 `save_document_files`（今天完工單端點沒傳；`UPLOAD_LIMITS_BY_SUBFOLDER` 需要 `completion_notes` 的項目，值由政策 `attach_max_files` 給）。`attachment_slots.check_upload`：
   - 單據狀態 → 套 `who_before_approval`／`who_after_approval`；不符 ⇒ 403 白話訊息（不洩漏設定鍵）。
   - `kind` 必須是啟用的種類（缺省＝`other`；舊用戶端不帶 `kind` 仍可傳）。
   - `max_files`：`len(existing)+len(incoming)` 超過 ⇒ 400。
   - `attach_lock_after_customer_signoff` 開且 `is_signed=1` ⇒ 409。
3. 既有：magic／副檔名／單檔大小檢查 → `save_document_files`。
4. 更新清單欄（單一交易）：每筆 metadata 蓋章 `kind`、`phase`（**三段**：`draft`＝核准前、`approved`＝已核准、`signed`＝已客戶簽回，取新增當下的狀態）、`uploadedAt`、`uploadedBy`（現有清單項已有 `id、filename、path、uploadedBy、uploadedAt…`；**同一份清單**，不另開第二份欄位）（metadata 的其餘鍵沿用 `save_document_files` 既有，**確切鍵集 UNKNOWN，實作前核對 `helpers/uploads.py::save_document_files`**；全是 JSON 欄內新增鍵，**無 migration**）。
5. **不更新 `updated_at`**：附件清單變動不得動樂觀鎖權杖（否則編輯草稿的人被誤擋 409）；若要讓列表顯示「附件有更新」，改在清單項內記 `uploadedAt`，由畫面自行取最大值（UNKNOWN：有無畫面依 `updated_at` 排序，實作前核對）。
5b. `attach_reopen_approval_on_upload` 開 ⇒ 同交易把狀態改回「待審核」並寫稽核；預設不動。
6. 稽核：沿用 `completion.upload_signed_files`／`completion.delete_signed_file`，`detail` 加 `kind`、`phase`、`via=slot`（不含檔名以外的個資）；刪除被 append-only 擋下也寫一筆 `completion.delete_signed_file_refused`。
6b. **簽回歷史互相對照**：核准後新增的附件，其 `phase` 章戳＋`uploadedAt` 即可對照 `signed_log`（簽回前／後）；不另寫入 `signed_log`（那是簽回事件的紀錄，不混附件）。
7. 刪除：`check_delete`——章戳 `phase` 為 `approved`／`signed` 且 `attach_post_approval_append_only` ⇒ 一律 403（含管理員）；**章戳是新增當下的狀態，取消客戶簽回（unsign）不會改章戳**，所以事後補件仍受保護；`phase=draft` 或舊檔（沒有章戳）維持今天（admin 以上）。`attach_lock_after_customer_signoff` 開且目前 `is_signed=1` ⇒ 新增與刪除都擋。
8. 讀取（下載）：`uploads.path_access` 的完工單規則（`modules/case/attachments.py` 的 `_CasePathAccess` 與 `attachments.catalog` 的 `completion_note`，標籤「完工單回簽」；**同一個 source_type，用 `kind` 區分，不新增 source_type**）加一個條件——`money_hidden_can_view=不能` 時，沒有金額檢視權限者回 404（單一閘道，不另寫第二套）。

## 5. 儲存路徑與回收桶
- 路徑不變：`uploads/completion_notes/<單號>/<uuid>.<副檔名>`（讀取授權提供者不用改路徑解析）。
- 回收桶：**只有草稿能刪**（c7 核對），adapter 打包 `signed_files_json` 與實體檔；因為本設計**不新增第二份清單**，adapter 不必改，新 metadata 鍵隨 JSON 一起；既有 adapter 已打包 `signed_files_json` 的檔案路徑；新增的 metadata 鍵隨 JSON 一起還原；**測試**：核准後新增附件 → 刪除完工單進回收桶 → 還原 → 清單與 `phase` 蓋章不變、實體檔存在。
- 備份：`uploads/` 隨每日備份鏡像（備份警示文字有提到），附件增加會增加備份體積（UNKNOWN：估算需正式機 `uploads/completion_notes` 現況大小）。

## 6. 下載與命名（A7）
- 單檔下載走既有 `uploads` 檔案服務或 `attachments` 開啟端點；檔名規則等附件前綴設計（`DOWNLOAD-NAME-ATTACHMENTS-DESIGN-T57.md`，另寫）決定：預設「案件編號_案件名_完工單附件_單號_原檔名」，原檔名先淨化、保留副檔名；無案件權限者省略案件名。
- 完工單 PDF 不變（不嵌附件）。

## 7. 客戶簽回後鎖定與核准重來
完工單**沒有匯出後凍結**（c7 核對：匯出只增加次數與紀錄）。因此鎖定的時點定為**客戶驗收簽回（`is_signed`）**：`attach_lock_after_customer_signoff`，預設不鎖（附件是補充證據）。`attach_reopen_approval_on_upload` 預設否；`revoke-approval` 在已簽回時本來就回 409，所以「新增附件讓核准重來」在已簽回的單據上不適用（不會繞過這條規則）。

## 8. 上線形態（灰色「規劃中」）
1. 功能狀態頁（E-b／MS1）登錄 `case.completion_note.attachments`：狀態＝規劃中、`available_from`＝預計里程碑（由 PM 決定；依賴 c7 的完工單堆疊）；完工單畫面顯示灰色卡片「附件（規劃中，預計 MSn）」，不出現上傳按鈕。
2. 實作完成的那一班：在既有 `completion_note` 群組加入 `attach_*` 鍵（群組數不變；`completion_note` 群組的鍵數與步驟檔 #13 的預期輸出同步）、解除灰色。**不在之前登錄**（避免出現沒有作用的選項）。
3. 在設定編輯器（S1）上線前，政策一律是預設值（與 M3 相同說法）。

## 9. 測試（紅 → 綠）
1. 純函式：`check_upload`／`check_delete` 的狀態×角色×政策組合表（含「無人」、`append_only`、`max_files` 邊界、未啟用種類）。
2. 端點：核准後新增被允許／被擋；刪除 `phase=post` 被擋（含管理員）、`phase=pre` 照今天；`kind` 缺省＝`other`；舊用戶端不帶 `kind` 仍可傳。
3. 授權：看不到完工單 ⇒ 404；`money_hidden_can_view=不能` ⇒ 無金額權限者 404、有權限者 200（正反對照）。
4. `reopen_approval_on_upload`：預設不改狀態；開啟後狀態回「待審核」且同交易稽核。
5. 回收桶往返；清單欄與實體檔的同交易（上傳中途失敗 ⇒ 實體檔被清除）。
6. 設定：群組註冊成功、預設值與基準檔一致、白話守門（問句不出現鍵名）、放寬類標高影響＋紅色橫幅（E-e）、群組數量斷言同步。
7. `limits_for` 泛化：`case_extra_expense` 行為與預設值逐位不變（回歸）。
8. 前端：`attachment-block.js` 純函式題（動作可用性判定）與靜態守門（用到的頁面載入該檔）。

## 10. 風險、UNKNOWN 與需要使用者回答的問題（只列不可逆者）

**UNKNOWN（實作前由 c7 核對）**：`save_document_files` 回傳的 metadata 確切鍵集；正式機 `uploads/completion_notes` 現況（檔數、最大檔、單據最多幾個）→ 決定 `max_files` 預設；完工單 PDF 是否未來要嵌附件；HEIC／iPhone 原檔（現況只有 `case_extra_expense` 放行 `.heic .heif`；驗收照片多半是手機拍的 ⇒ 完工單資料夾是否要放行，是引擎表 `_EXTRA_EXTS_BY_SUBFOLDER` 的一行加法，但屬安全面，需非作者審查）；縮圖／預覽（現況沒有）。

**問題**
- **Q1（已由 c7 對齊）**：「簽核完成的上傳」＝核准後與客戶簽回後仍能附驗收文件，並**分開**「客戶簽回掃描」（`kind=signed_scan`）與事後補件；同一份清單加種類，不另開清單。
- **Q2**：`post_approval_append_only` 預設「是」（核准後新增的附件連管理員也不能刪）——這比今天（管理員可刪）嚴；你是否接受預設？（可由管理者放寬，需第二位核准。）
- **Q3**：核准後新增的附件，是否要預設通知申請人與簽核人？（預設「不通知」；信件要等通知範本登錄。）
- **Q4（UNKNOWN 流程）**：`append_only` 下若真的傳錯檔，現況沒有「作廢附件」流程；是否需要「最高管理者標記作廢（不刪檔、列為作廢）」？不做的話，錯傳只能留著或由最高管理者關掉政策後刪。

## 11. 與其他設計的接點
- **E-b／功能狀態頁**：插槽宣告與灰色卡片。**E-e**：放寬類選項的紅色橫幅與影響範圍。**S1**：政策編輯畫面。**A7**：下載命名（附件前綴設計另文）。**回收桶**、**uploads 設定群組**：重用。**權限矩陣**：完工單「誰可建立」（B2）與本文「誰可附檔」是兩件事，不要混；日後 F3 能力 `case.completion.attach` 可取代 `who_*` 的角色清單（過渡期用角色名單）。
