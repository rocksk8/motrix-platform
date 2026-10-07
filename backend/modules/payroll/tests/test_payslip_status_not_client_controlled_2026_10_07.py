# -*- coding: utf-8 -*-
"""勞報單狀態不可由前端指定（2026-10-07 快修）。

原本 `POST /api/payslips`（建立）與 `PUT /api/payslips/{no}`（修改）把請求 `data.status` 原樣寫進 `payslips.status`：
最高管理者（唯一能呼叫者）可繞過「匯出 → 簽回 → 出納付款」的流程，直接把單據寫成已簽回（進出納待付款、總帳應付分錄）或已付款。
狀態只應由匯出／簽回／付款／作廢等專用端點改變。反向控制：把兩處改回 `d.get("status", "草稿")` ⇒ 本檔必須紅。"""
import pytest

from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _auth, _insert_payslip, _login, _payload

_MAKE_USER_DEFAULT_ROLE = "superadmin"


def _status(no):
    import db
    c = db.get_db()
    try:
        return c.execute("SELECT status FROM payslips WHERE slip_no=?", (no,)).fetchone()["status"]
    finally:
        c.close()


@pytest.mark.parametrize("n,wanted", list(enumerate(["已付款", "已簽回", "已匯出", "已作廢", "亂寫"], 1)))
def test_put_never_changes_status_from_the_request(client, make_user, n, wanted):
    u, p = make_user(username="psfix_su_%d" % n, role="superadmin")
    h = _auth(_login(client, u, p))
    no = "PS-203102-%03d" % n
    _insert_payslip(no, status="草稿")
    body = _payload()
    body["data"]["status"] = wanted
    assert client.put("/api/payslips/%s" % no, json=body, headers=h).status_code == 200
    assert _status(no) == "草稿"


def test_create_always_starts_as_draft(client, make_user):
    u, p = make_user(username="psfix_su_c", role="superadmin")
    h = _auth(_login(client, u, p))
    body = _payload()
    body["data"]["status"] = "已付款"
    r = client.post("/api/payslips", json=body, headers=h)
    assert r.status_code == 201, r.text
    assert _status(r.json()["slip_no"]) == "草稿"
    assert not [x for x in client.get("/api/payslips", headers=h).json()["items"] if x["status"] == "已付款"]


def test_put_keeps_the_real_status_of_a_locked_slip_out_of_reach(client, make_user):
    """已匯出以後 PUT 本來就 409（鎖定），狀態不受影響——正對照：鎖仍在。"""
    u, p = make_user(username="psfix_su_l", role="superadmin")
    h = _auth(_login(client, u, p))
    _insert_payslip("PS-203102-901", status="已匯出")
    body = _payload()
    body["data"]["status"] = "已付款"
    assert client.put("/api/payslips/PS-203102-901", json=body, headers=h).status_code == 409
    assert _status("PS-203102-901") == "已匯出"


def test_client_status_is_not_kept_in_the_stored_data_blob(client, make_user):
    """第 45 班稽核 S5：data_json 也不留前端送來的 status（GET 的 data.status 不會顯示被偽造的值）；欄位 status 仍是真實狀態。"""
    u, p = make_user(username="psfix_su_blob", role="superadmin")
    h = _auth(_login(client, u, p))
    body = _payload()
    body["data"]["status"] = "已付款"
    r = client.post("/api/payslips", json=body, headers=h)
    assert r.status_code == 201, r.text
    no = r.json()["slip_no"]
    got = client.get("/api/payslips/%s" % no, headers=h).json()
    assert got["status"] == "草稿" and "status" not in got["data"]
    body2 = _payload()
    body2["data"]["status"] = "已簽回"
    assert client.put("/api/payslips/%s" % no, json=body2, headers=h).status_code == 200
    got = client.get("/api/payslips/%s" % no, headers=h).json()
    assert got["status"] == "草稿" and "status" not in got["data"]
