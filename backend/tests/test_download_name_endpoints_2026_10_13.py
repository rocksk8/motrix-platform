# -*- coding: utf-8 -*-
"""A7 第一期：非報價單 PDF 下載端點的 Content-Disposition（設計 DOWNLOAD-FILENAME-CASE-T56.md r6 §6.4）。

每個端點：①超級管理員（讀得到案件）⇒ 檔名含案件編號＋案件名＋文件類型＋單號；②沒有案件權限的角色 ⇒ 保留案件編號、不含案件名；
③檔名與標頭都不含金額數字；④既有內容（PDF 位元組）不變。PDF 產生器以替身取代（本題只驗命名，不驗 PDF 內容）。
"""
import json
import re
from urllib.parse import unquote

import pytest

import db

QNO = "Q-DN-0001"
PROJECT = "新竹廠區網路建置"
AMOUNT = "7654321"            # 金額哨兵：任何位置出現都是洩漏


def _login(client, make_user, name, role):
    pw = "Pw!" + name + "123"
    make_user(name, pw, role)
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def boss(client, make_user):
    return _login(client, make_user, "dn_boss", "superadmin")


@pytest.fixture()
def owner_id(client, make_user):
    make_user("dn_owner", "Pw!dn_owner123", "sales")
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", ("dn_owner",)).fetchone()[0]
    finally:
        conn.close()


def _seed(table_sql, params, owner):
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                     " created_at, updated_at, sales_person_id, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (QNO, "已送出", "某某科技", PROJECT, int(AMOUNT), int(AMOUNT) - 1, json.dumps({"items": []}), now, now, owner, "dn_owner"))
        if "contractor_payment_vouchers" in table_sql:
            cur = conn.execute("INSERT INTO contractor_dispatches (quote_no) VALUES (?)", (QNO,))
            table_sql = table_sql.replace("(voucher_no,", "(dispatch_id, voucher_no,").replace("VALUES (?,", "VALUES (?,?,", 1)
            params = (cur.lastrowid,) + tuple(params)
        conn.execute(table_sql, params)
        conn.commit()
    finally:
        conn.close()


def _cd(r):
    h = r.headers["content-disposition"]
    h.encode("latin-1")
    star = h.split("filename*=UTF-8''", 1)[1]
    return h, unquote(star)


def _assert_money_free(h, name):
    assert AMOUNT not in h and AMOUNT not in name


CASES = [
    # (key, 模組路徑, 產生器名, 端點, 種子 SQL, 種子參數, 文件類型用語, 單號)
    ("completion", "modules.case.api.completion_notes", "generate_completion_pdf_bytes", "/api/completion-notes/{no}/pdf-download",
     "INSERT INTO completion_notes (note_no, quote_no, data_json) VALUES (?,?,?)", ("CN-DN-1", QNO, "{}"), "完工單", "CN-DN-1"),
    ("shipping", "modules.supply.api.shipping_notes", "generate_shipping_pdf_bytes", "/api/shipping-notes/{no}/pdf-download",
     "INSERT INTO shipping_notes (note_no, quote_no, data_json) VALUES (?,?,?)", ("SN-DN-1", QNO, "{}"), "出貨單", "SN-DN-1"),
    ("payment_request", "modules.arap.api.payment_requests", "generate_payment_request_pdf_bytes", "/api/payment-requests/{no}/pdf-download",
     "INSERT INTO payment_requests (request_no, quote_no, data_json) VALUES (?,?,?)", ("PR-DN-1", QNO, "{}"), "請款單", "PR-DN-1"),
    ("invoice_voucher", "modules.arap.api.invoice_vouchers", "generate_invoice_voucher_pdf_bytes", "/api/invoice-vouchers/{no}/pdf-download",
     "INSERT INTO invoice_vouchers (voucher_no, quote_no, data_json) VALUES (?,?,?)", ("IV-DN-1", QNO, "{}"), "開票申請", "IV-DN-1"),
    ("contractor_voucher", "modules.subcontract.api.contractor_vouchers", "generate_contractor_voucher_pdf_bytes", "/api/contractor-vouchers/{no}/pdf-download",
     "INSERT INTO contractor_payment_vouchers (voucher_no, quote_no, data_json) VALUES (?,?,?)", ("CV-DN-1", QNO, "{}"), "承攬商傳票", "CV-DN-1"),
]


@pytest.mark.parametrize("key,mod,gen,url,sql,params,label,no", CASES, ids=[c[0] for c in CASES])
def test_superadmin_gets_case_no_name_type_and_number(client, boss, owner_id, monkeypatch, key, mod, gen, url, sql, params, label, no):
    import importlib
    m = importlib.import_module(mod)
    monkeypatch.setattr(m, gen, lambda *a, **k: b"%PDF-1.4 stub")
    _seed(sql, params, owner_id)
    r = client.get(url.format(no=no), headers=boss)
    assert r.status_code == 200, (key, r.status_code, r.text[:200])
    assert r.content == b"%PDF-1.4 stub"
    h, name = _cd(r)
    assert name == f"{QNO}_{PROJECT}_{label}_{no}.pdf", name
    _assert_money_free(h, name)


@pytest.mark.parametrize("key,mod,gen,url,sql,params,label,no", CASES, ids=[c[0] for c in CASES])
def test_caller_without_case_access_keeps_case_no_but_not_name(client, boss, owner_id, monkeypatch, key, mod, gen, url, sql, params, label, no):
    import importlib
    m = importlib.import_module(mod)
    monkeypatch.setattr(m, gen, lambda *a, **k: b"%PDF-1.4 stub")
    _seed(sql, params, owner_id)
    from helpers import case_access
    orig = case_access.row_access.visible
    monkeypatch.setattr(case_access.row_access, "visible",
                        lambda *a, **k: False if k.get("scope") == "read" else orig(*a, **k))      # 只關「讀案件頁」這一條；端點自己的單據權限不動
    r = client.get(url.format(no=no), headers=boss)
    assert r.status_code == 200, (key, r.status_code, r.text[:200])
    h, name = _cd(r)
    assert PROJECT not in name and PROJECT not in unquote(h) and "某某科技" not in name
    assert name == f"{QNO}_{label}_{no}.pdf", name
    _assert_money_free(h, name)


def test_no_endpoint_in_phase1_still_hand_writes_the_header():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for _, mod, *_rest in CASES:
        src = (root / (mod.replace(".", "/") + ".py")).read_text(encoding="utf-8")
        i = src.index("pdf-download")
        body = src[i:i + 2600]
        assert "download_name.build(" in body and "Content-Disposition" not in body, mod


# ── 勞報單（承攬人姓名、日期、第 N 次）─────────────────────────────────────────

def _seed_payslip():
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO payslips (slip_no, contractor_name, slip_date, data_json) VALUES (?,?,?,?)",
                     ("PS-202610-001", "王小明", "2026-10-13", "{}"))
        conn.commit()
    finally:
        conn.close()


def test_payslip_download_keeps_contractor_name_and_date(client, boss, monkeypatch):
    import pdf_gen
    monkeypatch.setattr(pdf_gen, "generate_payslip_pdf_bytes", lambda *a, **k: b"%PDF-1.4 stub")
    _seed_payslip()
    r = client.get("/api/payslips/PS-202610-001/pdf-download", headers=boss)
    assert r.status_code == 200, r.text[:200]
    h, name = _cd(r)
    assert name == "勞報單_王小明_20261013.pdf", name


def test_payslip_archive_name_has_nth(client, boss, monkeypatch):
    import pdf_gen
    monkeypatch.setattr(pdf_gen, "generate_payslip_pdf_bytes", lambda *a, **k: b"%PDF-1.4 stub")
    _seed_payslip()
    r = client.get("/api/payslips/PS-202610-001/archive/3", headers=boss)
    assert r.status_code == 200, r.text[:200]
    h, name = _cd(r)
    assert name == "勞報單_王小明_20261013_第3次.pdf", name
    assert h.startswith("inline;")


def test_payslip_name_hidden_when_setting_off(client, boss, monkeypatch):
    import pdf_gen
    from helpers import download_name as D
    monkeypatch.setattr(pdf_gen, "generate_payslip_pdf_bytes", lambda *a, **k: b"%PDF-1.4 stub")
    monkeypatch.setattr(D, "_settings", lambda: {**D.DEFAULTS, "payslip_show_name": 0})
    _seed_payslip()
    r = client.get("/api/payslips/PS-202610-001/pdf-download", headers=boss)
    h, name = _cd(r)
    assert "王小明" not in name and "王小明" not in unquote(h)


def test_batch2_modules_do_not_hand_write_headers():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for rel in ("modules/payroll/api/payslips.py", "modules/payroll/api/bonus.py", "modules/accounting/api/vouchers.py",
                "modules/case/api/expense_form_pdf.py"):
        src = (root / rel).read_text(encoding="utf-8")
        bad = [l for l in src.splitlines() if re.search(r'"Content-Disposition"\s*:\s*[\'"f]', l) and "download_name" not in l]
        # payslips.py 的簽回檔讀取（inline，不是下載檔名）與報表類端點不在 A7 範圍
        bad = [l for l in bad if '"Content-Disposition": "inline"' not in l]
        assert not bad, (rel, bad)
