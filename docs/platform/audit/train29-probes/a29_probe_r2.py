# -*- coding: utf-8 -*-
"""A29 稽核探針 R2/R4：類型化支出（kind≠''）的 PDF 單據、檔案中心搜尋、附件開啟對「非金額可見者」的輸出面（包 47db5613；不進倉庫）。"""
import json

import pytest


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def world(client, make_user):
    import db
    owner = make_user(username="p2_owner", role="user", modules=["quotation", "case_manage"])     # 案件擁有者、不是申請人
    appl = make_user(username="p2_appl", role="user", modules=["quotation", "case_manage"])        # 申請人（金額可見）
    fc = make_user(username="p2_filecenter", role="user", modules=["file_center"])                 # 有檔案中心、無案件權限
    sa = make_user(username="p2_sa", role="superadmin")
    conn = db.get_db()
    try:
        oid = conn.execute("SELECT id FROM users WHERE username='p2_owner'").fetchone()[0]
        aid = conn.execute("SELECT id FROM users WHERE username='p2_appl'").fetchone()[0]
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at, deal_tag, sales_person, sales_person_id, assigned_user_ids)"
                     " VALUES ('MQ-P2-1','已送出','客','案','{}','2026-09-01','2026-09-01','已成案','p2_owner',?,?)", (oid, json.dumps([aid])))
        files = [{"id": "f1", "filename": "發票.pdf", "path": "case_extra_expense/MQ-P2-1_1/x.pdf", "size": 10, "uploaded_at": "2026-09-01T00:00:00", "uploaded_by": "申請人"}]
        conn.execute(
            "INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no,"
            " files_json, created_by, created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name,"
            " status, approval_json, change_status, change_json, kind, doc_code, lines_json, data_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,'{}','','{}',?,?,?,?)",
            ("MQ-P2-1", "差旅", "出差", 1, "式", 5000, 5000, "", "2026-09-01", "", json.dumps(files, ensure_ascii=False), "p2_appl", "申請人",
             "p2_appl", "申請人", "2026-09-01T00:00:00", "2026-09-01T00:00:00", "申請人", "已核准", "travel", "TE-P2-1",
             json.dumps([{"category": "交通", "amount": 5000, "summary": "高鐵"}], ensure_ascii=False), json.dumps({"applicant": "p2_appl"})))
        conn.commit()
        eid = conn.execute("SELECT id FROM case_extra_expenses").fetchone()[0]
    finally:
        conn.close()
    import os
    from helpers import uploads as UP
    fp = os.path.join(UP.UPLOADS_ROOT, "uploads", "case_extra_expense", "MQ-P2-1_1", "x.pdf")
    for cand in (os.path.join(UP.UPLOADS_ROOT, "case_extra_expense", "MQ-P2-1_1", "x.pdf"), fp):
        os.makedirs(os.path.dirname(cand), exist_ok=True)
        open(cand, "wb").write(b"%PDF-1.4 probe")
    h = {k: _login(client, v[0], v[1]) for k, v in (("owner", owner), ("appl", appl), ("fc", fc), ("sa", sa))}
    return client, h, eid


def test_pdf_document_only_for_amount_viewers(world):
    client, h, eid = world
    url = "/api/quotations/MQ-P2-1/extra-expenses/%d/document" % eid
    for who in ("owner", "fc"):
        r = client.get(url, headers=h[who])
        assert r.status_code in (403, 404), (who, r.status_code)                    # 非金額可見者：不給單據 PDF/HTML
        assert "5000" not in r.text and "5,000" not in r.text, who
    assert client.get(url, headers=h["appl"]).status_code in (200, 503), "申請人本人應可（503＝無瀏覽器可印 PDF）"
    assert client.get(url, headers=h["sa"]).status_code in (200, 503)


def test_list_masks_amount_for_case_owner_who_is_not_applicant(world):
    client, h, eid = world
    r = client.get("/api/quotations/MQ-P2-1/extra-expenses", headers=h["owner"])
    assert r.status_code == 200, r.text
    assert "5000" not in r.text and "高鐵" not in r.text, r.text[:300]
    assert "5000" in client.get("/api/quotations/MQ-P2-1/extra-expenses", headers=h["appl"]).text          # 正對照：申請人看得到


def test_filehub_hides_typed_expense_attachment_from_non_viewers(world):
    client, h, eid = world
    for who in ("owner", "fc"):
        r = client.get("/api/filehub/search", headers=h[who], params={"q": "發票", "quote_no": "MQ-P2-1"})
        assert r.status_code == 200, (who, r.status_code, r.text[:200])
        assert "發票.pdf" not in r.text, (who, "非金額可見者在檔案中心看到了費用單據的附件名稱")
    ra = client.get("/api/filehub/search", headers=h["appl"], params={"q": "發票", "quote_no": "MQ-P2-1"})
    assert ra.status_code == 200
    ra2 = client.get("/api/filehub/search", headers=h["sa"], params={"q": "發票", "quote_no": "MQ-P2-1"})
    assert "發票.pdf" in ra.text or "發票.pdf" in ra2.text, "正對照：申請人或最高管理者至少一方應搜得到（否則探針沒打中）"


def test_legacy_extra_expense_attachment_not_visible_to_outsider(world):
    """R4：舊版（kind=''）額外支出的附件：案件擁有者看得到（正對照）、沒有案件權限的人（即使有 file_center）看不到。"""
    import db
    client, h, eid = world
    files = [{"id": "f2", "filename": "舊版收據.pdf", "path": "case_extra_expense/MQ-P2-1_2/y.pdf", "size": 10, "uploadedAt": "2026-09-01T00:00:00", "uploadedBy": "申請人"}]
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, note, expense_date, doc_no,"
            " files_json, created_by, created_by_name, created_by_inferred, payer_username, payer_name, created_at, updated_at, updated_by_name,"
            " status, approval_json, change_status, change_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,'{}','','{}')",
            ("MQ-P2-1", "材料", "舊版", 1, "式", 100, 100, "", "2026-09-01", "", json.dumps(files, ensure_ascii=False), "p2_appl", "申請人",
             "p2_appl", "申請人", "2026-09-01T00:00:00", "2026-09-01T00:00:00", "申請人", "已核准"))
        conn.commit()
    finally:
        conn.close()
    ok = client.get("/api/filehub/search", headers=h["owner"], params={"q": "舊版收據", "quote_no": "MQ-P2-1"})
    assert ok.status_code == 200 and "舊版收據.pdf" in ok.text, "正對照：案件擁有者應搜得到舊版附件"
    for who in ("fc",):
        r = client.get("/api/filehub/search", headers=h[who], params={"q": "舊版收據", "quote_no": "MQ-P2-1"})
        assert r.status_code == 200 and "舊版收據.pdf" not in r.text, "無案件權限者看到了舊版額外支出附件"
