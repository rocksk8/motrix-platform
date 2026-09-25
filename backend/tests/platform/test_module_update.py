"""P7 模組更新包（tools/platform/module_update.py；CUSTOMIZATION-SPEC §7）。

合成 git repo 打包、合成安裝目錄套用與回滾；每一條套用前檢查都有反向控制。不綁特定 L2 模組
（最後一題另對 repo 裡現有的模組做正對照）。
"""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("_module_update", REPO / "tools" / "platform" / "module_update.py")
MU = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MU)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _module(repo, version, core=">=1.0,<2.0", extra=""):
    m = repo / "backend" / "modules" / "zz"
    _write(m / "module.json", json.dumps({"key": "zz", "version": version, "core": core,
                                          "pages": [{"path": "zz.html"}]}))
    _write(m / "api.py", "VERSION = %r\n%s" % (version, extra))
    _write(m / "tests" / "test_zz.py", "def test_x():\n    pass\n")
    _write(m / "SPEC.md", "# spec\n")
    _write(repo / "frontend" / "pages" / "zz.html", "<p>%s</p>\n" % version)


@pytest.fixture()
def src(tmp_path):
    r = tmp_path / "src"
    _write(r / "backend" / "core" / "registry.py", 'CORE_VERSION = "1.2"\n')
    _module(r, "1.0.0")
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "v1")
    return r


def _commit(r, msg):
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", msg)


def _install(tmp_path, core="1.2", with_lock=True):
    root = tmp_path / "install"
    _write(root / "backend" / "core" / "registry.py", 'CORE_VERSION = "%s"\n' % core)
    _write(root / "frontend" / "pages" / "index.html", "home\n")
    if with_lock:
        _write(root / "backend" / "modules.lock.json",
               json.dumps({"lock_version": 1, "kind": "full_package", "product": "core-only",
                           "core_version": core, "modules": {}, "excluded": ["zz"]}))
    return root


def _build(src, tmp_path, name="out"):
    return MU.build("zz", tmp_path / name, repo=src)


def test_build_takes_only_the_module_and_its_pages(src, tmp_path):
    pkg = _build(src, tmp_path)
    assert (pkg / "backend" / "modules" / "zz" / "api.py").is_file()
    assert (pkg / "frontend" / "pages" / "zz.html").is_file()
    assert not (pkg / "backend" / "modules" / "zz" / "tests").exists(), "測試不進更新包"
    assert not (pkg / "backend" / "modules" / "zz" / "SPEC.md").exists()
    assert not (pkg / "backend" / "core").exists(), "L0／L1 不進更新包"
    lock = json.loads((pkg / MU.LOCK_NAME).read_text(encoding="utf-8"))
    assert lock["kind"] == "module_update" and list(lock["modules"]) == ["zz"] and lock["core_version"] == "1.2"
    assert MU.check(pkg) == []


def test_fresh_install_then_rollback_removes_it(src, tmp_path):
    root = _install(tmp_path)
    pkg = _build(src, tmp_path)
    before = MU._tree_hashes(root, "zz")
    rec, _ = MU.apply(root, pkg)
    assert rec["from_version"] is None and (root / "frontend" / "pages" / "zz.html").is_file()
    assert json.loads((root / "backend" / "modules.lock.json").read_text(encoding="utf-8"))["modules"]["zz"]["version"] == "1.0.0"
    MU.rollback(root, "zz")
    assert MU._tree_hashes(root, "zz") == before == {}
    assert "zz" not in json.loads((root / "backend" / "modules.lock.json").read_text(encoding="utf-8"))["modules"]
    assert (root / "frontend" / "pages" / "index.html").is_file(), "其他頁面不可以被動到"


def test_upgrade_then_rollback_restores_every_hash(src, tmp_path):
    root = _install(tmp_path)
    MU.apply(root, _build(src, tmp_path, "v1"))
    v1 = MU._tree_hashes(root, "zz")
    _module(src, "1.1.0", extra="NEW = 1\n")
    _commit(src, "v1.1")
    rec, _ = MU.apply(root, _build(src, tmp_path, "v11"))
    assert rec["from_version"] == "1.0.0" and rec["to_version"] == "1.1.0"
    assert MU._tree_hashes(root, "zz") != v1
    MU.rollback(root, "zz")
    assert MU._tree_hashes(root, "zz") == v1


# ── 套用前檢查的反向控制（每一條都不可以動到安裝目錄）─────────────────────────

def _snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _refused(root, pkg, match, **kw):
    snap = _snapshot(root)
    with pytest.raises(MU.UpdateError, match=match):
        MU.apply(root, pkg, **kw)
    assert _snapshot(root) == snap, "被拒絕時安裝目錄不可以有任何改動"


def test_rc_same_or_lower_version_is_refused(src, tmp_path):
    root = _install(tmp_path)
    pkg = _build(src, tmp_path)
    MU.apply(root, pkg)
    _refused(root, pkg, "不高於已安裝")
    MU.apply(root, pkg, allow_downgrade=True)              # 明確要求才允許


def test_rc_incompatible_core_is_refused(src, tmp_path):
    root = _install(tmp_path, core="2.0")
    _refused(root, _build(src, tmp_path), "不相容")


def test_rc_tampered_package_is_refused(src, tmp_path):
    root = _install(tmp_path)
    pkg = _build(src, tmp_path)
    (pkg / "backend" / "modules" / "zz" / "api.py").write_text("EVIL = 1\n", encoding="utf-8")
    _refused(root, pkg, "打包後被改過")


def test_rc_tampered_page_is_refused(src, tmp_path):
    root = _install(tmp_path)
    pkg = _build(src, tmp_path)
    (pkg / "frontend" / "pages" / "zz.html").write_text("x", encoding="utf-8")
    _refused(root, pkg, "雜湊不符")


def test_rc_module_with_migrations_is_refused(src, tmp_path):
    _write(src / "backend" / "modules" / "zz" / "migrations" / "0001_x.py", "")
    _commit(src, "add migration")
    root = _install(tmp_path)
    _refused(root, _build(src, tmp_path), "P7b")


def test_rc_install_without_lock_is_refused(src, tmp_path):
    root = _install(tmp_path, with_lock=False)
    _refused(root, _build(src, tmp_path), "modules.lock.json")


def test_rc_rollback_without_backup_is_refused(tmp_path):
    root = _install(tmp_path)
    with pytest.raises(MU.UpdateError, match="沒有任何套用備份"):
        MU.rollback(root, "zz")


def test_rc_corrupted_backup_stops_rollback(src, tmp_path):
    root = _install(tmp_path)
    MU.apply(root, _build(src, tmp_path, "v1"))
    _module(src, "1.1.0")
    _commit(src, "v1.1")
    MU.apply(root, _build(src, tmp_path, "v11"))
    stamp = MU.backups(root, "zz")[-1]
    victim = next((root / MU.BACKUP_DIR / "zz" / stamp / "files").rglob("api.py"))
    victim.write_text("CORRUPT\n", encoding="utf-8")
    with pytest.raises(MU.UpdateError, match="備份已損壞"):
        MU.rollback(root, "zz", stamp)


def test_real_module_in_repo_builds_and_checks(tmp_path):
    """正對照：repo 裡現有的已安裝模組（任取一個）能打成更新包並通過檢查。"""
    mods = sorted(p.name for p in (REPO / "backend" / "modules").iterdir() if (p / "module.json").is_file())
    if not mods:
        pytest.skip("repo 裡沒有已安裝模組")
    pkg = MU.build(mods[0], tmp_path)
    assert MU.check(pkg) == []
