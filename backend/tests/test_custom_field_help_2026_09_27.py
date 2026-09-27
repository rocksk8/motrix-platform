# -*- coding: utf-8 -*-
"""自訂模組欄位選填說明 `help`（使用者 2026-09-27 試用意見：「帶入公式需要註解或是說明這公式是甚麼」；CORE 1.57，只新增）。

沒填 ⇒ 與舊版一樣沒有問題；文字且不超過 HELP_MAX ⇒ 沒有問題；非文字或過長 ⇒ `fields[i].help` 問題。
"""
from helpers import custom_modules as CM

KEY = "help_probe"


def _body(**extra):
    f = {"key": "total", "label": "總值", "type": "formula", "formula": "qty * unit_value"}
    f.update(extra)
    return {
        "name": "說明測試", "icon": "box", "permission": "custom.help_probe",
        "numbering": {"prefix": "HP", "date": "YYYYMMDD", "digits": 4},
        "fields": [
            {"key": "qty", "label": "數量", "type": "number"},
            {"key": "unit_value", "label": "單價", "type": "number"},
            f,
        ],
        "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿", "final": True}], "transitions": []},
    }


def _paths(body):
    return {p["path"]: p["message"] for p in CM.validate_module(body, KEY)}


def test_help_is_optional_and_a_short_text_is_accepted():
    assert _paths(_body()) == {}
    assert _paths(_body(help="依數量與單價計算")) == {}
    assert _paths(_body(help="字" * CM.HELP_MAX)) == {}


def test_help_that_is_not_text_or_too_long_is_a_problem_on_that_field():
    for bad in (123, ["x"], "字" * (CM.HELP_MAX + 1)):
        got = _paths(_body(help=bad))
        assert set(got) == {"fields[2].help"}, (bad, got)
        assert str(CM.HELP_MAX) in got["fields[2].help"]
