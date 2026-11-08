# 案件發票上傳 → 通知「最高管理者」與「財務」— 設計（已確認，實作中）

> 2026-11-07｜讀程式整理，**未改任何程式**｜需求來源：MOTRIX-ERP 模組結構圖窗口轉達（非使用者逐字）：「案件管理的發票只要有人上傳成功，就發通知信給最高管理者與財務角色」

## 1. 結論（先講）

- **不用發明新角色**：「最高管理者」＝既有 `role="superadmin"`；「財務」＝既有 `role="finance"`。專案已有一個信件收件群組 **`finance`（財務角色＋超級管理員）**，正好就是這兩者，付款／匯款／勞報單待付款等信都用它。
- 做法：新增一種信件類型（`group="finance"`），在上傳成功、資料存妥**之後**呼叫 `send_registered(..., to_group=True)`。**寄信是附帶動作，失敗只記 log，不擋上傳**。
- 範圍先收斂到兩個真的是「發票」的案件上傳端點；費用單據（額外支出）的發票另列待決（§5 Q1）。

## 2. 上傳端點（讀碼確認；`attachments.py` 只是**讀取**提供者，上傳寫在 `quotations.py`）

| 類型 | 端點 | 位置 | 現況 |
|---|---|---|---|
| payment_item（款項明細發票） | `POST /api/quotations/{no}/payment/{idx}/invoice-files` | `modules/case/api/quotations.py:4956` | 多檔；存好檔 → 寫鎖重讀 `data_json` → `save_quotation_json` → commit → `_audit`（`payment.upload_invoice_files`） |
| material_invoice（叫料發票） | `POST /api/quotations/{no}/materials/{idx}/invoice-files` | 同檔 `:5103` | 同上（`material.upload_invoice_files`） |
| 兩者的「結案半解鎖」路徑 | 同一個端點，`_check_case_gate` 成立時 | 同檔 | 檔案暫存到 `_pending_case_changes`、回 `{pending:true}`；**此時發票尚未進案件**，待最高管理員核准後才由 `_apply_case_change`（`:3920` 起，action `payment_invoice_upload`／`material_invoice_upload`）併入 |
| 費用單據發票 | `POST /api/quotations/{no}/extra-expenses/{id}/files`（`kind=invoice`） | `modules/case/api/case_extra_expenses.py:1209` | 申請人／管理員／財務（待審核與簽核中補發票）／核准後補發票；另有「核准後變更」的 `addFiles` 暫存路徑 |

## 3. 設計

### 3.1 信件類型（登記一次）
新檔 `modules/case/invoice_notify.py`（比照 `payable_reminders.py`、`payslip_notify.py` 的寫法）：

```python
_mt.register("case_invoice_uploaded", "案件發票已上傳（財務）", "business", "finance", "財務",
             "案件的款項或叫料有人上傳了發票。", "請登入系統，於案件管理查看發票並核對、登錄。", owner="case")
```
- `group="finance"`＝財務角色＋超級管理員（`email_notify._group_emails` → `finance_recipient_emails`）；在職、有 email、未退訂者才收。
- 超級管理員仍可在「信件與通知收件設定」頁覆寫這一類（僅超管／自訂），個人可退訂（`owner="case"` 會自動併進個人通知偏好）。**不另做任何收件人設定。**

### 3.2 哪裡加 hook
在兩個端點的**直接路徑**，`conn.commit()` 且 `finally: conn.close()` 之後、與 `_audit` 並排處呼叫 `invoice_notify.fire_uploaded(...)`；`pending` 的暫存分支**不寄**（發票還沒進案件）。
半解鎖核准套用時：`_apply_case_change` 的 `payment_invoice_upload`／`material_invoice_upload` 分支沿用既有 `deferred_audits`（commit 後才執行）的作法，新增一個 `deferred_notices`，**commit 後**才寄——同一封信、同一內容。`material_file_upload`（一般到貨憑證附件）**不寄**。

### 3.3 信件內容（主旨寫結果；不放金額）
- 主旨：`【MOTRIX 系統通知】案件 MQ-… 有新上傳的發票`（走 `_mt.subject`）
- 列：案件編號、客戶／專案名稱、項目（款項「第 n 期／label」或叫料「料件名稱」）、上傳人（顯示名）、檔案數量
- 按鈕：前往案件管理（`case-management.html?quote=<單號>`）
- **只給檔案數量，不列檔名**（檔名常含金額；費用單據附件另有金額遮蔽規則，這裡一律保守）。
- 重複與頻率：**一次上傳請求（可多檔）＝一封信**；不跨請求合併（連續上傳 5 次會有 5 封，見 Q3）。

### 3.4 失敗不擋上傳
- `fire_uploaded` 內全部包 `try/except Exception → logger.exception`，回 bool；呼叫端不看結果。
- 寄送本身走 `_async_send`（背景執行緒，不阻塞）；沒有收件人（沒有財務或沒設 email）只記 warning。
- hook 放在 commit **之後**：即使寄信路徑壞掉，檔案與資料都已寫好。

## 4. 測試（驗收）

1. 兩個端點直接上傳成功 ⇒ `send_registered("case_invoice_uploaded", to_group=True, …)` 恰好呼叫一次（多檔也是一次），內容含案件編號與檔案數、**不含檔名與金額**。
2. 半解鎖暫存路徑（`pending:true`）⇒ **不寄**；最高管理員核准套用後 ⇒ 寄一次。
3. `material_file_upload`、刪除發票、其他一般附件 ⇒ 不寄。
4. 寄信函式丟例外 ⇒ 上傳仍回 201、資料已存、`_audit` 照寫。
5. 收件人：財務角色＋超級管理員收到；admin／sales／viewer 不收；已退訂者不收；覆寫為 `superadmin_only` 時只寄超管（沿用既有機制，驗登記後行為）。
6. 守門：`test_mail_registry`（字面 key 已登記）、changelog-follows-code（`modules/case/CHANGELOG.md`）、模組邊界／import 白名單守門（新檔屬 case 模組，用 `helpers.email_notify`／`mail_types`，與 `payable_reminders.py` 同）。無新路由，路由表 golden 不動。

## 5. 待你定（我的建議放前面）

- **Q1 費用單據（額外支出）的發票要不要一起通知？** 建議**先不含**（這一版只做案件的款項與叫料發票），理由：申請人在「草稿」階段會反覆上傳，通知會很吵；若要做，規則建議「`kind=invoice` 且狀態不是草稿（待審核／簽核中／核准後補發票）才寄」，且該流程財務本來就在待付款清單看得到。
- **Q2 上傳人自己是財務／最高管理者時，要不要寄給自己？** 建議**照寄、不特別排除**（`to_group` 無法排除個人，要排除得改成逐帳號寄而失去「收件設定頁覆寫」）；若在意再改。
- **Q3 連續上傳要不要合併？** 建議**這一版不合併**（一個上傳請求一封信）；若實務上太吵，再加「同案件同項目 N 分鐘內合併」。
- **Q4 要不要同時發站內通知（鈴鐺）？** 需求只說「通知信」，建議**只做信**；站內通知可後加（`finance_usernames()` ＋ `_notify`，勞報單就是這樣）。

## 6. 影響與風險

- 改動集中：新增 `invoice_notify.py`＋兩個端點與 `_apply_case_change` 各加幾行；不動資料表、不新增路由、不改權限。
- 風險：①信件頻率（Q3）；②寄信失敗被吞掉只剩 log（附帶動作的既定做法，與勞報單／匯款通知一致）；③半解鎖套用路徑要確認「commit 後才寄」確實在交易外（沿用 `deferred_audits`，實作時以測試 #2 鎖定）。
- 流程：此設計經你確認 → 寫碼 → hichan-7 覆核 → 併入。

## 7. 我確認了什麼、沒確認什麼

- ✅ 讀程式確認：兩個上傳端點與位置、`finance` 群組＝財務角色＋超級管理員（`mail_types.GROUPS`、`email_notify._group_emails`／`finance_recipient_emails`、`auth.FINANCE_ROLES=("superadmin","finance")`）、`send_registered(to_group=True)` 的用法與「失敗只記 log」的既有慣例（`payslip_notify.py`）、半解鎖暫存／套用路徑（`quotations.py:3920`）。
- ❌ 沒跑任何程式或測試。
- ❌ 沒查正式機有沒有設定財務角色帳號、這些帳號有沒有 email（沒有 email 就收不到信，這是資料問題，不是程式問題）。
- ❌ 費用單據那條路的「核准後變更」暫存發票（`addFiles`）我只讀到入口，未細看，若 Q1 要做需再讀。

## 8. 裁示紀錄與已知限制（2026-11-07）

- **裁示（產品窗口轉達）**：Q1 本版不含費用單據發票；Q2 上傳人是財務／最高管理者也照寄；Q3 不合併（一請求一封）；Q4 只寄信、無站內通知。
- **退訂範圍**：使用者退訂以信件類型 key 為單位（`users.notification_muted`，opt-out，空＝全收）。新類型 `case_invoice_uploaded` **不繼承** `module_activity` 等其他類型的退訂；正式機財務帳號（queena、sundy）退訂的是 `module_activity`，不影響本類型。若日後有人退訂本類型，屬使用者自選的預期行為，不是 bug。
- **已知限制（既有缺口，非本功能新增）**：財務收件對象目前以 `users.role`（finance／superadmin）判斷，不是 `duty_roles` 職責旗標；旗標開 on 之前若有人職責有異動但 role 未同步，收／不收名單可能與預期不一致。本功能走既有 `to_group=True` → `finance_recipient_emails()`，沒有新增寫死判斷，旗標切換時會跟著該函式一起改。
- **寄信可靠度**：SMTP 失敗（含 Gmail 421 限流）只記 log、不重送（既有機制）。8/10、9/2 曾因同一事件短時間連發被限流；本功能同一請求多檔＝一封；**逐檔分次上傳仍一檔一封、無跨請求合併／節流**（K 審實測連續 5 次單檔上傳＝5 封），連續分次上傳會連發。是否加合併（如同案件同項目 60 秒內一封）是產品決定，本版不做。
- **退訂後果**：因嫌吵退訂 `module_activity` 的財務（正式機 queena、sundy）仍會收到這類新信（退訂以類型 key 為單位）；上線說明請寫明。
- **永不影響上傳／核准**：通知內容組裝（`notice()`）與寄送（`send_notice`／`fire_uploaded`）都不丟例外；半解鎖套用路徑的組裝另包 try/except（在交易內，K 審建議修）。
- **實作**：`modules/case/invoice_notify.py`；兩個上傳端點 commit 後呼叫；半解鎖套用走 `deferred_notices`（commit 後）。連結 `case-management.html?q=<單號>`（該頁以 `q` 參數搜尋）。

