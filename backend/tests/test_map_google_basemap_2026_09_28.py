# -*- coding: utf-8 -*-
"""第十五班 ②(b)：有地圖（瀏覽器）金鑰 ⇒ Google 底圖（Maps JavaScript API）；金鑰分兩把（使用者裁示，CORE-SPEC dee64c54）。

- `/api/map/config`：沒有瀏覽器金鑰 ⇒ osm；有 ⇒ google＋那一把；每次回 google 記一次 `google:dynamic-maps`（近似）。
- 🔴 伺服器定位那把（google_maps_api_key）**永不外流**：地圖設定、地圖點、公司資料、額度設定的回應都不含它；
  另以原始碼守門：讀那一把的地方只准在白名單檔案裡（新的讀取點要先過審）。
- 瀏覽器金鑰在設定頁同樣遮蔽、稽核不記值；`geo.google_basemap()` 跟著它。
- CSP：只有地圖頁放寬到 Google 網域（官方 Allowlist CSP 範例），其他頁不變。
"""
import ast
from pathlib import Path

import pytest

from helpers import geo

SERVER_KEY = "AIzaSyServerKeyNeverLeaves0123456789ab"
BROWSER_KEY = "AIzaSyBrowserKeyForMapsJs0123456789cd"
PROFILE = "/api/settings/company-profile"


@pytest.fixture()
def h(client, make_user, monkeypatch):
    monkeypatch.setattr(geo, "tiles_blocked", lambda: None)
    u, p = make_user(username="gbm_admin", role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _set_keys(server=SERVER_KEY, browser="", map_id=None):
    """map_id 省略 ⇒ 有瀏覽器金鑰就一併填地圖 ID（兩項都有才切 Google，使用者裁示）。"""
    from helpers.settings import _get_setting, _set_setting
    cur = _get_setting("company_profile", {}) or {}
    if map_id is None:
        map_id = "test-map-id" if browser else ""
    _set_setting("company_profile", {**cur, "google_maps_api_key": server, "google_maps_browser_key": browser,
                                     "google_maps_map_id": map_id})


def _usage(sku):
    return geo.usage_this_period(sku)


def test_no_browser_key_means_osm_and_no_key_is_returned(client, h):
    _set_keys(browser="")
    r = client.get("/api/map/config", headers=h)
    assert r.status_code == 200 and r.json() == {"basemap": "osm"}
    assert geo.google_basemap() is False


def test_browser_key_means_google_basemap_and_only_that_key_is_returned(client, h):
    _set_keys(browser=BROWSER_KEY)
    before = _usage(geo.USAGE_SKU_DYNAMIC_MAPS)
    r = client.get("/api/map/config", headers=h)
    assert r.status_code == 200
    assert r.json() == {"basemap": "google", "browserKey": BROWSER_KEY, "mapId": "test-map-id"}
    assert geo.google_basemap() is True
    assert _usage(geo.USAGE_SKU_DYNAMIC_MAPS) == before + 1, "回 Google 底圖一次要記一次 dynamic-maps（近似）"


def test_config_requires_login(client):
    assert client.get("/api/map/config").status_code == 401


@pytest.mark.parametrize("browser", ["", BROWSER_KEY])
def test_server_key_never_appears_in_any_map_or_settings_response(client, h, browser):
    _set_keys(browser=browser)
    from tests._map_cache_warm import clear_map_response_cache
    clear_map_response_cache()
    for path in ("/api/map/config", "/api/map/points?sources=customers", PROFILE, "/api/settings/google-quota"):
        r = client.get(path, headers=h)
        assert r.status_code == 200, (path, r.text)
        assert SERVER_KEY not in r.text, "伺服器定位金鑰出現在 %s 的回應" % path
    # 設定頁：兩把都遮蔽（末四碼）
    prof = client.get(PROFILE, headers=h).json()
    assert BROWSER_KEY not in str(prof)
    if browser:
        assert prof["google_maps_browser_key"].endswith(BROWSER_KEY[-4:])


def test_browser_key_saved_masked_and_never_audited_in_clear(client, h):
    r = client.put(PROFILE, json={"google_maps_browser_key": BROWSER_KEY}, headers=h)
    assert r.status_code == 200, r.text
    from helpers.settings import _get_setting
    assert _get_setting("company_profile", {})["google_maps_browser_key"] == BROWSER_KEY
    import db
    conn = db.get_db()
    try:
        rows = [dict(x) for x in conn.execute("SELECT detail FROM audit_log").fetchall()]
    finally:
        conn.close()
    assert not [x for x in rows if BROWSER_KEY in (x["detail"] or "")], "瀏覽器金鑰明文進了稽核"
    # 遮蔽字送回 ⇒ 不覆蓋
    masked = client.get(PROFILE, headers=h).json()["google_maps_browser_key"]
    assert client.put(PROFILE, json={"google_maps_browser_key": masked}, headers=h).status_code == 200
    assert _get_setting("company_profile", {})["google_maps_browser_key"] == BROWSER_KEY


def test_csp_only_the_map_page_allows_google_domains(client):
    m = client.get("/pages/map.html")
    assert m.status_code == 200
    csp = m.headers["Content-Security-Policy"]
    for part in ("https://*.googleapis.com", "https://*.gstatic.com", "worker-src blob:"):
        assert part in csp, part
    assert "https://tile.openstreetmap.org" in csp, "沒有瀏覽器金鑰時地圖頁仍要能載 OSM 圖磚"
    other = client.get("/pages/login.html").headers["Content-Security-Policy"]
    assert "googleapis" not in other and "gstatic" not in other, "Google 網域放寬漏到其他頁"


# ── 原始碼守門：讀伺服器金鑰的地方只准在白名單 ──────────────────────────────

BACKEND = Path(__file__).resolve().parents[1]
#: 讀 `google_maps_api_key`（伺服器定位金鑰）的程式檔。新增讀取點 ⇒ 這一題紅 ⇒ 先確認它不會進任何回應。
SERVER_KEY_READERS = {
    "helpers/geo.py",            # GOOGLE_KEY_SETTING 定義、_google_key_configured、_locate_google
    "routers/system.py",         # 公司資料模型／遮蔽／稽核（回應一律遮蔽）
    "routers/map_points.py",     # 只取 bool（googleMapsConfigured）
}


def test_only_whitelisted_files_read_the_server_key():
    hits = set()
    for p in BACKEND.rglob("*.py"):
        rel = p.relative_to(BACKEND).as_posix()
        if "/tests/" in "/" + rel or rel.startswith("tests/") or "__pycache__" in rel:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        # 用 AST：只算程式裡真的用到那個鍵（字串常數整段相等、或名稱 GOOGLE_KEY_SETTING），
        # 註解與 docstring 裡提到它不算（voucher_pdf 的 docstring 寫了「不讓那包東西流進 PDF」）
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and node.value == "google_maps_api_key") or \
               (isinstance(node, ast.Name) and node.id == "GOOGLE_KEY_SETTING") or \
               (isinstance(node, ast.Attribute) and node.attr == "GOOGLE_KEY_SETTING"):
                hits.add(rel)
                break
    extra = hits - SERVER_KEY_READERS
    assert not extra, "新的檔案讀了伺服器定位金鑰：%s ⇒ 確認不會進任何回應後再加進白名單" % sorted(extra)
    assert hits, "正對照：至少 geo.py 讀得到（掃描器沒壞）"


def test_map_id_is_returned_when_set(client, h):
    _set_keys(browser=BROWSER_KEY, map_id="abc123mapid")
    assert client.get("/api/map/config", headers=h).json()["mapId"] == "abc123mapid"


@pytest.mark.parametrize("browser,map_id", [(BROWSER_KEY, ""), ("", "abc123mapid")])
def test_only_one_of_key_and_map_id_means_osm_and_no_key_is_returned(client, h, browser, map_id):
    """使用者裁示：瀏覽器金鑰＋地圖 ID 兩項都填才切 Google；缺一項 ⇒ osm、不回任何金鑰、不記地圖載入。"""
    _set_keys(browser=browser, map_id=map_id)
    before = _usage(geo.USAGE_SKU_DYNAMIC_MAPS)
    r = client.get("/api/map/config", headers=h)
    assert r.json() == {"basemap": "osm"}
    assert BROWSER_KEY not in r.text and SERVER_KEY not in r.text
    assert geo.google_basemap() is False
    assert _usage(geo.USAGE_SKU_DYNAMIC_MAPS) == before


def test_demo_map_id_never_appears_in_product_code():
    """DEMO_MAP_ID 只准在測試／開發（主持裁示）：產品程式（backend 非測試、frontend）不可以出現它，也不可以預設它。"""
    root = BACKEND.parent
    bad = []
    for base in (BACKEND, root / "frontend"):
        for p in base.rglob("*"):
            if p.suffix not in (".py", ".js", ".html", ".json") or not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if "/tests/" in rel or "__pycache__" in rel or "/vendor/" in rel:
                continue
            if "DEMO_MAP_ID" in p.read_text(encoding="utf-8", errors="replace"):
                bad.append(rel)
    assert not bad, bad
