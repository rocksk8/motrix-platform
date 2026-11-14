# -*- coding: utf-8 -*-
"""author_gate --quick 的牆鐘上限（T87 A2）：預算不只管選題，執行也要被限住，沒跑到的一律列「未跑」。

T87 實測：現行 quick 980／1975／678 s 都遠超 5 分鐘——預算只砍 T4、e2e 不計預算、執行沒有逾時。這裡釘住修法：
  * failfast 外掛的 MOTRIX_DEADLINE_AT：到點停（單行程與 xdist 都要停），並把「有開跑的檔」寫進 MOTRIX_DEADLINE_SEEN；
  * author_gate 的 quick 階段命令一定帶 `-p failfast`＋PYTHONPATH（原本沒帶，外掛根本沒載入、到點停形同虛設）；
  * 階段起跑前剩餘時間不足 ⇒ 整段列未跑；到點中止 ⇒ 沒開跑的檔逐一列未跑；行程被硬逾時殺掉 ⇒ 明講紅清單可能不完整。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
TOOLS = REPO / "tools" / "platform"
sys.path.insert(0, str(TOOLS))

import author_gate as AG  # noqa: E402

CONFTEST_FREE = "-p no:cacheprovider"


def _make_tests(tmp_path, n=6, sleep=0.4):
    for i in range(n):
        (tmp_path / ("test_slow_%d.py" % i)).write_text("import time\n\ndef test_a():\n    time.sleep(%s)\n\ndef test_b():\n    time.sleep(%s)\n" % (sleep, sleep), encoding="utf-8")


def _run(tmp_path, extra, deadline_in):
    seen = tmp_path / "seen.json"
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=str(TOOLS), MOTRIX_DEADLINE_AT="%.3f" % (time.time() + deadline_in), MOTRIX_DEADLINE_SEEN=str(seen), MOTRIX_FAILFAST="0")
    env.pop("MOTRIX_FAILFIRST", None)
    p = subprocess.run([sys.executable, "-m", "pytest", str(tmp_path), "-q", "-p", "failfast", "-p", "no:cacheprovider", "--rootdir", str(tmp_path), *extra],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(tmp_path), timeout=120)
    return p, (json.loads(seen.read_text(encoding="utf-8")) if seen.exists() else None)


def test_deadline_stops_a_single_process_run_and_reports_which_files_started(tmp_path):
    _make_tests(tmp_path)
    p, seen = _run(tmp_path, [], deadline_in=1.0)
    assert seen is not None and seen["deadline_hit"] is True, p.stdout[-800:]
    assert 0 < len(seen["seen"]) < 6, "到點就停：只有一部分檔開跑，沒開跑的由呼叫端列未跑"
    assert "DEADLINE:" in p.stdout


@pytest.mark.skipif(subprocess.run([sys.executable, "-c", "import xdist"], capture_output=True).returncode != 0, reason="沒有 xdist")
def test_deadline_stops_an_xdist_run_too(tmp_path):
    _make_tests(tmp_path, n=10, sleep=0.5)
    t0 = time.time()
    p, seen = _run(tmp_path, ["-n", "2"], deadline_in=1.5)
    assert seen is not None and seen["deadline_hit"] is True, p.stdout[-800:]
    assert len(seen["seen"]) < 10 and time.time() - t0 < 60


def test_without_the_deadline_env_nothing_changes(tmp_path):
    _make_tests(tmp_path, n=2, sleep=0.01)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONPATH=str(TOOLS))
    for k in ("MOTRIX_DEADLINE_AT", "MOTRIX_DEADLINE_SEEN", "MOTRIX_FAILFAST", "MOTRIX_FAILFIRST"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-m", "pytest", str(tmp_path), "-q", "-p", "failfast", "-p", "no:cacheprovider", "--rootdir", str(tmp_path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, cwd=str(tmp_path), timeout=120)
    assert p.returncode == 0 and "4 passed" in p.stdout and "DEADLINE" not in p.stdout


# ── author_gate 的階段執行 ───────────────────────────────────────────────

def _sel(high=("backend/tests/test_a.py", "backend/tests/test_b.py"), e2e=("backend/tests/test_e2e_p.py",), guards=("backend/tests/test_g.py",)):
    stages = [{"name": "high", "files": list(high)}, {"name": "e2e", "files": list(e2e)}, {"name": "guards", "files": list(guards)}]
    tiers = {"T0": {"files": [high[0]]}, "T1": {"files": []}, "T2": {"files": [high[1]]}, "T3": {"files": list(guards)}, "T4": {"files": list(e2e)}}
    return {"stages": stages, "quick_plan": {"tiers": tiers}, "guard_args": []}


def _fake_run(monkeypatch, outputs, calls):
    def fake(argv, cwd, env, stream=True, hard_timeout=None):
        calls.append({"argv": list(argv), "env": dict(env or {}), "hard": hard_timeout})
        out = outputs[len(calls) - 1]
        AG.TIMED_OUT["flag"] = out.get("killed", False)
        if out.get("seen") is not None:
            Path(env["MOTRIX_DEADLINE_SEEN"]).write_text(json.dumps(out["seen"]), encoding="utf-8")
        return out.get("rc", 0), out.get("text", "= 2 passed in 1s =")
    monkeypatch.setattr(AG, "run_pytest", fake)


def _stages(monkeypatch, tmp_path, sel, outputs, deadline_in=600):
    calls = []
    _fake_run(monkeypatch, outputs, calls)
    agg = AG.run_quick_stages(sel, tmp_path, "python", {}, str(tmp_path / "bt"), 2, time.time() + deadline_in, False, lambda out: [])
    return agg, calls


def test_every_quick_stage_loads_the_deadline_plugin_and_gets_the_shared_deadline(monkeypatch, tmp_path):
    agg, calls = _stages(monkeypatch, tmp_path, _sel(), [{}, {}, {}])
    assert len(calls) == 3
    for c in calls:
        assert any(a == "-p" and c["argv"][i + 1] == "failfast" for i, a in enumerate(c["argv"][:-1])), "沒帶 -p failfast ⇒ 外掛不載入、到點停形同虛設"
        assert float(c["env"]["MOTRIX_DEADLINE_AT"]) > time.time() and c["env"]["MOTRIX_FAILFAST"] == "0"
        assert str(TOOLS) in c["env"]["PYTHONPATH"] and c["hard"] is not None and c["hard"] > 60
    assert len({c["env"]["MOTRIX_DEADLINE_AT"] for c in calls}) == 1, "三段共用同一個牆鐘上限，不是各給一份預算"
    assert agg["unrun"] == [] and agg["deadline_hit"] is False
    marks = [calls[1]["argv"][i + 1] for i, a in enumerate(calls[1]["argv"][3:-1], start=3) if a == "-m"]
    assert marks == ["e2e"] and "-n" not in calls[1]["argv"], "e2e 單行程序列"


def test_a_stage_with_no_time_left_is_listed_as_not_run_and_never_started(monkeypatch, tmp_path):
    agg, calls = _stages(monkeypatch, tmp_path, _sel(), [{}], deadline_in=5)
    assert calls == [] and agg["deadline_hit"] is True
    assert {u["item"] for u in agg["unrun"]} == {"backend/tests/test_a.py", "backend/tests/test_b.py", "backend/tests/test_e2e_p.py", "backend/tests/test_g.py"}
    assert all("未跑" in u["reason"] for u in agg["unrun"])


def test_deadline_hit_lists_the_files_that_never_started(monkeypatch, tmp_path):
    out = [{"rc": 1, "text": "DEADLINE: 牆鐘預算到了\n= 1 passed in 100s =", "seen": {"seen": ["tests/test_a.py"], "deadline_hit": True}}, {}, {}]
    agg, calls = _stages(monkeypatch, tmp_path, _sel(), out)
    miss = [u["item"] for u in agg["unrun"] if u["tier"] != "牆鐘"]
    assert "backend/tests/test_b.py" in miss and "backend/tests/test_a.py" not in miss and agg["deadline_hit"] is True
    tier_b = next(u["tier"] for u in agg["unrun"] if u["item"] == "backend/tests/test_b.py")
    assert tier_b == "T2", "未跑項目要帶它原本的優先層，方便看漏的是哪一層"
    assert any(u["tier"] == "牆鐘" and "high" in u["item"] for u in agg["unrun"])


def test_a_killed_pytest_says_the_red_list_may_be_incomplete(monkeypatch, tmp_path):
    out = [{"rc": 1, "text": "....", "killed": True}, {}, {}]
    agg, _ = _stages(monkeypatch, tmp_path, _sel(), out)
    assert agg["killed"] is True and any("紅清單可能不完整" in u["reason"] for u in agg["unrun"])
