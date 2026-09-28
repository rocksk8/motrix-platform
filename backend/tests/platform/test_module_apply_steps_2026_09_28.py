# -*- coding: utf-8 -*-
"""backend/tools/module_apply_steps.py（apply_module_update.ps1 的 Python 步驟；B55 §1.3）。

① 疊加樹白名單（D 審 DB-M1）：只有 classify=="program" 的檔進去、.apply.lock 排除、模組換成包裡那一份；
   個資與帳密（db、logs、license.key、certs、初始帳密檔）一律不進（正對照＋逐項反向）。
② 載入狀態檔（D 審 DB-S4）：重啟之後、正在聽 port 的行程寫的，模組狀態與版本相符才過；舊檔、別的 pid、
   沒有行程、讀不到、壞 JSON、缺模組、失敗、版本不對 ⇒ 各自失敗並說原因。
③ 停用模組（D 審 DB-S5）：走 module_switches.set_enabled（與模組管理頁同一機制）。
"""
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "module_apply_steps", Path(__file__).resolve().parents[2] / "tools" / "module_apply_steps.py")
S = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(S)


def _w(root, rel, text="x"):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture()
def trees(tmp_path):
    inst, pkg = tmp_path / "inst", tmp_path / "pkg"
    for rel in ("backend/main.py", "backend/helpers/geo.py", "backend/modules/k/__init__.py", "backend/modules/k/old.py",
                "backend/modules/other/__init__.py"):
        _w(inst, rel, "code")
    secrets = ("backend/motrix_erp.db", "backend/motrix_erp_demo.db", "backend/logs/server.log",
               "backend/license.key", "backend/certs/cert.pem", "backend/.initial_admin_credentials.txt",
               "backend/heartbeat_config.json", "backend/db_backups/2026-09-28/motrix_erp.db", "backend/.apply.lock")
    for rel in secrets:
        _w(inst, rel, "SECRET")
    _w(pkg, "backend/modules/k/__init__.py", "new")
    _w(pkg, "backend/modules/k/new.py", "new")
    return inst, pkg, secrets


def test_overlay_copies_program_files_and_swaps_the_module(tmp_path, trees):
    inst, pkg, secrets = trees
    dest = tmp_path / "ov"
    n = S.build_overlay(inst, pkg, "k", dest)
    got = {p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()}
    assert {"backend/main.py", "backend/helpers/geo.py", "backend/modules/other/__init__.py",
            "backend/modules/k/__init__.py", "backend/modules/k/new.py"} <= got
    assert "backend/modules/k/old.py" not in got, "模組要換成包裡那一份（鏡像），不是疊上去"
    assert (dest / "backend/modules/k/__init__.py").read_text(encoding="utf-8") == "new"
    assert n == len(got)
    leaked = [r for r in secrets if r in got]
    assert not leaked, "個資／帳密／鎖進了疊加樹（%TEMP%）：%s" % leaked


def test_overlay_refuses_an_existing_dest_and_a_package_without_the_module(tmp_path, trees):
    inst, pkg, _s = trees
    (tmp_path / "ov").mkdir()
    with pytest.raises(ValueError):
        S.build_overlay(inst, pkg, "k", tmp_path / "ov")
    with pytest.raises(ValueError):
        S.build_overlay(inst, pkg, "nope", tmp_path / "ov2")


def _states(tmp_path, started, pid=4242, mods=None, **extra):
    p = tmp_path / "module_states.json"
    data = {"pid": pid, "started_at": started.isoformat(timespec="seconds"),
            "modules": mods if mods is not None else [{"key": "k", "state": "loaded", "version": "1.3.4", "reason": ""}]}
    data.update(extra)
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_states_pass_when_written_after_restart_by_the_listener(tmp_path):
    since = datetime.now().replace(microsecond=0)
    p = _states(tmp_path, since + timedelta(seconds=3))
    assert S.check_states(p, "k", since, [4242], "1.3.4") == (True, "")


@pytest.mark.parametrize("case,expect", [
    ("old_file", "重啟之前"),
    ("other_pid", "pid"),
    ("no_listener", "沒有任何行程"),
    ("missing_module", "沒有模組"),
    ("failed", "狀態是 failed"),
    ("wrong_version", "版本是 1.3.3"),
])
def test_states_fail_for_each_reason(tmp_path, case, expect):
    since = datetime.now().replace(microsecond=0)
    after = since + timedelta(seconds=3)
    pids = [4242]
    if case == "old_file":
        p = _states(tmp_path, since - timedelta(seconds=30))
    elif case == "other_pid":
        p = _states(tmp_path, after, pid=9999)
    elif case == "no_listener":
        p, pids = _states(tmp_path, after), []
    elif case == "missing_module":
        p = _states(tmp_path, after, mods=[])
    elif case == "failed":
        p = _states(tmp_path, after, mods=[{"key": "k", "state": "failed", "version": "1.3.4", "reason": "ImportError"}])
    else:
        p = _states(tmp_path, after, mods=[{"key": "k", "state": "loaded", "version": "1.3.3", "reason": ""}])
    ok, why = S.check_states(p, "k", since, pids, "1.3.4")
    assert not ok and expect in why, why


def test_states_unreadable_is_a_failure_not_a_pass(tmp_path):
    since = datetime.now()
    ok, why = S.check_states(tmp_path / "nope.json", "k", since, [1], "1")
    assert not ok and "還沒有載入狀態檔" in why
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    ok, why = S.check_states(bad, "k", since, [1], "1")
    assert not ok and "不是 JSON" in why


def test_states_disabled_check_for_the_restore_failed_path(tmp_path):
    """F13：回滾備份壞掉 ⇒ 停用該模組再重啟 ⇒ 要確認它是 disabled、不看版本。"""
    since = datetime.now().replace(microsecond=0)
    p = _states(tmp_path, since, mods=[{"key": "k", "state": "disabled", "version": "1.3.4", "reason": "停用"}])
    assert S.check_states(p, "k", since, [4242], None, "disabled") == (True, "")
    assert not S.check_states(p, "k", since, [4242], None, "loaded")[0]


def test_cli_prints_one_result_line(tmp_path, capsys):
    since = datetime.now().replace(microsecond=0)
    p = _states(tmp_path, since)
    assert S.main(["states", "--file", str(p), "--key", "k", "--since", since.isoformat(), "--pids", "4242",
                   "--version", "1.3.4"]) == 0
    assert capsys.readouterr().out.strip() == "STATES_OK"
    assert S.main(["states", "--file", str(p), "--key", "k", "--since", since.isoformat(), "--pids", "1"]) == 2
    assert capsys.readouterr().out.startswith("STATES_FAIL ")


def test_disable_goes_through_module_switches(monkeypatch):
    import helpers.module_switches as sw
    seen = []
    monkeypatch.setattr(sw, "set_enabled", lambda key, enabled: seen.append((key, enabled)) or [key])
    assert S.disable_module("k") == ["k"] and seen == [("k", False)]
