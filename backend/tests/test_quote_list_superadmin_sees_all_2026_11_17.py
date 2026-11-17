"""報價單列表：最高管理者看得到所有人的報價單（2026-11-17 使用者交辦）。

後端不用改（row_access 對 superadmin／admin 直通、列表沒有別的狀態過濾），這裡把「現況就是這樣」鎖住，之後有人加過濾會紅燈：
1. 最高管理者看得到他人的草稿、已核准、已送出、已成案、已結案、已取消、已退回（每個狀態都在）。
2. `?mine=1` 仍只回他自己負責的（開關「僅顯示我負責的」要能用）；不帶時不限縮。
3. 一般業務不變：只看得到自己的；`?mine=1` 不放寬。
4. counts=1 的總數口徑對最高管理者是全部。
"""
import json

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔打 M01（報價單）的清單端點")

_STATUSES = ["草稿", "待審核", "簽核中", "已核准", "已送出", "已拒絕", "已取消"]


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _uid(username):
    import db
    c = db.get_db()
    try:
        return c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        c.close()


def _seed(no, owner_id, status, deal_tag=""):
    import db
    dj = {"quoteNo": no, "status": status}
    if deal_tag:
        dj["dealTag"] = deal_tag
    now = "2026-11-01T00:00:00"
    c = db.get_db()
    try:
        c.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date, sales_person_id, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, status, "客戶" + no[-3:], "案" + no[-3:], 1050, 1000, json.dumps(dj, ensure_ascii=False),
             now, now, deal_tag, "2026-11-01", owner_id, "業務乙"))
        c.commit()
    finally:
        c.close()


def _world(make_user, tag):
    sup = make_user(username=f"sa_{tag}_super", role="superadmin")
    other = make_user(username=f"sa_{tag}_other", role="sales")
    mine_owner = make_user(username=f"sa_{tag}_mine", role="sales")
    others = []
    for i, st in enumerate(_STATUSES):
        no = f"MQ-SA{tag}-{i:03d}"
        _seed(no, _uid(f"sa_{tag}_other"), st)
        others.append(no)
    _seed(f"MQ-SA{tag}-100", _uid(f"sa_{tag}_other"), "已送出", deal_tag="已成案")
    _seed(f"MQ-SA{tag}-101", _uid(f"sa_{tag}_other"), "已送出", deal_tag="已結案")
    _seed(f"MQ-SA{tag}-102", _uid(f"sa_{tag}_other"), "已送出", deal_tag="未成案")
    others += [f"MQ-SA{tag}-100", f"MQ-SA{tag}-101", f"MQ-SA{tag}-102"]
    # 最高管理者自己負責的一張
    _seed(f"MQ-SA{tag}-200", _uid(f"sa_{tag}_super"), "草稿")
    assert other and mine_owner
    return sup, others


def _nos(client, h, extra=""):
    r = client.get("/api/quotations?limit=500" + extra, headers=h)
    assert r.status_code == 200, r.text
    return [it["quote_no"] for it in r.json()["items"]], r.json()


def test_superadmin_sees_every_status_of_other_peoples_quotes(client, make_user):
    sup, others = _world(make_user, "A")
    got, _ = _nos(client, _login(client, *sup))
    missing = [n for n in others if n not in got]
    assert not missing, "最高管理者看不到：%s" % missing
    assert "MQ-SAA-200" in got


def test_superadmin_can_open_someone_elses_draft(client, make_user):
    sup, _others = _world(make_user, "B")
    r = client.get("/api/quotations/MQ-SAB-000", headers=_login(client, *sup))
    assert r.status_code == 200, r.text


def test_mine_filter_still_narrows_for_superadmin_and_default_does_not(client, make_user):
    sup, others = _world(make_user, "C")
    h = _login(client, *sup)
    mine, _ = _nos(client, h, "&mine=1")
    assert mine == ["MQ-SAC-200"], "「僅顯示我負責的」要能用：%s" % mine
    allq, _ = _nos(client, h)
    assert len(allq) == len(others) + 1, "不帶 mine ⇒ 不限縮"


def test_counts_are_over_everything_for_superadmin(client, make_user):
    sup, others = _world(make_user, "D")
    _, body = _nos(client, _login(client, *sup), "&counts=1")
    assert body["counts"]["all"] == len(others) + 1, body["counts"]
    assert body["counts"]["mine"] == 1


def test_plain_sales_is_unchanged_only_own_quotes(client, make_user):
    _sup, _others = _world(make_user, "E")
    owner = make_user(username="sa_E_owner2", role="sales")
    _seed("MQ-SAE-300", _uid("sa_E_owner2"), "草稿")
    h = _login(client, *owner)
    got, _ = _nos(client, h)
    assert got == ["MQ-SAE-300"], "一般業務只看得到自己的：%s" % got
    got_mine, _ = _nos(client, h, "&mine=1")
    assert got_mine == ["MQ-SAE-300"]
    r = client.get("/api/quotations/MQ-SAE-000", headers=h)
    assert r.status_code in (403, 404), "別人的草稿一般業務仍不能開（現況回 404，不洩漏單號存在）：%s" % r.status_code


@pytest.mark.parametrize("role", ["admin"])
def test_admin_role_also_sees_all_unchanged(client, make_user, role):
    _sup, others = _world(make_user, "F")
    adm = make_user(username="sa_F_adm", role=role)
    got, _ = _nos(client, _login(client, *adm))
    assert all(n in got for n in others)
