# T48 audit #5 (hichan-1d, 2026-10-09): (A) po-bank-block ccaee3e63, (B) oh25-s3 dac7ec96b delta

Tests: `test_po_bank_block_t48.py` 6 passed; on s3: cutover + labels + s3_form + form_version 24 passed. Rest static.

## (A) wip/t48-po-bank-block
MUST-FIX
1. **Bypass of the block:** `PATCH /api/quotations/{qn}/extra-expenses/{id}/dates` (`case_extra_expenses.py` set_extra_expense_dates) lets any cashier-role user (and superadmin) set `paidDate` on an approved PO, which IP-100 treats as paid (`payable_sql`: paid_date empty = pending). It never calls `mark_paid`, so a blocked PO (empty vendor bank/account, created after `since`) can be marked paid there with no remit info. Apply the same `_po_bank_missing(row, since)` → 409 in that branch when `paidDate` is being set (not cleared). Add a test (none covers /dates).
SHOULD-FIX
2. Check in `mark_paid` is read-then-UPDATE (row read before the conditional UPDATE); fine for the cashier endpoint (single pay endpoint, no bulk/other provider calls `_Payables.mark_paid`), but a change request that blanks the bank between read and UPDATE is theoretically possible — put the block predicate into the UPDATE's WHERE (or read inside the same write txn).
3. `payeeType='employee'` skips the block by design; a requester can flip a PO to employee payee to dodge it. Either accept (document) or also block POs with employee type when the requester != payee.
NITS (all PASS otherwise)
- Semantics OK: absent/empty = OFF; `created_at >= since` string compare is consistent (both second-resolution local isoformat; single INSERT path); future `since` rejected (422, tz-aware rejected); PUT superadmin-only + audit old→new; GET finance/superadmin; one pay endpoint `/api/cashier/pending-payables/{source}/{key}/pay` maps `status=409`; UI disables 登錄付款 with reason (backend is the last line). Reopening the switch sweeps in POs created while it was off (documented).
- Unblock path = existing change request (payeeBank/Account omitted keep old values via `_payee_val`), no new permission.

## (B) oh25-s3 delta (a4ae943a3, dac7ec96b)
- Cut-over sequence test PASS (report → recalc refused without v2 → `--set-mode-v2` writes marker+mode → server recognises v2 → new quote 25% → marker deleted ⇒ legacy again).
- items[].amount server recompute PASS: `round_half_up(qty, unitPrice)` = JS `halfUp(qty, unitPrice)`; header rows 0 (JS leaves header untouched = 0 normally).
- taxRate: stored `0` ⇒ 0% (JS and server, only null/''/missing ⇒ 5). **SHOULD-FIX:** old `calcTotals` treated `null` as 0% tax (`null !== undefined`), now 5% — any stored quotation with `taxRate: null`/'' and `tot.tax = 0` will silently gain 5% tax on its first v2 save (and in the form on open). Before cut-over run a read-only count: `SELECT quote_no FROM quotations WHERE json_extract(data_json,'$.taxRate') IS NULL AND json_extract(data_json,'$.tot.tax')=0` (note json_extract also returns NULL for missing key); if non-zero, migrate those to explicit taxRate 0/5 first. Server `server_totals` also ignores `taxType`: `taxType in (zero, exempt)` with taxRate key missing ⇒ taxed 5% (backend `quote_tax_type` says exempt) — derive from `quote_tax_type`. Nit: string `"0"` ⇒ server 5, JS 0.
- 管理費 relabel PASS (bridge chart `adminLbl`, label guard test greps frontend + non-test backend; none left); FORM V3.19 bumped + `test_form_version_bumped` updated.
- SHOULD-FIX (cut-over): the migration marker is never removed when the mode goes back to legacy via API, so a later legacy→v2 flip passes the marker check although quotes saved during the legacy period are unmigrated ⇒ mixed bases. Delete the marker (or require a new `recalc --apply`) when PUT sets legacy.
