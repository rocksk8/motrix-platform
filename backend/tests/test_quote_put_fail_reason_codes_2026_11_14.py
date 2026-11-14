"""報價單整份存檔（PUT）被擋時帶失敗原因碼（T86 U1，2026-11-14）。

正式機 90 天：主檔 PUT 失敗 403 ×14、409 ×2，audit 只記狀態碼沒有原因，無法判斷是「狀態鎖定」還是「權限」。
修法：端點在回應標頭 `X-Fail-Reason` 帶固定詞彙的原因碼（不改回應本文），main.py 的失敗稽核據此記 `reason_code`。
觀測點：回應標頭＋ audit_log 失敗列的 reason_code；正對照：沒帶碼的 409（版本衝突）仍記預設的 conflict。
"""
import json

import pytest

from helpers import audit as A


@pytest.fixture(autouse=True)
def _clean_fail_state():
    A._FAIL_LAST.clear()
    A._FAIL_HOUR.clear()
    yield
    A._FAIL_LAST.clear()
    A._FAIL_HOUR.clear()


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _seed(quote_no, status):
    import db
    data = {"quoteNo": quote_no, "status": status, "customerName": "測試客戶", "projectName": "測試專案", "items": []}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, status, "測試客戶", "測試專案", 0, 0, json.dumps(data, ensure_ascii=False),
             "2026-11-14T09:00:00", "2026-11-14T09:00:00", "", "業務X", "[]"))
        conn.commit()
    finally:
        conn.close()


def _fail_rows(username):
    """只讀**這個測試自己的使用者**寫下的失敗列：audit_log 是整個 worker 共用的表，讀整張會撞到前面測試留下的 login_failed 等列。"""
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_log WHERE result='fail' AND username=? ORDER BY id", (username,)).fetchall()]
    finally:
        conn.close()


def _put(client, h, quote_no, status, extra=None):
    data = {"quoteNo": quote_no, "status": status, "customerName": "測試客戶", "projectName": "測試專案", "items": []}
    data.update(extra or {})
    return client.put(f"/api/quotations/{quote_no}", headers=h, json={"quote_no": quote_no, "status": status, "data": data})


def test_locked_status_put_is_403_with_status_locked_code_in_header_and_audit(client, make_user):
    u, p = make_user(username="qf_sa1", role="superadmin", modules=[])
    h = _login(client, u, p)
    _seed("MQ-2611-901", "已送出")
    r = _put(client, h, "MQ-2611-901", "已送出")
    assert r.status_code == 403, r.text
    assert r.headers.get("X-Fail-Reason") == "status_locked"
    assert "請透過正式流程操作或解鎖後修改" in r.json()["detail"], "回應本文不變"
    rows = [x for x in _fail_rows(u) if x["status_code"] == 403]
    assert len(rows) == 1 and rows[0]["reason_code"] == "status_locked"
    assert "status_locked" in A._FAIL_REASON_LABELS


def test_rejected_quote_put_is_403_with_rejected_locked_code(client, make_user):
    u, p = make_user(username="qf_sa2", role="superadmin", modules=[])
    h = _login(client, u, p)
    _seed("MQ-2611-902", "已拒絕")
    r = _put(client, h, "MQ-2611-902", "已拒絕")
    assert r.status_code == 403, r.text
    assert r.headers.get("X-Fail-Reason") == "rejected_locked"
    assert [x["reason_code"] for x in _fail_rows(u) if x["status_code"] == 403] == ["rejected_locked"]


def test_version_conflict_409_keeps_default_conflict_code(client, make_user):
    u, p = make_user(username="qf_sa3", role="superadmin", modules=[])
    h = _login(client, u, p)
    _seed("MQ-2611-903", "草稿")
    r = _put(client, h, "MQ-2611-903", "草稿", {"_expectedUpdatedAt": "2020-01-01T00:00:00"})
    assert r.status_code == 409, r.text
    assert not r.headers.get("X-Fail-Reason"), "版本衝突沒有另帶碼（維持依狀態碼的預設）"
    assert [x["reason_code"] for x in _fail_rows(u) if x["status_code"] == 409] == ["conflict"]


def test_unknown_reason_code_falls_back_to_status_default():
    """不認得的碼不能被寫進 reason_code（固定詞彙）：退回依狀態碼的預設。"""
    A._audit_failure(5, "qf_unknown_code_user", "U", "PUT", "/api/quotations/{quote_no}", 403, reason="made_up_code", now=10.0)
    assert [x["reason_code"] for x in _fail_rows("qf_unknown_code_user")] == ["permission_denied"]
