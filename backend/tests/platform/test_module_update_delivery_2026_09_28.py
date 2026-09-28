"""B55 S3：module_update 上線所需（設計 docs/platform/MODULE-UPDATE-DELIVERY.md §1.1、§1.3 步驟 7、§3）。

- ship：P→X 不是只改這個模組 ⇒ 拒絕（必須完整包）；是 ⇒ lock 記 prod_base、tier、version_manifest 條目
- preflight：正式機基準 commit、授權、同一版（雜湊相同）
- apply／rollback：鏡像（新版刪掉的檔不留）、baseline 片段、version_manifest 文字插入、覆蓋紀錄；回滾三個狀態檔逐位元組還原
- CLI --json：給 apply_module_update.ps1 解析的一行
"""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from tests._requires import requires_module  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("_module_update_b55", REPO / "tools" / "platform" / "module_update.py")
MU = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MU)

PAGES_DIR = "frontend/" + "pages"      # 合成 repo 的頁面目錄（資料，不是讀 repo 的頁面）


@pytest.fixture(autouse=True)
def _licensed(monkeypatch):
    monkeypatch.setattr(MU, "_license_check", lambda manifest: (True, ""))


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout.decode().strip()


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


MANIFEST_V1 = '[\n  {"module": "其他", "version": "2026-09-01a", "date": "2026-09-01", "time": "10:00", "content": "舊"}\n]\n'


def _module(repo, version, extra_files=None, name="測試模組"):
    m = repo / "backend" / "modules" / "zz"
    _write(m / "module.json", json.dumps({"key": "zz", "name": name, "version": version, "core": ">=1.0,<2.0",
                                          "pages": [{"path": "zz.html"}]}))
    _write(m / "api.py", "VERSION = %r\n" % version)
    for rel, text in (extra_files or {}).items():
        _write(m / rel, text)
    _write(repo / PAGES_DIR / "zz.html", "<p>%s</p>\n" % version)


@pytest.fixture()
def src(tmp_path):
    r = tmp_path / "src"
    _write(r / "backend" / "core" / "registry.py", 'CORE_VERSION = "1.2"\n')
    _write(r / "backend" / "version_manifest.json", MANIFEST_V1)
    _module(r, "1.0.0", {"old_only.py": "X = 1\n"})
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _commit(r, "v1")
    return r


def _commit(r, msg):
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", msg)
    return _git(r, "rev-parse", "HEAD")


def _install(tmp_path, commit, src=None):
    """合成安裝目錄：等同從 commit 做完整包（模組 zz 已在）＋部署標記＋baseline＋version_manifest。"""
    root = tmp_path / "install"
    _write(root / "backend" / "core" / "registry.py", 'CORE_VERSION = "1.2"\n')
    _write(root / PAGES_DIR / "index.html", "home\n")
    _write(root / "backend" / "version_manifest.json", MANIFEST_V1)
    _write(root / "backend" / ".deployed_commit.json", "﻿" + json.dumps({"commit": commit}))   # PS 5.1 會寫 BOM
    files = ["backend/core/registry.py", PAGES_DIR + "/index.html"]
    if src is not None:
        pkg = MU.build("zz", tmp_path / "base", commit=commit, repo=src)
        (root / "backend" / "modules").mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copytree(pkg / "backend" / "modules" / "zz", root / "backend" / "modules" / "zz")
        shutil.copy2(pkg / PAGES_DIR / "zz.html", root / PAGES_DIR / "zz.html")
        files += sorted(MU._tree_hashes(root, "zz"))
        entry = json.loads((pkg / MU.LOCK_NAME).read_text(encoding="utf-8"))["modules"]["zz"]
        mods = {"zz": entry}
    else:
        mods = {}
    _write(root / "backend" / "modules.lock.json",
           json.dumps({"lock_version": 1, "kind": "full_package", "product": "full", "core_version": "1.2",
                       "modules": mods, "excluded": []}))
    _write(root / "backend" / ".deployed_files.json", json.dumps({"commit": commit, "files": files}))
    return root


def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
            if p.is_file() and "module_backups" not in p.parts}


def _v2(src):
    """v2：刪掉 old_only.py、加 new.py、改頁面、version_manifest 加一筆本模組條目。"""
    (src / "backend" / "modules" / "zz" / "old_only.py").unlink()
    _module(src, "1.1.0", {"new.py": "Y = 2\n"})
    text = (src / "backend" / "version_manifest.json").read_text(encoding="utf-8")
    line = '  {"module": "測試模組", "version": "2026-09-28z", "date": "2026-09-28", "time": "12:00", "content": "新"},\n'
    (src / "backend" / "version_manifest.json").write_text("[\n" + line + text[2:], encoding="utf-8")
    return _commit(src, "v2")


# ── ship ─────────────────────────────────────────────────────────────────

def test_ship_records_base_tier_and_manifest_line(src, tmp_path):
    p = _git(src, "rev-parse", "HEAD")
    x = _v2(src)
    pkg = MU.ship("zz", tmp_path / "out", p, x, run_tests=False, repo=src)
    lock = MU.load_pkg(pkg)
    assert lock["prod_base_commit"] == p and lock["tier"] == "module" and lock["built_from"] == x
    assert [json.loads(l)["version"] for l in lock["manifest_lines"]] == ["2026-09-28z"]
    assert MU.check(pkg) == []


def test_ship_refuses_when_anything_outside_the_module_changed(src, tmp_path):
    p = _git(src, "rev-parse", "HEAD")
    _v2(src)
    _write(src / "backend" / "core" / "registry.py", 'CORE_VERSION = "1.2"\n# 改 L0 一行\n')
    x = _commit(src, "touch core")
    with pytest.raises(MU.UpdateError, match="必須完整包"):
        MU.ship("zz", tmp_path / "out", p, x, run_tests=False, repo=src)
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").iterdir()), "拒絕時不可以留下包"


def test_ship_with_tests_requires_working_tree_at_x(src, tmp_path):
    p = _git(src, "rev-parse", "HEAD")
    x = _v2(src)
    _write(src / "backend" / "modules" / "zz" / "api.py", "DIRTY = 1\n")      # 工作樹不是 X
    with pytest.raises(MU.UpdateError, match="工作樹必須是"):
        MU.ship("zz", tmp_path / "out", p, x, run_tests=True, repo=src)


# ── preflight：正式機基準、授權、同一版 ─────────────────────────────────────────

def _shipped(src, tmp_path):
    p = _git(src, "rev-parse", "HEAD")
    x = _v2(src)
    return p, MU.ship("zz", tmp_path / "out", p, x, run_tests=False, repo=src)


def _refused(root, pkg, match, **kw):
    snap = _snapshot(root)
    with pytest.raises(MU.UpdateError, match=match):
        MU.apply(root, pkg, **kw)
    assert _snapshot(root) == snap, "被拒絕時安裝目錄不可以有任何改動"


def test_rc_package_made_for_another_prod_commit_is_refused(src, tmp_path):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, "0" * 40, src=None)
    _refused(root, pkg, "是對正式機")


def test_rc_missing_deployed_marker_is_refused(src, tmp_path):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    (root / "backend" / ".deployed_commit.json").unlink()
    _refused(root, pkg, "判不了")


def test_rc_require_base_refuses_package_without_base(src, tmp_path):
    p = _git(src, "rev-parse", "HEAD")
    root = _install(tmp_path, p)
    pkg = MU.build("zz", tmp_path / "raw", repo=src)          # 低階 build：沒有 prod_base
    _refused(root, pkg, "沒有記正式機基準", require_base=True)


def test_rc_unlicensed_module_is_refused(src, tmp_path, monkeypatch):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    monkeypatch.setattr(MU, "_license_check", lambda manifest: (False, "未授權"))
    _refused(root, pkg, "不在這台機器的授權內")


def test_rc_license_check_unavailable_is_refused(src, tmp_path, monkeypatch):
    """授權判不了（安裝目錄沒有 helpers/licensing）⇒ 不套用（不猜）。"""
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    monkeypatch.setattr(MU, "_license_check", None)
    _refused(root, pkg, "授權判不了")


def test_rc_same_content_is_refused_as_already_installed(src, tmp_path):
    p = _git(src, "rev-parse", "HEAD")
    root = _install(tmp_path, p, src=src)
    pkg = MU.build("zz", tmp_path / "same", commit=p, repo=src)
    _refused(root, pkg, "已是這一版", allow_downgrade=True)


# ── apply：鏡像、baseline、version_manifest、覆蓋紀錄 ─────────────────────────────

def test_apply_mirrors_updates_state_and_rollback_restores_bytes(src, tmp_path):
    p = _git(src, "rev-parse", "HEAD")
    root = _install(tmp_path, p, src=src)
    before = _snapshot(root)
    x = _v2(src)
    pkg = MU.ship("zz", tmp_path / "out", p, x, run_tests=False, repo=src)
    rec, bdir = MU.apply(root, pkg)
    mdir = root / "backend" / "modules" / "zz"
    assert not (mdir / "old_only.py").exists(), "鏡像：新版刪掉的檔不可以留著（DB-S6）"
    assert (mdir / "new.py").is_file()
    base = MU._read_json(root / MU.BASELINE_REL)
    assert "backend/modules/zz/new.py" in base["files"] and "backend/modules/zz/old_only.py" not in base["files"]
    assert PAGES_DIR + "/index.html" in base["files"], "baseline 其他段不可以被動到"
    man_text = (root / MU.MANIFEST_REL).read_text(encoding="utf-8")
    assert man_text.splitlines()[1].strip().startswith('{"module": "測試模組", "version": "2026-09-28z"')
    assert man_text.endswith(MANIFEST_V1[2:]), "文字插入：原本的每一行逐位元組不變"
    dm = MU._read_json(root / MU.DEPLOYED_MODULES_REL)
    assert dm["zz"]["version"] == "1.1.0" and dm["zz"]["prod_base_commit"] == p
    assert MU.overlays(root) == {"zz": dm["zz"]["sha256"]}
    MU.rollback(root, "zz")
    assert _snapshot(root) == before, "回滾後安裝目錄（含三個狀態檔、lock）逐位元組回到套用前"


def test_deployed_modules_drops_entries_of_an_older_full_package(src, tmp_path):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    _write(root / MU.DEPLOYED_MODULES_REL, json.dumps({"old": {"version": "9", "prod_base_commit": "f" * 40}}))
    MU.apply(root, pkg)
    dm = MU._read_json(root / MU.DEPLOYED_MODULES_REL)
    assert set(dm) == {"zz"}, "base 不是目前 commit 的舊條目要去掉（完整包換版後過期）"


def test_manifest_insert_is_idempotent(src, tmp_path):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    lines = MU.load_pkg(pkg)["manifest_lines"]
    assert MU._insert_manifest(root, lines) == 1
    assert MU._insert_manifest(root, lines) == 0, "同一 (module, version) 已在 ⇒ 不重複插入"


def test_rollback_with_corrupted_state_backup_stops(src, tmp_path):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    rec, bdir = MU.apply(root, pkg)
    (bdir / "state_before" / MU.BASELINE_REL).unlink()
    with pytest.raises(MU.UpdateError, match="備份已損壞"):
        MU.rollback(root, "zz")


def test_backups_are_pruned_to_keep(src, tmp_path, monkeypatch):
    p = _git(src, "rev-parse", "HEAD")
    root = _install(tmp_path, p, src=src)
    monkeypatch.setattr(MU, "BACKUP_KEEP", 2)
    for i in range(4):
        pkg = MU.build("zz", tmp_path / ("b%d" % i), repo=src)
        (root / "backend" / "modules.lock.json").write_text(json.dumps(
            {"lock_version": 1, "kind": "full_package", "modules": {}, "excluded": []}), encoding="utf-8")
        MU.apply(root, pkg, allow_downgrade=True)
    assert len(MU.backups(root, "zz")) == 2


# ── CLI --json（給 ps1 解析）──────────────────────────────────────────────────

def test_cli_json_lines(src, tmp_path, capsys):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    assert MU.main(["preflight", "--root", str(root), "--pkg", str(pkg), "--require-base", "--json"]) == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line.startswith("MODULE_UPDATE_RESULT ") and line.isascii()
    data = json.loads(line.split(" ", 1)[1])
    assert data["ok"] and data["key"] == "zz" and data["to_version"] == "1.1.0" and data["has_migrations"] is False
    assert MU.main(["apply", "--root", str(root), "--pkg", str(pkg), "--require-base", "--json"]) == 0
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1].split(" ", 1)[1])
    assert data["ok"] and data["stamp"]
    assert MU.main(["apply", "--root", str(root), "--pkg", str(pkg), "--json"]) == 2
    data = json.loads(capsys.readouterr().out.strip().splitlines()[-1].split(" ", 1)[1])
    assert data["ok"] is False and data["error"]


# ── 第②級測試閘門 ──────────────────────────────────────────────────────────────

def _mini(tmp_path, body):
    r = tmp_path / "mini"
    _write(r / "backend" / "test_mini.py", body)
    return r


def test_run_ship_tests_green(tmp_path):
    res = MU.run_ship_tests(["test_mini.py"], repo=_mini(tmp_path, "def test_a():\n    pass\n"))
    assert res["passed"] == 1 and res["failed"] == 0


@pytest.mark.parametrize("body, why", [
    ("def test_a():\n    assert False\n", "有紅"),
    ("X = 1\n", "一題都沒收到（假綠）"),
    ("import pytest\n\ndef test_a():\n    pytest.skip('x')\n", "全部略過：exit 0 而 0 passed（假綠）"),
])
def test_run_ship_tests_refuses(tmp_path, body, why):
    with pytest.raises(MU.UpdateError, match="沒有全綠"):
        MU.run_ship_tests(["test_mini.py"], repo=_mini(tmp_path, body))


def test_run_ship_tests_names_the_failures(tmp_path):
    with pytest.raises(MU.UpdateError) as ei:
        MU.run_ship_tests(["test_mini.py"], repo=_mini(tmp_path, "def test_boom():\n    assert False\n"))
    assert "test_mini.py::test_boom" in str(ei.value)


@requires_module("case", "提供者是 case（case.access）；模組不在時沒有對象")
@requires_module("netplan", "斷言消費端 netplan 的題被選到；模組不在時沒有對象")
def test_ship_tests_adds_consumers_of_a_changed_provider():
    """第②級選題（使用者裁示甲）：case 的提供者有改 ⇒ 選題含 netplan（case.access 的直接消費端）的題。"""
    import sys
    sys.path.insert(0, str(REPO / "tools" / "platform"))
    import ship_tier as ST
    src = {p.relative_to(REPO).as_posix(): p.read_text(encoding="utf-8")
           for p in (REPO / "backend").rglob("*.py") if "__pycache__" not in p.parts}
    pc = ST.provider_check(ST.Repo(src), "case", ["backend/modules/case/api/quotations.py"], policy="consumers")
    sel = MU.ship_tests("case", {"provider": pc})
    assert "tests/platform" in sel and "modules/case/tests" in sel
    assert any(s.startswith("modules/netplan/tests/") for s in sel), sel


# ── 稽核 D S3-M1：套用中途失敗 ──────────────────────────────────────────────────

def _boom(*a, **k):
    raise OSError("模擬：複製到一半失敗")


def test_first_apply_failing_midway_restores_and_leaves_no_backup(src, tmp_path, monkeypatch):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)                          # 模組原本不在
    before = _snapshot(root)
    monkeypatch.setattr(MU.shutil, "copytree", _boom)
    with pytest.raises(MU.UpdateError, match="已用本次備份還原"):
        MU.apply(root, pkg)
    assert _snapshot(root) == before, "中途失敗 ⇒ 安裝目錄回到套用前（模組不可以就此消失）"
    assert MU.backups(root, "zz") == [], "還原成功的那一份失敗備份要清掉（S3-S1）"


def test_v2_to_v3_failing_midway_stays_on_v2(src, tmp_path, monkeypatch):
    p = _git(src, "rev-parse", "HEAD")
    root = _install(tmp_path, p, src=src)
    x = _v2(src)
    MU.apply(root, MU.ship("zz", tmp_path / "o2", p, x, run_tests=False, repo=src))
    on_v2 = _snapshot(root)
    _module(src, "1.2.0", {"new.py": "Y = 3\n"})
    x3 = _commit(src, "v3")
    pkg3 = MU.ship("zz", tmp_path / "o3", p, x3, run_tests=False, repo=src)
    monkeypatch.setattr(MU.shutil, "copytree", _boom)
    with pytest.raises(MU.UpdateError, match="已用本次備份還原"):
        MU.apply(root, pkg3)
    assert _snapshot(root) == on_v2, "v3 失敗 ⇒ 仍是 v2（不是半套、也不是 v1）"
    assert len(MU.backups(root, "zz")) == 1, "只剩 v2 那一次的備份"


def test_crash_midway_leaves_in_progress_record_that_rollback_uses(src, tmp_path, monkeypatch):
    """行程在套用中途死掉（還原也沒機會跑）⇒ 留下 in_progress 紀錄 ⇒ rollback 用它回到套用前。"""
    p = _git(src, "rev-parse", "HEAD")
    root = _install(tmp_path, p, src=src)
    before = _snapshot(root)
    x = _v2(src)
    pkg = MU.ship("zz", tmp_path / "o2", p, x, run_tests=False, repo=src)
    monkeypatch.setattr(MU.shutil, "copytree", _boom)
    real_restore = MU._restore_from
    monkeypatch.setattr(MU, "_restore_from", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("行程被殺")))
    with pytest.raises(MU.UpdateError, match="半套"):
        MU.apply(root, pkg)
    monkeypatch.setattr(MU, "_restore_from", real_restore)
    [stamp] = MU.backups(root, "zz")
    assert MU._record(root, "zz", stamp)["status"] == "in_progress"
    MU.rollback(root, "zz")
    assert _snapshot(root) == before


# ── 稽核 D S3-M2：整檔還原不可以蓋掉之後的寫入 ──────────────────────────────────────

def test_rollback_refused_after_another_module_was_applied(src, tmp_path):
    """套 A（zz）→ 套 B（yy）→ 回滾 A ⇒ 拒絕（三個狀態檔與 lock 已被 B 改過，整檔還原會把 B 抹掉）。"""
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    MU.apply(root, pkg)
    y = src / "backend" / "modules" / "yy"
    _write(y / "module.json", json.dumps({"key": "yy", "version": "1.0.0", "core": ">=1.0,<2.0", "pages": []}))
    _write(y / "api.py", "Y = 1\n")
    _commit(src, "yy")
    MU.apply(root, MU.build("yy", tmp_path / "yy", repo=src))
    snap = _snapshot(root)
    with pytest.raises(MU.UpdateError, match="又有別的寫入"):
        MU.rollback(root, "zz")
    assert _snapshot(root) == snap, "被拒絕時不可以動任何檔"


def test_rollback_refused_after_a_full_package(src, tmp_path):
    """模組包之後裝了完整包（部署 commit 換了）⇒ 拒絕回滾這個模組包。"""
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    MU.apply(root, pkg)
    _write(root / "backend" / ".deployed_commit.json", "\ufeff" + json.dumps({"commit": "9" * 40}))
    snap = _snapshot(root)
    with pytest.raises(MU.UpdateError, match="另一個完整包"):
        MU.rollback(root, "zz")
    assert _snapshot(root) == snap


def test_rollback_refused_when_module_files_changed_later(src, tmp_path):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    MU.apply(root, pkg)
    (root / "backend" / "modules" / "zz" / "api.py").write_text("HOTFIX = 1\n", encoding="utf-8")
    with pytest.raises(MU.UpdateError, match="又被改過"):
        MU.rollback(root, "zz")


def test_rolled_back_record_is_not_offered_again(src, tmp_path):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    MU.apply(root, pkg)
    MU.rollback(root, "zz")
    assert MU.backups(root, "zz") == [], "回滾過的那一份不再列為可回滾"


# ── §10 機器可讀輸出（A 的 apply_module_update.ps1 對齊）─────────────────────────────

def _last(capsys):
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line.startswith("MODULE_UPDATE_RESULT ") and line.isascii(), line
    return json.loads(line.split(" ", 1)[1])


def test_apply_uses_caller_stamp_and_rejects_bad_or_duplicate(src, tmp_path, capsys):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    assert MU.main(["apply", "--root", str(root), "--pkg", str(pkg), "--stamp", "bad", "--json"]) == 2
    assert _last(capsys)["code"] == "bad_args"
    assert MU.main(["apply", "--root", str(root), "--pkg", str(pkg), "--stamp", "20260928_190000", "--json"]) == 0
    d = _last(capsys)
    assert d["stamp"] == "20260928_190000" and MU.backups(root, "zz") == ["20260928_190000"]


def test_rollback_json_codes(src, tmp_path, capsys):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    assert MU.main(["rollback", "--root", str(root), "--key", "zz", "--json"]) == 2
    assert _last(capsys)["code"] == "no_backup"
    MU.apply(root, pkg, stamp="20260928_190001")
    victim = next((root / MU.BACKUP_DIR / "zz" / "20260928_190001" / "state_before").rglob("*.json"))
    victim.write_text("CORRUPT", encoding="utf-8")
    (root / MU.BACKUP_DIR / "zz" / "20260928_190001" / "lock_before.json").unlink()
    snap = _snapshot(root)
    assert MU.main(["rollback", "--root", str(root), "--key", "zz", "--backup", "20260928_190001", "--json"]) == 2
    d = _last(capsys)
    assert d["code"] == "backup_corrupt" and d["stamp"] == "20260928_190001", d
    assert _snapshot(root) == snap, "backup_corrupt：一個檔都不動（ps1 據此改走「停用該模組再重啟」）"


def test_unexpected_exception_still_prints_a_result_line(src, tmp_path, capsys, monkeypatch):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    monkeypatch.setattr(MU, "apply", lambda *a, **k: (_ for _ in ()).throw(ValueError("爆")))
    assert MU.main(["apply", "--root", str(root), "--pkg", str(pkg), "--stamp", "20260928_190002", "--json"]) == 3
    d = _last(capsys)
    assert d == {"ok": False, "code": "unexpected", "error": "ValueError: 爆", "stamp": "20260928_190002"}


def test_every_code_is_documented_for_the_ps1():
    """程式裡每一個 UpdateError code 都列在設計 §10 的值域表（A 的 ps1 依它分流；新增 code 沒寫進表 ⇒ 紅）。"""
    import ast
    src_text = (REPO / "tools" / "platform" / "module_update.py").read_text(encoding="utf-8")
    codes = {kw.value.value for n in ast.walk(ast.parse(src_text)) if isinstance(n, ast.Call)
             for kw in n.keywords if kw.arg == "code" and isinstance(kw.value, ast.Constant)}
    codes |= {"refused", "unexpected"}
    doc = (REPO / "docs" / "platform" / "MODULE-UPDATE-DELIVERY.md").read_text(encoding="utf-8")
    table = doc[doc.index("## 10."):]
    missing = sorted(c for c in codes if "| `%s` |" % c not in table)
    assert not missing, "設計 §10 沒列的 code：%s" % missing
    assert len(codes) >= 20, "正對照：程式裡應該抓得到二十幾個 code（抓不到＝這一題量尺壞了）"


# ── 稽核 D S3R-M1（探針 P7）：中斷的套用 ─────────────────────────────────────────

def _crash(monkeypatch, root, pkg):
    """模擬行程在換檔中途被砍（還原也來不及跑）⇒ 留下 in_progress。"""
    monkeypatch.setattr(MU.shutil, "copytree", _boom)
    real = MU._restore_from
    monkeypatch.setattr(MU, "_restore_from", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("行程被殺")))
    with pytest.raises(MU.UpdateError):
        MU.apply(root, pkg)
    monkeypatch.undo()
    MU._license_check = lambda manifest: (True, "")        # undo 也還原了 autouse 的授權注入
    return real


def test_interrupted_apply_blocks_new_apply_until_rolled_back(src, tmp_path, monkeypatch):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    _crash(monkeypatch, root, pkg)
    [stamp] = MU.pending_interrupted(root, "zz")
    with pytest.raises(MU.UpdateError) as ei:
        MU.apply(root, pkg)
    assert ei.value.code == "interrupted_apply_pending" and stamp in str(ei.value)
    MU.rollback(root, "zz", stamp)
    assert MU.pending_interrupted(root, "zz") == []
    MU.apply(root, pkg)                                      # 回滾之後才准再套


def test_rollback_of_an_older_interrupted_record_is_refused(src, tmp_path, monkeypatch):
    """D 探針 P7：舊的 in_progress 之後又有紀錄（例：繞過檢查重套）⇒ rollback --backup <舊的> 拒絕，不動任何檔。"""
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    _crash(monkeypatch, root, pkg)
    [old] = MU.pending_interrupted(root, "zz")
    MU._restore_from(root, "zz", root / MU.BACKUP_DIR / "zz" / old, MU._record(root, "zz", old))   # 人工收拾現場
    monkeypatch.setattr(MU, "pending_interrupted", lambda *a: [])                                  # 模擬舊版工具（沒有 ① 的檢查）
    MU.apply(root, pkg)
    monkeypatch.undo()
    MU._license_check = lambda manifest: (True, "")
    snap = _snapshot(root)
    with pytest.raises(MU.UpdateError) as ei:
        MU.rollback(root, "zz", old)
    assert ei.value.code == "interrupted_not_latest"
    assert _snapshot(root) == snap


def test_interrupted_rollback_checks_the_full_package_base(src, tmp_path, monkeypatch):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    _crash(monkeypatch, root, pkg)
    _write(root / "backend" / ".deployed_commit.json", json.dumps({"commit": "8" * 40}))
    with pytest.raises(MU.UpdateError) as ei:
        MU.rollback(root, "zz")
    assert ei.value.code == "base_changed"


def test_prune_also_removes_rolled_back_but_never_in_progress(src, tmp_path, monkeypatch):
    """S3R-S1：回滾過的備份也在保留數之內被清；in_progress 永遠不刪（它是唯一的還原依據）。"""
    p = _git(src, "rev-parse", "HEAD")
    root = _install(tmp_path, p, src=src)
    monkeypatch.setattr(MU, "BACKUP_KEEP", 1)
    x = _v2(src)
    pkg = MU.ship("zz", tmp_path / "o", p, x, run_tests=False, repo=src)
    MU.apply(root, pkg)
    MU.rollback(root, "zz")
    MU.apply(root, pkg)
    names = MU._all_records(root, "zz")
    assert len(names) == 1 and MU._record(root, "zz", names[0])["status"] == "applied", names


# ── 稽核 D P8：中斷的套用跨模組（lock 與狀態檔是全安裝共用）─────────────────────────────

def _yy(src, tmp_path):
    y = src / "backend" / "modules" / "yy"
    _write(y / "module.json", json.dumps({"key": "yy", "version": "1.0.0", "core": ">=1.0,<2.0", "pages": []}))
    _write(y / "api.py", "Y = 1\n")
    _commit(src, "yy")
    return MU.build("yy", tmp_path / "yy", repo=src)


def test_interrupted_apply_of_one_module_blocks_every_module(src, tmp_path, monkeypatch):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    _crash(monkeypatch, root, pkg)
    with pytest.raises(MU.UpdateError) as ei:
        MU.apply(root, _yy(src, tmp_path))
    assert ei.value.code == "interrupted_apply_pending" and "zz" in str(ei.value)


def test_p8_rollback_of_interrupted_zz_after_yy_is_refused(src, tmp_path, monkeypatch):
    """D 探針 P8：zz 中斷 → （繞過檢查）套 yy 成功 → rollback zz ⇒ 拒絕（否則 lock 的 yy 條目與覆蓋紀錄被抹掉而 yy 檔還在）。"""
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    _crash(monkeypatch, root, pkg)
    [zz_stamp] = MU.pending_interrupted(root, "zz")
    ypkg = _yy(src, tmp_path)
    monkeypatch.setattr(MU, "pending_interrupted_any", lambda *a: [])          # 模擬舊版工具（沒有 ① 的檢查）
    MU.apply(root, ypkg)
    monkeypatch.undo()
    MU._license_check = lambda manifest: (True, "")
    snap = _snapshot(root)
    with pytest.raises(MU.UpdateError) as ei:
        MU.rollback(root, "zz", zz_stamp)
    assert ei.value.code == "interrupted_not_latest" and "yy" in str(ei.value)
    assert _snapshot(root) == snap


def test_full_package_plan_refuses_while_a_module_apply_is_interrupted(tmp_path):
    """完整包（apply_update → apply_plan plan）也要檢查並報出 ⇒ plan_refused 級（APPLY_PLAN_REFUSED）。"""
    import sys
    sys.path.insert(0, str(REPO / "backend" / "tools"))
    import apply_plan as AP
    root = tmp_path / "install"
    rec = root / AP.MODULE_BACKUP_DIR / "zz" / "20260928_190000"
    rec.mkdir(parents=True)
    (rec / "apply.json").write_text(json.dumps({"status": "in_progress"}), encoding="utf-8")
    assert AP.interrupted_module_applies(str(root)) == [("zz", "20260928_190000")]
    with pytest.raises(AP.Refuse, match="中斷的單模組套用"):
        AP.make_plan(str(root), str(REPO), 200)
    (rec / "apply.json").write_text(json.dumps({"status": "applied"}), encoding="utf-8")
    assert AP.interrupted_module_applies(str(root)) == []


# ── 稽核 D S4-S2：lock 的頁面路徑形狀 ────────────────────────────────────────────

@pytest.mark.parametrize("bad", [PAGES_DIR + "/../../backend/main.py", PAGES_DIR + "/sub/x.html", "backend/x.html",
                                 PAGES_DIR + "/x.htm"])
def test_lock_page_paths_must_stay_in_the_pages_dir(src, tmp_path, bad):
    p, pkg = _shipped(src, tmp_path)
    lock = MU.load_pkg(pkg)
    lock["pages"] = {bad: "0" * 64}
    MU._write_lock(pkg, lock)
    assert any("頁面路徑不合格" in x for x in MU.check(pkg))
    root = _install(tmp_path, p)
    _refused(root, pkg, "頁面路徑不合格")



# ── 稽核 D S5-S1（P9）／S5-S2 ──────────────────────────────────────────────────

def test_unreadable_apply_record_counts_as_interrupted(src, tmp_path):
    p, pkg = _shipped(src, tmp_path)
    root = _install(tmp_path, p)
    rec = root / MU.BACKUP_DIR / "zz" / "20260928_190500"
    rec.mkdir(parents=True)
    (rec / "apply.json").write_text("{壞掉", encoding="utf-8")
    assert MU.pending_interrupted_any(root) == [("zz", "20260928_190500")]
    with pytest.raises(MU.UpdateError) as ei:
        MU.apply(root, pkg)
    assert ei.value.code == "interrupted_apply_pending"
    # 〔更正（B55F-M1 填入確切指令，2026-09-29 B）：原寫 `"module_update" not in`——確切指令 apply_module_update.ps1 本身含這個子字串；改驗「不叫人跑 module_update.py」且帶上確切的回滾指令〕
    msg = str(ei.value)
    assert "module_update.py" not in msg and "回滾模式" in msg, "S5-S2：不叫人直接跑 module_update rollback"
    assert "apply_module_update.ps1 -Rollback -ModuleKey zz -Backup 20260928_190500 -Yes" in msg, "B55F-M1：訊息帶確切指令（模組與備份）"
    assert "-IncludeDatabase -ConfirmDatabaseOverwrite" in msg and "needs_database" in msg
    with pytest.raises(MU.UpdateError) as ei2:
        MU.rollback(root, "zz", "20260928_190500")
    assert ei2.value.code == "backup_corrupt"


def test_manifest_lines_handle_multi_line_older_entries(src, tmp_path):
    """S6 演練踩到：實際的 version_manifest 較舊的條目跨多行 ⇒ 原本逐行解析就丟例外。新條目照樣取成一行。"""
    p0 = _git(src, "rev-parse", "HEAD")
    multi = '[\n  {\n    "module": "其他",\n    "version": "2026-08-01a",\n    "content": "舊的多行條目"\n  }\n]\n'
    (src / "backend" / "version_manifest.json").write_text(multi, encoding="utf-8")
    p = _commit(src, "multi-line manifest")
    x = _v2(src)
    lines = MU.manifest_lines(p, x, "zz", repo=src)
    assert [json.loads(l)["version"] for l in lines] == ["2026-09-28z"] and all("\n" not in l for l in lines)
    del p0
