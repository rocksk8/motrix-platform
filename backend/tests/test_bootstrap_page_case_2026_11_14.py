# -*- coding: utf-8 -*-
"""GET /api/bootstrap?page=case（T86 #10，2026-11-14）：案件管理頁首屏的 8 支小請求併進 bootstrap。

鐵則同 test_bootstrap_bundle：**不可以回傳比原端點更多的資料**。本檔守：
  - 每個頁面區段 == 單打原端點的回應；原端點對這個人拒絕（403…）的區段 ⇒ 不給、`errors` 記同一個狀態碼；
  - 沒帶 `page`／不認得的 `page` ⇒ 與今天逐位元相同（不多一個區段、不報錯）；
  - 本公司資料未設定（428 閘門）⇒ 頁面區段一個都不給、`errors` 記 428；
  - 每支被呼叫的處理函式，綁定固定參數後只剩 `authorization`（直接呼叫不會把 Query 物件當值傳進去）；
  - 前端：只有案件管理頁才多帶 `?page=case`、才登記這些路徑；JS 表與後端 `PAGE_SECTIONS` 逐字相同；
    各載入點都用 `(window.motrixBootFetch || fetch)` 且網址在表內；其他頁不受影響（網址不在表內 ⇒ 立刻真的 fetch）。
"""
import inspect
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from routers import bootstrap as B

ROLES = ("superadmin", "admin", "sales", "engineer", "viewer", "finance")
FRONT = Path(__file__).resolve().parents[2] / "frontend"
GUARD = FRONT / "static" / "auth-guard.js"
NODE = shutil.which("node")


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def world(client, make_user):
    hdr = {}
    for role in ROLES:
        u, pw = make_user(username="pc_" + role, role=role)
        hdr[role] = _login(client, u, pw)
    return hdr


def _page_sections():
    return B.PAGE_SECTIONS["case"]


def _orig_sections():
    """有原端點的頁面區段（衍生區段 financeView 沒有原端點，另有專門的測試）。"""
    return {n: p for n, p in _page_sections().items() if n not in B.DERIVED_SECTIONS}


# ── 後端：逐區段、逐角色 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ROLES)
def test_page_sections_equal_the_original_endpoints_or_carry_the_same_refusal(client, world, role):
    h = world[role]
    r = client.get("/api/bootstrap?page=case", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()
    for name, path in _orig_sections().items():
        orig = client.get(path, headers=h)
        if orig.status_code == 200:
            assert name in d, (role, name, d["errors"])
            assert d[name] == orig.json(), (role, name)
            assert name not in d["errors"], (role, name)
        else:                                               # 原端點拒絕 ⇒ bootstrap 不給資料、只記同一個狀態碼
            assert name not in d, (role, name)
            assert d["errors"].get(name) == orig.status_code, (role, name, orig.status_code, d["errors"])


def test_superadmin_gets_every_page_section_with_real_content(client, world):
    d = client.get("/api/bootstrap?page=case", headers=world["superadmin"]).json()
    assert d["errors"] == {}
    assert set(_page_sections()) <= set(d)
    assert "groups" in d["onepipeFlags"] and "onepipe" in d["onepipeFlags"]["groups"]
    assert d["financeView"] == {"financialView": True}
    assert set(d["builderGroups"]["groups"]) <= set(B.CASE_BUILDER_GROUPS)
    assert isinstance(d["usersSelectable"], list) and d["usersSelectable"]


def test_page_sections_follow_the_global_ones_in_a_fixed_order(client, world):
    d = client.get("/api/bootstrap?page=case", headers=world["superadmin"]).json()
    assert [k for k in d if k not in ("v", "errors")] == B.sections_for("superadmin", False, "case")
    assert B.sections_for("superadmin", False, "case") == list(B.ORIGINAL_PATH) + list(_page_sections())


@pytest.mark.parametrize("page", ("", "nope", "CASE", "case-management", "../x"))
def test_no_or_unknown_page_is_byte_identical_to_today(client, world, page):
    h = world["superadmin"]
    base = client.get("/api/bootstrap", headers=h).json()
    got = client.get("/api/bootstrap", params={"page": page}, headers=h)
    assert got.status_code == 200
    d = got.json()
    assert [k for k in d if k not in ("v", "errors")] == [k for k in base if k not in ("v", "errors")]
    assert not (set(d) & set(_page_sections()))
    assert d["errors"] == base["errors"] == {}


def test_page_sections_are_never_cached_and_need_login(client, world):
    assert client.get("/api/bootstrap?page=case").status_code == 401
    r = client.get("/api/bootstrap?page=case", headers=world["admin"])
    assert r.headers.get("cache-control") == "no-store"


def test_page_param_is_not_a_way_to_reach_any_other_handler(client, world):
    """頁面鍵只能挑 PAGE_SECTIONS 裡寫死的區段；任何字串都不會變成別的處理函式／路徑。"""
    assert set(B.PAGE_SECTIONS) == {"case"}
    assert B._page_handlers("nope") == {} and B._page_handlers(None) == {}
    assert set(B._page_handlers("case")) == set(_page_sections())
    assert B.DERIVED_SECTIONS == {"financeView"} and set(B.DERIVED_SECTIONS) <= set(_page_sections())


def test_every_page_handler_takes_only_authorization_after_binding():
    for name, fn in B._page_handlers("case").items():
        params = list(inspect.signature(fn).parameters)
        assert params == ["authorization"], (name, params)


def test_builder_groups_string_equals_what_the_case_page_asks_for():
    html = (FRONT / "pages" / "case-management.html").read_text(encoding="utf-8")
    m = re.search(r"MotrixPublicFlags\.read\(\[([^\]]+)\]", html)
    assert m, "找不到案件頁讀版面群組的呼叫"
    groups = re.findall(r"'([a-z_]+)'", m.group(1))
    assert tuple(groups) == B.CASE_BUILDER_GROUPS


# ── 閘門 ────────────────────────────────────────────────────────────────────────────

@pytest.mark.company_gate
@pytest.mark.parametrize("role", ("superadmin", "admin", "sales"))
def test_unconfigured_company_gives_no_page_section(client, make_user, role):
    u, pw = make_user(username="pcg_" + role, role=role)
    h = _login(client, u, pw)
    d = client.get("/api/bootstrap?page=case", headers=h).json()
    for name, path in _page_sections().items():
        assert name not in d, (role, name)
        assert d["errors"].get(name) == 428, (role, name)
        if name not in B.DERIVED_SECTIONS:
            assert client.get(path, headers=h).status_code == 428, (role, name)   # 前提：原端點本來就被擋
    assert {k for k in d if k not in ("v", "errors")} <= B.SETUP_GATE_OK


# ── 前端 ────────────────────────────────────────────────────────────────────────────

def _case_block():
    src = GUARD.read_text(encoding="utf-8")
    start = src.index("if (BOOT_PAGE === 'case') {")
    return src[start:src.index("\n  }\n", start)]


def test_js_case_table_matches_the_backend():
    block = _case_block()
    pairs = dict(re.findall(r"BOOT_SECTIONS\['(/api/[^']+)'\] = \['(\w+)', \d\]", block))
    want = {path: name for name, path in _orig_sections().items()}
    # 全站區段在案件頁有兩個載入點（側欄＋案件頁）：次數放寬成 2，但路徑→區段仍要與後端全站表一致
    for path, name in list(pairs.items()):
        if name in B.ORIGINAL_PATH:
            assert B.ORIGINAL_PATH[name] == path, name
            pairs.pop(path)
    assert pairs == want
    assert sorted(re.findall(r"\['(\w+)', 2\]", block)) == ["bonusModuleStatus", "moduleAvailability"]


def test_only_the_case_page_asks_for_page_sections():
    src = GUARD.read_text(encoding="utf-8")
    assert "var BOOT_PAGE = /\\/case-management\\.html$/.test(location.pathname) ? 'case' : '';" in src
    assert "fetch(BOOT_PAGE ? '/api/bootstrap?page=' + BOOT_PAGE : '/api/bootstrap'," in src


def test_every_case_call_site_uses_boot_fetch_with_a_registered_url():
    table = set(_orig_sections().values()) | {
        "/api/auth/me", "/api/system/modules/availability", "/api/system/bonus-module-status"}
    sites = {
        "js/case-management-core.js": ["/api/settings/company-profile/public", "/api/auth/me", "/api/users/selectable", "/api/system/modules/availability"],
        "js/case-management-dispatch.js": ["/api/vendor-contractors/selectable", "/api/contractors/selectable"],
        "js/case-management-close.js": ["/api/system/bonus-module-status"],
        "static/onepipe.js": ["/api/settings-center/public?groups=onepipe"],
        "static/profit-warning.js": ["/api/profit-warning/config"],
        "static/public-flags.js": ["/api/settings-center/public?groups="],
        "static/list-sort.js": ["/api/list-prefs/"],
    }
    for rel, urls in sites.items():
        src = (FRONT / rel).read_text(encoding="utf-8")
        for u in urls:
            assert re.search(r"\(window\.motrixBootFetch \|\| fetch\)\(\s*[`'\"]" + re.escape(u), src), (rel, u)
            if u.endswith(("groups=", "/api/list-prefs/")):
                continue                                     # 組字串的網址：整串由上面的 builder 守門與 harness 驗證
            assert u in table, (rel, u)


HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[1], 'utf8'); const inp = JSON.parse(process.argv[2])
const handlers = {}; const real = []; const calls = []
const win = { addEventListener: (ev, fn) => { (handlers[ev] = handlers[ev] || []).push(fn) }, motrixApplyBanners() {} }
const ls = { getItem: () => JSON.stringify({ token: 'T' }), removeItem() {} }
const ss = { setItem() {}, getItem: k => (k === 'motrix_prefs_synced' ? '1' : null), removeItem() {} }
const loc = { pathname: inp.path, search: '', hash: '', replace() {} }
const doc = { createElement: () => ({}), head: { appendChild() {} }, getElementById: () => null }
let guardMeSeen = false
const fetchFn = (url, opts) => {
  calls.push(url)
  if (url.indexOf('/api/bootstrap') === 0) return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(Object.assign({ v: 1, me: { username: 'u' }, errors: {} }, inp.extra)) })
  if (url === '/api/auth/me' && !guardMeSeen) { guardMeSeen = true; return Promise.resolve({ ok: true, status: 200 }) }
  real.push(url)
  return Promise.resolve(new Response(JSON.stringify({ real: url }), { status: 200 }))
}
new Function('window', 'location', 'localStorage', 'sessionStorage', 'document', 'fetch', 'setTimeout', 'clearTimeout', src)(win, loc, ls, ss, doc, fetchFn, () => 0, () => {})
const H = { headers: { Authorization: 'Bearer T' } }
;(async () => {
  await win.MotrixBoot
  const got = []
  for (const u of inp.urls) got.push([u, await (await win.motrixBootFetch(u, H)).json()])
  console.log(JSON.stringify({ calls, real, got }))
})()
"""


def _run(path, extra, urls):
    out = subprocess.run([NODE, "-e", HARNESS, str(GUARD), json.dumps({"path": path, "extra": extra, "urls": urls})],
                         capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_case_page_is_served_from_the_bundle_and_asks_with_page_case():
    urls = list(_orig_sections().values())
    extra = {name: {"boot": name} for name in _orig_sections()}
    out = _run("/pages/case-management.html", extra, urls)
    assert "/api/bootstrap?page=case" in out["calls"] and "/api/bootstrap" not in out["calls"]
    assert out["real"] == []                                   # 8 支都由 bootstrap 供應，沒有真的請求
    assert [g[1] for g in out["got"]] == [{"boot": n} for n in _orig_sections()]


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_case_page_falls_back_to_the_real_endpoint_for_missing_sections():
    urls = list(_orig_sections().values())
    out = _run("/pages/case-management.html", {"usersSelectable": {"boot": "u"}}, urls)
    assert out["got"][urls.index("/api/users/selectable")][1] == {"boot": "u"}
    assert sorted(out["real"]) == sorted(u for u in urls if u != "/api/users/selectable")


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_other_pages_do_not_register_or_ask_for_case_sections():
    urls = list(_orig_sections().values())
    extra = {name: {"boot": name} for name in _orig_sections()}
    out = _run("/pages/quotation-form.html", extra, urls)
    assert "/api/bootstrap" in out["calls"] and "/api/bootstrap?page=case" not in out["calls"]
    assert sorted(out["real"]) == sorted(urls)                 # 一律真的 fetch、不被 bootstrap 內容取代
    assert all(g[1] == {"real": g[0]} for g in out["got"])


# ── T86 #15：非財務角色開案件頁不送 /finance-summary（以前每個業務／工程師開財務分頁或存款項都多一筆 403）────────────

FIN_JS = FRONT / "js" / "case-management-fin.js"
CORE_JS = FRONT / "js" / "case-management-core.js"

FIN_HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[1], 'utf8'); const inp = JSON.parse(process.argv[2])
const a = src.indexOf('async loadFinanceSummary(quoteNo) {'); const b = src.indexOf('\n    },\n', a) + 6
const obj = new Function('return {' + src.slice(a, b) + '}')()
const calls = []
const self = Object.assign(obj, {
  session: { token: 'T', role: inp.role }, financeSummary: { stale: 1 }, financeSummaryLoading: false,
  canSeeFinancial() { return ['superadmin', 'finance'].includes(this.session.role) },
  _selectLive() { return () => true },
})
global.fetch = (url, opts) => { calls.push(url); return Promise.resolve({ ok: true, json: () => Promise.resolve({ summary: 1 }) }) }
self.loadFinanceSummary('MQ-1').then(() => console.log(JSON.stringify({ calls, fs: self.financeSummary, loading: self.financeSummaryLoading })))
"""


def _fin(role):
    out = subprocess.run([NODE, "-e", FIN_HARNESS, str(FIN_JS), json.dumps({"role": role})],
                         capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not NODE, reason="需要 node")
@pytest.mark.parametrize("role", ("sales", "engineer", "admin", "viewer"))
def test_non_finance_roles_never_send_finance_summary(role):
    out = _fin(role)
    assert out["calls"] == [] and out["fs"] is None and out["loading"] is False


@pytest.mark.skipif(not NODE, reason="需要 node")
@pytest.mark.parametrize("role", ("superadmin", "finance"))
def test_finance_roles_still_load_the_summary(role):
    out = _fin(role)
    assert out["calls"] == ["/api/quotations/MQ-1/finance-summary"] and out["fs"] == {"summary": 1}


def test_frontend_gate_equals_backend_can_see_financial():
    """前端 canSeeFinancial() 只看角色；後端 can_see_financial 在旗標 off（預設）時也只看角色 ⇒ 兩邊對每個角色答案相同。
    不一致就會回到『畫面不送卻有權限』或『送了卻 403』。"""
    from helpers import auth
    src = CORE_JS.read_text(encoding="utf-8")
    assert "return ['superadmin', 'finance'].includes(this.session.role)" in src    # 伺服器答案還沒到時的備援規則
    for role in ("superadmin", "admin", "finance", "sales", "engineer", "viewer"):
        assert auth.can_see_financial({"role": role, "username": "x", "modules": []}) == (role in ("superadmin", "finance")), role


# ── T86：財務金額可視以後端答案為準（financeView 區段；旗標 finance_via_effective 開啟時前端不能只看角色）────────────

def _set_finance_flag(value):
    import db
    from helpers import auth as A
    conn = db.get_db()
    conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,'2026-11-14') "
                 "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (A.FINANCE_FLAG_KEY, json.dumps(value)))
    conn.commit()
    conn.close()
    A.reset_finance_mode_cache()


@pytest.fixture()
def fin_world(client, make_user):
    import db
    from helpers import auth as A
    hdr = {}
    for name, role in (("fv_sa", "superadmin"), ("fv_fin", "finance"), ("fv_sales", "sales"), ("fv_eng", "engineer"), ("fv_adm", "admin")):
        u, pw = make_user(username=name, role=role)
        hdr[name] = _login(client, u, pw)
    conn = db.get_db()
    ids = {r["username"]: r["id"] for r in conn.execute("SELECT id, username FROM users")}
    roles = {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM duty_roles")}
    conn.close()
    A.reset_finance_mode_cache()
    yield ids, roles, hdr
    A.reset_finance_mode_cache()


def _fv(client, h):
    d = client.get("/api/bootstrap?page=case", headers=h).json()
    assert d["errors"].get("financeView") is None, d["errors"]
    return d["financeView"]["financialView"]


def test_finance_view_follows_the_role_rule_while_the_flag_is_off(client, fin_world):
    _ids, _roles, hdr = fin_world
    assert {n: _fv(client, h) for n, h in hdr.items()} == {
        "fv_sa": True, "fv_fin": True, "fv_sales": False, "fv_eng": False, "fv_adm": False}


@pytest.mark.parametrize("flag", ("off", "shadow", "on"))
def test_finance_view_equals_backend_can_see_financial_for_every_user_and_flag(client, fin_world, flag):
    """旗標 off／shadow／on 下，bootstrap 給前端的答案 ＝ 後端 can_see_financial 對同一個人的答案（含職責角色與個人扣項）。"""
    import db
    from helpers import auth as A
    from helpers import duty_roles as DR
    ids, roles, hdr = fin_world
    sa = {"id": 1, "username": "sa", "display_name": "SA", "role": "superadmin", "modules": "[]"}
    conn = db.get_db()
    DR.bind_role(conn, sa, ids["fv_sales"], roles["finance"], reason="測試財務角色綁定")          # 業務被授予財務職責
    conn.execute("INSERT INTO user_perm_subtracts (user_id, perm_key, set_by, set_at, reason) VALUES (?,?,?,?,?)",
                 (ids["fv_fin"], "financial_view", 1, "2026-11-14", "測試"))                    # 財務角色被扣掉財務檢視
    conn.commit()
    conn.close()
    _set_finance_flag(flag)
    users = {}
    conn = db.get_db()
    try:
        for r in conn.execute("SELECT id, username, display_name, role, modules FROM users WHERE username LIKE 'fv_%'"):
            users[r["username"]] = dict(r)
    finally:
        conn.close()
    got = {n: _fv(client, h) for n, h in hdr.items()}
    assert got == {n: bool(A.can_see_financial(users[n])) for n in hdr}
    if flag == "on":
        assert got["fv_sales"] is True and got["fv_fin"] is False and got["fv_sa"] is True    # 前端只看角色會答錯的兩個人
    else:
        assert got["fv_sales"] is False and got["fv_fin"] is True


def test_finance_view_section_is_login_gated_and_carries_nothing_else(client, fin_world):
    _ids, _roles, hdr = fin_world
    d = client.get("/api/bootstrap?page=case", headers=hdr["fv_eng"]).json()
    assert d["financeView"] == {"financialView": False}
    assert client.get("/api/bootstrap?page=case").status_code == 401


CAN_SEE_HARNESS = r"""
const fs = require('fs'); const src = fs.readFileSync(process.argv[1], 'utf8'); const inp = JSON.parse(process.argv[2])
const grab = n => { const a = src.indexOf(n); return src.slice(a, src.indexOf('\n    },\n', a) + 7) }
const body = grab('    canSeeFinancial() {') + grab('    canFinanceRole() {')
const o = new Function('return {' + body.replace(/,\s*$/, '') + '}')()
o.session = { role: inp.role }
if (inp.ok !== null) o.financeViewOk = inp.ok
console.log(JSON.stringify(o.canSeeFinancial()))
"""


@pytest.mark.skipif(not NODE, reason="需要 node")
@pytest.mark.parametrize("role,ok,want", [("sales", None, False), ("finance", None, True), ("sales", True, True),
                                          ("finance", False, False), ("superadmin", False, False)])
def test_frontend_can_see_financial_uses_the_server_answer_then_falls_back_to_role(role, ok, want):
    out = subprocess.run([NODE, "-e", CAN_SEE_HARNESS, str(CORE_JS), json.dumps({"role": role, "ok": ok})],
                         capture_output=True, text=True, timeout=60, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip()) is want
    src = CORE_JS.read_text(encoding="utf-8")
    assert "financeViewOk: undefined," in src and "motrixBoot('financeView')" in src
