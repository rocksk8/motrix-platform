# -*- coding: utf-8 -*-
"""D14／D15 後端：`GET /api/definitions/{kind}/{key}/default`（程式出貨預設，不看資料庫）與存草稿的 `adopted` 稽核。
- 公司發布過也一樣回出貨預設（與 resolve 不同）；沒有預設的 key／未知 kind 的行為；僅最高管理者
- PUT draft 帶 `adopted`（採用出貨範本的路徑）⇒ 稽核 detail `adopted_from_default`（最多 200 項、每項截 200 字）；不帶則沒有該鍵"""
import json
from pathlib import Path

import pytest


@pytest.fixture()
def api(client, make_user):
    u, p = make_user(username="d14_sa", role="superadmin")
    u3, p3 = make_user(username="d14_adm", role="admin")

    def login(a, b):
        r = client.post("/api/auth/login", json={"username": a, "password": b})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}
    return client, {"sa": login(u, p), "adm": login(u3, p3)}


def _shipped(key):
    import db
    return json.loads((Path(db.__file__).parent / "helpers" / "expense_type_defs" / (key + ".json")).read_text(encoding="utf-8"))


def _audits():
    import db
    c = db.get_db()
    try:
        return [json.loads(r["detail"] or "{}") for r in c.execute("SELECT detail FROM audit_log WHERE action='definitions.save_draft' ORDER BY id").fetchall()]
    finally:
        c.close()


def test_default_returns_the_shipped_body(api):
    c, h = api
    r = c.get("/api/definitions/expense_type/travel/default", headers=h["sa"])
    assert r.status_code == 200 and r.json()["body"] == _shipped("travel")


def test_default_is_still_the_shipped_body_after_the_company_published(api):
    c, h = api
    body = _shipped("travel")
    body["name"] = "公司改名"
    assert c.put("/api/definitions/expense_type/travel/draft", headers=h["sa"], json={"body": body}).status_code == 200
    assert c.post("/api/definitions/expense_type/travel/publish", headers=h["sa"], json={"note": "n"}).status_code == 200
    assert c.get("/api/definitions/expense_type/travel/default", headers=h["sa"]).json()["body"]["name"] == _shipped("travel")["name"]


def test_default_for_a_key_without_a_shipped_default_is_null(api):
    c, h = api
    r = c.get("/api/definitions/expense_type/no_such_type/default", headers=h["sa"])
    assert r.status_code == 200 and r.json() == {"body": None}


def test_default_unknown_kind_is_400_and_non_superadmin_is_refused(api):
    c, h = api
    assert c.get("/api/definitions/no_such_kind/x/default", headers=h["sa"]).status_code == 400
    assert c.get("/api/definitions/expense_type/travel/default", headers=h["adm"]).status_code in (401, 403)
    assert c.get("/api/definitions/expense_type/travel/default").status_code in (401, 403)


def test_adopted_paths_are_audited_and_capped(api):
    c, h = api
    body = _shipped("travel")
    r = c.put("/api/definitions/expense_type/travel/draft", headers=h["sa"], json={"body": body, "base_etag": "", "adopted": ["fields[applicant].help", "x" * 500]})
    assert r.status_code == 200
    d = _audits()[-1]
    assert d["adopted_from_default"][0] == "fields[applicant].help" and len(d["adopted_from_default"][1]) == 200
    c.put("/api/definitions/expense_type/travel/draft", headers=h["sa"], json={"body": body, "adopted": ["p%d" % i for i in range(300)]})
    assert len(_audits()[-1]["adopted_from_default"]) == 200


def test_no_adopted_means_no_key_in_the_audit(api):
    c, h = api
    c.put("/api/definitions/expense_type/travel/draft", headers=h["sa"], json={"body": _shipped("travel")})
    assert "adopted_from_default" not in _audits()[-1]
