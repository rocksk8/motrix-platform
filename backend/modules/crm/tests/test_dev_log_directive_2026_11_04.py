"""開發記錄「批示」（crm v4，2026-11-04；docs/platform/plans/DEV-LOG-DIRECTIVE-PLAN.md）。

觀測點是資料庫（`dev_log_directive`、`dev_log_directive_target`、`dev_cases`、`dev_logs`、`notifications`、`audit_log`）與實際端點呼叫，
不只看回應文字。

涵蓋：
- 權限：未登入 401；沒有能力 403；能力可由權限矩陣勾給一般成員（真的寫 perm_user_overrides）；勾了但沒有業務開發模組仍 403；`canDirect` 旗標
- 對象驗證：至少 1 人、最多 10 人、不含自己、去重、不存在／停用／無模組／看不到案件各 400 並列名字；log 不屬該案 400；內容空白／過長 400
- 可見度（使用者裁示）：只有管理員、作者、對象看得到；其他人 GET 看不到任何一筆、回覆 404（不洩漏存在）
- 回覆：對象與作者可回、管理員但非作者／對象 403、不能回覆回覆、replied_at 只記首次、各方向的站內通知
- 通知：站內給所有對象；信只給 must_reply=1 且本文不含批示全文；不呼叫 notify_module_activity
- 不連動：dev_cases.updated_at 不變、dev_logs 沒有新列也沒有「新增拜訪記錄」稽核
- 擋刪：已有批示的紀錄 DELETE 409（單一陳述不交錯）、沒有批示的紀錄照常刪、既有編輯 PUT 不受影響
- migration 0004：新庫實測、冪等；能力登錄
"""
import sqlite3
import types
from datetime import date

import pytest

import db
from modules.crm import api as crm


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


def _notices(username, type_=None):
    sql = "SELECT * FROM notifications WHERE username=?" + (" AND type=?" if type_ else "") + " ORDER BY id"
    return _q(sql, *((username, type_) if type_ else (username,)))


def _make_case(client, owner, sales, name="批示測試案"):
    r = client.post("/api/dev-cases", headers=owner, json={"case_name": name, "customer_name": "客戶", "sales_persons": sales})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _make_log(client, h, cid, by, content="今天拜訪客戶，對方想殺價"):
    r = client.post(f"/api/dev-cases/{cid}/logs", headers=h,
                    data={"log_date": date.today().isoformat(), "log_by": str(by), "content": content})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _direct(client, h, cid, log_id, content="這筆報價太低，下週前回我怎麼處理", targets=None):
    return client.post(f"/api/dev-cases/{cid}/directives", headers=h,
                       json={"logId": log_id, "content": content, "targets": targets or []})


def _t(uid, must=True):
    return {"userId": uid, "mustReply": must}


def _reply(client, h, cid, did, content="收到，下週一前回覆"):
    return client.post(f"/api/dev-cases/{cid}/directives/{did}/replies", headers=h, json={"content": content})


def _list(client, h, cid):
    r = client.get(f"/api/dev-cases/{cid}/directives", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def world(client, make_user):
    """owner（建立者）、admin、sup、a／b（案件的業務）、c（有 dev_crm 但不在這個案件）、out（沒有 dev_crm）；案件 cid；a 寫的一筆紀錄 log。"""
    w = types.SimpleNamespace(client=client)
    w.owner = _login(client, make_user, "dr_owner")
    w.admin = _login(client, make_user, "dr_admin", role="admin", modules=None)
    w.sup = _login(client, make_user, "dr_sup", role="superadmin", modules=None)
    w.a = _login(client, make_user, "dr_a")
    w.b = _login(client, make_user, "dr_b")
    w.c = _login(client, make_user, "dr_c")
    w.out = _login(client, make_user, "dr_out", modules=("quotation",))
    w.ida, w.idb, w.idc, w.idout = _uid("dr_a"), _uid("dr_b"), _uid("dr_c"), _uid("dr_out")
    w.idadmin, w.idowner = _uid("dr_admin"), _uid("dr_owner")
    w.cid = _make_case(client, w.owner, [w.ida, w.idb])
    w.log = _make_log(client, w.a, w.cid, w.ida)
    return w


@pytest.fixture()
def sync_mail(monkeypatch):
    """背景寄信改成當場執行並記下呼叫；順手記下有沒有人呼叫 notify_module_activity。"""
    calls = types.SimpleNamespace(directive=[], activity=[])
    monkeypatch.setattr(crm, "spawn_bg_thread", lambda fn, args=(), kwargs=None, daemon=True: fn(*args))
    monkeypatch.setattr(crm, "notify_dev_log_directive", lambda *a, **k: calls.directive.append(a))
    monkeypatch.setattr(crm, "notify_module_activity", lambda *a, **k: calls.activity.append(a))
    return calls


# ─────────────────────────── 權限 ───────────────────────────

def test_all_three_endpoints_require_login(client, world):
    assert client.get(f"/api/dev-cases/{world.cid}/directives").status_code == 401
    assert client.post(f"/api/dev-cases/{world.cid}/directives", json={"logId": world.log, "content": "x", "targets": []}).status_code == 401
    assert client.post(f"/api/dev-cases/{world.cid}/directives/1/replies", json={"content": "x"}).status_code == 401


def test_a_member_without_the_capability_gets_403_and_nothing_is_written(client, world, sync_mail):
    r = _direct(client, world.owner, world.cid, world.log, targets=[_t(world.ida)])
    assert r.status_code == 403 and "crm.dev_log_directive.comment" in r.text
    assert _q("SELECT id FROM dev_log_directive") == [] and _notices("dr_a") == []
    assert _list(client, world.owner, world.cid)["canDirect"] is False            # 前端據此不顯示「批示」鈕
    r = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)])    # 正對照：管理員可以
    assert r.status_code == 201, r.text
    assert _list(client, world.admin, world.cid)["canDirect"] is True


def test_superadmin_can_direct_too(client, world, sync_mail):
    assert _direct(client, world.sup, world.cid, world.log, targets=[_t(world.ida)]).status_code == 201


def test_the_capability_can_be_granted_to_an_ordinary_member_through_the_matrix(client, world, sync_mail):
    """權限矩陣的真實路徑：寫 perm_user_overrides ⇒ perm.invalidate() ⇒ 該成員可以下批示；撤掉就不行（不是寫死管理員）。"""
    from helpers import perm
    now = "2026-11-04 12:00:00"
    _x("INSERT INTO perm_user_overrides (user_id, cap, effect, set_by, set_at, reason) VALUES (?,?,?,?,?,?)",
       world.idowner, "crm.dev_log_directive.comment", "allow", world.idadmin, now, "測試")
    perm.invalidate()
    try:
        assert _list(client, world.owner, world.cid)["canDirect"] is True
        r = _direct(client, world.owner, world.cid, world.log, targets=[_t(world.ida)])
        assert r.status_code == 201, r.text
        # 勾了能力但沒有業務開發模組的人，仍被模組那一層擋下
        _x("INSERT INTO perm_user_overrides (user_id, cap, effect, set_by, set_at, reason) VALUES (?,?,?,?,?,?)",
           world.idout, "crm.dev_log_directive.comment", "allow", world.idadmin, now, "測試")
        perm.invalidate()
        assert _direct(client, world.out, world.cid, world.log, targets=[_t(world.ida)]).status_code == 403
        assert client.get(f"/api/dev-cases/{world.cid}/directives", headers=world.out).status_code == 403
    finally:
        _x("DELETE FROM perm_user_overrides WHERE cap=?", "crm.dev_log_directive.comment")
        perm.invalidate()
    assert _direct(client, world.owner, world.cid, world.log, targets=[_t(world.ida)]).status_code == 403


def test_the_capability_is_registered_with_a_seed_equal_to_admin_only():
    from core import capabilities as cap
    c = cap.get("crm.dev_log_directive.comment")
    assert c is not None and c.roles == frozenset({"admin"}) and c.delegable and c.risk == "mid"
    assert c.label == "對開發記錄下批示" and "業務開發模組" in c.impact


def test_a_user_who_cannot_see_the_case_cannot_direct_on_it(client, world):
    # 管理員一定看得到案件，所以用「勾了能力的成員 c（不在案件上）」驗證第三道閘
    from helpers import perm
    _x("INSERT INTO perm_user_overrides (user_id, cap, effect, set_by, set_at, reason) VALUES (?,?,?,?,?,?)",
       world.idc, "crm.dev_log_directive.comment", "allow", world.idadmin, "2026-11-04 12:00:00", "測試")
    perm.invalidate()
    try:
        r = _direct(client, world.c, world.cid, world.log, targets=[_t(world.ida)])
        assert r.status_code == 403 and "案件" in r.text
    finally:
        _x("DELETE FROM perm_user_overrides WHERE cap=?", "crm.dev_log_directive.comment")
        perm.invalidate()


# ─────────────────────────── 輸入與對象驗證 ───────────────────────────

def test_content_and_target_validation(client, world, sync_mail):
    ok = [_t(world.ida)]
    assert _direct(client, world.admin, world.cid, world.log, content="   ", targets=ok).status_code == 400
    assert _direct(client, world.admin, world.cid, world.log, content="字" * 4001, targets=ok).status_code == 400
    assert _direct(client, world.admin, world.cid, world.log, content="字" * 4000, targets=ok).status_code == 201     # 邊界：4000 可以
    r = _direct(client, world.admin, world.cid, world.log, targets=[])
    assert r.status_code == 400 and "至少" in r.text
    r = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.idadmin), _t(world.ida)])
    assert r.status_code == 400 and "自己" in r.text
    n = len(_q("SELECT id FROM dev_log_directive"))
    assert n == 1                                                                              # 所有失敗都沒有寫入


def test_targets_are_deduplicated_and_any_must_reply_wins(client, world, sync_mail):
    r = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida, False), _t(world.ida, True), _t(world.idb, False)])
    assert r.status_code == 201, r.text
    rows = _q("SELECT user_id, must_reply FROM dev_log_directive_target ORDER BY user_id")
    assert rows == [{"user_id": world.ida, "must_reply": 1}, {"user_id": world.idb, "must_reply": 0}]


def test_invalid_targets_are_rejected_with_their_names(client, world, make_user):
    _login(client, make_user, "dr_gone")                                       # 先有帳號再停用
    gone = _uid("dr_gone")
    _x("UPDATE users SET active=0 WHERE id=?", gone)
    for uid, hint in ((gone, "已停用"), (world.idout, "沒有業務開發模組權限"), (world.idc, "看不到此案件"), (99999, "不存在")):
        r = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida), _t(uid)])
        assert r.status_code == 400 and hint in r.text, (uid, r.text)
    r = _direct(client, world.admin, world.cid, world.log, targets=[_t(gone), _t(world.idc)])
    assert "dr_gone" in r.text and "dr_c" in r.text                            # 一次列出所有不合格的名字
    assert _q("SELECT id FROM dev_log_directive") == []                        # 一律沒寫入


def test_at_most_ten_targets(client, world, make_user, sync_mail):
    ids = []
    for i in range(11):
        _login(client, make_user, f"dr_m{i}", modules=None, role="admin")       # 管理員一定看得到案件
        ids.append(_uid(f"dr_m{i}"))
    r = _direct(client, world.sup, world.cid, world.log, targets=[_t(i) for i in ids])
    assert r.status_code == 400 and "最多" in r.text
    assert _direct(client, world.sup, world.cid, world.log, targets=[_t(i) for i in ids[:10]]).status_code == 201


def test_the_log_must_exist_and_belong_to_this_case(client, world):
    other = _make_case(client, world.owner, [world.ida], name="另一案")
    other_log = _make_log(client, world.a, other, world.ida)
    for bad in (other_log, 99999):
        r = _direct(client, world.admin, world.cid, bad, targets=[_t(world.ida)])
        assert r.status_code == 400 and "開發記錄" in r.text
    assert _q("SELECT id FROM dev_log_directive") == []


def test_a_soft_deleted_case_has_no_directives_endpoint(client, world):
    _x("UPDATE dev_cases SET is_deleted=1 WHERE id=?", world.cid)
    assert client.get(f"/api/dev-cases/{world.cid}/directives", headers=world.admin).status_code == 404
    assert _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)]).status_code == 404


# ─────────────────────────── 通知 ───────────────────────────

def test_directive_notifies_every_target_by_site_and_only_the_must_reply_ones_by_mail(client, world, sync_mail):
    r = _direct(client, world.admin, world.cid, world.log, content="這筆報價太低，下週前回我怎麼處理",
                targets=[_t(world.ida, True), _t(world.idb, False)])
    assert r.status_code == 201, r.text
    (na,) = _notices("dr_a", "dev_log_directive")
    (nb,) = _notices("dr_b", "dev_log_directive")
    assert "請回覆" in na["message"] and "批示測試案" in na["message"] and "太低" in na["message"]
    assert "僅知會" in nb["message"]
    assert _notices("dr_admin", "dev_log_directive") == [] and _notices("dr_owner") == [] and _notices("dr_c") == []
    assert len(sync_mail.directive) == 1                                         # 只有一封、收件人只有要回覆的人
    case_id, case_name, usernames, actor = sync_mail.directive[0]
    assert (case_id, case_name, usernames) == (world.cid, "批示測試案", ["dr_a"])
    assert sync_mail.activity == []                                              # 不呼叫 notify_module_activity（會把全文寄全體 admin）


def test_all_informational_directive_sends_no_mail(client, world, sync_mail):
    assert _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida, False)]).status_code == 201
    assert sync_mail.directive == [] and len(_notices("dr_a", "dev_log_directive")) == 1


def test_the_mail_function_goes_to_the_right_people_and_never_contains_the_directive_text(monkeypatch):
    from helpers import email_notify
    sent = []
    monkeypatch.setattr(email_notify, "_lookup_emails", lambda names, key=None: [f"{n}@example.test" for n in names] if key == "dev_log_directive" else [])
    monkeypatch.setattr(email_notify, "_async_send", lambda to, subject, html: sent.append((to, subject, html)))
    email_notify.notify_dev_log_directive(7, "測試案", ["dr_a"], "管理員甲")
    (to, subject, html), = sent
    assert to == ["dr_a@example.test"] and "測試案" in subject and "管理員甲" in html and "請登入系統" in html
    sent.clear()
    monkeypatch.setattr(email_notify, "_lookup_emails", lambda names, key=None: [])
    email_notify.notify_dev_log_directive(7, "測試案", ["dr_a"], "管理員甲")          # 沒有有效收件人：不寄、不丟例外
    assert sent == []


def test_the_new_mail_type_is_registered_and_visible_in_notification_prefs():
    from helpers import mail_types, notification_prefs
    assert mail_types.get("dev_log_directive") is not None
    keys = [k for _g, items in notification_prefs.EVENT_GROUPS for k, _l in items]
    assert "dev_log_directive" in keys


# ─────────────────────────── 可見度 ───────────────────────────

def test_only_admins_the_author_and_the_targets_can_see_a_directive(client, world, sync_mail):
    d = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)]).json()
    assert [x["id"] for x in _list(client, world.admin, world.cid)["items"]] == [d["id"]]      # 管理員（作者）
    assert [x["id"] for x in _list(client, world.sup, world.cid)["items"]] == [d["id"]]        # 另一位管理員（非作者非對象）仍可見
    assert [x["id"] for x in _list(client, world.a, world.cid)["items"]] == [d["id"]]          # 對象
    for who in (world.b, world.owner):                                                          # 看得到案件、也看得到那筆紀錄，但不是作者／對象
        got = _list(client, who, world.cid)
        assert got["items"] == [] and got["canDirect"] is False
    # 連「這筆紀錄有批示」都不能從別處推得：紀錄清單本身完全沒有批示相關欄位
    logs = client.get(f"/api/dev-cases/{world.cid}/logs", headers=world.b).json()
    assert logs and all("directive" not in " ".join(x.keys()).lower() for x in logs)


def test_a_member_granted_the_capability_sees_only_their_own_directives_not_other_peoples(client, world, sync_mail):
    from helpers import perm
    _x("INSERT INTO perm_user_overrides (user_id, cap, effect, set_by, set_at, reason) VALUES (?,?,?,?,?,?)",
       world.idowner, "crm.dev_log_directive.comment", "allow", world.idadmin, "2026-11-04 12:00:00", "測試")
    perm.invalidate()
    try:
        d_admin = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)]).json()
        d_owner = _direct(client, world.owner, world.cid, world.log, targets=[_t(world.idb)]).json()
        assert [x["id"] for x in _list(client, world.owner, world.cid)["items"]] == [d_owner["id"]]     # 有能力不等於看得到別人的
        assert {x["id"] for x in _list(client, world.admin, world.cid)["items"]} == {d_admin["id"], d_owner["id"]}
    finally:
        _x("DELETE FROM perm_user_overrides WHERE cap=?", "crm.dev_log_directive.comment")
        perm.invalidate()


def test_the_response_has_targets_and_pending_reply_names(client, world, sync_mail):
    d = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida, True), _t(world.idb, False)]).json()
    assert d["logId"] == world.log and d["authorId"] == world.idadmin and d["canReply"] is True
    assert [(t["userId"], t["mustReply"], t["repliedAt"]) for t in d["targets"]] == [(world.ida, True, None), (world.idb, False, None)]
    assert d["pendingReplyNames"] == [d["targets"][0]["name"]]                    # 只有 must_reply 且還沒回的人


# ─────────────────────────── 回覆 ───────────────────────────

def test_a_target_replies_once_and_the_author_is_notified(client, world, sync_mail):
    d = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida), _t(world.idb, False)]).json()
    r = _reply(client, world.a, world.cid, d["id"], "收到，下週一前回覆")
    assert r.status_code == 201, r.text
    body = r.json()
    assert [x["content"] for x in body["replies"]] == ["收到，下週一前回覆"] and body["pendingReplyNames"] == []
    first = _q("SELECT replied_at FROM dev_log_directive_target WHERE directive_id=? AND user_id=?", d["id"], world.ida)[0]["replied_at"]
    assert first
    (n,) = _notices("dr_admin", "dev_log_directive_reply")
    assert "回覆" in n["message"] and "收到" in n["message"]
    assert _notices("dr_b", "dev_log_directive_reply") == []                      # 對象回覆只通知作者
    assert _reply(client, world.a, world.cid, d["id"], "補充一點").status_code == 201
    again = _q("SELECT replied_at FROM dev_log_directive_target WHERE directive_id=? AND user_id=?", d["id"], world.ida)[0]["replied_at"]
    assert again == first                                                          # replied_at 只記首次
    assert len(_notices("dr_admin", "dev_log_directive_reply")) == 2


def test_the_author_can_reply_in_the_thread_and_all_targets_are_notified(client, world, sync_mail):
    d = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida), _t(world.idb, False)]).json()
    r = _reply(client, world.admin, world.cid, d["id"], "好，這件結案")
    assert r.status_code == 201, r.text
    assert len(_notices("dr_a", "dev_log_directive_reply")) == 1 and len(_notices("dr_b", "dev_log_directive_reply")) == 1
    assert _notices("dr_admin", "dev_log_directive_reply") == []                   # 不通知自己
    assert _q("SELECT replied_at FROM dev_log_directive_target WHERE directive_id=? AND user_id=?", d["id"], world.ida)[0]["replied_at"] is None


def test_who_may_not_reply(client, world, sync_mail):
    d = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)]).json()
    assert _reply(client, world.sup, world.cid, d["id"]).status_code == 403          # 管理員，但不是作者也不是對象
    for h in (world.b, world.owner, world.c):                                          # 看不到這筆批示的人：404，不洩漏它存在
        assert _reply(client, h, world.cid, d["id"]).status_code in (403, 404)
    assert _reply(client, world.b, world.cid, d["id"]).status_code == 404
    assert _reply(client, world.a, world.cid, 99999).status_code == 404
    other = _make_case(client, world.owner, [world.ida], name="另一案")
    assert _reply(client, world.a, other, d["id"]).status_code == 404                  # 批示不屬於這個案件
    assert _q("SELECT id FROM dev_log_directive WHERE parent_id IS NOT NULL") == []


def test_replies_cannot_be_replied_to_and_content_is_validated(client, world, sync_mail):
    d = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)]).json()
    rep = _reply(client, world.a, world.cid, d["id"]).json()["replies"][0]
    r = _reply(client, world.a, world.cid, rep["id"])
    assert r.status_code == 400 and "回覆" in r.text
    assert _reply(client, world.a, world.cid, d["id"], "  ").status_code == 400
    assert _reply(client, world.a, world.cid, d["id"], "字" * 4001).status_code == 400
    assert len(_q("SELECT id FROM dev_log_directive WHERE parent_id IS NOT NULL")) == 1


def test_a_target_who_lost_access_to_the_case_can_no_longer_read_or_reply(client, world, sync_mail):
    d = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)]).json()
    _x("UPDATE dev_cases SET sales_persons=? WHERE id=?", f"[{world.idb}]", world.cid)      # 案件換人：a 不再是業務
    assert client.get(f"/api/dev-cases/{world.cid}/directives", headers=world.a).status_code == 403
    assert _reply(client, world.a, world.cid, d["id"]).status_code == 403
    assert len(_q("SELECT id FROM dev_log_directive_target WHERE directive_id=?", d["id"])) == 1       # target 列留著（已知限制）


# ─────────────────────────── 不連動、只增不改不刪 ───────────────────────────

def test_directives_and_replies_touch_neither_updated_at_nor_dev_logs(client, world, sync_mail):
    _x("UPDATE dev_cases SET updated_at='2020-01-01 00:00:00' WHERE id=?", world.cid)
    logs_before = _q("SELECT * FROM dev_logs ORDER BY id")
    audit_before = len(_q("SELECT id FROM audit_log WHERE action LIKE 'dev_log.%'"))
    d = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)]).json()
    _reply(client, world.a, world.cid, d["id"])
    _reply(client, world.admin, world.cid, d["id"], "好")
    assert _q("SELECT updated_at FROM dev_cases WHERE id=?", world.cid)[0]["updated_at"] == "2020-01-01 00:00:00"
    assert _q("SELECT * FROM dev_logs ORDER BY id") == logs_before                  # dev_logs 逐欄相同
    new = _q("SELECT action, target_label FROM audit_log WHERE action LIKE 'dev_log.%' ORDER BY id")[audit_before:]
    assert [x["action"] for x in new] == ["dev_log.directive", "dev_log.directive_reply", "dev_log.directive_reply"]
    assert all(len(x["target_label"]) <= 41 for x in new)                          # 稽核標籤只放摘要


def test_there_is_no_edit_or_delete_endpoint_for_directives(client, world, sync_mail):
    d = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)]).json()
    for method in ("put", "patch", "delete"):
        for url in (f"/api/dev-cases/{world.cid}/directives/{d['id']}", f"/api/dev-log-directives/{d['id']}"):
            assert client.request(method.upper(), url, headers=world.admin, json={"content": "改"}).status_code in (404, 405)
    assert _q("SELECT content FROM dev_log_directive WHERE id=?", d["id"])[0]["content"] != "改"


# ─────────────────────────── 擋刪 ───────────────────────────

def test_a_log_with_a_directive_cannot_be_deleted_but_one_without_can(client, world, sync_mail):
    other_log = _make_log(client, world.a, world.cid, world.ida, content="另一筆沒有批示")
    _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)])
    r = client.delete(f"/api/dev-logs/{world.log}", headers=world.a)                  # 建立者本人也不行
    assert r.status_code == 409 and "批示" not in r.text                               # 訊息不洩漏批示存在
    r = client.delete(f"/api/dev-logs/{world.log}", headers=world.admin)
    assert r.status_code == 409
    assert _q("SELECT id FROM dev_logs WHERE id=?", world.log) != []                  # 紀錄還在
    assert client.delete(f"/api/dev-logs/{other_log}", headers=world.a).status_code == 204     # 正對照：沒批示照常刪
    assert _q("SELECT id FROM dev_logs WHERE id=?", other_log) == []


def test_deleting_a_log_and_directing_it_cannot_interleave(client, world, sync_mail):
    """兩個方向都是單一陳述：先刪掉紀錄 ⇒ 批示 400 且沒留下半套；已經有批示 ⇒ 刪除 409 且紀錄與附件都還在。"""
    lonely = _make_log(client, world.a, world.cid, world.ida, content="將被刪掉")
    assert client.delete(f"/api/dev-logs/{lonely}", headers=world.a).status_code == 204
    r = _direct(client, world.admin, world.cid, lonely, targets=[_t(world.ida)])
    assert r.status_code == 400
    assert _q("SELECT id FROM dev_log_directive") == [] and _q("SELECT id FROM dev_log_directive_target") == []
    # 直接塞一列批示（沒有走批示端點）⇒ 刪除端點仍擋下：擋刪是 DELETE 陳述本身的條件，不是先查再刪
    _x("INSERT INTO dev_log_directive (log_id, case_id, author_id, content, parent_id, created_at) VALUES (?,?,?,?,NULL,?)",
       world.log, world.cid, world.idadmin, "x", "2026-11-04 00:00:00")
    assert client.delete(f"/api/dev-logs/{world.log}", headers=world.admin).status_code == 409
    assert _q("SELECT id FROM dev_logs WHERE id=?", world.log) != []


def test_editing_a_directed_log_is_still_allowed(client, world, sync_mail):
    _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)])
    r = client.put(f"/api/dev-logs/{world.log}", headers=world.a,
                   json={"log_date": date.today().isoformat(), "log_by": world.ida, "content": "改過的內容"})
    assert r.status_code == 200 and r.json()["content"] == "改過的內容"


# ─────────────────────────── migration 0004 ───────────────────────────

def _load_migration():
    import importlib
    return importlib.import_module("modules.crm.migrations.0004_dev_log_directive")


def test_migration_0004_creates_both_tables_and_is_idempotent():
    mig = _load_migration()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE dev_logs (id INTEGER PRIMARY KEY, case_id INTEGER)")
    assert mig.up(conn) is None
    cols = {r[1] for r in conn.execute("PRAGMA table_info(dev_log_directive)")}
    assert {"id", "log_id", "case_id", "author_id", "owner_unit_id", "content", "parent_id", "created_at"} <= cols
    tcols = {r[1]: r for r in conn.execute("PRAGMA table_info(dev_log_directive_target)")}
    assert {"directive_id", "user_id", "must_reply", "replied_at", "owner_unit_id"} <= set(tcols)
    assert tcols["owner_unit_id"][4] == "1" and tcols["owner_unit_id"][3] == 1       # NOT NULL DEFAULT 1
    conn.execute("INSERT INTO dev_log_directive_target (directive_id, user_id) VALUES (1, 2)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO dev_log_directive_target (directive_id, user_id) VALUES (1, 2)")      # UNIQUE(directive_id, user_id)
    conn.execute("INSERT INTO dev_log_directive (log_id, case_id, author_id, content, created_at) VALUES (1,1,1,'x','t')")
    assert mig.up(conn) is None                                                      # 重跑：不丟例外、資料不動
    assert conn.execute("SELECT COUNT(*) FROM dev_log_directive").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM dev_log_directive_target").fetchone()[0] == 1


def test_migration_0004_reports_unfinished_when_the_prerequisite_table_is_missing():
    mig = _load_migration()
    conn = sqlite3.connect(":memory:")
    reason = mig.up(conn)
    assert isinstance(reason, str) and "dev_logs" in reason                           # 回原因字串＝未完成，不是什麼都不做就回 None
    assert conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'dev_log_directive%'").fetchall() == []


def test_a_real_migrated_database_has_the_tables_and_the_module_registers_version_4():
    cols = {r["name"] for r in _q("PRAGMA table_info(dev_log_directive)")}
    assert "parent_id" in cols
    assert _q("SELECT version FROM module_schema_versions WHERE module='crm'")[0]["version"] >= 4


def test_listing_without_the_tables_does_not_500(client, world, monkeypatch):
    """舊庫（migration 未完成）：案件頁載入批示不能 500，回空；擋刪退回舊行為。"""
    _x("DROP TABLE dev_log_directive_target")
    _x("DROP TABLE dev_log_directive")
    got = _list(client, world.admin, world.cid)
    assert got["items"] == [] and got["canDirect"] is True
    assert client.delete(f"/api/dev-logs/{world.log}", headers=world.a).status_code == 204


def test_migration_0004_on_a_populated_crm_v3_database_keeps_every_existing_row(client, world):
    """票 §1 的「含既有資料的庫實測」：把這個已經過 0001～0003 的真庫（有案件、開發記錄、進度回報、通知）倒回 crm v3，
    再用真正的模組 migration 執行器（core.migrations.run_all）跑一次 ⇒ crm 3→4、兩張新表出現、既有資料逐列不變；再跑一次什麼都不動。"""
    from core import migrations as mg
    _x("INSERT INTO dev_case_progress (case_id, author_id, content, created_at) VALUES (?,?,?,?)", world.cid, world.ida, "舊進度", "2026-11-01 09:00:00")
    _make_log(client, world.a, world.cid, world.ida, content="第二筆舊紀錄")
    snap = {t: _q("SELECT * FROM %s ORDER BY id" % t) for t in ("dev_cases", "dev_logs", "dev_case_progress", "users")}
    assert snap["dev_logs"] and snap["dev_case_progress"]
    _x("DROP TABLE dev_log_directive_target")
    _x("DROP TABLE dev_log_directive")
    _x("UPDATE module_schema_versions SET version=3 WHERE module='crm'")
    conn = db.get_db()
    try:
        ran = mg.run_all(conn)
        conn.commit()
        assert ran.get("crm") == (3, 4), ran
        assert mg.current_version(conn, "crm") == 4
        assert mg.run_all(conn).get("crm") is None                                   # 再跑：版號已前進，什麼都不做
    finally:
        conn.close()
    assert {t: _q("SELECT * FROM %s ORDER BY id" % t) for t in snap} == snap          # 既有資料逐列逐欄不變
    cols = {r["name"] for r in _q("PRAGMA table_info(dev_log_directive_target)")}
    assert {"must_reply", "replied_at", "owner_unit_id"} <= cols
    assert _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)]).status_code == 201     # 遷移後功能可用


# ─────────────────────────── 複核修正（hichan-9：M1～M3、S1、S2）───────────────────────────

def _dev_crm_badge(client, h):
    r = client.get("/api/reads/module-counts", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["dev_crm"]


def test_a_bystanders_menu_badge_does_not_move_when_a_directive_or_reply_happens(client, world, sync_mail):
    """M1：批示限作者／對象／管理員可見，audit_log 的 dev_log.directive* 不能讓旁觀者的 dev_crm 紅點 +1。"""
    before = _dev_crm_badge(client, world.c)
    d = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)]).json()
    _reply(client, world.a, world.cid, d["id"])
    assert _dev_crm_badge(client, world.c) == before
    # 正對照：同一個旁觀者，其他的 dev_log 稽核事件照算（證明這個量測量得到東西）
    _x("INSERT INTO audit_log (username, action, at) VALUES (?,?,?)", "dr_admin", "dev_log.create", "2999-01-01T00:00:00")
    assert _dev_crm_badge(client, world.c) == before + 1


def test_the_badge_exclusion_covers_both_counting_paths():
    """M1：選單數字有兩條算法（system.audit_module_counts 與 item_reads.module_counts），共用同一張排除表。"""
    from helpers import module_registry as mr
    from routers import item_reads, system
    for act in ("dev_log.directive", "dev_log.directive_reply"):
        assert act in mr.BADGE_EXCLUDE["dev_crm"]
    assert item_reads._MODULE_EXCLUDE_ACTIONS is mr.BADGE_EXCLUDE
    assert system._MODULE_EXCLUDE_ACTIONS is mr.BADGE_EXCLUDE


def test_replying_gives_a_bystander_the_same_404_for_every_kind_of_id(client, world, sync_mail):
    """M2：看不到批示的人，不論給的是根批示 id、回覆 id、還是不存在的 id，都得到同一個 404（不能用 400 當探針）。"""
    d = _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)]).json()
    rid = _reply(client, world.a, world.cid, d["id"]).json()["replies"][0]["id"]
    got = {k: _reply(client, world.b, world.cid, i) for k, i in (("root", d["id"]), ("reply", rid), ("none", 99999))}
    assert {k: r.status_code for k, r in got.items()} == {"root": 404, "reply": 404, "none": 404}
    assert len({r.text for r in got.values()}) == 1
    # 看得到的人回覆「回覆」仍是 400（正對照：400 的規則還在，只是排在可見度之後）
    assert _reply(client, world.a, world.cid, rid).status_code == 400
    assert _reply(client, world.sup, world.cid, rid).status_code == 400


class _LockedOn:
    """get_db() 的代理：執行到含 needle 的 SQL 就丟 OperationalError('database is locked')，其餘照常。"""

    def __init__(self, conn, needle):
        self._c, self._n = conn, needle

    def execute(self, sql, *a, **k):
        if self._n in sql:
            raise sqlite3.OperationalError("database is locked")
        return self._c.execute(sql, *a, **k)

    def __getattr__(self, name):
        return getattr(self._c, name)


def test_a_locked_database_never_falls_back_to_an_unguarded_delete(client, world, sync_mail, monkeypatch):
    """M3：只有『表不存在』才可退回舊行為；鎖定時刪除要失敗（503），紀錄與批示都還在。"""
    _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)])
    real = crm.get_db
    monkeypatch.setattr(crm, "get_db", lambda: _LockedOn(real(), "NOT EXISTS"))
    r = client.delete(f"/api/dev-logs/{world.log}", headers=world.a)
    assert r.status_code == 503, r.text
    monkeypatch.setattr(crm, "get_db", real)
    assert _q("SELECT id FROM dev_logs WHERE id=?", world.log) != []
    assert len(_q("SELECT id FROM dev_log_directive WHERE log_id=?", world.log)) == 1


def test_a_locked_database_does_not_make_the_listing_look_empty(client, world, sync_mail, monkeypatch):
    """M3：讀批示時鎖定 ⇒ 503，不能回空清單讓畫面以為沒有批示。"""
    _direct(client, world.admin, world.cid, world.log, targets=[_t(world.ida)])
    real = crm.get_db
    monkeypatch.setattr(crm, "get_db", lambda: _LockedOn(real(), "dev_log_directive_target"))
    assert client.get(f"/api/dev-cases/{world.cid}/directives", headers=world.admin).status_code == 503
    monkeypatch.setattr(crm, "get_db", real)
    assert len(_list(client, world.admin, world.cid)["items"]) == 1


def test_huge_ids_are_rejected_with_422_not_500(client, world, sync_mail):
    """S2：2**70 這種超過 SQLite 整數範圍的 id 不能變成 500。"""
    big = 2 ** 70
    assert _direct(client, world.admin, world.cid, big, targets=[_t(world.ida)]).status_code == 422
    assert _direct(client, world.admin, world.cid, world.log, targets=[_t(big)]).status_code == 422
    assert client.get(f"/api/dev-cases/{big}/directives", headers=world.admin).status_code == 422
    assert _direct(client, world.admin, big, world.log, targets=[_t(world.ida)]).status_code == 422
    assert _reply(client, world.a, world.cid, big).status_code == 422
    assert _direct(client, world.admin, world.cid, 0, targets=[_t(world.ida)]).status_code == 422       # 下界
    assert _q("SELECT id FROM dev_log_directive") == []


def test_the_audit_log_carries_neither_the_directive_text_nor_its_targets(client, world, sync_mail):
    """S1：有 audit_log 模組的人讀得到稽核，但批示限作者／對象／管理員可見，所以稽核裡不放內文也不放對象。"""
    secret = "底價絕對不能讓步的機密內文"
    d = _direct(client, world.admin, world.cid, world.log, content=secret, targets=[_t(world.ida)]).json()
    _reply(client, world.a, world.cid, d["id"], secret + "回覆")
    rows = _q("SELECT * FROM audit_log WHERE action LIKE 'dev_log.directive%' ORDER BY id")
    assert [r["action"] for r in rows] == ["dev_log.directive", "dev_log.directive_reply"]
    blob = repr([tuple(r.values()) for r in rows])
    assert secret not in blob
    assert "targets" not in blob and "mustReply" not in blob
    assert rows[0]["target_label"] == "批示#%d" % d["id"]
