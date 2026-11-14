# -*- coding: utf-8 -*-
"""測試寫法守門：新測試不得用「文字子字串」當計數或錨點（T87 A2；T86 fx33 教訓）。

T86 的 fx33 探針用文案字面值（「尚無待簽核的單據」）定位頁面上的判斷式、並用 `.count(文案)` 數出現次數；
文案一改（PM 要求用語中性化）整支探針紅，最後改成「以結構定位、以行為比對」。bp1_layout／module_startup 的錨點、
motrix_format 的 needle 同一類。規則與掃描器在 tools/platform/text_anchor_scan.py（author_gate --quick 也會跑這一題）。

棘輪（tools/platform/ratchet.py 三道檢查）：既有檔的命中數記在 text_anchor_baseline.json，**只准減少**。
  1. 逐檔貼合（基線 > 現場＝要重寫基線，而且只准往下寫）；
  2. 基線對照合併基準上的基線（任何一檔變多、總數變多＝紅；抓不到基準＝明確 skip 並寫原因，不當通過）；
  3. 不另存上限常數（上限就是合併基準上的基線）。
逃生口（`# text-anchor-ok: <理由>`，理由 ≥8 字元且≥2 詞或中文≥4 字，必須是真正的註解）的使用數也在基線裡，同樣只准減少，失敗輸出會列出清單。
已知限制：總數與逐檔數都不變的「同檔換一個錨點」看不出來——靠審查。
掃描範圍＝測試根底下所有 .py（含 conftest.py 與非 test_ 開頭的輔助檔）。
"""
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))

import ratchet as R  # noqa: E402
import text_anchor_scan as T  # noqa: E402

BASELINE_REL = "backend/tests/platform/text_anchor_baseline.json"


def _all_test_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(REPO / "backend"):
        dirnames[:] = [d for d in dirnames if d not in (".venv", ".venv312", "node_modules", "__pycache__", ".git", "data")]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(Path(dirpath, fn).relative_to(REPO).as_posix())
    return T.test_files(out)


def _read(f):
    return (REPO / f).read_text(encoding="utf-8", errors="replace")


# ── 該抓的（正對照）：fx33 那一類寫法 ───────────────────────────────────────

@pytest.mark.parametrize("src,kind", [
    ('def test_a(text):\n    assert text.count("尚無待簽核的單據") == 1\n', "count"),
    ('def test_a(html):\n    n = html.count("<template x-for")\n', "count"),
    ('def test_a(src):\n    i = src.index("def _title_expr(")\n', "anchor"),
    ('def test_a(src):\n    i = src.find("待簽核標題")\n', "anchor"),
    ('def test_a(src):\n    head = src.split("<main")[0]\n', "anchor"),
    ('TITLE_COPY = "您尚無待簽核的單據"\n\ndef test_a(text):\n    assert text.count(TITLE_COPY) == 1\n', "count"),          # 常數名也追得到
    ('NEEDLE = "x-text=\\"band\\""\n\ndef test_a(text):\n    p = text.partition(NEEDLE)\n', "anchor"),
    ('def test_a(t):\n    assert t.count("儲存") == 1\n', "count"),                                                         # 兩字中文（按鈕文字）
    ('def test_a(t):\n    assert t.count("x-for") == 2\n', "count"),                                                       # `-` 也算標記字元
    ('def test_a(t):\n    assert t.count("@click") == 2\n', "count"),
    ('def test_a(t, n):\n    assert t.count(f"尚無{n}資料") == 1\n', "count"),                                              # f-string
    ('def test_a(t):\n    assert t.count("尚無" + "資料") == 1\n', "count"),                                               # 字串相加
    ('M: str = "尚無資料"\n\ndef test_a(t):\n    assert t.count(M) == 1\n', "count"),                                      # AnnAssign 常數
    ('class K:\n    M = "x-for"\n\n    def test_a(self, t):\n        assert t.count(self.M) == 1\n', "count"),            # 類別層級常數
    ('MS = ("x-for", "@click")\n\ndef test_a(t):\n    for m in MS:\n        assert t.count(m)\n', "count"),                # 走訪常數清單的迴圈變數
    ('import re\n\ndef test_a(t):\n    assert len(re.findall(r"尚無資料", t)) == 1\n', "count"),                           # 正規式當子字串計數
    ('def test_a(t):\n    assert str.count(t, "尚無資料") == 1\n', "count"),
    ('def test_a(t):\n    a, b = t.split("<tr", 1)\n', "anchor"),                                                          # 拆包
    ('def test_a(t):\n    assert len(t.split("<tr")) == 3\n', "anchor"),                                                  # 數段數
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


@pytest.mark.parametrize("reason", ["", "x", "ok", "數資料列"])
def test_escape_hatch_needs_a_real_reason(reason):
    src = 'def test_a(text):\n    assert text.count("尚無資料") == 1  # text-anchor-ok: %s\n' % reason
    assert len(T.scan_source(src)) == 1, "理由太短（<8 字元、單詞）不算逃生口"


def test_escape_hatch_must_be_a_real_comment_not_text_inside_a_string():
    src = 'def test_a(text):\n    assert text.count("尚無資料 # text-anchor-ok: 數資料列標題不是文案") == 1\n'
    assert len(T.scan_source(src)) == 1


def test_escape_hatch_uses_are_counted_so_the_ratchet_can_see_them():
    src = ('def test_a(text):\n    assert text.count("尚無資料") == 1  # text-anchor-ok: 數的是資料列標題，不是文案\n'
           '    assert 1  # text-anchor-ok: 沒有蓋住任何命中的註解\n')
    assert T.scan_source(src) == []
    assert [ln for ln, _r in T.hatch_uses(src)] == [2], "只有真的蓋住命中的逃生口才算使用（行 3 的註解沒蓋住任何命中）"


def test_syntax_error_file_is_not_this_guards_business():
    assert T.scan_source("def broken(:\n") == []


def test_scan_scope_includes_conftest_and_non_test_helpers():
    got = T.test_files(["backend/tests/conftest.py", "backend/tests/_helper.py", "backend/modules/case/tests/test_x.py",
                        "backend/modules/case/api/quotes.py", "backend/helpers/x.py", "frontend/pages/x.html"])
    assert got == ["backend/modules/case/tests/test_x.py", "backend/tests/_helper.py", "backend/tests/conftest.py"]


# ── 棘輪：只准減少 ───────────────────────────────────────────────────────

def test_over_baseline_flags_new_files_and_increases_only():
    base = {"a.py": 2, "b.py": 1}
    assert T.over_baseline({"a.py": 2, "b.py": 1}, base) == []
    assert T.over_baseline({"a.py": 1}, base) == []                                  # 減少 OK
    assert T.over_baseline({"a.py": 3}, base) == [("a.py", 3, 2)]                    # 既有檔增加 ⇒ 紅
    assert T.over_baseline({"new.py": 1}, base) == [("new.py", 1, 0)]                # 新檔基線＝0 ⇒ 任何命中都紅


def test_baseline_is_internally_consistent():
    b = T.load_baseline()
    assert b.get("files"), "text_anchor_baseline.json 讀不到或是空的"
    assert sum(b["files"].values()) == b["total"], "基線檔的 total 與各檔加總不符"


def test_baseline_hugs_the_tree_exactly_no_stale_slack():
    """逐檔貼合：基線的每個數字都等於現場（基線 > 現場＝有人改乾淨了卻沒重寫基線，空位之後會被補滿）。重寫：`python tools/platform/text_anchor_scan.py --write-baseline`（只准往下寫）。"""
    cur = T.scan_tree(_all_test_files(), _read)
    stale = R.slack(cur, T.load_baseline()["files"])
    assert not stale, "基線有空位（請重寫基線，只准往下）：%s" % stale[:5]


def test_baseline_is_not_higher_than_the_merge_base_baseline():
    res = R.check_against_base(BASELINE_REL, T.load_baseline(), REPO, env_base=os.environ.get("MOTRIX_RATCHET_BASE"))
    if res["status"] == "no_base":
        pytest.skip("未跑：抓不到合併基準（%s）——這一題需要 git 與主線分支；整合者的閘門必須在有基準的環境跑" % res["note"])
    assert not res["violations"], "基線比合併基準高（基線只准減少；改寫測試，不要調基線）：%s %s" % (res["violations"][:8], res["note"])


def test_no_test_file_exceeds_its_baseline():
    files = _all_test_files()
    assert len(files) > 500, "掃到的測試檔太少（%d）——掃描範圍壞了，不可當成通過" % len(files)
    cur = T.scan_tree(files, _read)
    bad = T.over_baseline(cur, T.load_baseline()["files"])
    msg = []
    for f, n, b in bad[:10]:
        for ln, kind, snip in T.scan_source(_read(f))[:4]:
            msg.append("  %s:%d [%s] %s（此檔 %d 處，基線 %d）" % (f, ln, kind, snip, n, b))
    assert not bad, (
        "測試用文字子字串當計數／錨點（T86 fx33 教訓：文案一改整支探針紅）：\n" + "\n".join(msg) +
        "\n改法：用 data-testid／結構（AST、正規式抓結構）定位，用行為比對；真的在數資料列＝同一行加 `# text-anchor-ok: <理由>`。")


def test_escape_hatch_uses_do_not_exceed_baseline_and_are_listed():
    files = _all_test_files()
    cur = T.hatches_in_tree(files, _read)
    base = T.load_baseline().get("hatches", {})
    over = [(f, n, base.get(f, 0)) for f, n in sorted(cur.items()) if n > base.get(f, 0)]
    listing = ["  %s:%d %s" % (f, ln, r) for f in sorted(cur) for ln, r in T.hatch_uses(_read(f))][:20]
    assert not over, "逃生口（# text-anchor-ok）使用數超過基線（只准減少；審查請看下面清單）：%s\n%s" % (over[:5], "\n".join(listing))


def test_baseline_files_still_exist():
    """基線裡的檔被刪／改名後要一起清掉（否則改名過的檔拿新名字＝基線 0，反而會被抓到——這題是提醒基線要跟著更新）。"""
    missing = [f for f in T.load_baseline()["files"] if not (REPO / f).is_file()]
    assert not missing, "基線裡有不存在的檔，請 `python tools/platform/text_anchor_scan.py --write-baseline`（只准總數減少）：%s" % missing[:5]
