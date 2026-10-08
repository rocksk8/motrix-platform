# -*- coding: utf-8 -*-
"""第 46 班補強（第 46 班獨立稽核 S1/S2/S3 與 paid_via_remit）：勞報單狀態變更的並發防護。

「並發」的做法：端點用 `payslips_api.get_db()` 拿連線；題目把它換成代理——代理在端點**第一次讀完勞報單那一列**之後，
用另一條連線做一件事（模擬另一位操作者在讀與寫之間動手），其餘全部委派給真連線。端點的條件式 UPDATE／DELETE 必須因此 409，
而且**不可以把對方剛寫的狀態蓋回去**（以資料庫的實際內容斷言，不是回應文字）。
"""
import json

import pytest

from core import source_tree
from modules.payroll.api import payslips as payslips_api
from modules.payroll.tests.test_payslip_cashier_t46 import _row, _slip, _x
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _auth, _login

_MAKE_USER_DEFAULT_ROLE = "superadmin"
FID = "0123456789abcdef"


@pytest.fixture(autouse=True)
def _archive_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(payslips_api, "_archive_dir", lambda: str(tmp_path / "payslip_archive"))


class _OneRow:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        r, self._row = self._row, None
        return r

    def fetchall(self):
        r = self.fetchone()
        return [r] if r is not None else []


class _StaleProxy:
    """端點第一次 `SELECT ... FROM payslips` 的整列取回之後，執行 then()（另一條連線）；其餘委派給真連線。"""

    def __init__(self, conn, then):
        self._c, self._then, self._fired = conn, then, False
        self.sql = []

    def execute(self, sql, *a):
        self.sql.append(sql.strip())
        cur = self._c.execute(sql, *a)
        if not self._fired and sql.lstrip().upper().startswith("SELECT") and "FROM payslips" in sql:
            row = cur.fetchone()
            self._fired = True
            self._then()
            return _OneRow(row)
        return cur

    def __getattr__(self, name):
        return getattr(self._c, name)


def _race(monkeypatch, then):
    import db
    real = db.get_db
    proxies = []

    def fake():
        p = _StaleProxy(real(), then)
        proxies.append(p)
        return p
    monkeypatch.setattr(payslips_api, "get_db", fake)
    return proxies


def _su(client, make_user, name):
    u, p = make_user(username=name, role="superadmin")
    return _auth(_login(client, u, p))


# ── S1：上傳簽回檔 ───────────────────────────────────────────────────────────────────────────────
def test_upload_after_concurrent_payment_does_not_flip_paid_back(client, make_user, monkeypatch):
    h = _su(client, make_user, "t47_up1")
    _slip("PS-203106-901", status="已匯出", exported=1)
    _race(monkeypatch, lambda: _x("UPDATE payslips SET status='已付款', payment_date='2031-06-10', voucher_no='V-1', paid_by='f', paid_at='T1' WHERE slip_no='PS-203106-901'"))
    r = client.post("/api/payslips/PS-203106-901/signed-files", headers=h, files=[("files", ("s.pdf", b"%PDF-1.4 x", "application/pdf"))])
    assert r.status_code == 409, r.text
    row = _row("PS-203106-901")
    assert row["status"] == "已付款" and row["voucher_no"] == "V-1" and row["signed_files_json"] == "[]"      # 沒被蓋回「已簽回」


def test_upload_after_concurrent_upload_does_not_lose_the_other_file(client, make_user, monkeypatch):
    h = _su(client, make_user, "t47_up2")
    _slip("PS-203106-902", status="已簽回", signed=True, exported=1)
    other = json.dumps([{"id": "aaaaaaaaaaaaaaaa", "filename": "other.pdf", "ext": ".pdf"}])
    _race(monkeypatch, lambda: _x("UPDATE payslips SET signed_files_json=? WHERE slip_no='PS-203106-902'", (other,)))
    r = client.post("/api/payslips/PS-203106-902/signed-files", headers=h, files=[("files", ("s.pdf", b"%PDF-1.4 x", "application/pdf"))])
    assert r.status_code == 409, r.text
    assert _row("PS-203106-902")["signed_files_json"] == other                                              # 對方剛傳的檔案清單原封不動


def test_upload_normal_path_still_works(client, make_user):
    h = _su(client, make_user, "t47_up3")
    _slip("PS-203106-903", status="已匯出", exported=1)
    r = client.post("/api/payslips/PS-203106-903/signed-files", headers=h, files=[("files", ("s.pdf", b"%PDF-1.4 x", "application/pdf"))])
    assert r.status_code == 201, r.text
    assert _row("PS-203106-903")["status"] == "已簽回"


# ── S1：刪簽回檔／退回簽回 ─────────────────────────────────────────────────────────────────────────
def test_delete_signed_file_after_concurrent_payment_is_refused(client, make_user, monkeypatch):
    h = _su(client, make_user, "t47_ds1")
    _slip("PS-203106-904", status="已簽回", signed=True, exported=1)
    before = _row("PS-203106-904")["signed_files_json"]
    _race(monkeypatch, lambda: _x("UPDATE payslips SET status='已付款', voucher_no='V-2', paid_at='T1' WHERE slip_no='PS-203106-904'"))
    r = client.delete("/api/payslips/PS-203106-904/signed-files/" + FID, headers=h)
    assert r.status_code == 409, r.text
    row = _row("PS-203106-904")
    assert row["status"] == "已付款" and row["signed_files_json"] == before


def test_unsign_after_concurrent_payment_is_refused(client, make_user, monkeypatch):
    h = _su(client, make_user, "t47_us1")
    _slip("PS-203106-905", status="已簽回", signed=True, exported=1)
    _race(monkeypatch, lambda: _x("UPDATE payslips SET status='已付款', voucher_no='V-3', paid_at='T1' WHERE slip_no='PS-203106-905'"))
    r = client.post("/api/payslips/PS-203106-905/unsign", headers=h)
    assert r.status_code == 409, r.text
    row = _row("PS-203106-905")
    assert row["status"] == "已付款" and row["voucher_no"] == "V-3"                                          # 已付款沒被退成已匯出


# ── S2：退回付款 ─────────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not source_tree.module_installed("modules/arap/"), reason="出納端點在應收應付（M05）")
def test_unpay_does_not_wipe_a_payment_made_after_the_read(client, make_user, monkeypatch):
    h = _su(client, make_user, "t47_up_pay")
    _slip("PS-203106-906", status="已付款", signed=True, exported=1)
    _x("UPDATE payslips SET payment_date='2031-06-10', voucher_no='V-OLD', paid_by='f', paid_at='T-OLD' WHERE slip_no='PS-203106-906'")
    # 另一位先退回、再重新付款（狀態還是「已付款」，但付款欄位是新的）
    _race(monkeypatch, lambda: _x("UPDATE payslips SET voucher_no='V-NEW', paid_at='T-NEW', payment_date='2031-06-12' WHERE slip_no='PS-203106-906'"))
    r = client.post("/api/payslips/PS-203106-906/unpay", headers=h)
    assert r.status_code == 409, r.text
    row = _row("PS-203106-906")
    assert row["status"] == "已付款" and row["voucher_no"] == "V-NEW" and row["paid_at"] == "T-NEW"


# ── 作廢：條件沒中不可回「已作廢」 ─────────────────────────────────────────────────────────────────


# ── S3：刪除 ─────────────────────────────────────────────────────────────────────────────────────
def test_delete_takes_the_write_lock_before_reading_status(client, make_user, monkeypatch):
    h = _su(client, make_user, "t47_del")
    _slip("PS-203106-908", status="草稿")
    proxies = _race(monkeypatch, lambda: None)
    r = client.delete("/api/payslips/PS-203106-908", headers=h)
    assert r.status_code == 204, r.text
    sql = proxies[-1].sql
    assert sql[0].upper().startswith("BEGIN IMMEDIATE"), sql[:3]                                            # 先拿寫鎖，再讀狀態
    import db
    c = db.get_db()
    try:
        assert c.execute("SELECT 1 FROM payslips WHERE slip_no='PS-203106-908'").fetchone() is None
    finally:
        c.close()


@pytest.mark.parametrize("status", ["待審核", "已核准", "已匯出", "已簽回", "已付款", "已作廢"])
def test_delete_refuses_every_locked_status_and_keeps_the_row(client, make_user, status):
    h = _su(client, make_user, "t47_del_" + str(abs(hash(status)) % 10000))
    no = "PS-203106-%03d" % (910 + ["待審核", "已核准", "已匯出", "已簽回", "已付款", "已作廢"].index(status))
    _slip(no, status=status)
    r = client.delete("/api/payslips/" + no, headers=h)
    assert r.status_code == 400, r.text
    assert _row(no)["status"] == status


# ── paid_via_remit 只准匯款連結程式寫 ───────────────────────────────────────────────────────────────
def test_client_cannot_plant_paid_via_remit_on_create_or_update(client, make_user):
    h = _su(client, make_user, "t47_pvr")
    body = {"data": {"contractorName": "測試承攬人", "incomeType": "9A", "grossAmount": 35000, "contractorNationality": "本國籍",
                     "contractorHasUnionInsurance": False, "paid_via_remit": "RM-FAKE-1"}}
    r = client.post("/api/payslips", json=body, headers=h)
    assert r.status_code in (200, 201), r.text
    no = r.json()["slip_no"]
    assert "paid_via_remit" not in json.loads(_row(no)["data_json"])
    body["data"]["grossAmount"] = 36000
    assert client.put("/api/payslips/" + no, json=body, headers=h).status_code == 200
    assert "paid_via_remit" not in json.loads(_row(no)["data_json"])


# ── 小項 ─────────────────────────────────────────────────────────────────────────────────────────


# ── S8：出納看收款人銀行資料（勞報單＝嚴格提供者）──────────────────────────────────────────────────
