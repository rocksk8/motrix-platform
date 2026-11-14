# -*- coding: utf-8 -*-
"""T87：文字前後對照表產生器（tools/platform/text_diff_table.py）的契約題。拋棄式 git repo，不碰真的 repo。"""
import importlib.util
import subprocess
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[3] / "tools" / "platform" / "text_diff_table.py"


@pytest.fixture(scope="module")
def tdt():
    spec = importlib.util.spec_from_file_location("_text_diff_table_under_test", str(TOOL))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True,
                   capture_output=True, text=True, encoding="utf-8")


def _put(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def test_classify_sections_and_exclusions(tdt):
    c = tdt.classify
    assert c("backend/helpers/a.py") == "後端訊息／通知"
    assert c("backend/modules/x/module.json") == "後端訊息／通知"
    assert c("frontend/pages/a.html") == "前端畫面" and c("frontend/js/a.js") == "前端畫面"
    assert c("docs/platform/guides/G.md") == "說明文件"
    # 不收
    assert c("backend/tests/test_a.py") is None and c("backend/modules/x/tests/a.py") is None
    assert c("tools/platform/a.py") is None and c("backend/modules/x/CHANGELOG.md") is None
    assert c("docs/platform/UNIT-INDEX.md") is None and c("backend/version_manifest.json") is None
    assert c("backend/helpers/quote_pdf.py") is None and c("frontend/js/export_x.js") is None


def test_changed_phrase_gets_context_and_ellipsis(tdt):
    rows = tdt.line_changes('    msg = "這份資料看不到，請稍後再試"', '    msg = "這份資料無法檢視，請稍後再試"', 6)
    assert rows == [('…"這份資料看不到，請稍後…', '…"這份資料無法檢視，請稍後…')] or len(rows) == 1
    a, b = rows[0]
    assert a.startswith("…") and a.endswith("…") and "看不到" in a and "無法檢視" in b


def test_line_without_chinese_or_whole_rewrite_is_skipped(tdt):
    assert tdt.line_changes("x = 1", "x = 2") == []
    assert tdt.line_changes('say("今天天氣很好，我們出門")', 'run_job(queue, retries=3, delay=10)') == []


def test_comment_lines_are_not_collected(tdt):
    diff = ("diff --git a/backend/helpers/a.py b/backend/helpers/a.py\n--- a/backend/helpers/a.py\n+++ b/backend/helpers/a.py\n"
            "@@ -1 +1 @@\n-# 這裡看不到資料\n+# 這裡無法檢視資料\n"
            "@@ -5 +5 @@\n-x = 1  # 看不到\n+x = 1  # 無法檢視\n")
    res, _ = tdt.collect(diff)
    assert sum(len(v) for v in res.values()) == 0


def test_pure_additions_and_deletions_are_not_rewordings(tdt):
    diff = ("diff --git a/backend/helpers/a.py b/backend/helpers/a.py\n--- a/backend/helpers/a.py\n+++ b/backend/helpers/a.py\n"
            "@@ -0,0 +1 @@\n+msg = '全新的功能訊息'\n@@ -9 +9,0 @@\n-msg = '被移除的訊息'\n")
    res, _ = tdt.collect(diff)
    assert sum(len(v) for v in res.values()) == 0


def test_end_to_end_dedup_sections_and_render(tdt, tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _put(r, "backend/helpers/a.py", 'MSG = "目前沒有資料，請稍後再試"\n')
    _put(r, "backend/helpers/b.py", 'MSG = "目前沒有資料，請稍後再試"\n')
    _put(r, "frontend/pages/p.html", "<p>目前沒有待您簽核的項目。</p>\n")
    _put(r, "backend/tests/test_a.py", 'X = "目前沒有資料"\n')
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    _git(r, "tag", "base")
    _put(r, "backend/helpers/a.py", 'MSG = "尚無資料，請稍後再試"\n')
    _put(r, "backend/helpers/b.py", 'MSG = "尚無資料，請稍後再試"\n')
    _put(r, "frontend/pages/p.html", "<p>尚無待您簽核的單據。</p>\n")
    _put(r, "backend/tests/test_a.py", 'X = "尚無資料"\n')
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "reword")
    out = tmp_path / "t.md"
    assert tdt.main(["--root", str(r), "--base", "base", "--head", "HEAD", "--out", str(out), "--title", "T9"]) == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# T9 文字專業化——前後對照表")
    assert "比對區間：`base..HEAD`" in text
    assert "## 後端訊息／通知（1 組）" in text and "a.py 等 2 處" in text        # 相同改前／改後只列一次
    assert "## 前端畫面（1 組）" in text and "p.html" in text
    assert "## 說明文件（0 組）" in text and "本區間無此類改動" in text
    assert "test_a.py" not in text                                               # 測試檔不收
    assert "| 改前 | 改後 | 位置 |" in text


def test_punctuation_only_changes_are_not_listed(tdt):
    # 中文沒變、只動標點／括號 ⇒ 不收；中文真的改了 ⇒ 收
    assert tdt.line_changes('x = ("目前沒有資料")),', 'x = ("目前沒有資料")],') == []
    assert tdt.line_changes('x = ("目前沒有資料", 1)', 'x = ("目前沒有資料", 2)') == []
    assert len(tdt.line_changes('x = ("目前沒有資料")', 'x = ("尚無資料")')) == 1
