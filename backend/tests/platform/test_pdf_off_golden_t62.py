# -*- coding: utf-8 -*-
"""T62 旗標全關的 PDF／HTML 輸出 golden（稽核 SHOULD-3：『旗標關 ⇒ 輸出逐位元相同』原本只是推論）。

做法：`pdf_golden/cases.json` 是固定的合成輸入（沒有真實資料）；`pdf_golden/expected_platform.json` 是用 **origin/platform 1e231ea9e（正式機 H1）**
的 builder、在同一個凍結時鐘下跑出來的 HTML（用純 python 產生，不是 pytest）。本題在 T62 樹上用同樣輸入、同樣時鐘跑同一批 builder，**逐字串相等**。
涵蓋：報價單（客戶版／內部版／浮水印）、出貨單（草稿／已核准）、請款單、完工單、勞報單、開票申請憑據、外包憑據、結案報表。
未涵蓋：專案執行報告（_build_project_execution_report_html）、PDF 之外的預覽端點、真正走 Edge 的渲染（硬化後的 HTML 另由 H2 題驗證）。
更新方式：『故意』改了輸出時才重新產生 expected（用新的 platform 基準重跑 cases.json）；不可為了讓題目變綠而改 expected。
備註（稽核項 7，主持另行處理）：正式機 TEMP 路徑若含 `#` 或 `?`，硬化會拒絕渲染所有 PDF——本題不涵蓋，由主持確認。
"""
import datetime as _dt
import importlib
import json
from pathlib import Path

import pytest

HERE = Path(__file__).with_name("pdf_golden")
CASES = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
EXPECTED = json.loads((HERE / "expected_platform.json").read_text(encoding="utf-8"))


class _FrozenDT(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 14, 12, 0, 0)


class _FrozenDate(_dt.date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 14)


def _build(case, monkeypatch):
    mod, fn = case["builder"].split(":")
    m = importlib.import_module(mod)
    for nm, obj in (("datetime", _FrozenDT), ("date", _FrozenDate)):
        if hasattr(m, nm):
            monkeypatch.setattr(m, nm, obj)
    return getattr(m, fn)(*case["args"], **case["kwargs"])


def test_every_case_has_a_frozen_platform_output():
    assert sorted(c["name"] for c in CASES) == sorted(EXPECTED)
    assert all(isinstance(v, str) and "<html" in v.lower() and len(v) > 2000 for v in EXPECTED.values())


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_flags_off_output_equals_the_platform_output(case, client, monkeypatch):
    got = _build(case, monkeypatch)
    exp = EXPECTED[case["name"]]
    if got != exp:
        i = next((k for k, (a, b) in enumerate(zip(got, exp)) if a != b), min(len(got), len(exp)))
        pytest.fail("%s：與 platform 輸出不同（長度 %d vs %d，第一個差異在 %d）\nT62: …%r\nplat: …%r" % (case["name"], len(got), len(exp), i, got[max(0, i - 60):i + 80], exp[max(0, i - 60):i + 80]))


def test_the_golden_is_sensitive_to_a_published_decor_template(client, monkeypatch):
    """正對照：一旦有已發布的頁尾／浮水印範本（旗標開），輸出就必須和 golden 不同——否則這組 golden 驗不到 decorate_pdf 的掛鉤。"""
    from helpers import export_templates as ET
    quote = next(c for c in CASES if c["name"] == "quote_customer_draft")
    monkeypatch.setattr(ET, "resolve", lambda e, conn=None: {"version": 1, "format": "pdf", "footer": {"text": "機密"}} if e == "case:quotation-pdf" else None)
    assert _build(quote, monkeypatch) != EXPECTED["quote_customer_draft"]
