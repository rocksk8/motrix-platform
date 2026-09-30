"""P0 安全修正（2026-09-30）：派工單附件／承攬商發票 `contractor_dispatches|contractor_dispatch_invoices/<派工id>/<檔名>`
的讀取權限（IP-104 `uploads.path_access`，M04 提供者）。規則＝派工單單筆端點的模組（procurement／case_manage／
contractor_list／quotation）∨ 看得到該案的單據（`case_documents_readable`，同 IP-21 提供者）。修正前任何登入者都簽得到。"""
import json

from tests._requires import requires_module


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(t):
    return {"Authorization": "Bearer " + t}


@requires_module("case", "案件業務本人那一格走 case_documents_readable（M01 不在時不放行）")
def test_dispatch_files_follow_dispatch_read_rule(client, make_user):
    import db
    toks = {}
    for name, mods in (("c0_owner", []), ("c0_proc", ["procurement"]), ("c0_out", ["work_log"])):
        u, p = make_user(username=name, role="sales", modules=mods)
        toks[name] = _login(client, u, p)
    c = db.get_db()
    try:
        oid = c.execute("SELECT id FROM users WHERE username='c0_owner'").fetchone()["id"]
        c.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at, sales_person_id, "
                  "sales_person) VALUES (?,?,?,?,?,?,?)",
                  ("MQ-P0C-1", "已送出", json.dumps({}), "2026-01-01", "2026-01-01", oid, "c0_owner"))
        vid = c.execute("INSERT INTO vendor_contractors (name) VALUES ('P0 廠商')").lastrowid
        did = c.execute("INSERT INTO contractor_dispatches (quote_no, vendor_id) VALUES (?, ?)",
                        ("MQ-P0C-1", vid)).lastrowid
        c.commit()
    finally:
        c.close()
    for folder in ("contractor_dispatches", "contractor_dispatch_invoices"):
        path = f"{folder}/{did}/a.pdf"
        tok = lambda who: client.get("/api/photo-token", headers=_h(toks[who]), params={"path": path})  # noqa: E731
        assert tok("c0_owner").status_code == 200, folder      # 案件業務本人
        assert tok("c0_proc").status_code == 200, folder       # 派工單端點的模組
        assert tok("c0_out").status_code == 404, folder
    assert client.get("/api/photo-token", headers=_h(toks["c0_proc"]),
                      params={"path": "contractor_dispatches/999999/a.pdf"}).status_code == 404
