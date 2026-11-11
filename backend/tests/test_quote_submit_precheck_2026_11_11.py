"""2026-11-11（hichan-12 UX 評分 A 項）：送審前置檢查＋後端具體原因要送得到前端。

起因：新建、沒設過部門主管的帳號第一次送審——後端其實回了「申請人尚未歸屬任何部門…」，前端卻一律說
「請確認後端伺服器是否在線」，畫面還一度顯示「待審核」。這裡釘住後端這一半：

  * `GET /api/quotations/submit-precheck`：用跟真正送審同一套解析 dry-run，沒部門／沒主管 ⇒ ok=False，
    帶機器可讀 code、中文訊息、該去哪個設定頁；設定齊了 ⇒ ok=True；只讀、不建單。
  * 真正送審被擋時 HTTP 400 的 `detail` 就是同一句話（前端 apiSave 直接顯示它）。
  * precheck 與真正送審「同進同出」：precheck 說 ok ⇒ 送審不會被組織設定擋；說不 ok ⇒ 送審一定 400。
"""
from tests._requires import requires_module  # noqa: E402
pytestmark = requires_module("case", "本檔打 M01（案件）的報價單端點")

import datetime as _dt


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _org(conn_fn):
    """建一個處＋一個部門，回 (division_id, department_id)。名字帶時間戳，避免與種子資料撞名。"""
    import db
    conn = db.get_db()
    try:
        now = _dt.datetime.now().isoformat(timespec="seconds")
        cur = conn.execute("INSERT INTO divisions (name, sort_order, created_at) VALUES (?,?,?)", ("預檢測試處", 0, now))
        div_id = cur.lastrowid
        cur = conn.execute("INSERT INTO departments (division_id, name, sort_order, created_at) VALUES (?,?,?,?)",
                           (div_id, "預檢測試部", 0, now))
        dept_id = cur.lastrowid
        conn.commit()
        return div_id, dept_id
    finally:
        conn.close()


def _set(sql, args):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _body(username):
    return {
        "status": "待審核",
        "data": {
            "customerName": "預檢客戶", "projectName": "預檢專案", "salesPerson": "",
            "quoteDate": "2026-11-11",
            "tot": {"total": 1000, "pretax": 952, "directMarginPct": 0, "netMarginPct": 0},
            "items": [{"description": "品項 A", "amount": 1000}],
            "approval": {"requestedBy": username, "status": "pending"},
        },
    }


def _count():
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) c FROM quotations").fetchone()["c"]
    finally:
        conn.close()


def test_no_department_is_blocked_with_clear_message_and_fix_page(client, make_user):
    username, password = make_user(username="pc_nodept", role="admin")
    token = _login(client, username, password)
    before = _count()
    r = client.get("/api/quotations/submit-precheck", headers=_auth(token))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is False
    assert len(d["problems"]) == 1
    p = d["problems"][0]
    assert p["code"] == "no_department"
    assert "尚未歸屬任何部門" in p["message"]
    assert p["fixPage"] == "users.html"
    assert d["canFix"] is False          # admin 不是最高管理者：只能聯絡管理員
    keys = [s["key"] for s in d["steps"]]
    assert keys == ["division", "department", "membership", "manager"]
    assert [s["done"] for s in d["steps"] if s["key"] == "membership"] == [False]
    assert _count() == before, "precheck 是唯讀，不可建單"


def test_department_without_manager_is_blocked(client, make_user):
    username, password = make_user(username="pc_nomgr", role="admin")
    _div, dept = _org(None)
    _set("UPDATE users SET department_id=? WHERE username=?", (dept, username))
    token = _login(client, username, password)
    d = client.get("/api/quotations/submit-precheck", headers=_auth(token)).json()
    assert d["ok"] is False
    p = d["problems"][0]
    assert p["code"] == "no_manager"
    assert "預檢測試部" in p["message"] and "尚未指定主管" in p["message"]
    assert p["fixPage"] == "org-structure.html"
    done = {s["key"]: s["done"] for s in d["steps"]}
    assert done["membership"] is True and done["manager"] is False


def test_fully_configured_passes_and_submit_is_not_blocked(client, make_user):
    # 申請人 + 另一位部門主管；設齊後 precheck ok，且真正送審回 201（兩者同進同出）
    username, password = make_user(username="pc_ok", role="admin")
    mgr_name, _pw = make_user(username="pc_ok_mgr", role="admin")
    _div, dept = _org(None)
    _set("UPDATE users SET department_id=? WHERE username=?", (dept, username))
    _set("UPDATE departments SET manager_user_id=? WHERE id=?", (_uid(mgr_name), dept))
    token = _login(client, username, password)
    d = client.get("/api/quotations/submit-precheck", headers=_auth(token)).json()
    assert d["ok"] is True and d["problems"] == []
    assert all(s["done"] for s in d["steps"])
    r = client.post("/api/quotations", json=_body(username), headers=_auth(token))
    assert r.status_code == 201, r.text


def test_blocked_precheck_means_real_submit_400_with_same_message(client, make_user):
    """precheck 說不行 ⇒ 真正送審一定 400，而且 detail 就是 precheck 的 message（前端直接顯示 detail）。"""
    username, password = make_user(username="pc_same", role="admin")
    token = _login(client, username, password)
    pc = client.get("/api/quotations/submit-precheck", headers=_auth(token)).json()
    assert pc["ok"] is False
    before = _count()
    r = client.post("/api/quotations", json=_body(username), headers=_auth(token))
    assert r.status_code == 400, r.text
    assert r.json()["detail"] == pc["problems"][0]["message"]
    assert _count() == before


def test_superadmin_can_fix_flag(client, make_user):
    username, password = make_user(username="pc_super", role="superadmin")
    token = _login(client, username, password)
    d = client.get("/api/quotations/submit-precheck", headers=_auth(token)).json()
    assert d["canFix"] is True


def test_precheck_requires_login(client):
    r = client.get("/api/quotations/submit-precheck")
    assert r.status_code in (401, 403)


def test_precheck_route_not_shadowed_by_quote_no_route(client, make_user):
    """路徑要排在 `/api/quotations/{quote_no}` 之前，否則會被當成單號 'submit-precheck' 回 404。"""
    username, password = make_user(username="pc_route", role="admin")
    token = _login(client, username, password)
    r = client.get("/api/quotations/submit-precheck", headers=_auth(token))
    assert r.status_code == 200 and "ok" in r.json()


def test_unresolved_manager_error_codes_are_set():
    """每個 raise 點都帶機器可讀 code（前端分流用）；沒帶時預設 unresolved，且 str(e) 不受影響。"""
    from helpers.tiered_approval import UnresolvedManagerError
    e = UnresolvedManagerError("x")
    assert e.code == "unresolved" and str(e) == "x"
    e2 = UnresolvedManagerError("y", code="no_manager")
    assert e2.code == "no_manager" and str(e2) == "y"
