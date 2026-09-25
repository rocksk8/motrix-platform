"""自 `tests/test_bonus_award_2026_09_23.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import importlib
import json
import re
import sqlite3
from pathlib import Path
import pytest
import db
from tests.test_bonus_award_2026_09_23 import (  # noqa: E402,F401  含 fixture
    _BACKEND,
    _FRONTEND,
)


def test_reports_has_no_second_copy_of_the_bonus_coefficients():
    """tests/test_bonus_award_2026_09_23.py 那一題的營運報表部分：報表只讀已存值，不可以有第二份乘法。"""
    src = (_BACKEND / "modules/analytics/api/reports.py").read_text(encoding="utf-8")
    hits = ["%d %s" % (i, line.strip()[:60]) for i, line in enumerate(src.splitlines(), 1)
            if re.search(r"\*\s*0\.10\b|\*\s*0\.01\b", line)]
    assert not hits, "營運報表有第二份係數：" + "；".join(hits)


def test_the_reports_fallback_to_gross_profit_really_exists():
    """⚙️ **證明「退回用毛利」那個前例是真的** —— 它是 `FN2` 禁令二的理由。

    ```
    routers/reports.py:340
      int(settle.get("netProfit") or settle.get("grossProfit") or 0)
    ```
    ☠️ 少了這一題，禁令二建立在**一段我沒有跑過的描述**上。
    🔑 而它同時說明為什麼那個禁令難守：**那個 fallback 對報表是合理的** ——
       它不是一段爛碼，它是一段**在別的脈絡下正確**的碼。
    📌 〈同一段碼在新脈絡下的風險不同〉。
    """
    src = (_BACKEND / "modules" / "analytics" / "api" / "reports.py").read_text(encoding="utf-8")
    assert re.search(r'settle\.get\("netProfit"\)\s*or\s*settle\.get\("grossProfit"\)',
                     src), (
        "`reports.py` 裡找不到 `netProfit or grossProfit` 的 fallback ——\n"
        + "🔑 它被改掉了 ⇒ **禁令二的理由要重寫**（那是好消息）。")
