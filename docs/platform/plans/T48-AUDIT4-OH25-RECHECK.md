# T48 audit #4 (hichan-1d, 2026-10-09): re-check of oh25 fixes — s2b ba13d5cf2, s3 735a140e1, s5 ba5bc0540/04028624e

Tests run (single worker): `test_overhead_s2_t48.py` + `test_overhead_recalc_t48.py` on the s3 tree: 40 passed, 1 skipped. Static review of diffs.

## Audit #1 must-fix
1. Forged formulaVer/overheadPct strip — **PASS** (`profit_guard._restore_stamps`; settled ⇒ DB stamps restored; unsettled ⇒ client `formulaVer/overheadPct` popped, `_legacy/_recalc` kept from DB).
2. Mode-flip guard — **PASS in s2b** (`confirm=true`, 409 without `overhead_migration_done`, `rule_mode()` falls back to legacy without marker). **Assembly note:** the marker writer is b5's 04028624e, which is NOT in s3 (nor s2b); s3's tool sets mode v2 without a marker ⇒ app would stay legacy. 48a (s2b only, no tool) stays legacy ⇒ safe; before the real cut-over the tool must include 04028624e.
3. Server recompute of pretax — **PARTIAL**: v2 recomputes subtotal/pretax/tax/total from items/discount/freight/taxRate, but `items[].amount` is still client-supplied (not qty×unitPrice) and legacy mode still trusts `tot`. Edge: `taxRate:null` ⇒ server 5, JS 0.
4. Validate/403 before conn + notifications — **PASS** (PUT top, own short conn). Nit: now runs before `require_case`/404 and reads a separate snapshot (TOCTOU vs later `existing`).
5. S5 per-quote pct / plan-in-txn + settled re-check / `five<0` skip / `--pct` validation / recalc needs v2 (`--set-mode-v2` same txn) / server-side legacy snapshot for rollback — **PASS**.

## Audit #1 should-fix
conn leak PASS; false-403 PASS (S3 copy sets `overheadPct:null`, server compares against stored/default; form never writes top-level pct unless edited); rollback `_legacy` loss PASS (snapshot + skip_edited_since); recalc-under-legacy PASS; legacy no longer adds `overheadPct` to new quotes PASS; `overheadPct` in `QUOTE_MONEY_KEYS` PASS; reports mixing old/new basis NOT addressed (note in changelog).

## S3 UI
PASS: pct input only for superadmin and not settled (server still authoritative); deviation warning + confirm on save; 還原預設; hidden in legacy; copy-as-new resets pct; formulaVer-aware labels (settlement `adminHow/adminLabel`, pdf_gen, reports.js, case-management-fin.js, bonus.row_label); finalize stamps `formulaVer/overheadPct` and `origFormulaVer/origOverheadPct` server-side.
SHOULD-FIX: `settlement.html:1081` bridge chart label is a hard literal `管理費（報價×10%）` (wrong under v2); leftover wording `管理費` at settlement.html 560/832/969/1402/1409/1413 (rename to 管銷分攤). Nits: `alert/confirm` dialogs; v2→legacy rollback with a form opened earlier saves v2 numbers without stamp; quotes skipped as `skip_nodata` by the tool get v2 actual side vs legacy original side at finalize (`_profit_basis` uses global mode).
