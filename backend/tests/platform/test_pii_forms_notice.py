# -*- coding: utf-8 -*-
"""守門：蒐集自然人個資的表單都要有個資蒐集告知（CUSTOMIZATION-SPEC §9.3；MODULE-GUIDE §11）。

清單 `docs/platform/pii_forms.json`（鍵＝頁面檔名），掃描規則 `_pii_forms.py`（頁面位置問 `core.source_tree.page_files()`）。
- 正對照①（不綁 L2）：暫存目錄裡一張有個資欄位、沒有決定的頁面 ⇒ 被抓到。
- 正對照②（使用者 2026-09-26 指定）：承攬人員名冊（R3 已有告知）要被掃到，而且決定是 notice。
- 反向控制：把所有決定都改成「非自然人」或「由別頁涵蓋」⇒ 轉紅；拿掉某一頁的告知區塊 ⇒ 轉紅；
  豁免頁多一個個資欄位 ⇒ 轉紅；過期的決定 ⇒ 轉紅；可以手打的欄位用 covered_by ⇒ 轉紅；
  `api_module` 的模組在 ⇒ 端點照驗（不在才免驗端點，PLAYBOOK §B-11）。
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


@pytest.mark.parametrize("page", [p for p, d in pf.load_registry()["forms"].items() if "notice" in d])
def test_reverse_control_removing_the_notice_card_turns_red(tmp_path, page):
    d = _copies(tmp_path)
    f = d / page
    f.write_text(f.read_text(encoding="utf-8").replace("data-privacy-card", "data-x"), encoding="utf-8")
    errs = pf.violations(pages=_pages(d))
    assert any(page in e and "data-privacy-card" in e for e in errs), errs


@pytest.mark.parametrize("page", [p for p, d in pf.load_registry()["forms"].items() if "notice" in d])
def test_reverse_control_missing_ack_endpoint_turns_red(tmp_path, page):
    d = _copies(tmp_path)
    reg = copy.deepcopy(pf.load_registry())
    mod = reg["forms"][page]["notice"].get("api_module")
    if mod is not None:
        from core import source_tree
        if not source_tree.module_installed("modules/%s/" % mod):
            pytest.skip("端點的模組 %s 不在這個安裝包（PLAYBOOK §B-11；模組在時照驗，見 test_api_module_only_waives_…）" % mod)
    api = reg["forms"][page]["notice"]["ack_api"][-1]
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
    page = next(p for p, v in reg["forms"].items() if "notice" not in v)
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
