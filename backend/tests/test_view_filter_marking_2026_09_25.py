"""W-8 靜態守門（2026-09-25）：名字長得像「篩選／期間／檢視」的 x-model 欄位，每一個都要有人決定過。

決定只有兩種，都寫在欄位本身（不另開清單，避免清單與頁面各自漂移）：
- 看法類（改了不該觸發離頁警告）：靜態 class 含 `filter` 或 `search`、或 type=search／range
  ——與 sidebar.js `_maybeSetDirty` 跳過的條件相同，所以標了就真的會被跳過。
- 資料類（會存檔，名字只是剛好像）：加 `data-saved-field`。

⚠ 只看靜態 `class="…"`：`:class` 在執行期也會併進 className，但守門讀不到它，寫在那裡等於沒標。
⚠ 名稱比對一定會漏（例：map 的圖層勾選框叫 `picked`）。這一題只保證「像的都有人看過」，
  看不像的靠各頁 e2e（test_e2e_view_filters_not_dirty_2026_09_25.py）。
"""
import re

from core import source_tree

#: 範圍：`core.source_tree.page_files()`（L1 頁面目錄 ∪ 各模組的 pages/）。
#: 〔主持派工 wip/b-scan-modules：原本只 glob L1 頁面目錄——頁面搬進 modules/<key>/pages/ 之後會安靜地少掃〕

NAME = re.compile(r"(filter|search|keyword|kw|(^|\.)q$|query|dateFrom|dateTo|sort|year|month|period|range|scope"
                  r"|view|mode|show|tab|page|layer|near|status)", re.I)
TAG = re.compile(r"<(input|select|textarea)\b[^>]*>", re.S | re.I)
XMODEL = re.compile(r"\bx-model(?:\.[\w.]+)?=\"([^\"]+)\"")
STATIC_CLASS = re.compile(r"(?<![:\w-])class=\"([^\"]*)\"")
TYPE = re.compile(r"(?<![:\w-])type=\"([^\"]*)\"")

#: hichan-a3 手上的 22 頁（W-8 分工，2026-09-25）。落地一頁就從這裡拿掉一頁；只准變少（下面有斷言）。
PENDING = set()   # 2026-09-25：a3 的 22 頁已全數落地（20 頁標記、daily-tasks／topology-quick 本無篩選欄）
_PENDING_AT_START = 22


def undecided(html):
    """回傳 [(行號, x-model 名稱)]：名字像篩選、卻沒有任何一種標記的欄位。"""
    html = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), html, flags=re.S)
    out = []
    for m in TAG.finditer(html):
        t = m.group(0)
        xm = XMODEL.search(t)
        if not xm or not NAME.search(xm.group(1)):
            continue
        cls = (STATIC_CLASS.search(t) or [None, ""])[1]
        typ = (TYPE.search(t) or [None, ""])[1]
        if "filter" in cls or "search" in cls or typ in ("search", "range") or "data-saved-field" in t:
            continue
        out.append((html.count("\n", 0, m.start()) + 1, xm.group(1)))
    return out


def _undecided_pages(files):
    bad = {}
    for f in files:
        if f.name in PENDING:
            continue
        u = undecided(f.read_text(encoding="utf-8"))
        if u:
            bad[f.name] = u
    return bad


def test_every_filter_like_binding_has_a_decision():
    bad = _undecided_pages(source_tree.page_files())
    assert not bad, ("這些欄位名字像篩選，但沒有標 class=\"filter\"（看法類）或 data-saved-field（存檔欄位）："
                     "%s" % bad)


def test_the_guard_sees_what_it_should():
    """正對照：守門真的抓得到未標的欄位，也真的放過兩種標記與 sidebar 本來就跳過的寫法。"""
    assert undecided('<select x-model.number="year">') == [(1, "year")]
    assert undecided('<select :class="{a:1}" class="x" x-model="filterMonth">') == [(1, "filterMonth")]
    assert undecided('<select :class="{filter:1}" x-model="filterMonth">') == [(1, "filterMonth")]   # :class 不算
    assert undecided('<select class="mp-near filter" x-model="nearN">') == []
    assert undecided('<input data-saved-field x-model="form.status">') == []
    assert undecided('<input class="search-input" x-model="q">') == []
    assert undecided('<input type="search" x-model="q">') == []
    assert undecided('<input x-model="form.name">') == []        # 名字不像 ⇒ 不歸這一題管
    assert undecided('<!-- <select x-model="year"> -->') == []


def test_pending_pages_only_shrink_and_still_exist():
    assert len(PENDING) <= _PENDING_AT_START
    missing = [p for p in PENDING if not _page_exists(p)]
    assert not missing, "PENDING 裡的頁面不存在（改名了？）：%s" % missing


def _page_exists(name):
    try:
        source_tree.page_file(name)
        return True
    except FileNotFoundError:
        return False


def _sandbox_with_module_page(tmp_path, monkeypatch, html):
    """沙盒：L1 頁面目錄一頁乾淨的＋modules/x/pages 一頁指定內容；source_tree 指到沙盒。"""
    backend = (tmp_path / "backend").resolve()
    pages = (tmp_path / "fe" / "pg").resolve()
    pages.mkdir(parents=True)
    (pages / "l1-clean.html").write_text('<input class="filter" x-model="year">', encoding="utf-8")
    mod = backend / "modules" / "x"
    (mod / "pages").mkdir(parents=True)
    (mod / "module.json").write_text("{}", encoding="utf-8")
    mp = mod / "pages"
    (mp / "x-view.html").write_text(html, encoding="utf-8")
    monkeypatch.setattr(source_tree, "BACKEND", backend)
    monkeypatch.setattr(source_tree, "FRONTEND_PAGES", pages)


def test_a_module_page_is_in_scope(tmp_path, monkeypatch):
    """⚙️ 反向控制（主持裁示）：模組頁面（modules/x/pages）有未標的篩選欄 ⇒ 要被抓到；標了 ⇒ 放過。"""
    _sandbox_with_module_page(tmp_path, monkeypatch, '<select x-model="year">')
    assert {p.name for p in source_tree.page_files()} == {"l1-clean.html", "x-view.html"}
    assert _undecided_pages(source_tree.page_files()) == {"x-view.html": [(1, "year")]}


def test_a_marked_module_page_passes(tmp_path, monkeypatch):
    _sandbox_with_module_page(tmp_path, monkeypatch, '<select class="filter" x-model="year">')
    assert _undecided_pages(source_tree.page_files()) == {}
