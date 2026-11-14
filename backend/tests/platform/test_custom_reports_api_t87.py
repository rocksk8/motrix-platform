# -*- coding: utf-8 -*-
"""T87 B2-S1b：`/api/custom-reports/sources`、`/preview`。

旗標關 ⇒ 404；能力與模組存取各查各的（能力不取代模組）；欄位可見性與遮罩由 runner 決定（這裡驗 HTTP 形狀與不外洩）；
限流 20/分；預覽不留稽核；未預期例外回固定訊息。
"""
import json

import pytest

from db import get_db
from helpers import report_policy as RP
from helpers import settings_registry as R
from modules.analytics.api import custom_reports as CR

BASE = "/api/custom-reports"


def _login(client, make_user, name, role, modules=None):
    kw = {"username": name, "role": role}
    if modules is not None:
        kw["modules"] = modules
    u, p = make_user(**kw)
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _set_flag(client, value):
    c = get_db()
    try:
        R.publish("custom_reports", {"enabled": value}, reason="測試", user="sa_flag", conn=c)
    finally:
        c.close()
    R.invalidate()


@pytest.fixture(autouse=True)
def _clean(client):
    CR.reset_rate_limit()
    R.invalidate()
    yield
    CR.reset_rate_limit()
    R.invalidate()


@pytest.fixture
def on(client):
    _set_flag(client, 1)


def _audit_count():
    c = get_db()
    try:
        return c.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    finally:
        c.close()


def _q(**kw):
    d = {"version": 1, "source": "quotation", "columns": ["quote_no", "customer_name"]}
    d.update(kw)
    return d


# ── 旗標 ──────────────────────────────────────────────────────────────────

def test_flag_defaults_off_and_every_endpoint_is_404_for_a_logged_in_user(client, make_user):
    assert RP.enabled() is False
    h = _login(client, make_user, "cra_sa0", "superadmin")
    assert client.get(BASE + "/sources", headers=h).status_code == 404
    assert client.post(BASE + "/preview", json=_q(), headers=h).status_code == 404


def test_not_logged_in_is_401_whether_or_not_the_flag_is_on(client, on):
    assert client.get(BASE + "/sources").status_code == 401
    assert client.post(BASE + "/preview", json=_q()).status_code == 401


def test_turning_the_flag_off_again_closes_it(client, make_user):
    h = _login(client, make_user, "cra_sa1", "superadmin")
    _set_flag(client, 1)
    assert client.get(BASE + "/sources", headers=h).status_code == 200
    _set_flag(client, 0)
    assert client.get(BASE + "/sources", headers=h).status_code == 404


# ── 能力與模組存取 ────────────────────────────────────────────────────────

def test_user_with_no_source_module_is_refused_by_the_capability(client, make_user, on):
    h = _login(client, make_user, "cra_nom", "sales", [])
    assert client.get(BASE + "/sources", headers=h).status_code == 403
    r = client.post(BASE + "/preview", json=_q(), headers=h)
    assert r.status_code == 403 and "analytics.custom_report.view" in r.text


def test_capability_does_not_replace_module_access(client, make_user, on):
    h = _login(client, make_user, "cra_crm", "sales", ["dev_crm"])               # 有能力（任一來源模組），但只有商機模組
    ids = [s["id"] for s in client.get(BASE + "/sources", headers=h).json()["sources"]]
    assert ids == ["dev_case"]
    assert client.post(BASE + "/preview", json=_q(), headers=h).status_code == 404       # 報價單來源：沒有模組 ⇒ 404，不是 200
    assert client.post(BASE + "/preview", json=_q(source="case"), headers=h).status_code == 404
    assert client.post(BASE + "/preview", json={"version": 1, "source": "dev_case", "columns": ["case_name"]}, headers=h).status_code == 200


def test_module_access_does_not_replace_the_capability(client, make_user, on, monkeypatch):
    from helpers import perm
    h = _login(client, make_user, "cra_nocap", "sales", ["quotation", "case_manage"])
    assert client.get(BASE + "/sources", headers=h).status_code == 200
    real = perm.can
    monkeypatch.setattr(perm, "can", lambda u, k: False if k == CR.CAP_VIEW else real(u, k))      # 矩陣把這格收掉
    assert client.get(BASE + "/sources", headers=h).status_code == 403
    assert client.post(BASE + "/preview", json=_q(), headers=h).status_code == 403


# ── /sources ───────────────────────────────────────────────────────────────

def test_sources_for_superadmin_lists_all_three_with_visible_fields_and_limits(client, make_user, on):
    h = _login(client, make_user, "cra_sa2", "superadmin")
    body = client.get(BASE + "/sources", headers=h).json()
    srcs = {s["id"]: s for s in body["sources"]}
    assert set(srcs) == {"quotation", "case", "dev_case"}
    tot = next(f for f in srcs["quotation"]["fields"] if f["id"] == "total")
    assert tot["visible"] is True and tot["aggregate"] and "gte" in tot["ops"]
    dt = next(f for f in srcs["quotation"]["fields"] if f["id"] == "doc_type")
    assert {o[0] for o in dt["options"]} >= {"quotation", "estimate"} or dt["options"]
    assert srcs["case"]["defaultFilters"] == [{"field": "deal_tag", "op": "in", "value": ["已成案", "已結案"]}]
    assert body["limits"]["previewRows"] == 50 and body["canExport"] is True


def test_sources_marks_hidden_fields_without_revealing_details(client, make_user, on):
    h = _login(client, make_user, "cra_eng", "engineer", ["quotation"])
    body = client.get(BASE + "/sources", headers=h).json()
    q = next(s for s in body["sources"] if s["id"] == "quotation")
    hid = [f for f in q["fields"] if not f["visible"]]
    assert {f["id"] for f in hid} >= {"total", "pretax", "direct_margin_pct", "net_margin_pct"}
    for f in hid:
        assert set(f) == {"id", "label", "type", "visible", "reason"} and f["reason"] == CR.NO_ACCESS_REASON      # 不透露哪道規則、沒有能力旗標或選項
    assert next(f for f in q["fields"] if f["id"] == "customer_name")["visible"] is True
    assert body["canExport"] in (True, False)


def test_can_export_follows_both_the_capability_and_the_policy(client, make_user, on):
    h = _login(client, make_user, "cra_exp", "sales", ["quotation", "case_manage"])
    assert client.get(BASE + "/sources", headers=h).json()["canExport"] is True
    c = get_db()
    try:
        R.publish("custom_reports", {"export_scope": 1}, reason="測試", user="sa_x", conn=c)
    finally:
        c.close()
    R.invalidate()
    assert client.get(BASE + "/sources", headers=h).json()["canExport"] is False


# ── /preview ───────────────────────────────────────────────────────────────

def test_preview_returns_rows_and_writes_no_audit(client, make_user, on):
    h = _login(client, make_user, "cra_sa3", "superadmin")
    before = _audit_count()
    r = client.post(BASE + "/preview", json=_q(), headers=h)
    assert r.status_code == 200 and {"columns", "rows", "totalRows", "truncated", "hiddenFields", "hiddenCount"} <= set(r.json())
    assert _audit_count() == before


def test_refusals_use_a_fixed_message_shape_and_never_echo_values(client, make_user, on):
    h = _login(client, make_user, "cra_eng2", "engineer", ["quotation"])
    secret = "SECRET-VALUE-9917"
    r = client.post(BASE + "/preview", json=_q(filters=[{"field": "total", "op": "gte", "value": 424242}, {"field": "customer_name", "op": "eq", "value": secret}]), headers=h)
    assert r.status_code == 422
    d = r.json()["detail"]
    assert d["reason"] == "no_permission" and "total" in d["fields"] and set(d) <= {"message", "reason", "fields", "action"}
    assert secret not in r.text and "424242" not in r.text
    for bad in ("x", [1, 2], {"version": 1}, _q(columns=["no_such_field"]) | {"unknown": 1}):
        assert client.post(BASE + "/preview", json=bad, headers=h).status_code == 422


def test_unexpected_error_returns_a_fixed_message_without_internals(client, make_user, on, monkeypatch):
    h = _login(client, make_user, "cra_sa4", "superadmin")

    def boom(*a, **k):
        raise RuntimeError("SELECT secret FROM users -- internals")
    monkeypatch.setattr(CR.RR, "preview", boom)
    r = client.post(BASE + "/preview", json=_q(), headers=h)
    assert r.status_code == 500 and "secret" not in r.text and "internals" not in r.text


def test_preview_is_rate_limited_per_user_to_20_per_minute(client, make_user, on):
    a = _login(client, make_user, "cra_rl_a", "superadmin")
    b = _login(client, make_user, "cra_rl_b", "superadmin")
    codes = [client.post(BASE + "/preview", json=_q(), headers=a).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429
    assert client.post(BASE + "/preview", json=_q(), headers=b).status_code == 200              # 別人不受影響
    assert client.get(BASE + "/sources", headers=a).status_code == 200                           # 只限預覽
    r = client.post(BASE + "/preview", json=_q(), headers=a)
    assert r.json()["detail"]["reason"] == "rate_limited"


def test_oversized_body_is_refused_not_executed(client, make_user, on):
    h = _login(client, make_user, "cra_sa5", "superadmin")
    big = _q(filters=[{"field": "customer_name", "op": "in", "value": ["x" * 190] * 50}])
    assert len(json.dumps(big)) > 8192
    assert client.post(BASE + "/preview", json=big, headers=h).status_code == 422
