"""業務開發案件「指派／進度回報」（2026-11-03）。

依規格寫的獨立視角測試（寫測試的人沒看過實作）。觀測點：資料庫（`dev_cases`、`notifications`），
不只看 API 回應文字。

涵蓋：
- `PATCH /api/dev-cases/{id}/assign`：非管理員 403；管理員指到不存在／停用者 400、指到有效者 200（回應欄位＋DB＋通知）、
  設 null 取消、案件不存在 404
- `PATCH /api/dev-cases/{id}/progress`：被指派人／管理員 200 並寫入；建立者（非被指派人、非管理員）與外人 403；案件不存在 404
- 列權限：被指派人 ≠ 建立者、不在業務／企劃名單、不是管理員 ⇒ 指派前看不到、指派後看得到且享有完整權限
  （能改狀態），取消指派後又看不到
- 舊資料相容：`dev_cases` 沒有三個新欄位時，GET 單筆／列表不 500
"""
import sqlite3

import pytest


# ─────────────────────────── helpers ───────────────────────────

def _login(client, make_user, username, role="sales", modules=("dev_crm",)):
    name, pw = make_user(username=username, role=role, modules=None if modules is None else list(modules))  # None＝角色樣板
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _case_cols(cid):
    import db
    conn = db.get_db()
    try:
        return dict(conn.execute("SELECT assigned_to, reply_deadline, progress_report, status"
                                 " FROM dev_cases WHERE id=?", (cid,)).fetchone())
    finally:
        conn.close()


def _notices(username):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM notifications WHERE username=? ORDER BY id", (username,)).fetchall()]
    finally:
        conn.close()


def _make_case(client, owner, **extra):
    body = {"case_name": "指派測試案", "customer_name": "指派客戶"}
    body.update(extra)
    r = client.post("/api/dev-cases", headers=owner, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _assign(client, h, cid, assigned_to, deadline=None):
    return client.patch(f"/api/dev-cases/{cid}/assign", headers=h,
                        json={"assignedTo": assigned_to, "replyDeadline": deadline})


def _ids(client, h):
    r = client.get("/api/dev-cases", headers=h)
    assert r.status_code == 200, r.text
    return [c["id"] for c in r.json()]


# ─────────────────────────── assign ───────────────────────────

def test_assign_requires_admin(client, make_user):
    owner = _login(client, make_user, "da_owner")
    _login(client, make_user, "da_target")
    outsider = _login(client, make_user, "da_out")
    cid = _make_case(client, owner)
    tid = _uid("da_target")

    for who, h in (("建立者（業務）", owner), ("外人", outsider)):
        r = _assign(client, h, cid, tid, "2026-12-01")
        assert r.status_code == 403, (who, r.text)
    after = _case_cols(cid)
    assert after["assigned_to"] is None and after["reply_deadline"] is None            # 資料不變
    assert _notices("da_target") == []                                                  # 沒通知


def test_assign_validates_target_user(client, make_user):
    owner = _login(client, make_user, "dv_owner")
    admin = _login(client, make_user, "dv_admin", role="admin", modules=None)
    _login(client, make_user, "dv_gone")
    cid = _make_case(client, owner)

    # 不存在的使用者
    r = _assign(client, admin, cid, 999999, "2026-12-01")
    assert r.status_code == 400, r.text
    assert _case_cols(cid)["assigned_to"] is None

    # 停用的使用者
    gone = _uid("dv_gone")
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET active=0 WHERE id=?", (gone,))
        conn.commit()
    finally:
        conn.close()
    r = _assign(client, admin, cid, gone, "2026-12-01")
    assert r.status_code == 400, r.text
    assert _case_cols(cid)["assigned_to"] is None
    assert _notices("dv_gone") == []


def test_assign_success_writes_db_response_and_notification(client, make_user):
    owner = _login(client, make_user, "ds_owner")
    admin = _login(client, make_user, "ds_admin", role="admin", modules=None)
    _login(client, make_user, "ds_target")
    cid = _make_case(client, owner)
    tid = _uid("ds_target")
    assert _notices("ds_target") == []

    r = _assign(client, admin, cid, tid, "2026-12-01")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["assignedToId"] == tid
    assert body["assignedToName"]                                       # 有顯示名稱（非空）
    assert body["replyDeadline"] == "2026-12-01"

    row = _case_cols(cid)
    assert row["assigned_to"] == tid and row["reply_deadline"] == "2026-12-01"

    notes = _notices("ds_target")                                       # 觀測點打 notifications 表
    assert len(notes) == 1, notes
    assert notes[0]["is_read"] == 0
    # 別的人不該被通知
    assert _notices("ds_owner") == [] and _notices("ds_admin") == []


def test_assign_accepts_snake_case_body(client, make_user):
    owner = _login(client, make_user, "dsn_owner")
    admin = _login(client, make_user, "dsn_admin", role="admin", modules=None)
    _login(client, make_user, "dsn_target")
    cid = _make_case(client, owner)
    tid = _uid("dsn_target")
    r = client.patch(f"/api/dev-cases/{cid}/assign", headers=admin,
                     json={"assigned_to": tid, "reply_deadline": "2026-12-15"})
    assert r.status_code == 200, r.text
    row = _case_cols(cid)
    assert row["assigned_to"] == tid and row["reply_deadline"] == "2026-12-15"


def test_assign_null_unassigns(client, make_user):
    owner = _login(client, make_user, "du_owner")
    admin = _login(client, make_user, "du_admin", role="admin", modules=None)
    _login(client, make_user, "du_target")
    cid = _make_case(client, owner)
    tid = _uid("du_target")
    assert _assign(client, admin, cid, tid, "2026-12-01").status_code == 200
    assert _case_cols(cid)["assigned_to"] == tid

    r = _assign(client, admin, cid, None, None)
    assert r.status_code == 200, r.text
    assert r.json()["assignedToId"] is None
    assert _case_cols(cid)["assigned_to"] is None


def test_assign_missing_case_is_404(client, make_user):
    admin = _login(client, make_user, "dm_admin", role="admin", modules=None)
    _login(client, make_user, "dm_target")
    r = _assign(client, admin, 999999, _uid("dm_target"), "2026-12-01")     # 目標使用者有效 ⇒ 404 只可能來自案件
    assert r.status_code == 404, r.text
    assert _notices("dm_target") == []


# ─────────────────────────── progress ───────────────────────────

def test_progress_assignee_and_admin_can_write(client, make_user):
    owner = _login(client, make_user, "pg_owner")
    admin = _login(client, make_user, "pg_admin", role="admin", modules=None)
    assignee = _login(client, make_user, "pg_assignee")
    cid = _make_case(client, owner)
    assert _assign(client, admin, cid, _uid("pg_assignee"), "2026-12-01").status_code == 200
    assert _case_cols(cid)["progress_report"] == ""                        # 預設空字串

    r = client.patch(f"/api/dev-cases/{cid}/progress", headers=assignee, json={"progressReport": "已拜訪客戶，等報價"})
    assert r.status_code == 200, r.text
    assert _case_cols(cid)["progress_report"] == "已拜訪客戶，等報價"

    # 管理員不是被指派人也可以
    r = client.patch(f"/api/dev-cases/{cid}/progress", headers=admin, json={"progressReport": "管理員補充"})
    assert r.status_code == 200, r.text
    assert _case_cols(cid)["progress_report"] == "管理員補充"


def test_progress_denied_for_non_assignee_non_admin(client, make_user):
    owner = _login(client, make_user, "pd_owner")
    admin = _login(client, make_user, "pd_admin", role="admin", modules=None)
    _login(client, make_user, "pd_assignee")
    outsider = _login(client, make_user, "pd_out")
    cid = _make_case(client, owner)
    assert _assign(client, admin, cid, _uid("pd_assignee"), None).status_code == 200
    before = _case_cols(cid)["progress_report"]

    # 建立者有列權限，但既非被指派人也非管理員 ⇒ 403（分辨「回報進度」權限與「看得到」是兩回事）
    for who, h in (("建立者", owner), ("外人", outsider)):
        r = client.patch(f"/api/dev-cases/{cid}/progress", headers=h, json={"progressReport": "我亂寫"})
        assert r.status_code == 403, (who, r.text)
    assert _case_cols(cid)["progress_report"] == before


def test_progress_missing_case_is_404(client, make_user):
    admin = _login(client, make_user, "pn_admin", role="admin", modules=None)
    r = client.patch("/api/dev-cases/999999/progress", headers=admin, json={"progressReport": "x"})
    assert r.status_code == 404, r.text


# ─────────────────────────── row_access ───────────────────────────

def test_assignee_gets_full_row_access_until_unassigned(client, make_user):
    owner = _login(client, make_user, "ra_owner")                       # A：建立者
    admin = _login(client, make_user, "ra_admin", role="admin", modules=None)
    b = _login(client, make_user, "ra_b")                               # B：同模組、同角色，不在名單、不是管理員
    cid = _make_case(client, owner)                                     # 業務／企劃名單都不含 B
    bid = _uid("ra_b")

    # 指派前：B 看不到
    assert cid not in _ids(client, b)
    assert client.get(f"/api/dev-cases/{cid}", headers=b).status_code == 403
    assert client.patch(f"/api/dev-cases/{cid}/status", headers=b, json={"status": "暫擱置"}).status_code == 403
    assert _case_cols(cid)["status"] != "暫擱置"

    # 指派給 B
    assert _assign(client, admin, cid, bid, "2026-12-01").status_code == 200
    assert cid in _ids(client, b)
    assert client.get(f"/api/dev-cases/{cid}", headers=b).status_code == 200
    # 完整權限（與業務／企劃同等）：能改狀態，不是只能看或只能回報進度
    r = client.patch(f"/api/dev-cases/{cid}/status", headers=b, json={"status": "暫擱置"})
    assert r.status_code == 200, r.text
    assert _case_cols(cid)["status"] == "暫擱置"

    # 取消指派：B 又看不到、又改不了
    assert _assign(client, admin, cid, None, None).status_code == 200
    assert cid not in _ids(client, b)
    assert client.get(f"/api/dev-cases/{cid}", headers=b).status_code == 403
    assert client.patch(f"/api/dev-cases/{cid}/status", headers=b, json={"status": "洽談中"}).status_code == 403
    assert _case_cols(cid)["status"] == "暫擱置"                         # 取消後的那次改動沒生效


def test_assignment_does_not_leak_to_other_users(client, make_user):
    """指派給 B 只開 B 的權限，不影響同模組同角色的 C。"""
    owner = _login(client, make_user, "rl_owner")
    admin = _login(client, make_user, "rl_admin", role="admin", modules=None)
    _login(client, make_user, "rl_b")
    c = _login(client, make_user, "rl_c")
    cid = _make_case(client, owner)
    assert _assign(client, admin, cid, _uid("rl_b"), None).status_code == 200
    assert cid not in _ids(client, c)
    assert client.get(f"/api/dev-cases/{cid}", headers=c).status_code == 403


# ─────────────────────────── 舊資料相容 ───────────────────────────

def test_legacy_row_without_assignment_columns_does_not_crash(client, make_user):
    """模擬 migration 還沒跑到的舊庫：把三個新欄位拿掉，再手動插一列，GET 單筆／列表不應 500。

    這個 repo 的 `client` 每題給一個已完整遷移的新庫，所以用 `ALTER TABLE … DROP COLUMN` 把欄位拿掉來模擬；
    若這顆 SQLite 不支援（或欄位被索引／約束卡住）就 skip，不硬做。
    """
    sup = _login(client, make_user, "lg_sup", role="superadmin", modules=None)
    import db
    conn = db.get_db()
    try:
        try:
            for col in ("assigned_to", "reply_deadline", "progress_report"):
                conn.execute(f"ALTER TABLE dev_cases DROP COLUMN {col}")
            conn.commit()
        except sqlite3.OperationalError as exc:                          # pragma: no cover - 環境不支援才走這條
            pytest.skip(f"這個 SQLite 無法 DROP COLUMN，沒辦法模擬缺欄位：{exc}")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(dev_cases)").fetchall()]
        assert not {"assigned_to", "reply_deadline", "progress_report"} & set(cols)     # 前提：欄位真的不見了
        cur = conn.execute("INSERT INTO dev_cases (case_name, customer_name, created_at, updated_at)"
                           " VALUES (?,?,?,?)", ("舊案", "舊客戶", "t", "t"))
        cid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    r = client.get(f"/api/dev-cases/{cid}", headers=sup)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == cid
    r = client.get("/api/dev-cases", headers=sup)
    assert r.status_code == 200, r.text
    assert cid in [c["id"] for c in r.json()]
