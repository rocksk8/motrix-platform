"""CM12 P3 預備（2026-09-24）：語意色彩 token、案件頁 11px 字級守門。

- style.css 最後一段「語意色彩 token」：案件頁寫死的色碼歸納成語意 token，另有 `:root[data-theme="dark"]` 一組。
- 對照表 docs/windows/CM12-P3-COLOR-TOKENS.md：案件頁用到的每一個色碼都要有對應 token，而且 token 真的存在。
- 字級：案件頁 font-size < 11px 的現況以 xfail(strict) 釘住（P3 套完轉綠 ⇒ strict 讓它紅 ⇒ 拿掉 xfail），
  另有棘輪題：處數只能減少。
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / "frontend" / "css" / "style.css"
DOC = ROOT / "docs" / "windows" / "CM12-P3-COLOR-TOKENS.md"
PAGE = ROOT / "frontend" / "pages" / "case-management.html"
# CM12 起案件頁 JS 拆成 case-management-*.js
PAGE_JS_FILES = sorted((ROOT / "frontend" / "js").glob("case-management-*.js"))
COLOR = r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\([^)]*\)"
SMALL_FONT_NOW = 114      # 2026-09-24 的現況（10px 87、9px 15、10.5px 6、9.5px 5、8.5px 1）


def _norm(c):
    c = c.lower().replace(" ", "")
    if re.fullmatch(r"#[0-9a-f]{3}", c):
        c = "#" + "".join(ch * 2 for ch in c[1:])
    return c


def _token_blocks():
    css = CSS.read_text(encoding="utf-8")
    block = css[css.index("語意色彩 token"):]
    start = block.index(":root {")
    dark_at = block.index(':root[data-theme="dark"] {', start)
    light, dark = block[start:dark_at], block[dark_at:]
    names = lambda text: set(re.findall(r"^\s*(--[\w-]+)\s*:", text, flags=re.M))   # noqa: E731
    return names(light), names(dark[:dark.index("}")])


def _page_colors():
    text = PAGE.read_text(encoding="utf-8") + "".join(p.read_text(encoding="utf-8") for p in PAGE_JS_FILES)
    return {_norm(c) for c in re.findall(COLOR, text)}


def _doc_mapping():
    rows = re.findall(r"^\| `([^`]+)` \| \d+ \| `([^`]+)` \|", DOC.read_text(encoding="utf-8"), flags=re.M)
    return {_norm(c): tok for c, tok in rows}


def _existing_tokens():
    css = CSS.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*(--[\w-]+)\s*:", css, flags=re.M))


def test_every_page_color_has_a_token_in_the_table():
    mapping = _doc_mapping()
    missing = sorted(_page_colors() - set(mapping))
    assert not missing, "案件頁有色碼沒有列進對照表：%s" % missing


def test_every_token_in_the_table_exists():
    defined = _existing_tokens()
    bad = sorted({t for t in _doc_mapping().values() if t not in defined})
    assert not bad, "對照表指到不存在的 token：%s" % bad


def test_dark_group_defines_every_new_token():
    light, dark = _token_blocks()
    assert light, "量尺：淺色組應該有 token"
    assert light == dark, ("淺色有、深色沒有：%s；深色多出：%s" % (sorted(light - dark), sorted(dark - light)))


def test_positive_control_the_scanner_sees_known_colors():
    colors = _page_colors()
    assert "#92400e" in colors and "#ffffff" in colors, "量尺：掃描器應該看得到案件頁的琥珀字與白底"


def _small_fonts():
    s = PAGE.read_text(encoding="utf-8")
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return [float(v) for v in re.findall(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", s) if float(v) < 11]


@pytest.mark.xfail(strict=True, reason="CM12 P3 尚未套用：案件頁仍有 font-size < 11px（現況 %d 處）；"
                                        "P3 套完這題會轉綠，strict 讓它紅 ⇒ 屆時拿掉 xfail" % SMALL_FONT_NOW)
def test_case_page_has_no_font_smaller_than_11px():
    assert not _small_fonts()


def test_small_font_count_only_goes_down():
    n = len(_small_fonts())
    assert n <= SMALL_FONT_NOW, "案件頁 font-size < 11px 從 %d 處增加到 %d 處" % (SMALL_FONT_NOW, n)
