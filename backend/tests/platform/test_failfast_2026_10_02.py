# -*- coding: utf-8 -*-
"""建包優化 2 · 項 1（tools/platform/failfast.py）的 dry-run 測試台＋反向控制：在**自造的小專案**裡跑巢狀 pytest，不碰真正的建包腳本。

自造專案（tmp）：test_a_ok.py 30 題綠；test_b_red.py 12 題紅；test_c_tail.py 30 題綠（每題 0.1 秒，用來看「停止後還有沒有繼續跑」）；總共 72 題。
每個行為都配一個「反面」：預設關時照跑完、已登記的偶發不計、全綠不可能被截斷、重排不刪題、停止時 exit code 是 1 不是 2、fail_stream 不把它記成 aborted。
"""
import json
import os
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
TOOLS = HERE.parents[3] / "tools" / "platform"
if not (TOOLS / "failfast.py").is_file():
    pytest.skip("tools/platform/failfast.py 不在這個安裝包", allow_module_level=True)

OK = "import time\n\n" + "".join("def test_ok_%02d():\n    time.sleep(0.02)\n\n" % i for i in range(30))
RED = "import time\n\n" + "".join("def test_red_%02d():\n    time.sleep(0.02)\n    assert False, 'boom %d'\n\n" % (i, i) for i in range(12))
TAIL = "import time\n\n" + "".join("def test_tail_%02d():\n    time.sleep(0.1)\n\n" % i for i in range(30))


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    (p / "test_a_ok.py").write_text(OK, encoding="utf-8")
    (p / "test_b_red.py").write_text(RED, encoding="utf-8")
    (p / "test_c_tail.py").write_text(TAIL, encoding="utf-8")
    (p / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
    return p


def run(proj, args=(), env=None, plugins=("failfast",)):
    e = {k: v for k, v in os.environ.items() if not k.startswith("MOTRIX_") and k != "PYTEST_ADDOPTS"}
    e["PYTHONPATH"] = str(TOOLS)
    e["PYTHONIOENCODING"] = "utf-8"
    e["MOTRIX_FAIL_STREAM_DIR"] = str(proj.parent / "fs")
    e.update(env or {})
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *sum((["-p", p] for p in plugins), []), *args]
    r = subprocess.run(cmd, cwd=str(proj), env=e, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    return r.returncode, r.stdout + r.stderr


def counts(out):
    m = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|error|errors)", out.splitlines()[-1] if out.strip() else "")}
    return m.get("passed", 0), m.get("failed", 0)


def test_default_is_off_and_runs_everything(proj):
    rc, out = run(proj, ["-n", "2"])
    assert rc == 1 and counts(out) == (60, 12), out[-400:]
    assert "FAIL-FAST" not in out


def test_stops_after_n_reds_exit_code_is_1_not_2_and_runs_fewer(proj):
    rc, out = run(proj, ["-n", "2"], {"MOTRIX_FAILFAST": "1", "MOTRIX_FAILFAST_N": "3"})
    assert "FAIL-FAST" in out and "未登記的紅達 3 筆" in out, out[-600:]
    p, f = counts(out)
    assert p + f < 72 and f >= 3, (p, f)                                # 比全跑少（把 test_c_tail 的一部分省掉了）
    assert rc == 1, "停止要回 1（測試失敗）；xdist 的 shouldstop 預設是 2＝INTERRUPTED，會被建包當外部中斷"


def test_single_process_also_stops_and_returns_1(proj):
    rc, out = run(proj, ["-p", "no:xdist"], {"MOTRIX_FAILFAST": "1", "MOTRIX_FAILFAST_N": "2"})
    p, f = counts(out)
    assert rc == 1 and f == 2 and p == 30 and "FAIL-FAST" in out, (rc, p, f, out[-400:])    # 前 30 綠＋2 紅就停，第三個紅（與 tail）沒跑


def test_registered_flakes_do_not_count_toward_the_stop(proj, tmp_path):
    reg = {"flakes": [{"nodeid": "test_b_red.py::test_red_%02d" % i, "first_seen": str(date.today()), "owner": "t", "ticket": "T",
                       "expires": str(date.today() + timedelta(days=5))} for i in range(12)]}
    f = tmp_path / "flakes.json"
    f.write_text(json.dumps(reg), encoding="utf-8")
    rc, out = run(proj, ["-p", "no:xdist"], {"MOTRIX_FAILFAST": "1", "MOTRIX_FAILFAST_N": "2", "MOTRIX_FAILFAST_FLAKES": str(f)})
    assert counts(out) == (60, 12) and "FAIL-FAST" not in out, out[-400:]            # 已登記的紅不計 ⇒ 不停（照舊交 flaky_retry）
    reg["flakes"][0]["expires"] = str(date.today() - timedelta(days=1))               # 反向：過期的登記不算
    f.write_text(json.dumps(reg), encoding="utf-8")
    rc, out = run(proj, ["-p", "no:xdist"], {"MOTRIX_FAILFAST": "1", "MOTRIX_FAILFAST_N": "1", "MOTRIX_FAILFAST_FLAKES": str(f)})
    assert "FAIL-FAST" in out, "過期的登記不可以讓紅被當成已登記"


def test_a_green_run_is_never_truncated(proj):
    (proj / "test_b_red.py").unlink()
    rc, out = run(proj, ["-n", "2"], {"MOTRIX_FAILFAST": "1", "MOTRIX_FAILFAST_N": "1", "MOTRIX_FAILFAST_QUIET_MIN": "0.001"})
    assert rc == 0 and counts(out) == (60, 0) and "FAIL-FAST" not in out, out[-300:]    # 沒有紅 ⇒ 任何停止條件都不成立


def test_quiet_window_stops_once_there_is_a_red_and_nothing_new(proj):
    (proj / "test_a_ok.py").unlink()
    (proj / "test_b_red.py").write_text(RED.split("def test_red_01")[0], encoding="utf-8")   # 只留 1 個紅
    (proj / "test_c_tail.py").write_text("import time\n\n" + "".join("def test_t_%02d():\n    time.sleep(0.3)\n\n" % i for i in range(30)), encoding="utf-8")
    rc, out = run(proj, ["-p", "no:xdist"], {"MOTRIX_FAILFAST": "1", "MOTRIX_FAILFAST_N": "99", "MOTRIX_FAILFAST_QUIET_MIN": "0.03"})   # 0.03 分＝1.8 秒
    p, f = counts(out)
    assert rc == 1 and f == 1 and 3 <= p < 30 and "沒有新的紅" in out, (rc, p, f, out[-400:])


def test_fail_stream_does_not_call_a_failfast_stop_an_external_abort(proj):
    rc, out = run(proj, ["-n", "2"], {"MOTRIX_FAILFAST": "1", "MOTRIX_FAILFAST_N": "3", "MOTRIX_FAIL_STREAM_GRACE": "0.2"}, plugins=("failfast", "fail_stream"))
    files = sorted((proj.parent / "fs").glob("*.jsonl"))
    assert files, out[-400:]
    recs = [json.loads(x) for x in files[-1].read_text(encoding="utf-8").splitlines() if x.strip()]
    summ = [r for r in recs if r["type"] == "summary"][-1]
    assert summ["aborted"] is False and summ["aborted_by"] == "failfast" and summ["failed"] >= 3, summ
    assert [r for r in recs if r["type"] == "fail"], "紅清單照常寫"
    assert not [r for r in recs if r["type"] == "aborted"]


def _ids(out):
    return [l.strip() for l in out.splitlines() if "::" in l and not l.startswith(("FAIL", "ERROR"))]


def test_failure_first_reorders_but_never_drops_or_adds_tests(proj, tmp_path):
    fs = proj.parent / "fs"
    fs.mkdir()
    (fs / "20300101_000000_1.jsonl").write_text(json.dumps({"type": "fail", "nodeid": "test_c_tail.py::test_tail_17"}) + "\n", encoding="utf-8")
    rc0, base = run(proj, ["--collect-only", "-p", "no:xdist"])
    rc1, first = run(proj, ["--collect-only", "-p", "no:xdist"], {"MOTRIX_FAILFIRST": "1"})
    a, b = _ids(base), _ids(first)
    assert len(a) == 72 and sorted(a) == sorted(b), "重排前後的題集合必須完全相同"
    assert a != b and b[0] == "test_c_tail.py::test_tail_17", b[:3]               # 最近紅過的排最前
    assert [x for x in b if x != "test_c_tail.py::test_tail_17"] == [x for x in a if x != "test_c_tail.py::test_tail_17"]   # 其餘維持原順序（穩定排序）
    rc2, off = run(proj, ["--collect-only", "-p", "no:xdist"])
    assert _ids(off) == a, "沒開 MOTRIX_FAILFIRST 就不重排"


def test_failure_first_with_xdist_workers_agree_and_run_everything(proj):
    fs = proj.parent / "fs"
    fs.mkdir()
    (fs / "20300101_000000_1.jsonl").write_text(json.dumps({"type": "fail", "nodeid": "test_c_tail.py::test_tail_29"}) + "\n", encoding="utf-8")
    rc, out = run(proj, ["-n", "2"], {"MOTRIX_FAILFIRST": "1"})
    assert counts(out) == (60, 12) and "worker" not in out.lower().replace("workers", ""), out[-500:]   # 全部跑完、worker 之間沒有 collection 不一致

def test_xdist_workers_stop_after_the_current_test_instead_of_draining_their_queue(proj):
    """W2 實測：controller 端 shouldstop 只在每個 worker 已分到的題之後排 SHUTDOWN ⇒ 手上排的幾百題都跑完才收工（+4:07 停、+16:05 才結束）。
    這題在 -n 2、600 題（每題 0.1 秒）的專案裡讓 1 個紅出現在最前面、安靜期 1.2 秒：worker 端停止旗標生效時只會多跑幾題；
    若退回「只靠 controller 的 shouldstop」，每個 worker 的初始批次（600//4//2＝75 題）都會被跑完 ⇒ 超過 140 題。"""
    for f in proj.glob("test_*.py"):
        f.unlink()
    (proj / "test_0_red.py").write_text("def test_red():"+chr(10)+"    assert False"+chr(10), encoding="utf-8")
    many = "import time"+chr(10)+chr(10) + "".join(("def test_m_%03d():" + chr(10) + "    time.sleep(0.1)" + chr(10) + chr(10)) % i for i in range(600))
    (proj / "test_1_many.py").write_text(many, encoding="utf-8")
    rc, out = run(proj, ["-n", "2"], {"MOTRIX_FAILFAST": "1", "MOTRIX_FAILFAST_N": "99", "MOTRIX_FAILFAST_QUIET_MIN": "0.02"})
    p, f = counts(out)
    assert rc == 1 and f == 1 and "FAIL-FAST" in out, out[-300:]
    assert p < 80, "停止後 worker 沒有收工（跑了 %d 題；排隊的題被跑完了）" % p
