# -*- coding: utf-8 -*-
"""33-M1 強制採購單的出貨預設（案件側 UI 上線後＝開）：`material_approval.PO_REQUIRED` 預設 True——新申請沒有採購單連結就存不了、送不了；
設成 False（運維回退，舊流程＝第 32 包行為）時手動新增可存可送審。回退開關保留：規則本身與 UI 的導引文字不受影響。"""
import pytest
from modules.case import material_approval as MA
from modules.case.tests.test_material_po_required_2026_10_03 import _ap, _mo, _orders, _patch, _submit_mo
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401


def test_default_is_on():
    import importlib
    assert importlib.import_module("modules.case.material_approval").PO_REQUIRED is True


def test_by_default_a_manual_request_without_po_is_refused(W):
    c, h = W
    assert MA.PO_REQUIRED
    res = _patch(c, h, [_mo("m2")])
    assert [x["code"] for x in res["rejected"]] == ["po_required"]
    assert _orders() == [] and _ap("m2") is None


def test_with_the_rule_switched_off_the_old_flow_works_like_package_32(W, monkeypatch):
    c, h = W
    monkeypatch.setattr(MA, "PO_REQUIRED", False)
    res = _patch(c, h, [_mo("m1")])
    assert not res.get("rejected"), res
    assert _orders()[0]["itemId"] == "m1" and "poDocCode" not in _orders()[0] and _ap("m1")["status"] == "草稿"
    r = _submit_mo(c, h, "m1")
    assert r.status_code == 200, r.text
