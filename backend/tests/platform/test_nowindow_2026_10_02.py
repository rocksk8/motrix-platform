# -*- coding: utf-8 -*-
"""背景工具預設不跳視窗（tools/platform/nowindow.py；演練與作者端守門集用）。純函式題＋冪等／關閉開關題。
反向控制：DETACHED_PROCESS／CREATE_NEW_CONSOLE 由呼叫端自負責，不被偷改；非 Windows 什麼都不做。"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "platform"))
import nowindow as NW  # noqa: E402

pytestmark = pytest.mark.skipif(os.name != "nt", reason="只有 Windows 有主控台視窗問題")


def test_with_hidden_adds_no_window_and_sw_hide():
    flags, si = NW.with_hidden(0x00004000)                      # 原本有 BELOW_NORMAL
    assert flags & NW.CREATE_NO_WINDOW and flags & 0x00004000
    assert si.dwFlags & subprocess.STARTF_USESHOWWINDOW and si.wShowWindow == NW.SW_HIDE


def test_with_hidden_leaves_detached_and_new_console_alone():
    for f in (NW.DETACHED_PROCESS, NW.CREATE_NEW_CONSOLE, NW.DETACHED_PROCESS | 0x200):
        flags, _ = NW.with_hidden(f)
        assert not flags & NW.CREATE_NO_WINDOW and flags & f == f


def test_with_hidden_is_a_noop_off_windows():
    assert NW.with_hidden(5, None, nt=False) == (5, None)


def test_install_is_idempotent_patches_popen_and_respects_the_opt_out(monkeypatch):
    orig = subprocess.Popen.__init__
    seen = {}

    class Fake:
        _motrix_nowindow = False

        def __init__(self, *a, **kw):
            seen.update(kw)
    monkeypatch.setattr(subprocess, "Popen", Fake)
    monkeypatch.setenv("MOTRIX_SHOW_WINDOWS", "1")
    assert NW.install() is False and Fake.__init__ is not orig and not getattr(Fake, "_motrix_nowindow")      # 開關：不安裝
    monkeypatch.delenv("MOTRIX_SHOW_WINDOWS")
    assert NW.install() is True and Fake._motrix_nowindow is True
    patched = Fake.__init__
    assert NW.install() is True and Fake.__init__ is patched                                                   # 冪等
    Fake(["x"])
    assert seen["creationflags"] & NW.CREATE_NO_WINDOW and seen["startupinfo"].wShowWindow == NW.SW_HIDE
