# -*- coding: utf-8 -*-
"""helpers.validation（第 49 班 W1-c-P2）：旗標只收真布林；字串 "false"／"0"／"" 永遠不是 true。"""
import pytest
from fastapi import HTTPException

from helpers.validation import body_flag, strict_bool


@pytest.mark.parametrize("v,want", [(True, True), (False, False), (1, True), (0, False)])
def test_real_booleans_and_01_pass(v, want):
    assert strict_bool(v, "x") is want


@pytest.mark.parametrize("v", ["false", "False", "0", "1", "true", "", "no", None, 2, -1, 1.0, [], {}, [True]])
def test_everything_else_is_422(v):
    with pytest.raises(HTTPException) as e:
        strict_bool(v, "accept_warnings")
    assert e.value.status_code == 422 and "accept_warnings" in str(e.value.detail)


def test_body_flag_missing_none_and_default():
    assert body_flag(None, "a") is False and body_flag({}, "a") is False and body_flag({"a": None}, "a") is False
    assert body_flag({}, "a", True) is True and body_flag({"a": None}, "a", True) is True
    assert body_flag({"a": False}, "a", True) is False and body_flag({"a": True}, "a") is True
    with pytest.raises(HTTPException):
        body_flag({"a": "false"}, "a")
    with pytest.raises(HTTPException):
        body_flag({"a": ""}, "a", True)
