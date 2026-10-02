"""P0 安全修正（2026-09-30）：開票申請已開立檔案 `invoice_vouchers/<開票單號>/<檔名>` 的讀取權限
（IP-104 `uploads.path_access`，M05 提供者）。規則＝開票申請單筆的 `_voucher_readable`（案件層＋金額層，含本單簽核人例外）。
修正前任何登入者都簽得到。"""
import json

from tests._requires import requires_module


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(t):
    return {"Authorization": "Bearer " + t}


@requires_module("case", "開票申請的讀取規則含案件層（case_access_allowed）；簽核佇列詳情的守門也經案件")
def test_invoice_voucher_files_follow_voucher_read_rule(client, make_user):
    import db
    toks = {}
    # 角色 sales 本身就看得到金額（can_see_financial）⇒ 「沒有財務檢視」的兩個人用 engineer
    for name, role, mods in (("v0_owner", "sales", []), ("v0_nofin", "engineer", []),
                             ("v0_out", "sales", ["work_log"]), ("v0_appr", "engineer", [])):
        u, p = make_user(username=name, role=role, modules=mods)
        toks[name] = _login(client, u, p)
    c = db.get_db()
    try:
        oid = c.execute("SELECT id FROM users WHERE username='v0_owner'").fetchone()["id"]
        c.execute("INSERT INTO quotations (quote_no, status, data_json, created_at, updated_at, sales_person_id, "
                  "sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?)",
                  ("MQ-P0V-1", "已送出", json.dumps({}), "2026-01-01", "2026-01-01", oid, "v0_owner",
                   json.dumps([c.execute("SELECT id FROM users WHERE username='v0_nofin'").fetchone()["id"]])))
        c.execute("INSERT INTO invoice_vouchers (voucher_no, quote_no, data_json, issued_files_json) VALUES (?,?,?,?)",
                  ("IV-P0-1", "MQ-P0V-1",
                   json.dumps({"approval": {"tiers": [{"approvers": [{"username": "v0_appr"}]}]}}),
                   json.dumps([{"id": "f1", "filename": "a.pdf", "path": "invoice_vouchers/IV-P0-1/a.pdf"}])))
        c.commit()
    finally:
        c.close()
    path = "invoice_vouchers/IV-P0-1/a.pdf"
    tok = lambda who: client.get("/api/photo-token", headers=_h(toks[who]), params={"path": path})  # noqa: E731
    assert tok("v0_owner").status_code == 200
    assert tok("v0_nofin").status_code == 404      # 案件協作者，但沒有財務檢視（金額層）
    assert tok("v0_out").status_code == 404        # 有財務檢視，但看不到該案
    # 本單簽核人、看不到案件：開票申請單筆規則的案件層不放行（allow_approver 看的是案件的簽核鏈）⇒ 單看路徑 404；
    # 從簽核佇列帶 (type, id)：詳情守門放行（簽核鏈上）且詳情列出這個路徑 ⇒ 200
    assert tok("v0_appr").status_code == 404
    r = client.get("/api/photo-token", headers=_h(toks["v0_appr"]),
                   params={"path": path, "type": "invoice_voucher", "id": "IV-P0-1"})
    assert r.status_code == 200, r.text
    r = client.get("/api/photo-token", headers=_h(toks["v0_out"]),
                   params={"path": path, "type": "invoice_voucher", "id": "IV-P0-1"})
    assert r.status_code == 404, r.text
