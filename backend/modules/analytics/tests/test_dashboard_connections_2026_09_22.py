"""§3i · `dashboard.py` 的每一支端點都不可以洩漏資料庫連線。

## 🔴 現況（B 用 AST 掃出來的，我複核過）

```
函式                          get_db@        .close()@   finally
dashboard_monthly              [350]          []          0     ← 開了從不關
dashboard_expenses_monthly     [440, 469]     [516]       0     ← 開兩次只關一次
（其餘七支都成對，但**全部都沒有 finally**）
```

⚠️ **兩支都在首頁會打的端點上** —— 而首頁七天 1,044 次，全站最高。

## 🔑 判準是**行為**，不是**形狀**

**不釘 `with`，也不釘「`open` 與 `close` 數量相等」。** 兩個理由：

**① 數量判準抓得到那兩支，抓不到另外七支**（B 指出）——
七支在**正常路徑**下是成對的，而它們沒有 `finally`
⇒ **中途丟例外就一樣洩漏**。那是「比較少見但後果一樣」的路徑。
📌 那是〈判準的寬窄都會騙人〉：**太窄會讓另外七支看起來是安全的。**

**② 釘 `with` 是釘一種寫法。** `try/finally` 與 `with` 在行為上等價
⇒ 一個用 `try/finally` 寫對的實作會**紅在一個正確的修法上**。
⚠️ 我今晚已經犯過一次（CSP 那題釘「必須是萬用子網域」，而條款其實要單一主機）——
🔑 **我把「今天的慣用法」寫成不變量，那是同一個錯的第二次機會。**

> 🔑 **一個剛好會過的題目，跟一個驗對了東西的題目，在綠燈上長得一樣。**（A 的話）

## ⚠️ 觀測點：**包住 `db.get_db`** —— 連線真正被開出來的那一層

第一版包的是 `routers.dashboard.get_db`（`dashboard.py:11` 的那份副本），
依據是「**patch 目標要走模組**」。⚠️ 而 B 把九支轉成 `with db_conn()` 之後，
`dashboard.py` 裡**再也沒有一處裸的 `get_db()`** ⇒ 那個名字再也不會被呼叫。

🔑 **「走模組」保證你打得到，不保證你打在連線真的被開出來的那一層。**
📌 細節在 `ledger` fixture 的說明裡。

2026-09-26（稽核 ⑰ M-1）：帳本改用 `tests/_db_ledger.py`——在 **`sqlite3.connect`** 這一層記帳並記下呼叫堆疊。
包 `db.get_db` 那一版看不到 `from db import get_db` 綁名的 helper 開的連線；而改在最底層之後，
「它真的開了至少一個連線」要看**端點自己**（堆疊經過 dashboard.py）開的，不然中介層驗 token 開的就會讓前提空綠。
L1（GCIS、`/api/now`）與 M01（`/api/sales-orders`）那幾支已搬到 `tests/platform/test_l1_connections.py`。
"""

import pytest

import modules.analytics.api.dashboard as dash
from tests import _db_ledger as L

#: `dashboard.py` 的每一支 GET 端點（全部都查資料庫；沒有豁免）。
DASHBOARD_PATHS = (
    "/api/dashboard/stats",
    "/api/dashboard/monthly",
    "/api/dashboard/expenses-monthly",
    "/api/devices",
    "/api/dashboard/funnel",
    "/api/dashboard/ops-alerts",
    "/api/materials-summary",
    "/api/dashboard/activity-feed",
)
DASH_FILE = dash.__file__


@pytest.fixture()
def ledger(monkeypatch):
    return L.install(monkeypatch)


def _auth(client, make_user):
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.mark.parametrize("path", DASHBOARD_PATHS)
def test_the_endpoint_closes_every_connection_it_opens(client, make_user, ledger, path):
    """🔴 打一次端點，整個請求開出去的連線要全部被關回來；前提：**端點自己**真的開了至少一個。"""
    hdr = _auth(client, make_user)
    L.reset(ledger)
    r = client.get(path, headers=hdr)
    assert r.status_code in (200, 404), f"{path} 回 {r.status_code}：{r.text[:200]}"
    assert L.opened_from(ledger, DASH_FILE) >= 1, f"{path} 自己一個連線都沒開 —— 前提不成立（它沒有查資料庫？）"
    leaked = ledger["open"] - ledger["closed"]
    assert leaked == 0, f"{path} 開了 {ledger['open']} 個連線，只關了 {ledger['closed']} 個（洩漏 {leaked} 個）"


def test_repeated_calls_do_not_accumulate_connections(client, make_user, ledger):
    """🔴 連打十次，未關閉的連線數不成長（洩漏是斜率不是截距）。"""
    hdr = _auth(client, make_user)
    L.reset(ledger)
    for _ in range(10):
        client.get("/api/dashboard/expenses-monthly", headers=hdr)
    assert L.opened_from(ledger, DASH_FILE) >= 10
    assert ledger["open"] == ledger["closed"], (ledger["open"], ledger["closed"])


@pytest.mark.parametrize("path", DASHBOARD_PATHS)
def test_a_failure_midway_still_closes_the_connection(client, make_user, ledger, monkeypatch, path):
    """🔴🔴 端點自己的查詢中途丟例外時，連線仍然要被關（只炸堆疊經過 dashboard.py 的查詢；中介層照常）。"""
    hdr = _auth(client, make_user)
    L.explode_in(monkeypatch, ledger, DASH_FILE)
    L.reset(ledger)
    try:
        client.get(path, headers=hdr)
    except Exception:            # noqa: BLE001  端點可能把它往外丟
        pass
    if not ledger.get("exploded"):
        pytest.skip(f"{path} 的查詢不經 dashboard.py 裡的 execute ⇒ 這一題對它不適用")
    leaked = ledger["open"] - ledger["closed"]
    assert leaked == 0, f"{path} 在查詢中途丟例外之後，洩漏了 {leaked} 個連線（開 {ledger['open']}、關 {ledger['closed']}）"


def test_every_endpoint_is_covered():
    """🟢 `dashboard.py` 註冊的每一支 GET 都在清單上（讀真的被註冊的路由，不是原始碼文字）；清單上沒有已不存在的。"""
    registered = {r.path for r in dash.router.routes if "GET" in getattr(r, "methods", set())}
    assert registered, "前提不成立：`dash.router` 一支 GET 路由都沒有"
    assert registered == set(DASHBOARD_PATHS), (sorted(registered - set(DASHBOARD_PATHS)), sorted(set(DASHBOARD_PATHS) - registered))
