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
          data=None, stages=(), ensure_ascii=False):
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
             sales_display, sid, json.dumps(d, ensure_ascii=ensure_ascii), "2026-01-01T00:00:00", "2026-02-02T00:00:00"))
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


def test_visibility_is_case_membership_and_other_peoples_case_is_404_even_with_case_manage(client, make_user, sales):
    """K 審 M1：單件不再用 `case_manage` 放行。持 `case_manage` 的人對「別人的案件」＝404（列表看不到、單件也打不開）；自己的案件 200。
    （舊版這題只比兩邊狀態碼相等，而別人的案件兩邊都是 200，是假綠。）"""
    u, t = sales
    ob, pb = make_user(username="fld_other", role="user", modules=["case_manage"])
    _seed("MQ-FLD-003", sales_username=ob, sales_display="別人")
    _seed("MQ-FLD-004", sales_username=u, sales_display="我")
    got = {i["quote_no"] for i in client.get("/api/field/cases?mine=0&scope=all&limit=50", headers=_auth(t)).json()["items"]}
    assert got == {"MQ-FLD-004"}
    other = client.get("/api/field/cases/MQ-FLD-003", headers=_auth(t))
    assert other.status_code == 404
    assert "0912-345-678" not in other.text and "王主任" not in other.text and "工業路" not in other.text      # 404 內文不帶客戶資料
    assert client.get("/api/field/cases/MQ-FLD-004", headers=_auth(t)).status_code == 200
    # 正對照：既有案件執行面（allow_module=case_manage）對這個「別人的案件」確實放行——證明 404 是這支端點收緊的結果，不是種子沒種好
    assert client.get("/api/quotations/MQ-FLD-003/updates", headers=_auth(t)).status_code == 200


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
    pages, cur, seen = 0, "", []
    while True:                                                         # 游標翻頁：每頁 3 筆，共 7 筆
        r = client.get("/api/field/cases?limit=3" + cur, headers=h).json()
        pages += 1
        seen += [i["quote_no"] for i in r["items"]]
        assert "offset" not in r
        if not r["has_more"]:
            assert r["next_before_id"] is None
            break
        assert r["next_before_id"]
        cur = "&before_id=%d" % r["next_before_id"]
        assert pages < 10
    assert pages == 3 and len(seen) == 7 and len(set(seen)) == 7           # 不漏、不重
    big = client.get("/api/field/cases?limit=100000", headers=h).json()
    assert big["limit"] == 50
    assert client.get("/api/field/cases?limit=0", headers=h).json()["limit"] == 1
    assert len(client.get("/api/field/cases?before_id=-5", headers=h).json()["items"]) == 7       # 非正數＝從頭


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
    from modules.case.api import field_cases as F
    F._LOGGED.clear()                                   # 限頻集合是行程內狀態：每題自己清
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


def test_the_scan_cap_returns_what_it_has_and_a_cursor_that_reaches_older_cases(client, make_user, monkeypatch):
    """K 審 M2/N4：掃描上限到了 ⇒ 回已湊到的（可能是空頁）＋has_more＋next_before_id；照游標續掃必定到得了更舊的案件，不會永遠空。"""
    from modules.case.api import field_cases as F
    monkeypatch.setattr(F, "_CHUNK", 2)
    monkeypatch.setattr(F, "_MAX_SCAN", 4)
    u, p = make_user(username="fld_adm3", role="admin")
    t = _login(client, u, p)
    other, _ = make_user(username="fld_oth3", role="user", modules=["case_manage"])
    _seed("MQ-CAP-OLD", sales_username=u)                                   # 我的、最舊（id 最小）
    for i in range(6):
        _seed("MQ-CAP-N%d" % i, sales_username=other)                       # 6 張別人的、較新
    h = _auth(t)
    first = client.get("/api/field/cases", headers=h).json()
    assert first["items"] == [] and first["has_more"] is True and first["next_before_id"]     # 掃了 4 筆都不是我的：誠實說還有，並給游標
    got, cur, hops = [], first["next_before_id"], 0
    while cur and hops < 10:
        r = client.get("/api/field/cases?before_id=%d" % cur, headers=h).json()
        got += [i["quote_no"] for i in r["items"]]
        cur = r["next_before_id"] if r["has_more"] else None
        hops += 1
    assert got == ["MQ-CAP-OLD"], got                                       # 舊案件到得了（舊版：offset 任何值都永遠空）


def test_engineer_who_is_only_roles_executor_lists_and_opens_the_case(client, make_user):
    """K 審 P2：現場工程師不是業務、只在 caseRecord.roles.executor——列表要列得出來、單件要點得進去（與 `_is_case_member` 同一口徑）。"""
    u, p = make_user(username="fld_eng", role="engineer", modules=["case_manage"])
    t = _login(client, u, p)
    owner, _ = make_user(username="fld_sale2", role="user", modules=["case_manage"])
    data = {"dealTag": "已成案", "caseRecord": {"contract": {"deliveryAddress": "高雄市", "contactPerson": "林先生", "contactPhone": "07-1234567"},
                                                "roles": {"executor": {"username": u}}}}
    _seed("MQ-P2-001", sales_username=owner, data=data)
    _seed("MQ-P2-002", sales_username=owner)                                # 沒指派他的案件
    assert _ids(client, t) == ["MQ-P2-001"]
    assert client.get("/api/field/cases/MQ-P2-001", headers=_auth(t)).status_code == 200
    assert client.get("/api/field/cases/MQ-P2-002", headers=_auth(t)).status_code == 404


def test_membership_equals_the_existing_case_member_rule_for_every_path(client, make_user):
    """差分：這支的可見性與既有 `_is_case_member`（CM14）逐案一致——業務／協作者／三種角色（物件、舊字串）／階段負責人／無關。"""
    import db
    from modules.case.api.quotations import _is_case_member
    u, p = make_user(username="fld_mem", role="user", modules=["case_manage"])
    t = _login(client, u, p)
    me = _uid(u)
    disp = db.get_db().execute("SELECT display_name FROM users WHERE username=?", (u,)).fetchone()[0]
    other, _ = make_user(username="fld_mem_o", role="user", modules=["case_manage"])
    roles_of = lambda k, v: {"dealTag": "已成案", "caseRecord": {"roles": {k: v}}}
    seeds = {
        "MQ-MEM-01": dict(sales_username=u),
        "MQ-MEM-02": dict(sales_username=other, data=roles_of("filler", {"username": u})),
        "MQ-MEM-03": dict(sales_username=other, data=roles_of("sales", {"username": u})),
        "MQ-MEM-04": dict(sales_username=other, data=roles_of("executor", {"username": u})),
        "MQ-MEM-05": dict(sales_username=other, data=roles_of("executor", disp)),             # 舊字串：比顯示名
        "MQ-MEM-06": dict(sales_username=other, data=roles_of("executor", {"username": other})),
        "MQ-MEM-07": dict(sales_username=other),                                              # 無關
        "MQ-MEM-08": dict(sales_username=other, stages=[("丈量", False, "")]),                # 階段負責人（下面補 assigned_to）
        "MQ-MEM-09": dict(sales_username=other, stages=[("丈量", False, "")]),                # 階段有人但不是我
        "MQ-MEM-10": dict(sales_username=None, sales_display=disp),                           # 無業務 id、業務名＝我
        "MQ-MEM-11": dict(sales_username=other),                                              # 協作者名單含我
    }
    for no, kw in seeds.items():
        _seed(no, **kw)
    conn = db.get_db()
    conn.execute("UPDATE case_stages SET assigned_to=? WHERE quote_no='MQ-MEM-08'", (json.dumps([u]),))
    conn.execute("UPDATE case_stages SET assigned_to=? WHERE quote_no='MQ-MEM-09'", (json.dumps([other]),))
    conn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no='MQ-MEM-11'", (json.dumps([me]),))
    conn.commit()
    user = dict(conn.execute("SELECT * FROM users WHERE id=?", (me,)).fetchone())
    ref = set()
    for no in seeds:
        row = conn.execute("SELECT * FROM quotations WHERE quote_no=?", (no,)).fetchone()
        if _is_case_member(conn, no, row, user):
            ref.add(no)
    conn.close()
    assert ref >= {"MQ-MEM-01", "MQ-MEM-02", "MQ-MEM-04", "MQ-MEM-08", "MQ-MEM-11"} and "MQ-MEM-07" not in ref      # 對照組本身有分辨力
    got = {i["quote_no"] for i in client.get("/api/field/cases?scope=all&limit=50", headers=_auth(t)).json()["items"]}
    assert got == ref, sorted(got ^ ref)
    for no in seeds:
        assert (client.get("/api/field/cases/" + no, headers=_auth(t)).status_code == 200) == (no in ref), no


def test_nested_values_are_dropped_not_stringified(client, sales):
    """K 審 N1：dealTag／contactPerson 若是 dict／list，不可被 str() 後流出（巢狀 SECRET 值不出現在回應文字）。"""
    u, t = sales
    data = {"dealTag": {"note": "X%d" % SECRET_TOTAL},
            "caseRecord": {"contract": {"contactPerson": {"amt": SECRET_COST}, "contactPhone": 1234567, "deliveryAddress": ["Y%d" % SECRET_PRETAX]},
                           "roles": {}}}
    _seed("MQ-P3-001", sales_username=u, deal_tag="", data=data)
    r = client.get("/api/field/cases/MQ-P3-001", headers=_auth(t))
    assert r.status_code == 200
    for secret in (str(SECRET_COST), str(SECRET_TOTAL), str(SECRET_PRETAX)):
        assert secret not in r.text
    d = r.json()
    assert d["contact_person"] is None and d["contact_phone"] == "1234567" and d["deal_tag"] == ""      # 數字轉字串、巢狀丟掉
    lst = client.get("/api/field/cases?scope=all", headers=_auth(t))
    assert str(SECRET_TOTAL) not in lst.text and str(SECRET_COST) not in lst.text


def test_responses_are_private_no_store(client, sales):
    """K 審 N2：含客戶電話／地址、給個人手機——不留快取。"""
    u, t = sales
    _seed("MQ-NS-001", sales_username=u)
    for url in ("/api/field/cases", "/api/field/cases/MQ-NS-001"):
        assert client.get(url, headers=_auth(t)).headers.get("cache-control") == "private, no-store", url


def test_corrupt_json_is_logged_once_per_case_not_on_every_poll(client, sales, caplog):
    """K 審 N3：手機輪詢同一筆壞資料，ERROR 只在行程內記第一次，之後降為 DEBUG。"""
    import db
    import logging
    from modules.case.api import field_cases as F
    F._LOGGED.clear()
    u, t = sales
    _seed("MQ-LOG-001", sales_username=u)
    conn = db.get_db()
    conn.execute("UPDATE quotations SET data_json='{bad' WHERE quote_no='MQ-LOG-001'")
    conn.commit()
    conn.close()
    with caplog.at_level(logging.ERROR, logger="modules.case.api.field_cases"):
        for _ in range(5):
            assert client.get("/api/field/cases", headers=_auth(t)).status_code == 200
            assert client.get("/api/field/cases/MQ-LOG-001", headers=_auth(t)).status_code == 200
    errs = [r for r in caplog.records if "MQ-LOG-001" in r.getMessage() and r.levelno >= logging.ERROR]
    assert len(errs) == 1, len(errs)


@pytest.mark.parametrize("ascii_json", [False, True])
def test_coarse_filter_finds_cjk_names_under_both_json_encodings(client, make_user, ascii_json):
    """K 審：data_json／assigned_to 可能是 ensure_ascii=True（中文存成跳脫序列）或 False（原文）寫入；SQL 粗篩兩種都要命中，
    否則（假陰性）工程師的列表又是空的。中文顯示名的舊字串角色、物件角色（username）、階段負責人各一筆。"""
    import db
    u, p = make_user(username="fld_cjk", role="engineer", modules=["case_manage"])
    conn = db.get_db()
    conn.execute("UPDATE users SET display_name=? WHERE username=?", ("工程師甲", u))
    conn.commit()
    conn.close()
    t = _login(client, u, p)
    disp = db.get_db().execute("SELECT display_name FROM users WHERE username=?", (u,)).fetchone()[0]
    assert any(ord(c) > 127 for c in disp), "對照組要有中文顯示名才有意義：%r" % disp
    owner, _ = make_user(username="fld_cjk_o", role="user", modules=["case_manage"])
    mk = lambda roles: {"dealTag": "已成案", "caseRecord": {"roles": roles}}
    _seed("MQ-CJK-01", sales_username=owner, data=mk({"executor": disp}), ensure_ascii=ascii_json)              # 舊字串＝顯示名
    _seed("MQ-CJK-02", sales_username=owner, data=mk({"executor": {"username": u, "display": disp}}), ensure_ascii=ascii_json)
    _seed("MQ-CJK-03", sales_username=owner, stages=[("丈量", False, "")], ensure_ascii=ascii_json)
    _seed("MQ-CJK-04", sales_username=owner, data=mk({"executor": "別的人"}), ensure_ascii=ascii_json)          # 無關
    conn = db.get_db()
    conn.execute("UPDATE case_stages SET assigned_to=? WHERE quote_no='MQ-CJK-03'", (json.dumps([u], ensure_ascii=ascii_json),))
    conn.commit()
    conn.close()
    assert _ids(client, t) == ["MQ-CJK-01", "MQ-CJK-02", "MQ-CJK-03"]
    assert client.get("/api/field/cases/MQ-CJK-04", headers=_auth(t)).status_code == 404


def test_coarse_filter_is_a_superset_even_for_names_with_quotes_and_backslashes():
    """username／顯示名含雙引號、反斜線、非 ASCII 時，JSON 兩種寫法都會跳脫它們；粗篩片段在兩種寫法下都不能漏。"""
    import sqlite3
    from modules.case.api.field_cases import _coarse_member_sql
    bs = chr(92)                                       # 反斜線（不在原始碼裡手打跳脫）
    for uname, disp in (('we"ird' + bs + 'user', '王"小' + bs + '明'), ("plain", "王小明"), ("jo_hn", "")):
        user = {"id": 7, "username": uname, "display_name": disp}
        frag, params = _coarse_member_sql(user)
        for ascii_json in (False, True):
            c = sqlite3.connect(":memory:")
            c.execute("CREATE TABLE quotations (quote_no TEXT, sales_person_id INTEGER, sales_person TEXT, assigned_user_ids TEXT, data_json TEXT)")
            c.execute("CREATE TABLE case_stages (quote_no TEXT, assigned_to TEXT)")
            rows = {
                "role_user": {"caseRecord": {"roles": {"executor": {"username": uname}}}},
                "role_str": {"caseRecord": {"roles": {"executor": disp}}} if disp else None,
                "none": {"caseRecord": {"roles": {"executor": "別人"}}},
            }
            for no, d in rows.items():
                if d is not None:
                    c.execute("INSERT INTO quotations VALUES (?,?,?,?,?)", (no, 99, "x", "[]", json.dumps(d, ensure_ascii=ascii_json)))
            c.execute("INSERT INTO quotations VALUES ('staged',99,'x','[]','{}')")
            c.execute("INSERT INTO case_stages VALUES ('staged', ?)", (json.dumps([uname], ensure_ascii=ascii_json),))
            hit = {r[0] for r in c.execute("SELECT quote_no FROM quotations WHERE 1=1" + frag, params)}
            want = {"role_user", "staged"} | ({"role_str"} if disp else set())
            assert hit == want, (uname, ascii_json, hit)


def test_bad_token_is_401_on_both_endpoints(client):
    for url in ("/api/field/cases", "/api/field/cases/MQ-X"):
        assert client.get(url, headers={"Authorization": "Bearer not-a-real-token"}).status_code == 401, url
        assert client.get(url, headers={"Authorization": "garbage"}).status_code == 401, url


def test_same_display_name_but_case_owned_by_another_id_is_not_visible(client, make_user):
    """業務「名字」只在案件沒有業務 id（舊資料）時才比；有 id 的案件，同名但不同人的帳號看不到（列表與單件都是）。"""
    import db
    a, pa = make_user(username="fld_same_a", role="user", modules=["case_manage"])
    b, pb = make_user(username="fld_same_b", role="user", modules=["case_manage"])
    conn = db.get_db()
    conn.execute("UPDATE users SET display_name='同名人' WHERE username IN (?,?)", (a, b))
    conn.commit()
    conn.close()
    tb = _login(client, b, pb)
    _seed("MQ-SAME-01", sales_username=a, sales_display="同名人")        # 有 id＝A：同名的 B 不算
    _seed("MQ-SAME-02", sales_username=None, sales_display="同名人")     # 舊資料沒有 id：比名字，B 看得到
    assert _ids(client, tb) == ["MQ-SAME-02"]
    assert client.get("/api/field/cases/MQ-SAME-01", headers=_auth(tb)).status_code == 404
    assert client.get("/api/field/cases/MQ-SAME-02", headers=_auth(tb)).status_code == 200


def test_before_id_out_of_range_is_clamped_not_a_500(client, sales):
    """K 複審 N1：超過 SQLite INTEGER 上限的 before_id 不可變成 500（OverflowError 會進 ERROR log）。"""
    u, t = sales
    _seed("MQ-BIG-001", sales_username=u)
    for v in ("99999999999999999999", str(2 ** 63), str(2 ** 62), "-5", "0"):
        r = client.get("/api/field/cases?before_id=" + v, headers=_auth(t))
        assert r.status_code == 200, (v, r.status_code)
        assert [i["quote_no"] for i in r.json()["items"]] == ["MQ-BIG-001"], v          # 大於所有 id ⇒ 從頭；非正數 ⇒ 從頭
    assert client.get("/api/field/cases?before_id=abc", headers=_auth(t)).status_code == 422
