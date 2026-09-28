# -*- coding: utf-8 -*-
"""本公司資料設定閘門：中介層（第一道）、白名單、確認流程、暫時放行、判定失敗（COMPANY-SETUP-GATE §3.6、§4；CG-M2、CG2-S1、Q7）。

用真的判定（company_gate marker）；每題一個全新測試庫（沒有確認紀錄＝未設定）。統編由檢查碼演算法產生，不寫真實公司資料。
"""
import json
import re
from datetime import datetime, timedelta

import pytest

from helpers import company_setup as cs
from tests.test_company_setup_core_2026_09_28 import make_ubn

pytestmark = pytest.mark.company_gate

UBN = make_ubn("2345670")
PROFILE = {"name": "測試乙股份有限公司", "tax_id": UBN, "contact_info": "Tel: 02-1234-5678"}


@pytest.fixture(autouse=True)
def _fresh_gate_cache():
    cs.reset_cache()
    yield
    cs.reset_cache()


def _login(client, make_user, name, role, modules=None):
    u, pw = make_user(username=name, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def boss(client, make_user):
    return _login(client, make_user, "gate_boss", "superadmin")


@pytest.fixture()
def clerk(client, make_user):
    return _login(client, make_user, "gate_clerk", "admin")


def _confirm(client, h, **over):
    body = dict(PROFILE, confirmIdentity=True, **over)
    return client.put("/api/settings/company-profile", json=body, headers=h)


# ── 未設定 ⇒ 擋；白名單照常 ─────────────────────────────────────────────────────

def test_unconfigured_blocks_business_api_with_428(client, boss, clerk):
    for h, can in ((boss, True), (clerk, False)):
        r = client.get("/api/customers", headers=h)
        assert r.status_code == 428, r.text
        d = r.json()
        assert d["code"] == "company_setup_required" and d["canFix"] is can
        assert d["settingsUrl"] == "/pages/company-profile-settings.html?setup=1"
    assert client.get("/api/auth/me", headers=clerk).status_code == 200
    assert client.get("/api/ping").status_code == 200
    st = client.get("/api/settings/company-setup/status", headers=clerk).json()
    assert st["configured"] is False and st["canFix"] is False and st["developer"] is None


def test_confirm_flow_opens_everything(client, boss, clerk):
    assert client.put("/api/settings/company-profile", json=PROFILE, headers=boss).status_code == 200
    assert client.get("/api/customers", headers=clerk).status_code == 428          # 一般存檔不算確認
    r = _confirm(client, boss)
    assert r.status_code == 200 and r.json()["confirmed"] is True
    assert client.get("/api/customers", headers=clerk).status_code == 200
    st = client.get("/api/settings/company-setup/status", headers=boss).json()
    assert st["configured"] is True and st["via"] == "settings_page"
    import db
    conn = db.get_db()
    try:
        acts = [r[0] for r in conn.execute("SELECT action FROM audit_log WHERE action LIKE 'settings.company_identity%'")]
    finally:
        conn.close()
    assert acts == ["settings.company_identity.confirm"]


def test_only_superadmin_can_confirm(client, clerk):
    assert _confirm(client, clerk).status_code == 403


@pytest.mark.parametrize("over,msg", [({"tax_id": "12345678"}, "統一編號"), ({"name": ""}, "公司名稱"),
                                      ({"contact_info": ""}, "電話或 email")])
def test_confirm_refused_saves_nothing(client, boss, over, msg):
    before = client.get("/api/settings/company-profile", headers=boss).json()
    r = _confirm(client, boss, **over)
    assert r.status_code == 422 and msg in r.json()["detail"]
    assert client.get("/api/settings/company-profile", headers=boss).json() == before


def test_developer_identity_cannot_be_confirmed_without_signed_file(client, boss, monkeypatch):
    monkeypatch.setattr(cs, "DEVELOPER_IDENTITY_FP", frozenset({cs.identity_fp("tax", UBN)}))
    before = client.get("/api/settings/company-profile", headers=boss).json()
    r = _confirm(client, boss)
    assert r.status_code == 422 and "開發者" in r.json()["detail"]
    # 先驗再寫：被拒 ⇒ 開發者資料沒被存進去（只靠 confirm() 丟例外會是「已存檔＋422」）
    assert client.get("/api/settings/company-profile", headers=boss).json() == before


def test_confirm_clears_gate_cache_even_if_cache_key_unchanged(client, boss, clerk, monkeypatch):
    """快取鍵含 updated_at（秒）；同一秒內確認時鍵不變 ⇒ 靠 reset_cache() 立即生效。"""
    monkeypatch.setattr(cs, "_cache_key", lambda conn, root=None: "fixed")
    cs.reset_cache()
    assert client.get("/api/customers", headers=clerk).status_code == 428        # 快取進「未設定」
    assert _confirm(client, boss).status_code == 200
    assert client.get("/api/customers", headers=clerk).status_code == 200


# ── 暫時放行、判定失敗（Q7＝C） ────────────────────────────────────────────────

def test_grace_lets_everything_through_with_a_header(client, clerk):
    cs.ensure_install_id()
    now = datetime.now()
    with open(cs._files()[2], "w", encoding="utf-8") as f:
        json.dump({"created": now.isoformat(), "until": (now + timedelta(hours=2)).isoformat(),
                   "reason": "測試", "install": cs.install_hash()}, f)
    try:
        r = client.get("/api/customers", headers=clerk)
        assert r.status_code == 200 and r.headers.get(cs.HEADER) == "grace"
        st = client.get("/api/settings/company-setup/status", headers=clerk).json()
        assert st["configured"] is False and st["grace"]["until"]
    finally:
        import os
        os.remove(cs._files()[2])


def test_status_error_passes_general_api_with_header_and_alerts_once(client, clerk, monkeypatch):
    sent = []
    import helpers.email_notify as en
    monkeypatch.setattr(en, "_group_emails", lambda key: ["a@example.invalid"])
    monkeypatch.setattr(en, "_send_raising", lambda to, subj, body: sent.append(subj) or "sent")
    monkeypatch.setattr(cs, "status", lambda conn, root=None, now=None: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.get("/api/customers", headers=clerk)
    assert r.status_code == 200 and r.headers.get(cs.HEADER) == "status_error"
    st = client.get("/api/settings/company-setup/status", headers=clerk).json()
    assert st["configured"] is None and st["message"] == cs.MSG_UNDETERMINED
    client.get("/api/customers", headers=clerk)
    assert len(sent) == 1                                                            # 告警每日一次


def test_reverse_control_configured_has_no_header(client, boss, clerk):
    assert _confirm(client, boss).status_code == 200
    r = client.get("/api/customers", headers=clerk)
    assert r.status_code == 200 and cs.HEADER not in r.headers


# ── 白名單（CG-M2、CG2-S1） ────────────────────────────────────────────────────

def _all_routes(app):
    out = []

    def walk(routes, prefix=""):
        for r in routes:
            if type(r).__name__ == "_IncludedRouter":
                walk(r.original_router.routes, prefix + (getattr(r.include_context, "prefix", "") or ""))
                continue
            path = getattr(r, "path", None)
            methods = getattr(r, "methods", None)
            if path and methods:
                out.append((prefix + path, set(methods)))
    walk(app.routes)
    return out


def allowlist_problems(allowed: dict, routes) -> list:
    problems = []
    table = {}
    for path, methods in routes:
        table.setdefault(path, set()).update(methods)
    for (method, template), why in allowed.items():
        if "*" in template or not template.startswith("/api/"):
            problems.append("不是精確的路由樣板：%s" % template)
            continue
        if template not in table:
            problems.append("路由表沒有：%s %s" % (method, template))
        elif method not in table[template]:
            problems.append("方法不符：%s %s（實際 %s）" % (method, template, sorted(table[template])))
        if len((why or "").strip()) < 20:
            problems.append("理由太短：%s %s" % (method, template))
    return problems


def test_allowlist_is_exact_and_exists(client):
    import main
    assert allowlist_problems(main._COMPANY_SETUP_ALLOWED, _all_routes(client.app)) == []
    paths = {t for _m, t in main._COMPANY_SETUP_ALLOWED}
    for p in main._MUST_CHANGE_PW_ALLOWED:
        assert p in paths, "必須先改密碼的白名單要被涵蓋：%s" % p
    from helpers import licensing
    for p in licensing.LICENSE_EXEMPT_PATHS:
        assert p in paths or p in main._PUBLIC_API_PATHS, "授權豁免路徑要被涵蓋：%s" % p


def test_allowlist_reverse_controls(client):
    routes = _all_routes(client.app)
    bad = {("DELETE", "/api/settings/company-profile"): "這一條在路由表裡不存在（方法不符），應該要被抓到",
           ("GET", "/api/settings/branding*"): "萬用字元不收，前綴會讓以後的新端點自動放行",
           ("GET", "健康檢查"): "描述性條目不收，沒有路徑無從比對與守門",
           ("GET", "/api/ping"): "短"}
    probs = allowlist_problems(bad, routes)
    assert len([p for p in probs if "company-profile" in p]) == 1
    assert any("branding*" in p for p in probs) and any("健康檢查" in p for p in probs)
    assert any("理由太短" in p for p in probs)


def test_matching_uses_route_templates():
    comp = cs.compile_allowed({("PUT", "/api/settings/branding/{kind}"): "x" * 20})
    assert cs.is_allowed(comp, "PUT", "/api/settings/branding/logo")
    assert not cs.is_allowed(comp, "DELETE", "/api/settings/branding/logo")
    assert not cs.is_allowed(comp, "PUT", "/api/settings/branding-x/logo")
    assert not cs.is_allowed(comp, "PUT", "/api/settings/branding/logo/extra")


def test_every_other_api_route_is_blocked_when_unconfigured(client, clerk):
    """預設擋（§7-①）：白名單與公開路徑以外的每一條 /api 路由，未設定時都是 428（新 API 自動被擋）。"""
    import main
    allowed = {(m, t) for m, t in main._COMPANY_SETUP_ALLOWED}
    checked = 0
    leaks = []
    for path, methods in _all_routes(client.app):
        if not path.startswith("/api/") or path in main._PUBLIC_API_PATHS:
            continue
        if path.startswith("/api/uploads/"):
            continue                                                                  # ?pt= 簽名 token 在登入檢查前放行（CG-O2）
        concrete = re.sub(r"\{[^}]+\}", "1", path)
        for m in sorted(methods - {"HEAD", "OPTIONS"}):
            if (m, path) in allowed:
                continue
            r = client.request(m, concrete, headers=clerk)
            checked += 1
            if r.status_code != 428:
                leaks.append("%s %s ⇒ %s" % (m, path, r.status_code))
    assert checked > 300, checked                                                     # 正對照：真的走過路由表
    assert not leaks, leaks[:20]
