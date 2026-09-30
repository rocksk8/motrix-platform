# -*- coding: utf-8 -*-
"""fake_clock（行程時鐘平移）、boundary_days（邊界日矩陣）、collect_determinism（收集決定性）、建包腳本的接線。

時鐘類的題在**子行程**裡換時鐘，本行程的時鐘不動。
"""
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from datetime import date, datetime
from pathlib import Path

import pytest

from tests._subproc import probe_pytest_args, run_python, utf8_env

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
PLAT = REPO / "tools" / "platform"
if str(PLAT) not in sys.path:
    sys.path.insert(0, str(PLAT))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FC = _load("_fake_clock_t", PLAT / "fake_clock.py")
BD = _load("_boundary_days_t", PLAT / "boundary_days.py")
CD = _load("_collect_determinism_t", PLAT / "collect_determinism.py")
PS1 = (BACKEND / "tools" / "build_deploy_package.ps1").read_text(encoding="utf-8-sig")


# ── fake_clock ────────────────────────────────────────────────────────────────

def test_parse_accepts_three_shapes_and_rejects_the_rest():
    assert FC.parse("2026-02-28T23:59:30") == datetime(2026, 2, 28, 23, 59, 30)
    assert FC.parse("2026-02-28 23:59:30") == datetime(2026, 2, 28, 23, 59, 30)
    assert FC.parse("2026-02-28") == datetime(2026, 2, 28, 12, 0, 0)
    for bad in ("", "tomorrow", "2026-13-01", "2026/02/28", "2026-02-30T00:00:00"):
        with pytest.raises(ValueError):
            FC.parse(bad)


def test_delta_to_makes_now_equal_target():
    real = datetime(2026, 10, 1, 8, 0, 0)
    assert FC.delta_to(datetime(2026, 10, 31, 8, 0, 0), real) == 30 * 86400
    assert FC.delta_to(datetime(2026, 10, 1, 7, 59, 0), real) == -60


_CLOCK_PROBE = """
import sys, time, datetime
sys.path.insert(0, %(plat)r)
import fake_clock as fc
target = fc.parse(%(target)r)
fc.install(target)
from datetime import date, datetime as DT, timezone
now = DT.now()
assert abs((now - target).total_seconds()) < 5, now
assert date.today() == target.date(), date.today()
assert DT.today().date() == target.date()
assert abs(time.time() - target.timestamp()) < 5
t1 = time.time(); time.sleep(0.05); t2 = time.time()
assert t2 > t1, "時鐘沒有往前走（應該是平移不是凍結）"
assert abs(DT.now(timezone.utc).timestamp() - target.timestamp()) < 5
assert abs(DT.utcnow().timestamp() - DT.now(timezone.utc).replace(tzinfo=None).timestamp()) < 86400
assert time.localtime().tm_year == target.year and time.localtime().tm_mday == target.day
assert isinstance(date.today(), datetime.date) and isinstance(DT.now(), datetime.datetime)
assert (date.today() - date(2020, 1, 1)).days > 0 and (DT.now() - DT(2020, 1, 1)).days > 0
assert DT.strptime('2026-01-02', '%%Y-%%m-%%d').year == 2026
fc.uninstall()
assert abs((DT.now() - datetime.datetime.now()).total_seconds()) < 5
print('PROBE-OK')
"""


@pytest.mark.parametrize("target", ["2026-02-28T23:59:30", "2028-02-29T12:00:00", "2026-12-31T12:00:00", "2026-03-01T00:01:00"])
def test_fake_clock_shifts_the_process_clock_and_keeps_it_ticking(target):
    p = run_python(["-c", _CLOCK_PROBE % {"plat": str(PLAT), "target": target}], cwd=BACKEND, timeout=60)
    assert p.returncode == 0 and "PROBE-OK" in p.stdout, p.stdout[-400:] + p.stderr[-800:]


def test_without_install_nothing_is_patched():
    p = run_python(["-c", "import sys; sys.path.insert(0, %r); import fake_clock, datetime, time; "
                          "assert datetime.date.__name__ == 'date' and time.time.__name__ == 'time'; print('PLAIN')" % str(PLAT)],
                   cwd=BACKEND, timeout=60)
    assert "PLAIN" in p.stdout, p.stderr[-400:]


def test_fake_clock_as_a_pytest_plugin_applies_before_tests_and_rejects_a_bad_value(tmp_path):
    t = tmp_path / "t"
    t.mkdir()
    (t / "test_probe.py").write_text(textwrap.dedent("""
        from datetime import date, datetime
        def test_fake_today():
            assert date.today().isoformat() == "2026-02-28", date.today()
            assert datetime.now().month == 2
    """), encoding="utf-8")
    env = utf8_env(PYTHONPATH=str(PLAT), MOTRIX_FAKE_NOW="2026-02-28T12:00:00", MOTRIX_PYTEST_LOCK=str(tmp_path / "lock"))
    p = run_python(["-m", "pytest", "-q", "-p", "fake_clock", "-p", "no:cacheprovider", "--basetemp=%s" % (tmp_path / "bt-adhoc"),
                    *probe_pytest_args(t / "test_probe.py")], cwd=BACKEND, env=env, timeout=120)
    assert p.returncode == 0 and "1 passed" in p.stdout, (p.stdout + p.stderr)[-600:]
    env = utf8_env(PYTHONPATH=str(PLAT), MOTRIX_FAKE_NOW="garbage", MOTRIX_PYTEST_LOCK=str(tmp_path / "lock"))
    p = run_python(["-m", "pytest", "-q", "-p", "fake_clock", "-p", "no:cacheprovider", "--basetemp=%s" % (tmp_path / "bt2-adhoc"),
                    *probe_pytest_args(t / "test_probe.py")], cwd=BACKEND, env=env, timeout=120)
    assert p.returncode != 0, "壞的 MOTRIX_FAKE_NOW 被靜默略過（等於以為固定了其實沒有）"


# ── boundary_days ───────────────────────────────────────────────────────────────

def _sc(ref):
    return {n: d for n, d in BD.scenarios(ref)}


def test_scenarios_cover_month_year_midnight_and_leap_edges():
    s = _sc(date(2026, 9, 30))
    assert s["month_first"] == datetime(2026, 9, 1, 12)
    assert s["month_end"] == datetime(2026, 9, 30, 12)
    assert s["year_end"] == datetime(2026, 12, 31, 12)
    assert s["pre_midnight"] == datetime(2026, 9, 30, 23, 59)
    assert s["post_midnight"] == datetime(2026, 10, 1, 0, 1), "23:59 之後的 00:01 要跨月"
    assert s["leap_day"] == datetime(2028, 2, 29, 12)
    assert _sc(date(2026, 2, 10))["month_end"] == datetime(2026, 2, 28, 12), "二月月底（非閏年）"
    assert _sc(date(2028, 2, 10))["month_end"] == datetime(2028, 2, 29, 12), "二月月底（閏年）"
    assert _sc(date(2026, 12, 31))["post_midnight"] == datetime(2027, 1, 1, 0, 1), "年底跨年"
    assert _sc(date(2028, 2, 29))["leap_day"] == datetime(2028, 2, 29, 12), "ref 就是閏日"
    assert _sc(date(2028, 3, 1))["leap_day"] == datetime(2032, 2, 29, 12)
    assert [n for n, _ in BD.scenarios(date(2026, 9, 30))] == list(BD.SCENARIO_NAMES)


def test_files_from_collect_and_judge_and_env():
    out = "tests/test_a.py::test_1\ntests\\test_a.py::test_2[x]\nmodules/case/tests/test_b.py::T::t\n\n3 tests collected\n"
    assert BD.files_from_collect(out) == ["tests/test_a.py", "modules/case/tests/test_b.py"]
    c = [{"nodeid": "a::1", "kind": "FAILED", "msg": ""}]
    s = [{"nodeid": "a::1", "kind": "FAILED", "msg": ""}, {"nodeid": "b::2", "kind": "FAILED", "msg": "x"}]
    assert [f["nodeid"] for f in BD.judge(c, s)] == ["b::2"], "control 也紅的題被算成邊界日紅"
    e = BD.scenario_env(datetime(2026, 10, 1, 0, 1))
    assert e["MOTRIX_FAKE_NOW"] == "2026-10-01T00:01:00" and e["MOTRIX_TEST_TODAY"] == "2026-10-01" and str(PLAT) in e["PYTHONPATH"]
    cmd = BD.build_cmd("py", ["tests/a.py"], "bt")
    assert "date_sensitive" in cmd and "--basetemp=bt" in cmd and "-n" not in cmd, "邊界日矩陣必須單程序（輕，不搶全機鎖）"


class _Runner:
    def __init__(self, collect_out="tests/test_a.py::t1\ntests/test_a.py::t2\n", control="1 passed\n", scen=None, rcs=None):
        self.calls, self.collect_out, self.control, self.scen, self.rcs = [], collect_out, control, scen or {}, rcs or {}

    def run(self, argv, cwd, env=None, stream=False, low=False, timeout=None):
        self.calls.append({"argv": list(argv), "env": env or {}, "low": low, "cwd": str(cwd)})
        if "--collect-only" in argv:
            return self.rcs.get("collect", 0), self.collect_out
        name = (env or {}).get("MOTRIX_FAKE_NOW")
        if not env:
            return self.rcs.get("control", 0 if "FAILED" not in self.control else 1), self.control
        for key, out in self.scen.items():
            if name and name.startswith(key):
                return (0 if "FAILED" not in out and "ERROR" not in out else 1), out
        return 0, "2 passed\n"


REF = date(2026, 9, 30)


def test_matrix_green_runs_control_then_every_scenario_single_process_low_priority():
    r = _Runner()
    code, rep = BD.run_matrix(REF, runner=r, backend=BACKEND, python="py", out=lambda *_: None)
    assert code == 0
    runs = [c for c in r.calls if "--collect-only" not in c["argv"]]
    assert len(runs) == 1 + 6 and runs[0]["env"] == {}, "第一輪要是真實時鐘的 control"
    assert all(c["low"] for c in r.calls)
    assert [c["env"]["MOTRIX_FAKE_NOW"] for c in runs[1:]] == [d.strftime("%Y-%m-%dT%H:%M:%S") for _, d in BD.scenarios(REF)]
    assert all("-n" not in c["argv"] for c in runs)
    assert "邊界日矩陣" in rep and "control（真實時鐘）：全綠" in rep


def test_matrix_reports_a_boundary_only_red_with_owner_and_rerun_command():
    r = _Runner(scen={"2026-09-01": "FAILED modules/lodging/tests/test_x.py::test_q - AssertionError: month\n1 failed\n"})
    code, rep = BD.run_matrix(REF, runner=r, backend=BACKEND, python="py", out=lambda *_: None)
    assert code == 1
    assert "month_first" in rep and "邊界日紅 1 題" in rep and "[lodging]" in rep
    assert "MOTRIX_FAKE_NOW='2026-09-01T12:00:00'" in rep and "-p fake_clock" in rep and "test_x.py::test_q" in rep


def test_matrix_a_red_that_control_shares_is_not_a_boundary_red():
    same = "FAILED tests/test_a.py::t1 - boom\n1 failed\n"
    r = _Runner(control=same, scen={"2026-09": same, "2026-12": same, "2028": same, "2026-10": same})
    code, rep = BD.run_matrix(REF, runner=r, backend=BACKEND, python="py", out=lambda *_: None)
    assert code == 0 and "control（真實時鐘）：紅 1 題" in rep, "與日期無關的紅被算成邊界日紅"


def test_matrix_unidentified_scenario_failure_is_red():
    class R(_Runner):
        def run(self, argv, cwd, env=None, **kw):
            if env and env.get("MOTRIX_FAKE_NOW", "").startswith("2026-12"):
                self.calls.append({"argv": argv, "env": env, "low": True, "cwd": str(cwd)})
                return 2, "INTERNALERROR\n"
            return super().run(argv, cwd, env=env, **kw)
    code, rep = BD.run_matrix(REF, runner=R(), backend=BACKEND, python="py", out=lambda *_: None)
    assert code == 1 and "認不出是哪一題" in rep, "非 0 而認不出題被當成綠"


def test_matrix_blocked_by_a_build_and_empty_collection_exit_2():
    blocked = "【建包獨佔中：不開始臨時 pytest】"
    assert BD.run_matrix(REF, runner=_Runner(rcs={"collect": 4}, collect_out=blocked), backend=BACKEND, out=lambda *_: None)[0] == 2
    code, msg = BD.run_matrix(REF, runner=_Runner(collect_out="no tests\n"), backend=BACKEND, out=lambda *_: None)
    assert code == 2 and "收集不到" in msg, "沒有 date_sensitive 的題卻回成功（標記機制壞了會靜默全綠）"


def test_matrix_only_filter_and_list_mode():
    r = _Runner()
    code, _ = BD.run_matrix(REF, only=["pre_midnight", "month_end"], runner=r, backend=BACKEND, out=lambda *_: None)
    assert code == 0 and len([c for c in r.calls if "--collect-only" not in c["argv"]]) == 1 + 2
    r2 = _Runner()
    code, rep = BD.run_matrix(REF, runner=r2, backend=BACKEND, out=lambda *_: None, list_only=True)
    assert code == 0 and "tests/test_a.py" in rep and not [c for c in r2.calls if "--collect-only" not in c["argv"]]


def test_the_real_collection_finds_the_marked_files():
    """正對照：清單裡的檔真的被標上 date_sensitive、能被收集到（標記機制沒壞）。"""
    p = run_python(["-m", "pytest", "-m", "date_sensitive", "--collect-only", "-q", "-p", "no:cacheprovider",
                    "--basetemp=%s" % (Path(os.environ.get("TEMP", ".")) / ("motrix-pytest-bdcollect-%d" % os.getpid())),
                    "tests/test_monthly_backup_2026_09_14.py", "tests/test_backup_retention_policy_2026_09_14.py",
                    "tests/test_audit_search_dos_2026_09_30.py"], cwd=BACKEND, timeout=300)
    files = BD.files_from_collect(p.stdout)
    assert {"tests/test_monthly_backup_2026_09_14.py", "tests/test_backup_retention_policy_2026_09_14.py",
            "tests/test_audit_search_dos_2026_09_30.py"} <= set(files), p.stdout[-500:] + p.stderr[-300:]
    p = run_python(["-m", "pytest", "-m", "date_sensitive", "--collect-only", "-q", "-p", "no:cacheprovider",
                    "--basetemp=%s" % (Path(os.environ.get("TEMP", ".")) / ("motrix-pytest-bdcollect2-%d" % os.getpid())),
                    "tests/test_upload_magic_2026_09_30.py"], cwd=BACKEND, timeout=300)
    assert BD.files_from_collect(p.stdout) == [], "沒標記的檔也被 -m date_sensitive 選到"


# ── collect_determinism ─────────────────────────────────────────────────────────────

def test_ids_and_diff():
    assert CD.ids_of("tests/a.py::t1\nnoise\nmodules/x/tests/b.py::T::t2[p]\n2 tests collected\n") == \
        ["tests/a.py::t1", "modules/x/tests/b.py::T::t2[p]"]
    assert CD.diff_ids(["a::1", "a::2"], ["a::1", "a::2"]) == ([], [], False)
    assert CD.diff_ids(["a::1", "a::2"], ["a::1", "a::3"]) == (["a::2"], ["a::3"], False)
    assert CD.diff_ids(["a::1", "a::2"], ["a::2", "a::1"]) == ([], [], True), "順序不同也要擋"
    assert CD.diff_ids(["a::1", "a::1"], ["a::1"]) == (["a::1"], [], False), "重複的 id 數量不同要看得見"


class _CRunner:
    def __init__(self, outs, rcs=None):
        self.outs, self.rcs, self.n = list(outs), list(rcs or [0] * len(outs)), 0

    def run(self, argv, cwd, env=None, **kw):
        i = self.n
        self.n += 1
        assert "--collect-only" in argv
        return self.rcs[i], self.outs[i]


def test_check_same_ids_exit_0_and_waits_between_collections():
    sleeps, said = [], []
    r = _CRunner(["t/a.py::x[1]\n", "t/a.py::x[1]\n"])
    assert CD.check(r, "py", BACKEND, interval=2.0, sleep=sleeps.append, out=said.append) == 0 and sleeps == [2.0]


def test_check_different_ids_exit_1_and_names_the_ids():
    said = []
    r = _CRunner(["t/a.py::x[2026-09-30]\n", "t/a.py::x[2026-10-01]\n"])
    assert CD.check(r, "py", BACKEND, sleep=lambda s: None, out=said.append) == 1
    msg = "\n".join(said)
    assert "x[2026-09-30]" in msg and "x[2026-10-01]" in msg and "收集不決定" in msg


def test_check_collection_failure_exit_2():
    assert CD.check(_CRunner(["boom\n"], [2]), "py", BACKEND, sleep=lambda s: None, out=lambda m: None) == 2
    assert CD.check(_CRunner(["t/a.py::x\n", ""], [0, 0]), "py", BACKEND, sleep=lambda s: None, out=lambda m: None) == 2, \
        "第二次收集到 0 個 id 卻當成相同"


def test_the_real_collect_is_deterministic_on_a_small_slice(tmp_path):
    """整合題（真的 pytest）：一個固定的小目錄，兩次收集相同 ⇒ 0；含『現在時間』參數 id 的檔 ⇒ 1。"""
    d = tmp_path / "coll"
    d.mkdir()
    (d / "test_fixed.py").write_text("import pytest\n@pytest.mark.parametrize('x', [1, 2])\ndef test_a(x): pass\n", encoding="utf-8")
    (d / "test_moving.py").write_text("import pytest, time\n@pytest.mark.parametrize('x', [time.time_ns()])\ndef test_a(x): pass\n",
                                      encoding="utf-8")
    base = [sys.executable, str(PLAT / "collect_determinism.py"), "--python", sys.executable, "--backend", str(BACKEND), "--interval", "0.1"]
    env = utf8_env(MOTRIX_PYTEST_LOCK=str(tmp_path / "lock"))
    args = probe_pytest_args(d / "test_fixed.py")[:-1]          # 去掉尾端的檔案，換成我們要收集的
    ok = subprocess.run(base + ["--"] + args + [str(d / "test_fixed.py")], capture_output=True, text=True, encoding="utf-8",
                        errors="replace", env=env, timeout=240)
    assert ok.returncode == 0, ok.stdout[-500:] + ok.stderr[-500:]
    bad = subprocess.run(base + ["--"] + args + [str(d / "test_moving.py")], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env, timeout=240)
    assert bad.returncode == 1 and "收集不決定" in bad.stdout, bad.stdout[-500:] + bad.stderr[-500:]


# ── 建包腳本與沿用指紋的接線 ───────────────────────────────────────────────────────────

def test_build_script_has_clock_date_and_collect_check_before_the_test_stage():
    for needle in ("[string]$ClockDate", "[switch]$NoCollectCheck"):
        assert needle in PS1, needle
    acq = PS1.index("\nAcquire-TestExclusive\n")
    assert PS1.index("if ($ClockDate) { $ClockDate } else { $commitDate }") < acq, "預設不是 commit 日期"
    assert PS1.index("$env:MOTRIX_TEST_TODAY = $clockDate") < acq
    assert PS1.index("collect_determinism.py") < acq, "收集決定性檢查要在 20 分鐘的測試階段之前"
    i = PS1.index("$cdExit = Invoke-PyTool")
    assert "if (-not $NoCollectCheck)" in PS1[:i] and "if ($cdExit -ne 0) {" in PS1[i:i + 400] and "Fail \"收集不決定" in PS1[i:i + 600], "收集不決定沒有被接成 Fail"
    assert "ParseExact" in PS1, "沒有驗證 -ClockDate 的格式"
    assert '$BuildStats["clock_date"]' in PS1
    # 指紋先算、環境變數後設：MOTRIX_TEST_TODAY 不能影響沿用指紋的計算順序
    assert PS1.index("build_test_reuse.py") < PS1.index("$env:MOTRIX_TEST_TODAY = $clockDate")


def test_test_today_and_fake_now_are_not_part_of_the_reuse_fingerprint(monkeypatch):
    from tools import build_test_reuse as tr
    monkeypatch.setenv("MOTRIX_TEST_TODAY", "2026-10-01")
    monkeypatch.setenv("MOTRIX_FAKE_NOW", "2026-10-01T12:00:00")
    monkeypatch.setenv("MOTRIX_EDGE_PDF_TIMEOUT", "40")
    env = tr.current_env()["motrix_env"]
    assert "MOTRIX_EDGE_PDF_TIMEOUT" in env and "MOTRIX_TEST_TODAY" not in env and "MOTRIX_FAKE_NOW" not in env
