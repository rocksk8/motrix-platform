# 稽核：主持的 U15 使用者表單——系統技術類信件不可以讓最後一位收得到的超管退訂（wip/h-u15）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。合回前稽核。
> 對象：`origin/wip/h-u15` `2f79d454`（`ea0dcdcd` 實作＋題、`2f79d454` 重產產生檔）：`routers/mail_settings.last_superadmin_blockers`，由 `PUT /api/users/{id}` 在改 `notification_muted` 時呼叫。

## 0. 結論

**必修 1、建議 2、觀察 1。** 主持點名四項：①判準與寄信端一致：成立（一處邊角見 O-1）；②覆寫為 custom 不擋：取捨可以接受，但需要配套（S-1）；③其他會讓「最後一位」消失的路徑：**改角色、清空 Email 沒擋（必修 M-1）**；刪帳號、停用帳號原本就擋；④突變：3 項中 2 紅（S-2）。

## 1. ①判準與寄信端

| 條件 | 寄信端（`email_notify._users_emails`／`_only_superadmins`） | U15（`last_superadmin_blockers`） |
|---|---|---|
| 啟用 | `active=1` | 自己：`me["active"]`；別人：`active=1` ✅ |
| 有 Email | SQL `email IS NOT NULL AND email != ''` | 別人：同 SQL ✅；**自己：`(me["email"] or "").strip()`**（見 O-1） |
| 未退訂 | `notification_prefs.is_enabled` | 同一支 ✅ |
| 角色 | 系統類 6 種（cert_expiry、backup_stale、disk_space_low、backup_error、geo_quota_warning、system_test_mail）的 group 都是 `superadmins`；`superadmin_only` 模式也是超管 | `role='superadmin'` ✅ |

## 2. ②custom 不擋

custom 模式由設定頁的指定名單寄出（`_custom_emails`），名單由超管決定，退訂時不擋可以接受；**但 custom 名單本身可能是空的，或者名單上的人全都退訂了、沒有 Email**，這時系統類信件一樣沒有人收（寄信端只記 ERROR）。見 S-1。

## 3. ③其他路徑（D 以暫時探針實測，跑完即刪）

先讓 boss、a 退訂某一類系統信件，b 成為最後一位收得到的超管，然後：

| 路徑 | 結果 | 判定 |
|---|---|---|
| `PUT /api/users/{b}` `{"email": ""}` | **200**，收得到的超管變成 **0 位** | **M-1** |
| `PUT /api/users/{b}` `{"role": "admin"}` | **200**，收得到的超管變成 **0 位** | **M-1** |
| 刪帳號 `DELETE /api/users/{id}` | 原本就擋：「不可刪除超級管理員帳號」（`auth.py`） | ✅ |
| 停用 `PATCH /api/users/{id}/active` | 原本就擋：「不可停用超級管理員帳號」 | ✅ |

## 4. ④突變（`test_u15_last_superadmin_mute_2026_09_26.py`，3 題，-n 4）

| # | 突變 | 結果 |
|---|---|---|
| U15a | 一律放行 | 紅（2） |
| U15b | 別人不看 Email | 紅（`test_a_superadmin_without_email_does_not_count`） |
| U15c | 業務類信件也擋 | **存活** ⇒ S-2 |

## 5. 發現

### 必修

**M-1　同一支 PUT 清空 Email 或改角色，可以讓「最後一位」消失**
- 守門和這兩個欄位在同一支端點（`PUT /api/users/{id}`），但只看 `notification_muted`。程式註解寫的是「永遠至少一人收得到」，而同一個請求就能讓它不成立。系統技術類信件包含備份失敗、磁碟空間不足、憑證到期；收不到時，寄信端只記一行 ERROR。
- 修法：`last_superadmin_blockers` 改成以「這個請求套用之後的狀態」判斷（新的 role、email、muted 一起算），PUT 在這三個欄位任一有變時呼叫它；補兩題：最後一位被清空 Email ⇒ 400、被改成 admin ⇒ 400，而且 DB 不變。

### 建議

- **S-1　custom 模式的名單也要「至少一人收得到」**：在設定頁儲存 custom 覆寫時，對系統類型檢查名單裡至少一人收得到（啟用、有 Email、未退訂），否則拒絕；或者在退訂判斷裡，把 custom 名單當成收件人一起算。
- **S-2　業務類「不受限」的正對照沒有打到**：`test_positive_controls` 的業務類信件從來沒有處在「只剩一位」的狀態，所以把擋的範圍擴大到業務類照樣全過（U15c）。建議補一題：其他超管都退訂同一種業務信件，最後一位退訂它 ⇒ 200。

### 觀察

- **O-1　「自己有沒有 Email」用了 `.strip()`，寄信端沒有**：Email 只有空白時，寄信端會當成有 Email（寄了會失敗），U15 對自己卻當成沒有 Email（退訂不擋）。兩邊都是邊角，建議判準統一（例如都用 `TRIM(email) != ''`）。

## 6. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| M-1 | 以「套用這個請求之後」判斷（muted／email／role）；清空 Email 與改成非超管參數化兩題 | wip/h-u15 a6aaa85a | ✅ 13:50 D：突變 V1（忽略新 Email）、V2（忽略新角色）各紅對應參數 ⇒ **關閉（a6aaa85a）** |
| S-1～S-2 | S-1 `custom_override_blockers`：系統類型存成 custom 時名單至少一人收得到；S-2 業務類「只剩一位」照樣可退訂的正對照 | a6aaa85a | ✅ 13:50 D：V3（custom 名單不檢查）紅、V4（業務類也擋）紅（先前存活的 U15c 現在會紅）⇒ **關閉（a6aaa85a）** |
| O-1 | `_has_email` 與寄信端 SQL 同判準、不 strip | a6aaa85a | ✅ 13:50 程式已統一 ⇒ **關閉（a6aaa85a）**；小觀察：V5（改回 strip）存活——沒有「只含空白的 Email」的題，影響小 |

## 7. a6aaa85a 複核的新觀察（D，13:50）

- **O-2　custom 名單只在「存檔那一刻」檢查**：`custom_override_blockers` 在設定頁存成 custom 時擋；之後名單上的人退訂、被清空 Email、被改角色，`last_superadmin_blockers` 對 custom 類型是跳過的（由 set_mail_recipients 負責），所以名單可能在事後變成沒人收得到。與 M-1 同一類，但發生在 custom 那一側；建議 `PUT /api/users/{id}` 套用後也對 custom 系統類型呼叫 `_custom_emails` 檢查一次。
- 基準 7 passed（-n 4）；突變 5 項 4 紅。

## 8. h-u15-2 複核（D，14:09，`134328be`，已 rebase 到第七班）

- `git range-diff`：`ea0dcdcd`→`99ce3558`、`32f3a8c8`→`48632818` **相同（=）**；產生檔重產（rebase 後預期不同）；新增 `0b12bf4f`（O-2）、`134328be`（重產）。
- **O-2 ✅ 關閉（134328be）**：收件人一律以「套用這個請求之前、之後各幾人收得到」判斷，custom 名單也算（`in_group`：帳號在名單或角色在名單，與寄信端 `_custom_emails` 同判準）。D 突變：W1（custom 不算名單）紅、W2（不套用新狀態）紅 5、W3（只含空白的 Email 當成沒有）紅（V5 的題補上了）。基準 9 passed。
- **小建議 S-3**：W4（拿掉「套用前 >0」這一半）存活。實際影響：某類信件在修改前**就已經**沒人收（例如舊資料所有超管都退訂），拿掉這一半之後，任何人任何修改都會被擋成 400、連修正都做不到。程式目前是對的，建議補一題「修改前已經 0 人 ⇒ 其他修改照樣放行」鎖住它。
- 只含空白的 Email：與寄信端同判準算「有」，不擋，D 同意。要不要在存檔時擋掉只含空白的 Email，是另一個格式驗證問題；影響只有「那位使用者收不到信」，列為觀察，不開建議。

