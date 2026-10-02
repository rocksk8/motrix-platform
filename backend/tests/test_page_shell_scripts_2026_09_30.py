"""頁面外框守門（2026-09-30，使用者回報「新的模組沒有最上面的模組跟 logo」）。

頁面有 `id="sidebar-root"`（要掛側欄／頂列）就必須載入 `static/sidebar.js`，而且 `static/notif.js` 要在它之前
（sidebar.js 無條件輸出 globalSearchStore()／notifStore()，定義在 notif.js）。
總帳 5 頁（ledger-hub／periods／reports／settings／statements）上線時兩支都漏載 ⇒ 頂列、logo、側欄全空，
而頁面本身其他功能正常，所以測試全綠。
"""
import re

from core.source_tree import page_file, page_files
_SRC = re.compile(r'<script[^>]*\bsrc="([^"]+)"', re.I)


def shell_problems(html: str) -> list:
    """回傳問題清單（空＝通過）。只看宣告要外框（sidebar-root）的頁面。"""
    if 'id="sidebar-root"' not in html:
        return []
    srcs = [s.split("?")[0] for s in _SRC.findall(html)]
    out = []
    if "../static/sidebar.js" not in srcs:
        out.append("沒有載入 ../static/sidebar.js（頂列／logo／側欄不會出現）")
    if "../static/notif.js" not in srcs:
        out.append("沒有載入 ../static/notif.js（全域搜尋／通知鈴鐺會失效）")
    elif "../static/sidebar.js" in srcs and srcs.index("../static/notif.js") > srcs.index("../static/sidebar.js"):
        out.append("notif.js 要放在 sidebar.js 之前")
    return out


def test_every_shell_page_loads_sidebar_and_notif():
    pages = page_files()                                  # 共用頁面＋各模組頁面
    assert len(pages) > 50, "掃不到頁面（量尺）"
    bad = {p.name: shell_problems(p.read_text(encoding="utf-8")) for p in pages}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, bad


def test_ledger_pages_are_covered():
    """正對照：這次出事的 5 頁都有 sidebar-root（守門真的看得到它們）。"""
    for n in ("hub", "periods", "reports", "settings", "statements"):
        html = page_file("ledger-%s.html" % n).read_text(encoding="utf-8")
        assert 'id="sidebar-root"' in html, n
        assert shell_problems(html) == [], n


def test_reverse_controls():
    base = '<div id="sidebar-root"></div><script src="../static/notif.js"></script><script src="../static/sidebar.js"></script>'
    assert shell_problems(base) == []
    assert shell_problems(base.replace('<script src="../static/sidebar.js"></script>', ""))
    assert shell_problems(base.replace('<script src="../static/notif.js"></script>', ""))
    swapped = '<div id="sidebar-root"></div><script src="../static/sidebar.js"></script><script src="../static/notif.js"></script>'
    assert shell_problems(swapped) == ["notif.js 要放在 sidebar.js 之前"]
    assert shell_problems("<html>login</html>") == []  # 沒有外框的頁面（登入、導向頁）不管
