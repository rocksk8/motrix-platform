"""簽核佇列的送審詳情（2026-09-14）。

使用者要求：「簽核佇列內的送審資料要詳細，例如夾帶檔案，要顯示哪個案件什麼內容，
如果是檔案可顯示預覽，編修後的結果」。

原本佇列每一筆只有單號／客戶／金額／簽核進度——簽核人要知道「這張到底送了什麼」，
得自己跑去各模組頁面翻。這支端點依 type 分流，回傳：屬於哪個案件、內容欄位、明細、
**夾帶檔案**（含 kind 讓前端決定怎麼預覽）、**編修後的結果**。

清單本身刻意不帶這些（佇列一次可能上百筆，每筆都讀 items_json／files_json 會讓
開啟佇列變慢）——這也是為什麼要有這支獨立端點。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": "Bearer " + token}


def _seed_case(quote_no="MQ-AQD-001"):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, sales_person, assigned_user_ids) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", 100000, 95238,
             json.dumps({"dealTag": "已成案",
                         "items": [{"name": "交換器", "qty": 2, "amount": 50000}],
                         "paymentTerms": "月結 30 天"}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", "業務甲", "[]"),
        )
        conn.commit()
    finally:
        conn.close()
    return quote_no


def test_detail_shows_case_and_content_for_completion_note(client, make_user):
    """完工單：要看得到屬於哪個案件、執行說明、完成項目。"""
    import db
    u, p = make_user(username="aqd_u1", role="superadmin")
    quote_no = _seed_case("MQ-AQD-CN")
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO completion_notes (note_no, quote_no, status, data_json, created_by, "
            "created_at, updated_at, site_address, work_summary, items_json, warranty_months) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("CN-AQD-001", quote_no, "待審核", "{}", "aqd_u1",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "台中市西屯區",
             "完成機房佈線與測試",
             json.dumps([{"name": "佈線", "qty": 1}], ensure_ascii=False), 12),
        )
        conn.commit()
    finally:
        conn.close()

    d = client.get("/api/approval-queue/detail?type=completion_note&id=CN-AQD-001",
                   headers=_auth(_login(client, u, p))).json()
    assert d["case"]["quoteNo"] == quote_no
    assert d["case"]["customerName"] == "測試客戶"
    labels = {f["label"]: f["value"] for f in d["fields"]}
    assert labels["執行說明"] == "完成機房佈線與測試", labels
    assert labels["服務地點"] == "台中市西屯區"
    assert len(d["items"]) == 1


def test_detail_lists_attached_files_with_preview_kind(client, make_user):
    """額外支出：夾帶的收據要列出來，而且要標出是不是圖片（前端據此決定怎麼預覽）。"""
    import db
    u, p = make_user(username="aqd_u2", role="superadmin")
    quote_no = _seed_case("MQ-AQD-XE")
    files = [
        {"id": "f1", "filename": "收據.jpg", "path": "extra/2026/receipt.jpg",
         "uploadedBy": "工程師乙"},
        {"id": "f2", "filename": "明細.pdf", "path": "extra/2026/detail.pdf"},
    ]
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, "
            "total_cost, note, expense_date, doc_no, files_json, created_by, created_by_name, "
            "created_by_inferred, payer_username, payer_name, created_at, updated_at, "
            "updated_by_name, status, approval_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,'待審核','{}')",
            (quote_no, "交通", "現場往返油資", 1, "式", 1200, 1200, "自付", "2026-09-01", "R-001",
             json.dumps(files, ensure_ascii=False), "eng_b", "工程師乙", "eng_b", "工程師乙",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "工程師乙"),
        )
        conn.commit()
        xe_id = conn.execute("SELECT id FROM case_extra_expenses WHERE quote_no=?",
                             (quote_no,)).fetchone()["id"]
    finally:
        conn.close()

    d = client.get("/api/approval-queue/detail?type=extra_expense&id=" + str(xe_id),
                   headers=_auth(_login(client, u, p))).json()
    kinds = {f["name"]: f["kind"] for f in d["files"]}
    assert kinds == {"收據.jpg": "image", "明細.pdf": "pdf"}, kinds
    assert any(f["uploadedBy"] == "工程師乙" for f in d["files"])
    labels = {f["label"]: f["value"] for f in d["fields"]}
    assert labels["項目"] == "現場往返油資" and labels["支出人"] == "工程師乙"


def test_detail_shows_change_request_result(client, make_user):
    """額外支出的變更申請：簽核人要看得到「核准後會變成什麼」的前後對照。"""
    import db
    u, p = make_user(username="aqd_u3", role="superadmin")
    quote_no = _seed_case("MQ-AQD-CHG")
    change = {"description": "更正後品名", "qty": 2, "unit_cost": 900,
              "total_cost": 1800, "note": "改成兩件"}
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, "
            "total_cost, note, expense_date, doc_no, files_json, created_by, created_by_name, "
            "created_by_inferred, payer_username, payer_name, created_at, updated_at, "
            "updated_by_name, status, approval_json, change_status, change_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,'[]',?,?,0,?,?,?,?,?,'已核准','{}','待審核',?)",
            (quote_no, "材料", "原始品名", 1, "式", 1000, 1000, "原備註", "2026-09-01", "",
             "eng_c", "工程師丙", "eng_c", "工程師丙", "2026-01-01T00:00:00",
             "2026-01-01T00:00:00", "工程師丙", json.dumps(change, ensure_ascii=False)),
        )
        conn.commit()
        xe_id = conn.execute("SELECT id FROM case_extra_expenses WHERE quote_no=?",
                             (quote_no,)).fetchone()["id"]
    finally:
        conn.close()

    d = client.get("/api/approval-queue/detail?type=extra_expense&id=" + str(xe_id),
                   headers=_auth(_login(client, u, p))).json()
    assert d["changes"], d
    assert d["changes"]["before"]["項目"] == "原始品名"
    assert d["changes"]["after"]["項目"] == "更正後品名"
    assert d["changes"]["after"]["小計"] == 1800


def test_detail_shows_staged_files_of_case_change(client, make_user):
    """已結案案件的變更申請：暫存待審的上傳檔案必須看得到——否則簽核人是在盲簽。"""
    import db
    u, p = make_user(username="aqd_u4", role="superadmin")
    quote_no = _seed_case("MQ-AQD-CC")
    staged = [{"id": "s1", "filename": "補件照片.png", "path": "staged/2026/photo.png"}]
    conn = db.get_db()
    try:
        cur = conn.execute(
            "INSERT INTO case_change_requests (quote_no, action_type, summary, payload_json, "
            "staged_files_json, status, requested_by, requested_by_display, requested_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            # 2026-09-14 更正：原本用的 "material_files" **不在 approve_case_change()
            # 支援的類型裡**（真的送出去會撞「未知的變更類型」500），而當時的斷言
            # 驗的是「payload 被原樣回傳」——等於把後來要修掉的那個 bug 固化成規格。
            # 改用真實類型，並改驗可讀摘要（見 test_case_change_summary_2026_09_14.py）。
            (quote_no, "material_file_upload", "補上叫料照片",
             json.dumps({"idx": 0}, ensure_ascii=False),
             json.dumps(staged, ensure_ascii=False), "pending", "eng_d", "工程師丁",
             "2026-09-14T10:00:00"),
        )
        cid = cur.lastrowid
        conn.commit()
    finally:
        conn.close()

    d = client.get("/api/approval-queue/detail?type=case_change&id=" + str(cid),
                   headers=_auth(_login(client, u, p))).json()
    assert [f["name"] for f in d["files"]] == ["補件照片.png"], d["files"]
    assert d["files"][0]["kind"] == "image"
    # 摘要要講得出「這次要做什麼、動到哪一項、帶了哪些檔案」，而不是倒 payload
    after = d["changes"]["after"]
    assert "叫料項目 #1" in after["動作"], after
    assert after["檔案數"] == 1
    assert "補件照片.png" in after["檔案"]
    # 只驗**摘要**裡沒有實體路徑；`files` 陣列本來就帶 path（前端靠它開檔），
    # 那是既有設計、不是這次要改的東西
    assert "staged/2026/photo.png" not in json.dumps(d["changes"], ensure_ascii=False),         "檔案的實體路徑不該出現在變更摘要裡"


def test_detail_shows_quotation_items_and_last_edit(client, make_user):
    """報價單：品項與「最近一次編修」——解鎖編輯後再送審時，簽核人要知道改了什麼。"""
    import db
    u, p = make_user(username="aqd_u5", role="superadmin")
    quote_no = _seed_case("MQ-AQD-Q")
    conn = db.get_db()
    try:
        row = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?",
                           (quote_no,)).fetchone()
        d0 = json.loads(row["data_json"])
        d0["editHistory"] = [{"rev": 3, "at": "2026-09-14T09:00:00", "by": "jeff",
                              "byDisplay": "黃玉龍", "type": "quote_edit"}]
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?",
                     (json.dumps(d0, ensure_ascii=False), quote_no))
        conn.commit()
    finally:
        conn.close()

    d = client.get("/api/approval-queue/detail?type=quotation&id=" + quote_no,
                   headers=_auth(_login(client, u, p))).json()
    assert d["items"] and d["items"][0]["name"] == "交換器"
    assert "第 3 版" in d["changes"]["label"], d["changes"]
    assert d["changes"]["after"]["編修人"] == "黃玉龍"


def test_detail_rejects_unknown_type(client, make_user):
    """不支援的類型要明確回 400——靜默回空物件會讓前端以為「這張沒有內容」。"""
    u, p = make_user(username="aqd_u6", role="superadmin")
    r = client.get("/api/approval-queue/detail?type=nonsense&id=x",
                   headers=_auth(_login(client, u, p)))
    assert r.status_code == 400, r.text
