# T48 independent audit #3 (hichan-1d, 2026-10-09): wip/t48-payslip-person-link 005085fea (base 412a53630)

Static review + `test_payslip_person_link_t48.py` (7 passed, single worker). Not run: e2e (browser).

## MUST-FIX
1. **Backfill writes a name-guess into the authoritative `payslips.contractor_id`, which money/GL paths read without looking at `contractor_match`.** `payroll/gl_events.py:75` builds the E06/E06b party key as `C<contractor_id>` else the name, and `ledger/contract.py:116` puts the party key in the event signature ⇒ every backfilled 已簽回/已付款 payslip changes party key (name → `C<id>`) for already-posted entries ⇒ drift / split sub-ledger (應付對象). Also `remit_link.candidates()` (`remit_link.py:41`) now lists name-guessed payslips as payable for that payee, and the payee check at `contractor_vouchers.py:963` turns strict for them. Fix: do not touch rows with status 已簽回/已付款 (and skip 已作廢), or better store the guess in a separate column (`contractor_guess_id`) and promote to `contractor_id` only on confirm. If kept as is, add `contractor_match=''` filters to gl_events/remit_link and document.
2. **`unconfirmedCount` is returned to every dispatch-tab viewer** (`dispatch_payslip_links.py` list_payslip_links return) — spec says superadmin only; UI hides it but the API doesn't. Return 0 unless `_can_open(user)`.

## SHOULD-FIX
3. `byPerson` lists ALL confirmed payslips of each person on the dispatch (any case, any date; slip no, status, name) to every user passing `require_any_module` + this case's guard — cross-case disclosure beyond "same visibility as before" (before: only explicitly linked slips). Limit to slips linked to dispatches of the same case, or superadmin-only, or confirm with the user (Q9).
4. Rollback: loader never refuses a newer module schema (`run_all` skips `v <= start`), so code-only rollback with schema 5 is safe (column has default; old INSERTs OK) — but the **backfill is not undone** by code rollback (contractor_id stays; GL/remit effects in #1 persist). Step file must include `UPDATE payslips SET contractor_id=NULL, contractor_match='' WHERE contractor_match='unconfirmed'` and warn it also reverts any later unconfirmed rows; take the DB backup before first start.
5. `up()` returns a string when `contractors` is missing (`0005…py`, 2nd return) ⇒ loader rolls back the savepoint AND takes the whole payroll module offline until it appears. `contractors` is created in db.py so prod is fine, but a string for "nothing to backfill" is too harsh: return None after adding the column.
6. Single `?dispatchId=` path (`payslips.py` create) still skips the "dispatch must contain this person" check that `dispatchIds` enforces — inconsistent; apply the same membership rule (or document).
7. PUT on an unconfirmed slip keeps the guessed `contractor_id` even if the user changed the name (form sends no id): payslip "B" stays bound to guess "A". Drop the guess (set NULL, match '') when `contractorName` changed.

## NITS
- Migration is idempotent (ADD COLUMN guarded; only `contractor_id IS NULL`; never creates links; unique-name only; Python `strip` vs SQL TRIM only matters for blank names). Prod-shaped DB (10 rows, 5 voided): voided rows are also backfilled — pointless, exclude 已作廢.
- Create authz OK (superadmin + payslip module); `dispatchIds` ≤50, int, de-duplicated, membership via `dispatch.brief.personnelIds`, links in the same txn with rollback; no IDOR concern since superadmin-only, `contractor_id` itself is not verified to exist (FK only).
- `GET /api/payslip-person-dispatches` (superadmin; doc says `/api/payslips/person-dispatches` — fix doc), no amounts/ID/bank; `confirm-contractor` superadmin, conditional UPDATE (race-safe), audited. `dispatches_for_person` uses `LIKE '%id%'` full scan then exact parse (fine at current size).
- IP-115 registered as single provider; `dispatch.brief` additions (`dispatchDate`, `personnelIds`) are additive — IP-113 consumers unaffected.
- UI: picks reset on person change; payload sent only when `contractorId` set; badge/confirm use `alert/confirm` dialogs (project convention elsewhere is toast) — nit.
