# -*- coding: utf-8 -*-
"""測試不可留下永不刪的暫存目錄（使用者 2026-09-30：「盡可能降低硬碟的重複寫入」；PLAYBOOK §G-寫入 #9）。

`tempfile.mkdtemp()` 建的目錄不會被 pytest 的 basetemp 清掉：每跑一輪就多一個（曾累積 167 個 `motrix-C-fn1*`）。
規則：測試檔若呼叫 `mkdtemp(`，同一檔內必須有清除（`rmtree`／`rmdir`／`atexit`）；能用 `tmp_path` 就用 `tmp_path`。
守門是靜態掃描（不跑測試）；`_leaks()` 純函式用合成資料做正對照／反向控制。
"""
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
CLEANERS = ("rmtree", "rmdir", "atexit", "TemporaryDirectory")


def _leaks(text: str) -> bool:
    return "mkdtemp(" in text and not any(c in text for c in CLEANERS)


def _test_files():
    for root in (BACKEND / "tests", BACKEND / "modules"):
        for p in root.rglob("test_*.py"):
            if "__pycache__" in p.parts:
                continue
            yield p


def test_no_test_file_creates_a_tempdir_it_never_removes():
    bad = [str(p.relative_to(BACKEND)) for p in _test_files()
           if p.resolve() != Path(__file__).resolve() and _leaks(p.read_text(encoding="utf-8", errors="replace"))]
    assert not bad, "這些測試檔用 mkdtemp() 卻沒有任何清除（改用 tmp_path，或加 atexit／rmtree）：%s" % bad


def test_leak_detector_positive_and_negative_control():
    assert _leaks("d = tempfile.mkdtemp()\n")
    assert not _leaks("d = tempfile.mkdtemp()\natexit.register(shutil.rmtree, d, True)\n")
    assert not _leaks("def test_x(tmp_path):\n    pass\n")
