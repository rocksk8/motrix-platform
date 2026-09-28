# -*- coding: utf-8 -*-
"""API 文件頁預設關閉（2026-09-28 主持裁示；E 盤點：/openapi.json、/docs、/docs/oauth2-redirect、/redoc 未登入可讀）。

- 預設（沒有 MOTRIX_API_DOCS=1）⇒ 四條都 404（FastAPI 不註冊這些路由）；
- 反向控制：旗標開 ⇒ 同一支設定函式建出的 app 四條都 200（證明 404 是旗標造成的，不是路徑寫錯）；
- 只認旗標：值不是 "1"（"0"、"true"、空）一律關；不看安裝路徑（記憶〈不可以用安裝路徑猜正式機〉）；
- 依賴 /openapi.json 的內部工具改走別的路：payroll 題改 `client.app.openapi()`、final_drill 演練伺服器自己帶旗標。
"""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

DOC_PATHS = ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc")


def _main():
    return sys.modules["main"]


@pytest.mark.parametrize("path", DOC_PATHS)
def test_docs_routes_are_off_by_default(client, path):
    assert client.get(path).status_code == 404, "%s 未登入可讀（應預設關閉）" % path


def test_reverse_control_flag_on_registers_all_four():
    kw = _main()._docs_kwargs({"MOTRIX_API_DOCS": "1"})
    app = FastAPI(docs_url=kw["docs_url"], redoc_url=kw["redoc_url"], openapi_url=kw["openapi_url"])
    c = TestClient(app)
    for p in DOC_PATHS:
        assert c.get(p).status_code == 200, p


@pytest.mark.parametrize("value", [None, "", "0", "true", "yes", " 1"])
def test_only_the_exact_flag_turns_docs_on(value):
    env = {} if value is None else {"MOTRIX_API_DOCS": value}
    assert _main()._docs_kwargs(env) == {"docs_url": None, "redoc_url": None, "openapi_url": None}


def test_app_schema_is_still_available_in_process(client):
    """關掉的是對外路由，不是 schema 本身：程式內（測試、工具）仍可 app.openapi()。"""
    assert "/api/system/version" in client.app.openapi()["paths"]


def test_final_drill_server_turns_docs_on_for_its_crawl():
    src = (Path(__file__).resolve().parents[2] / "tools" / "platform" / "final_drill.py").read_text(encoding="utf-8")
    i = src.index("def smoke(")
    assert '"MOTRIX_API_DOCS": "1"' in src[i:i + 800], "final_drill 的 GET 全掃靠 /openapi.json，演練伺服器要帶旗標"
