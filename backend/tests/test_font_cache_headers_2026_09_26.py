# -*- coding: utf-8 -*-
"""字型快取（D 調查 O5 的 S3 第一步）：/fonts/ 給 7 天快取＋可重新驗證；頁面、css、js 照舊不快取（反向控制）。"""
from pathlib import Path

FONTS = Path(__file__).resolve().parents[2] / "frontend" / "fonts"


def test_fonts_are_cacheable_and_revalidatable(client):
    names = sorted(p.name for p in FONTS.iterdir() if p.suffix in (".otf", ".woff2", ".woff", ".ttf"))
    assert names, "正對照：frontend/fonts 底下要有字型"
    for n in names:
        r = client.get("/fonts/" + n)
        assert r.status_code == 200, n
        cc = r.headers.get("cache-control", "")
        assert "max-age=604800" in cc and "no-store" not in cc and "immutable" not in cc, (n, cc)
        assert r.headers.get("etag") or r.headers.get("last-modified"), "要能重新驗證：%s" % n


def test_pages_css_js_are_still_not_cached(client):
    """反向控制：字型規則不可以吃到頁面、css、js（它們會頻繁覆寫，一律 no-store）。"""
    for path in ("/css/style.css", "/pages/login.html"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "no-store" in r.headers.get("cache-control", ""), (path, r.headers.get("cache-control"))



def test_css_references_only_existing_fonts_and_license_ships_with_them():
    """U19（使用者表單：確認 OFL）：CSS 引用的字型檔都存在；字型隨附 OFL.txt（OFL §2 散布時必須附上授權）。"""
    import re as _re
    css = (FONTS.parent / "css" / "style.css").read_text(encoding="utf-8")
    refs = _re.findall(r"url\('\.\./fonts/([^']+)'\)", css)
    assert refs, "正對照：style.css 要有 @font-face"
    missing = [r for r in refs if not (FONTS / r).is_file()]
    assert not missing, missing
    lic = (FONTS / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in lic and "LY Corporation" in lic



def test_woff2_is_served_as_font_woff2(client):
    """D 稽核觀察 1：woff2 的 Content-Type 固定為 font/woff2（不依賴主機的 mimetypes 登錄表）。"""
    names = sorted(p.name for p in FONTS.iterdir() if p.suffix == ".woff2")
    assert names, "正對照：要有 woff2"
    for n in names:
        assert client.get("/fonts/" + n).headers.get("content-type", "").startswith("font/woff2"), n
