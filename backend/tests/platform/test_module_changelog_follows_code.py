"""G4：模組程式有改動，但 CHANGELOG 或版號沒跟著更新 ⇒ 紅（MODULE-GUIDE §6）。

判定（依 git 歷史，不依記憶）：
  程式檔＝modules/<key>/ 底下，扣掉 tests/、README.md、SPEC.md、CHANGELOG.md、module.json
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


def check_module(repo, rel_dir):
    """repo 內某個模組資料夾（repo 相對路徑）⇒ 問題清單。"""
    repo = Path(repo)
    d = repo / rel_dir
    spec = [rel_dir] + [":(exclude)%s/%s" % (rel_dir, x) for x in EXCLUDE]
    problems = []
    last_code = _git(repo, "log", "-1", "--format=%H", "--", *spec)
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
