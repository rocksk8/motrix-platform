# -*- coding: utf-8 -*-
"""`_local_date_of`：簽核 requestedAt 的「日期」顯示要是本地日期（使用者 2026-10-01）。

舊資料裡報價單送審時間是前端 `toISOString()` 存的 UTC（帶 Z）；後端切前 10 碼會得到 UTC 日期——台灣 00:00–08:00 送審會顯示成前一天。
`_local_date_of` 只改顯示、不改資料：帶時區的先換成伺服器本地時區再取日期；不帶時區的（後端自己存的本地時間）照取前 10 碼。
"""
from datetime import datetime, timedelta, timezone

import pytest

import pdf_gen
from modules.case.api import quotations as Q

FUNCS = [pdf_gen._local_date_of, Q._local_date_of]


@pytest.mark.parametrize("fn", FUNCS)
def test_naive_local_strings_keep_their_first_ten_characters(fn):
    assert fn("2026-10-01T01:03:00") == "2026-10-01"
    assert fn("2026-10-01 01:03:00") == "2026-10-01"
    assert fn("2026-09-30T23:59:59.123456") == "2026-09-30"
    assert fn("2026-10-01") == "2026-10-01"


@pytest.mark.parametrize("fn", FUNCS)
def test_empty_and_unreadable_values_do_not_raise(fn):
    assert fn("") == "" and fn(None) == ""
    assert fn("not a date at all") == "not a date"          # 讀不懂 ⇒ 前 10 碼（與舊行為相同）


@pytest.mark.parametrize("fn", FUNCS)
def test_timezone_aware_strings_are_converted_to_the_server_local_date(fn):
    """帶 Z／偏移的先轉本地。期望值用獨立公式（UTC ＋ 本機位移）算，不呼叫被測函式自己的路徑。"""
    off = datetime.now().astimezone().utcoffset()
    for z in ("2026-09-30T16:30:00Z", "2026-09-30T23:59:59Z", "2026-10-01T00:00:00Z", "2026-12-31T20:00:00Z"):
        utc = datetime.fromisoformat(z.replace("Z", "+00:00"))
        assert fn(z) == (utc + off).strftime("%Y-%m-%d"), z
    # 帶 +08:00 的 01:03 ＝ UTC 前一天 17:03：本地日期由「絕對時刻」決定，不是字串前 10 碼
    a = "2026-10-01T01:03:00+08:00"
    assert fn(a) == (datetime.fromisoformat(a).astimezone(timezone.utc) + off).strftime("%Y-%m-%d")


@pytest.mark.parametrize("fn", FUNCS)
def test_taipei_example_when_the_server_runs_in_taipei(fn):
    if datetime.now().astimezone().utcoffset() != timedelta(hours=8):
        pytest.skip("這台不是 UTC+8；上一題已用獨立公式驗過換算")
    assert fn("2026-09-30T17:03:00Z") == "2026-10-01"       # 使用者回報的那一筆（10/01 01:03 台北）
    assert fn("2026-09-30T15:59:59Z") == "2026-09-30"
