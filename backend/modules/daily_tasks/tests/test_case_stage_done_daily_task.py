"""案件執行進度勾選完成 → M12 每日任務（月曆總覽）：需要 M12 在的 5 題。

2026-09-26 自 `tests/test_case_stage_done_calendar_2026_09_11.py` 移入（稽核 AUDIT-D-A-M12-move M-1：
拿掉 M12 時這些題驗的是 M12 的行為，應跟著模組消失）。要守的兩件事（原檔 docstring 第 2、3 點）：

2. **每日工作事項一定要有指派人**。空的那列只有 superadmin 看得到（`_user_filter_sql()`），等於做了一個使用者看不見的東西。
3. **建立當下就要標成已完成**。否則隔天 `_check_overdue_and_notify()` 會對每個負責人寄一封「你逾期未完成」。
"""
import json

from modules.case.case_stage_tasks import sync_daily_task_for_case_stage
# 夾具 _no_background_sync（autouse）與輔助函式沿用原檔：端點自己的背景同步關掉，測試明確同步呼叫
from tests.test_case_stage_done_calendar_2026_09_11 import (  # noqa: F401
    _no_background_sync, _login, _auth, _make_case, _stage_row,
)


def _tasks_for(quote_no):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM daily_tasks WHERE case_no=? ORDER BY id", (quote_no,)).fetchall()]
    finally:
        conn.close()


def _completions(task_id):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM daily_task_completions WHERE task_id=?", (task_id,)).fetchall()]
    finally:
        conn.close()


def test_daily_task_created_with_case_name_and_stage(client, make_user):
    """月曆上那條橫條顯示的就是 daily_tasks.title，格式同樣是「案件名稱｜進度」。"""
    username, password = make_user(username="stgdt1", role="superadmin")
    token = _login(client, username, password)
    _make_case("MQ-STGDT-001", project_name="南投機房擴充")

    sid = client.post("/api/quotations/MQ-STGDT-001/stages", headers=_auth(token),
                      json={"label": "客戶驗收"}).json()["id"]
    client.put(f"/api/quotations/MQ-STGDT-001/stages/{sid}", headers=_auth(token),
               json={"done": True, "doneAt": "2026-09-11"})
    sync_daily_task_for_case_stage(sid, username, username)

    tasks = _tasks_for("MQ-STGDT-001")
    assert len(tasks) == 1, tasks
    t = tasks[0]
    assert t["title"] == "南投機房擴充｜客戶驗收"
    assert t["task_date"] == "2026-09-11", "落在完成日那一格，不是勾選當下"
    assert t["recurrence_type"] == "once" and t["is_deleted"] == 0
    assert _stage_row(sid)["daily_task_id"] == t["id"], "要記住是哪一列，取消勾選才收得回來"


def test_daily_task_always_has_an_assignee(client, make_user):
    """沒有階段負責人時掛在勾選的人身上。

    `_user_filter_sql()` 對非 superadmin 只回「我是負責人或監督人」的任務，
    assigned_to 空的那列等於做了一個使用者看不見的東西。
    """
    username, password = make_user(username="stgdt2", role="engineer")
    admin, admin_pw = make_user(username="stgdt2_adm", role="superadmin")
    atoken = _login(client, admin, admin_pw)
    _make_case("MQ-STGDT-002")

    sid = client.post("/api/quotations/MQ-STGDT-002/stages", headers=_auth(atoken),
                      json={"label": "施工安裝"}).json()["id"]
    client.put(f"/api/quotations/MQ-STGDT-002/stages/{sid}", headers=_auth(atoken),
               json={"done": True, "doneAt": "2026-09-11"})
    sync_daily_task_for_case_stage(sid, username, username)

    t = _tasks_for("MQ-STGDT-002")[0]
    assert json.loads(t["assigned_to"]) == [username]


def test_daily_task_prefers_stage_assignees(client, make_user):
    """有階段負責人就用他們——那才是真正做這件事的人。"""
    owner, owner_pw = make_user(username="stgdt3_own", role="engineer")
    admin, admin_pw = make_user(username="stgdt3_adm", role="superadmin")
    atoken = _login(client, admin, admin_pw)
    _make_case("MQ-STGDT-003")

    sid = client.post("/api/quotations/MQ-STGDT-003/stages", headers=_auth(atoken),
                      json={"label": "施工安裝"}).json()["id"]
    client.post(f"/api/quotations/MQ-STGDT-003/stages/{sid}/assignees", headers=_auth(atoken),
                json={"username": owner})
    client.put(f"/api/quotations/MQ-STGDT-003/stages/{sid}", headers=_auth(atoken),
               json={"done": True, "doneAt": "2026-09-11"})
    sync_daily_task_for_case_stage(sid, admin, admin)

    t = _tasks_for("MQ-STGDT-003")[0]
    assert json.loads(t["assigned_to"]) == [owner]


def test_daily_task_is_marked_complete_so_no_overdue_mail(client, make_user):
    """建立當下就標完成，否則隔天每個負責人都會收到「逾期未完成」。

    直接跑 `_check_overdue_and_notify()` 驗證——這比檢查 completions 表更接近
    使用者真正會遇到的事（信箱裡有沒有多一封）。
    """
    from modules.daily_tasks import api as dt
    username, password = make_user(username="stgdt4", role="superadmin")
    token = _login(client, username, password)
    _make_case("MQ-STGDT-004")

    sid = client.post("/api/quotations/MQ-STGDT-004/stages", headers=_auth(token),
                      json={"label": "尾款結清"}).json()["id"]
    client.put(f"/api/quotations/MQ-STGDT-004/stages/{sid}", headers=_auth(token),
               json={"done": True, "doneAt": "2026-09-10"})
    sync_daily_task_for_case_stage(sid, username, username)

    t = _tasks_for("MQ-STGDT-004")[0]
    comps = _completions(t["id"])
    assert len(comps) == 1 and comps[0]["completed"] == 1, comps

    sent = []
    import threading as _th

    class _FakeThread:
        def __init__(self, target=None, args=(), **kw):
            self._t, self._a = target, args

        def start(self):
            sent.append((getattr(self._t, "__name__", str(self._t)), self._a))

    monkey_orig = _th.Thread
    _th.Thread = _FakeThread
    try:
        dt._check_overdue_and_notify("2026-09-10")
    finally:
        _th.Thread = monkey_orig

    overdue_for_this = [s for s in sent if any("尾款結清" in str(a) for a in s[1])]
    assert not overdue_for_this, f"已完成的項目不該進逾期通知，實際 {overdue_for_this}"


def test_uncheck_withdraws_the_daily_task(client, make_user):
    """取消勾選 → soft delete，月曆上那條橫條要消失。"""
    username, password = make_user(username="stgdt5", role="superadmin")
    token = _login(client, username, password)
    _make_case("MQ-STGDT-005")

    sid = client.post("/api/quotations/MQ-STGDT-005/stages", headers=_auth(token),
                      json={"label": "叫料出貨"}).json()["id"]
    client.put(f"/api/quotations/MQ-STGDT-005/stages/{sid}", headers=_auth(token),
               json={"done": True, "doneAt": "2026-09-11"})
    sync_daily_task_for_case_stage(sid, username, username)
    assert _tasks_for("MQ-STGDT-005")[0]["is_deleted"] == 0

    client.put(f"/api/quotations/MQ-STGDT-005/stages/{sid}", headers=_auth(token),
               json={"done": False, "doneAt": ""})
    sync_daily_task_for_case_stage(sid, username, username)

    assert _tasks_for("MQ-STGDT-005")[0]["is_deleted"] == 1
    assert _stage_row(sid)["daily_task_id"] == 0

    # 月曆真的看不到了（走跟前端同一支 API，不是直接查表）
    r = client.get("/api/daily-tasks?year_month=2026-09", headers=_auth(token))
    titles = [i["title"] for i in r.json()["items"]]
    assert not [t for t in titles if "叫料出貨" in t], titles
