# T66: `audience.units` resolver — design (S5a / S5b)

Status: design only. Builds on T64-F7-FIELD-POLICY-DESIGN §9.9, §11.6, §12.4 (branch `wip/t65-f7-docs-r1`).
Scope: who is in a policy audience by org unit. NOT row-level filtering by `owner_unit_id` (S5c / U1).

## 0. PM rulings (2026-10-16, taken as given)
1. Legacy `divisions` / `departments` / `users.department_id` and the U0a unit tree **coexist**. No forced mapping; resolver never reads departments.
2. Resolver is `audience.units`; **a user with no `user_units` row = root unit** (U1 convention).
3. A mapping tool (department -> unit) is a later, separate item (not in this spec's slices).
4. Resolves T64 §12.4 Q1 as option (b); Q2 (`role_binding` unread) stays recommended default.

## 1. Current state (verified in `backend/core/migrations.py` `_core_next_org_units`)
- `org_units(id, parent_id, code, name, is_legal_entity, parent_sees_children, status, sort_order, ...)`; root id=1 (`U0A_ROOT_UNIT_ID`), seeded `INSERT OR IGNORE`.
- `org_unit_closure(ancestor_id, descendant_id, depth)`; PK (ancestor, descendant). Root self-row depth 0 seeded; **self-row for every unit is required** (invariant, see 3.4).
- `user_units(user_id, unit_id, is_primary, role_binding)`; PK (user_id, unit_id). Seeded once for existing users only; later users have no row.
- No runtime code reads any of the three. `core/internal_cols.py` strips `owner_unit_id`/`unit_id`/`legal_entity_id` from all outputs (unchanged here).

## 2. Data model
No new tables, no schema change in S5a.

Policy audience entry (inside `field_policy` rule, T64 §3):
```json
"audience": { "roles": [...], "users": [...],
              "units": [ { "unit": 3, "includeChildren": false } ] }
```
- `unit`: int, must exist in `org_units`, `status='active'` at publish time.
- `includeChildren`: bool, default **false** (widening must be deliberate).
- Unknown keys rejected (strict validator; no silent drop).
- Dedup on `(unit, includeChildren)`; `includeChildren=true` entry subsumes a `false` entry of the same unit (validator normalises, preview shows normalised form).
- Stored by **unit id**, not code/name (rename-safe). Preview shows current name + code.

Optional S5b additions (migration, only with the admin screen): `org_units` soft-delete via `status='inactive'` (no new column); no change to `user_units`.

## 3. Resolver semantics

### 3.1 API (`backend/helpers/org_scope.py`, read-only)
```
units_of(user_id) -> frozenset[int]          # direct memberships, root-default applied
expand(unit_ids, include_children) -> frozenset[int]
audience_units_hit(user_id, entries) -> bool # the only thing field_policy calls
members_of(entries, explicit_only=False) -> list[(user_id, unit_id)]   # preview / protected-grant snapshot
# explicit_only=True (REQUIRED for protected grants): only users with an explicit, active user_units row;
# the no-row=root default is never applied; any entry that is or expands to root -> raise (grant rejected).
```
`field_policy.visible()` evaluates `hit = role_hit OR user_hit OR units_hit`, then `AND ceiling` (T64 §3 rule 1, §12.2). Units never bypass the ceiling or §11 protected layer.

### 3.2 `units_of(user_id)`
- rows = `SELECT unit_id FROM user_units WHERE user_id=?` joined to `org_units` with `status='active'`.
- **No row at all -> {root}** (ruling 2), **only when the lookup itself succeeded**. Query error, missing table, locked DB, or any exception -> **empty set, never {root}**, and that failure is **never cached** as "no row" (no negative caching of errors; next call retries).
- `units_of` applies to ordinary fields only. Protected-grant evaluation does not use the default (see 3.6).
- Rows exist but all point to inactive/missing units -> **empty set** (fail-closed, not root). Rationale: "no row" is a legitimate default; "dangling rows" is corrupt data and must not widen access.
- `is_primary` and `role_binding` are **not read** (T64 §12.4 Q2). A user in several units hits if **any** unit matches.
- Inactive user (`users` disabled/deleted): audience never hits; the check is made by the caller's existing auth, resolver also returns empty for unknown user_id.

### 3.3 `expand`
- `includeChildren=false`: set is exactly `{unit}`.
- `includeChildren=true`: `SELECT descendant_id FROM org_unit_closure WHERE ancestor_id=?` (includes self via depth 0), filtered to active units.
- Match direction: **user's unit is in the audience unit's subtree** (audience names an ancestor, children members hit). The reverse (child audience, parent member) never hits.
- `parent_sees_children` flag is a **row-visibility** concept (S5c); the audience resolver ignores it. State this explicitly in code docstring to prevent drift.

### 3.3a Inactive ancestors prune the subtree
For audience expansion, a unit is usable only if **it and every ancestor up to the audience unit** are active. An inactive intermediate unit removes its whole subtree from the expansion (members of its active descendants do not hit through it). Reactivation restores it. This applies to ordinary and protected audiences.

### 3.4 Failure behaviour (fail-closed everywhere)
Any of: missing table, closure lacks the self-row, sqlite error, cycle detected, entry fails shape check -> that entry contributes **no hit** (never "all"), a structured warning is logged once per cache generation, and `audience_units_hit` returns False. The validator at publish time rejects such entries so this is a runtime-only safety net.

### 3.5 Cache
- **Ordinary fields**: the cache window is stated and accepted -- a membership or unit change can take up to **30 s** (or the next `invalidate()`) to affect `audience_units_hit`.
- **Protected fields bypass the cache entirely** (3.6): evaluated against the DB on every read, so a revocation, deactivation or membership change takes effect on the next read. The bypass is by call path (`protected=True`), not by TTL.
- Per-process dict `{user_id: frozenset}` plus `{(unit, flag): frozenset}`, keyed by a generation counter.
- Generation bumps on any write to `org_units`, `org_unit_closure`, `user_units` (S5b write paths call `org_scope.invalidate()`; S5a has no writers, but the migration/test helper calls it).
- Multi-process safety: no cross-process cache assumed; cache TTL cap 30 s as backstop, plus generation also re-read from a `PRAGMA data_version`-style cheap check is NOT used (keep simple): TTL only. Out-of-band edits (direct SQL, restore, demo reset) are therefore visible within 30 s; restore/demo reset call `invalidate()` explicitly.

### 3.6 Protected-grant evaluation path
Separate from `audience_units_hit`: reads the **approved snapshot** (named user ids stored at approval), then at every read checks, uncached: (1) user active; (2) user **still matches the original audience criterion** (still holds the explicit `user_units` row / role the snapshot was built from, units still active with active ancestors) -- the snapshot can only **narrow**, never widen; (3) grant not expired/revoked/timed out. If (1) or (2) fails the grant is **auto-revoked for that user** with an audit row `revoked` (reason `criterion_no_longer_matched`). Explicit rows only: no-row=root is never applied. Own active-status check -- does not rely on the caller.

## 4. Validator (publish-time, in `field_policy` kind)
1. Entry shape / types as in 2.
2. Unit exists and is active; else reject with plain-language message naming the unit id.
3. **Any entry naming the root unit (id 1), with `includeChildren` true or false, counts as "everyone"**: on a non-protected field it is allowed but flagged in preview and always goes the approval path (widening); on a protected field it is **rejected** (also any non-root entry that expands to include root, which cannot happen in a tree but is checked).
4. **Widening classification**: adding any `units` entry = widening (goes to approval, like personal exceptions). Narrowing/removal = immediate.
5. `margin` family audience must remain a subset of `cost` audience (T64 §3 rule 3) -- subset test is done on **member sets, not unit ids**: for protected fields compare the **approved snapshots**; for ordinary fields compare the expansion at publish time (preview states the time). Later membership drift is not re-checked; the next publish re-runs it.
6. Protected layer (§11): a unit entry on a protected field is expanded with `members_of(..., explicit_only=True)` to **named members at approval time and snapshotted**; later membership changes do not auto-grant (T64 §12.2). The **snapshot size** (not the unit count) is checked against `protected.grant.max_headcount`; empty snapshot is rejected; root rejected (4.3).
7. Feature flag off or `units` empty -> validator behaves exactly as today (zero change).

## 5. Edge cases
| # | Case | Expected |
|---|---|---|
| E1 | User has no `user_units` row | in root only |
| E2 | User has rows, all to inactive units | empty (fail-closed) |
| E3 | User in several units | hit if any matches |
| E4 | Audience `{unit:2, includeChildren:false}`, user in child of 2 | no hit |
| E5 | Audience `{unit:2, includeChildren:true}`, user in grandchild | hit (via closure) |
| E6 | Audience on child, user only in parent | no hit |
| E7 | Audience unit later deactivated | entry stops hitting; preview shows it as "unit inactive"; policy not auto-edited; publish of an unchanged policy still allowed, new publishes must remove it |
| E8 | Unit moved to another parent (closure rewritten by S5b) | next generation reflects new subtree; protected-grant snapshots unaffected |
| E9 | Closure missing self row for a unit | that unit's `expand` returns empty + warning; S5b write path must always insert self row (test) |
| E10 | Cycle in `parent_id` | S5b rejects on write; runtime detects via closure depth anomaly -> fail-closed |
| E11 | Role-bound member (`role_binding` non-empty) | ignored in S5a |
| E12 | New user created after migration | no row = root; S5b "add user" screen should write an explicit row (not required for correctness) |
| E13 | Unit entry present but user fails the ceiling (no finance permission) | still hidden; preview flags "no amount permission, policy ineffective" |
| E14 | Demo reset / restore swaps DB | `invalidate()` called; test asserts no stale hit |
| E15 | Legacy department head (`departments` manager column) | no effect; departments are not an audience source |
| E16 | `includeChildren` omitted | false |
| E17 | Duplicate / overlapping entries | normalised, union semantics |
| E18 | Unit id as string "3" | rejected (strict int) |
| E19 | Inactive intermediate unit between audience unit and member's unit | member does not hit (subtree pruned) |
| E20 | Query error / missing `user_units` table | empty set, not root; error not cached |
| E21 | Entry `{unit:1, includeChildren:false}` on non-protected | "everyone", approval path; on protected: rejected |
| E22 | Protected read right after membership removed / unit deactivated | denied on that read (cache bypass); auto-revoke audit row |
| E23 | Protected: user has no `user_units` row | not in snapshot (explicit rows only) |
| E24 | Ordinary field, membership changed < 30 s ago | may still use old result; documented window |

## 6. Test list (no heavy ops; all in-memory sqlite, `tests/platform/test_org_scope_t66.py` + validator cases in field_policy tests)
Resolver: E1-E6, E8-E11, E14, E16-E18; closure self-row positive control (resolver on a hand-built tree gives expected sets; **mutation control**: drop a closure row -> test must fail); fail-closed on sqlite error (monkeypatch cursor to raise -> False, not True); cache invalidation after `user_units` insert; TTL expiry using injected clock.
Validator: reject unknown unit / inactive unit / extra key; includeChildren default; root+children flagged everyone; margin-subset on expanded sets (positive and negative); widening routes to approval; flag off -> byte-identical results to pre-T66 on the existing matrix golden.
Regression guards: `test_unit_scope_guard_t6` unchanged and green; grep-guard that `org_scope` is the only module reading `user_units`/`org_unit_closure` at runtime (positive control: guard flags a planted read); grep-guard that `org_scope` never imports from departments code.
Protected: `members_of` snapshot stable after membership change (E8/§4.6); `explicit_only` excludes no-row users and rejects root; headcount counted on snapshot; E19-E24 (E20: monkeypatch query failure then success -> second call correct, proving no negative cache; E22: protected path not served from cache even with warm ordinary cache); auto-revoke writes `revoked` audit; margin-subset on snapshots (positive and negative).

## 7. Slices
| Slice | Content | pd | Depends |
|---|---|---|---|
| T66-A | `helpers/org_scope.py` (`units_of`, `expand`, `audience_units_hit`, `members_of`, cache, `invalidate`) + unit tests; no caller yet | 1.0 | none (can start now, independent of S1/S2) |
| T66-B | Validator support for `audience.units` (shape, existence, widening class, margin subset) + `field_policy.visible()` wiring behind flag | 1.0 | T64 S2 (kind + comparator) + T66-A |
| T66-C | Impact preview: named members per unit, "everyone" and "inactive" badges, ceiling-ineffective note | 0.5 | T66-B, T64 S3 |
| T66-D (=S5b) | Unit admin API/screen: create/move/deactivate unit, edit membership, write closure incl. self-row, call `invalidate()`, cycle check | 3.0 | T66-A; user decision on role_binding stays "unread" |
| T66-E | Department -> unit mapping tool (optional, later, ruling 3) | TBD | T66-D |
| S5c | Row filter by `owner_unit_id` | -- | U1, out of scope |

Total in scope A-D: ~5.5 pd (A+B+C = 2.5 matches T64's S5a 1.5 + preview overhead).
All slices ship behind the existing field-policy flag; with no `units` in any policy there is zero behaviour change.

## 8. Risks / open items
- Widening risk: a unit entry silently grows with membership. Mitigation: default `includeChildren=false`, approval on add, protected layer snapshots. Non-protected fields do follow live membership by design.
- Performance: one dict lookup per (user, rule) after warm cache; closure query only on cache miss.
- Still needs user decision (carried from T64 §9.9): whether unit keys may be exposed in outputs (`internal_cols.py`) -- not required by this spec; recommended no.
