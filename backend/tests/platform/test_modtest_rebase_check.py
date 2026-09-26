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
    assert res["high_impact"] is False and res["fixture_layer"] == [] and res["overlap"] == []
    assert res["incoming"] == ["backend/modules/n/api.py"]
    assert res["mine"] == ["backend/modules/m/api.py"]


@pytest.mark.parametrize("rel", MT.FIXTURE_LAYER)
def test_rc_incoming_fixture_layer_needs_full(repo, rel):
    """反向控制：帶進來的碰到任一 fixture 層檔 ⇒ 全量。"""
    r, green = repo
    _write_commit(r, rel, "# changed\n", "他人改 fixture 層")
    res = MT.rebase_check(green, "platform", repo=r)
    assert res["high_impact"] is True and res["fixture_layer"] == [rel]


def test_rc_same_file_on_both_sides_needs_full(repo):
    """反向控制：兩邊改了同一個檔（即使 git 能自動合併）⇒ 全量。"""
    r, green = repo
    _write_commit(r, "backend/modules/m/api.py", "x = 1\n# 他人加註解\n", "他人改同檔")
    res = MT.rebase_check(green, "platform", repo=r)
    assert res["high_impact"] is True and res["overlap"] == ["backend/modules/m/api.py"]


def test_same_doc_on_both_sides_is_listed_but_not_full(repo):
    """兩邊都改同一份 .md ⇒ 列在 overlap_docs、不判全量（程式檔同檔的對照見 test_rc_same_file_on_both_sides_needs_full）。"""
    r, green0 = repo
    _git(r, "checkout", "-q", "mine")
    green = _write_commit(r, "docs/SPEC.md", "mine\n", "我改文件")
    _git(r, "checkout", "-q", "platform")
    _write_commit(r, "docs/SPEC.md", "theirs\n", "他人改文件")
    res = MT.rebase_check(green, "platform", repo=r)
    assert res["high_impact"] is False and res["overlap_docs"] == ["docs/SPEC.md"] and res["overlap"] == []


def test_my_own_fixture_change_is_not_counted_as_incoming(repo):
    """本分支自己改 fixture 層：已在 green 的全量裡驗過 ⇒ 不因此判全量（帶進來的才算）。"""
    r, green = repo
    _git(r, "checkout", "-q", "mine")
    green2 = _write_commit(r, "backend/conftest.py", "# mine\n", "我改 conftest")
    _git(r, "checkout", "-q", "platform")
    _write_commit(r, "backend/modules/n/api.py", "z = 1\n", "他人")
    res = MT.rebase_check(green2, "platform", repo=r)
    assert res["high_impact"] is False
    assert "backend/conftest.py" in res["mine"]


def test_cli_exit_code_follows_the_verdict(repo, monkeypatch, capsys):
    r, green = repo
    monkeypatch.setattr(MT, "REPO", r)
    _write_commit(r, "backend/pytest.ini", "[pytest]\n", "他人改 pytest.ini")
    assert MT.main(["--rebase-check", green, "--onto", "platform"]) == 3
    out = capsys.readouterr().out
    assert "全量交給列車" in out and "§G3" in out, out


def _rebased(r, green, after=()):
    """模擬 rebase：從 platform 開 `rebased` 分支、疊上 green 的改動，再疊 after＝[(路徑, 內容)]（全量之後才改的）。"""
    _git(r, "checkout", "-q", "-b", "rebased", "platform")
    _git(r, "cherry-pick", green)
    for rel, text in after:
        _write_commit(r, rel, text, "全量之後又改")
    return _git(r, "rev-parse", "HEAD")


def test_after_green_is_only_my_changes_since_the_full(repo):
    """after_green＝全量之後本分支才改的檔；帶進來的（已由對方驗過）與全量裡驗過的都不在其中。"""
    r, green = repo
    _write_commit(r, "backend/modules/n/api.py", "z = 1\n", "他人")
    head = _rebased(r, green, after=[("backend/tests/test_x.py", "t = 1\n")])
    res = MT.rebase_check(green, "platform", repo=r, head=head)
    assert res["high_impact"] is False
    assert res["after_green"] == ["backend/tests/test_x.py"]


def test_rc_incoming_file_touched_again_after_green_needs_full(repo):
    """反向控制：全量之後本分支又改了一個帶進來的檔 ⇒ 那是沒被任何人驗過的組合 ⇒ 全量。"""
    r, green = repo
    _write_commit(r, "backend/modules/n/api.py", "z = 1\n", "他人")
    head = _rebased(r, green, after=[("backend/modules/n/api.py", "z = 2\n")])
    res = MT.rebase_check(green, "platform", repo=r, head=head)
    assert res["high_impact"] is True and res["overlap"] == ["backend/modules/n/api.py"]


def test_rc_before_rebase_gives_no_recommendation(repo, monkeypatch, capsys):
    """反向控制：rebase 之前跑（head 還是 green）⇒ after_green 必然是空的、不可信 ⇒ 不給建議、exit 2。"""
    r, green = repo
    monkeypatch.setattr(MT, "REPO", r)
    _write_commit(r, "backend/modules/n/api.py", "z = 1\n", "他人")
    res = MT.rebase_check(green, "platform", repo=r, head=green)
    assert res["rebased"] is False
    _git(r, "checkout", "-q", "mine")
    assert MT.main(["--rebase-check", green, "--onto", "platform"]) == 2
    out = capsys.readouterr().out
    assert "先 rebase" in out and "判定：跑" not in out


def test_cli_recommends_files_after_green(repo, monkeypatch, capsys):
    """不需全量時建議 `modtest --files <after_green>`。
    ☠️ `--base <onto>`：本分支自己改過 fixture 層時一定被 modtest 拒絕；`--changed-since <green>`：把帶進來的也算進去，
    對方改到 L0 時挑出九成（2026-09-26 兩者都實際踩到）。"""
    r, green = repo
    monkeypatch.setattr(MT, "REPO", r)
    _write_commit(r, "backend/modules/n/api.py", "z = 1\n", "他人")
    _rebased(r, green, after=[("backend/tests/test_x.py", "t = 1\n")])
    assert MT.main(["--rebase-check", green, "--onto", "platform"]) == 0
    out = capsys.readouterr().out
    assert "modtest --files backend/tests/test_x.py" in out
    assert "--base" not in out and "--changed-since" not in out


def test_rebase_check_never_tells_a_line_to_run_the_full_suite(repo, capsys):
    """§G3（主持 2026-09-26）：全量只由列車跑。影響大（fixture 層＋同檔）時也只建議差異題，輸出不出現「重跑全量」、建議指令不帶 --full。"""
    r, green = repo
    fx = MT.FIXTURE_LAYER[0]
    _write_commit(r, fx, "# changed\n", "他人改 fixture 層")
    _write_commit(r, "backend/modules/m/api.py", "x = 3\n", "他人改同檔")
    res = MT.rebase_check(green, "platform", repo=r)
    assert res["high_impact"] is True and res["fixture_layer"] == [fx]
    assert "--full" not in res["suggest"] and "--files" in res["suggest"]
    assert fx not in res["suggest"], "fixture 層檔放進 --files 會讓 modtest 拒絕縮小"
    assert "backend/modules/m/api.py" in res["suggest"], "兩邊都改的檔要進差異題"
    MT.print_rebase_check(dict(res, rebased=True))
    out = capsys.readouterr().out
    assert "重跑全量" not in out and "--full" not in out, out
    assert "不要自己跑全量" in out and "全量交給列車" in out, out


def test_own_fixture_layer_change_runs_the_diff_and_does_not_ask_for_full(monkeypatch, capsys):
    """§G3：本分支自己動到 fixture 層 ⇒ 差異題照跑、輸出不叫人跑全量；閘門過了回 3（月台要註明、排車頭）。"""
    ran = []
    monkeypatch.setattr(MT, "run_pytest", lambda picked, *a, **k: (ran.append(list(picked)) or 0, None))
    monkeypatch.setattr(MT, "record_stats", lambda *a, **k: None)
    monkeypatch.setattr(MT, "resolve_python", lambda *a, **k: sys.executable)
    code = MT.main(["--files", MT.FIXTURE_LAYER[0], "backend/core/menu.py"])
    out = capsys.readouterr().out
    assert ran, "差異題沒有跑"
    assert "--full" not in out and "須全量" not in out, out
    assert "全量交給列車" in out and "§G3" in out, out
    assert code == 3
