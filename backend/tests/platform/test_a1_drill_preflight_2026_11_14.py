# -*- coding: utf-8 -*-
"""T87 A1 M1 演練前環境檢查（tools/platform/a1_drill_preflight.py）：全部用假的探針，不碰本機網路、排程工作或正式機。
重點：每一項各有一個「單獨失敗就整體不過」的反向控制；無法確認＝不通過；連線被拒＝連得到主機＝不通過。"""
import socket
import sys
from pathlib import Path

import pytest

PLATFORM_TOOLS = Path(__file__).resolve().parents[3] / "tools" / "platform"
sys.path.insert(0, str(PLATFORM_TOOLS))
import a1_drill_preflight as PF  # noqa: E402

GOOD_ROOT = r"D:\Claude-pm\a1-drill\20261114_220000"


class FakeProbes:
    def __init__(self, task=False, listening=(), reach="unreachable", ping=False, ips=("192.168.1.5",), raise_on=()):
        self.task, self.listening, self.reach, self.ping_ok, self.ips, self.raise_on = task, set(listening), reach, ping, set(ips), set(raise_on)
        self.reach_calls = []

    def _maybe(self, what):
        if what in self.raise_on:
            raise RuntimeError("探針壞了：" + what)

    def scheduled_task_exists(self, name):
        self._maybe("task")
        return self.task

    def is_listening(self, port):
        self._maybe("listen")
        return port in self.listening

    def tcp_reach(self, host, port, timeout=3):
        self._maybe("tcp")
        self.reach_calls.append((host, port))
        return self.reach

    def ping(self, host):
        self._maybe("ping")
        return self.ping_ok

    def local_ips(self):
        self._maybe("ips")
        return self.ips


def _failed(rows):
    return [r[0] for r in rows if not r[1]]


def test_all_good_passes_and_checks_every_item():
    rows = PF.check(GOOD_ROOT, FakeProbes())
    assert _failed(rows) == []
    labels = " ".join(r[0] for r in rows)
    for needle in ("排程工作", "演練路徑", "6766", "8766", "666", "本機不是正式機", "ping", "172.16.10.177:666", "172.16.10.177:8765"):
        assert needle in labels, needle
    assert PF.require_ok(GOOD_ROOT, FakeProbes())


@pytest.mark.parametrize("probe_kw,expected", [
    ({"task": True}, "排程工作不存在"),
    ({"listening": (6766,)}, "ERP 埠 6766"),
    ({"listening": (8766,)}, "儀表板埠 8766"),
    ({"listening": (666,)}, "正式 ERP 埠 666"),
    ({"ips": ("172.16.10.177",)}, "本機不是正式機"),
    ({"ping": True}, "ping 不通"),
    ({"reach": "open"}, "連不上"),
    ({"reach": "refused"}, "連不上"),
])
def test_each_single_failure_blocks_the_drill(probe_kw, expected):
    rows = PF.check(GOOD_ROOT, FakeProbes(**probe_kw))
    assert any(expected in f for f in _failed(rows)), (probe_kw, _failed(rows))
    with pytest.raises(PF.DrillAbort) as ei:
        PF.require_ok(GOOD_ROOT, FakeProbes(**probe_kw))
    assert "不執行演練" in str(ei.value)


@pytest.mark.parametrize("root", [
    r"D:\Claude-pm\a1-drill\V9.0\x", r"D:\Claude-pm\a1-drill\x\v9.0", r"C:\Users\Motrix\Desktop\V9.0",
    r"D:\Claude-pm\a1-drill", r"D:\Claude-pm\a1-drillX\x", r"D:\other\a1-drill\x", "relative\\a1-drill\\x",
    r"D:\Claude-pm\a1-drill\..\..\x",
])
def test_bad_drill_paths_are_refused(root):
    assert "演練路徑" in _failed(PF.check(root, FakeProbes()))


def test_forward_slash_and_case_do_not_hide_v9():
    assert "演練路徑" in _failed(PF.check("D:/Claude-pm/a1-drill/v9.0/x", FakeProbes()))


@pytest.mark.parametrize("what", ["task", "listen", "tcp", "ping", "ips"])
def test_a_probe_that_cannot_answer_counts_as_a_failure_not_a_pass(what):
    rows = PF.check(GOOD_ROOT, FakeProbes(raise_on=(what,)))
    bad = [r for r in rows if not r[1]]
    assert bad and all("無法確認" in r[2] for r in bad), (what, bad)
    with pytest.raises(PF.DrillAbort):
        PF.require_ok(GOOD_ROOT, FakeProbes(raise_on=(what,)))


def test_failure_messages_name_every_failed_item():
    with pytest.raises(PF.DrillAbort) as ei:
        PF.require_ok(GOOD_ROOT, FakeProbes(task=True, ping=True, listening=(8766,)))
    msg = str(ei.value)
    assert msg.count("✗") == 3 and "排程工作" in msg and "ping" in msg and "8766" in msg


def test_main_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(PF, "Probes", lambda: FakeProbes())
    assert PF.main(["--root", GOOD_ROOT]) == 0
    assert "可以演練" in capsys.readouterr().out
    monkeypatch.setattr(PF, "Probes", lambda: FakeProbes(task=True))
    assert PF.main(["--root", GOOD_ROOT]) == 1
    assert "不可以演練" in capsys.readouterr().out


# ── 真探針的判斷邏輯（只打本機、不碰正式機）────────────────────────────────

def test_real_is_listening_distinguishes_listening_from_refused():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert PF.Probes().is_listening(port) is True
    finally:
        srv.close()
    assert PF.Probes().is_listening(port) is False, "關掉之後連線被拒＝沒人聽"


def test_real_tcp_reach_maps_open_and_refused_on_loopback():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert PF.Probes().tcp_reach("127.0.0.1", port) == "open"
    finally:
        srv.close()
    assert PF.Probes().tcp_reach("127.0.0.1", port) == "refused"


def test_real_probe_never_contacts_the_prod_address_in_tests():
    """守門：這個測試檔不得對 172.16.10.177 發任何真連線（單元測試只准用假探針）。"""
    text = Path(__file__).read_text(encoding="utf-8")
    assert ("Probes()." + "tcp_reach(\"172.") not in text and ("Probes()." + "ping(") not in text
