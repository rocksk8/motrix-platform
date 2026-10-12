# S1 設定中心「可編輯」工作計畫（T57）

> 2026-10-13／1d。分支 `wip/t57-s1-settings-edit-r1`，基底 `origin/train/m2-int-r9`（`c87079be2`）。設計依據：`SETTINGS-CENTER-DESIGN-T54.md`（`origin/wip/t54-n39-settings-design-r2`）＋ 欄位版面框架 r8（E-e `impact_scope`、§16.6 橫幅標準、§17.2）。**本文是開工前的作業計畫；程式分小提交陸續落地，每個提交附對應 CHANGELOG。**

## 0. 結論（先看）

1. M2 基底上**後端 S0 已經大致齊全**（`routers/settings_center.py`：群組清單／明細／儲存／待生效／核准／撤銷／預設組／公開值；`helpers/settings_registry.py`：`publish()` 含放寬→待生效→雙人核准、`profiles`、`materialize_due`；`helpers/config_ledger.py`）。**缺的是『可編輯的畫面』與四個後端缺口**：目前 `frontend/pages/settings-center.html` 只是**唯讀表格**（顯示目前值／建議／範圍／影響），沒有任何輸入、儲存、差異預覽、待生效處理、版本還原。
2. 盤點時發現三個需要在 S1 處理的**實質問題**（§1 G2～G4），其中 G2 是**繞過雙人核准的安全缺口**，列為 S1 第一個提交。
3. S1 範圍 = 編輯畫面＋E-e（`SettingDef.impact_scope` 欄位與驗證、橫幅渲染）＋ 預覽（dry-run）＋ 即時影響＋ 版本／差異／還原流程＋ 待生效處理。**工量 7.4 pd**（設計稿原估 S1≈4 pd，未含 E-e、dry-run、G2～G4）。
4. 底層列車檔案（§6）僅 3 支 L1 檔；前端與測試不佔底層閘門。

## 1. 現況盤點與缺口（已核對程式，非推測）

| 項 | 現況（m2-int-r9） | 缺口 |
|---|---|---|
| G1 畫面 | `settings-center.html`（5.5KB）唯讀：左無群組樹、無輸入、無儲存；`x-for` 逐群組列欄位 | 整頁改為編輯器（§3） |
| G2 **繞過** | 通用端點 `PUT /api/definitions/{kind}/{key}/draft`、`POST …/publish`、`POST …/restore/{version}`（`routers/definitions.py:252/289/375`）對 kind `setting_group` **沒有任何特別處理**——任一 superadmin 可直接寫草稿並發布設定群組，**不經 `settings_registry.publish()`**：不分即時／待生效、不要求雙人核准、不寫 `config_changes`（只留 `definitions.publish_unreviewed` 稽核）。放寬類設定（如縮短 `audit_log_keep_days`）因此可單人立即生效 | **S1-1**：`setting_group` 設為『受管 kind』，通用寫入端點一律 409『請到設定中心調整』；GET（版本、差異）保留 |
| G3 還原與待生效互相抵銷（待測試證實） | `config_ledger.restore_version()` 先呼叫 adapter（`settings_registry._restore` → `publish()`）再 `cancel_pending_for()`。若還原的舊值屬『放寬』，`publish()` 寫出的**待生效項會被緊接著的 `cancel_pending_for` 撤銷**，結果還原『看似成功、其實什麼都沒生效』；反之收緊時舊待生效項要先被取代才正確 | **S1-5**：設定中心的還原流程改為『先撤銷該群組舊待生效項 → 再 `publish()`』，並以測試鎖定三種情形（收緊、放寬、混合） |
| G4 列舉型放寬 | `publish()` 的 `_loosens()` 只處理數字（`int/float`）；`bool`／`str` 的 `loosen` **不會觸發待生效**。既有做法是把選項編成**整數**（例 `system_hub.show_denied`：`int` 0/1＋`choices`） | S1 不改機制；**登錄規約**：需要放寬管制的選項一律『整數編碼＋choices』。**連帶**：`CRM-DIRECTIVE-COMMENTS-T56.md` r2 的 `bool`／`str` 選項欄位（`supervisor_read`、`who`、`visible_to`、`email_include_text`、`on_deleted` 等）須改為整數編碼——記入該文 r3 |
| G5 即時影響 | `SettingDef.impact_fn` 存在、`meta()` 回 `hasLiveImpact`，但**沒有任何端點呼叫它** | **S1-4**：`POST /api/settings-center/groups/{group}/impact`（唯讀連線、1.5 秒逾時、60 秒快取、失敗只回靜態說明） |
| G6 影響範圍欄位 | `SettingDef` 無 `impact_scope`（`__slots__` 已核對） | **S1-3（E-e 核心）**：欄位＋結構驗證＋『新登錄的 money／legal／security 必須有』守門（既有群組以白名單暫免，下次修改補） |
| G7 預覽 | 沒有 dry-run：UI 要顯示『即時／待生效／需雙人核准』必須自己重算 | **S1-4**：`POST …/groups/{group}/preview`（不寫入，回逐欄分類、驗證問題、效果句、橫幅） |
| G8 版本清單 | 版本只能經通用定義端點讀（GET 可用）；沒有以設定群組為單位的『版本清單＋變更明細』 | **S1-5**：`GET …/groups/{group}/versions`（版本、時間、操作者、備註）；差異與單版沿用通用 GET |
| G9 預設組畫面 | 端點齊全（profiles／preview／apply）、無畫面 | 10 日範圍只做『預覽＋套用（原因必填）』最小頁籤 |

## 2. API 清單

沿用 `/api/settings-center` 前綴（全部 superadmin；新增路由登錄整合點並重產 route golden）。

| 方法／路徑 | 狀態 | 說明 |
|---|---|---|
| `GET /groups`、`GET /groups/{g}` | 既有 | 增補回傳：每個欄位的 `impactScope`、`banner`（§2.1）、`isDefault`（目前值是否等於預設）、`pendingCount` |
| `POST /groups/{g}` | 既有 | 儲存（`values`、`reason`）；不變。回傳補 `classification`（與 preview 相同結構，便於畫面顯示結果） |
| `POST /groups/{g}/preview` | **新** | body `{values}`。不寫入、不 commit。回 `{ok, problems[], fields:[{field,label,old,new,unit,kind:'immediate'｜'pending'｜'pending_approval'｜'unchanged',effectiveAt?,approvalsRequired,effect(句),banner?}], needsReason, otherSuperadmins, warnings[]}` |
| `POST /groups/{g}/impact` | **新** | body `{field,value}`。呼叫 `impact_fn`（唯讀連線；逾時 1.5 秒；結果快取 60 秒，鍵＝group/field/value）；失敗回 `{live:null, static:impact}` |
| `GET /groups/{g}/versions` | **新** | 已發布版本清單（版本、時間、操作者、備註）＋最近變更明細（`ledger.history`） |
| `POST /groups/{g}/restore/{version}` | **新** | body `{reason}`（必填）。流程：撤銷該群組舊待生效項 → `publish()`（放寬者成為待生效／雙人核准）→ 稽核 `settings.<g>.restore`；回 `classification` |
| `POST /groups/{g}/reset` | **新** | body `{fields:[…], reason}`：把指定欄位改回程式預設（走 `publish()`，同樣可能是放寬）；畫面的『還原預設』 |
| `GET /pending`、`POST /pending/{id}/cancel｜approve` | 既有 | 畫面串接；補回 `label`（欄位白話名稱）、`groupLabel` |
| `GET /profiles`、`GET …/{n}/preview`、`POST …/{n}/apply` | 既有 | 畫面串接最小頁籤 |
| 通用 `PUT/POST /api/definitions/setting_group/…`（draft／publish／restore） | **改** | 一律 409（S1-1）；GET 不變 |

### 2.1 橫幅結構（E-e 渲染；脊柱 §16.6）

`SettingDef.impact_scope`（選填；新登錄的 `money／legal／security` 必填）：
```
{"documents": ["白話單據類型…"], "roles": ["白話角色／能力…"], "amounts": "一句話", "reversible": True｜False, "effective": "immediate"｜"pending"}
```
伺服器端 `banner_of(field, value)` 產出（畫面只負責呈現，不自行組句）：`{level: 'amber'｜'red', lines: [①影響哪些單據 ②影響哪些人 ③金額／後果＋可否復原＋何時生效], liveCount?}`。
**等級規則**：`risk ∈ {legal, security}` 或 `reversible=False` ⇒ 紅；`risk = money` ⇒ 琥珀；`ops／none` ⇒ 無橫幅。**只在選到非預設且為放寬方向／較高風險的選項時顯示**（選項型依 `choices` 與 `loosen`；數值型依 `loosen` 方向）。缺 `impact_scope` 的既有欄位以 `impact`＋`risk_text` 組成降級橫幅（兩行），不報錯。

## 3. 畫面（`frontend/pages/settings-center.html` 重寫＋新 `frontend/static/settings-editor.js`）

白話、無代碼（鍵名不顯示）；深色模式；手機寬度不橫向捲動；`data-testid` 供 e2e。

1. **版型**：左欄『群組樹』（依領域分組、搜尋、風險徽章、『已改過』標記、『有 N 項待生效』徽章）；右側『目前值』表單；上方頁籤：**目前值／待生效／版本與變更紀錄／預設組**。
2. **表單（由 `SettingDef` 產生）**：問句為標題；數值＝步進＋單位＋可設定範圍（版本邊界取交集後的有效範圍）；`choices`＝選項卡（每個選項顯示自己的影響說明）；`bool`＝開關；`str`＝文字框；『建議』標籤；『進階』收合；每欄『還原預設』；目前不是預設值時，欄位旁常駐『目前不是系統預設（預設：…）』。
3. **橫幅**：選到會放寬／較高風險的值時，緊貼該欄展開橫幅（琥珀／紅，三行固定；紅色需勾『我已了解上述影響』才能儲存）；若有 `impact_fn`，橫幅附『目前有 N 筆…』（呼叫 `/impact`，逾時不顯示）。
4. **儲存流程**：按『檢視變更』→ 呼叫 `/preview` → 顯示差異清單（舊→新）、每欄『立即生效／等 N 天確認期間後生效／需另一位最高管理者核准』、一句話摘要（用 `effect` 句型）、原因欄（`needsReason` 時必填）→ 『確認儲存』呼叫 `POST /groups/{g}`；成功後顯示結果（版本號或待生效清單）。只有一位最高管理者時顯示警告句（`warnings`）。
5. **待生效頁籤**：清單（群組、欄位白話名、舊→新、申請人、生效時間、已核准／需要票數）；『核准』（申請人不可核自己的，按鈕停用並說明）、『撤銷』（原因選填）；到期值顯示『已到時，等待落版』。
6. **版本與變更紀錄**：版本清單、選兩版看差異（沿用通用 `diff` GET）、『還原到這一版』（原因必填；走 `/restore`，畫面說明放寬項會變成待生效）；變更紀錄表（`ledger.history`）。
7. **預設組**：列表＋『預覽會改什麼』＋『套用』（原因必填；結果同儲存流程的分類顯示）。
8. **非 superadmin**：維持現狀（看不到）；`finance` 唯讀待權限矩陣就緒後（不在本期）。

## 4. 變更檔案（預估）

| 區 | 檔案 | 備註 |
|---|---|---|
| **底層列車（L1）** | `backend/helpers/settings_registry.py`（E-e 欄位／驗證／`banner_of`／`plan()` 抽出分類邏輯／`live_impact`／`reset`） | CHANGELOG：`backend/core/CHANGELOG.md`（L1 契約）；`plan()` 與 `publish()` **共用同一個分類函式**，不得各寫一份 |
| | `backend/routers/settings_center.py`（新端點、回傳補欄） | route golden 重產 |
| | `backend/routers/definitions.py`（受管 kind 守門） | 一個小函式＋三處呼叫 |
| 非底層 | `frontend/pages/settings-center.html`、`frontend/static/settings-editor.js`（新）、`frontend/css`（若需要） | 頁面版號／`FORM_VERSION` 規則照既有守門 |
| 測試 | `backend/tests/platform/test_settings_editor_s1.py`（新）、`test_settings_ui_plain_language.py`（擴充橫幅與新端點文字）、`backend/tests/test_e2e_settings_center_edit_s1.py`（新 e2e） | 見 §5 |
| 文件 | 本檔、`docs/platform/UNIT-INDEX.md`／契約索引依既有生成規則、`version_manifest.json`（若有登錄頁面變更）| 時間戳由 `date` 產生 |
| **不動** | `settings_groups.py`、`settings_deploy_baseline.json`（S1 不新增群組；E-a 基準分割屬後續底層項）、`core/definitions.py` | 避開熱點 |

## 5. 測試（單檔、各自獨立執行）

`test_settings_editor_s1.py`（API／邏輯，不開瀏覽器）：
1. **G2**：對 `setting_group` 呼叫通用 `PUT draft／POST publish／POST restore` 全 409，且設定值不變、無新版本；GET 版本／差異仍可；其他 kind（如 `remit_kinds`）不受影響（正反對照）。
2. **preview**：數值收緊＝`immediate`、放寬（`loosen`）＝`pending_approval`（有第二位最高管理者）／`pending`（只有一位＋警告）、`requires_pending`＝`pending`、無變更＝`unchanged`；**不寫入**（前後 `config_changes`、定義版本計數不變）；驗證失敗回 `problems`；`preview` 與實際 `POST` 的分類逐欄相同（共用函式）。
3. **E-e**：`impact_scope` 結構驗證（缺鍵／型別錯 ⇒ 登錄失敗）；新群組含 `money／legal／security` 而缺 `impact_scope` ⇒ `register_group` 失敗；白名單內既有群組不受影響且有降級橫幅；`banner_of` 等級（legal／security／不可逆＝紅；money＝琥珀；其他無）、只對非預設且放寬方向的值顯示。
4. **impact**：呼叫 `impact_fn`（唯讀連線——寫入嘗試會失敗）；逾時回靜態；60 秒快取（呼叫次數斷言）；`impact_fn` 丟例外 ⇒ 靜態。
5. **restore（G3）**：①還原到較緊的舊值＝立即生效並撤銷舊待生效；②還原到較鬆的舊值＝產生**存活的**待生效項（不被撤銷）；③混合；各自驗證 `config_changes`、事件、稽核 `settings.<g>.restore`。
6. **reset**：改回預設走 `publish()`，放寬者待生效；原因必填。
7. **權限**：非 superadmin 對所有新端點 403；`finance` 亦 403。
8. **稽核守門**：新寫入端點全有稽核（`test_write_endpoints_are_audited_2026_09_24`、`test_ac1_write_actions_2026_09_23` 既有守門吻合）。

`test_e2e_settings_center_edit_s1.py`（e2e，真路由）：改一個即時欄位並儲存→值變、版本出現；改放寬欄位→顯示待生效與橫幅、需第二位核准（以第二個 superadmin 登入核准）→ 到期前仍為舊值；紅色橫幅未勾選不可送出；還原預設；版本頁還原；頁面無代碼字串（鍵名不出現）；手機寬度無橫向捲動；深色模式。
`test_settings_ui_plain_language.py` 擴充：橫幅文字、`effect` 句型、新端點錯誤訊息不含鍵名／英文代碼。
**執行方式**：每次只跑單一檔、單一程序，先看 `D:\ram_watch_20261012.csv` 可用記憶體 ≥ 10 GB 才開 e2e；測試暫存用完即刪（只刪自己的）。

## 6. 底層列車檔案清單（隨列車一次過閘）

`backend/helpers/settings_registry.py`、`backend/routers/settings_center.py`、`backend/routers/definitions.py`（＋ `backend/core/CHANGELOG.md` 條目、route golden）。**本計畫不新增 `core/**` 檔**。若其他列車項（脊柱 P0／P1、E-a／E-b、`annotations`）同期要改 `settings_registry.py`，以 E-a（基準分割）為後者、本工作先落地；兩者先後由 PM 排定，不並行改同檔。

## 7. 10 日範圍與延後

| 內容 | 10 日 | 延後 |
|---|---|---|
| S1-1 受管 kind 守門（G2） | ✔ | |
| S1-2 編輯畫面（數值／bool／選項／文字；還原預設；非預設標示） | ✔ | |
| S1-3 E-e 欄位＋驗證＋橫幅（伺服器渲染）＋紅色勾選 | ✔ | |
| S1-4 preview／impact | ✔ | |
| S1-5 版本清單、差異、還原（含 G3） | ✔ | |
| 待生效頁籤（核准／撤銷） | ✔ | |
| 預設組頁籤（預覽＋套用） | ✔ 最小版 | 精靈（多步驟） |
| 白話精靈、受影響人員清單 | | ✔ |
| `finance` 唯讀、依能力顯示 | | ✔（權限矩陣後） |
| `config_epoch`／`next_change_at` 跨行程快取失效 | | ✔（M1 既定） |
| E-a 基準分割、E-b 彙整驗證 | | 另列車項 |

## 8. 工量（誠實）

| 項 | pd |
|---|---|
| S1-1 受管 kind 守門＋測試 | 0.25 |
| S1-3 E-e 欄位＋驗證＋白名單＋`banner_of` | 0.75 |
| S1-4 `plan()` 抽出（與 `publish()` 共用）＋preview＋impact＋reset | 1.0 |
| S1-5 版本清單＋還原流程（含 G3 修正）＋預設組串接 | 0.75 |
| S1-2 畫面與 JS（群組樹、表單、橫幅、差異確認、待生效、版本、預設組、深色／手機） | 2.5 |
| 測試（API 單檔＋e2e＋白話守門擴充） | 1.5 |
| 文件、CHANGELOG、route golden、版號 | 0.25 |
| 合計 | **7.0** |
| 風險緩衝（`publish()` 分類抽出屬底層改動，需謹慎回歸） | 0.4 |
| **含緩衝** | **7.4** |

## 9. 提交順序（小提交；CHANGELOG 與程式同提交）

1. 本計畫文件（本提交）。
2. S1-1 受管 kind 守門＋測試（安全缺口優先）。
3. S1-3 E-e（欄位、驗證、白名單、`banner_of`）＋測試。
4. S1-4 `plan()` 抽出＋preview／impact／reset 端點＋測試。
5. S1-5 versions／restore 流程＋測試。
6. S1-2 畫面（先骨架＋表單，再橫幅，再待生效／版本／預設組）。
7. e2e＋白話守門擴充；重產 route golden；最後一次回報。

## 10. 待 1c／PM 確認

- **G2 嚴重度**：現況單一 superadmin 即可繞過放寬的雙人核准（僅限直接呼叫 API，UI 沒入口）；建議 S1-1 單獨先出（或列為 M2 後的緊急補丁），請決定是否要比 S1 其餘更早上線。
- **G4**：directive 文件需改整數編碼（我方負責，記入 r3）；其他進行中設計若有 `bool`／`str` 且 `loosen` 的欄位同理。
- **S1 與 E-a 先後**：兩者都動 `settings_registry.py`；建議 S1 先、E-a 後。
- 是否要把 `finance` 唯讀或預設組精靈拉進 10 日：本計畫預設延後。
