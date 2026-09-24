"""案件清單常用篩選（2026-09-24 使用者表單），全部在伺服器端（CM6 的清單端點）。

GET /api/quotations 選填：
- mine=1：我負責的＝業務歸屬是我、被分配（assigned_user_ids）、或案件角色（填表人／業務負責／執行負責）
  的帳號是我
- stage_overdue=1：有未完成且已過到期日的執行階段
- recv_overdue=1：有未收款且預計收款日（expectedReceiptDate）已過的期別（當日不算）
- missing_docs=1：缺發票（已收款卻沒登錄發票號碼），或執行階段全部完成而完工單與出貨單兩張都沒有
  （使用者裁示 ④，同日更正：只有其一不算缺）；每筆回傳 missing_invoice／missing_notes 標出原因
- unread=1：有別人造成、我還沒看過的動態（與未讀紅點同一套判斷，item_reads）；不受分頁限制
counts 另回 mine／stageOverdueCases／recvOverdue／missingDocs／unread 的件數。
"""
import json

URL = "/api/quotations"
BOTH = "已成案,已結案"


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


def _case(no, *, items=(), roles=None, sales="", assigned=(), overdue_stage=False, done_stages=0,
          completion=False, shipping=False):
    import db
    now = "2026-01-01T00:00:00"
    cr = {"payment": {"items": list(items)}}
    if roles:
        cr["roles"] = roles
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date, sales_person, assigned_user_ids)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", "客戶", "專案", 1000, 952,
             json.dumps({"dealTag": "已成案", "caseRecord": cr}, ensure_ascii=False),
             now, now, "已成案", "2026-08-01", sales, json.dumps(list(assigned))))
        if overdue_stage:
            conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, due_date, created_at, updated_at)"
                         " VALUES (?,?,?,?,?,?,?)", (no, "逾期", 0, 0, "2020-01-01", now, now))
        for k in range(done_stages):
            conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, created_at, updated_at)"
                         " VALUES (?,?,?,?,?,?)", (no, f"完成{k}", k + 1, 1, now, now))
        if completion:
            conn.execute("INSERT INTO completion_notes (note_no, quote_no, status, data_json, created_at, updated_at)"
                         " VALUES (?,?,?,?,?,?)", ("CN-" + no, no, "已核准", "{}", now, now))
        if shipping:
            conn.execute("INSERT INTO shipping_notes (note_no, quote_no, status, customer_name, items_json, data_json,"
                         " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                         ("SN-" + no, no, "已核准", "客戶", "[]", "{}", now, now))
        conn.commit()
    finally:
        conn.close()


def _nos(client, h, **params):
    r = client.get(URL, headers=h, params={"deal_tag": BOTH, **params})
    assert r.status_code == 200, r.text
    return sorted(c["quote_no"] for c in r.json()["items"])


def test_mine_covers_sales_assigned_and_case_roles(client, make_user):
    h = _login(client, *make_user(username="qf_me", role="admin"))
    make_user(username="qf_other", role="admin")
    me = _uid("qf_me")
    _case("MQ-QF-SALES", sales="qf_me")                         # 業務歸屬（display_name＝username）
    _case("MQ-QF-ASSIGN", assigned=[me])
    _case("MQ-QF-ROLE", roles={"executor": {"username": "qf_me", "display": "我"}})
    _case("MQ-QF-NOTME", sales="qf_other", roles={"executor": {"username": "qf_other", "display": "他"}})
    assert _nos(client, h, mine=1) == ["MQ-QF-ASSIGN", "MQ-QF-ROLE", "MQ-QF-SALES"]


def test_stage_overdue(client, make_user):
    h = _login(client, *make_user(username="qf_a1", role="admin"))
    _case("MQ-QF-LATE", overdue_stage=True)
    _case("MQ-QF-OK")
    assert _nos(client, h, stage_overdue=1) == ["MQ-QF-LATE"]


def test_receivable_overdue(client, make_user):
    h = _login(client, *make_user(username="qf_a2", role="admin"))
    _case("MQ-QF-RECV-LATE", items=[{"id": 1, "received": False, "expectedReceiptDate": "2020-01-01"}])
    _case("MQ-QF-RECV-PAID", items=[{"id": 1, "received": True, "expectedReceiptDate": "2020-01-01",
                                     "invoiceNo": "AB12345678"}])
    _case("MQ-QF-RECV-FUTURE", items=[{"id": 1, "received": False, "expectedReceiptDate": "2099-01-01"}])
    _case("MQ-QF-RECV-NODATE", items=[{"id": 1, "received": False, "expectedReceiptDate": ""}])
    assert _nos(client, h, recv_overdue=1) == ["MQ-QF-RECV-LATE"]


def test_missing_docs_invoice_or_notes_after_all_stages_done(client, make_user):
    h = _login(client, *make_user(username="qf_a3", role="admin"))
    _case("MQ-QF-NOINV", items=[{"id": 1, "received": True, "invoiceNo": ""}])
    _case("MQ-QF-HASINV", items=[{"id": 1, "received": True, "invoiceNo": "AB12345678"}])
    _case("MQ-QF-UNPAID", items=[{"id": 1, "received": False, "invoiceNo": ""}])
    _case("MQ-QF-DONE-ONLYSN", done_stages=2, shipping=True)                # 只有出貨單 ⇒ 不算缺
    _case("MQ-QF-DONE-ONLYCN", done_stages=2, completion=True)              # 只有完工單 ⇒ 不算缺
    _case("MQ-QF-DONE-NONE", done_stages=2)                                 # 兩張都沒有 ⇒ 缺
    _case("MQ-QF-RUNNING", done_stages=1, overdue_stage=True)               # 還沒全完成 ⇒ 不算缺
    assert _nos(client, h, missing_docs=1) == ["MQ-QF-DONE-NONE", "MQ-QF-NOINV"]
    rows = {c["quote_no"]: c for c in client.get(URL, headers=h, params={"deal_tag": BOTH, "missing_docs": 1}).json()["items"]}
    assert (rows["MQ-QF-NOINV"]["missing_invoice"], rows["MQ-QF-NOINV"]["missing_notes"]) == (1, 0)
    assert (rows["MQ-QF-DONE-NONE"]["missing_invoice"], rows["MQ-QF-DONE-NONE"]["missing_notes"]) == (0, 1)


def test_unread_is_server_side_and_ignores_paging(client, make_user):
    h = _login(client, *make_user(username="qf_reader", role="admin"))
    for i in range(30):
        _case(f"MQ-QF-U{i:02d}")
    # 先建立未讀基準，再由別人在基準之後留一則動態（在最舊的那一件）
    client.post("/api/reads/unread", headers=h, json={"kind": "case", "keys": []})
    import time
    from datetime import datetime
    import db
    time.sleep(1.1)                     # 時間戳到秒：動態要嚴格晚於基準，已讀要嚴格晚於動態
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO case_updates (quote_no, author, content, created_at) VALUES (?,?,?,?)",
                     ("MQ-QF-U00", "別人", "有新動態", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
    finally:
        conn.close()
    assert _nos(client, h, unread=1, limit=5) == ["MQ-QF-U00"]
    body = client.get(URL, headers=h, params={"deal_tag": BOTH, "counts": 1, "limit": 0}).json()
    assert body["counts"]["unread"] == 1
    # 標成已讀之後就不在了
    time.sleep(1.1)
    client.post("/api/reads", headers=h, json={"kind": "case", "key": "MQ-QF-U00"})
    assert _nos(client, h, unread=1) == []


def test_counts_for_quick_filters(client, make_user):
    h = _login(client, *make_user(username="qf_cnt", role="admin"))
    _case("MQ-QF-C1", sales="qf_cnt", overdue_stage=True,
          items=[{"id": 1, "received": False, "expectedReceiptDate": "2020-01-01"}])
    _case("MQ-QF-C2", items=[{"id": 1, "received": True, "invoiceNo": ""}])
    c = client.get(URL, headers=h, params={"deal_tag": BOTH, "counts": 1, "limit": 0}).json()["counts"]
    assert (c["mine"], c["stageOverdueCases"], c["recvOverdue"], c["missingDocs"]) == (1, 1, 1, 1)
