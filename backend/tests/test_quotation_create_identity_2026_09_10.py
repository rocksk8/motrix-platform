"""2026-09-10 稽核發現：`POST /api/quotations` 的建立者取自 request body。

`quotations.py` 有 45 支寫入端點，這一支是唯一沒有 `_require_user()` 的，
`created_by` 直接存 `body.created_by`、活動通知的操作者也用同一個字串。
對照同專案 `customers.py:84`／`shipping_notes.py:192` 一律從 session 取——
沒有這道修正，任何登入者都能把報價單掛在別人名下。

這裡釘住：不論 client 送什麼 `created_by`，落庫的一律是 session 的使用者。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _payload(created_by):
    return {
        "status": "草稿",
        "created_by": created_by,
        "data": {
            "customerName": "身分測客",
            "projectName": "身分測專",
            "salesPerson": "",
            "quoteDate": "2026-09-10",
            "tot": {"total": 1000, "pretax": 952,
                    "directMarginPct": 0, "netMarginPct": 0},
        },
    }


def test_created_by_comes_from_session_not_request_body(client, make_user):
    """核心：client 謊報 created_by 也沒用，落庫的是 session 使用者。"""
    import db

    victim, _vpw = make_user(username="q_victim", role="admin")
    actor, actor_pw = make_user(username="q_actor", role="admin")
    token = _login(client, actor, actor_pw)

    r = client.post("/api/quotations", json=_payload(victim), headers=_auth(token))
    assert r.status_code == 201, r.text
    qno = r.json()["quote_no"]

    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT created_by FROM quotations WHERE quote_no=?", (qno,)
        ).fetchone()
    finally:
        conn.close()

    assert row["created_by"] == actor, (
        f"created_by 應為送出請求的使用者 {actor!r}，實際 {row['created_by']!r}"
        f"（若等於 {victim!r} 代表仍在信任 client 送來的 created_by）"
    )


def test_created_by_filled_even_when_client_omits_it(client, make_user):
    """client 完全不送 created_by 時也要有值（原本會存成 NULL）。"""
    import db

    actor, actor_pw = make_user(username="q_actor2", role="admin")
    token = _login(client, actor, actor_pw)

    body = _payload(None)
    body.pop("created_by")
    r = client.post("/api/quotations", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    qno = r.json()["quote_no"]

    conn = db.get_db()
    try:
        row = conn.execute(
            "SELECT created_by FROM quotations WHERE quote_no=?", (qno,)
        ).fetchone()
    finally:
        conn.close()
    assert row["created_by"] == actor


def test_create_requires_valid_session(client):
    """沒有 token 一律 401（middleware 層，這裡順手釘住不要被改壞）。"""
    r = client.post("/api/quotations", json=_payload("anyone"))
    assert r.status_code == 401, r.text
