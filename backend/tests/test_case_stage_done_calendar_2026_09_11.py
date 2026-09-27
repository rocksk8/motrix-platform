"""案件執行進度「勾選完成」→ 兩張行事曆（2026-09-11 第二輪交辦第 3 項）。

使用者交辦：「案件管理執行進度勾選進單確認、叫料出貨這些或是手動打上的選項，
只要有勾選，要同步於行事曆標註，例如當日勾選客戶驗收，行事曆要增加案件名稱＋
進度在行事曆上。」並回答「兩邊都要」——Google 行事曆與系統內的
「每日工作事項 → 月曆總覽」。

三個最容易做錯、而且錯了都不會有任何錯誤訊息的地方，各有一條測試守著：

1. **完成日事件不能共用到期日那一欄**。共用的話，設了到期日再勾完成，後者會把
   前者的事件改成完成日，到期提醒就這樣無聲消失。
2. **每日工作事項一定要有指派人**。空的那列只有 superadmin 看得到
   （`daily_tasks.py::_user_filter_sql()`），等於做了一個使用者看不見的東西。
3. **建立當下就要標成已完成**。否則隔天 `_check_overdue_and_notify()` 會對每個
   負責人寄一封「你逾期未完成」——那是一件已經做完的事。

2026-09-26：第 2、3 點與「系統內月曆」的 5 題需要 M12 每日任務在，移到
`modules/daily_tasks/tests/test_case_stage_done_daily_task.py`（拿掉 M12 時一起消失；稽核 AUDIT-D-A-M12-move M-1）。
M12 不在時 M01 照常存檔並回 notice 的反向控制在 `tests/platform/test_case_stage_connectors.py`。
"""
import pytest


@pytest.fixture(autouse=True)
def _no_background_sync(monkeypatch):
    """把端點自己起的背景同步關掉，測試裡改成明確、同步地呼叫那兩支 helper。

    不關的話，端點起的執行緒與測試自己的呼叫會同時寫同一列，斷言拿到誰的結果
    純看排程——實際上就先偶發紅過一次（`assigned_to` 有時是勾選的人、有時是
    背景執行緒帶進去的那個人）。**那是測試自己製造的競態，不是產品的**：正式
    流程一次勾選只會起一支執行緒。

    需要驗「端點有沒有真的呼叫這兩支」的那兩條測試會自己再蓋一次 monkeypatch
    換成記錄器（autouse fixture 先跑，測試內的 setattr 後跑，會蓋過這裡）。
    """
    from modules.case.api import quotations as q
    monkeypatch.setattr(q, "spawn_bg_thread", lambda target, args=(), **kw: None)


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_case(quote_no="MQ-STGDONE-001", project_name="台中廠房監控工程"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", project_name, 100000, 95238, "{}",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def _stage_row(stage_id):
    import db
    conn = db.get_db()
    try:
        return dict(conn.execute("SELECT * FROM case_stages WHERE id=?", (stage_id,)).fetchone())
    finally:
        conn.close()


# ── Google 行事曆 ───────────────────────────────────────────────────────────

def test_done_event_uses_its_own_column_not_the_due_date_one(client, make_user, monkeypatch):
    """完成日事件與到期日事件是兩個獨立欄位。

    這條紅掉代表「設到期日 → 勾完成」會讓到期提醒被覆蓋掉，而且行事曆上不會有
    任何跡象（事件還在，只是日期跟標題都被改了）。
    """
    from helpers import google_calendar as gc
    username, password = make_user(username="stgcal1", role="superadmin")
    token = _login(client, username, password)
    _make_case()

    created = []
    monkeypatch.setattr(gc, "_create_all_day_event",
                        lambda summary, desc, d: created.append((summary, desc, d)) or f"evt{len(created)}")
    monkeypatch.setattr(gc, "_update_all_day_event",
                        lambda eid, summary, desc, d: eid)
    monkeypatch.setattr(gc, "_delete_event", lambda eid: None)

    sid = client.post(f"/api/quotations/MQ-STGDONE-001/stages", headers=_auth(token),
                      json={"label": "客戶驗收"}).json()["id"]

    # 先設到期日（走既有的 push_event_for_case_stage_due）
    client.put(f"/api/quotations/MQ-STGDONE-001/stages/{sid}", headers=_auth(token),
               json={"dueDate": "2026-09-20"})
    gc.push_event_for_case_stage_due(sid)
    due_event = _stage_row(sid)["google_calendar_event_id"]
    assert due_event, "到期日事件 id 要寫回 google_calendar_event_id"

    # 再勾完成 → 寫到另一欄，到期日那欄不能被動到
    client.put(f"/api/quotations/MQ-STGDONE-001/stages/{sid}", headers=_auth(token),
               json={"done": True, "doneAt": "2026-09-11"})
    gc.push_event_for_case_stage_done(sid)

    row = _stage_row(sid)
    assert row["google_calendar_event_id"] == due_event, "到期日事件不能被完成日事件覆蓋"
    assert row["google_calendar_done_event_id"], "完成日事件要有自己的 id"
    assert row["google_calendar_done_event_id"] != due_event


def test_done_event_title_has_case_name_and_stage(client, make_user, monkeypatch):
    """標題格式就是使用者指定的「案件名稱＋進度」——月檢視上只看得到標題。"""
    from helpers import google_calendar as gc
    username, password = make_user(username="stgcal2", role="superadmin")
    token = _login(client, username, password)
    _make_case("MQ-STGDONE-002", project_name="彰化倉儲門禁")

    created = []
    monkeypatch.setattr(gc, "_create_all_day_event",
                        lambda summary, desc, d: created.append((summary, desc, d)) or "evtX")
    sid = client.post("/api/quotations/MQ-STGDONE-002/stages", headers=_auth(token),
                      json={"label": "客戶驗收"}).json()["id"]
    client.put(f"/api/quotations/MQ-STGDONE-002/stages/{sid}", headers=_auth(token),
               json={"done": True, "doneAt": "2026-09-11"})
    gc.push_event_for_case_stage_done(sid)

    assert len(created) == 1, created
    summary, _desc, event_date = created[0]
    assert "彰化倉儲門禁" in summary and "客戶驗收" in summary, summary
    assert event_date.isoformat() == "2026-09-11", "事件日期用完成日，不是勾選當下的日期"


def test_uncheck_deletes_the_done_event(client, make_user, monkeypatch):
    """取消勾選要把事件刪掉——留著的話行事曆會顯示一件其實沒完成的事。"""
    from helpers import google_calendar as gc
    username, password = make_user(username="stgcal3", role="superadmin")
    token = _login(client, username, password)
    _make_case("MQ-STGDONE-003")

    deleted = []
    monkeypatch.setattr(gc, "_create_all_day_event", lambda s, d, dt: "evtDel")
    monkeypatch.setattr(gc, "_delete_event", lambda eid: deleted.append(eid))

    sid = client.post("/api/quotations/MQ-STGDONE-003/stages", headers=_auth(token),
                      json={"label": "叫料出貨"}).json()["id"]
    client.put(f"/api/quotations/MQ-STGDONE-003/stages/{sid}", headers=_auth(token),
               json={"done": True, "doneAt": "2026-09-11"})
    gc.push_event_for_case_stage_done(sid)
    assert _stage_row(sid)["google_calendar_done_event_id"] == "evtDel"

    client.put(f"/api/quotations/MQ-STGDONE-003/stages/{sid}", headers=_auth(token),
               json={"done": False, "doneAt": ""})
    gc.push_event_for_case_stage_done(sid)

    assert deleted == ["evtDel"]
    assert _stage_row(sid)["google_calendar_done_event_id"] == ""


def test_ticking_a_stage_triggers_both_syncs(client, make_user, monkeypatch):
    """端點真的有接上這兩支——helper 寫得再好，沒被呼叫就等於沒做。"""
    from modules.case.api import quotations as q
    username, password = make_user(username="stgboth", role="superadmin")
    token = _login(client, username, password)
    _make_case("MQ-STGBOTH-001")

    calls = []
    monkeypatch.setattr(q, "spawn_bg_thread",
                        lambda target, args=(), **kw: calls.append((target.__name__, args)))

    sid = client.post("/api/quotations/MQ-STGBOTH-001/stages", headers=_auth(token),
                      json={"label": "訂單確認"}).json()["id"]
    client.put(f"/api/quotations/MQ-STGBOTH-001/stages/{sid}", headers=_auth(token),
               json={"done": True, "doneAt": "2026-09-11"})

    names = [c[0] for c in calls]
    assert "push_event_for_case_stage_done" in names, names
    assert "sync_daily_task_for_case_stage" in names, names


def test_non_done_edits_do_not_spam_the_calendar(client, make_user, monkeypatch):
    """只改標題之類的不該重推事件——每推一次就是一封 Google API 請求。"""
    from modules.case.api import quotations as q
    username, password = make_user(username="stgnospam", role="superadmin")
    token = _login(client, username, password)
    _make_case("MQ-STGNOSPAM-001")

    sid = client.post("/api/quotations/MQ-STGNOSPAM-001/stages", headers=_auth(token),
                      json={"label": "訂單確認"}).json()["id"]
    calls = []
    monkeypatch.setattr(q, "spawn_bg_thread",
                        lambda target, args=(), **kw: calls.append(target.__name__))
    client.put(f"/api/quotations/MQ-STGNOSPAM-001/stages/{sid}", headers=_auth(token),
               json={"label": "訂單確認（改）"})

    assert "push_event_for_case_stage_done" not in calls, calls
    assert "sync_daily_task_for_case_stage" not in calls, calls
