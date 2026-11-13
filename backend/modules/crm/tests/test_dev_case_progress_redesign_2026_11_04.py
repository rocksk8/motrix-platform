"""業務開發案件「指派／進度回報」重設計（crm v3，2026-11-04；docs/platform/plans/DEV-CASE-PROGRESS-REDESIGN-PLAN.md）。

觀測點是資料庫（`dev_case_progress`、`dev_cases`、`notifications`、`audit_log`）與實際端點／排程呼叫，不只看回應文字。

涵蓋：
- 進度回報：POST／GET（401、只有目前被指派人可新增、不是被指派人的管理員含 superadmin 403、管理員本人即被指派人 201、內容 1～4000 字）、只增不改不刪、
  新增連動 updated_at、換人後舊進度全留著且「目前進度」只認現任被指派人自指派之後寫的、稽核標籤只放摘要
- 指派：重存同一組值不動任何東西；換人／取消／只改期限各自的通知（誰收站內、誰收信）；有改動的期限早於今天 400
- 逾期：端點的 overdueDays 條件（洽談中、期限已過、自指派後沒進度）、每日排程的收件人（含退路）與只提醒一次、換人／改期重新武裝
- 信件：新 mail type 登記齊全（mail_types、通知偏好），真的寄信函式收件人與主旨
- migration 0003：用 T73 之後（含舊進度文字）的資料實測，冪等
"""
import sqlite3
import threading
import types
from datetime import date, datetime, timedelta

import pytest

import db
from modules.crm import api as crm

def TODAY():                  # 不在 import 時讀時鐘（守門 test_no_import_time_clock）
    return date.today()


def FUT():
    return (date.today() + timedelta(days=30)).isoformat()


def FUT2():
    return (date.today() + timedelta(days=45)).isoformat()


def PAST():
    return (date.today() - timedelta(days=3)).isoformat()


# ─────────────────────────── helpers ───────────────────────────

def _login(client, make_user, username, role="sales", modules=("dev_crm",)):
    name, pw = make_user(username=username, role=role, modules=None if modules is None else list(modules))
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _q(sql, *args):
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _x(sql, *args):
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _uid(username):
    return _q("SELECT id FROM users WHERE username=?", username)[0]["id"]


def _case(cid):
    return _q("SELECT * FROM dev_cases WHERE id=?", cid)[0]


def _progress(cid):
    return _q("SELECT * FROM dev_case_progress WHERE case_id=? ORDER BY id", cid)


def _notices(username, type_=None):
    sql = "SELECT * FROM notifications WHERE username=?" + (" AND type=?" if type_ else "") + " ORDER BY id"
    return _q(sql, *( (username, type_) if type_ else (username,) ))


def _make_case(client, owner, **extra):
    body = {"case_name": "進度重設計案", "customer_name": "客戶"}
    body.update(extra)
    r = client.post("/api/dev-cases", headers=owner, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _assign(client, h, cid, to, deadline=None):
    return client.patch(f"/api/dev-cases/{cid}/assign", headers=h, json={"assignedTo": to, "replyDeadline": deadline})


def _post(client, h, cid, content="已拜訪客戶，等報價"):
    return client.post(f"/api/dev-cases/{cid}/progress", headers=h, json={"content": content})


def _get_case(client, h, cid):
    r = client.get(f"/api/dev-cases/{cid}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def world(client, make_user):
    """owner（建立者／業務）、admin、superadmin、a（被指派人）、b（另一位成員）、out（沒有 dev_crm 模組）；一張案件 cid。"""
    w = types.SimpleNamespace(client=client)
    w.owner = _login(client, make_user, "pr_owner")
    w.admin = _login(client, make_user, "pr_admin", role="admin", modules=None)
    w.sup = _login(client, make_user, "pr_sup", role="superadmin", modules=None)
    w.a = _login(client, make_user, "pr_a")
    w.b = _login(client, make_user, "pr_b")
    w.out = _login(client, make_user, "pr_out", modules=("quotation",))
    w.ida, w.idb, w.idadmin = _uid("pr_a"), _uid("pr_b"), _uid("pr_admin")
    w.cid = _make_case(client, w.owner)
    return w


@pytest.fixture()
def sync_mail(monkeypatch):
    """把背景寄信改成當場執行並記下呼叫：assigned（既有指派信）、overdue（新逾期信）。"""
    calls = types.SimpleNamespace(assigned=[], overdue=[])
    monkeypatch.setattr(crm, "spawn_bg_thread", lambda fn, args=(), kwargs=None, daemon=True: fn(*args))
    monkeypatch.setattr(crm, "notify_dev_case_assigned", lambda *a, **k: calls.assigned.append(a))
    monkeypatch.setattr(crm, "notify_dev_case_reply_overdue", lambda *a, **k: calls.overdue.append(a))

    class _Sync:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._t, self._a, self._k = target, args, kwargs or {}

        def start(self):
            self._t(*self._a, **self._k)

    monkeypatch.setattr(crm, "threading", types.SimpleNamespace(Thread=_Sync, Timer=threading.Timer))
    return calls


# ─────────────────────────── 進度回報：權限 ───────────────────────────

def test_progress_endpoints_require_login(client, world):
    assert client.post(f"/api/dev-cases/{world.cid}/progress", json={"content": "x"}).status_code == 401
    assert client.get(f"/api/dev-cases/{world.cid}/progress").status_code == 401
    assert _progress(world.cid) == []


def test_only_the_current_assignee_can_add_progress_and_admins_are_read_only(client, world):
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200
    for who, h in (("管理員", world.admin), ("最高管理者", world.sup), ("建立者（業務）", world.owner),
                   ("另一位成員", world.b), ("沒有模組權限的人", world.out)):
        r = _post(client, h, world.cid, "我亂寫")
        assert r.status_code == 403, (who, r.text)
    assert _progress(world.cid) == []                                       # 一筆都沒寫進去
    assert _case(world.cid)["progress_report"] == ""                        # 舊欄位也沒被碰
    r = _post(client, world.a, world.cid)                                    # 正對照：被指派人本人可以
    assert r.status_code == 201, r.text


def test_an_admin_who_is_the_current_assignee_can_add_progress(client, world):
    assert _assign(client, world.admin, world.cid, world.idadmin, FUT()).status_code == 200      # 主持裁示：管理員本人就是現任負責人 ⇒ 可寫
    r = _post(client, world.admin, world.cid, "管理員自己負責，自己回報")
    assert r.status_code == 201, r.text
    assert [p["author_id"] for p in _progress(world.cid)] == [world.idadmin]
    assert _post(client, world.sup, world.cid, "超管不是被指派人").status_code == 403           # 正對照：別的管理員還是 403
    assert _post(client, world.a, world.cid, "非被指派人").status_code == 403


def test_nobody_can_add_progress_when_the_case_is_unassigned(client, world):
    for h in (world.admin, world.sup, world.owner, world.a):
        assert _post(client, h, world.cid).status_code == 403
    assert _progress(world.cid) == []


def test_progress_on_a_missing_case_is_404(client, world):
    assert _post(client, world.a, 999999).status_code == 404
    assert client.get("/api/dev-cases/999999/progress", headers=world.a).status_code == 404


# ─────────────────────────── 進度回報：內容與寫入 ───────────────────────────

def test_progress_content_must_be_1_to_4000_chars_after_trim(client, world):
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200
    for bad in ("", "   ", "\n\t "):
        assert _post(client, world.a, world.cid, bad).status_code == 400, repr(bad)
    assert _post(client, world.a, world.cid, "x" * 4001).status_code == 400
    assert client.post(f"/api/dev-cases/{world.cid}/progress", headers=world.a, json={"content": 123}).status_code == 422
    assert _progress(world.cid) == []
    assert _post(client, world.a, world.cid, "  " + "y" * 4000 + "  ").status_code == 201     # 去頭尾空白後剛好 4000
    assert _progress(world.cid)[0]["content"] == "y" * 4000


def test_adding_progress_writes_the_row_bumps_updated_at_and_audits_only_a_summary(client, world):
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200
    _x("UPDATE dev_cases SET updated_at='2020-01-01 00:00:00' WHERE id=?", world.cid)
    long_text = "進度" * 50                                                     # 100 字：超過 40 字的摘要長度
    r = _post(client, world.a, world.cid, long_text)
    assert r.status_code == 201, r.text
    (row,) = _progress(world.cid)
    assert (row["author_id"], row["content"]) == (world.ida, long_text) and row["created_at"] >= "2026"
    assert _case(world.cid)["updated_at"] == row["created_at"] != "2020-01-01 00:00:00"      # 算真活動：重置停滯計時
    body = r.json()
    assert body["entry"]["id"] == row["id"] and body["entry"]["authorName"] and body["entry"]["legacy"] is False
    assert body["case"]["currentProgress"]["content"] == long_text and body["case"]["progressCount"] == 1
    (aud,) = _q("SELECT * FROM audit_log WHERE action='dev_case.progress' AND target_id=?", str(world.cid))
    assert aud["target_label"] == long_text[:40] + "…" and long_text not in (aud["detail"] or "")   # 全文不進稽核


def test_progress_is_append_only_there_is_no_edit_or_delete_endpoint(client, world):
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200
    assert _post(client, world.a, world.cid).status_code == 201
    pid = _progress(world.cid)[0]["id"]
    for method in ("patch", "put", "delete"):
        for path in (f"/api/dev-cases/{world.cid}/progress", f"/api/dev-cases/{world.cid}/progress/{pid}"):
            r = getattr(client, method)(path, headers=world.a, json={"content": "改"}) if method != "delete" else client.delete(path, headers=world.a)
            assert r.status_code in (404, 405), (method, path, r.status_code)
    assert [p["content"] for p in _progress(world.cid)] == ["已拜訪客戶，等報價"]


def test_progress_list_is_newest_first_and_visible_to_everyone_who_can_see_the_case(client, world):
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200
    for t in ("第一次", "第二次", "第三次"):
        assert _post(client, world.a, world.cid, t).status_code == 201
    for who, h in (("被指派人", world.a), ("建立者", world.owner), ("管理員", world.admin), ("最高管理者", world.sup)):
        r = client.get(f"/api/dev-cases/{world.cid}/progress", headers=h)
        assert r.status_code == 200, (who, r.text)
        assert [e["content"] for e in r.json()] == ["第三次", "第二次", "第一次"], who
    assert client.get(f"/api/dev-cases/{world.cid}/progress", headers=world.b).status_code == 403      # 看不到案件的人
    assert client.get(f"/api/dev-cases/{world.cid}/progress", headers=world.out).status_code == 403


# ─────────────────────────── 換人：舊進度怎麼處理 ───────────────────────────

def test_reassigning_keeps_the_old_progress_and_current_progress_only_counts_the_new_assignee(client, world):
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200
    assert _post(client, world.a, world.cid, "前任寫的").status_code == 201
    assert _get_case(client, world.admin, world.cid)["currentProgress"]["content"] == "前任寫的"
    # 換人：assigned_at 取成「現在」之後；測試在同一秒內，所以把前任那筆往回調，模擬「前任早就寫了」
    _x("UPDATE dev_case_progress SET created_at='2020-01-01 00:00:00' WHERE case_id=?", world.cid)
    assert _assign(client, world.admin, world.cid, world.idb, FUT()).status_code == 200
    c = _get_case(client, world.admin, world.cid)
    assert c["currentProgress"] is None and c["progressCount"] == 1                       # 新負責人尚未回報；前任的還在歷史裡
    hist = client.get(f"/api/dev-cases/{world.cid}/progress", headers=world.admin).json()
    assert [(e["content"], e["authorId"]) for e in hist] == [("前任寫的", world.ida)]
    assert _post(client, world.a, world.cid, "我已不是負責人").status_code == 403            # 前任失去新增權
    assert _post(client, world.b, world.cid, "新負責人寫的").status_code == 201
    c = _get_case(client, world.admin, world.cid)
    assert c["currentProgress"]["content"] == "新負責人寫的" and c["progressCount"] == 2
    hist = client.get(f"/api/dev-cases/{world.cid}/progress", headers=world.admin).json()
    assert [e["authorId"] for e in hist] == [world.idb, world.ida]                       # 時間軸兩人都在、各自標作者


def test_legacy_progress_without_an_author_is_flagged_as_legacy(client, world):
    _x("INSERT INTO dev_case_progress (case_id, author_id, content, created_at) VALUES (?,NULL,'舊文字','2026-11-01 09:00:00')", world.cid)
    (e,) = client.get(f"/api/dev-cases/{world.cid}/progress", headers=world.admin).json()
    assert e["legacy"] is True and e["authorId"] is None and e["authorName"] == "" and e["content"] == "舊文字"


# ─────────────────────────── 指派：只有真的變才動作 ───────────────────────────

def test_saving_the_same_assignee_and_deadline_again_changes_nothing(client, world, sync_mail):
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200
    _x("UPDATE dev_cases SET updated_at='2020-01-01 00:00:00' WHERE id=?", world.cid)       # 讓「updated_at 沒被碰」看得出來
    before_case = _case(world.cid)
    n_notice = {u: len(_notices(u)) for u in ("pr_a", "pr_b", "pr_admin")}
    n_audit = len(_q("SELECT id FROM audit_log WHERE action='dev_case.assign'"))
    n_mail = len(sync_mail.assigned)
    r = _assign(client, world.admin, world.cid, world.ida, FUT())
    assert r.status_code == 200 and r.json()["assignedToId"] == world.ida
    assert _case(world.cid) == before_case                                                 # DB 逐欄相同（含 updated_at、assigned_at）
    assert {u: len(_notices(u)) for u in ("pr_a", "pr_b", "pr_admin")} == n_notice
    assert len(_q("SELECT id FROM audit_log WHERE action='dev_case.assign'")) == n_audit
    assert len(sync_mail.assigned) == n_mail
    r = client.patch(f"/api/dev-cases/{world.cid}/assign", headers=world.admin, json={"assignedTo": world.ida, "replyDeadline": ""})
    assert r.status_code == 200 and _case(world.cid)["reply_deadline"] is None            # 正對照：真的改了（清除期限）就會動


def test_reassigning_notifies_the_new_assignee_by_site_and_mail_and_the_predecessor_by_site_only(client, world, sync_mail):
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200
    assert len(sync_mail.assigned) == 1 and sync_mail.assigned[0][3] == "pr_a"
    case = _case(world.cid)
    assert case["assigned_at"] and case["assigned_by"] == world.idadmin
    assert _notices("pr_a", "dev_case_unassigned") == []
    assert _assign(client, world.admin, world.cid, world.idb, FUT2()).status_code == 200
    assert len(_notices("pr_b", "dev_case_assigned")) == 1 and sync_mail.assigned[-1][3] == "pr_b"
    (gone,) = _notices("pr_a", "dev_case_unassigned")
    assert "不再負責" in gone["message"] and "進度重設計案" in gone["message"]
    assert len(sync_mail.assigned) == 2                                                     # 前任沒有信
    case = _case(world.cid)
    assert case["assigned_to"] == world.idb and case["reply_deadline"] == FUT2() and case["assigned_by"] == world.idadmin
    (aud,) = _q("SELECT * FROM audit_log WHERE action='dev_case.assign' AND target_id=? ORDER BY id DESC LIMIT 1", str(world.cid))
    assert "pr_b" in aud["target_label"] or "→" in aud["target_label"]


def test_cancelling_the_assignment_notifies_only_the_predecessor_and_clears_assigned_at(client, world, sync_mail):
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200
    n_mail = len(sync_mail.assigned)
    assert _assign(client, world.admin, world.cid, None, None).status_code == 200
    case = _case(world.cid)
    assert (case["assigned_to"], case["assigned_at"], case["assigned_by"], case["reply_deadline"]) == (None, None, None, None)
    (gone,) = _notices("pr_a", "dev_case_unassigned")
    assert "取消指派" in gone["message"]
    assert len(sync_mail.assigned) == n_mail
    assert _notices("pr_b") == []


def test_changing_only_the_deadline_sends_a_site_notice_without_mail_and_keeps_assigned_at(client, world, sync_mail):
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200
    before = _case(world.cid)
    n_mail = len(sync_mail.assigned)
    _x("UPDATE dev_cases SET updated_at='2020-01-01 00:00:00' WHERE id=?", world.cid)
    assert _assign(client, world.admin, world.cid, world.ida, FUT2()).status_code == 200
    after = _case(world.cid)
    assert after["reply_deadline"] == FUT2() and after["assigned_at"] == before["assigned_at"] and after["assigned_by"] == before["assigned_by"]
    assert after["updated_at"] != "2020-01-01 00:00:00"                                      # 真的改了 ⇒ 算更新
    (n,) = _notices("pr_a", "dev_case_deadline_changed")
    assert FUT2() in n["message"]
    assert len(sync_mail.assigned) == n_mail                                                 # 不寄信
    assert _notices("pr_a", "dev_case_unassigned") == []


def test_a_deadline_that_is_changed_to_a_past_date_is_rejected_but_an_unchanged_past_one_is_not_checked(client, world, sync_mail):
    r = _assign(client, world.admin, world.cid, world.ida, PAST())
    assert r.status_code == 400 and "早於今天" in r.text
    c = _case(world.cid)
    assert (c["assigned_to"], c["reply_deadline"]) == (None, None) and _notices("pr_a") == []         # 整筆不生效
    assert _assign(client, world.admin, world.cid, world.ida, TODAY().isoformat()).status_code == 200  # 正對照：今天可以
    _x("UPDATE dev_cases SET reply_deadline=? WHERE id=?", PAST(), world.cid)                          # 期限之後自然過期
    assert _assign(client, world.admin, world.cid, world.ida, PAST()).status_code == 200               # 沒改動的值不檢查（純重存）
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200                # 改成未來可以
    bad = client.patch(f"/api/dev-cases/{world.cid}/assign", headers=world.admin, json={"assignedTo": world.ida, "replyDeadline": "20261201"})
    assert bad.status_code == 400 and "格式" in bad.text


def test_reassigning_or_first_assigning_with_an_already_past_deadline_is_rejected_but_resaving_the_same_is_a_noop(client, world, sync_mail):
    _x("UPDATE dev_cases SET reply_deadline=? WHERE id=?", PAST(), world.cid)                    # 舊案：期限早就過了、還沒指派
    r = _assign(client, world.admin, world.cid, world.ida, PAST())                              # 首次指派沿用過期期限（值沒變）
    assert r.status_code == 400 and "早於今天" in r.text
    c = _case(world.cid)
    assert (c["assigned_to"], c["reply_deadline"]) == (None, PAST()) and _notices("pr_a") == []  # 整筆不生效
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200
    _x("UPDATE dev_cases SET reply_deadline=? WHERE id=?", PAST(), world.cid)                    # 期限之後自然過期
    r = _assign(client, world.admin, world.cid, world.idb, PAST())                              # A→B 期限不變、已過期
    assert r.status_code == 400 and _case(world.cid)["assigned_to"] == world.ida
    assert _assign(client, world.admin, world.cid, world.idb, FUT2()).status_code == 200         # 正對照：換人並給未來期限可以
    assert _assign(client, world.admin, world.cid, None, PAST()).status_code == 200              # 取消指派不檢查期限（期限一併清空）
    assert _case(world.cid)["reply_deadline"] is None


def test_cancelling_clears_the_deadline_even_if_one_is_sent(client, world):
    assert _assign(client, world.admin, world.cid, world.ida, FUT()).status_code == 200
    assert _assign(client, world.admin, world.cid, None, FUT2()).status_code == 200
    c = _case(world.cid)
    assert (c["assigned_to"], c["reply_deadline"], c["assigned_at"]) == (None, None, None)


def test_assign_still_validates_the_target_when_the_assignee_changes(client, world, make_user):
    _login(client, make_user, "pr_nomod", modules=("quotation",))
    assert _assign(client, world.admin, world.cid, 999999, FUT()).status_code == 400
    assert _assign(client, world.admin, world.cid, _uid("pr_nomod"), FUT()).status_code == 400
    assert _case(world.cid)["assigned_to"] is None
    assert _assign(client, world.owner, world.cid, world.ida, FUT()).status_code == 403              # 非管理員


# ─────────────────────────── 逾期：端點 ───────────────────────────

def _seed_assigned(cid, to, by, deadline, assigned_at="2026-11-01 09:00:00", status="洽談中"):
    _x("UPDATE dev_cases SET assigned_to=?, assigned_by=?, assigned_at=?, reply_deadline=?, status=? WHERE id=?",
       to, by, assigned_at, deadline, status, cid)


def test_overdue_days_show_only_for_open_cases_past_deadline_without_a_report_from_the_current_assignee(client, world):
    cid = world.cid
    _seed_assigned(cid, world.ida, world.idadmin, PAST())
    assert _get_case(client, world.admin, cid)["overdueDays"] == 3
    assert next(c for c in client.get("/api/dev-cases", headers=world.admin).json() if c["id"] == cid)["overdueDays"] == 3    # 清單也有
    _seed_assigned(cid, world.ida, world.idadmin, TODAY().isoformat())
    assert _get_case(client, world.admin, cid)["overdueDays"] is None                        # 期限當天不算
    _seed_assigned(cid, world.ida, world.idadmin, None)
    assert _get_case(client, world.admin, cid)["overdueDays"] is None                        # 沒設期限
    for st in ("成案", "未成案", "暫擱置"):
        _seed_assigned(cid, world.ida, world.idadmin, PAST(), status=st)
        assert _get_case(client, world.admin, cid)["overdueDays"] is None, st
    _seed_assigned(cid, None, None, PAST(), assigned_at=None)
    assert _get_case(client, world.admin, cid)["overdueDays"] is None                        # 沒人被指派
    _seed_assigned(cid, world.ida, world.idadmin, PAST())
    assert _get_case(client, world.admin, cid)["overdueDays"] == 3                           # 還原後又逾期
    assert _post(client, world.a, cid).status_code == 201                                    # 被指派人一回報就消失
    assert _get_case(client, world.admin, cid)["overdueDays"] is None


def test_a_report_written_before_the_current_assignment_does_not_clear_overdue(client, world):
    cid = world.cid
    _x("INSERT INTO dev_case_progress (case_id, author_id, content, created_at) VALUES (?,?,?,?)", cid, world.ida, "很久以前寫的", "2026-10-01 09:00:00")
    _seed_assigned(cid, world.ida, world.idadmin, PAST(), assigned_at="2026-11-01 09:00:00")     # 之後又（重新）指派給同一人
    c = _get_case(client, world.admin, cid)
    assert c["overdueDays"] == 3 and c["currentProgress"] is None and c["progressCount"] == 1
    _x("INSERT INTO dev_case_progress (case_id, author_id, content, created_at) VALUES (?,?,?,?)", cid, world.idb, "別人寫的", "2026-11-02 09:00:00")
    assert _get_case(client, world.admin, cid)["overdueDays"] == 3                           # 別人（非現任）寫的不算


# ─────────────────────────── 逾期：每日排程 ───────────────────────────

def test_the_daily_job_notifies_assignee_and_assigner_once_by_site_and_mail(client, world, sync_mail):
    cid = world.cid
    _seed_assigned(cid, world.ida, world.idadmin, PAST())
    crm._check_dev_case_reply_overdue()
    for u in ("pr_a", "pr_admin"):
        (n,) = _notices(u, "dev_case_reply_overdue")
        assert n["ref_id"] == str(cid) and PAST() in n["message"] and "3 天" in n["message"]
    assert _notices("pr_sup", "dev_case_reply_overdue") == [] and _notices("pr_b", "dev_case_reply_overdue") == []   # 沒被列入的人沒有
    (call,) = sync_mail.overdue
    assert call[0] == cid and call[2] == PAST() and call[3] == 3 and sorted(call[5]) == ["pr_a", "pr_admin"]
    crm._check_dev_case_reply_overdue()                                                      # 再跑一次：同一組合不重複提醒
    assert len(_notices("pr_a", "dev_case_reply_overdue")) == 1 and len(sync_mail.overdue) == 1


def test_the_daily_job_ignores_a_report_written_before_the_current_assignment(client, world, sync_mail):
    cid = world.cid
    _x("INSERT INTO dev_case_progress (case_id, author_id, content, created_at) VALUES (?,?,?,?)", cid, world.ida, "很久以前寫的", "2026-10-01 09:00:00")
    _seed_assigned(cid, world.ida, world.idadmin, PAST(), assigned_at="2026-11-01 09:00:00")     # 之後又（重新）指派給同一人，舊回報早於 assigned_at
    crm._check_dev_case_reply_overdue()
    (call,) = sync_mail.overdue                                                              # 排程層：舊回報不算，仍要提醒（突變掉 SQL 的 assigned_at 下界就會紅）
    assert call[0] == cid and sorted(call[5]) == ["pr_a", "pr_admin"]
    _x("INSERT INTO dev_case_progress (case_id, author_id, content, created_at) VALUES (?,?,?,?)", cid, world.ida, "指派後寫的", "2026-11-02 09:00:00")
    _seed_assigned(cid, world.ida, world.idadmin, (TODAY() - timedelta(days=1)).isoformat(), assigned_at="2026-11-01 09:00:00")
    crm._check_dev_case_reply_overdue()
    assert len(sync_mail.overdue) == 1                                                       # 指派後有回報 ⇒ 不再提醒（正對照）


def test_changing_the_deadline_or_the_assignee_rearms_the_reminder(client, world, sync_mail):
    cid = world.cid
    _seed_assigned(cid, world.ida, world.idadmin, PAST())
    crm._check_dev_case_reply_overdue()
    assert len(sync_mail.overdue) == 1
    _x("UPDATE dev_cases SET reply_deadline=? WHERE id=?", (TODAY() - timedelta(days=1)).isoformat(), cid)      # 改期限（仍逾期）
    crm._check_dev_case_reply_overdue()
    assert len(sync_mail.overdue) == 2
    _seed_assigned(cid, world.idb, world.idadmin, (TODAY() - timedelta(days=1)).isoformat())                    # 換人（同期限）
    crm._check_dev_case_reply_overdue()
    assert len(sync_mail.overdue) == 3 and len(_notices("pr_b", "dev_case_reply_overdue")) == 1
    assert sorted(sync_mail.overdue[-1][5]) == ["pr_admin", "pr_b"]


def test_the_daily_job_skips_cases_that_are_not_overdue_or_already_reported(client, world, sync_mail, make_user):
    cid = world.cid
    _seed_assigned(cid, world.ida, world.idadmin, TODAY().isoformat())
    crm._check_dev_case_reply_overdue()                                                      # 期限當天
    _seed_assigned(cid, world.ida, world.idadmin, None)
    crm._check_dev_case_reply_overdue()                                                      # 沒期限
    _seed_assigned(cid, world.ida, world.idadmin, PAST(), status="成案")
    crm._check_dev_case_reply_overdue()                                                      # 已成案
    _seed_assigned(cid, None, None, PAST(), assigned_at=None)
    crm._check_dev_case_reply_overdue()                                                      # 沒人被指派
    _seed_assigned(cid, world.ida, world.idadmin, PAST())
    assert _post(client, world.a, cid).status_code == 201
    crm._check_dev_case_reply_overdue()                                                      # 被指派人已回報
    _x("UPDATE dev_cases SET is_deleted=1 WHERE id=?", cid)
    _x("DELETE FROM dev_case_progress WHERE case_id=?", cid)
    crm._check_dev_case_reply_overdue()                                                      # 已刪除的案件
    assert sync_mail.overdue == [] and _q("SELECT id FROM notifications WHERE type='dev_case_reply_overdue'") == []
    _x("UPDATE dev_cases SET is_deleted=0 WHERE id=?", cid)
    crm._check_dev_case_reply_overdue()                                                      # 正對照：條件都對就會提醒
    assert len(sync_mail.overdue) == 1


def test_recipients_fall_back_to_all_admins_when_a_party_is_missing_or_inactive(client, world, sync_mail):
    cid = world.cid
    admins = {r["username"] for r in _q("SELECT username FROM users WHERE active=1 AND role IN ('admin','superadmin')")}
    assert {"pr_admin", "pr_sup"} <= admins                                                   # 前提：名單含測試庫自帶的管理員（如 demo），所以用 DB 算期望值
    _seed_assigned(cid, world.ida, None, PAST())                                               # 舊資料：沒有 assigned_by
    crm._check_dev_case_reply_overdue()
    assert set(sync_mail.overdue[-1][5]) == {"pr_a"} | admins                                # 被指派人＋全體 admin／superadmin
    _x("UPDATE users SET active=0 WHERE id=?", world.ida)                                    # 被指派人已停用
    _seed_assigned(cid, world.ida, world.idadmin, (TODAY() - timedelta(days=2)).isoformat())
    crm._check_dev_case_reply_overdue()
    assert set(sync_mail.overdue[-1][5]) == admins                                           # 停用者不收；指派人（admin）在名單內
    _x("UPDATE users SET active=1 WHERE id=?", world.ida)
    _x("UPDATE users SET active=0 WHERE id=?", world.idadmin)                                # 指派人已停用
    _seed_assigned(cid, world.ida, world.idadmin, (TODAY() - timedelta(days=1)).isoformat())
    crm._check_dev_case_reply_overdue()
    assert set(sync_mail.overdue[-1][5]) == {"pr_a"} | (admins - {"pr_admin"})               # 停用的指派人不收，其餘 admin 補上
    _x("UPDATE users SET active=1 WHERE id=?", world.idadmin)
    _seed_assigned(cid, world.ida, world.idadmin, (TODAY() - timedelta(days=4)).isoformat())   # 正對照：兩人都在 ⇒ 只寄這兩人，不驚動其他 admin
    crm._check_dev_case_reply_overdue()
    assert set(sync_mail.overdue[-1][5]) == {"pr_a", "pr_admin"}


def test_the_daily_job_is_part_of_the_scheduled_run(monkeypatch):
    """排程掛上了：_run_all 會呼叫逾期檢查（不然函式寫得再對也永遠不會跑）。"""
    seen = []
    monkeypatch.setattr(crm, "_check_dev_case_stale", lambda: seen.append("stale"))
    monkeypatch.setattr(crm, "_check_dev_case_reply_overdue", lambda: seen.append("overdue"))
    monkeypatch.setattr(crm, "_check_dev_case_hold_expiry", lambda: seen.append("hold"))
    timers = []

    class _T:
        def __init__(self, *a, **k):
            timers.append(a)
            self.daemon = False

        def start(self):
            pass

    monkeypatch.setattr(crm, "threading", types.SimpleNamespace(Timer=_T, Thread=threading.Thread))
    crm.schedule_dev_case_stale_check()
    assert seen == ["stale", "overdue", "hold"]


# ─────────────────────────── 信件登記與寄信函式 ───────────────────────────

def test_the_new_mail_type_is_registered_everywhere_a_mail_type_must_be(client):
    from helpers import mail_types, notification_prefs
    mt = mail_types.get("dev_case_reply_overdue")
    assert mt is not None and mt.category == "business" and mt.group == "none" and mt.event == "被指派人與指派人"
    assert mail_types.subject("dev_case_reply_overdue", "x").startswith("【MOTRIX 系統通知】業務")        # 已登記才會有分類（未登記會寫「未登記」）
    groups = {name: [e for e, _ in events] for name, events in notification_prefs.EVENT_GROUPS}
    assert "dev_case_reply_overdue" in groups["案件與到期提醒"]                                           # 帳號通知偏好看得到、關得掉


def test_the_overdue_mail_function_sends_to_the_given_users_with_the_registered_subject(client, world, monkeypatch):
    from helpers import email_notify
    sent = []
    monkeypatch.setattr(email_notify, "_lookup_emails", lambda names, key=None: [f"{n}@example.test" for n in names] if key == "dev_case_reply_overdue" else [])
    monkeypatch.setattr(email_notify, "_async_send", lambda to, subject, html: sent.append((to, subject, html)))
    email_notify.notify_dev_case_reply_overdue(7, "測試案", PAST(), 3, "小A", ["pr_a", "pr_admin"])
    (to, subject, html), = sent
    assert to == ["pr_a@example.test", "pr_admin@example.test"] and "測試案" in subject
    assert PAST() in html and "3 天" in html and "小A" in html
    sent.clear()
    monkeypatch.setattr(email_notify, "_lookup_emails", lambda names, key=None: [])
    email_notify.notify_dev_case_reply_overdue(7, "測試案", PAST(), 3, "小A", ["pr_a"])           # 沒有有效收件人：不寄、不丟例外
    assert sent == []


# ─────────────────────────── migration 0003 ───────────────────────────

def _t73_db():
    """T73 之後（crm migration 0001、0002 都跑過）的 dev_cases，放幾筆含舊進度文字的資料。"""
    import importlib
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE customers (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
    db._m027_dev_crm(conn)
    importlib.import_module("modules.crm.migrations.0001_dev_cases_referrer").up(conn)
    importlib.import_module("modules.crm.migrations.0002_dev_case_assignment").up(conn)
    rows = [  # (name, assigned_to, deadline, progress, updated_at)
        ("有進度有人", 5, "2026-12-01", "已拜訪，等報價", "2026-11-03 15:00:00"),
        ("有進度沒人", None, None, "舊版管理員在沒指派時填的", "2026-11-02 10:00:00"),
        ("只有指派", 6, "2026-11-20", "", "2026-11-03 16:00:00"),
        ("什麼都沒有", None, None, "", "2026-10-01 08:00:00"),
        ("只有空白進度", 7, None, "   \n", "2026-11-03 17:00:00"),
    ]
    for n, a, d, p, u in rows:
        conn.execute("INSERT INTO dev_cases (case_name, created_at, updated_at, assigned_to, reply_deadline, progress_report) VALUES (?,?,?,?,?,?)",
                     (n, u, u, a, d, p))
    conn.commit()
    return conn


def _mig():
    import importlib
    return importlib.import_module("modules.crm.migrations.0003_dev_case_progress").up


def test_migration_0003_moves_old_progress_text_into_the_new_table_and_is_idempotent():
    conn, up = _t73_db(), _mig()
    assert up(conn) is None
    snap = lambda: ([tuple(r) for r in conn.execute("SELECT case_id, author_id, content, created_at FROM dev_case_progress ORDER BY case_id")],
                    [tuple(r) for r in conn.execute("SELECT id, assigned_to, assigned_at, assigned_by, progress_report FROM dev_cases ORDER BY id")])
    prog, cases = snap()
    assert prog == [(1, 5, "已拜訪，等報價", "2026-11-03 15:00:00"),                           # 作者＝當時的 assigned_to，時間＝updated_at
                    (2, None, "舊版管理員在沒指派時填的", "2026-11-02 10:00:00")]             # 沒有被指派人 ⇒ 作者留空
    by_id = {c[0]: c for c in cases}
    assert by_id[1][2] == "2026-11-03 15:00:00" and by_id[3][2] == "2026-11-03 16:00:00" and by_id[5][2] == "2026-11-03 17:00:00"   # 已指派 ⇒ assigned_at＝updated_at
    assert by_id[2][2] is None and by_id[4][2] is None                                       # 沒人被指派 ⇒ 空
    assert all(c[3] is None for c in cases)                                                  # 舊資料不知道是誰指派的
    assert by_id[1][4] == "已拜訪，等報價"                                                       # 舊欄位保留不動
    for _ in range(3):                                                                       # 冪等：重跑不重複搬、不覆寫
        assert up(conn) is None
    assert snap() == (prog, cases)
    # 搬完那一刻不會因為「assigned_at 很舊、沒有進度」把有回報的案件誤判逾期：條件同排程（NOT EXISTS 被指派人自 assigned_at 之後的進度）
    flagged = [r[0] for r in conn.execute(
        "SELECT d.id FROM dev_cases d WHERE d.assigned_to IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dev_case_progress p "
        "WHERE p.case_id=d.id AND p.author_id=d.assigned_to AND p.created_at >= COALESCE(d.assigned_at,''))")]
    assert 1 not in flagged                                                                  # 有回報的不在名單


def test_migration_0003_does_not_touch_cases_that_already_have_progress_rows_and_reports_a_missing_table():
    conn, up = _t73_db(), _mig()
    conn.execute("CREATE TABLE IF NOT EXISTS dev_case_progress (id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL, author_id INTEGER, owner_unit_id INTEGER NOT NULL DEFAULT 1, content TEXT NOT NULL, created_at TEXT NOT NULL)")
    conn.execute("INSERT INTO dev_case_progress (case_id, author_id, content, created_at) VALUES (1, 5, '新系統寫的', '2026-11-04 09:00:00')")
    conn.commit()
    assert up(conn) is None
    assert [r[0] for r in conn.execute("SELECT content FROM dev_case_progress WHERE case_id=1")] == ["新系統寫的"]   # 該案已有進度列 ⇒ 不再搬舊欄位
    bare = sqlite3.connect(":memory:")
    assert isinstance(up(bare), str)                                                         # dev_cases 不存在 ⇒ 回原因字串（未完成，下次再補）


def test_migration_0003_runs_against_the_real_migrated_schema_with_old_progress_text(client):
    """真實庫（所有 migration 都跑過）：塞一筆 T73 風格的舊進度，再跑一次 up() ⇒ 搬進新表，且不碰別的案件。"""
    up = _mig()
    _x("INSERT INTO dev_cases (case_name, created_at, updated_at, assigned_to, progress_report) VALUES ('實庫舊案','2026-11-03 10:00:00','2026-11-03 10:00:00',NULL,'實庫舊進度')")
    cid = _q("SELECT id FROM dev_cases WHERE case_name='實庫舊案'")[0]["id"]
    conn = db.get_db()
    try:
        assert up(conn) is None
        conn.commit()
    finally:
        conn.close()
    assert [(p["author_id"], p["content"]) for p in _progress(cid)] == [(None, "實庫舊進度")]
    conn = db.get_db()
    try:
        assert up(conn) is None
        conn.commit()
    finally:
        conn.close()
    assert len(_progress(cid)) == 1


def test_module_declares_migration_3_and_the_new_table():
    import json
    from pathlib import Path
    import modules.crm as m
    assert [v for v, _ in m.MODULE.migrations][:3] == [1, 2, 3]       # 0004（開發記錄批示）之後只增不改：前三支固定
    meta = json.loads((Path(m.__file__).parent / "module.json").read_text(encoding="utf-8"))
    assert "dev_case_progress" in meta["tables"] and "dev_case_progress" in [t["name"] for t in meta["data"]["tables"]]


def test_migration_0003_copies_the_case_unit_onto_migrated_progress_rows_and_new_table_has_the_unit_key():
    import importlib
    import sqlite3
    up = importlib.import_module("modules.crm.migrations.0003_dev_case_progress").up
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE dev_cases (id INTEGER PRIMARY KEY, owner_unit_id INTEGER NOT NULL DEFAULT 1, created_at TEXT, updated_at TEXT, assigned_to INTEGER, progress_report TEXT)")
    conn.execute("INSERT INTO dev_cases VALUES (1, 7, '2026-11-01 08:00:00', '2026-11-02 09:00:00', 5, '舊進度')")
    conn.execute("INSERT INTO dev_cases VALUES (2, 3, '2026-11-01 08:00:00', '2026-11-02 09:00:00', 5, '')")
    assert up(conn) is None
    assert [tuple(r) for r in conn.execute("SELECT case_id, owner_unit_id FROM dev_case_progress")] == [(1, 7)]
    info = {r[1]: r for r in conn.execute("PRAGMA table_info(dev_case_progress)")}
    assert info["owner_unit_id"][2].upper() == "INTEGER" and info["owner_unit_id"][3] == 1 and str(info["owner_unit_id"][4]) == "1"

