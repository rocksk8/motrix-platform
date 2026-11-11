"""外勤窄唯讀案件端點（T80c S2）：`GET /api/field/cases`、`GET /api/field/cases/{quote_no}`。

釘住的事：
- **金額根本不下發**：回應鍵集是白名單；種一張帶獨特金額／毛利／成本／付款資料的案件，原始回應文字裡找不到那些值。
- 權限與 `GET /api/quotations` 同一套（row_access）：別人的案件列表看不到、單件查無（404）；未登入 401。
- `mine` 預設開、`scope` 預設只看已成案、每頁上限 50、`q` 搜尋。
- 壞掉的 data_json 只讓聯絡欄位留空，不 500。
"""
from tests._requires import requires_module  # noqa: E402
import json

import pytest

pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點')

SECRET_TOTAL = 8765432
SECRET_PRETAX = 8765431
SECRET_COST = 7654321
LIST_KEYS = {"quote_no", "customer_name", "project_name", "status", "deal_tag", "sales_person", "current_stage",
             "stage_done", "stage_total", "last_update_at", "updated_at"}
DETAIL_KEYS = {"quote_no", "customer_name", "project_name", "status", "deal_tag", "sales_person", "quote_date", "address",
               "contact_person", "contact_phone", "current_stage", "stages", "last_update_at", "updated_at", "server_time"}
STAGE_KEYS = {"id", "label", "done", "due_date"}


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": "Bearer " + token}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()[0]
    finally:
        conn.close()


def _seed(quote_no, sales_username=None, sales_display="", deal_tag="已成案", customer="外勤客戶", project="外勤案件",
          data=None, stages=()):
    import db
    sid = _uid(sales_username) if sales_username else None
    d = {"dealTag": deal_tag,
         "caseRecord": {"contract": {"deliveryAddress": "台中市西屯區工業路 1 號", "contactPerson": "王主任", "contactPhone": "0912-345-678",
                                     "contractAmount": SECRET_TOTAL},
                        "roles": {}},
         "tot": {"totalCost": SECRET_COST}}
    if data is not None:
        d = data
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, customer_name, project_name, status, deal_tag, total, pretax, direct_margin_pct, net_margin_pct, "
            "sales_person, sales_person_id, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, customer, project, "已送出", deal_tag, SECRET_TOTAL, SECRET_PRETAX, 37.5, 21.25,
             sales_display, sid, json.dumps(d, ensure_ascii=False), "2026-01-01T00:00:00", "2026-02-02T00:00:00"))
        for i, (label, done, due) in enumerate(stages):
            conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, due_date, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                         (quote_no, label, i, 1 if done else 0, due, "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    return quote_no


@pytest.fixture
def sales(client, make_user):
    u, p = make_user(username="fld_sales", role="user", modules=["case_manage"])
    return u, _login(client, u, p)


def test_requires_login(client):
    assert client.get("/api/field/cases").status_code == 401
    assert client.get("/api/field/cases/MQ-X").status_code == 401


def test_list_returns_only_whitelisted_keys_and_no_money(client, sales):
    u, t = sales
    _seed("MQ-FLD-001", sales_username=u, sales_display="業務甲", stages=[("丈量", True, "2026-03-01"), ("施工", False, "2026-04-01")])
    r = client.get("/api/field/cases", headers=_auth(t))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1 and body["has_more"] is False and "total" not in body
    item = body["items"][0]
    assert set(item) == LIST_KEYS
    assert item["current_stage"] == "施工" and item["stage_done"] == 1 and item["stage_total"] == 2
    for secret in (str(SECRET_TOTAL), str(SECRET_PRETAX), str(SECRET_COST), "37.5", "21.25"):
        assert secret not in r.text, "金額／毛利不可以出現在外勤列表回應：%s" % secret


def test_detail_returns_only_whitelisted_keys_and_no_money(client, sales):
    u, t = sales
    _seed("MQ-FLD-002", sales_username=u, stages=[("丈量", True, "2026-03-01"), ("施工", False, "")])
    r = client.get("/api/field/cases/MQ-FLD-002", headers=_auth(t))
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d) == DETAIL_KEYS
    assert all(set(s) == STAGE_KEYS for s in d["stages"]) and len(d["stages"]) == 2
    assert d["address"] == "台中市西屯區工業路 1 號" and d["contact_person"] == "王主任" and d["contact_phone"] == "0912-345-678"
    assert d["current_stage"] == "施工" and d["stages"][1]["due_date"] is None
    for secret in (str(SECRET_TOTAL), str(SECRET_PRETAX), str(SECRET_COST), "37.5", "21.25", "contractAmount", "totalCost"):
        assert secret not in r.text, "金額／毛利／成本不可以出現在外勤單件回應：%s" % secret


def test_visibility_is_exactly_the_existing_list_and_guard(client, make_user, sales):
    """權限不是這裡另寫一套：列表＝`GET /api/quotations` 看得到的案件（row_access）；單件＝同一把 `_guard_case`（案件執行面）。"""
    u, t = sales
    ob, pb = make_user(username="fld_other", role="user", modules=["case_manage"])
    _seed("MQ-FLD-003", sales_username=ob, sales_display="別人")
    _seed("MQ-FLD-004", sales_username=u, sales_display="我")
    ref = {i["quote_no"] for i in client.get("/api/quotations?limit=500", headers=_auth(t)).json()["items"]}
    got = {i["quote_no"] for i in client.get("/api/field/cases?mine=0&scope=all&limit=50", headers=_auth(t)).json()["items"]}
    assert got == ref and "MQ-FLD-004" in got
    for no in ("MQ-FLD-003", "MQ-FLD-004"):
        det = client.get("/api/field/cases/" + no, headers=_auth(t))
        ref_det = client.get("/api/quotations/%s/updates" % no, headers=_auth(t))      # 同一把 _guard_case(allow_module="case_manage")
        assert det.status_code == ref_det.status_code, no


def test_mine_default_and_scope_default(client, make_user, sales):
    u, t = sales
    _seed("MQ-FLD-010", sales_username=u)                                   # 我的、已成案
    _seed("MQ-FLD-011", sales_username=u, deal_tag="已結案")                 # 我的、已結案
    ob, _p = make_user(username="fld_other2", role="user", modules=["case_manage"])
    _seed("MQ-FLD-012", sales_username=ob)                                  # 別人的、已成案
    nos = lambda q: sorted(i["quote_no"] for i in client.get("/api/field/cases" + q, headers=_auth(t)).json()["items"])
    assert nos("") == ["MQ-FLD-010"]                                        # 預設：我的＋已成案
    assert nos("?scope=all") == ["MQ-FLD-010", "MQ-FLD-011"]                # 已結案也要
    assert "MQ-FLD-012" not in nos("?mine=0&scope=all")                     # 沒有權限就是沒有權限，mine=0 不放寬


def test_search_and_paging_and_limit_clamp(client, sales):
    u, t = sales
    for i in range(7):
        _seed("MQ-FLD-02%d" % i, sales_username=u, customer="甲公司" if i % 2 == 0 else "乙公司", project="案%d" % i)
    h = _auth(t)
    r = client.get("/api/field/cases?q=甲公司", headers=h).json()
    assert len(r["items"]) == 4 and all(i["customer_name"] == "甲公司" for i in r["items"]) and r["has_more"] is False
    assert len(client.get("/api/field/cases?q=mq-fld-023", headers=h).json()["items"]) == 1           # 大小寫不分
    p1 = client.get("/api/field/cases?limit=3&offset=0", headers=h).json()
    p2 = client.get("/api/field/cases?limit=3&offset=3", headers=h).json()
    p3 = client.get("/api/field/cases?limit=3&offset=6", headers=h).json()
    assert len(p1["items"]) == 3 and p1["has_more"] is True and len(p2["items"]) == 3 and p2["has_more"] is True
    assert len(p3["items"]) == 1 and p3["has_more"] is False                                          # 共 7 筆
    assert not {i["quote_no"] for i in p1["items"]} & {i["quote_no"] for i in p2["items"]}
    big = client.get("/api/field/cases?limit=100000", headers=h).json()
    assert big["limit"] == 50
    assert client.get("/api/field/cases?limit=0", headers=h).json()["limit"] == 1
    assert client.get("/api/field/cases?offset=-5", headers=h).json()["offset"] == 0


def test_corrupt_data_json_only_blanks_the_contact_fields(client, sales):
    u, t = sales
    import db
    _seed("MQ-FLD-030", sales_username=u)
    conn = db.get_db()
    conn.execute("UPDATE quotations SET data_json='{not json' WHERE quote_no='MQ-FLD-030'")
    conn.commit()
    conn.close()
    r = client.get("/api/field/cases/MQ-FLD-030", headers=_auth(t))
    assert r.status_code == 200
    d = r.json()
    assert d["contact_person"] is None and d["contact_phone"] is None and d["address"] is None


def test_unknown_case_is_404(client, sales):
    assert client.get("/api/field/cases/MQ-NOPE-999", headers=_auth(sales[1])).status_code == 404


def test_admin_sees_the_case_but_still_no_money(client, make_user):
    ua, pa = make_user(username="fld_admin", role="superadmin")
    ta = _login(client, ua, pa)
    _seed("MQ-FLD-040", sales_username=ua)
    r = client.get("/api/field/cases/MQ-FLD-040", headers=_auth(ta))
    assert r.status_code == 200 and str(SECRET_TOTAL) not in r.text
    r = client.get("/api/field/cases?mine=0&scope=all", headers=_auth(ta))
    assert str(SECRET_TOTAL) not in r.text and str(SECRET_COST) not in r.text


def test_the_existing_list_does_carry_money_so_the_whitelist_test_is_not_vacuous(client, make_user):
    """正對照：同一份種子資料，既有 `GET /api/quotations`（超管）確實帶金額——所以上面「找不到金額」是端點的選擇，不是種子沒種進去。"""
    ua, pa = make_user(username="fld_admin2", role="superadmin")
    ta = _login(client, ua, pa)
    _seed("MQ-FLD-050", sales_username=ua)
    assert str(SECRET_TOTAL) in client.get("/api/quotations", headers=_auth(ta)).text


def _ids(client, t, q=""):
    return sorted(i["quote_no"] for i in client.get("/api/field/cases" + q, headers=_auth(t)).json()["items"])


def test_mine_matches_every_clause_of_the_existing_sql_definition(client, make_user):
    """「我的」＝與案件列表 `_CASE_MINE_SQL` 逐項同義：業務 id／無 id 時的業務名／協作者名單／合約角色（填表人、業務、執行）。
    用超管帳號（row_access 全可見）才分得出「我的」這一層；非超管本來就只看得到自己可見的案件。"""
    import db
    u, p = make_user(username="fld_adm", role="superadmin")
    t = _login(client, u, p)
    me = _uid(u)
    disp = db.get_db().execute("SELECT display_name FROM users WHERE username=?", (u,)).fetchone()[0]
    for who in ("fld_x1", "fld_x4", "fld_x5"):
        make_user(username=who, role="user", modules=["case_manage"])
    _seed("MQ-FLD-M01", sales_username=u)                                              # 業務 id
    _seed("MQ-FLD-M02", sales_username="fld_x1", sales_display="別人")                   # 不是我
    for who, no in (("filler", "MQ-FLD-M03"), ("sales", "MQ-FLD-M04"), ("executor", "MQ-FLD-M05")):
        _seed(no, sales_username="fld_x1", data={"dealTag": "已成案", "caseRecord": {"roles": {who: {"username": u}}}})
    _seed("MQ-FLD-M06", sales_username="fld_x1", data={"dealTag": "已成案", "caseRecord": {"roles": {"executor": {"username": "fld_x4"}}}})
    _seed("MQ-FLD-M07", sales_username="fld_x5")
    _seed("MQ-FLD-M08", sales_username=None, sales_display=disp)                        # 無業務 id、業務名＝我的顯示名
    conn = db.get_db()
    conn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no='MQ-FLD-M07'", (json.dumps([me]),))   # 協作者名單含我
    conn.commit()
    conn.close()
    want = ["MQ-FLD-M01", "MQ-FLD-M03", "MQ-FLD-M04", "MQ-FLD-M05", "MQ-FLD-M07", "MQ-FLD-M08"]
    got = _ids(client, t)
    assert got == want, got
    # 正對照（逐項同義）：既有列表 mine=1 在這批種子上回同一組
    ref = sorted(i["quote_no"] for i in client.get("/api/quotations?mine=1&limit=500", headers=_auth(t)).json()["items"]
                 if i["quote_no"].startswith("MQ-FLD-M") and i["deal_tag"] == "已成案")
    assert got == ref, (got, ref)


def test_deal_tag_falls_back_to_data_json_only_when_the_column_is_empty(client, sales):
    import db
    u, t = sales
    _seed("MQ-FLD-T01", sales_username=u, deal_tag="", data={"dealTag": "已成案", "caseRecord": {}})     # 欄位空、JSON 有 ⇒ 已成案
    _seed("MQ-FLD-T02", sales_username=u, deal_tag="已結案", data={"dealTag": "已成案", "caseRecord": {}})  # 欄位優先 ⇒ 已結案
    assert _ids(client, t) == ["MQ-FLD-T01"]
    r = client.get("/api/field/cases", headers=_auth(t)).json()["items"][0]
    assert r["deal_tag"] == "已成案"


def test_one_corrupt_data_json_does_not_break_the_list(client, sales, caplog):
    """§G5 #2：壞的一筆跳過並記 ERROR，其他列照常回（SQL json_extract 會讓整個查詢丟例外）。"""
    import db
    import logging
    u, t = sales
    _seed("MQ-FLD-C01", sales_username=u)
    _seed("MQ-FLD-C02", sales_username=u)
    conn = db.get_db()
    conn.execute("UPDATE quotations SET data_json='{not json' WHERE quote_no='MQ-FLD-C01'")
    conn.commit()
    conn.close()
    with caplog.at_level(logging.ERROR, logger="modules.case.api.field_cases"):
        r = client.get("/api/field/cases", headers=_auth(t))
    assert r.status_code == 200
    # C01：欄位 deal_tag 有值＝已成案、業務 id 是我 ⇒ 仍列出（不需要靠壞掉的 JSON 判斷）；C02 正常
    assert sorted(i["quote_no"] for i in r.json()["items"]) == ["MQ-FLD-C01", "MQ-FLD-C02"]
    assert any("MQ-FLD-C01" in rec.getMessage() for rec in caplog.records)


def test_corrupt_json_row_is_skipped_when_json_is_needed_to_decide(client, sales):
    import db
    u, t = sales
    _seed("MQ-FLD-C11", sales_username=u, deal_tag="")                 # 欄位空 ⇒ 要靠 JSON 判斷已成案
    _seed("MQ-FLD-C12", sales_username=u)
    conn = db.get_db()
    conn.execute("UPDATE quotations SET data_json='[1,2' WHERE quote_no='MQ-FLD-C11'")
    conn.commit()
    conn.close()
    assert _ids(client, t) == ["MQ-FLD-C12"]


def test_the_scan_cap_returns_what_it_has_with_has_more(client, sales, monkeypatch):
    from modules.case.api import field_cases as F
    u, t = sales
    monkeypatch.setattr(F, "_CHUNK", 2)
    monkeypatch.setattr(F, "_MAX_SCAN", 4)
    for i in range(5):
        _seed("MQ-FLD-S0%d" % i, sales_username=u, deal_tag="已結案")     # 掃了也湊不到（都不是已成案）
    r = client.get("/api/field/cases", headers=_auth(t)).json()
    assert r["items"] == [] and r["has_more"] is True                      # 掃描上限到了 ⇒ 誠實說「可能還有」
