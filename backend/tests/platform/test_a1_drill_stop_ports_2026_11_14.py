"""A1 演練收尾（stop_drill_processes）：多輪、殼先殺、演練埠類別（2026-11-14 演練：重生的 ERP 被漏掉 ⇒ 檔案被鎖）。"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))

import a1_drill_preflight as PF  # noqa: E402


def test_stop_drill_processes_runs_multiple_passes_shells_first(monkeypatch):
    """2026-11-14 演練：autostart 迴圈在被殺的瞬間重生 ERP，單輪收尾漏掉它 ⇒ 檔案被鎖、之後每個情境都還原失敗。
    ⇒ 多輪：每輪殼（cmd）先殺，殺完再查，查不到才停；已殺過的 pid 不重複殺。"""
    passes = [[{"id": 5000, "name": "python.exe", "created": 1, "verified": True}, {"id": 4000, "name": "cmd.exe", "created": 1, "verified": True}],
              [{"id": 5000, "name": "python.exe", "created": 1, "verified": True}, {"id": 6000, "name": "python.exe", "created": 2, "verified": False}],
              []]
    seen_ports = []

    def fake_owned(records, base, start, me=None, ports=()):
        seen_ports.append(tuple(ports))
        return passes.pop(0)

    monkeypatch.setattr(PF, "owned_processes", fake_owned)
    killed = []
    out = PF.stop_drill_processes(r"D:\Claude-pm\a1-drill\x", [], 0, killer=killed.append, ports=(6866, 8866), sleep=lambda s: None)
    assert killed == [4000, 5000, 6000] and out == killed
    assert seen_ports == [(6866, 8866)] * 3


def test_stop_drill_processes_gives_up_after_max_passes(monkeypatch):
    n = []
    monkeypatch.setattr(PF, "owned_processes", lambda *a, **k: n.append(1) or [{"id": 7000 + len(n), "name": "python.exe", "created": 1, "verified": True}])
    killed = []
    PF.stop_drill_processes("x", [], 0, killer=killed.append, sleep=lambda s: None)
    assert len(killed) == PF.STOP_MAX_PASSES                      # 永遠殺不完也不會無限迴圈


def test_owned_processes_port_class_finds_orphan_uvicorn_without_drill_dir_in_cmdline(tmp_path):
    """真的 PowerShell、真的程序（正對照）：命令列沒有演練目錄、父程序也不在清單裡，但是 `uvicorn main:app --port <演練埠>` ⇒ 要被找到；沒給埠就不能找到。"""
    import subprocess
    import sys
    import time
    port = 6877
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "uvicorn", "main:app", "--port", str(port)],
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        time.sleep(1.5)
        if p.pid < PF.MIN_KILL_PID:
            pytest.skip("pid 太小（硬性規則不殺）")
        with_port = [o["id"] for o in PF.owned_processes([], str(tmp_path / "no-such-drill"), 0, ports=(port,))]
        without = [o["id"] for o in PF.owned_processes([], str(tmp_path / "no-such-drill"), 0)]
        other_port = [o["id"] for o in PF.owned_processes([], str(tmp_path / "no-such-drill"), 0, ports=(port + 1,))]
        assert p.pid in with_port
        assert p.pid not in without and p.pid not in other_port
    finally:
        p.kill()
        p.wait(10)
