# -*- coding: utf-8 -*-
"""第 49 班 W1c-P5：工作日誌 POST／PUT／DELETE 與 GET 同一把模組鑰匙（work_log／case_manage）；PUT 只有最高管理者能改記錄對象。"""
import pytest

import db


def _hdr(client, name, pw):
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(name):
    c = db.get_db()
    try:
        return c.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()["id"]
    finally:
        c.close()


def _row(wid):
    c = db.get_db()
    try:
        r = c.execute("SELECT * FROM work_logs WHERE id=?", (wid,)).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


@pytest.fixture()
def world(client, make_user):
    out = {}
    for name, role, mods in (("wl_su", "superadmin", []), ("wl_adm", "admin", ["work_log"]), ("wl_eng", "engineer", ["work_log"]),
                             ("wl_cm", "engineer", ["case_manage"]), ("wl_none", "engineer", ["dashboard"])):
        u, p = make_user(username=name, role=role, modules=mods)
        out[name] = _hdr(client, u, p)
        out[name + "_id"] = _uid(name)
    return out


def _new(client, w, who="wl_eng", on_behalf=None):
    r = client.post("/api/work-logs", json={"log_date": "2026-10-09", "user_id": on_behalf or w[who + "_id"], "content": "巡檢", "hours": 2}, headers=w[who])
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_without_the_module_every_write_is_403_and_nothing_changes(client, world):
    w = world
    wid = _new(client, w)
    before = _row(wid)
    base = {"log_date": "2026-10-09", "user_id": w["wl_none_id"], "content": "x"}
    assert client.post("/api/work-logs", json=base, headers=w["wl_none"]).status_code == 403
    assert client.put("/api/work-logs/%d" % wid, json={"content": "改"}, headers=w["wl_none"]).status_code == 403
    assert client.delete("/api/work-logs/%d" % wid, headers=w["wl_none"]).status_code == 403
    assert _row(wid) == before


def test_work_log_or_case_manage_holders_can_write(client, world):
    w = world
    wid = _new(client, w, "wl_eng")
    assert client.put("/api/work-logs/%d" % wid, json={"content": "改", "user_id": w["wl_eng_id"]}, headers=w["wl_eng"]).status_code == 200, "送回同一個 user_id（畫面編輯視窗每次都會帶）不算改"
    assert _row(wid)["content"] == "改"
    wid2 = _new(client, w, "wl_cm")
    assert client.delete("/api/work-logs/%d" % wid2, headers=w["wl_cm"]).status_code == 200 and _row(wid2) is None


def test_only_superadmin_can_reassign_the_record_target(client, world):
    w = world
    wid = _new(client, w, "wl_eng")
    for who in ("wl_eng", "wl_adm"):                                    # 本人與管理員都不行
        r = client.put("/api/work-logs/%d" % wid, json={"user_id": w["wl_su_id"]}, headers=w[who])
        assert r.status_code == 403, (who, r.status_code)
        assert _row(wid)["user_id"] == w["wl_eng_id"], "403 不可改到"
    # 管理員仍可改別人日誌的其他欄位
    assert client.put("/api/work-logs/%d" % wid, json={"hours": 5}, headers=w["wl_adm"]).status_code == 200 and _row(wid)["hours"] == 5
    assert client.put("/api/work-logs/%d" % wid, json={"user_id": w["wl_adm_id"]}, headers=w["wl_su"]).status_code == 200
    assert _row(wid)["user_id"] == w["wl_adm_id"]


def test_the_other_roles_still_cannot_touch_someone_elses_log(client, world):
    w = world
    wid = _new(client, w, "wl_eng")
    assert client.put("/api/work-logs/%d" % wid, json={"content": "偷改"}, headers=w["wl_cm"]).status_code == 403
    assert client.delete("/api/work-logs/%d" % wid, headers=w["wl_cm"]).status_code == 403
