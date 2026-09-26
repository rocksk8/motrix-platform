"""L1 公司查詢（`routers/company_lookup.py`）與 `/api/sales-orders`（M01）的連線關閉＋豁免守門。

M08 搬遷時 `test_dashboard_connections` 隨營運分析模組搬進 modules/analytics/tests；這幾處原本也由它驗，
模組不在時就沒有人驗（覆蓋率倒退，主持 2026-09-26 裁示補回 L1）。

觀測點：`tests/_db_ledger.py` 在 **`sqlite3.connect`** 這一層記帳，並記下每一個連線被開出來時的呼叫堆疊
（稽核 ⑰ M-1：第一版只包 `db.get_db` 這個名字，`from db import get_db` 綁名的 helper 開的連線看不到——
兩支 GCIS「豁免」端點實際每次多開 5 個，豁免題照樣判 0）。
- 端點「自己」開的＝堆疊經過端點所在原始檔的連線（含它呼叫的 helper）；中介層（驗 token）開的不算。
  ⚠ 不用「減掉一支空路由的基準」：`/api/now` 是公開路由，中介層對它開的連線比對需驗證的路由少，基準會算出負數。
- **豁免**（端點本身一個連線都不開）：只有 `/api/now`
- **查資料庫、必須打平**：GCIS 兩支（額度計數讀寫設定）、`/api/sales-orders`（M01；路由沒註冊 ⇒ skip 寫明）；
  整個請求開的全部要關，正常路徑與「端點自己的查詢中途丟例外」都一樣
- 歸屬：company_lookup 註冊的每一支 GET 都要在兩邊其中之一
"""
import pytest

import routers.company_lookup as lookup
from tests import _db_ledger as L

#: 查資料庫、必須打平連線 ⇒ 擁有者（M01 搬進 modules/ 之後改成它的 module key）
DB_PATHS = {
    "/api/sales-orders": "M01",
    "/api/company/tax/{tax_id}": "L1",      # GCIS 查詢本身不碰庫，但每日額度計數讀寫 system_settings
    "/api/company/search": "L1",
}
EXEMPT = {"/api/now": "只回 datetime.now()，端點本身一個連線都不開"}


def _url(path):
    url = path.replace("{tax_id}", "12345678")
    return url + "?q=motrix" if url.endswith("/api/company/search") else url


@pytest.fixture()
def ledger(monkeypatch):
    return L.install(monkeypatch)


def _drop_route(app, path):
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != path]


def _add_front(app, path, fn):
    """臨時 GET 放在路由表最前面（根目錄的靜態檔 mount 會吃掉後加的路徑 ⇒ 404）。"""
    app.router.add_api_route(path, fn, methods=["GET"])
    app.router.routes.insert(0, app.router.routes.pop())


def _auth(client, make_user):
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _registered_gets(app):
    from tests._routes import all_routes    # FastAPI 0.14x 的 include_router 要攤平才看得到路徑
    return {p for p, methods, _r in all_routes(app) if "GET" in methods}


def _endpoint_file(app, path):
    from tests._routes import all_routes
    for p, methods, r in all_routes(app):
        if p == path and "GET" in methods:
            ep = getattr(r, "endpoint", None)
            return ep.__code__.co_filename if ep else None
    return None


def _hit(client, ledger, path, hdr):
    """打一次端點 ⇒ (回應, 端點自己開的, 整個請求開的, 整個請求關的)。"""
    src = _endpoint_file(client.app, path)
    assert src, "找不到 %s 的端點函式" % path
    L.reset(ledger)
    r = client.get(_url(path), headers=hdr)
    return r, L.opened_from(ledger, src), ledger["open"], ledger["closed"]


def _require_route(client, path):
    if path not in _registered_gets(client.app):
        pytest.skip("%s 沒有註冊（擁有者 %s 不在這棵樹）⇒ 這一題對它不適用" % (path, DB_PATHS[path]))


def test_route_lookup_sees_registered_routes(client):
    """正對照：路由篩選看得到確定存在的 L1 路由（否則 DB_PATHS 那幾題會全部假 skip）。"""
    assert set(EXEMPT) | {"/api/company/tax/{tax_id}"} <= _registered_gets(client.app)


@pytest.mark.parametrize("path", sorted(DB_PATHS))
def test_db_endpoint_closes_every_connection_it_opens(client, make_user, ledger, monkeypatch, path):
    _require_route(client, path)
    monkeypatch.setattr(lookup, "_gcis_get", lambda *a, **kw: ([], None))
    hdr = _auth(client, make_user)
    r, own, opened, closed = _hit(client, ledger, path, hdr)
    assert r.status_code in (200, 404), r.text[:200]    # 假統編查無 ⇒ 404 是端點正常處理完的結果
    assert own >= 1, "%s 自己一個連線都沒開 —— 前提不成立（它沒有查資料庫？那就移到 EXEMPT）" % path
    assert opened == closed, "%s 開 %d 關 %d" % (path, opened, closed)


@pytest.mark.parametrize("path", sorted(DB_PATHS))
def test_db_endpoint_closes_the_connection_when_a_query_fails(client, make_user, ledger, monkeypatch, path):
    _require_route(client, path)
    monkeypatch.setattr(lookup, "_gcis_get", lambda *a, **kw: ([], None))
    hdr = _auth(client, make_user)
    L.explode_in(monkeypatch, ledger, _endpoint_file(client.app, path))
    try:
        _hit(client, ledger, path, hdr)
    except Exception:   # noqa: BLE001  端點可能把它往外丟
        pass
    if not ledger.get("exploded"):
        pytest.skip("%s 的查詢不經端點原始檔裡的 execute（全在 helper 裡）⇒ 中途失敗這一條對它無從觸發" % path)
    assert ledger["open"] == ledger["closed"], "%s 中途失敗後開 %d 關 %d" % (path, ledger["open"], ledger["closed"])


@pytest.mark.parametrize("path", sorted(EXEMPT))
def test_exempt_endpoint_really_does_not_touch_the_database(client, make_user, ledger, path):
    hdr = _auth(client, make_user)
    r, own, opened, closed = _hit(client, ledger, path, hdr)
    assert r.status_code == 200, r.text[:200]
    assert own == 0, "%s 列為豁免（%s），卻自己開了 %d 個連線" % (path, EXEMPT[path], own)
    assert opened == closed, (opened, closed)


def test_every_company_lookup_route_is_accounted_for():
    """company_lookup 註冊的 GET 路由＝EXEMPT ∪（DB_PATHS 裡屬於它的）；新增一支沒有歸屬 ⇒ 紅。"""
    registered = {r.path for r in lookup.router.routes if "GET" in (getattr(r, "methods", None) or set())}
    assert registered, "前提不成立：company_lookup 一支 GET 路由都沒有"
    assert registered - set(EXEMPT) - set(DB_PATHS) == set()
    assert set(EXEMPT) - registered == set(), "EXEMPT 裡有已不存在的路由"


def test_rc_ledger_sees_connections_opened_by_a_helper_that_binds_get_db(client, make_user, ledger):
    """反向控制（稽核 ⑰ M-1 建議）：端點經 helper（`from db import get_db` 綁名）開連線 ⇒ 算成端點自己開的；
    中介層的連線（驗 token）也看得到、但不算在端點頭上。"""
    from helpers import settings as helper_settings
    app = client.app
    probe = "/api/__ledger_probe_helper"

    def _probe():
        helper_settings._get_setting("ledger_probe", None)
        return {}
    _add_front(app, probe, _probe)
    try:
        hdr = _auth(client, make_user)
        L.reset(ledger)
        r = client.get(probe, headers=hdr)
        own = L.opened_from(ledger, __file__)
        assert r.status_code == 200, r.text[:200]
        assert own >= 1, "帳本看不到 helper 綁名 get_db 開的連線"
        assert ledger["open"] > own, "帳本看不到中介層開的連線（或把它算到端點頭上）：總 %d／端點 %d" % (ledger["open"], own)
    finally:
        _drop_route(app, probe)
