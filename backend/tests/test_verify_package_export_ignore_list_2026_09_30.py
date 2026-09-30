"""T22-2：verify_package 4a 在沒有 .git 的安裝目錄改讀包內「不出貨清單」；建包端由 git 算出清單。

判準（使用者選定）：檢查保留、不自製 git 語意；有 .git ⇒ 仍是 git check-attr；無 .git＋清單 ⇒ 過；
清單裡的檔出現在包裡 ⇒ 紅；MUST_EXIST 的檔在清單裡 ⇒ 紅；包內缺清單／壞清單 ⇒ 紅（不是略過）。
"""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, TOOLS / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def vp(tmp_path, monkeypatch):
    mod = _load("_vp_t222", "verify_package.py")
    wt = tmp_path / "install"          # 沒有 .git 的「安裝目錄」
    wt.mkdir()
    monkeypatch.setattr(mod, "WT", str(wt))
    monkeypatch.setattr(mod, "R", mod.Report())
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    return mod


def _pkg(tmp_path, files=("backend/autostart.bat", "DEPLOY.md"), ignored=("docs/x.md",), write_list=True, raw=None):
    pkg = tmp_path / "pkg"
    for f in files:
        p = pkg / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    if write_list:
        (pkg / "backend").mkdir(parents=True, exist_ok=True)
        body = raw if raw is not None else json.dumps({"format": 1, "commit": "abc", "count": len(ignored), "paths": list(ignored)})
        (pkg / "backend" / "export_ignore.json").write_text(body, encoding="utf-8")
    return str(pkg)


def test_no_git_with_list_passes(vp, tmp_path):
    vp.check_exclusion_vs_must_exist(_pkg(tmp_path))
    assert vp.R.fails == []


def test_must_exist_file_in_the_list_fails(vp, tmp_path):
    vp.check_exclusion_vs_must_exist(_pkg(tmp_path, ignored=("DEPLOY.md",)))
    assert any("MUST_EXIST" in g for g, _ in vp.R.fails), vp.R.fails


def test_a_listed_file_present_in_the_package_fails(vp, tmp_path):
    vp.check_exclusion_vs_must_exist(_pkg(tmp_path, files=("backend/autostart.bat", "DEPLOY.md", "docs/x.md")))
    assert any("不出貨清單" in g for g, _ in vp.R.fails), vp.R.fails


@pytest.mark.parametrize("kw", [dict(write_list=False), dict(raw="not json"), dict(raw='{"format": 2, "count": 0, "paths": []}'),
                                dict(raw='{"format": 1, "count": 5, "paths": []}'), dict(raw="[1,2]"),
                                dict(raw='{"format": 1, "count": 1, "paths": [1]}')])
def test_missing_or_bad_list_fails_not_skipped(vp, tmp_path, kw):
    vp.check_exclusion_vs_must_exist(_pkg(tmp_path, **kw))
    assert vp.R.fails, "缺清單／壞清單必須是 FAIL，不是略過"


def test_a_missing_must_exist_file_still_fails(vp, tmp_path):
    vp.check_exclusion_vs_must_exist(_pkg(tmp_path, files=("DEPLOY.md",)))
    assert any("MUST_EXIST" in g for g, _ in vp.R.fails)


def test_with_a_dot_git_it_still_asks_git(vp, tmp_path, monkeypatch):
    """有 .git ⇒ 維持 git check-attr（行為不變）：不讀清單。"""
    (Path(vp.WT) / ".git").mkdir()
    calls = []
    monkeypatch.setattr(vp, "_export_ignore_state", lambda root, rel: (calls.append(rel) or ("unspecified", None)))
    vp.check_exclusion_vs_must_exist(_pkg(tmp_path, write_list=False))
    assert sorted(calls) == ["DEPLOY.md", "backend/autostart.bat"] and vp.R.fails == []


def test_builder_marks_exactly_what_git_archive_leaves_out(tmp_path, monkeypatch):
    """建包端：清單＝git 判定 export-ignore 的已追蹤檔；與 `git archive` 實際排除的一致。"""
    import io
    import tarfile
    ei = _load("_ei_t222", "export_ignore_list.py")
    repo = tmp_path / "r"
    (repo / "docs" / "deep").mkdir(parents=True)
    (repo / "keep").mkdir()
    for f in ("keep/a.py", "docs/x.md", "docs/deep/y.md", "DEPLOY.md", "top.md", "tests_only.txt"):
        (repo / f).write_text("x", encoding="utf-8")
    (repo / ".gitattributes").write_text("docs/ export-ignore\ndocs/** export-ignore\ntop.md export-ignore\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for a in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    d = ei.build(str(repo), "HEAD")
    tar = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", "HEAD"], capture_output=True, check=True).stdout
    shipped = {n for n in tarfile.open(fileobj=io.BytesIO(tar)).getnames() if not n.endswith("/")}
    tracked = set(subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", "HEAD"], capture_output=True, text=True,
                                 encoding="utf-8").stdout.split())
    assert set(d["paths"]) == tracked - shipped, (d["paths"], tracked - shipped)
    assert "docs/deep/y.md" in d["paths"] and "top.md" in d["paths"] and "DEPLOY.md" not in d["paths"]
    assert d["count"] == len(d["paths"]) and d["format"] == 1
