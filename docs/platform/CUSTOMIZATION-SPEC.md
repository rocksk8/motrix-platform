# 網站內自訂：模組建構、拖曳排版、獨立升級（CUSTOMIZATION-SPEC）

> 2026-09-25 使用者提出的核心方向。本檔是**目標規格**：目前還沒開始實作，但底層從現在起所有設計都要為它留好串接點（§5）。
> 使用者裁示寫在 CORE-SPEC「使用者裁示」；本檔描述怎麼達成。

## 0. 三個核心（使用者原話整理）

1. **模組化，並開放超級管理員自訂**：增加一個介面，讓超級管理員在網站上自訂模組的內容，可以帶入系統既有的串接、文件、輸出檔。未來直接在網站上建立與輸出模組。
   - 例子：「租賃報價單」由使用者在系統內自己建立。**這只是例子，不要真的做。**
   - ⇒ 底層的共用能力必須**一開始就留下高串接度**。
2. **未來更新可以拆開、獨立升級**：只更新有變動的模組，減少硬碟與硬體耗損（不必每次整包更新、跑全量）。
3. **網站上自由拖曳排版**：模組排序、列表顯示方式、輸出檔版型，都可以拖曳重排；可以加行列、按鈕、選單、匯出，以及目前系統有的所有選項。

## 1. 使用者裁示（2026-09-25）

| 項目 | 裁示 |
|---|---|
| 自訂模組的資料 | **文件式**：每筆一份結構化資料（JSON），系統依定義自動建索引；建立或修改模組**不用改資料庫結構** |
| 內建模組的自訂範圍 | **外觀與輸出可自訂＋可加自訂欄位**；核心欄位與計算不動（單號、狀態、客戶、金額、品項、簽核等）。自訂欄位放在獨立命名空間，送審時凍結 |
| 自訂邏輯 | **積木式**：欄位、公式、狀態流程、簽核、通知、串接、輸出都從目錄挑，**不能寫程式**；公式用安全的運算式（四則運算、條件、引用欄位） |
| 排版的套用範圍 | **公司預設一套＋可依角色覆寫**；個人只能調整欄位的顯示與排序（沿用既有的「清單偏好」）；每次發布都有版本、可以還原 |

## 2. 架構：三種東西，同一套積木

```
            ┌───────────────── 能力目錄（L1，唯一來源）─────────────────┐
            │ 欄位型別｜公式函式｜狀態流程｜簽核（分層）｜通知事件｜串接（provider／端點）│
            │ 輸出引擎（PDF／Excel 版型）｜檔案附件｜權限（row_access）｜編號規則   │
            └────────────────────────────────────────────────────────────┘
                 ▲ 只從這裡挑                ▲ 只從這裡挑               ▲ 註冊進來
   ┌─────────────┴──────┐   ┌──────────────┴────────┐   ┌──────────────┴──────┐
   │ 自訂模組（資料定義）   │   │ 版面定義（覆寫內建或自訂）│   │ 內建模組（程式碼）      │
   │ 實體／欄位／流程／輸出 │   │ 選單／列表／表單／輸出版型 │   │ 報價、案件…（modules/）│
   └────────────────────┘   └──────────────────────┘   └────────────────────┘
```

- **能力目錄**：所有可以被組裝的東西都登記在這裡，並帶有「契約」：參數、回傳、所需權限、版本。自訂模組、排版器、內建模組**都只透過目錄互相串接**。它是 CORE-SPEC §7「端點登錄表」的擴充。
- **自訂模組**是「資料」不是「程式」：定義存在資料庫、有版本、先草稿再發布、可以還原；執行時由 L1 的「自訂模組引擎」解譯（通用的新增、修改、查詢 API，權限、稽核、備份分類一律沿用 L1）。
- **內建模組**要把自己「可以被自訂的點」登記進目錄：欄位清單（核心或可顯示）、動作（按鈕）、輸出、列表欄位。排版器只能動這些點，**不能改核心欄位與計算**。

## 3. 各部分要點

### 3.1 自訂模組的定義（草稿 → 發布）

| 定義 | 內容 |
|---|---|
| 實體 | 名稱、編號規則、欄位（型別、必填、預設值、驗證、公式、參照其他實體或內建模組的資料） |
| 流程 | 狀態與轉換；每個轉換可以掛：簽核（L1 分層簽核）、通知（L1 事件）、串接（呼叫目錄裡的 provider） |
| 輸出 | 從輸出引擎挑版型（PDF／Excel），欄位拖曳配置；可以套用公司身分（company_identity）與據點 |
| 權限 | 誰可以看、改、簽核（沿用模組權限 key 與 row_access） |
| 資料分類 | 每個欄位標 T／F 類別（MODULE-GUIDE §3）；含個資的欄位自動走個資備份的分流 |

- 發布時產生**不可變的版本**；已經送出的單據凍結在它當時的版本（比照條款組與公司身分快照）。
- 自訂模組同樣適用「拿掉不影響其他模組」、授權與啟停（CORE-SPEC §9c）。

### 3.2 拖曳排版（版面定義）

- 可以排：選單的順序與分組、列表的欄位、排序與篩選、表單的行列與區塊、按鈕與選單的位置、匯出按鈕、輸出檔版型。
- 版面存成定義，有版本、可還原；套用順序：**角色覆寫 > 公司預設 > 模組原始版面**；個人只能調欄位的顯示與排序。
- 排版器只列出目錄裡這個模組登記的元件，**不會出現「程式沒有提供」的選項**。

### 3.3 獨立升級

- 每個模組各自是一個升級單位：只帶 `modules/<key>/`（含它的 migration）的「模組更新包」，可以單獨套用與回滾；只跑該模組的測試加契約測試。
- 底層（L0／L1）是另一個升級單位，頻率低，照主版號或次版號規則走（MODULE-GUIDE §2）。
- 自訂模組與版面定義是資料，**不需要升級程式**；它們跟著資料庫備份。
- 儀表板要能顯示「這次只更新哪些模組」（已有：D2 模組變更預覽），並且只套用那些模組。

### 3.4 輸出引擎版型化（P2，C 2026-09-25）

**目標**：單據的 PDF 不再由每種單據一支寫死的 builder 產生，而是由「**版型定義（資料）＋單據視圖（資料）**」經 L1 輸出引擎組出 HTML，再交給既有的 Edge 轉 PDF。排版器（P9）之後只編輯版型定義。

**三層，各自的責任**

| 層 | 內容 | 誰能改 |
|---|---|---|
| 單據視圖（view） | 由擁有模組把一筆單據整理成**扁平、已計算好**的欄位（金額、稅、狀態、申請人…）。計算只在這裡，版型不能計算核心欄位（§1 裁示：核心欄位與計算不動） | 程式（擁有模組） |
| 版型定義（template） | JSON：`{key, version, theme, blocks:[…]}`。只能引用視圖欄位與 `customFields.*`；只能使用積木目錄裡的積木（見下） | 預設版型隨程式出貨；覆寫版（公司／角色）存在 P5 版面定義，有版本 |
| 輸出引擎（L1） | `helpers/doc_template.render(template, view, ident)`：依積木逐一產生 HTML 片段，**所有值一律跳脫**；不執行任何版型提供的程式 | 程式（L1） |

**積木目錄（v1）**：每個積木有型別與參數，未知型別 ⇒ 渲染失敗並指出是哪一塊（不略過、不猜）。

| 積木 | 參數 | 說明 |
|---|---|---|
| `watermark` | `unless`（條件）、`text`、`small` | 預覽稿浮水印（例：狀態不是「已核准」） |
| `accent_bar` | — | 頁首色條 |
| `identity_header` | `title` | 公司抬頭（據點身分＋快照，沿用 company_identity）＋單據標題 |
| `meta` | `fields:[{label, path, style?, format?}]` | 單號／日期等三欄資訊列 |
| `banner` | `unless`、`text`（可含 `{path}`） | 預覽提示列 |
| `boxes` | `boxes:[{title, rows:[{label, path, format?}]}]` | 兩欄資訊框 |
| `when` | `path`、`equals`、`then:[積木]`、`else:[積木]` | 依視圖欄位切換一組積木（例：自訂品項／自訂金額） |
| `items_table` | `label`、`source`、`columns:[{title, path, align?, width?, format?}]`、`numbered`、`hide_when_empty?` | 品項表 |
| `amount_box` | `label`、`path` | 單一金額框 |
| `totals` | `rows:[{label, path, format, grand?}]` | 小計／稅／總額 |
| `approval_sign` | — | 簽核紀錄（沿用 L1 分層簽核的呈現） |
| `sign_boxes` | `boxes:[{label, name_path?, date_label, date_path?}]` | 手寫簽名框 |
| `identity_footer` | — | 公司頁尾 |
| `fit_a4` | — | 單頁 A4 自動縮放 |

**格式（format）**：`text`（預設）、`money`（千分位、無小數）、`date10`（取前 10 字）、`mono`（Arial）、`spec_brand`（品名＋全形空白＋品牌）。**條件**：`{path, equals}`（相等）或 `{path, in:[…]}`；不支援任意運算式（公式另見 P8 的安全運算式）。

**主題（theme）**：版面的 CSS 是整套主題（例：`voucher_standard`），v1 不開放逐條改 CSS；主題也登記在能力目錄。

**驗收**
1. 第一種單據（開票申請憑據）改為「視圖＋預設版型」，輸出的 HTML 與改版前的 builder **逐位元組相同**，涵蓋：自訂品項／自訂金額、已核准／預覽稿、有無報價品項、特殊字元跳脫、據點快照抬頭。舊 builder 凍結一份在測試裡，作為永久的正對照。
2. 反向控制：版型改一個標籤、調換兩塊順序、拿掉一塊 ⇒ 輸出隨之改變，且其他塊不變；未知積木 ⇒ 明確錯誤；版型引用視圖沒有的欄位 ⇒ 空字串（跟既有 builder 對缺欄位的處理一致），並由版型驗證器事先列出。
3. 版型本身是資料：可以序列化、比對、存進 P5 版面定義；預設版型的檔案位置由 `core.paths` 以外的程式目錄決定（隨程式出貨，不是使用者資料）。

4. 第二種單據（勞務報酬單，2026-09-26，主持裁示 A）驗收＝與凍結的舊 builder（`tests/_frozen/legacy_payslip_html.py`）相比：**結構正規化後相同**（`re.sub(r'>\s+<', '><', …)` 之後逐字相同，文字內容與屬性一字不差）＋**瀏覽器 innerText 逐字相同**＋**PDF 抽出的文字相同**；截圖只當參考。理由：舊 builder 的空白排版不規則（同類的列在不同位置縮排不同、附件頁在 `#root` 之外），要逐位元組相同就得為每種縮排各做一個特例積木；而 `>\s+<` 正規化會吃掉行內元素之間有意義的空白，所以另外用 innerText 與 PDF 文字把關（有反向控制題）。開票申請憑據維持**逐位元組相同**。
   - 新增的積木：`doc_header`、`section_title`、`kv_table`（列可帶 when／unless）、`part`（程式提供的片段：重印註記、身分證與存簿附件頁）、`footer_text`、`text_page`；`sign_boxes` 加 `variant: named`；格式加 `ntd`；條件加 `present`；主題可自帶外框（`frame`）與 `#root` 之外的 `after_root` 積木。
   - 比對時拿掉改版後新增的個資告知兩塊（`id` 以 `privacy` 開頭）：R3 規定已告知 ⇒ 印「已告知（時間、人員）」；沒有 ⇒ 附上告知事項全文（公司資料設定的「個資蒐集告知」，空白用範本）。

**不做（v1）**：Excel 版型（第二步，沿用 `helpers/xlsx_out`）、逐條 CSS、拖曳介面（P9）、覆寫版的儲存（P5）。

### 3.5 定義文件庫：草稿、版本、差異、還原（P5 的儲存，P4／P8／P2 覆寫共用；C 2026-09-25）

版面、輸出版型的覆寫版、自訂欄位的定義、自訂模組的定義，性質都一樣：**一份結構化資料（JSON），要有草稿、要能發布成不可變的版本、要能比對差異、要能還原**。所以只做一套 L1 儲存，用 `kind` 區分用途，不各做一套。

**資料表** `ui_definitions`（L1，由 `core` 的第一支模組 migration 建立，記在 `module_schema_versions`，不動 V9 基準）：

| 欄 | 說明 |
|---|---|
| `kind` | `layout`（P5 版面）／`output_template`（P2 版型覆寫）／`custom_fields`（P4）／`custom_module`（P8） |
| `key` | 同一 kind 內的對象，例如 `invoice_voucher`、`module:shipping_notes` |
| `scope` | `company`（公司預設）或 `role:<角色>`（角色覆寫）；個人層不在這裡（沿用既有清單偏好） |
| `version` | 同一 (kind, key, scope) 內遞增；**草稿的 version 是 0**，每個 (kind, key, scope) 最多一份草稿 |
| `status` | `draft`／`published`；已發布的列**不可修改、不可刪除** |
| `body_json` | 定義本身 |
| `note`、`created_by`、`created_at`、`published_by`、`published_at` | 誰、何時、為什麼 |

**操作**（`core.definitions`，純函式＋一張表，API 由 L1 router 包一層，僅超級管理員）：

| 操作 | 行為 |
|---|---|
| `save_draft(kind, key, scope, body)` | 建立或覆寫草稿（草稿可以改） |
| `publish(kind, key, scope, note)` | 先跑該 kind 的驗證器，全部通過才發布：草稿內容複製成新的 `published` 版本（version＝上一版＋1），草稿刪除 |
| `versions(kind, key, scope)` | 版本清單（不含 body） |
| `get(kind, key, scope, version)` | 取一版 |
| `diff(a, b)` | JSON 差異：新增／刪除／變更的路徑（例：`blocks[5].boxes[0].rows[0].label`），給「發布前看差異」用 |
| `restore(kind, key, scope, version, note)` | **不改歷史**：把舊版內容再發布成一個新版本（版本號繼續往上） |
| `resolve(kind, key, role)` | 套用順序：`role:<角色>` 最新發布版 ＞ `company` 最新發布版 ＞ 程式出貨的預設（例：`helpers/output_templates/<key>.json`） |

- **驗證器登記**：每個 kind 登記一支驗證器（例：`output_template` ⇒ `doc_template.validate`）。驗證器回傳問題清單，每一項帶**位置**（JSON 路徑），給建構器標出錯在哪。
- **已送出的單據凍結在當時的版本**：單據存 `(kind, key, scope, version)`，重印時用那一版，不用最新版。
  - 輸出版型的實作（C 2026-09-25）：單據資料裡的 `outputTemplate: {scope, version}` 有值 ⇒ 用那一版（找不到已發布的那一版 ⇒ WARNING 後改用目前的）；沒有 ⇒ 公司最新發布版 ⇒ 程式預設。讀定義失敗 ⇒ 程式預設＋WARNING（覆寫層出錯不可以讓單據印不出來）。**寫入 `outputTemplate` 的時機（送審時）尚未接**，與 P4 的 `customFieldsVersion` 同一批做。
- 資料分類：`ui_definitions` 是 T1（每日 JSON 匯出、跟著資料庫備份）；自訂模組與版面是資料，**不需要升級程式**（§3.3）。

### 3.6 自訂欄位命名空間（P4，C 2026-09-25）

- 內建模組的單據，在自己的 `data_json`（或對應的 JSON 欄位）裡預留 `customFields: {}`；**核心欄位的名稱與計算不動**（§1 裁示）。
- 欄位定義是 `ui_definitions` 的 `custom_fields` kind（key＝模組 key），body：`{fields:[{key, label, type, required, default, options?, formula?, dataClass}]}`。
  - `key` 限 `[a-z][a-z0-9_]{0,39}`，**不可以與核心欄位同名**（模組在 P3 描述裡列出核心欄位）。
  - 型別目錄（v1）：`text`、`number`、`date`、`select`、`checkbox`；`dataClass` 標 `T1`／`F2`（F2 走個資分流，MODULE-GUIDE §3）。
- 儲存時由 L1 `custom_fields.clean(module, values, definition)` 驗證與正規化：未定義的鍵丟掉並回報、型別不符回 400 並指出是哪一欄、必填檢查。
- **送審時凍結**：單據記下 `customFieldsVersion`（定義的發布版本號）；之後定義改了，舊單據仍依它自己的版本顯示與輸出。
- 輸出版型（P2）以 `customFields.<key>` 引用；驗證器會檢查引用的欄位是否存在於該版定義。

### 3.7 自訂模組引擎（P8 後端，C 2026-09-25；前端建構器由主持依 §8.1 做）

**定義**＝定義文件庫的 `custom_module` kind，key＝模組 key（`[a-z][a-z0-9_]{1,39}`），scope 一律 `company`。草稿、發布、差異、還原走 `/api/definitions/custom_module/{key}/…`（§3.5）；發布前跑 `helpers.custom_modules.validate_module`，每個問題帶 `path`。

```json
{
  "name": "測試用設備借用單", "icon": "box", "menu": {"group": "…", "order": 10},
  "permission": "custom.equipment_loan",
  "numbering": {"prefix": "EL", "date": "YYYYMMDD", "digits": 4},
  "fields": [
    {"key": "qty", "label": "數量", "type": "number", "required": true},
    {"key": "total", "label": "總值", "type": "formula", "formula": "qty * unit_value"},
    {"key": "borrower", "label": "借用人", "type": "ref", "target": "users"}
  ],
  "workflow": {
    "initial": "draft",
    "states": [
      {"key": "draft", "label": "草稿"},
      {"key": "pending", "label": "簽核中", "approval": {
        "tiers": [{"approvers": [{"username": "mgr"}]}, {"approvers": [{"sourceType": "division_manager", "divisionId": 3}], "when": "total > 10000"}],
        "on_approved": "approved", "on_rejected": "rejected"}},
      {"key": "approved", "label": "已核准", "notify": {"requester": true}},
      {"key": "returned", "label": "已歸還", "final": true}
    ],
    "transitions": [{"key": "submit", "label": "送審", "from": "draft", "to": "pending"}]
  },
  "output": {"template": {"theme": "voucher_standard", "blocks": ["…doc_template 積木…"]}}
}
```

| 項目 | 規則 |
|---|---|
| 欄位型別 | `text`／`number`／`date`／`select`／`checkbox`（同 §3.6）＋`formula`（唯讀，由公式算）＋`ref`（`target`：參照目錄 `users`、`customers`，或 `custom:<模組>`） |
| 公式 | `helpers.formula`：數字、字串、欄位 key、`+ - * / %`、比較、`and／or／not`、`if(條件, 是, 否)`、`round`、`min`、`max`、`sum`、`abs`、`coalesce`、`days_between`。只能一行，最長 500 字。**空值不等於 0**（`coalesce(x, 0)` 才當 0）；除以 0 ⇒ 那一欄空值並回報。循環引用在發布前擋下。數字欄位不收 NaN／無限大（稽核 D C-M5）；發布前用樣本資料實際算一次公式與簽核條件，型別錯誤在發布時就指出位置（C-S1） |
| 資料分類 | 只收 T1。**F2（個資）欄位一律拒絕**，直到個資分流接上自訂模組（單據是整份 JSON，分流要另外做） |
| 流程 | 起始狀態、終點（`final`）至少一個；每個狀態都要從起始狀態走得到；非終點狀態要有出路；終點不可以再轉出。轉換可以設 `requester_only` |
| 簽核 | 掛在**狀態**上：進入該狀態就展開簽核層（沿用 `helpers.tiered_approval`：依序、代理人、當層任一人可退回；簽核人可以是帳號、部門主管、處主管、申請人主管）。層可以帶條件 `when`（公式），條件不成立那一層就不列入；全部不成立 ⇒ 直接視為通過。簽核中的狀態**不能用轉換跳過簽核**。**條件只有明確不成立（False 或 0）才跳過該層；算出空值（有欄位沒填）或執行出錯 ⇒ 那一層照簽**，回應的 notices 寫明原因（稽核 D C-M1／C-M2、C-O4）。起始狀態不可以掛簽核（C-S3）；簽核狀態的 on_approved 不可以互相指向，執行時自動通過最多連跳 20 次，超過回 409（C-M3） |
| 通知與事件 | 狀態的 `notify`：`requester`、`users`。進入簽核狀態時通知第一位簽核人，每過一層通知下一位。每次狀態改變發事件 `custom_module.transitioned`（`module, recordNo, from, to, action, by`）。**通知與事件都在 commit 之後才送** |
| 編號 | `前綴-日期-流水號`；日期格式 `YYYYMMDD`（每日重新計）、`YYYYMM`（每月）、空白（不分期）；位數 3～8 |
| 輸出 | `output.template` 是 doc_template 版型（§3.4），視圖欄位：`recordNo`、`status`、`statusLabel`、`createdBy`、`createdAt`、`moduleName`、`fields.<key>`（也可以直接寫 `<key>`）、`approval`。沒有指定版型 ⇒ 通用版型（抬頭、編號、狀態、每個欄位一列、簽核欄、頁尾） |
| 凍結 | 單據建立時記下 `def_version`；之後的修改、流程與輸出都用那一版。起始狀態以外不能改內容 |
| 權限 | 超級管理員，或使用者的模組清單裡有 `permission`（預設 `custom.<key>`）。簽核人不需要模組權限，也能讀單據、簽自己那一層。permission 不可以用內建模組的 key，也不可以與另一個已發布的自訂模組共用（C-S4）；簽核代理人也能讀單與輸出（C-S2）。**草稿（起始狀態）只有建立者與超級管理員可以修改、送出**，同權限的其他人只能看（使用者裁示 U14，2026-09-26；後端 403，讀單回 `canEdit`） |
| 儲存 | 表 `custom_records`（每筆一份 JSON）、`custom_record_values`（欄位索引，可由 JSON 重建，不匯出）、`custom_record_counters`、`custom_record_log`。由 core 的第 2 支模組 migration 建立；T1，每日 JSON 匯出、demo 清空 |

**API**

| 用途 | 端點 |
|---|---|
| 側欄清單（使用者看得到的已發布模組） | `GET /api/custom-modules` |
| 表單與列表要的定義 | `GET /api/custom/{key}/meta` |
| 單據 | `GET／POST /api/custom/{key}/records`（列表可用 `status`、`field`＋`value` 篩選）、`GET／PUT /api/custom/{key}/records/{no}` |
| 流程 | `POST …/records/{no}/transitions/{t}`、`POST …/records/{no}/approve`、`POST …/records/{no}/reject`（body 可帶 `note`） |
| 輸出 | `GET …/records/{no}/output`（HTML）、`?format=pdf` |
| 建構器（僅超級管理員） | `GET /api/custom-modules/catalog`（欄位型別、公式函式、參照對象、日期格式、輸出積木）、`POST /api/custom-modules/formula/check`（`{formula, fields}` ⇒ `problems[{pos, message}]`）、`POST /api/custom-modules/numbering/preview`、`POST /api/custom-modules/{key}/output/preview`（整份草稿定義 ⇒ 用樣本資料的 HTML） |

錯誤：欄位值不對 ⇒ 400 `problems[{key, message}]`；定義問題 ⇒ 422 `problems[{path, message}]`；狀態不對 ⇒ 409；沒權限 ⇒ 403；模組沒發布 ⇒ 404。

**未做（P8 後續）**：流程圖的視覺化資料（座標）由前端自己存在定義裡的 `ui` 鍵（引擎不讀它）；列表的排序與分頁；附件欄位；`custom:<模組>` 參照的顯示名稱；個資分流；自訂模組的授權與啟停（§9c 的 license_key）。

## 4. 不做的事（刻意）

- 不讓使用者寫程式或腳本（裁示）。
- 自訂內容不能改內建模組的核心欄位與計算（裁示）。
- 網站上建立模組**不會**在正式機上動態改資料庫結構（裁示：文件式）。

## 5. 對「現在」的影響：底層要先留好的串接點

以下項目從現在起納入第一階段，排在模組搬遷之前或同時進行（ROADMAP 階段 P）：

| # | 底層要留的東西 | 為什麼現在就要 |
|---|---|---|
| P1 | **能力目錄**：擴充 CORE-SPEC §7 的端點登錄表，端點、provider、輸出引擎、事件、欄位型別都登記，並帶契約版本 | 自訂模組與排版器只能從目錄挑；模組搬遷時順手登記，事後補的成本高 |
| P2 | **輸出引擎版型化**：PDF／Excel 由「版型定義＋資料」產生，不再每種單據各寫一支 builder | 使用者要拖曳輸出版型；現在 pdf_gen 有 9 支寫死的 builder |
| P3 | **模組描述**：每個內建模組在 module.json 描述可自訂點（欄位、動作、列表欄位、輸出） | 排版器靠它知道能擺什麼 |
| P4 | **自訂欄位命名空間**：內建模組的單據預留 `customFields{}` 並在送審時凍結 | 裁示：內建模組可加自訂欄位 |
| P5 | **版面定義的儲存與套用機制**（公司、角色、個人三層、有版本） | 先有機制，排版器才有地方存 |
| P6 | **事件匯流排**（STATES P-IP-06 目前「未實作」） | 自訂流程的「狀態轉換時通知或串接」要靠它 |
| P7 | **模組更新包**：以單一模組為單位打包、套用、回滾 | 裁示 2：獨立升級 |

實作順序與驗收條件寫在 ROADMAP 階段 P；每一項開工前，都要先把規格細節寫進本檔再動程式。

## 6. P6 事件匯流排（規格細節，2026-09-25 主持）

**用途**：模組之間「發生了什麼事」的通知，例如報價核准、獎金進入待發放。之後自訂模組的流程在狀態轉換時觸發通知或串接，也用它。它跟 provider 不同：provider 是「我要向你拿一樣東西」（呼叫方需要回傳）；事件是「我告訴大家發生了一件事」（發佈方不在乎誰聽）。

| 規則 | 內容 |
|---|---|
| 宣告 | 事件要先宣告：`events.declare(name, owner, version, fields)`。宣告會進能力目錄（P1），欄位清單就是契約 |
| 發佈 | `events.publish(name, payload)`：**在發佈方的交易 commit 之後呼叫**。沒有訂閱者是正常情況 |
| 發佈時機的守門（2026-09-26，稽核 D H-S1） | 同一條執行緒還開著 `core.txn.begin_write` 的寫交易時就發佈 ⇒ 違反契約（測試 raise、產品記 ERROR 照送）。**⚠ 已知範圍**（稽核 D N-3）：只認得 `begin_write` 開的交易；sqlite 在第一個寫入語句時隱式開啟的交易抓不到，所以寫入路徑仍須遵守「讀改寫一律走 begin_write」（既有守門 test_begin_only_via_begin_write） |
| payload（2026-09-26，稽核 D H-M1） | **只能放 JSON 可序列化的值**；每個訂閱者拿到的是 JSON 來回的完整副本〔更正：原本的實作是 `dict(payload)` 淺拷貝，巢狀資料會被訂閱者改掉，連發佈方的物件也會被改〕 |
| 執行時間（2026-09-26，稽核 D H-S2） | 訂閱者同步執行，**必須很快返回**；超過 0.2 秒記 WARNING。寄信、呼叫外部 API 這類慢工作，要由訂閱者自己丟到背景 |
| 訂閱 | `events.subscribe(name, handler, subscriber=<模組 key>)`：在模組匯入時登記。模組沒載入（未安裝、停用、未授權），它的訂閱就不存在 ⇒ 只是少了一個反應 |
| 隔離 | 任何一個訂閱者丟例外，都**不影響發佈方，也不影響其他訂閱者**；失敗記 ERROR，並留在「最近失敗」清單（`events.recent_failures()`），供管理頁顯示 |
| 契約檢查 | 發佈沒宣告過的事件，或 payload 少了宣告的欄位：預設記 ERROR 照送；設了 `MOTRIX_STRICT_DB_GUARDS=1`（測試）就 raise（沿用「守門預設記 ERROR 照寫」的原則） |
| 順序 | 同一事件的訂閱者依登記順序執行；訂閱者不可以依賴其他訂閱者的結果 |
| 不做的事 | 不做跨行程或持久化佇列（目前單機單行程）；也不做「交易內」的同步參與，需要同一個交易內一起寫的，走 provider |

## 7. P7 模組更新包（規格細節，2026-09-25 B）

**用途**：以單一模組為單位更新已安裝的系統（裁示 2：獨立升級），不動 L0／L1，也不動其他模組。儀表板的操作介面由主持接（D2 已能預覽「這次改到哪些模組」）。

| 項目 | 規則 |
|---|---|
| 工具 | `python tools/platform/module_update.py build／check／apply／rollback／list` |
| 包的內容 | `backend/modules/<key>/`（**不含** `tests/`、`SPEC.md`）＋它 `module.json` 宣告的頁面 `frontend/pages/<path>`＋`module-update.lock.json`（lock 結構同 9c①，`kind: "module_update"`，只列這一個模組；另記 `built_from` commit 與 `core_version`） |
| 打包前提 | 工作樹乾淨（只打已 commit 的內容，從 git 取檔）；該模組的 CHANGELOG 最上面版號＝module.json version（G2） |
| 套用前檢查（全部過才動手） | ① 包的 lock 與內容雜湊一致 ② 安裝目錄有 `backend/modules.lock.json`（full_package）③ 安裝目錄的 `CORE_VERSION` 滿足模組 `core` 範圍 ④ 版本只能往上（同版或降版 ⇒ 拒絕，除非 `--allow-downgrade`）⑤ 模組帶 `migrations/` ⇒ 拒絕（模組自有 migration 尚未實作；見下方「未做」） |
| 套用 | 先把安裝目錄現有的 `modules/<key>/` 與它的頁面複製到 `module_backups/<key>/<時間>/`（附雜湊清單），再整個替換；更新安裝目錄的 `modules.lock.json` 該模組那一筆；寫 `module_backups/<key>/<時間>/apply.json` 紀錄。**需要重啟服務才生效**（路由在啟動時掛上，同 9c③） |
| 回滾 | 從最近一次（或指定）備份還原 `modules/<key>/` 與頁面；還原後雜湊必須與備份時逐一相等，否則報錯；`modules.lock.json` 還原為備份時那一筆 |
| 首次安裝 | 安裝目錄沒有這個模組 ⇒ 允許（備份記錄「原本不存在」，回滾＝移除該模組與頁面） |
| 資料 | 不動資料庫；模組的表由凍結 migration 或未來的模組 migration 建立 |
| 守門 | `tests/platform/test_module_update.py`：合成安裝目錄上跑 build→apply→rollback，雜湊逐一相等；每一條套用前檢查各有反向控制 |

**未做（排入 ROADMAP 階段 P）**：模組自有 migration 的套用與回滾（P7b）；正式機上的實際套用流程（停服務、套用、重啟、健康檢查、失敗自動回滾）由儀表板串接（主持）。

## 8. 建構介面與排版器的畫面需求（P8 前端、P9；主持 2026-09-25，給 C 設計 P5／P8 API 時對齊）

> 參考 BENCHMARK §3.3（NUEiP／Ragic 的區塊自訂）與 §4（使用者體驗）。原則：**所見即所得、每一步都能預覽、發布前能看差異、發布後能還原**。

### 8.1 自訂模組建構器（P8，超級管理員專用頁 `module-builder.html`）

| 步驟 | 畫面 | 需要的 API（C 設計時對齊） |
|---|---|---|
| ① 基本 | 名稱、圖示、選單位置、編號規則（前綴＋日期＋流水號）、權限 key | 草稿的建立與儲存；編號規則即時預覽（例：`RQ-20260925-0001`） |
| ② 欄位 | 左邊是欄位型別清單（從能力目錄取），拖進中間的表單；右邊是屬性面板（必填、預設值、驗證、公式、參照、T／F 分類、欄位層權限 R8） | 欄位型別目錄；公式語法檢查（回傳錯誤位置）；參照對象清單（自訂模組＋內建模組公開的資料） |
| ③ 版面 | 表單的行列與區塊、列表的欄位與排序（跟 P9 同一個排版元件） | P5 版面定義的讀寫 |
| ④ 流程 | 狀態圖：拖出狀態、連線成轉換；轉換上掛簽核（R4 積木：sequential／all／any、條件、退回到指定關）、通知（P6 事件）、串接（目錄裡的 provider） | 流程定義的驗證（孤立狀態、沒有終點、條件語法） |
| ⑤ 輸出 | 從 P2 輸出引擎挑版型，把欄位拖進版型；即時預覽 PDF／Excel | 用樣本資料產生預覽 |
| ⑥ 發布 | 顯示跟上一版的差異（欄位、流程、輸出）；已送出的單據仍然停在舊版本；可以還原到任何一版 | 版本清單、差異、發布、還原 |

- 草稿自動存檔；發布前做完整驗證，並列出所有問題的位置。
- 建構器本身只從能力目錄挑選，不會出現「程式沒有提供」的選項。

### 8.2 拖曳排版器（P9，內建與自訂模組共用）

- 進入方式：超級管理員在任一模組頁面按「編輯版面」⇒ 同一頁切換成編輯模式（不跳到別頁）。
- 能動的東西只有該模組在 module.json 登記的可自訂點（P3）：列表欄位、表單區塊、按鈕、選單、匯出按鈕、輸出版型。
- 套用範圍選擇：公司預設，或某個角色；右上角可以「以某個角色預覽」。
- 儲存成草稿 ⇒ 預覽 ⇒ 發布；發布有版本、可以還原；個人只能調整欄位的顯示與排序（沿用既有的清單偏好）。
- 行動版：排版器只在桌機使用；發布出來的版面必須在手機上可讀（R7）。

### 8.3 驗收（D4）

e2e：用建構器從零建立一個「測試用設備借用單」（欄位含公式與參照、兩層簽核含條件、事件通知、PDF 輸出），不改任何程式碼，就能新增、送審、核准、匯出；再用排版器調整內建模組（例如出貨單）的列表與表單，並依角色套用，另一個角色看到的仍然是公司預設。

## 9. 法規參數（ROADMAP 階段 R；BENCHMARK §6、§7；2026-09-25 R）

**用途**：扣繳率、起扣標準、補充保費門檻、最低工資這類「法規決定、每年會變」的數字，集中成一份**依生效日版本化**的參數，由 L1 提供；模組只問「這張單的日期適用哪一版」，不自己寫死數字。報價的零稅率／免稅依據、個資蒐集告知是同一類「法規要求的欄位」，一併寫在這一節。

### 9.1 勞報單的法規參數（R1）

| 規則 | 內容 |
|---|---|
| 服務 | L1 `helpers/legal_params.py`。設定鍵 `tax_rules_versions`＝清單 `[{version, effectiveFrom, resident, non_resident, nhi, minimum_wage, sources}]`；沒有這個鍵時，舊的單一設定 `tax_rules` 視為 `effectiveFrom=2026-01-01` 的一版（相容 V9） |
| 選版 | 依**單據日期**（勞報單 `slipDate`；空白＝今天）挑 `effectiveFrom ≤ 日期` 的最新一版。日期早於最早一版 ⇒ **拒絕存檔**並說明要先新增哪一年的版本（算不出來就不猜） |
| 單據凍結 | 建立時存 `taxRulesVersion`（欄位 `tax_rules_version`）與參數快照 `data_json.taxRulesSnapshot`。**修改舊單沿用快照**（沒有快照的舊單依版本號查；版本號也查不到 ⇒ 409，請使用者選擇重算）；只有使用者明確勾選「依給付日重新套用規則」（`recalcTaxRules: true`）才改用日期挑版。前端送來的快照一律忽略，以資料庫裡的為準 |
| 版本不可改 | 已生效（`effectiveFrom ≤ 今天`）的版本不能修改或刪除，只能新增；尚未生效的可以改或刪。要更正已生效的數字 ⇒ 新增一版 |
| 獎金門檻倍數 | `nhi.bonus_insured_multiple`（獎金補充保費門檻＝投保金額 × N；115 年＝4）：必填、≥1、設定頁可編輯；舊資料沒有這個鍵 ⇒ 讀取時補 115 年的值（U4 獎金分潤使用，INTEGRATION-POINTS IP-7） |
| 守門 | 每一版都要「兼職薪資補充保費門檻 `nhi.thresholds["50"]` ＝ 當年最低工資 `minimum_wage.monthly`」：存檔時不符 ⇒ 400；載入的資料不符 ⇒ 設定頁與勞報單頁顯示警告；預設值與 `db.py` 種子由測試守住 |
| 跨年提示 | 進入 12 月且沒有任何 `effectiveFrom` 在下一年的版本 ⇒「法規參數設定」頁與勞報單頁顯示「下一年度規則未設定」；今年沒有任何版本 ⇒ 顯示「今年沿用 ○○ 版的規則」 |
| 權限 | 讀寫都是 superadmin（勞報單頁試算另允許具 `payslip` 模組者讀單一版） |
| 端點 | `GET /api/legal-params/tax-rules`（清單＋狀態）、`PUT /api/legal-params/tax-rules`（整份清單，驗證後寫入）、`GET /api/tax-rules?date=｜version=`（單一版，勞報單頁試算用；不帶參數＝今天） |
| 預設值 | 只放查得到官方來源的 115 年（2026）版，來源寫在每一版的 `sources`。**116 年（2027）不預設**：最低工資 30,900 元尚待行政院核定、起扣標準尚未公告；核定後由管理者在設定頁新增一版 |

### 9.2 零稅率、免稅的依據（R2）

| 規則 | 內容 |
|---|---|
| 欄位 | 報價 `data_json.taxBasis = {code, note}`；核心欄位（稅別、稅率、金額）不動 |
| 選項 | 零稅率：營業稅法 §7 第 1～9 款＋「其他法律規定」；免稅：§8 第一項（款次與說明由使用者填）＋「其他法律規定」。「其他」與 §8 一律要填說明 |
| 何時必填 | 稅別為零稅率或免稅，且存檔狀態**不是草稿**（送審、解鎖修改）⇒ 沒有有效依據回 400。草稿可以先存（自動存檔不被擋）。應稅單的 `taxBasis` 存檔時移除 |
| 開票申請 | 新建開票申請時，零稅率／免稅報價要有依據：報價上有就帶入；沒有（舊單）⇒ 申請時補填（`taxBasis`），否則 400。依據寫進快照 `taxBasis` 與 `taxNote` |
| 舊資料 | 沒有依據的舊報價、舊開票申請照常顯示；只有新送出的單據要求 |

### 9.3 個資蒐集告知（R3，個資法 §8 I）

| 規則 | 內容 |
|---|---|
| 告知文字 | 公司資料設定頁新增「個資蒐集告知」（`company_profile.privacy_notice`）；空白時使用範本（L1 `helpers/privacy_notice.py`），範本涵蓋 §8 I 六款：機關名稱、蒐集目的、個資類別、利用期間／地區／對象／方式、§3 權利與行使方式、不提供的影響 |
| 列印 | 承攬商頁與勞報單頁都有「列印告知書」（公司名稱＋告知文字＋當事人姓名＋簽名欄） |
| 已告知紀錄 | 勾選「已告知當事人」⇒ **伺服器**記下時間、人員與告知文字的雜湊；已記錄的不能被覆蓋或清除。勞報單存在 `data_json.privacyNotice`；承攬商存在 L1 設定鍵 `privacy_notice_acks`（`contractor:<id>`），並寫稽核紀錄 |
| 不擋存檔 | 沒勾選不擋存檔或匯出（系統無法驗證實際告知），畫面顯示「尚未記錄個資告知」 |
