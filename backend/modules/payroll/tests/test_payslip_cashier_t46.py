# -*- coding: utf-8 -*-
"""第 46 班 P2：勞報單進出納「待付款申請」（IP-100 `payroll_payslip`）——已核准即可付款（Q4）、出納端權限＝財務角色＋最高管理者（Q1）、
付款唯一實作、unpay 退回推導、不進行事曆（Q7）、F2 欄位不外洩、預定付款日。"""
import json

import pytest

from core import source_tree
from modules.payroll.api import payslips as payslips_api
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _auth, _login
from modules.payroll.tests.test_payslip_void_signed_paid_2026_09_29 import _voucher

pytestmark = [pytest.mark.skipif(not source_tree.module_installed("modules/arap/"), reason="出納端點在應收應付（M05）"),
              pytest.mark.skipif(not source_tree.module_installed("modules/accounting/"), reason="傳票單號驗證在會計（M06）")]

_MAKE_USER_DEFAULT_ROLE = "superadmin"
SECRET_ID, SECRET_ADDR, SECRET_ACCT = "A123456789", "台北市某某路 1 號", "28881234567890"


@pytest.fixture(autouse=True)
def _archive_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(payslips_api, "_archive_dir", lambda: str(tmp_path / "payslip_archive"))


def _x(sql, args=()):
    import db
    c = db.get_db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def _row(no):
    import db
    c = db.get_db()
    try:
        return dict(c.execute("SELECT * FROM payslips WHERE slip_no=?", (no,)).fetchone())
    finally:
        c.close()


def _slip(no, status="已核准", net=18000, signed=False, exported=0, by="ps46c_req"):
    data = {"slipNo": no, "contractorName": "測試承攬人", "idNumber": SECRET_ID, "address": SECRET_ADDR, "bankAccountNumber": SECRET_ACCT,
            "bankCode": "812", "bankName": "台新", "bankAccountName": "測試承攬人"}
    files = json.dumps([{"id": "0123456789abcdef", "filename": "s.pdf", "ext": ".pdf"}]) if signed else "[]"
    _x("INSERT INTO payslips (slip_no, contractor_id, contractor_name, income_type, gross_amount, tax_withheld, nhi_supplement, net_amount, payment_method,"
       " slip_date, status, tax_rules_version, data_json, created_by, created_at, updated_at, signed_files_json, export_count, approval_json, approved_at)"
       " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
       (no, None, "測試承攬人", "9A", 20000, 2000, 0, net, "匯款", "2031-06-01", status, "2031", json.dumps(data, ensure_ascii=False), by,
        "2031-06-01T00:00:00", "2031-06-02T00:00:00", files, exported, json.dumps({"requestedBy": by}), "2031-06-02T00:00:00"))


def _who(client, make_user, name, role="finance", modules=None):
    u, p = make_user(username=name, role=role, modules=modules, legacy_finance_flag=False)      # 保留「惰性 cashier 勾選」的一般帳號（不要被換成財務角色）
    return _auth(_login(client, u, p))


def _pending(client, h):
    r = client.get("/api/cashier/pending-payables", headers=h)
    assert r.status_code == 200, r.text
    return [i for i in r.json()["items"] if i["source"] == "payroll_payslip"]


def _pay(client, h, no, date="2031-06-10", vno="20310601-001"):
    return client.post("/api/cashier/pending-payables/payroll_payslip/%s/pay" % no, headers=h, json={"paidDate": date, "voucherNo": vno})


def test_listing_statuses_and_no_personal_data(client, make_user):
    fin = _who(client, make_user, "ps46c_fin")
    for i, st in enumerate(("草稿", "待審核", "已核准", "已匯出", "已簽回", "已付款", "已作廢"), 1):
        _slip("PS-203106-%03d" % i, status=st)
    got = {i["key"]: i for i in _pending(client, fin)}
    assert set(got) == {"PS-203106-003", "PS-203106-004", "PS-203106-005"}, sorted(got)
    blob = json.dumps(list(got.values()), ensure_ascii=False)
    for secret in (SECRET_ID, SECRET_ADDR, SECRET_ACCT, "28881234"):
        assert secret not in blob, secret
    it = got["PS-203106-003"]
    assert it["kind"] == "payslip" and it["needsVoucherNo"] is True and it["amount"] == 18000.0 and it["signedBack"] is False
    assert got["PS-203106-005"]["signedBack"] is True


def test_approved_payslip_can_be_paid_without_export_or_signed_file(client, make_user):
    fin = _who(client, make_user, "ps46c_fin")
    _slip("PS-203106-010", status="已核准")
    _voucher("20310601-001")
    r = _pay(client, fin, "PS-203106-010")
    assert r.status_code == 200, r.text
    row = _row("PS-203106-010")
    assert (row["status"], row["payment_date"], row["voucher_no"]) == ("已付款", "2031-06-10", "20310601-001")
    assert _pay(client, fin, "PS-203106-010").status_code == 409, "不可重複付款"
    assert [i for i in _pending(client, fin) if i["key"] == "PS-203106-010"] == [], "付款後離開待付款"


def test_pay_validations_and_unpayable_states(client, make_user):
    fin = _who(client, make_user, "ps46c_fin")
    for no, st in (("PS-203106-021", "草稿"), ("PS-203106-022", "待審核"), ("PS-203106-023", "已作廢")):
        _slip(no, status=st)
        assert _pay(client, fin, no).status_code in (404, 409), no
    _slip("PS-203106-024")
    assert _pay(client, fin, "PS-203106-024", vno="").status_code == 400, "傳票單號必填"
    assert _pay(client, fin, "PS-203106-024", vno="NOPE-1").status_code == 400, "傳票要真實存在"
    assert _pay(client, fin, "PS-203106-024", date="2031/06/10").status_code == 400
    assert _row("PS-203106-024")["status"] == "已核准"


def test_permissions_finance_and_superadmin_only_not_cashier_module_or_others(client, make_user):
    """Q1：出納端權限＝財務角色＋最高管理者；只勾 cashier 模組的一般帳號、admin 都不行（原本 payslips.py 認 cashier 模組勾選）。"""
    _slip("PS-203106-030")
    _voucher("20310601-001")
    legacy = _who(client, make_user, "ps46c_cash", role="user", modules=["cashier"])
    admin = _who(client, make_user, "ps46c_adm", role="admin")
    plain = _who(client, make_user, "ps46c_plain", role="user")
    for h in (legacy, admin, plain):
        assert client.post("/api/payslips/PS-203106-030/mark-paid", headers=h, json={"payment_date": "2031-06-10", "voucher_no": "20310601-001"}).status_code in (401, 403)
        assert client.post("/api/payslips/PS-203106-030/unpay", headers=h).status_code in (401, 403)
        assert _pay(client, h, "PS-203106-030").status_code in (401, 403)
    assert _row("PS-203106-030")["status"] == "已核准"
    sa = _who(client, make_user, "ps46c_sa", role="superadmin")
    assert client.post("/api/payslips/PS-203106-030/mark-paid", headers=sa, json={"payment_date": "2031-06-10", "voucher_no": "20310601-001"}).status_code == 200
    fin = _who(client, make_user, "ps46c_fin")
    assert client.post("/api/payslips/PS-203106-030/unpay", headers=fin).status_code == 200, "財務角色可退回付款"


def test_signed_file_view_needs_finance_or_superadmin(client, make_user, tmp_path):
    _slip("PS-203106-040", status="已簽回", signed=True)
    plain = _who(client, make_user, "ps46c_plain", role="user", modules=["cashier"])
    assert client.get("/api/payslips/PS-203106-040/signed-files/0123456789abcdef", headers=plain).status_code == 403
    fin = _who(client, make_user, "ps46c_fin")
    assert client.get("/api/payslips/PS-203106-040/signed-files/0123456789abcdef", headers=fin).status_code in (200, 404), "財務角色通過權限（實體檔不存在 ⇒ 404）"


def test_legacy_queue_visible_to_finance_not_to_cashier_module_only(client, make_user):
    _slip("PS-203106-050", status="已簽回", signed=True)
    fin = _who(client, make_user, "ps46c_fin")
    assert client.get("/api/cashier/payslip-queue", headers=fin).json().get("visible") is True
    legacy = _who(client, make_user, "ps46c_cash", role="user", modules=["cashier"])
    r = client.get("/api/cashier/payslip-queue", headers=legacy)
    assert r.status_code == 403 or r.json().get("visible") is False


def test_unpay_returns_to_the_status_before_payment(client, make_user):
    fin = _who(client, make_user, "ps46c_fin")
    _voucher("20310601-001")
    cases = (("PS-203106-061", dict(status="已核准"), "已核准"),
             ("PS-203106-062", dict(status="已匯出", exported=1), "已匯出"),
             ("PS-203106-063", dict(status="已簽回", signed=True, exported=1), "已簽回"))
    for no, kw, back in cases:
        _slip(no, **kw)
        assert _pay(client, fin, no).status_code == 200
        r = client.post("/api/payslips/%s/unpay" % no, headers=fin)
        assert r.status_code == 200 and r.json()["status"] == back, (no, r.text)
        row = _row(no)
        assert row["status"] == back and row["payment_date"] == "" and row["voucher_no"] == ""


def test_no_calendar_events_for_payslips_at_all(client, make_user, monkeypatch):
    """Q7：勞報單不進行事曆——付款、改預定日都不呼叫任何 push_event_*（反向控制見 payable_due_core.sync_event 的來源開關）。"""
    import helpers
    calls = []
    for name in ("push_event_upsert_for_module", "push_event_delete_for_module", "push_event_for_module"):
        monkeypatch.setattr(helpers, name, lambda *a, _n=name, **k: calls.append(_n))
    from modules.arap.api import cashier
    from tests import _fake_gcal
    _fake_gcal.sync_spawn(monkeypatch, cashier)
    monkeypatch.setattr(cashier, "push_event_for_module", lambda *a, **k: calls.append("cashier.push_event_for_module"))
    monkeypatch.setattr(cashier, "push_event_delete_for_module", lambda *a, **k: calls.append("cashier.push_event_delete_for_module"))
    fin = _who(client, make_user, "ps46c_fin")
    _slip("PS-203106-070")
    _voucher("20310601-001")
    assert client.patch("/api/cashier/pending-payables/payroll_payslip/PS-203106-070/planned-pay-date", headers=fin, json={"plannedPayDate": "2031-06-20"}).status_code == 200
    assert _pay(client, fin, "PS-203106-070").status_code == 200
    assert calls == [], calls


def test_planned_pay_date_set_clear_and_history_after_paid(client, make_user):
    fin = _who(client, make_user, "ps46c_fin")
    _slip("PS-203106-080")
    _voucher("20310601-001")
    url = "/api/cashier/pending-payables/payroll_payslip/PS-203106-080/planned-pay-date"
    assert client.patch(url, headers=fin, json={"plannedPayDate": "2031-06-20"}).status_code == 200
    assert _row("PS-203106-080")["planned_pay_date"] == "2031-06-20"
    assert [i["plannedPayDate"] for i in _pending(client, fin)] == ["2031-06-20"]
    assert client.patch(url, headers=fin, json={"plannedPayDate": ""}).status_code == 200 and _row("PS-203106-080")["planned_pay_date"] == ""
    assert client.patch(url, headers=fin, json={"plannedPayDate": "2031-02-30"}).status_code == 400
    client.patch(url, headers=fin, json={"plannedPayDate": "2031-06-20"})
    assert _pay(client, fin, "PS-203106-080").status_code == 200
    r = client.patch(url, headers=fin, json={"plannedPayDate": "2031-07-01"})
    assert r.status_code == 409 and _row("PS-203106-080")["planned_pay_date"] == "2031-06-20"


def test_paid_notifies_the_requester_without_amount(client, make_user):
    make_user(username="ps46c_req", role="user")
    fin = _who(client, make_user, "ps46c_fin")
    _slip("PS-203106-090")
    _voucher("20310601-001")
    assert _pay(client, fin, "PS-203106-090").status_code == 200
    import db
    c = db.get_db()
    try:
        notes = [dict(r) for r in c.execute("SELECT * FROM notifications WHERE username='ps46c_req' AND type='payslip_paid'")]
    finally:
        c.close()
    assert len(notes) == 1 and "PS-203106-090" in notes[0]["message"] and "18000" not in notes[0]["message"] and "NT$" not in notes[0]["message"]


def test_remit_link_accepts_approved_and_unmark_goes_back_by_derivation(client, make_user):
    """Q13：匯款單關聯勞報單放寬為已核准／已匯出／已簽回；取消匯款退回付款前最近的狀態。"""
    import db
    from modules.payroll import remit_link as RL
    _slip("PS-203106-100", status="已核准")
    import db as _db
    cn = _db.get_db()
    try:
        cid = cn.execute("INSERT INTO contractors(name, id_number) VALUES (?,?)", ("測試承攬人", "B234567890")).lastrowid
        cn.commit()
    finally:
        cn.close()
    _x("UPDATE payslips SET contractor_id=? WHERE slip_no='PS-203106-100'", (cid,))
    c = db.get_db()
    try:
        assert [x["slipNo"] for x in RL.candidates(c, cid)] == ["PS-203106-100"]
        assert RL.mark_paid(c, ["PS-203106-100"], "PV-T46-1", "2031-06-10", "t") == 1
        c.commit()
        assert RL.unmark_paid(c, "PV-T46-1") == 1
        c.commit()
        assert c.execute("SELECT status FROM payslips WHERE slip_no='PS-203106-100'").fetchone()["status"] == "已核准"
    finally:
        c.close()


def test_payslips_api_has_no_cashier_module_checks():
    """靜態守門（設計 §4「權限」）：勞報單端點不得再用 `user_has_module(..., "cashier")` 判斷出納權限。"""
    import re
    from pathlib import Path
    src = (Path(payslips_api.__file__)).read_text(encoding="utf-8")
    assert not re.search(r"user_has_module\([^)]*cashier", src), "出納權限一律走 has_cashier_access／has_finance_access"
