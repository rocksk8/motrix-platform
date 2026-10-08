# -*- coding: utf-8 -*-
"""regen_all（建包優化 O2）：順序、--check 不寫檔、出錯即停、改動清單。用假 runner，不跑真正的產生器（秒級）。"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import regen_all as R  # noqa: E402

PY = "PY"


def _repo(tmp_path, files=("docs/platform/dep_graph.json", "docs/platform/UNIT-INDEX.md", "docs/platform/test_map.json")):
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("old\n", encoding="utf-8")
    return tmp_path


class Fake:
    """記錄每次呼叫；可指定哪個指令回什麼碼、寫什麼檔。"""
    def __init__(self, repo, rc=None, write=None):
        self.repo, self.calls, self.rc, self.write = repo, [], rc or {}, write or {}

    def __call__(self, cmd, cwd=None, **kw):
        self.calls.append(list(cmd))
        key = next((k for k in ("dep_scan", "unit_index", "test_map", "train_number") if any(k in c for c in cmd)), "?")
        if "--out" in cmd:                                     # dep_scan 重產到暫存
            Path(cmd[cmd.index("--out") + 1]).write_text(self.write.get(key, "old\n"), encoding="utf-8")
        elif key in self.write and "--check" not in cmd:       # 寫入模式：寫進 repo 內的產生檔
            rel = {s[0]: s[1] for s in R.STEPS}.get({"dep_scan": "dep_graph"}.get(key, key))
            if rel:
                (Path(self.repo) / rel).write_text(self.write[key], encoding="utf-8")
        return subprocess.CompletedProcess(cmd, self.rc.get(key, 0), stdout="", stderr="")


def test_plan_order_is_dep_graph_then_unit_index_then_test_map_and_number_first_when_asked():
    names = [s[0] for s in R.plan(PY)]
    assert names == ["dep_graph", "unit_index", "test_map"]
    names = [s[0] for s in R.plan(PY, take_number=True)]
    assert names == ["train_number", "dep_graph", "unit_index", "test_map"]
    cmd = R.plan(PY, base="origin/x", take_number=True)[0][2]
    assert cmd[-2:] == ["--base", "origin/x"] and "{" not in " ".join(cmd)


def test_check_mode_current_files_exit_ok_and_write_nothing(tmp_path):
    repo = _repo(tmp_path)
    fake = Fake(repo)
    res = R.run(repo, check_only=True, py=PY, runner=fake)
    assert res["ok"] and res["stale"] == [] and res["error"] is None
    assert all((repo / r).read_text() == "old\n" for r in ("docs/platform/dep_graph.json", "docs/platform/UNIT-INDEX.md", "docs/platform/test_map.json"))
    assert any("--out" in c for c in fake.calls)               # dep_graph 是重產到暫存目錄
    assert not any(c[-1] == "tools/platform/test_map.py" for c in fake.calls)   # 沒有一個寫入指令被叫


def test_check_mode_reports_every_stale_file(tmp_path):
    repo = _repo(tmp_path)
    fake = Fake(repo, rc={"unit_index": 1, "test_map": 1}, write={"dep_scan": "NEW\n"})
    res = R.run(repo, check_only=True, py=PY, runner=fake)
    assert not res["ok"] and res["stale"] == ["dep_graph", "unit_index", "test_map"]
    assert R.main  # CLI 退出碼：過期 ⇒ 1（下一題）


def test_check_mode_tool_error_is_exit2_not_stale(tmp_path):
    repo = _repo(tmp_path)
    res = R.run(repo, check_only=True, py=PY, runner=Fake(repo, rc={"unit_index": 5}))
    assert not res["ok"] and res["error"] and "unit_index" in res["error"] and res["stale"] == []


def test_write_mode_runs_in_order_and_lists_only_changed_files(tmp_path):
    repo = _repo(tmp_path)
    fake = Fake(repo, write={"dep_scan": "NEW\n", "test_map": "old\n"})
    res = R.run(repo, py=PY, runner=fake)
    assert res["ok"] and res["changed"] == ["docs/platform/dep_graph.json"]
    order = [next(k for k in ("dep_scan", "unit_index", "test_map") if k in c[1]) for c in fake.calls]
    assert order == ["dep_scan", "unit_index", "test_map"]


def test_write_mode_stops_at_the_first_failure(tmp_path):
    repo = _repo(tmp_path)
    fake = Fake(repo, rc={"dep_scan": 2})
    res = R.run(repo, py=PY, runner=fake)
    assert not res["ok"] and "dep_graph" in res["error"]
    assert len(fake.calls) == 1                                # 後面的步驟讀前面的輸出 ⇒ 不繼續


def test_take_number_runs_first_and_only_when_asked(tmp_path):
    repo = _repo(tmp_path)
    fake = Fake(repo)
    R.run(repo, py=PY, runner=fake)
    assert not any("train_number" in " ".join(c) for c in fake.calls)
    fake = Fake(repo)
    R.run(repo, take_number=True, py=PY, runner=fake)
    assert "train_number" in " ".join(fake.calls[0]) and "assign" in fake.calls[0]


def test_cli_exit_codes_and_no_git(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path)
    monkeypatch.setattr(R.subprocess, "run", Fake(repo, rc={"test_map": 1}, write={"dep_scan": "old\n"}))
    assert R.main(["--check", "--repo", str(repo)]) == 1
    cap = capsys.readouterr()
    assert cap.out.splitlines() == ["docs/platform/test_map.json"]         # stdout＝只有過期檔路徑（train_preflight 約定）
    assert "test_map" in cap.err
    monkeypatch.setattr(R.subprocess, "run", Fake(repo, write={"dep_scan": "old\n"}))
    assert R.main(["--check", "--repo", str(repo)]) == 0
    assert capsys.readouterr().out == ""                                    # 都是最新 ⇒ stdout 空
    monkeypatch.setattr(R.subprocess, "run", Fake(repo, rc={"unit_index": 7}))
    assert R.main(["--check", "--repo", str(repo)]) == 2
    fake = Fake(repo)
    R.run(repo, take_number=True, py=PY, runner=fake)
    assert not any(c[0] == "git" or "git" in c[1:2] for c in fake.calls)       # 不碰 git（不 add／commit）
