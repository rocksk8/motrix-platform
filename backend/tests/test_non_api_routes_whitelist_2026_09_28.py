# -*- coding: utf-8 -*-
"""不在 `/api/` 底下的路由＝**不經登入檢查**（auth_middleware：「非 /api/ 一律放行」是設計）。

D 稽核 E3-S2（2026-09-28，E 線附近旅宿加了 `/map-overlays/…`）：這一類路由沒有題目列出它們 ⇒
下一條回傳資料的非 /api 路由會直接變成公開端點，而沒有人做過決定。
⇒ 列出 app 裡所有不在 `/api/` 的路由（含 include 進來的子 router，逐層帶前綴），比對白名單；
   新增要一起改白名單並寫理由（＝有人做過決定）；白名單過期（路由不在了）也紅。
"""
from starlette.routing import Mount

#: 路徑 ⇒ 理由（至少 20 字）。**只放不回傳資料、或本身自己驗證的路由。**
ALLOWED = {
    "/pages/{name:path}":
        "頁面 HTML（core.pages）：靜態頁本體，不含資料；模組未載入 ⇒ 404＋提示頁。資料一律經 /api 各自驗權限",
    "/map-overlays/{module_key}/{script}":
        "地圖覆蓋層腳本（IP-101，helpers.map_overlays）：<script src> 帶不了 token；只給已載入模組宣告的 .js，內容是程式碼不含資料",
    "/static/sidebar.js":
        "側欄腳本（前置選單宣告 window.MOTRIX_MENU）：與使用者無關的 L1＋已載入模組選單宣告，不含任何使用者資料",
    "/":
        "首頁 index.html（靜態檔），登入導向由前端 auth-guard 處理，不含資料",
    "<mount>":
        "StaticFiles 掛在根目錄：frontend/ 底下的靜態檔（HTML／CSS／JS／圖），不含資料",
    # 2026-09-28 主持裁示：FastAPI 的 /openapi.json、/docs、/docs/oauth2-redirect、/redoc 預設關閉
    # （main.MOTRIX_API_DOCS，test_api_docs_off_2026_09_28）⇒ 從白名單移除（原四條為 E 盤點時列出待裁示）
}


def non_api_routes(app):
    """app 內所有不在 `/api/` 底下的路由路徑（include 進來的子 router 逐層帶前綴；Mount 記成 '<mount>' 或其路徑）。"""
    out = set()

    def walk(routes, prefix=""):
        for r in routes:
            if type(r).__name__ == "_IncludedRouter":          # FastAPI include_router 的包裝
                walk(r.original_router.routes, prefix + (getattr(r.include_context, "prefix", "") or ""))
                continue
            if isinstance(r, Mount):
                path = prefix + (r.path or "")
                out.add(path if path else "<mount>")
                continue
            path = prefix + (getattr(r, "path", "") or "")
            if not path.startswith("/api/"):
                out.add(path)
    walk(app.routes)
    return out


def check(found, allowed=ALLOWED):
    problems = ["不在 /api 底下、沒有登入檢查的路由沒有登記：%s ⇒ 確認不回傳資料後附理由登記" % p
                for p in sorted(found - set(allowed))]
    problems += ["白名單 %s 已不存在（過期）⇒ 刪掉這一筆" % p for p in sorted(set(allowed) - found)]
    problems += ["白名單 %s 的理由太短（至少 20 字）" % p for p, why in allowed.items() if len((why or "").strip()) < 20]
    return problems


def test_every_non_api_route_is_decided(client):
    found = non_api_routes(client.app)
    assert len(found) >= 5, found                                   # 正對照：真的走到了路由表（含 include 的子 router）
    problems = check(found)
    assert not problems, "\n".join(problems)


def test_positive_control_a_new_public_route_in_an_included_router_lights_up():
    from fastapi import APIRouter, FastAPI
    app = FastAPI()
    sub = APIRouter()

    @sub.get("/export/{x}")
    def leak(x: str):
        return {"x": x}

    @sub.get("/api/fine")
    def fine():
        return {}
    app.include_router(sub, prefix="/data")                         # 前綴也要算進去
    app.include_router(sub)
    found = non_api_routes(app) - {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    assert found == {"/data/export/{x}", "/data/api/fine", "/export/{x}"}
    problems = check(found, {"/export/{x}": "合成：理由寫得夠長的一筆白名單，用來驗證比對邏輯"})
    assert any("/data/export/{x}" in p for p in problems) and any("/data/api/fine" in p for p in problems)
    assert not any("：/export/{x} ⇒" in p for p in problems)            # 已登記的那一條不報


def test_reverse_control_stale_or_thin_whitelist_is_red():
    problems = check({"/"}, {"/": "x", "/gone": "這一條路由已經不存在了，白名單應該被判定為過期"})
    assert any("/gone" in p and "過期" in p for p in problems) and any("太短" in p for p in problems)
