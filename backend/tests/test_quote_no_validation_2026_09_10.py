"""2026-09-10：client 送來的報價單號一律要通過格式驗證才採用。

起因：`quotation-form.html::copyToNew()` 在取不到號時會造一個
`MQ-YYYYMM-???` 佔位字串當單號送出。那個字串**不會**跟任何既有單號衝突
（先前誤以為會撞號改派），所以 INSERT 成功，接著

    seq_no = int(qno.split("-")[-1])     # int('???')

直接炸成未捕捉的 ValueError → 500。使用者只看到「儲存失敗」，而複製的內容
在頁面載入時就已經從 sessionStorage 清掉，重新整理再也回不來。

前端那一處已修（不再造假號），但「後端才是單號的權威」要在這裡守住——
不管哪個 client、哪個版本送什麼過來，格式不對就由後端自己派號。
"""
import json

import pytest


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _payload(quote_no):
    return {
        "quote_no": quote_no,
        "status": "草稿",
        "data": {
            "customerName": "單號驗證客戶",
            "projectName": "單號驗證專案",
            "quoteNo": quote_no,
            "quoteDate": "2026-09-10",
            "tot": {"total": 1000, "pretax": 952,
                    "directMarginPct": 0, "netMarginPct": 0},
        },
    }


BAD_NUMBERS = [
    "MQ-202609-???",      # copyToNew() 舊版的佔位字串（本 bug 的來源）
    "MQ-202609-??",
    "MQ-2026-001",        # 月份位數不對
    "MQ-202609-1",        # 序號沒補零
    "MQ-202609-0001",     # 序號太長
    "XX-202609-001",      # 前綴不對
    "MQ-202609-ABC",
    "隨便亂打",
    "'; DROP TABLE quotations; --",
]


@pytest.mark.parametrize("bad", BAD_NUMBERS)
def test_malformed_quote_no_is_replaced_not_crashed(client, make_user, bad):
    """格式不合的單號不該讓端點爆掉，而是由後端派一個合法號碼。"""
    username, password = make_user(username="qno_user", role="admin")
    token = _login(client, username, password)

    r = client.post("/api/quotations", json=_payload(bad), headers=_auth(token))
    assert r.status_code == 201, (
        f"送 {bad!r} 應該正常建立（由後端派號），實際 {r.status_code}: {r.text[:200]}"
    )
    qno = r.json()["quote_no"]
    assert qno != bad, f"格式不合的 {bad!r} 不該被原樣採用"
    assert qno.startswith("MQ-") and qno.count("-") == 2, f"後端派的號碼不合法：{qno!r}"
    assert qno.split("-")[-1].isdigit(), f"序號不是數字：{qno!r}"

    import db
    conn = db.get_db()
    try:
        assert conn.execute(
            "SELECT 1 FROM quotations WHERE quote_no=?", (qno,)).fetchone(), \
            f"回傳的單號 {qno} 在資料庫裡不存在"
        assert not conn.execute(
            "SELECT 1 FROM quotations WHERE quote_no=?", (bad,)).fetchone(), \
            f"格式不合的 {bad!r} 竟然真的被寫進資料庫"
    finally:
        conn.close()


def test_wellformed_quote_no_is_honoured(client, make_user):
    """反向釘住：格式正確的單號仍然照用（前端正常取號的路徑不受影響）。"""
    username, password = make_user(username="qno_user2", role="admin")
    token = _login(client, username, password)

    r = client.post("/api/quotations", json=_payload("MQ-202609-007"), headers=_auth(token))
    assert r.status_code == 201, r.text
    assert r.json()["quote_no"] == "MQ-202609-007"


def test_quote_seq_advances_for_backend_assigned_number(client, make_user):
    """後端派號之後，quote_seq 要跟著前進，下一張不會拿到同一個號。"""
    username, password = make_user(username="qno_user3", role="admin")
    token = _login(client, username, password)

    first = client.post("/api/quotations", json=_payload("MQ-202609-???"),
                        headers=_auth(token))
    assert first.status_code == 201, first.text
    second = client.post("/api/quotations", json=_payload("MQ-202609-???"),
                         headers=_auth(token))
    assert second.status_code == 201, second.text
    assert first.json()["quote_no"] != second.json()["quote_no"], \
        "連續兩張由後端派號的報價單拿到同一個號碼"
