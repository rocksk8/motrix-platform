"""勞報單 作廢、簽回、出納付款（2026-09-29；使用者裁示：成本取應付總額、歸月依付款日期、出納回填既有傳票單號）。

狀態：草稿 → 已匯出 → 已簽回 → 已付款；已作廢＝終結（只准從已匯出）。
INTEGRATION-POINTS：IP-103 `payslip.payables`（M07 → M05 出納）、IP-9 `expense.entries`（名稱 payslip，M07 → M08 報表）、
IP-4 追加 `voucher.by_no`（M06 → M07，驗證出納填的傳票單號）。
反向控制：會計模組不在 ⇒ 標記付款拒絕並說明；提供者不在 ⇒ 出納頁與報表照常、只少這一項並明說。
"""
import json

import pytest

from core import registry
from core import source_tree
from modules.payroll.api import payslips as payslips_api
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import (  # noqa: F401
    _login, _auth, _insert_payslip, _payload)

_NEEDS_ACCOUNTING = pytest.mark.skipif(not source_tree.module_installed("modules/accounting/"),
                                       reason="需要會計（M06）：模組不在這個安裝包")
_NEEDS_ARAP = pytest.mark.skipif(not source_tree.module_installed("modules/arap/"),
                                 reason="需要應收應付（M05）：模組不在這個安裝包")
_NEEDS_ANALYTICS = pytest.mark.skipif(not source_tree.module_installed("modules/analytics/"),
                                      reason="需要營運報表（M08）：模組不在這個安裝包")


@pytest.fixture(autouse=True)
def _archive_tmp(tmp_path, monkeypatch):
    """簽回檔是 F2 實體檔：一律寫進 tmp，不碰真實的勞報單存檔目錄。"""
    monkeypatch.setattr(payslips_api, "_archive_dir", lambda: str(tmp_path / "payslip_archive"))


def _su(client, make_user, name):
    su, pw = make_user(username=name, role="superadmin")
    return _login(client, su, pw)


def _row(no):
    import db
    c = db.get_db()
    try:
        return dict(c.execute("SELECT * FROM payslips WHERE slip_no=?", (no,)).fetchone())
    finally:
        c.close()


def _void(client, tok, no, reason="金額開錯"):
    return client.post(f"/api/payslips/{no}/void", json={"reason": reason}, headers=_auth(tok))


def _upload(client, tok, no, name="signed.pdf", body=b"%PDF-1.4 test"):
    return client.post(f"/api/payslips/{no}/signed-files", headers=_auth(tok),
                       files=[("files", (name, body, "application/pdf"))])


def _voucher(no="20260929-901", voided=""):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO vouchers_all (voucher_no, voucher_date, created_by, voided_at, "
                  "created_at, updated_at) VALUES (?,?,?,?,?,?)",
                  (no, "2026-09-29", "t", voided, "2026-09-29T00:00:00", "2026-09-29T00:00:00"))
        c.commit()
    finally:
        c.close()


def _pay(client, tok, no, date="2026-09-30", vno="20260929-901"):
    return client.post(f"/api/payslips/{no}/mark-paid", headers=_auth(tok),
                       json={"payment_date": date, "voucher_no": vno})


# ── 作廢 ─────────────────────────────────────────────────────────────────────

def test_void_exported_records_who_when_why(client, make_user):
    tok = _su(client, make_user, "pv_su1")
    _insert_payslip("PS-202609-901", status="已匯出")
    assert _void(client, tok, "PS-202609-901").status_code == 200
    row = _row("PS-202609-901")
    assert row["status"] == "已作廢" and row["void_reason"] == "金額開錯" and row["voided_by"] and row["voided_at"]
    it = [i for i in client.get("/api/payslips", headers=_auth(tok)).json()["items"]
          if i["slip_no"] == "PS-202609-901"][0]
    assert it["status"] == "已作廢" and it["void_reason"] == "金額開錯"


def test_void_rejects_draft_blank_reason_and_double(client, make_user):
    tok = _su(client, make_user, "pv_su2")
    _insert_payslip("PS-202609-902", status="草稿")
    assert _void(client, tok, "PS-202609-902").status_code == 409
    _insert_payslip("PS-202609-903", status="已匯出")
    assert _void(client, tok, "PS-202609-903", "  ").status_code == 400
    assert _row("PS-202609-903")["status"] == "已匯出"
    assert _void(client, tok, "PS-202609-903").status_code == 200
    assert _void(client, tok, "PS-202609-903").status_code == 409
    assert _void(client, tok, "PS-209999-999").status_code == 404


def test_voided_is_terminal(client, make_user):
    tok = _su(client, make_user, "pv_su3")
    _insert_payslip("PS-202609-904", status="已匯出")
    _void(client, tok, "PS-202609-904")
    assert client.put("/api/payslips/PS-202609-904", json=_payload(), headers=_auth(tok)).status_code == 409
    assert client.delete("/api/payslips/PS-202609-904", headers=_auth(tok)).status_code == 400
    assert client.post("/api/payslips/PS-202609-904/export", headers=_auth(tok)).status_code == 409
    assert _upload(client, tok, "PS-202609-904").status_code == 409


def test_void_requires_superadmin(client, make_user):
    su, pw = make_user(username="pv_norm", role="user")
    tok = _login(client, su, pw)
    _insert_payslip("PS-202609-905", status="已匯出")
    assert _void(client, tok, "PS-202609-905").status_code in (401, 403)
    assert _row("PS-202609-905")["status"] == "已匯出"


def test_void_pdf_html_shows_voided():
    import pdf_gen
    html = pdf_gen._payslip_apply_void_mark("<html><body><div>x</div></body></html>",
                                            {"at": "2026-09-29 10:00:00", "by": "王", "reason": "重複開單"})
    assert "已作廢" in html and "重複開單" in html and html.index("已作廢") < html.index("<div>x</div>")
    # 版型被覆寫成沒有 <body> 的結構：標示仍要在，不可靜默漏掉
    assert "已作廢" in pdf_gen._payslip_apply_void_mark("<div>x</div>", {"reason": "r"})


# ── 簽回 ─────────────────────────────────────────────────────────────────────

def test_upload_moves_exported_to_signed_only(client, make_user):
    tok = _su(client, make_user, "pv2_su1")
    _insert_payslip("PS-202609-911", status="草稿")
    assert _upload(client, tok, "PS-202609-911").status_code == 409
    _insert_payslip("PS-202609-912", status="已匯出")
    r = _upload(client, tok, "PS-202609-912")
    assert r.status_code == 201, r.text
    row = _row("PS-202609-912")
    assert row["status"] == "已簽回" and row["signed_by"] and row["signed_at"]
    files = json.loads(row["signed_files_json"])
    assert len(files) == 1 and files[0]["filename"] == "signed.pdf"
    got = client.get(f"/api/payslips/PS-202609-912/signed-files/{files[0]['id']}", headers=_auth(tok))
    assert got.status_code == 200 and got.content == b"%PDF-1.4 test"


def test_signed_upload_rejects_bad_extension_and_empty(client, make_user):
    tok = _su(client, make_user, "pv2_su2")
    _insert_payslip("PS-202609-913", status="已匯出")
    r = client.post("/api/payslips/PS-202609-913/signed-files", headers=_auth(tok),
                    files=[("files", ("x.exe", b"MZ", "application/octet-stream"))])
    assert r.status_code == 400
    assert _upload(client, tok, "PS-202609-913", body=b"").status_code == 400
    assert _row("PS-202609-913")["status"] == "已匯出"


def test_signed_is_locked_and_not_directly_voidable(client, make_user):
    tok = _su(client, make_user, "pv2_su3")
    _insert_payslip("PS-202609-914", status="已匯出")
    _upload(client, tok, "PS-202609-914")
    assert client.put("/api/payslips/PS-202609-914", json=_payload(), headers=_auth(tok)).status_code == 409
    assert client.delete("/api/payslips/PS-202609-914", headers=_auth(tok)).status_code == 400
    assert _void(client, tok, "PS-202609-914").status_code == 409
    client.post("/api/payslips/PS-202609-914/export", headers=_auth(tok))   # 補印不可把狀態洗回已匯出
    assert _row("PS-202609-914")["status"] == "已簽回"
    assert client.post("/api/payslips/PS-202609-914/unsign", headers=_auth(tok)).status_code == 200
    assert _void(client, tok, "PS-202609-914").status_code == 200


def test_delete_last_signed_file_returns_to_exported(client, make_user):
    tok = _su(client, make_user, "pv2_su4")
    _insert_payslip("PS-202609-915", status="已匯出")
    _upload(client, tok, "PS-202609-915")
    fid = json.loads(_row("PS-202609-915")["signed_files_json"])[0]["id"]
    r = client.delete(f"/api/payslips/PS-202609-915/signed-files/{fid}", headers=_auth(tok))
    assert r.status_code == 200 and r.json()["status"] == "已匯出"
    assert _row("PS-202609-915")["signed_at"] == ""


# ── 出納付款 ─────────────────────────────────────────────────────────────────

@_NEEDS_ACCOUNTING
def test_mark_paid_needs_real_voucher_and_valid_date(client, make_user):
    tok = _su(client, make_user, "pv3_su1")
    _insert_payslip("PS-202609-921", status="已匯出")
    assert _pay(client, tok, "PS-202609-921").status_code == 409          # 未簽回
    _upload(client, tok, "PS-202609-921")
    assert _pay(client, tok, "PS-202609-921", date="2026/09/30").status_code == 400
    assert _pay(client, tok, "PS-202609-921", vno="").status_code == 400
    assert _pay(client, tok, "PS-202609-921", vno="NOPE-1").status_code == 400
    _voucher("20260929-902", voided="2026-09-29T00:00:00")
    assert _pay(client, tok, "PS-202609-921", vno="20260929-902").status_code == 400
    assert _row("PS-202609-921")["status"] == "已簽回"
    _voucher("20260929-901")
    assert _pay(client, tok, "PS-202609-921").status_code == 200
    row = _row("PS-202609-921")
    assert (row["status"], row["payment_date"], row["voucher_no"]) == ("已付款", "2026-09-30", "20260929-901")
    fid = json.loads(row["signed_files_json"])[0]["id"]
    assert client.delete(f"/api/payslips/PS-202609-921/signed-files/{fid}", headers=_auth(tok)).status_code == 409
    assert client.post("/api/payslips/PS-202609-921/unsign", headers=_auth(tok)).status_code == 409
    assert client.post("/api/payslips/PS-202609-921/unpay", headers=_auth(tok)).status_code == 200
    row = _row("PS-202609-921")
    assert row["status"] == "已簽回" and row["payment_date"] == "" and row["voucher_no"] == ""


@_NEEDS_ACCOUNTING
def test_mark_paid_refuses_and_says_so_without_accounting(client, make_user, monkeypatch):
    """反向控制：會計模組（voucher.by_no 提供者）不在 ⇒ 無法驗證傳票單號 ⇒ 拒絕並說明，狀態不變。"""
    tok = _su(client, make_user, "pv3_su2")
    _insert_payslip("PS-202609-922", status="已匯出")
    _upload(client, tok, "PS-202609-922")
    _voucher("20260929-903")
    orig = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda cap: None if cap == "voucher.by_no" else orig(cap))
    r = _pay(client, tok, "PS-202609-922", vno="20260929-903")
    assert r.status_code == 409 and "會計模組未安裝" in r.json()["detail"]
    assert _row("PS-202609-922")["status"] == "已簽回"


@_NEEDS_ACCOUNTING
def test_cashier_can_pay_but_plain_user_cannot(client, make_user):
    tok = _su(client, make_user, "pv3_su3")
    _insert_payslip("PS-202609-923", status="已匯出")
    _upload(client, tok, "PS-202609-923")
    _voucher("20260929-904")
    u, pw = make_user(username="pv3_plain", role="user", modules=[])
    assert _pay(client, _login(client, u, pw), "PS-202609-923", vno="20260929-904").status_code == 403
    c, pw = make_user(username="pv3_cash", role="user", modules=["cashier"])
    assert _pay(client, _login(client, c, pw), "PS-202609-923", vno="20260929-904").status_code == 200


# ── IP-103 出納佇列（M05）與 IP-9 報表成本（M08）──────────────────────────────

@_NEEDS_ARAP
def test_cashier_queue_lists_signed_only_and_hides_from_finance(client, make_user):
    tok = _su(client, make_user, "pv4_su1")
    _insert_payslip("PS-202609-931", status="已匯出")
    _insert_payslip("PS-202609-932", status="已匯出")
    _upload(client, tok, "PS-202609-931")
    q = client.get("/api/cashier/payslip-queue", headers=_auth(tok)).json()
    assert q["available"] and q["visible"] and [i["slipNo"] for i in q["items"]] == ["PS-202609-931"]
    assert "contractorIdNumber" not in json.dumps(q, ensure_ascii=False)          # 不外流個資欄位
    f, pw = make_user(username="pv4_fin", role="user", modules=["finance"])
    r = client.get("/api/cashier/payslip-queue", headers=_auth(_login(client, f, pw))).json()
    assert r["visible"] is False and r["items"] == []
    c, pw = make_user(username="pv4_cash", role="user", modules=["cashier"])
    assert client.get("/api/cashier/payslip-queue", headers=_auth(_login(client, c, pw))).json()["visible"] is True


@_NEEDS_ARAP
def test_cashier_queue_says_so_when_payroll_provider_missing(client, make_user, monkeypatch):
    """反向控制：薪資獎金提供者不在 ⇒ 出納頁其餘照常，勞報單子頁籤明說（不是空清單）。"""
    tok = _su(client, make_user, "pv4_su2")
    orig = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda cap: None if cap == "payslip.payables" else orig(cap))
    r = client.get("/api/cashier/payslip-queue", headers=_auth(tok)).json()
    assert r["available"] is False and "薪資獎金模組未安裝" in r["notice"] and r["items"] == []


@_NEEDS_ACCOUNTING
@_NEEDS_ANALYTICS
def test_cost_report_counts_paid_by_payment_month_gross(client, make_user):
    from modules.analytics.api.reports import _collect_expenses
    tok = _su(client, make_user, "pv5_su1")
    _voucher("20260929-905")
    for no, gross in (("PS-202609-941", 30000), ("PS-202609-942", 10000), ("PS-202609-943", 5000)):
        _insert_payslip(no, status="已匯出", gross=gross)
        _upload(client, tok, no)
    assert _pay(client, tok, "PS-202609-941", date="2026-10-05", vno="20260929-905").status_code == 200
    assert _pay(client, tok, "PS-202609-943", date="2026-10-06", vno="20260929-905").status_code == 200
    client.post("/api/payslips/PS-202609-943/unpay", headers=_auth(tok))     # 付款後退回 ⇒ 不算
    for basis in ("accrual", "cash"):
        res = _collect_expenses(2026, None, basis)
        by = {m["month"]: m for m in res["monthly"]}
        assert by["2026-10"]["other"] == 30000 and by["2026-09"]["other"] == 0 and by["2026-08"]["other"] == 0
        descs = [d["desc"] for d in res["details"]["other"] if d.get("category") == "勞報單"]
        assert any("PS-202609-941" in d for d in descs)
        assert not any("PS-202609-942" in d or "PS-202609-943" in d for d in descs)   # 只簽回／退回付款 ⇒ 不算
    assert _collect_expenses(2026, 999999, "accrual")["totals"]["other"] == 0          # 無案件歸屬 ⇒ 篩部門時不含


@_NEEDS_ANALYTICS
def test_cost_report_still_works_without_payslip_provider(client, make_user, monkeypatch):
    """反向控制：勞報單提供者不在 ⇒ 報表少這一類、其餘照常，不丟例外。"""
    from modules.analytics.api.reports import _collect_expenses
    orig = registry.providers
    monkeypatch.setattr(registry, "providers",
                        lambda cap: {k: v for k, v in orig(cap).items() if k != "payslip"} if cap == "expense.entries"
                        else orig(cap))
    assert "monthly" in _collect_expenses(2026, None, "accrual")


# ── migration ────────────────────────────────────────────────────────────────

def test_migration_is_idempotent_and_reports_missing_table():
    import importlib
    import sqlite3
    m = importlib.import_module("modules.payroll.migrations.0001_payslip_void_signed_paid")
    c = sqlite3.connect(":memory:")
    assert "payslips 表不存在" in m.up(c)                      # 表不在 ⇒ 回原因字串（未完成），不建表
    c.execute("CREATE TABLE payslips (id INTEGER PRIMARY KEY, slip_no TEXT)")
    assert m.up(c) is None and m.up(c) is None                # 兩次都成功、不重複加欄
    cols = {r[1] for r in c.execute("PRAGMA table_info(payslips)")}
    assert {"voided_at", "signed_files_json", "payment_date", "voucher_no", "paid_at"} <= cols
