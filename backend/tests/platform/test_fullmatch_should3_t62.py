# -*- coding: utf-8 -*-
"""SHOULD-3：附件子資料夾名與料號前綴用 fullmatch——結尾換行（`$` 會放行）必須被拒絕。"""
import pytest

from helpers import attachment_slots as AS
from helpers import option_lists as OL


@pytest.mark.parametrize("sub", ["abc", "報價單_1", "a-b"])
def test_subfolder_plain_names_still_pass_the_pattern(sub):
    assert AS._SUBFOLDER.fullmatch(sub)


@pytest.mark.parametrize("sub", ["abc\n", "abc\n\n", "\n"])
def test_subfolder_trailing_newline_fails(sub):
    assert not AS._SUBFOLDER.fullmatch(sub)
    assert AS._subfolder_problem(sub, "case") is not None


@pytest.mark.parametrize("pf", ["NET", "CCTV", "SW"])
def test_prefix_plain_values_still_pass(pf):
    assert OL._PREFIX_RE.fullmatch(pf)


@pytest.mark.parametrize("pf", ["NET\n", "NET\n\n", "SW\n"])
def test_prefix_trailing_newline_fails_in_definition_problems(pf):
    body = {"version": 1, "values": [{"value": "網通設備", "label": "網通設備", "prefix": pf}]}
    probs = OL.definition_problems("part_category", body, live={})
    assert any(p["path"] == "values[0].prefix" for p in probs), probs
