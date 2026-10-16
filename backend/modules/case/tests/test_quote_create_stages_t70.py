# -*- coding: utf-8 -*-
"""T70 衛生：POST /api/quotations 帶 caseRecord.stages（含空陣列）不可違反『讀 data_json 前要用 begin_write 拿寫鎖』的結構守門。

背景（triage-quote-create-stages）：create_quotation 在 INSERT 之後呼叫 `_sync_stages_to_json`，後者經 `save_quotation_json` 的守門檢查
「寫交易是不是 begin_write 開的」；舊程式沒有 begin_write ⇒ 測試環境（MOTRIX_STRICT_DB_GUARDS=1，conftest 設定）會 RuntimeError，
正式機預設只記一行 ERROR 照寫。這裡用真實最高管理者＋HTTP 驗證：建立成功、階段進了 case_stages、id 寫回 data_json、之後連線沒有帶著寫鎖漏出去。
"""
import json
import os

import pytest

import db


def _login(client, make_user, name="t70_su", role="superadmin"):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _body(**case_record):
    data = {"customerName": "T70 客戶", "projectName": "T70 專案", "quoteDate": "2026-10-17", "items": []}
    if case_record:
        data["caseRecord"] = dict({"payment": {"received": 0, "invoiced": False}, "materials": [], "devices": []}, **case_record)
    return {"status": "草稿", "data": data}


def _stages(no):
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute("SELECT id, label FROM case_stages WHERE quote_no=? ORDER BY sort_order, id", (no,)).fetchall()]
    finally:
        c.close()


def _data(no):
    c = db.get_db()
    try:
        return json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()["data_json"])
    finally:
        c.close()


def test_strict_guards_are_on_in_this_suite():
    assert os.environ.get("MOTRIX_STRICT_DB_GUARDS") == "1"      # 否則下面的題目驗不到守門（假綠燈）


@pytest.mark.parametrize("stages", [[], [{"label": "拜訪", "done": False}, {"label": "報價", "done": True}]])
def test_create_with_case_record_stages_succeeds_and_syncs(client, make_user, stages):
    h = _login(client, make_user)
    r = client.post("/api/quotations", headers=h, json=_body(stages=stages))
    assert r.status_code in (200, 201), r.text
    no = r.json()["quote_no"]
    rows = _stages(no)
    assert [x["label"] for x in rows] == [s["label"] for s in stages]
    in_json = _data(no)["caseRecord"]["stages"]
    assert [x["id"] for x in in_json] == [x["id"] for x in rows]          # 真實 id 已寫回 data_json


def test_create_without_case_record_is_unchanged(client, make_user):
    h = _login(client, make_user)
    r = client.post("/api/quotations", headers=h, json=_body())
    assert r.status_code in (200, 201), r.text
    assert _stages(r.json()["quote_no"]) == []


def test_a_failing_create_does_not_leak_the_write_lock(client, make_user, monkeypatch):
    """create 中途出錯 ⇒ 連線 rollback 並關閉；下一個建立馬上成功（沒有被前一次漏出去的寫鎖卡住）。"""
    from modules.case.api import quotations as Q
    h = _login(client, make_user)
    real = Q._peek_next_no
    state = {"boom": True}

    def flaky(conn, month):
        if state["boom"]:
            state["boom"] = False
            raise RuntimeError("模擬中途失敗")
        return real(conn, month)
    monkeypatch.setattr(Q, "_peek_next_no", flaky)
    with pytest.raises(RuntimeError):
        client.post("/api/quotations", headers=h, json=_body())
    r = client.post("/api/quotations", headers=h, json=_body(stages=[{"label": "後續", "done": False}]))
    assert r.status_code in (200, 201), r.text
    c = db.get_db()
    try:
        assert c.execute("SELECT COUNT(*) FROM quotations").fetchone()[0] == 1     # 失敗那次什麼都沒留下
    finally:
        c.close()
