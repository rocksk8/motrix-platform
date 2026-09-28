# 模組建構器第三輪：表單設計器（BUILDER-FORMS-V3）

> 2026-09-28 19:10 H3 起草（主持 hichan-28 派工）。依據：CORE-SPEC 裁示表「模組建構器第三輪：表單設計器（給未來管理者）」列（d71f1e8f，使用者原話全文在該列）。
> 參考圖 `D:\MOTRIX-DRILLS\handoff\builder-ref\forms-reference-1.png` 為第三方產品截圖，**本檔只描述其版面，不複製圖、不進 repo**。
> 範圍：只做差距盤點＋設計；**未改任何產品碼**。流程：本檔交 D 審 → 主持／使用者裁示 §8 → 分段實作（§7）。
> 基底：origin/platform d71f1e8f（CORE_VERSION 1.64，`backend/core/registry.py:22`）。

---

## 1. 現況（以檔案與行號為準）

### 1.1 既有建構器已具備的

| 項目 | 現況 | 佐證 |
|---|---|---|
| 欄位型別（catalog 實際值） | `text`、`number`、`date`、`select`、`checkbox`（`custom_fields.TYPES`）＋`formula`、`ref`，共 7 種 | `backend/helpers/custom_fields.py:14`；`backend/helpers/custom_modules.py:27`；端點 `backend/routers/custom_records.py:237-246` |
| 公式函式 | `if round min max sum abs coalesce days_between`；AST 白名單解析，不用 `eval` | `backend/helpers/formula.py:24`、`:79-152`（check）、`:170-268`（evaluate） |
| 型別只來自 catalog | 工具列 `x-for="t in catalog.fieldTypes"`；`addField` 不在 catalog 就拒絕 | `frontend/pages/module-builder.html:292-297`、`:1346`；題 `test_e2e_builder_dnd_2026_09_27.py:66` |
| ⚠ 寫死的型別對照 | 型別**名稱**、icon 寫在頁內；執行頁 `KNOWN_TYPES` 寫死 7 種 | `module-builder.html:937`（TYPE_LABELS）、`:963-972`（TYPE_ICONS）；`frontend/pages/custom-records.html:343` |
| ⚠ catalog 區段缺口 | `fieldTypes`／`formulaFunctions` 在 `EXPECTED_SECTIONS`，但**沒有擁有者 `register_section`** ⇒ 整份目錄 `/api/catalog` 把它們列為 gaps；建構器走的是舊端點 `/api/custom-modules/catalog` | `backend/core/catalog.py:37`；`grep register_section backend` 只有 `routers/platform_catalog.py:32`（outputs） |
| 拖曳 | 原生 HTML5：工具列 → 畫布區塊任意位置；卡片 ⠿ 拖曳、跨區塊；區塊拖曳排序；鍵盤 Alt+↑↓／Enter／Delete | `module-builder.html:290-351`、`dropOn` `:1397-1419`；規則純函式 `frontend/static/custom-layout.js`（`placeField` 等） |
| 預覽 | 第二輪：**畫布本身就是表單**（與執行頁同一套 `.cr-sec／.cr-grid／.cr-f`，一致性題）；右側同時顯示輸出預覽（後端同一 renderer）＋列表預覽 | `docs/platform/BUILDER-UX.md` §8；`frontend/static/form-preview.js:1-18`；`custom_modules.preview_output` `:435-503` |
| 代號產生 | 欄位：`nextKey` ⇒ `field_n／calc_n／ref_n`（取第一個沒被用的 n，**會重用已刪除的號碼**）；狀態 `state_n`、轉換 `action_n` | `module-builder.html:1339-1343`、`:1512-1517`、`:1612-1617` |
| 代號仍要人填／看得到 | 模組代號首頁手打（建立後不能改）；權限 key 輸入框；編號前綴必填手打；欄位代號 `#mb-f-key`、狀態／轉換 key 都在畫面上可改 | `module-builder.html:165-168`、`:254-256`、`:262-263`、`:355-356`（`renameField` `:1455-1463`）、`:506`、`:629` |
| 草稿 JSON | 定義文件庫 kind `custom_module`（草稿／發布／差異／還原）；格式見 BUILDER-UX §3.1 | `backend/core/definitions.py:21`；`backend/routers/definitions.py:123-264`；`CUSTOMIZATION-SPEC.md` §3.7 |
| 值的形狀 | **全是純量**：`_cf._coerce` 逐型別正規化；`_write_index` 每鍵一列索引 | `custom_fields.py:57-84`；`custom_modules.py:583-590` |
| 預設值 | 只收**固定值**，由伺服器在沒填時補（`clean`）；前端 `blankValues` 也預填 | `custom_fields.py:50-54`、`:101-102`；`custom-records.html:541` |
| 申請人 | 系統欄 `created_by`＝登入者（伺服器寫，不是表單欄位）；列表／輸出可顯示 | `custom_modules.py:645-665`；`custom-layout.js` SYSTEM_COLUMNS |
| 簽核／通知 | 簽核掛在狀態、分層、條件 `when`；`notify.requester／users`；事件 `custom_module.transitioned` | `custom_modules.py:198-305`、`:732-816`；CUSTOMIZATION-SPEC §3.7 |
| 按鈕 | 執行頁的轉換自動畫成按鈕（依流程），不是可擺放的元素 | `custom-records.html:294` |
| 輸出 | `output.template`＝doc_template 版型；已有 `items_table`（`source`＝清單路徑）、`totals`、`amount_box` 積木；格式 `money` | `backend/helpers/doc_template.py:160`、`:296`、`:309-330`；`module-builder.html:949`（FORMAT_LABELS） |
| 上傳（別的模組） | L1 `helpers/uploads.save_document_files`：副檔名白名單 jpg/png/pdf、20MB、`uploads/<sub>/<doc_no>/`；**只驗副檔名、不驗檔頭** | `backend/helpers/uploads.py:31-32`、`:84-135`（`:113`） |
| 上傳檔讀取 | `GET /api/uploads/{path}`：`Authorization` **只驗登入**，或 `?pt=` 單路徑簽章 | `backend/routers/uploads.py:78-114` |
| 版面欄數 | `.cr-grid` 為 `repeat(auto-fill, minmax(240px,1fr))`，欄數隨寬度自動，不可設定 | `frontend/css/custom-form.css:7`、`:19` |
| 取消發布 | 沒有（只有草稿刪除、發布、還原） | `routers/definitions.py:136`、`:191`、`:248` |

### 1.2 對照使用者要求①～⑥與參考圖

| # | 項目 | 狀態 | 說明／佐證 |
|---|---|---|---|
| G1 | ① 模組代號自動 | 沒有 | 首頁手打 `#mb-key`（`:165`） |
| G2 | ① 權限 key 自動 | 部分 | 預設 `custom.<key>`（`:1066`）但輸入框可見可改（`:254`） |
| G3 | ① 編號前綴自動 | 沒有 | 必填手打（`:262`；`PREFIX_RE` `custom_modules.py:25`） |
| G4 | ① 欄位代號自動、看不到 | 部分 | 自動 `field_n` 但可見可改；刪除後號碼重用 |
| G5 | ① 狀態／轉換代號 | 部分 | 自動 `state_n／action_n`，表格內可見可改 |
| G6 | ② 拖曳到畫布即時顯示 | 已有 | §1.1 拖曳／預覽 |
| G7 | ② 點選後在屬性面板選內容 | 已有 | 卡片就地展開 `#mb-f-*` |
| G8 | ③ 段落／說明文字 | 部分 | 只有欄位 `help`（≤300 字，`custom_modules.py:151`）；沒有獨立段落元素 |
| G9 | ③ 文字單行 | 已有 | `text` |
| G10 | ③ 文字多行 | 沒有 | 執行頁 `text` 只畫 `<input>`（`custom-records.html:167`） |
| G11 | ③ 數值 | 已有 | `number` |
| G12 | ③ 金額 | 部分 | 只能用 `number`；輸出有 `money` 格式，輸入端沒有 |
| G13 | ③ 日期（指定值預設） | 已有 | `date`＋固定 `default` |
| G14 | ③ 日期時間 | 沒有 | 無 `datetime` |
| G15 | ③ 預設＝填單當下 | 沒有 | `default` 只收固定值 |
| G16 | ③ 人員：可選人員 | 已有 | `ref`＋`target:users` |
| G17 | ③ 人員：自動帶入申請人 | 部分 | 只有系統欄 `created_by`，不是可擺放的欄位 |
| G18 | ③ 下拉選單 | 已有 | `select` |
| G19 | ③ 單選 | 沒有 | — |
| G20 | ③ 多選 | 沒有 | `checkbox` 是布林 |
| G21 | ③ 附件上傳 | 沒有 | CUSTOMIZATION-SPEC §3.7「未做：附件欄位」 |
| G22 | ③ 圖片 | 沒有 | — |
| G23 | ③ 公式 | 已有 | `formula` |
| G24 | ③ 加總（明細金額自動加總） | 沒有 | `sum()` 只收純量參數（`formula.py:258-264`） |
| G25 | ③ 按鈕（送出、新增一列） | 部分 | 送出＝流程轉換自動成按鈕；不可擺放、無「新增一列」 |
| G26 | ③ 重複明細列 | 沒有 | 值的形狀全是純量（§1.1） |
| G27 | ④ 元素集合／範本 | 沒有 | — |
| G28 | ⑤ 分頁（頁面 N 之 M、頁標題與說明） | 沒有 | 只有區塊 `ui.form.groups` |
| G29 | ⑤ 區塊 | 已有 | BUILDER-UX §8-1 |
| G30 | ⑤ 兩欄並排 | 部分 | 欄數隨寬度自動（`custom-form.css:7`），不能指定 |
| G31 | 參考圖：表單標題＋說明 | 部分 | 有 `name`，沒有表單說明 |
| G32 | 參考圖：右側「新增元素」面板＋元素／元素集合頁籤 | 部分 | 工具列在左、無頁籤、無分類 |
| G33 | 參考圖：選中元素顯示類型標籤＋⋮ 選單 | 部分 | 卡片有型別 icon、↑↓✕；無複製、無選單 |
| G34 | 參考圖：上方 預覽／儲存／取消發布 | 部分 | 自動存檔＋發布＋還原；無取消發布；預覽常駐右側 |
| G35 | ⑥ 草稿 JSON 與已發布沿用 | 已有 | 版本化＋單據凍結 `def_version`；新增欄位只准加（本檔 §6） |
| G36 | ⑥ 型別只來自 catalog | 部分 | 清單來自 catalog，但名稱／執行頁型別寫死；catalog 區段未登記（§1.1） |

**統計：已有 10、部分 13、沒有 13（共 36）。** 不在本輪：參考圖的「分享」「多語系（中文(台灣)＋）」「網格（矩陣選擇）」——列 §8 確認。

---

## 2. 設計① 代號全自動

原則：**代號是系統的，名稱是人的**。設定者只看名稱；代號產生一次後永不改（改名不動代號）。

| 代號 | 產生規則 | 時機 | 衝突處理 |
|---|---|---|---|
| 模組 key | `cm_` ＋ base36（毫秒時間）＋ 2 碼亂數，例 `cm_mfk3x2q9a7`（符合 `KEY_RE` `custom_modules.py:23`，≤40 字） | 首頁按「＋ 新表單」 | 先查 `GET /api/definitions/custom_module`；撞到重抽；`PUT …/draft` 前再查一次 |
| 權限 key | 固定 `custom.<模組key>`，**不提供輸入框** | 建立時 | 既有 `_validate_custom_module` 的重複檢查照舊（`custom_records.py:22-36`） |
| 編號前綴 | 預設 `F`＋兩碼序號（`F01`…`F99`，再來 `G01`…），取已發布／草稿都沒用過的最小值；**進階區可改**（待裁示 §8-2） | 建立時 | 與既有前綴重複 ⇒ 換下一個；可改時由既有 `PREFIX_RE` 驗 |
| 欄位 key | `<型別縮寫>_<n>`，n＝`ui.builder.seq` **單調遞增**（全模組共用、刪除不回收）。例 `amt_7`、`dt_8`、`tbl_9`；明細欄 `tbl_9_c10` | 元素放上畫布時 | 單調序號 ⇒ 不會撞；載入時 seq 小於現有最大號 ⇒ 校正為 max+1 |
| 狀態／轉換 key | 沿用 `state_n／action_n`，改成同一個單調序號 | 新增時 | 同上 |

- 為何單調不回收：`custom_record_values` 以欄位 key 做索引、跨定義版本共用（`custom_modules.py:583-590`）；刪掉 `field_2` 再新增又叫 `field_2` ⇒ 舊單與新單的「同一欄」其實是兩個意思，列表篩選會混在一起。
- 公式與條件：儲存照舊用 key（引擎不變），**畫面一律顯示名稱**：輸入時點選欄位籌碼插入 `{名稱}`，存檔前轉成 key；顯示時反轉（已有 `L.formulaReadable`，`module-builder.html:1313`）。加總走結構化設定，不讓人寫式子（§3.3）。
- 畫面：`#mb-key` 輸入框換成「＋ 新表單」按鈕；`#mb-perm`、`#mb-f-key`、狀態／轉換 key 欄從主畫面拿掉，只在「進階（系統代號）」摺疊區**唯讀**顯示（供除錯與客服，待裁示 §8-1）。
- **既有草稿遷移**：不改任何既有 key（已發布版與舊單據都綁著它）。`normalize()`（`module-builder.html:1074-1086`）補 `ui.builder.seq = 現有所有 key 尾碼數字的最大值＋1`；沒有前綴的草稿在開啟時補預設前綴並標為「已自動補上」。引擎不讀 `ui`（CUSTOMIZATION-SPEC §3.7「未做」段），後端不動。
- 既有 e2e 依賴 `#mb-key`、`#mb-f-key`、`[data-k=key]` 直接 fill ⇒ 改題（逐題寫原因，比照 BUILDER-UX §8-6）；進階區保留同一組 id（唯讀），題改成讀值驗「自動產生且改名不變」。

---

## 3. 設計② 元素清單與屬性面板

### 3.1 元素 ≠ 型別

工具列上的是**元素**（使用者看得懂的東西），每個元素對應一個**型別＋預設屬性**。例：「申請人」＝`ref`(users)＋預設帶入申請人＋鎖定；「加總」＝`formula`＋結構化設定。元素清單與型別規格一律由 catalog 提供（§6.1），頁內不寫清單。

### 3.2 元素表

分類沿用參考圖的「基本元素」概念，但分組名稱由 catalog 給。

| 元素 | 型別（新＝本輪新增） | 屬性面板（名稱、必填、說明為共通，下表只列特有） | 值 |
|---|---|---|---|
| 段落 | `static`（新，不收值） | 文字內容（≤2000 字，純文字＋換行）；樣式：一般／提示 | 無 |
| 文字 | `text` | 單行／多行（新 `multiline`）；最長字數（新 `maxLength`，≤2000）；預設值 | 字串 |
| 數值 | `number` | 小數位數（新 `decimals` 0～4）；最小／最大（新 `min`／`max`）；預設值 | 數字 |
| 金額 | `money`（新） | 幣別（第一版固定 TWD，唯讀）；小數位 0 或 2；不可負（新 `min:0` 預設開） | 數字（捨入 `legal_params.round_half_up`） |
| 日期 | `date` | 預設：無／**填單當下**／指定日期；鎖定（不可改） | `YYYY-MM-DD` |
| 日期時間 | `datetime`（新） | 預設：無／**填單當下**／指定；鎖定 | `YYYY-MM-DDTHH:MM`（伺服器當地時間） |
| 人員 | `ref`（target `users`） | 預設：無／**申請人**；鎖定；可選範圍（第一版：全部啟用帳號） | username |
| 申請人（捷徑） | 同上 | ＝人員＋預設申請人＋鎖定 | username |
| 下拉選單 | `select` | 選項（新增／刪除／拖曳排序）；預設 | 字串 |
| 單選 | `select`＋`display:'radio'`（新屬性） | 同下拉；排列：直／橫 | 字串 |
| 多選 | `multiselect`（新） | 選項；最少／最多勾幾個 | 字串陣列 |
| 勾選（是／否） | `checkbox` | 預設 | 布林 |
| 附件 | `file`（新） | 允許：圖片／PDF（catalog 給的集合的子集）；最多幾個（≤10）；單檔上限（≤ 平台上限 20MB） | `[{id,name,size,mime}]`（伺服器產生） |
| 圖片 | `file`＋`accept:['image']` | 同附件（只收圖） | 同上 |
| 公式 | `formula` | 式子（以名稱籌碼編輯）；顯示格式（數字／金額） | 算出 |
| 加總 | `formula`（preset） | **來源**：明細表＋欄（例：報銷明細．金額）或勾選多個數值欄；**方式**：加總／平均／最大／最小／筆數 ⇒ 產生 `total(tbl_9, "tbl_9_c10")` 等 | 算出 |
| 參照 | `ref` | 參照對象（catalog `refTargets`） | 依對象 |
| 明細表（重複列） | `table`（新） | 欄位（子元素，只准：文字、數值、金額、日期、下拉、勾選、公式（列內））；最少／最多列（≤200）；「新增一列」按鈕文字 | `[{欄key: 值}]` |
| 按鈕 | 不是欄位（§3.4） | 見 §3.4 | — |

共通屬性：名稱、必填、說明（沿用 `help`）、寬度（整列／半列，§5）、**資料分類**照舊只收 T1（F2 仍拒絕，`custom_modules.py:168-170`）。

### 3.3 預設值與「填單當下」「申請人」

- 定義：`"default": {"$": "today" | "now" | "requester"}`（物件形式，避免與字面字串 `"$today"` 混淆）；固定值照舊用純量。
- **由伺服器決定**：`create_record` 在 `clean_values` 之前把 token 換成伺服器當下時間／`user["username"]`（`custom_modules.py:645-650`）。前端 `blankValues` 只顯示「（送出時自動填入）」或本機時間作參考，不當真。
- `locked: true` ⇒ 伺服器**忽略**使用者送來的值、一律用 token 結果（申請時間、申請人不可竄改）；`update_record` 保留建立時的值不重算。
- 驗證：token 只准用在對應型別（today→date、now→datetime、requester→ref users）。樣本資料（`sample_values`，`:405-412`）給固定樣本。

### 3.4 按鈕的定義與限制

- 按鈕**不能**自訂 URL、腳本或任意 API；只能從 catalog `buttonActions` 挑，第一版：
  - `transition:<轉換key>`：就是流程轉換（送出、送審…），權限、`requester_only`、簽核照舊由後端擋；
  - `addRow:<明細表key>`：明細表自帶，屬性面板只能改文字；
  - `saveDraft`：儲存草稿（等同現行「儲存」）。
- 存在 `ui.form.actions: [{action, label?}]`（順序＝畫面順序）；沒設 ⇒ 照現行「每個可用轉換一顆按鈕」（相容）。
- 「按鈕」元素拖進畫布 ⇒ 只能放在表單底部的動作列（不是任意位置），屬性面板下拉選 action。

### 3.5 明細表與加總（後端要點）

- 值：`[{col: 值}]`；逐列用同一套 `_coerce` 驗子欄（重用 `custom_fields._coerce`，錯誤帶 `key: "tbl_9[3].tbl_9_c10"`）。
- 列內公式：先逐列算，再算表外公式。
- 新公式函式（加進 `formula.FUNCTIONS`，照樣 AST 白名單）：`total(表, "欄")`、`avg(表,"欄")`、`count(表)`；`check()` 驗第一參數必須是 table 欄、第二參數必須是該表的數值／金額欄；空值不等於 0（沿用 `coalesce` 慣例，全空 ⇒ `total` 回 0、`avg` 回空）。
- 索引：`_write_index` 對 list 值只寫「列數」到 `value_num`（不把整份 JSON 塞進 `value_text`）；列表欄位顯示「3 筆」。
- 輸出：預設版型遇到 table 欄 ⇒ 用既有 `items_table`（`source`＝欄 key）＋`totals`；不需新積木。

---

## 4. 設計③ 元素集合／範本

- **定義**：範本＝一段可插入的片段 `{name, description, fields:[…], ui:{form:{groups…}}, actions?}`，key 用範本內的區域代號（`$1`、`$2`…），公式以區域代號互相引用。
- **插入**：以目前模組的 `ui.builder.seq` 逐一換成真 key，公式與 `ui` 內的引用同步換（純函式，放 `custom-layout.js`，可單測）；插入後就是普通元素，與範本不再連動。
- **內建範本（隨產品出貨）**：第一版兩個——
  - 報銷申請：申請人（鎖定）、申請時間（填單當下、鎖定）、事由（多行）、報銷明細（明細表：日期、項目、說明、金額）、金額合計（加總）、收據（附件）、送出按鈕；
  - 費用申請：申請人、申請日期、費用類別（下拉）、預計金額（金額）、原因（多行）、附件。
  存放：`backend/helpers/form_templates/*.json`（程式資料，不是使用者資料），由 `helpers.custom_modules` 以 catalog 區段 `formTemplates` 登記；載入時用 `validate_module` 的欄位驗證跑一次，壞的範本不列出並記入 catalog `gaps`。
- **管理者自存**：畫布上選取區塊 ⇒「另存為元素集合」。存定義文件庫新 kind `form_template`（scope `company`，有版本）——`core/definitions.py:21` 的 `KINDS` 是 L0，**要升 CORE 次版號**。待裁示 §8-4（推薦：分段 S6 第二步再做，先出內建兩個）。
- 未來 L2 模組想貢獻範本：用 `registry.provide("form_template", <名稱>, fn)`，由 catalog 區段收集（不讓模組直接登記同一區段，`catalog.register_section` 同名只准一個擁有者，`catalog.py:43-53`）。

---

## 5. 設計④ 分頁／區塊／兩欄

- 資料（全部在 `ui`，引擎不讀）：
  - `ui.form.pages: [{title, description}]`；`ui.form.groups[].page`（頁索引，缺＝0）；
  - `ui.form.groups[].cols: 1 | 2`（缺＝現行 auto-fill，相容）；
  - `ui.form.span: {<欄位key>: "full"}`（在 2 欄區塊裡佔整列；明細表、段落、多行文字預設 full）；
  - 表單說明：頂層 `description`（新增、選填、≤500 字；會進輸出抬頭下方，所以放 body 不放 ui）。
- 版面規則：`custom-layout.js` 新增 `formPages(def)`（回 `[{title, description, sections:[…]}]`，內部沿用 `formSections`），執行頁與畫布同用；既有 `formSections` 不改簽章。
- 執行頁呈現（待裁示 §8-5）：推薦**同一頁分段**（頁標題是大標題、「頁面 N 之 M」是錨點導覽），不做逐頁「下一頁」——必填驗證與手機閱讀都不變。
- CSS：`.cr-grid--2 { grid-template-columns: 1fr 1fr }`、`.cr-f--full { grid-column: 1 / -1 }`；手機一律 1 欄（沿用 `custom-form.css:19` 的斷點）。

---

## 6. 設計⑤ 畫面版面（仿參考圖）

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 報銷申請（未發布）  已儲存 ✓            [預覽] [發布▸] [取消發布] [進階]     │
│ 基本 · 表單 · 流程 · 簽核 · 通知 · 輸出 · 發布   ← 既有縮圖導覽保留           │
├───────────────────────────────────────────────┬──────────────────────────┤
│ 畫布（＝表單本身）                              │ ┌新增元素┐┌元素集合┐┌屬性┐│
│  表單標題／表單說明（就地編輯）                   │ 基本元素 ▾               │
│  ┌ 頁面 1 之 2 ─────────────────────────────┐  │  ¶ 段落                 │
│  │ 頁標題／頁說明                              │  │  A 文字                 │
│  │ ┌[日期時間 ⋮]──────┐ ┌─────────────────┐   │  │  12 數值  $ 金額        │
│  │ │ 申請時間 🔒       │ │ 申請人 🔒        │   │  │  📅 日期  🕑 日期時間   │
│  │ └──────────────────┘ └─────────────────┘   │  │  👤 人員  ☰ 下拉 …      │
│  │ ┌ 報銷明細（明細表，整列）────────────────┐ │  │ 進階元素 ▾              │
│  │ │ 日期 | 項目 | 金額      [＋ 新增一列]   │ │  │  ▦ 明細表  Σ 加總 …    │
│  │ └────────────────────────────────────────┘ │  │                          │
│  │ 金額合計  = 報銷明細．金額 的加總             │  │ （選中元素時自動切到     │
│  └──────────────────── [＋ 新增頁面] ─────────┘  │   「屬性」頁籤）          │
└───────────────────────────────────────────────┴──────────────────────────┘
```

- **左畫布、右面板**（參考圖）；右面板三個頁籤：新增元素／元素集合／屬性。選中元素 ⇒ 切到「屬性」；按 Esc ⇒ 回「新增元素」。卡片上方浮出「類型標籤＋⋮」（複製、上移、下移、刪除；複製會取新代號）。
- 與既有三欄骨架（BUILDER-UX §1、§8-2）的取捨：
  - 工具列從左移到右 ⇒ `#mb-palette` **id 保留**（移位置不改鉤子）；屬性面板從「卡片就地展開」移到右側「屬性」頁籤，`#mb-f-*` id 保留。
  - 右側常駐的輸出／列表預覽 ⇒ 改由上方「預覽」按鈕開抽屜（同一個 `MotrixFormPreview.render`，`mode:'output'|'list'`）。這**改變**第二輪「右側同時顯示、沒有頁籤切換」的做法（§8-2），需使用者確認（§8-6）。理由：畫布本身已經就是表單長相，右側空間讓給元素面板，與參考圖一致。
  - 流程／簽核／通知／輸出／發布步驟不變。
- 鍵盤替代照舊（工具列 `<button>` Enter＝加到目前區塊最後；卡片 Alt+↑↓；頁籤 `role=tablist`）。

---

## 7. 設計⑥ 後端 schema、模組化、安全、相容

### 7.1 schema 新增（只准加，CORE 次版號）

```
body（新增）: description?
fields[]（新增屬性）: multiline?, maxLength?, decimals?, min?, max?, display?('radio'), locked?,
                      default?: 純量 | {"$": "today"|"now"|"requester"},
                      accept?[], maxFiles?, columns?[子欄位], minRows?, maxRows?
fields[].type（新增值）: static, money, datetime, multiselect, file, table
ui（引擎不讀）: builder.seq, form.pages[], form.groups[].page/.cols, form.span{}, form.actions[]
```

- 新型別只加在 `custom_modules.FIELD_TYPES`（`custom_modules.py:27`），**不加進** `custom_fields.TYPES`（那是內建模組自訂欄位 P4 的目錄，範圍不同）；`_coerce` 的新分支寫在 `custom_modules`（包一層），不改 `_cf` 行為。
- 型別規格集中一處：`custom_modules.FIELD_TYPE_SPECS = {type: {label, input: bool, props: {名稱: _P(...)}, valueShape}}`（比照 `doc_template.BLOCK_SPECS` 的 `_P` 寫法，`doc_template.py:308-330`）；`FORM_ELEMENTS`＝元素 preset 清單（§3.1）；`BUTTON_ACTIONS`。

### 7.2 catalog 為唯一來源（守門）

- `helpers.custom_modules` 匯入時 `register_section("fieldTypes", …)`、`("formulaFunctions", …)`（補上 §1.1 的缺口）、`("formElements", …)`、`("formTemplates", …)`；舊端點 `/api/custom-modules/catalog` 加 `fieldTypeSpecs`、`formElements`、`formTemplates`、`buttonActions`（只加鍵，`CATALOG_VERSION` 不動）。
- 頁內 `TYPE_LABELS`（`module-builder.html:937`）拿掉、改讀 spec 的 label；icon 對照留頁內（缺 ⇒ 通用 icon，現行規則）。
- 守門（新）：
  1. 建構器屬性面板的每個控制項對應 `fieldTypeSpecs[type].props` 的一個鍵，雙向（比照 `test_builder_block_param_forms_follow_catalog_specs`，`test_e2e_p8_gaps_2026_09_26.py:329`）；
  2. 執行頁每個 `fieldTypes` 都有渲染分支、沒有多出的分支（取代寫死的 `KNOWN_TYPES`，`custom-records.html:343`），雙向；
  3. `validate_module` 對每個 spec prop 有驗證（掃 spec 鍵 ⇒ 送壞值必須回該 path 的 problem）。
  每道附正對照（植入一個假型別要亮）與反向控制。

### 7.3 L1／L2 邊界

- 全部落在 L1：`helpers/custom_modules.py`、`helpers/formula.py`、`routers/custom_records.py`、`core/catalog.py`（僅登記呼叫）、`core/definitions.py`（僅 S6 第二步的 KINDS）；前端 `module-builder.html`、`custom-records.html`、`static/custom-layout.js`、`static/form-preview.js`、`css/custom-form.css`。
- 不 import 任何 L2；範本檔不點名 L2 模組。改 L1 ⇒ 每段升 CORE 次版號、寫 `core/CHANGELOG.md`、跑 `_l1_interface.py --update`（MODULE-GUIDE §2）；測試範圍接近全量（MODULE-GUIDE §7，結構造成，接受）。

### 7.4 安全

| 面向 | 設計 |
|---|---|
| 公式 | 只擴 `FUNCTIONS` 白名單；`total/avg/count` 在 `check()` 驗參數型別；仍不准屬性存取、下標、lambda（現行 `formula.py:104-152` 的節點白名單不放寬）；最長 500 字照舊 |
| XSS | 段落、選項、標籤、說明、明細值一律 `x-text`（既有守門 `test_custom_records_no_x_html_2026_09_28`、JS sink 白名單，BUILDER-UX §4）；段落的換行用 CSS `white-space: pre-wrap`，**不**支援 HTML／Markdown |
| 上傳：存放 | 不放在 `UPLOADS_ROOT` 底下——`/api/uploads/{path}` 只驗登入（`routers/uploads.py:78-114`），任何登入者猜到路徑就能讀。改放 `core.paths` 新目錄 `custom_uploads/<模組>/<單號>/<uuid><ext>`（demo 隔離沿用 `_effective_subfolder` 規則），檔案分類 F1（MODULE-GUIDE §3.2） |
| 上傳：寫入 | `POST /api/custom/{key}/records/{no}/files/{field}`：`_can_use`＋`_require_draft_owner`（只有草稿的建立者／超管，`custom_modules.py:667-676`）；副檔名白名單取 `accept` 與平台白名單交集；**加檔頭判斷**（PNG／JPEG／PDF magic；現行 `uploads.py:113` 只看副檔名）；拒 SVG；單檔 ≤20MB、`maxFiles` 上限；檔名只存顯示用，磁碟名由伺服器產生 |
| 上傳：讀取 | `GET /api/custom/{key}/records/{no}/files/{id}`：與讀單同一套權限（`_can_use` 或該單簽核人／代理人，`custom_records.py:46-70`）；回應帶 `Content-Disposition: attachment`（PDF 可 inline）、`X-Content-Type-Options: nosniff`；`<img>` 用現行 `?pt=` 同型的短效單路徑簽章 |
| 上傳：值 | 表單送來的 `file` 欄值只接受**本單已上傳的 id**，伺服器用自己的 metadata 覆寫（使用者不能指定路徑） |
| 個資 | 收據、身分證明可能是個資；自訂模組仍不支援 F2（`custom_modules.py:168-170`）。附件欄的說明提示「勿上傳身分證件」，F2 分流另案 |
| 鎖定值 | `locked` 欄由伺服器寫，送來的值丟掉並列入 `dropped`（現行回報方式） |
| 大小 | 明細 ≤200 列、子欄 ≤20、`multiselect` 選項 ≤100、段落 ≤2000 字；超過 ⇒ 422（定義）／400（值） |

### 7.5 既有已發布模組的相容與遷移

- 全部是新增：舊定義不含新鍵 ⇒ 行為完全不變；新執行頁必須能畫舊定義（凍結的 `def_version` 單據永遠用舊定義，`custom_modules.py:679-684`）。
- **不做資料遷移**：已發布模組的 key、前綴、權限一律不動；只有建構器開啟時補 `ui.builder.seq`（寫進下一次草稿，發布才生效）。
- 舊公式、條件照舊用 key 存；畫面改顯示名稱，不改存法。
- 還原舊版（`restore`）⇒ 舊版沒有 `ui.builder.seq` ⇒ 開啟時重新校正（§2），不會撞號。
- 舊執行頁（沒更新的正式機）不會讀到新型別：新型別只會出現在新建構器發布的定義；同一包出貨，無跨版問題。

---

## 8. 分段實作計畫（每段可獨立驗收；A＝後端為主、B＝前端為主）

| 段 | 內容 | 窗 | 依賴 | 驗收（摘要） | 預估 |
|---|---|---|---|---|---|
| S1 | catalog 型別規格＋元素 preset＋`register_section` 補缺口；新純量型別 `static money datetime multiselect`、`multiline/decimals/min/max/display/locked`；default token（伺服器端） | A | 本檔 | 單元：每型別 coerce／驗證（含 NaN、負金額、token 用錯型別）；`locked` 竄改被丟；catalog gaps 不再列 fieldTypes；§7.2 守門 3 | 1 天 |
| S2 | 代號全自動（§2）＋版面改右側面板（§6）＋屬性面板由 spec 產生；`TYPE_LABELS` 拿掉 | B | S1 的 catalog 形狀（可先用假資料） | e2e：新表單不需輸入任何代號即可發布；改名後 key 不變（驗 DB）；刪欄再加不重號；舊草稿開啟 seq 校正；§7.2 守門 1；改題清單寫原因 | 1.5 天 |
| S3 | `table` 型別＋列內公式＋`total/avg/count`＋索引列數＋預設輸出 items_table | A | S1 | 單元：逐列驗證錯誤路徑、加總空值語意、循環引用、200 列上限；輸出預覽含明細 | 1.5 天 |
| S4 | 執行頁渲染新型別（多行、單選、多選、金額、日期時間、段落、鎖定欄、明細表新增／刪除列）＋畫布一致性題擴充 | B | S1、S3 介面 | e2e：報銷單填 3 列 ⇒ 合計自動算（DOM 與 DB 都對）；鎖定欄改不了；§7.2 守門 2 | 1.5 天 |
| S5 | 附件／圖片：存放、上傳、讀取端點＋前端元件 | A（後端）＋B（元件） | S1 | 題：無權限者 404／403、非本人草稿 403、偽副檔名（.png 內容是 HTML）拒收、值只能指到本單檔案、`/api/uploads` 讀不到 | 1.5 天 |
| S6 | 元素集合：內建「報銷申請」「費用申請」＋插入換號；（第二步）管理者另存 `form_template` kind | B（插入）＋A（catalog／kind） | S3、S5 | 一鍵帶入後可直接發布並走完送審 → 核准 → 匯出（D4 同級 e2e）；兩次插入同一範本不撞號 | 1 天（＋0.5 第二步） |
| S7 | 分頁／兩欄／整列、表單說明、動作列按鈕（`ui.form.actions`） | B | S2 | 一致性題：畫布與執行頁的頁、區塊、欄數、整列相同；手機 1 欄；沒設 actions 的舊模組按鈕不變 | 1 天 |

- 合計約 9～9.5 人天；A／B 兩窗平行約 5 個工作天。順序：S1 →（S2‖S3）→（S4‖S5）→（S6‖S7）。
- 每段：當天第一個 commit 補 version_manifest；送測前做 PLAYBOOK §G5 自查（特別 #3 色碼 token、#9 e2e 驗 DOM＋DB、#10 守門雙向）；L1 改動升 CORE 次版號。

### 8.1 核心代碼方向

- `helpers/custom_modules.py`：`FIELD_TYPE_SPECS`、`FORM_ELEMENTS`、`BUTTON_ACTIONS`；`_coerce_ext(f, v)` 包 `_cf._coerce`；`_resolve_defaults(body, values, user, now)` 在 `clean_values` 前；`_validate_fields` 依 spec 驗 props；`_write_index` 對 list 寫列數。
- `helpers/formula.py`：`FUNCTIONS` 加 `total avg count`；`check()` 接受 `tables={key: [欄key]}` 參數驗第二參數。
- `routers/custom_records.py`：catalog 端點加鍵；附件兩支端點。
- `static/custom-layout.js`：`nextKey(def, type)`（單調 seq）、`formPages(def)`、`insertTemplate(def, tpl)`（換號＋引用重寫）、`fieldLabelFormula` ⇄ `fieldKeyFormula`。純函式、可單測。
- `pages/module-builder.html`：右側面板頁籤、屬性面板依 spec 渲染、進階區唯讀代號、預覽抽屜。
- `pages/custom-records.html`：新型別分支、明細表元件、附件元件；仍只准 `x-text`。

---

## 9. 待主持／使用者裁示

1. **系統代號要不要保留「進階」唯讀檢視**（超級管理員除錯／客服用）。推薦：保留、摺疊、唯讀。
2. **編號前綴**：全自動不可改，或自動產生、進階區可改（它印在單號上，客戶可能想要 `EXP`）。推薦：自動＋可改。
3. **附件存放**：獨立目錄＋模組權限端點（推薦），或沿用 `/api/uploads`（任何登入者可讀）。
4. **管理者自存元素集合**：本輪做（L0 `definitions.KINDS` 加 `form_template`，升 CORE）或先只出內建兩個。推薦：S6 先內建、第二步再做自存。
5. **分頁在執行頁**：同頁分段（推薦）或逐頁填寫（上一頁／下一頁）。
6. **版面**：右側改為「新增元素／元素集合／屬性」面板，輸出／列表預覽改由上方「預覽」按鈕開啟——這改變第二輪「右側同時顯示兩個預覽」的做法。推薦：照參考圖改。
7. **按鈕範圍**：只准 catalog 動作（轉換、新增一列、儲存草稿），不開放自訂連結／腳本。推薦：照此。
8. **不在本輪**：分享、多語系、網格（矩陣）、取消發布（停用模組）。請確認；取消發布若要做，另開一段（牽涉側欄、權限、既有單據唯讀）。
