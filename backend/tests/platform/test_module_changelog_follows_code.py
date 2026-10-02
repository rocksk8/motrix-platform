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
#: 最上面的條目：「## X.Y.Z」或版號佔位「## (next…)」（PLAYBOOK §G6：分支不取號，列車 train_number.py 取號；
#: 佔位也算「有寫條目」——准不准有佔位由 test_version_slots 另守）
_TOP = re.compile(r"^##[ \t]+(?:(\d+\.\d+\.\d+)\b|\(next(?::(?:patch|minor|major))?\)).*$", re.M)


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


def heading_commit(repo, version, path):
    """CHANGELOG 版號標題「## x.y.z」被寫進去的 commit（沿第一親代那條主線）；找不到 ⇒ ""。

    ⚠️ 不能用預設的 `git log -S`：它**不看 merge commit 的變動**。列車合併多條分支時，版號撞號（兩條分支各自取了同一號）
    會在 merge 的解衝突裡重編（把後合的改成下一號）——那個標題只存在於 merge commit 裡 ⇒ 找不到 ⇒ 誤報「還沒提交」
    （2026-09-30 一天內第三次，每次都靠「暫名→改回」兩個一般 commit 繞過＝修結果不修作法）。
    `-m --first-parent`：merge 也對**第一親代**做 diff，且只沿主線走；分支上的各個 commit 併入主線時，標題出現的那一刻就是那次 merge。
    原意不變：回傳的 commit 之後，程式不可以再有改動（由呼叫端的 is-ancestor 檢查）。"""
    return _git(repo, "log", "-1", "-m", "--first-parent", "--format=%H", "-S", "## " + version, "--", path)


def placeholder_commit(repo, heading_line, path):
    """佔位標題（整行，含日期與分支 ⇒ 幾乎唯一）被寫進去的 commit；找法同 heading_commit。找不到 ⇒ ""。"""
    return _git(repo, "log", "-1", "-m", "--first-parent", "--format=%H", "-S", heading_line, "--", path)


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
            problems.append("有程式改動，但 CHANGELOG.md 沒有「## X.Y.Z」版號條目（或 `## (next)` 佔位）")
        else:
            label = top.group(1) or top.group(0).rstrip()
            if top.group(1):
                entry = heading_commit(repo, top.group(1), "%s/CHANGELOG.md" % rel_dir)
            else:
                entry = placeholder_commit(repo, top.group(0).rstrip(), "%s/CHANGELOG.md" % rel_dir)
            if not entry:
                problems.append("CHANGELOG 最上面的 %s 還沒提交" % label)
            elif subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", last_code, entry]).returncode != 0:
                problems.append("最後一次程式改動 %s 之後沒有新的版號條目（最上面仍是 %s，寫於 %s）"
                                % (last_code[:8], label, entry[:8]))
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


# ── 合併內重編版號（列車撞號）：不紅；真的沒升版仍紅 ──────────────────────────────────────

def _branch(r):
    return _git(r, "symbolic-ref", "--short", "HEAD")


def _collide(repo, resolved_changelog, feat_bumps=True):
    """main 與 feat 各自在同一處新增「## 1.0.1」標題（撞號）；把 feat 合進 main，衝突的 CHANGELOG 以 `resolved_changelog` 解掉。
    feat 另外改了 api.py（程式）。回傳 merge commit。"""
    main = _branch(repo)
    _git(repo, "checkout", "-q", "-b", "feat")
    (repo / "mod" / "api.py").write_text("x = 'feat'\n", encoding="utf-8")
    if feat_bumps:
        (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n## 1.0.1 — feat\n- feat 的改動\n\n## 1.0.0 — d\n- 初版\n", encoding="utf-8")
    _commit(repo, "feat")
    _git(repo, "checkout", "-q", main)
    (repo / "mod" / "b.py").write_text("y = 1\n", encoding="utf-8")
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n## 1.0.1 — main\n- main 的改動\n\n## 1.0.0 — d\n- 初版\n", encoding="utf-8")
    _commit(repo, "main")
    r = subprocess.run(["git", "-C", str(repo), "merge", "--no-ff", "-q", "feat", "-m", "merge feat"], capture_output=True, text=True)
    if r.returncode != 0:                                   # 撞號 ⇒ CHANGELOG 衝突
        (repo / "mod" / "CHANGELOG.md").write_text(resolved_changelog, encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "--no-edit")
    return _git(repo, "rev-parse", "HEAD")


RENUMBERED = ("# m\n\n## 1.0.2 — feat（合併時重編）\n- feat 的改動\n\n## 1.0.1 — main\n- main 的改動\n\n## 1.0.0 — d\n- 初版\n")


def test_rc_renumbering_inside_a_merge_is_not_red(repo):
    """列車：兩條分支撞號，merge 的解衝突把後合的重編成 1.0.2 ⇒ 標題只存在於 merge commit 裡；不可以誤報「還沒提交」。"""
    m = _collide(repo, RENUMBERED)
    assert _git(repo, "log", "-1", "--format=%H", "-S", "## 1.0.2", "--", "mod/CHANGELOG.md") == "", \
        "前提：預設的 git log -S 看不到 merge 裡的變動（這正是舊守門誤報的原因）"
    assert heading_commit(repo, "1.0.2", "mod/CHANGELOG.md") == m
    assert check_module(repo, "mod") == []


def test_rc_merge_that_brings_code_without_any_new_heading_is_still_red(repo):
    """反向控制：feat 改了程式、卻沒有任何人為它升版（解衝突時把 feat 的標題丟掉）⇒ 仍紅。"""
    only_main = "# m\n\n## 1.0.1 — main\n- main 的改動\n\n## 1.0.0 — d\n- 初版\n"
    _collide(repo, only_main)
    assert any("之後沒有新的版號條目" in p for p in check_module(repo, "mod"))


def test_rc_code_change_after_the_renumbering_merge_is_still_red(repo):
    """合併重編之後又改了程式、沒再升版 ⇒ 紅（原意：程式改動之後必須有新版號標題）。"""
    _collide(repo, RENUMBERED)
    (repo / "mod" / "api.py").write_text("x = 'after merge'\n", encoding="utf-8")
    _commit(repo, "合併後又改程式")
    assert any("之後沒有新的版號條目" in p for p in check_module(repo, "mod"))
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n## 1.0.3 — d\n\n" + RENUMBERED[len("# m\n\n"):], encoding="utf-8")
    _commit(repo, "補版號")
    assert check_module(repo, "mod") == []


def test_rc_linear_history_behaves_as_before(repo):
    """沒有 merge 的線性歷史：結果與改動前相同（既有題另守；這裡多驗一次 heading_commit 在線性歷史找得到）。"""
    (repo / "mod" / "api.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n## 1.0.1 — d\n\n## 1.0.0 — d\n", encoding="utf-8")
    _commit(repo, "程式＋版號同一個 commit")
    assert heading_commit(repo, "1.0.1", "mod/CHANGELOG.md") == _git(repo, "rev-parse", "HEAD")
    assert check_module(repo, "mod") == []


# ── 版號佔位（PLAYBOOK §G6）：`## (next)` 也算有條目；時間順序照舊驗 ──────────────────────────

NEXT_HEAD = "## (next) — 2026-09-30（wip/x）"


def test_rc_placeholder_heading_after_code_passes(repo):
    (repo / "mod" / "api.py").write_text("x = 2\n", encoding="utf-8")
    _commit(repo, "改程式")
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n%s\n- 修正\n\n## 1.0.0 — d\n- 初版\n" % NEXT_HEAD, encoding="utf-8")
    _commit(repo, "寫佔位條目")
    assert check_module(repo, "mod") == []


def test_rc_code_change_after_placeholder_is_still_red(repo):
    """反向控制：佔位寫完之後又改程式 ⇒ 紅（佔位不是免死金牌）。"""
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n%s\n- 修正\n\n## 1.0.0 — d\n- 初版\n" % NEXT_HEAD, encoding="utf-8")
    _commit(repo, "先寫佔位")
    (repo / "mod" / "api.py").write_text("x = 3\n", encoding="utf-8")
    _commit(repo, "再改程式")
    assert any("之後沒有新的版號條目" in p and "(next)" in p for p in check_module(repo, "mod"))


def test_rc_malformed_placeholder_does_not_count(repo):
    """反向控制：`## (Next)` 不是佔位 ⇒ 最上面的條目仍是舊的 1.0.0 ⇒ 紅。"""
    (repo / "mod" / "api.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n## (Next) — d\n- 修正\n\n## 1.0.0 — d\n- 初版\n", encoding="utf-8")
    _commit(repo, "寫錯的佔位")
    assert any("最上面仍是 1.0.0" in p for p in check_module(repo, "mod"))


def test_rc_train_numbering_commit_counts_as_the_entry(repo):
    """列車取號（佔位 ⇒ 1.0.1，單獨一個 commit）之後：1.0.1 標題寫於程式改動之後 ⇒ 不紅。"""
    (repo / "mod" / "api.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n%s\n- 修正\n\n## 1.0.0 — d\n- 初版\n" % NEXT_HEAD, encoding="utf-8")
    _commit(repo, "分支：程式＋佔位")
    (repo / "mod" / "CHANGELOG.md").write_text("# m\n\n## 1.0.1 — 2026-09-30（wip/x）\n- 修正\n\n## 1.0.0 — d\n- 初版\n", encoding="utf-8")
    _commit(repo, "列車取號")
    assert check_module(repo, "mod") == []
