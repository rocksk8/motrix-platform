# 第 31 班稽核報告：表單設計器（稽核員 d7；非作者，無「作者自審」項）
基準：包 `20261002_134219_a5dea50c_full`（commit a5dea50c）；清單 `audit/train31-designer-c7@761525ed`（K-1 已關閉、K-2 順延）。
方法：單檔單程序；探針斷言打在草稿 DB／伺服器回應／真 DOM。探針檔（隨本報告提供，可併入）：
`backend/tests/test_audit_d7_designer_probes_2026_10_02.py`（A2／A3／A4）、`test_e2e_audit_d7_designer_2026_10_02.py`（A1／B2／B3／B4／C／E1～E4）、
`test_audit_d7_model_gaps_2026_10_02.py`（H 組補洞，見 S1／S2）。

## 結論先行
**無必修（must-fix 0）。** 建議修 2 項（都是「守門有洞」：M2、M6 突變沒有任何現有題會紅；補洞題已附並實證會抓到）；觀察 2 項。

## 逐項結果
| # | 結果 | 證據 |
|---|---|---|
| A1 非 superadmin 開兩頁 `?designer=1` | PASS | admin 開 `module-builder.html`、`expense-types.html`（有／無參數）都沒有 `.fd .fd-paper`；反向控制：superadmin 同網址載得到頁面主體 |
| A2 非 superadmin 寫草稿端點 | PASS | `PUT /api/definitions/{expense_type,custom_module}/{key}/draft`：admin／user／未登入皆 401／403；反向：superadmin 不是 403 |
| A3 `GET /api/platform/prefill-sources` | PASS | 未登入被擋；登入者回應的每筆鍵 ⊆ {token,label,why,example,applies_to,lockable,needs_context,requires_time}；種入的客戶名／案名／單號／使用者帳號／密碼都不在回應內 |
| A4 靜態：元件不發請求、不用動態碼 | PASS | `static/form-designer.js`、`form-designer-model.js`：fetch／XMLHttpRequest／window.open／eval／new Function／document.write 命中 0（先去註解）；掃描器自身正對照命中；轉接層 `module-builder-designer.js`、`expense-types-designer.js` 無 eval／Function／document.write |
| A5 modules.json＋邊界 | PASS | 四支檔都在 modules.json；`test_module_boundaries` 27 passed |
| B1 資料層往返 | PASS | `test_form_designer_model` 24 passed（四份出貨定義位元相同、空 groups、list.columns 原順序、output.template） |
| B2 四個內建類型不編輯就存草稿 | PASS（強於清單） | 開 purchase_req／purchase_order／travel／petty_cash 的設計器、不改、按「儲存草稿」，讀 DB 草稿 ＝ 出貨定義 **逐鍵相同且鍵順序相同**（遞迴差異 `[]`＋`json.dumps` 字串相等） |
| B3 建構器開關新舊畫面不存檔 | PASS | 來回切換 2 次＋等 1.5 秒：`definitions.save_draft` 稽核列數與草稿列（rowid／body）都不變 |
| B4 只改一欄名稱 | PASS | 改 travel 的一欄 label 後存草稿 vs 出貨定義：差異恰為 `/fields[i]/label` 一處 |
| B5～B8 | PASS（作者題；未另做獨立探針） | beginner_tasks 12 passed（新增欄位、清單插入、刪除復原、被引用欄位不能刪、已發布／固定欄位刪除前確認、固定選項唯讀、不一致只回報）；B7 公式往返在 model 題內 |
| C1／C2／C4 建構器預設關閉與開關 | PASS | 無參數：舊畫布可見、無 `.fd`、`#mb-fd-host` 不可見、localStorage 空；`?designer=1`：設計器（**網址參數本身不寫 localStorage，只有按鈕寫**）；按鈕 關⇒'0'、開⇒'1'；`?designer=0` 蓋過 localStorage=1；整段無任何 `definitions.*` 稽核列（不寫伺服器、不影響他人）|
| C3 請款類型頁預設關閉 | PASS（作者題＋舊頁題） | `test_e2e_expense_types_designer`（10）＋`test_e2e_expense_types_editor`（4，舊畫面 testid 全在）＋`test_designer_switch_back_to_the_old_table_screen`；未另做獨立的 localStorage 探針 |
| D 舊 UI 不受影響（19 檔單檔逐一） | PASS | builder_form_canvas 4、builder3_singlepage 8、builder_dnd 8、expense_types_editor 4、expense_form_a24 11、platform/test_expense_types 17、alpine_double_init 16、scope_gate 103、dark_mode_chrome 3、module_boundaries 27、builder_preview_static 6，另 model 24／prefill 25＋6／beginner 12／clarity 4／dark 3／autosave 2／types_designer 10 全綠。`module-builder-core.js` 與 6b5d2865 相比 +5／−1：`fdInitSwitch()`、`_publishedKeys`、`jumpTo` 聚焦＋K-1 的去抖（`useFD ? 4000 : 700`），符合清單 |
| E1 欄位名稱／說明／區塊名／選項填注入字串 | PASS | label／help／區塊名／選項填 `<img src=x onerror=…>`、`"><script>…`、`<b onmouseover=…>`：每個欄位點開（中間、右欄、選項、用語檢查表）後 `window.__x` 仍 undefined、`.fd` 內無 `img[src=x]`／`script`／`[onerror]`／`[onmouseover]`；畫面以文字顯示惡意字串 |
| E2 註冊表字串含 HTML | PASS | 以 route 回 label／why／example／token 都含 HTML 的註冊表：同上全部只當文字，下拉與說明有出現標籤文字 |
| E3 貼上 1 萬行到選項 | 觀察 | 10,000 行 ⇒ 10,002 格、1.5 秒、頁面仍可回應；**沒有上限**（若要上限，由作者決定；存下來的定義會有 1 萬個選項） |
| E4 `javascript:` 協定字串 | PASS | 當成文字；`.fd` 內無 `a[href^=javascript]` |
| F1 去抖 4 秒 | PASS（K-1 已關閉） | `test_e2e_form_designer_autosave` 2 passed：連續打字（每字 0.25 秒）1.5 秒內草稿未動，之後只存 **1 次**；舊畫布仍是短去抖 |
| F2 併發 | 觀察（K-2 順延，已知） | 後端無併發戳（後寫者勝）；客戶端「別人剛改過」檢查未實作 |
| F3 重新整理後復原堆疊 | PASS（符合設計） | 不保留；刪除已發布欄位前有確認（beginner 題） |
| G 可及性／外觀 | PASS（作者題；未另做獨立探針） | dark 3、clarity 4 passed（像素＋每個設定列有說明與例子、禁用詞掃描）；**未獨立探**：鍵盤全流程、≤960px 三欄切換、真滑鼠拖放（環境限制，清單已列人工驗收）|
| H 突變 | 4／6 被抓；**M2、M6 沒被抓** | 見下 |

## H 組突變結果（改檔 → 單檔跑 → 還原；樹乾淨）
| 突變 | 結果 |
|---|---|
| M1 `strip()` 不剔除 `_calc` | RED（`test_form_designer_model`） |
| M2 `setListed` 一律 push 到尾端 | **GREEN（沒抓到）** ← S1 |
| M3 `groupsOf` 空 groups 回 `[]` | RED |
| M4 `esc()` 回原字串 | RED（我的 E1 探針；作者題原本抓不到——見 S3 觀察） |
| M5 `fillsFor` 忽略 `needs_context` | RED |
| M6 `localProblems` 拿掉禁用字眼 | **GREEN（沒抓到）**，連 `clarity` e2e 也綠 ← S2 |

## 發現
- **S1（建議修，守門有洞）**：`test_list_columns_keep_their_order_and_new_ones_are_inserted_after_the_nearest_shown_predecessor` 的範例是 `columns=["d","a"]` 插入 `c`——前一個已顯示欄位 `a` 剛好是最後一個，**「接在尾端」與「接在前驅之後」結果相同**，所以 M2 不紅。補洞：`columns=["a","d"]` 插入 `b` 必須得 `["a","b","d"]`（附於 `test_audit_d7_model_gaps_2026_10_02.py::test_setListed_inserts_after_the_nearest_shown_predecessor_not_at_the_end`；對 M2 實證 RED）。
- **S2（建議修，守門有洞）**：`localProblems` 的 `bannedWords`（請款類型頁用它擋「銀行／帳號」類欄名，`expense-types-designer.js:58`）**沒有任何題直接驗**。補洞：`test_localProblems_flags_banned_words_in_field_names_and_column_labels`（欄位 label 與明細欄 label 都要被標、正常欄位不標、沒有 caps 時不檢查；對 M6 實證 RED）。
- **觀察 O1**：XSS 轉義（M4）原本只靠「esc 的使用處人工確認」——現有作者題抓不到 `esc` 失效；建議把 `test_e2e_audit_d7_designer` 的 E1／E2 併進作者題（已是綠的、不依賴內部模型）。
- **觀察 O2**：E3 無上限；F2＝K-2 順延。

## 輸出
清單其餘項全 PASS（B5～B8、C3、G 為作者題覆蓋、未另做獨立探針，已逐項標明）；建議修 2（S1、S2，均為測試補洞，非產品缺陷）；觀察 2＋1；必修 0；作者自審項 0（稽核員 d7 非作者）。
