# -*- coding: utf-8 -*-
"""tools/platform/core_major_bump.py：核心大版本升級工具＋守門（T86；核心升主版號時所有模組 `core` 範圍都要一起放寬）。

守的事：
① 放寬只動上限、下限與 `version` 不動；放寬後的範圍被載入器 `core_compatible` 與模組更新 `_core_ok` 接受（新、舊核心都行）。
② 預演不寫檔；真的做會寫 module.json＋各模組／核心 CHANGELOG（沿用檔案換行與 BOM），寫出的 `## (next)` 段落列車取號認得；重跑不再改。
③ 模組測試紅、L1 相容檢查不過、有要人工處理的範圍 ⇒ 拒絕且**一個檔都不改**。
④ 守門：核心要升主版號（`(next:major)` 或 L1 介面需要主版號）而範圍還沒接受下一個主版號，或目前 CORE_VERSION 超出某模組範圍 ⇒ 明確失敗並指到本工具。
⑤ 真實的樹：每個 module.json 的 core 範圍都接受目前 CORE_VERSION，工具改得動每一份 module.json，`check` 通過。
"""
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CMB = _load("_core_major_bump", "tools/platform/core_major_bump.py")
TN = _load("_train_number_for_cmb", "tools/platform/train_number.py")


@pytest.fixture(autouse=True)
def _no_default_base(monkeypatch):
    """合成樹放在樹內暫存目錄下，會解析到外層 repo 的 origin/platform；預設基準改指向不存在的 ref，讓測試不依賴外層 repo。
    要測預設基準的測試自己改回 "origin/platform"（在它自己建的 git repo 裡）。"""
    monkeypatch.setattr(CMB, "DEFAULT_BASE", "refs/none/none")


# ── 合成樹 ──────────────────────────────────────────────────────────────

def _tree(tmp_path, core="1.5", modules=None, core_changelog_head="", nl="\n", bom=False):
    modules = modules if modules is not None else {"a": ">=1.0,<2.0", "b": ">=1.2,<2.0"}
    (tmp_path / "backend" / "core").mkdir(parents=True)
    (tmp_path / "backend" / "core" / "registry.py").write_text('CORE_VERSION = "%s"\n' % core, encoding="utf-8")
    (tmp_path / "backend" / "core" / "CHANGELOG.md").write_text(
        "# L0／L1 底層 更新紀錄\n\n%s## %s — 2026-11-01\n- 舊\n" % (core_changelog_head, core), encoding="utf-8")
    for key, spec in modules.items():
        d = tmp_path / "backend" / "modules" / key
        d.mkdir(parents=True)
        mj = ('{' + nl + '  "key": "%s",' + nl + '  "version": "1.0.3",' + nl + '  "core": "%s",' + nl +
              '  "customization": {"fields": {"x": {"core": true}}}' + nl + '}' + nl) % (key, spec)
        (d / "module.json").write_bytes((b"\xef\xbb\xbf" if bom else b"") + mj.encode("utf-8"))
        (d / "CHANGELOG.md").write_bytes(("# %s 更新紀錄%s%s## 1.0.3 — 2026-10-01%s- 舊%s" % (key, nl, nl, nl, nl)).encode("utf-8"))
    return tmp_path


def _snapshot_of(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def _ok_runner(root, keys):
    return []


# ── ① 範圍放寬 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("spec,target,expect", [
    (">=1.0,<2.0", 2, ">=1.0,<3.0"),
    (">=1.155,<2.0", 2, ">=1.155,<3.0"),
    (">=1.0,<=1.99", 2, ">=1.0,<3.0"),
    (">=1.0,<3.0", 2, ">=1.0,<3.0"),          # 已經接受 ⇒ 不動
    (">=1.0,<2.5", 2, ">=1.0,<2.5"),          # 2.0 已在範圍內 ⇒ 不動（不要硬改成 <3.0）
    (">=1.0,<=2.5", 2, ">=1.0,<=2.5"),
    (">=1.0,<4.0", 2, ">=1.0,<4.0"),
    (">=1.0", 2, ">=1.0"),                    # 沒有上限 ⇒ 本來就接受
    (">=2.0,<3.0", 2, ">=2.0,<3.0"),
    (">=1.0,<3.0", 3, ">=1.0,<4.0"),          # 連續兩次大版本
])
def test_relax_spec_only_moves_the_upper_bound(spec, target, expect):
    new, why = CMB.relax_spec(spec, target)
    assert (new, why) == (expect, None)


def test_relax_spec_refuses_pins_and_empty():
    assert CMB.relax_spec("==1.0", 2)[1]
    assert CMB.relax_spec("", 2)[1]


@pytest.mark.parametrize("version,ok", [("1.0", True), ("1.168", True), ("2.0", True), ("2.9", True), ("3.0", False)])
def test_relaxed_range_is_accepted_by_loader_and_module_update(version, ok):
    from core.loader import core_compatible
    spec = CMB.relax_spec(">=1.0,<2.0", 2)[0]
    assert core_compatible(spec, version) is ok
    mu = _load("_module_update_for_cmb", "tools/platform/module_update.py")
    assert mu._core_ok(spec, version) is ok


def test_old_range_is_what_blocks_the_major_bump():
    """反向控制：沒放寬時 2.0 一到，載入器判不相容（這就是要這支工具的原因）。"""
    from core.loader import core_compatible
    assert core_compatible(">=1.0,<2.0", "1.168") is True
    assert core_compatible(">=1.0,<2.0", "2.0") is False


# ── ② 預演／真的做／冪等 ─────────────────────────────────────────────────

def test_dry_run_writes_nothing_and_exit_is_3(tmp_path):
    root = _tree(tmp_path)
    before = _snapshot_of(root)
    lines = []
    assert CMB.apply(root, dry_run=True, skip_tests=True, out=lines.append) == 3
    assert _snapshot_of(root) == before
    text = "\n".join(lines)
    assert ">=1.0,<3.0" in text and "沒有寫任何檔" in text


@pytest.mark.parametrize("nl,bom", [("\n", False), ("\r\n", False), ("\n", True)])
def test_apply_rewrites_only_the_core_line_and_keeps_newlines_and_bom(tmp_path, nl, bom):
    root = _tree(tmp_path, nl=nl, bom=bom)
    before = {k: v for k, v in _snapshot_of(root).items() if k.endswith("module.json")}
    assert CMB.apply(root, skip_tests=False, runner=_ok_runner, today="2026-11-14", out=lambda *_: None, force=True) == 0
    for key, spec in (("a", ">=1.0,<3.0"), ("b", ">=1.2,<3.0")):
        p = root / "backend" / "modules" / key / "module.json"
        raw = p.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf") is bom
        text = raw.decode("utf-8-sig")
        assert json.loads(text)["core"] == spec
        assert json.loads(text)["version"] == "1.0.3", "version 由列車取，工具不能動"
        assert '"customization": {"fields": {"x": {"core": true}}}' in text, "別處的 core 不能被誤改"
        old = before["backend/modules/%s/module.json" % key].decode("utf-8-sig")
        assert len(old.splitlines()) == len(text.splitlines())
        assert text.count("\r\n") == old.count("\r\n")


def test_apply_writes_changelog_sections_that_the_train_numbering_understands(tmp_path):
    root = _tree(tmp_path)
    CMB.apply(root, skip_tests=True, today="2026-11-14", out=lambda *_: None, force=True)
    mod_cl = (root / "backend" / "modules" / "a" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert mod_cl.splitlines()[2].startswith("## (next) — 2026-11-14（core-major-bump")
    assert ">=1.0,<2.0" in mod_cl and ">=1.0,<3.0" in mod_cl and "## 1.0.3 — 2026-10-01" in mod_cl
    new, top, changes = TN.assign_changelog(mod_cl, (1, 0, 3), 3)           # 列車取號：下一個修正號
    assert top == (1, 0, 4) and "## 1.0.4 — 2026-11-14" in new
    core_cl = (root / "backend" / "core" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert core_cl.splitlines()[2].startswith("## (next) — 2026-11-14（core-major-bump") and "2 個模組" in core_cl
    new, top, _ = TN.assign_changelog(core_cl, (1, 5), 2, default_level="minor")
    assert top == (1, 6)


def test_apply_is_idempotent(tmp_path):
    root = _tree(tmp_path)
    assert CMB.apply(root, skip_tests=True, out=lambda *_: None, force=True) == 0
    after_first = _snapshot_of(root)
    lines = []
    assert CMB.apply(root, skip_tests=True, out=lines.append, force=True) == 0
    assert _snapshot_of(root) == after_first
    assert "不用改" in "\n".join(lines)
    assert CMB.apply(root, skip_tests=True, out=lambda *_: None) == 0           # 沒 --force 也一樣：已經放寬 ⇒ 不用改（不是拒絕）
    assert _snapshot_of(root) == after_first


def test_dry_run_last_line_does_not_promise_a_next_step_that_would_be_refused(tmp_path):
    lines = []
    assert CMB.apply(_tree(tmp_path), dry_run=True, skip_tests=True, out=lines.append) == 3
    assert "真的執行要加 --force" in lines[-1] and "確認後執行" not in lines[-1]
    lines2 = []
    root2 = _tree(tmp_path / "p", core_changelog_head="## (next:major) — 2026-11-14（分支）\n- x\n\n") if (tmp_path / "p").mkdir() is None else None
    assert CMB.apply(root2, dry_run=True, skip_tests=True, out=lines2.append) == 3
    assert "確認後執行 `apply`" in lines2[-1]


@pytest.mark.parametrize("spec", [">=3.0,<4.0", ">=abc,<2.0"])
def test_range_that_cannot_be_fixed_by_widening_is_reported_not_silently_ok(tmp_path, spec):
    """F2：下限高於目標／看不懂的範圍，不可以被當成「已經接受」而印不用改。"""
    root = _tree(tmp_path, modules={"a": ">=1.0,<2.0", "odd": spec})
    before = _snapshot_of(root)
    lines = []
    assert CMB.apply(root, skip_tests=True, out=lines.append, force=True) == 1
    assert _snapshot_of(root) == before
    text = "\n".join(lines)
    assert "odd" in text and "要人工處理" in text and "不用改" not in text


def test_guard_hint_uses_the_platform_venv_interpreter_like_the_doc():
    hint = "\n".join(CMB.guard_problems("2.0", {"a": ">=1.0,<2.0"}, major_pending=False))
    assert r"D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe tools/platform/core_major_bump.py apply" in hint


def test_status_prints_a_summary_line_when_the_current_core_is_rejected(tmp_path, capsys):
    root = _tree(tmp_path, core="2.0")
    assert CMB.main(["status", "--root", str(root)]) == 0
    assert "✗ 2 個模組不接受目前核心 2.0" in capsys.readouterr().out


def test_apply_without_force_refuses_when_no_major_is_pending(tmp_path):
    root = _tree(tmp_path)
    before = _snapshot_of(root)
    lines = []
    assert CMB.apply(root, skip_tests=True, out=lines.append) == 1
    assert _snapshot_of(root) == before
    assert "--force" in "\n".join(lines)


def test_recovery_when_core_is_already_the_new_major(tmp_path):
    """核心已經是 2.0 才發現範圍沒放寬 ⇒ 預設目標＝目前主版號 2.0（不跳到 3.0），不需要 --force。"""
    root = _tree(tmp_path, core="2.0")
    lines = []
    assert CMB.apply(root, skip_tests=True, out=lines.append, today="2026-11-14") == 0
    assert "補救" in "\n".join(lines)
    for key in ("a", "b"):
        assert json.loads((root / "backend" / "modules" / key / "module.json").read_text(encoding="utf-8"))["core"].endswith("<3.0")


def test_only_modules_that_need_it_are_touched(tmp_path):
    root = _tree(tmp_path, modules={"a": ">=1.0,<2.0", "ok": ">=1.0,<3.0"})
    before_ok = {k: v for k, v in _snapshot_of(root).items() if "/ok/" in k}
    CMB.apply(root, skip_tests=True, out=lambda *_: None, force=True)
    assert {k: v for k, v in _snapshot_of(root).items() if "/ok/" in k} == before_ok


# ── ③ 拒絕時一個檔都不改 ─────────────────────────────────────────────────

def test_failing_module_tests_refuse_and_change_nothing(tmp_path):
    root = _tree(tmp_path)
    before = _snapshot_of(root)
    lines = []
    assert CMB.apply(root, runner=lambda r, keys: [("b", "1 failed")], out=lines.append, force=True) == 1
    assert _snapshot_of(root) == before
    assert "模組 b 測試未過" in "\n".join(lines)


def test_unfixable_range_is_reported_and_blocks_everything(tmp_path):
    root = _tree(tmp_path, modules={"a": ">=1.0,<2.0", "pinned": "==1.5"})
    before = _snapshot_of(root)
    lines = []
    assert CMB.apply(root, skip_tests=True, out=lines.append, force=True) == 1
    assert _snapshot_of(root) == before
    assert "pinned" in "\n".join(lines) and "人工" in "\n".join(lines)


def test_target_not_above_current_major_is_refused(tmp_path):
    root = _tree(tmp_path)
    assert CMB.apply(root, target_major=1, skip_tests=True, out=lambda *_: None) == 1


def test_l1_names_still_used_by_a_module_block_the_bump(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    mod = root / "backend" / "modules" / "a"
    (mod / "api.py").write_text("from helpers.legacy import old_fn\n\ndef f():\n    return old_fn()\n", encoding="utf-8")
    monkeypatch.setattr(CMB, "l1_diff", lambda r, base=None: ([], [], ["helper:legacy::old_fn"]))
    before = _snapshot_of(root)
    lines = []
    assert CMB.apply(root, skip_tests=True, out=lines.append, force=True) == 1
    assert _snapshot_of(root) == before
    assert "modules/a/api.py: helpers.legacy.old_fn" in "\n".join(lines)


def test_default_base_is_origin_platform_and_catches_a_removed_name_without_base_arg(tmp_path, monkeypatch):
    """F1 真實路徑：不給 --base，工具自己用 origin/platform 的快照比；基準快照有 helper:x::old_fn、目前介面沒有、模組還在 import ⇒ 拒絕。
    （舊作法拿樹內快照當基準，永遠比出空差異，這個檢查形同虛設。）"""
    import subprocess
    root = _tree(tmp_path)
    (root / "backend" / "modules" / "a" / "api.py").write_text("from helpers.x import old_fn\n", encoding="utf-8")
    snap = root / CMB.SNAPSHOT
    snap.parent.mkdir(parents=True)
    snap.write_text(json.dumps({"interface": {"helper:x::old_fn": "def()", "helper:x::kept": "def()"}}), encoding="utf-8")

    def git(*a):
        subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)

    git("init", "-q")
    git("add", CMB.SNAPSHOT)
    git("commit", "-q", "-m", "base")
    git("update-ref", "refs/remotes/origin/platform", "HEAD")
    snap.write_text(json.dumps({"interface": {"helper:x::kept": "def()"}}), encoding="utf-8")        # 樹內快照＝目前介面（列車規則）

    class FakeL1:
        @staticmethod
        def current_interface():
            return {"helper:x::kept": "def()"}

        @staticmethod
        def diff(base, cur):
            return [], [], [k for k in base if k not in cur]

    monkeypatch.setattr(CMB, "_l1_module", lambda r: FakeL1)
    monkeypatch.setattr(CMB, "DEFAULT_BASE", "origin/platform")
    lines = []
    before = _snapshot_of(root)
    before.pop(".git", None)
    assert CMB.apply(root, skip_tests=True, out=lines.append) == 1
    text = "\n".join(lines)
    assert "modules/a/api.py: helpers.x.old_fn" in text
    assert "沒給" not in text
    after = {k: v for k, v in _snapshot_of(root).items() if not k.startswith(".git/")}
    assert after == {k: v for k, v in before.items() if not k.startswith(".git/")}, "拒絕時一個檔都不改"
    assert CMB.main(["check", "--root", str(root)]) == 1                               # check 也看得到「這包要升主版號」且範圍沒處理


def test_missing_base_says_the_l1_check_was_not_done(tmp_path):
    """基準找不到時不能默默當成通過：要明印「L1 相容檢查未做」。"""
    root = _tree(tmp_path, core_changelog_head="## (next:major) — 2026-11-14（分支）\n- x\n\n")
    lines = []
    assert CMB.apply(root, skip_tests=True, dry_run=True, out=lines.append) == 3
    text = "\n".join(lines)
    assert "L1 相容檢查未做" in text and "結束碼 3 是正常的" in text


def test_explicit_base_that_does_not_resolve_is_an_error(tmp_path):
    root = _tree(tmp_path)
    lines = []
    assert CMB.apply(root, skip_tests=True, base="no-such-ref", out=lines.append) == 1
    assert "找不到 --base no-such-ref" in "\n".join(lines)
    assert CMB.main(["check", "--root", str(root), "--base", "no-such-ref"]) == 1


def test_unknown_unit_kinds_are_reported_not_silently_skipped():
    assert CMB.unknown_units({"helper:x": {"a"}, "weird:y": {"b"}}) == ["weird:y"]


def test_scan_module_uses_finds_imports_and_attributes_but_not_tests_or_other_names(tmp_path):
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "tests").mkdir()
    (tmp_path / "m" / "x.py").write_text(
        "import helpers.legacy as L\nfrom helpers import legacy as L2, other\nfrom helpers.legacy import gone, kept\n"
        "def f():\n    return L.gone(), L2.changed, other.thing, kept\n", encoding="utf-8")
    (tmp_path / "m" / "tests" / "test_x.py").write_text("from helpers.legacy import gone\n", encoding="utf-8")
    (tmp_path / "m" / "clean.py").write_text("from helpers.legacy import kept\n", encoding="utf-8")
    hits = CMB.scan_module_uses(tmp_path, CMB.breaking_names(["helper:legacy::changed  def(a) → def(a, b)"], ["helper:legacy::gone"]))
    assert hits == ["modules/m/x.py: helpers.legacy.changed", "modules/m/x.py: helpers.legacy.gone"]


def test_scan_module_uses_more_import_shapes(tmp_path):
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "star.py").write_text("from helpers.legacy import *\n", encoding="utf-8")
    (tmp_path / "m" / "bare.py").write_text("import helpers.legacy\n\ndef f():\n    return helpers.legacy.gone()\n", encoding="utf-8")
    (tmp_path / "m" / "pkg.py").write_text("import helpers\n\ndef f():\n    return helpers.gone\n", encoding="utf-8")
    (tmp_path / "m" / "reexport.py").write_text("from helpers import gone\n", encoding="utf-8")
    (tmp_path / "m" / "clean.py").write_text("import helpers\nfrom helpers.legacy import kept\n\ndef f():\n    return helpers.other, kept\n", encoding="utf-8")
    hits = CMB.scan_module_uses(tmp_path, CMB.breaking_names([], ["helper:legacy::gone"]))
    assert sorted(hits) == ["modules/m/bare.py: helpers.legacy.gone", "modules/m/pkg.py: helpers.gone",
                            "modules/m/reexport.py: helpers.gone", "modules/m/star.py: helpers.legacy.*（import *）"]


def test_breaking_names_counts_members_as_their_class():
    got = CMB.breaking_names(["helper:h::Klass.method  def(a) → def(a, b)"], ["core:archive::_gone", "helper:h::Klass.other"])
    assert got == {"helper:h": {"Klass"}, "core:archive": {"_gone"}}


# ── ④ 守門 ──────────────────────────────────────────────────────────────

def test_guard_fails_when_major_is_pending_and_ranges_are_not_ready():
    probs = CMB.guard_problems("1.168", {"stale_one": ">=1.0,<2.0", "stale_two": ">=1.0,<2.0", "fresh_one": ">=1.0,<3.0"}, major_pending=True)
    text = "\n".join(probs)
    assert "stale_one、stale_two" in text and "fresh_one" not in text and "2.0" in text
    assert "core_major_bump.py apply" in text, "訊息要指到工具，不能只說失敗"
    assert len(probs) == 2, "同一個範圍的模組併成一行（＋最後一行指到工具），不要一個模組一行"


def test_guard_is_quiet_when_ranges_are_ready_or_no_major_is_pending():
    assert CMB.guard_problems("1.168", {"a": ">=1.0,<3.0"}, major_pending=True) == []
    assert CMB.guard_problems("1.168", {"a": ">=1.0,<2.0"}, major_pending=False) == []


def test_guard_fails_when_current_core_is_outside_a_range():
    """核心已經是 2.0（例如列車取號之後）而範圍沒放寬 ⇒ 不能等到啟動時 404 才發現。"""
    probs = CMB.guard_problems("2.0", {"a": ">=1.0,<2.0"}, major_pending=False)
    assert probs and "與目前核心 2.0 不相容" in probs[0] and "core_major_bump.py" in "\n".join(probs)


def test_check_cli_flags_next_major_placeholder_then_passes_after_apply(tmp_path, capsys):
    root = _tree(tmp_path, core_changelog_head="## (next:major) — 2026-11-14（分支）\n- 刪了 L1 名稱\n\n")
    assert CMB.main(["check", "--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "core_major_bump.py apply" in out
    assert CMB.main(["apply", "--root", str(root), "--skip-tests"]) == 0
    capsys.readouterr()
    assert CMB.main(["check", "--root", str(root)]) == 0
    assert "OK：核心這包要升主版號" in capsys.readouterr().out


def test_check_cli_prints_ok_without_a_pending_major(tmp_path, capsys):
    root = _tree(tmp_path)
    assert CMB.main(["check", "--root", str(root)]) == 0
    assert "OK：" in capsys.readouterr().out


def test_status_cli_lists_every_module(tmp_path, capsys):
    root = _tree(tmp_path)
    assert CMB.main(["status", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "核心 1.5" in out and "a " in out and "b " in out
    assert "目前核心 1.5" in out and "下一個主版號 2.0" in out and "不相容" in out, "要有欄名與圖例，不只是一排「相容」"


# ── ⑤ 真實的樹 ──────────────────────────────────────────────────────────

def test_every_real_module_range_accepts_the_current_core_version():
    from core import registry
    specs = {k: s for k, (_, s) in CMB.module_specs(REPO).items()}
    assert len(specs) >= 10, specs
    bad = {k: s for k, s in specs.items() if not CMB.compatible(s, registry.CORE_VERSION)}
    assert not bad, "這些模組的 core 範圍不接受目前核心 %s：%s ⇒ %s" % (registry.CORE_VERSION, bad, CMB.HINT)


def test_real_check_passes_without_a_pending_major(monkeypatch):
    """（不依賴外層 repo 的 origin/platform：DEFAULT_BASE 已由 autouse 夾具指到不存在的 ref，只看樹內 CHANGELOG 佔位與範圍。）"""
    assert CMB.main(["check", "--root", str(REPO)]) == 0


def test_tool_can_rewrite_every_real_module_json_in_memory():
    """正對照：真實 module.json 都找得到唯一的頂層 core 行、改完仍是合法 JSON、其餘不變（不寫檔）。"""
    n = 0
    for key, (mj, spec) in CMB.module_specs(REPO).items():
        text, _ = CMB._read(mj)
        new = CMB.rewrite_module_json(text, CMB.relax_spec(spec, 2)[0])
        a, b = json.loads(text), json.loads(new)
        assert b.pop("core") == CMB.relax_spec(spec, 2)[0] and a.pop("core") == spec and a == b, key
        n += 1
    assert n >= 10


def test_real_dry_run_does_not_touch_the_tree():
    import subprocess
    before = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "backend/modules", "backend/core"],
                            capture_output=True, text=True).stdout
    code = CMB.apply(REPO, dry_run=True, skip_tests=True, out=lambda *_: None)
    after = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", "backend/modules", "backend/core"],
                           capture_output=True, text=True).stdout
    assert code in (0, 3) and before == after


# ── ④ 守門接到列車取號（train_number.plan）──────────────────────────────

from tests.platform import test_train_number as TT          # noqa: E402  合成列車樹的夾具
from tests.platform.test_train_number import train          # noqa: E402,F401


def _set_core_range(root, spec):
    p = root / "backend" / "modules" / "m" / "module.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["core"] = spec
    p.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8", newline="\n")


def test_assign_fails_clearly_when_core_goes_major_but_ranges_are_not_relaxed(train, monkeypatch, capsys):
    _set_core_range(train, ">=1.0,<2.0")
    monkeypatch.setattr(TT.TN, "_need_major", lambda tree: (True, None))
    before = {p: p.read_bytes() for p in train.rglob("*") if p.is_file() and ".git" not in p.parts}
    assert TT._run(train, "assign") == 1
    out = capsys.readouterr().out
    assert "core_major_bump.py apply" in out and "1 個模組的 core 範圍" in out and "：m" in out
    assert before == {p: p.read_bytes() for p in train.rglob("*") if p.is_file() and ".git" not in p.parts}, "失敗時一個檔都不寫"
    assert TT._run(train, "--check") == 1


def test_assign_goes_through_once_ranges_accept_the_new_major(train, monkeypatch):
    _set_core_range(train, ">=1.0,<3.0")
    monkeypatch.setattr(TT.TN, "_need_major", lambda tree: (True, None))
    assert TT._run(train, "assign") == 0
    assert 'CORE_VERSION = "2.0"' in (train / "backend/core/registry.py").read_text(encoding="utf-8")


def test_assign_without_a_major_need_ignores_the_ranges(train, monkeypatch):
    """T86 這種不升主版號的列車：範圍維持 <2.0 照常取號（守門不誤傷）。"""
    _set_core_range(train, ">=1.0,<2.0")
    monkeypatch.setattr(TT.TN, "_need_major", lambda tree: (False, None))
    assert TT._run(train, "assign") == 0
    assert 'CORE_VERSION = "1.71"' in (train / "backend/core/registry.py").read_text(encoding="utf-8")
