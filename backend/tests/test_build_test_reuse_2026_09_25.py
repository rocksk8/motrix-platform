"""建包：同一份 tree 已全綠就沿用測試結果（PLAN-TEST-PERF §3.1，0a 加做）。

🔑 沿用的前提是「會影響測試結果的東西完全沒變」。指紋涵蓋：
   - **整棵 tracked tree**（`HEAD^{tree}`）＋工作樹必須乾淨（含未追蹤檔）；
     ⚠️ **文件不排除**：45 個測試檔會讀 `docs/`（spec_coverage 掃規格、manifest 對照…），
        排除文件＝改規格不重跑規格守門。
   - 執行環境：Python 版本、`pip freeze`、Playwright 版本與已安裝的瀏覽器、影響測試的 `MOTRIX_*` 環境變數。
🔑 還要：上一次**兩段都嚴格全綠**（e2e 逾時放行不算）、**同一天**、12 小時內。
   時間相依的題（VR1 比日期、跨午夜）⇒ 跨日一律重跑。
"""
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tools import build_test_reuse as tr


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "backend").mkdir()
    (r / "backend" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (r / "docs").mkdir()
    (r / "docs" / "SPEC.md").write_text("# spec\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    return r


ENV = {"python": "3.11.15", "pip_freeze": "pytest==9.1.1", "playwright": "1.62", "browsers": ["chromium-1234"],
       "motrix_env": {}}


def _fp(repo, env=ENV):
    return tr.fingerprint(repo, env=env)


def _commit(repo, rel, text):
    p = repo / rel
    p.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")


def test_changing_one_py_file_changes_the_fingerprint(repo):
    """🔴 0a 指定的證明：改一個 .py ⇒ 不沿用。"""
    before = _fp(repo)
    _commit(repo, "backend/a.py", "x = 2\n")
    assert _fp(repo) != before


def test_changing_a_doc_also_changes_it_because_tests_read_docs(repo):
    before = _fp(repo)
    _commit(repo, "docs/SPEC.md", "# spec v2\n")
    assert _fp(repo) != before


def test_a_dirty_tree_has_no_fingerprint(repo):
    assert _fp(repo) is not None
    (repo / "backend" / "a.py").write_text("x = 3\n", encoding="utf-8")
    assert _fp(repo) is None, "工作樹有未提交改動卻給出指紋"
    _git(repo, "checkout", "--", "backend/a.py")
    (repo / "backend" / "new.py").write_text("", encoding="utf-8")
    assert _fp(repo) is None, "有未追蹤檔卻給出指紋"


def test_the_environment_is_part_of_the_fingerprint(repo):
    base = _fp(repo)
    for key, val in (("python", "3.12.0"), ("pip_freeze", "pytest==9.2"), ("playwright", "1.63"),
                     ("browsers", ["chromium-9999"]), ("motrix_env", {"MOTRIX_EDGE_PDF_TIMEOUT": "40"})):
        assert _fp(repo, dict(ENV, **{key: val})) != base, key
    assert _fp(repo) == base, "同樣的輸入要給同樣的指紋"


def _rec(fp, when, green=True):
    return {"fingerprint": fp, "tested_at": when.strftime("%Y-%m-%d %H:%M:%S"), "green": green, "commit": "abc"}


def test_reuse_only_a_strictly_green_same_day_recent_match():
    now = datetime(2026, 9, 25, 15, 0, 0)
    ok = _rec("F", now - timedelta(hours=2))
    assert tr.find_reusable([ok], "F", now) == ok
    assert tr.find_reusable([ok], "G", now) is None, "指紋不同也沿用"
    assert tr.find_reusable([_rec("F", now - timedelta(hours=2), green=False)], "F", now) is None, "沒全綠也沿用"
    assert tr.find_reusable([_rec("F", datetime(2026, 9, 24, 23, 50))], "F", now) is None, "跨日也沿用"
    assert tr.find_reusable([_rec("F", now - timedelta(hours=13))], "F", now) is None, "超過 12 小時也沿用"
    assert tr.find_reusable([], "F", now) is None
    assert tr.find_reusable([ok], None, now) is None, "沒有指紋（工作樹髒）也沿用"


def test_the_cli_round_trip(repo, tmp_path):
    """建包腳本走的路：fingerprint → lookup（沒有）→ record → lookup（有）。"""
    records = tmp_path / "test_results.jsonl"
    fp = _fp(repo)
    assert tr.lookup(records, fp) is None
    tr.record(records, fp, green=True, commit="abc")
    got = tr.lookup(records, fp)
    assert got and got["fingerprint"] == fp and got["green"] is True
    tr.record(records, fp, green=False, commit="abc")        # 最新一筆紅 ⇒ 不可以沿用舊的綠
    assert tr.lookup(records, fp) is None


def test_the_build_script_records_green_only_when_both_stages_exit_zero():
    """建包腳本那一側：綠＝兩段都 exit 0（e2e 逾時放行不算綠）；沿用時可用 -ForceTests 關掉。"""
    s = (Path(__file__).resolve().parents[1] / "tools" / "build_deploy_package.ps1").read_text(encoding="utf-8-sig")
    assert "Record-TestResult ($testExit -eq 0 -and $e2eExit -eq 0)" in s
    assert "[switch]$ForceTests" in s and "-not $ForceTests" in s
    assert "build_test_reuse.py" in s


def test_every_red_exit_from_the_test_stage_is_recorded_before_it_leaves():
    """🔴 紅了就 Fail 離開的路徑，**離開前**要先記「非綠」——否則同一份 tree 之前那筆綠會被下次沿用
    （同 tree 偶發紅之後又沿用舊綠）。a3 已把 e2e 那一條移到閘門之前（6526c21c）；非 e2e 那一條也要。"""
    s = (Path(__file__).resolve().parents[1] / "tools" / "build_deploy_package.ps1").read_text(encoding="utf-8-sig")
    start = s.index("if ($reuse) {")
    end = s.index("}   # end: if ($reuse) else")
    section = s[start:end]
    fails = [i for i in range(len(section)) if section.startswith('Fail "', i)]   # 呼叫，不是註解裡的字
    assert len(fails) >= 2, "測試段裡的 Fail 數量不對，這一題的切片可能失效了"
    for i in fails:
        before = section[:i]
        # 「最後一次跑 pytest」到這個 Fail 之間，必須先記錄過結果
        last_run = before.rfind("-m pytest")
        assert last_run >= 0 and "Record-TestResult" in before[last_run:], \
            "這個 Fail 之前沒有先記錄非綠：…%s" % section[i:i + 60]


# ── 第 45 班：只影響速度／順序／診斷的開關不進指紋；影響「哪些題跑、過不過」的仍進指紋 ───────────────────────────────

#: 第 45 班全閘門優化的開關（gate_slices／modtest／failfast）：改它們不可以讓指紋變（否則換個 shell 建包就整套重跑）
SPEED_ONLY = ("MOTRIX_GATE_WORKERS", "MOTRIX_GATE_DIST", "MOTRIX_GATE_LPT", "MOTRIX_GATE_RECORD", "MOTRIX_GATE_VERIFY", "MOTRIX_GATE_SLICES",
              "MOTRIX_FULL_OVERLAP", "MOTRIX_FULL_OVERLAP_MIN_GB", "MOTRIX_FULL_FLAKY_RETRY",
              "MOTRIX_FAILFAST", "MOTRIX_FAILFAST_N", "MOTRIX_FAILFAST_QUIET_MIN", "MOTRIX_FAILFIRST", "MOTRIX_FAILFIRST_BASE",
              "MOTRIX_FULL_MAX_WORKERS", "MOTRIX_E2E_MAX_WORKERS", "MOTRIX_PARTIAL_MAX_WORKERS")


def _fp_with_env(repo, monkeypatch, **env):
    """用真的 current_env()（pip freeze 換成固定字串，省時間）＋給定的環境變數算指紋。"""
    for k in list(__import__("os").environ):
        if k.startswith("MOTRIX_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    real = subprocess.run
    monkeypatch.setattr(tr.subprocess, "run", lambda cmd, *a, **k: type("R", (), {"stdout": "pytest==9.1.1"})() if "pip" in list(cmd) else real(cmd, *a, **k))   # 只換 pip freeze；git 照真的跑
    return tr.fingerprint(repo)


def test_speed_and_order_switches_do_not_change_the_fingerprint(repo, monkeypatch):
    base = _fp_with_env(repo, monkeypatch)
    assert base
    for name in SPEED_ONLY:
        assert _fp_with_env(repo, monkeypatch, **{name: "2"}) == base, "%s 不該進指紋（只決定速度／順序／診斷）" % name
    assert _fp_with_env(repo, monkeypatch, MOTRIX_GATE_WORKERS="2", MOTRIX_GATE_SLICES="0", MOTRIX_FULL_OVERLAP="1") == base


def test_switches_that_change_which_tests_run_or_pass_still_change_it(repo, monkeypatch):
    """反向控制：MOTRIX_TRAIN 決定「只在列車跑」的守門題是跑還是 skip；其他沒登記的 MOTRIX_* 也照舊進指紋。"""
    base = _fp_with_env(repo, monkeypatch)
    assert _fp_with_env(repo, monkeypatch, MOTRIX_TRAIN="1") != base
    assert _fp_with_env(repo, monkeypatch, MOTRIX_EDGE_PDF_TIMEOUT="40") != base
    assert _fp_with_env(repo, monkeypatch, MOTRIX_SOME_NEW_SWITCH_XYZ="1") != base          # 新開關預設進指紋（保守）；確定只影響速度才加進 _ENV_IGNORE
    assert _fp_with_env(repo, monkeypatch, PYTEST_ADDOPTS="-k foo") != base                  # 縮小範圍的參數一律進指紋（稽核 W4）


def test_the_ignore_list_is_pinned():
    """清單被改（多一個少一個）要有人看：新增＝確認它不決定哪些題存在／過不過；MOTRIX_TRAIN 不得出現。"""
    assert "MOTRIX_TRAIN" not in tr._ENV_IGNORE
    for name in SPEED_ONLY:
        assert name in tr._ENV_IGNORE, name
    assert len(tr._ENV_IGNORE) == 32, "個數變了：%s（改清單時同步這個數字並說明理由）" % sorted(tr._ENV_IGNORE)
