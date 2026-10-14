# T63 Q0 — settings groups for quote/case/finance decisions (spec)

> Date 2026-10-15. Author: hichan-1f. Status: **spec only (docs); no code, no pytest** (T62 gate pending). Base: `origin/train/t62-int` @ b87f1b79d.
> PM rule (framework-first): no decision is hardcoded. Each open decision is a settings-center option, default = the safe value, changeable in-system by the top admin; loosening a risky option needs a second top-admin (D-K1 pattern).

## 0. Findings that change the earlier plan (verified on the base)
1. **S5 and Q3 are already in the train.** `backend/helpers/builtin_fields.py` has `RECORD_TYPES = case_info, quotation, supplier` (Q3 commit 3f5b9434b; write gate `_quote_custom_fields_gate` in `modules/case/api/quotations.py:1605`). The branch `wip/t61-s5-impl-r5` is not an ancestor by name, but its content is present. So "S5 before Q3" is already satisfied in code; decision (c) reduces to *how Q3 is exposed*, not merge order.
2. **Today's Q3 behavior is hardcoded**: the docstring says custom fields are internal only (not in PDF, preview, sign-back page). Q0 turns that into options (default = same as today).
3. **One master flag exists**: group `builder_custom_fields`, field `enabled` (type `bool`, risk `ops`). Its help text says fields appear only for case info and supplier — must be updated to mention the quote form.
4. **Registry constraint**: `SettingDef(loosen=...)` is allowed **only for `int`/`float`** (`settings_registry.py`, ValueError otherwise). Any option that must require a second approver is therefore an **int code with `choices`**, not a bool. Existing pattern: `finance_cashier.custom_due_soon` (int 0/1 with choices).
5. **Per-document PDF toggles already exist**: the quote form has `q.pdfShow.{taxId,contactName,contactPhone,contactEmail,…}` (`quotation-form.html` ~1284-1350; read in `pdf_gen.py:302`). Decision (a)/(b) options sit above this: they set the company-wide behavior; `pdfShow` stays the per-quote switch. Implementation must read `pdf_gen.py` terms rendering before coding (not verified here whether terms blocks honor `pdfShow`).
6. **Status display is already a group**: `builder_status_display` ("狀態顯示名稱與顏色") exists. Decision (d) reuses it; no new group.

## 1. Naming (verified against `helpers/settings_groups.py`)
Groups are flat snake_case codes (`quote_approval`, `finance_cashier`, `builder_custom_fields`, `completion_note`…), fields are snake_case without dots. The dotted keys in the delta (`quote_terms.hidden_terms_pdf_mode`) are replaced by `<group>` + `<field>` as below. Registration via `register_group(...)` in `settings_groups.py` (core) with `S(...)` = `SettingDef`. Every field needs: `question`, `label`, `help`, `impact` (zh-Hant, no raw keys); `risk_text` if risk is money/legal/security or `requires_pending`; `impact_scope` when `loosen`/`requires_pending`; `choices=[(value, label, impact)]` for options.

## 2. The eight settings
Risk levels use the registry values: `none`, `ops`, `legal`, `security`, `money`. "Who" = top admin (group `sensitive=True` where noted). Loosen direction is expressed on the int code.

| # | Group.field (final key) | Type / choices (default first) | Risk | loosen | Who / approval |
|---|---|---|---|---|---|
| a | `quote_output.hidden_terms_pdf_mode` | int: 0 print default text (default), 1 print only if filled, 2 omit hidden terms from PDF | legal | `up` | top admin; 1→2 or 0→1/2 = loosen: pending + confirm period + second top-admin; back down = immediate |
| a2 | `quote_output.hidden_terms_editor_warning` | int: 1 show warning when hiding a terms field (default), 0 don't | none | — | top admin, immediate |
| b | `quote_privacy.contact_email_hideable`, `quote_privacy.contact_fax_hideable` | int each: 1 hideable (default per PM), 0 core (not hideable) | legal (PII) | none (default is already hideable per PM; hiding affects input only, notice flow is b2) | top admin, immediate |
| b2 | `quote_privacy.notice_flow_when_hidden` | int: 1 notice flow unchanged (default), 0 skip notice when field hidden | legal | `down` | top admin; →0 = loosen: second top-admin + confirm period. H5 audit stays hardwired |
| c | `builder_custom_fields.quote_enabled` | int: 0 off (default), 1 on | ops | — | top admin; enabling is a pending change with preview; requires master `enabled` = true (see §4) |
| c2 | `builder_custom_fields.quote_in_customer_output` | int: 0 internal only (default), 1 may appear in PDF/preview/sign-back | legal | `up` | top admin; 0→1 = loosen (second approver); impact preview lists the customer-output paths |
| c3 | `builder_custom_fields.quote_on_finance_docs` | int: 0 never (default), 1 may appear on invoice / payment-request / receivable views | **money** | `up` | top admin; 0→1 = loosen, second top-admin per **D-K1**; `risk_text` mandatory |
| d | `builder_status_display` (existing) | existing label/color fields; **canonical values (`dealTag` '已成案' etc.) stay unchangeable** | ops | — | top admin; display only |

Notes
- (b): only `contactEmail`, `contactFax` are non-core today (`case/module.json` lines 121-122). All other contact fields remain core and are not offered.
- (a)/(b)/(c2)/(c3) change **rendering/inclusion only**; no stored data is changed or deleted (hidden values stay in `data_json`).
- Group `quote_output` and `quote_privacy` are new; (c)/(c2)/(c3) extend the existing `builder_custom_fields` group (keep `enabled` bool as-is for compatibility).
- Defaults reproduce today's behavior exactly (zero behavior change). Equivalence test required (§6).

## 3. Governance and ledger
- Use the existing publish path in `settings_registry.publish()`: changes in a `loosen` direction (or `requires_pending`) go pending → second top-admin approval (single admin: reason + confirm period + warning + notification) → confirm period (`confirm_period_days`, default 7) → effective; tightening is immediate. Do **not** build a parallel approval mechanism.
- Every change writes the settings ledger (`L.record(domain, group, changes, reason, actor, ip, risk=…, ref_version=…, effective_at=…)`), includes reason (mandatory for risk ≠ none), and is covered by the existing snapshot-before-change + one-click restore.
- Read failure → strictest value (D-K1 rule): a2/b/b2 unreadable ⇒ keep notice and warnings on; a unreadable ⇒ print default text; c/c2/c3 unreadable ⇒ off.

## 4. Dependency check (UI, no L1 change)
`register_group(..., cross_check=fn)` already exists (`fn(values) -> [problem]`). Use it:
- `quote_enabled=1` requires master `enabled=True` → problem text (zh-Hant): 「要先開放『內建畫面的自訂欄位』，報價單才能使用。」
- `quote_on_finance_docs=1` requires `quote_enabled=1`.
- `quote_in_customer_output=1` requires `quote_enabled=1`.
UI shows the option disabled with the plain reason (via `cross_check` problem + `choices` impact text); no code/keys shown.

## 5. impact_fn (read-only live numbers; failure falls back to static text)
Signature: `impact_fn(conn, new_value) -> {"numbers": {...}, "sentence": "…"}`.
- a: count quotations whose terms fields (`paymentTerms/deliveryTerms/acceptanceTerms/warrantyTerms/afterSales`) are non-empty or have preset text (those would stop printing) — "N 張報價單的條款將不再印出".
- b/b2: count quotations with non-empty `contactEmail`/`contactFax`; count customers with a recorded notice (read-only).
- c: number of quotations that already have `customFields` (reuse `builtin_fields.usage_counts("quotation")`).
- c2: number of quotations with `customFields` that would become visible to customers; list of output channels (PDF, preview, sign-back page).
- c3: count of invoices/payment requests linked to quotations with `customFields`; names the document types.
All impact_fn are SELECT-only, with row caps; must not take write locks.

## 6. Guard tests (list, for the code slice; not run now)
1. Equivalence at defaults: with all Q0 options at default, quote PDF/preview/exports and quotation GET/PUT responses are byte-identical to base (extend existing PDF golden tests).
2. Registration validity: every new field has zh-Hant question/label/help/impact; `risk_text` for legal/money; `loosen` only on int; `impact_scope` present for loosen/pending fields (registry raises at import — test imports the module).
3. Loosen governance: changing a→2, b2→0, c2→1, c3→1 returns pending (not effective); tightening is immediate; single-admin path produces warning + notification.
4. Strictest-on-failure: corrupt/missing stored value ⇒ strictest value (per §3).
5. Customer-output scan: with c2=0, `customFields` content never appears in PDF, preview, sign-back page (positive control: with c2=1 it does appear in a test fixture).
6. Finance scan: with c3=0, `customFields` never appears on invoice/payment-request/receivable payloads (positive control with c3=1); money amounts/tax/rounding paths untouched (existing money golden tests unchanged).
7. Masking first: role without financial visibility still gets masked amounts after any option change (existing publish-before/after API-equal test pattern).
8. Hidden data preserved: hiding `contactEmail`/`contactFax` or terms fields never removes stored values; PDF behavior follows a/b only.
9. H5 audit: money-document tamper-proof audit rows still written regardless of b2.
10. No raw-key leak: settings UI payload for the new groups contains no raw keys/enums (existing guard pattern for settings pages).
11. Dependency checks (§4) produce the zh-Hant problem texts and block enabling when unmet.
12. Spine scan: new groups declared in `module.json`/allowlist if the literal scanner requires it (`tests/platform/test_spine_literal_scan.py`).

## 7. Slice and order
Q0 (this spec) → implement after the T62 gate: register groups + `cross_check` + `impact_fn` + wire a/b/c2/c3 reads at the existing hardcoded points (PDF terms block, `case/module.json` core flags via layout engine, `_quote_custom_fields_gate`/output paths) → guard tests. Hotspots to serialize: `quotations.py` (S-ST4, export-cols, Q0 wiring), `pdf_gen.py` (pay-stage-src, Q0 (a)).

## 8. Open items (need confirmation, not assumed)
- Whether terms blocks in `pdf_gen.py` honor `pdfShow`; if not, (a) mode 1 definition must be fixed by code reading first.
- Exact customer-output paths for c2 (PDF `pdf_gen.py`, preview, sign-back page) and finance document types for c3 — enumerate by `git grep` at implementation time; the scan test is the source of truth.
- Single-admin installations: governance falls back to reason + confirm period + warning (registry behavior); confirm this is acceptable for c3 (money).
