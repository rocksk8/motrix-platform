# T48 overhead 25% — independent audit #1 (hichan-1d, 2026-10-09)

Scope: s1 75e426fb2, s2 fb6ff8e77 (S3 commits above it NOT reviewed), s4 d374a6512, s5 68dc19aa1, s6 e8f3f7dd3. Read-only; ran only profit_rules / s2 / s5 test files (all pass: 5, s2 file, 6).

## Formula (S1) — PASS
- Python/JS parity OK: golden vectors 251 cases incl. pct 0/100/0.1/7.1/12.5, 21 negative-direct. Charity `max(0,halfUp)`, admin `max(direct,0)` match spec. Frozen S5 formula vs `profit_rules` v2: 200k random quotes, 0 diffs (adminCost/netProfit/netMarginPct).
- Nit: JS `pctRate` rejects exponent/negative strings (`1e-7`), Python accepts; unreachable via `parse_pct` (0–100, 1 decimal).

## MUST-FIX
1. **S5 migration overwrites per-quote custom pct** — `recalc.py:44,104-106` uses one global `pct` for every unsettled quote; a quote already holding `data_json.overheadPct` (set by superadmin in legacy mode, S2 stores it) is reset to default. Use `d.overheadPct` when present.
2. **S5 plan/apply race with live writes + settled-freeze hole** — `overhead_migrate.py:133` plans outside the txn; `apply_plan` (`recalc.py:91-108`) only re-checks `formulaVer`, then writes the *stale planned values*. A save/finalize between plan and `BEGIN IMMEDIATE` (line 161) ⇒ stale tot written, or a just-finalized quote recalculated. Fix: run `plan()` after `BEGIN IMMEDIATE` and re-check `is_settled`; require app stopped or document it.
3. **Client-supplied `tot.formulaVer/overheadPct` survive in legacy mode** — `profit_guard.py:~120-137` legacy branch never strips them. DevTools/stale client can stamp `formulaVer=2` on a 10%-basis tot ⇒ S5 `skip_done` (`recalc.py:75`) skips it, labels (S6 `bonus.py:166-175`) show the new basis. Strip/force-set `tot.formulaVer/overheadPct` server-side in both modes (legacy: pop them; settled: keep DB value).
4. **Hard-coded "管銷分攤（10%）" will be wrong after v2** (S4 did not make them dynamic): `pdf_gen.py:2633,2650`, `analytics/api/reports.py:2157,2177`, `case-management.html:2739,2780`, `reports.html:2229,2267`. Also `settlement_actuals.py:487-488,493` still "管理費/淨利/淨利率(%)" and 10% text (check S3 covers). Block enabling `v2` until fixed.
5. **Mode flip is unguarded** — `overhead.py` PUT `ruleMode=v2` and tool `mode` succeed without migration done or `_expected_downstream` (still 10%, `settlement_actuals.py:489-512`, untouched by S2) updated ⇒ every 完結 check mismatches. Require S3 + migration; add precondition/warning.

## SHOULD-FIX
6. `profit_guard.server_profit:61-66` trusts client `tot.pretax` (not recomputed from items/discount/freight), so "server recompute" doesn't stop pretax inflation via DevTools; recompute `pretax = Σamount − discount + freight` (still client amounts, but at least self-consistent) — or state the limit.
7. `quotations.py:1850` (PUT): `_PG.prepare` raises 403/422 after `conn=get_db()` (line ~1770) without `conn.close()` (all neighbouring raises close it) → leaked connection; also runs after `_build_approval_tiers_and_notify` (~1764) so a rejected non-superadmin pct change may already have sent approval notifications. Move `prepare` to the top of the handler.
8. Non-superadmin friction/false 403: `prepare` compares against *current global default*; after superadmin changes the default, any non-superadmin save of an old unsaved-pct quote, or copy-as-new of a quote with custom pct (POST path, `quotations.py:1496`), gets 403 though they changed nothing. Ignore incoming pct when it equals the stored/previous value; for copy-as-new, drop pct for non-superadmin.
9. S5 rollback fidelity: `_legacy` lives inside `tot`; the form rebuilds `this.tot={…}` (`quotation-form.html calcTotals`) so any post-migration save drops `_legacy` → `plan_rollback` silently omits it and rollback leaves mixed basis; rollback also restores stale totals over later edits. Report "not restorable" count; keep `_legacy` server-side (S2 `prepare` can carry it over).
10. S5 `--pct` unvalidated (`overhead_migrate.py:117`): `abc` ⇒ every quote `skip_nodata`, exit 0; `250`/`-5` accepted. Reuse `parse_pct` rules. Also `five = totalIndirect−admin−charity` (`recalc.py:43`) can go negative on stale tot — skip as nodata.
11. Recalc under `legacy` mode: migrated quotes (v2 tot) re-saved by legacy form silently revert to 10% basis and lose the stamp. Tool should refuse/warn unless mode=v2 (or set it in the same txn).
12. Reports mix bases: AVG/sum of `net_margin_pct` over unsettled(new) + settled(old, frozen) quotes (analytics KPIs, dashboard) — add a basis note or split by `formulaVer`. Draft-settlement `origAdminCost/_origTot` snapshots are not migrated (S5 skips summary) — confirm S3 reconciles.

## NITS
- Legacy "zero behaviour change" is not strictly true: `prepare` persists `overheadPct` on every *new* quote even in legacy (`profit_guard.py:~118`) and 422s junk pct; shadow compare is cheap (O(items), 2 settings reads) and compares float-equal on 5 keys — acceptable, but doc should say "data shape adds overheadPct".
- Mask: top-level `overheadPct` is not in `financial_mask.QUOTE_MONEY_KEYS` (only `tot`, which hides `_legacy/_recalc` correctly) ⇒ visible to non-money roles in quote JSON; add it (PUT already requires money visibility). `GET /api/overhead/settings` readable by any login (pct + mode only; fine, note).
- Labels still old by design: history label "淨利率" kept in mask set (good); `bonus.py:114`, `bonus_case.py:14` comments mention 10% (bonus rate, unrelated). Not-reviewed: settlement.html (13 hits), quotation-form (3) = S3.
- Cross-slice: S5 tests don't exercise app reader (`_get_setting`) against tool-written keys; formats verified compatible by hand (`value_json` JSON).
