# -*- coding: utf-8 -*-
"""T87 A2：列車收尾一鍵（tools/platform/train_endgame.py）的契約題。

用拋棄式 git repo 驗：功能變更判定、檢查 ①（沒有版本紀錄就擋、逃生口格式）、a1_expectations 產生規則（免登入端點不列、
新路由才列）、bottom_layer 補登、步驟檔事實區塊與代入、包檢查。不碰真的 repo 狀態，不跑 pytest 子行程。"""
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[3] / "tools" / "platform" / "train_endgame.py"


@pytest.fixture(scope="module")
def eg():
    import sys
    sys.path.insert(0, str(TOOL.parent))
    spec = importlib.util.spec_from_file_location("_train_endgame_under_test", str(TOOL))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                   capture_output=True, text=True, encoding="utf-8")


def _write(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _write(r, "backend/version_manifest.json", json.dumps([{"module": "舊/功能", "version": "2026-11-01a", "date": "2026-11-01", "time": "10:00", "content": "x"}], ensure_ascii=False))
    _write(r, "backend/modules/alpha/module.json", json.dumps({"version": "1.0.0"}))
    _write(r, "backend/modules/alpha/api.py", "x = 1\n")
    _write(r, "backend/main.py", '_PUBLIC_API_PATHS = {"/api/ping", "/api/public/x"}\n')
    _write(r, "backend/tests/platform/route_inventory.json", json.dumps({"endpoints": {"GET /api/old": {"w": False}}}))
    _write(r, "frontend/index.html", "<html></html>")
    _commit(r, "base")
    _git(r, "tag", "base")
    return r


# ── 功能變更判定 ───────────────────────────────────────────────────────────

def test_endgame_functional_files_keeps_product_code_and_drops_bookkeeping(eg):
    changed = ["backend/modules/alpha/api.py", "frontend/pages/a.html", "backend/modules/alpha/tests/test_a.py",
               "backend/tests/test_b.py", "backend/modules/alpha/CHANGELOG.md", "backend/version_manifest.json",
               "backend/modules/alpha/module.json", "backend/tools/delivery.py", "docs/platform/x.md", "tools/platform/a.py",
               "backend/a1_expectations.json", "backend/README.md"]
    assert eg.functional_files(changed) == ["backend/modules/alpha/api.py", "frontend/pages/a.html"]


def test_endgame_functional_files_accepts_windows_separators(eg):
    assert eg.functional_files(["backend\\modules\\alpha\\api.py"]) == ["backend/modules/alpha/api.py"]


# ── 檢查 ①：版本紀錄 ───────────────────────────────────────────────────────

def test_endgame_version_record_blocks_functional_change_without_new_entry(eg, repo):
    _write(repo, "backend/modules/alpha/api.py", "x = 2\n")
    _commit(repo, "change")
    r = eg.check_version_record(repo, "base")
    assert r.status == eg.BLOCK and "alpha" in " ".join(r.lines)


def test_endgame_version_record_passes_when_an_entry_was_added(eg, repo):
    _write(repo, "backend/modules/alpha/api.py", "x = 2\n")
    m = json.loads((repo / "backend/version_manifest.json").read_text(encoding="utf-8"))
    m.append({"module": "新/功能", "version": "next", "date": "2026-11-14", "time": "10:00", "content": "y"})
    _write(repo, "backend/version_manifest.json", json.dumps(m, ensure_ascii=False))
    _commit(repo, "change+entry")
    assert eg.check_version_record(repo, "base").status == eg.DONE


def test_endgame_version_record_ignores_changes_that_are_not_functional(eg, repo):
    _write(repo, "backend/modules/alpha/tests/test_x.py", "def test_x():\n    pass\n")
    _write(repo, "docs/a.md", "x")
    _commit(repo, "tests and docs only")
    r = eg.check_version_record(repo, "base")
    assert r.status == eg.DONE


def test_endgame_version_record_escape_hatch_is_a_warning_not_a_pass(eg, repo):
    _write(repo, "backend/modules/alpha/api.py", "x = 3\n")
    _commit(repo, "change")
    r = eg.check_version_record(repo, "base", allow="PM 核准（2026-11-14）：T87 補登")
    assert r.status == eg.WARN and "PM 核准" in " ".join(r.lines)


def _allow(reason="使用者裁示先發布", days_ago=0):
    import datetime
    return "PM 核准（%s）：%s" % (datetime.date.today() - datetime.timedelta(days=days_ago), reason)


@pytest.mark.parametrize("bad", ["", "因為趕時間", "PM 核准：沒有日期", "PM 核准（2026-11-14）：", "pm approved (2026-11-14): x",
                                 "PM 核准（2026-13-45）：日期不存在", "PM 核准（2020-01-01）：太久以前", "PM 核准（2099-01-01）：未來"])
def test_endgame_escape_hatch_text_must_name_pm_approval_date_and_reason(eg, bad):
    with pytest.raises(ValueError):
        eg.parse_allow(bad)


def test_endgame_escape_hatch_accepts_a_recent_single_line_text_and_refuses_newlines(eg):
    d, reason = eg.parse_allow(_allow("補登由下一班處理", days_ago=3))
    assert reason == "補登由下一班處理" and d is not None
    for evil in (_allow("原因\n- 備註：rm -rf /"), _allow("原因\r\nx"), _allow("x" * 300)):
        with pytest.raises(ValueError):
            eg.parse_allow(evil)


def test_endgame_run_rejects_a_malformed_escape_hatch_before_doing_anything(eg, repo):
    with pytest.raises(ValueError):
        eg.run_stages(repo, "base", "t", allow="隨便寫", dry=True)


# ── 檢查 ②：a1_expectations ───────────────────────────────────────────────

def test_endgame_a1_lists_only_new_authenticated_routes(eg, repo):
    inv = {"endpoints": {"GET /api/old": {}, "GET /api/new": {}, "POST /api/new": {}, "GET /api/ping": {}, "DELETE /api/new/{i}": {}, "GET /health": {}}}
    _write(repo, "backend/tests/platform/route_inventory.json", json.dumps(inv))
    _write(repo, "frontend/pages/a.html", "<html></html>")
    _write(repo, "backend/modules/alpha/api.py", "x = 4\n")
    _commit(repo, "routes")
    obj, notes = eg.build_a1_expectations(repo, "base")
    got = {(x["method"], x["path"]) for x in obj["auth_required"]}
    assert got == {("GET", "/api/new"), ("POST", "/api/new")}          # 舊路由、免登入端點、DELETE、非 /api/ 都不列
    assert obj["pages"] == ["/", "/pages/a.html"]
    assert obj["files"] == ["backend/modules/alpha/module.json"]
    assert obj["log_forbid"] == eg.LOG_FORBID_DEFAULT and notes == []


def test_endgame_a1_skips_auth_required_when_public_list_cannot_be_read(eg, repo):
    _write(repo, "backend/main.py", "def f():\n    return 1\n")
    _write(repo, "backend/tests/platform/route_inventory.json", json.dumps({"endpoints": {"GET /api/old": {}, "GET /api/new": {}}}))
    _commit(repo, "no public list")
    obj, notes = eg.build_a1_expectations(repo, "base")
    assert "auth_required" not in obj and any("_PUBLIC_API_PATHS" in n for n in notes)


def test_endgame_a1_output_passes_the_consumer_format_rules(eg, repo):
    """h7 的格式規則：路徑以單一 / 開頭、不含 scheme／@／反斜線／空白；method 只准四種；files 不得絕對或含 ..。"""
    inv = {"endpoints": {"GET /api/old": {}, "GET /api/x/{id}": {}}}
    _write(repo, "backend/tests/platform/route_inventory.json", json.dumps(inv))
    _write(repo, "frontend/pages/b.html", "<html></html>")
    _commit(repo, "x")
    obj, _ = eg.build_a1_expectations(repo, "base")
    paths = list(obj.get("pages", [])) + [x["path"] for x in obj.get("auth_required", [])]
    for p in paths:
        assert p.startswith("/") and not p.startswith("//") and not any(ch in p for ch in ("@", "\\", " ")) and "://" not in p
    assert all(x["method"] in ("GET", "POST", "HEAD", "OPTIONS") for x in obj.get("auth_required", []))
    assert all(not f.startswith("/") and ".." not in f for f in obj.get("files", []))


# ── bottom_layer 補登 ─────────────────────────────────────────────────────

def test_endgame_bottom_layer_sync_appends_missing_entries_without_reordering(eg, repo, monkeypatch):
    _write(repo, "tools/platform/bottom_layer.json", '{\n "format": 1,\n "global_tests": [\n  "backend/tests/test_a.py",\n  "backend/tests/test_old.py"\n ],\n "rules": []\n}\n')
    monkeypatch.setattr(eg, "bottom_layer_gap", lambda r: (["backend/tests/test_new.py"], ["backend/tests/test_old.py"]))
    missing, stale = eg.sync_bottom_layer(repo)
    data = json.loads((repo / "tools/platform/bottom_layer.json").read_text(encoding="utf-8"))
    assert missing == ["backend/tests/test_new.py"] and stale == ["backend/tests/test_old.py"]
    assert data["global_tests"] == ["backend/tests/test_a.py", "backend/tests/test_old.py", "backend/tests/test_new.py"]   # 只補、不移除過期
    assert data["rules"] == [] and data["format"] == 1


# ── 步驟檔 ─────────────────────────────────────────────────────────────────

PKG = "20261114_191358_1580c8c1_full"


def _pkg_dir(tmp_path, name=PKG):
    d = tmp_path / name
    d.mkdir()
    (d / "package.sha256").write_bytes(b"abc  a.txt\n")
    return d, hashlib.sha256(b"abc  a.txt\n").hexdigest()


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def test_endgame_fill_replaces_only_the_placeholders_it_was_given(eg, tmp_path, repo):
    f = tmp_path / "s.md"
    f.write_text("包 <PKG_NAME> sha <PKG_SHA256> 凍結 <FREEZE_SHA> 前綴 <FREEZE_8> 其他 <ROOT>\n", encoding="utf-8")
    d, sha = _pkg_dir(tmp_path)
    head = _head(repo)
    done = eg.fill_step_file(f, pkg_name=PKG, pkg_sha=sha, freeze=head, pkg_dir=d, repo=repo)
    assert done == ["<PKG_NAME>", "<PKG_SHA256>", "<FREEZE_SHA>", "<FREEZE_8>"]
    assert f.read_text(encoding="utf-8") == "包 %s sha %s 凍結 %s 前綴 %s 其他 <ROOT>\n" % (PKG, sha, head, head[:8])
    assert eg.unfilled_placeholders(f) == []


def test_endgame_fill_rejects_unsafe_or_mismatched_values_and_writes_nothing(eg, tmp_path, repo):
    f = tmp_path / "s.md"
    text = "包 <PKG_NAME> sha <PKG_SHA256> 凍結 <FREEZE_SHA>\n"
    f.write_text(text, encoding="utf-8")
    d, sha = _pkg_dir(tmp_path)
    head = _head(repo)
    bad_cases = [
        dict(pkg_name="x; rm -rf /", pkg_sha=sha, freeze=head, pkg_dir=d),                        # 包名格式
        dict(pkg_name=PKG + "\\n`id`", pkg_sha=sha, freeze=head, pkg_dir=d),
        dict(pkg_name=PKG, pkg_sha="a" * 63, freeze=head, pkg_dir=d),                             # sha 長度
        dict(pkg_name=PKG, pkg_sha="b" * 64, freeze=head, pkg_dir=d),                             # 與 package.sha256 不符
        dict(pkg_name=PKG, pkg_sha=sha, freeze="$(id)", pkg_dir=d),                               # 凍結格式
        dict(pkg_name=PKG, pkg_sha=sha, freeze="f" * 40, pkg_dir=d),                              # 凍結不在 repo
        dict(pkg_name=PKG, pkg_sha=sha, freeze=head),                                             # 沒給 --pkg-dir
        dict(pkg_name="20261114_191358_deadbeef_full", pkg_sha=sha, freeze=head, pkg_dir=d),      # 資料夾名與包名不符
    ]
    for kw in bad_cases:
        with pytest.raises(ValueError):
            eg.fill_step_file(f, repo=repo, **kw)
        assert f.read_text(encoding="utf-8") == text


def test_endgame_fill_reports_placeholders_left_behind(eg, tmp_path, repo):
    f = tmp_path / "s.md"
    f.write_text("包 <PKG_NAME> 凍結 <FREEZE_SHA> 前綴 <FREEZE_8>\n", encoding="utf-8")
    d, sha = _pkg_dir(tmp_path)
    eg.fill_step_file(f, pkg_name=PKG, pkg_sha=sha, pkg_dir=d, repo=repo)
    assert eg.unfilled_placeholders(f) == ["<FREEZE_8>", "<FREEZE_SHA>"]


def test_endgame_step_file_facts_are_replaced_in_place_and_carry_the_override_note(eg, repo, tmp_path):
    _write(repo, "backend/core/registry.py", 'CORE_VERSION = "9.9"\n')
    _write(repo, "backend/tests/_prod_baseline.py", 'BASELINE = "%s"\n' % subprocess.run(["git", "-C", str(repo), "rev-parse", "base"], capture_output=True, text=True).stdout.strip())
    _write(repo, "docs/platform/prod-tasks/s.md", "# 步驟\n\n正文\n")
    _commit(repo, "setup")
    allow = _allow("補登由下一班處理")
    assert eg.write_step_file(repo, "base", "docs/platform/prod-tasks/s.md", "t", allow) is True
    first = (repo / "docs/platform/prod-tasks/s.md").read_text(encoding="utf-8")
    assert "正文" in first and eg.FACTS_BEGIN in first and "core 9.9" in first and allow in first
    assert "train-overrides/t.json" in first                                                      # 指到進版控的放行紀錄
    assert eg.write_step_file(repo, "base", "docs/platform/prod-tasks/s.md", "t", allow) is False   # 冪等
    assert (repo / "docs/platform/prod-tasks/s.md").read_text(encoding="utf-8") == first


# ── 包檢查 ─────────────────────────────────────────────────────────────────

def test_endgame_package_check_counts_pyc_and_hashes_the_sorted_file_list(eg, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.txt").write_bytes(b"1")
    (tmp_path / "b.txt").write_bytes(b"2")
    r = eg.package_check(tmp_path)
    rows = "%s  a/x.txt\n%s  b.txt\n" % (hashlib.sha256(b"1").hexdigest(), hashlib.sha256(b"2").hexdigest())
    assert r["files"] == 2 and r["pyc"] == 0 and r["pycache"] == 0
    assert r["filelist_sha256"] == hashlib.sha256(rows.encode()).hexdigest()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "m.cpython-312.pyc").write_bytes(b"x")
    r2 = eg.package_check(tmp_path)
    assert r2["pyc"] == 1 and r2["pycache"] == 1


def test_endgame_tracked_pyc_is_reported(eg, repo):
    _write(repo, "backend/__pycache__/a.cpython-312.pyc", "x")
    _commit(repo, "pyc")
    assert eg.tracked_pyc(repo) == ["backend/__pycache__/a.cpython-312.pyc"]


def test_endgame_stage_list_matches_the_documented_order(eg):
    assert eg.STAGES == ("baselines", "bottom_layer", "version_record", "a1_expectations", "changelog",
                         "l1_pre", "assign", "regen", "l1_post", "step_file", "pyc")
    for name in eg.STAGES:
        assert name in (TOOL.read_text(encoding="utf-8"))


# ── CHANGELOG 要寫在最後一次程式改動之後 ───────────────────────────────

def test_endgame_changelog_order_flags_code_changed_after_the_top_entry(eg, repo):
    _write(repo, "backend/modules/alpha/CHANGELOG.md", "# alpha\n\n## (next) — 2026-11-14（x）\n\n- a\n")
    _commit(repo, "changelog first")
    _write(repo, "backend/modules/alpha/api.py", "x = 5\n")
    _commit(repo, "code after the entry")
    bad = eg.changelog_order_problems(repo)
    assert list(bad) == ["alpha"] and "之後沒有新的版號條目" in bad["alpha"][0]


def test_endgame_changelog_order_is_clean_when_the_entry_comes_last(eg, repo):
    _write(repo, "backend/modules/alpha/api.py", "x = 6\n")
    _commit(repo, "code")
    _write(repo, "backend/modules/alpha/CHANGELOG.md", "# alpha\n\n## (next) — 2026-11-14（y）\n\n- b\n")
    _commit(repo, "entry after code")
    assert eg.changelog_order_problems(repo) == {}


# ── 取號會升核心主版號：沒處理 core_major_bump 就停（T86 CORE 2.0 事故）──────────────────

def _core_tree(repo, specs, next_head):
    _write(repo, "backend/core/registry.py", 'CORE_VERSION = "1.9"\n')
    _write(repo, "backend/core/CHANGELOG.md", "# core\n\n## %s\n- x\n\n## 1.9\n- y\n" % next_head)
    for k, spec in specs.items():
        _write(repo, "backend/modules/%s/module.json" % k, json.dumps({"version": "1.0.0", "core": spec}))


def test_core_major_gap_blocks_when_ranges_not_relaxed(eg, repo):
    _core_tree(repo, {"alpha": ">=1.0,<2.0", "beta": ">=1.0,<3.0"}, "(next:major)")
    gap = eg.core_major_gap(repo, "base")
    text = "\n".join(gap)
    assert gap and "core_major_bump" in text and "alpha" in text
    assert "beta" not in "\n".join(gap[1:-1])        # 已接受下一個主版號的模組不列


def test_core_major_gap_passes_after_core_major_bump(eg, repo):
    _core_tree(repo, {"alpha": ">=1.0,<3.0", "beta": ">=1.0,<3.0"}, "(next:major)")
    assert eg.core_major_gap(repo, "base") == []


def test_core_major_gap_silent_for_ordinary_assign(eg, repo):
    _core_tree(repo, {"alpha": ">=1.0,<2.0"}, "(next)")
    assert eg.core_major_gap(repo, "base") == []


# ── 複審修正（h11 M1–M3、S1–S4）：run 模式的安全與前置檢查 ────────────────────────────

_STUB_TRAIN_NUMBER = """import sys
from pathlib import Path
M = Path(__file__).resolve().parents[2] / "backend" / "_assigned.txt"
a = sys.argv[1:]
if a[:2] == ["assign", "--dry-run"]:
    sys.exit(0 if M.exists() else 3)
if a[:1] == ["assign"]:
    M.write_text("assigned\\n", encoding="utf-8")
    sys.exit(0)
if "--check" in a:
    sys.exit(0 if M.exists() else 1)
sys.exit(2)
"""


def _git_out(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8").stdout.strip()


@pytest.fixture()
def trainrepo(repo):
    """有一個功能變更 commit（base..HEAD 非空）、有 stub 的 train_number.py、工作樹乾淨。"""
    _write(repo, "backend/modules/alpha/api.py", "x = 2\n")
    _write(repo, "tools/platform/train_number.py", _STUB_TRAIN_NUMBER)
    _commit(repo, "feature + stub")
    return repo


def _stage(results, name):
    return next(r for r in results if r.stage == name)


def test_run_blocks_on_a_dirty_tree_and_commits_nothing(eg, trainrepo):
    _write(trainrepo, "scratch.txt", "someone else's file\n")
    before = _head(trainrepo)
    res = eg.run_stages(trainrepo, "base", "t", dry=False, only="assign")
    assert res[0].stage == "preflight" and res[0].status == eg.BLOCK and "scratch.txt" in " ".join(res[0].lines)
    assert [r.stage for r in res] == ["preflight"]
    assert _head(trainrepo) == before and not (trainrepo / "backend/_assigned.txt").exists()


def test_assign_commit_contains_only_the_files_the_tool_changed(eg, trainrepo):
    res = eg.run_stages(trainrepo, "base", "t", dry=False, only="assign")
    r = _stage(res, "assign")
    assert r.status == eg.DONE and len(r.commits) == 1
    assert _git_out(trainrepo, "show", "--name-only", "--format=", "HEAD").splitlines() == ["backend/_assigned.txt"]
    assert _git_out(trainrepo, "status", "--porcelain") == ""


def test_stage_commit_does_not_sweep_files_that_were_already_dirty(eg, trainrepo):
    """直接呼叫階段（略過 preflight）時，commit_tool_changes 也只帶走『階段開始之後』新出現的檔。"""
    _write(trainrepo, "scratch.txt", "x\n")
    ctx = eg.Ctx(trainrepo, "base", "t", None, None, "", False)
    r = eg.st_assign(ctx)
    assert r.status == eg.DONE
    assert _git_out(trainrepo, "show", "--name-only", "--format=", "HEAD").splitlines() == ["backend/_assigned.txt"]
    assert "scratch.txt" in _git_out(trainrepo, "status", "--porcelain")


def test_assign_is_done_without_a_commit_when_nothing_is_left_to_assign(eg, trainrepo):
    _write(trainrepo, "backend/_assigned.txt", "assigned\n")
    _commit(trainrepo, "already assigned")
    before = _head(trainrepo)
    r = eg.st_assign(eg.Ctx(trainrepo, "base", "t", None, None, "", False))
    assert r.status == eg.DONE and r.commits == [] and _head(trainrepo) == before


def test_assign_stops_for_a_core_major_bump_that_core_major_bump_has_not_handled(eg, trainrepo):
    _core_tree(trainrepo, {"alpha": ">=1.0,<2.0"}, "(next:major)")
    _commit(trainrepo, "core tree")
    before = _head(trainrepo)
    r = eg.st_assign(eg.Ctx(trainrepo, "base", "t", None, None, "", False))
    assert r.status == eg.BLOCK and "core_major_bump" in " ".join(r.lines)
    assert _head(trainrepo) == before and not (trainrepo / "backend/_assigned.txt").exists()


def test_preflight_blocks_a_base_that_is_head_or_unknown_or_not_an_ancestor(eg, repo):
    assert eg.preflight(repo, "base", True)[0].status == eg.BLOCK                       # base＝HEAD，沒有差異
    assert eg.preflight(repo, "no-such-ref", True)[0].status == eg.BLOCK
    _git(repo, "checkout", "-q", "-b", "other")
    _write(repo, "backend/modules/alpha/api.py", "x = 9\n")
    _commit(repo, "other branch")
    _git(repo, "tag", "otherbase")
    _git(repo, "checkout", "-q", "main")
    _write(repo, "backend/modules/alpha/api.py", "x = 8\n")
    _commit(repo, "main moves on")
    res, sha = eg.preflight(repo, "otherbase", False)
    assert res.status == eg.BLOCK and "祖先" in " ".join(res.lines) and sha


def test_preflight_ok_prints_both_shas_and_plan_only_warns_about_a_dirty_tree(eg, trainrepo):
    res, sha = eg.preflight(trainrepo, "base", True)
    assert res.status == eg.DONE and sha[:12] in res.lines[0] and _head(trainrepo)[:12] in res.lines[0]
    _write(trainrepo, "scratch.txt", "x")
    assert eg.preflight(trainrepo, "base", True)[0].status == eg.WARN
    assert eg.preflight(trainrepo, "base", False)[0].status == eg.BLOCK


def test_override_is_written_into_the_repo_bound_to_label_and_base(eg, trainrepo):
    allow = _allow("T87 補登")
    res = eg.run_stages(trainrepo, "base", "t87", allow=allow, dry=False, only="version_record")
    assert _stage(res, "override").commits and _stage(res, "version_record").status == eg.WARN
    rec = json.loads((trainrepo / "docs/platform/train-overrides/t87.json").read_text(encoding="utf-8"))
    assert rec["label"] == "t87" and rec["base_sha"] == _git_out(trainrepo, "rev-parse", "base") and rec["text"] == allow
    assert _git_out(trainrepo, "ls-files", "docs/platform/train-overrides/t87.json")             # 進版控
    # 之後不帶旗標也採用（同班同 base）
    res2 = eg.run_stages(trainrepo, "base", "t87", dry=False, only="version_record")
    assert _stage(res2, "version_record").status == eg.WARN and allow in " ".join(_stage(res2, "override").lines)


def test_override_does_not_carry_over_to_another_train_or_another_base(eg, trainrepo):
    eg.run_stages(trainrepo, "base", "t87", allow=_allow("T87 補登"), dry=False, only="version_record")
    # 另一班（label 不同）
    res = eg.run_stages(trainrepo, "base", "t88", dry=False, only="version_record")
    assert _stage(res, "version_record").status == eg.BLOCK
    # 同 label、base 換了
    _write(trainrepo, "backend/modules/alpha/api.py", "x = 77\n")
    _commit(trainrepo, "later feature")
    _git(trainrepo, "tag", "base2", "HEAD~1")
    res = eg.run_stages(trainrepo, "base2", "t87", dry=False, only="version_record")
    assert _stage(res, "version_record").status == eg.BLOCK and "別班" in " ".join(_stage(res, "override").lines)


def test_run_stages_rejects_unsafe_labels(eg, trainrepo):
    for bad in ("", "a b", "x;rm", "t\n87", "x" * 41):
        with pytest.raises(ValueError):
            eg.run_stages(trainrepo, "base", bad, dry=True)


def test_run_lock_is_exclusive_and_released_after_the_run(eg, trainrepo):
    p = eg.acquire_lock(trainrepo)
    try:
        with pytest.raises(ValueError):
            eg.acquire_lock(trainrepo)
        res = eg.run_stages(trainrepo, "base", "t", dry=False, only="pyc")
        assert _stage(res, "lock").status == eg.BLOCK
        assert [r.stage for r in eg.run_stages(trainrepo, "base", "t", dry=True, only="pyc")][-1] == "pyc"   # plan 不需要鎖
    finally:
        eg.release_lock(p)
    res = eg.run_stages(trainrepo, "base", "t", dry=False, only="pyc")
    assert _stage(res, "pyc").status == eg.DONE and not p.exists()


def test_version_record_asks_for_a_human_check_when_units_outnumber_new_entries(eg, trainrepo):
    _write(trainrepo, "frontend/pages/x.html", "<html>1</html>")
    m = json.loads((trainrepo / "backend/version_manifest.json").read_text(encoding="utf-8"))
    m.append({"module": "新/功能", "version": "next", "date": "2026-11-14", "time": "10:00", "content": "y"})
    _write(trainrepo, "backend/version_manifest.json", json.dumps(m, ensure_ascii=False))
    _commit(trainrepo, "two units, one entry")
    r = eg.check_version_record(trainrepo, "base")
    assert r.status == eg.WARN and "alpha" in " ".join(r.lines) and "frontend" in " ".join(r.lines)


def test_package_check_counts_pyo_too(eg, tmp_path):
    (tmp_path / "m.pyo").write_bytes(b"x")
    assert eg.package_check(tmp_path)["pyc"] == 1
