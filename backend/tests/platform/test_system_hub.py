# -*- coding: utf-8 -*-
"""系統中心（第 54 班 P1）守門：註冊表合約、與選單對等、權限一致、徽章隔離、快取、框架先行（頁面不寫死項目）。
設計 docs/platform/plans/SYSTEM-HUB-DESIGN-T54.md；實作 core/system_hub.py、routers/system_hub.py、frontend/pages/system-hub.html。"""
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from core import menu as core_menu
from core import pages as core_pages
from core import registry, source_tree
from core import system_hub as H

ROOT = Path(__file__).resolve().parents[3]


def _manifests():
    return {d.name: json.loads((d / "module.json").read_text(encoding="utf-8")) for d in source_tree.module_dirs()}


def _all_cards():
    return H.load_l1_cards() + H.module_cards(_manifests())


def _all_pages():
    pages = set(core_pages.load_l1_pages())
    for m in _manifests().values():
        for p in m.get("pages") or []:
            pages.add(p["path"])
    return pages


def _menu_perm_by_page():
    """頁面檔名 ⇒ 選單 perm（L1 選單項＋模組 pages[].menu）。"""
    out = {}
    for it in core_menu.load_l1()["items"] + core_menu.module_items(_manifests()):
        out[it["href"].lstrip("/")] = it["perm"]
    return out


# ── 1 宣告有效 ────────────────────────────────────────────────────────────────
def test_card_declarations_are_valid_and_point_at_real_pages():
    assert H.validate(_all_cards(), _all_pages()) == []


def test_sections_are_fixed_in_l1_and_modules_cannot_add_one():
    assert [s["key"] for s in H.SECTIONS] == ["identity", "workflow", "notify", "data", "audit", "settings", "modules", "status"]
    bad = dict(_all_cards()[0], id="zz-new", section="my-own-section")
    probs = H.validate([bad])
    assert len(probs) == 1 and "my-own-section" in probs[0]


def test_validate_catches_each_kind_of_bad_card():
    ok = {"id": "a", "section": "data", "title": "標題", "desc": "說明", "impact": "影響：只是查看。", "href": "x.html", "perm": "superadmin", "order": 1}
    assert H.validate([ok], {"x.html"}) == []
    assert H.validate([{k: v for k, v in ok.items() if k != "impact"}], {"x.html"}), "缺 impact 要被抓到"
    assert H.validate([ok, dict(ok)], {"x.html"}), "重複 id 要被抓到"
    assert H.validate([dict(ok, perm="everyone")]), "不合法 perm 要被抓到"
    assert H.validate([dict(ok, order="1")]), "order 要是整數"
    assert H.validate([dict(ok, bogus=1)]), "不認得的欄位要被抓到"
    assert H.validate([dict(ok, icon="nope")]), "不認得的 icon 要被抓到"
    assert H.validate([ok], {"other.html"}), "指向不存在的頁面要被抓到"
    assert H.validate([dict(ok, planned=True)], {"other.html"}) == [], "planned 卡片不檢查頁面是否存在"
    assert H.validate([dict(ok, href="x.html#backup")], {"x.html"}) == [], "錨點不影響頁面判斷"


# ── 2 與選單對等：系統群組的每一頁都有卡片；卡片的 perm 與頁面選單 perm 相同 ──────────────────────
def test_every_system_menu_page_has_a_card_and_every_card_has_its_pages_permission():
    cards = _all_cards()
    by_page = {}
    for c in cards:
        by_page.setdefault(H._page_of(c["href"]), []).append(c)
    menu_perm = _menu_perm_by_page()
    sys_pages = []
    for it in core_menu.load_l1()["items"]:
        if it["group"] == "system" and not it.get("hub"):
            sys_pages.append(it["href"].lstrip("/"))
    for m in _manifests().values():
        for p in m.get("pages") or []:
            if (p.get("menu") or {}).get("group") == "system":
                sys_pages.append(p["path"])
    missing = [p for p in sys_pages if p not in by_page]
    assert not missing, "系統群組的頁面沒有系統中心卡片（在擁有它的模組 module.json 加 system_cards）：%s" % missing
    for page, cs in by_page.items():
        if page in menu_perm:
            for c in cs:
                assert c["perm"] == menu_perm[page], "卡片 %s 的 perm %r 與頁面 %s 的選單 perm %r 不同" % (c["id"], c["perm"], page, menu_perm[page])


def test_exactly_one_hub_entry_in_the_system_group_and_it_is_the_hub_page():
    items = [it for it in core_menu.load_l1()["items"] if it.get("hub")]
    assert len(items) == 1 and items[0]["group"] == "system" and items[0]["href"] == "system-hub.html" and items[0]["perm"] == "any"
    groups = core_menu.build(core_menu.load_l1(), core_menu.module_items(_manifests()), [], True)
    sysg = [g for g in groups if g["key"] == "system"][0]
    assert [r["href"] for r in sysg["items"] if r.get("hub")] == ["system-hub.html"]
    assert core_menu.validate(core_menu.load_l1(), core_menu.module_items(_manifests())) == []


# ── 3 API：權限過濾（零洩漏、零遺漏）、未登入 401 ───────────────────────────────────────────────
def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture(autouse=True)
def _fresh_cache(client):
    from routers import system_hub as R
    R.clear_cache()
    yield
    R.clear_cache()


def _hub(client, headers):
    r = client.get("/api/system-hub", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(d):
    return {it["id"] for s in d["sections"] for it in s["items"]}


def test_requires_login(client):
    assert client.get("/api/system-hub").status_code == 401


def test_superadmin_sees_every_declared_card_in_fixed_section_order(client, make_user):
    u, p = make_user(username="hub_su", role="superadmin")
    d = _hub(client, _login(client, u, p))
    assert _ids(d) == {c["id"] for c in _all_cards()}
    assert [s["key"] for s in d["sections"]] == [k for k in H.section_keys() if k in {s["key"] for s in d["sections"]}]
    assert d["total"] == len(_all_cards()) and all(s["count"] == len(s["items"]) for s in d["sections"])


def test_each_role_sees_exactly_the_cards_its_menu_would_show(client, make_user):
    """hub 不放寬也不收緊：使用者看到的卡片頁面 == 選單 system 群組（排除 hub 本身）對他可見的頁面（有選單項的那些）。"""
    from helpers.auth import effective_modules
    cases = [("hub_viewer", "viewer", []), ("hub_admin", "admin", ["audit_log", "module_versions"]), ("hub_fin", "finance", [])]
    menu_perm = _menu_perm_by_page()
    for name, role, mods in cases:
        u, p = make_user(username=name, role=role, modules=mods)
        d = _hub(client, _login(client, u, p))
        got_pages = {H._page_of(it["href"]) for s in d["sections"] for it in s["items"]}
        modules = effective_modules(role, mods)
        for card in _all_cards():
            page = H._page_of(card["href"])
            allowed = core_menu.visible(card["perm"], set(modules), role == "superadmin")
            assert (card["id"] in _ids(d)) == allowed, "%s 對 %s：卡片 %s 可見性與權限不符" % (role, name, card["id"])
            if page in menu_perm and not card.get("planned"):
                assert core_menu.visible(menu_perm[page], set(modules), role == "superadmin") == allowed
        if role == "viewer":
            assert got_pages == set() and d["sections"] == []
        if role == "admin":
            assert {"audit-log.html", "module-versions.html"} <= got_pages and "users.html" not in got_pages
        if role == "finance":
            assert "ledger-settings.html" in got_pages and "users.html" not in got_pages


# ── 4 徽章：隔離、逾時、格式、pending、快取 ────────────────────────────────────────────────────
def _install_providers(monkeypatch, table):
    for name, fn in table.items():
        monkeypatch.setitem(registry._LEGACY_PROVIDERS, ("system.hub_badge", name), fn)


def test_badges_attach_and_a_failing_provider_never_breaks_the_page(client, make_user, monkeypatch):
    calls = {"slow": 0}

    def ok(conn, user):
        return {"text": "12 筆", "tone": "warn", "count": 12}

    def boom(conn, user):
        raise RuntimeError("provider down")

    def slow(conn, user):
        calls["slow"] += 1
        time.sleep(1.5)
        return {"text": "late", "tone": "ok"}

    _install_providers(monkeypatch, {"users": ok, "duty-roles": boom, "org-structure": slow,
                                     "approval-settings": lambda c, u: {"text": "x", "tone": "purple"},     # 不認得的 tone
                                     "notification-settings": lambda c, u: "not a dict"})
    u, p = make_user(username="hub_su2", role="superadmin")
    t0 = time.monotonic()
    d = _hub(client, _login(client, u, p))
    assert time.monotonic() - t0 < 1.4, "逾時的提供者不可以拖住整頁"
    items = {it["id"]: it for s in d["sections"] for it in s["items"]}
    assert items["users"]["badge"] == {"text": "12 筆", "tone": "warn", "count": 12}
    for bad in ("duty-roles", "org-structure", "approval-settings", "notification-settings"):
        assert items[bad]["badge"] is None, bad
    ident = [s for s in d["sections"] if s["key"] == "identity"][0]
    assert ident["pending"] is True
    assert [s for s in d["sections"] if s["key"] == "workflow"][0]["pending"] is False


def test_response_is_cached_for_15_seconds_per_user(client, make_user, monkeypatch):
    n = {"c": 0}

    def counting(conn, user):
        n["c"] += 1
        return {"text": "ok", "tone": "ok"}

    _install_providers(monkeypatch, {"users": counting})
    u, p = make_user(username="hub_su3", role="superadmin")
    h = _login(client, u, p)
    _hub(client, h)
    _hub(client, h)
    assert n["c"] == 1
    from routers import system_hub as R
    R.clear_cache()
    _hub(client, h)
    assert n["c"] == 2


def test_attach_badges_reports_why_each_failure_happened(monkeypatch):
    from routers import system_hub as R
    secs = [{"key": "k", "items": [{"id": i, "planned": False, "badge": None} for i in ("a", "b", "c")]}]
    _install_providers(monkeypatch, {"a": lambda c, u: {"text": "ok", "tone": "info"}, "b": lambda c, u: 1 / 0, "c": lambda c, u: {"text": "", "tone": "ok"}})
    fails = R.attach_badges(secs, {"id": 1, "username": "x", "role": "superadmin"}, timeout=2)
    assert fails == {"b": "error:ZeroDivisionError", "c": "bad_format"}
    assert secs[0]["items"][0]["badge"]["text"] == "ok" and secs[0]["pending"] is False


# ── 5 框架先行：頁面不寫死任何項目；導覽列收斂與麵包屑 ─────────────────────────────────────────────
def test_page_hardcodes_no_card_titles_or_links():
    html = (ROOT / "frontend" / "pages" / "system-hub.html").read_text(encoding="utf-8")
    leaked = [c["title"] for c in _all_cards() if c["title"] in html]
    assert leaked == [], "系統中心頁面寫死了項目標題（項目只能來自註冊表）：%s" % leaked
    hrefs = [c["href"] for c in _all_cards() if c["href"] in html]
    assert hrefs == []
    assert html.count("/api/system-hub") == 1, "載入只打一支端點"


NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_sidebar_collapses_the_system_group_to_one_link_only_when_something_is_visible():
    src = (ROOT / "frontend" / "static" / "sidebar.js").read_text(encoding="utf-8")
    m = re.search(r"  function _collapseHub\(g\) \{.*?\n  \}\n", src, re.S)
    assert m, "找不到 _collapseHub"
    script = m.group(0) + """
const hub={href:'system-hub.html',label:'系統',active:['system-hub.html'],hub:true}
const a={href:'users.html',label:'使用者管理',active:['users.html']}
const b={href:'audit-log.html',label:'歷史紀錄',active:['audit-log.html','x.html']}
const full=_collapseHub({key:'system',label:'系統',items:[hub,a,b]})
const none=_collapseHub({key:'system',label:'系統',items:[hub]})
const other=_collapseHub({key:'case',label:'案件',items:[a,b]})
console.log(JSON.stringify({full, none, otherN: other.items.length}))
"""
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, encoding="utf-8", check=True, timeout=30).stdout
    r = json.loads(out)
    assert len(r["full"]["items"]) == 1 and r["full"]["items"][0]["href"] == "system-hub.html" and r["full"]["items"][0]["label"] == "系統"
    assert set(r["full"]["items"][0]["active"]) == {"system-hub.html", "users.html", "audit-log.html", "x.html"}
    assert r["none"]["items"] == [] and r["otherN"] == 2


def test_breadcrumb_wiring_exists_and_skips_the_hub_page():
    src = (ROOT / "frontend" / "static" / "sidebar.js").read_text(encoding="utf-8")
    assert "_systemCrumb()" in src and "file === 'system-hub.html'" in src and "sys-crumb" in src


# ── 6 使用者介面核心原則：畫面上不出現程式碼（render-scan）──────────────────────────────────────
def test_all_user_visible_strings_are_plain_language():
    """標題、說明、分組名稱都要白話中文；不得出現網址、檔名、底線代碼、module、API 等字樣。"""
    cards = _all_cards()
    bad = {c["id"]: [(f, H.plain_problem(c.get(f))) for f in ("title", "desc", "impact") if H.plain_problem(c.get(f))] for c in cards}
    bad = {k: v for k, v in bad.items() if v}
    assert bad == {}, bad
    for sct in H.SECTIONS:
        assert H.plain_problem(sct["title"]) == "" and H.plain_problem(sct["sub"]) == "", sct


def test_plain_language_check_catches_code_like_text():
    assert H.plain_problem("使用者管理") == ""
    for t in ("users.html", "Open /api/x", "module_settings 設定", "只有英文", "請到 https://x.y 設定", "給 API 用"):
        assert H.plain_problem(t), t
    ok = {"id": "a", "section": "data", "title": "標題", "desc": "說明", "impact": "影響：沒有。", "href": "x.html", "perm": "superadmin", "order": 1}
    assert H.validate([ok], {"x.html"}) == []
    assert any("不是白話" in p for p in H.validate([dict(ok, desc="see module_settings")], {"x.html"}))


def test_page_never_renders_ids_hrefs_or_module_keys_as_text():
    """頁面模板裡 x-text／x-html 不得綁 href、module、id、keywords（它們只用在連結與搜尋）；徽章只顯示白話 text。"""
    html = (ROOT / "frontend" / "pages" / "system-hub.html").read_text(encoding="utf-8")
    binds = re.findall(r'x-(?:text|html)="([^"]*)"', html)
    assert binds, "掃不到任何 x-text／x-html ⇒ 掃描器壞了"
    for b in binds:
        assert not re.search(r"\.(href|module|id|keywords)", b), "畫面不可顯示程式碼欄位：%s" % b
    assert "title=\"" not in re.sub(r"<title>.*?</title>", "", html, flags=re.S) or ":title" not in html, "不要用 title 屬性洩漏網址"
    assert not re.search(r':title="[^"]*(href|module)', html)


def test_first_time_hint_is_plain_dismissible_and_remembered():
    html = (ROOT / "frontend" / "pages" / "system-hub.html").read_text(encoding="utf-8")
    m = re.search(r'data-testid="hub-first-hint">\s*<span>(.*?)</span>', html, re.S)
    assert m, "找不到第一次使用的提示"
    assert H.plain_problem(m.group(1)) == "" and "dismissHint()" in html and "motrix_system_hub_hint" in html


# ── 7 使用者決定：沒有權限的項目預設隱藏（超級管理員可改成顯示灰色＋原因）；最近使用存在帳號上 ──────────────────────
def test_denied_rows_are_hidden_by_default_and_shown_with_plain_reason_when_the_setting_is_on(client, make_user):
    su, sp = make_user(username="hub_su_set", role="superadmin")
    vu, vp = make_user(username="hub_v_set", role="viewer", modules=[])
    sh, vh = _login(client, su, sp), _login(client, vu, vp)
    assert _hub(client, vh)["sections"] == [] and _hub(client, vh)["showDenied"] is False
    r = client.put("/api/system-hub/settings", headers=sh, json={"showDenied": True})
    assert r.status_code == 200 and r.json() == {"showDenied": True}
    d = _hub(client, vh)
    rows = [it for s in d["sections"] for it in s["items"]]
    assert rows and all(it["denied"] for it in rows) and d["total"] == 0
    assert all(s["count"] == 0 for s in d["sections"])
    for it in rows:
        assert it["reason"] and H.plain_problem(it["reason"]) == "", it["reason"]
    audit = [r for r in _q("SELECT action, target_id FROM audit_log WHERE action='system_hub.settings.update'")]
    assert audit and audit[-1]["target_id"] == "system_hub_show_denied"
    client.put("/api/system-hub/settings", headers=sh, json={"showDenied": False})
    assert _hub(client, vh)["sections"] == []


def test_only_superadmin_can_change_the_denied_setting_and_the_value_must_be_a_real_flag(client, make_user):
    su, sp = make_user(username="hub_su_set2", role="superadmin")
    au, ap = make_user(username="hub_ad_set2", role="admin")
    assert client.put("/api/system-hub/settings", headers=_login(client, au, ap), json={"showDenied": True}).status_code == 403
    sh = _login(client, su, sp)
    assert client.put("/api/system-hub/settings", headers=sh, json={}).status_code == 400
    assert client.put("/api/system-hub/settings", headers=sh, json={"showDenied": "yes"}).status_code in (400, 422)


def test_denied_reason_never_shows_module_keys():
    labels = {"audit_log": "歷史紀錄（全系統操作軌跡）"}
    assert H.denied_reason("superadmin", labels) == "需要最高管理者的權限"
    r = H.denied_reason(["audit_log"], labels)
    assert "audit_log" not in r and "「歷史紀錄」" in r and H.plain_problem(r) == ""
    assert "audit_log" not in H.denied_reason(["audit_log"], {})


def test_recent_used_is_stored_per_account_and_only_openable_items_come_back(client, make_user):
    au, ap = make_user(username="hub_ad_rec", role="admin", modules=["audit_log"])
    bu, bp = make_user(username="hub_ad_rec2", role="admin", modules=["audit_log"])
    ah, bh = _login(client, au, ap), _login(client, bu, bp)
    r = client.put("/api/list-prefs/system_hub_recent", headers=ah, json={"customOrder": ["audit-log", "users", "no-such-card", "audit-log"]})
    assert r.status_code == 200
    assert _hub(client, ah)["recent"] == ["audit-log"], "看不到的、不存在的、重複的都要被濾掉"
    assert _hub(client, bh)["recent"] == [], "最近使用是每個帳號各自的"


def test_page_wires_recent_and_the_denied_setting_without_showing_codes():
    html = (ROOT / "frontend" / "pages" / "system-hub.html").read_text(encoding="utf-8")
    assert "system_hub_recent" in html and "/api/system-hub/settings" in html and "hub-recent" in html and "hub-settings" in html
    for b in re.findall(r'x-(?:text|html)="([^"]*)"', html):
        assert not re.search(r"\.(href|module|id|keywords)", b), b


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


# ── 8 審查補強：快取按人分、徽章唯讀、cap 過濾 ──────────────────────────────────────────────────
def test_cache_is_per_user_so_a_filtered_view_never_leaks_to_someone_else(client, make_user):
    su, sp = make_user(username="hub_c_su", role="superadmin")
    vu, vp = make_user(username="hub_c_v", role="viewer", modules=[])
    sh, vh = _login(client, su, sp), _login(client, vu, vp)
    full = _hub(client, sh)
    assert full["total"] > 0
    assert _hub(client, vh)["sections"] == [], "同一個 15 秒窗口內，沒有權限的人不能拿到超級管理員的快取"
    assert _hub(client, sh)["total"] == full["total"]
    from routers import system_hub as R
    keys = list(R._CACHE)
    assert len({k[0] for k in keys}) == len(keys) == 2, "快取鍵要含使用者 id"


def test_badge_providers_run_on_a_read_only_connection(client, make_user, monkeypatch):
    import db
    wrote = {}

    def sneaky(conn, user):
        try:
            conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES ('hub_probe', '1', 'x')")
            wrote["ok"] = True
        except Exception as e:                                      # noqa: BLE001
            wrote["err"] = e.__class__.__name__
        return {"text": "已檢查", "tone": "ok"}

    _install_providers(monkeypatch, {"users": sneaky})
    u, p = make_user(username="hub_ro", role="superadmin")
    _hub(client, _login(client, u, p))
    assert "ok" not in wrote and wrote.get("err") == "OperationalError", wrote
    c = db.get_db()
    try:
        assert c.execute("SELECT 1 FROM system_settings WHERE key='hub_probe'").fetchone() is None
    finally:
        c.close()


def test_cards_with_a_cap_follow_the_permission_matrix_when_it_exists(monkeypatch):
    cards = [{"id": "a", "perm": "superadmin", "cap": "menu.a", "section": "data"}, {"id": "b", "perm": ["audit_log"], "section": "data"},
             {"id": "c", "perm": "superadmin", "section": "data"}]
    # 沒有矩陣（can=None）⇒ 舊語意
    assert [c["id"] for c in H.visible_cards(cards, [], False)] == []
    assert [c["id"] for c in H.visible_cards(cards, ["audit_log"], False)] == ["b"]
    # 有矩陣：有 cap 的卡片以 can(cap) 為準（即使 perm 是 superadmin）；沒 cap 的仍走舊語意
    assert [c["id"] for c in H.visible_cards(cards, [], False, can=lambda cap: cap == "menu.a")] == ["a"]
    assert [c["id"] for c in H.visible_cards(cards, [], True, can=lambda cap: False)] == ["a", "b", "c"], "最高管理者一律可見"
    assert H.validate([dict(cards[0], title="標題", desc="說明", impact="影響：無。", href="x.html", order=1, cap="")], {"x.html"}), "空 cap 不合法"
