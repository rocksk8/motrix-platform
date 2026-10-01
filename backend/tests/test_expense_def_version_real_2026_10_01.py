# -*- coding: utf-8 -*-
"""A2：def_version 釘版的整合題——用 W1 的**真** `helpers.expense_types`（定義庫發布版本）。
單獨在 W2 分支沒有該模組 ⇒ 略過（假模組版的題在 modules/case/tests/test_expense_def_version_2026_10_01.py）。
流程：發布 v1 → 建立（釘 1）→ 發布 v2（草稿仍 1）→ 送審（重釘 2）→ 發布 v3 → 單據仍是 2，依釘住的版本讀到 v2 的內容；目前生效的才是 v3（正對照）。"""
import copy
import json

import pytest

import db
from tests._requires import requires_module, skip_module_unless

skip_module_unless("case", "費用單據端點")
ET = pytest.importorskip("helpers.expense_types", reason="需要 W1 的 helpers.expense_types（A2-2）；此分支沒有")
from core import definitions as D  # noqa: E402

pytestmark = requires_module("case", "費用單據端點")
SENT = "/api/quotations/-/extra-expenses"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _publish(name, note):
    conn = db.get_db()
    try:
        body = copy.deepcopy(ET._default_for("travel"))
        body["name"] = name
        D.save_draft(conn, "expense_type", "travel", "company", body, "boss")
        D.publish(conn, "expense_type", "travel", "company", note, "boss")
        conn.commit()
    finally:
        conn.close()


def _row(eid):
    conn = db.get_db()
    try:
        return dict(conn.execute("SELECT def_version FROM case_extra_expenses WHERE id=?", (eid,)).fetchone())
    finally:
        conn.close()


def test_real_definition_versions_are_pinned_at_create_and_submit(client, make_user):
    nm, pw = make_user(username="dvr_form", role="sales", modules=["expense_forms"])
    h = _login(client, nm, pw)
    conn = db.get_db()
    try:
        from modules.accounting.ledger import category_map as _cm
        _cm.upsert_category(conn, "OTHER", "其他")                                           # 有費用類別提供者時，送審的類別必須先定義（沒定義 ⇒ 400）
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                     ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    _publish("差旅（v1）", "v1")
    r = client.post(SENT, headers=h, json={"kind": "travel", "lines": [{"category": "其他", "summary": "x", "amount": 100}], "data": {"applicant": "dvr_form"}})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    assert _row(eid)["def_version"] == 1                                                   # 建立當下釘到目前生效的 v1
    _publish("差旅（v2）", "v2")
    assert _row(eid)["def_version"] == 1                                                   # 草稿期間改版不動
    assert client.post("%s/%d/submit" % (SENT, eid), headers=h).json()["status"] == "已核准"
    assert _row(eid)["def_version"] == 2                                                   # 送審當下重釘到 v2
    _publish("差旅（v3）", "v3")
    assert _row(eid)["def_version"] == 2                                                   # 之後改版不動
    conn = db.get_db()
    try:
        assert ET.get_type(conn, "travel", _row(eid)["def_version"])["body"]["name"] == "差旅（v2）"    # 單據依釘住的版本輸出
        assert ET.get_type(conn, "travel")["body"]["name"] == "差旅（v3）"                             # 正對照：目前生效的是 v3
    finally:
        conn.close()
    d = client.get(SENT, headers=h).json()
    assert {i["id"]: i["defVersion"] for i in d["items"]}[eid] == 2
