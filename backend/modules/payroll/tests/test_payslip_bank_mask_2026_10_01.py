# -*- coding: utf-8 -*-
"""勞報單收款帳號遮蔽（稽核 F1；使用者裁示 2026-10-01：只有最高管理者看得到完整帳號，其餘一律遮蔽、沒有例外）。

- GET /api/payslips/{no}：非最高管理者（持 payslip 模組）看到 `****末四碼` 與 `bankMasked=true`；最高管理者全碼。
- pdf-download：非最高管理者的 PDF 文字只有末四碼、不帶存簿影本；最高管理者全碼。匯出存檔（F2 法定紀錄）永遠是完整版；存檔讀取對非最高管理者改回遮蔽版。
- 寫入：遮蔽值原樣送回 ⇒ 沿用舊值；沒有舊值可沿用 ⇒ 400；非最高管理者沒有帳號 ⇒ 伺服器從外包名冊取值（真值不經過前端）。
- 稽核不含帳號全碼。反向控制：把 `can_see_full` 改成永遠 True ⇒ 一般人看到全碼。
"""
import io
import json

import pytest

from modules.payroll import payslip_bank as PB
from modules.payroll.api import payslips as payslips_api
from modules.payroll.tests.test_payslip_edit_guard_2026_08_28 import _login, _auth  # noqa: F401

FULL = "00012345678901"
MASKED = "****8901"
PASSBOOK = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"


@pytest.fixture(autouse=True)
def _archive_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(payslips_api, "_archive_dir", lambda: str(tmp_path / "payslip_archive"))


def _db(sql, args=()):
    import db
    c = db.get_db()
    try:
        cur = c.execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()] if cur.description else []      # 先取完（RETURNING）再 commit
        c.commit()
        return rows
    finally:
        c.close()


@pytest.fixture
def world(client, make_user):
    out = {}
    for name, role, mods in (("pb_su", "superadmin", []), ("pb_staff", "sales", ["payslip"]), ("pb_none", "sales", [])):
        u, p = make_user(username=name, role=role, modules=mods)
        out[name] = _auth(_login(client, u, p))
    cid = _db("INSERT INTO contractors (name, bank_code, bank_name, bank_account_name, bank_account_number, bank_passbook_image) "
              "VALUES ('甲承攬人','700','中華郵政','甲承攬人',?,?) RETURNING id", (FULL, PASSBOOK))[0]["id"]
    out["cid"] = cid
    return out


def _body(cid, account=None, gross=30000):
    d = {"contractorName": "甲承攬人", "incomeType": "9A", "grossAmount": gross, "contractorNationality": "本國籍",
         "contractorHasUnionInsurance": False, "slipDate": "2026-10-01", "bankName": "中華郵政"}
    if account is not None:
        d["bankAccountNumber"] = account
    return {"contractor_id": cid, "data": d}


def _stored(no):
    return json.loads(_db("SELECT data_json FROM payslips WHERE slip_no=?", (no,))[0]["data_json"]).get("bankAccountNumber")


def _create(client, h, cid, account=None):
    r = client.post("/api/payslips", headers=h, json=_body(cid, account))
    assert r.status_code == 201, r.text
    return r.json()["slip_no"]


# ── 讀取 ───────────────────────────────────────────────────────────────────

def test_get_masks_for_payslip_module_holders_and_shows_full_to_superadmin(client, world):
    no = _create(client, world["pb_su"], world["cid"], FULL)
    su = client.get("/api/payslips/%s" % no, headers=world["pb_su"]).json()
    assert su["data"]["bankAccountNumber"] == FULL and su["bankMasked"] is False              # 正對照
    st = client.get("/api/payslips/%s" % no, headers=world["pb_staff"])
    assert st.status_code == 200 and st.json()["data"]["bankAccountNumber"] == MASKED and st.json()["bankMasked"] is True
    assert FULL not in st.text                                                                  # 整個回應任何地方都沒有全碼
    assert client.get("/api/payslips/%s" % no, headers=world["pb_none"]).status_code == 403    # 沒有模組：照舊 403
    assert _stored(no) == FULL                                                                   # 庫裡仍是真值


def test_reverse_control_without_the_mask_staff_would_see_the_full_number(client, world, monkeypatch):
    no = _create(client, world["pb_su"], world["cid"], FULL)
    monkeypatch.setattr(PB, "can_see_full", lambda user: True)
    assert client.get("/api/payslips/%s" % no, headers=world["pb_staff"]).json()["data"]["bankAccountNumber"] == FULL


# ── 寫入 ───────────────────────────────────────────────────────────────────

def test_staff_creating_without_an_account_gets_it_from_the_contractor_record_server_side(client, world):
    no = _create(client, world["pb_staff"], world["cid"], None)                                 # 前端不帶（遮蔽的帳號不會被帶進表單）
    assert _stored(no) == FULL                                                                   # 伺服器端從外包名冊取真值
    no2 = _create(client, world["pb_staff"], world["cid"], "")
    assert _stored(no2) == FULL
    assert client.get("/api/payslips/%s" % no, headers=world["pb_staff"]).json()["data"]["bankAccountNumber"] == MASKED   # 員工仍只看到遮蔽


def test_superadmin_blank_stays_blank_and_masked_value_is_rejected_on_create(client, world):
    no = _create(client, world["pb_su"], world["cid"], "")
    assert _stored(no) == ""                                                                     # 最高管理者明確留空 ⇒ 就是空（不自動補）
    r = client.post("/api/payslips", headers=world["pb_su"], json=_body(world["cid"], MASKED))
    assert r.status_code == 400 and "遮蔽" in r.json()["detail"]
    assert _db("SELECT COUNT(*) AS n FROM payslips WHERE data_json LIKE '%****%'")[0]["n"] == 0  # 沒有任何單據存進遮蔽值


def test_editing_with_the_masked_value_keeps_the_stored_number(client, world):
    no = _create(client, world["pb_su"], world["cid"], FULL)
    body = _body(world["cid"], MASKED, gross=45000)                                              # 編輯表單載入遮蔽值、沒動帳號就存
    for who in ("pb_staff", "pb_su"):
        r = client.put("/api/payslips/%s" % no, headers=world[who], json=body)
        assert r.status_code == 200, (who, r.text)
        assert _stored(no) == FULL, who                                                          # 真值還在、沒被 ****8901 蓋掉
    assert _db("SELECT gross_amount FROM payslips WHERE slip_no=?", (no,))[0]["gross_amount"] == 45000   # 其他欄位照常更新


def test_masked_value_with_nothing_to_keep_is_rejected_on_update(client, world):
    no = _create(client, world["pb_su"], world["cid"], "")                                       # 舊單沒有帳號
    r = client.put("/api/payslips/%s" % no, headers=world["pb_su"], json=_body(world["cid"], MASKED))
    assert r.status_code == 400 and _stored(no) == ""
    st = client.put("/api/payslips/%s" % no, headers=world["pb_staff"], json=_body(world["cid"], MASKED))
    assert st.status_code == 200 and _stored(no) == FULL                                         # 員工：舊單沒有 ⇒ 改由外包名冊取值（不是拒絕）


def test_staff_can_still_enter_a_new_full_number_and_audit_has_no_account(client, world):
    no = _create(client, world["pb_staff"], world["cid"], "99887766554433")
    assert _stored(no) == "99887766554433"
    client.put("/api/payslips/%s" % no, headers=world["pb_staff"], json=_body(world["cid"], MASKED))
    assert _stored(no) == "99887766554433"
    blob = json.dumps(_db("SELECT action, target_id, target_label, detail FROM audit_log WHERE action LIKE 'payslip.%'"), ensure_ascii=False)
    assert "99887766554433" not in blob and FULL not in blob and "payslip.update" in blob


# ── PDF ────────────────────────────────────────────────────────────────────

def _pdf_text(b):
    import pypdf
    return "".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(b)).pages)


def test_pdf_download_text_is_masked_for_staff_and_full_for_superadmin(client, world):
    no = _create(client, world["pb_su"], world["cid"], FULL)
    st = client.get("/api/payslips/%s/pdf-download" % no, headers=world["pb_staff"])
    assert st.status_code == 200 and st.content[:5] == b"%PDF-", st.text[:200]
    t = _pdf_text(st.content)
    assert FULL not in t and "8901" in t                                                         # PDF 文字層：沒有全碼、有末四碼
    su = client.get("/api/payslips/%s/pdf-download" % no, headers=world["pb_su"])
    assert FULL in _pdf_text(su.content)                                                         # 正對照：最高管理者看得到全碼（證明抽文字有效）


def test_pdf_drops_the_passbook_image_when_masked(client, world, monkeypatch):
    import pdf_gen
    no = _create(client, world["pb_su"], world["cid"], FULL)
    seen = []
    real = pdf_gen._build_payslip_html
    monkeypatch.setattr(pdf_gen, "_build_payslip_html", lambda d, template=None: (seen.append((d.get("bankAccountNumber"), d.get("_bank_passbook"))), real(d, template))[1])
    pdf_gen.generate_payslip_pdf_bytes(no)                                                       # 預設 fail closed
    pdf_gen.generate_payslip_pdf_bytes(no, mask_bank=False)
    assert seen[0] == (MASKED, "") and seen[1] == (FULL, PASSBOOK)


def test_pdf_mutation_mask_false_for_staff_turns_the_assertion_red(client, world, monkeypatch):
    import pdf_gen
    no = _create(client, world["pb_su"], world["cid"], FULL)
    real = pdf_gen.generate_payslip_pdf_bytes
    monkeypatch.setattr(pdf_gen, "generate_payslip_pdf_bytes", lambda n, mask_bank=True: real(n, mask_bank=False))
    r = client.get("/api/payslips/%s/pdf-download" % no, headers=world["pb_staff"])
    assert FULL in _pdf_text(r.content), "突變沒讓 PDF 洩漏 ⇒ 偵測器壞了"


def test_export_archive_stays_full_but_staff_reads_a_masked_regeneration(client, world):
    no = _create(client, world["pb_su"], world["cid"], FULL)
    assert client.post("/api/payslips/%s/submit" % no, headers=world["pb_su"]).status_code == 200      # 第46班：匯出只准核准之後（沒設簽核層＝送審即核准）
    assert client.post("/api/payslips/%s/export" % no, headers=world["pb_staff"]).status_code == 200      # 員工按匯出
    log = json.loads(_db("SELECT export_log FROM payslips WHERE slip_no=?", (no,))[0]["export_log"])
    assert log[-1]["archived"] is True
    su = client.get("/api/payslips/%s/archive/1" % no, headers=world["pb_su"])
    assert FULL in _pdf_text(su.content)                                                         # 存檔是完整的法定紀錄（不論誰按的匯出）
    st = client.get("/api/payslips/%s/archive/1" % no, headers=world["pb_staff"])
    assert st.status_code == 200 and FULL not in _pdf_text(st.content) and "8901" in _pdf_text(st.content)   # 員工讀到的是遮蔽的重新產生版


# ── 純函式 ─────────────────────────────────────────────────────────────────

def test_masked_value_recogniser_and_mask_number():
    for v in ("****8901", "****", "***1234", "*****"):
        assert PB.is_masked_value(v), v
    for v in ("", "00012345678901", "12**34", "**12", None, 8901):
        assert not PB.is_masked_value(v), v
    assert PB.mask_number(FULL) == MASKED and PB.mask_number("123") == "****" and PB.mask_number("") == ""


def test_payroll_and_subcontract_masking_rules_agree():
    """模組之間不互相 import ⇒ 各留一份；這題逐案對照兩份行為相同（改一份忘了另一份就紅）。"""
    from modules.subcontract import bank_mask as BM
    for n in ("", "1", "1234", "12345", FULL, None):
        assert PB.mask_number(n) == BM.mask_number(n), n
    for v in ("****8901", "***", "****12345", "abc", "", None, "12**34"):
        assert PB.is_masked_value(v) == BM.is_masked_value(v), v
    for role in ("superadmin", "admin", "sales", None):
        assert PB.can_see_full({"role": role}) == BM.can_see_full({"role": role})
