# -*- coding: utf-8 -*-
"""字型授權（OFL §2：散布字型時授權檔必須跟著）：每個隨產品散布的字型資料夾都有授權檔；授權檔是 OFL 1.1；查證出處與日期有記錄。"""
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
FONTS = REPO / "frontend" / "fonts"
FONT_EXT = (".woff2", ".woff", ".ttf", ".otf")


def _fonts():
    return sorted(p for p in FONTS.rglob("*") if p.suffix.lower() in FONT_EXT)


def test_there_are_bundled_fonts_and_every_font_folder_has_an_ofl_file():
    fonts = _fonts()
    assert fonts, "frontend/fonts 底下沒有字型？（守門的對象不見了）"
    for f in fonts:
        assert (f.parent / "OFL.txt").is_file(), "%s 旁邊沒有 OFL.txt（OFL §2）" % f.relative_to(REPO)


def test_ofl_text_is_1_1_with_the_copyright_line_and_full_body():
    t = (FONTS / "OFL.txt").read_text(encoding="utf-8")
    assert "Copyright (c) LY Corporation" in t or "LY Corporation" in t
    assert "SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007" in t
    for clause in ("PREAMBLE", "PERMISSION & CONDITIONS", "TERMINATION", "DISCLAIMER"):
        assert clause in t, "OFL 全文缺 %s 段" % clause


def test_readme_records_the_official_source_and_the_access_date():
    r = (FONTS / "README.md").read_text(encoding="utf-8")
    assert "https://seed.line.me/index_tw.html" in r and "https://github.com/line/seed" in r
    assert re.search(r"存取日\s*\*{0,2}\s*20\d\d-\d\d-\d\d", r), "查證日期沒記"
    assert "SIL Open Font License" in r and "逐字相同" in r


def test_third_party_doc_lists_the_fonts_with_their_license_file():
    d = (REPO / "docs" / "platform" / "THIRD-PARTY-LICENSES.md").read_text(encoding="utf-8")
    assert "LINE Seed TW" in d and "frontend/fonts/OFL.txt" in d and "SIL Open Font License 1.1" in d


def test_license_and_fonts_are_shipped_together_not_export_ignored():
    """`git archive` 出貨時 OFL.txt 與字型必須一起出去：兩者都不是 export-ignore。"""
    for rel in ["frontend/fonts/OFL.txt"] + [str(f.relative_to(REPO)).replace("\\", "/") for f in _fonts()]:
        r = subprocess.run(["git", "-C", str(REPO), "check-attr", "export-ignore", rel], capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout.strip().endswith("unspecified"), (rel, r.stdout)
