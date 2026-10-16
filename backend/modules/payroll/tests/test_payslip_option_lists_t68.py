# -*- coding: utf-8 -*-
"""T68 勞報單開立頁的下拉選項走「選項清單」（census #4）：預設逐項＝今天寫死的清單；扣繳相關的代碼只能改顯示名稱；舊值不被洗掉。"""
import re

from core.source_tree import page_file
from helpers import option_lists as OL

IDS = ("payslip_nationality", "payslip_income_type", "payslip_payment_method", "payslip_income_subtype")


def _bad(key, vals):
    return OL.definition_problems(key, {"version": 1, "values": vals}, live={})


def _paths(p):
    return {x["path"] for x in p}


def _defaults(key, **over):
    return [dict(d, **over) if over else dict(d) for d in OL.BUILTIN[key]["defaults"]]


def _items(src, name):
    body = re.search(name + r":\s*\[(.*?)\],\n", src, re.S).group(1)
    return re.findall(r"value:\s*'([^']+)',\s*label:\s*'([^']+)'", body)


def test_defaults_equal_the_values_the_form_page_used_to_hard_code():
    src = page_file("payslip-form.html").read_text(encoding="utf-8")
    for key, name in (("payslip_nationality", "NATIONALITY_ITEMS"), ("payslip_income_type", "INCOME_TYPE_ITEMS"), ("payslip_payment_method", "PAYMENT_METHOD_ITEMS")):
        assert _items(src, name) == [(d["value"], d["label"]) for d in OL.BUILTIN[key]["defaults"]], key
    sub = re.search(r"INCOME_SUBTYPES:\s*\[(.*?)\],\n", src, re.S).group(1)
    assert re.findall(r"'([^']+)'", sub) == [d["value"] for d in OL.BUILTIN["payslip_income_subtype"]["defaults"]]
    assert len(OL.BUILTIN["payslip_income_subtype"]["defaults"]) == 21
    # 今天的樣子：國籍三項、所得類別 50／9A／9B、付款方式 匯款／現金（頁面預設值也在清單裡）
    assert [d["value"] for d in OL.BUILTIN["payslip_income_type"]["defaults"]] == ["50", "9A", "9B"]
    assert "incomeType: '9A'" in src and "paymentMethod: '匯款'" in src and "contractorNationality: '本國籍'" in src
    for k in IDS:
        assert OL.effective(k) == [dict(d, disabled=False) for d in OL.BUILTIN[k]["defaults"]]      # 旗標關 ⇒ 預設


def test_tax_driving_lists_are_closed_labels_only():
    """國籍與所得類別的值決定扣繳 ⇒ 只能改顯示名稱與順序，不能新增、不能停用。"""
    for key in ("payslip_nationality", "payslip_income_type"):
        assert OL.BUILTIN[key]["closed"] is True and OL.BUILTIN[key]["relabel"] is True
        relabeled = _defaults(key)
        relabeled[0]["label"] = "改名後的名稱"
        assert _bad(key, relabeled) == [], key
        assert _bad(key, list(reversed(_defaults(key)))) == [], key
        added = _defaults(key) + [{"value": "新代碼", "label": "新代碼"}]
        assert any("不能新增" in x["message"] for x in _bad(key, added)), key
        disabled = _defaults(key)
        disabled[1]["disabled"] = True
        assert any("不能停用" in x["message"] for x in _bad(key, disabled)), key
        assert any("不能少" in x["message"] for x in _bad(key, _defaults(key)[:-1])), key


def test_payment_method_and_subtype_lists_can_grow_but_defaults_stay_and_labels_stay_as_values():
    pm = _defaults("payslip_payment_method") + [{"value": "支票", "label": "支票"}]
    assert _bad("payslip_payment_method", pm) == []
    pm_relabel = _defaults("payslip_payment_method")
    pm_relabel[0]["label"] = "電匯"
    assert "values[0].label" in _paths(_bad("payslip_payment_method", pm_relabel)), "付款方式的值就是顯示字，不能另外改名"
    assert any("不能少" in x["message"] for x in _bad("payslip_payment_method", [{"value": "現金", "label": "現金"}]))
    st = _defaults("payslip_income_subtype") + [{"value": "[91] 其他", "label": "[91] 其他"}]
    assert _bad("payslip_income_subtype", st) == []
    off = _defaults("payslip_income_subtype")
    off[0]["disabled"] = True
    assert _bad("payslip_income_subtype", off) == [], "細項可以停用（只是建議選項；已存的與自由輸入的文字都照常有效）"


def test_pages_wire_the_lists_and_keep_stored_values_visible():
    form = page_file("payslip-form.html").read_text(encoding="utf-8")
    assert '<script src="../static/option-lists.js"></script>' in form
    assert '<meta name="motrix-option-lists" content="%s">' % ",".join(IDS) in form
    assert "option-list-editor.js" not in form
    for key, cur in (("payslip_nationality", "q.contractorNationality"), ("payslip_income_type", "q.incomeType"), ("payslip_payment_method", "q.paymentMethod")):
        assert "optItems('%s'," % key in form and cur + ")" in form, key           # 目前這筆的值一併傳入 ⇒ 不在清單裡的舊值照原樣顯示
    assert "optValues('payslip_income_subtype'" in form and "motrix-options" in form and "optVer" in form
    assert '<option value="[10] 律師">' not in form, "細項建議選項不再寫死在頁面"
    assert form.count("async init()") == 1                                          # 不多一個 init（Alpine 雙重初始化守門）
    con = page_file("contractors.html").read_text(encoding="utf-8")
    assert '<meta name="motrix-option-lists" content="payslip_nationality">' in con and "optItems('payslip_nationality'," in con
    assert "motrix-options" in con and con.count("async init()") == 1
