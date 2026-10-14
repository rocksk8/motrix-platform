# T62 整合交接（給 46）

> 2026-10-14　hichan-3e。整合分支：`wip/t62-bp2-r5-r1`（主線＋案件提供者＋R5＋K01＋04 修正）；其上一個獨立提交 `wip/t62-approval-margin-r1`（單項毛利率門檻，可單獨丟棄）。T62 預覽把關線 `wip/t62-preview-gate-r1` 已包含在 r5 之內。

## 1. 會衝突的檔案與解法
| 檔案 | 衝突 | 解法 |
|---|---|---|
| `backend/main.py` | 路由匯入／`include_router` | 兩邊都留（`def_governance`、`def_pipeline`、`rules`；3c 的 `custom_fields_builtin`） |
| `backend/routers/def_pipeline.py` | `ACTIVE_KINDS` 一行 | `("custom_fields", "layout", "user_buttons", "rule_set")`（t61 的 user_buttons 加我的 rule_set）；`COMPARATORS` 兩邊都留 |
| `docs/platform/modules.json` | 單元清單 | 取聯集（`router:rules`、`/api/rules`、`helper:rule_*`、`helper:settings_strict`、`js:js/rule-marks.js`、`js:js/rules-builder.js`、`js:static/public-flags.js`——public-flags 3c 那邊若沒登記就用我這份） |
| `frontend/pages/case-management.html` | script 標籤區＋`initLayout()` | 旗標讀取用 `MotrixPublicFlags.read(['builder_layout', 'builder_custom_fields', 'builder_rules'], { token })`（單一請求；golden 第 99 步＝`GET /api/settings-center/public?groups=builder_layout,builder_custom_fields,builder_rules ×1`）。兩段旗標區塊都留：3c 的 `builder_custom_fields.enabled === true → MotrixCustomFields.start()`，我的 `builder_rules.enabled === 1 → MotrixRuleMarks.start(); MotrixRulesBuilder.mountEntry()`。`public-flags.js` 的 `<script>` 只留一個（我的檔案與 3c e6e33c6dd 逐字相同）。 |
| `backend/helpers/settings_groups.py`、`tests/platform/settings_deploy_baseline.json` | 兩邊都在尾端加群組 | 兩邊都留（文字插入） |
| `backend/modules/case/CHANGELOG.md` | `(next)` 區塊尾端 | 兩邊的條目都留 |
| `frontend/pages/quotation-form.html`（只有 approval-margin 提交） | `pmCfg`／`checkApproval` 三個小區塊 | 與 S5 預期不重疊 |

## 2. 需重新產生的共用生成物（我沒有動）
`route_inventory.json`（+ `/api/rules/config|summary|preview|marks|k01/seed`；`/api/def-governance/{kind}/{key}/impact` 多一個選用的 `version` 查詢參數）、`response_keys_baseline.json`（`/api/project-margin/config` 多 `minItemMarginPct`；`/api/rules/*`）、`l1_interface_snapshot.json`（新 helper：`rule_catalog`、`rule_engine`、`rule_grammar`、`rule_sets`、`settings_strict`）、`INTEGRATION-POINTS.md` 已含 IP-RULES1（`rules.entity`）與 `test_case_module_spec.py` 的 EXPECTED。

## 3. `def_impact` 在 t60 之後的形狀（`_require_user` ＋ `_flag_gate`）
t60-int 現在是 `_gate(authorization, kind)`；t59-int 與 46 說的新形狀是 `_require_user(...)` 在先、`_flag_gate(kind)` 在後。**我要保留的行為**（不論用哪個形狀）：

```python
@router.get("/api/def-governance/{kind}/{key}/impact")
def def_impact(kind: str, key: str, scope: str = Query("company"), version: int = Query(None), authorization: str = Header(None)):
    _require_user(authorization, require_superadmin=True)          # 路由守門掃描器要在 handler 內直接看到
    conn = _flag_gate(kind)                                        # 規則見下
    try:
        out = impact(conn, kind, key, scope) if version is None else impact_of_restore(conn, kind, key, scope, version)
    except D.DefinitionError as e:
        raise HTTPException(400, str(e))
    finally:
        conn.close()
    _audit(_tok(authorization), "definitions.previewed", "ui_definition", "%s/%s/%s" % (kind, key, scope),
           "看過發布前影響預覽（%s %s，草稿戳 %s）" % (kind, key, out["previewHash"] or "無草稿"), {"previewHash": out["previewHash"]})
    return out
```
- `impact_of_restore(conn, kind, key, scope, version)` 與 `version_stamp(version, body, live_version)`（`v<版本>@live<生效版>:<內容 sha256 前 16 碼>`）是 def_governance.py 內新增的兩個函式，整段原樣搬過去（還原預覽的雜湊綁定生效版）。
- `_flag_gate(kind)` 的判定（與我的 `_gate` 相同）：先看 `enabled(conn)`（`builder_governance.enabled`）；`kind == "rule_set"` 時改看 `helpers.rule_sets.enabled(conn)`（規則旗標且治理旗標都開）；其他 kind 若總開關關著、但 `routers.definitions._opt_in_enforced(conn, kind)` 為真（管理者開了該類的強制預覽）仍放行；不通過或 kind 未登記 ⇒ `conn.close()` 後丟 404。
- 發布／還原端點的閘門（`routers/definitions.py`：`_preview_gate`／`_restore_gate`／`_preview_enforced`／`_strict_setting`）已在 r5 內，用 `helpers/settings_strict.strict_value`。

## 4. 旗標一覽（全部預設關，正式機在使用者確認前不開）
`builder_governance.enabled`、`builder_governance.enforce_layout|custom_fields|user_buttons|output_template|rule_set`（loosen=down）、`builder_rules.enabled`、`builder_rules.k01_seed`；`quote_approval.min_item_margin_pct` 預設 30＝今天（不是旗標）。
