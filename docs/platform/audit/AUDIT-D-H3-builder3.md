# 稽核：H3 建構器第三輪設計（wip/h-builder3 89561df5，BUILDER-FORMS-V3.md）（D，2026-09-28）

> 範圍：設計文件。依據 CORE-SPEC d71f1e8f＋裁示 a2d1b068：⑥ 右側元素面板＋預覽抽屜、⑤ 同頁分段、② 前綴自動可改發布後鎖、④ 本輪只內建範本、① 代號進階唯讀、③ 附件獨立存放＋模組權限下載＋檔頭、⑦ 按鈕只 catalog 動作、⑧ 分享／多語系／網格／取消發布不在本輪。
> 對照 d71f1e8f 的 `helpers/custom_modules.py`、`helpers/formula.py`、`core/catalog.py`、`pages/custom-records.html`；另做一個公式引擎探針（見 H3-M1）。

## 0. 結論

- **必修 3、建議 5、觀察 2。**
- 差距盤點（36 項）與行號都對得上。方向正確：代號由系統產生、型別集中在 catalog、新型別只加不改、`ui` 引擎不讀、附件不放 `/api/uploads`
- 三個必修都落在主持點名的「值不再是純量」與「代號不回收」：
  - 簽核條件會對明細表／多選的值**靜默判 False** ⇒ 跳過簽核層
  - 「單調不回收」只看目前草稿 ⇒ 仍會重用舊版用過的代號
  - 附件的新目錄不在備份裡

## 1. 主持指定

**① 明細列改到 L1（值不再是純量）的相容與索引**

- **公式與條件：見 H3-M1（必修）。** D 探針（d71f1e8f 的 `formula.evaluate`，傳入 list／dict 值）：

  | 式子 | 值 | 結果 |
  |---|---|---|
  | `t + 1`、`sum(t)`、`max(m, 1)`、`f * 2` | 明細表／多選／附件 | `FormulaError`（不會 500，這部分引擎已經擋住） |
  | `t > 100` | 明細表 | `FormulaError` |
  | **`t == 0`** | 明細表 | **False** |
  | **`m == 'a'`** | 多選 `['a','b']` | **False** |
  | **`if(t, 1, 0)`** | 明細表 | **1**（非空 list 為真） |

  `_tier_applies`（custom_modules.py:732-751）的規則是「False 或 0 ⇒ 這一層跳過」。管理者寫簽核條件「類別 == '差旅'」而「類別」是多選 ⇒ 永遠 False ⇒ **這一層簽核永遠被跳過**，而且沒有任何提示（不是錯誤，是一個合法的 False）
- **索引**：`_write_index`（:583-590）現在對非字串值已經寫 `json.dumps` 進 `value_text`。設計改成「list 只寫列數到 value_num」，可以。但 `list_records` 的篩選是 `v.value_text = str(value)`（:630）：
  - 多選以單一選項篩選永遠找不到
  - 附件的 `value_text` 會是含檔名的 JSON
  - 要寫明每個新型別的索引形狀與可不可以篩選（H3-S1）
- **清理**：`clean_values`（:343-354）把**所有**輸入欄位交給 `_cf.clean`，只先把 `ref` 換成 `text`。新型別不在 `_cf.TYPES`，設計說「`_coerce_ext` 包一層、不改 `_cf`」，但沒寫 clean_values 要先把新型別分流出去，否則 `_cf.clean` 會把它們當未知型別處理（H3-S2）
- **讀出與輸出**：`_finite` 已處理巢狀 list／dict（:562-570），好。`_dump_values` 對巢狀 NaN 會拒絕，但錯誤清單只列頂層 key ⇒ 明細列裡的 NaN 回一個空的錯誤清單（H3-S2 一併）
- **畫面／輸出的呈現**：多選、附件在列表欄、輸出的 `field` 積木、通知內文、`ref_options` 的標籤裡怎麼顯示，設計只寫了明細表（「3 筆」、items_table）。沒寫的地方會出現 `['a', 'b']` 或 `[object Object]`（H3-S3）

**② 欄位 key 單調遞增不回收：見 H3-M2（必修）。**
設計的理由完全正確：`custom_record_values` 跨定義版本共用 key。但校正規則「`seq` ＝ **目前草稿**所有 key 尾碼最大值＋1」看不到**已刪除**的 key：
- v1 有 `amt_7`，v2 刪掉；之後 `ui.builder.seq` 遺失（還原到沒有 seq 的舊版、或舊草稿）⇒ 以目前草稿校正，max 可能是 6 ⇒ 下一個新欄位又叫 `*_7`
- 同一個 key 在舊單（v1 的金額）與新單（v3 的別的欄位）意思不同 ⇒ 正是設計要防的混淆

**③ catalog fieldTypes 沒有擁有者（catalog.py:37）＋執行頁 KNOWN_TYPES 寫死（custom-records.html:343）**
- 補 `register_section` 成立；§7.2 守門 1～3 雙向＋正對照，好
- 兩處要補：
  - `formulaFunctions` 的擁有者應該是 `helpers.formula`（FUNCTIONS 在那裡），不是 `custom_modules`
  - 建構器仍走舊端點 `/api/custom-modules/catalog`，設計在舊端點「加鍵」⇒ 兩個端點各自組資料＝兩個來源。舊端點要改成以 `catalog.section()` 投影（catalog.py 已有這支，註解就寫著給 P8 舊端點用），並加一題兩邊相等（H3-S4）

**④ 既有已發布模組的遷移**
- 「只加不改、不做資料遷移、凍結 `def_version` 的單用舊定義」成立
- 代號校正見 H3-M2
- 設計說「同一包出貨，無跨版問題」：**回滾**是跨版的。新版發布了含 `table` 的定義之後，若手動回滾到舊版程式（資料庫保留），舊版 `clean_values`／`KNOWN_TYPES` 不認得新型別。舊版已出貨、改不了 ⇒ 至少要在回滾說明寫明「新型別的模組在舊版無法使用，回滾前先停用這些模組或接受唯讀」（H3-O1）

## 2. 必修

**H3-M1（必修）　公式與簽核條件引用到非純量欄位，要在定義時就拒絕**
- 範圍：`formula` 欄位、狀態轉換／簽核層的 `when`、任何呼叫 `formula.check()` 的地方
- `check()` 要知道每個被引用 key 的型別：`table`、`multiselect`、`file`、`static` 只准出現在新的聚合函式（`total`／`avg`／`count`，以及將來明確支援 list 的函式）的對應參數位置；其他任何位置（比較、四則、`if` 條件、`coalesce`、其他函式）⇒ 定義時回 problem（path 指到該條件或公式）
- 多選若要當條件用，另給明確的函式（例：`has(m, '差旅')`），不要讓 `==` 有值
- evaluate 端再加一道保險：比較運算的任一邊是 list／dict ⇒ `FormulaError`（不回 False）。這樣舊資料或漏網的定義會落到 `_tier_applies` 的「無法計算 ⇒ 照簽」（fail-safe），不是跳過
- 題：
  - 多選欄 `==` 當簽核條件 ⇒ 發布被拒
  - 繞過 check 直接寫進 DB 的定義 ⇒ 送審時這一層照簽，並有 notice
  - 明細表當 `if` 條件 ⇒ 被拒
  - 正對照：`total(tbl, "amt") > 1000` 當條件 ⇒ 可發布、依金額正確分流

**H3-M2（必修）　代號校正要看所有版本，不只目前草稿**
- `seq` 校正＝max（目前草稿、**此模組所有已發布版本**〔definitions 歷史〕、**所有單據 data_json 出現過的 key**）的尾碼＋1。後兩者由後端算，例如 `GET …/custom_module/<key>/key-floor`，前端 normalize 時取用
- 建議把 `seq` 的權威存在**後端**：發布時由伺服器驗「新增的 key 不在任何舊版本或單據中出現過」，不符 ⇒ 拒絕發布。前端的 `ui.builder.seq` 只當建議值（`ui` 本來就不被引擎讀，也不該是唯一防線）
- 題：
  - v1 有 `amt_7` → v2 刪除 → 還原成沒有 seq 的草稿 → 新增欄位 ⇒ 不得產生 `*_7`
  - 直接以 API 發布一個重用舊 key 的定義 ⇒ 拒絕

**H3-M3（必修）　附件的新目錄要進備份、DR、升級分類與 demo 隔離**
- 設計把附件放 `core.paths` 新目錄 `custom_uploads/…`（不放 `UPLOADS_ROOT`，理由正確：`/api/uploads` 只驗登入）
- 但現行備份只認 `_paths.UPLOADS_ROOT`（archive.py:135 `_UPLOADS_DIR`）⇒ 新目錄**不在每日／月備份裡**；DR 還原之後單據還在（在 DB），附件全部不見
- 修法，要寫進設計並各有題：
  - 新目錄登記進每日／月備份
  - DR-SOP 的還原步驟
  - `apply_update.ps1` 與 `core.upgrade` 的「資料目錄，不動」清單（完整包、V9 轉換、兩種回滾都不碰）
  - demo 隔離（`_demo_*` 同規則）
  - 單據刪除（草稿刪除）時的孤兒檔清理
- 題：建一張帶附件的單 ⇒ 每日備份的樹裡有該檔；模擬完整包套用＋回滾 ⇒ 檔逐位元組不變

## 3. 建議

- **H3-S1　索引形狀逐型別寫明**：`money`／`datetime` 同 number／text；`multiselect` 每個選項一列（或另開 `value_items`），讓「含某選項」可以篩選；`file` 只寫檔數、**不寫檔名**（檔名可能含個資）；`table` 寫列數。`rebuild_index` 同一套
- **H3-S2　clean_values 分流**：新型別不進 `_cf.clean`（先分流，走 `_coerce_ext`）；`_dump_values` 的錯誤要能指到 `tbl_9[3].tbl_9_c10` 這種巢狀路徑
- **H3-S3　每個型別的「顯示字串」集中一處**：`FIELD_TYPE_SPECS[type].display(value)`（多選以「、」串接、附件「2 個檔案」、明細「3 筆」），列表、輸出 `field` 積木、通知、`ref_options` 標籤一律經它；守門：每個型別都有 display
- **H3-S4　catalog 單一來源**：舊端點 `/api/custom-modules/catalog` 改以 `catalog.section()` 投影＋一題兩端點相等；`formulaFunctions` 由 `helpers.formula` 登記
- **H3-S5　附件讀取**：
  - `<img>` 的短效簽章不可以沿用 `/api/uploads?pt=` 的路徑空間（那個端點只驗簽章）；要簽 `/api/custom/{key}/records/{no}/files/{id}`，並在該端點驗
  - PDF inline 顯示時加 `Content-Security-Policy: sandbox`（PDF 可帶腳本；attachment 則不需要）

## 4. 觀察

- **H3-O1**：回滾到不認得新型別的舊版程式時，新型別模組的行為沒有定義（§1-④）；舊版無法修改，只能靠回滾說明
- **H3-O2**：`FormulaError` 的訊息會帶出整個值（探針：「需要數字，得到 [{'c': 1}, …]」），它會進簽核 notice 與回應。明細列內容可能很長或含個資 ⇒ 訊息改成只寫型別（「需要數字，得到明細表」）
