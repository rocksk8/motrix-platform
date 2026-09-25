"""G4：模組程式有改動，但 CHANGELOG 或版號沒跟著更新 ⇒ 紅（MODULE-GUIDE §6）。

判定（依 git 歷史，不依記憶）：
  程式檔＝modules/<key>/ 底下，扣掉 tests/、README.md、SPEC.md、CHANGELOG.md、module.json；
         **加上** module.json 宣告的頁面 frontend/pages/<path>，以及 module.json 除了 version 以外的任何欄位（稽核 G-4）
  ① 已提交：最後一次改程式的 commit，必須是「CHANGELOG 最上面那個版號被寫進去」的 commit 本身或其祖先
     ——也就是說，版號條目是在程式改動之後（或同一個 commit）才加的
  ② 未提交：工作樹裡程式檔有改動，而 CHANGELOG.md 沒有改動 ⇒ 紅
module.json 的 version＝CHANGELOG 最上面的版號，由 G2 守。
⚠ 版本「升的幅度」是否合理（修正／新增／不相容）不在這裡判斷。
"""
import re
import subprocess
from pathlib import Path

import pytest

from core import source_tree

EXCLUDE = ("tests", "README.md", "SPEC.md", "CHANGELOG.md", "module.json")
_TOP = re.compile(r"^##\s+(\d+\.\d+\.\d+)\b", re.M)


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError("git %s 失敗：%s" % (" ".join(args), r.stderr.strip()))
    return r.stdout.strip()


def _manifest_at(repo, commit, path):
    try:
        import json
        return json.loads(_git(repo, "show", "%s:%s" % (commit, path)))
    except (RuntimeError, ValueError):
        return None


def _without_version(m):
    return {k: v for k, v in (m or {}).items() if k != "version"}


def last_manifest_change(repo, path):
    """module.json 最後一次「version 以外」有改動的 commit（新增也算）；沒有 ⇒ ""。"""
    for c in _git(repo, "log", "--format=%H", "--", path).split():
        parents = _git(repo, "log", "-1", "--format=%P", c).split()
        before = _manifest_at(repo, parents[0], path) if parents else None
        if _without_version(_manifest_at(repo, c, path)) != _without_version(before):
            return c
    return ""


def _newer(repo, a, b):
    """兩個 commit 取較新的一個（一方是另一方的祖先 ⇒ 取後代；空字串視為不存在）。"""
    if not a or not b:
        return a or b
    if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b]).returncode == 0:
        return b
    return a


def check_module(repo, rel_dir):
    """repo 內某個模組資料夾（repo 相對路徑）⇒ 問題清單。"""
    import json
    repo = Path(repo)
    d = repo / rel_dir
    manifest = json.loads((d / "module.json").read_text(encoding="utf-8")) if (d / "module.json").is_file() else {}
    pages = ["frontend/pages/%s" % p["path"] for p in manifest.get("pages", [])]
    spec = [rel_dir] + [":(exclude)%s/%s" % (rel_dir, x) for x in EXCLUDE] + pages
    problems = []
    last_code = _newer(repo, _git(repo, "log", "-1", "--format=%H", "--", *spec),
                       last_manifest_change(repo, "%s/module.json" % rel_dir))
    cl = d / "CHANGELOG.md"
    top = _TOP.search(cl.read_text(encoding="utf-8")) if cl.is_file() else None
    if last_code:
        if top is None:
            problems.append("有程式改動，但 CHANGELOG.md 沒有「## X.Y.Z」版號條目")
        else:
            entry = _git(repo, "log", "-1", "--format=%H", "-S", "## " + top.group(1), "--",
                         "%s/CHANGELOG.md" % rel_dir)
            if not entry:
                problems.append("CHANGELOG 最上面的 %s 還沒提交" % top.group(1))
            elif subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", last_code, entry]).returncode != 0:
                problems.append("最後一次程式改動 %s 之後沒有新的版號條目（最上面仍是 %s，寫於 %s）"
                                % (last_code[:8], top.group(1), entry[:8]))
    dirty = _git(repo, "status", "--porcelain", "--", *spec)
    head_manifest = _manifest_at(repo, "HEAD", "%s/module.json" % rel_dir)
    if head_manifest is not None and _without_version(manifest) != _without_version(head_manifest):
        dirty = (dirty + "\n" if dirty else "") + " M %s/module.json（version 以外的欄位）" % rel_dir
    if dirty and not _git(repo, "status", "--porcelain", "--", "%s/CHANGELOG.md" % rel_dir):
        problems.append("工作樹有未提交的程式改動，而 CHANGELOG.md 沒有更新：\n    " + dirty.replace("\n", "\n    "))
    return problems


def test_every_module_changelog_follows_its_code():
    repo = source_tree.BACKEND.parent
    dirs = source_tree.module_dirs()
    if not dirs:
        pytest.skip("沒有任何已安裝模組 ⇒ 無對象")
    bad = {d.name: check_module(repo, d.relative_to(repo).as_posix()) for d in dirs}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, "模組改了程式卻沒更新 CHANGELOG／版號：\n" + "\n".join(
        "  %s：%s" % (k, "；".join(v)) for k, v in sorted(bad.items()))


# ── 反向控制：tmp 裡的合成 git repo ──────────────────────────────────────────

@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    m = r / "mod"
    (m / "tests").mkdir(parents=True)
    (m / "api.py").write_text("x = 1\n", encoding="utf-8")
    (m / "CHANGELOG.md").write_text("# m\n\n## 1.0.0 — d\n- 初版\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "init")
    return r


def _commit(r, msg):
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", msg)


def test_rc_initial_state_is_clean(repo):
    assert check_module(repo, "mod") == []


def test_rc_code_change_without_changelog_is_caught(repo):
    (repo / "mod" / "api.py").write_text("x = 2\n", encoding="utf-8")
    _commit(repo, "改程式")
    assert any("之後沒有新的版號條目" in p for p in check_module(repo, "mod"))


def test_rc_code_then_new_version_entry_passes(repo):
    (repo / "mod" / "api.py").write_text("x = 2\n", encoding="utf-8")
    _commit(repo, "改程式")
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n## 1.0.1 — d\n- 修正\n\n## 1.0.0 — d\n", encoding="utf-8")
    _commit(repo, "寫版號")
    assert check_module(repo, "mod") == []


def test_rc_editing_changelog_without_new_version_does_not_count(repo):
    """只改 CHANGELOG 文字、沒有新增版號 ⇒ 仍然紅（比的是版號條目寫進去的時間，不是檔案最後修改）。"""
    (repo / "mod" / "api.py").write_text("x = 2\n", encoding="utf-8")
    _commit(repo, "改程式")
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n## 1.0.0 — d\n- 初版（補字）\n", encoding="utf-8")
    _commit(repo, "只改描述")
    assert any("之後沒有新的版號條目" in p for p in check_module(repo, "mod"))


def test_rc_tests_and_docs_changes_do_not_need_a_version(repo):
    (repo / "mod" / "tests" / "test_x.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    (repo / "mod" / "README.md").write_text("# 說明\n", encoding="utf-8")
    _commit(repo, "只動測試與說明")
    assert check_module(repo, "mod") == []


def test_rc_uncommitted_code_change_is_caught(repo):
    (repo / "mod" / "api.py").write_text("x = 3\n", encoding="utf-8")
    assert any("未提交的程式改動" in p for p in check_module(repo, "mod"))
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n## 1.0.1 — d\n\n## 1.0.0 — d\n", encoding="utf-8")
    assert not any("未提交的程式改動" in p for p in check_module(repo, "mod"))



# ── 稽核 G-4 的反向控制：頁面與 module.json ─────────────────────────────────

def _add_manifest_and_page(repo):
    import json
    (repo / "mod" / "module.json").write_text(json.dumps({"key": "mod", "version": "1.0.0",
                                                          "pages": [{"path": "mod.html"}]}), encoding="utf-8")
    (repo / "frontend" / "pages").mkdir(parents=True)
    (repo / "frontend" / "pages" / "mod.html").write_text("<p>v1</p>\n", encoding="utf-8")
    _commit(repo, "manifest＋page")
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n## 1.0.1 — d\n\n## 1.0.0 — d\n", encoding="utf-8")
    _commit(repo, "版號")


def test_rc_page_change_without_changelog_is_caught(repo):
    """稽核 B4：改模組宣告的頁面並 commit，沒有新版號 ⇒ 紅。"""
    _add_manifest_and_page(repo)
    assert check_module(repo, "mod") == []
    (repo / "frontend" / "pages" / "mod.html").write_text("<p>v2</p>\n", encoding="utf-8")
    _commit(repo, "改頁面")
    assert any("之後沒有新的版號條目" in p for p in check_module(repo, "mod"))


def test_rc_manifest_change_other_than_version_is_caught(repo):
    """稽核 B4b：改 module.json 的 permissions 等欄位並 commit ⇒ 紅；只改 version 不算程式改動。"""
    import json
    _add_manifest_and_page(repo)
    mp = repo / "mod" / "module.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    mp.write_text(json.dumps(dict(m, permissions=["x"])), encoding="utf-8")
    _commit(repo, "改權限")
    assert any("之後沒有新的版號條目" in p for p in check_module(repo, "mod"))
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n## 1.0.2 — d\n\n## 1.0.1 — d\n", encoding="utf-8")
    mp.write_text(json.dumps(dict(m, permissions=["x"], version="1.0.2")), encoding="utf-8")
    _commit(repo, "補版號")
    assert check_module(repo, "mod") == []


def test_rc_uncommitted_manifest_change_is_caught(repo):
    import json
    _add_manifest_and_page(repo)
    mp = repo / "mod" / "module.json"
    mp.write_text(json.dumps(dict(json.loads(mp.read_text(encoding="utf-8")), provides={"a": 1})), encoding="utf-8")
    assert any("未提交的程式改動" in p for p in check_module(repo, "mod"))
