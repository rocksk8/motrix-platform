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
