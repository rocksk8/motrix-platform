"""PATCH case-record 的案件成員檢查（CM14，2026-09-24 使用者裁示）。

過去這支完全沒有擁有者檢查：任何登入者都能寫任何案件（quote_no 可列舉，IDOR）。
成員＝admin／superadmin、業務（sales_person_id；舊資料無 id 時比 sales_person 顯示名稱）、
assigned_user_ids、caseRecord.roles 的 filler／sales／executor（存顯示名稱）、階段負責人
（case_stages.assigned_to，存帳號）。非成員 ⇒ 403、不寫入。
例外：已結案且半解鎖——非成員也可以送（每筆變更都排進 superadmin 審核）。
已知限制：roles 以顯示名稱比對，同名帳號會互相放行。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json

import pytest
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')

NO = "MQ-MEMBER-001"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _seed(sales_person_id=None, sales_person="", assigned=(), roles=None, stage_assignees=(),
          deal_tag="已成案", semi_unlocked=0):
    import db
    cr = {"materials": [{"id": 1, "name": "原料", "qty": 1}], "roles": roles or {}}
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, sales_person_id, sales_person, assigned_user_ids,"
            " case_semi_unlocked) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "客", "案", 100, 95, json.dumps({"dealTag": deal_tag, "caseRecord": cr}, ensure_ascii=False),
             now, now, deal_tag, sales_person_id, sales_person, json.dumps(list(assigned)), semi_unlocked))
        conn.execute(
            "INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, created_at, updated_at, assigned_to)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (NO, "施工", 0, 0, "", now, now, json.dumps(list(stage_assignees))))
        conn.commit()
    finally:
        conn.close()


def _materials():
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])
    finally:
        conn.close()
    return d["caseRecord"]["materials"]


def _save(client, h):
    return client.patch(f"/api/quotations/{NO}/case-record", headers=h, json={
        "segments": {"materials": [{"id": 1, "name": "改過", "qty": 1}]},
        "base": {"materials": [{"id": 1, "name": "原料", "qty": 1}]}})


# ── 非成員：擋下、不寫入（先在 master 證明紅）──────────────────────────────

@pytest.mark.parametrize("role", ["engineer", "viewer", "sales"])
def test_non_member_is_403_and_nothing_written(client, make_user, role):
    u = make_user(username=f"mb_non_{role}", role=role)
    _seed()
    r = _save(client, _login(client, *u))
    assert r.status_code == 403, r.text
    assert _materials()[0]["name"] == "原料"


def test_non_member_legacy_whole_record_format_also_403(client, make_user):
    u = make_user(username="mb_non_old", role="engineer")
    _seed()
    r = client.patch(f"/api/quotations/{NO}/case-record", headers=_login(client, *u),
                     json={"case_record": {"materials": [{"id": 1, "name": "改過", "qty": 1}]}})
    assert r.status_code == 403, r.text
    assert _materials()[0]["name"] == "原料"


# ── 防誤擋：每一種成員都要 200 ─────────────────────────────────────────────

def _member_case(kind, u):
    name = u[0]                                    # make_user 的 display_name＝username
    if kind == "sales_id":
        _seed(sales_person_id=_uid(name))
    elif kind == "sales_name_legacy":
        _seed(sales_person_id=None, sales_person=name)
    elif kind == "assigned":
        _seed(assigned=[_uid(name)])
    elif kind in ("filler", "sales", "executor"):
        _seed(roles={kind: name})
    elif kind == "stage_assignee":
        _seed(stage_assignees=[name])
    else:
        raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["sales_id", "sales_name_legacy", "assigned", "filler", "sales", "executor",
                                  "stage_assignee"])
def test_every_kind_of_member_can_save(client, make_user, kind):
    u = make_user(username=f"mb_{kind}", role="engineer")
    _member_case(kind, u)
    r = _save(client, _login(client, *u))
    assert r.status_code == 200, (kind, r.text)
    assert _materials()[0]["name"] == "改過"


@pytest.mark.parametrize("role", ["admin", "superadmin"])
def test_admins_can_save_any_case(client, make_user, role):
    u = make_user(username=f"mb_{role}", role=role)
    _seed()
    assert _save(client, _login(client, *u)).status_code == 200


def test_semi_unlocked_closed_case_non_member_can_submit_for_review(client, make_user):
    u = make_user(username="mb_semi", role="engineer")
    _seed(deal_tag="已結案", semi_unlocked=1)
    r = _save(client, _login(client, *u))
    assert r.status_code == 200, r.text
    assert r.json().get("pending") is True, "半解鎖期間的變更要排進審核，不是直接寫入"
    assert _materials()[0]["name"] == "原料"


def test_other_users_role_name_does_not_let_me_in(client, make_user):
    """roles 裡是別人的名字 ⇒ 我不是成員（確認比對的是我自己的顯示名稱）。"""
    u = make_user(username="mb_other", role="engineer")
    make_user(username="mb_someone", role="engineer")
    _seed(roles={"executor": "mb_someone"}, stage_assignees=["mb_someone"])
    assert _save(client, _login(client, *u)).status_code == 403


# ── 追加裁示：持 cashier 模組者可寫所有案件的「收款」分段 ───────────────────

def _pay_seed():
    import db
    _seed()
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])
        d["caseRecord"]["payment"] = {"items": [{"id": 1, "type": "訂金款", "pct": 100, "amount": 100,
                                                 "received": False, "note": ""}]}
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO))
        conn.commit()
    finally:
        conn.close()
    return d["caseRecord"]["payment"]


def _cr():
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])["caseRecord"]
    finally:
        conn.close()


def test_non_member_cashier_can_save_payment_segment(client, make_user):
    u = make_user(username="mb_cash", role="engineer", modules=["cashier"])
    base = _pay_seed()
    new = json.loads(json.dumps(base))
    new["items"][0]["received"] = True
    new["items"][0]["receivedAt"] = "2026-09-20"
    new["items"][0]["actualAmount"] = 100
    r = client.patch(f"/api/quotations/{NO}/case-record", headers=_login(client, *u), json={
        "segments": {"payment": new}, "base": {"payment": base},
        "defaults": {"contract": {"deliveryAddress": ""}}})
    assert r.status_code == 200, r.text
    cr = _cr()
    assert cr["payment"]["items"][0]["received"] is True
    assert "contract" not in cr, "出納這條路不寫頁面補的預設分段"


@pytest.mark.parametrize("body", [
    {"segments": {"materials": [{"id": 1, "name": "改過", "qty": 1}]},
     "base": {"materials": [{"id": 1, "name": "原料", "qty": 1}]}},
    {"segments": {"payment": {"items": []}, "materials": [{"id": 1, "name": "改過", "qty": 1}]},
     "base": {"payment": None, "materials": [{"id": 1, "name": "原料", "qty": 1}]}},
    {"case_record": {"materials": [{"id": 1, "name": "改過", "qty": 1}]}},
], ids=["other-segment", "payment-plus-other", "legacy-whole-record"])
def test_non_member_cashier_other_segments_still_403(client, make_user, body):
    u = make_user(username="mb_cash2", role="engineer", modules=["cashier"])
    _pay_seed()
    before = _cr()
    r = client.patch(f"/api/quotations/{NO}/case-record", headers=_login(client, *u), json=body)
    assert r.status_code == 403, r.text
    assert _cr() == before


def test_non_member_without_cashier_cannot_save_payment_segment(client, make_user):
    u = make_user(username="mb_nocash", role="engineer")
    base = _pay_seed()
    new = json.loads(json.dumps(base))
    new["items"][0]["note"] = "x"
    r = client.patch(f"/api/quotations/{NO}/case-record", headers=_login(client, *u),
                     json={"segments": {"payment": new}, "base": {"payment": base}})
    assert r.status_code == 403, r.text
