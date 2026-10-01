# -*- coding: utf-8 -*-
"""第二稽核探針（train 30，2e 對 a3 的勞報單帳號遮蔽）：作者的測試蓋了 GET／PDF／存檔讀取／寫入；這支只找「別的出口」——
非最高管理者（持 payslip 模組）能打到的**每一個**會回傳勞報單資料的端點，整個回應本文與 PDF 文字都不可含全碼（含中段數字）。"""
import io
import json

import pytest

from modules.payroll.api import payslips as payslips_api
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _login, _auth  # noqa: F401
from modules.payroll.tests.test_payslip_bank_mask_2026_10_01 import FULL, MASKED, _body, _create, _db, _pdf_text, world  # noqa: F401

MID = FULL[2:-2]                          # 中段數字：就算只洩一部分也算


@pytest.fixture(autouse=True)
def _archive_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(payslips_api, "_archive_dir", lambda: str(tmp_path / "payslip_archive"))


def _clean(r, label):
    text = r.text if "pdf" not in (r.headers.get("content-type") or "") else _pdf_text(r.content)
    assert FULL not in text and MID not in text, "%s 洩漏帳號：%r" % (label, text[:200])


def test_every_staff_reachable_payslip_response_is_free_of_the_full_account(client, world):
    su, st, none = world["pb_su"], world["pb_staff"], world["pb_none"]
    no = _create(client, su, world["cid"], FULL)
    assert client.post("/api/payslips/%s/export" % no, headers=st).status_code == 200
    seen = []

    def hit(label, r, ok=(200, 201, 204, 400, 403, 404, 409)):
        assert r.status_code in ok, (label, r.status_code, r.text[:200])
        seen.append((label, r.status_code))
        _clean(r, label)
    hit("list", client.get("/api/payslips", headers=st))
    hit("list-by-account-search", client.get("/api/payslips", headers=st, params={"q": MID, "search": MID, "keyword": MID}))
    hit("detail", client.get("/api/payslips/%s" % no, headers=st))
    hit("pdf", client.get("/api/payslips/%s/pdf-download" % no, headers=st))
    hit("archive", client.get("/api/payslips/%s/archive/1" % no, headers=st))
    hit("export-again", client.post("/api/payslips/%s/export" % no, headers=st))
    hit("put-echo", client.put("/api/payslips/%s" % no, headers=st, json=_body(world["cid"], MASKED)))
    hit("mark-paid", client.post("/api/payslips/%s/mark-paid" % no, headers=st, json={"paidDate": "2026-10-02"}))
    hit("unpay", client.post("/api/payslips/%s/unpay" % no, headers=st, json={}))
    hit("void", client.post("/api/payslips/%s/void" % no, headers=st, json={"reason": "探針"}))
    hit("after-void-detail", client.get("/api/payslips/%s" % no, headers=st))
    # 沒有 payslip 模組的人：任何一支都不該看到內容（403／404）
    for p in ("/api/payslips", "/api/payslips/%s" % no, "/api/payslips/%s/pdf-download" % no, "/api/payslips/%s/archive/1" % no):
        r = client.get(p, headers=none)
        assert r.status_code in (403, 404) and FULL not in r.text, (p, r.status_code)
    assert len(seen) >= 11
    assert FULL in _db("SELECT data_json FROM payslips WHERE slip_no=?", (no,))[0]["data_json"]     # 庫裡的真值沒被遮蔽值覆蓋


def test_staff_cannot_obtain_the_full_account_through_the_contractor_register_or_audit(client, world):
    su, st = world["pb_su"], world["pb_staff"]
    no = _create(client, su, world["cid"], FULL)
    for p in ("/api/contractors", "/api/contractors/%s" % world["cid"], "/api/contractors/%s/id-card" % world["cid"]):
        r = client.get(p, headers=st)
        assert r.status_code in (200, 403, 404), (p, r.status_code)
        _clean(r, p)
    r = client.get("/api/audit-log", headers=st)
    assert r.status_code in (200, 403, 404)
    _clean(r, "audit-log(staff)")
    _clean(client.get("/api/audit-log", headers=su), "audit-log(su)")                           # 稽核紀錄連最高管理者看也不含全碼
    assert no
