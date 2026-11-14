# -*- coding: utf-8 -*-
"""T87 A1 M1 演練的「不可能碰到正式機、而且要能證明」三道防線（tools/platform/a1_drill_preflight.py）。
全部用假探針與 tmp 目錄；**不連任何非本機位址**（測試檔本身也有守門）。每一項各有一個單獨失敗就整體不過的反向控制。"""
import json
import socket
import sys
from pathlib import Path

import pytest

PLATFORM_TOOLS = Path(__file__).resolve().parents[3] / "tools" / "platform"
sys.path.insert(0, str(PLATFORM_TOOLS))
import a1_drill_preflight as PF  # noqa: E402

PROD = PF.PROD_IP
GOOD_ROOT = r"D:\Claude-pm\a1-drill\20261114_220000"


class FakeProbes:
    def __init__(self, task=False, listening=(), ips=("192.168.1.5",), raise_on=(), route="ROUTE Ethernet 10.0.0.1"):
        self.task, self.listening, self.ips, self.raise_on, self.route = task, set(listening), set(ips), set(raise_on), route

    def _maybe(self, what):
        if what in self.raise_on:
            raise RuntimeError("探針壞了：" + what)

    def scheduled_task_exists(self, name):
        self._maybe("task")
        return self.task

    def is_listening(self, port):
        self._maybe("listen")
        return port in self.listening

    def local_ips(self):
        self._maybe("ips")
        return self.ips

    def route_info(self, ip):
        self._maybe("route")
        return self.route


def _failed(rows):
    return [r[0] for r in rows if not r[1]]


# ── 第 1 道 ─────────────────────────────────────────────────────────────

def test_all_good_passes_and_checks_every_item():
    rows = PF.check(GOOD_ROOT, FakeProbes())
    assert _failed(rows) == []
    labels = " ".join(r[0] for r in rows)
    for needle in ("排程工作", "演練路徑", "6766", "8766", "666", "本機不是正式機"):
        assert needle in labels, needle
    assert PF.require_ok(GOOD_ROOT, FakeProbes())


def test_check_has_no_ping_or_tcp_to_the_prod_machine():
    """PM：preflight 不再主動 ping 或連線正式機；Probes 沒有這類方法，check() 的列也不含正式機位址。"""
    assert not hasattr(PF.Probes, "ping") and not hasattr(PF.Probes, "tcp_reach")
    for _label, _ok, detail in PF.check(GOOD_ROOT, FakeProbes(ips=(PROD,))) + PF.check(GOOD_ROOT, FakeProbes()):
        assert PROD not in detail, "訊息裡不記錄正式機位址"


@pytest.mark.parametrize("probe_kw,expected", [
    ({"task": True}, "排程工作不存在"),
    ({"listening": (6766,)}, "ERP 埠 6766"),
    ({"listening": (8766,)}, "儀表板埠 8766"),
    ({"listening": (666,)}, "正式 ERP 埠 666"),
    ({"ips": (PROD,)}, "本機不是正式機"),
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


@pytest.mark.parametrize("what", ["task", "listen", "ips"])
def test_a_probe_that_cannot_answer_counts_as_a_failure_not_a_pass(what):
    rows = PF.check(GOOD_ROOT, FakeProbes(raise_on=(what,)))
    bad = [r for r in rows if not r[1]]
    assert bad and all("無法確認" in r[2] for r in bad), (what, bad)
    with pytest.raises(PF.DrillAbort):
        PF.require_ok(GOOD_ROOT, FakeProbes(raise_on=(what,)))


def test_route_note_is_information_only_and_never_raises():
    assert "ROUTE" in PF.route_note(FakeProbes())
    assert "無結果" in PF.route_note(FakeProbes(route=None))
    assert "無結果" in PF.route_note(FakeProbes(raise_on=("route",)))


def test_main_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(PF, "Probes", lambda: FakeProbes())
    assert PF.main(["--root", GOOD_ROOT]) == 0
    assert "可以建演練" in capsys.readouterr().out
    monkeypatch.setattr(PF, "Probes", lambda: FakeProbes(task=True))
    assert PF.main(["--root", GOOD_ROOT]) == 1
    assert "不可以演練" in capsys.readouterr().out


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


# ── 第 2 道：靜態掃描 ───────────────────────────────────────────────────

def _drill_dir(tmp_path, ps1_root=None, port=6766, bat_port=6766, bat_host="127.0.0.1", extra=None):
    root = tmp_path / "a1-drill" / "inst"
    (root / "backend" / "tools").mkdir(parents=True)
    pr = ps1_root if ps1_root is not None else str(root)
    (root / "backend" / "tools" / "apply_update.ps1").write_text(
        '# x\n$ProdRoot = "%s"\n$Port = %d\nWrite-Host ok\n' % (pr, port), encoding="utf-8-sig")
    (root / "backend" / "tools" / "rollback_update.ps1").write_text(
        '$ProdRoot = "%s"\n$Port = %d\n' % (pr, port), encoding="utf-8-sig")
    (root / "backend" / "autostart.bat").write_text(
        '@echo off\n"py" -m uvicorn main:app --port %d --host %s\n' % (bat_port, bat_host), encoding="utf-8")
    (root / "backend" / "modules.lock.json").write_text('{"modules": {}}', encoding="utf-8")
    for rel, text in (extra or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def test_static_scan_clean_drill_dir_passes(tmp_path):
    root = _drill_dir(tmp_path)
    res = PF.static_scan(root)
    assert res["findings"] == [] and res["files"] >= 3
    assert PF.require_static_ok(root)["files"] >= 3


@pytest.mark.parametrize("extra,needle", [
    ({"backend\\.env": "ERP=%s\n" % PROD}, "正式機位址"),
    ({"backend/settings.json": '{"host": "%s"}' % PROD}, "正式機位址"),
    ({"backend/tools/copy.ps1": 'cd C:\\Users\\Motrix\\Desktop\\V9.0\n'}, "V9.0"),
    ({"backend/.env": "MOTRIX_DELIVERY_ERP_URL=https://example.invalid:666\n"}, "ERP 位址不是本機"),
    ({"backend/.env.local": "MOTRIX_DELIVERY_ERP_URL=https://127.0.0.1@evil.example/\n"}, "ERP 位址不是本機"),
    ({"backend/cfg.ini": "erp_url = http://10.0.0.5:666\n"}, "ERP 位址不是本機"),
    ({"backend/dash.yaml": "base_url: http://myhost:8765\n"}, "ERP 位址不是本機"),
])
def test_static_scan_finds_prod_references_and_non_local_erp_urls(tmp_path, extra, needle):
    root = _drill_dir(tmp_path, extra={k.replace("\\", "/"): v for k, v in extra.items()})
    res = PF.static_scan(root)
    assert any(needle in why for _rel, why in res["findings"]), res
    with pytest.raises(PF.DrillAbort) as ei:
        PF.require_static_ok(root)
    assert "不啟動演練" in str(ei.value)
    assert PROD not in str(ei.value), "錯誤訊息不重複正式機位址"


def test_static_scan_allows_loopback_erp_urls(tmp_path):
    root = _drill_dir(tmp_path, extra={"backend/.env": "MOTRIX_DELIVERY_ERP_URL=https://127.0.0.1:6766\nerp_url=http://localhost:6766\nERP=http://[::1]:6766\n"})
    assert PF.static_scan(root)["findings"] == []


def test_static_scan_extra_patterns_for_the_prod_host_name(tmp_path):
    root = _drill_dir(tmp_path, extra={"backend/notes.json": '{"h": "MOTRIX-PROD-PC"}'})
    assert PF.static_scan(root)["findings"] == []
    assert any("禁用字串" in w for _r, w in PF.static_scan(root, extra_patterns=("motrix-prod-pc",))["findings"])


def test_static_scan_ps1_prodroot_and_port_must_point_at_the_drill(tmp_path):
    root = _drill_dir(tmp_path, ps1_root=r"C:\Users\Motrix\Desktop\x")
    f = PF.static_scan(root)["findings"]
    assert any("$ProdRoot 沒有指向演練目錄" in w for _r, w in f)
    assert {r for r, w in f if "$ProdRoot" in w} == {"backend\\tools\\apply_update.ps1", "backend\\tools\\rollback_update.ps1"}, "回復腳本也必須是演練副本"
    root2 = _drill_dir(tmp_path / "b", port=666)
    assert any("$Port 不是演練埠" in w for _r, w in PF.static_scan(root2)["findings"])
    root3 = _drill_dir(tmp_path / "c")
    (root3 / "backend" / "tools" / "apply_update.ps1").write_text('$ProdRoot = "a"\n$ProdRoot = "b"\n$Port = 6766\n', encoding="utf-8")
    assert any("恰好一行" in w for _r, w in PF.static_scan(root3)["findings"]), "不猜：多一行就拒絕"


def test_static_scan_autostart_must_bind_loopback_and_drill_port(tmp_path):
    assert any("--port 6766" in w for _r, w in PF.static_scan(_drill_dir(tmp_path / "a", bat_port=666))["findings"])
    assert any("127.0.0.1" in w for _r, w in PF.static_scan(_drill_dir(tmp_path / "b", bat_host="0.0.0.0"))["findings"])


def test_static_scan_missing_pieces_cannot_be_confirmed_so_they_fail(tmp_path):
    root = _drill_dir(tmp_path)
    (root / "backend" / "autostart.bat").unlink()
    (root / "backend" / "tools" / "apply_update.ps1").unlink()
    why = " ".join(w for _r, w in PF.static_scan(root)["findings"])
    assert "找不到腳本副本" in why and "找不到演練用的 autostart.bat" in why
    empty = tmp_path / "empty"
    empty.mkdir()
    assert any("無法確認" in w for _r, w in PF.static_scan(empty)["findings"])


def test_static_scan_skips_docs_tests_and_source_folders_that_mention_the_prod_machine_legitimately(tmp_path):
    root = _drill_dir(tmp_path, extra={"docs/x.json": '{"h": "%s"}' % PROD, "tests/y.json": '{"h": "%s"}' % PROD, "backend/logs/z.json": PROD})
    assert PF.static_scan(root)["findings"] == []


# ── 第 3 道：動態監看 ───────────────────────────────────────────────────

class FakeSampler:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def __call__(self, pids):
        self.calls.append(list(pids))
        item = self.script.pop(0) if self.script else {"tree": [1], "conns": []}
        if isinstance(item, Exception):
            raise item
        return item


def _mon(tmp_path, script, killed=None, **kw):
    return PF.ConnectionMonitor(tmp_path / "mon.jsonl", lambda: [100], interval=0.01, sampler=FakeSampler(script),
                                killer=(lambda tree: killed.append(list(tree))) if killed is not None else (lambda tree: None), **kw)


def _c(remote, pid=1, port=443, state="Established"):
    return {"pid": pid, "remote": remote, "port": port, "state": state}


def test_monitor_clean_run_logs_every_tick_and_states_zero_prod_connections(tmp_path):
    m = _mon(tmp_path, [{"tree": [100, 101], "conns": [_c("127.0.0.1", port=6766), _c("::1", port=8766)]}] * 3)
    for _ in range(3):
        assert m.tick() == []
    m.check_clean()
    s = m.summary()
    assert s["ticks"] == 3 and s["prod_connections"] == 0 and s["non_loopback_connections"] == 0 and s["tripped"] is False
    assert "對正式機 0 連線" in s["statement"] and "取樣有間隔" in s["statement"]
    lines = [json.loads(x) for x in (tmp_path / "mon.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 3 and all("conns" in x for x in lines)


def test_monitor_prod_connection_kills_the_tree_trips_and_aborts(tmp_path):
    killed = []
    m = _mon(tmp_path, [{"tree": [100, 101, 102], "conns": [_c("127.0.0.1"), _c(PROD, pid=101, port=666)]}], killed=killed)
    bad = m.tick()
    assert [b["kind"] for b in bad] == ["prod"] and killed == [[100, 101, 102]]
    assert m.summary()["prod_connections"] == 1 and m.summary()["tripped"] is True
    with pytest.raises(PF.DrillAbort) as ei:
        m.check_clean()
    assert "已殺掉程序樹並中止" in str(ei.value)
    log = (tmp_path / "mon.jsonl").read_text(encoding="utf-8")
    assert "TRIPPED" in log


def test_monitor_any_non_loopback_address_trips_not_only_the_prod_one(tmp_path):
    killed = []
    m = _mon(tmp_path, [{"tree": [100], "conns": [_c("142.250.1.1")]}], killed=killed)
    assert [b["kind"] for b in m.tick()] == ["non_loopback"] and killed
    assert m.summary()["prod_connections"] == 0 and m.summary()["non_loopback_connections"] == 1


def test_monitor_ipv4_mapped_loopback_and_127_net_are_clean(tmp_path):
    m = _mon(tmp_path, [{"tree": [1], "conns": [_c("::ffff:127.0.0.1"), _c("127.0.0.5"), _c("::")]}])
    assert m.tick() == [] and not m.tripped


def test_monitor_sample_failure_is_counted_and_logged_not_silently_clean(tmp_path):
    m = _mon(tmp_path, [RuntimeError("PowerShell 沒回"), {"tree": [1], "conns": []}])
    m.tick()
    m.tick()
    s = m.summary()
    assert s["sample_errors"] == 1 and s["ticks"] == 2
    assert "PowerShell 沒回" in (tmp_path / "mon.jsonl").read_text(encoding="utf-8")


def test_monitor_killer_failure_is_still_recorded_and_trips(tmp_path):
    def boom(tree):
        raise OSError("殺不掉")
    m = PF.ConnectionMonitor(tmp_path / "m.jsonl", lambda: [1], interval=0.01, sampler=FakeSampler([{"tree": [1], "conns": [_c(PROD)]}]), killer=boom)
    m.tick()
    assert m.tripped and "kill_error" in (tmp_path / "m.jsonl").read_text(encoding="utf-8")


def test_monitor_thread_runs_and_stops_on_trip(tmp_path):
    import time
    m = _mon(tmp_path, [{"tree": [1], "conns": []}, {"tree": [1], "conns": [_c(PROD)]}], killed=[])
    m.start()
    for _ in range(100):
        if m.tripped:
            break
        time.sleep(0.05)
    m.stop()
    assert m.tripped and m.ticks >= 2


def test_monitor_passes_the_current_roots_each_tick(tmp_path):
    pids = [[100]]
    sampler = FakeSampler([])
    m = PF.ConnectionMonitor(tmp_path / "m.jsonl", lambda: pids[0], interval=0.01, sampler=sampler, killer=lambda t: None)
    m.tick()
    pids[0] = [100, 200]
    m.tick()
    assert sampler.calls == [[100], [100, 200]]


NETSTAT_SAMPLE = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1000
  TCP    127.0.0.1:6766         127.0.0.1:50000        ESTABLISHED     200
  TCP    192.168.1.5:50001      @@PROD@@:666           ESTABLISHED     201
  TCP    192.168.1.5:50002      142.250.1.1:443        TIME_WAIT       0
  TCP    [::1]:8766             [::1]:50003            ESTABLISHED     202
  TCP    [fe80::1%12]:50004     [fe80::2%12]:445       ESTABLISHED     203
  UDP    0.0.0.0:5353           *:*                                    300
""".replace("@@PROD@@", PROD)


def test_parse_netstat_keeps_tcp_non_listening_rows_with_remote_host_and_pid():
    rows = PF.parse_netstat(NETSTAT_SAMPLE)
    assert [r["pid"] for r in rows] == [200, 201, 0, 202, 203], rows
    assert rows[1]["remote"] == PROD and rows[1]["port"] == 666
    assert rows[3]["remote"] == "::1" and rows[4]["remote"] == "fe80::2"
    bad = PF.violations(rows)
    assert sorted(b["kind"] for b in bad) == ["non_loopback", "non_loopback", "prod"], bad


def test_positive_control_passes_with_a_real_sampler_and_fails_with_a_blind_one(tmp_path):
    """這台機器的 Get-NetTCPConnection 查不到任何東西（假綠燈）：取樣器必須先看得到本行程剛開的連線，否則演練中止。"""
    good = PF.ConnectionMonitor(tmp_path / "g.jsonl", lambda: [], interval=0.01)       # 真取樣器（PowerShell 程序樹＋netstat）
    assert good.positive_control() is True
    blind = PF.ConnectionMonitor(tmp_path / "b.jsonl", lambda: [], interval=0.01, sampler=lambda pids: {"tree": list(pids), "conns": []})
    with pytest.raises(PF.DrillAbort) as ei:
        blind.positive_control()
    assert "監看器是瞎的" in str(ei.value)


def test_real_sampler_tree_includes_the_given_pid_and_filters_connections_to_the_tree():
    import os
    snap = PF.ConnectionMonitor._ps_sample([os.getpid()])
    assert os.getpid() in snap["tree"]
    assert all(c["pid"] in set(snap["tree"]) for c in snap["conns"])


def test_test_file_never_opens_a_connection_to_a_non_local_address():
    """守門：本檔只准對本機（srv.getsockname()）開連線，不 ping、不呼叫外部程式。"""
    import re
    text = Path(__file__).read_text(encoding="utf-8")
    calls = re.findall(r"create_connection\(([^)]*)\)", text)
    assert all(c.strip() == "srv.getsockname()" for c in calls), calls
    assert ("ping" + " -n") not in text and ("sub" + "process") not in text


def test_known_product_files_are_skipped_but_listed_and_new_files_mentioning_prod_still_fail(tmp_path):
    root = _drill_dir(tmp_path, extra={"backend/setup_autostart_task.ps1": "cd C:/prod/V9.0\n",
                                       "backend/version_manifest.json": '{"h": "%s"}' % PROD})
    res = PF.static_scan(root)
    assert res["findings"] == []
    assert sorted(res["allowed_product_files"]) == [r"backend\setup_autostart_task.ps1", r"backend\version_manifest.json"]
    root2 = _drill_dir(tmp_path / "n", extra={"backend/new_tool.ps1": "cd C:/prod/V9.0\n"})
    assert any(r == r"backend\new_tool.ps1" for r, _w in PF.static_scan(root2)["findings"])


def test_the_files_the_drill_runs_or_rewrites_are_never_on_the_allowlist():
    low = {k.lower() for k in PF.KNOWN_PRODUCT_FILES}
    for must_be_rewritten in (r"backend\tools\apply_update.ps1", r"backend\tools\rollback_update.ps1", r"backend\autostart.bat"):
        assert must_be_rewritten not in low
