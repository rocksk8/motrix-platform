"""版號佔位（PLAYBOOK §G6；使用者 2026-09-30「撞號太多次了，想辦法解決」）的守門與契約題。

① 不准有佔位的地方（MOTRIX_TRAIN=1、分支 platform／master／main／train/*、HEAD 是 prod/* 標籤）一筆都不可以有；
② 佔位的格式：CHANGELOG 標題只認 `## (next)`／`(next:patch|minor|major)`，寫錯的（`## (Next)`、`## next`）⇒ 紅（工具不猜）；
③ manifest 佔位條目要有 module／date（YYYY-MM-DD）／content（> 10 字）——列車取號靠 date 排字母；
④ core migration 的 NEXT：runtime 不記版號、排在已編號之後、每次重跑；非 core 不准。
判定（准不准、找佔位）在 tests/_version_slots.py，與 tools/platform/train_number.py 共用。
"""
import json
import logging
import re
import sqlite3
import subprocess

import pytest

from core import migrations
from tests import _version_slots as VS


def forbidden_placeholders(root=VS.ROOT, environ=None):
    """⇒ (准不准, 理由, 不准時找到的佔位)。真實題與反向控制走同一支（§G5 第 15 項）。"""
    ok, why = VS.placeholders_allowed(root, environ)
    return ok, why, ([] if ok else VS.find_placeholders(root))


# ── ① 不准的地方一筆都不可以有（含 core migration 的 NEXT：它在 runtime 是「每次重跑」，只准在分支上）──

def test_no_placeholders_where_they_are_forbidden():
    ok, why, found = forbidden_placeholders()
    if ok:
        pytest.skip("這裡准有佔位（%s）；列車取號" % why)
    assert not found, ("這裡不准有版號佔位（%s）⇒ 跑 `python tools/platform/train_number.py assign` 取號：\n  " % why
                       + "\n  ".join(found))


# ── ② ③ 格式 ──────────────────────────────────────────────────────────────

def test_placeholder_headings_are_well_formed():
    bad = []
    for cl in VS.module_changelogs() + [VS.ROOT / "backend" / "core" / "CHANGELOG.md"]:
        for line in VS.malformed_headings(cl.read_text(encoding="utf-8")):
            bad.append("%s：%s" % (cl.relative_to(VS.ROOT).as_posix(), line))
    assert not bad, "佔位標題格式不對（只認 `## (next)`、`## (next:minor)`、`## (next:major)`）：\n  " + "\n  ".join(bad)


def manifest_placeholder_problems(entries):
    bad = []
    for e in entries:
        if e.get("version") != VS.PLACEHOLDER:
            continue
        who = e.get("module") or "?"
        if not str(e.get("module") or "").strip():
            bad.append("%s：缺 module" % who)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e.get("date") or "")):
            bad.append("%s：date 要是 YYYY-MM-DD（列車依它排字母）" % who)
        if len(str(e.get("content") or "").strip()) <= 10:
            bad.append("%s：content 太短" % who)
    return bad


def test_manifest_placeholders_are_complete():
    entries = json.loads((VS.ROOT / "backend" / "version_manifest.json").read_text(encoding="utf-8-sig"))
    bad = manifest_placeholder_problems(entries)
    assert not bad, "manifest 佔位條目不完整：\n  " + "\n  ".join(bad)


def test_rc_format_checks():
    assert VS.malformed_headings("# m\n\n## (next) — d\n## (next:minor) — d\n## 1.0.0 — d\n") == []
    assert VS.malformed_headings("# m\n\n## (Next) — d\n## next — d\n## (next:big) — d\n") == [
        "## (Next) — d", "## next — d", "## (next:big) — d"]
    ok = {"module": "甲", "version": "next", "date": "2026-09-30", "content": "這是一段足夠長的說明文字。"}
    assert manifest_placeholder_problems([ok]) == []
    assert len(manifest_placeholder_problems([dict(ok, date="09/30")])) == 1
    assert len(manifest_placeholder_problems([dict(ok, content="短")])) == 1
    assert manifest_placeholder_problems([dict(ok, version="2026-09-30a", content="")]) == [], "有號碼的不歸這題管"


# ── 准不准：合成 git repo ─────────────────────────────────────────────────

def _g(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture()
def grepo(tmp_path):
    r = tmp_path / "g"
    r.mkdir()
    _g(r, "init", "-q", "-b", "wip/x")
    _g(r, "config", "user.email", "t@example.invalid")
    _g(r, "config", "user.name", "t")
    (r / "a.txt").write_text("a\n", encoding="utf-8")
    _g(r, "add", "-A")
    _g(r, "commit", "-q", "-m", "a")
    return r


def test_rc_allowed_on_wip_and_forbidden_on_train_platform_tags(grepo, tmp_path):
    assert VS.placeholders_allowed(grepo, {})[0] is True
    assert VS.placeholders_allowed(grepo, {"MOTRIX_TRAIN": "1"})[0] is False
    for b in ("platform", "master", "train/0930-1200"):
        _g(grepo, "checkout", "-q", "-b", b)
        assert VS.placeholders_allowed(grepo, {}) == (False, "分支 %s" % b)
        _g(grepo, "checkout", "-q", "wip/x")
    _g(grepo, "checkout", "-q", "--detach")
    assert VS.placeholders_allowed(grepo, {})[0] is True, "一般 detached（core_only_rc 的拋棄樹）照分支規則"
    _g(grepo, "tag", "prod/abc")
    assert VS.placeholders_allowed(grepo, {})[0] is False, "HEAD 是正式機標籤"
    nogit = tmp_path / "nogit"
    nogit.mkdir()
    assert VS.placeholders_allowed(nogit, {})[0] is False, "git 查不到 ⇒ 當成不准（寧可紅）"


def test_rc_core_migration_next_is_red_on_train_platform_and_prod_tag(grepo):
    """樹裡只有一支 `register("core", NEXT, …)`：wip ⇒ 准；MOTRIX_TRAIN=1、platform、prod 標籤 ⇒ 找到它（守門紅）。"""
    (grepo / "backend" / "core").mkdir(parents=True)
    (grepo / "backend" / "core" / "migrations.py").write_text('register("core", 1, _a)\nregister("core", NEXT, _b)\n',
                                                             encoding="utf-8")
    _g(grepo, "add", "-A")
    _g(grepo, "commit", "-q", "-m", "next")
    want = ['backend/core/migrations.py：register("core", NEXT,']
    assert forbidden_placeholders(grepo, {})[::2] == (True, [])
    assert forbidden_placeholders(grepo, {"MOTRIX_TRAIN": "1"})[::2] == (False, want)
    _g(grepo, "checkout", "-q", "-b", "platform")
    assert forbidden_placeholders(grepo, {})[::2] == (False, want)
    _g(grepo, "checkout", "-q", "--detach")
    _g(grepo, "tag", "prod/sim")
    assert forbidden_placeholders(grepo, {})[::2] == (False, want)


def test_rc_find_placeholders_sees_all_four_kinds(tmp_path):
    root = tmp_path / "t"
    (root / "backend" / "modules" / "m").mkdir(parents=True)
    (root / "backend" / "core").mkdir(parents=True)
    (root / "backend" / "tests" / "platform").mkdir(parents=True)
    (root / "backend" / "modules" / "m" / "CHANGELOG.md").write_text("# m\n\n## 1.0.0 — d\n", encoding="utf-8")
    (root / "backend" / "core" / "CHANGELOG.md").write_text("# c\n\n## 1.2 — d\n", encoding="utf-8")
    (root / "backend" / "version_manifest.json").write_text(json.dumps([{"module": "m", "version": "2026-09-30a"}]), encoding="utf-8")
    (root / "backend" / "tests" / "platform" / "l1_interface_snapshot.json").write_text('{"core_version": "1.2"}', encoding="utf-8")
    (root / "backend" / "core" / "migrations.py").write_text(
        '"""說明：register("core", NEXT, fn) 是佔位"""\n_P = []  # register("core", NEXT, fn)\nregister("core", 1, _a)\n',
        encoding="utf-8")
    assert VS.find_placeholders(root) == [], "正對照：沒有佔位（docstring／註解提到的不算）"
    (root / "backend" / "modules" / "m" / "CHANGELOG.md").write_text("# m\n\n## (next) — d\n\n## 1.0.0 — d\n", encoding="utf-8")
    (root / "backend" / "core" / "CHANGELOG.md").write_text("# c\n\n## (next:major) — d\n\n## 1.2 — d\n", encoding="utf-8")
    (root / "backend" / "version_manifest.json").write_text(json.dumps([{"module": "m", "version": "next"}]), encoding="utf-8")
    (root / "backend" / "tests" / "platform" / "l1_interface_snapshot.json").write_text('{"core_version": "next"}', encoding="utf-8")
    with open(root / "backend" / "core" / "migrations.py", "a", encoding="utf-8") as f:
        f.write('register("core", NEXT, _b)\n')
    found = VS.find_placeholders(root)
    assert len(found) == 5, found
    for part in ("modules/m/CHANGELOG.md", "core/CHANGELOG.md", "version=next", "core_version=next", "migrations.py"):
        assert any(part in x for x in found), (part, found)


# ── ④ core migration 的 NEXT（runtime）─────────────────────────────────────

@pytest.fixture
def iso(monkeypatch):
    monkeypatch.setattr(migrations, "_REGISTRY", {})
    monkeypatch.setattr(migrations, "_INCOMPLETE", {})
    monkeypatch.setattr(migrations, "_PENDING", [])


def _db(path):
    import db
    conn = sqlite3.connect(str(path))
    db._ensure_module_schema_versions(conn)
    return conn


def test_next_runs_after_numbered_every_time_and_never_records_a_version(tmp_path, iso, caplog):
    order = []
    migrations.register("core", 1, lambda c: order.append("v1"))
    migrations.register("core", migrations.NEXT, lambda c: order.append("next"))
    assert migrations.registered() == {"core": [1]}, "NEXT 不出現在已登記的版號裡"
    conn = _db(tmp_path / "m.db")
    try:
        with caplog.at_level(logging.WARNING, logger="motrix.migrations"):
            migrations.run_all(conn)
        assert order == ["v1", "next"]
        assert migrations.current_version(conn, "core") == 1, "佔位不記版號（資料庫裡只出現列車定的連續整數）"
        assert any("未取號" in r.getMessage() for r in caplog.records)
        migrations.run_all(conn)
        assert order == ["v1", "next", "next"], "每次重跑（靠冪等）；已記版號的 v1 不重跑"
    finally:
        conn.close()


def test_next_that_cannot_finish_is_incomplete(tmp_path, iso):
    migrations.register("core", 1, lambda c: None)
    migrations.register("core", migrations.NEXT, lambda c: "依賴的表還不在")
    conn = _db(tmp_path / "m.db")
    try:
        migrations.run_all(conn)
        assert migrations.incomplete(str(tmp_path / "m.db")) == {"core": (2, "依賴的表還不在")}
        assert migrations.current_version(conn, "core") == 1
    finally:
        conn.close()


def test_rc_next_is_core_only_and_numbered_behaviour_is_unchanged(tmp_path, iso):
    with pytest.raises(ValueError, match="只給 core"):
        migrations.register("zz_mod", migrations.NEXT, lambda c: None)
    hits = []
    migrations.register("core", 1, lambda c: hits.append(1))
    conn = _db(tmp_path / "m.db")
    try:
        migrations.run_all(conn)
        migrations.run_all(conn)
        assert hits == [1] and migrations.current_version(conn, "core") == 1, "沒有佔位時照舊：跑一次、記版號"
    finally:
        conn.close()


def test_real_core_migrations_have_no_duplicate_numbers():
    """真實 core migration：已編號的從 1 連續（列車取號後）；NEXT 只在准的地方出現（①另守）。"""
    import importlib
    src = (VS.ROOT / "backend" / "core" / "migrations.py").read_text(encoding="utf-8")
    nums = [int(n) for n in re.findall(r"""^register\(\s*["']core["']\s*,\s*(\d+)\s*,""", src, re.M)]
    assert nums and sorted(nums) == list(range(1, len(nums) + 1)), nums
    assert importlib.import_module("core.migrations").NEXT == "NEXT"
