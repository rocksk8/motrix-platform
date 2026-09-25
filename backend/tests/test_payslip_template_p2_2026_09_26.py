# -*- coding: utf-8 -*-
"""P2 第二份單據：勞務報酬單版型化（CUSTOMIZATION-SPEC §3.4）＋R3 個資蒐集告知（主持 2026-09-26 併入 P2）。

驗收（主持裁示 A，理由見 §3.4）：與凍結的舊 builder（tests/_frozen/legacy_payslip_html.py）相比
① 結構正規化後相同（標籤之間的空白拿掉後逐字相同）② 瀏覽器 innerText 逐字相同 ③ PDF 抽出的文字相同。
比對時把改版後新增的個資告知兩塊（id 以 privacy 開頭）拿掉；那兩塊另有自己的題。
"""
import copy
import re

import pytest

from tests._frozen.legacy_payslip_html import legacy_build_payslip_html as legacy

BASE = {"companyName": "甲公司 <A&B>", "companyTaxId": "12345678", "companyContactInfo": "Tel 02｜a@b.c",
        "contractorName": "王小明", "contractorIdNumber": "A123456789", "contractorPhone": "0912", "contractorEmail": "w@x.y",
        "contractorAddress": "台北市\n信義區", "contractorNationality": "本國籍", "contractorHasUnionInsurance": True,
        "serviceContent": "網路施工", "serviceStartDate": "2026-09-01", "serviceEndDate": "2026-09-05",
        "incomeType": "9A", "incomeSubtype": "工程<甲>", "slipDate": "2026-09-06", "slipNo": "PS-1", "remarks": "備註\n第二行",
        "grossAmount": 30000, "paymentMethod": "匯款",
        "calc": {"taxWithheld": 3000, "nhiSupplement": 633, "netAmount": 26367, "taxRate": 0.1, "nhiRate": 0.0211},
        "bankCode": "812", "bankName": "台新", "bankBranch": "信義", "bankAccountName": "王小明", "bankAccountNumber": "123",
        "_id_card_front": "data:image/png;base64,AAA", "_id_card_back": "data:image/png;base64,BBB",
        "_bank_passbook": "data:image/png;base64,CCC"}
CASES = {
    "full": BASE,
    "cash_no_union_no_remarks_one_id_side": dict(BASE, paymentMethod="現金", contractorHasUnionInsurance=False, remarks="",
                                                 _id_card_back="", _bank_passbook="",
                                                 calc={"taxWithheld": 0, "nhiSupplement": 0}),
    "foreign_resident_rules": dict(BASE, contractorNationality="外國籍（未滿183天）", incomeSubtype="", incomeType="50"),
    "reprint_without_company_snapshot": {k: v for k, v in BASE.items()
                                         if k not in ("companyName", "companyTaxId", "companyContactInfo")},
    "minimal": {},
}


@pytest.fixture()
def company(client):
    from helpers.settings import _set_setting
    _set_setting("company_profile", {"companyName": "現行公司", "taxId": "99999999", "phone": "02-1", "email": "x@y.z"})


def _without_privacy(t):
    t = copy.deepcopy(t)
    t["blocks"] = [b for b in t["blocks"] if not str(b.get("id", "")).startswith("privacy")]
    t["after_root"] = [b for b in t.get("after_root", []) if not str(b.get("id", "")).startswith("privacy")]
    return t


def _norm(h):
    return re.sub(r">\s+<", "><", h).strip()


def _pair(name):
    import pdf_gen
    from helpers import doc_template as dt
    d = CASES[name]
    return legacy(copy.deepcopy(d)), pdf_gen._build_payslip_html(copy.deepcopy(d), template=_without_privacy(dt.load_default("payslip")))


@pytest.mark.parametrize("name", sorted(CASES))
def test_payslip_structure_matches_the_frozen_builder(company, name):
    old, new = _pair(name)
    assert _norm(new) == _norm(old)


def test_normalization_alone_would_hide_meaningful_inline_spaces():
    """為什麼還要 innerText：`>\\s+<` 會把行內元素之間有意義的空白一起吃掉（主持裁示 1）。"""
    assert _norm("<b>承攬人</b> <b>姓名</b>") == _norm("<b>承攬人</b><b>姓名</b>")


# ── 瀏覽器 innerText（主持裁示 1：閘門）──────────────────────────────────────

def _inner_text(new_page, html):
    page = new_page()
    page.set_content(html)
    return page.evaluate("document.body.innerText")


@pytest.mark.e2e
@pytest.mark.parametrize("name", sorted(CASES))
def test_payslip_inner_text_matches_the_frozen_builder(company, new_page, name):
    old, new = _pair(name)
    assert _inner_text(new_page, new) == _inner_text(new_page, old)


@pytest.mark.e2e
def test_inner_text_catches_an_inline_space(company, new_page):
    """反向控制：只差一個行內空白（結構正規化看不出來）⇒ innerText 比對要抓到。"""
    old = "<p><b>承攬人</b> <b>姓名</b></p>"
    new = "<p><b>承攬人</b><b>姓名</b></p>"
    assert _norm(old) == _norm(new)
    assert _inner_text(new_page, old) != _inner_text(new_page, new)


# ── PDF 文字（主持裁示 1：閘門；需要 Edge）────────────────────────────────────

def _pdf_text(html):
    import io
    import pdf_gen
    from pypdf import PdfReader
    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf_gen.html_to_pdf_bytes(html))).pages)


@pytest.mark.e2e
@pytest.mark.parametrize("name", ["full", "reprint_without_company_snapshot"])
def test_payslip_pdf_text_matches_the_frozen_builder(company, name):
    from helpers import _get_edge_path
    try:
        _get_edge_path()
    except Exception as e:                                       # noqa: BLE001
        pytest.skip("這台機器沒有 Edge：%s" % e)
    old, new = _pair(name)
    assert _pdf_text(new) == _pdf_text(old)


# ── R3 個資蒐集告知（新增的兩塊）──────────────────────────────────────────────

def _html(d):
    import pdf_gen
    return pdf_gen._build_payslip_html(copy.deepcopy(d))


def test_payslip_attaches_the_notice_when_not_yet_acknowledged(company):
    """沒有「已告知」紀錄 ⇒ 附上告知事項全文（取自公司資料設定；空白用範本，公司名代入）。"""
    html = _html(BASE)
    assert "個人資料蒐集告知事項見附件" in html and "附件：個人資料蒐集告知事項" in html
    assert "依個人資料保護法第 8 條第 1 項" in html and "已告知（" not in html


def test_payslip_uses_the_companys_own_notice_text(company):
    from helpers.settings import _set_setting
    _set_setting("company_profile", {"companyName": "現行公司", "privacy_notice": "本公司自訂的告知 <條款>"})
    assert "本公司自訂的告知 &lt;條款&gt;" in _html(BASE)


def test_payslip_prints_who_and_when_once_acknowledged(company):
    """已告知 ⇒ 印「已告知（時間、人員）」，不再附全文。"""
    d = dict(BASE, privacyNotice={"at": "2026-09-20T14:05:33", "by": "承辦人甲", "noticeHash": "x"})
    html = _html(d)
    assert "已告知（2026-09-20 14:05，承辦人甲）" in html
    assert "附件：個人資料蒐集告知事項" not in html and "個人資料蒐集告知事項見附件" not in html


def test_payslip_default_template_is_valid_against_its_view(company):
    import pdf_gen
    from helpers import doc_template as dt
    assert dt.validate(dt.load_default("payslip"), pdf_gen._payslip_view(copy.deepcopy(BASE))) == []


def test_payslip_template_can_be_overridden_and_previewed(client, make_user, company):
    """P5：勞報單的版型也能在定義文件庫覆寫、驗證、預覽（樣本資料）。"""
    from helpers import doc_template as dt
    u, p = make_user("ps_super", "Payslip-Pass-123", role="superadmin")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    body = dt.load_default("payslip")
    body["blocks"][0]["title"] = "勞務報酬單（覆寫）"
    r = client.post("/api/definitions/output_template/payslip/preview", headers=h, json={"body": body})
    assert r.status_code == 200 and "勞務報酬單（覆寫）" in r.text and "PS-202609-0001" in r.text
    bad = copy.deepcopy(body)
    bad["blocks"][1]["type"] = "nope"
    r = client.post("/api/definitions/output_template/payslip/validate", headers=h, json={"body": bad})
    assert r.json()["problems"][0]["path"] == "blocks[1].type"
