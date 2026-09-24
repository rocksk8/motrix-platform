"""地圖圖磚一律在瀏覽器端攔下，回一張 1×1 空白 png（2026-09-25）。

map.html 的底圖從 tile.openstreetmap.org 載；測試不攔的話每跑一次就真的連 OSM
（`conftest.py::_browser_netguard` 會讓那一題紅）。
"""
import base64

BLANK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


def block_tiles(page_or_context):
    page_or_context.route("**/tile.openstreetmap.org/**",
                          lambda r: r.fulfill(status=200, content_type="image/png", body=BLANK_PNG))
