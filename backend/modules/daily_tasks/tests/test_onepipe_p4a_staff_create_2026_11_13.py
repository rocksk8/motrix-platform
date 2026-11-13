# -*- coding: utf-8 -*-
"""一條龍 P4a（旗標 onepipe.entry_unify；使用者裁示 D5＝A）：現場人員可新增「掛在自己看得到的案件上、指派給自己」的每日事項。

- 旗標關 ⇒ 與今天逐字相同的 403（「僅最高管理者可建立工作事項」）；最高管理者建立不受旗標影響。
- 旗標開 ⇒ 只放寬「新增」：必須掛案件、案件要看得到（看不到＝同案件端點的 404）、只能指派給自己、不能指定主管、只能單次。
- 修改、刪除仍限最高管理者；事項只有本人看得到（沒被指派的案件成員看不到）。
"""
import json

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔的新增事項要掛案件（打 M01 的案件可見性）")

NO = "MQ-P4A-001"
DENIED = "僅最高管理者可建立工作事項"


@pytest.fixture(autouse=True)
def _no_background_mail(monkeypatch):
    from modules.daily_tasks import api
    monkeypatch.setattr(api, "spawn_bg_thread", lambda target, args=(), **kw: None)


def _flag(monkeypatch, on):
    from helpers import onepipe_flags
    monkeypatch.setattr(onepipe_flags, "flag_on", lambda field, conn=None: bool(on) and field == "entry_unify")


def _login(client, make_user, username, role, modules=None):
    u, pw = make_user(username=username, role=role, modules=modules)[:2]
    r = client.post("/api/auth/login", json={"username": u, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _seed_case(members=()):
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (NO, "已送出", "自建客戶", "自建工程", 1000, 950, json.dumps({"dealTag": "已成案"}, ensure_ascii=False), now, now, "已成案",
                      json.dumps([_uid(u) for u in members])))
        conn.commit()
    finally:
        conn.close()


def _rows(sql, *args):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _post(client, h, **kw):
    body = {"task_date": "2026-11-14", "title": "到場確認設備位置", "case_no": NO, **kw}
    return client.post("/api/daily-tasks", headers=h, json=body)


@pytest.fixture()
def world(client, make_user):
    eng = _login(client, make_user, "p4a_eng", "engineer", ["daily_task"])
    mate = _login(client, make_user, "p4a_mate", "engineer", ["daily_task"])          # 同案件成員，但沒被指派這筆事項
    out = _login(client, make_user, "p4a_out", "engineer", ["daily_task"])            # 不是案件成員
    adm = _login(client, make_user, "p4a_adm", "superadmin")
    _seed_case(["p4a_eng", "p4a_mate"])
    return {"eng": eng, "mate": mate, "out": out, "adm": adm}


def test_flag_off_staff_create_is_still_the_same_403(client, world, monkeypatch):
    _flag(monkeypatch, False)
    r = _post(client, world["eng"])
    assert r.status_code == 403 and r.json()["detail"] == DENIED, r.text
    assert _rows("SELECT id FROM daily_tasks") == []


def test_flag_on_staff_creates_a_case_task_assigned_to_self_only(client, world, monkeypatch):
    _flag(monkeypatch, True)
    r = _post(client, world["eng"], assigned_to=[])                                 # 沒填指派 ⇒ 伺服器補成自己
    assert r.status_code == 201, r.text
    row = _rows("SELECT created_by, case_no, assigned_to, supervisors, recurrence_type FROM daily_tasks WHERE id=?", r.json()["id"])[0]
    assert row["created_by"] == "p4a_eng" and row["case_no"] == NO and row["recurrence_type"] == "once"
    assert json.loads(row["assigned_to"]) == ["p4a_eng"] and json.loads(row["supervisors"]) == []
    # 稽核記得出是現場自建
    audit = _rows("SELECT detail FROM audit_log WHERE action='daily_task.create'")
    assert audit and "現場自建" in audit[-1]["detail"] and NO in audit[-1]["detail"], audit
    # 本人看得到
    mine = client.get("/api/daily-tasks?year_month=2026-11", headers=world["eng"]).json()["items"]
    assert [i["id"] for i in mine] == [r.json()["id"]]


def test_the_new_task_is_not_visible_to_other_case_members_or_outsiders(client, world, monkeypatch):
    """負向：新增權放寬，不等於「誰看得到」放寬——事項只給被指派的本人（與今天相同）。"""
    _flag(monkeypatch, True)
    tid = _post(client, world["eng"]).json()["id"]
    for who in ("mate", "out"):
        items = client.get("/api/daily-tasks?year_month=2026-11", headers=world[who]).json()["items"]
        assert not [i for i in items if i["id"] == tid], who
        assert client.get(f"/api/daily-tasks/{tid}", headers=world[who]).status_code == 403, who


@pytest.mark.parametrize("extra,code", [
    ({"case_no": ""}, 403),                                    # 一定要掛案件
    ({"assigned_to": ["p4a_mate"]}, 403),                      # 不能指派別人
    ({"assigned_to": ["p4a_eng", "p4a_mate"]}, 403),           # 連同自己也不行
    ({"supervisors": ["p4a_mate"]}, 403),                      # 不能指定主管（會收到通知）
    ({"recurrence_type": "weekly", "recurrence_days": [1]}, 403),
    ({"recurrence_type": "range", "recurrence_end_date": "2026-11-20"}, 403),
])
def test_flag_on_still_refuses_anything_beyond_my_own_case_task(client, world, monkeypatch, extra, code):
    _flag(monkeypatch, True)
    r = _post(client, world["eng"], **extra)
    assert r.status_code == code, r.text
    assert _rows("SELECT id FROM daily_tasks") == []


def test_a_case_i_cannot_see_is_the_same_404_as_a_missing_case(client, world, monkeypatch):
    _flag(monkeypatch, True)
    hidden = _post(client, world["out"])
    missing = _post(client, world["eng"], case_no="MQ-NO-SUCH")
    assert hidden.status_code == 404 and missing.status_code == 404, (hidden.text, missing.text)
    assert hidden.json()["detail"].replace(NO, "X") == missing.json()["detail"].replace("MQ-NO-SUCH", "X"), "不洩漏案件存不存在"
    assert _rows("SELECT id FROM daily_tasks") == []


def test_without_the_daily_task_or_case_manage_module_it_is_still_refused(client, make_user, world, monkeypatch):
    _flag(monkeypatch, True)
    h = _login(client, make_user, "p4a_nomod", "engineer", ["dashboard"])
    assert _post(client, h).status_code == 403


def test_edit_and_delete_stay_superadmin_only(client, world, monkeypatch):
    _flag(monkeypatch, True)
    tid = _post(client, world["eng"]).json()["id"]
    body = {"task_date": "2026-11-14", "title": "改過的標題", "assigned_to": ["p4a_eng"], "case_no": NO}
    assert client.put(f"/api/daily-tasks/{tid}", headers=world["eng"], json=body).status_code == 403
    assert client.delete(f"/api/daily-tasks/{tid}", headers=world["eng"]).status_code == 403
    assert client.put(f"/api/daily-tasks/{tid}", headers=world["adm"], json=body).status_code == 200


@pytest.mark.parametrize("on", [False, True])
def test_superadmin_create_is_unchanged_by_the_flag(client, world, monkeypatch, on):
    _flag(monkeypatch, on)
    r = client.post("/api/daily-tasks", headers=world["adm"],
                    json={"task_date": "2026-11-14", "title": "指派給別人、不掛案件", "assigned_to": ["p4a_mate"], "supervisors": ["p4a_eng"]})
    assert r.status_code == 201, r.text
    row = _rows("SELECT assigned_to, supervisors, case_no FROM daily_tasks WHERE id=?", r.json()["id"])[0]
    assert json.loads(row["assigned_to"]) == ["p4a_mate"] and json.loads(row["supervisors"]) == ["p4a_eng"] and row["case_no"] == ""


def test_staff_self_create_does_not_notify_the_creator(client, world, monkeypatch):
    _flag(monkeypatch, True)
    from modules.daily_tasks import api
    sent = []
    monkeypatch.setattr(api, "_notify", lambda *a, **k: sent.append(a))
    assert _post(client, world["eng"]).status_code == 201
    assert sent == [], "自己建給自己，不發站內通知"


# ── 案件選單（h9 審查 MUST-FIX：/api/sales-orders 只給財務／最高管理者，現場人員選不到案件）────────────────────────

def _seed_other(no, members, deal="已成案", customer="別家客戶"):
    import db
    now = "2026-01-02T00:00:00"
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (no, "已送出", customer, "別案工程", 98765, 90000, json.dumps({"dealTag": deal}, ensure_ascii=False), now, now, deal,
                      json.dumps([_uid(u) for u in members])))
        conn.commit()
    finally:
        conn.close()


def test_picker_lists_only_my_closed_won_cases_and_never_an_amount(client, world, monkeypatch):
    _flag(monkeypatch, True)
    _seed_other("MQ-P4A-OTHER", ["p4a_out"])                       # 別人的案件（eng 不是成員）
    _seed_other("MQ-P4A-DRAFT", ["p4a_eng"], deal="")              # 我的案件，但還沒成案
    r = client.get("/api/daily-tasks/case-options", headers=world["eng"])
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["quoteNo"] for i in items] == [NO], items
    assert set(items[0]) == {"quoteNo", "customer", "projectName"}, "只回案號／客戶／案名"
    assert "98765" not in r.text and "1000" not in r.text and "total" not in r.text.lower() and "pretax" not in r.text.lower()
    out = client.get("/api/daily-tasks/case-options", headers=world["out"]).json()["items"]
    assert [i["quoteNo"] for i in out] == ["MQ-P4A-OTHER"], "別人只看到自己的案件，看不到我的"
    # 清單裡的每一筆，伺服器都收（選單與新增守門同一條規則）
    assert _post(client, world["eng"], case_no=items[0]["quoteNo"]).status_code == 201


def test_picker_search_and_the_listed_case_is_exactly_what_create_accepts(client, world, monkeypatch):
    _flag(monkeypatch, True)
    assert client.get("/api/daily-tasks/case-options?q=自建客戶", headers=world["eng"]).json()["items"][0]["quoteNo"] == NO
    assert client.get("/api/daily-tasks/case-options?q=不存在的字", headers=world["eng"]).json()["items"] == []
    assert client.get("/api/daily-tasks/case-options?q=%25", headers=world["eng"]).json()["items"] == [], "% 當一般字元，不是萬用字元"


def test_picker_is_404_when_the_flag_is_off_and_403_without_the_module(client, make_user, world, monkeypatch):
    _flag(monkeypatch, False)
    r = client.get("/api/daily-tasks/case-options", headers=world["eng"])
    assert r.status_code == 404 and r.json()["detail"] == "Not Found"
    _flag(monkeypatch, True)
    h = _login(client, make_user, "p4a_nomod2", "engineer", ["dashboard"])
    assert client.get("/api/daily-tasks/case-options", headers=h).status_code == 403
    assert client.get("/api/daily-tasks/case-options").status_code in (401, 403)


def test_the_case_no_is_stored_trimmed(client, world, monkeypatch):
    _flag(monkeypatch, True)
    r = _post(client, world["eng"], case_no="  %s  " % NO)
    assert r.status_code == 201, r.text
    assert _rows("SELECT case_no FROM daily_tasks WHERE id=?", r.json()["id"])[0]["case_no"] == NO


def test_real_flag_end_to_end_through_the_settings_engine(client, world):
    """不 monkeypatch：旗標走設定中心引擎（T84 起預設開；存成 0 就關、改回 1 就開）。"""
    from helpers import settings_registry as SR
    SR.publish("onepipe", {"entry_unify": 1}, user="t", reason="test")
    try:
        assert _post(client, world["eng"]).status_code == 201
        SR.publish("onepipe", {"entry_unify": 0}, user="t", reason="test")
        r = _post(client, world["eng"])
        assert r.status_code == 403 and r.json()["detail"] == DENIED
        assert client.get("/api/daily-tasks/case-options", headers=world["eng"]).status_code == 404
    finally:
        SR.publish("onepipe", {"entry_unify": 1}, user="t", reason="test")
