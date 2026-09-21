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

## ⚠️ 觀測點：**包住 `routers.dashboard.get_db` 這個名字**

`dashboard.py:11` 是 `from db import get_db` ⇒ **它持有一份副本**
⇒ patch `db.get_db` **打不到它**（今晚第 N 次遇到「patch 目標要走模組」）。
⇒ 所以包的是 `routers.dashboard.get_db`。
"""
import sqlite3

import pytest

import routers.dashboard as dash

#: `dashboard.py` 的每一支 GET 端點。**九支全部**（A 2026-09-22 把範圍從兩支改成全部）。
#: ⚠️ 只打那兩支的話，另外七支的例外路徑仍然沒有人守。
#:
#: 📌 **`/api/now` 不在名單裡**：它只回 `datetime.now()`，**一行資料庫都不碰**。
#: ⚠️ 我第一版把它放進來了，而**抓到它的是我自己那道前提斷言**
#: （「它真的開了至少一個連線」）—— 沒有那道前提，這一題會**空綠**，
#: 而清單上會多一支「已驗證不洩漏」的端點，**它從來沒有被驗過任何東西**。
#: 🔑 **一個不適用的測試通過了，跟一個適用的測試通過了，在綠燈上長得一樣。**
DASHBOARD_PATHS = (
    "/api/dashboard/stats",
    "/api/dashboard/monthly",
    "/api/dashboard/expenses-monthly",
    "/api/devices",
    "/api/sales-orders",
    "/api/dashboard/funnel",
    "/api/dashboard/ops-alerts",
    "/api/materials-summary",
    "/api/dashboard/activity-feed",
)


class _TrackedConnection:
    """把一個連線包起來，記下它有沒有被關。"""

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
    """把 `routers.dashboard.get_db` 換成會記帳的版本。

    ⚠️ 包的是**那個模組持有的名字**，不是 `db.get_db`：
    `dashboard.py:11` 是 `from db import get_db` ⇒ 它拿的是一份**副本**，
    改 `db.get_db` 打不到它。
    🔑 今晚反覆遇到的那一條：**patch 目標要走模組。**
    """
    book = {"open": 0, "closed": 0}
    real = dash.get_db

    def _tracked(*a, **kw):
        return _TrackedConnection(real(*a, **kw), book)

    monkeypatch.setattr(dash, "get_db", _tracked)
    return book


def _auth(client, make_user):
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.mark.parametrize("path", DASHBOARD_PATHS)
def test_the_endpoint_closes_every_connection_it_opens(
        client, make_user, ledger, path):
    """🔴 **打一次端點，開出去的連線要全部被關回來。**

    ⚠️ 前提先驗：**它真的開了至少一個連線** ——
    否則一個「根本沒查資料庫」的端點會讓這一題空綠
    （今晚第 N 個空集合假綠燈）。
    """
    hdr = _auth(client, make_user)
    r = client.get(path, headers=hdr)
    assert r.status_code in (200, 404), f"{path} 回 {r.status_code}：{r.text[:200]}"

    assert ledger["open"] >= 1, (
        f"{path} 一個連線都沒開 —— 這一題的前提不成立（它沒有查資料庫？）"
    )
    leaked = ledger["open"] - ledger["closed"]
    assert leaked == 0, (
        f"{path} 開了 {ledger['open']} 個連線，只關了 {ledger['closed']} 個"
        f"（洩漏 {leaked} 個）。\n"
        "⇒ 首頁端點七天被打 1,044 次，全站最高。"
    )


def test_repeated_calls_do_not_accumulate_connections(client, make_user, ledger):
    """🔴 **連打十次，未關閉的連線數不成長。**

    📌 這一題與上一題不同：上一題是「一次打平」，這一題是「**不累積**」。
    ⚠️ 一個「開兩個關一個」的實作**每一次都洩漏一個**，
    而單看一次的話那個數字小到像雜訊。
    🔑 **洩漏是斜率不是截距** —— 要看它成不成長，不是看它是不是零。
    """
    hdr = _auth(client, make_user)
    for _ in range(10):
        client.get("/api/dashboard/expenses-monthly", headers=hdr)
    leaked = ledger["open"] - ledger["closed"]
    assert leaked == 0, (
        f"打了十次，累積洩漏 {leaked} 個連線"
        f"（開 {ledger['open']}、關 {ledger['closed']}）"
    )


@pytest.mark.parametrize("path", DASHBOARD_PATHS)
def test_a_failure_midway_still_closes_the_connection(
        client, make_user, ledger, monkeypatch, path):
    """🔴🔴 **中途丟例外時，連線仍然要被關。**

    ☠️ **這一題才是那另外七支的守門。**
    它們在正常路徑下是成對的 ⇒ 上面兩題抓不到它們；
    **而九支全部沒有 `finally`** ⇒ 只要中途丟例外就一樣洩漏。

    📌 那是〈判準的寬窄都會騙人〉的正面用法：
    **太窄的判準會讓那七支看起來是安全的**，
    ⇒ 所以要有一題把「例外路徑」這個維度也走過一次。

    🔑 而修法（`with` 或 `try/finally`）**自然會同時涵蓋這兩題** ——
    那正是「修作法不要修結果」：**一個地方保證關，九個地方不必各自記得。**
    """
    hdr = _auth(client, make_user)

    class _Boom(Exception):
        pass

    def _explode(self, *a, **kw):
        raise _Boom("查詢中途爆炸")

    # 連線開出去之後才爆 —— 那正是 `finally` 存在的理由
    monkeypatch.setattr(_TrackedConnection, "execute", _explode, raising=False)
    try:
        client.get(path, headers=hdr)
    except Exception:            # noqa: BLE001  端點可能把它往外丟
        pass

    if ledger["open"] == 0:
        pytest.skip(f"{path} 在爆炸前沒有開連線 —— 這一題對它不適用")
    leaked = ledger["open"] - ledger["closed"]
    assert leaked == 0, (
        f"{path} 在查詢中途丟例外之後，洩漏了 {leaked} 個連線"
        f"（開 {ledger['open']}、關 {ledger['closed']}）。\n"
        "⇒ 那一支沒有 `finally`（或 `with`）。正常路徑下它看起來是成對的，"
        "**所以只驗正常路徑的題目會說它是安全的。**"
    )
