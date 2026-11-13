# -*- coding: utf-8 -*-
"""T82 預跑紅燈修正：image_guard／xlsx_guard 不再用 `**` 轉發參數（test_case_summary_purpose 基準 0），簽章不變（L1 快照）。
本檔釘住改寫後的行為：with_limits 逐欄覆寫、rows 只收五個 iter_rows 關鍵字、run_decode 只轉發位置參數。"""
import asyncio

import pytest

from helpers import image_guard as G
from helpers import xlsx_guard as X


def test_with_limits_overrides_fields_and_rejects_unknown():
    lim = X.with_limits(max_cells=123, max_bytes=456)
    assert lim.max_cells == 123 and lim.max_bytes == 456 and lim.max_cols == X.DEFAULT.max_cols
    assert X.with_limits() == X.DEFAULT
    with pytest.raises((TypeError, ValueError)):
        X.with_limits(no_such_limit=1)


def test_limits_roundtrip_through_dict_like_the_child_process_does():
    from dataclasses import asdict
    lim = X.with_limits(max_cells=77, deadline_seconds=1.5)
    assert X._limits_from(asdict(lim)) == lim


class _WS:
    def __init__(self):
        self.seen = None

    def iter_rows(self, **kw):
        self.seen = kw
        return iter([("a",), ("b",), ("c",)])


def test_rows_passes_the_five_keywords_and_defaults_max_col_to_limits():
    ws = _WS()
    out = list(X.rows(ws, values_only=True, min_row=2))
    assert out == [("a",), ("b",), ("c",)]
    assert ws.seen == {"min_row": 2, "max_row": None, "min_col": None, "max_col": X.DEFAULT.max_cols, "values_only": True}
    ws2 = _WS()
    list(X.rows(ws2, max_col=3))
    assert ws2.seen["max_col"] == 3 and ws2.seen["values_only"] is False


def test_rows_rejects_unknown_keyword_and_still_enforces_max_rows():
    with pytest.raises(TypeError):
        list(X.rows(_WS(), bogus=1))
    with pytest.raises(X.XlsxRejected):
        list(X.rows(_WS(), max_rows=2))


def test_run_decode_forwards_positionals_and_rejects_keywords():
    async def go():
        assert await G.run_decode(lambda a, b: a + b, 1, 2) == 3
        with pytest.raises(TypeError):
            await G.run_decode(lambda a, b=0: a + b, 1, b=2)
    asyncio.run(go())


def test_with_decode_slot_wrapper_takes_positionals_only():
    @G.with_decode_slot
    def f(a, b):
        return a * b
    assert f(3, 4) == 12
    with pytest.raises(TypeError):
        f(3, b=4)
