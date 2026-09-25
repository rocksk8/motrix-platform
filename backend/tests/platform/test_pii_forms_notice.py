# -*- coding: utf-8 -*-
"""守門：蒐集自然人個資的表單都要有個資蒐集告知（CUSTOMIZATION-SPEC §9.3；MODULE-GUIDE §11）。

清單 `docs/platform/pii_forms.json`，掃描規則 `_pii_forms.py`。
- 正對照①（不綁 L2）：暫存目錄裡一張有個資欄位、沒有決定的頁面 ⇒ 被抓到。
- 正對照②（使用者 2026-09-26 指定）：承攬人員名冊（R3 已有告知）要被掃到，而且決定是 notice。
- 反向控制：把所有決定都改成「非自然人」或「由別頁涵蓋」⇒ 轉紅；拿掉某一頁的告知區塊 ⇒ 轉紅；
  豁免頁多一個個資欄位 ⇒ 轉紅；過期的決定 ⇒ 轉紅。
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
    assert "frontend/pages/contractors.html" in found, "承攬人員名冊（已有 R3 告知）掃不到 ⇒ 偵測規則壞了，清單不能算完整"
    assert "form.id_number" in found["frontend/pages/contractors.html"]
    assert "notice" in pf.load_registry()["forms"]["frontend/pages/contractors.html"]


# ── 用暫存目錄做的正對照與反向控制 ──────────────────────────────────────────────

def _mini_repo(tmp_path):
    """複製真的頁面與 router 到暫存目錄（突變只動複本）。"""
    root = tmp_path / "repo"
    shutil.copytree(pf.REPO / "frontend" / "pages", root / "frontend" / "pages")
    shutil.copytree(pf.REPO / "backend" / "routers", root / "backend" / "routers",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return root


def test_new_pii_page_without_decision_turns_red(tmp_path):
    root = tmp_path / "r"
    (root / "frontend" / "pages").mkdir(parents=True)
    (root / "backend" / "routers").mkdir(parents=True)
    (root / "frontend" / "pages" / "new-form.html").write_text(
        '<input x-model.trim="form.contactPerson"><input x-model="item.mobile">', encoding="utf-8")
    errs = pf.violations(root, {"forms": {}})
    assert any("new-form.html" in e and "沒有決定" in e for e in errs), errs
    assert pf.scan(root)["frontend/pages/new-form.html"] == ["form.contactPerson", "item.mobile"]


def test_page_without_pii_is_not_flagged(tmp_path):
    root = tmp_path / "r"
    (root / "frontend" / "pages").mkdir(parents=True)
    (root / "frontend" / "pages" / "plain.html").write_text(
        '<input x-model="form.name"><input x-model="form.phoneticNote">', encoding="utf-8")
    assert pf.scan(root) == {}


def test_reverse_control_exempting_everything_turns_red(tmp_path):
    """「全部寫進排除清單」不可以變綠。"""
    root = _mini_repo(tmp_path)
    found = pf.scan(root)
    reg = {"forms": {p: {"not_natural_person": True, "fields": f, "reason": "x"} for p, f in found.items()}}
    errs = pf.violations(root, reg)
    assert any("contractors.html" in e and "強個資" in e for e in errs), errs
    assert any("payslip-form.html" in e and "強個資" in e for e in errs), errs
    reg2 = {"forms": {p: {"covered_by": p, "fields": f, "reason": "x"} for p, f in found.items()}}
    assert any("covered_by" in e for e in pf.violations(root, reg2))


@pytest.mark.parametrize("page", [p for p, d in pf.load_registry()["forms"].items() if "notice" in d])
def test_reverse_control_removing_the_notice_card_turns_red(tmp_path, page):
    root = _mini_repo(tmp_path)
    f = root / page
    f.write_text(f.read_text(encoding="utf-8").replace("data-privacy-card", "data-x"), encoding="utf-8")
    errs = pf.violations(root)
    assert any(page in e and "data-privacy-card" in e for e in errs), errs


@pytest.mark.parametrize("page", [p for p, d in pf.load_registry()["forms"].items() if "notice" in d])
def test_reverse_control_missing_ack_endpoint_turns_red(tmp_path, page):
    root = _mini_repo(tmp_path)
    reg = copy.deepcopy(pf.load_registry())
    api = reg["forms"][page]["notice"]["ack_api"][-1]
    for r in (root / "backend" / "routers").glob("*.py"):
        r.write_text(r.read_text(encoding="utf-8").replace(f'"{api}"', '"/api/gone"'), encoding="utf-8")
    errs = pf.violations(root, reg)
    assert any(page in e and api in e for e in errs), errs


def test_reverse_control_new_field_on_exempt_page_turns_red(tmp_path):
    root = _mini_repo(tmp_path)
    reg = pf.load_registry()
    page = next(p for p, d in reg["forms"].items() if "notice" not in d)
    f = root / page
    f.write_text(f.read_text(encoding="utf-8") + '\n<input x-model="extra.personalEmail">', encoding="utf-8")
    errs = pf.violations(root, reg)
    assert any(page in e and "fields" in e for e in errs), errs


def test_reverse_control_stale_decision_turns_red(tmp_path):
    root = _mini_repo(tmp_path)
    reg = copy.deepcopy(pf.load_registry())
    reg["forms"]["frontend/pages/removed-form.html"] = {"not_natural_person": True, "fields": [], "reason": "x"}
    assert any("removed-form.html" in e and "不存在" in e for e in pf.violations(root, reg))
