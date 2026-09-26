# -*- coding: utf-8 -*-
"""R2 零稅率、免稅必填依據（營業稅法 §7、§8；CUSTOMIZATION-SPEC §9.2；BENCHMARK §6.1、§7）。

守住的規則：
① 報價：零稅率／免稅且**非草稿**（送審、解鎖修改）⇒ 沒有有效依據回 400；草稿可以先存。
② §8 與「其他法律規定」一律要填說明。
③ 應稅單存檔時移除殘留的 taxBasis。
④ 開票申請：零稅率／免稅報價要有依據——報價上有就帶入快照；沒有（舊單）就要申請時補填，否則 400。
⑤ 舊資料：沒有依據的舊開票申請照常讀得到（taxBasis=None）。
"""
from tests._requires import requires_module, skip_module_unless  # noqa: E402  M01 ④(c)（稽核 D M4-M3）
import json
from datetime import datetime

import pytest

from helpers.legal_params import TAX_BASIS_OPTIONS, tax_basis_error, tax_basis_label
pytestmark = requires_module("case", '本檔的題打 M01（案件）的端點或讀寫 M01 的資料（報價單／案件）；M01 不在時沒有對象（稽核 D M4-M3）')


def _hdr(client, make_user, username="r2_root"):
    from tests.test_case_extra_expenses_api_2026_09_11 import _set_empty_approval_flow
    _set_empty_approval_flow()            # 送審需要簽核設定；本檔驗的是依據，不是流程
    u, p = make_user(username=username, role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _body(status="待審核", **data):
    d = {"customerName": "客戶", "projectName": "專案", "quoteDate": "2026-09-25", "validDays": 30,
         "items": [{"description": "品項", "qty": 1, "unitPrice": 1000, "amount": 1000}],
         "tot": {"total": 1000, "pretax": 1000}}
    d.update(data)
    return {"status": status, "data": d}


def _insert_quote(no, extra, status="已成案", total=20000, pretax=20000):
    import db
    data = {"quoteNo": no, "caseRecord": {"payment": {"items": []}}}
    data.update(extra)
    now = datetime.now().isoformat()
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, total, pretax, data_json, created_at, updated_at, "
            "customer_name) VALUES (?,?,?,?,?,?,?,?)",
            (no, status, total, pretax, json.dumps(data, ensure_ascii=False), now, now, "客戶"))
        conn.commit()
    finally:
        conn.close()


def _stored(no):
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
    finally:
        conn.close()


# ── 純函式 ──────────────────────────────────────────────────────────────────────

def test_zero_rate_options_cover_all_nine_items_of_article_7():
    codes = [c for c, _l in TAX_BASIS_OPTIONS["zero"]]
    assert codes[:9] == ["7-%d" % i for i in range(1, 10)]


@pytest.mark.parametrize("kind,basis,ok", [
    ("zero", None, False),
    ("zero", {"code": ""}, False),
    ("zero", {"code": "7-1"}, True),
    ("zero", {"code": "8", "note": "x"}, False),           # 免稅的代碼不能拿來當零稅率依據
    ("zero", {"code": "zero-other"}, False),              # 其他 ⇒ 說明必填
    ("zero", {"code": "zero-other", "note": "科學園區設置管理條例"}, True),
    ("exempt", {"code": "8-1"}, True),                    # §8 逐款選（2026-09-26 稽核 S-4）⇒ 不必再填說明
    ("exempt", {"code": "8-7"}, False),                   # 第 7 款已刪除，不是選項
    ("exempt", {"code": "8-33"}, False),
    ("exempt", {"code": "8", "note": "第 1 款"}, False),  # R2 初版的「§8＋說明」已不是選項（要重選款次）
    ("taxable", None, True),
])
def test_tax_basis_error(kind, basis, ok):
    assert (tax_basis_error(kind, basis) == "") is ok


# ── ① 報價 ──────────────────────────────────────────────────────────────────────

def test_submitting_a_zero_rated_quote_without_basis_is_refused(client, make_user):
    h = _hdr(client, make_user)
    r = client.post("/api/quotations", json=_body(taxRate=0, taxType="zero"), headers=h)
    assert r.status_code == 400, r.text
    assert "零稅率依據" in r.json()["detail"] and "§7" in r.json()["detail"]


def test_submitting_with_a_basis_is_accepted_and_stored(client, make_user):
    h = _hdr(client, make_user)
    r = client.post("/api/quotations", json=_body(taxRate=0, taxType="zero",
                                                  taxBasis={"code": "7-2", "note": "國外使用"}), headers=h)
    assert r.status_code == 201, r.text
    assert _stored(r.json()["quote_no"])["taxBasis"] == {"code": "7-2", "note": "國外使用"}


def test_exempt_under_article_8_requires_the_item_number(client, make_user):
    h = _hdr(client, make_user)
    r = client.post("/api/quotations", json=_body(taxRate=0, taxType="exempt", taxBasis={"code": "8"}), headers=h)
    assert r.status_code == 400 and "款次" in r.json()["detail"], r.text
    r = client.post("/api/quotations", json=_body(taxRate=0, taxType="exempt", taxBasis={"code": "8-5"}), headers=h)
    assert r.status_code == 201, r.text


def test_article_8_options_are_the_verbatim_items_with_source():
    """稽核 S-4：§8 第一項 32 款逐字（第 7 款已刪除 ⇒ 31 個選項）＋「其他法律規定」。"""
    from helpers import legal_params as lp
    assert [n for n, _t in lp.ARTICLE_8_ITEMS] == list(range(1, 33))
    assert lp.ARTICLE_8_DELETED == {7}
    codes = [c for c, _l in TAX_BASIS_OPTIONS["exempt"]]
    assert codes == ["8-%d" % n for n in range(1, 33) if n != 7] + ["exempt-other"]
    assert dict(TAX_BASIS_OPTIONS["exempt"])["8-1"] == "營業稅法 §8 第一項第 1 款：出售之土地。"
    assert "law.moj.gov.tw" in lp.ARTICLE_8_SOURCE and "G0340080" in lp.ARTICLE_8_SOURCE
    assert tax_basis_label({"code": "8", "note": "第 3 款"}).startswith("營業稅法 §8 第一項（舊選項"), "舊資料要顯示得出來"


def test_a_draft_can_be_saved_without_basis(client, make_user):
    h = _hdr(client, make_user)
    r = client.post("/api/quotations", json=_body(status="草稿", taxRate=0, taxType="exempt"), headers=h)
    assert r.status_code == 201, r.text


def test_an_old_exempt_quote_must_get_a_basis_when_submitted_again(client, make_user):
    """舊資料照常顯示與存草稿；再送出時才要求補依據。"""
    h = _hdr(client, make_user)
    _insert_quote("MQ-R2OLD", {"taxRate": 0, "customerName": "客戶"}, status="草稿")
    assert client.get("/api/quotations/MQ-R2OLD", headers=h).status_code == 200
    r = client.put("/api/quotations/MQ-R2OLD", json=_body(status="草稿", taxRate=0), headers=h)
    assert r.status_code == 200, r.text
    r = client.put("/api/quotations/MQ-R2OLD", json=_body(status="待審核", taxRate=0), headers=h)
    assert r.status_code == 400 and "免稅依據" in r.json()["detail"], r.text


def test_taxable_quote_drops_a_leftover_basis(client, make_user):
    h = _hdr(client, make_user)
    r = client.post("/api/quotations", json=_body(taxRate=5, taxType="taxable",
                                                  taxBasis={"code": "7-1", "note": ""}), headers=h)
    assert r.status_code == 201, r.text
    assert "taxBasis" not in _stored(r.json()["quote_no"])


# ── ④ 開票申請 ──────────────────────────────────────────────────────────────────

def _voucher(client, h, body):
    return client.post("/api/invoice-vouchers", json=body, headers=h)


def test_options_endpoint_is_the_single_source(client, make_user):
    h = _hdr(client, make_user)
    opts = client.get("/api/legal-params/tax-basis-options", headers=h).json()["options"]
    assert [o["code"] for o in opts["zero"]] == [c for c, _l in TAX_BASIS_OPTIONS["zero"]]
    assert {o["code"] for o in opts["exempt"] if o["noteRequired"]} == {"exempt-other"}
    assert [o["code"] for o in opts["exempt"]] == [c for c, _l in TAX_BASIS_OPTIONS["exempt"]]
