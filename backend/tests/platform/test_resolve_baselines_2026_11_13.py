# -*- coding: utf-8 -*-
"""測試流程改革①：基準檔合併自動化（tools/platform/merge_drivers.py 的 json／maxentries 驅動＋resolve_baselines.py）。

純函式（結構合併規則）＋真的 git（登記驅動後不衝突；沒登記 ⇒ 衝突，再由 resolve_baselines 收）＋真檔格式守門。
真實歷史驗證（200 個合併點、兩邊都改了基準檔的案例，驅動結果 vs 整合者最後提交的）見 CHANGELOG 說明；這裡只放可重現的小案例。
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load(name):
    spec = importlib.util.spec_from_file_location("_t_" + name, REPO / "tools" / "platform" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MD = _load("merge_drivers")
SETUP = _load("setup_merge_drivers")
RB = _load("resolve_baselines")


def _dump(obj, sort=True):
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=sort) + "\n"


def _mods(units):
    """手排的 modules.json 縮影（縮排不規則，json.dumps 排不出來）。"""
    return '{\n "L1": {\n  "units": [\n' + ",\n".join('   "%s"' % u for u in units) + '\n  ]\n },\n"m": {"x": 1}\n}\n'


# ── 結構合併（純函式）──────────────────────────────────────────────────────

def test_dict_both_add_different_keys_both_kept():
    o = _dump({"u": {"x": "const"}})
    a = _dump({"u": {"x": "const", "a": "def()"}})
    b = _dump({"u": {"x": "const", "b": "class"}, "v": {}})
    got = json.loads(MD.merge_json(o, a, b))
    assert got == {"u": {"x": "const", "a": "def()", "b": "class"}, "v": {}}


def test_same_key_changed_two_ways_is_a_conflict_not_a_guess():
    o, a, b = (_dump({"k": v}) for v in ("1", "2", "3"))
    assert MD.merge_json(o, a, b) is None


def test_one_side_deletes_other_untouched_stays_deleted():
    o = _dump({"u": {"x": 1, "y": 2}})
    a = _dump({"u": {"x": 1}})
    b = _dump({"u": {"x": 1, "y": 2, "z": 3}})
    assert json.loads(MD.merge_json(o, a, b)) == {"u": {"x": 1, "z": 3}}


def test_sorted_key_lists_stay_sorted_and_removed_keys_do_not_come_back():
    o = _dump({"/api/a": {"k": ["a", "c", "e"], "s": 200}})
    a = _dump({"/api/a": {"k": ["a", "b", "c", "e"], "s": 200}})                 # 加 b
    b = _dump({"/api/a": {"k": ["a", "c", "d"], "s": 200}})                      # 刪 e、加 d
    got = json.loads(MD.merge_json(o, a, b))["/api/a"]["k"]
    assert got == ["a", "b", "c", "d"]


def test_unsorted_scalar_lists_keep_order_and_insert_before_successor():
    o = _dump({"units": ["u1", "u3"]}, sort=False)
    a = _dump({"units": ["u1", "u2", "u3"]}, sort=False)
    b = _dump({"units": ["u1", "u3", "u4"]}, sort=False)
    assert json.loads(MD.merge_json(o, a, b))["units"] == ["u1", "u2", "u3", "u4"]


def test_list_of_objects_changed_on_both_sides_is_a_conflict():
    o, a, b = (_dump({"h": v}) for v in ([{"x": 1}], [{"x": 2}], [{"x": 3}]))
    assert MD.merge_json(o, a, b) is None


def test_core_version_next_beats_a_train_number_but_two_numbers_conflict():
    mk = lambda v, extra=None: _dump({"core_version": v, "interface": extra or {}})   # noqa: E731
    got = MD.merge_json(mk("1.144"), mk("1.145"), mk("next", {"u": {"f": "def()"}}), path="x/l1_interface_snapshot.json")
    assert json.loads(got) == {"core_version": "next", "interface": {"u": {"f": "def()"}}}
    assert MD.merge_json(mk("1.144"), mk("1.145"), mk("1.146"), path="x/l1_interface_snapshot.json") is None
    assert MD.merge_json(mk("1.144"), mk("1.145"), mk("1.146")) is None, "只有 l1 快照才有這條特例"


def _inv(*names):
    return {n: {"w": n.startswith("POST"), "pp": 0, "body": n.startswith("POST")} for n in names}


def _route_file(endpoints, select_star=5):
    return _dump({"summary": MD.summarize_inventory(endpoints), "select_star": {"modules": select_star}, "endpoints": endpoints}, sort=False)


def test_route_inventory_summary_is_recomputed_and_select_star_is_additive():
    base = _inv("GET /api/a")
    o = _route_file(base, 5)
    a = _route_file({**base, **_inv("POST /api/b")}, 6)
    b = _route_file({**base, **_inv("POST /api/c", "GET /api/d")}, 7)
    got = json.loads(MD.merge_json(o, a, b, path="backend/tests/platform/route_inventory.json"))
    assert set(got["endpoints"]) == {"GET /api/a", "POST /api/b", "POST /api/c", "GET /api/d"}
    assert got["summary"] == MD.summarize_inventory(got["endpoints"]), "summary 必須等於 endpoints 的合計（不是兩邊數字相加）"
    assert got["summary"]["endpoints_total"] == 4 and got["summary"]["write_api"] == 2
    assert got["select_star"] == {"modules": 8}, "5 + 1 + 2"


def test_output_format_is_byte_identical_to_the_base_layout():
    unscoped = lambda es: '{\n "entries": {\n%s\n }\n}\n' % ",\n".join('  "%s": "unscoped"' % k for k in sorted(es))   # noqa: E731
    o, a, b = unscoped(["a.py::f::t"]), unscoped(["a.py::f::t", "b.py::g::t"]), unscoped(["a.py::f::t", "c.py::h::t"])
    assert MD.merge_json(o, a, b) == unscoped(["a.py::f::t", "b.py::g::t", "c.py::h::t"])


def test_hand_laid_out_json_uses_line_union_only_if_it_equals_the_structural_merge():
    """modules.json 是手排的（縮排不規則）：認不出排版 ⇒ 逐行聯集，但解析結果必須等於結構合併。"""
    o = _mods(["u1", "u3", "u5", "u7"])
    a = _mods(["u1", "u2", "u3", "u5", "u7"])
    b = _mods(["u1", "u3", "u5", "u7", "u8"])
    assert MD.detect_renderer(o) is None
    got = MD.merge_json(o, a, b, path="docs/platform/modules.json")
    assert got is not None and json.loads(got)["L1"]["units"] == ["u1", "u2", "u3", "u5", "u7", "u8"]
    assert '"m": {"x": 1}' in got, "手排的部分原樣保留"


def test_invalid_json_input_falls_back_to_a_normal_conflict():
    assert MD.merge_json("{", "{}", "{}") is None


# ── MAX_ENTRIES ───────────────────────────────────────────────────────────

RATCHET_O = ("X = 1\n\nMAX_ENTRIES = 864      # 856 + 5（T80c：甲）\n"
             "                        # 856 = 853 + 3（舊註解）\n\n\ndef t():\n    pass\n")


def test_max_entries_numbers_add_and_both_comments_are_kept():
    a = RATCHET_O.replace("864      # 856 + 5（T80c：甲）", "866      # 864 + 2（乙：新端點）\n                        # 856 + 5（T80c：甲）")
    b = RATCHET_O.replace("864      # 856 + 5（T80c：甲）", "865      # 864 + 1（丙：另一個）\n                        # 856 + 5（T80c：甲）")
    got = MD.merge_maxentries(RATCHET_O, a, b)
    assert "MAX_ENTRIES = 867      # 864 + 2（乙：新端點）" in got, "數字＝864＋2＋1"
    assert "（併入）864 + 1（丙：另一個）" in got
    assert got.count("856 + 5（T80c：甲）") == 1 and "856 = 853 + 3（舊註解）" in got
    assert got.count("MAX_ENTRIES") == 1


def test_max_entries_rest_of_file_changed_on_both_sides_is_a_conflict():
    a = RATCHET_O.replace("pass", "pass  # a")
    b = RATCHET_O.replace("pass", "pass  # b")
    assert MD.merge_maxentries(RATCHET_O, a, b) is None


# ── resolve_baselines：真的 git ─────────────────────────────────────────

SNAP = "backend/tests/platform/l1_interface_snapshot.json"
MODS = "docs/platform/modules.json"
CLOG = "backend/core/CHANGELOG.md"
MANIFEST = "backend/version_manifest.json"
PRE = "# core 更新紀錄\n\n> 說明\n\n"
CBASE = PRE + "## 1.0.1 — d\n- old\n\n## 1.0.0 — d\n- init\n"


def _g(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True, text=True, encoding="utf-8")


def _w(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def _commit_branch(r, name, files):
    _g(r, "checkout", "-q", "-b", name, "platform")
    for rel, text in files.items():
        _w(r, rel, text)
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", name)
    _g(r, "checkout", "-q", "platform")


@pytest.fixture()
def repo2(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _g(r, "init", "-q", "-b", "platform")
    _g(r, "config", "user.email", "t@example.invalid")
    _g(r, "config", "user.name", "t")
    _g(r, "config", "core.autocrlf", "false")
    _w(r, ".gitattributes", (REPO / ".gitattributes").read_text(encoding="utf-8"))
    _w(r, SNAP, _dump({"core_version": "1.144", "interface": {"u": {"f": "def()"}}}))
    _w(r, MODS, _mods(["u1", "u3", "u5", "u7"]))
    _w(r, CLOG, CBASE)
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", "base")
    sec = "## (next) — 2026-11-13（wip/%s）\n- %s1\n\n"
    _commit_branch(r, "wip/a", {
        SNAP: _dump({"core_version": "next", "interface": {"u": {"f": "def()", "a": "def()"}}}),
        MODS: _mods(["u1", "u2", "u3", "u5", "u7"]),
        CLOG: CBASE.replace("## 1.0.1", (sec % ("a", "a")) + "## 1.0.1", 1)})
    _commit_branch(r, "wip/b", {
        SNAP: _dump({"core_version": "1.145", "interface": {"u": {"f": "def()", "b": "class"}}}),
        MODS: _mods(["u1", "u3", "u5", "u7", "u8"]),
        CLOG: CBASE.replace("## 1.0.1", (sec % ("b", "b")) + "## 1.0.1", 1)})
    return r


def test_git_merge_with_json_drivers_has_no_conflict(repo2):
    r = repo2
    SETUP.install(r, strict=False)
    assert SETUP.problems(r, strict=False) == []
    _g(r, "merge", "-q", "--no-ff", "wip/a", "-m", "a")
    res = _g(r, "merge", "--no-ff", "wip/b", "-m", "b", check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    snap = json.loads((r / SNAP).read_text(encoding="utf-8"))
    assert snap["interface"]["u"] == {"f": "def()", "a": "def()", "b": "class"} and snap["core_version"] == "next"
    assert json.loads((r / MODS).read_text(encoding="utf-8"))["L1"]["units"] == ["u1", "u2", "u3", "u5", "u7", "u8"]
    assert (r / CLOG).read_text(encoding="utf-8").count("## (next)") == 1


def test_without_drivers_git_conflicts_then_resolve_baselines_finishes_it(repo2):
    """沒登記驅動的機器（或換了新機器）：一般衝突 ⇒ 跑 resolve_baselines 一個指令收完，已 git add，可以直接 commit。"""
    r = repo2
    _g(r, "merge", "-q", "--no-ff", "wip/a", "-m", "a")
    res = _g(r, "merge", "--no-ff", "wip/b", "-m", "b", check=False)
    assert res.returncode != 0
    assert {SNAP, CLOG} <= set(RB.unmerged(r)), "快照（core_version 兩邊不同）與 CHANGELOG（兩邊的 (next)）一般 git 會衝突"
    rep = RB.resolve(r, post=False)
    assert rep["kept_for_human"] == [] and rep["unmerged_other"] == []
    assert {p for p, _ in rep["resolved"]} == {SNAP, CLOG}
    assert RB.unmerged(r) == {}, "已解決的檔都 git add 了"
    assert "<<<<<<<" not in (r / CLOG).read_text(encoding="utf-8")
    assert json.loads((r / SNAP).read_text(encoding="utf-8"))["core_version"] == "next"
    assert _g(r, "commit", "-q", "-m", "merge b", check=False).returncode == 0


def test_check_mode_writes_nothing(repo2):
    r = repo2
    _g(r, "merge", "-q", "--no-ff", "wip/a", "-m", "a")
    _g(r, "merge", "--no-ff", "wip/b", "-m", "b", check=False)
    before = (r / CLOG).read_bytes()
    rep = RB.resolve(r, dry=True, post=False)
    assert rep["resolved"] and RB.check_needed(rep)
    assert (r / CLOG).read_bytes() == before and set(RB.unmerged(r)) >= {SNAP, CLOG}


def test_code_conflicts_are_left_alone_and_listed(repo2):
    r = repo2
    for name, txt in (("wip/c", "x = 'c'\n"), ("wip/d", "x = 'd'\n")):
        _commit_branch(r, name, {"backend/code.py": txt})
    _g(r, "merge", "-q", "--no-ff", "wip/c", "-m", "c")
    res = _g(r, "merge", "--no-ff", "wip/d", "-m", "d", check=False)
    assert res.returncode != 0
    rep = RB.resolve(r, post=False)
    assert rep["unmerged_other"] == ["backend/code.py"]
    assert "<<<<<<<" in (r / "backend" / "code.py").read_text(encoding="utf-8"), "程式碼衝突原樣留給人"
    text, todo = RB.format_report(rep, False)
    assert todo and "backend/code.py" in text


def test_same_value_changed_two_ways_is_kept_for_a_human(tmp_path, repo2):
    r = repo2
    _commit_branch(r, "wip/e", {MODS: (r / MODS).read_text(encoding="utf-8").replace('"x": 1', '"x": 2')})
    _commit_branch(r, "wip/f", {MODS: (r / MODS).read_text(encoding="utf-8").replace('"x": 1', '"x": 3')})
    _g(r, "merge", "-q", "--no-ff", "wip/e", "-m", "e")
    _g(r, "merge", "--no-ff", "wip/f", "-m", "f", check=False)
    rep = RB.resolve(r, post=False)
    assert [p for p, _ in rep["kept_for_human"]] == [MODS]
    assert MODS in RB.unmerged(r), "沒解的不 git add"


def test_gitattributes_covers_every_baseline_with_a_registered_driver():
    attrs = (REPO / ".gitattributes").read_text(encoding="utf-8")
    drivers = set(SETUP.DRIVERS)
    for rel in (SNAP, "backend/tests/platform/route_inventory.json", "backend/tests/platform/response_keys_baseline.json",
                "backend/tests/platform/unscoped_reads_baseline.json", MODS, "backend/tests/platform/test_unscoped_reads_ratchet.py",
                CLOG, MANIFEST, *RB.EXTRA_JSON):
        line = next((l for l in attrs.splitlines() if l.split()[:1] == [rel]), None)
        assert line, "%s 沒有 merge= 驅動" % rel
        assert line.split("merge=")[1].strip() in drivers, line


# ── .ps1 雜湊／版本（post_ps1）──────────────────────────────────────────────

def test_post_ps1_recomputes_hash_and_version_and_keeps_the_description(tmp_path):
    (tmp_path / "backend" / "tools").mkdir(parents=True)
    ps1 = tmp_path / "backend" / "tools" / "apply_update.ps1"
    ps1.write_bytes(b'\xef\xbb\xbf$ApplyScriptVersion = "2026-12-01a"\r\nWrite-Host hi\r\n')
    reg = tmp_path / "backend" / "tools" / "apply_update.version.json"
    reg.write_text(json.dumps({"_說明": "說明文字", "version": "2026-11-13a", "sha256": "0" * 64}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    changed, problems = RB.post_ps1(tmp_path, dry=False, skip=set())
    assert changed == ["backend/tools/apply_update.version.json"] and problems == []
    got = json.loads(reg.read_text(encoding="utf-8"))
    assert got["version"] == "2026-12-01a" and got["_說明"] == "說明文字"
    assert got["sha256"] == RB.ps1_digest(b'$ApplyScriptVersion = "2026-12-01a"\nWrite-Host hi\n')
    assert RB.post_ps1(tmp_path, dry=False, skip=set()) == ([], []), "第二次不再改（冪等）"


def test_post_ps1_refuses_when_the_script_itself_has_conflict_markers(tmp_path):
    (tmp_path / "backend" / "tools").mkdir(parents=True)
    (tmp_path / "backend" / "tools" / "apply_update.ps1").write_text('<<<<<<< HEAD\n$ApplyScriptVersion = "x"\n>>>>>>> b\n', encoding="utf-8")
    (tmp_path / "backend" / "tools" / "apply_update.version.json").write_text("{}\n", encoding="utf-8")
    changed, problems = RB.post_ps1(tmp_path, dry=False, skip=set())
    assert changed == [] and problems and "衝突標記" in problems[0]


# ── MAX_ENTRIES 重算（post_unscoped；掃描結果用假的）─────────────────────────

def _ratchet_repo(tmp_path, cap, n_base):
    (tmp_path / "backend" / "tests" / "platform").mkdir(parents=True)
    (tmp_path / "backend" / "tests" / "platform" / "test_unscoped_reads_ratchet.py").write_text(
        "X = 1\nMAX_ENTRIES = %d      # 註解\n\ndef t():\n    pass\n" % cap, encoding="utf-8", newline="\n")
    return {"cur": {"a.py::f::t%d" % i: "unscoped" for i in range(n_base)}, "base": {"a.py::f::t%d" % i: "unscoped" for i in range(n_base)}}


@pytest.mark.parametrize("cap,n,expect_cap,note", [(10, 12, 12, "→ 12"), (20, 12, 20, "有餘裕"), (12, 12, 12, None)])
def test_post_unscoped_raises_cap_only_to_the_union_size(tmp_path, monkeypatch, cap, n, expect_cap, note):
    scan = _ratchet_repo(tmp_path, cap, n)
    monkeypatch.setattr(RB, "_py_run", lambda repo, code, cwd, timeout=600: (0, json.dumps(scan) + "\n", ""))
    changed, problems, notes = RB.post_unscoped(tmp_path, dry=False, skip=set())
    text = (tmp_path / "backend" / "tests" / "platform" / "test_unscoped_reads_ratchet.py").read_text(encoding="utf-8")
    assert "MAX_ENTRIES = %d      # 註解" % expect_cap in text and problems == []
    assert bool(changed) == (cap < n)
    assert (note is None) or any(note in x for x in notes)


def test_post_unscoped_reports_new_unregistered_reads_but_never_registers_them(tmp_path, monkeypatch):
    scan = _ratchet_repo(tmp_path, 50, 3)
    scan["cur"]["new.py::g::quotations"] = "unscoped"
    monkeypatch.setattr(RB, "_py_run", lambda repo, code, cwd, timeout=600: (0, json.dumps(scan) + "\n", ""))
    changed, problems, notes = RB.post_unscoped(tmp_path, dry=False, skip=set())
    assert changed == [] and problems and "new.py::g::quotations" in problems[0]


# ── 真檔格式守門（排版認得出來，驅動才用得上）──────────────────────────────

@pytest.mark.parametrize("rel,hand_laid", [
    (SNAP, False), ("backend/tests/platform/route_inventory.json", False), ("backend/tests/platform/response_keys_baseline.json", False),
    ("backend/tests/platform/unscoped_reads_baseline.json", False), (MODS, True),
    ("backend/tests/platform/recyclebin_baseline_t53.json", False), ("backend/tests/platform/write_golden_baseline.json", False)])
def test_real_baseline_files_are_in_a_supported_layout(rel, hand_laid):
    text = (REPO / rel).read_text(encoding="utf-8")
    renderer = MD.detect_renderer(text)
    if hand_laid:
        assert renderer is None, "%s 變成規則排版了：可以拿掉逐行聯集的備援" % rel
    else:
        assert renderer is not None, "%s 的排版不是 json.dumps(indent=1) 或 unscoped dump：驅動認不得，會退回一般衝突" % rel


def test_real_ratchet_file_has_a_parsable_max_entries_block():
    sp = MD.split_cap((REPO / "backend/tests/platform/test_unscoped_reads_ratchet.py").read_text(encoding="utf-8"))
    assert sp is not None and MD._cap_n(sp[1]) > 800 and len(sp[1]) > 1


def test_real_route_inventory_summary_matches_its_endpoints():
    """正對照：驅動重算 summary 用的 summarize_inventory 與測試用的 _route_inventory.summarize 是同一個答案。"""
    inv = json.loads((REPO / "backend/tests/platform/route_inventory.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(REPO / "backend"))
    try:
        from tests.platform import _route_inventory as RI
        assert MD.summarize_inventory(inv["endpoints"]) == RI.summarize(inv["endpoints"])
    finally:
        sys.path.remove(str(REPO / "backend"))


# ── CHANGELOG (next) 位置（next_to_top／post_changelog_order）──────────────────────

_CLOG_OK = "# Changelog\n\n## (next)\n\n- 新\n\n## 5.0 — 2026-11-01\n\n- 舊\n"
_CLOG_BAD = "# Changelog\n\n## 5.1 — 2026-11-10\n\n- 上游新增\n\n## (next)\n\n- 我的\n\n## 5.0 — 2026-11-01\n\n- 舊\n"


def test_next_to_top_moves_a_misplaced_next_section_and_leaves_correct_files_alone():
    assert RB.next_to_top(_CLOG_OK) is None
    got = RB.next_to_top(_CLOG_BAD)
    assert got is not None
    heads = [l for l in got.splitlines() if l.startswith("## ")]
    assert heads == ["## (next)", "## 5.1 — 2026-11-10", "## 5.0 — 2026-11-01"]
    assert "- 我的" in got and "- 上游新增" in got and "- 舊" in got
    assert RB.next_to_top(got) is None, "冪等"


def test_next_to_top_without_any_next_section_or_sections_is_a_noop():
    assert RB.next_to_top("# Changelog\n\n## 5.0 — x\n\n- a\n") is None
    assert RB.next_to_top("# 只有標題\n") is None


def test_post_changelog_order_fixes_core_and_module_changelogs(tmp_path):
    for rel, text in ((RB.CORE_CHANGELOG, _CLOG_BAD), ("backend/modules/foo/CHANGELOG.md", _CLOG_OK), ("backend/modules/bar/CHANGELOG.md", _CLOG_BAD)):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    changed, problems = RB.post_changelog_order(tmp_path, dry=True, skip=set())
    assert sorted(changed) == sorted([RB.CORE_CHANGELOG, "backend/modules/bar/CHANGELOG.md"]) and problems == []
    assert (tmp_path / RB.CORE_CHANGELOG).read_text(encoding="utf-8") == _CLOG_BAD, "--check 不寫檔"
    changed, _ = RB.post_changelog_order(tmp_path, dry=False, skip=set())
    assert len(changed) == 2
    assert RB.post_changelog_order(tmp_path, dry=False, skip=set()) == ([], [])
    assert RB.post_changelog_order(tmp_path, dry=False, skip={RB.CORE_CHANGELOG}) == ([], [])


def test_post_changelog_order_skips_files_with_conflict_markers(tmp_path):
    p = tmp_path / RB.CORE_CHANGELOG
    p.parent.mkdir(parents=True)
    p.write_text("<<<<<<< HEAD\n## 5.1\n=======\n## (next)\n>>>>>>> b\n", encoding="utf-8", newline="\n")
    assert RB.post_changelog_order(tmp_path, dry=False, skip=set()) == ([], [])


@pytest.mark.parametrize("rel", RB.EXTRA_JSON)
def test_extra_json_baselines_exist_and_are_in_a_supported_layout(rel):
    p = REPO / rel
    assert p.is_file(), "%s 不存在：EXTRA_JSON 登記的基準檔被搬走或改名了（同步 resolve_baselines.EXTRA_JSON 與 .gitattributes）" % rel
    hand_laid = {"backend/tests/platform/settings_deploy_baseline.json"}     # 手排：靠逐行聯集備援（與結構合併結果相同才用）
    got = MD.detect_renderer(p.read_text(encoding="utf-8"))
    assert (got is None) == (rel in hand_laid), "%s 的排版驅動認不得（或已變成規則排版，可從 hand_laid 拿掉）" % rel


# ── hichan-3 審查 M1／M2 的回歸題 ─────────────────────────────────────────────────

_CL_BASE = "# 紀錄\n\n## (next)\n- 基底 A\n- 基底 B\n\n## 1.0 — old\n- old\n"


def test_changelog_union_still_works_when_both_sides_only_add_lines():
    a = _CL_BASE.replace("- 基底 B\n", "- 基底 B\n- 甲新增\n")
    b = _CL_BASE.replace("- 基底 A\n", "- 基底 A\n- 乙新增\n")
    got = RB._union_changelog(_CL_BASE, a, b)
    assert got is not None and "- 甲新增" in got and "- 乙新增" in got and "- 基底 A" in got and "- 基底 B" in got


@pytest.mark.parametrize("a,b", [
    (_CL_BASE.replace("- 基底 A", "- A 版"), _CL_BASE.replace("- 基底 A", "- B 版")),                  # 同一行兩邊都改
    (_CL_BASE.replace("- 基底 B\n", ""), _CL_BASE.replace("- 基底 B", "- 基底 B（補充）")),            # 一邊刪、一邊改
    (_CL_BASE.replace("- old\n", ""), _CL_BASE.replace("- 基底 A\n", "- 基底 A\n- 乙新增\n")),         # 一邊只刪（另一邊純新增）也不自動
])
def test_changelog_union_refuses_when_either_side_rewrote_or_deleted_a_base_line(a, b):
    assert RB._union_changelog(_CL_BASE, a, b) is None


def test_select_star_mismatch_is_reported_and_summary_is_still_recomputed(tmp_path, monkeypatch):
    inv = {"summary": {"endpoints_total": 5}, "select_star": {"modules": 288}, "endpoints": {}}
    p = tmp_path / RB.ROUTE_INV
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(inv, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    fake = json.dumps({"summary": {"endpoints_total": 0}, "select_star": {"modules": 289}})
    monkeypatch.setattr(RB, "_py_run", lambda *a, **k: (0, fake + "\n", ""))
    changed, problems = RB.post_route_summary(tmp_path, False, set())
    after = json.loads(p.read_text(encoding="utf-8"))
    assert changed == [RB.ROUTE_INV] and after["summary"] == {"endpoints_total": 0}
    assert after["select_star"] == {"modules": 288}, "select_star 不由原始碼改寫"
    assert len(problems) == 1 and "select_star" in problems[0] and "288" in problems[0] and "289" in problems[0]


def test_max_entries_surplus_note_mentions_duplicate_registration():
    import inspect
    assert "兩邊登記了同一筆" in inspect.getsource(RB.post_unscoped)
