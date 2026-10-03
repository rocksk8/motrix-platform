# -*- coding: utf-8 -*-
"""建包優化 3 · tools/platform/stage_select.py（增量段選題計畫，DRY-RUN）的測試台＋反向控制。

不跑任何真測試：在**自造的小 git repo**（tmp）裡放假的 test_map／dep_graph／bottom_layer.json 與假測試檔，
只驗「算出來的計畫」。反向控制（突變）＝把 stage_select.py 的文字複本改掉一行（行尾 `# [M:xxx]` 錨點），
同一個情境 `scenario_*` 在真版必須綠、在突變版必須紅（AssertionError）——證明這個守門題真的抓得到那條規則被拿掉。

自造 repo（HEAD 的樣子）：
  契約目錄  backend/tests/platform/test_contract_a|b.py、test_modtest_scope.py（F1 演練，依賴鍵控）
  模組      alpha（foo.py＋test_alpha）、beta（bar.py＋test_beta）
  其他      test_global_pin（global_tests）、test_orphan（unmapped）、test_scan_dirs（os.listdir、無 dir: 單位）、
            test_scan_with_dir（os.listdir、但有 dir: 單位）、test_unrelated、test_new_untracked（不在 test_map）
  e2e       test_e2e_flow（alpha）、test_e2e_other、test_e2e_playwright_2026_09_07（冒煙）、test_mixed_e2e（e2e 類但有非 e2e 題）
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
TOOLS = HERE.parents[3] / "tools" / "platform"
if not (TOOLS / "stage_select.py").is_file():
    pytest.skip("tools/platform/stage_select.py 不在這個安裝包", allow_module_level=True)
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import modtest as MT  # noqa: E402

TEST_SRC = "def test_x():\n    assert True\n"
SCAN_SRC = "import os\n\ndef test_scan():\n    assert os.listdir('frontend')\n"
E2E_SRC = "import pytest\n\n@pytest.mark.e2e\ndef test_x():\n    pass\n"
MIXED_SRC = ("import pytest\n\n@pytest.mark.e2e\ndef test_browser():\n    pass\n\ndef test_plain():\n    pass\n")

#: tmap：檔 → (kind, units)
TESTS = {
    "backend/tests/platform/test_contract_a.py": ("api", []),
    "backend/tests/platform/test_contract_b.py": ("api", []),
    "backend/tests/platform/test_modtest_scope.py": ("api", []),                 # F1 演練
    "backend/modules/alpha/tests/test_alpha.py": ("api", ["mod:alpha/api/foo"]),
    "backend/modules/beta/tests/test_beta.py": ("api", ["mod:beta/api/bar"]),
    "backend/tests/test_unrelated.py": ("api", ["file:backend/data/x.json"]),
    "backend/tests/test_global_pin.py": ("api", ["file:backend/data/g.json"]),
    "backend/tests/test_orphan.py": ("api", []),
    "backend/tests/test_scan_dirs.py": ("api", ["file:backend/data/s.json"]),
    "backend/tests/test_scan_with_dir.py": ("api", ["dir:frontend/assets/"]),
    "backend/tests/test_e2e_flow.py": ("e2e", ["mod:alpha/api/foo"]),
    "backend/tests/test_e2e_other.py": ("e2e", ["file:backend/data/o.json"]),
    "backend/tests/test_e2e_playwright_2026_09_07.py": ("e2e", ["file:backend/data/p.json"]),
    "backend/tests/test_mixed_e2e.py": ("e2e", ["file:backend/data/m.json"]),
}
NEW_UNTRACKED = "backend/tests/test_new_untracked.py"      # 磁碟上有、test_map 沒有
PLATFORM_F1 = "backend/tests/platform/test_modtest_scope.py"
SELECTOR_PATHS = ("tools/platform/scope_gate.py", "tools/platform/modtest.py", "backend/tools/build_test_reuse.py")


def _bottom_layer():
    return {"format": 1, "global_tests": ["backend/tests/test_global_pin.py"], "rules": [
        {"pattern": "**/conftest.py", "layer": "bottom", "why": "fixture"},
        {"pattern": "backend/core/**", "layer": "bottom", "why": "L0"},
        {"pattern": "backend/tools/**", "layer": "bottom", "why": "tools"},
        {"pattern": "tools/**", "layer": "bottom", "why": "tools"},
        {"pattern": "backend/modules/*/**", "layer": "module", "why": "L2", "tests": ["@global_tests"]},
        {"pattern": "backend/tests/**/test_*.py", "layer": "test", "why": "測試檔"},
        {"pattern": "docs/**", "layer": "doc", "why": "doc"},
        {"pattern": "*.md", "layer": "doc", "why": "doc"},
    ]}


def _test_map():
    tests = {f: {"kind": k, "units": u, "evidence": {}} for f, (k, u) in TESTS.items()}
    return {"summary": {}, "unmapped": ["backend/tests/test_orphan.py"], "tests": tests}


def _graph():
    return {"units": {"mod:alpha/api/foo": {"imports": []}, "mod:beta/api/bar": {"imports": []}}}


def sh(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "-c", "core.autocrlf=false",
                        *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def put(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def commit(repo, changes, msg="c"):
    """changes＝{rel: 文字|None(刪)}；⇒ 新 commit 的 sha。"""
    for rel, text in changes.items():
        if text is None:
            (Path(repo) / rel).unlink()
        else:
            put(repo, rel, text)
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "--allow-empty", "-m", msg)
    return sh(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "proj"
    r.mkdir()
    sh(r, "init", "-q", "-b", "main")
    for f, (kind, _u) in TESTS.items():
        put(r, f, SCAN_SRC if "scan" in f else MIXED_SRC if "mixed" in f else E2E_SRC if kind == "e2e" else TEST_SRC)
    put(r, NEW_UNTRACKED, TEST_SRC)
    put(r, "backend/modules/alpha/api/foo.py", "X = 1\n")
    put(r, "backend/modules/beta/api/bar.py", "X = 1\n")
    put(r, "backend/conftest.py", "# fixtures\n")
    put(r, "backend/core/x.py", "X = 1\n")
    put(r, "docs/notes.md", "n\n")
    put(r, "tools/platform/other_tool.py", "X = 1\n")
    for p in SELECTOR_PATHS:
        put(r, p, "# v1\n")
    put(r, "tools/platform/bottom_layer.json", json.dumps(_bottom_layer(), ensure_ascii=False, indent=1))
    put(r, "docs/platform/test_map.json", json.dumps(_test_map(), ensure_ascii=False, indent=1))
    put(r, "docs/platform/dep_graph.json", json.dumps(_graph(), ensure_ascii=False, indent=1))
    sh(r, "add", "-A")
    sh(r, "commit", "-q", "-m", "base")
    monkeypatch.setattr(MT, "REPO", r)           # modtest.select 的「契約目錄」要看自造 repo，不是真 repo
    return r


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def SS():
    return load_module(TOOLS / "stage_select.py", "_stage_select_under_test")


def plan(SS, repo, base, head="HEAD", stage="not_e2e", **kw):
    kw.setdefault("pages", {})
    return SS.plan_stage(stage, base, head, repo, **kw)


def base_sha(repo):
    return sh(repo, "rev-parse", "HEAD")


# ── 情境（真版必須綠；突變版必須紅）──────────────────────────────────────────────

def scenario_selection(SS, repo):
    base = base_sha(repo)
    commit(repo, {"backend/modules/alpha/api/foo.py": "X = 2\n"})
    p = plan(SS, repo, base)
    assert p["mode"] == "incremental", p["forced_full"]
    assert "backend/modules/alpha/tests/test_alpha.py" in p["selected"]
    assert "backend/modules/beta/tests/test_beta.py" not in p["to_run"]
    assert "backend/tests/test_unrelated.py" in p["carried"]
    e = plan(SS, repo, base, stage="e2e")
    assert "backend/tests/test_e2e_flow.py" in e["selected"]
    assert "backend/tests/test_e2e_other.py" in e["carried"]


def scenario_floor(SS, repo):
    base = base_sha(repo)
    commit(repo, {"docs/notes.md": "changed\n"})              # 只動文件：沒有任何選題
    p = plan(SS, repo, base)
    assert p["mode"] == "incremental", p["forced_full"]
    assert p["selected"] == {}
    for f in ("backend/tests/platform/test_contract_a.py", "backend/tests/platform/test_contract_b.py",
              "backend/tests/test_global_pin.py", "backend/tests/test_orphan.py", "backend/tests/test_scan_dirs.py"):
        assert f in p["floor"] and f in p["to_run"], f
    assert p["to_run"], "底板不可以是空的"


def scenario_red(SS, repo):
    base = base_sha(repo)
    commit(repo, {"docs/notes.md": "changed\n"})
    recs = [{"type": "fail", "stage": "not_e2e", "nodeid": "modules/beta/tests/test_beta.py::test_x"},
            {"type": "aborted", "stage": "not_e2e", "nodeid": "tests/test_unrelated.py::test_x"}]
    p = plan(SS, repo, base, fail_records=recs)
    assert p["red_reselect"] == ["backend/modules/beta/tests/test_beta.py"]
    assert "backend/modules/beta/tests/test_beta.py" in p["to_run"]
    assert "backend/modules/beta/tests/test_beta.py" not in p["carried"]
    assert "backend/tests/test_unrelated.py" in p["carried"]      # aborted 不算紅


def scenario_selector_change(SS, repo):
    base = base_sha(repo)
    commit(repo, {"tools/platform/scope_gate.py": "# v2\n"})
    p = plan(SS, repo, base)
    assert p["mode"] == "full" and any("選題器" in r for r in p["forced_full"]), p["forced_full"]


def scenario_broken_carried(SS, repo):
    ok = SS.check_invariant(["a", "b", "c"], ["a"], {"b": ["F0a"]}, [], ["c"])
    assert ok["ok"] is True
    bad = SS.check_invariant(["a", "b", "c"], ["a"], {"b": ["F0a"]}, [], [])        # c 沒人管
    assert bad["ok"] is False and bad["missing"] == ["c"]
    dup = SS.check_invariant(["a", "b"], ["a"], {}, [], ["a", "b"])                 # a 既要跑又沿用
    assert dup["ok"] is False and dup["overlap"] == ["a"]


def scenario_hard(SS, repo):
    base = base_sha(repo)
    commit(repo, {"backend/conftest.py": "# fixtures v2\n"})
    p = plan(SS, repo, base)
    assert p["mode"] == "full" and any("硬底層" in r for r in p["forced_full"]), p["forced_full"]


# ── 真版 ─────────────────────────────────────────────────────────────────────────

def test_selection_includes_changed_module_tests_and_excludes_unrelated(SS, repo):
    scenario_selection(SS, repo)


def test_floor_is_always_present_even_when_nothing_selected(SS, repo):
    scenario_floor(SS, repo)


def test_floor_excludes_dependency_keyed_tool_drill_unless_triggered(SS, repo):
    base = base_sha(repo)
    commit(repo, {"docs/notes.md": "changed\n"})
    p = plan(SS, repo, base)
    assert PLATFORM_F1 not in p["floor"] and PLATFORM_F1 in p["carried"]
    q = plan(SS, repo, base, force_drill=True)
    assert PLATFORM_F1 in q["floor"] and any(g.startswith("F1") for g in q["floor"][PLATFORM_F1])
    assert SS.drill_triggered(["backend/core/x.py"], False) and SS.drill_triggered(["tools/platform/a.py"], False)
    assert SS.drill_triggered([], True) and not SS.drill_triggered(["backend/modules/alpha/api/foo.py"], False)


def test_tool_drill_list_covers_tool_tests_and_only_existing_files(SS):
    """T35-L1：工具自測（選題器／作者閘門／failfast／fail_stream／核心升級／建包沿用…）依賴鍵控；
    清單裡每個名字都要對得到真檔（改名後不會靜默失效），而架構守門（模組邊界、掃描型…）不可被誤納入。"""
    plat = Path(__file__).resolve().parent
    names = sorted(p.name for p in plat.glob("test_*.py"))
    keyed = [n for n in names if SS.TOOL_DRILL_RE.match(n)]
    must = ["test_author_gate", "test_stage_select", "test_modtest_rebase_bookkeeping", "test_failfast_2026",
            "test_fail_stream_2026", "test_fail_stream_aborted", "test_core_upgrade", "test_build_stage_reuse",
            "test_build_opt", "test_module_update_delivery", "test_scope_gate", "test_ship_tier"]
    for m in must:
        assert any(n.startswith(m) for n in keyed), "工具自測沒被依賴鍵控：" + m
    for guard in ("test_module_boundaries.py", "test_generated_maps.py", "test_unit_cards.py",
                  "test_build_failfast_wiring_2026_10_02.py", "test_pii_forms_notice.py"):
        assert guard in names and guard not in keyed, "架構守門被誤納入依賴鍵控：" + guard
    alts = SS.TOOL_DRILL_RE.pattern.split("test_(", 1)[1].rsplit(")(?:", 1)[0].split("|")
    dead = [a for a in alts if not any(n.startswith("test_" + a) for n in names)]
    assert not dead, "TOOL_DRILL_RE 有名字對不到任何檔：%s" % dead


def _real_select(changed, inert):
    """真樹的 test_map／dep_graph 上跑 modtest.select（T35-L2 正對照用）。"""
    import modtest as MT
    root = Path(__file__).resolve().parents[3]
    tmap = json.loads((root / "docs/platform/test_map.json").read_text(encoding="utf-8"))
    graph = json.loads((root / "docs/platform/dep_graph.json").read_text(encoding="utf-8"))
    graph = graph.get("units", graph)
    return MT.select(changed, tmap, graph, None, inert_schema=inert), tmap


def test_l2_direct_db_change_still_selects_core_db_tests():
    """(i) 改 db.py 本身 ⇒ 依賴 core:db 的題照選（結構擁有者只在「資料表一跳」被擋，直接改動不擋）。"""
    (picked, rep), tmap = _real_select(["backend/db.py"], inert=True)
    want = [t for t, v in tmap["tests"].items() if "core:db" in v["units"] and v["kind"] != "audit"]
    assert want and set(want) <= set(picked), "core:db 直接改動漏選 %d 題" % len(set(want) - set(picked))


def test_l2_direct_migration_change_still_selects_migration_tests():
    """(ii) 改遷移檔 ⇒ 依賴 plat:migrations 的題照選。"""
    (picked, rep), tmap = _real_select(["backend/core/migrations.py"], inert=True)
    want = [t for t, v in tmap["tests"].items() if "plat:migrations" in v["units"] and v["kind"] != "audit"]
    assert want and set(want) <= set(picked), "plat:migrations 直接改動漏選 %d 題" % len(set(want) - set(picked))


def test_l2_table_writer_change_still_selects_the_tables_readers_but_not_schema_owners():
    """(iii) 模組改了某資料表的寫入端 ⇒ 該表 readers 的題照選；只有結構擁有者（core:db、plat:migrations）不經一跳被拉進來。"""
    changed = ["backend/modules/case/material_payment.py"]
    (p_on, r_on), tmap = _real_select(changed, inert=True)
    (p_off, r_off), _ = _real_select(changed, inert=False)
    hop_on, hop_off = set(r_on["table_hop_units"]), set(r_off["table_hop_units"])
    assert hop_on and hop_on == hop_off - {"core:db", "plat:migrations"}, sorted(hop_off ^ hop_on)
    assert {"core:db", "plat:migrations"} & hop_off, "對照失效：不開旗標時一跳應拉進結構擁有者"
    readers = {u for u in hop_on if not u.startswith("table:")}
    must = {t for t, v in tmap["tests"].items() if set(v["units"]) & readers and v["kind"] != "audit"}
    assert must <= set(p_on), "資料表 readers 的題漏選 %d 題" % len(must - set(p_on))
    assert len(p_on) < len(p_off), "旗標沒有縮小選題（%d vs %d）" % (len(p_on), len(p_off))


def test_red_reselect_includes_red_files(SS, repo):
    scenario_red(SS, repo)


def test_red_files_normalization_and_stage_filter(SS, repo, tmp_path):
    recs = [{"type": "fail", "stage": "e2e", "nodeid": "tests/test_e2e_other.py::t"},
            {"type": "node_down", "stage": "not_e2e", "nodeid": "(worker gw1)"},
            {"type": "summary", "nodeid": "tests/x.py"}, {"type": "fail", "nodeid": "gw2"}]
    assert SS.red_files_from_records(recs) == {"backend/tests/test_e2e_other.py"}
    assert SS.red_files_from_records(recs, stage="not_e2e") == set()
    f = tmp_path / "fs.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in recs) + "\nnot json\n", encoding="utf-8")
    assert len(SS.load_fail_stream(f)) == 4
    base = base_sha(repo)
    commit(repo, {"docs/notes.md": "changed\n"})
    p = plan(SS, repo, base, red_files=["tests/test_e2e_other.py"])            # e2e 檔紅，但本段是 not_e2e
    assert p["red_reselect"] == [] and any("紅檔不在本段" in n for n in p["notes"])
    e = plan(SS, repo, base, stage="e2e", red_files=["backend/tests/test_e2e_other.py"])
    assert e["red_reselect"] == ["backend/tests/test_e2e_other.py"]


def test_forced_full_hard_bottom(SS, repo):
    scenario_hard(SS, repo)
    base = base_sha(repo)
    commit(repo, {"backend/core/x.py": "X = 2\n"})
    p = plan(SS, repo, base)
    assert p["mode"] == "full" and any("硬底層" in r for r in p["forced_full"])
    assert p["to_run_all"] and p["carried"] == [] and set(p["to_run"]) == set(p["collected"])


def test_forced_full_selector_change(SS, repo):
    scenario_selector_change(SS, repo)
    for rel in ("tools/platform/modtest.py", "backend/tools/build_test_reuse.py", "tools/platform/bottom_layer.json"):
        r2 = base_sha(repo)
        content = json.dumps(_bottom_layer(), indent=2) if rel.endswith(".json") else "# changed %s\n" % rel
        commit(repo, {rel: content})
        p = plan(SS, repo, r2)
        assert p["mode"] == "full" and any("選題器" in x for x in p["forced_full"]), rel


def test_selector_sha_changes_with_content_and_with_missing(SS, repo):
    rd0 = SS.GitReader(repo, base_sha(repo))
    s0 = SS.selector_sha(rd0)
    assert s0 == SS.selector_sha(SS.GitReader(repo, base_sha(repo)))
    commit(repo, {"tools/platform/modtest.py": "# v2\n"})
    assert SS.selector_sha(SS.GitReader(repo, base_sha(repo))) != s0
    assert SS.selector_sha(rd0, files=("tools/platform/nope.py",)) != SS.selector_sha(rd0, files=("tools/platform/modtest.py",))


def test_forced_full_unmapped_changes(SS, repo):
    base = base_sha(repo)
    commit(repo, {"tools/platform/other_tool.py": "X = 2\n"})            # 軟底層、沒有任何測試對得到
    p = plan(SS, repo, base)
    assert p["mode"] == "full" and any("unmapped_changes" in r for r in p["forced_full"]), p["forced_full"]
    assert "tools/platform/other_tool.py" in p["unmapped_changes"]


def test_forced_full_base_not_ancestor_and_missing(SS, repo):
    main = base_sha(repo)
    sh(repo, "checkout", "-q", "-b", "side")
    side = commit(repo, {"docs/side.md": "s\n"})
    sh(repo, "checkout", "-q", "main")
    head = commit(repo, {"docs/notes.md": "changed\n"})
    p = plan(SS, repo, side, head)
    assert p["mode"] == "full" and any("不是" in r and "祖先" in r for r in p["forced_full"]), p["forced_full"]
    for bad in (None, "", "deadbeefdeadbeef"):
        q = plan(SS, repo, bad, head)
        assert q["mode"] == "full" and any("基準不存在" in r for r in q["forced_full"]), (bad, q["forced_full"])
    ok = plan(SS, repo, main, head)
    assert ok["mode"] == "incremental"


def test_forced_full_chain_age_streak_limits_are_parameters(SS, repo):
    base = base_sha(repo)
    commit(repo, {"docs/notes.md": "changed\n"})
    assert plan(SS, repo, base, base_info={"chain_depth": 2, "age_hours": 6, "incr_streak": 2})["mode"] == "incremental"
    for info, key in (({"chain_depth": 3}, "鏈長"), ({"age_hours": 6.5}, "年齡"), ({"incr_streak": 3}, "連續"),
                      ({"root_full": False}, "鏈根"), ({"env_same": False}, "環境"), ({"aborted_by": "failfast"}, "中斷")):
        p = plan(SS, repo, base, base_info=info)
        assert p["mode"] == "full" and any(key in r for r in p["forced_full"]), (info, p["forced_full"])
    p = plan(SS, repo, base, base_info={"chain_depth": 3}, limits={"max_chain": 5})       # 上限是參數
    assert p["mode"] == "incremental"


def test_invariant_holds_and_broken_carried_is_detected(SS, repo):
    base = base_sha(repo)
    commit(repo, {"backend/modules/alpha/api/foo.py": "X = 2\n"})
    for stage in ("not_e2e", "e2e"):
        p = plan(SS, repo, base, stage=stage)
        assert p["invariant"]["ok"] and not p["invariant"]["missing"] and not p["invariant"]["overlap"]
        union = set(p["selected"]) | set(p["floor"]) | set(p["red_reselect"]) | set(p["carried"])
        assert union >= set(p["collected"])
        assert not (set(p["carried"]) & (set(p["selected"]) | set(p["floor"]) | set(p["red_reselect"])))
    scenario_broken_carried(SS, repo)


def test_plan_detects_a_broken_carried_set_and_goes_full(SS, repo, monkeypatch):
    base = base_sha(repo)
    commit(repo, {"docs/notes.md": "changed\n"})
    monkeypatch.setattr(SS, "_carried", lambda collected, run: sorted(set(collected) - set(run))[1:])   # 偷偷丟一個
    p = plan(SS, repo, base)
    assert p["mode"] == "full" and any("集合守恆" in r for r in p["forced_full"]), p["forced_full"]
    assert p["invariant"]["ok"] is False and p["invariant"]["missing"]


def test_collected_is_test_map_union_discovered_and_mixed_e2e_runs_in_both_stages(SS, repo):
    base = base_sha(repo)
    commit(repo, {NEW_UNTRACKED: TEST_SRC + "\n# changed\n"})
    p = plan(SS, repo, base)
    assert NEW_UNTRACKED in p["collected"]                                  # 不在 test_map，由磁碟發現
    assert p["selected"][NEW_UNTRACKED] == ["改動的測試檔"]
    assert "backend/tests/test_mixed_e2e.py" in p["collected"]               # e2e 類但有非 e2e 題 ⇒ 非 e2e 段也收
    assert "backend/tests/test_e2e_other.py" not in p["collected"]
    e = plan(SS, repo, base, stage="e2e")
    assert "backend/tests/test_mixed_e2e.py" in e["collected"] and NEW_UNTRACKED not in e["collected"]
    assert "E2E:登入冒煙" in e["floor"]["backend/tests/test_e2e_playwright_2026_09_07.py"]


def test_scan_dir_detector_function():
    SS = load_module(TOOLS / "stage_select.py", "_ss_detector")
    assert SS.detect_dir_scan("import os\nos.listdir('x')\n") == ["os.listdir"]
    assert set(SS.detect_dir_scan("import glob\nglob.glob('a/*')\nP.rglob('*.py')\nos.walk('.')\nQ.iterdir()\n")) \
        == {"glob", "rglob", "os.walk", "iterdir"}
    assert SS.detect_dir_scan("# os.listdir('x') 只在註解\nx = 1\n") == []
    assert SS.detect_dir_scan("def test_a():\n    assert 1\n") == []


def test_scan_dir_test_is_in_floor_unless_it_already_has_a_dir_unit(SS, repo):
    base = base_sha(repo)
    commit(repo, {"docs/notes.md": "changed\n"})
    p = plan(SS, repo, base)
    assert any(g.startswith("F0d") for g in p["floor"]["backend/tests/test_scan_dirs.py"])
    assert "backend/tests/test_scan_with_dir.py" not in p["floor"]           # 有 dir: 單位 ⇒ 靠 test_map，不進底板
    assert "backend/tests/test_scan_with_dir.py" in p["carried"]
    q = plan(SS, repo, base, legacy_floor=True)                             # 舊版底板（§3.1）沒有 F0d
    assert "backend/tests/test_scan_dirs.py" not in q["floor"]


def test_fail_closed_on_exception(SS, repo, monkeypatch):
    base = base_sha(repo)
    commit(repo, {"backend/modules/alpha/api/foo.py": "X = 2\n"})

    def boom(*a, **k):
        raise RuntimeError("選題炸了")
    monkeypatch.setattr(SS, "_select", boom)
    p = plan(SS, repo, base)
    assert p["mode"] == "full" and p["to_run_all"] and any("計算失敗" in r and "選題炸了" in r for r in p["forced_full"])


def test_fail_closed_on_broken_test_map_and_missing_config(SS, repo):
    base = base_sha(repo)
    commit(repo, {"docs/platform/test_map.json": "{ not json"})
    p = plan(SS, repo, base)
    assert p["mode"] == "full" and any("計算失敗" in r for r in p["forced_full"])
    b2 = base_sha(repo)
    commit(repo, {"docs/platform/test_map.json": json.dumps(_test_map()), "tools/platform/bottom_layer.json": None})
    q = plan(SS, repo, b2)
    assert q["mode"] == "full" and any("計算失敗" in r for r in q["forced_full"])
    assert plan(SS, repo, "HEAD", head="no-such-ref")["mode"] == "full"


def test_cli_plan_json_on_synthetic_repo(repo):
    base = base_sha(repo)
    commit(repo, {"backend/modules/alpha/api/foo.py": "X = 2\n"})
    r = subprocess.run([sys.executable, str(TOOLS / "stage_select.py"), "plan", "--stage", "not_e2e", "--base", base,
                        "--repo", str(repo), "--json"], capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, r.stderr
    p = json.loads(r.stdout)
    assert p["mode"] == "incremental" and "backend/modules/alpha/tests/test_alpha.py" in p["selected"]
    assert p["invariant"]["ok"]


# ── 反向控制（突變）──────────────────────────────────────────────────────────────

def mutate(tmp_path, anchor, replacement, name):
    """把 stage_select.py 複本裡「行尾有 # [M:anchor]」的那一行整行換掉（保留縮排）⇒ 載入的模組。找不到或不只一行 ⇒ 測試失敗。"""
    text = (TOOLS / "stage_select.py").read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    idx = [i for i, ln in enumerate(lines) if "# [M:%s]" % anchor in ln]
    assert len(idx) == 1, "錨點 [M:%s] 應該剛好一行，實際 %d" % (anchor, len(idx))
    indent = re.match(r"\s*", lines[idx[0]]).group(0)
    lines[idx[0]] = indent + replacement + "\n"
    d = tmp_path / ("mut_" + name)
    d.mkdir()
    (d / "stage_select.py").write_text("".join(lines), encoding="utf-8")
    return load_module(d / "stage_select.py", "_ss_mut_" + name)


def test_mutation_remove_floor_is_detected(tmp_path, repo):
    m = mutate(tmp_path, "floor", "floor = {}", "floor")
    with pytest.raises(AssertionError):
        scenario_floor(m, repo)


def test_mutation_drop_red_reselect_is_detected(tmp_path, repo):
    m = mutate(tmp_path, "red", "red_reselect = []", "red")
    with pytest.raises(AssertionError):
        scenario_red(m, repo)


def test_mutation_remove_selector_self_change_rule_is_detected(tmp_path, repo):
    m = mutate(tmp_path, "selector", "sel_changed = False", "selector")
    with pytest.raises(AssertionError):
        scenario_selector_change(m, repo)


def test_mutation_disable_invariant_check_is_detected(tmp_path, repo):
    m = mutate(tmp_path, "invariant", 'return {"ok": True, "missing": missing, "overlap": overlap}', "invariant")
    with pytest.raises(AssertionError):
        scenario_broken_carried(m, repo)


def test_mutation_remove_hard_bottom_rule_is_detected(tmp_path, repo):
    m = mutate(tmp_path, "hard", "if False:", "hard")
    with pytest.raises(AssertionError):
        scenario_hard(m, repo)


def test_unmutated_copy_passes_all_scenarios(tmp_path, repo):
    """對照：複本不改任何一行時，每個情境都綠——證明上面的「紅」來自突變，不是複本／情境本身壞掉。"""
    d = tmp_path / "copy"
    d.mkdir()
    (d / "stage_select.py").write_text((TOOLS / "stage_select.py").read_text(encoding="utf-8"), encoding="utf-8")
    m = load_module(d / "stage_select.py", "_ss_copy")
    for sc in (scenario_selection, scenario_floor, scenario_red, scenario_selector_change, scenario_hard):
        sc(m, repo)                       # 每個情境自己 commit 在同一個 repo 上，base 取當下 HEAD
    scenario_broken_carried(m, repo)
