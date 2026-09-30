"""P0 安全修正（2026-09-30）：開發記錄附件 `dev_logs/<業務開發案 id>/<檔名>` 的讀取權限（IP-104 `uploads.path_access`，M02 提供者）。
規則＝`GET /dev-cases/{id}/logs`：admin+ 或 dev_crm 模組，且 row_access `dev_case`（建立者／業務／規劃人員）。修正前任何登入者都簽得到。"""
import json
from datetime import datetime


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(t):
    return {"Authorization": "Bearer " + t}


def test_dev_log_file_follows_dev_case_visibility(client, make_user):
    import db
    toks = {}
    for name, mods in (("d0_owner", ["dev_crm"]), ("d0_other", ["dev_crm"]), ("d0_nomod", ["quotation"])):
        u, p = make_user(username=name, role="sales", modules=mods)
        toks[name] = _login(client, u, p)
    c = db.get_db()
    try:
        oid = c.execute("SELECT id FROM users WHERE username='d0_owner'").fetchone()["id"]
        nid = c.execute("SELECT id FROM users WHERE username='d0_nomod'").fetchone()["id"]
        now = datetime.now().isoformat()
        cid = c.execute("INSERT INTO dev_cases (case_name, created_by, sales_persons, created_at, updated_at) "
                        "VALUES (?,?,?,?,?)", ("案", oid, json.dumps([nid]), now, now)).lastrowid
        c.commit()
    finally:
        c.close()
    path = f"dev_logs/{cid}/a.png"
    tok = lambda who: client.get("/api/photo-token", headers=_h(toks[who]), params={"path": path})  # noqa: E731
    assert tok("d0_owner").status_code == 200
    assert tok("d0_other").status_code == 404          # 有模組、不是成員
    assert tok("d0_nomod").status_code == 404          # 是成員、沒有 dev_crm 模組（同 _require_dev）
    assert client.get("/api/photo-token", headers=_h(toks["d0_owner"]),
                      params={"path": "dev_logs/999999/a.png"}).status_code == 404
