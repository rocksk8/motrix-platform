# -*- coding: utf-8 -*-
"""A2：單據把「類型定義版本」釘在列上（`def_version`）——建立時釘一次、送審時再釘一次，之後定義改版不動它
（W1 回報：不釘＝已送審的單據改依「目前」定義輸出，改定義會牽動舊單）。
這裡用假的 `helpers.expense_types`（只實作 `get_type(conn, code, version=None)`，W1 的模組尚未合入本分支）；真模組的整合題在列車整合分支。"""
import json
import sys
import types

import pytest

SENT = "/api/quotations/-/extra-expenses"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _no_tiers():
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        c.commit()
    finally:
        c.close()


@pytest.fixture
def H(client, make_user):
    name, pw = make_user(username="dv_form", role="sales", modules=["expense_forms"])
    return {"dv_form": _login(client, name, pw)}


@pytest.fixture
def et(monkeypatch):
    """假的 W1 類型定義模組：`state['versions'][code]` ＝目前生效版本；查無的類型 ⇒ None。"""
    import helpers
    state = {"versions": {"travel": 3, "petty_cash": 0}}
    m = types.ModuleType("helpers.expense_types")

    def get_type(conn, code, version=None):
        v = state["versions"].get(code)
        return None if v is None else {"code": code, "version": v if version is None else version, "body": {}}
    m.get_type = get_type
    monkeypatch.setitem(sys.modules, "helpers.expense_types", m)
    monkeypatch.setattr(helpers, "expense_types", m, raising=False)
    return state


def _create(client, h, kind="travel"):
    r = client.post(SENT, headers=h, json={"kind": kind, "lines": [{"category": "其他", "summary": "x", "amount": 100}], "data": {"applicant": "dv_form"}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ver(eid):
    return _q("SELECT def_version FROM case_extra_expenses WHERE id=?", (eid,))[0]["def_version"]


def test_create_pins_the_current_definition_version(client, H, et):
    eid = _create(client, H["dv_form"])
    assert _ver(eid) == 3
    d = client.get(SENT, headers=H["dv_form"]).json()
    assert {i["id"]: i["defVersion"] for i in d["items"]}[eid] == 3
    assert _ver(_create(client, H["dv_form"], "petty_cash")) == 0                         # 沒發布過 ⇒ 程式預設 ⇒ 0


def test_submit_repins_to_the_version_current_at_submit_time(client, H, et):
    eid = _create(client, H["dv_form"])
    assert _ver(eid) == 3
    et["versions"]["travel"] = 4                                                           # 草稿期間定義改版
    assert client.patch("%s/%d" % (SENT, eid), headers=H["dv_form"], json={"kind": "travel", "lines": [{"category": "其他", "summary": "y", "amount": 100}]}).status_code == 200
    assert _ver(eid) == 3                                                                  # 編輯草稿不動釘住的版本
    _no_tiers()
    assert client.post("%s/%d/submit" % (SENT, eid), headers=H["dv_form"]).json()["status"] == "已核准"
    assert _ver(eid) == 4                                                                  # 送審當下釘到當時的版本


def test_definition_change_after_submit_does_not_move_the_pin(client, H, et):
    eid = _create(client, H["dv_form"])
    _no_tiers()
    assert client.post("%s/%d/submit" % (SENT, eid), headers=H["dv_form"]).status_code == 200
    assert _ver(eid) == 3
    et["versions"]["travel"] = 9                                                           # 送審後定義改版（含：之後的變更申請送審、讀取、列表）
    assert client.get(SENT, headers=H["dv_form"]).status_code == 200
    cr = client.put("%s/%d/change-request" % (SENT, eid), headers=H["dv_form"], json={"description": "改", "lines": [{"category": "其他", "summary": "z", "amount": 200}]})
    assert cr.status_code == 200, cr.text
    assert client.post("%s/%d/change-request/submit" % (SENT, eid), headers=H["dv_form"]).status_code == 200
    assert _ver(eid) == 3                                                                  # 已送審的單據仍釘在 3（變更申請也不重釘）
    d = client.get(SENT, headers=H["dv_form"]).json()
    assert {i["id"]: i["defVersion"] for i in d["items"]}[eid] == 3


def test_legacy_rows_and_missing_definition_module_stay_at_zero(client, H, monkeypatch, seed_extra_expense):
    import helpers
    monkeypatch.delitem(sys.modules, "helpers.expense_types", raising=False)
    monkeypatch.delattr(helpers, "expense_types", raising=False)
    monkeypatch.setitem(sys.modules, "helpers.expense_types", None)                        # 模擬 W1 模組不存在（import ⇒ ImportError）
    eid = _create(client, H["dv_form"])
    assert _ver(eid) == 0
    _no_tiers()
    assert client.post("%s/%d/submit" % (SENT, eid), headers=H["dv_form"]).status_code == 200
    assert _ver(eid) == 0
    from modules.case import expense_forms as EF
    assert EF.current_def_version(None, "") == 0                                           # 舊版列（kind=''）不查定義
