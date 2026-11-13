# -*- coding: utf-8 -*-
"""模組資產 POC：subcontract 自有的 `remit-kinds-settings.js`（真實 app；合成樹的契約在 tests/platform/test_module_assets_contract）。

① 載入時網址 `/js/remit-kinds-settings.js` 回 200、javascript、本文＝模組內的檔（逐位元組）；頁面的 `<script src>` 沒變。
② 沒有 `frontend/js` 的同名舊檔（同網址只能有一個來源）。
③ 模組不在已載入清單（停用／未授權／失敗共同的結果）⇒ 404。
④ 宣告了卻缺檔 ⇒ 記 ERROR、404、模組仍 loaded。
"""
import logging
from pathlib import Path

from core import registry, source_tree
from helpers import module_assets
from tests import _frontend_sources as FS

MOD = Path(__file__).resolve().parents[1]
JS = MOD / "js" / "remit-kinds-settings.js"
URL = "/js/remit-kinds-settings.js"
PAGE = source_tree.page_file("remit-kinds-settings.html")


def test_loaded_module_serves_its_js_byte_for_byte_at_the_unchanged_url(client):
    r = client.get(URL)
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert r.content == JS.read_bytes()
    assert r.headers.get("cache-control") == "no-cache"               # 沒帶 ?v= ⇒ 每次都問（帶目前版本才 immutable，見 static_cache）
    assert client.head(URL).status_code == 200


def test_page_still_points_at_the_same_url_and_no_orphan_copy_is_left_in_frontend(client):
    assert '<script src="../js/remit-kinds-settings.js">' in PAGE.read_text(encoding="utf-8")
    assert not (FS.FRONTEND / "js" / "remit-kinds-settings.js").exists()


def test_neighbouring_frontend_js_is_still_served(client):
    assert client.get("/js/def-governance.js").status_code == 200


def test_module_not_loaded_means_404(client):
    snap = registry.snapshot()
    try:
        registry.unload("subcontract", "合成：停用")
        assert client.get(URL).status_code == 404
    finally:
        registry.restore(snap)
    assert client.get(URL).status_code == 200


def test_declared_but_missing_logs_error_404_and_the_module_stays_loaded(client, caplog):
    snap = registry.snapshot()
    module_assets._logged.clear()
    lm = next(m for m in registry.loaded() if m.key == "subcontract")
    saved = lm.manifest["assets"]
    try:
        lm.manifest["assets"] = [{"path": "js/remit-kinds-settings.js"}, {"path": "js/ghost-asset.js"}]
        with caplog.at_level(logging.ERROR):
            assert client.get("/js/ghost-asset.js").status_code == 404
            assert client.get(URL).status_code == 200
        assert any("ghost-asset.js" in r.getMessage() for r in caplog.records)
        assert registry.is_loaded("subcontract")
    finally:
        lm.manifest["assets"] = saved                 # snapshot 不複製 manifest 本身
        registry.restore(snap)
        module_assets._logged.clear()
