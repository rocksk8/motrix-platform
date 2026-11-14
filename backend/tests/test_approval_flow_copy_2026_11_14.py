# -*- coding: utf-8 -*-
"""簽核流程複製（S4c；`POST /api/approval/flows/copy[/preview]`，邏輯在 helpers/approval_flow_copy.py）。

契約：預覽不寫入、會講進行中單據件數（總數／會改用新流程的數）；跟隨統一流程的類型略過；`planHash` 過期 ⇒ 409 且什麼都不寫；
只有最高管理者能用；套用後稽核＋一則合併通知在 commit 之後。反向控制：把 `_follows_unified` 的略過拿掉 ⇒ 「跟隨統一流程的類型被略過」必須紅；
把 `planHash` 比對拿掉 ⇒ 「過期預覽 ⇒ 409」必須紅。
"""
import json

import pytest

from helpers import approval_flow_copy as afc
from helpers.settings import _get_setting, _set_setting

SRC = {"tiers": [{"order": 1, "approvers": [{"sourceType": "user", "username": "flow_a"}]},
                 {"order": 2, "approvers": [{"sourceType": "user", "username": "flow_b"}]}], "includeSubmitterManagerTier": False}
EMPTY = {"tiers": []}


def _h(client, u):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}


@pytest.fixture()
def boss(client, make_user):
    return _h(client, make_user(username="afc_boss", role="superadmin"))


@pytest.fixture()
def flows():
    """統一流程＝SRC；出貨單、請款單獨立（空）；報價單跟隨統一流程。"""
    _set_setting("unified_approval_flow", SRC)
    _set_setting("shipping_approval_flow", EMPTY)
    _set_setting("payment_request_approval_flow", EMPTY)
    _set_setting("approval_flow_scope", {"quotation": True, "shipping": False, "payment_request": False})


def _body(**kw):
    b = {"source": "unified", "targets": ["shipping", "payment_request"]}
    b.update(kw)
    return b


def test_preview_writes_nothing_and_skips_types_that_follow_the_unified_flow(client, boss, flows):
    r = client.post("/api/approval/flows/copy/preview", headers=boss, json=_body(targets=["shipping", "quotation"]))
    assert r.status_code == 200, r.text
    d = r.json()
    by = {t["docType"]: t for t in d["targets"]}
    assert by["shipping"]["status"] == "copy" and by["shipping"]["after"].startswith("2 層")
    assert by["quotation"]["status"] == "skipped" and "跟隨統一流程" in by["quotation"]["note"]
    assert d["summary"]["changed"] == 1 and d["summary"]["skipped"] == 1 and d["planHash"]
    assert _get_setting("shipping_approval_flow", None) == EMPTY, "預覽不可寫入"


def test_apply_copies_and_a_second_apply_has_nothing_left_to_change(client, boss, flows):
    h = client.post("/api/approval/flows/copy/preview", headers=boss, json=_body()).json()["planHash"]
    r = client.post("/api/approval/flows/copy", headers=boss, json=_body(planHash=h))
    assert r.status_code == 200, r.text
    assert sorted(r.json()["applied"]) == ["payment_request", "shipping"]
    for dt in ("shipping", "payment_request"):
        got = _get_setting(dt + "_approval_flow", None)
        assert got["tiers"] == SRC["tiers"] and got["includeSubmitterManagerTier"] is False
    d2 = client.post("/api/approval/flows/copy/preview", headers=boss, json=_body()).json()
    assert d2["summary"]["changed"] == 0 and d2["summary"]["unchanged"] == 2


def test_stale_preview_is_409_and_nothing_is_written(client, boss, flows):
    h = client.post("/api/approval/flows/copy/preview", headers=boss, json=_body()).json()["planHash"]
    other = {"tiers": [{"order": 1, "approvers": [{"sourceType": "user", "username": "changed_after_preview"}]}]}
    _set_setting("shipping_approval_flow", other)                        # 預覽之後有人改了目標
    r = client.post("/api/approval/flows/copy", headers=boss, json=_body(planHash=h))
    assert r.status_code == 409, r.text
    assert _get_setting("shipping_approval_flow", None) == other
    assert _get_setting("payment_request_approval_flow", None) == EMPTY, "409 時其他目標也不可寫（整批同一交易）"


def test_validation_and_permissions(client, boss, flows, make_user):
    p = "/api/approval/flows/copy"
    assert client.post(p, headers=boss, json=_body()).status_code == 400                      # 沒帶 planHash
    for bad in (_body(targets=[]), _body(targets=["nope"]), _body(source="nope"), _body(source="shipping", targets=["shipping"]),
                {"source": "unified"}, _body(planHash=5)):
        assert client.post(p + "/preview", headers=boss, json=bad).status_code == 400, bad
    plain = _h(client, make_user(username="afc_sales", role="sales"))
    assert client.post(p + "/preview", headers=plain, json=_body()).status_code in (401, 403)
    assert client.post(p, headers=plain, json=_body(planHash="x")).status_code in (401, 403)
    assert _get_setting("shipping_approval_flow", None) == EMPTY


def test_inflight_counts_separate_documents_that_keep_their_own_tiers(monkeypatch):
    items = [{"type": "shipping_note", "tiers": [{"approvers": []}]}, {"type": "shipping_note", "tiers": []}, {"type": "shipping_note"},
             {"type": "payment_request", "tiers": []}, {"type": "ledger_action", "tiers": []}]
    monkeypatch.setattr(afc.registry, "providers", lambda name: {"a": lambda conn: items})
    c = afc.inflight_counts(None)
    assert c["shipping"] == {"total": 3, "usingFlow": 2} and c["payment_request"] == {"total": 1, "usingFlow": 1}
    assert "ledger_action" not in c and c["_complete"] is True


def test_a_failing_provider_is_reported_as_incomplete_not_as_zero(monkeypatch):
    def boom(conn):
        raise RuntimeError("provider down")
    monkeypatch.setattr(afc.registry, "providers", lambda name: {"a": boom, "b": lambda conn: [{"type": "voucher", "tiers": []}]})
    c = afc.inflight_counts(None)
    assert c["_complete"] is False and c["voucher"]["total"] == 1


def test_preview_reports_inflight_for_copied_targets_only(client, boss, flows, monkeypatch):
    items = [{"type": "shipping_note", "tiers": []}, {"type": "shipping_note", "tiers": [{"approvers": []}]}, {"type": "quotation", "tiers": []}]
    monkeypatch.setattr(afc.registry, "providers", lambda name: {"a": lambda conn: items})
    d = client.post("/api/approval/flows/copy/preview", headers=boss, json=_body(targets=["shipping", "quotation"])).json()
    by = {t["docType"]: t for t in d["targets"]}
    assert by["shipping"]["inflight"] == {"total": 2, "usingFlow": 1}
    assert d["summary"]["inflightTotal"] == 2 and d["summary"]["inflightUsingFlow"] == 1, "略過的類型（報價單）不算進會受影響的件數"
    assert d["inflightComplete"] is True


def test_apply_writes_audit_rows_after_commit(client, boss, flows):
    from db import get_db
    h = client.post("/api/approval/flows/copy/preview", headers=boss, json=_body(targets=["shipping"])).json()["planHash"]
    assert client.post("/api/approval/flows/copy", headers=boss, json=_body(targets=["shipping"], planHash=h)).status_code == 200
    conn = get_db()
    try:
        rows = conn.execute("SELECT action FROM audit_log WHERE action LIKE 'settings.shipping_approval_flow.copy'").fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    json.dumps(rows[0][0])


def test_empty_source_is_refused_with_409_on_preview_and_apply_and_nothing_is_written(client, boss, flows):
    """來源沒有簽核層 ⇒ 複製過去＝把對方放寬成「任一最高管理者簽核」：後端直接拒絕，不提供略過旗標。"""
    _set_setting("shipping_approval_flow", SRC)
    for url in ("/api/approval/flows/copy/preview", "/api/approval/flows/copy"):
        r = client.post(url, headers=boss, json={"source": "payment_request", "targets": ["shipping"], "planHash": "x"})
        assert r.status_code == 409, (url, r.text)
        assert "放寬" in r.json()["detail"]
    assert _get_setting("shipping_approval_flow", None)["tiers"] == SRC["tiers"], "被拒絕後目標流程不變"
    r = client.post("/api/approval/flows/copy/preview", headers=boss, json={"source": "payment_request", "targets": ["shipping"], "allowEmpty": True})
    assert r.status_code == 409, "沒有 allowEmpty 這種後門"


def test_a_source_that_follows_the_unified_flow_is_refused(client, boss, flows):
    """報價單跟隨統一流程：它自己存的流程沒在用，當來源會複製到一份死資料 ⇒ 409 並指向正確來源。"""
    r = client.post("/api/approval/flows/copy/preview", headers=boss, json={"source": "quotation", "targets": ["shipping"]})
    assert r.status_code == 409 and "統一簽核流程" in r.json()["detail"], r.text


def test_audit_keeps_the_previous_tiers_not_only_a_digest(client, boss, flows):
    from db import get_db
    _set_setting("shipping_approval_flow", {"tiers": [{"order": 1, "approvers": [{"sourceType": "user", "username": "old_one"}]}]})
    h = client.post("/api/approval/flows/copy/preview", headers=boss, json=_body(targets=["shipping"])).json()["planHash"]
    r = client.post("/api/approval/flows/copy", headers=boss, json=_body(targets=["shipping"], planHash=h))
    assert r.status_code == 200 and "_before" not in r.json() and all("_beforeValue" not in t for t in r.json()["targets"])
    conn = get_db()
    try:
        rows = [tuple(x) for x in conn.execute("SELECT * FROM audit_log WHERE action='settings.shipping_approval_flow.copy'").fetchall()]
    finally:
        conn.close()
    assert len(rows) == 1 and "old_one" in json.dumps(rows[0], ensure_ascii=False), "稽核要能還原舊流程"
