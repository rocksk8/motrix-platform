"""案件清單改由伺服器搜尋／篩選／排序／分頁（2026-09-24 使用者表單）。

過去案件頁一次拉 limit=500 再在前端篩 ⇒ 第 501 件以後永遠看不到、搜尋也搜不到。
GET /api/quotations 新增（皆選填、舊呼叫端不受影響）：
- q：單號／客戶／專案名稱關鍵字
- settle=draft：待精算
- sort＝quote_date／customer_name／total，dir＝asc／desc；
  看不到金額的帳號不可依金額排序（排序本身會洩漏金額大小）⇒ 忽略
- counts=1：回 counts（進行中／已結案／待精算／逾期階段數），不受 q 與分頁影響
edit_last 改在 SQL 取最後一筆，不再把整段 editHistory 撈回來。
"""
import json

import pytest

URL = "/api/quotations"
BOTH = "已成案,已結案"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _bulk(n, *, prefix="MQ-LIST-", deal_tag="已成案", customer="批量客戶", start=0, total_of=None):
    import db
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        for i in range(start, start + n):
            no = f"{prefix}{i:04d}"
            total = total_of(i) if total_of else 1000
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (no, "已送出", customer, f"專案{i}", total, total,
                 json.dumps({"dealTag": deal_tag}, ensure_ascii=False), now, now, deal_tag, "2026-08-01"))
        conn.commit()
    finally:
        conn.close()


def _one(no, *, customer="客戶", project="專案", deal_tag="已成案", settlement=None, edit_history=None,
         overdue_stages=0, total=1000, quote_date="2026-08-01"):
    import db
    now = "2026-01-01T00:00:00"
    d = {"dealTag": deal_tag}
    if settlement:
        d["settlement"] = settlement
    if edit_history is not None:
        d["editHistory"] = edit_history
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", customer, project, total, total, json.dumps(d, ensure_ascii=False),
             now, now, deal_tag, quote_date))
        for k in range(overdue_stages):
            conn.execute("INSERT INTO case_stages (quote_no, label, sort_order, done, due_date, created_at, updated_at)"
                         " VALUES (?,?,?,?,?,?,?)", (no, f"逾期{k}", k, 0, "2020-01-01", now, now))
        conn.commit()
    finally:
        conn.close()


def test_search_finds_a_case_beyond_the_first_500(client, make_user):
    h = _login(client, *make_user(username="cl_admin1", role="admin"))
    _bulk(520)
    _one("MQ-LIST-FAR", customer="很遠的客戶")
    # 讓目標排在最舊（id 最小以外的位置不重要，重點是它不在前 500 筆之內也要搜得到）
    r = client.get(URL, headers=h, params={"deal_tag": BOTH, "q": "很遠", "limit": 50})
    assert r.status_code == 200, r.text
    assert [c["quote_no"] for c in r.json()["items"]] == ["MQ-LIST-FAR"]
    assert r.json()["total"] == 1
    r = client.get(URL, headers=h, params={"deal_tag": BOTH, "q": "list-0519", "limit": 50})
    assert [c["quote_no"] for c in r.json()["items"]] == ["MQ-LIST-0519"], "單號搜尋要不分大小寫"


def test_paging_reaches_every_case(client, make_user):
    h = _login(client, *make_user(username="cl_admin2", role="admin"))
    _bulk(230)
    seen = []
    for off in (0, 100, 200):
        body = client.get(URL, headers=h, params={"deal_tag": BOTH, "limit": 100, "offset": off}).json()
        assert body["total"] == 230
        seen += [c["quote_no"] for c in body["items"]]
    assert len(seen) == len(set(seen)) == 230


def test_settle_draft_filter(client, make_user):
    h = _login(client, *make_user(username="cl_admin3", role="admin"))
    _one("MQ-SET-DRAFT", settlement={"status": "draft"})
    _one("MQ-SET-FINAL", settlement={"status": "finalized"})
    _one("MQ-SET-NONE")
    body = client.get(URL, headers=h, params={"deal_tag": BOTH, "settle": "draft"}).json()
    assert [c["quote_no"] for c in body["items"]] == ["MQ-SET-DRAFT"]


def test_sort_by_customer_and_total(client, make_user):
    h = _login(client, *make_user(username="cl_admin4", role="admin"))
    _one("MQ-SORT-1", customer="丙", total=300)
    _one("MQ-SORT-2", customer="甲", total=100)
    _one("MQ-SORT-3", customer="乙", total=200)
    by_total = client.get(URL, headers=h, params={"deal_tag": BOTH, "sort": "total", "dir": "desc"}).json()
    assert [c["quote_no"] for c in by_total["items"]] == ["MQ-SORT-1", "MQ-SORT-3", "MQ-SORT-2"]
    by_cust = client.get(URL, headers=h, params={"deal_tag": BOTH, "sort": "customer_name", "dir": "asc"}).json()
    assert [c["customer_name"] for c in by_cust["items"]] == sorted(["丙", "甲", "乙"])


def test_masked_account_cannot_sort_by_amount(client, make_user):
    h = _login(client, *make_user(username="cl_eng", role="engineer", modules=["case_manage"]))
    _one("MQ-MASK-1", total=300)
    _one("MQ-MASK-2", total=100)
    _one("MQ-MASK-3", total=200)
    import db
    conn = db.get_db()
    try:
        uid = conn.execute("SELECT id FROM users WHERE username='cl_eng'").fetchone()[0]
        conn.execute("UPDATE quotations SET assigned_user_ids=? WHERE quote_no LIKE 'MQ-MASK-%'", (json.dumps([uid]),))
        conn.commit()
    finally:
        conn.close()
    asc = client.get(URL, headers=h, params={"deal_tag": BOTH, "sort": "total", "dir": "asc"}).json()["items"]
    desc = client.get(URL, headers=h, params={"deal_tag": BOTH, "sort": "total", "dir": "desc"}).json()["items"]
    assert all(c["total"] is None for c in asc), "遮蔽帳號不回金額"
    # 依金額排序被忽略 ⇒ 兩個方向的順序相同（預設排序），不會洩漏大小
    assert [c["quote_no"] for c in asc] == [c["quote_no"] for c in desc]


def test_counts_ignore_search_and_paging(client, make_user):
    h = _login(client, *make_user(username="cl_admin5", role="admin"))
    _one("MQ-CNT-A1", overdue_stages=2)
    _one("MQ-CNT-A2", settlement={"status": "draft"})
    _one("MQ-CNT-C1", deal_tag="已結案")
    _one("MQ-CNT-X", deal_tag="未成案")
    body = client.get(URL, headers=h, params={"deal_tag": BOTH, "counts": 1, "q": "A1", "limit": 1}).json()
    assert body["counts"] == {"all": 3, "active": 2, "closed": 1, "settling": 1, "overdueStages": 2}


def test_edit_last_is_the_last_history_entry(client, make_user):
    h = _login(client, *make_user(username="cl_admin6", role="admin"))
    _one("MQ-EDIT-1", edit_history=[{"rev": 1, "at": "a", "by": "u1", "type": "edit"},
                                    {"rev": 2, "at": "b", "byDisplay": "王", "type": "revise"}])
    _one("MQ-EDIT-0", edit_history=[])
    items = {c["quote_no"]: c for c in client.get(URL, headers=h, params={"deal_tag": BOTH}).json()["items"]}
    assert items["MQ-EDIT-1"]["edit_last"] == {"rev": 2, "at": "b", "byDisplay": "王", "type": "revise"}
    assert items["MQ-EDIT-1"]["edit_count"] == 2
    assert items["MQ-EDIT-0"]["edit_last"] is None
