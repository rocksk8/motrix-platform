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


@pytest.mark.parametrize("bad", ["", "因為趕時間", "PM 核准：沒有日期", "PM 核准（2026-11-14）：", "pm approved (2026-11-14): x"])
def test_endgame_escape_hatch_text_must_name_pm_approval_date_and_reason(eg, bad):
    assert not eg.ALLOW_RE.match(bad)
    assert eg.ALLOW_RE.match("PM 核准（2026-11-14）：使用者裁示先發布")


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

def test_endgame_fill_replaces_only_the_placeholders_it_was_given(eg, tmp_path):
    f = tmp_path / "s.md"
    f.write_text("包 <PKG_NAME> sha <PKG_SHA256> 凍結 <FREEZE_SHA> 前綴 <FREEZE_8> 其他 <ROOT>\n", encoding="utf-8")
    done = eg.fill_step_file(f, pkg_name="N", pkg_sha="S", freeze="1234567890abcdef")
    assert done == ["<PKG_NAME>", "<PKG_SHA256>", "<FREEZE_SHA>", "<FREEZE_8>"]
    assert f.read_text(encoding="utf-8") == "包 N sha S 凍結 1234567890abcdef 前綴 12345678 其他 <ROOT>\n"


def test_endgame_step_file_facts_are_replaced_in_place_and_carry_the_override_note(eg, repo, tmp_path):
    _write(repo, "backend/core/registry.py", 'CORE_VERSION = "9.9"\n')
    _write(repo, "backend/tests/_prod_baseline.py", 'BASELINE = "%s"\n' % subprocess.run(["git", "-C", str(repo), "rev-parse", "base"], capture_output=True, text=True).stdout.strip())
    _write(repo, "docs/platform/prod-tasks/s.md", "# 步驟\n\n正文\n")
    _commit(repo, "setup")
    st = eg.load_state(repo)
    st["allow_no_version_record"] = "PM 核准（2026-11-14）：補登由下一班處理"
    eg.save_state(repo, st)
    assert eg.write_step_file(repo, "base", "docs/platform/prod-tasks/s.md", "t") is True
    first = (repo / "docs/platform/prod-tasks/s.md").read_text(encoding="utf-8")
    assert "正文" in first and eg.FACTS_BEGIN in first and "core 9.9" in first and "PM 核准（2026-11-14）" in first
    assert eg.write_step_file(repo, "base", "docs/platform/prod-tasks/s.md", "t") is False       # 冪等
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
