# T48 independent audit #2 (hichan-1d, 2026-10-09): paydate-gap 8012381a7, r2-step2 92bc62853, oh25 re-check

Read-only static review (no tests run; machine loaded). Scope per node-d8 request.

## (1) wip/t48-paydate-gap — no must-fix
- Validation parity OK: UI sends `planned_pay_date` (null when blank) → `contractor_vouchers.py:384` `normalize_date` (400 on bad format, '' / None = unset), runs inside `write_txn` so the earlier `payable_date` UPDATE rolls back on 400. Both create modes (whole / kind) carry the field.
- No other behaviour change: field optional, no backend/migration; create is `_require_admin` only.
- Masking: date is non-money; card shown under `_cvRowVisible && canFinanceRole()`; API `plannedPayDate` goes to anyone who can see the voucher (finance or the voucher's approver, `_visible_rows`). CHANGELOG says "same range as card" — slightly narrower than the API (approvers see it via API/queue). Nit: reword.
- Nits: card still shows 預定付款日 after the voucher is paid (platform treats it as history only) — consider hiding when `isPaid`; no past-date / sanity bound (same as other endpoints). Reminder e2e is a real `@pytest.mark.skip(reason=…L1…)` with the TODO text — fine; ensure it is removed when L1 lands (add to train checklist).

## (2) wip/t48-r2-step2 — no must-fix; 3 should-fix
- PUT reject (`auth.py` `_subtracted_clash`, flag `users_put_reject_subtracted`): correct placement (only when `body.modules` sent), flag default ON, fail-open on any error, audit `user.put_rejected_subtract` after conn.close. OK.
- Preview `POST /api/duty-roles/preview`: `require_superadmin`, read-only, uses same `apply_duty`; inactive roles excluded like real path (`resolve_raw_modules` active=1). No widening found; `apply_duty` returns the same object when nothing bound (zero-change proof kept).
- audit_id same txn: `_write_audit` inserts into `audit_log` on the same conn before `permission_changes`, one commit; no-op `update_role` branch commits its audit row. Matches `helpers.audit._audit` columns. Nit: unlike `_audit` there is no old-schema fallback (core migration v3) — op now fails if columns missing (acceptable; v3 is old).
- SHOULD-FIX 1: `users-duty.js` — a module that is both ticked in `form.modules` and in `duty.subs` disappears from `dutySubCandidates()` (filtered by `form.modules`) so the superadmin cannot untoggle the subtract in the dialog; save then hits the 400. Auto-drop the sub (or show it greyed) when the module is ticked, so `dutyBefore` unsubtracts it first.
- SHOULD-FIX 2: `preview_whatif` for base role `superadmin` returns `effective_modules` = raw + finance keys, not "all keys" (real gate uses `user_has_module` → True for superadmin), contradicting its docstring; the dialog lets `form.role` be switched to superadmin. Return a "全部" marker for superadmin.
- SHOULD-FIX 3: `audit_account_permissions --default` labels `basis:"effective"` even when per-user `effective_modules` threw and it silently fell back to raw (`eff[id]=None`); and superadmin rows now get +3 finance keys (moduleCount / sparse flag change). Mark per-row basis, or exclude superadmin.
- Q3 (no template prefill): correct and safer — server `effective_modules` has no empty→template fallback, so the old form showed rights the user didn't have and one Save granted the whole template. No widening. Nit: `duty.doneBeforePut` is not reset in `dutyOpen`; if the next opened user is superadmin (dutyBefore early-returns), a PUT failure message could cite the previous user's "已先完成…".
- Save order (unsubtract → PUT → unbind/bind → subtract) is the right one; partial-failure messaging present.

## (3) oh25 re-check — NOT yet testable
s2 head still eb368c002 (= fb6ff8e77 + S3), s3 ddd6c9987 = merge of s1,s2,s4,s5,s6; the only `profit_guard.py` change vs fb6ff8e77 is `tot["overheadPct"]=q["overheadPct"]` (+2 lines). None of the 5 must-fix from audit #1 are addressed yet (forged `tot.formulaVer` strip, mode-flip guard / migration marker, `pretax` recompute, validation-before-conn, S5 per-quote pct + plan-in-txn). Will re-check when ab announces the fix commit.
