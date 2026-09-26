# 稽核：B 的路由歸屬明列（wip/b-routes；合回前）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。
> 對象：`origin/wip/b-routes` `ce329534`（月台登記 `27f6a58b`）：modules.json 群組可寫 `"routes"`，明列優先於前綴；`dep_scan.check_route_ownership` 報四種錯誤；新題 `tests/platform/test_route_ownership.py`（7 題）；補上 origin 原本歸屬不明的路由（L1 `/api/layout`、`/api/mail-types`；M10 明列 `/api/quotations/{quote_no}/network-plan`）。

## 0. 結論

**必修 1、建議 1。** 主持點名的三件事中：①四種錯誤各自的突變都紅；②萬用寫法有範圍過寬的風險（建議）；③五條路由的歸屬正確。但新的真實樹守門在模組被拿掉時會紅（RT-M1）。

## 1. ①四種錯誤的突變（`test_route_ownership.py`，基準 7 passed）

| # | 突變 | 結果 |
|---|---|---|
| RT1 | ① 同一條路由被兩個群組明列：不報 | 紅（`test_rc_same_route_listed_by_two_groups_is_an_error`） |
| RT2 | ② 明列的路由在自己群組對不到：不報 | 紅（`test_rc_explicit_route_that_does_not_exist_in_the_group_is_an_error`） |
| RT3 | ③ 明列搶到別的群組的路由：不報 | 紅（`test_rc_explicit_listing_cannot_claim_another_groups_route`） |
| RT4 | ④ 沒明列、前綴也不屬於自己（歸屬不明）：不報 | 紅（`test_rc_route_without_explicit_listing_and_foreign_prefix_is_an_error`） |
| RT5 | 萬用寫法改成完全比對 | 紅（3） |

## 2. ②萬用寫法的範圍

`_route_matches` 的萬用寫法是純字串前綴比對，**沒有分界**。D 實測 `/api/reports/t100-export*`：
- `/api/reports/t100-export`、`/api/reports/t100-export/vouchers` ⇒ True（預期內）
- `/api/reports/t100-exporter`、`/api/reports/t100-export-archive` ⇒ **True**（可能不是本意）
- `/api/*` 對 `/api/quotations` ⇒ True

吃到**別的群組**的路由時，錯誤 ③ 會報，所以不會安靜地把別人的路由搶走；吃到的若是**自己群組**以後新增、而本意屬於別處的路由，就不會有人發現。目前 modules.json 還沒有任何萬用寫法。

## 3. ③五條路由的歸屬

| 路由 | 定義在 | 歸屬 | 判定 |
|---|---|---|---|
| `/api/layout/{module_key}` | `routers/definitions.py:277` | L1（`router:definitions` 在 L1 units，沒有模組認領） | ✅ |
| `/api/mail-types`、`/{key}/recipients`、`/receivable` | `routers/mail_settings.py:42,55,110` | L1（`router:mail_settings` 在 L1 units） | ✅ |
| `/api/quotations/{quote_no}/network-plan` | `modules/netplan/api.py:113` | M10 明列（前綴屬 M01） | ✅ 路由由 M10 的 router 提供：M10 不在 ⇒ 路由消失（404），與 M01 無關；M01 不在 ⇒ 路由還在，由 case.access 判定回 404（c-case-access-3 `test_both_paths_agree_when_m01_is_absent` 已驗）。M01 的 `routers/quotations.py` 沒有 `/api/quotations/{x}/{y}` 這種會蓋掉它的參數路由 |

## 4. 發現

### 必修

**RT-M1　`test_real_tree_has_no_route_ownership_errors` 在模組被拿掉時會紅**
- D 實測：拿掉 `modules/netplan` 後，這一題紅，錯誤是 `M10 明列的路由 '/api/quotations/{quote_no}/network-plan' 在該群組的 router 裡不存在`（錯誤 ②）。模組全在時 7 passed。
- 這一題是新題，不在 §B-11 與 `core_only_rc.ALLOWED` 的允許清單上，所以第一班 core-only 就會紅（與 BM-M2 同一類）。
- 修法：錯誤 ② 只對「已安裝」的群組檢查（群組是 L2 模組、而 `module_installed("modules/<key>/")` 為假時略過它的明列）；補反向控制「拿掉明列路由的那個模組 ⇒ 不報 ②、其他錯誤照報」。或者依 BM-M2 的前例列入允許清單，但這一題不是「產生檔一致性」，D 建議前者。

### 建議

- **RT-S1　萬用寫法要有分界**：`*` 前面要求是 `/`（例如 `/api/reports/t100-export/*`），或比對時要求下一個字元是 `/`、`{` 或字串結尾；另禁止只有 `/api/*` 這種整段前綴的寫法。補一題：`t100-export*` 不可以吃到 `t100-exporter`。

## 5. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| RT-M1 | 錯誤 ② 只對已安裝的群組報（`_installed_groups`：L1、未搬遷群組、`modules/<key>/module.json` 在）；補兩題反向控制 | wip/b-routes-2 3b38f6c6 | ✅ 11:55 D：拿掉 netplan（D 樹實刪、`ls backend/modules` 確認不在）⇒ **17 passed**（修正前紅 1）；模組全在 17 passed；突變「不看已安裝」「已安裝恆假」皆紅 ⇒ **關閉（3b38f6c6）**。小觀察：已搬遷群組若沒寫 `key` 會被當成永遠沒裝（② 不再報）；目前 4 個已搬遷群組都有 key，建議補一條「已搬遷群組必須有 key」 |
| RT-S1 | 萬用只接受結尾 `/*`、分界＝`/`、`/*` 前至少第三層；新增錯誤 ⑤ | 3b38f6c6 | ✅ 11:55 D：突變「格式不檢查」「分界拿掉」「第三層限制拿掉」皆紅 ⇒ **關閉（3b38f6c6）** |

## 6. 自查（主持提醒 MSYS 路徑轉換使 sparse 排除失效，11:55）

D 沒有在 Git Bash 下自己建過 sparse 樹：所有 §B-11 反向控制都在 D 自己的稽核樹以刪資料夾進行，並在跑之前 `ls backend/modules` 確認；唯一用到 sparse 的是 `core_only_rc.py`（從 Python 呼叫 git，不經 MSYS 轉換），該次執行中 D 查過拋棄式樹的 `backend/modules` 只有 `__init__.py`（AUDIT-D-B-G1 §7）。⇒ 不受影響。

