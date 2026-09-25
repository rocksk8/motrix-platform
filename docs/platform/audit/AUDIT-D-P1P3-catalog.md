# 稽核：P1 能力目錄＋P3 模組可自訂點（合回前稽核）（D 稽核，2026-09-26）

> 依 PLAYBOOK §E、CORE-SPEC §9d。稽核者 D 沒有寫過任何受稽核的程式碼。**合回前稽核**：必修關閉之前不可以合回（主持指示）。
> 對象：`origin/wip/cloud-p1p3` `6ac64b45`（基底 `66982bbf`）。規格：CUSTOMIZATION-SPEC §3.8、§3.9（章節號暫定）。
> 稽核在分支原樣上進行（detached `D:\MOTRIX-PLATFORM-D`），Python `D:\MOTRIX-PLATFORM\.venv312`（只用、未改）。
> 分級：**必修**／**建議**／**觀察**。關閉規則：被稽核者回覆後，由 D 確認才關。
> 縮寫：`CU`＝`backend/core/customization.py`、`CA`＝`backend/core/catalog.py`、`TC`＝`backend/tests/platform/test_platform_catalog.py`。

## 0. 結論

- 目錄「只收集、不擁有清單」、schema 嚴格驗證、loader 擋格式錯誤、區段擁有者唯一、缺擁有者列 gaps，這些都做到了，而且都有題目。
- D 自做突變 **16 項全紅**（§2）。作者說的「突變 15 項全紅」沒有留下清單（commit 訊息、RUN-PLAN、測試檔都沒有），無法照原清單抽查，所以改由 D 自己設計。
- 主持指定的三個重點：
  1. **「程式沒有提供的選項不可以出現」：只在目錄的輸出這一層成立**。`check_layout` 是規格指定給 P5／P9 用的守門，它看不到目錄已經藏起來的點；另外有兩種「選項」完全沒有驗（P-M1、P-M2）。
  2. **與 STAGE-C 的 `pages[].menu`**：資料格式沒有衝突（只讀、不重複宣告）。有兩處要先說清楚：G2 守門檔會兩邊同時改；側欄的使用者自訂同時出現在兩份規格裡（P-S3、P-O2）。
  3. 突變：見 §2。
- **必修 2 項**：P-M1、P-M2。建議 4 項、觀察 3 項。
- 合回注意：試 rebase 到 origin/platform `dc361073` 時，只在 `core/CHANGELOG.md`、`core/registry.py`、`l1_interface_snapshot.json` 衝突（§C-7 預期內），`core/loader.py` 自動合併成功。自動合併之後，loader 與 98d43855（`mount_modules`、停用清單）一起執行的行為**沒有驗**：D 在稽核樹解開版號衝突以便跑題的動作被權限擋下，所以沒做。依 RUN-PLAN，合回前要跑全量。

基準（分支原樣）：`TC`＋`test_module_package_files`＋`test_core_loader` **90 passed**。

## 1. 逐項驗收

| 規則 | 驗收 | 證據 |
|---|---|---|
| §3.8 目錄只收集；端點取自實際路由 | ✅ | CA:52-88（新舊 FastAPI 都攤平）；突變 P10 紅 |
| 引用不存在端點／版型的點不列、列 problems | ✅（只在目錄輸出） | CA:91-112、162-173；突變 P10、P11、P12 紅。守門層見 P-M1 |
| 擁有者唯一、區段失敗隔離、缺擁有者列 gaps | ✅ | CA:32-42、146-151；突變 P13、P14 紅 |
| 僅超級管理員 | ✅ | `routers/platform_catalog.py:38`；突變 P16 紅 |
| providers 契約版本明寫 null（不猜） | ✅ | CA:127-128 |
| §3.9 schema 嚴格（不認得的鍵是錯、schema 看不懂不猜） | ✅ | CU:52-63、111-113；突變 P05、P09 紅 |
| 參照：頁面要宣告、選單項是本頁按鈕、perm 在 permissions、欄位在實體裡 | ✅ | CU:139-150、167-269；突變 P06、P07、P08 紅 |
| loader：格式錯誤不載入；沒有 customization 照常載入 | ✅ | `core/loader.py:99`；突變 P15 紅 |
| 點與操作表 | ✅ | CU:28-40；突變 P03 紅（核心欄位加 hide／relabel） |
| 排版守門 `check_layout` | ⚠ | 已登記的點、允許的操作、欄位換容器都擋（突變 P01、P02、P04 紅）；**漏洞見 P-M1、P-M2、P-S1、P-S2** |
| G2：每個模組都要寫 customization | ✅ | `test_module_package_files.py:39-43` |
| 與 STAGE-C `pages[].menu` 並存 | ✅ 格式 ／ ⚠ 規格分工 | 見 P-S3、P-O2 |

## 2. 突變（D 自做；每項都用 `git checkout` 還原並核對內容）

| 突變 | 結果 | 轉紅的題 |
|---|---|---|
| P01 `check_layout` 對未登記的 target 放行 | 🔴 | `test_layout_touching_unregistered_or_forbidden_is_rejected[程式沒有提供的欄位]` 等 3 |
| P02 不檢查該點允許的操作 | 🔴 | 同上 `[隱藏核心欄位]` 等 3 |
| P03 核心欄位可 hide／relabel | 🔴 | `test_core_and_display_fields_get_different_ops` 等 3 |
| P04 欄位可移到別的容器 | 🔴 | `…[欄位搬到別張表單]` 等 2 |
| P05 不驗 schema 版本 | 🔴 | `test_broken_manifest_is_rejected_with_its_location[看不懂的…]` 等 3 |
| P06 頁面不必在 pages[].path | 🔴 | `…[頁面不在…]` |
| P07 選單項不必是本頁按鈕 | 🔴 | `…[選單項目不是按鈕]` |
| P08 perm 不驗 | 🔴 | `…[按鈕權限不在…]` |
| P09 不認得的鍵放行 | 🔴 | `…[不認得的頂層鍵]` 等 2 |
| P10 端點不存在不報 | 🔴 | `test_point_with_missing_endpoint_is_hidden_and_reported` |
| P11 版型不存在不報 | 🔴 | `test_output_with_missing_template_is_hidden_and_reported` |
| P12 有問題的點照樣列出 | 🔴 | 上面兩題 |
| P13 同一區段允許兩個擁有者 | 🔴 | `test_two_owners_for_one_section_is_an_error` |
| P14 區段例外不隔離 | 🔴 | `test_broken_section_does_not_break_catalog` |
| P15 loader 不呼叫 `require_valid` | 🔴 | `test_loader_refuses_module_with_broken_customization` |
| P16 非超級管理員可讀 | 🔴 | `test_catalog_endpoint_superadmin_only` |

探針（直接呼叫，用 TC 的合成模組 `_manifest()`；把刪除按鈕的端點改成不存在的 `DELETE /api/zz-syn/nope`）：

| 探針 | 結果 |
|---|---|
| 目錄計算 problems | 藏起 `zz_syn:zz-syn.html/action:del` ✅ |
| `check_layout(points(manifest), [{op:"hide", target:<藏起的那一點>}])` | **`[]`（放行）** ⇒ P-M1 |
| 選單點 `row` 的 `items` | 仍然是 `[…/action:edit, …/action:del]`，藏起的按鈕還在選單裡 ⇒ P-M1 |
| `{op:"select_template", target:<輸出點>, template:"不存在"}` | **`[]`（放行）** ⇒ P-M2 |
| `{op:"move", target:<區塊>, to:<按鈕>}` | `[]`（放行）⇒ P-S1 |
| `{op:"hide", target:<按鈕>, evil:1}` | `[]`（不認得的鍵放行）⇒ P-S2 |
| 欄位移到另一張表單的區塊 | 擋下 ✅ |

## 3. 發現

### 必修

**P-M1　`check_layout` 看不到目錄藏起來的點；選單仍然引用被藏起的按鈕**
- 位置：CU:360-393 以傳入的 `pts` 為準；CA:163-172 的「藏起」只存在於 `build()` 的輸出裡。規格 §3.9 寫「P5 的 layout 驗證器與 P9 都必須呼叫它」，但沒有規定傳哪一份 points。最自然的呼叫方式是 `check_layout(customization.points(manifest), ops)`，而這一份包含引用了不存在端點的點。
- 為什麼是必修：主持點名的重點就是「程式沒有提供的選項不可以出現」。目前只有目錄**畫面**看不到，資料層守門照樣放行。P9 只要照規格呼叫，就能把一個不存在的按鈕排進版面（顯示、改名、移動），而這正是守門要擋的情況。選單點的 `items` 也沒有跟著過濾，所以就算用目錄輸出的 points 當輸入，選單仍然帶著被藏起的按鈕。
- 重現：見 §2 探針（TC 的 `_manifest()`，把 `actions[2].endpoint` 改成不存在的端點）。
- 建議修法：
  - 提供唯一的入口，例如 `catalog.layout_points(module_key)`：回傳已過濾的點（與目錄輸出同一份），選單 `items` 同步過濾。規格改寫成「P5／P9 必須用這一份」。
  - 或者讓 `check_layout` 接受 problems 清單。
  - 另外，**模組沒有載入**（停用、未授權）時，它的點也不可以通過。
  - 補題：藏起的點 ⇒ `check_layout` 擋；選單不含藏起的按鈕；未載入模組的點 ⇒ 擋。

**P-M2　`select_template` 選的版型沒有驗證**
- 位置：CU:391-392 只驗 relabel 的 label。`select_template` 要選哪一個版型（ops 裡的參數）完全沒有檢查，參數名稱也沒寫進規格。
- 為什麼是必修：輸出版型是「程式提供的選項」。目前可以選一個不存在的版型，而目錄的 `outputs.templates` 明明有清單，守門卻沒有用它。
- 建議修法：
  - 規格定下參數名（例如 `template`）。
  - `check_layout` 驗證它在 `outputs` 區段的 templates 裡；目錄沒有 outputs 區段時一律擋（與 `output_problems` 同一個判準）。
  - 補題與突變。

### 建議

- **P-S1　只有欄位的 `move` 有容器限制**：區塊（section）、按鈕、選單、側欄的 `to` 只要是登記過的點都放行（探針：區塊可以移到按鈕底下）。建議依 kind 定 `to` 的合法種類：區塊只能在同一張表單、按鈕只能在同一頁或選單裡、側欄等 STAGE-C D4 裁示。
- **P-S2　排版操作本身是寬鬆驗證**：`check_layout` 不擋不認得的鍵（探針 `evil:1` 放行），與 §3.9「嚴格」的原則不一致。依〈寬鬆驗證會靜默丟掉欄位〉，打錯鍵名（例如 `lable`）會回成功，而改名沒有生效。建議每一種 op 列出允許的鍵。
- **P-S3　G2 守門檔會兩邊同時改**：本分支在 `test_module_package_files.py` 加「每個模組都要寫 customization」；STAGE-C 的 G2 也要在同一檔加 `pages[].path` 存在、`menu.icon`／`menu.group` 驗證。兩者合回的順序要排好，後合的一方 rebase 時要重跑整檔，並檢查合成模組 fixture（line 72）同時滿足兩邊的規則。
- **P-S4　作者的突變清單沒有落地**：「突變 15 項全紅」只寫在 RUN-PLAN 的一句話裡，看不到是哪 15 項、怎麼重現。依〈主持人的記憶是負債〉，建議突變清單寫進測試檔的說明或 audit 回覆欄。

### 觀察

- **P-O1　sidebar 點目前沒有真實資料**：origin 上沒有任何模組的 `pages[].menu` 是物件（tender_radar 只有 `{"path": …}`），所以 sidebar 點只在合成模組上驗過。C3 合回之後，要在真實模組上重跑「登記＝列出」那一題。
- **P-O2　側欄的使用者自訂出現在兩份規格**：STAGE-C §8「不在本階段」寫「選單的使用者自訂（隱藏、排序、改名）屬 CUSTOMIZATION-SPEC，建在本階段的 menu API 之上」；本分支 §3.9 的 sidebar 點已經給了 move／hide／relabel。兩者一致，但實作要落在哪裡（`/api/platform/menu` 套用使用者版面，或 P9 自己套），需要在 C3／P9 之前定案，避免做兩次。「move 可否換群組」本分支已經列為待裁示。
- **P-O3　點引用的端點比對用字串全等**：`"METHOD /path"` 與路由逐字相同（含 `{param}` 名稱）。模組改了參數名稱（例如 `{watch_id}` 改成 `{id}`），點就會被藏起並列在 problems。這是正確的行為（fail closed），但作者要知道：改路由參數名稱時，module.json 要跟著改；目錄 problems 不為空時，守門題會紅。

## 4. 回覆欄（被稽核者填；D 確認後才關）

| # | 回覆（修正／不修＋理由／需使用者裁示） | commit | D 確認 |
|---|---|---|---|
| P-M1 | 修正。唯一入口 `catalog.layout_points(module_key=None)`，過濾只在 `catalog._module_points` 一處：不存在的端點／版型、選單 items 去掉被藏起的按鈕（全部被藏起 ⇒ 選單也藏起並列 problems）、未載入模組沒有點。`build()` 與排版守門都經它；守門搬到 `catalog.check_layout(module_key, ops)`，`customization.points／check_layout` 改私有 `_raw_points／_check_ops`。守門 `test_only_one_way_to_get_points`（產品碼掃 AST，只准 `_module_points`／`check_layout` 呼叫；附正對照）。補稽核探針題（刪除按鈕端點改成不存在 ⇒ hide／relabel／move 都擋）、選單去掉藏起按鈕、未載入模組、指定模組篩選。突變 M1a～M1d 皆紅；未載入一項無程式突變（來源只有 registry.loaded()），以同一描述 register 後轉通過作正對照 | 6cacd083 | |
| P-M2 | 修正。規格定參數名 `template`（必填）；須在輸出點的 `templates`（＝目錄 outputs 區段的版型）裡；outputs 區段不在 ⇒ 輸出點不在 layout_points ⇒ 一律擋（與 output_problems 同一判準）。突變 M2a、M2b 皆紅 | 6cacd083 | |
| P-S1 | 修正。`MOVE_DEST_KINDS`：列表欄 ⇒ 原列表、表單欄 ⇒ 同表單區塊、區塊 ⇒ 原表單、按鈕 ⇒ 同頁頁內選單；匯出／頁內選單／側欄不可帶 `to`。突變 S1b～S1e 紅；S1a（種類檢查）為等價突變——每種可帶 to 的點都另有更嚴的容器檢查，理由寫在 `_mutations_p1p3.md` | 6cacd083 | |
| P-S2 | 修正。`OP_KEYS` 列出每種操作的必填／選填鍵，不認得的鍵擋（`lable`、`evil`、側欄 `group`）；reorder（`order`＝恰好是目前子點）、add_section（`key`、`label`，不可撞名）、move（`index` 非負整數）一併定案並驗證。突變 S2a～S2c 紅 | 6cacd083 | |
| P-S3 | 處理：排在 B 的 C1／C3 之後上列車；後合者（本包）rebase 時重跑 `test_module_package_files` 整檔，合成模組 fixture 同時滿足兩邊規則。tender_radar 版號 C3 用 1.1.0、本包改 1.2.0（C3 上 origin 後處理） | — | |
| P-S4 | 修正。突變清單落地 `backend/tests/platform/_mutations_p1p3.md`：稽核 P01～P16（依新程式位置重做）＋本次 M／S／O 15 項，共 31 項 30 紅、S1a 等價突變附理由；每項列原文→突變與預期轉紅的題 | 70737644 | |
| P-O1～O3 | O1：C3 合回後在真實模組重跑 `test_every_loaded_module_lists_all_its_points_without_problems`（rebase 到 C3 時一併跑）。O2：定案寫進 CUSTOMIZATION-SPEC §3.9——以 STAGE-C 為準，套用落在 `/api/platform/menu`，P9 不另套；個人層只調顯示與排序（sidebar ops＝move（index，原群組內）／hide／show），v1 不換群組（`to`、`group` 一律擋）、不改名（STAGE-C §8 列的改名延後）；突變 O2 紅。O3：知悉，行為不改（fail closed） | 6cacd083 | |
