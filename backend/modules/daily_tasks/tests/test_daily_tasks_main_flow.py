"""M12 每日任務的主要流程：建立 → 被指派的人看得到 → 完成回報；以及三道權限（稽核 AUDIT-D-A-M12-move S-2）。

搬遷前後整個 repo 都沒有一題打 `/api/daily-tasks` 的建立與完成 ⇒ 模組選題只剩契約題。本檔補最小的一條端到端細線。
"""
import pytest


@pytest.fixture(autouse=True)
def _no_background_mail(monkeypatch):
    """指派／完成通知信在背景執行緒寄；本檔只驗資料與權限。"""
    from modules.daily_tasks import api
    monkeypatch.setattr(api, "spawn_bg_thread", lambda target, args=(), **kw: None)


def _token(client, make_user, username, role, modules=None):
    u, pw = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _q(sql, *args):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _create(client, h, **kw):
    body = {"task_date": "2026-09-15", "title": "機房巡檢", "assigned_to": ["dt_eng"], **kw}
    return client.post("/api/daily-tasks", headers=h, json=body)


def test_create_then_assignee_sees_it_and_reports_completion(client, make_user):
    adm = _token(client, make_user, "dt_adm", "superadmin")
    eng = _token(client, make_user, "dt_eng", "engineer", modules=["daily_task"])
    other = _token(client, make_user, "dt_other", "engineer", modules=["daily_task"])

    r = _create(client, adm)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    mine = client.get("/api/daily-tasks?year_month=2026-09", headers=eng)
    assert mine.status_code == 200, mine.text
    assert [i["id"] for i in mine.json()["items"] if i["title"] == "機房巡檢"] == [tid]
    theirs = client.get("/api/daily-tasks?year_month=2026-09", headers=other).json()["items"]
    assert not [i for i in theirs if i["id"] == tid], "沒被指派的人不該看到"

    r = client.patch(f"/api/daily-tasks/{tid}/complete", headers=eng, json={"completed": True, "report": "已完成巡檢"})
    assert r.status_code == 200 and r.json()["completed_at"], r.text
    comp = _q("SELECT username, completed, report FROM daily_task_completions WHERE task_id=?", tid)
    assert comp == [{"username": "dt_eng", "completed": 1, "report": "已完成巡檢"}]


def test_only_superadmin_creates_and_only_assignees_complete(client, make_user):
    adm = _token(client, make_user, "dt_adm2", "superadmin")
    _token(client, make_user, "dt_eng", "engineer", modules=["daily_task"])
    admin = _token(client, make_user, "dt_admin2", "admin", modules=["daily_task"])
    other = _token(client, make_user, "dt_other2", "engineer", modules=["daily_task"])

    r = _create(client, admin)
    assert r.status_code == 403 and "最高管理者" in r.json()["detail"], r.text
    assert _q("SELECT id FROM daily_tasks WHERE title='機房巡檢'") == []

    tid = _create(client, adm).json()["id"]
    r = client.patch(f"/api/daily-tasks/{tid}/complete", headers=other, json={"completed": True})
    assert r.status_code == 403, r.text
    assert _q("SELECT * FROM daily_task_completions WHERE task_id=?", tid) == []


def test_without_the_module_permission_the_list_is_refused(client, make_user):
    none = _token(client, make_user, "dt_none", "engineer", modules=[])
    r = client.get("/api/daily-tasks?year_month=2026-09", headers=none)
    assert r.status_code == 403, r.text
