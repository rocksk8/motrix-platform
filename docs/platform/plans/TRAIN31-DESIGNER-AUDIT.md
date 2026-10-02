# 第 31 班稽核清單：表單設計器（模組建構器頁、請款類型頁）

作者：hichan-c7（元件與建構器接入）、hichan-a3（請款類型頁轉接層）。**作者不能稽核自己的成果**：建議由 hichan-2e 或 d7 執行；若仍由作者做，報告標「作者自審」。
基準：c7 最終 `f9958ab5`（wip/t31-form-designer-c7）；a3 的轉接分支以整合後 platform 為準。被稽核檔：`static/form-designer-model.js`、`static/form-designer.js`、`css/form-designer.css`、`js/module-builder-designer.js`、`js/expense-types-designer.js`、兩頁 html／core 的接線。
方法：單檔單程序、不用 `-n`；斷言打在草稿 DB／伺服器回應／真像素，不讀內部模型。

## A. 權限與暴露面
| # | 探針 | 通過條件 |
|---|---|---|
| A1 | 非最高管理者開 `module-builder.html?designer=1`、`expense-types.html?designer=1` | 與關閉時相同：被擋（頁面本來就僅 superadmin）；設計器不載入 |
| A2 | 非 superadmin（admin／user）打 `PUT /api/definitions/{custom_module,expense_type}/{key}/draft` | 403（設計器沒有新增端點，沿用既有權限） |
| A3 | `GET /api/platform/prefill-sources`（2e）任何登入者 | 只回註冊表中繼資料（token／label／why／example／applies_to／lockable／needs_context），**不含任何人員、部門、客戶資料**；未登入 401 |
| A4 | 靜態：`form-designer*.js` 內 `fetch`／`XMLHttpRequest`／`window.open`／`eval`／`new Function`／`document.write` 出現次數 | 0（元件不自己發請求；資料由宿主頁給） |
| A5 | 設計器檔案進了 `modules.json` 且 `test_module_boundaries` 綠 | 綠 |

## B. 資料往返不變（最重要）
| # | 探針 | 通過條件 |
|---|---|---|
| B1 | 資料層：4 份出貨 `expense_type_defs/*.json` 載入→`strip`→逐位元相同；含 `output.template`、未知欄位屬性、`ui.list.columns` 原順序、空 `groups` 仍為空 | `test_form_designer_model_2026_10_02.py` 綠（23＋題） |
| B2 | 頁面層（請款類型）：4 個內建類型各開一次（`?designer=1`），**不編輯**，按「儲存草稿」，讀 DB 草稿 | 草稿 body ＝ 該類型目前生效定義（逐鍵相同，順序相同） |
| B3 | 頁面層（建構器）：開草稿→開關新舊畫面來回→等 1.2 秒 | 草稿不變、不產生存檔（`test_opening_the_designer_and_switching_back…`） |
| B4 | 只編輯一欄（改名）→存草稿→與已發布版差異 | 差異恰好 1 處（該欄 label），其餘無 |
| B5 | 新增欄位：`list.columns` 只多該欄、groups 為空時仍為空、`fields[]` 順序＝畫面順序；刪除後復原＝位元相同 | 同左 |
| B6 | 重複代碼進兩個區塊、孤兒欄位（不在任何群組） | 載入時警告、不丟資料；孤兒顯示在「其他」 |
| B7 | 計算器：每個出貨公式（`total(lines,"amount")`、`round_half_up(qty * unitCost)`…）解析→重建＝原字串；認不得的公式原樣保留（「進階公式」） | `test_known_formulas_round_trip…`、`…unrecognised…` 綠 |
| B8 | `fixedOptions`／`fixedTypeKeys`／`publishedKeys`：不一致只回報、不偷改；刪除前確認 | beginner-tasks e2e 綠 |

## C. 預設關閉（使用者預覽前不得生效）
| # | 探針 | 通過條件 |
|---|---|---|
| C1 | 建構器：無參數、`localStorage.mb_designer` 空 → 開 ② 表單 | 舊畫布可見（`#mb-canvas`），`#mb-fd-host` 不可見／沒有 `.fd` |
| C2 | `?designer=1` → 設計器；`?designer=0` 即使 localStorage=1 也關 | 同左 |
| C3 | 請款類型頁（a3；主持要求改預設關閉）：無參數／無 `et_designer` → 舊表格畫面；`?designer=1` → 設計器 | 同左；`et-f-*`／`et-fields` 等既有 testid 在預設狀態全在 |
| C4 | 開關狀態只存 `localStorage`（每使用者每瀏覽器），不寫伺服器、不影響他人 | 靜態＋實測 |

## D. 舊 UI 與既有行為不受影響（單檔逐一跑）
`test_e2e_builder_form_canvas_2026_09_27.py`、`test_e2e_builder3_singlepage_2026_09_30.py`、`test_e2e_builder_dnd_2026_09_27.py`、`test_e2e_expense_types_editor_2026_10_01.py`（a3 改寫後）、`test_e2e_expense_form_a24_2026_10_01.py`、`platform/test_expense_types_2026_10_01.py`、`test_alpine_double_init_2026_09_23.py`（`_initDone` 守衛未被破壞）、`platform/test_scope_gate_2026_09_30.py`、`test_dark_mode_chrome_structure_2026_09_13.py`、`platform/test_module_boundaries.py`、`test_builder_preview_static_2026_09_27.py`。通過條件：全綠；`module-builder-core.js` 只多 3 行（`fdInitSwitch()`、`_publishedKeys`、`jumpTo` 聚焦），人工 diff 確認。

## E. 注入與輸出跳脫（XSS）
| # | 探針 | 通過條件 |
|---|---|---|
| E1 | 欄位名稱、說明文字、區塊名稱、選項、預設文字、明細欄名都填 `<img src=x onerror=window.__x=1>`／`"><script>` | 中間表單、右欄、用語檢查表都以文字顯示；`window.__x` 仍 undefined；DOM 中沒有新增 `img`／`script` |
| E2 | 後端註冊表字串（label／why／example）含 HTML | 同上（元件對它們一律 `esc`） |
| E3 | 貼上 1 萬行到選項 | 不當掉；（觀察）是否需要上限 |
| E4 | `javascript:` 等協定出現在說明文字 | 只是文字，不成連結（元件不產生 `<a>`） |

## F. 草稿／存檔語意（與設計 §12-7 對照）
| # | 探針 | 現況／通過條件 |
|---|---|---|
| F1 | 連續輸入 20 個字元，數 `audit_log` 的 `definitions.save_draft` 列 | **已知落差 K-1**：建構器沿用自己的 700 ms 去抖，設計 §12-7 寫的「閒置 4 秒」**未實作**；打字期間每停頓 0.7 秒就存一次並寫一筆稽核。需決定：在 `useFD` 時把去抖改 4 秒（`module-builder-core.js` 一行）或接受 |
| F2 | 兩位最高管理者同時編輯同一草稿 | 後端無併發戳（後寫者勝）；客戶端「別人剛改過」檢查**未實作**（K-2，設計列為客戶端檢查、後端 `expected_created_at` 為切片 5 選配） |
| F3 | 重新整理後復原堆疊 | 不保留（刪除已發布欄位前有確認，符合設計） |

## G. 可及性與外觀（抽查）
鍵盤：欄位 Tab／Enter／Delete／Alt+↑↓、選項 Enter／Backspace／↑↓／貼上；窄螢幕（≤960px）三欄切換；深色（`test_e2e_form_designer_dark_2026_10_02.py` 像素驗證）；清晰度（`…clarity…`：每個設定列有說明＋例子、禁用詞掃描）。**真滑鼠拖放缺口**：環境限制，只驗事件鏈；列入人工驗收清單。

## H. 突變（確認守門會紅）
M1 `strip()` 不剔除 `_calc` ⇒ B1／B2 紅；M2 `setListed` 改成每次 push 到尾端 ⇒ list 順序題紅；M3 `groupsOf` 空 groups 時回 `[]`（不回虛擬區塊）⇒ 往返題紅；M4 `esc()` 改成回原字串 ⇒ E1 紅；M5 `fillsFor` 忽略 `needs_context` ⇒ 預設來源題紅；M6 `localProblems` 拿掉禁用字眼 ⇒ 對應題紅。（突變前先 commit，避免 `git checkout` 吃掉未提交修改。）

## 輸出
PASS/FAIL 逐項＋必修／建議／觀察三級；列出「作者自審」項。
