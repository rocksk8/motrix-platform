"""深色模式的「chrome 元素必須是 body 直接子元素」結構前提（2026-09-13 新增）。

**問題本身**：深色模式不是另一套色票，而是對 body 的非 chrome 子元素套
`filter: invert(1) hue-rotate(180deg)`（`frontend/css/style.css`「DARK MODE」區塊）。
topbar／sidebar／sidebar-overlay 本來就是深色，所以被寫在排除清單裡：

    :root[data-theme="dark"] body > *:not(.topbar):not(.sidebar):not(.sidebar-overlay)

這是 **`body > *` 直接子元素**選擇器。只要有人把側欄多包一層容器（實際發生過：
15 頁把 `<aside class="sidebar">` 放進 `<div class="app-shell">`），排除就對不上——
被反轉的是那個容器，側欄整片變成**白底深字**，而且容器有了 filter 會依 CSS 規範
變成子孫 `position: fixed` 的 containing block，側欄與該容器內的 Modal 會改以容器
（而不是 viewport）定位。使用者看到的是「部分頁面深色模式左側選單是白的」。

**為什麼不是在 CSS 裡用雙重反轉硬扛**：`hue-rotate` 是近似矩陣、來回兩次顏色會偏，
而且那只蓋掉顏色、fixed 定位仍然是壞的。正確解法是維持結構前提，所以這裡把前提
本身變成一支會紅的測試。

**這支測試不能單獨證明畫面是深色的**——computed style 讀到的永遠是作者寫的
`background: var(--sidebar)`，filter 是繪製階段的事，DOM 層看不出來（正是假綠燈的
典型來源）。真正量到「畫出來是深色」的是 e2e：
`test_e2e_dark_mode_sidebar_2026_09_13.py`（截圖取像素）。兩支互補：這支快、每次
都跑、指出違規的檔案；那支慢、需要 playwright，但量的是最終畫面。
"""
import glob
import io
import os
import re
from html.parser import HTMLParser

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
PAGES = sorted(glob.glob(os.path.join(ROOT, "frontend", "pages", "*.html"))) + \
    [os.path.join(ROOT, "frontend", "index.html")]
STYLE_CSS = os.path.join(ROOT, "frontend", "css", "style.css")

# 深色模式排除清單裡的 class（與 style.css 的選擇器一一對應）
# 2026-09-14：首頁的深色主視覺與深色三欄帶一併納入——它們也是「本來就深色、
# 兩種模式都不該被反轉」的區塊，同樣只有在 body 直下時排除清單才會生效。
CHROME_CLASSES = {"topbar", "sidebar", "sidebar-overlay", "h-hero", "h-band"}

# HTML 規範中不需要（也不能）有結束標籤的元素，解析時不入堆疊
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


class _ChromeParser(HTMLParser):
    """記錄每個 chrome 元素出現時的祖先鏈，用來判斷它是不是 body 直下。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack = []
        self.hits = []   # (class 名, 祖先鏈字串)

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        classes = set((d.get("class") or "").split())
        hit = classes & CHROME_CLASSES
        if hit:
            chain = "/".join(t for t, _ in self._stack)
            self.hits.append((",".join(sorted(hit)), chain or "(root)"))
        if tag not in VOID:
            self._stack.append((tag, d))

    def handle_endtag(self, tag):
        # 容忍未閉合標籤：往回找最近的同名開標籤，連同它之後的殘留一起收掉
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break


def _scan(path):
    parser = _ChromeParser()
    parser.feed(io.open(path, encoding="utf-8").read())
    return parser.hits


def test_chrome_elements_are_direct_children_of_body():
    """topbar／sidebar／sidebar-overlay 一律是 <body> 直下，深色模式排除清單才會生效。"""
    offenders = []
    for path in PAGES:
        for cls, chain in _scan(path):
            if chain != "html/body":
                offenders.append(f"{os.path.basename(path)}: .{cls} 的祖先鏈是 {chain}")

    assert not offenders, (
        "這些 chrome 元素不是 <body> 的直接子元素，深色模式會把它們連同容器一起反轉成白底"
        "（且容器的 filter 會讓其中的 position:fixed 改以容器定位）：\n  "
        + "\n  ".join(offenders)
        + "\n修法：把該元素移回 <body> 直下（.app-shell 之類的純版面容器沒有任何 CSS，"
          "只包住 <main> 即可）。"
    )


def test_dark_mode_rule_still_uses_direct_child_selector():
    """反向鎖定：上面那支測試的前提是 style.css 用直接子元素選擇器。

    哪天有人把深色模式改成別的機制（例如改用色票變數、或改成後代選擇器），
    這裡會紅——提醒回來確認上面那條結構規則還需不需要，而不是讓它默默變成
    一條沒人記得為什麼存在的規定。"""
    css = io.open(STYLE_CSS, encoding="utf-8").read()
    expected = (':root[data-theme="dark"] body > *'
                ':not(.topbar):not(.sidebar):not(.sidebar-overlay):not(.h-hero):not(.h-band)')
    assert expected in css, (
        "style.css 的深色模式選擇器變了，找不到：\n  " + expected
        + "\n若深色模式已改用別的機制，請一併確認 "
          "test_chrome_elements_are_direct_children_of_body 的前提是否仍成立。"
    )


# ── 頁面不得自己寫深色色票（2026-09-14 新增）──────────────────────────────
#
# 起因：使用者回報「業務開發在深色模式下、新增案件那一區還是白的」。根因不是
# 結構，而是 `dev-crm.html` 自己寫了 11 條
# `:root[data-theme="dark"] .dc-list { background: #1A1A1A … }` 手寫深色覆寫。
#
# 全站深色模式是**反轉濾鏡**，不是另一套色票：在會被整片反轉的內容上再塗一次深色，
# 反轉後就變成淺色——寫得越「對」，結果越白。正確作法是什麼都不寫，讓淺色底被反轉。
#
# 例外只有一種：**本來就不在反轉範圍內**的元素（.topbar／.sidebar／.sidebar-overlay），
# 或整頁都不套反轉的獨立頁面。要破例請在下面白名單補一筆並寫明原因。

DARK_OVERRIDE_ALLOWED = {}

_COMMENT_RE = re.compile(r"/\*.*?\*/|<!--.*?-->", re.S)


def test_pages_do_not_define_their_own_dark_palette():
    offenders = []
    for path in PAGES:
        src = _COMMENT_RE.sub("", io.open(path, encoding="utf-8").read())   # 註解裡提到不算
        hits = len(re.findall(r':root\[data-theme="dark"\]', src))
        if hits and os.path.basename(path) not in DARK_OVERRIDE_ALLOWED:
            offenders.append(f"{os.path.basename(path)}：{hits} 條 :root[data-theme=\"dark\"] 覆寫")
    assert not offenders, (
        "這些頁面自己寫了深色色票，但全站深色模式是反轉濾鏡——手寫的深色會被反轉成"
        "淺色，症狀正好相反（越『正確』越白）：\n  " + "\n  ".join(offenders)
        + "\n修法：刪掉那些覆寫，讓淺色底被反轉即可；真的要破例請在本檔 "
          "DARK_OVERRIDE_ALLOWED 補一筆並寫明原因。"
    )
