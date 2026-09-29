"""W3 待辦 4：更新標註（tools/platform/update_annotation.py）＋驗包 (8) 對帳＋modtest --annotation。

使用者裁定（2026-09-30）：只標列車／出貨包；動檔沒升版先警告不擋。
"""
import importlib.util
import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend" / "tools"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


UA = _load("_ua_t", "tools/platform/update_annotation.py")


def _has(commit):
    return subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", commit + "^{commit}"], capture_output=True).returncode == 0


# ── 真實歷史：第二十二班（29e435df → b6182dbf）手寫的步驟檔，要與機器產出一致 ──────────────────

STEP22 = REPO / "docs" / "platform" / "prod-tasks" / "20260929-train22-apply.md"


@pytest.mark.skipif(not (_has("29e435df") and _has("b6182dbf")), reason="這個 clone 沒有第二十二班的 commit（淺層 clone）")
def test_train22_annotation_matches_the_hand_written_stepfile():
    a = UA.build(REPO, "29e435df", "b6182dbf")
    assert {m["key"]: (m["from"], m["to"]) for m in a["modules"] if m["from"] != m["to"]} == {
        "lodging": ("1.1.1", "1.2.1"), "tender_radar": ("1.3.4", "1.5.1")}
    assert a["complete"] is True
    assert UA.render_stepfile(a) == "唯一允許的版本變化：`lodging`→`1.2.1`、`tender_radar`→`1.5.1`，其餘模組版本不變"
    assert UA.check_stepfile(a, STEP22.read_text(encoding="utf-8")) == []
    assert "lodging 1.1.1→1.2.1" in UA.render_runplan(a)


def test_stepfile_check_catches_a_hand_written_mismatch():
    a = {"modules": [{"key": "lodging", "from": "1.1.1", "to": "1.2.1"}, {"key": "case", "from": "1.0.18", "to": "1.0.19"}]}
    text = "…唯一允許的版本變化：`lodging`→`1.2.1`、`tender_radar`→`1.5.1`，其餘模組版本不變…"
    probs = UA.check_stepfile(a, text)
    assert any("case" in p for p in probs) and any("tender_radar" in p for p in probs), probs
    assert UA.check_stepfile(a, "沒有那一句") != []


# ── 合成 repo：警告／完整性／L1 ─────────────────────────────────────────────────

def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


def _mk(repo, files):
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "c")
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def _mj(v):
    return json.dumps({"key": "a", "version": v})


REG = json.dumps({"L1": {"units": ["core:main"]}, "modules": {"M01": {"key": "a", "name": "甲", "units": []}, "M02": {"key": "b", "name": "乙", "units": []}}})
CORE = 'CORE_VERSION = "1.0"\n'


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    r = tmp_path / "r"
    r.mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True, capture_output=True)
    return r


BASE = {"docs/platform/modules.json": REG, "backend/core/registry.py": CORE,
        "backend/modules/a/module.json": _mj("1.0.0"), "backend/modules/a/x.py": "x=1\n",
        "backend/modules/b/module.json": json.dumps({"key": "b", "version": "2.0.0"}), "backend/modules/b/y.py": "y=1\n",
        "backend/main.py": "m=1\n"}


def test_code_change_without_bump_warns_and_bump_does_not(repo):
    c0 = _mk(repo, BASE)
    c1 = _mk(repo, {"backend/modules/a/x.py": "x=2\n"})
    a = UA.build(repo, c0, c1)
    assert [m["key"] for m in a["modules"]] == ["a"] and a["unchanged_modules"] == ["b"]
    assert any("模組 a" in w and "版號沒升" in w for w in a["warnings"]), a["warnings"]
    c2 = _mk(repo, {"backend/modules/a/x.py": "x=3\n", "backend/modules/a/module.json": _mj("1.0.1")})
    a2 = UA.build(repo, c1, c2)
    assert a2["warnings"] == [] and a2["modules"][0]["from"] == "1.0.0" and a2["modules"][0]["to"] == "1.0.1"
    assert UA.allowed_changes(a2) == {"a": "1.0.1"}


def test_docs_or_tests_only_change_needs_no_bump(repo):
    c0 = _mk(repo, BASE)
    c1 = _mk(repo, {"backend/modules/a/README.md": "doc\n", "backend/modules/a/tests/test_x.py": "pass\n"})
    assert UA.build(repo, c0, c1)["warnings"] == []


def test_l1_change_is_flagged_and_core_version_compared(repo):
    c0 = _mk(repo, BASE)
    c1 = _mk(repo, {"backend/main.py": "m=2\n"})
    a = UA.build(repo, c0, c1)
    assert a["l1"]["changed"] is True and a["l1"]["core_from"] == a["l1"]["core_to"] == "1.0"
    assert any("共用核心" in w for w in a["warnings"]), a["warnings"]
    c2 = _mk(repo, {"backend/main.py": "m=3\n", "backend/core/registry.py": 'CORE_VERSION = "1.1"\n'})
    a2 = UA.build(repo, c1, c2)
    assert a2["warnings"] == [] and a2["l1"]["core_to"] == "1.1"


def test_unreadable_module_json_makes_the_annotation_incomplete_not_silent(repo):
    c0 = _mk(repo, BASE)
    c1 = _mk(repo, {"backend/modules/a/module.json": "{ not json", "backend/modules/a/x.py": "x=9\n"})
    a = UA.build(repo, c0, c1)
    assert a["complete"] is False and a["modules"][0]["to"] == "unknown"
    assert "不完整" in UA.render_runplan(a)


# ── 驗包 (8) ──────────────────────────────────────────────────────────────────

@pytest.fixture
def vp(monkeypatch):
    mod = _load("_vp_ann", "backend/tools/verify_package.py")
    monkeypatch.setattr(mod, "R", mod.Report())
    return mod


def _pkg(tmp_path, annotation="ok", commit="abcdef1234", lock_ver="1.0.1"):
    pkg = tmp_path / "pkg"
    (pkg / "backend").mkdir(parents=True)
    (pkg / "deploy_manifest.json").write_text(json.dumps({"commit": commit}), encoding="utf-8")
    (pkg / "backend" / "modules.lock.json").write_text(json.dumps({"modules": {"a": {"version": lock_ver}}}), encoding="utf-8")
    if annotation == "ok":
        body = {"format": 1, "from": "0" * 40, "to": "abcdef1234" + "0" * 30, "complete": True,
                "modules": [{"key": "a", "from": "1.0.0", "to": "1.0.1"}, {"key": "not_in_lock", "from": "1", "to": "2"}], "warnings": ["w"]}
        (pkg / "backend" / "update_annotation.json").write_text(json.dumps(body), encoding="utf-8")
    elif annotation is not None:
        (pkg / "backend" / "update_annotation.json").write_text(annotation, encoding="utf-8")
    return str(pkg)


def test_verify_annotation_ok_and_missing_is_only_a_warning(vp, tmp_path, capsys):
    vp.check_update_annotation(_pkg(tmp_path))
    assert vp.R.fails == []
    vp.check_update_annotation(_pkg(tmp_path / "n", annotation=None))
    assert vp.R.fails == [] and "沒有更新標註" in capsys.readouterr().out


def test_verify_annotation_mismatches_fail(vp, tmp_path):
    vp.check_update_annotation(_pkg(tmp_path / "a", lock_ver="9.9.9"))
    assert any("modules.lock.json" in d for _, d in vp.R.fails)
    vp.R.fails.clear()
    vp.check_update_annotation(_pkg(tmp_path / "b", commit="ffffffff"))
    assert any("不是這一包" in d for _, d in vp.R.fails)
    vp.R.fails.clear()
    for bad in ("nope", json.dumps({"format": 2, "modules": []}), json.dumps([1])):
        vp.check_update_annotation(_pkg(tmp_path / ("c%d" % len(bad)), annotation=bad))
    assert len(vp.R.fails) == 3


# ── modtest --annotation ──────────────────────────────────────────────────────

def test_modtest_takes_its_changed_files_from_the_annotation(tmp_path):
    mt = _load("_mt_ann", "tools/platform/modtest.py")
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"format": 1, "complete": True, "l1": {"files": ["backend/main.py"]},
                             "modules": [{"key": "a", "files": ["backend/modules/a/x.py", "frontend/pages/a.html"]}]}), encoding="utf-8")
    got = mt.changed_files(Namespace(annotation=str(f), files=None, commit=None, changed_since=None, base=None))
    assert got == ["backend/main.py", "backend/modules/a/x.py", "frontend/pages/a.html"]
