"""案件關卡矩陣 `/api/quotations/gate-matrix`（2026-09-14）。

這支端點把「完結案五項前置條件」攤成一案一列供案件管理的矩陣使用，判定完全來自
`_case_close_gates()`——跟 `update_deal_tag()` 擋下完結案的是同一份程式碼。
這裡釘住三件實作過程中真的踩到、而且回歸時會安靜壞掉的事：

1. **路由順序**。`/api/quotations/{quote_no}` 定義在前面的話，
   `GET /api/quotations/gate-matrix` 會先命中它、被當成一個叫 gate-matrix 的
   單號而回 404——端點看起來就像「沒生效」。實作時就是這樣踩到的。
2. **na 不是 blocked**。沒有階段／沒有款項／沒有精算資料的舊案件，那幾關是
   「不適用」而不是「未達成」（①②④原本就有的語意）。矩陣上要畫成空心灰；
   若誤把 na 當 ok 計入 readyCount，一件什麼都沒建的空案件會顯示成 5/5 可結案，
   那是這個畫面最危險的誤導。
3. **canClose 必須跟實際按下去的結果一致**。矩陣說「可結案」而 API 回 400 的話，
   這個畫面就沒有存在的意義了。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json

import pytest
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": "Bearer " + token}


def _seed_case(quote_no, customer="測試客戶", deal_tag="已成案", data=None):
    """直接塞一筆已成案的報價單。

    ⚠️ deal_tag 必須**同時**寫進欄位與 data_json.dealTag。兩邊的讀取口徑不一樣：
    清單／矩陣走 SQL_DEAL_TAG（欄位優先、再退回 data_json），但
    update_deal_tag() 判斷「已結案只能從已成案進入」時讀的是
    `d.get("dealTag")`——只寫欄位的話矩陣看得到案件、完結案卻會回 400
    「案件須先標記為『已成案』」。正常寫入路徑會同步兩邊（§4.2 熱路徑同步），
    這裡是種資料，得自己補上。
    """
    import db
    payload = dict(data or {})
    payload["dealTag"] = deal_tag
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, customer_name, project_name, status, "
            "deal_tag, total, data_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, customer, "測試案件", "已送出", deal_tag, 100000,
             json.dumps(payload), "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def _add_stage(quote_no, label, done, sort_order=0, due_date=""):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO case_stages (quote_no, label, done, sort_order, due_date, "
            "start_date, done_at, depends_on, assigned_to, created_at, updated_at) "
            "VALUES (?,?,?,?,?,'','','','[]',?,?)",
            (quote_no, label, 1 if done else 0, sort_order, due_date,
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def test_gate_matrix_route_is_not_swallowed_by_quote_no(client, make_user):
    """路由順序守門：這支必須回 200，不能被 /api/quotations/{quote_no} 吃掉成 404。"""
    u, p = make_user(username="gm_route", role="superadmin")
    token = _login(client, u, p)
    r = client.get("/api/quotations/gate-matrix", headers=_auth(token))
    assert r.status_code == 200, (
        f"回 {r.status_code}——如果是 404，八成是這支的 @router.get 被排到了 "
        f"/api/quotations/{{quote_no}} 後面（FastAPI 依定義順序比對）。"
    )
    assert "items" in r.json()


def test_empty_case_is_not_reported_as_ready_to_close(client, make_user):
    """什麼都沒建的案件：readyCount 不可以是 5。

    實測的正確答案是 1/5——①②④⑤ 都是 na，但③單據是 ok，因為**報價單自己
    就算一份單據**（_CLOSE_DOC_TABLES 的第一項就是 quotations），而它的狀態是
    「已送出」＝簽核已完成。這是對的，不是漏判。

    canClose 仍然是 True——沒有任何 blocked，實際上也真的按得下去；
    重點是 na 不可以被算成 ok，否則空案件會顯示成 5/5 可結案。
    """
    u, p = make_user(username="gm_empty", role="superadmin")
    token = _login(client, u, p)
    _seed_case("MQ-GM-EMPTY")

    r = client.get("/api/quotations/gate-matrix", headers=_auth(token))
    assert r.status_code == 200
    item = next(i for i in r.json()["items"] if i["quoteNo"] == "MQ-GM-EMPTY")

    states = {g["key"]: g["state"] for g in item["gates"]}
    assert states == {"progress": "na", "payment": "na", "documents": "ok",
                      "settlement": "na", "extraExpense": "na"}, item["gates"]
    assert item["readyCount"] == 1, "na 被誤算成 ok 了——空案件會顯示成 5/5 可結案"
    assert item["naCount"] == 4
    assert item["blockedCount"] == 0
    assert item["canClose"] is True


def test_incomplete_progress_blocks_and_is_reported(client, make_user):
    """階段沒做完：進度關卡 blocked、canClose False、value 是 done/total。"""
    u, p = make_user(username="gm_prog", role="superadmin")
    token = _login(client, u, p)
    _seed_case("MQ-GM-PROG")
    _add_stage("MQ-GM-PROG", "訂單確認", True, 0)
    _add_stage("MQ-GM-PROG", "施工安裝", False, 1)

    r = client.get("/api/quotations/gate-matrix", headers=_auth(token))
    item = next(i for i in r.json()["items"] if i["quoteNo"] == "MQ-GM-PROG")
    progress = next(g for g in item["gates"] if g["key"] == "progress")

    assert progress["state"] == "blocked"
    assert progress["value"] == "1/2"
    assert progress["ratio"] == pytest.approx(0.5)
    assert item["canClose"] is False
    assert "進度" in item["blockedLabels"]


def test_can_close_matches_the_real_close_endpoint(client, make_user):
    """canClose 為 True 的案件，實際打完結案端點必須真的成功（不能被 400 擋）。

    這是整個矩陣的存在前提：畫面說可以結案，按下去就要真的可以。
    """
    u, p = make_user(username="gm_close", role="superadmin")
    token = _login(client, u, p)
    _seed_case("MQ-GM-CLOSE")
    _add_stage("MQ-GM-CLOSE", "訂單確認", True, 0)

    r = client.get("/api/quotations/gate-matrix", headers=_auth(token))
    item = next(i for i in r.json()["items"] if i["quoteNo"] == "MQ-GM-CLOSE")
    assert item["canClose"] is True, item["blockedLabels"]

    closed = client.patch("/api/quotations/MQ-GM-CLOSE/deal-tag",
                          json={"deal_tag": "已結案"}, headers=_auth(token))
    assert closed.status_code == 200, (
        f"矩陣說可結案，實際完結案卻回 {closed.status_code}：{closed.text}"
        f"——兩邊的判定漂開了，矩陣就沒有意義了。"
    )


def test_blocked_case_is_rejected_by_the_close_endpoint(client, make_user):
    """反向：canClose 為 False 的案件，完結案端點必須擋下來（400）。

    少了這一題，上面那題有可能只是因為「什麼都放行」而綠。
    """
    u, p = make_user(username="gm_block", role="superadmin")
    token = _login(client, u, p)
    _seed_case("MQ-GM-BLOCK")
    _add_stage("MQ-GM-BLOCK", "訂單確認", True, 0)
    _add_stage("MQ-GM-BLOCK", "客戶驗收", False, 1)

    r = client.get("/api/quotations/gate-matrix", headers=_auth(token))
    item = next(i for i in r.json()["items"] if i["quoteNo"] == "MQ-GM-BLOCK")
    assert item["canClose"] is False

    closed = client.patch("/api/quotations/MQ-GM-BLOCK/deal-tag",
                          json={"deal_tag": "已結案"}, headers=_auth(token))
    assert closed.status_code == 400, (
        f"矩陣說不能結案，完結案端點卻回 {closed.status_code}——探針量到的不是真的。"
    )


def test_payment_gate_counts_unreceived_instalments(client, make_user):
    """收款關卡讀的是 data_json.caseRecord.payment.items（不是 payments）。

    這個路徑寫錯的話關卡會永遠是 na（看起來像「這件案子沒有款項」），
    而不是報錯——所以值得單獨釘一題。
    """
    u, p = make_user(username="gm_pay", role="superadmin")
    token = _login(client, u, p)
    _seed_case("MQ-GM-PAY", data={"caseRecord": {"payment": {"items": [
        {"type": "訂金款", "pct": 30, "received": True},
        {"type": "驗收款", "pct": 70, "received": False},
    ]}}})

    r = client.get("/api/quotations/gate-matrix", headers=_auth(token))
    item = next(i for i in r.json()["items"] if i["quoteNo"] == "MQ-GM-PAY")
    payment = next(g for g in item["gates"] if g["key"] == "payment")

    assert payment["state"] == "blocked"
    assert payment["value"] == "1/2 期"
    assert "1 期未收齊" in (payment["reason"] or "")


def test_non_case_quotations_are_excluded(client, make_user):
    """只回已成案／已結案。報價中的單子不該出現在案件矩陣上。"""
    u, p = make_user(username="gm_scope", role="superadmin")
    token = _login(client, u, p)
    _seed_case("MQ-GM-CASE", deal_tag="已成案")
    _seed_case("MQ-GM-QUOTE", deal_tag="已提供")

    r = client.get("/api/quotations/gate-matrix", headers=_auth(token))
    nos = [i["quoteNo"] for i in r.json()["items"]]
    assert "MQ-GM-CASE" in nos
    assert "MQ-GM-QUOTE" not in nos
