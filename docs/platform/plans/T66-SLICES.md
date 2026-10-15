# T66 slice plan (F7 field policy remainder + audience.units + protected grant)

Doc-only. Inputs: `T64-F7-FIELD-POLICY-DESIGN.md` (branch `wip/t66-f7-docs-fix-r1`, §8/§11/§12), `T66-AUDIENCE-UNITS-RESOLVER-DESIGN.md` (this branch family). Estimates in pd are design-time numbers.

**Owners**: the PM assigns windows. Column "Role" is the proposed role; the owner name stays blank until dispatch. "PM + user" = needs a ruling or sign-off, not coding.

**T65 assumption** (verify at T65 freeze; I could not see the T65 branch): T65 delivers the F7 design docs and S1 impact notes, plus whatever S0/S1 code T65 integration lands. Each row says what it needs from T65; if T65 lands less, that row's start is blocked, its content does not change.

## 1. Slices

| ID | Content | pd | Role | Needs (T65 / other) | Flag |
|---|---|---|---|---|---|
| S0 | `fieldCatalog` registration + guard (keys == today's 6 tuples / export `money` cols / layout points). No behaviour change | 1.5 | Window (backend) | none | none |
| S1 | `field_policy.visible()` + migrate `financial_mask`/export exits; empty rules == old output cell by cell | 8.5 | Window (backend; may split by exit) | S0; T65 S1 impact notes | `field_policy.enforce` off |
| S2 | `field_policy` kind: comparator (widen/narrow), impact preview, governance wiring | 2.5 | Window (backend) | S1; D-K1 second-admin path (T62, live) | same |
| S3 | Editor front end + plain-language labels (部門 vs 單位 wording rule) | 2 | Window (frontend) | S2 | same |
| S4 | Custom fields (T61 S5 `x_`) and q3 into catalog | 2 | Window (backend) | S1; T61 S5 | same |
| T66-A (S5a core) | `helpers/org_scope.py` resolver + tests, no caller | 1.0 | Window (backend) | none (independent of S1/S2) | none (no caller) |
| T66-B (S5a wire) | Validator `audience.units` + `visible()` wiring | 1.0 | Window (backend) | S2, T66-A | `field_policy.enforce` |
| T66-C | Impact preview for units (named members, "everyone"/"inactive" badges, ceiling-ineffective note) | 0.5 | Window (frontend) | T66-B, S3 | same |
| T66-D (S5b) | Unit admin API/screen: create/move/deactivate, membership, closure incl. self-row, `invalidate()`, cycle check | 3.0 | Window (full stack) | T66-A | `org_units.admin` |
| P0 | Protected-field inventory (read-only): per field the guarding function and every exit; fills catalog `moneyClass=protected` + exit list. No ceiling from memory | 1.5 | Window (read-only audit) | S0 | none |
| PG | **User written confirmation gate** (§11.6): defaults 72h/24h floor, 90d/365d cap, headcount 10, timeout 7d; audience types; unit keys not grantable | n/a | **PM + user** | P0 done and revised §11 accepted | blocks P1 |
| P1 | `protected_grant` kind + comparator + governance (§11.3) + ceiling-layer read in `visible()` + write-time exit exclusions (§11.4: index, audit diff, recycle snapshot, logs/traces) + access log (fail-closed) | 3.5 in F7 doc; I expect 5-6 | Window (backend; second reviewer for exits) | PG, S2, T66-A/B, P0 | `protected.grant.enabled` off |
| P2 | Red warning box, preview with named snapshot, countdown, auto-revoke UI | 1.5 | Window (frontend) | P1 | same |
| T66-E | Department -> unit mapping tool | TBD | PM decides if/when | T66-D | -- |
| S5c | Row filter by `owner_unit_id` | -- | out of scope | U1 | -- |

P1 note: exit exclusions, fail-closed access log, snapshot audiences and the §11.7 settings are most of the work. Re-estimate after P0.

## 2. Dependency order

```
S0 -> S1 -> S2 -> S3 -> T66-C
 |      \      \-> T66-B (needs T66-A)
 |       \-> S4
 +-> P0 -> PG (user) -> P1 -> P2
T66-A (anytime) -> T66-B, T66-D
```
- **Start now (no T65 dependency)**: T66-A, S0, P0 (read-only).
- **Wait for T65 integration freeze**: S1, then S2.
- **Critical path**: S0 -> S1 (8.5) -> S2 -> T66-B -> P1 -> P2. PG runs in parallel with S1/S2 and must finish before P1 starts; send the confirmation request when P0 completes.
- T66-D and S3 are off the critical path.

## 3. Test and gate impact per slice

| ID | New / changed tests | Existing guards touched | Gate / build cost |
|---|---|---|---|
| S0 | catalog-vs-today parity; planted-key negative control | none | tiny |
| S1 | exit matrix golden (exit x role x flag off/on); "hidden account saves, amount unchanged" write-back test | financial_mask, export, notification placeholder tests | **largest**: many exits; flag off must be byte-identical |
| S2 | comparator, preview-enforced kind, governance | `_PREVIEW_ENFORCED_KINDS` registry test, definition pipeline tests | medium |
| S3 | UI button/label verification | UI inventory | medium |
| S4 | custom numeric field default-hidden | T61 S5 tests | small |
| T66-A | `test_org_scope_t66.py` (E1-E6, E8-E11, E14, E16-E18; mutation control; fail-closed on sqlite error; TTL with injected clock) | `test_unit_scope_guard_t6` stays green (no schema change) | small, in-memory sqlite |
| T66-B | validator cases; margin-subset on expanded sets; flag-off golden equality; grep-guard "only org_scope reads user_units/closure at runtime" (planted-read positive control) | field_policy tests | small |
| T66-C | preview rendering cases | -- | small |
| T66-D | closure self-row, cycle rejection, invalidate-after-write, membership audit | `test_org_units_u0a`, `test_u0a_rollback_drill`, unit-scope guard (declared-table ceiling 139 must not rise) | medium; no column added |
| P0 | scanner positive control (planted exit is found) | -- | tiny |
| P1 | snapshot at approval; root unit forbidden; no-row-not-root; proposer != approver; revalidate at activation; timeout and expiry at read time; single-top-admin disables grant and settings relaxation; tightening immediate + audited; exit-exclusion test per sink (index, audit diff, recycle snapshot + restore backfill, logs/traces, notify/email/LINE placeholder); access log one row per record view, write failure denies read | audit, recycle bin, search index, notification, backup/export tests | **heavy**: several subsystems; second reviewer; full gate; build only after PG |
| P2 | UI cases | -- | medium |

Rules for every slice: flag off == zero change (golden equality); run only the slice's own tests locally (full gate only at train freeze, per the shared-machine load rule); tests run in `.venv312`; delete own pytest temp afterwards.

## 4. Release grouping (suggestion)
- Train N: S0 + T66-A + P0 (no behaviour change).
- Train N+1: S1 alone (widest blast radius).
- Train N+2: S2 + T66-B + S3 + T66-C + S4 (T66-D may ride along).
- Train N+3: P1 (only after PG), then P2 (may share the train).
Flags default off; enabling is a settings action, not a deploy.

## 5. Risks
- S1 size and T65 timing gate everything except T66-A, S0, P0.
- PG is a user action; unscheduled, it stalls P1/P2. Ask early.
- P1 exit exclusions touch search, audit, recycle bin and logging: use a reviewer who did not write them.
- One fail-closed rule across resolver and grants: bad data = empty set, never root.
