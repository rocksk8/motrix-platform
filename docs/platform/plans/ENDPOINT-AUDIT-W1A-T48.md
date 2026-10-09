# 端點稽核 W1a：accounting／analytics／arap／payroll（第 48 班，2026-10-09）

> 範圍：`backend/modules/{accounting,analytics,arap,payroll}/**`。基準 `origin/platform` 4012847ab。修正分支 `wip/t48-w1a-fixes`。
> 原則：只修明確壞掉的；刪除只在「全 repo 零引用且非對外端點」時做（本次沒有符合者）；其餘列「延後＋理由」。

## 方法（可重現）
1. **動態探測**（一次性 pytest，未提交）：走 app 路由表（逐層帶 include 前綴），取 `endpoint.__module__` 屬於四個模組的所有路由 ⇒ 共 **234 個 路由×方法**（accounting 93、payroll 79、arap 41、analytics 21）。每條各打兩次：①不帶 token；②帶「角色 sales、模組清單為空」的帳號（路徑參數代 `1`、非 GET 送 `{}`）。
2. 靜態：AST 掃描每條路由函式內的守門呼叫（`_require_user(…, require_superadmin=True / module=…)`、`require_any_module`、`has_*_access`、各檔 `_require_*`）；對 422（驗證先於守門）與 404（先查列再守門）的路由逐一讀碼確認守門在。
3. 前端：frontend 的 `/api/...` 字面值與四模組路由比對；測試／文件／其他原始碼引用計數。
4. 串接點：把執行期登錄表（`registry._LEGACY_PROVIDERS` ＋已載入模組 `spec.providers`）傾倒出來，與全 backend 非測試碼的 `single_provider/providers("…")` 消費端、`INTEGRATION-POINTS.md` 比對。

## 總表
| 項目 | 結果 |
|---|---|
| 不帶 token | 234／234 ＝ 401（`auth_middleware`；四模組沒有任何非 `/api/` 路由，不需白名單） |
| 零模組帳號 | 403×170、422×28、404×16、200×11、410×8、400×1（見各模組；422／404 已讀碼確認守門在） |
| 前綴 宣告 vs 實際 | **1 處遺漏（已修）**：accounting `/api/expense-categories` |
| 串接點 | 提供的能力全部有 IP 章節；四模組消費的能力在全載入時全有提供者；無孤兒章節 |
| 懸空前端呼叫 | 0（`/api/settings/*` 命中屬 L1 routers，不在四模組） |
| 死端點（零引用） | 0 ⇒ 沒有刪除；有 2 組「無前端呼叫」列為提案 |

## accounting（M06，93 條）
| # | 發現 | 處置 |
|---|---|---|
| 1 | `GET /api/expense-categories`（`ledger_category_map.list_router`，IP `expense.categories`，任何登入者）實際由本模組提供，但 `module.json`／`modules.json` 的 `api_prefixes` 沒宣告 | **已修**：兩處補 `/api/expense-categories`；accounting CHANGELOG `(next)` |
| 1b | 為何沒被守門抓到：`tools/platform/dep_scan.py` 的路由歸屬檢查只讀名為 `router` 的 APIRouter；`list_router` 是全 repo 唯一一個不叫 `router` 的 | **延後**：改 `dep_scan`（工具，屬全域稽核 1d 範圍）；目前全 repo 只此一例，不會再漏 |
| 2 | 守門：除 `GET /api/account-items`（科目樹挑選用，登入即可）、`GET /api/expense-categories`（IP 明載「任何登入者」）外，零模組帳號全部被擋；`POST/PATCH /api/account-items` 要 superadmin；總帳讀 `cashier|finance`、寫 `finance`；T100 匯出 `_require_t100_admin/superadmin`。28 條 422 是參數驗證先於守門，已逐檔讀碼確認每個函式第一行就是守門 | 無需修；兩條「僅登入」列為**有理由的例外**（資料＝科目名稱／類別名稱，不含金額） |
| 3 | 提供：`accounting.settings`、`expense.categories`、`gl.category_account`、`gl.source_status`、`ledger.month_totals`、`voucher.*`（by_case／by_no／draft／status／void_draft／account_check）全有 IP 章節與消費端 | 無 |
| 4 | `module.json` probes（`/api/vouchers`、`/api/account-items`）皆為本模組 GET 路由、唯讀；7 個頁面都存在；7 種信件類型都有寄送點 | 無 |
| 5 | `PUT /api/ledger/settings`（會計年度起始月）：沒有前端呼叫、沒有測試（只有 route_table golden／文件）。`fiscal_year_start_month` 全 repo 只在後端出現 ⇒ **功能缺口（沒有設定畫面），不是死碼** | **延後＋提案**：要嘛在 `ledger-settings.html` 補一個欄位，要嘛明載「僅 API／DBA 設定」。需使用者裁示 |
| 5b | `GET /api/ledger/events/preview`、`/engine/runs`、`/statements/check`、`PUT /api/ledger/roles`：無前端呼叫但有測試與文件（管理診斷／API 用） | 保留 |
| 6 | 懸空呼叫 | 無 |

## analytics（M08，21 條）
| # | 發現 | 處置 |
|---|---|---|
| 1 | 4 個前綴都有路由；沒有未宣告路由。`/api/reports` 與 arap（`bank-reconcile`）、accounting（`t100-export*`，modules.json 明列）共用前綴，屬既有設計 | 無 |
| 2 | `GET /api/dashboard/*`（6 條）僅登入：README 明載「登入；金額依 `financial_view`」，函式內以 `has_finance_access`／`can_see_financial` 過濾金額；零模組帳號得到空資料、`financeVisible:false`。`/api/devices`、`/api/materials-summary` 要 `require_any_module` | 有理由的例外（資料依使用者範圍過濾）；無需修 |
| 3 | 提供 `ledger.month_totals` 的消費端（accounting 提供，analytics 消費）、`receivables.*`、`case.*`、`dispatch.row`、`expense.entries` 皆有提供者 | 無 |
| 4 | probes 4 條皆本模組 GET；4 個頁面都存在 | 無 |
| 5 | 看似「無前端呼叫」的 dashboard 子路由（funnel／ops-alerts／activity-feed／monthly）實際由 `index.html` 呼叫（字面值寫法特殊，掃描一度漏判，已用關鍵字複核） | 保留 |

## arap（M05，41 條）
| # | 發現 | 處置 |
|---|---|---|
| 1 | 4 個前綴都有路由，無遺漏 | 無 |
| 2 | 零模組帳號全 403 或在查列後被單據級守門擋下：`_guard_voucher`（申請人／案件權限）、簽核端點以「是否當層簽核人」判斷（程式註解載明刻意不要求 admin）、出納端點 `has_cashier_access`、`bank_reconcile` 同。404 是「單據不存在」（先查列再守門，對不存在與無權限回同一訊息，不洩漏存在與否） | 無需修 |
| 2b | `get_invoice_voucher`／`download_invoice_voucher_pdf` 在 `conn.close()` 之後還有不可達的 `if not row: raise`（上方已處理） | **延後**（純整潔；為了不動核准／憑據流程程式碼，不在端點稽核裡改） |
| 3 | 提供 `receivables.income_items`／`tax_invoices`、`attachments.for_document`、`calendar.writeback`；消費 `payables.pending`、`remit.reviews`、`bonus.payouts`、`payslip.payables`、`payee.bank_profile`、`contractor_voucher.*`、`voucher.account_check`：全有提供者；缺提供者時多數走 `if hook is not None`／空集合退化 | 無 |
| 4 | probes 3 條皆本模組 GET；3 個頁面都存在 | 無 |
| 6 | 懸空呼叫 | 無 |

## payroll（M07，79 條）
| # | 發現 | 處置 |
|---|---|---|
| 1 | 6 個前綴都有路由 | 無 |
| 2 | 勞報單全部 `module='payslip'`（多數 `require_superadmin=True`），權限 key 與 `module.json permissions: ['payslip']` 一致。零模組帳號只剩設計上的自助／清單端點：`GET/PUT /api/me/bank-account`（本人，PUT 空本 400）、`/api/bonus/awards`（列表依身分過濾，`is_manager:false`）、`/api/bonus/cases`（同）。`/api/bank-accounts*` 對無資格者回 404（檔頭載明「當作不存在」） | 無需修 |
| 5 | **舊版獎金分潤（以人為中心）**：`POST /api/bonus/items`、`POST /api/bonus/awards` 及 `…/{id}/submit｜approve｜reject｜mark-paid｜void｜recall` 共 **8 條直接回 410**（墓碑）；對應的唯讀 `GET /api/bonus/items｜base/{q}｜awards｜awards/{id}｜awards/plan/{q}｜awards/candidates｜awards/{id}/preview｜pdf-download` 仍可讀舊資料。前端（`bonus.js`）已改用 `/api/bonus/cases`，**沒有任何前端呼叫**；但各有 1～16 題測試與文件引用，且 `module.json` probes 用到 `/api/bonus/awards`、`/api/bonus/items` | **延後＋提案**（不符「零引用」不刪）：①8 條 410 墓碑可在下一班連同其測試刪除（行為＝永遠 410）；②舊 GET 是否保留要看舊獎金單資料是否還要在 UI 查閱——需使用者裁示；刪除時 probes 要改成 `/api/bonus/cases` |
| 3 | 提供 `payee.bank_profile`、`payslip.payables`、`payslip.remit`、`payslip.dispatch_links`、`bonus.payouts`、`bonus.module_status`、`attachments.catalog`、`gl.events`；消費 `voucher.*`、`accounting.settings`、`dispatch.brief`：全有 IP 與提供者 | 無 |
| 4 | probes 4 條皆本模組 GET（其中 2 條是上述舊獎金端點）；5 個頁面都存在；8 種信件類型都有寄送點 | 見上（probes 隨舊端點處理） |
| 6 | 懸空呼叫 | 無 |

## 修正與分支
- 分支 `wip/t48-w1a-fixes`（自 `origin/platform` 4012847ab）：1 個修正提交（accounting 前綴宣告＋CHANGELOG `(next)`）。
- 測試：`test_module_boundaries`、`test_route_ownership`、`test_module_startup`、`test_module_changelog_follows_code`、`test_version_slots`（非列車模式）、`test_module_rc_scope`、`test_generated_maps`、`test_non_api_routes_whitelist` 單進程全過（列車模式下 `test_version_slots` 的 `(next)` 佔位紅屬預期）。本變更只動宣告（`module.json`／`modules.json`），沒有程式行為變化，模組測試不受影響。
- 產生檔（dep_graph／UNIT-INDEX／test_map）沒重產：wip 分支不可帶產生檔，列車重產。

## 給 1d（全域守門稽核）的備註
- `dep_scan` 路由歸屬只認 `router` 變數名（見 accounting #1b）。
- 「零模組帳號逐路由探測」這種動態探測能補靜態掃描看不到的守門順序問題（422／404 先於守門）；可考慮做成常駐守門（每模組一題，列出不 401／403 的路由並比對有理由清單）。
