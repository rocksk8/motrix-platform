# -*- coding: utf-8 -*-
"""tools/platform/module_rc_scope.py：單一模組真刪的選題（PLAYBOOK §B-11；B，2026-09-28）。

① 正對照（真實的樹）：M01 真刪漏掉的 11 題（accounting 傳票 e2e：自己塞 quotations、點 src-case，
   一個字都沒提到 modules/case）所在的 4 個檔，必須以「table」條件被選到；11 個題名仍在那些檔裡（改名時對照要跟著改，不可以靜默失效）。
② 反向控制（合成的樹）：五種條件各一個檔會被選到；字面相近的表名、模組自己的 tests/、無關的檔不選；
   模組資料夾不在（sparse 樹）時 module.json 改從 git HEAD 讀；工作樹與 HEAD 都沒有 ⇒ 找不到（不猜）。
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import module_rc_scope as S  # noqa: E402
from tests._requires import requires_module  # noqa: E402

#: M01 真刪（B41，2026-09-28）漏掉的 11 題：{檔: [題名]}
MISSED_BY_M01_RC = {
    "modules/accounting/tests/test_jv36_voucher_line_source_files_2026_09_24.py": [
        "test_second_expense_on_the_same_line_brings_its_own_amount",
        "test_auto_amount_does_not_linger_after_switching_to_a_case_or_an_expense_without_amount",
        "test_o13_late_focus_move_does_not_steal_the_field_the_user_moved_to",
        "test_o13_focus_still_returns_to_the_summary_when_the_user_stays"],
    "modules/accounting/tests/test_e2e_voucher_summary_2026_09_23.py": [
        "test_jv7_an_edited_summary_survives_a_tab_switch",
        "test_jv7_an_edited_summary_survives_a_reload"],
    "modules/accounting/tests/test_e2e_voucher_summary_panel_side_by_side_2026_09_25.py": [
        "test_picking_a_case_keeps_the_focus_on_that_lines_summary"],
    "modules/accounting/tests/test_jv33_voucher_summary_panel_2026_09_24.py": [
        "test_jv33_focusing_a_summary_shows_files_and_expenses_together",
        "test_jv33_clicking_a_source_overwrites_the_summary_instead_of_appending",
        "test_jv33_the_thumbnail_previews_without_touching_the_summary",
        "test_jv33_the_expense_section_says_loading_while_sources_are_in_flight"],
}


@requires_module("accounting", "讀 modules/accounting/tests/ 裡那幾題的原始碼（M01 真刪漏選的對照題）；模組不在時沒有對象")
@requires_module("case", "選題對象是 case（讀 case 的 module.json）；模組不在時工具的行為由本檔合成樹的反向控制覆蓋")
def test_positive_control_the_eleven_tests_missed_by_the_m01_rc_are_selected():
    found, rows = S.select(REPO, "case")
    assert found
    got = dict(rows)
    assert rows[0] == ("tests/platform", ["always"])
    for rel, names in MISSED_BY_M01_RC.items():
        src = (REPO / "backend" / rel).read_text(encoding="utf-8")
        for n in names:
            assert "def %s(" % n in src, "對照題改名或搬走了：%s::%s ⇒ 更新 MISSED_BY_M01_RC" % (rel, n)
        assert rel in got and "table" in got[rel], (rel, got.get(rel))
    assert not any(r.startswith("modules/case/") for r in got), "模組自己的 tests/ 跟著模組一起不在，不列"


# ── 反向控制：合成的樹 ─────────────────────────────────────────────────────────

def _w(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _synthetic(tmp_path):
    b = tmp_path / "backend"
    _w(b / "modules" / "zz" / "module.json", json.dumps({
        "key": "zz", "provides": {"api_prefixes": ["/api/zz-items"]},
        "data": {"tables": [{"name": "zz_items", "class": "T1"}]}}))
    _w(b / "modules" / "zz" / "tests" / "test_own.py", "def test_x():\n    assert 'modules.zz'\n")
    _w(b / "conftest.py", "import pytest\n\n@pytest.fixture\ndef seed_zz():\n    conn.execute('INSERT INTO zz_items VALUES (1)')\n\n"
                          "@pytest.fixture\ndef other():\n    return 1\n")
    t = b / "tests"
    _w(t / "platform" / "test_p.py", "def test_p():\n    pass\n")
    _w(t / "test_path.py", "from modules.zz import api\n")
    _w(t / "test_mark.py", "pytestmark = requires_module('zz', 'x')\n")
    _w(t / "test_api.py", "def test_a(client):\n    client.get('/api/zz-items/1')\n")
    _w(b / "modules" / "acc" / "tests" / "test_table.py", "def test_t():\n    conn.execute(\"INSERT INTO zz_items (id) VALUES (1)\")\n")
    _w(t / "test_fixture.py", "def test_f(seed_zz):\n    pass\n")
    _w(t / "test_lookalike.py", "def test_l(other):\n    conn.execute('SELECT * FROM zz_items_archive')\n    get('/api/zz-items-v2')\n")
    _w(t / "test_unrelated.py", "def test_u():\n    pass\n")
    return tmp_path


def test_reverse_control_each_signal_selects_and_lookalikes_do_not(tmp_path):
    found, rows = S.select(_synthetic(tmp_path), "zz")
    assert found
    assert dict(rows) == {
        "tests/platform": ["always"],
        "tests/test_path.py": ["path"],
        "tests/test_mark.py": ["mark"],
        "tests/test_api.py": ["api"],
        "modules/acc/tests/test_table.py": ["table"],
        "tests/test_fixture.py": ["fixture"],
    }, rows


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_sparse_tree_reads_the_manifest_from_git_head_and_missing_means_not_found(tmp_path):
    repo = _synthetic(tmp_path)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    for p in sorted((repo / "backend" / "modules" / "zz").rglob("*"), reverse=True):     # 模擬 sparse 樹：資料夾不在
        p.unlink() if p.is_file() else p.rmdir()
    (repo / "backend" / "modules" / "zz").rmdir()
    found, rows = S.select(repo, "zz")
    assert found and "modules/acc/tests/test_table.py" in dict(rows)
    found, rows = S.select(repo, "nope")
    assert (found, rows) == (False, [])
