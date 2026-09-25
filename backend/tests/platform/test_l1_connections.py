"""L1 公司查詢（`routers/company_lookup.py`）與 `/api/sales-orders`（M01）的連線關閉＋豁免守門。

M08 搬遷時 `test_dashboard_connections` 隨營運分析模組搬進 modules/analytics/tests；這兩處原本也由它驗，
模組不在時就沒有人驗（覆蓋率倒退，主持 2026-09-26 裁示補回 L1）。做法與原檔相同：
包 `db.get_db`（連線真正被開出來的那一層），登入後帳本歸零，再打端點。

- 豁免（不碰資料庫）：`/api/now` 與兩支 GCIS 代理——反向控制：真的一個連線都不開（GCIS 換掉產品自己的接縫 `_gcis_get`，不放行 NETGUARD）
- `/api/sales-orders`：M01 的端點，暫放本檔（M01 尚未搬進 modules/）；**依路由有沒有被註冊篩選**——
  M01 不在這棵樹 ⇒ skip 並寫明，不紅、也不假裝驗過
- 歸屬：company_lookup 註冊的每一支 GET 都要在「查資料庫」或「豁免」其中一邊
"""
import pytest

import routers.company_lookup as lookup

#: 查資料庫、必須打平連線的端點 ⇒ 擁有者（M01 搬進 modules/ 之後改成它的 module key）
DB_PATHS = {"/api/sales-orders": "M01"}
EXEMPT = {
    "/api/now": "只回 datetime.now()，一行資料庫都不碰",
    "/api/company/tax/{tax_id}": "GCIS 政府開放資料純查詢，不碰資料庫",
    "/api/company/search": "GCIS 政府開放資料純查詢，不碰資料庫",
}


class _TrackedConnection:
    def __init__(self, conn, ledger):
        self._conn = conn
        self._ledger = ledger
        ledger["open"] += 1

    def close(self):
        if not getattr(self, "_closed", False):
            self._closed = True
            self._ledger["closed"] += 1
        return self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture()
def ledger(monkeypatch):
    import db as db_module
    book = {"open": 0, "closed": 0}
    real = db_module.get_db
    monkeypatch.setattr(db_module, "get_db", lambda *a, **kw: _TrackedConnection(real(*a, **kw), book))
    return book


def _auth(client, make_user, ledger):
    """登入後帳本歸零：make_user 與 /api/auth/login 自己就會開連線，不歸零「至少開一個」的前提會空綠。"""
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    ledger["open"] = ledger["closed"] = 0
    return {"Authorization": "Bearer " + r.json()["token"]}


def _registered_gets(app):
    from tests._routes import all_routes    # FastAPI 0.14x 的 include_router 要攤平才看得到路徑
    return {p for p, methods, _r in all_routes(app) if "GET" in methods}


def test_route_lookup_sees_registered_routes(client):
    """正對照：路由篩選看得到確定存在的 L1 路由（否則 DB_PATHS 那幾題會全部假 skip）。"""
    assert set(EXEMPT) <= _registered_gets(client.app)


def _require_route(client, path):
    if path not in _registered_gets(client.app):
        pytest.skip("%s 沒有註冊（擁有者 %s 不在這棵樹）⇒ 這一題對它不適用" % (path, DB_PATHS[path]))


@pytest.mark.parametrize("path", sorted(DB_PATHS))
def test_db_endpoint_closes_every_connection_it_opens(client, make_user, ledger, path):
    _require_route(client, path)
    hdr = _auth(client, make_user, ledger)
    r = client.get(path, headers=hdr)
    assert r.status_code == 200, r.text[:200]
    assert ledger["open"] >= 1, "%s 一個連線都沒開 —— 前提不成立（它沒有查資料庫？）" % path
    assert ledger["open"] == ledger["closed"], ledger


@pytest.mark.parametrize("path", sorted(DB_PATHS))
def test_db_endpoint_closes_the_connection_when_a_query_fails(client, make_user, ledger, monkeypatch, path):
    _require_route(client, path)
    hdr = _auth(client, make_user, ledger)

    def _explode(self, *a, **kw):
        raise RuntimeError("查詢中途爆炸")
    monkeypatch.setattr(_TrackedConnection, "execute", _explode, raising=False)
    try:
        client.get(path, headers=hdr)
    except Exception:   # noqa: BLE001  端點可能把它往外丟
        pass
    assert ledger["open"] >= 1, "%s 在爆炸前沒有開連線 —— 前提不成立" % path
    assert ledger["open"] == ledger["closed"], ledger


@pytest.mark.parametrize("path", sorted(EXEMPT))
def test_exempt_endpoint_really_does_not_touch_the_database(client, make_user, ledger, monkeypatch, path):
    monkeypatch.setattr(lookup, "_gcis_get", lambda *a, **kw: ([], None))
    hdr = _auth(client, make_user, ledger)
    url = path.replace("{tax_id}", "12345678")
    if url.endswith("/api/company/search"):
        url += "?q=motrix"
    r = client.get(url, headers=hdr)
    assert r.status_code in (200, 404), r.text[:200]
    assert ledger["open"] == 0, "%s 列為豁免（%s），卻開了 %d 個連線" % (path, EXEMPT[path], ledger["open"])


def test_every_company_lookup_route_is_accounted_for():
    """company_lookup 註冊的 GET 路由＝EXEMPT ∪（DB_PATHS 裡屬於它的）；新增一支沒有歸屬 ⇒ 紅。"""
    registered = {r.path for r in lookup.router.routes if "GET" in (getattr(r, "methods", None) or set())}
    assert registered, "前提不成立：company_lookup 一支 GET 路由都沒有"
    assert registered - set(EXEMPT) - set(DB_PATHS) == set()
    assert set(EXEMPT) - registered == set(), "EXEMPT 裡有已不存在的路由"


def test_ledger_sees_connections_opened_through_db_conn(client, ledger):
    """反向控制：帳本真的看得到 `db.db_conn()` 開的連線（端點取連線的那一層）——看不到 ⇒ 豁免題的「0 個」不可信。
    ⚠ 不用「打某支 L1 端點」當對照：`from db import get_db` 綁了名字的端點繞過帳本（實測 /api/customers 開 0 個），
    那量到的是端點的 import 寫法，不是帳本。"""
    import db
    with db.db_conn() as conn:
        conn.execute("SELECT 1")
    assert (ledger["open"], ledger["closed"]) == (1, 1), ledger
