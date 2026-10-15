# T64 切片 D：F7 欄位可見政策（共用欄位目錄）——設計

> 日期：2026-10-15　作者：Claude（hichan-61 視窗）　基底 `origin/train/t63-int`（26a0a07d4）　分支 `wip/t64-f7-design-r1`　**僅文件，沒有任何程式改動、沒有跑測試**。
> 對應 `quote-case-finance-coupling` §4 的 F7，以及 T64 切片順序 D。依賴：T63 匯出欄位（`helpers/export_templates.py`）、T63 Q0 設定（`quote_privacy`）、T61 S5 欄位目錄設計（`x_` 自訂欄位）、定義管線（放寬需第二位最高管理者核准）。
> 目標一句話：**『誰能看到哪個欄位』變成一份可設定的政策；金額類欄位永遠不會超出後端遮蔽允許的範圍；沒設定時行為與今天逐位元相同。**

## 0. 結論（先看）

1. 今天有**三份互不相通的欄位清單**（金額遮蔽的鍵、版面引擎的欄位點、匯出的欄位目錄），加上自訂建構器各自的 `visibleTo`。同一個欄位（例如品項成本）在三處各登記一次，改一處不會動另外兩處——這就是『第二個來源』。
2. 做法：**一份共用欄位目錄**（`fieldCatalog`，只收集、不擁有，沿用 `core/catalog.py` 的 `register_section` 手法），每個欄位一筆：代號、白話名稱、資料分類、金額等級、**天花板**（後端遮蔽規則）、今天的預設。三個既有清單改成**從目錄衍生**（鍵集合與今天逐字相同，有守門測試）。
3. 政策只有一個基本式：**實際可見 ＝ 天花板 ∧ 政策**。天花板是程式裡的後端遮蔽（`financial_mask`／`export_templates` 的 `visible`），**政策只能在天花板之內再縮小或指定**，不能超出。⇒ 金額欄位不可能因為設定錯誤而洩漏給後端本來就擋掉的人。
4. 『放寬天花板』本身（例如讓工程師也算有成本權限）不在這份政策裡，而是既有的**權限勾選制**（`finance_via_effective` D5／權限矩陣）；本設計只負責把它的結果**顯示出來並預覽影響**，不另開第二條路。
5. 預設＝今天；政策不存在或旗標關 ⇒ 全部走原本的函式。放寬一律走定義管線（第二位最高管理者核准＋影響預覽『N 人將看得到成本』），縮小立即生效。
6. 組織單位維度**這一期不做**：資料庫只有 `owner_unit_id` 欄位與剝除（`core/internal_cols.py`），沒有『人屬於哪個單位』的成員資料可供判斷。政策格式預留 `units`，第一版驗證器拒絕非空值。

## 1. 現況盤點（已查證，皆在 `train/t63-int`）

| 面向 | 登記在哪 | 形狀 | 問題 |
|---|---|---|---|
| 金額遮蔽 | `helpers/financial_mask.py`：`QUOTATION_MONEY_COLS`、`ITEM_MONEY_KEYS`、`QUOTE_MONEY_KEYS`、`PAYMENT_MONEY_KEYS`、`MATERIAL_ORDER_MONEY_KEYS`、`HISTORY_MONEY_FIELDS`（顯示名稱字串） | 鍵名元組 | 鍵名＝資料裡的鍵，沒有白話名稱、沒有『屬於哪張表』；歷史紀錄用**顯示名稱**比對（改名會漏） |
| 金額可見條件 | `financial_mask.money_visible`／`quote_money_visible`／`material_money_visible`、`auth.has_finance_access`、`auth.can_see_financial`、`auth.has_cashier_access` | 6 支函式，各自角色集合 | 同一件事（『看得到金額嗎』）有 6 種答案；呼叫端自己挑一支 |
| 版面引擎欄位點 | `module.json` 的 `customization.fields.<entity>[]`（`key`、`label`、`core`）→ `core/catalog.py::layout_points`；Q0 的 `forced_core` 可在執行期把某欄位升為核心 | 每模組一份 JSON | 版面的『隱藏』只是畫面（`ops`），不是權限；沒有金額等級欄位 |
| 匯出欄位 | `export_templates.register(...)`：`columns[{id,label,money?,visible?}]`、`sheets[...]` | 程式登記 | 欄位 id 與上面兩者無關；`money:true` 而無 `visible` ⇒ fail-closed（好設計，要保留） |
| 建構器欄位 | `custom_builder_support`：`fields[].access.visibleTo/editableTo` `{roles,users}`，`mask_for`／`mask_record` 後端強制 | 定義 JSON | 已經是『角色＋個人』模型——**本設計沿用它的形狀與語意**（最高管理者直通、改得到蘊含看得到） |
| 單位鍵 | `core/internal_cols.py`：`owner_unit_id`／`unit_id`／`legal_entity_id` 一律剝除，**沒有輸出開關** | 元組 | 單位維度要新欄位名才能開，見 §8 |

**觀察**：建構器的 `visibleTo` 模型（角色＋個人，後端強制）已經是我們要的政策形狀，內建畫面缺的只是『欄位目錄』與『套用到內建遮蔽』。所以不發明新模型。

## 2. 共用欄位目錄（`fieldCatalog`）

只收集、不擁有（沿用 `core/catalog.py` 原則：寫死的那一份就是第二個來源）。擁有者（模組、L1 helper）以 `register_section("fieldCatalog", owner, fn)` 登記自己的欄位；目錄 `build()` 合併並驗證。

每個欄位一筆：

| 欄位 | 說明 |
|---|---|
| `id` | 穩定代號 `<實體>.<鍵>`，如 `quote_item.cost`、`case.payment.actualAmount`、`quotation.net_margin_pct`。**一旦發布不改名**（政策引用它）；改名＝新增＋停用 |
| `label` | 白話名稱（『品項成本』），畫面與影響預覽用 |
| `family` | 家族：`cost`（成本）、`margin`（毛利）、`price`（單價／金額）、`payment`（款項）、`pii`（個資）、`plain`（一般）。**同家族一起判斷**：成本藏了、毛利率卻露出來＝可反推成本，所以 `margin` 依賴 `cost`（`derivedFrom`） |
| `moneyClass` | `none`／`money`／`hardlock`。`hardlock`＝政策**不可放寬**（薪資、銀行帳號等，見 §9 問題 5） |
| `ceiling` | 天花板：一個**具名能力**（`quote_money`＝今天 `quote_money_visible`；`finance_money`＝今天 `money_visible`；`material_money`；`cashier`），由後端函式回答，不是角色清單的複本 |
| `surfaces` | 這個欄位出現在哪：`api`（JSON 回應）、`screen`（版面欄位點，帶 `entity/key`）、`export`（匯出欄位，帶 `exportId/columnId`）、`pdf_internal` |
| `default` | 今天的規則（由 `ceiling` 推出）；政策不存在時就是它 |

**衍生，不是複製**：
- `financial_mask` 的 6 個元組 ⇒ 改為從目錄依 `surfaces.api` 與 `family` 產生；守門測試比對『產生結果＝今天的元組（逐字、順序）』，不一致即紅。`HISTORY_MONEY_FIELDS` 的顯示名稱一併登記為 `legacyLabels`（舊紀錄比對用，不再當鍵）。
- 版面欄位點 ⇒ `module.json` 欄位點加選填 `catalogId`；有 `catalogId` 的點，其可見性來自目錄（政策），沒有的維持今天。目錄驗證：每個 `catalogId` 必須存在、`entity/key` 必須與登記一致。
- 匯出欄位 ⇒ `columns[]` 加選填 `catalogId`；`money` 旗標與 `visible` 由目錄的 `moneyClass/ceiling` 推出（登記端不再各寫一份；遷移期兩者並存並互相驗證）。

**版面的『隱藏』≠ 安全**：版面操作只影響畫面，API 與匯出照樣會回該欄位。凡 `moneyClass != none` 的欄位，`layout` 驗證器在**發布前**提示『隱藏這個欄位不會讓沒權限的人看不到，請改用欄位可見政策』。

## 3. 政策定義（新 kind `field_policy`）

沿用定義管線（草稿、版本、差異、還原、影響預覽、放寬進待核准），key＝`company`（一份）。

```json
{ "version": 1,
  "rules": [
    { "field": "quote_item.cost",                 // 欄位代號；或 "family:cost" 一次套一個家族
      "audience": { "roles": ["superadmin","admin","finance"],   // 空＝今天預設
                    "users": ["王大明"],
                    "units": [] }                  // 第一版必須為空
    } ] }
```

規則：
1. **求值**：`可見(欄位,人) = 天花板(欄位,人) ∧ (沒有規則 ∨ 規則命中(人))`。最高管理者直通**仍須**過天花板與 `hardlock`（天花板對最高管理者必為真，這是今天的不變式 `has_finance_access` 含 superadmin）。
2. **個人例外**只能在天花板內加人：政策裡列了某人、但他過不了天花板 ⇒ 仍看不到，並在影響預覽標『此人沒有金額權限，政策無效』。
3. 家族規則自動涵蓋 `derivedFrom`：把 `cost` 範圍縮小，`margin` 家族不得比它寬（驗證器擋：`margin` 的受眾必須是 `cost` 受眾的子集；否則發布被拒並白話說明『毛利可以反推成本』）。
4. 政策只存**受眾**，不存值；停用一條規則＝回到今天的預設。
5. 後端是最後一道關：所有出口（API 回應、匯出、內部 PDF、通知占位符、搜尋結果、回收桶、稽核檢視）都必須經同一個求值函式 `field_policy.visible(field_id, user)`；既有 `mask_*` 變成它的薄包裝。

## 4. 套用點（要遷移的出口，先列清單才算數）

`grep financial_mask` 實際引用者（可由守門測試固化為清單）：`helpers/rule_catalog.py`、`modules/analytics/api/{reports,ledger_diff}.py`、`modules/case/{alt_lock,completion_sync,material_guard,rule_provider}.py`、`modules/case/api/{alt_plan,material_approvals,material_changes,material_orders,material_payments,project_margin,quotations}.py`。另有不經 `financial_mask` 但各自判斷金額的出口：`notify_actions._expand_text`（`has_finance_access`）、匯出範本（`visible=`）、`recycle_bin.mask_obj`、建構器 `mask_record`。

遷移順序：先**只登記不改行為**（目錄＋等價守門），再逐出口改成呼叫 `visible()`，每改一處用『角色 × 欄位』矩陣金標證明與舊函式輸出逐格相同。**不新增路由、旗標關時零新請求。**

## 5. 預設＝今天、旗標、治理

- 旗標 `builder_field_policy.enabled`（設定中心，預設關）＋既有 `builder_governance.enabled`。關 ⇒ `visible()` 直接回舊函式的結果；開但沒有已發布政策 ⇒ 同上（rules 空）。
- **放寬**（任一個『欄位×人』由不可見變可見）：進待核准，需**第二位最高管理者**核准（與 D-K1 簽核門檻放寬同一條規則），核准前保持舊行為。**縮小**：立即生效。
- 求值錯誤（目錄讀不到、政策壞掉）⇒ **fail-closed 到天花板的預設**（今天的行為），不是全開。

## 6. 影響預覽與遷移

發布前『看看會怎樣』（沿用 `_PREVIEW_ENFORCED_KINDS`：未看預覽不能發布）：
- 對每位在職使用者算出『改前／改後』可見欄位集合，只列**有差異**的格子，彙總成白話：『**3 位**同仁將看得到「品項成本」：王小明（業務）、李小華（業務）、陳大同（工程師，⚠ 此人沒有金額權限，設定無效）』『**1 位**同仁將看不到「毛利率」』。
- 同時列出受影響的**出口**（畫面、匯出『案件批次匯出』、內部 PDF、通知內容）。
- 不含金額值本身，只含人名與欄位名；預覽不寫任何資料，只留一筆稽核 `field_policy.previewed`（比照 `notify_action.previewed`）。
- 遷移＝**沒有資料遷移**：政策是新定義；目錄是程式登記；舊行為由 `default` 提供。上線第一天『已發布政策』為空，所有人看到的與昨天相同。

## 7. 白話畫面草圖（設定中心 → 欄位可見政策；只有最高管理者）

```
欄位可見設定                                   [說明] 這裡只能「縮小」或「指定」；超出系統金額權限的人，加了也看不到。
┌ 家族 ─────────────┬ 目前誰看得到 ────────────────────┬ 狀態 ┐
│ 成本（4 個欄位）   │ 最高管理者、管理員、業務、財務     │ 預設 │
│ 毛利（5 個欄位）   │ 最高管理者、管理員、業務、財務     │ 預設 │
│ 單價與金額          │ 最高管理者、管理員、業務、財務     │ 預設 │
│ 款項與收付款        │ 最高管理者、財務                   │ 預設 │
│ 個人資料（鎖定 🔒） │ 依系統規定，無法修改               │ 鎖定 │
└──────────────────┴──────────────────────────────┴─────┘
[展開「成本」] ── 品項成本 ▢ 每個欄位可單獨設定
   誰可以看：  ☑ 最高管理者(固定)  ☑ 管理員  ☐ 業務  ☑ 財務  ＋指定人員：[王大明 ×] [＋加人]
   ⚠ 毛利比成本寬：目前「毛利」業務看得到、「成本」業務看不到 → 業務可以由單價與毛利率反推成本。[一併調整毛利]
[看看會怎樣]  → 「2 位同仁將看不到成本：…（不含金額）」「0 位將多看到」
[檢查並發布]   縮小＝立即生效；放寬＝送第二位最高管理者核准
```
畫面原則同 S5 編輯器：不出現代號或列舉值（`family:cost` 顯示為『成本』）、不用 innerHTML、後端錯誤原文轉白話。

## 8. 分階段（每階段單獨可上線、旗標關＝零變化）

| 階段 | 內容 | 風險 |
|---|---|---|
| S0 | `fieldCatalog` 登記＋守門：目錄衍生的鍵集合＝今天的 6 個元組／匯出 `money` 欄位／版面欄位點；**不改任何行為** | 低；純測試與登記 |
| S1 | `field_policy.visible()` 求值＋`financial_mask`／匯出出口改走它（rules 空 ⇒ 與舊函式逐格相同） | 中；出口多，需矩陣金標 |
| S2 | `field_policy` kind＋比較器（放寬／縮小）＋影響預覽＋治理接線 | 中 |
| S3 | 編輯器前端＋白話標籤 | 低 |
| S4 | 自訂欄位（T61 S5 `x_`）與 q3 加入目錄；數字欄預設隱藏規則改為目錄屬性 | 中；依 T61 S5 |
| S5 | 組織單位維度：**先要有『人屬於哪個單位』的成員資料**（今天只有資料列上的 `owner_unit_id`，且被剝除輸出）。需另開設計 | 高；本期不做 |

預估（pd）：S0 1.5、S1 3、S2 2.5、S3 2、S4 2；S5 另估。

## 9. 需要使用者決定的事（每題附建議預設；能做成設定的都已做成設定，這裡只列『不能是設定』或『預設值要先選一個』）

1. **成本與毛利預設誰看得到？**　建議：**維持今天**（報價層級：最高管理者、管理員、業務、財務；精算與款項：只有最高管理者與財務）。之後可在設定改。
2. **放寬欄位可見是否一律要第二位最高管理者核准？**　建議：**是**（與簽核門檻放寬同一條）。若公司只有一位最高管理者，放寬維持『確認期間』後生效。
3. **允許『指定個人』加看嗎？**　建議：**允許**，但只能在系統金額權限之內，且算放寬（走核准）。
4. **要不要讓『毛利比成本寬』成為禁止而不只是警告？**　建議：**禁止**（發布被拒，白話說明可反推成本）；若要例外，請明說理由並由最高管理者承擔。
5. **哪些欄位永遠不能由設定放寬（鎖定）？**　建議鎖定：薪資單金額、銀行帳號、身分證／個資欄位、`owner_unit_id` 等單位鍵。**這題不能做成設定**——鎖定清單是最後防線，要改只能改程式並過稽核。請確認清單有沒有要增減。
6. **組織單位維度要不要做？**　建議：**這期不做**；等『人員屬於哪個單位』的資料模型定案再開設計（沒有成員資料就沒有可判斷的依據）。
7. **自訂欄位的數字欄**：沿用 T61 S5 決定（無金額權限者預設看不到，可由最高管理者勾『非金額』放寬並走核准）。建議：沿用，不另問。

## 10. 風險與不做

- **寫回風險**（`financial_mask` 檔頭）：看不到的人送回來的資料沒有那些鍵，照單全收會用空值蓋掉真值。目錄上線後凡經 `visible()` 隱藏的欄位，寫入路徑必須沿用 `restore_*` 補回現值；S1 的矩陣金標要含『隱藏帳號存檔後金額不變』。
- **推論洩漏**：家族依賴（§3 規則 3）只擋已登記的關係；未登記的衍生值（例如總額與其他部分相減）仍可能反推——目錄新增欄位時 `derivedFrom` 是必填審查項。
- **公式／通知／搜尋**：建構器的 `leaking_formulas()` 規則延伸到政策；通知占位符（`notify_actions`）已逐收件人遮蔽，S1 要改走同一個 `visible()`。
- **不做**：改變任何計算、簽核、狀態；改變天花板（走權限勾選制）；單位維度；客戶可見輸出（維持『內部欄位不進客戶輸出』的既有規則）。
