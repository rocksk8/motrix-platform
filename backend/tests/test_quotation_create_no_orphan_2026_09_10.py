"""2026-09-10：送審失敗不可以留下孤兒報價單。

起因：追既有 e2e flaky 測試的根因時（診斷 dump 顯示 approver 開的是
`MQ-202609-002`、簽核流程卻建在 `MQ-202609-001`）做了可控重現，發現
`create_quotation()` 是「先 INSERT + commit，再建簽核層級」——層級解析失敗時
拋 400，但那筆 `status='待審核'` 的報價單已經留在資料庫裡，而且沒有任何簽核層級：

  * 它會出現在報價單清單／簽核佇列統計裡
  * 沒有 tiers 就永遠簽不掉
  * 使用者看到「送出審核失敗」以為沒建成，再按一次又多一張（單號還往後跳）

修法是補償性刪除：建不出簽核流程就把剛剛建立的那筆收回去再拋錯。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _submit_payload():
    return {
        "status": "待審核",
        "data": {
            "customerName": "孤兒測試客戶",
            "projectName": "孤兒測試專案",
            "salesPerson": "",
            "quoteDate": "2026-09-10",
            "tot": {"total": 1000, "pretax": 952,
                    "directMarginPct": 0, "netMarginPct": 0},
            "items": [{"description": "品項 A", "amount": 1000}],
            "approval": {"requestedBy": "", "status": "pending"},
        },
    }


def _count_quotations(prefix="MQ-"):
    import db
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT COUNT(*) c FROM quotations WHERE quote_no LIKE ?", (prefix + "%",)
        ).fetchone()["c"]
    finally:
        conn.close()


def test_failed_submission_leaves_no_orphan(client, make_user):
    """申請人沒有歸屬部門 → 簽核層級解析失敗 → 回 400，且**資料庫不留任何報價單**。"""
    username, password = make_user(username="orphan_user", role="admin")
    token = _login(client, username, password)

    before = _count_quotations()

    body = _submit_payload()
    body["data"]["approval"]["requestedBy"] = username
    r = client.post("/api/quotations", json=body, headers=_auth(token))

    assert r.status_code == 400, (
        f"申請人未歸屬部門時送審應回 400，實際 {r.status_code}: {r.text}"
    )
    after = _count_quotations()
    assert after == before, (
        f"送審失敗卻留下了 {after - before} 張報價單——"
        f"這種孤兒單沒有簽核層級、永遠簽不掉，還會讓使用者重按時單號一直往後跳"
    )


def test_failed_submission_twice_does_not_burn_numbers(client, make_user):
    """連按兩次失敗的送審，不會累積出兩張孤兒單、也不會把單號燒掉。"""
    username, password = make_user(username="orphan_user2", role="admin")
    token = _login(client, username, password)

    body = _submit_payload()
    body["data"]["approval"]["requestedBy"] = username
    for _ in range(2):
        r = client.post("/api/quotations", json=body, headers=_auth(token))
        assert r.status_code == 400, r.text

    assert _count_quotations() == 0, "兩次失敗的送審不該留下任何報價單"

    # 失敗過之後，下一張成功的單仍然要拿到 001（號碼沒有被燒掉）
    r = client.get("/api/next-quote-no", headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["quote_no"].endswith("-001"), (
        f"失敗的送審把單號燒掉了，下一號變成 {r.json()['quote_no']}"
    )


def test_successful_draft_create_is_kept(client, make_user):
    """反向釘住：草稿（非送審）不受影響，正常建立且留在資料庫。"""
    username, password = make_user(username="orphan_user3", role="admin")
    token = _login(client, username, password)

    body = _submit_payload()
    body["status"] = "草稿"
    body["data"].pop("approval", None)
    r = client.post("/api/quotations", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    assert _count_quotations() == 1


def test_backend_assigns_number_when_client_sends_none(client, make_user):
    """前端不再自己猜號（原本會寫死 MQ-{ym}-001）：完全不送 quote_no 時，
    後端要派一個有效號碼並回傳，前端據此回填。"""
    username, password = make_user(username="assign_user", role="admin")
    token = _login(client, username, password)

    body = _submit_payload()
    body["status"] = "草稿"
    body["data"].pop("approval", None)

    r = client.post("/api/quotations", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    qno = r.json()["quote_no"]
    assert qno and qno.startswith("MQ-"), f"後端應派出有效單號，實際 {qno!r}"

    import db
    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT quote_no FROM quotations WHERE quote_no=?", (qno,)).fetchone()
    finally:
        conn.close()
    assert row, f"回傳的單號 {qno} 在資料庫裡不存在——回傳值與實際存檔必須一致"
