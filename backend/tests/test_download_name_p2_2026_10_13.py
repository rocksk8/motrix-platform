# -*- coding: utf-8 -*-
"""A7 第二期：報價單四個文件端點（報價單 PDF／內部版、存檔版本、結案報表、專案執行報告）的 Content-Disposition。

單號就是案件編號 ⇒ 不重複寫兩次：預設檔名＝案件名_文件類型_單號；沒有案件權限 ⇒ 只剩文件類型_單號；永不含金額。
"""
import json
from urllib.parse import unquote

import pytest

import db

QNO = "Q-DN2-0001"
PROJECT = "新竹廠區網路建置"
AMOUNT = "7654321"


def _login(client, make_user, name, role):
    pw = "Pw!" + name + "123"
    make_user(name, pw, role)
    r = client.post("/api/auth/login", json={"username": name, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def boss(client, make_user):
    return _login(client, make_user, "dn2_boss", "superadmin")


@pytest.fixture()
def seeded(client, make_user, tmp_path):
    make_user("dn2_owner", "Pw!dn2_owner123", "sales")
    conn = db.get_db()
    try:
        owner = conn.execute("SELECT id FROM users WHERE username=?", ("dn2_owner",)).fetchone()[0]
        data = {"items": [], "dealTag": "已結案", "docVersions": [{"seq": 1, "event": "送審", "at": "2026-10-13T09:00:00", "file": "x.pdf"}]}
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, deal_tag,"
                     " created_at, updated_at, sales_person_id, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (QNO, "已送出", "某某科技", PROJECT, int(AMOUNT), int(AMOUNT) - 1, json.dumps(data), "已結案",
                      "2026-01-01T00:00:00", "2026-01-01T00:00:00", owner, "dn2_owner"))
        conn.commit()
    finally:
        conn.close()
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF-1.4 archived")
    return str(f)


def _cd(r):
    h = r.headers["content-disposition"]
    h.encode("latin-1")
    return h, unquote(h.split("filename*=UTF-8''", 1)[1])


def _patch(monkeypatch, seeded):
    from modules.case.api import quotations as Q
    for fn in ("generate_pdf_bytes", "generate_case_closing_pdf_bytes", "generate_project_execution_report_pdf_bytes"):
        monkeypatch.setattr(Q, fn, lambda *a, **k: b"%PDF-1.4 stub")
    monkeypatch.setattr(Q, "_resolve_archived_pdf", lambda base, rel: seeded)


CASES = [
    ("/api/quotations/%s/pdf-download" % QNO, "%s_報價單_%s.pdf" % (PROJECT, QNO), "報價單"),
    ("/api/quotations/%s/pdf-download?internal=true" % QNO, "%s_報價單（內部）_%s.pdf" % (PROJECT, QNO), "報價單（內部）"),
    ("/api/quotations/%s/versions/1/download" % QNO, "%s_報價單存檔版本_%s_送審_20261013.pdf" % (PROJECT, QNO), "報價單存檔版本"),
    ("/api/quotations/%s/closing-report-pdf" % QNO, "%s_結案報表_%s.pdf" % (PROJECT, QNO), "結案報表"),
    ("/api/quotations/%s/project-report-pdf" % QNO, "%s_專案執行報告_%s.pdf" % (PROJECT, QNO), "專案執行報告"),
]


@pytest.mark.parametrize("url,expected,label", CASES, ids=[c[2] for c in CASES])
def test_quotation_documents_name(client, boss, seeded, monkeypatch, url, expected, label):
    _patch(monkeypatch, seeded)
    r = client.get(url, headers=boss)
    assert r.status_code == 200, (url, r.status_code, r.text[:200])
    h, name = _cd(r)
    assert name == expected, name
    assert AMOUNT not in h and AMOUNT not in name
    assert name.count(QNO) == 1                                   # 單號即案件編號，不重複


@pytest.mark.parametrize("url,expected,label", CASES, ids=[c[2] for c in CASES])
def test_quotation_documents_without_case_read(client, boss, seeded, monkeypatch, url, expected, label):
    _patch(monkeypatch, seeded)
    from helpers import case_access
    orig = case_access.row_access.visible
    monkeypatch.setattr(case_access.row_access, "visible", lambda *a, **k: False if k.get("scope") == "read" else orig(*a, **k))
    r = client.get(url, headers=boss)
    assert r.status_code == 200, (url, r.status_code, r.text[:200])
    h, name = _cd(r)
    assert PROJECT not in name and PROJECT not in unquote(h) and "某某" not in name
    assert name.endswith(QNO + ".pdf") or QNO in name


def test_no_hand_written_headers_left_in_quotation_documents():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "modules/case/api/quotations.py").read_text(encoding="utf-8")
    for fn in ("def download_quotation_pdf", "def download_quotation_version", "def download_case_closing_report_pdf",
               "def download_project_execution_report_pdf"):
        if fn not in src:
            continue
        i = src.index(fn)
        body = src[i:i + 4500].split("\n@router", 1)[0]
        assert "download_name.build(" in body and "Content-Disposition" not in body, fn


def test_case_no_equal_to_doc_no_is_not_repeated(monkeypatch):
    from helpers import download_name as D
    monkeypatch.setattr(D, "_case_label", lambda conn, qn, u: (True, "案", ""))
    monkeypatch.setattr(D, "_settings", lambda: dict(D.DEFAULTS))
    r = D.build("quotation", quote_no="Q-1", doc_no="Q-1", ext="pdf", user={"id": 1}, conn=object())
    assert r.name == "案_報價單_Q-1.pdf"
    r2 = D.build("completion", quote_no="Q-1", doc_no="CN-1", ext="pdf", user={"id": 1}, conn=object())
    assert r2.name == "Q-1_案_完工單_CN-1.pdf"


# ── 期間型／其他端點：檔名維持現狀，只統一標頭編碼（設計 Q7）────────────────────────

UNIFIED = ["modules/analytics/api/reports.py", "modules/accounting/api/accounting_export.py", "modules/arap/api/cashier.py",
           "modules/accounting/api/ledger_closing.py", "modules/accounting/api/ledger_tax.py", "modules/netplan/api.py",
           "modules/lodging/api_records.py", "modules/daily_tasks/api.py", "routers/custom_records.py",
           "modules/subcontract/api/contractors.py", "modules/case/api/quotations.py"]


def test_unified_modules_use_content_disposition_helper():
    """這些檔不再手寫 `attachment; filename…`：一律 `download_name.content_disposition()`（latin-1 安全退路＋RFC 8187＋淨化）。
    例外：`xlsx_out._pdf_filename`（跟隨來源檔名）尚未納入。"""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for rel in UNIFIED:
        src = (root / rel).read_text(encoding="utf-8")
        bad = [l.strip() for l in src.splitlines() if "attachment; filename" in l and "download_name" not in l]
        assert not bad, (rel, bad)


def test_content_disposition_helper_handles_hostile_report_names():
    from helpers import download_name as D
    for raw in ("財務報表_2026年度_決算.xlsx", "營業稅401_2026年第3期.xlsx", "MOTRIX_營運報表_2026-08.xlsx", "lodging-12.csv",
                'x"y\z%.csv', "a\r\nSet-Cookie: x.csv", "\u202efdp.exe"):
        h = D.content_disposition(raw)
        h.encode("latin-1")
        assert "\r" not in h and "\n" not in h and h.startswith("attachment;")
