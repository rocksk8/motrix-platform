"""T84：報價清單「下一步」用的 `waiting_on`（GET /api/quotations?with_waiting_on=1）。

PM 核准的五個條件：
1. 只出現在本來就看得到的列（業務看不到別人的單 ⇒ 也看不到那張單的簽核人名）。
2. data_json 壞掉／簽核結構怪 ⇒ 該列回空陣列，清單不失敗。
3. 一次批次查詢（IN），不是逐列查；有查詢次數測試。
4. 顯示名稱取自 users 表的現名（不是 data_json 裡存的帳號或舊名）。
5. 選用：沒帶參數 ⇒ 回應沒有這個鍵（舊呼叫端不變）。
"""
import json

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔打 M01（報價單）的清單端點")


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


def _approval(approvers, tier2=None):
    tiers = [{"order": 0, "approvers": approvers}]
    if tier2:
        tiers.append({"order": 1, "approvers": tier2})
    return {"requestedBy": "x", "currentTier": 0, "tiers": tiers}


def _seed(no, owner_id, status="待審核", approval=None, raw=None):
    import db
    dj = raw if raw is not None else json.dumps({"approval": approval} if approval is not None else {}, ensure_ascii=False)
    now = "2026-11-01T00:00:00"
    c = db.get_db()
    try:
        c.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, sales_person_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (no, status, "客戶", "案" + no, 100, 95, dj, now, now, owner_id))
        c.commit()
    finally:
        c.close()


def _name(username, display):
    import db
    c = db.get_db()
    c.execute("UPDATE users SET display_name=? WHERE username=?", (display, username))
    c.commit()
    c.close()


def _items(client, h, extra=""):
    r = client.get("/api/quotations?with_waiting_on=1&limit=200" + extra, headers=h)
    assert r.status_code == 200, r.text
    return {it["quote_no"]: it for it in r.json()["items"]}


def _approvers(*names, status="pending"):
    return [{"userId": None, "username": n, "displayName": "舊名" + n, "status": status} for n in names]


def test_waiting_on_lists_current_tier_pending_approvers_with_current_names(client, make_user):
    boss = make_user(username="t84_boss", role="admin")
    sales = make_user(username="t84_sales", role="sales")
    import db
    c = db.get_db()
    c.execute("UPDATE users SET display_name=? WHERE username='t84_boss'", ("王經理",))
    c.commit()
    c.close()
    _seed("MQ-T84-001", _uid("t84_sales"), approval=_approval(_approvers("t84_boss"), tier2=_approvers("t84_x")))
    it = _items(client, _login(client, *sales))["MQ-T84-001"]
    assert it["waiting_on"] == ["王經理"], "現名取自 users，不是簽核資料裡存的『舊名』也不是帳號"
    assert boss  # 夾具已建帳號


def test_already_approved_approvers_are_not_listed(client, make_user):
    sales = make_user(username="t84_sales2", role="sales")
    make_user(username="t84_a", role="admin")
    make_user(username="t84_b", role="admin")
    _name("t84_a", "甲")
    _name("t84_b", "乙")
    ap = _approval([{"username": "t84_a", "displayName": "甲", "status": "approved"},
                    {"username": "t84_b", "displayName": "乙", "status": "pending"}])
    _seed("MQ-T84-002", _uid("t84_sales2"), approval=ap)
    assert _items(client, _login(client, *sales))["MQ-T84-002"]["waiting_on"] == ["乙"]


def test_non_waiting_rows_get_an_empty_list(client, make_user):
    sales = make_user(username="t84_sales3", role="sales")
    _seed("MQ-T84-003", _uid("t84_sales3"), status="草稿")
    _seed("MQ-T84-004", _uid("t84_sales3"), status="已核准", approval=_approval(_approvers("t84_sales3")))
    got = _items(client, _login(client, *sales))
    assert got["MQ-T84-003"]["waiting_on"] == [] and got["MQ-T84-004"]["waiting_on"] == []


def test_sales_cannot_see_approvers_of_quotes_they_cannot_see(client, make_user):
    s1 = make_user(username="t84_s1", role="sales")
    make_user(username="t84_s2", role="sales")
    make_user(username="t84_secret_boss", role="admin")
    _seed("MQ-T84-010", _uid("t84_s1"), approval=_approval(_approvers("t84_s1")))
    _seed("MQ-T84-011", _uid("t84_s2"), approval=_approval(_approvers("t84_secret_boss")))
    r = client.get("/api/quotations?with_waiting_on=1&limit=200", headers=_login(client, *s1))
    body = r.text
    nos = [i["quote_no"] for i in r.json()["items"]]
    assert "MQ-T84-010" in nos and "MQ-T84-011" not in nos, "別人的單本來就看不到"
    assert "舊名t84_secret_boss" not in body and "t84_secret_boss" not in body, "看不到的單的簽核人名不會出現在回應任何地方"


@pytest.mark.parametrize("raw", ["[]", json.dumps({"approval": "oops"}),
                                 json.dumps({"approval": {"tiers": "bad", "currentTier": "x"}}),
                                 json.dumps({"approval": {"tiers": [{"approvers": [None, 3, "a"]}]}}),
                                 json.dumps({"approval": {"tiers": [{"approvers": [{"username": None, "status": "pending"}]}]}})])
def test_odd_structure_gives_empty_list_and_the_list_still_loads(client, make_user, raw):
    sales = make_user(username="t84_sales4", role="sales")
    _seed("MQ-T84-020", _uid("t84_sales4"), raw=raw)
    _seed("MQ-T84-021", _uid("t84_sales4"), approval=_approval(_approvers("t84_sales4")))
    got = _items(client, _login(client, *sales))
    assert got["MQ-T84-020"]["waiting_on"] == []
    assert got["MQ-T84-021"]["waiting_on"], "好的那一列照常算"


@pytest.mark.parametrize("raw", ["{not json", None, "", "[" * 5000 + "]" * 5000, json.dumps({"approval": {"tiers": [{"approvers": [{"username": "u", "status": "pending"}]}]}}) + "}"])
def test_helper_returns_empty_for_unparseable_data(raw):
    """壞 JSON 在 SQL 層本來就會讓整個清單查詢失敗（既有行為、與本欄位無關）；這裡鎖的是本欄位的解析不再多丟例外。"""
    from modules.case.api import quotations as Q
    assert Q._waiting_on_names(raw, {}) == []


def test_tier_fields_raising_gives_empty_list_not_a_failure(client, make_user, monkeypatch):
    from modules.case.api import quotations as Q
    sales = make_user(username="t84_sales5", role="sales")
    _seed("MQ-T84-030", _uid("t84_sales5"), approval=_approval(_approvers("t84_sales5")))

    def boom(_raw):
        raise RuntimeError("tier_fields exploded")
    monkeypatch.setattr(Q, "_queue_tier_fields", boom)
    assert _items(client, _login(client, *sales))["MQ-T84-030"]["waiting_on"] == []


def test_without_the_param_the_key_is_absent(client, make_user):
    sales = make_user(username="t84_sales6", role="sales")
    _seed("MQ-T84-040", _uid("t84_sales6"), approval=_approval(_approvers("t84_sales6")))
    r = client.get("/api/quotations?limit=200", headers=_login(client, *sales))
    assert all("waiting_on" not in it for it in r.json()["items"]), "舊呼叫端的回應形狀不變"


def test_waiting_on_costs_a_constant_number_of_queries(client, make_user):
    """批次 IN：列數從 3 增到 40，多出來的查詢次數不隨列數增加。"""
    sales = make_user(username="t84_sales7", role="sales")
    uid = _uid("t84_sales7")
    h = _login(client, *sales)

    def count_selects():
        n = {"q": 0}
        import db
        real_get_db = db.get_db

        def counting_get_db(*a, **k):
            conn = real_get_db(*a, **k)
            conn.set_trace_callback(lambda st: n.__setitem__("q", n["q"] + (1 if st.lstrip().upper().startswith("SELECT") else 0)))
            return conn
        return n, counting_get_db

    def run(extra):
        from modules.case.api import quotations as Q
        n, spy = count_selects()
        old = Q.get_db
        Q.get_db = spy
        try:
            r = client.get("/api/quotations?limit=200" + extra, headers=h)
        finally:
            Q.get_db = old
        assert r.status_code == 200, r.text
        return n["q"]

    for i in range(3):
        _seed("MQ-T84-05%d" % i, uid, approval=_approval(_approvers("t84_sales7")))
    base3, with3 = run(""), run("&with_waiting_on=1")
    for i in range(3, 40):
        _seed("MQ-T84-1%02d" % i, uid, approval=_approval(_approvers("t84_sales7")))
    base40, with40 = run(""), run("&with_waiting_on=1")
    assert (with3 - base3) == (with40 - base40), "多的查詢次數與列數無關（不是 N+1）：%s vs %s" % (with3 - base3, with40 - base40)
    assert (with40 - base40) >= 1, "計數器有在數（否則上面的相等沒有意義）"
    assert (with40 - base40) <= 3, "只多一次 users 對照＋一次批次讀 data_json"


def test_user_without_quote_money_sees_the_same_waiting_on_but_masked_totals(client, make_user):
    """沒有 quote_money 的人（例如工程師）看得到的列：金額照舊遮蔽，「等誰」和有權限的人看到的一樣（不因遮蔽而多給或少給）。"""
    eng = make_user(username="t84_eng", role="engineer")
    sales = make_user(username="t84_sales_m", role="sales")
    make_user(username="t84_boss_m", role="admin")
    _name("t84_boss_m", "陳主管")
    _seed("MQ-T84-020", _uid("t84_eng"), approval=_approval(_approvers("t84_boss_m")))
    mine = _items(client, _login(client, *eng))
    assert "MQ-T84-020" in mine, "夾具：工程師看得到自己的單"
    it = mine["MQ-T84-020"]
    assert it["waiting_on"] == ["陳主管"]
    assert not it.get("total") and not it.get("pretax"), "金額維持遮蔽：%s／%s" % (it.get("total"), it.get("pretax"))
    # 對照：有權限的人看同一張單（以業務為擁有者），等的人相同
    _seed("MQ-T84-021", _uid("t84_sales_m"), approval=_approval(_approvers("t84_boss_m")))
    assert _items(client, _login(client, *sales))["MQ-T84-021"]["waiting_on"] == it["waiting_on"]
