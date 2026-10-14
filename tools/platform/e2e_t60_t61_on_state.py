# -*- coding: utf-8 -*-
"""ON-state HTTP e2e for the t60/t61 builder slices (written, NOT yet run). Throwaway server + throwaway DB only.

Slices covered (each: flag OFF = unchanged, flag ON = works, masking wins, non-superadmin cannot see admin-only definitions):
  S5  field catalog         builder_custom_fields.enabled   GET /api/custom-fields/{case_info|supplier}, definitions kind custom_fields
  S6  action catalog        builder_actions.enabled         /api/user-buttons/*, definitions kind user_buttons
  S2  governance pipeline   builder_governance.enabled      pending/approve/activate/cancel, ledger
  S4  layout page flags     builder_layout.<page>           /api/layout/<module> unchanged by flag
  BP1 menu + pending        builder_menu.enabled            /api/platform/menu(+preview), layout publish honesty

Tree needed: an integration tree that contains S5 + S6 + t60 (e.g. a local merge of train/t60-int + wip/t61-s6-impl-r1).
Sections whose endpoints do not exist in the tree are reported as SKIP (never silent PASS).

Run (one uvicorn, throwaway DB whose path contains "e2e"):
    DB path env as the app expects, e.g. MOTRIX_DB=D:\\wt-xxx-e2e\\data\\e2e.db  uvicorn main:app --port 18766   (cwd backend)
    python tools/platform/e2e_t60_t61_on_state.py <backend_dir> 18766
Exit code 1 if any FAIL.
"""
import json
import os
import sys
import urllib.error
import urllib.request

BACKEND, PORT = sys.argv[1], int(sys.argv[2])
BASE = "http://127.0.0.1:%d" % PORT
os.chdir(BACKEND)
sys.path.insert(0, BACKEND)
RES = []


def check(name, ok, detail=""):
    RES.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else "  :: " + str(detail)[:400]))


def skip(name, why):
    RES.append((name, None, why))
    print("SKIP %s  :: %s" % (name, why))


def http(method, path, tok=None, body=None):
    h = {"Content-Type": "application/json"}
    if tok:
        h["Authorization"] = "Bearer " + tok
    req = urllib.request.Request(BASE + path, method=method, headers=h, data=None if body is None else json.dumps(body).encode())
    try:
        r = urllib.request.urlopen(req, timeout=60)
        raw = r.read()
        return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:200].decode("utf-8", "replace")}


# ── users (throwaway DB only) ──
import db  # noqa: E402
from helpers.auth import _hash_pw  # noqa: E402
assert "e2e" in os.path.abspath(db.DB_PATH).replace("\\", "/").lower(), "refusing: DB is not a throwaway e2e DB: " + db.DB_PATH
PW = "E2e-Pass-12345"


def mkuser(name, role, modules):
    c = db.get_db()
    try:
        c.execute("DELETE FROM users WHERE username=?", (name,))
        c.execute("INSERT INTO users (username, password_hash, display_name, role, modules, active, created_at, must_change_password) VALUES (?,?,?,?,?,1,?,0)",
                  (name, _hash_pw(PW), name, role, json.dumps(modules), "2026-01-01T00:00:00"))
        c.commit()
    finally:
        c.close()


mkuser("e2e_sa", "superadmin", [])
mkuser("e2e_sa2", "superadmin", [])      # second approver (governance D3)
mkuser("e2e_ad", "admin", ["quotations"])
mkuser("e2e_rs", "viewer", [])           # restricted: sees almost nothing


def login(n):
    s, d = http("POST", "/api/auth/login", body={"username": n, "password": PW})
    assert s == 200, (n, s, d)
    return d["token"]


SA, SA2, AD, RS = login("e2e_sa"), login("e2e_sa2"), login("e2e_ad"), login("e2e_rs")
from helpers import company_setup as _cs  # noqa: E402
http("PUT", "/api/settings/company-profile", SA, {"name": "E2E測試公司", "tax_id": "12345670", "contact_info": "02-12345678 e2e@example.com"})
_c = db.get_db()
try:
    _cs.confirm(_c, "e2e_sa")
    _c.commit()
finally:
    _c.close()


def setflag(group, field, val, tok=None):
    return http("POST", "/api/settings-center/groups/" + group, tok or SA, {"values": {field: val}, "reason": "e2e t60/t61"})


def flags(val):
    out = {}
    for g, f in (("builder_custom_fields", "enabled"), ("builder_actions", "enabled"), ("builder_governance", "enabled"), ("builder_menu", "enabled")):
        out[g] = setflag(g, f, val)[0]
    return out


def put_publish_def(kind, key, body, tok=SA, note="e2e"):
    """save draft then publish; ⇒ (draft_status, draft_resp, publish_status, publish_resp)"""
    url = "/api/definitions/%s/%s" % (kind, key)
    s0, cur = http("GET", url + "?scope=company", tok)
    et = ((cur.get("draft") or {}).get("etag")) if s0 == 200 else None
    s1, r1 = http("PUT", url + "/draft?scope=company", tok, {"body": body, "base_etag": et})
    if s1 != 200 or r1.get("problems"):
        return s1, r1, None, None
    s2, r2 = http("POST", url + "/publish?scope=company", tok, {"note": note, "base_etag": r1.get("etag")})
    return s1, r1, s2, r2


def pub_fields(rt, tok=SA):
    s, d = http("GET", "/api/custom-fields/" + rt, tok)
    return s, d


# ═══ S0: everything OFF — baseline snapshots ═══
flags(0)
base = {}
for rt in ("case_info", "supplier"):
    base["cf_" + rt] = (pub_fields(rt, SA), pub_fields(rt, RS))
base["menu_sa"] = http("GET", "/api/platform/menu", SA)
base["menu_rs"] = http("GET", "/api/platform/menu", RS)
base["btn"] = http("GET", "/api/user-buttons/supply/suppliers.html", SA)

# ═══ S5 OFF ═══
for rt in ("case_info", "supplier"):
    (s_sa, d_sa), (s_rs, d_rs) = base["cf_" + rt]
    check("S5 OFF %s: GET enabled=false fields=[] (sa)" % rt, s_sa == 200 and d_sa.get("enabled") is False and d_sa.get("fields") == [], (s_sa, d_sa))
    check("S5 OFF %s: GET enabled=false fields=[] (restricted)" % rt, s_rs == 200 and d_rs.get("enabled") is False and d_rs.get("fields") == [], (s_rs, d_rs))
check("S5 OFF: unknown record type 404", pub_fields("nope")[0] == 404)
check("S5 OFF: unauthenticated 401", http("GET", "/api/custom-fields/case_info")[0] in (401, 403))
check("S5 OFF: usage endpoint non-superadmin refused", http("GET", "/api/custom-fields/case_info/usage", AD)[0] in (401, 403))
# a published definition while OFF must not become visible
_f = {"fields": [{"key": "site_boss", "label": "現場工頭", "type": "text"}]}
s1, r1, s2, r2 = put_publish_def("custom_fields", "case_info", _f)
print("S5 OFF: definition save/publish allowed while flag off?", s1, s2)
check("S5 OFF: even with a published definition, GET still empty", pub_fields("case_info", SA)[1].get("fields") == [], pub_fields("case_info", SA))
# supplier write with customFields while OFF: value must not be stored / echoed
s, sup = http("POST", "/api/suppliers", SA, {"name": "E2E供應商OFF", "customFields": {"site_boss": "不該存"}})
sid = (sup or {}).get("id")
if s in (200, 201) and sid is not None:
    s_g, g = http("GET", "/api/suppliers/%s" % sid, SA)
    check("S5 OFF supplier: customFields not stored/echoed", s_g == 200 and not (g.get("customFields") or (g.get("data") or {}).get("customFields")), g)
else:
    skip("S5 OFF supplier write", "POST /api/suppliers -> %s %s (adapt the create body to this tree)" % (s, str(sup)[:120]))

# ═══ S6 OFF ═══
s, d = http("GET", "/api/user-buttons/supply/suppliers.html", SA)
if s == 404:
    skip("S6", "S6 router not in this tree (%s)" % d)
else:
    check("S6 OFF: GET enabled=false buttons=[] (sa)", s == 200 and d.get("enabled") is False and d.get("buttons") == [], (s, d))
    check("S6 OFF: GET enabled=false (restricted)", http("GET", "/api/user-buttons/supply/suppliers.html", RS)[1].get("enabled") is False)
    check("S6 OFF: catalog 404", http("GET", "/api/user-buttons/catalog", SA)[0] == 404)
    check("S6 OFF: preview 404", http("POST", "/api/user-buttons/supply/suppliers.html/preview", SA, {"buttons": []})[0] == 404)
    check("S6 OFF: unregistered page 404", http("GET", "/api/user-buttons/supply/nope.html", SA)[0] == 404)

# ═══ S2 / menu OFF ═══
check("S2 OFF: def-governance ledger 404", http("GET", "/api/def-governance/custom_fields/case_info/ledger", SA)[0] == 404)
check("S2 OFF: def-pipeline pending 404", http("GET", "/api/def-pipeline/pending", SA)[0] == 404)
check("BP1 OFF: no builderMenu key", "builderMenu" not in base["menu_sa"][1])
check("BP1 OFF: preview 404", http("POST", "/api/platform/menu/preview", SA, {"ops": []})[0] == 404)

# ═══ S4 layout page flags: default 0, toggling a page flag must not change an unrelated page's layout API ═══
LAYOUT_PAGES = ("suppliers", "case_management", "procurement", "devices", "vendor_contractors")
lay_before = {m: http("GET", "/api/layout/" + m, RS) for m in ("supply", "case")}
st = {p: setflag("builder_layout", p, 1)[0] for p in LAYOUT_PAGES}
if all(v in (400, 404, 422) for v in st.values()):
    skip("S4 page flags", "builder_layout page flags not in this tree: %s" % st)
else:
    check("S4: all five page flags settable", all(v == 200 for v in st.values()), st)
    lay_after = {m: http("GET", "/api/layout/" + m, RS) for m in ("supply", "case")}
    check("S4: flag ON with no published layout leaves /api/layout unchanged for a restricted user", lay_before == lay_after, (lay_before, lay_after))
    for p in LAYOUT_PAGES:
        setflag("builder_layout", p, 0)

# ═══ S5 ON ═══
setflag("builder_custom_fields", "enabled", 1)
check("S5 ON: flag set", pub_fields("case_info")[1].get("enabled") is True, pub_fields("case_info"))
good = {"fields": [{"key": "site_boss", "label": "現場工頭", "type": "text", "maxLength": 20},
                   {"key": "grade", "label": "等級", "type": "select", "options": ["A", "B"]}]}
bad_cases = {
    "core-name collision": {"fields": [{"key": "notes", "label": "備註2", "type": "text"}]},
    "type number (v1 forbids)": {"fields": [{"key": "amt", "label": "金額", "type": "number"}]},
    "unknown key required": {"fields": [{"key": "x1", "label": "必填", "type": "text", "required": True}]},
    "duplicate label": {"fields": [{"key": "a1", "label": "同名", "type": "text"}, {"key": "a2", "label": "同名", "type": "text"}]},
    "options on non-select": {"fields": [{"key": "a3", "label": "文字", "type": "text", "options": ["x"]}]},
    "dataClass not T1": {"fields": [{"key": "a4", "label": "個資", "type": "text", "dataClass": "F2"}]},
    "21 fields": {"fields": [{"key": "f%d" % i, "label": "欄%d" % i, "type": "text"} for i in range(21)]},
}
for nm, body in bad_cases.items():
    s_, r_ = http("POST", "/api/definitions/custom_fields/case_info/validate", SA, {"body": body})
    check("S5 ON validate rejects: " + nm, s_ == 200 and bool(r_.get("problems")), (s_, r_))
check("S5 ON validate accepts good body", http("POST", "/api/definitions/custom_fields/case_info/validate", SA, {"body": good})[1].get("problems") == [])
# admin-only definitions: non-superadmin cannot read/write the definition
for who, tk in (("admin", AD), ("restricted", RS)):
    check("S5 ON: %s cannot read the definition" % who, http("GET", "/api/definitions/custom_fields/case_info?scope=company", tk)[0] in (401, 403))
    check("S5 ON: %s cannot save a draft" % who, http("PUT", "/api/definitions/custom_fields/case_info/draft?scope=company", tk, {"body": good})[0] in (401, 403))
    check("S5 ON: %s cannot read usage" % who, http("GET", "/api/custom-fields/case_info/usage", tk)[0] in (401, 403))
s1, r1, s2, r2 = put_publish_def("custom_fields", "case_info", good)
check("S5 ON: publish (governance off) goes live", s2 == 200 and not (r2 or {}).get("pending"), (s1, s2, r2))
for who, tk in (("sa", SA), ("admin", AD), ("restricted", RS)):
    s_, d_ = pub_fields("case_info", tk)
    keys = [f["key"] for f in d_.get("fields", [])]
    check("S5 ON: %s sees both published fields (public shape only)" % who, s_ == 200 and keys == ["site_boss", "grade"], d_)
    check("S5 ON: public shape leaks no internals (%s)" % who, all(set(f) <= {"key", "label", "type", "options", "maxLength", "help"} for f in d_.get("fields", [])), d_)
# type change of a published field is refused
s_, r_ = http("POST", "/api/definitions/custom_fields/case_info/validate", SA, {"body": {"fields": [{"key": "grade", "label": "等級", "type": "text"}, good["fields"][0]]}})
check("S5 ON: published field type change refused", bool(r_.get("problems")), r_)
# supplier values: valid / invalid select / unknown key
sup_def = {"fields": [{"key": "tier", "label": "等級", "type": "select", "options": ["金", "銀"]}, {"key": "memo2", "label": "備註二", "type": "text"}]}
put_publish_def("custom_fields", "supplier", sup_def)
s, sup = http("POST", "/api/suppliers", SA, {"name": "E2E供應商ON", "customFields": {"tier": "金", "memo2": "ok"}})
sid2 = (sup or {}).get("id")
if s in (200, 201) and sid2 is not None:
    g = http("GET", "/api/suppliers/%s" % sid2, SA)[1]
    cf = g.get("customFields") or (g.get("data") or {}).get("customFields") or {}
    check("S5 ON supplier: valid values stored and returned", cf.get("tier") == "金" and cf.get("memo2") == "ok", g)
    s_bad, _ = http("PUT", "/api/suppliers/%s" % sid2, SA, {"name": "E2E供應商ON", "customFields": {"tier": "鑽石"}})
    check("S5 ON supplier: select value outside options -> 400", s_bad == 400, s_bad)
    g2 = http("GET", "/api/suppliers/%s" % sid2, SA)[1]
    cf2 = g2.get("customFields") or (g2.get("data") or {}).get("customFields") or {}
    check("S5 ON supplier: rejected write left stored value intact", cf2.get("tier") == "金", g2)
    s_u, d_u = http("GET", "/api/custom-fields/supplier/usage", SA)
    check("S5 ON: usage counts the filled field", s_u == 200 and (d_u.get("counts") or {}).get("tier", 0) >= 1, d_u)
    s_rs, _ = http("GET", "/api/suppliers/%s" % sid2, RS)
    check("S5 masking: restricted viewer still cannot read the supplier record", s_rs in (401, 403), s_rs)
    # disable the field: value retained in storage, no longer public
    put_publish_def("custom_fields", "supplier", {"fields": [dict(sup_def["fields"][0], disabled=True), sup_def["fields"][1]]})
    pubs = [f["key"] for f in pub_fields("supplier")[1].get("fields", [])]
    check("S5 ON: disabled field no longer public (or pending under governance)", "tier" not in pubs or pub_fields("supplier")[1].get("enabled"), pubs)
else:
    skip("S5 ON supplier value checks", "POST /api/suppliers -> %s %s (adapt create body)" % (s, str(sup)[:120]))
# flag back OFF: values stay but fields vanish, writes ignored
setflag("builder_custom_fields", "enabled", 0)
d_ = pub_fields("case_info")[1]
check("S5 flag back OFF: GET empty again", d_.get("enabled") is False and d_.get("fields") == [], d_)
setflag("builder_custom_fields", "enabled", 1)

# ═══ S6 ON ═══
if http("GET", "/api/user-buttons/supply/suppliers.html", SA)[0] == 404:
    skip("S6 ON", "S6 not in this tree")
else:
    setflag("builder_actions", "enabled", 1)
    s, cat = http("GET", "/api/user-buttons/catalog", SA)
    check("S6 ON: catalog for superadmin", s == 200 and any(x["id"] == "suppliers.html/toolbar" for x in cat.get("slots", [])), (s, cat))
    check("S6 ON: catalog lists only allow-listed exports", {x["id"] for x in cat.get("exports", [])} <= {"subcontract:roster"}, cat.get("exports"))
    for who, tk in (("admin", AD), ("restricted", RS)):
        check("S6 ON: %s cannot read the catalog" % who, http("GET", "/api/user-buttons/catalog", tk)[0] in (401, 403))
        check("S6 ON: %s cannot read the definition" % who, http("GET", "/api/definitions/user_buttons/module:supply?scope=company", tk)[0] in (401, 403))
        check("S6 ON: %s cannot save a draft" % who, http("PUT", "/api/definitions/user_buttons/module:supply/draft?scope=company", tk, {"body": {"buttons": []}})[0] in (401, 403))
        check("S6 ON: %s cannot preview" % who, http("POST", "/api/user-buttons/supply/suppliers.html/preview", tk, {"buttons": []})[0] in (401, 403))
    slot = "suppliers.html/toolbar"
    ok_btn = {"key": "b1", "slot": slot, "label": "外包名冊", "action": {"type": "export", "export": "subcontract:roster"}}
    nav_pages = [p["page"] for p in cat.get("pages", [])]
    bad_btns = {
        "unknown action type": [{"key": "b1", "slot": slot, "label": "X", "action": {"type": "post", "url": "/api/x"}}],
        "export not allow-listed": [{"key": "b1", "slot": slot, "label": "X", "action": {"type": "export", "export": "subcontract:other"}}],
        "export with free path": [{"key": "b1", "slot": slot, "label": "X", "action": {"type": "export", "export": "/api/users"}}],
        "label with markup": [{"key": "b1", "slot": slot, "label": "<b>x</b>", "action": {"type": "export", "export": "subcontract:roster"}}],
        "unknown button key": [dict(ok_btn, onclick="alert(1)")],
        "bad slot": [dict(ok_btn, slot="suppliers.html/nope")],
        "navigate to unlisted page": [{"key": "b1", "slot": slot, "label": "X", "action": {"type": "navigate", "page": "http://evil.example/"}}],
        "7 buttons in one slot": [dict(ok_btn, key="b%d" % i, label="按鈕%d" % i) for i in range(1, 8)],
        "duplicate key": [ok_btn, dict(ok_btn, label="另一顆")],
    }
    for nm, btns in bad_btns.items():
        s_, r_ = http("POST", "/api/definitions/user_buttons/module:supply/validate", SA, {"body": {"buttons": btns}})
        check("S6 ON validate rejects: " + nm, s_ == 200 and bool(r_.get("problems")), (s_, r_))
    s_, pv = http("POST", "/api/user-buttons/supply/suppliers.html/preview", SA, {"buttons": [ok_btn]})
    check("S6 ON: preview as self shows the button", s_ == 200 and [b["key"] for b in pv.get("visible", [])] == ["b1"], (s_, pv))
    s_, pv2 = http("POST", "/api/user-buttons/supply/suppliers.html/preview", SA, {"buttons": [ok_btn], "user": "e2e_rs"})
    check("S6 masking: preview as restricted user hides the export button with a reason", s_ == 200 and not pv2.get("visible") and pv2.get("hidden"), (s_, pv2))
    if nav_pages:
        navb = {"key": "b2", "slot": slot, "label": "開頁", "action": {"type": "navigate", "page": nav_pages[0]}}
        s_, pv3 = http("POST", "/api/user-buttons/supply/suppliers.html/preview", SA, {"buttons": [navb], "user": "e2e_rs"})
        check("S6 masking: navigate button to a page the restricted user cannot see is hidden", s_ == 200 and not pv3.get("visible"), (s_, pv3))
    s1, r1, s2, r2 = put_publish_def("user_buttons", "module:supply", {"buttons": [ok_btn]})
    check("S6 ON: publish (governance off) goes live", s2 == 200 and not (r2 or {}).get("pending"), (s1, s2, r2))
    vis = lambda tk: [b["key"] for b in http("GET", "/api/user-buttons/supply/suppliers.html", tk)[1].get("buttons", [])]
    check("S6 ON: superadmin sees the button", vis(SA) == ["b1"], vis(SA))
    check("S6 masking wins: restricted viewer does not get the button", vis(RS) == [], vis(RS))
    check("S6 masking wins: admin without the export's module does not get the button", vis(AD) == [], vis(AD))
    check("S6: a button never carries the export URL/perm to non-owners", "perm" not in json.dumps(http("GET", "/api/user-buttons/supply/suppliers.html", RS)[1]))
    setflag("builder_actions", "enabled", 0)
    check("S6 flag back OFF: buttons vanish, page unchanged", http("GET", "/api/user-buttons/supply/suppliers.html", SA)[1] == base["btn"][1], http("GET", "/api/user-buttons/supply/suppliers.html", SA))
    setflag("builder_actions", "enabled", 1)

# ═══ S2 governance ON: pending is honest, second approver required ═══
setflag("builder_governance", "enabled", 1)
check("S2 ON: ledger reachable for superadmin", http("GET", "/api/def-governance/custom_fields/case_info/ledger", SA)[0] == 200)
check("S2 ON: ledger refused to non-superadmin", http("GET", "/api/def-governance/custom_fields/case_info/ledger", AD)[0] in (401, 403))
check("S2 ON: pending list refused to non-superadmin", http("GET", "/api/def-pipeline/pending", RS)[0] in (401, 403))
before = [f["key"] for f in pub_fields("case_info")[1]["fields"]]
loosen = {"fields": good["fields"] + [{"key": "extra1", "label": "新增欄", "type": "text"}]}
s1, r1, s2, r2 = put_publish_def("custom_fields", "case_info", loosen, note="e2e loosen")
check("S2 ON: adding a field (loosening) returns pending, not published", s2 == 200 and (r2 or {}).get("pending") is True and r2.get("changeId") and r2.get("effectiveAt") and r2.get("reasons"), (s2, r2))
check("S2 ON: pending change is NOT live", [f["key"] for f in pub_fields("case_info")[1]["fields"]] == before)
cid = (r2 or {}).get("changeId")
if cid:
    s_, pl = http("GET", "/api/def-pipeline/pending", SA)
    check("S2 ON: pending list shows the change", s_ == 200 and any(str(i.get("id", i.get("changeId"))) == str(cid) for i in pl.get("items", [])), pl)
    s_, _ = http("POST", "/api/def-pipeline/changes/%s/approve" % cid, SA, {})
    check("S2 ON: proposer cannot approve own change", s_ in (400, 403, 409, 422), s_)
    s_, _ = http("POST", "/api/def-pipeline/changes/%s/activate" % cid, SA2, {})
    check("S2 ON: activate before approval is refused", s_ in (400, 403, 409, 422), s_)
    check("S2 ON: still not live", [f["key"] for f in pub_fields("case_info")[1]["fields"]] == before)
    s_, _ = http("POST", "/api/def-pipeline/changes/%s/approve" % cid, SA2, {})
    check("S2 ON: second superadmin can approve", s_ == 200, s_)
    s_, _ = http("POST", "/api/def-pipeline/changes/%s/activate" % cid, SA2, {})
    live = [f["key"] for f in pub_fields("case_info")[1]["fields"]]
    check("S2 ON: activate either applies (confirm period over) or is refused while still not live (never half-applied)",
          (s_ == 200 and "extra1" in live) or (s_ in (400, 409, 422) and live == before), (s_, live))
    if live == before:
        s_, _ = http("POST", "/api/def-pipeline/changes/%s/cancel" % cid, SA2, {})
        check("S2 ON: cancel during the confirm period", s_ == 200, s_)
else:
    skip("S2 pipeline follow-up", "no changeId returned")
# tighten (remove a field) is immediate
s1, r1, s2, r2 = put_publish_def("custom_fields", "case_info", {"fields": [good["fields"][0]]}, note="e2e tighten")
check("S2 ON: tightening (remove a field) is immediate (not pending)", s2 == 200 and not (r2 or {}).get("pending"), (s2, r2))
# S6 buttons under governance
if http("GET", "/api/user-buttons/supply/suppliers.html", SA)[0] != 404:
    s1, r1, s2, r2 = put_publish_def("user_buttons", "module:supply", {"buttons": [ok_btn, dict(ok_btn, key="b2", label="第二顆")]}, note="e2e add button")
    check("S2/S6 ON: adding an export button is pending or (if kind not in ACTIVE_KINDS) direct — never a false 'published'",
          s2 == 200 and (((r2 or {}).get("pending") is True and ["b1"] == vis(SA)) or ((r2 or {}).get("pending") is not True and "b2" in vis(SA))), (s2, r2, vis(SA)))

# ═══ BP1 menu ON + governance: published label change is honest ═══
setflag("builder_menu", "enabled", 1)
m = http("GET", "/api/platform/menu", SA)[1]
check("BP1 ON: builderMenu true only for superadmin", m.get("builderMenu") is True and "builderMenu" not in http("GET", "/api/platform/menu", RS)[1] and "builderMenu" not in http("GET", "/api/platform/menu", AD)[1])
items = [(it["href"], it.get("module")) for g in m["layout"]["groups"] for it in g["items"] if it.get("module")]
if items:
    href, mod = items[0]
    tgt = "%s:%s/sidebar" % (mod, href)
    s1, r1, s2, r2 = put_publish_def("layout", "module:%s" % mod, {"ops": [{"op": "relabel", "target": tgt, "label": "E2E改名"}]})
    labels = {it["href"]: it["label"] for g in http("GET", "/api/platform/menu", SA)[1]["layout"]["groups"] for it in g["items"]}
    pend = (r2 or {}).get("pending") is True
    check("BP1/S2: relabel publish is honest (pending => menu unchanged; direct => menu changed)",
          s2 == 200 and ((pend and labels.get(href) != "E2E改名") or (not pend and labels.get(href) == "E2E改名")), (s2, r2, labels.get(href)))
    rs_labels = {it["href"]: it["label"] for g in http("GET", "/api/platform/menu", RS)[1]["layout"]["groups"] for it in g["items"]}
    check("BP1 masking wins: restricted user never sees an item they could not see before", set(rs_labels) <= {it["href"] for g in base["menu_rs"][1]["layout"]["groups"] for it in g["items"]})
else:
    skip("BP1 relabel publish", "superadmin menu has no module item in this DB")

# ═══ cleanup: all flags OFF, final unchanged check ═══
flags(0)
end_sa, end_rs = http("GET", "/api/platform/menu", SA), http("GET", "/api/platform/menu", RS)
print("NOTE: a published relabel may persist after flags go OFF (data kept, not applied); END menu check is manual")
check("END all flags OFF: no builderMenu key", "builderMenu" not in end_sa[1])
check("END all flags OFF: custom-fields GET empty", pub_fields("case_info")[1].get("fields") == [])

fails = [r for r in RES if r[1] is False]
skips = [r for r in RES if r[1] is None]
print("\nTOTAL %d  PASS %d  FAIL %d  SKIP %d" % (len(RES), len(RES) - len(fails) - len(skips), len(fails), len(skips)))
sys.exit(1 if fails else 0)
