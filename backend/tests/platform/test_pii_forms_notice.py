# -*- coding: utf-8 -*-
"""守門：蒐集自然人個資的表單都要有個資蒐集告知（CUSTOMIZATION-SPEC §9.3；MODULE-GUIDE §11）。

清單 `docs/platform/pii_forms.json`（鍵＝頁面檔名），掃描規則 `_pii_forms.py`（頁面位置問 `core.source_tree.page_files()`）。
- 正對照①（不綁 L2）：暫存目錄裡一張有個資欄位、沒有決定的頁面 ⇒ 被抓到。
- 正對照②（使用者 2026-09-26 指定）：承攬人員名冊（R3 已有告知）要被掃到，而且決定是 notice。
- 反向控制：把所有決定都改成「非自然人」或「由別頁涵蓋」⇒ 轉紅；拿掉某一頁的告知區塊 ⇒ 轉紅；
  豁免頁多一個個資欄位 ⇒ 轉紅；過期的決定 ⇒ 轉紅；可以手打的欄位用 covered_by ⇒ 轉紅；
  `api_module` 的模組在 ⇒ 端點照驗（不在才免驗端點，PLAYBOOK §B-11）。
- 逐欄（稽核 D PN-M1）：告知頁多一個個資欄位 ⇒ 轉紅；一欄屬於兩個對象 ⇒ 轉紅；兩個告知對象卻少了其中一個的區塊 ⇒ 轉紅；
  notice 沒列 fields ⇒ 轉紅；簽收人（recipient）掃得到。
- 「不可手打」只認屬性名稱（稽核 D PN-S3）：屬性值裡的 readonly／disabled 不算；屬性值裡的 `=>` 不截斷標籤。
"""
import copy
import shutil

import pytest

from tests.platform import _pii_forms as pf


def test_every_pii_form_has_a_decision_and_it_still_holds():
    errs = pf.violations()
    assert not errs, "\n".join(errs)


def test_positive_control_contractors_form_is_detected_as_notice():
    found = pf.scan()
    assert "contractors.html" in found, "承攬人員名冊（已有 R3 告知）掃不到 ⇒ 偵測規則壞了，清單不能算完整"
    assert "form.id_number" in found["contractors.html"]
    assert "notice" in pf.load_registry()["forms"]["contractors.html"]


# ── 用暫存目錄做的正對照與反向控制（頁面複本平放在一個資料夾，突變只動複本）──────────

def _copies(tmp_path):
    d = tmp_path / "copies"
    d.mkdir()
    for p in pf.product_pages():
        shutil.copy2(p, d / p.name)
    return d


def _pages(d):
    return sorted(d.glob("*.html"))


def _told_subjects(reg=None):
    """(頁面, 對象索引或 None, 告知對象)：每一個有紀錄端點的告知對象（`notice` 或 `notices` 裡非 covered_by／not_natural_person 的）。"""
    out = []
    for page, dec in (reg or pf.load_registry())["forms"].items():
        if "notice" in dec:
            out.append((page, None, dec["notice"]))
        for i, n in enumerate(dec.get("notices") or []):
            if not ({"covered_by", "not_natural_person"} & set(n)):
                out.append((page, i, n))
    return out


def _is_notice_page(dec):
    return "notice" in dec or "notices" in dec


def test_new_pii_page_without_decision_turns_red(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    (d / "new-form.html").write_text('<input x-model.trim="form.contactPerson"><input x-model="item.mobile">',
                                     encoding="utf-8")
    errs = pf.violations({"forms": {}}, pages=_pages(d), router_text="")
    assert any("new-form.html" in e and "沒有決定" in e for e in errs), errs
    assert pf.scan(_pages(d))["new-form.html"] == ["form.contactPerson", "item.mobile"]


def test_page_without_pii_is_not_flagged(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    (d / "plain.html").write_text('<input x-model="form.name"><input x-model="form.phoneticNote">', encoding="utf-8")
    assert pf.scan(_pages(d)) == {}


def test_reverse_control_exempting_everything_turns_red(tmp_path):
    """「全部寫進排除清單」不可以變綠。"""
    d = _copies(tmp_path)
    found = pf.scan(_pages(d))
    reg = {"forms": {p: {"not_natural_person": True, "fields": f, "reason": "x"} for p, f in found.items()}}
    errs = pf.violations(reg, pages=_pages(d), router_text="")
    assert any("contractors.html" in e and "強個資" in e for e in errs), errs
    assert any("payslip-form.html" in e and "強個資" in e for e in errs), errs
    reg2 = {"forms": {p: {"covered_by": p, "fields": f, "reason": "x"} for p, f in found.items()}}
    assert any("covered_by" in e for e in pf.violations(reg2, pages=_pages(d), router_text=""))


@pytest.mark.parametrize("page", [p for p, d in pf.load_registry()["forms"].items() if _is_notice_page(d)])
def test_reverse_control_removing_the_notice_card_turns_red(tmp_path, page):
    d = _copies(tmp_path)
    f = d / page
    f.write_text(f.read_text(encoding="utf-8").replace("data-privacy-card", "data-x"), encoding="utf-8")
    errs = pf.violations(pages=_pages(d))
    assert any(page in e and "data-privacy-card" in e for e in errs), errs


@pytest.mark.parametrize("page,idx,subject", _told_subjects(),
                         ids=lambda x: x if isinstance(x, str) else "")
def test_reverse_control_missing_ack_endpoint_turns_red(tmp_path, page, idx, subject):
    d = _copies(tmp_path)
    reg = copy.deepcopy(pf.load_registry())
    mod = subject.get("api_module")
    if mod is not None:
        from core import source_tree
        if not source_tree.module_installed("modules/%s/" % mod):
            pytest.skip("端點的模組 %s 不在這個安裝包（PLAYBOOK §B-11；模組在時照驗，見 test_api_module_only_waives_…）" % mod)
    api = subject["ack_api"][-1]
    routers = pf.product_router_text().replace(f'"{api}"', '"/api/gone"')
    errs = pf.violations(reg, pages=_pages(d), router_text=routers)
    assert any(page in e and api in e for e in errs), errs


def test_api_module_only_waives_the_endpoint_when_that_module_is_absent(tmp_path, monkeypatch):
    """`api_module`：模組在 ⇒ 端點照常比對（不可以因為登記了模組就免驗）；模組不在 ⇒ 不比對端點，告知區塊照驗。"""
    from core import source_tree
    d = _copies(tmp_path)
    reg = copy.deepcopy(pf.load_registry())
    page = next(p for p, v in reg["forms"].items() if "notice" in v)
    reg["forms"][page]["notice"]["api_module"] = "payroll"
    apis = reg["forms"][page]["notice"]["ack_api"]
    routers = pf.product_router_text()
    for a in apis:
        routers = routers.replace(f'"{a}"', '"/api/gone"')
    monkeypatch.setattr(source_tree, "module_installed", lambda p: True)
    mine = lambda errs: [e for e in errs if e.startswith(page + "：")]   # 不用 `page in e`：contractors.html 是 vendor-contractors.html 的子字串
    assert any(apis[0] in e for e in mine(pf.violations(reg, pages=_pages(d), router_text=routers)))
    monkeypatch.setattr(source_tree, "module_installed", lambda p: "modules/payroll/" not in str(p))
    assert not mine(pf.violations(reg, pages=_pages(d), router_text=routers))
    f = d / page
    f.write_text(f.read_text(encoding="utf-8").replace("data-privacy-card", "data-x"), encoding="utf-8")
    assert any("data-privacy-card" in e
               for e in mine(pf.violations(reg, pages=_pages(d), router_text=routers))), "模組不在時告知區塊仍要驗"


def test_reverse_control_new_field_on_exempt_page_turns_red(tmp_path):
    d = _copies(tmp_path)
    reg = pf.load_registry()
    page = next(p for p, v in reg["forms"].items() if not _is_notice_page(v))
    f = d / page
    f.write_text(f.read_text(encoding="utf-8") + '\n<input x-model="extra.personalEmail">', encoding="utf-8")
    errs = pf.violations(reg, pages=_pages(d))
    assert any(page in e and "fields" in e for e in errs), errs


def test_typed_contact_cannot_be_covered_by_a_master_form(tmp_path):
    """主持裁示 2026-09-26：手動輸入的聯絡人要有告知；只有 readonly／disabled 的欄位可以用 covered_by。"""
    d = _copies(tmp_path)
    reg = copy.deepcopy(pf.load_registry())
    page = d / "doc-x.html"
    page.write_text('<input x-model="doc.contactName">', encoding="utf-8")
    reg["forms"]["doc-x.html"] = {"covered_by": "customers.html", "fields": ["doc.contactName"], "reason": "x"}
    assert any("doc-x.html" in e and "手動輸入" in e for e in pf.violations(reg, pages=_pages(d)))
    page.write_text('<input x-model="doc.contactName" readonly>', encoding="utf-8")
    assert not [e for e in pf.violations(reg, pages=_pages(d)) if "doc-x.html" in e]
    page.write_text('<input x-model="doc.contactName" :disabled="!editable">', encoding="utf-8")
    assert any("doc-x.html" in e and "手動輸入" in e for e in pf.violations(reg, pages=_pages(d))), "依狀態的 :disabled 仍可手打"


def test_reverse_control_stale_decision_turns_red(tmp_path):
    d = _copies(tmp_path)
    reg = copy.deepcopy(pf.load_registry())
    reg["forms"]["removed-form.html"] = {"not_natural_person": True, "fields": [], "reason": "x"}
    assert any("removed-form.html" in e and "不存在" in e for e in pf.violations(reg, pages=_pages(d)))


# ── 逐欄（稽核 D PN-M1，主持裁示 2026-09-26）──────────────────────────────────────────

def _mine(page, errs):
    return [e for e in errs if e.startswith(page + "：")]


def test_reverse_control_new_field_on_a_notice_page_turns_red(tmp_path):
    """告知頁多一個個資欄位（例：出貨單的收件人）⇒ 轉紅，要有人決定它屬於哪一個當事人。"""
    d = _copies(tmp_path)
    for page, _, _ in _told_subjects():
        f = d / page
        orig = f.read_text(encoding="utf-8")
        f.write_text(orig + '\n<input x-model="foo.contactPhone">', encoding="utf-8")
        errs = _mine(page, pf.violations(pages=_pages(d)))
        assert any("foo.contactPhone" in e for e in errs), (page, errs)
        f.write_text(orig, encoding="utf-8")


def test_reverse_control_notice_without_fields_turns_red(tmp_path):
    d = _copies(tmp_path)
    reg = copy.deepcopy(pf.load_registry())
    reg["forms"]["users.html"]["notice"].pop("fields")
    assert any("逐欄" in e for e in _mine("users.html", pf.violations(reg, pages=_pages(d))))


def _two_subject_page(tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    markers = " ".join(pf.NOTICE_MARKERS)
    (d / "two.html").write_text(
        '<div data-privacy-card data-privacy-subject="a">' + markers + '</div>'
        '<div data-privacy-card data-privacy-subject="b"></div>'
        '<input x-model="x.contactName"><input x-model="y.recipient"><input x-model="y.address">', encoding="utf-8")
    reg = {"forms": {"two.html": {"notices": [
        {"subject": "a", "purpose": "contact", "ack_api": ["/api/a/ack"], "fields": ["x.contactName"]},
        {"subject": "b", "purpose": "contact", "ack_api": ["/api/b/ack"], "fields": ["y.address", "y.recipient"]}]}}}
    return d, reg


def test_positive_control_two_subjects_each_with_its_own_card(tmp_path):
    d, reg = _two_subject_page(tmp_path)
    assert pf.violations(reg, pages=_pages(d), router_text='"/api/a/ack" "/api/b/ack"') == []
    assert pf.scan(_pages(d))["two.html"] == ["x.contactName", "y.address", "y.recipient"], "簽收人（recipient）要掃得到"


def test_reverse_control_one_field_two_subjects_turns_red(tmp_path):
    d, reg = _two_subject_page(tmp_path)
    reg["forms"]["two.html"]["notices"][0]["fields"].append("y.recipient")
    errs = pf.violations(reg, pages=_pages(d), router_text='"/api/a/ack" "/api/b/ack"')
    assert any("同時屬於" in e for e in errs), errs


def test_reverse_control_second_subject_without_its_card_turns_red(tmp_path):
    d, reg = _two_subject_page(tmp_path)
    f = d / "two.html"
    f.write_text(f.read_text(encoding="utf-8").replace('data-privacy-subject="b"', ""), encoding="utf-8")
    errs = pf.violations(reg, pages=_pages(d), router_text='"/api/a/ack" "/api/b/ack"')
    assert any("b" in e and "data-privacy-subject" in e for e in errs), errs


def test_per_field_covered_by_follows_the_same_rules(tmp_path):
    """notices 裡逐欄的 covered_by：可手打 ⇒ 紅；靜態 readonly ⇒ 綠（同整頁的規則）。"""
    d, reg = _two_subject_page(tmp_path)
    f = d / "two.html"
    f.write_text(f.read_text(encoding="utf-8") + '<input x-model="s.salesEmail">', encoding="utf-8")
    reg["forms"]["users.html"] = pf.load_registry()["forms"]["users.html"]
    reg["forms"]["two.html"]["notices"].append({"subject": "sales", "covered_by": "users.html",
                                                "fields": ["s.salesEmail"], "reason": "x"})
    rt = '"/api/a/ack" "/api/b/ack"'
    assert any("手動輸入" in e for e in _mine("two.html", pf.violations(reg, pages=_pages(d), router_text=rt)))
    f.write_text(f.read_text(encoding="utf-8").replace('x-model="s.salesEmail"', 'x-model="s.salesEmail" readonly'),
                 encoding="utf-8")
    assert not _mine("two.html", pf.violations(reg, pages=_pages(d), router_text=rt))


@pytest.mark.parametrize("tag,expect", [
    ('<input x-model="d.contactName" readonly>', True),
    ('<input readonly x-model="d.contactName">', True),
    ('<input x-model="d.contactName" disabled="disabled">', True),
    ('<input x-model="d.contactName" :disabled="!editable">', False),
    # 稽核 D PN-S3：屬性值裡的同名單字不算
    ("""<input x-model="d.contactName" :class="{ 'opacity-50': disabled }">""", False),
    ('<input x-model="d.contactName" title="readonly when locked">', False),
    # 屬性值裡有 `=>`：標籤不可以在那裡截斷
    ('<input x-model="d.contactName" @keyup="e => go(e)" readonly>', True),
])
def test_not_typeable_only_counts_attribute_names(tag, expect):
    assert pf._not_typeable(tag, "d.contactName") is expect
