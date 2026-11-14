# -*- coding: utf-8 -*-
"""測試寫法守門：新測試不得用「文字子字串」當計數或錨點（T87 A2；T86 fx33 教訓）。

T86 的 fx33 探針用文案字面值（「尚無待簽核的單據」）定位頁面上的判斷式、並用 `.count(文案)` 數出現次數；
文案一改（PM 要求用語中性化）整支探針紅，最後改成「以結構定位、以行為比對」。bp1_layout／module_startup 的錨點、
motrix_format 的 needle 同一類。規則與掃描器在 tools/platform/text_anchor_scan.py（author_gate --quick 也會跑這一題）。

棘輪：既有檔的命中數記在 text_anchor_baseline.json，**只准減少**；新增與修改的測試超過基線＝紅。基線不得為了讓新測試過關而調高
——下面 BASELINE_TOTAL_CEILING 是同一個數字的第二個釘子，調高它必須出現在 diff 裡被審。
"""
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))

import text_anchor_scan as T  # noqa: E402

#: 既有命中總數的上限（只准往下改）。基線檔的 total 必須 ≤ 這個數。
BASELINE_TOTAL_CEILING = 787


def _all_test_files():
    out = []
    root = REPO / "backend"
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".venv", ".venv312", "node_modules", "__pycache__", ".git", "data")]
        for fn in filenames:
            if fn.startswith("test_") and fn.endswith(".py"):
                out.append(Path(dirpath, fn).relative_to(REPO).as_posix())
    return sorted(out)


# ── 該抓的（正對照）：fx33 那一類寫法 ───────────────────────────────────────

@pytest.mark.parametrize("src,kind", [
    ('def test_a(text):\n    assert text.count("尚無待簽核的單據") == 1\n', "count"),
    ('def test_a(html):\n    n = html.count("<template x-for")\n', "count"),
    ('def test_a(src):\n    i = src.index("def _title_expr(")\n', "anchor"),
    ('def test_a(src):\n    i = src.find("待簽核標題")\n', "anchor"),
    ('def test_a(src):\n    head = src.split("<main")[0]\n', "anchor"),
    ('TITLE_COPY = "您尚無待簽核的單據"\n\ndef test_a(text):\n    assert text.count(TITLE_COPY) == 1\n', "count"),          # 常數名也追得到
    ('NEEDLE = "x-text=\\"band\\""\n\ndef test_a(text):\n    p = text.partition(NEEDLE)\n', "anchor"),
])
def test_scanner_flags_text_substring_counts_and_anchors(src, kind):
    hits = T.scan_source(src)
    assert [k for _ln, k, _s in hits] == [kind], hits


# ── 不該抓的（反對照）────────────────────────────────────────────────────

@pytest.mark.parametrize("src", [
    'def test_a():\n    assert "a,b".count(",") == 1\n',                      # 接收者是字串常數
    'def test_a(s):\n    assert s.count("ab") == 1\n',                         # 純英數短字，不是文案／標記
    'def test_a(s):\n    i = s.find("id")\n',
    'def test_a(text):\n    assert "尚無" in text\n',                           # 存在性斷言不在這條規則（只管計數與定位）
    'def test_a(rows):\n    assert rows.count({"a": 1}) == 1\n',               # 引數不是字串
    'def test_a(text):\n    assert text.count("尚無資料") == 1  # text-anchor-ok: 數的是資料列標題，不是文案\n',   # 有理由的逃生口
])
def test_scanner_leaves_alone_what_it_should(src):
    assert T.scan_source(src) == []


def test_escape_hatch_needs_a_reason():
    src = 'def test_a(text):\n    assert text.count("尚無資料") == 1  # text-anchor-ok:\n'
    assert len(T.scan_source(src)) == 1, "text-anchor-ok 後面沒有理由 ⇒ 不算逃生口"


def test_syntax_error_file_is_not_this_guards_business():
    assert T.scan_source("def broken(:\n") == []


# ── 棘輪：只准減少 ───────────────────────────────────────────────────────

def test_over_baseline_flags_new_files_and_increases_only():
    base = {"a.py": 2, "b.py": 1}
    assert T.over_baseline({"a.py": 2, "b.py": 1}, base) == []
    assert T.over_baseline({"a.py": 1}, base) == []                                  # 減少 OK
    assert T.over_baseline({"a.py": 3}, base) == [("a.py", 3, 2)]                    # 既有檔增加 ⇒ 紅
    assert T.over_baseline({"new.py": 1}, base) == [("new.py", 1, 0)]                # 新檔基線＝0 ⇒ 任何命中都紅


def test_baseline_is_consistent_and_never_raised():
    b = T.load_baseline()
    assert b.get("files"), "text_anchor_baseline.json 讀不到或是空的"
    assert sum(b["files"].values()) == b["total"], "基線檔的 total 與各檔加總不符"
    assert b["total"] <= BASELINE_TOTAL_CEILING, (
        "基線總數 %d 高於上限 %d：基線只准減少。要放寬請改寫測試，不要調基線（調高上限必須在 diff 裡被審）。" % (b["total"], BASELINE_TOTAL_CEILING))


def test_no_test_file_exceeds_its_baseline():
    files = _all_test_files()
    assert len(files) > 500, "掃到的測試檔太少（%d）——掃描範圍壞了，不可當成通過" % len(files)
    cur = T.scan_tree(files, lambda f: (REPO / f).read_text(encoding="utf-8", errors="replace"))
    bad = T.over_baseline(cur, T.load_baseline()["files"])
    msg = []
    for f, n, b in bad[:10]:
        for ln, kind, snip in T.scan_source((REPO / f).read_text(encoding="utf-8", errors="replace"))[:4]:
            msg.append("  %s:%d [%s] %s（此檔 %d 處，基線 %d）" % (f, ln, kind, snip, n, b))
    assert not bad, (
        "測試用文字子字串當計數／錨點（T86 fx33 教訓：文案一改整支探針紅）：\n" + "\n".join(msg) +
        "\n改法：用 data-testid／結構（AST、正規式抓結構）定位，用行為比對；真的在數資料列＝同一行加 `# text-anchor-ok: <理由>`。")


def test_baseline_files_still_exist():
    """基線裡的檔被刪／改名後要一起清掉（否則改名過的檔拿新名字＝基線 0，反而會被抓到——這題是提醒基線要跟著更新）。"""
    missing = [f for f in T.load_baseline()["files"] if not (REPO / f).is_file()]
    assert not missing, "基線裡有不存在的檔，請 `python tools/platform/text_anchor_scan.py --write-baseline`（只准總數減少）：%s" % missing[:5]
