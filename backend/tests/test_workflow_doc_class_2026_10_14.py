# -*- coding: utf-8 -*-
"""BP-5 P0：單據風險類登錄（plain／money／ledger）與守門。
- 每一個簽核單據類型（含各模組登記的）都必須有合法的風險類；新增類型而漏分類 ⇒ 預設 money（最嚴），且此測試會抓到顯式缺漏
- 流程建構器可完整調整的只有 plain：目前只有完工單與出貨單；傳票是 ledger；其餘一律 money
- 登記失敗不留下半登記狀態"""
import importlib

import pytest

from helpers import tiered_approval as T

# 各模組在匯入時登記自己的類型；守門必須在它們都載入後才檢查
for _m in ("modules.case.material_approval", "modules.case.material_change", "modules.case.material_payment",
           "modules.payroll.api.payslip_approval", "modules.subcontract.api.dispatch_approval"):
    try:
        importlib.import_module(_m)
    except Exception:                      # 缺環境時退回只檢查內建九類（不讓守門本身因匯入失敗而消失）
        pass


def test_every_registered_doc_type_is_classified():
    missing = [c for c in T.APPROVAL_DOC_TYPES if c not in T.DOC_CLASS]
    assert not missing, missing
    assert all(v in T.DOC_CLASSES for v in T.DOC_CLASS.values())
    assert set(T.DOC_CLASS) == set(T.APPROVAL_DOC_TYPES)                # 沒有指向不存在類型的多餘項目


def test_builtin_classes_are_pinned():
    plain = {c for c in T._BUILTIN_DOC_TYPES if T.doc_class(c) == "plain"}
    assert plain == {"completion", "shipping"}                           # 放寬這個集合＝擴大建構器範圍，必須有人明確改測試
    assert T.doc_class("voucher") == "ledger"
    for c in ("quotation", "invoice_voucher", "payment_request", "contractor_voucher", "extra_expense", "bonus"):
        assert T.doc_class(c) == "money", c


def test_unknown_code_is_the_strictest_class():
    assert T.doc_class("never_registered") == "money"


def test_register_defaults_to_money_and_rejects_bad_class():
    code = "t62_probe_doc"
    try:
        T.register_doc_type(code, "探針")
        assert T.doc_class(code) == "money"
        with pytest.raises(ValueError):
            T.register_doc_type("t62_probe_bad", "壞", doc_class="plainish")
        assert "t62_probe_bad" not in T.APPROVAL_DOC_TYPES and "t62_probe_bad" not in T.DOC_CLASS   # 沒有半登記
        T.register_doc_type("t62_probe_plain", "探針二", doc_class="plain")
        assert T.doc_class("t62_probe_plain") == "plain"
    finally:
        for c in (code, "t62_probe_plain"):
            if c in T.APPROVAL_DOC_TYPES:
                T.APPROVAL_DOC_TYPES.remove(c)
            T.APPROVAL_DOC_TYPE_LABELS.pop(c, None)
            T.DOC_CLASS.pop(c, None)
            T.DEFAULT_UNIFIED_DOC_TYPES.discard(c)


def test_guard_is_sensitive_mutation_control():
    """正對照：把某類型從登錄拿掉，第一個守門要紅。"""
    saved = T.DOC_CLASS.pop("completion")
    try:
        assert [c for c in T.APPROVAL_DOC_TYPES if c not in T.DOC_CLASS] == ["completion"]
    finally:
        T.DOC_CLASS["completion"] = saved
