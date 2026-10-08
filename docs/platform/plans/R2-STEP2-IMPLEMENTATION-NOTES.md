# R2 第 2 步實作備忘：設計稿與程式的差異（wip/t48-r2-step2）

> 依據：`R2-STEPS-2-4-DESIGN.md` §2（在分支 `wip/t46-r2-design`，尚未進 platform）。使用者裁示 Q1（拒絕＋旗標）、Q2（保留 `duty-roles.html`）、Q3（既有使用者不預填）。
> 本文件只記**設計稿與現況程式不一致的地方**與建議；每項都已在本分支處理或標明留待。

## 已實作（對照 §2.1）
| 項 | 做法 | 回滾 |
|---|---|---|
| 2a 編輯視窗：角色、個人扣項、生效預覽 | `frontend/static/users-duty.js`（Alpine mixin）＋`users.html` 一個區塊；預覽走新端點 `POST /api/duty-roles/preview`（唯讀） | 程式回退 |
| 2b 變更原因 | 有高敏感差異才出現紅星必填；伺服器端 `_require_reason_if_sensitive` 本來就強制（缺 ⇒ 400），這次不改 | — |
| 2c 舊 PUT 與扣項衝突 | `routers/auth.py::_subtracted_clash`，400＋稽核 `user.put_rejected_subtract` | 旗標 `system_settings.users_put_reject_subtracted`＝`0`（預設開＝拒絕）；秒級 |
| 2d 唯讀報表讀生效權限 | 見下方差異 3；兩支都有 `--raw` 舊口徑 | 加 `--raw` |
| 2e／8a `audit_id` ＋ 禁止 REPLACE | 見下方差異 4；靜態掃描測試 `test_no_source_file_writes_permission_changes_with_replace`（含正對照與字串拼接） | 程式回退 |
| Q3 既有使用者不預填樣板 | `users.html::openEdit`：`modules` 照實顯示（空就是空）；`openCreate` 仍預填 | 程式回退 |

## 與設計稿不一致之處（與建議）

1. **§2.1 2a「預覽呼叫既有 `effective_preview`」做不到「即時更新」**：`effective_preview(conn, user)` 讀的是**已存的**綁定／扣項，使用者在視窗裡剛勾還沒存的角色／扣項它看不到。
   → 新增 `helpers/duty_roles.py::preview_whatif` ＋ `POST /api/duty-roles/preview`（唯讀）。為了「前端不自己算、預覽＝真實」，把 `resolve_raw_modules` 的合併邏輯抽成純函式 `apply_duty`，真實路徑與預覽共用；
   題 `test_preview_equals_the_real_effective_modules_for_every_combination` 窮舉（基礎類別 × 原始勾選 × 角色組合 × 扣項）證明兩者相等。**建議**：維持。

2. **§2.3 第 1 點存檔順序（先 PUT → 再綁定 → 再扣項）在「解除扣項並同時勾回該鍵」時會自己撞 2c**：要勾回的鍵仍被扣著，PUT 會 400。
   → 實作順序改為 **解除扣項 → PUT → 解除／新增角色綁定 → 新增扣項**（新增扣項放最後，因為 `set_subtract` 拒絕「同時是個人勾選」的鍵，PUT 先把勾選存好才不衝突）。每步失敗即停，UI 明講已完成／未完成。**建議**：維持；步驟檔手動驗證項加「解除扣項＋勾回」一例。

3. **§2.1 2d「兩支都改呼叫 `effective_modules`」對 `finance_role_impact_report.py` 會讓報表永遠是空的**：`effective_modules` 依財務規則把非財務角色的 `cashier／finance／financial_view` 一律拿掉，而這份報表正是要列出「勾了財務鍵、上線後會失去的人」。
   → `audit_account_permissions.py` 用完整 `effective_modules`（符合設計）；`finance_role_impact_report.py` 只把職責角色與扣項套到勾選上（`resolve_raw_modules`）、**刻意不套財務規則**，輸出標示口徑。**建議**：維持；若使用者要完整生效口徑，另開 `--effective-full`。

4. **§2.1 2e「`audit_id` 填值」：`permission_changes` 有 UPDATE 觸發器（只增不改）**，路由事後補不了。
   → `audit_log` 那一筆改在服務層、與 `permission_changes` **同一個交易**寫入（`_write_audit`），`audit_id` 在 INSERT 時帶入；`routers/duty_roles.py` 原本六處 `_audit(...)` 拿掉（否則同一個動作兩列），動作名稱沿用 `duty_roles.*`。
   沒有實質變更的 `update_role` 早退：與舊路由一致，仍留一筆 `audit_log`、不寫 `permission_changes`（題 `test_noop_role_update_...`）。**建議**：維持。

5. **§5.2 建議「先把 `users.html` 角色／權限區塊抽成獨立片段」未做**：新邏輯放進 `static/users-duty.js`（mixin），`users.html` 只多一個約 65 行的區塊與 5 處接線；既有 80 KB 檔案沒有搬動。
   **建議**：下一個碰 `users.html` 的班次再做行為不變的抽離（Alpine 模板不能放在 JS 檔，需要 partial 機制，不是一個 commit 的小事）。

6. **§8 已知未驗證項已查實**：`users.html` 對空 `modules` 的樣板預填有兩處——`openEdit`（編輯視窗，已改）與 **`hasAccess(user, mod)`（使用者清單的存取矩陣）**。後者仍對空 `modules` 用樣板顯示「有權限」，但後端 `effective_modules` 沒有這個回退（實際是零權限）——清單顯示與實際不一致。
   **本步沒改**（設計只涵蓋編輯視窗）。**建議**：第 3 步（Q4 重新啟用＝全空）一併改，否則停用回收後清單會顯示樣板權限；風險低。

7. **無 `DELETE`／migration**：`audit_id` 欄 R1 已建（core migration 7），本步沒有 migration。

## 上線步驟檔補充（§2.8）
快照 → 套用 → `verify`（零差異）→ 手動驗：①開一位使用者編輯、不改任何東西存檔，`users.modules` 不變（唯讀 SQL 比對）；②綁一個角色、只存檔，`users.modules` 位元組不變；③有扣項的人，PUT 勾回被扣的鍵 ⇒ 400（可把旗標 `users_put_reject_subtracted` 設 0 退場）；④`permission_changes` 新列的 `audit_id` 非空。
