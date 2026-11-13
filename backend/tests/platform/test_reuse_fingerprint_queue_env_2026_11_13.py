# -*- coding: utf-8 -*-
"""run-stage 的結果建包要能沿用（2026-11-13，T84：T82 打包沒沿用、多花約 45 分鐘）。

根因：run-stage 經 heavy_run 跑時，子行程環境多了**每輪都不同**的 MOTRIX_CI_TICKET（票根檔路徑）、MOTRIX_GATE_TOKEN（每把閘門鎖一個）、
MOTRIX_WINDOW 等；這些原本會進指紋（只有 _ENV_IGNORE 內的 MOTRIX_* 不進）⇒ 同 tree、同直譯器的兩次 run-stage 指紋不同，
也跟直接跑的建包對不上（explain 只說「tree 相同 ⇒ 差在執行環境」，因為 run-stage 不寫旁表）。
修法：排隊／鎖相關的變數進 _ENV_IGNORE；run-stage 寫診斷旁表；結束時列出仍會讓建包對不上的成分。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
sys.path.insert(0, str(REPO / "backend" / "tools"))
import build_test_reuse as btr  # noqa: E402
import heavy_run as H  # noqa: E402

QUEUE_VARS = {"MOTRIX_CI_TICKET": "D:/q/ticket-0001.json", "MOTRIX_GATE_TOKEN": "tok-abc", "MOTRIX_WINDOW": "hichan-2",
              "MOTRIX_CI_DIR": "D:/q", "MOTRIX_REQUIRE_QUEUE": "1", "MOTRIX_QUEUE_GUARD": "1"}


@pytest.fixture
def tiny_repo(tmp_path):
    r = tmp_path / "r"
    (r / "backend").mkdir(parents=True)
    for a in (["init", "-q"], ["config", "user.email", "t@x"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(r), *a], check=True, capture_output=True)
    (r / "backend" / "k.txt").write_text("k", encoding="utf-8")
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "c"], check=True, capture_output=True)
    return r


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    import os
    # pytest 行程自己就帶一些 MOTRIX_*（conftest 設的 HARDCAP／STRICT_DB_GUARDS 等）⇒ 全部清掉，從乾淨環境開始比
    for k in [k for k in os.environ if k.startswith("MOTRIX_")] + ["PYTEST_ADDOPTS"]:
        monkeypatch.delenv(k, raising=False)
    real_run = subprocess.run

    def run(cmd, *a, **k):                           # pip freeze 很慢且與這裡要驗的無關；其餘（git）照舊
        if isinstance(cmd, list) and cmd[1:4] == ["-m", "pip", "freeze"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="pkg==1" + chr(10), stderr="")
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(btr.subprocess, "run", run)


def _fp(repo, monkeypatch, extra=None):
    for k, v in (extra or {}).items():
        monkeypatch.setenv(k, v)
    return btr.fingerprint(repo)


def test_queue_and_lock_variables_do_not_change_the_fingerprint(tiny_repo, monkeypatch):
    base = _fp(tiny_repo, monkeypatch)
    assert base
    for k, v in QUEUE_VARS.items():
        monkeypatch.setenv(k, v)
        assert btr.fingerprint(tiny_repo) == base, "%s 進了指紋：經 heavy_run 跑的 run-stage 與直接跑的建包會永遠對不上" % k
        monkeypatch.setenv(k, v + "-another-run")
        assert btr.fingerprint(tiny_repo) == base, "%s 每輪不同的值改變了指紋" % k
        monkeypatch.delenv(k)


def test_every_unique_per_run_variable_heavy_run_injects_is_ignored():
    """結構對照：heavy_run 注入子行程的每輪變數（票根、閘門 token）都在 _ENV_IGNORE。新增注入變數而沒進這裡 ⇒ 紅。"""
    for name in (H.CI_TICKET_ENV, H.GATE_TOKEN_ENV):
        assert name in btr._ENV_IGNORE, "%s 是 heavy_run 注入子行程的變數，沒進 _ENV_IGNORE ⇒ 每輪指紋都不同" % name


def test_result_deciding_variables_still_change_the_fingerprint(tiny_repo, monkeypatch):
    """反向控制：真正決定題目跑不跑、過不過的（MOTRIX_TRAIN、PYTEST_ADDOPTS）仍進指紋，不是把整類 MOTRIX_* 都放掉。"""
    base = _fp(tiny_repo, monkeypatch)
    monkeypatch.setenv("MOTRIX_TRAIN", "1")
    assert btr.fingerprint(tiny_repo) != base
    monkeypatch.delenv("MOTRIX_TRAIN")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k nothing")
    assert btr.fingerprint(tiny_repo) != base


def test_reuse_blockers_names_the_variables_not_their_values():
    assert btr.reuse_blockers(env={}) == []
    assert btr.reuse_blockers(env=dict(QUEUE_VARS)) == [], "已放掉的變數不算會擋沿用的"
    got = btr.reuse_blockers(env={"MOTRIX_TRAIN": "secret-value-1", "PYTEST_ADDOPTS": "-x"})
    text = "\n".join(got)
    assert "MOTRIX_TRAIN" in text and "PYTEST_ADDOPTS" in text and "secret-value-1" not in text
    other = btr.reuse_blockers(python=r"C:\elsewhere\.venv\Scripts\python.exe", env={})
    assert other and "pip freeze" in other[0], "算指紋的直譯器不是跑測試的那支要警告"
    assert btr.reuse_blockers(python=sys.executable, env={}) == []


def test_run_stage_records_parts_and_warns_when_the_build_would_not_reuse(tiny_repo, tmp_path, monkeypatch):
    recs = tmp_path / "rec.jsonl"
    for k, v in QUEUE_VARS.items():
        monkeypatch.setenv(k, v)
    rc, wrote, why = btr.run_stage(tiny_repo, "not_e2e", recs, runner=lambda cmd, cwd, env: 0, note=lambda *_: None)
    assert (rc, wrote) == (0, True) and "⚠" not in why, why
    fp = json.loads(recs.read_text(encoding="utf-8").splitlines()[-1])["fingerprint"]
    assert btr._parts_for(recs, fp), "run-stage 沒寫診斷旁表（之後 explain 又答不出環境哪一項不同）"
    # 同 tree、不同輪的票根：指紋不變 ⇒ 建包（或第二次 run-stage）的結果對得上
    monkeypatch.setenv("MOTRIX_CI_TICKET", "D:/q/ticket-0002.json")
    rc2, wrote2, _ = btr.run_stage(tiny_repo, "e2e", recs, runner=lambda cmd, cwd, env: 0, note=lambda *_: None)
    fp2 = json.loads(recs.read_text(encoding="utf-8").splitlines()[-1])["fingerprint"]
    assert wrote2 and fp2 == fp
    # 仍會擋沿用的成分要在結束時說出來
    monkeypatch.setenv("MOTRIX_TRAIN", "1")
    _, _, why3 = btr.run_stage(tiny_repo, "not_e2e", recs, runner=lambda cmd, cwd, env: 0, note=lambda *_: None)
    assert "⚠" in why3 and "MOTRIX_TRAIN" in why3, why3
