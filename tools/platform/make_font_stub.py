"""產生 e2e 用的字型替身 font_stub.ttf（O5-S1）：從零組一個合法的 TrueType（只有 .notdef 與空白），不取自任何真字型（沒有授權問題）。

e2e 每題都開新的 browser context、快取不跨題 ⇒ 每題打到頁面就下載 /fonts/ 的兩支 otf（約 10.7 MB）。
conftest 的 E2E_CONTEXT_HOOKS 把 **/fonts/* 換成這個檔；它要是**能解碼**的字型——空檔或 204 會讓瀏覽器在 console 印
「Failed to decode downloaded font」，而不少 e2e 在收 console 錯誤。

重產（只在要改它時；執行期不需要 fontTools，它不在 requirements）：
  uv run --no-project --with fonttools python tools/platform/make_font_stub.py
放在 tools/platform（不在 backend/tests）：fontTools 只是重產時要，不是測試相依（test_requirements_cover_imports 掃 tests/）
"""
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

OUT = Path(__file__).resolve().parents[2] / "backend" / "tests" / "_assets" / "font_stub.ttf"


def build():
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "space"])
    fb.setupCharacterMap({0x20: "space"})
    pen = TTGlyphPen(None)
    pen.moveTo((100, 0)); pen.lineTo((100, 700)); pen.lineTo((500, 700)); pen.lineTo((500, 0)); pen.closePath()
    empty = TTGlyphPen(None)
    fb.setupGlyf({".notdef": pen.glyph(), "space": empty.glyph()})
    fb.setupHorizontalMetrics({".notdef": (600, 100), "space": (250, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "MotrixTestStub", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    fb.setupPost()
    fb.save(str(OUT))
    return OUT


if __name__ == "__main__":
    p = build()
    print("%s %d bytes" % (p, p.stat().st_size))
