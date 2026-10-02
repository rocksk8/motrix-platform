"""tools/platform/train_number.py：列車取號（PLAYBOOK §G6）。純函式＋合成 git repo 的整合題；每條規則附反向控制。"""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("_train_number", REPO / "tools" / "platform" / "train_number.py")
TN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(TN)

HDR = "# m 更新紀錄\n\n"
OLD = "## 1.2.0 — 2026-09-20\n- 已出貨\n\n## 1.1.0 — 2026-09-10\n- 更早\n"


def _heads(text):
    return [l for l in text.splitlines() if l.startswith("## ")]


# ── 模組 CHANGELOG ───────────────────────────────────────────────────────

def test_placeholders_take_next_patch_bottom_up_and_levels_are_honoured():
    text = HDR + "## (next:minor) — d（wip/b）\n- b\n\n## (next) — d（wip/a）\n- a\n\n" + OLD
    new, top, ch = TN.assign_changelog(text, (1, 2, 0), 3)
    assert _heads(new)[:2] == ["## 1.3.0 — d（wip/b）", "## 1.2.1 — d（wip/a）"]
    assert top == (1, 3, 0) and [c[1] for c in ch] == ["1.2.1", "1.3.0"]
    assert new.endswith(OLD), "已出貨的段落一個字都不動"


def test_numbered_unshipped_is_kept_and_placeholder_goes_above():
    text = HDR + "## (next) — d（wip/a）\n- a\n\n## 1.2.1 — 已在 platform\n- p\n\n" + OLD
    new, top, ch = TN.assign_changelog(text, (1, 2, 0), 3)
    assert _heads(new)[:2] == ["## 1.2.2 — d（wip/a）", "## 1.2.1 — 已在 platform"]
    assert len(ch) == 1


def test_collision_is_renumbered_base_number_wins_and_is_reported():
    """舊式分支（先取號）撞號：platform 已有的 1.2.1 保留，分支帶來的 1.2.1 重編並在標題尾註記；分支段落排到上面。"""
    plat = "## 1.2.1 — platform\n- p\n\n"
    branch = "## 1.2.1 — wip/b\n- b\n\n"
    text = HDR + plat + branch + OLD                        # 合併驅動：我方（列車）在上
    new, top, ch = TN.assign_changelog(text, (1, 2, 0), 3, pinned_heads=["## 1.2.1 — platform"])
    assert _heads(new)[:2] == ["## 1.2.2 — wip/b〔train_number：1.2.1 → 1.2.2〕", "## 1.2.1 — platform"]
    assert ch == [("1.2.1", "1.2.2", "撞號／未遞增 ⇒ 重編")]


def test_rc_without_pin_the_lower_one_keeps_the_number():
    text = HDR + "## 1.2.1 — x\n\n## 1.2.1 — y\n\n" + OLD
    new, _, ch = TN.assign_changelog(text, (1, 2, 0), 3)
    assert _heads(new)[:2] == ["## 1.2.2 — x〔train_number：1.2.1 → 1.2.2〕", "## 1.2.1 — y"]


def test_minor_collision_keeps_its_level():
    text = HDR + "## 1.3.0 — a\n\n## 1.3.0 — b\n\n" + OLD
    new, top, _ = TN.assign_changelog(text, (1, 2, 0), 3)
    assert top == (1, 4, 0), "撞號的 x.y.0 仍升次版號"


def test_new_module_placeholder_starts_at_1_0_0():
    new, top, _ = TN.assign_changelog(HDR + "## (next) — d\n- 初版\n", None, 3)
    assert top == (1, 0, 0) and "## 1.0.0 — d" in new


def test_assign_is_idempotent():
    text = HDR + "## (next) — d（wip/a）\n- a\n\n## 1.2.1 — x\n\n## 1.2.1 — y\n\n" + OLD
    once, top1, _ = TN.assign_changelog(text, (1, 2, 0), 3)
    twice, top2, ch2 = TN.assign_changelog(once, (1, 2, 0), 3)
    assert once == twice and top1 == top2 and ch2 == []


def test_rc_nothing_to_do_changes_nothing():
    text = HDR + "## 1.2.1 — x\n- x\n\n" + OLD
    assert TN.assign_changelog(text, (1, 2, 0), 3) == (text, (1, 2, 1), [])


# ── CORE CHANGELOG ───────────────────────────────────────────────────────

CORE_OLD = "## 1.70 — d\n- 已出貨\n"


def test_core_placeholder_takes_minor_and_skips_non_version_sections():
    text = "# c\n\n## (next) — d（wip/a）\n- a\n\n## （不升版號：介面不變）— d\n- b\n\n## 1.71 — platform\n- p\n\n" + CORE_OLD
    new, top, ch = TN.assign_changelog(text, (1, 70), 2, ["## 1.71 — platform"], "minor")
    assert top == (1, 72) and "## 1.72 — d（wip/a）" in new and "## （不升版號：介面不變）— d" in new


def test_core_major_need_goes_to_the_lowest_placeholder():
    text = "# c\n\n## (next) — b\n\n## (next) — a\n\n" + CORE_OLD
    new, top, _ = TN.assign_changelog(text, (1, 70), 2, (), "minor", need_major=True)
    assert _heads(new)[:2] == ["## 2.1 — b", "## 2.0 — a"]
    new2, top2, _ = TN.assign_changelog(text, (1, 70), 2, (), "minor", need_major=False)
    assert top2 == (1, 72), "反向控制：不需要主版號就只升次版號"


# ── manifest ─────────────────────────────────────────────────────────────

def _m(entries):
    return "[\n  " + ",\n  ".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n]\n"


def E(mod, ver, date="2026-09-30", time="10:00", content="一段足夠長的說明文字內容"):
    return {"module": mod, "version": ver, "date": date, "time": time, "content": content}


def test_manifest_placeholders_take_letters_after_the_days_maximum_in_time_order():
    text = _m([E("乙", "next", time="12:00"), E("甲", "next", time="09:00"), E("丙", "2026-09-30c"), E("丁", "2026-09-29z", "2026-09-29")])
    new, ch = TN.assign_manifest(text, shipped={("丙", "2026-09-30c"), ("丁", "2026-09-29z")})
    got = {e["module"]: e["version"] for e in json.loads(new)}
    assert got == {"甲": "2026-09-30d", "乙": "2026-09-30e", "丙": "2026-09-30c", "丁": "2026-09-29z"}
    assert new.startswith('[\n  {"module": "乙", "version": "2026-09-30e"'), "排版與位置不變，只換版號"


def test_manifest_suffix_after_z_is_aa():
    assert [TN.next_suffix(s) for s in ("", "a", "z", "az", "zz")] == ["a", "b", "aa", "ba", "aaa"]
    new, _ = TN.assign_manifest(_m([E("甲", "next"), E("乙", "2026-09-30z")]), shipped=set())
    assert json.loads(new)[0]["version"] == "2026-09-30aa"


def test_manifest_placeholder_merges_into_the_modules_unshipped_entry():
    text = _m([E("甲", "next", time="11:00", content="第二件事的說明文字"), E("甲", "2026-09-30a", content="第一件事的說明文字")])
    new, ch = TN.assign_manifest(text, shipped=set(), base_entries=[E("甲", "2026-09-30a", content="第一件事的說明文字")])
    es = json.loads(new)
    assert len(es) == 1 and es[0]["version"] == "2026-09-30a"
    assert es[0]["content"] == "第一件事的說明文字\n第二件事的說明文字"


def test_rc_shipped_entries_are_never_merged_or_renumbered():
    shipped = E("甲", "2026-09-30a", content="已出貨的說明文字")
    text = _m([E("甲", "next"), E("乙", "2026-09-30a"), shipped])
    new, ch = TN.assign_manifest(text, shipped={("甲", "2026-09-30a")})
    es = json.loads(new)
    assert shipped in es, "已出貨的逐字留著"
    assert {e["module"]: e["version"] for e in es if e is not shipped and e != shipped} == {"甲": "2026-09-30b", "乙": "2026-09-30c"}, \
        "未出貨的撞到已出貨的號 ⇒ 未出貨的重編；佔位不併進已出貨的"


def test_manifest_collision_keeps_the_base_entry():
    base = E("乙", "2026-09-30b", content="platform 上的說明文字")
    text = _m([E("甲", "2026-09-30b"), base])
    new, ch = TN.assign_manifest(text, shipped=set(), base_entries=[base])
    got = {e["module"]: e["version"] for e in json.loads(new)}
    assert got == {"乙": "2026-09-30b", "甲": "2026-09-30c"} and ch == [("甲", "2026-09-30b", "2026-09-30c", "撞號 ⇒ 重編")]


def test_manifest_assign_is_idempotent_and_keeps_multiline_entries():
    multi = '{\n    "module": "舊",\n    "version": "2026-09-01",\n    "date": "2026-09-01",\n    "time": "",\n    "content": "x"\n  }'
    text = "[\n  " + json.dumps(E("甲", "next"), ensure_ascii=False) + ",\n  " + multi + "\n]\n"
    once, _ = TN.assign_manifest(text, shipped={("舊", "2026-09-01")})
    assert multi in once
    twice, ch = TN.assign_manifest(once, shipped={("舊", "2026-09-01")})
    assert once == twice and ch == []


def test_rc_manifest_placeholder_without_date_is_refused():
    with pytest.raises(SystemExit, match="缺 date"):
        TN.assign_manifest(_m([E("甲", "next", date="")]), shipped=set())


# ── core migration ───────────────────────────────────────────────────────

MIG = 'register("core", 1, _a)\nregister("core", 2, _b)\n'


def test_migration_next_slots_become_consecutive_in_file_order():
    new, ch = TN.assign_migrations(MIG + 'register("core", NEXT, _c)\nregister("core", NEXT, _d)\n', MIG)
    assert new.endswith('register("core", 3, _c)\nregister("core", 4, _d)\n')
    assert TN.assign_migrations(new, MIG) == (new, []), "冪等"


def test_migration_collision_keeps_the_base_line():
    text = MIG + 'register("core", 3, _x)\nregister("core", 3, _y)\n'
    new, ch = TN.assign_migrations(text, MIG + 'register("core", 3, _y)\n')
    assert 'register("core", 3, _y)' in new and 'register("core", 4, _x)' in new
    assert "開發庫" in ch[0][3]


def test_migration_next_is_numbered_above_base_and_prod_baseline():
    """NEXT 一律換成整數，且高於 origin/platform 與正式機已用的號碼。"""
    text = MIG + 'register("core", 3, _p)\nregister("core", NEXT, _c)\n'
    new, ch = TN.assign_migrations(text, MIG + 'register("core", 3, _p)\n', MIG)
    assert 'register("core", 4, _c)' in new and "NEXT" not in new
    assert ch == [("_c", "NEXT", "4", "佔位取號")]


def test_rc_migration_file_missing_shipped_numbers_is_refused():
    """檔案最大號比 platform／正式機小（少了已上線的 migration）⇒ 拒絕，不從較小的號往上給（會與已上線的撞號）。"""
    with pytest.raises(SystemExit, match="少了已上線"):
        TN.assign_migrations(MIG + 'register("core", NEXT, _c)\n', MIG + 'register("core", 3, _p)\n')
    with pytest.raises(SystemExit, match="少了已上線"):
        TN.assign_migrations(MIG + 'register("core", NEXT, _c)\n', MIG, MIG + 'register("core", 3, _p)\n')


def test_rc_docstring_mentions_are_not_rewritten():
    text = '"""register("core", NEXT, fn) 說明"""\n' + MIG
    assert TN.assign_migrations(text) == (text, [])


# ── 整合：合成 repo ＋ CLI（assign／--check）─────────────────────────────────

def _g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


def _w(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture()
def train(tmp_path):
    """shipped（正式機基準）→ platform（多一個未出貨的 1.2.1）→ train（兩個分支的佔位疊上去）。"""
    r = tmp_path / "t"
    r.mkdir()
    _g(r, "init", "-q", "-b", "platform")
    _g(r, "config", "user.email", "t@example.invalid")
    _g(r, "config", "user.name", "t")
    _w(r, "backend/modules/m/module.json", json.dumps({"key": "m", "version": "1.2.0"}, indent=2) + "\n")
    _w(r, "backend/modules/m/CHANGELOG.md", HDR + OLD)
    _w(r, "backend/core/CHANGELOG.md", "# c\n\n" + CORE_OLD)
    _w(r, "backend/core/registry.py", 'CORE_VERSION = "1.70"\n')
    _w(r, "backend/tests/platform/l1_interface_snapshot.json", json.dumps({"core_version": "1.70", "interface": {}}, indent=1) + "\n")
    _w(r, "backend/core/migrations.py", MIG)
    _w(r, "backend/version_manifest.json", _m([E("舊", "2026-09-29a", "2026-09-29")]))
    _w(r, "backend/tests/_prod_baseline.py", 'BASELINE = "0000000"\n')
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", "shipped")
    shipped = _g(r, "rev-parse", "HEAD")
    _w(r, "backend/tests/_prod_baseline.py", 'BASELINE = "%s"\n' % shipped)
    _w(r, "backend/modules/m/CHANGELOG.md", HDR + "## 1.2.1 — platform\n- p\n\n" + OLD)
    _w(r, "backend/modules/m/module.json", json.dumps({"key": "m", "version": "1.2.1"}, indent=2) + "\n")
    _g(r, "commit", "-q", "-am", "platform")
    _g(r, "checkout", "-q", "-b", "train/1")
    _w(r, "backend/modules/m/CHANGELOG.md", HDR + "## (next) — d（wip/b）\n- b\n\n## (next) — d（wip/a）\n- a\n\n## 1.2.1 — platform\n- p\n\n" + OLD)
    _w(r, "backend/core/CHANGELOG.md", "# c\n\n## (next) — d（wip/a）\n- a\n\n" + CORE_OLD)
    _w(r, "backend/tests/platform/l1_interface_snapshot.json", json.dumps({"core_version": "next", "interface": {}}, indent=1) + "\n")
    _w(r, "backend/core/migrations.py", MIG + 'register("core", NEXT, _c)\n')
    _w(r, "backend/version_manifest.json", _m([E("m", "next", time="11:00"), E("n", "next", time="10:00"), E("舊", "2026-09-29a", "2026-09-29")]))
    _g(r, "commit", "-q", "-am", "train: 兩包疊上來")
    return r


def _run(r, *args):
    return TN.main([*args, "--root", str(r), "--base", "platform"])


def test_check_is_red_before_and_green_after_assign(train, capsys):
    assert _run(train, "--check") == 1, "有佔位 ⇒ --check 紅"
    assert _run(train, "assign", "--dry-run") == 3
    assert _run(train, "assign") == 0
    out = capsys.readouterr().out
    assert "佔位取號" in out and "類別" in out, "印出取號表"
    assert json.loads((train / "backend/modules/m/module.json").read_text(encoding="utf-8"))["version"] == "1.2.3"
    assert _heads((train / "backend/modules/m/CHANGELOG.md").read_text(encoding="utf-8"))[:3] == [
        "## 1.2.3 — d（wip/b）", "## 1.2.2 — d（wip/a）", "## 1.2.1 — platform"]
    assert 'CORE_VERSION = "1.71"' in (train / "backend/core/registry.py").read_text(encoding="utf-8")
    assert json.loads((train / "backend/tests/platform/l1_interface_snapshot.json").read_text(encoding="utf-8"))["core_version"] == "1.71"
    assert 'register("core", 3, _c)' in (train / "backend/core/migrations.py").read_text(encoding="utf-8")
    vers = {e["module"]: e["version"] for e in json.loads((train / "backend/version_manifest.json").read_text(encoding="utf-8"))}
    assert vers == {"n": "2026-09-30a", "m": "2026-09-30b", "舊": "2026-09-29a"}
    assert _run(train, "--check") == 0, "取號後 --check 綠"
    before = {p: p.read_bytes() for p in train.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert _run(train, "assign") == 0
    assert before == {p: p.read_bytes() for p in train.rglob("*") if p.is_file() and ".git" not in p.parts}, "冪等"


def test_rc_check_catches_a_collision_without_placeholders(train):
    _g(train, "checkout", "-q", "platform")
    _w(train, "backend/modules/m/CHANGELOG.md", HDR + "## 1.2.1 — 另一包也取了 1.2.1\n\n## 1.2.1 — platform\n- p\n\n" + OLD)
    assert _run(train, "--check") == 1


def test_rc_missing_baseline_commit_is_refused(train):
    _w(train, "backend/tests/_prod_baseline.py", 'BASELINE = "deadbeef"\n')
    with pytest.raises(SystemExit, match="正式機基準"):
        _run(train, "--check")
