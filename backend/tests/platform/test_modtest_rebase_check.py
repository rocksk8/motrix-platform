"""modtest --rebase-check（PLAYBOOK §C-11）：全量綠之後 rebase，判定要不要重跑全量。在 tmp 建合成 repo。"""
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
_spec = importlib.util.spec_from_file_location("_modtest_rc", REPO / "tools" / "platform" / "modtest.py")
MT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MT)


def _git(r, *args):
    return subprocess.run(["git", "-C", str(r), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout.strip()


def _write_commit(r, rel, text, msg):
    p = r / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git(r, "add", "--", rel)
    _git(r, "commit", "-q", "-m", msg, "--", rel)
    return _git(r, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    """base ─┬─ mine（backend/modules/m/api.py）＝全量綠的分支尖端
             └─ upstream（由各題往上疊）"""
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "platform")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    _write_commit(r, "backend/modules/m/api.py", "x = 1\n", "base")
    _write_commit(r, "backend/core/other.py", "y = 1\n", "base2")
    _git(r, "checkout", "-q", "-b", "mine")
    green = _write_commit(r, "backend/modules/m/api.py", "x = 2\n", "mine")
    _git(r, "checkout", "-q", "platform")
    return r, green


def test_unrelated_incoming_needs_only_diff_tests(repo):
    """正對照：帶進來的只碰別的檔、不碰 fixture 層 ⇒ 不用全量。"""
    r, green = repo
    _write_commit(r, "backend/modules/n/api.py", "z = 1\n", "他人")
    res = MT.rebase_check(green, "platform", repo=r)
    assert res["need_full"] is False and res["fixture_layer"] == [] and res["overlap"] == []
    assert res["incoming"] == ["backend/modules/n/api.py"]
    assert res["mine"] == ["backend/modules/m/api.py"]


@pytest.mark.parametrize("rel", MT.FIXTURE_LAYER)
def test_rc_incoming_fixture_layer_needs_full(repo, rel):
    """反向控制：帶進來的碰到任一 fixture 層檔 ⇒ 全量。"""
    r, green = repo
    _write_commit(r, rel, "# changed\n", "他人改 fixture 層")
    res = MT.rebase_check(green, "platform", repo=r)
    assert res["need_full"] is True and res["fixture_layer"] == [rel]


def test_rc_same_file_on_both_sides_needs_full(repo):
    """反向控制：兩邊改了同一個檔（即使 git 能自動合併）⇒ 全量。"""
    r, green = repo
    _write_commit(r, "backend/modules/m/api.py", "x = 1\n# 他人加註解\n", "他人改同檔")
    res = MT.rebase_check(green, "platform", repo=r)
    assert res["need_full"] is True and res["overlap"] == ["backend/modules/m/api.py"]


def test_same_doc_on_both_sides_is_listed_but_not_full(repo):
    """兩邊都改同一份 .md ⇒ 列在 overlap_docs、不判全量（程式檔同檔的對照見 test_rc_same_file_on_both_sides_needs_full）。"""
    r, green0 = repo
    _git(r, "checkout", "-q", "mine")
    green = _write_commit(r, "docs/SPEC.md", "mine\n", "我改文件")
    _git(r, "checkout", "-q", "platform")
    _write_commit(r, "docs/SPEC.md", "theirs\n", "他人改文件")
    res = MT.rebase_check(green, "platform", repo=r)
    assert res["need_full"] is False and res["overlap_docs"] == ["docs/SPEC.md"] and res["overlap"] == []


def test_my_own_fixture_change_is_not_counted_as_incoming(repo):
    """本分支自己改 fixture 層：已在 green 的全量裡驗過 ⇒ 不因此判全量（帶進來的才算）。"""
    r, green = repo
    _git(r, "checkout", "-q", "mine")
    green2 = _write_commit(r, "backend/conftest.py", "# mine\n", "我改 conftest")
    _git(r, "checkout", "-q", "platform")
    _write_commit(r, "backend/modules/n/api.py", "z = 1\n", "他人")
    res = MT.rebase_check(green2, "platform", repo=r)
    assert res["need_full"] is False
    assert "backend/conftest.py" in res["mine"]


def test_cli_exit_code_follows_the_verdict(repo, monkeypatch, capsys):
    r, green = repo
    monkeypatch.setattr(MT, "REPO", r)
    _write_commit(r, "backend/pytest.ini", "[pytest]\n", "他人改 pytest.ini")
    assert MT.main(["--rebase-check", green, "--onto", "platform"]) == 3
    assert "重跑全量" in capsys.readouterr().out


def test_cli_recommends_changed_since_green(repo, monkeypatch, capsys):
    """不需全量時建議 `--changed-since <green>`：`--base <onto>` 在本分支自己改過 fixture 層時會被 modtest 拒絕
    （2026-09-26 實際踩到）。"""
    r, green = repo
    monkeypatch.setattr(MT, "REPO", r)
    _write_commit(r, "backend/modules/n/api.py", "z = 1\n", "他人")
    assert MT.main(["--rebase-check", green, "--onto", "platform"]) == 0
    out = capsys.readouterr().out
    assert "modtest --changed-since %s" % green in out and "--base" not in out
