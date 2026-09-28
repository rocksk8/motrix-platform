# -*- coding: utf-8 -*-
"""modtest 的 collect-only 子行程不帶建包獨佔旗標（2026-09-29 A 代理主持：第二十一班建包卡死）。

建包設 MOTRIX_PYTEST_EXCLUSIVE=1 並持有全機鎖；題目 test_ship_tests_adds_consumers_of_a_changed_provider 經
module_update.ship_tests 起子行程 `modtest --files … --dry-run --json`，它 collect-only 全部題目時繼承了這個旗標
⇒ conftest 判成重跑 ⇒ 排在自己的父行程（建包）後面等鎖，最多 90 分 ⇒ 建包停在 91%。
〔不改 conftest：鎖的守門題刻意用 collect-only 子行程當便宜的探針，改成「collect-only 一律不搶」會讓它們全紅〕
"""
import importlib.util
import subprocess
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "modtest_collect_env", Path(__file__).resolve().parents[2] / "tools" / "platform" / "modtest.py")
MT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(MT)


def test_collect_env_drops_only_the_build_exclusive_flags():
    env = MT._collect_env({"MOTRIX_PYTEST_EXCLUSIVE": "1", "MOTRIX_PYTEST_EXCLUSIVE_OWNER": "4711", "PATH": "x", "MOTRIX_E2E_MAX_WORKERS": "3"})
    assert env == {"PATH": "x", "MOTRIX_E2E_MAX_WORKERS": "3"}


def test_run_pytest_collect_only_uses_that_env(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setenv("MOTRIX_PYTEST_EXCLUSIVE", "1")
    monkeypatch.setattr(MT.subprocess, "run", fake_run)
    monkeypatch.setattr(MT, "_new_basetemp", lambda window, full: "C:/T/modtest-x")
    MT.run_pytest(["tests"], [], "x", False, collect_only=True)
    assert "--collect-only" in seen["cmd"]
    assert seen["env"] is not None and "MOTRIX_PYTEST_EXCLUSIVE" not in seen["env"], \
        "collect-only 子行程繼承了建包獨佔旗標 ⇒ 會排在建包自己後面等全機鎖（死鎖）"
