# -*- coding: utf-8 -*-
"""第 48 班：新採購單缺廠商收款帳戶 ⇒ 擋出納登錄付款（使用者 Q2）。預設關；只擋切換時間點之後建立的採購單；舊單與其他單據類型不受影響。
設計：docs/platform/plans/PO-BANK-BLOCK-T48.md"""
import json
from datetime import date, datetime, timedelta

import pytest

from modules.case.tests.test_queue_detail_real_forms_2026_10_07 import (  # noqa: F401  (world 是 fixture)
    DOCS, LINES, SENT, _approve_row, _db, _pending, world)
from tests._requires import requires_module

pytestmark = requires_module("case", "額外支出在 M01")

_MAKE_USER_DEFAULT_ROLE = "superadmin"
URL = "/api/extra-expenses/po-bank-block"
PAY = {"paidDate": "2026-10-09", "payTerms": "月結30天", "remitDate": "2026-10-09"}


def _po(client, w, **payee):
    data = dict(DOCS["purchase_order"]["data"], applicant=w["user"], dept=w["dept"], req_date="2031-06-01")
    body = {"kind": "purchase_order", "data": data, "lines": LINES, "departmentId": w["dept"], "expenseDate": "2031-06-01", **payee}
    r = client.post(SENT, headers=w["h"], json=body)
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    _approve_row(eid)
    return eid


def _sql(sql, args=()):
    c = _db()
    try:
        c.execute(sql, args)
        c.commit()
    finally:
        c.close()


def _paid(eid):
    c = _db()
    try:
        return (c.execute("SELECT paid_date FROM case_extra_expenses WHERE id=?", (eid,)).fetchone()["paid_date"] or "")
    finally:
        c.close()


def _enable(client, w, since=None):
    body = {"enabled": True}
    if since:
        body["since"] = since
    r = client.put(URL, headers=w["h"], json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _pay(client, w, eid):
    return client.post("/api/cashier/pending-payables/case/%d/pay" % eid, headers=w["h"], json=PAY)


@pytest.fixture(autouse=True)
def _reset():
    yield
    _sql("DELETE FROM system_settings WHERE key='po_bank_block_since'")


def test_flag_off_changes_nothing(client, world):
    eid = _po(client, world)                                          # 沒填銀行資料
    got = _pending(client, world["h"])[str(eid)]
    assert got["blocked"] is False and got["blockReason"] == ""
    assert _pay(client, world, eid).status_code == 200 and _paid(eid) == "2026-10-09"


def test_new_po_without_bank_data_is_blocked_old_po_is_not(client, world):
    old = _po(client, world)
    new = _po(client, world)
    _sql("UPDATE case_extra_expenses SET created_at='2020-01-01T00:00:00' WHERE id=?", (old,))     # 舊單：切換時間點之前建立
    _enable(client, world, since=date.today().isoformat())
    p = _pending(client, world["h"])
    assert p[str(old)]["blocked"] is False and p[str(new)]["blocked"] is True
    assert "缺廠商收款帳戶" in p[str(new)]["blockReason"] and "自然人" in p[str(new)]["blockReason"], "原因欄＋自然人提示"
    assert p[str(new)]["payeeNote"], "原有的『資料未收集』警示照舊"
    r = _pay(client, world, new)
    assert r.status_code == 409 and "缺廠商收款帳戶" in r.json()["detail"] and _paid(new) == "", "擋下且沒寫任何東西"
    assert _pay(client, world, old).status_code == 200 and _paid(old) == "2026-10-09", "舊單照常付款"


def test_missing_only_the_account_or_only_the_bank_is_still_blocked_and_complete_data_can_pay(client, world):
    _enable(client, world, since=date.today().isoformat())
    a = _po(client, world, payeeType="vendor", payeeName="甲", payeeBank="玉山銀行", payeeAccount="123456789")
    for col in ("payee_account", "payee_bank"):                       # 後端建立時要求『有帳號必有銀行』；缺其中之一的單用 SQL 造（舊資料／變更申請殘留）
        _sql("UPDATE case_extra_expenses SET %s='' WHERE id=?" % col, (a,))
        assert _pending(client, world["h"])[str(a)]["blocked"] is True, col
        assert _pay(client, world, a).status_code == 409
        _sql("UPDATE case_extra_expenses SET payee_bank='玉山銀行', payee_account='123456789' WHERE id=?", (a,))
        assert _pending(client, world["h"])[str(a)]["blocked"] is False
    assert _pay(client, world, a).status_code == 200 and _paid(a) == "2026-10-09"


def test_filling_the_bank_data_later_unblocks_the_same_po(client, world):
    """補資料的路是第 47 班既有的變更申請；核准後 payee_* 生效。這裡直接模擬『生效後』。"""
    _enable(client, world, since=date.today().isoformat())
    eid = _po(client, world)
    assert _pay(client, world, eid).status_code == 409
    _sql("UPDATE case_extra_expenses SET payee_type='vendor', payee_name='甲', payee_bank='玉山銀行 台中分行', payee_account='123456789012' WHERE id=?", (eid,))
    assert _pending(client, world["h"])[str(eid)]["blocked"] is False
    assert _pay(client, world, eid).status_code == 200


def test_other_document_kinds_and_non_vendor_payees_are_never_blocked(client, world):
    _enable(client, world, since=date.today().isoformat())
    eid = _po(client, world)
    _sql("UPDATE case_extra_expenses SET kind='petty_cash' WHERE id=?", (eid,))
    assert _pending(client, world["h"])[str(eid)]["blocked"] is False
    _sql("UPDATE case_extra_expenses SET kind='purchase_order', payee_type='employee' WHERE id=?", (eid,))
    assert _pending(client, world["h"])[str(eid)]["blocked"] is False


def test_switch_endpoint_authz_validation_status_and_audit(client, world, make_user):
    fin, fp = make_user(username="pb_fin", role="finance")
    fh = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": fin, "password": fp}).json()["token"]}
    assert client.put(URL, headers=fh, json={"enabled": True}).status_code == 403, "只有最高管理者能改"
    assert client.get(URL, headers=fh).status_code == 200, "財務角色可以看狀態"
    assert client.put(URL, headers=world["h"], json={"enabled": "yes"}).status_code == 422
    assert client.put(URL, headers=world["h"], json={"enabled": True, "since": "not-a-date"}).status_code == 422
    future = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    assert client.put(URL, headers=world["h"], json={"enabled": True, "since": future}).status_code == 422
    assert client.get(URL, headers=world["h"]).json() == {"enabled": False, "since": "", "blockedPending": 0}
    eid = _po(client, world)
    out = _enable(client, world)                                       # 沒給 since ⇒ 現在
    assert out["enabled"] is True and out["since"][:10] == date.today().isoformat()
    _sql("UPDATE case_extra_expenses SET created_at=? WHERE id=?", ((datetime.now() + timedelta(seconds=1)).isoformat(timespec="seconds"), eid))
    st = client.get(URL, headers=world["h"]).json()
    assert st["enabled"] is True and st["blockedPending"] == 1
    assert client.put(URL, headers=world["h"], json={"enabled": False}).json() == {"ok": True, "enabled": False, "since": ""}
    c = _db()
    try:
        rows = [dict(r) for r in c.execute("SELECT * FROM audit_log WHERE action='settings.po_bank_block.update' ORDER BY id")]
    finally:
        c.close()
    assert len(rows) == 2 and json.loads(rows[0]["detail"])["old"] == "" and json.loads(rows[1]["detail"])["new"] == ""
