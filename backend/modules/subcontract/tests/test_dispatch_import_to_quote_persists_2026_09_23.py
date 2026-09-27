"""2026-09-23（T9）：派發回推報價單品項 —— 回 200 而資料庫沒寫入。

`POST /api/contractor-dispatches/{did}/import-to-quote` 的兩個缺陷，
與 `modules/case/api/material_orders.py` 2026-09-10 修過的①②**同一型**：

① `save_quotation_json()` 之後沒有 `conn.commit()` 就 `conn.close()`
   ⇒ UPDATE 被回滾，端點照樣回 `{"ok": True, "imported": N}`
② 第 4 個位置參數傳 `user["username"]`，而簽名第 4 個是 `status`
   ⇒ **只修①會讓報價單狀態變成使用者名稱**（①遮住了②）

⚠️ 所以兩題的觀測點都打在**資料庫本身**（`data_json.items` 與 `status` 欄），
   直接讀表、不透過剛剛寫入的那支 API —— 回應正是當初會騙人的那個東西。
"""
import json

import pytest


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _insert_draft_quote_and_dispatch(quote_no):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, "
            "total, pretax, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "草稿", "測試客戶", "測試專案", 0, 0,
             json.dumps({"items": [{"id": "orig-1", "description": "原有品項"}]},
                        ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        items = [{"description": "配線施工", "qty": 3, "unit": "式", "unitPrice": 1200}]
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, "
            "total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (quote_no, "2026-01-01", "items", json.dumps(items, ensure_ascii=False),
             3600, "pending", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        did = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.commit()
        return did
    finally:
        conn.close()


def _row(quote_no):
    import db
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT status, updated_at, data_json FROM quotations WHERE quote_no=?",
            (quote_no,)).fetchone()
    finally:
        conn.close()


@pytest.fixture()
def admin(client, make_user):
    username, password = make_user("t9_admin", role="admin")
    return _login(client, username, password)


def test_import_actually_persists_items(client, admin):
    """①：回 200 之後，資料庫的 data_json.items 必須真的多了派發品項。"""
    did = _insert_draft_quote_and_dispatch("MQ-T9-001")
    r = client.post(f"/api/contractor-dispatches/{did}/import-to-quote", headers=_auth(admin))
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 1

    items = json.loads(_row("MQ-T9-001")["data_json"])["items"]
    descs = [it.get("description") for it in items]
    assert "配線施工" in descs, f"派發品項沒有真的寫進 data_json（回 200 不代表有 commit）：{descs}"
    assert descs[0] == "原有品項", "原有品項被覆蓋或重排了"
    assert len(items) == 3, f"預期 原有1＋區段標題1＋派發1＝3 列，實得 {len(items)}"


def test_import_does_not_corrupt_status_or_updated_at(client, admin):
    """②：狀態必須維持「草稿」，不可以變成使用者名稱；updated_at 必須可解析。"""
    did = _insert_draft_quote_and_dispatch("MQ-T9-002")
    r = client.post(f"/api/contractor-dispatches/{did}/import-to-quote", headers=_auth(admin))
    assert r.status_code == 200, r.text

    after = _row("MQ-T9-002")
    assert after["status"] == "草稿", f"報價單 status 被匯入端點改成了 {after['status']!r}"
    from datetime import datetime
    datetime.fromisoformat(after["updated_at"])
    assert after["updated_at"] != "2026-01-01T00:00:00", "updated_at 沒有更新（UPDATE 沒落地）"
    assert after["updated_at"] == r.json()["updated_at"], "回應的 updated_at 與資料庫不一致"
