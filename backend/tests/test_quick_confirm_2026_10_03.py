"""快速確認（build_test_reuse run-stage --only-failed）：找錯迴圈用，結果只是提示——不寫沿用紀錄、不影響 lookup-stage、不算階段綠燈。
反向控制：快速確認綠之後 lookup-stage 仍是 None（拿掉「不寫紀錄」的保證＝這題紅）。"""
import json
import os
from datetime import datetime

from tools import build_test_reuse as tr

FP = "f" * 40


def _stream(tmp_path, rows):
    p = tmp_path / "run1.jsonl"
    p.write_text("\n".join(json.dumps(r) if isinstance(r, dict) else r for r in rows) + "\n", encoding="utf-8")
    return p


def _tree(tmp_path):
    repo = tmp_path / "repo"
    d = repo / "backend" / "tests" / "x"
    d.mkdir(parents=True)
    for n in ("test_a.py", "test_b.py", "test_c.py", "helper.py"):
        (d / n).write_text("def test_ok():\n    pass\n", encoding="utf-8")
    return repo


def test_failed_nodeids_takes_fail_and_node_down_only_dedupes_and_skips_bad_lines(tmp_path):
    p = _stream(tmp_path, [
        {"type": "fail", "nodeid": "tests/x/test_a.py::test_1", "stage": "not_e2e"},
        {"type": "fail", "nodeid": "tests" + chr(92) + "x" + chr(92) + "test_a.py::test_1", "stage": "not_e2e"},          # 反斜線＋重複
        {"type": "node_down", "nodeid": "tests/x/test_b.py::test_2", "stage": "not_e2e"},
        {"type": "aborted", "nodeid": "tests/x/test_c.py::test_3", "stage": "not_e2e"},        # 外部終止不算
        {"type": "summary", "stage": "not_e2e"},
        {"type": "fail", "nodeid": "tests/x/test_e2e.py::test_4", "stage": "e2e"},
        "{壞行", {"type": "fail"}])
    assert tr.failed_nodeids(p) == ["tests/x/test_a.py::test_1", "tests/x/test_b.py::test_2", "tests/x/test_e2e.py::test_4"]
    assert tr.failed_nodeids(p, "not_e2e") == ["tests/x/test_a.py::test_1", "tests/x/test_b.py::test_2"]


def test_quick_targets_exact_nodeids_vs_siblings_and_missing_files(tmp_path):
    repo = _tree(tmp_path)
    ids = ["tests/x/test_a.py::test_ok", "tests/gone/test_z.py::test_1"]
    t, missing = tr.quick_targets(repo, ids)
    assert t == ["tests/x/test_a.py::test_ok"] and missing == ["tests/gone/test_z.py"]
    t, missing = tr.quick_targets(repo, ids, with_siblings=True)
    assert t == ["tests/x/test_a.py", "tests/x/test_b.py", "tests/x/test_c.py"] and missing == ["tests/gone/test_z.py"]      # helper.py 不是 test_*


def test_run_only_failed_runs_targets_via_argsfile_without_failfast_and_labels_output(tmp_path):
    repo = _tree(tmp_path)
    p = _stream(tmp_path, [{"type": "fail", "nodeid": "tests/x/test_a.py::test_ok", "stage": "not_e2e"}])
    seen, notes = {}, []

    def runner(cmd, cwd, env):
        af = [c for c in cmd if c.startswith("@")][0][1:]
        seen["targets"] = open(af, encoding="utf-8").read().split()
        seen["cmd"], seen["cwd"] = cmd, cwd
        return 0
    rc, why = tr.run_only_failed(repo, "not_e2e", p, runner=runner, note=notes.append)
    assert rc == 0 and seen["targets"] == ["tests/x/test_a.py::test_ok"] and seen["cwd"].endswith("backend")
    assert "-p" in seen["cmd"] and "fail_stream" not in seen["cmd"] and "failfast" not in seen["cmd"]       # 不寫 fail_stream、不 fail-fast
    assert "not e2e" in seen["cmd"] and not os.path.exists([c for c in seen["cmd"] if c.startswith("@")][0][1:])     # 用完刪 argsfile
    assert notes and all(tr.QUICK_LABEL in n for n in notes) and "不算階段綠燈" in why


def test_run_only_failed_with_empty_stream_or_gone_files_does_not_claim_green(tmp_path):
    repo = _tree(tmp_path)
    rc, why = tr.run_only_failed(repo, "not_e2e", _stream(tmp_path, [{"type": "summary"}]), runner=lambda *a: 1 / 0, note=lambda s: None)
    assert rc == 0 and "沒有失敗題" in why                                                              # 沒有東西可確認（不呼叫 runner）
    p = tmp_path / "gone.jsonl"
    p.write_text(json.dumps({"type": "fail", "nodeid": "tests/gone/test_z.py::t"}) + "\n", encoding="utf-8")
    rc, why = tr.run_only_failed(repo, "not_e2e", p, runner=lambda *a: 1 / 0, note=lambda s: None)
    assert rc == 2


def test_green_quick_confirm_never_lets_lookup_stage_hit(tmp_path, monkeypatch):
    """反向控制：同指紋的階段是紅的；快速確認這批題綠了——lookup-stage 仍不得命中，紀錄檔一個位元都不能變。"""
    repo = _tree(tmp_path)
    records = tmp_path / "records.jsonl"
    tr.record(records, FP, False, "abc1234", stages={"not_e2e": tr.stage_entry(False)}, source="standalone")
    before = records.read_bytes()
    def boom(*a, **k):                                                                                # 任何寫紀錄的嘗試（record／_append／default_records）都直接失敗
        raise AssertionError("快速確認不得寫沿用紀錄")
    for fn in ("record", "_append", "default_records"):
        monkeypatch.setattr(tr, fn, boom)
    p = _stream(tmp_path, [{"type": "fail", "nodeid": "tests/x/test_a.py::test_ok", "stage": "not_e2e"}])
    rc, _ = tr.run_only_failed(repo, "not_e2e", p, runner=lambda *a: 0, note=lambda s: None)
    assert rc == 0
    assert tr.lookup_stage(records, FP, "not_e2e", datetime.now()) is None
    assert records.read_bytes() == before
    tr.run_only_failed(repo, "e2e", _stream(tmp_path, [{"type": "fail", "nodeid": "tests/x/test_a.py::test_ok"}]), runner=lambda *a: 0, note=lambda s: None)
