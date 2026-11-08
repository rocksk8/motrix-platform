"""T79：dep_scan 的 `<script src>` 靜默跳過——把『解析失敗』變成看得見的數字，並有守門盯著。

背景：`fe_scan` 解析不到（路徑搬動、寫了 `/static/x.js`、`?v=1` 這類形式）時直接 `continue`，`build()` 又用 `s in units` 濾一次，
頁面→JS 的邊（⇒ `routers_called_effective`、test_map 的頁面對應）就悄悄少一條，沒有任何測試會紅。

基準（2026-11-08 實測，T79 開工樹）：79 頁、574 個 `<script src>`＝489 個有效 js 單位＋85 個 vendor、**解析失敗 0**。
所以守門直接釘 0 不會讓既有的建包變紅；將來有人搬動頁面／JS 造成失敗 ⇒ 這題紅並列出是哪一頁哪一條。
不是每一種失敗都該擋：真的需要（例如站台根路徑 `/static/…` 由後端掛載）就寫進 `KNOWN_UNRESOLVED`，附理由。
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import dep_scan  # noqa: E402

#: 已知且接受的解析失敗：`{(頁面 repo 相對路徑, src 原字串): 理由}`。目前沒有（基準 0）；加進來要寫理由，過期要刪。
KNOWN_UNRESOLVED: dict[tuple[str, str], str] = {}


# ── 真實樹：失敗數 = 0 ─────────────────────────────────────────────────────────

def test_no_unresolved_script_src_in_real_tree():
    stats = {}
    got = {(d["page"], d["src"]): d["reason"] for d in dep_scan.script_ref_problems(stats)}
    new = {k: v for k, v in got.items() if k not in KNOWN_UNRESOLVED}
    assert not new, (
        "這些 <script src> 解析失敗（dep_scan 悄悄略過它們 ⇒ 頁面→JS 的邊會少，routers_called_effective／test_map 退化）：\n"
        + "\n".join("  %s  src=%s  (%s)" % (p, s, r) for (p, s), r in sorted(new.items()))
        + "\n📌 路徑搬動 ⇒ 改頁面裡的 src；確實需要的特殊寫法 ⇒ 寫進 KNOWN_UNRESOLVED 並附理由。")


def test_the_guard_really_scanned_something():
    """正對照：基準 0 不能是『什麼都沒掃』造成的。"""
    stats = {}
    probs = dep_scan.script_ref_problems(stats)
    assert stats.get("pages", 0) >= 50 and stats.get("refs", 0) >= 300, stats
    # 每個 src 都有去處：有效／vendor／外部／列為失敗，沒有第五種（對帳）
    assert stats.get("ok", 0) > 0 and stats["ok"] + stats.get("vendor", 0) + stats.get("external", 0) + len(probs) == stats["refs"], stats


def test_known_unresolved_entries_are_alive_and_explained():
    got = {(d["page"], d["src"]) for d in dep_scan.script_ref_problems()}
    assert all(str(v).strip() for v in KNOWN_UNRESOLVED.values()), "KNOWN_UNRESOLVED 有空白理由"
    stale = sorted(set(KNOWN_UNRESOLVED) - got)
    assert not stale, "KNOWN_UNRESOLVED 裡這些已經不是解析失敗（過期要刪）：%s" % stale


# ── 合成樹：守門真的抓得到（反向控制，不綁任何真實頁面） ───────────────────────

def _tree(root: Path, files: dict[str, str]):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


PAGE = ("<script src=\"../js/ok.js\"></script>\n"
        "<script src=\"../js/gone.js\"></script>\n"                 # 檔案不存在（被搬走／改名）
        "<script src=\"../js/ok.js?v=3\"></script>\n"               # 掃描器不認 query
        "<script src=\"/static/x.js\"></script>\n"                  # 站台根路徑：解析後在 frontend/ 之外
        "<script src=\"../../../etc/y.js\"></script>\n"             # 爬出 frontend/
        "<script src=\"https://cdn.example.invalid/a.js\"></script>\n"   # 外部：不算失敗
        "<script src=\"//cdn.example.invalid/b.js\"></script>\n"
        "<script src=\"../static/vendor/v.js\"></script>\n"         # vendor 目錄：刻意略過
        "<script src=\"../js/vendor-utils.js\"></script>\n")        # 名字帶 vendor 的『真 JS』：是有效單位，不可以被當 vendor 靜默丟掉


@pytest.fixture
def synthetic(tmp_path):
    _tree(tmp_path, {"frontend/pages/p.html": PAGE, "frontend/js/ok.js": "x=1\n", "frontend/js/vendor-utils.js": "u=1\n",
                           "frontend/static/vendor/v.js": "v=1\n"})
    with dep_scan.use_root(tmp_path):
        yield tmp_path


def test_guard_catches_each_kind_of_silent_skip(synthetic):
    stats = {}
    got = {(d["src"], d["reason"]) for d in dep_scan.script_ref_problems(stats)}
    assert got == {("../js/gone.js", "not_found"), ("../js/ok.js?v=3", "not_found"),
                   ("/static/x.js", "outside_frontend"), ("../../../etc/y.js", "outside_frontend"),
                   ("../js/vendor-utils.js", "dropped_as_vendor")}, got
    assert stats == {"pages": 1, "refs": 9, "ok": 1, "vendor": 1, "external": 2}, stats


def test_moving_a_js_file_is_detected(synthetic):
    """這張票要防的情境：JS 被搬到別的目錄、頁面沒跟著改 src ⇒ 以前悄悄少一條邊，現在抓得到。"""
    before = {d["src"] for d in dep_scan.script_ref_problems()}
    assert "../js/ok.js" not in before
    (synthetic / "frontend" / "js" / "sub").mkdir()
    (synthetic / "frontend" / "js" / "ok.js").rename(synthetic / "frontend" / "js" / "sub" / "ok.js")
    after = {d["src"] for d in dep_scan.script_ref_problems()}
    assert "../js/ok.js" in after


def test_fe_scan_default_result_is_unchanged(synthetic):
    """只多了觀測參數：不給時回傳值與舊版相同（有效邊只有 ok.js；其餘一律略過，維持原行為）。"""
    page = synthetic / "frontend" / "pages" / "p.html"
    assert dep_scan.fe_scan(page)[1] == ["js:js/ok.js", "js:js/gone.js", "js:js/ok.js?v=3"]
    with_obs = dep_scan.fe_scan(page, problems=[], known=set(), stats={})
    assert with_obs == dep_scan.fe_scan(page)                         # 觀測參數不改回傳


def test_build_still_drops_unresolved_edges_only_from_imports(synthetic):
    """build() 的 `s in units` 過濾不動：失敗的 src 不會變成邊（行為不變），只是現在看得見。"""
    units = dep_scan.frontend_units()
    page = synthetic / "frontend" / "pages" / "p.html"
    imports = sorted(s for s in dep_scan.fe_scan(page)[1] if s in units)
    assert imports == ["js:js/ok.js"]
