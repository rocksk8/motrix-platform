# 報價送審的單項毛利率門檻（`quote_approval.min_item_margin_pct`）

> 2026-10-14　hichan-3e　分支 `wip/t62-approval-margin-r1`

## 行為
- 原本寫死 30%（三處：`modules/case/quote_terms.py::compute_approval_reasons`、`quotation-form.html` 的「需審核」徽章與 `checkApproval()`）。現在是設定 `quote_approval.min_item_margin_pct`，**預設 30＝與過去逐位元相同**（原因文字「低於 30%」不變；門檻不是 30 時文字帶實際門檻）。
- 前端經 `GET /api/project-margin/config` 的 `minItemMarginPct` 取得（沒有新請求；沒有金額權限者仍是 403）。**伺服器送審時重算原因並覆蓋前端送來的內容**，所以前端值只影響畫面提示。
- 調低＝放寬：經設定中心的確認期間與第二位最高管理者核准（含「還原預設」路徑，因為它也走 `publish`）；調高即時生效。群組是敏感群組、風險 money。

## 讀不到時往最嚴的一邊收（04 審查）
`min_item_margin_pct()` 用 `helpers/settings_strict.strict_value` 直接讀定義表（不經 `settings_registry.get`——它永不丟例外，失敗會回預設 30＝悄悄放寬）。資料庫讀不到、格式不對、不是有限數字、超出 0～100 ⇒ **100**（每個有成本的品項都列為需審核）。`MOTRIX_SETTINGS_DEFAULTS_ONLY=1` 不影響。第一個有成本的品項才讀設定（沒有成本品項時完全不碰資料庫）。

## 已知缺口（既有，未擴大範圍）
`compute_approval_reasons` 使用用戶端送來的 `item.margin` 與 `item.cost`；`profit_guard.prepare()` 只重算整單損益（`server_totals`：數量×成本、稅前、管銷…），**不會**重算每個品項的 `margin`。所以直接打 API 的人仍可送一個與單價／成本不一致的 `margin` 來避開這條原因。這是門檻變成設定之前就存在的缺口；修法是在 `_apply_server_submit_reasons` 之前由伺服器依 `unitPrice`／`cost` 重算每項毛利率（會動到簽核判定，另案，需使用者知情）。

## 決定（暫定）
D-K1：門檻調低要第二位核准——暫定是（與規則引擎一致）；使用者尚未確認。

---
## 擴充：有效天數上限與折讓門檻（hichan-1f，wip/t62-approval-thresholds-r1）
同一個群組 `quote_approval`、同一套做法（預設＝今天、嚴格讀取、伺服器送審重算、表單經 `GET /api/project-margin/config` 取數字）：

| 門檻 | 設定 | 預設（＝今天） | 範圍 | 放寬方向 | 讀不到時 | 判準（`compute_approval_reasons`） |
|---|---|---|---|---|---|---|
| 單項毛利率 | `min_item_margin_pct` | 30 % | 0～100 | 調低 | 100（最嚴） | 有成本的品項，毛利率 `<` 門檻 |
| 有效天數上限 | `max_valid_days` | 30 天 | 1～365 | 調大 | **1**（最嚴） | `validDays > 上限`；文字「有效期限 N 天（超過 上限 天）」 |
| 折讓門檻 | `discount_review_above` | 0 元 | 0～1 億 | 調高 | **0**（最嚴＝今天的規則） | 有折讓、`discount > 門檻`；0 ＝任何折讓都列 |

- 三個都是『嚴格讀取』：資料庫讀不到、格式不對、非有限數字、超出範圍 ⇒ 最嚴值，**不是預設**；`MOTRIX_SETTINGS_DEFAULTS_ONLY` 不會把管理者調過的值悄悄換回預設。
- 折讓門檻是**絕對金額（元）**，不是百分比；選這個是因為今天的規則（`discount > 0`）本來就是金額判斷，預設 0 完全等價。若之後要「占總額幾 % 以上才列」，另開欄位（需要先確認總額口徑：含稅／未稅）。
- **非 5% 的稅別不開放設定**：`_js_num(tax_rate) < 5` 與「非應稅 5%」「標準 5%」是營業稅法的法定稅別判斷（零稅率／免稅有法條依據，見 AC1／R2），留在程式裡；測試 `test_non_five_percent_tax_is_a_statutory_rule_and_stays_hard_coded` 鎖住群組只有這三個欄位。
- 測試：`backend/tests/test_quote_approval_thresholds_2026_10_14.py`——預設格子與過去寫死版逐項相同（有效天數 × 折讓 × showDiscount）、門檻×值格子（含邊界）、**突變控制**（載入 `>` 改 `>=` 的變異模組，邊界格必須翻面）、頁面實際原始碼片段用 node 與後端逐格比對、讀不到／不合法 ⇒ 最嚴、設定預設與放寬方向、端點多回的鍵（沒有金額權限者仍 403）、鎖住的資料庫與 DEFAULTS_ONLY 下調嚴的值不被放回。
- 順手修：群組 `quote_approval` 的 `min_item_margin_pct.help` 原本含「N」「X」，會讓『設定畫面不得露出代碼』守門測試（`test_settings_ui_plain_language`）紅燈，改成白話。

