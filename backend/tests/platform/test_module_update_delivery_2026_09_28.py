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
