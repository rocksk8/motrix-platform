# T66: Per-user list preferences (columns, sort, page size) — design

> Date 2026-10-16. Base `origin/platform` 5112b93f3. Branch `wip/t66-list-prefs-design-r1`. **Design only: no code, no tests run.**
> User ruling: each user may set list columns, default sort, default page size and rows-per-page, **inside a company-allowed range**. Amount columns may only be **hidden / reordered, never exposed**. Framework-first: no hardcoded lists/columns/ranges; modules register, admins configure.
> Related: `T64-F7-FIELD-POLICY-DESIGN.md` (§2 catalog, §3 policy, §11 protected tier), `T63-EXPORT-COLUMNS-DESIGN.md` (same "can only subtract" pattern), `T61-S6-ACTION-CATALOG-DESIGN.md` (registry+kind pattern), `helpers/settings_registry.py`, `core/definitions.py`.

## Revision 2026-10-16 (L2) — supersedes §1.3, §2 and §3 where they conflict

Found while implementing L2: **a per-user list-preference feature already exists** and is used in production.
- Table `user_list_prefs(username, list_key, sort_mode, sort_dir, custom_order, updated_at)` (`db.py::_m056_user_list_prefs`) and routes `GET/PUT /api/list-prefs/{list_key}` (`routers/list_prefs.py`), consumed by `list-sort.js`, system-hub, dev-crm and the P9 layout engine.
- The layout engine (`frontend/static/layout-runtime.js`, `custom-layout.js`) already implements the **personal column layer**: key `layout-cols.<module>.<list>`, `sortMode='columns'`, `customOrder` = column keys in order with a `-` prefix for hidden; upper layers (company/role `layout` kind) bound it, core columns can't be hidden.

Decision (PM, 2026-10-16): **one source of truth, no parallel column layer.**
1. The layout engine + `user_list_prefs` stay the owner of personal column hide/reorder and sort. T66 does **not** copy them.
2. T66 adds only: (a) **per-user page size** (`user_list_view_prefs`, one row per user+list, `prefs_json={"v":1,"pageSize":N}`); (b) the **company policy** `list_pref_policy` as a filter/clamp applied *on top of* the layout-engine output; (c) the **F7 money-column rules** (hide/reorder only, never added back; sort only on visible, allowed columns).
3. Names (no collision): table `user_list_view_prefs` (core migration, registered `NEXT`; has `owner_unit_id INTEGER NOT NULL DEFAULT 1` to satisfy the unit-scope guard); routes `/api/list-views` and `/api/list-views/{list_id}` (GET/PUT/DELETE); helper `helpers/list_view_prefs.py`; router `routers/list_view_prefs.py`. Old route/table untouched.
4. What the API returns is therefore the **constraint set**, not a column preference: `columns[]` (only columns that pass F7 ∩ policy; `money`, `pinned`, `defaultVisible`, `canShow`), `sort{allowed, default}`, `pageSize{value, source, options}`, `custom`, `etag`. Money columns that are not visible by default are **not listed at all** (never exposed, existence not confirmed). The client (or a later server-side caller) applies `clamp_columns()` / `clamp_sort()` to what the layout engine produced: unlisted columns dropped, pinned/required forced visible, `canShow=false` columns forced hidden, sort restricted to allowed+visible columns.
5. `PUT /api/list-views/{list_id}` body is `{"pageSize": N}` only (unknown keys 422); `If-Match` etag; 403 when the company policy disallows personal settings; flag off ⇒ 404 on all four routes. `DELETE` resets to the company default.

## Migration question (not now): fold the old table in later?
Options for a later slice, **no decision requested now**:
- **A. Keep two tables forever.** `user_list_prefs` = presentation (sort/columns, opaque key); `user_list_view_prefs` = bounded, policy-checked settings. Cost: two places to look; benefit: zero migration risk.
- **B. Fold column/sort into T66.** One-time migration of `layout-cols.*` rows (`customOrder` with `-` prefix) into a typed `prefs_json` (`hidden/order/sort`), layout engine reads via `/api/list-views`, old route kept as a read-only shim for one release. Cost: touches P9 runtime + 4 frontend files + a data migration; benefit: server-side validation of personal columns (today the client alone decides what is hidden; harmless for money because masking is server-side, but policy `pinned/allowed` is only enforced by `clamp_*`).
- **C. Fold T66 into the old table** (add `page_size` column). Rejected: opaque `list_key` has no list catalog, no etag, and mixes unrelated keys (system-hub recents).
Recommendation: A now, revisit B only if a list needs server-side column enforcement (e.g. a policy `pinned` column that must not be hideable via a hand-crafted request).

## 0. Summary

1. **Three layers, each reusing an existing mechanism; one new table only for the per-user values.**
   - *Catalog* (what can be configured): modules register lists via `register_section("listCatalog", owner, fn)` (same as `fieldCatalog`). No hardcode in core.
   - *Company policy* (allowed range): new definition **kind `list_pref_policy`**, key = `<list_id>` or `*` (global default), scope `company` (+ optional `role:<r>` via existing `resolve()`). Gets drafts/versions/diff/restore/loosening-approval for free.
   - *User values*: table `user_list_prefs` (not a definition — see §1.3 for why).
2. **Server computes the effective view; client never decides.** `effective(user, list)` = F7 visibility ∧ company allowed ∧ user choice, re-resolved on every read. Stored prefs hold only ids/numbers, never grants, so a policy tightening takes effect immediately and a loosening never retro-exposes anything.
3. **Money columns are subtract-only.** A user pref can hide or reorder them; it can never add one that the user's effective default does not already show. Sorting by a money column requires it to be visible.
4. **Flag `list_prefs.enabled` (settings center), default OFF ⇒ no new route reachable, list endpoints byte-identical.** Prefs affect presentation + the *default* `limit/sort` the frontend sends; list endpoints keep their own hard caps.

## 1. Storage model

### 1.1 Catalog entry (code, registered by the owning module)
```
listCatalog = { "<list_id>": {                  # e.g. "case:case-list", "supply:suppliers"
   "label": "案件清單", "owner": "case",
   "columns": [ {"id":"customer","label":"客戶","catalogId":null,"sortable":true,"required":false},
                {"id":"total","label":"含稅總額","catalogId":"quotation.total","sortable":true,"required":false}, ... ],
   "defaults": {"columns":["customer","status",...], "sort":{"col":"updated","dir":"desc"}, "pageSize":50},
   "pageSizeCeiling": 200,        # code-level hard cap; admin cannot exceed (matches endpoint limit cap)
   "pageSizeMenu": [20,50,100,200]
}}
```
- `catalogId` (nullable) links the column to the F7 field catalog (`helpers/field_catalog.py`). **A column with a `catalogId` whose `moneyClass != none` is a money column** — derived, not re-declared (single source; same rule as T64 F7 §2 "derive, don't copy").
- `required: true` = cannot be hidden (e.g. the document number/primary link).
- Validator at registration/`build()`: ids unique, `catalogId` exists in field catalog, defaults ⊆ columns, `pageSizeCeiling` ≤ 500, sort col sortable. Bad entry ⇒ list not offered (fail closed), logged.
- Registered from module code, not `module.json`, in v1 (avoids a core validator change); promote to `module.json` later like `button_slots`.

### 1.2 Company policy (definition kind `list_pref_policy`, via `definitions.register_kind`)
```
{ "version":1,
  "allowUserPrefs": true,                     # master switch for this list ("*" = default for all lists)
  "columns": { "allowed": ["customer","status","total",...],   # subset of catalog; absent ⇒ all catalog columns
               "pinned":  ["case_no"],                          # always visible, order fixed first (can't hide)
               "defaultHidden": ["internal_note"] },            # hidden unless user shows it (non-money only)
  "sort":    { "allowed": ["updated","customer"], "default": {"col":"updated","dir":"desc"} },
  "pageSize":{ "allowed": [20,50,100], "default": 50 }          # ⊆ pageSizeMenu, max ≤ pageSizeCeiling
}
```
Resolution: `definitions.resolve(conn,"list_pref_policy",list_id,role)` → falls back to `*` → falls back to catalog defaults (**no row = today's behavior**, nothing written on deploy). Validator rejects: unknown ids; `allowed` missing a `pinned`/`required` column; default outside allowed; pageSize > ceiling; **any money column in `defaultHidden` is fine, but a policy can never *add* a money column the F7 layer hides** (policy is intersected with F7, never unions).
- Loosening (more columns, larger page sizes, `allowUserPrefs` false→true) goes through the existing definition pipeline (second top-admin approval + confirm period, T54). Tightening is immediate. Comparator `_cmp_list_pref_policy` follows `_cmp_custom_fields` pattern (T61 S5 §1).
- Setting-center group `list_prefs` (settings_registry) holds only the flag and one number: `max_saved_lists_per_user` (default 200, clamp), both `risk=ops`. The *range* lives in the policy kind, not in settings (ranges are structured data, versioning/diff wanted).

### 1.3 Per-user values: new table, not a definition

> **Superseded by the L2 revision above**: table name is `user_list_view_prefs`; it stores only `pageSize` (columns/sort stay in `user_list_prefs`). The reasons for not using definitions scope `user:*` below still hold.
`definitions` scope regex is `company|role:*`; adding `user:*` would create a version row + validator + submission machinery **per click** for thousands of tiny, self-service, non-governed writes, and `list_definitions` would scan them. So:
```
CREATE TABLE IF NOT EXISTS user_list_prefs (
  username TEXT NOT NULL, list_id TEXT NOT NULL,
  prefs_json TEXT NOT NULL,            -- {"v":1,"hidden":["a"],"shown":["b"],"order":["c","a"],"sort":{"col":..,"dir":..},"pageSize":50}
  updated_at TEXT NOT NULL, PRIMARY KEY (username, list_id));
```
- Additive `CREATE TABLE IF NOT EXISTS` migration (core/migrations pattern), no change to existing tables; absent row = defaults. Size cap 4 KB/row; `shown` only meaningful for non-money columns.
- **Reuse of the definition layer is by contract, not storage:** same `kind` registration, same validator function (`validate_prefs(body, policy, catalog, viewer)`), same `etag` idea for optimistic concurrency (`If-Match` = sha256[:16] of prefs_json, `etag_of`) to avoid two-tab clobbering.
- Not in the recycle bin / not a business record; included in user-deletion cleanup and in the account-export for the user (privacy).

## 2. Effective-view algorithm (single function `list_prefs.effective(conn, user, list_id)`; never raises)

> **Superseded in part**: the column order/hide/show and sort are computed by the layout engine; this function becomes `constraints()` + `clamp_columns()/clamp_sort()` (see revision). Order of precedence is unchanged: F7 ∩ company policy ∩ personal choice.

```
cols  = catalog.columns
cols  = [c for c in cols if f7_visible(c.catalogId, user) or c.catalogId is None]   # ceiling ∧ F7 policy — authority
cols  = [c for c in cols if c.id in policy.allowed]
base  = policy default-visible set (∩ cols)                                          # "today" if no policy
visible = base
  − user.hidden                                                                      # any column, except pinned/required
  + (user.shown ∩ cols) restricted to NON-money columns                              # money can't be added by users
order = user.order filtered to visible, then remaining in policy/catalog order; pinned first
sort  = user.sort if (col ∈ visible ∩ sortable ∩ policy.sort.allowed) else policy default (if visible) else catalog default
pageSize = user.pageSize if ∈ policy.allowed else policy.default (≤ ceiling)
```
Rules: unknown ids dropped silently; new columns shipped later appear per policy default (not auto-shown if `defaultHidden`); any exception ⇒ return catalog/policy defaults (flag-off shape). Response includes `source` per setting (`user|policy|default`) and `clamped:[...]` so UI can say "your setting was adjusted by company policy".

## 3. API (new router `routers/list_prefs.py`, all behind flag; auth = logged-in user, own prefs only)

> **Superseded by the L2 revision above**: routes are `/api/list-views[/{list_id}]`; PUT stores only `pageSize`; GET returns constraints. The admin read and `max_saved_lists_per_user` are dropped (nothing unbounded to cap).
| Method + path | Purpose |
|---|---|
| `GET /api/list-prefs/{list_id}` | Effective view + the *choosable* range (allowed columns with `locked/money/pinned` marks, pageSize menu, sortable cols) + `etag`. Body contains **no column the viewer cannot see** (F7-filtered before serialization). |
| `PUT /api/list-prefs/{list_id}` | Save own prefs. Body `{hidden,shown,order,sort,pageSize}` + `If-Match`. Server validates against current policy+F7; **rejects (422 with reasons) rather than silently clamps** on write: e.g. `shown` containing a money column, sort on hidden column, pageSize not in menu. 409 on etag mismatch. |
| `DELETE /api/list-prefs/{list_id}` | Reset to company default. |
| `GET /api/list-prefs` | The viewer's lists with `has_custom` (for a "reset all" screen). |
| Admin: `GET /api/list-prefs-admin/catalog` | Catalog + current policy per list (settings-center screen reads this; writes go through existing `/api/definitions/list_pref_policy/{list_id}` draft/publish pipeline — **no new write route**). Also `GET …/usage` aggregate counts only (how many users customized) — no per-user content. |

- Reads are cached per (user, list) 15 s like settings_registry; PUT invalidates. Policy publish invalidates all (TTL-bound for multiprocess).
- List endpoints (e.g. `case_list` `limit/offset`, caps 200–500) are **unchanged**: frontend sends `limit=pageSize&sort=…` only if the endpoint already supports it; endpoints keep their server-side `min(limit, cap)` and re-check F7 on sort keys (see §4.3).
- Audit: `list_prefs.save/reset` as low-severity audit rows (user, list, diff keys); policy publish audited by definitions pipeline. No export logging needed (no data egress).

## 4. Permission interplay with F7 (field visibility)

1. **F7 is authority; prefs are a view-layer subset.** `f7_visible()` = `field_policy.visible(field_id, user)` (ceiling ∧ policy; ceiling is the existing backend capability such as `quote_money_visible`). S0 today (`field_catalog`, no policy) ⇒ use the registered `ceiling` function directly; when F7 S1+ lands, swap to `field_policy.visible` — one call site (`_f7_visible` in the new helper), so no rework.
2. **Money columns subtract-only** (user ruling): hide/reorder allowed; never in `shown`; never in the *choosable-to-add* list sent to the client; if the viewer's effective default does not include it, it does not appear at all (not even greyed — avoids confirming existence).
3. **Sort is a disclosure channel.** Sorting by cost/margin reveals ordering even if values are masked. Rule: sort col must be currently visible to the viewer; the *server list endpoints* that accept a `sort` param must check `f7_visible` for the sort field (integration point per endpoint, listed in L3). Where an endpoint sorts client-side, only visible columns are sortable by construction.
4. **Protected tier (F7 §11)**: protected columns are never in a user's choosable set unless granted by the governed grant; a user-hidden protected column stays hidden after grant (prefs persist, only subtract).
5. **Policy tightening/role change** takes effect on next read: stored `shown/order` entries that fail F7 are dropped in `effective()`; nothing to migrate. **Loosening never auto-exposes** a column to existing users with `hidden` entries — they keep their choice; columns newly allowed follow `defaultHidden`.
6. **Derived-family rule**: if cost is not visible, margin must not be either (F7 §3.3) — `effective()` applies F7's `derivedFrom` closure, so a user can't "show margin" to back out cost.
7. **Hide ≠ secure** (F7 §2 note): prefs never substitute for server-side masking; API payloads are unchanged by prefs (columns hidden by the user are still in the payload only if the viewer is allowed to see them).
8. **Export/print/PDF do not follow list prefs** (T63 export templates and output templates are governed separately); stated in the UI ("this only changes how this list looks").
9. **Org-unit dimension (F7 §12)**: not used in v1; `effective()` takes a `viewer` object so units can be added to F7 without touching prefs.

## 5. Company-level settings screen (settings center → "Lists"), top-admin only

> L2 note: the card edits `list_pref_policy` (column allowed/pinned/defaultHidden, sort, page sizes, allowUserPrefs) which now acts as a clamp on the layout-engine output; usage counts come from `user_list_view_prefs` (page size) only — column customizations live in `user_list_prefs` and are counted there if wanted.
Plain-language per-list card: "Which columns may people use? (checkbox list, money ones tagged 'amount — hide/reorder only')", "Page sizes people may pick", "Default sort", "Let people customize this list (on/off)". Preview: "N users currently customized; this change would reset M of them" (counts via `user_list_prefs`, no names). Writes through the definition draft→publish pipeline (loosening ⇒ second approver). Zero technical jargon (CORE-SPEC zero-tech-barrier).

## 6. Slices (each independently shippable; flag OFF = zero change)
| # | Slice | Content | Size |
|---|---|---|---|
| L0 | Catalog + validator | `helpers/list_catalog.py` (L1): `register_list`, `register_section("listCatalog")`, `build()` validation, money-derivation from field catalog; register **one** pilot list (suppliers list: already has layout slots, no money). No routes/tables. | 0.5 pd |
| L1 | Policy kind | `register_kind("list_pref_policy", validator, default)`, comparator for loosening, UNIT-INDEX entry, settings group `list_prefs` (flag + cap). Definition API reused. | 1 pd |
| L2 | Effective + user store | Migration `user_list_prefs`; `effective()`, `validate_prefs()`, `save/reset`; router + cache + audit; flag gate. | 1.5 pd |
| L3 | Sort/page integration | Per-endpoint: enforce `f7_visible` on `sort` param, clamp `limit` to policy ceiling where endpoint is server-paged. Start with case list + suppliers; others client-side. | 1 pd per list family |
| L4 | Frontend | Shared `list-prefs.js` (gear popover: show/hide checkboxes, drag order, sort, page size, "reset to company default"), wired via `data-list-id` attr on tables; pilot on suppliers. | 2 pd |
| L5 | Admin screen + rollout | Settings-center "Lists" cards, usage counts, register money lists (case list, quotations list) after L3 for each; docs (MODULE-GUIDE "how to register a list"). | 1.5 pd |
Order: L0 → L1 → L2 → L4(pilot) → L3 (money lists) → L5. Money-bearing lists must not be registered until L3 for that list is done (guarded by a test: a registered list with a money column requires an `sortGuard` declaration).

## 7. Tests (written with the slices; run only after the gate window)
- **L0**: catalog validation (bad `catalogId`, dup ids, default ⊄ columns, ceiling > 500 ⇒ rejected); money flag derived from field catalog (mutation: change moneyClass ⇒ flag follows, no second source); registered-list inventory matches golden file.
- **L1**: validator matrix (unknown id, pinned not allowed, default outside allowed, pageSize > ceiling); loosening comparator (add column / raise page size / enable ⇒ pending; remove ⇒ immediate); no-row ⇒ `resolve` returns None ⇒ defaults.
- **L2 (core safety)**: (a) user cannot `shown` a money column (PUT 422); (b) user with no `quote_money` ceiling never sees money column in GET body nor choosable list; (c) tightening policy after save ⇒ next GET drops the column, no error; (d) sort on hidden/forbidden column rejected on PUT and ignored on GET; (e) margin visible only if cost visible; (f) etag conflict 409; (g) own-prefs-only (user A cannot read/write B: path has no username param, test with forged body); (h) corrupt `prefs_json` / DB error ⇒ defaults, no 500; (i) flag OFF ⇒ routes 404 and list endpoint responses byte-identical to baseline (route inventory + response-keys baselines unchanged when OFF); (j) payload size cap.
- **L3**: per list: server rejects `sort=<money field>` for non-money viewers (negative control: a viewer with the ceiling is allowed — positive control, per scanner-positive-control rule); `limit` above policy ceiling clamped.
- **Property test**: for random (policy, F7 grants, prefs) triples, `effective(user)` ⊆ F7-visible set and money columns ⊆ base default set.
- **L4/L5**: UI button verification (gear, reset, drag order, save conflict), admin card writes via definitions API, usage counts reveal no usernames.

## 8. Risks / not doing
- Prefs are per `username`; renaming/merging users needs a migration hook (same as other per-user tables).
- Client-side paged lists: "page size" is presentation only; no data-volume protection claimed there.
- Not doing: per-role *user-visible* presets sharing, saved filter sets, mobile-specific layouts, per-user prefs for forms (layout engine P9 handles forms), org-unit scoping (waits on F7 §12).

## 9. Decisions for the user (defaults chosen; changeable as settings where possible)
1. Per-user values live in a **new table, not definitions** (rationale §1.3). Default: table. *Only non-setting decision.*
2. Server **rejects** invalid saves (422) instead of silently clamping. Default: reject (clamp only on read after policy tightening).
3. Pilot list: suppliers (no money). Default: yes; money lists follow only after L3.
4. Default `allowUserPrefs` for lists with **no** policy row: on (flag itself is OFF by default, so nothing changes until an admin turns the feature on). Setting-ified in policy `*`.

## Status and follow-ups (L3 revision, 2026-10-16, PM decisions)
- **Shipped = API-only slice.** L3 (per-endpoint sort/limit enforcement) and L4 (frontend) are **pending**; `clamp_columns` / `clamp_sort` have **no consumer yet**. Only `supply:suppliers` (no money column) is registered, so the "money list needs sortGuard" rule is not yet exercised.
- **Access rule (added):** a catalog entry may declare `modules` (module keys; same set as the list's data endpoint, suppliers = customer/procurement/inventory). `GET /api/list-views[/{id}]`, PUT and DELETE use `auth.user_has_module` (superadmin passes; others need one key). No `modules` declared => superadmin only (fail closed). No access: summary omits the list, routes return 403.
- **Deferred, not implemented (follow-ups):** (1) `max_saved_lists_per_user` cap - moot, one small row per user+list; (2) admin catalog/usage read (counts of users with a custom page size); (3) cleanup/export of `user_list_view_prefs` on user delete/rename (same hook as other per-user tables); (4) swap `_ceiling_ok` map for `field_policy.visible` when F7 S1 lands (TODO in code; no test pins the map).
- Tests added: no-module 403/empty, list without `modules` superadmin-only, concurrent PUT (one wins, one 409), `*` fallback and per-list override.
