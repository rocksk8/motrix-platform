# -*- coding: utf-8 -*-
"""補登歷史報價單 T71：D1（caseRecord 為 null 時新增階段 500）、自動關閉排程。真實使用者 HTTP。"""
import json
from datetime import datetime, timedelta

import pytest

import db


def _login(client, make_user, name, role="superadmin"):
    u, p = make_user(name, "Lay-Pass-123", role=role)[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


@pytest.fixture
def boss(client, make_user):
    return _login(client, make_user, "t71_boss")


@pytest.fixture
def flag_on():
    from helpers import settings_registry as SR

    def _set(**vals):
        conn = db.get_db()
        try:
            SR.publish("quote_backfill", dict({"enabled": 1, "auto_off_hours": 24}, **vals), reason="測試", user="t71_test", conn=conn)
            conn.commit()
            SR.invalidate("quote_backfill")
        finally:
            conn.close()
    _set()
    yield _set
    _set(enabled=0, auto_off_hours=24)


def _data_json(no):
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
    finally:
        c.close()


@pytest.mark.parametrize("variant", ["null", "absent", "list"])
def test_backfill_then_add_stage_works_whatever_the_client_sent_for_caseRecord(client, boss, flag_on, variant):
    """D1：畫面新增頁送 caseRecord:null ⇒ 補登單存成 null ⇒ 新增階段曾 500。"""
    d = {"customerName": "D1 客戶", "items": [], "quoteDate": "2026-07-15"}
    if variant == "null":
        d["caseRecord"] = None
    elif variant == "list":
        d["caseRecord"] = []
    r = client.post("/api/quotations/historical", headers=boss, json={"data": d, "reason": "D1 補登測試案件"})
    assert r.status_code == 201, r.text
    no = r.json()["quote_no"]
    assert isinstance(_data_json(no)["caseRecord"], dict), "補登建立時就把 caseRecord 補成 dict"
    s = client.post("/api/quotations/%s/stages" % no, headers=boss, json={"label": "施工"})
    assert s.status_code in (200, 201), s.text
    assert [x["label"] for x in _data_json(no)["caseRecord"]["stages"]] == ["施工"]


def test_add_stage_tolerates_a_null_caseRecord_already_in_the_database(client, boss):
    """舊資料／其他路徑留下的 caseRecord:null 也不可讓新增階段 500（不只補登單）。"""
    r = client.post("/api/quotations", headers=boss, json={"status": "草稿", "data": {"customerName": "舊資料", "items": []}})
    assert r.status_code in (200, 201), r.text
    no = r.json()["quote_no"]
    c = db.get_db()
    try:
        d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
        d["caseRecord"] = None
        c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), no))
        c.commit()
    finally:
        c.close()
    s = client.post("/api/quotations/%s/stages" % no, headers=boss, json={"label": "A"})
    assert s.status_code in (200, 201), s.text
