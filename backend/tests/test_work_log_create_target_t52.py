# -*- coding: utf-8 -*-
"""第 52 班（使用者裁示）：工作日誌「建立」時，只有最高管理者能指定別人為記錄對象；其他人只能記自己的（同值可以）。更新（PUT）本來就不准改記錄對象（第 49 班）。"""
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _auth, _login


def _u(client, make_user, name, role, mods=("work_log",)):
    u, p = make_user(username=name, role=role, modules=list(mods))
    import db
    c = db.get_db()
    try:
        uid = c.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone()["id"]
    finally:
        c.close()
    return _auth(_login(client, u, p)), uid


def _body(uid, content="安裝"):
    return {"log_date": "2026-10-09", "user_id": uid, "content": content, "hours": 8}


def _rows(uid):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute("SELECT id, user_id, content FROM work_logs WHERE user_id=?", (uid,)).fetchall()]
    finally:
        c.close()


def test_only_superadmin_may_create_a_log_for_someone_else(client, make_user):
    sa, sa_id = _u(client, make_user, "wl52_sa", "superadmin")
    adm, adm_id = _u(client, make_user, "wl52_adm", "admin")
    usr, usr_id = _u(client, make_user, "wl52_usr", "sales")
    # 最高管理者可以替別人建
    assert client.post("/api/work-logs", headers=sa, json=_body(usr_id, "代記")).status_code == 200
    assert [r["content"] for r in _rows(usr_id)] == ["代記"]
    # admin／一般人員替別人建 ⇒ 403 且什麼都沒寫
    for h, other in ((adm, usr_id), (usr, adm_id), (adm, sa_id)):
        r = client.post("/api/work-logs", headers=h, json=_body(other, "不該寫進去"))
        assert r.status_code == 403 and "最高管理者" in r.text, r.text
    assert [r["content"] for r in _rows(adm_id)] == [] and [r["content"] for r in _rows(sa_id)] == []
    assert [r["content"] for r in _rows(usr_id)] == ["代記"]


def test_everyone_may_create_their_own_log_same_value_allowed(client, make_user):
    for name, role in (("wl52_s", "superadmin"), ("wl52_a", "admin"), ("wl52_u", "sales")):
        h, uid = _u(client, make_user, name, role)
        r = client.post("/api/work-logs", headers=h, json=_body(uid, "自己的 " + name))
        assert r.status_code == 200, (name, r.text)
        assert [x["content"] for x in _rows(uid)] == ["自己的 " + name]


def test_update_still_cannot_reassign_the_target(client, make_user):
    adm, adm_id = _u(client, make_user, "wl52_adm2", "admin")
    usr, usr_id = _u(client, make_user, "wl52_usr2", "sales")
    wid = client.post("/api/work-logs", headers=adm, json=_body(adm_id)).json()["id"]
    r = client.put("/api/work-logs/%d" % wid, headers=adm, json={"user_id": usr_id})
    assert r.status_code == 403
    assert client.put("/api/work-logs/%d" % wid, headers=adm, json={"user_id": adm_id, "content": "同值可以"}).status_code == 200
