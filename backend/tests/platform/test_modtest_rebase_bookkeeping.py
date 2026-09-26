"""modtest --rebase-check 的簿記檔判定（2026-09-26 主持派工）：只在「同一個項目」被兩邊改時才判衝突。

簿記檔＝每次合回都會兩邊一起改的檔：registry.py（CORE_VERSION）、G1 快照、version_manifest、modules.json。
原本「兩邊都改同檔」一律判重跑全量 ⇒ 每條線都在追著跑全量。每一種都有正對照（不重疊 ⇒ 不判）與反向控制（重疊 ⇒ 判）。
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
_spec = importlib.util.spec_from_file_location("_modtest_bk", REPO / "tools" / "platform" / "modtest.py")
MT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MT)

REG = "backend/core/registry.py"
SNAP = "backend/tests/platform/l1_interface_snapshot.json"
MAN = "backend/version_manifest.json"
MODS = "docs/platform/modules.json"

BASE = {
    REG: 'CORE_VERSION = "1.9"\n\ndef f():\n    return 1\n',
    SNAP: json.dumps({"core_version": "1.9", "interface": {"plat:a": {"x": "def()"}, "plat:b": {"y": "def()"}}}, indent=1),
    MAN: json.dumps([{"module": "系統", "version": "2026-09-26a", "content": "a"}], ensure_ascii=False, indent=1),
    MODS: json.dumps({"L1": {"units": ["plat:a", "plat:b"]}, "modules": {"M01": {"units": ["router:x"]}}}, indent=1),
}


def _git(r, *args):
    return subprocess.run(["git", "-C", str(r), *args], capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout.strip()


def _commit(r, changes, msg):
    for rel, text in changes.items():
        p = r / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        _git(r, "add", "--", rel)
    _git(r, "commit", "-q", "-m", msg)
    return _git(r, "rev-parse", "HEAD")


def _edit(rel, fn):
    """BASE[rel] 經 fn 修改後的文字（JSON 檔：fn 收到解析後的物件、就地改）。"""
    if rel == REG:
        return fn(BASE[rel])
    obj = json.loads(BASE[rel])
    fn(obj)
    return json.dumps(obj, ensure_ascii=False, indent=1)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "platform")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _commit(r, BASE, "base")
    return r


def _check(r, mine, theirs):
    """mine／theirs：{rel: 新文字}。回傳 rebase_check 結果（head＝platform 上疊 mine）。"""
    _git(r, "checkout", "-q", "-b", "mine")
    green = _commit(r, mine, "mine")
    _git(r, "checkout", "-q", "platform")
    _commit(r, theirs, "theirs")
    return MT.rebase_check(green, "platform", repo=r)


def _ver(v):
    return lambda t: t.replace('CORE_VERSION = "1.9"', 'CORE_VERSION = "%s"' % v)


# ── registry.py ───────────────────────────────────────────────────────────

def test_registry_both_only_bump_version_is_not_a_conflict(repo):
    res = _check(repo, {REG: _edit(REG, _ver("1.10"))}, {REG: _edit(REG, _ver("1.10"))})
    assert res["high_impact"] is False and res["bookkeeping"][REG]["conflict"] is False


def test_registry_other_change_on_one_side_only_is_not_a_conflict(repo):
    mine = _edit(REG, lambda t: _ver("1.10")(t).replace("return 1", "return 2"))
    res = _check(repo, {REG: mine}, {REG: _edit(REG, _ver("1.10"))})
    assert res["high_impact"] is False


def test_rc_registry_other_change_on_both_sides_is_a_conflict(repo):
    mine = _edit(REG, lambda t: t.replace("return 1", "return 2"))
    theirs = _edit(REG, lambda t: t + "\nX = 1\n")
    res = _check(repo, {REG: mine}, {REG: theirs})
    assert res["high_impact"] is True and REG in res["overlap"]


# ── G1 快照 ──────────────────────────────────────────────────────────────

def test_snapshot_different_units_is_not_a_conflict(repo):
    def mine(o):
        o["core_version"] = "1.10"
        o["interface"]["plat:a"]["x2"] = "def()"

    def theirs(o):
        o["core_version"] = "1.10"
        o["interface"]["plat:c"] = {"z": "def()"}
    res = _check(repo, {SNAP: _edit(SNAP, mine)}, {SNAP: _edit(SNAP, theirs)})
    assert res["high_impact"] is False and res["bookkeeping"][SNAP]["conflict"] is False


def test_rc_snapshot_same_name_changed_on_both_sides_is_a_conflict(repo):
    def mine(o):
        o["interface"]["plat:a"]["x"] = "def(a)"

    def theirs(o):
        o["interface"]["plat:a"]["x"] = "def(b)"
    res = _check(repo, {SNAP: _edit(SNAP, mine)}, {SNAP: _edit(SNAP, theirs)})
    assert res["high_impact"] is True and SNAP in res["overlap"]


# ── version_manifest ─────────────────────────────────────────────────────

def test_manifest_different_entries_is_not_a_conflict(repo):
    res = _check(repo, {MAN: _edit(MAN, lambda o: o.insert(0, {"module": "傳票", "version": "2026-09-26b", "content": "m"}))},
                 {MAN: _edit(MAN, lambda o: o.insert(0, {"module": "地圖", "version": "2026-09-26c", "content": "t"}))})
    assert res["high_impact"] is False


def test_rc_manifest_same_entry_changed_on_both_sides_is_a_conflict(repo):
    """VR3：同一模組併進同一筆 ⇒ 兩邊都改 26a 的 content ⇒ 衝突。"""
    res = _check(repo, {MAN: _edit(MAN, lambda o: o[0].update(content="a；mine"))},
                 {MAN: _edit(MAN, lambda o: o[0].update(content="a；theirs"))})
    assert res["high_impact"] is True and MAN in res["overlap"]


# ── modules.json ─────────────────────────────────────────────────────────

def test_modules_json_different_new_units_is_not_a_conflict(repo):
    res = _check(repo, {MODS: _edit(MODS, lambda o: o["L1"]["units"].append("plat:menu"))},
                 {MODS: _edit(MODS, lambda o: o["L1"]["units"].append("plat:pages"))})
    assert res["high_impact"] is False


def test_rc_modules_json_same_unit_on_both_sides_is_a_conflict(repo):
    """同一個單位被兩邊改（這裡：一邊移到 M01、另一邊從 L1 刪掉）⇒ 衝突。"""
    def mine(o):
        o["L1"]["units"].remove("plat:b")
        o["modules"]["M01"]["units"].append("plat:b")

    res = _check(repo, {MODS: _edit(MODS, mine)}, {MODS: _edit(MODS, lambda o: o["L1"]["units"].remove("plat:b"))})
    assert res["high_impact"] is True and MODS in res["overlap"]


# ── rebase 之後才改的（core_bump）與保守判定 ─────────────────────────────

def test_version_bump_after_rebase_is_not_a_conflict(repo):
    """core_bump 在 rebase 之後改 CORE_VERSION ⇒ 帶進來的也改過 registry ⇒ 原本判「又被本分支改過」＝衝突。"""
    _git(repo, "checkout", "-q", "-b", "mine")
    green = _commit(repo, {"backend/x.py": "x = 1\n"}, "mine")
    _git(repo, "checkout", "-q", "platform")
    _commit(repo, {REG: _edit(REG, _ver("1.10"))}, "theirs 1.10")
    _git(repo, "checkout", "-q", "-b", "rebased", "platform")
    _git(repo, "cherry-pick", green)
    _commit(repo, {REG: _edit(REG, _ver("1.11"))}, "core_bump 1.11")
    res = MT.rebase_check(green, "platform", repo=repo, head=_git(repo, "rev-parse", "HEAD"))
    assert res["high_impact"] is False and res["bookkeeping"][REG]["conflict"] is False


def test_rc_unreadable_side_is_conservatively_a_conflict(repo):
    """一邊新增（base 沒有這個檔）⇒ 讀不到 ⇒ 保守判衝突。"""
    _git(repo, "rm", "-q", "--", MAN)
    _git(repo, "commit", "-q", "-m", "drop manifest")
    res = _check(repo, {MAN: "[]"}, {MAN: "[]\n"})
    assert res["high_impact"] is True and "保守" in res["bookkeeping"][MAN]["detail"]


def test_rc_non_bookkeeping_file_still_counts_as_file_overlap(repo):
    """反向控制：其他程式檔照舊（同檔就判衝突），不受簿記檔規則影響。"""
    res = _check(repo, {"backend/y.py": "a = 1\n"}, {"backend/y.py": "b = 1\n"})
    assert res["high_impact"] is True and res["overlap"] == ["backend/y.py"]
