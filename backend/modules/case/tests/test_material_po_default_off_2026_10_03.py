# -*- coding: utf-8 -*-
"""33-M1 出貨預設＝關（反向控制）：`material_approval.PO_REQUIRED` 預設 False 時，材料申請的流程與第 32 包逐位相同——
手動新增（沒有採購單連結）可存、可送審、可核准；設成 True 才強制（同一組操作被擋）。
M1 案件側 UI 上線的那個 commit 把預設翻成 True，並把本檔的 `test_default_is_off` 改成 `is True`、第一題改成「預設即強制」。"""
import json

import db
import pytest
from modules.case import material_approval as MA
from modules.case.tests.test_material_po_required_2026_10_03 import _ap, _mo, _orders, _patch, _submit_mo
from modules.case.tests.test_purchase_item_lines_2026_10_02 import NO, W  # noqa: F401


def test_default_is_off():
    import importlib
    assert importlib.import_module("modules.case.material_approval").PO_REQUIRED is False


def test_with_the_rule_off_a_manual_request_saves_and_submits_like_package_32(W):
    c, h = W
    assert not MA.PO_REQUIRED
    res = _patch(c, h, [_mo("m1")])
    assert not res.get("rejected"), res
    assert _orders()[0]["itemId"] == "m1" and "poDocCode" not in _orders()[0] and _ap("m1")["status"] == "草稿"
    r = _submit_mo(c, h, "m1")
    assert r.status_code == 200, r.text                                    # 沒有採購單也能送審（出貨預設關）
    assert _ap("m1")["status"] in ("待審核", "簽核中", "已核准")


def test_with_the_rule_on_the_same_operations_are_refused(W, monkeypatch):
    c, h = W
    monkeypatch.setattr(MA, "PO_REQUIRED", True)
    res = _patch(c, h, [_mo("m2")])
    assert [x["code"] for x in res["rejected"]] == ["po_required"]
    assert _orders() == [] and _ap("m2") is None
