# -*- coding: utf-8 -*-
"""A7：前端 `static/download.js` 的純函式題（解析 Content-Disposition）＋與後端 `content_disposition()` 的往返一致。

沒有 node 的機器會略過——⚠️ skip 不是驗過。
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from helpers import download_name as D

JS = Path(__file__).resolve().parents[2] / "frontend" / "static" / "download.js"


def _run(cases):
    node = shutil.which("node")
    if not node:
        pytest.skip("這台機器沒有 node —— ⚠️ skip 不是驗過")
    script = ("var window = {};\n" + JS.read_text(encoding="utf-8") + "\n"
              "var cases = " + json.dumps(cases) + ";\n"
              "console.log(JSON.stringify(cases.map(function (c) {\n"
              "  return window.MotrixDownload.nameFrom({headers: {get: function () { return c.h }}}, c.fb)\n"
              "})));")
    out = subprocess.run([node], input=script, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr[-600:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_parse_basic_forms():
    cases = [
        {"h": "attachment; filename*=UTF-8''%E5%AE%8C%E5%B7%A5%E5%96%AE.pdf", "fb": "x.pdf"},
        {"h": 'attachment; filename="a.pdf"', "fb": "x.pdf"},
        {"h": 'attachment; filename="ascii.pdf"; filename*=UTF-8\'\'%E4%B8%AD.pdf', "fb": "x.pdf"},
        {"h": "", "fb": "fallback.pdf"},
        {"h": None, "fb": ""},
        {"h": "attachment; filename*=ISO-8859-1''%E4.pdf; filename=\"plain.pdf\"", "fb": "x.pdf"},
        {"h": "attachment; filename=\"../../evil.exe\"", "fb": "x.pdf"},
    ]
    got = _run(cases)
    assert got == ["完工單.pdf", "a.pdf", "中.pdf", "fallback.pdf", "download", "plain.pdf", ".._.._evil.exe"]


def test_roundtrip_with_backend_header():
    names = ["Q2026-0001_新竹廠區網路建置_完工單_CN0007.pdf", "Q-1 完工單(A,B);'x'=1.pdf", "😀報價單.pdf", "勞報單_王小明_20261013_第2次.pdf"]
    cases = [{"h": D.content_disposition(n), "fb": "x"} for n in names]
    got = _run(cases)
    assert got == [D._clean(n) for n in names]
