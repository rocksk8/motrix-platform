"""9c① 匯出選配（tools/platform/product_select.py）：在 tmp 建合成部署包，不綁特定 L2 模組。"""
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("_product_select", REPO / "tools" / "platform" / "product_select.py")
PS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(PS)


def _pkg(tmp_path, mods=("alpha", "beta")):
    """合成部署包：backend/core/registry.py、L1 檔、幾個模組（各帶一頁前端）。"""
    pkg = tmp_path / "pkg"
    b = pkg / "backend"
    (b / "core").mkdir(parents=True)
    (b / "core" / "registry.py").write_text('CORE_VERSION = "9.9"\n', encoding="utf-8")
    (b / "helpers").mkdir()
    (b / "helpers" / "auth.py").write_text("", encoding="utf-8")
    (b / "main.py").write_text("", encoding="utf-8")
    (pkg / "frontend" / "pages").mkdir(parents=True)
    (pkg / "frontend" / "pages" / "index.html").write_text("", encoding="utf-8")
    (pkg / "tools" / "platform").mkdir(parents=True)
    (pkg / "tools" / "platform" / "upgrade.py").write_text("", encoding="utf-8")
    for i, k in enumerate(mods):
        d = b / "modules" / k
        d.mkdir(parents=True)
        (d / "module.json").write_text(json.dumps({"key": k, "version": "1.%d.0" % i,
                                                   "pages": [{"path": k + ".html"}]}), encoding="utf-8")
        (d / "api.py").write_text("", encoding="utf-8")
        (pkg / "frontend" / "pages" / (k + ".html")).write_text("", encoding="utf-8")
    mj = tmp_path / "modules.json"
    mj.write_text(json.dumps({"L1": {"units": ["plat:registry", "helper:auth", "core:main"]}, "modules": {}}),
                  encoding="utf-8")
    return pkg, mj


@pytest.fixture(autouse=True)
def _only_synthetic_core(monkeypatch):
    """required_l1_files 另會掃 repo 的 backend/core/*.py；合成包只驗它自己宣告的 L1。"""
    real = PS.required_l1_files
    monkeypatch.setattr(PS, "REPO", Path("Z:/__no_such_repo__"))
    yield real


def test_full_keeps_every_module_and_writes_lock(tmp_path):
    pkg, mj = _pkg(tmp_path)
    lock = PS.apply(pkg, {"name": "full", "modules": ["*"]})
    assert {k: v["version"] for k, v in lock["modules"].items()} == {"alpha": "1.0.0", "beta": "1.1.0"}
    assert lock["excluded"] == [] and lock["lock_version"] == 1 and lock["kind"] == "full_package"
    assert all(len(v["sha256"]) == 64 for v in lock["modules"].values())
    assert lock["core_version"] == "9.9"
    assert PS.check(pkg, mj) == []


def test_core_only_drops_every_module_and_its_pages(tmp_path):
    pkg, mj = _pkg(tmp_path)
    lock = PS.apply(pkg, {"name": "core-only", "modules": []})
    assert lock["modules"] == {} and lock["excluded"] == ["alpha", "beta"]
    assert not (pkg / "backend" / "modules" / "alpha").exists()
    assert not (pkg / "frontend" / "pages" / "alpha.html").exists()
    assert (pkg / "frontend" / "pages" / "index.html").exists(), "非模組頁不可以被刪"
    assert PS.check(pkg, mj) == []


def test_subset_keeps_only_listed(tmp_path):
    pkg, mj = _pkg(tmp_path)
    PS.apply(pkg, {"name": "x", "modules": ["beta"]})
    assert sorted(PS.module_dirs(pkg / "backend")) == ["beta"]
    assert PS.check(pkg, mj) == []


def test_unknown_module_is_refused_not_ignored(tmp_path):
    pkg, _ = _pkg(tmp_path)
    with pytest.raises(PS.SelectError):
        PS.apply(pkg, {"name": "x", "modules": ["alpha", "gamma"]})
    assert sorted(PS.module_dirs(pkg / "backend")) == ["alpha", "beta"], "拒絕時不可以動到包"


def test_star_mixed_with_names_is_refused(tmp_path):
    pkg, _ = _pkg(tmp_path)
    with pytest.raises(PS.SelectError):
        PS.apply(pkg, {"name": "x", "modules": ["*", "alpha"]})


def test_readonly_file_inside_dropped_module_is_removed(tmp_path):
    pkg, mj = _pkg(tmp_path)
    ro = pkg / "backend" / "modules" / "alpha" / "api.py"
    os.chmod(ro, stat.S_IREAD)
    PS.apply(pkg, {"name": "x", "modules": ["beta"]})
    assert not (pkg / "backend" / "modules" / "alpha").exists()


# ── check 的反向控制 ────────────────────────────────────────────────────────

def test_rc_missing_lock(tmp_path):
    pkg, mj = _pkg(tmp_path)
    assert any("modules.lock.json" in p for p in PS.check(pkg, mj))


def test_rc_lock_lists_a_module_that_is_not_in_the_package(tmp_path):
    pkg, mj = _pkg(tmp_path)
    PS.apply(pkg, {"name": "full", "modules": ["*"]})
    PS._rmtree(pkg / "backend" / "modules" / "beta")
    assert any("≠ 包內實際" in p for p in PS.check(pkg, mj))


def test_rc_package_has_a_module_the_lock_does_not_list(tmp_path):
    pkg, mj = _pkg(tmp_path, mods=("alpha",))
    PS.apply(pkg, {"name": "full", "modules": ["*"]})
    d = pkg / "backend" / "modules" / "sneaky"
    d.mkdir()
    (d / "module.json").write_text(json.dumps({"key": "sneaky", "version": "0.1.0"}), encoding="utf-8")
    assert any("≠ 包內實際" in p for p in PS.check(pkg, mj))


def test_rc_version_mismatch(tmp_path):
    pkg, mj = _pkg(tmp_path)
    PS.apply(pkg, {"name": "full", "modules": ["*"]})
    mf = pkg / "backend" / "modules" / "alpha" / "module.json"
    mf.write_text(json.dumps({"key": "alpha", "version": "2.0.0"}), encoding="utf-8")
    assert any("lock 版本" in p for p in PS.check(pkg, mj))


def test_rc_missing_l1_file_blocks(tmp_path):
    pkg, mj = _pkg(tmp_path)
    PS.apply(pkg, {"name": "core-only", "modules": []})
    (pkg / "backend" / "helpers" / "auth.py").unlink()
    assert any("helpers/auth.py" in p for p in PS.check(pkg, mj))


def test_real_product_files_are_valid():
    """repo 裡的產品設定檔都讀得進來；至少有 full 與 core-only。"""
    names = {p.stem for p in (REPO / "product").glob("*.json")}
    assert {"full", "core-only"} <= names
    for n in names:
        prod = PS.load_product(str(REPO / "product" / (n + ".json")))
        assert prod["name"] == n
    assert PS.load_product(str(REPO / "product" / "core-only.json"))["modules"] == []


def test_real_required_l1_files_exist_in_the_repo(_only_synthetic_core, monkeypatch):
    """正對照：用 repo 自己的 modules.json 算出的必要檔，在 repo 的 backend/ 裡都要存在。"""
    monkeypatch.setattr(PS, "REPO", REPO)
    req = _only_synthetic_core()
    assert len(req) > 20
    missing = [r for r in req if not (REPO / "backend" / r).is_file()]
    assert not missing, missing


def test_rc_missing_upgrade_tool_blocks(tmp_path):
    """tools/ 刻意進包（升級精靈在正式機執行 tools/platform/upgrade.py）⇒ 缺了要擋。"""
    pkg, mj = _pkg(tmp_path)
    PS.apply(pkg, {"name": "full", "modules": ["*"]})
    (pkg / "tools" / "platform" / "upgrade.py").unlink()
    assert any("tools/platform/upgrade.py" in p for p in PS.check(pkg, mj))


def test_real_repo_still_tracks_the_upgrade_tool_without_export_ignore():
    """正對照：repo 真的有 tools/platform/upgrade.py，而且 .gitattributes 沒有把它排除出包。"""
    import subprocess
    assert (REPO / "tools" / "platform" / "upgrade.py").is_file()
    out = subprocess.run(["git", "-C", str(REPO), "check-attr", "export-ignore", "--", "tools/platform/upgrade.py"],
                         capture_output=True, text=True, check=True).stdout
    assert "export-ignore: set" not in out, out


def test_rc_content_changed_after_packaging(tmp_path):
    pkg, mj = _pkg(tmp_path)
    PS.apply(pkg, {"name": "full", "modules": ["*"]})
    (pkg / "backend" / "modules" / "alpha" / "api.py").write_text("x = 1\n", encoding="utf-8")
    assert any("內容雜湊" in p for p in PS.check(pkg, mj))


def test_rc_unknown_lock_version_or_kind_is_refused(tmp_path):
    pkg, mj = _pkg(tmp_path)
    PS.apply(pkg, {"name": "full", "modules": ["*"]})
    lp = pkg / "backend" / PS.LOCK_NAME
    lock = json.loads(lp.read_text(encoding="utf-8"))
    for key, bad in (("lock_version", 2), ("kind", "mystery")):
        broken = dict(lock, **{key: bad})
        lp.write_text(json.dumps(broken), encoding="utf-8")
        assert PS.check(pkg, mj), key


def test_module_update_kind_checks_only_listed_modules(tmp_path):
    """P7 預留：module_update 只核對它列的模組（其他模組存在與否不管），且不驗 L0／L1。"""
    pkg, mj = _pkg(tmp_path)
    b = pkg / "backend"
    lock = {"lock_version": 1, "kind": "module_update", "product": "update-alpha", "core_version": "9.9",
            "modules": {"alpha": PS.module_entry(b / "modules" / "alpha")}}
    (b / PS.LOCK_NAME).write_text(json.dumps(lock), encoding="utf-8")
    (b / "helpers" / "auth.py").unlink()
    assert PS.check(pkg, mj) == []
    lock["modules"]["gamma"] = {"version": "1.0.0", "sha256": "0" * 64}
    (b / PS.LOCK_NAME).write_text(json.dumps(lock), encoding="utf-8")
    assert any("不在包裡" in p for p in PS.check(pkg, mj))
