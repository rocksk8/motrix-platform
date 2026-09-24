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
from pathlib import Path

PAGES = Path(__file__).resolve().parents[2] / "frontend" / "pages"

NAME = re.compile(r"(filter|search|keyword|kw|(^|\.)q$|query|dateFrom|dateTo|sort|year|month|period|range|scope"
                  r"|view|mode|show|tab|page|layer|near|status)", re.I)
TAG = re.compile(r"<(input|select|textarea)\b[^>]*>", re.S | re.I)
XMODEL = re.compile(r"\bx-model(?:\.[\w.]+)?=\"([^\"]+)\"")
STATIC_CLASS = re.compile(r"(?<![:\w-])class=\"([^\"]*)\"")
TYPE = re.compile(r"(?<![:\w-])type=\"([^\"]*)\"")

#: hichan-a3 手上的 22 頁（W-8 分工，2026-09-25）。落地一頁就從這裡拿掉一頁；只准變少（下面有斷言）。
PENDING = {
    "case-management.html", "access-guide.html", "automation-guide.html", "gateway-guide.html",
    "monitor-guide.html", "switch-guide.html", "netarch-guide.html", "env-guide.html", "dev-crm.html",
    "tender-radar.html", "case-stage-board.html", "customer-log.html", "supplier-log.html", "work-log.html",
    "network-plan-form.html", "network-plans.html", "inventory.html", "parts.html", "devices.html",
    "online-stats.html", "topology-quick.html", "daily-tasks.html",
}
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


def test_every_filter_like_binding_has_a_decision():
    bad = {}
    for f in sorted(PAGES.glob("*.html")):
        if f.name in PENDING:
            continue
        u = undecided(f.read_text(encoding="utf-8"))
        if u:
            bad[f.name] = u
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
    missing = [p for p in PENDING if not (PAGES / p).exists()]
    assert not missing, "PENDING 裡的頁面不存在（改名了？）：%s" % missing
