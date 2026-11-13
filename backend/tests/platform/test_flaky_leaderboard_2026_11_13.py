# -*- coding: utf-8 -*-
"""偶發排行榜（T84）：只記錄、不影響結果。

硬規則的守門：
 (a) 沒有任何其他建包／偶發工具引用排行榜（known_flakes／failfast／fail_stream／build_test_reuse／modtest／build_deploy_package.ps1），
     flaky_retry.py 裡只有一處、在 main() 的 `try … except Exception` 裡；
 (b) 同一組重跑結果：排行榜寫得成、寫失敗（丟例外）、寫到寫不進去的路徑 ⇒ `flaky_retry.main` 的結束碼與 --result-out 逐字相同；
 (c) known_flakes.json 的 flakes 保持空（排行榜不會自動登記），且跑完 main 後登記簿檔案沒被動。
另鎖：事件格式、排序與天數窗、檔案大小上限、.gitignore。
"""
import ast
import importlib.util
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PLAT = REPO / "tools" / "platform"
BACKEND = REPO / "backend"
if str(PLAT) not in sys.path:
    sys.path.insert(0, str(PLAT))

import flaky_leaderboard as LB  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FR = _load("_flaky_retry_lb_t", PLAT / "flaky_retry.py")

NOW = datetime(2026, 11, 13, 12, 0, 0)
NID_A = "tests/test_a.py::test_a"
NID_B = "tests/test_b.py::test_b"


def _res(nid, attempts, passed):
    return {"nodeid": nid, "attempts": attempts, "passed": passed}


# ── 記錄與統計 ─────────────────────────────────────────────────────────────────────

def test_record_writes_one_line_per_retried_test_and_skips_empty(tmp_path):
    p = tmp_path / "lb.jsonl"
    assert LB.record([], "r1", "s1", path=p, now=NOW) == 0 and not p.exists()                 # 沒重跑任何題 ⇒ 不建檔
    n = LB.record([_res(NID_A, [1, 0], True), _res(NID_B, [1, 1], False), {"nodeid": "", "attempts": [], "passed": False}],
                  "r1", "s1", path=p, now=NOW)
    assert n == 2
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    assert [r["nodeid"] for r in rows] == [NID_A, NID_B]
    assert rows[0] == {"t": "2026-11-13T12:00:00", "run": "r1", "stage": "s1", "nodeid": NID_A, "attempts": [1, 0], "passed": True}
    assert rows[1]["passed"] is False


def test_aggregate_ranks_flaky_first_and_respects_the_day_window():
    ev = []
    for days_ago, nid, passed in [(1, NID_A, True), (2, NID_A, True), (3, NID_B, True), (10, NID_B, True), (10, NID_B, True),
                                  (1, "tests/test_c.py::test_c", False)]:
        t = (NOW - timedelta(days=days_ago)).strftime(LB.TS_FMT)
        ev.append({"t": t, "run": "r%s%s" % (days_ago, nid[-1]), "stage": "s", "nodeid": nid, "attempts": [1, 0], "passed": passed})
    w7 = LB.aggregate(ev, 7, NOW)
    assert [r["nodeid"] for r in w7] == [NID_A, NID_B, "tests/test_c.py::test_c"]                # 偶發 2、1、0（真紅排最後）
    assert w7[0]["flaky"] == 2 and w7[1]["flaky"] == 1 and w7[2]["hard_fail"] == 1 and w7[2]["flaky"] == 0
    w30 = LB.aggregate(ev, 30, NOW)
    assert next(r for r in w30 if r["nodeid"] == NID_B)["flaky"] == 3                           # 30 天窗看得到 10 天前的
    assert LB.aggregate([], 7, NOW) == []


def test_cli_prints_text_and_json_and_tolerates_missing_or_garbled_file(tmp_path, capsys):
    p = tmp_path / "lb.jsonl"
    assert LB.main(["--path", str(p)]) == 0
    assert "沒有偶發紀錄" in capsys.readouterr().out
    LB.record([_res(NID_A, [1, 0], True)], "r1", "s1", path=p, now=datetime.now())
    with open(p, "a", encoding="utf-8") as f:
        f.write("這不是 json\n")
    assert LB.main(["--path", str(p), "--days", "7", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["days"] == 7 and [r["nodeid"] for r in out["rows"]] == [NID_A] and out["rows"][0]["flaky"] == 1
    assert LB.main(["--path", str(p), "--days", "30"]) == 0
    assert NID_A in capsys.readouterr().out


def test_file_size_is_bounded_old_lines_dropped_then_only_the_last_lines_kept(tmp_path, monkeypatch):
    p = tmp_path / "lb.jsonl"
    monkeypatch.setattr(LB, "MAX_BYTES", 2000)
    monkeypatch.setattr(LB, "MAX_LINES", 5)
    old = NOW - timedelta(days=LB.KEEP_DAYS + 5)
    LB.record([_res("tests/old.py::t", [1, 0], True)], "old", "s", path=p, now=old)
    for i in range(40):
        LB.record([_res("tests/n%02d.py::t" % i, [1, 0], True)], "r%d" % i, "s", path=p, now=NOW)
    lines = p.read_text(encoding="utf-8").splitlines()
    assert 0 < len(lines) <= 40 and p.stat().st_size < 2000 * 3                                  # 沒有無限長大
    assert not any("tests/old.py" in ln for ln in lines), "超過保留天數的行沒被丟掉"
    assert "tests/n39.py::t" in lines[-1], "最新的一筆被修剪掉了"


def test_default_path_is_gitignored_and_env_overrides_it(monkeypatch, tmp_path):
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "tools/platform/" + LB.FILE_NAME in ignore.replace("\r", "").splitlines()
    monkeypatch.setenv(LB.PATH_ENV, str(tmp_path / "x.jsonl"))
    assert LB.default_path() == tmp_path / "x.jsonl"
    monkeypatch.delenv(LB.PATH_ENV)
    assert LB.default_path().name == LB.FILE_NAME


# ── (a) 沒有人引用排行榜 ───────────────────────────────────────────────────────────

NOT_ALLOWED_TO_MENTION = [PLAT / "known_flakes.py", PLAT / "failfast.py", PLAT / "fail_stream.py", PLAT / "modtest.py",
                          BACKEND / "tools" / "build_test_reuse.py", BACKEND / "tools" / "build_deploy_package.ps1"]


def test_a_no_other_build_or_flaky_tool_mentions_the_leaderboard():
    for f in NOT_ALLOWED_TO_MENTION:
        assert f.is_file(), "守門的對象不見了（被搬走？）：%s" % f
        assert "leaderboard" not in f.read_text(encoding="utf-8-sig", errors="replace").lower(), "%s 引用了排行榜——排行榜只能被 flaky_retry 的 hook 寫入" % f.name
    # 排行榜本身不讀登記簿與判定
    src = (PLAT / "flaky_leaderboard.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"known_flakes", "failfast", "build_test_reuse", "modtest"}, imported


def _parents(tree):
    par = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            par[ch] = node
    return par


def test_a_the_only_reference_in_flaky_retry_is_inside_a_swallow_all_try_in_main():
    tree = ast.parse((PLAT / "flaky_retry.py").read_text(encoding="utf-8"))
    par = _parents(tree)
    imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
               and any("flaky_leaderboard" in (a.name or "") for a in getattr(n, "names", [])) or
               isinstance(n, ast.ImportFrom) and "flaky_leaderboard" in (n.module or "")]
    uses = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "_lb"]
    assert len(imports) == 1 and uses, "hook 應該恰好一處 import、並有使用"
    for node in imports + uses:
        chain, cur = [], node
        while cur in par:
            cur = par[cur]
            chain.append(cur)
        tries = [c for c in chain if isinstance(c, ast.Try)]
        assert tries, "hook 沒包在 try 裡"
        t = tries[0]
        assert any(isinstance(h.type, ast.Name) and h.type.id == "Exception" for h in t.handlers), "hook 的 except 沒吞掉所有例外"
        assert any(isinstance(c, ast.FunctionDef) and c.name == "main" for c in chain), "hook 不在 main() 裡"
        # hook 在 main 中位於結果檔寫出與 fail_stream 追加之後（結果已定案）
    main = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
    stmts = main.body
    idx_hook = next(i for i, s in enumerate(stmts) if isinstance(s, ast.Try) and any(u in ast.walk(s) for u in uses))
    idx_write = next(i for i, s in enumerate(stmts) if "write_text" in ast.dump(s) and "result_out" in ast.dump(s))
    assert idx_hook > idx_write, "hook 必須在 --result-out 寫完之後"


# ── (b)(c) 不影響結果 ──────────────────────────────────────────────────────────────

def _run_main(tmp_path, monkeypatch, tag, lb_mode):
    """跑一次 flaky_retry.main：一題紅、重跑第 2 次綠、已登記 ⇒ 預期放行。lb_mode：ok／raise／unwritable。"""
    import fail_stream
    monkeypatch.setenv(fail_stream.DIR_ENV, str(tmp_path / ("fs-" + tag)))
    out = tmp_path / ("out-%s.txt" % tag)
    out.write_text("FAILED %s - boom\n" % NID_A, encoding="utf-8")
    reg = tmp_path / ("reg-%s.json" % tag)
    reg.write_text(json.dumps({"flakes": [{"nodeid": NID_A, "first_seen": "2026-11-01", "owner": "t", "ticket": "T-1",
                                            "expires": (date.today() + timedelta(days=7)).isoformat()}]}), encoding="utf-8")
    res = tmp_path / ("res-%s.json" % tag)
    lb_file = tmp_path / ("lb-%s.jsonl" % tag)
    if lb_mode == "unwritable":
        blocker = tmp_path / "iam-a-file"
        blocker.write_text("x", encoding="utf-8")
        lb_file = blocker / "sub" / "lb.jsonl"                         # 父層是檔案 ⇒ mkdir／open 都會 OSError
    monkeypatch.setenv(LB.PATH_ENV, str(lb_file))
    if lb_mode == "raise":
        def _boom(*a, **k):
            raise RuntimeError("排行榜壞了")
        monkeypatch.setattr(LB, "record", _boom)
    monkeypatch.setattr(FR, "make_runner", lambda *a, **k: (lambda nid, attempt: 0 if attempt == 2 else 1))
    rc = FR.main(["--run-id", "run-" + tag, "--stage", "stg", "--exit-code", "1", "--output-file", str(out), "--basetemp-prefix",
                  str(tmp_path / "bt"), "--result-out", str(res), "--registry", str(reg)])
    stream = (tmp_path / ("fs-" + tag) / ("run-" + tag + ".jsonl")).read_text(encoding="utf-8")
    return rc, res.read_text(encoding="utf-8"), lb_file, stream


def test_b_leaderboard_ok_failing_or_unwritable_does_not_change_exit_code_or_result(tmp_path, monkeypatch):
    rc_ok, res_ok, lb_file, _ = _run_main(tmp_path, monkeypatch, "ok", "ok")
    assert rc_ok == 0, "基準情境本身要放行（一題紅、重跑綠、已登記）"
    rows = [json.loads(x) for x in lb_file.read_text(encoding="utf-8").splitlines()]          # 正對照：寫得成時真的有記到
    assert len(rows) == 1 and rows[0]["nodeid"] == NID_A and rows[0]["passed"] is True and rows[0]["attempts"] == [1, 0]
    monkeypatch.undo()
    rc_raise, res_raise, _, _ = _run_main(tmp_path, monkeypatch, "raise", "raise")
    monkeypatch.undo()
    rc_bad, res_bad, bad_file, _ = _run_main(tmp_path, monkeypatch, "bad", "unwritable")
    assert not bad_file.exists()
    assert rc_ok == rc_raise == rc_bad == 0
    norm = lambda s, tag: s.replace(tag, "X")  # noqa: E731  結果檔裡只有 run id 不同
    assert norm(res_ok, "run-ok") == norm(res_raise, "run-raise") == norm(res_bad, "run-bad")


def test_b_a_blocked_retry_leaves_the_same_exit_code_with_and_without_the_leaderboard(tmp_path, monkeypatch):
    """未登記的偶發（重跑綠）照樣擋下（exit 1）——排行榜記了它，但判定不變。"""
    import fail_stream
    monkeypatch.setenv(fail_stream.DIR_ENV, str(tmp_path / "fs"))
    out = tmp_path / "out.txt"
    out.write_text("FAILED %s - boom\n" % NID_B, encoding="utf-8")
    reg = tmp_path / "reg.json"
    reg.write_text(json.dumps({"flakes": []}), encoding="utf-8")
    monkeypatch.setenv(LB.PATH_ENV, str(tmp_path / "lb.jsonl"))
    monkeypatch.setattr(FR, "make_runner", lambda *a, **k: (lambda nid, attempt: 0 if attempt == 2 else 1))
    rc = FR.main(["--run-id", "r", "--stage", "s", "--exit-code", "1", "--output-file", str(out), "--basetemp-prefix",
                  str(tmp_path / "bt"), "--result-out", str(tmp_path / "res.json"), "--registry", str(reg)])
    assert rc == 1
    assert json.loads((tmp_path / "res.json").read_text(encoding="utf-8"))["ok"] is False
    assert json.loads((tmp_path / "lb.jsonl").read_text(encoding="utf-8").splitlines()[0])["nodeid"] == NID_B


def test_c_known_flakes_registry_stays_empty_and_untouched_by_a_run(tmp_path, monkeypatch):
    real = PLAT / "known_flakes.json"
    before = real.read_bytes()
    assert json.loads(before.decode("utf-8-sig"))["flakes"] == [], "known_flakes.json 的 flakes 要保持空：登記只由人做（known_flakes.py add）"
    _run_main(tmp_path, monkeypatch, "c", "ok")
    assert real.read_bytes() == before
