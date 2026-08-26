"""API-level integration tests for 網路架構規劃書 (network_plans) — CRUD 層，
見 routers/network_plans.py 與 NETWORK-PLAN-MODULE-DESIGN.md。匯出（Excel/PDF）
與庫存挑選整合屬於後續施做步驟，尚未開發，不在此檔涵蓋範圍。"""
import io
import json
import re
import zipfile

import openpyxl


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_quotation(quote_no, customer_name="測試客戶"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", customer_name, "測試專案", 100000, 95238, "{}",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"),
        )
        conn.commit()
    finally:
        conn.close()


def test_create_standalone_plan_requires_edit_permission(client, make_user):
    viewer_user, viewer_pw = make_user(username="viewer1", role="viewer")
    token = _login(client, viewer_user, viewer_pw)
    r = client.post("/api/network-plans", headers=_auth(token), json={"siteName": "測試案場"})
    assert r.status_code == 403, r.text


def test_engineer_with_module_can_create_and_edit(client, make_user):
    eng_user, eng_pw = make_user(username="eng1", role="engineer", modules=["netplan_edit"])
    token = _login(client, eng_user, eng_pw)

    r = client.post("/api/network-plans", headers=_auth(token), json={"siteName": "測試案場"})
    assert r.status_code == 201, r.text
    plan_no = r.json()["planNo"]
    assert plan_no.startswith("NP-")

    listed = client.get("/api/network-plans", headers=_auth(token))
    assert listed.status_code == 200
    assert any(p["planNo"] == plan_no for p in listed.json())


def test_create_bound_to_case_prefills_site_name_and_blocks_duplicate(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    _make_quotation("MQ-NP-001", customer_name="小林機械")

    r = client.post("/api/network-plans", headers=_auth(token), json={"quoteNo": "MQ-NP-001"})
    assert r.status_code == 201, r.text
    plan_no = r.json()["planNo"]

    detail = client.get(f"/api/quotations/MQ-NP-001/network-plan", headers=_auth(token))
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["planNo"] == plan_no
    assert body["siteName"] == "小林機械"
    assert body["data"]["revisionLog"][0]["note"] == "初版建立"

    dup = client.post("/api/network-plans", headers=_auth(token), json={"quoteNo": "MQ-NP-001"})
    assert dup.status_code == 409, dup.text


def test_create_unbound_case_404(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    r = client.post("/api/network-plans", headers=_auth(token), json={"quoteNo": "MQ-NOPE-999"})
    assert r.status_code == 404, r.text


def test_update_with_optimistic_lock(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    created = client.post("/api/network-plans", headers=_auth(token), json={"siteName": "案場A"})
    plan_no = created.json()["planNo"]
    detail = client.get(f"/api/network-plans", headers=_auth(token)).json()
    plan_id = next(p["id"] for p in detail if p["planNo"] == plan_no)
    old_updated_at = next(p["updatedAt"] for p in detail if p["planNo"] == plan_no)

    stale = client.put(
        f"/api/network-plans/{plan_id}", headers=_auth(token),
        json={"_expectedUpdatedAt": "2000-01-01T00:00:00", "data": {"vlans": []}},
    )
    assert stale.status_code == 409, stale.text

    ok = client.put(
        f"/api/network-plans/{plan_id}", headers=_auth(token),
        json={"_expectedUpdatedAt": old_updated_at,
              "data": {"vlans": [{"vlanId": 20, "name": "MGMT"}]}},
    )
    assert ok.status_code == 200, ok.text

    refreshed = client.get(f"/api/network-plans/{plan_id}", headers=_auth(token)).json()
    assert refreshed["data"]["vlans"][0]["name"] == "MGMT"


def test_status_transition_appends_revision_log(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    created = client.post("/api/network-plans", headers=_auth(token), json={"siteName": "案場B"})
    plan_no = created.json()["planNo"]
    plan_id = next(p["id"] for p in client.get("/api/network-plans", headers=_auth(token)).json()
                   if p["planNo"] == plan_no)

    r = client.patch(f"/api/network-plans/{plan_id}/status", headers=_auth(token),
                      json={"status": "已確認", "note": "客戶已確認規劃"})
    assert r.status_code == 200, r.text

    detail = client.get(f"/api/network-plans/{plan_id}", headers=_auth(token)).json()
    assert detail["status"] == "已確認"
    assert "規劃中 → 已確認" in detail["data"]["revisionLog"][-1]["note"]

    bad = client.patch(f"/api/network-plans/{plan_id}/status", headers=_auth(token),
                        json={"status": "不存在的狀態"})
    assert bad.status_code == 400


def test_excel_sheet_names_avoid_fullwidth_forbidden_chars():
    """2026-08-26 迴歸測試：分頁名稱含全形斜線「／」（如舊版的「WAN／對外
    線路」「IP／Port 群組」）會讓 Microsoft Excel 判定 workbook.xml 損毀、
    跳出修復對話框、把後續分頁吞掉重組成「復原_工作表1」——即使 openpyxl／
    zipfile／XML well-formedness 檢查全部過關也一樣，這是 Excel 自己額外的
    分頁名稱驗證規則。純靜態檢查 SECTIONS 定義，不需要真的產生檔案。"""
    import network_plan_export as npe
    forbidden_fullwidth = "／＼？＊［］："
    for _, title, _ in npe.SECTIONS:
        bad = [c for c in title if c in forbidden_fullwidth]
        assert not bad, f"分頁標題「{title}」含有可能讓 Excel 判定損毀的字元：{bad}"


def test_export_excel_and_pdf(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    created = client.post("/api/network-plans", headers=_auth(token), json={"siteName": "案場匯出測試"})
    plan_no = created.json()["planNo"]
    plan_id = next(p["id"] for p in client.get("/api/network-plans", headers=_auth(token)).json()
                   if p["planNo"] == plan_no)

    client.put(
        f"/api/network-plans/{plan_id}", headers=_auth(token),
        json={"data": {"vlans": [{"vlanId": 10, "name": "MGMT", "cidr": "172.16.10.0/24"}],
                       "devices": [{"name": "USW-01", "mac": "58d61f23 4f21", "mgmtIp": "172.16.20.10"}]}},
    )

    excel_resp = client.get(f"/api/network-plans/{plan_id}/export/excel", headers=_auth(token))
    assert excel_resp.status_code == 200, excel_resp.text
    assert excel_resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert len(excel_resp.content) > 0

    # 2026-08-26 迴歸測試：空白欄位曾被寫成 `<c t="inlineStr"></c>`（缺少必要的
    # <is> 子元素），是不合法的 OOXML，會讓 Excel 跳出「發現部分內容有問題，
    # 是否修復」的對話框（見 network_plan_export.py::_cell_text 說明）。
    # openpyxl 讀得回來不代表檔案合法（openpyxl 解析較寬鬆），直接在 XML
    # 層級掃描這個壞掉的樣式，openpyxl 本身也能正常 load_workbook 讀回。
    zf = zipfile.ZipFile(io.BytesIO(excel_resp.content))
    bad_cells = []
    for name in zf.namelist():
        if name.startswith("xl/worksheets/"):
            xml = zf.read(name).decode("utf-8")
            bad_cells += re.findall(r'<c [^>]*t="inlineStr"[^>]*></c>', xml)
    assert not bad_cells, f"發現不合法的空白 inlineStr 儲存格：{bad_cells}"
    wb = openpyxl.load_workbook(io.BytesIO(excel_resp.content))
    assert "封面" in wb.sheetnames
    assert "設備清單" in wb.sheetnames

    pdf_resp = client.get(f"/api/network-plans/{plan_id}/export/pdf", headers=_auth(token))
    if pdf_resp.status_code == 503:
        return  # 此環境沒有 Microsoft Edge，比照 reports.py 既有測試慣例略過實際產出驗證
    assert pdf_resp.status_code == 200, pdf_resp.text
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert len(pdf_resp.content) > 0


def test_import_excel_roundtrip(client, make_user):
    """匯出→（模擬現場離線填寫，這裡直接重用匯出檔）→匯入回另一份規劃書，
    驗證分頁/欄位能正確讀回，且不動案場識別欄位。"""
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)

    src = client.post("/api/network-plans", headers=_auth(token), json={"siteName": "來源案場"})
    src_no = src.json()["planNo"]
    src_id = next(p["id"] for p in client.get("/api/network-plans", headers=_auth(token)).json()
                  if p["planNo"] == src_no)
    client.put(
        f"/api/network-plans/{src_id}", headers=_auth(token),
        json={"data": {
            "devices": [{"seq": 1, "name": "USW-01", "category": "交換器", "mgmtVlan": "20"}],
            "vlans": [{"vlanId": 20, "name": "MGMT", "cidr": "172.16.20.0/24"}],
            "firewallRules": [{"priority": 1, "name": "ALLOW-ALL", "enabled": True}],
        }},
    )
    excel_resp = client.get(f"/api/network-plans/{src_id}/export/excel", headers=_auth(token))
    assert excel_resp.status_code == 200

    dst = client.post("/api/network-plans", headers=_auth(token), json={"siteName": "目的案場"})
    dst_no = dst.json()["planNo"]
    dst_id = next(p["id"] for p in client.get("/api/network-plans", headers=_auth(token)).json()
                  if p["planNo"] == dst_no)

    files = {"file": ("plan.xlsx", excel_resp.content,
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    imp = client.post(f"/api/network-plans/{dst_id}/import/excel", headers=_auth(token), files=files)
    assert imp.status_code == 200, imp.text
    body = imp.json()
    assert "devices" in body["updatedSections"]
    assert "vlans" in body["updatedSections"]
    assert "firewallRules" in body["updatedSections"]

    detail = client.get(f"/api/network-plans/{dst_id}", headers=_auth(token)).json()
    assert detail["siteName"] == "目的案場"  # 案場識別欄位不受匯入影響
    assert detail["data"]["devices"][0]["name"] == "USW-01"
    assert detail["data"]["devices"][0]["mgmtVlan"] == "20"  # mgmtVlan 是文字型欄位，非數字型
    assert detail["data"]["vlans"][0]["cidr"] == "172.16.20.0/24"
    assert detail["data"]["firewallRules"][0]["enabled"] is True
    assert "匯入" in detail["data"]["revisionLog"][-1]["note"]


def test_import_excel_rejects_garbage_file(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    created = client.post("/api/network-plans", headers=_auth(token), json={"siteName": "案場X"})
    plan_id = next(p["id"] for p in client.get("/api/network-plans", headers=_auth(token)).json()
                   if p["planNo"] == created.json()["planNo"])
    files = {"file": ("plan.xlsx", b"not a real xlsx file", "application/octet-stream")}
    r = client.post(f"/api/network-plans/{plan_id}/import/excel", headers=_auth(token), files=files)
    assert r.status_code == 400


def test_import_excel_requires_edit_permission(client, make_user):
    viewer_user, viewer_pw = make_user(username="viewer2", role="viewer")
    admin_user, admin_pw = make_user(username="admin3", role="superadmin")
    admin_token = _login(client, admin_user, admin_pw)
    viewer_token = _login(client, viewer_user, viewer_pw)

    created = client.post("/api/network-plans", headers=_auth(admin_token), json={"siteName": "案場Y"})
    plan_id = next(p["id"] for p in client.get("/api/network-plans", headers=_auth(admin_token)).json()
                   if p["planNo"] == created.json()["planNo"])
    excel_resp = client.get(f"/api/network-plans/{plan_id}/export/excel", headers=_auth(admin_token))

    files = {"file": ("plan.xlsx", excel_resp.content,
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    r = client.post(f"/api/network-plans/{plan_id}/import/excel", headers=_auth(viewer_token), files=files)
    assert r.status_code == 403


def test_export_requires_login(client, make_user):
    username, password = make_user(role="superadmin")
    token = _login(client, username, password)
    created = client.post("/api/network-plans", headers=_auth(token), json={"siteName": "案場E"})
    plan_id = next(p["id"] for p in client.get("/api/network-plans", headers=_auth(token)).json()
                   if p["planNo"] == created.json()["planNo"])
    r = client.get(f"/api/network-plans/{plan_id}/export/excel")
    assert r.status_code == 401


def test_delete_only_allowed_while_planning_and_superadmin_only(client, make_user):
    eng_user, eng_pw = make_user(username="eng2", role="engineer", modules=["netplan_edit"])
    admin_user, admin_pw = make_user(username="admin2", role="superadmin")

    eng_token = _login(client, eng_user, eng_pw)
    admin_token = _login(client, admin_user, admin_pw)

    created = client.post("/api/network-plans", headers=_auth(eng_token), json={"siteName": "案場C"})
    plan_no = created.json()["planNo"]
    plan_id = next(p["id"] for p in client.get("/api/network-plans", headers=_auth(eng_token)).json()
                   if p["planNo"] == plan_no)

    forbidden = client.delete(f"/api/network-plans/{plan_id}", headers=_auth(eng_token))
    assert forbidden.status_code == 403, forbidden.text

    client.patch(f"/api/network-plans/{plan_id}/status", headers=_auth(admin_token),
                 json={"status": "已確認"})
    blocked = client.delete(f"/api/network-plans/{plan_id}", headers=_auth(admin_token))
    assert blocked.status_code == 409, blocked.text

    another = client.post("/api/network-plans", headers=_auth(admin_token), json={"siteName": "案場D"})
    plan_no2 = another.json()["planNo"]
    plan_id2 = next(p["id"] for p in client.get("/api/network-plans", headers=_auth(admin_token)).json()
                    if p["planNo"] == plan_no2)
    ok = client.delete(f"/api/network-plans/{plan_id2}", headers=_auth(admin_token))
    assert ok.status_code == 200, ok.text
