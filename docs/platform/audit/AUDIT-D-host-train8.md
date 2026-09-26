# 事後抽查：第八班列車上改動主持的兩處（D，2026-09-26 16:23）

> 主持裁示接受、不退回，要求 D 事後抽查。題號與 origin 上的 SHA：`07547758`（主持訊息寫的是 4f96447e，那是列車 rebase 前的 SHA，不在任何 remote 分支上）、`cf7c3bb3`（原 b506fe0e）。

| commit | 抽查 | 結果 |
|---|---|---|
| 07547758 冒煙共用清單守門的正對照改從 modules.json 取已搬遷模組的前綴 | diff；`test_final_drill_tool`＋`test_system_audit`＋`test_mail_registry` 65 過 | 通過。改動前正對照依賴 L2 模組在不在，違反 §C-6；改成讀 L1 的 modules.json，方向正確 |
| cf7c3bb3 mail_settings 的 `role in (ov.get("roles") or [])` 拆出變數 | 突變「還原原寫法」⇒ `test_no_unknown_role_strings_in_backend` 紅 | 行為不變，通過。**觀察 T8-O1**：這是守門的誤判——regex `role.{0,20}?['"]([a-z_]{3,20})['"]` 把 `ov.get("roles")` 的鍵名當成角色字串。改寫法是繞過誤判；下一個人寫 `role in (cfg.get("roles"))` 還會再踩一次。建議修守門本身，例如排除 `.get("…")` 的鍵名，或者只看被比較的集合裡的字面值 |

## T8-O1 複核：wip/h-roleguard d10fc8e9（主持修守門本身；§G4 抽查，D 16:27）

- 基準 `test_system_audit` 24 過。突變 RG1「名稱含 role 就算角色」⇒ 紅（反向控制）。
- 新舊掃描器在真實樹（排除 tests）上的比較：舊正則 11 筆、新 AST 64 筆。舊有新無的只有 2 筆，都是舊正則的誤抓：`db.py` 裡的 `"role"` 鍵名，以及 `tools/audit_account_permissions.py` docstring 裡的 'superadmin'。沒有真的比對被漏掉。
- 真實樹上跟字面值比較的角色變數只有 `role` 一種拼法（36 處），沒有 `user_role` 之類只有正則才抓得到的變體。
- **觀察 RG-O1（新舊都沒守）**：SQL 字串裡的角色字面值，例如 `WHERE role='superadmin'`、`role IN ('admin', …)`、`role != 'viewer'`，在產品碼有 9 檔。拼錯的話會變成永遠查不到人，目前沒有題驗。
⇒ **T8-O1 關閉（d10fc8e9）**。
