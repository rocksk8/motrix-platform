# -*- coding: utf-8 -*-
"""採購單廠商收款帳戶（第 47 班，PO-VENDOR-BANK-GAP-T47 選項 A）：建立採購單時可填銀行／帳號／戶名；出納看得到這份快照（優先於任何員工帳戶）；
清單只給末四碼；帳號格式與長度在後端檢查（前端另有同一組檢查）；非金額角色看不到。"""
import json

import pytest

from modules.case.tests.test_queue_detail_real_forms_2026_10_07 import (  # noqa: F401  (world 是 fixture)
    DOCS, LINES, SENT, _approve_row, _db, _pending, world)
from tests._requires import requires_module

pytestmark = requires_module("case", "額外支出在 M01")

_MAKE_USER_DEFAULT_ROLE = "superadmin"


def _post(client, w, **payee):
    data = dict(DOCS["purchase_order"]["data"], applicant=w["user"], dept=w["dept"], req_date="2031-06-01")
    body = {"kind": "purchase_order", "data": data, "lines": LINES, "departmentId": w["dept"], "expenseDate": "2031-06-01", **payee}
    return client.post(SENT, headers=w["h"], json=body)


def _row(eid):
    c = _db()
    try:
        return dict(c.execute("SELECT * FROM case_extra_expenses WHERE id=?", (eid,)).fetchone())
    finally:
        c.close()


def test_po_stores_the_vendor_bank_snapshot_and_cleans_the_account(client, world):
    r = _post(client, world, payeeType="vendor", payeeName="甲廠商", payeeBank="玉山銀行 台中分行", payeeAccount="1234-5678 9012")
    assert r.status_code == 201, r.text
    row = _row(r.json()["id"])
    assert (row["payee_type"], row["payee_name"], row["payee_bank"], row["payee_account"]) == ("vendor", "甲廠商", "玉山銀行 台中分行", "123456789012")


def test_cashier_sees_the_entered_snapshot_not_the_requesters_profile_and_list_is_masked(client, world):
    eid = _post(client, world, payeeType="vendor", payeeName="甲廠商", payeeBank="玉山銀行 台中分行", payeeAccount="123456789012").json()["id"]
    _approve_row(eid)
    got = _pending(client, world["h"])[str(eid)]
    assert got["payee"] == "甲廠商" and got["payeeUsername"] == "" and got["payeeNote"] == "", "有帳戶資料 ⇒ 不再顯示『未收集』警示"
    assert "123456789012" not in json.dumps(got, ensure_ascii=False) and got["payeeBank"].endswith("9012"), "清單只給遮罩（末四碼）"
    r = client.get("/api/cashier/pending-payables/case/%d/payee-bank" % eid, headers=world["h"])
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["source"], b["bank"], b["account"], b["payeeName"]) == ("form", "玉山銀行 台中分行", "123456789012", "甲廠商")


def test_po_without_bank_data_keeps_the_warning(client, world):
    from modules.case.payables import PAYEE_NOTE
    eid = _post(client, world).json()["id"]
    _approve_row(eid)
    assert _pending(client, world["h"])[str(eid)]["payeeNote"] == PAYEE_NOTE


@pytest.mark.parametrize("account,ok", [("12345", True), ("1" * 20, True), ("1234", False), ("1" * 21, False), ("12AB5678", False), ("１２３４５６７８", False)])
def test_account_must_be_5_to_20_digits(client, world, account, ok):
    r = _post(client, world, payeeType="vendor", payeeName="甲", payeeBank="玉山銀行", payeeAccount=account)
    assert (r.status_code == 201) is ok, (account, r.status_code, r.text)
    if not ok:
        assert r.status_code == 400 and "數字" in r.json()["detail"]


def test_account_requires_a_bank_name_on_purchase_orders_and_lengths_are_limited(client, world):
    r = _post(client, world, payeeType="vendor", payeeName="甲", payeeBank="", payeeAccount="123456789")
    assert r.status_code == 400 and "銀行" in r.json()["detail"]
    assert _post(client, world, payeeType="vendor", payeeName="甲" * 61, payeeBank="玉山銀行", payeeAccount="123456789").status_code == 400
    assert _post(client, world, payeeType="vendor", payeeName="甲", payeeBank="銀" * 61, payeeAccount="123456789").status_code == 400


def test_patch_draft_updates_and_clears_the_snapshot(client, world):
    eid = _post(client, world, payeeType="vendor", payeeName="甲", payeeBank="玉山銀行", payeeAccount="111111").json()["id"]
    data = dict(DOCS["purchase_order"]["data"], applicant=world["user"], dept=world["dept"], req_date="2031-06-01")
    base = {"kind": "purchase_order", "data": data, "lines": LINES, "departmentId": world["dept"], "expenseDate": "2031-06-01"}
    r = client.patch(SENT + "/%d" % eid, headers=world["h"], json={**base, "payeeType": "vendor", "payeeName": "乙", "payeeBank": "台新銀行", "payeeAccount": "222-222"})
    assert r.status_code == 200, r.text
    assert (_row(eid)["payee_name"], _row(eid)["payee_bank"], _row(eid)["payee_account"]) == ("乙", "台新銀行", "222222")
    assert client.patch(SENT + "/%d" % eid, headers=world["h"], json={**base, "payeeAccount": "abc"}).status_code == 400
    assert client.patch(SENT + "/%d" % eid, headers=world["h"], json=base).status_code == 200
    assert _row(eid)["payee_account"] == ""


def test_other_kinds_only_get_the_format_check_no_new_required_fields(client, world):
    data = {"place": "國內", "city": "台中", "period": {"from": "2031-06-03", "to": "2031-06-05"}, "pay_date": "2031-06-30", "remark": "x",
            "applicant": world["user"], "dept": world["dept"], "req_date": "2031-06-01", "cost_dept": world["dept"]}
    lines = [{"category": "其他", "summary": "車票", "qty": 1, "unitCost": 100, "invoiceNo": "AB12345678"}]
    base = {"kind": "travel", "data": data, "lines": lines, "departmentId": world["dept"], "expenseDate": "2031-06-01"}
    assert client.post(SENT, headers=world["h"], json={**base, "payeeType": "employee", "payeeAccount": "987654321"}).status_code == 201
    assert client.post(SENT, headers=world["h"], json={**base, "payeeType": "employee", "payeeAccount": "9876x"}).status_code == 400


def test_non_money_viewer_gets_no_payee_data_in_the_case_list_or_payee_bank(client, world, make_user):
    """案件列表對非金額角色逐列遮蔽（不含收款人欄）；出納收款人銀行資料端點需要付款權限。"""
    c = _db()
    try:
        c.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag, sales_person)"
                  " VALUES ('MQ-POB-1','已送出','客','案',1,1,'{}','2031-01-01T00:00:00','2031-01-01T00:00:00','已成案','pob_viewer')")
        c.commit()
    finally:
        c.close()
    r = client.post("/api/quotations/MQ-POB-1/extra-expenses", headers=world["h"], json={
        "kind": "purchase_order", "data": dict(DOCS["purchase_order"]["data"], applicant=world["user"], dept=world["dept"], req_date="2031-06-01"),
        "lines": LINES, "departmentId": world["dept"], "expenseDate": "2031-06-01", "payeeType": "vendor", "payeeName": "甲", "payeeBank": "玉山銀行", "payeeAccount": "123456789"})
    assert r.status_code == 201, r.text
    eid = r.json()["id"]
    _approve_row(eid)
    u, p = make_user(username="pob_viewer", role="user", modules=["case_manage"], legacy_finance_flag=False)
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    lst = client.get("/api/quotations/MQ-POB-1/extra-expenses", headers=h)
    assert lst.status_code == 200, lst.text
    assert "123456789" not in lst.text and "玉山銀行" not in lst.text, "非金額角色看不到收款帳戶"
    assert client.get("/api/cashier/pending-payables/case/%d/payee-bank" % eid, headers=h).status_code in (401, 403)


# ── 使用者裁示 2026-10-08：完整帳號只給財務角色＋最高管理者（FULL_ACCOUNT_STRICT，與叫料匯款同規則）────────────────
# 讀碼實測：payee-bank 端點本來就以 `_can_pay`（＝has_cashier_access：財務角色＋superadmin）把關，無出納權限的管理員直接 403，
# 所以『管理員看到完整帳號』的疑慮並不存在；嚴格旗標補上的是『先稽核才給值（寫不進稽核 ⇒ 不回帳號）』與 no-store，並與叫料匯款一致。

def _login(client, u, p):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _audits(eid):
    c = _db()
    try:
        return [dict(r) for r in c.execute("SELECT username, target_label FROM audit_log WHERE action='cashier.payee_bank_view' AND target_id=? ORDER BY id", (str(eid),)).fetchall()]
    finally:
        c.close()


def test_full_account_only_for_finance_and_superadmin_admin_without_cashier_gets_403(client, world, make_user):
    eid = _post(client, world, payeeType="vendor", payeeName="甲廠商", payeeBank="玉山銀行", payeeAccount="123456789012").json()["id"]
    _approve_row(eid)
    url = "/api/cashier/pending-payables/case/%d/payee-bank" % eid
    adm = _login(client, *make_user(username="fas_admin", role="admin", legacy_finance_flag=False))
    fin = _login(client, *make_user(username="fas_fin", role="finance"))
    r = client.get(url, headers=adm)
    assert r.status_code == 403 and "123456789012" not in r.text
    for h in (fin, world["h"]):
        rr = client.get(url, headers=h)
        assert rr.status_code == 200 and rr.json()["account"] == "123456789012" and rr.json()["bank"] == "玉山銀行"
        assert rr.headers.get("cache-control") == "no-store", "嚴格提供者：回應不可被快取"
    log = _audits(eid)
    assert [a["username"] for a in log] == ["fas_fin", world["user"]], "每次查看都留稽核（被擋的 403 不算查看）"
    lst = client.get("/api/cashier/pending-payables", headers=world["h"]).json()["items"]
    mine = next(i for i in lst if i["source"] == "case" and i["key"] == str(eid))
    assert "123456789012" not in json.dumps(mine, ensure_ascii=False) and mine["payeeBank"].endswith("9012"), "清單永遠只給末四碼"


def test_audit_failure_means_no_account_is_returned(client, world, monkeypatch):
    eid = _post(client, world, payeeType="vendor", payeeName="甲", payeeBank="玉山銀行", payeeAccount="123456789012").json()["id"]
    _approve_row(eid)
    from modules.arap.api import cashier as C

    def boom(*a, **k):
        raise RuntimeError("audit down")
    monkeypatch.setattr(C, "_audit_raising", boom)
    with pytest.raises(RuntimeError):                                  # 例外往外傳（正式機＝500）：沒有任何回應內容帶出帳號
        client.get("/api/cashier/pending-payables/case/%d/payee-bank" % eid, headers=world["h"])
