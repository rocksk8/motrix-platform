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
