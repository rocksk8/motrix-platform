"""A29-B：承攬商／外包人員收款帳號遮蔽的『輸出面 × 角色』掃描（合成資料）。非守門測試。"""
import json, io
import pytest
import db

VENDOR_FULL = "00012345678901"       # 協力廠商帳號
PERS_FULL = "99887766554433"         # 外包人員（個人）帳號（憑據 snapshot.personnel）
CONTR_FULL = "55544433322211"        # contractors 表（個人名冊）帳號
SLIP_FULL = "11122233344455"         # 勞報單內的個人帳號
FULLS = (VENDOR_FULL, PERS_FULL, CONTR_FULL, SLIP_FULL)
PASSBOOK = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p}); assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _seed():
    snap = {"vendorName": "測試承攬商", "grandTotal": 1000, "bankAccountName": "測試承攬商", "bankAccountNumber": VENDOR_FULL, "bankPassbookImage": PASSBOOK,
            "personnel": [{"name": "甲", "bankAccountNumber": PERS_FULL, "bankPassbookImage": PASSBOOK}]}
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, data_json, created_at, updated_at) VALUES ('MQ-SW-1','已送出','客','案','{}','2026-01-01','2026-01-01')")
        c.execute("INSERT INTO contractor_dispatches (id, quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json, total_amount, tax_rate, status, notes, created_by, created_at, updated_at, accepted_at, accepted_by, files_json, invoice_files_json)"
                  " VALUES (99301,'MQ-SW-1',NULL,'2026-09-01','測試','[]','[]',1000,0,'已完成','','x','2026-01-01T00:00:00','2026-01-01T00:00:00','','','[]','[]')")
        c.execute("INSERT INTO contractor_payment_vouchers (voucher_no, quote_no, dispatch_id, status, snapshot_json, data_json, created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  ("CV-SW-1", "MQ-SW-1", 99301, "待審核", json.dumps(snap, ensure_ascii=False),
                   json.dumps({"approval": {"tiers": [{"approvers": [{"username": "sw_apr", "status": "pending"}]}], "currentTier": 0}}, ensure_ascii=False),
                   "x", "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        c.execute("INSERT INTO contractors (name, bank_code, bank_name, bank_account_name, bank_account_number, bank_passbook_image, created_at, updated_at) VALUES ('名冊甲','812','台新','名冊甲',?,?, '2026-01-01','2026-01-01')", (CONTR_FULL, PASSBOOK))
        c.execute("INSERT INTO payslips (slip_no, contractor_name, data_json, created_at, updated_at) VALUES ('PS-SW-1','名冊甲',?, '2026-01-01','2026-01-01')",
                  (json.dumps({"slipNo": "PS-SW-1", "contractorName": "名冊甲", "bankAccountNumber": SLIP_FULL, "bankAccountName": "名冊甲", "grossAmount": 1000}, ensure_ascii=False),))
        c.commit()
    finally:
        c.close()


def _text(r):
    try:
        return r.text
    except Exception:
        return ""


def _pdf_text(b):
    from pypdf import PdfReader
    try:
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(b)).pages)
    except Exception as e:
        return "PDFERR %s" % e


def test_sweep(client, make_user):
    users = {}
    for n, role, mods in (("sw_sa", "superadmin", None),
                          ("sw_admin", "admin", ["contractor_list", "procurement", "case_manage", "finance", "cashier", "quotation", "payslip", "financial_view"]),
                          ("sw_apr", "admin", ["procurement", "case_manage", "quotation", "financial_view"]),
                          ("sw_cl", "engineer", ["contractor_list"]),
                          ("sw_cash", "engineer", ["cashier", "finance", "financial_view"])):
        users[n] = _login(client, *make_user(username=n, role=role, modules=mods))
    c = client
    r = c.post("/api/vendor-contractors", headers=users["sw_sa"], json={"name": "測試承攬商", "tax_id": "12345678",
               "data": {"bankCode": "700", "bankName": "郵局", "bankBranch": "中", "bankAccountName": "測試承攬商", "bankAccountNumber": VENDOR_FULL}})
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert c.put("/api/vendor-contractors/%d/passbook" % vid, headers=users["sw_sa"], json={"bank_passbook": PASSBOOK}).status_code == 200
    _seed()
    surfaces = [
        ("GET", "/api/vendor-contractors"), ("GET", "/api/vendor-contractors/%d" % vid), ("GET", "/api/vendor-contractors/selectable"),
        ("GET", "/api/vendor-contractors/%d/passbook" % vid),
        ("GET", "/api/contractors"), ("GET", "/api/contractors/1"), ("GET", "/api/contractors/selectable"), ("GET", "/api/contractors/1/id-card"),
        ("GET", "/api/contractors/export"),
        ("GET", "/api/contractor-vouchers"), ("GET", "/api/contractor-vouchers/CV-SW-1"), ("GET", "/api/contractor-vouchers/CV-SW-1/personnel-links"),
        ("GET", "/api/contractor-vouchers/CV-SW-1/pdf-download"), ("POST", "/api/contractor-vouchers/CV-SW-1/export"),
        ("GET", "/api/approval-queue"), ("GET", "/api/approval-queue/detail?type=contractor_voucher&id=CV-SW-1"),
        ("GET", "/api/cashier/payable-queue"), ("GET", "/api/cashier/payslip-queue"), ("GET", "/api/cashier/pending-payables"), ("GET", "/api/cashier/execution-history"),
        ("GET", "/api/payslips"), ("GET", "/api/payslips/PS-SW-1"), ("GET", "/api/payslips/PS-SW-1/pdf-download"),
        ("GET", "/api/vouchers/summary-sources?quote_no=MQ-SW-1"),
    ]
    rows, leaks = [], []
    for who in ("sw_sa", "sw_admin", "sw_apr", "sw_cl", "sw_cash"):
        for method, path in surfaces:
            r = c.request(method, path, headers=users[who])
            txt = _text(r)
            if "pdf" in (r.headers.get("content-type") or "") or path.endswith("pdf-download") or path.endswith("/export"):
                txt = txt + _pdf_text(r.content) + r.content.decode("latin-1", "ignore")
            ct = r.headers.get("content-type") or ""
            if "spreadsheet" in ct or "excel" in ct or r.content[:2] == b"PK":
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(io.BytesIO(r.content))
                    txt += " ".join(str(cell.value) for ws in wb.worksheets for row in ws.iter_rows() for cell in row if cell.value is not None)
                    print("SWEEP xlsx parsed", who, path, r.status_code, len(wb.worksheets))
                except Exception as e:
                    print("SWEEP xlsx parse fail", who, path, e)
            hit = [f for f in FULLS if f in txt]
            pb = PASSBOOK[:40] in txt
            rows.append((who, method, path, r.status_code, hit, pb))
            if who != "sw_sa" and (hit or pb):
                leaks.append((who, method, path, r.status_code, hit, pb))
    sa_hits = {(p) for (w, m, p, s, h, pb) in rows if w == "sw_sa" and h}
    print("SWEEP positive-control (superadmin sees full on):", sorted(sa_hits))
    for w, m, p, s, h, pb in rows:
        if w == "sw_sa" and s >= 400:
            print("SWEEP sa non-2xx", m, p, s)
    for who in ("sw_admin", "sw_apr", "sw_cl", "sw_cash"):
        print("SWEEP", who, " ".join("%s=%s%s" % (p.split("?")[0].replace("/api/", ""), s, "*" if any(w == who and pp == p and "****" in str(h) for (w, m, pp, s, h, pb) in rows) else "") for (w, m, p, s, h, pb) in rows if w == who))
    print("SWEEP LEAKS:", json.dumps(leaks, ensure_ascii=False))
    print("SWEEP status table (non-sa):", [(w, p, s) for (w, m, p, s, h, pb) in rows if w != "sw_sa" and s in (500,)])
    assert sa_hits, "positive control failed: superadmin never saw a full number — probe not valid"
    assert not leaks, leaks
