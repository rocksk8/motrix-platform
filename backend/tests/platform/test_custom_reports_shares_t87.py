# -*- coding: utf-8 -*-
"""T87 B2-S5：「分享給誰」挑選面板的後端（候選名單、批次增減、能力再查、稽核、設定關閉）。

重點：候選只列在職＋有使用能力的人（後端每次重算）；增減分享時後端逐位再查能力，不信前端名單；
取消分享在設定關閉時仍可做、新增不行；稽核每位一列且只記帳號與報表編號；非擁有者與不存在逐字相同 404。
"""
import json

import pytest

from db import get_db
from helpers import settings_registry as R
from modules.analytics.api import custom_reports as CR

BASE = "/api/custom-reports"


def _login(client, make_user, name, role="sales", modules=None, display_name=None, department=None):
    k = {"username": name, "role": role}
    if modules is not None:
        k["modules"] = modules
    u, p = make_user(**k)
    if display_name or department:
        c = get_db()
        try:
            if display_name:
                c.execute("UPDATE users SET display_name=? WHERE username=?", (display_name, u))
            if department:
                c.execute("INSERT OR IGNORE INTO divisions (name, sort_order, created_at) VALUES ('測試處', 0, '2026-11-14')")
                div = c.execute("SELECT id FROM divisions WHERE name='測試處'").fetchone()[0]
                c.execute("INSERT OR IGNORE INTO departments (division_id, name, sort_order, created_at) VALUES (?,?,0,'2026-11-14')", (div, department))
                dep = c.execute("SELECT id FROM departments WHERE division_id=? AND name=?", (div, department)).fetchone()[0]
                c.execute("UPDATE users SET department_id=? WHERE username=?", (dep, u))
            c.commit()
        finally:
            c.close()
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _set(**kv):
    c = get_db()
    try:
        R.publish("custom_reports", kv, reason="測試", user="sa_shares", conn=c)
    finally:
        c.close()
    R.invalidate()


@pytest.fixture(autouse=True)
def _on(client):
    CR.reset_rate_limit()
    _set(enabled=1, sharing=1)
    yield
    _set(enabled=0, sharing=0)
    R.invalidate()


def _mk(client, h, name="分享測"):
    return client.post(BASE, json={"name": name, "definition": {"version": 1, "source": "quotation", "columns": ["quote_no"]}}, headers=h).json()


def _targets(client, h, q=""):
    r = client.get(BASE + "/share-targets", params={"q": q}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _audits(like="custom_reports.share_%"):
    c = get_db()
    try:
        return [dict(r) for r in c.execute("SELECT action, target_id, target_label, detail FROM audit_log WHERE action LIKE ? ORDER BY id", (like,))]
    finally:
        c.close()


def test_candidates_list_only_active_capable_people_never_self(client, make_user):
    a = _login(client, make_user, "shs_a", modules=["quotation"])
    _login(client, make_user, "shs_ok", modules=["quotation", "case_manage"], display_name="王小明")
    _login(client, make_user, "shs_nocap", modules=["inventory"], display_name="王無權")        # 沒有 quotation／case_manage／dev_crm
    t = _targets(client, a, "王")
    assert [p["username"] for p in t["people"]] == ["shs_ok"] and t["truncated"] is False
    assert set(t["people"][0]) == {"username", "name", "department"}
    assert "shs_a" not in [p["username"] for p in _targets(client, a, "shs_")["people"]]


def test_candidates_search_by_name_account_and_department_and_escapes_wildcards(client, make_user):
    a = _login(client, make_user, "shs_b", modules=["quotation"])
    _login(client, make_user, "shs_x1", modules=["quotation"], display_name="甲乙")
    _login(client, make_user, "shs_x2", modules=["quotation"], display_name="丙丁")
    assert [p["username"] for p in _targets(client, a, "甲")["people"]] == ["shs_x1"]
    assert [p["username"] for p in _targets(client, a, "shs_x2")["people"]] == ["shs_x2"]
    _login(client, make_user, "shs_x3", modules=["quotation"], display_name="戊己", department="業務一部")
    t = _targets(client, a, "業務一")["people"]
    assert [(p["username"], p["department"]) for p in t] == [("shs_x3", "業務一部")]
    assert _targets(client, a, "%")["people"] == [] and _targets(client, a, "s_s")["people"] == []      # 萬用字元當字面字元（"s_s" 若當萬用字元會配到 "shs"）
    assert [p["username"] for p in _targets(client, a, "shs_x2")["people"]] == ["shs_x2"]
    assert _targets(client, a, "查無此人")["people"] == []


def test_candidates_closed_when_sharing_off_or_flag_off_or_no_capability(client, make_user):
    a = _login(client, make_user, "shs_c", modules=["quotation"])
    _set(sharing=0)
    assert client.get(BASE + "/share-targets", headers=a).status_code == 404
    _set(sharing=1, enabled=0)
    assert client.get(BASE + "/share-targets", headers=a).status_code == 404
    _set(enabled=1)
    nocap = _login(client, make_user, "shs_c2", modules=["inventory"])
    assert client.get(BASE + "/share-targets", headers=nocap).status_code == 403


def test_batch_add_and_remove_with_audit_rows_per_person_and_no_etag_change(client, make_user):
    a = _login(client, make_user, "shs_d", modules=["quotation"])
    for n in ("shs_d1", "shs_d2", "shs_d3"):
        _login(client, make_user, n, modules=["quotation"])
    rep = _mk(client, a)
    url = "%s/%d/shares" % (BASE, rep["id"])
    r = client.post(url, json={"add": ["shs_d1", "shs_d2", "shs_d3", "shs_d1"]}, headers=a)
    assert r.status_code == 200 and sorted(p["username"] for p in r.json()["shared"]) == ["shs_d1", "shs_d2", "shs_d3"]
    assert r.json()["added"] == ["shs_d1", "shs_d2", "shs_d3"] and r.json()["removed"] == []
    assert client.get("%s/%d" % (BASE, rep["id"]), headers=a).json()["etag"] == rep["etag"]            # 增減分享不讓編輯中的定義過期
    r2 = client.post(url, json={"add": ["shs_d1"], "remove": ["shs_d2", "shs_d3", "shs_nobody"]}, headers=a)
    assert [p["username"] for p in r2.json()["shared"]] == ["shs_d1"] and r2.json()["added"] == [] and r2.json()["removed"] == ["shs_d2", "shs_d3"]
    got = client.get(url, headers=a).json()
    assert [p["username"] for p in got["shared"]] == ["shs_d1"] and got["sharingEnabled"] is True and got["max"] == 20
    rows = _audits()
    assert [(x["action"], json.loads(x["detail"])["user"]) for x in rows] == [
        ("custom_reports.share_add", "shs_d1"), ("custom_reports.share_add", "shs_d2"), ("custom_reports.share_add", "shs_d3"),
        ("custom_reports.share_remove", "shs_d2"), ("custom_reports.share_remove", "shs_d3")]
    assert all(x["target_id"] == str(rep["id"]) and set(json.loads(x["detail"])) == {"user"} and "分享測" not in x["target_label"] for x in rows)


def test_backend_rechecks_capability_even_if_the_target_was_in_an_old_candidate_list(client, make_user):
    a = _login(client, make_user, "shs_e", modules=["quotation"])
    _login(client, make_user, "shs_nocap_e", modules=["inventory"])
    rep = _mk(client, a)
    url = "%s/%d/shares" % (BASE, rep["id"])
    r = client.post(url, json={"add": ["shs_nocap_e"]}, headers=a)
    assert r.status_code == 422 and r.json()["detail"]["reason"] == "no_capability" and "shs_nocap_e" not in r.text
    assert client.get(url, headers=a).json()["shared"] == [] and _audits() == []                       # 沒寫入、沒稽核
    # 舊的 PUT sharedWith 走同一道檢查
    put = client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": ["shs_nocap_e"]}, headers=dict(a, **{"If-Match": rep["etag"]}))
    assert put.status_code == 422


def test_validation_and_limits(client, make_user):
    a = _login(client, make_user, "shs_f", modules=["quotation"])
    rep = _mk(client, a)
    url = "%s/%d/shares" % (BASE, rep["id"])
    assert client.post(url, json={"add": ["shs_f"]}, headers=a).status_code == 422                     # 自己
    r = client.post(url, json={"add": ["ghost_user"]}, headers=a)
    assert r.status_code == 422 and "ghost_user" not in r.text                                         # 不回顯輸入
    assert client.post(url, json={"add": "x"}, headers=a).status_code == 422
    assert client.post(url, json={"add": [1]}, headers=a).status_code == 422
    assert client.post(url, json={"who": []}, headers=a).status_code == 422
    names = []
    for i in range(21):
        n = "shs_f_%02d" % i
        _login(client, make_user, n, modules=["quotation"])
        names.append(n)
    assert client.post(url, json={"add": names}, headers=a).status_code == 422                         # 21 位超過 20
    assert client.post(url, json={"add": names[:20]}, headers=a).status_code == 200
    assert client.post(url, json={"add": [names[20]]}, headers=a).status_code == 422                   # 已滿
    assert client.post(url, json={"add": [names[20]], "remove": [names[0]]}, headers=a).status_code == 200       # 同時移除就騰出名額


def test_only_the_owner_can_see_or_change_shares_and_404_is_identical(client, make_user):
    a = _login(client, make_user, "shs_g", modules=["quotation"])
    b = _login(client, make_user, "shs_g2", modules=["quotation"])
    rep = _mk(client, a)
    client.post("%s/%d/shares" % (BASE, rep["id"]), json={"add": ["shs_g2"]}, headers=a)
    url = "%s/%d/shares" % (BASE, rep["id"])
    missing = "%s/999999/shares" % BASE
    for u in (url, missing):
        g = client.get(u, headers=b)
        p = client.post(u, json={"remove": ["shs_g2"]}, headers=b)
        assert g.status_code == 404 and p.status_code == 404
    assert client.get(url, headers=b).json() == client.get(missing, headers=b).json()
    assert client.post(url, json={"remove": ["shs_g2"]}, headers=b).json() == client.post(missing, json={"remove": ["shs_g2"]}, headers=b).json()
    assert [p["username"] for p in client.get(url, headers=a).json()["shared"]] == ["shs_g2"]           # 被分享者的動作沒生效


def test_removal_still_works_when_sharing_is_off_but_adding_does_not(client, make_user):
    a = _login(client, make_user, "shs_h", modules=["quotation"])
    _login(client, make_user, "shs_h2", modules=["quotation"])
    _login(client, make_user, "shs_h3", modules=["quotation"])
    rep = _mk(client, a)
    url = "%s/%d/shares" % (BASE, rep["id"])
    client.post(url, json={"add": ["shs_h2"]}, headers=a)
    _set(sharing=0)
    r = client.post(url, json={"add": ["shs_h3"]}, headers=a)
    assert r.status_code == 403 and r.json()["detail"]["reason"] == "sharing_off"
    assert client.get(url, headers=a).json() == {"shared": [], "sharingEnabled": False, "max": 20}        # 設定關閉：名單不顯示
    ok = client.post(url, json={"remove": ["shs_h2"]}, headers=a)
    assert ok.status_code == 200 and ok.json()["removed"] == ["shs_h2"]
    _set(sharing=1)
    assert client.get(url, headers=a).json()["shared"] == []


def test_put_shared_with_also_writes_per_person_audit(client, make_user):
    a = _login(client, make_user, "shs_i", modules=["quotation"])
    _login(client, make_user, "shs_i2", modules=["quotation"])
    rep = _mk(client, a)
    r = client.put("%s/%d" % (BASE, rep["id"]), json={"sharedWith": ["shs_i2"]}, headers=dict(a, **{"If-Match": rep["etag"]}))
    assert r.status_code == 200 and "_shareChanges" not in r.json() and r.json()["sharedWith"] == ["shs_i2"]
    rows = _audits()
    assert [(x["action"], json.loads(x["detail"])["user"]) for x in rows] == [("custom_reports.share_add", "shs_i2")]


def test_a_user_who_lost_the_capability_disappears_from_candidates_but_existing_share_stays_visible_to_owner(client, make_user):
    a = _login(client, make_user, "shs_j", modules=["quotation"])
    _login(client, make_user, "shs_j2", modules=["quotation"])
    rep = _mk(client, a)
    url = "%s/%d/shares" % (BASE, rep["id"])
    client.post(url, json={"add": ["shs_j2"]}, headers=a)
    c = get_db()
    try:
        c.execute("UPDATE users SET modules=? WHERE username='shs_j2'", (json.dumps(["inventory"]),))
        c.commit()
    finally:
        c.close()
    assert "shs_j2" not in [p["username"] for p in _targets(client, a, "shs_j")["people"]]
    assert [p["username"] for p in client.get(url, headers=a).json()["shared"]] == ["shs_j2"]          # 擁有者仍看得到、能取消
    assert client.post(url, json={"remove": ["shs_j2"]}, headers=a).json()["removed"] == ["shs_j2"]
