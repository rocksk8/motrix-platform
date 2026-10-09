"""tools/platform/merge_drivers.py＋setup_merge_drivers.py：CHANGELOG／version_manifest 兩邊都在最上面插入 ⇒ 兩邊都留（PLAYBOOK §G6）。

純函式（三方合併規則）＋真的 git（登記驅動後 merge／cherry-pick 不衝突；沒登記或形狀看不懂 ⇒ 照常衝突，不靜默少東西）。
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load(name):
    spec = importlib.util.spec_from_file_location("_" + name, REPO / "tools" / "platform" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MD = _load("merge_drivers")
SETUP = _load("setup_merge_drivers")

PRE = "# m 更新紀錄\n\n> 說明\n\n"
BASE = PRE + "## 1.0.1 — d\n- old\n\n## 1.0.0 — d\n- init\n"
SEC_A = "## (next) — 2026-09-30（wip/a）\n- a1\n- 題：tests/platform/test_same.py\n\n"
SEC_B = "## (next) — 2026-09-30（wip/b）\n- b1\n- 題：tests/platform/test_same.py\n\n"


def _ins(sec, text=BASE):
    return text.replace("## 1.0.1", sec + "## 1.0.1", 1)


# ── CHANGELOG（純函式）──────────────────────────────────────────────────

#: 兩邊各新增一塊 `## (next)` ⇒ 併成一塊（第 51 班，SPEEDUP-PREPUSH-T50 類 1）：A 的整塊照舊，B 的標題變成「（併入）」一行、內文接在後面
COALESCED = (SEC_A.rstrip("\n") + "\n- **（併入）(next) — 2026-09-30（wip/b）**\n- b1\n- 題：tests/platform/test_same.py\n\n")
SEC_N1 = "## 1.0.3 — x\n- n1\n\n"
SEC_N2 = "## 1.0.2 — y\n- n2\n\n"


def test_both_top_next_blocks_are_coalesced_into_one():
    got = MD.merge_changelog(BASE, _ins(SEC_A), _ins(SEC_B))
    assert got == PRE + COALESCED + "## 1.0.1 — d\n- old\n\n## 1.0.0 — d\n- init\n"
    assert got.count("## (next)") == 1


def test_both_top_numbered_blocks_are_still_kept_as_whole_blocks():
    """反向控制：只有 `## (next)` 才併；兩邊各新增一個『版號』段落仍然兩個都留。"""
    got = MD.merge_changelog(BASE, _ins(SEC_N1), _ins(SEC_N2))
    assert got == PRE + SEC_N1 + SEC_N2 + "## 1.0.1 — d\n- old\n\n## 1.0.0 — d\n- init\n"


def test_coalesce_next_is_a_noop_with_fewer_than_two_next_blocks():
    secs = [SEC_A, SEC_N1]
    assert MD.coalesce_next(secs) == secs
    assert MD.coalesce_next([]) == []


def test_identical_insertions_are_kept_once():
    assert MD.merge_changelog(BASE, _ins(SEC_A), _ins(SEC_A)) == _ins(SEC_A)


def test_one_side_edits_an_old_section_the_other_inserts():
    edited = BASE.replace("- old", "- old（補字）")
    assert MD.merge_changelog(BASE, _ins(SEC_A), edited) == _ins(SEC_A, edited)


def test_missing_blank_line_between_blocks_is_restored():
    a = _ins("## (next) — a\n- a\n")                       # 作者沒留空行
    got = MD.merge_changelog(BASE, a, _ins(SEC_B))
    assert "- a\n- **（併入）(next) — 2026-09-30（wip/b）**\n- b1" in got      # 作者沒留空行也照常併成一塊
    assert got.count("## (next)") == 1


@pytest.mark.parametrize("a,b,why", [
    (BASE.replace("- old", "- 甲改"), BASE.replace("- old", "- 乙改"), "兩邊改同一段舊內容"),
    (BASE.replace("> 說明", "> 甲"), BASE.replace("> 說明", "> 乙"), "前言兩邊改得不一樣"),
    (BASE.replace("## 1.0.1 — d", "## 1.0.1 — 改標題"), _ins(SEC_B), "基底第一段的標題被改（對不上）"),
])
def test_rc_unsafe_shapes_fall_back_to_a_normal_conflict(a, b, why):
    assert MD.merge_changelog(BASE, a, b) is None, why


# ── manifest（純函式）───────────────────────────────────────────────────

def _m(*es):
    return "[\n  " + ",\n  ".join(json.dumps(e, ensure_ascii=False) for e in es) + "\n]\n"


X = {"module": "舊", "version": "2026-09-29a", "date": "2026-09-29", "time": "", "content": "x"}
A = {"module": "甲", "version": "next", "date": "2026-09-30", "time": "10:00", "content": "a"}
B = {"module": "乙", "version": "next", "date": "2026-09-30", "time": "11:00", "content": "b"}


def test_manifest_both_additions_are_kept_ours_first():
    assert MD.merge_manifest(_m(X), _m(A, X), _m(B, X)) == _m(A, B, X)


def test_manifest_identical_addition_is_kept_once():
    assert MD.merge_manifest(_m(X), _m(A, X), _m(A, X)) == _m(A, X)


def test_manifest_one_side_renumbers_the_other_adds():
    """列車取號（我方把 next 換成號碼）之後再疊下一包：對方沒動基底 ⇒ 照我方。"""
    numbered = dict(A, version="2026-09-30a")
    assert MD.merge_manifest(_m(A, X), _m(numbered, X), _m(B, A, X)) == _m(numbered, B, X)


def test_manifest_keeps_multiline_entries_verbatim():
    multi = '{\n    "module": "多行",\n    "version": "2026-09-01",\n    "content": "y"\n  }'
    base = "[\n  " + multi + "\n]\n"
    a = "[\n  " + json.dumps(A, ensure_ascii=False) + ",\n  " + multi + "\n]\n"
    b = "[\n  " + json.dumps(B, ensure_ascii=False) + ",\n  " + multi + "\n]\n"
    got = MD.merge_manifest(base, a, b)
    assert multi in got and [e["module"] for e in json.loads(got)] == ["甲", "乙", "多行"]


@pytest.mark.parametrize("o,a,b,why", [
    (_m(X), _m(dict(X, content="甲改")), _m(dict(X, content="乙改")), "兩邊都改了基底條目"),
    (_m(X), _m(A, X), json.dumps([B, X]), "對方不是本 repo 的排版"),
    (_m(X), _m(A, X), "[\n  {壞掉\n]\n", "對方不是合法 JSON"),
])
def test_rc_manifest_unsafe_shapes_fall_back(o, a, b, why):
    assert MD.merge_manifest(o, a, b) is None, why


def test_real_manifest_is_in_the_supported_format():
    """正對照：真實檔案必須是驅動看得懂的排版，否則驅動永遠退回一般合併（安全，但等於沒裝）。"""
    text = (REPO / "backend" / "version_manifest.json").read_text(encoding="utf-8")
    spans = MD.parse_manifest(text)
    assert spans is not None and len(spans) == len(json.loads(text))


# ── 真的 git：登記驅動 ⇒ 不衝突；沒登記 ⇒ 照常衝突 ────────────────────────────

ATTR = ("CHANGELOG.md merge=motrix-changelog\nversion_manifest.json merge=motrix-manifest\n")


def _g(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True, text=True, encoding="utf-8")


def _w(repo, name, text):
    (repo / name).write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture()
def two_branches(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _g(r, "init", "-q", "-b", "platform")
    _g(r, "config", "user.email", "t@example.invalid")
    _g(r, "config", "user.name", "t")
    _g(r, "config", "core.autocrlf", "false")
    _w(r, ".gitattributes", ATTR)
    _w(r, "CHANGELOG.md", BASE)
    _w(r, "version_manifest.json", _m(X))
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", "base")
    for name, sec, e in (("wip/a", SEC_A, A), ("wip/b", SEC_B, B)):
        _g(r, "checkout", "-q", "-b", name, "platform")
        _w(r, "CHANGELOG.md", _ins(sec))
        _w(r, "version_manifest.json", _m(e, X))
        _g(r, "commit", "-q", "-am", name)
    _g(r, "checkout", "-q", "platform")
    return r


def test_git_merge_with_drivers_keeps_both_sides(two_branches):
    r = two_branches
    SETUP.install(r)
    assert SETUP.problems(r) == []
    _g(r, "merge", "-q", "--no-ff", "wip/a", "-m", "a")
    res = _g(r, "merge", "--no-ff", "wip/b", "-m", "b", check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    assert (r / "CHANGELOG.md").read_text(encoding="utf-8") == PRE + COALESCED + BASE[len(PRE):]
    assert [e["module"] for e in json.loads((r / "version_manifest.json").read_text(encoding="utf-8"))] == ["甲", "乙", "舊"]


def test_git_cherry_pick_with_drivers_keeps_both_sides(two_branches):
    """列車是一包一包 cherry-pick 上去的：同樣要兩邊都留。"""
    r = two_branches
    SETUP.install(r)
    _g(r, "checkout", "-q", "-b", "train/1", "platform")
    _g(r, "cherry-pick", "wip/a")
    res = _g(r, "cherry-pick", "wip/b", check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    text = (r / "CHANGELOG.md").read_text(encoding="utf-8")
    assert SEC_A.rstrip("\n") in text and "（併入）(next) — 2026-09-30（wip/b）" in text and "<<<<<<<" not in text
    assert text.count("## (next)") == 1


def test_rc_without_drivers_git_reports_a_conflict(two_branches):
    """沒登記驅動的機器：git 照常出衝突（有標記、exit≠0）——不會靜默只留一邊。"""
    r = two_branches
    _g(r, "merge", "-q", "--no-ff", "wip/a", "-m", "a")
    res = _g(r, "merge", "--no-ff", "wip/b", "-m", "b", check=False)
    assert res.returncode != 0
    text = (r / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "<<<<<<<" in text and "wip/a" in text and "wip/b" in text


def test_rc_driver_falls_back_to_conflict_markers_on_unsafe_shape(two_branches):
    """驅動裝了，但兩邊改了同一段舊內容 ⇒ 驅動交給 git merge-file：衝突標記、exit≠0。"""
    r = two_branches
    SETUP.install(r)
    for name, txt in (("wip/c", "- 甲改"), ("wip/d", "- 乙改")):
        _g(r, "checkout", "-q", "-b", name, "platform")
        _w(r, "CHANGELOG.md", BASE.replace("- old", txt))
        _g(r, "commit", "-q", "-am", name)
    _g(r, "checkout", "-q", "platform")
    _g(r, "merge", "-q", "--no-ff", "wip/c", "-m", "c")
    res = _g(r, "merge", "--no-ff", "wip/d", "-m", "d", check=False)
    assert res.returncode != 0
    text = (r / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "<<<<<<<" in text and "- 甲改" in text and "- 乙改" in text


def test_setup_check_detects_stale_copy_and_missing_config(two_branches):
    r = two_branches
    assert any("沒有登記" in p for p in SETUP.problems(r))
    copy = SETUP.install(r)
    copy.write_text("# 舊版\n", encoding="utf-8")
    assert any("過期" in p for p in SETUP.problems(r))
    SETUP.install(r)
    assert SETUP.problems(r) == []
    SETUP.remove(r)
    assert SETUP.problems(r)


def test_cli_usage_error_is_not_a_silent_success(tmp_path):
    res = subprocess.run([sys.executable, str(REPO / "tools" / "platform" / "merge_drivers.py"), "bogus"],
                         capture_output=True)
    assert res.returncode == 2
