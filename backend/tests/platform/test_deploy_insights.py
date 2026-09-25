# -*- coding: utf-8 -*-
"""部署儀表板唯讀分析（CORE-SPEC §9e D2／D6／D7）。用暫存 git repo，不碰正式機、不碰真 repo 歷史。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import deploy_insights as di  # noqa: E402


def _git(root, *a):
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)


def _commit(root, files: dict, msg):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    mods = {"L1": {"units": ["router:auth", "plat:loader"]},
            "modules": {"M11": {"key": "zz_mod", "name": "假模組", "units": ["mod:zz_mod/api"]},
                        "M02": {"key": "crm", "name": "業務", "units": ["router:dev_crm", "page:pages/dev-crm.html"]}}}
    base = _commit(root, {"docs/platform/modules.json": json.dumps(mods),
                          "backend/modules/zz_mod/CHANGELOG.md": "# log\n",
                          "backend/core/CHANGELOG.md": "# core\n"}, "base")
    return root, base


@pytest.mark.parametrize("path,unit", [
    ("backend/routers/auth.py", "router:auth"),
    ("backend/helpers/x.py", "helper:x"),
    ("backend/db.py", "core:db"),
    ("backend/core/loader.py", "plat:loader"),
    ("backend/modules/zz_mod/api.py", "mod:zz_mod/api"),
    ("backend/modules/zz_mod/tests/test_a.py", "moddir:zz_mod"),
    ("frontend/pages/dev-crm.html", "page:pages/dev-crm.html"),
    ("frontend/js/a.js", "js:js/a.js"),
    ("backend/core/CHANGELOG.md", "platdir"),
    ("docs/x.md", None),
])
def test_unit_of(path, unit):
    assert di.unit_of(path) == unit


def test_module_changes_groups_files_and_changelog(repo):
    root, base = repo
    head = _commit(root, {
        "backend/modules/zz_mod/api.py": "x=1\n",
        "backend/modules/zz_mod/CHANGELOG.md": "# log\n## 1.0.1\n- 修正：甲\n",
        "backend/routers/dev_crm.py": "y=1\n",
        "backend/core/loader.py": "z=1\n",
        "backend/core/CHANGELOG.md": "# core\n## 1.1\n- 新增：乙\n",
        "docs/readme.md": "doc\n",
    }, "head")
    out = di.module_changes(root, base, head)
    g = {x["id"]: x for x in out["groups"]}
    assert set(g) == {"L1", "M11", "M02", "OTHER"}
    assert out["groups"][0]["id"] == "L1" and out["groups"][-1]["id"] == "OTHER"
    assert "backend/modules/zz_mod/api.py" in g["M11"]["files"]
    assert "- 修正：甲" in g["M11"]["changelog"]
    assert "- 新增：乙" in g["L1"]["changelog"]
    assert g["M02"]["files"] == ["backend/routers/dev_crm.py"] and g["M02"]["changelog"] == []
    assert g["OTHER"]["files"] == ["docs/readme.md"]


def test_unknown_commit_is_refused_not_guessed(repo):
    root, base = repo
    with pytest.raises(RuntimeError):
        di.module_changes(root, base, "deadbeef" * 5)


def test_last_full_states(tmp_path):
    p = tmp_path / ".last_full.json"
    sha = "a" * 40
    assert di.last_full(p, sha)["state"] == "missing"
    p.write_text("{bad", encoding="utf-8")
    assert di.last_full(p, sha)["state"] == "unreadable"
    p.write_text(json.dumps({"commit": "b" * 40, "ok": True}), encoding="utf-8")
    assert di.last_full(p, sha)["state"] == "other_commit"
    p.write_text(json.dumps({"commit": sha, "ok": True, "dirty": True}), encoding="utf-8")
    assert di.last_full(p, sha)["state"] == "dirty"
    p.write_text(json.dumps({"commit": sha, "ok": False}), encoding="utf-8")
    assert di.last_full(p, sha)["state"] == "failed"
    # ok 必須是真的 True，不接受 "true"／1 這類值（守門寧可擋錯）
    p.write_text(json.dumps({"commit": sha, "ok": "true"}), encoding="utf-8")
    assert di.last_full(p, sha)["state"] == "failed"
    p.write_text(json.dumps({"commit": sha, "ok": True}), encoding="utf-8")
    assert di.last_full(p, sha)["state"] == "ok"


def test_upstream_ahead_without_upstream_is_none(repo):
    root, _ = repo
    assert di.upstream_ahead(root) == (None, None)
