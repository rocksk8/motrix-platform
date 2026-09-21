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
"""
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

#: **被排除的端點，以及排除的理由。** 三支都是「真的不碰資料庫」。
#:
#: ⚠️ 這張表存在的理由不是「記錄我排除了什麼」，而是讓
#: **`DASHBOARD_PATHS ∪ EXEMPT` 必須等於 `dashboard.py` 的全部 `@router.get`**
#: ⇒ 下一支端點加進來時，**有人得做一個決定**，否則測試紅。
#: 📌 〈守門要驗「有沒有人做過決定」〉—— 不是驗決定得對不對。
EXEMPT = {
    "/api/now": "只回 datetime.now()，一行資料庫都不碰",
    "/api/company/tax/{tax_id}": "GCIS 政府開放資料純查詢，不碰資料庫",
    "/api/company/search": "GCIS 政府開放資料純查詢，不碰資料庫",
}


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
    """把 **`db.get_db`** 換成會記帳的版本 —— 連線**真正被開出來**的那一層。

    ## 🔴 我第一版包錯了層，而重構把它證明出來

    第一版包的是 `routers.dashboard.get_db`（`dashboard.py:11` 的那份副本），
    理由是「**patch 目標要走模組**」—— 那個理由**當時是對的**。
    ⚠️ 而 B 把九支轉成 `with db_conn() as conn:` 之後，
    **`dashboard.py` 裡再也沒有任何一處裸的 `get_db()`**
    ⇒ 我包的那個名字**再也不會被呼叫**，九題全部紅在「一個連線都沒開」。

    🔑 **「走模組」保證你打得到，但不保證你打在連線真的被開出來的那一層。**
    ⇒ 改包 `db.get_db`：重構之後它是**唯一**的來源。
    📌 而 `routers.dashboard.db_conn` 只是一個引用 ——
    **下一支端點用別的方式拿連線時，`db.get_db` 仍然看得到，它看不到。**
    （B 的判斷，我同意：**包在最上游，重構才搬不走它。**）
    """
    import db as db_module

    book = {"open": 0, "closed": 0}
    real = db_module.get_db

    def _tracked(*a, **kw):
        return _TrackedConnection(real(*a, **kw), book)

    monkeypatch.setattr(db_module, "get_db", _tracked)
    return book


def _auth(client, make_user, ledger):
    """登入拿 token，**然後把帳本歸零**。

    ## ☠️ 這個歸零是整組題目的成敗所在

    觀測點從 `routers.dashboard.get_db` 上移到 `db.get_db` 之後，
    帳本看得到的不只是被測端點 —— **`make_user` 與 `/api/auth/login`
    自己就會開連線**（`routers.auth` 也是從 `db` 拿的）。

    ⇒ 後果有兩層，第二層才貴：
    ① 排除清單那一題會紅在 `/api/now`（**它根本沒開連線，開的是登入**）；
    ② ⚠️ **而九支端點那一題的前提斷言 `open >= 1` 會變成空的** ——
       登入自己就滿足了它，**那道前提再也擋不住一個不查資料庫的端點**。
       🔴 而那道前提，正是我寫來擋 `/api/now` 的。

    🔑 〈判準的寬窄都會騙人〉的**寬**那一側：
    **B 說「包在最上游，重構才搬不走它」是對的，而上游看得到的東西比你要測的多。**
    📌 一個觀測點的位置同時決定了**打不打得到**與**混不混得進來**，
    兩者往相反方向移動 —— 所以搬了位置就得回頭重驗每一道前提。
    """
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    ledger["open"] = 0
    ledger["closed"] = 0
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.mark.parametrize("path", DASHBOARD_PATHS)
def test_the_endpoint_closes_every_connection_it_opens(
        client, make_user, ledger, path):
    """🔴 **打一次端點，開出去的連線要全部被關回來。**

    ⚠️ 前提先驗：**它真的開了至少一個連線** ——
    否則一個「根本沒查資料庫」的端點會讓這一題空綠
    （今晚第 N 個空集合假綠燈）。

    📌 **而這道前提自己也需要被證明還活著。** 證據不在這一題裡，
    在 `test_an_exempt_endpoint_really_does_not_touch_the_database[/api/now]`：
    它綠 ⇒ `/api/now` 在歸零之後開 **0** 個連線
    ⇒ `/api/now` 若被放進 `DASHBOARD_PATHS`，這道前提就會紅。
    ⚠️ 兩題是一對，**刪掉那一題，這一道前提會安靜地變回空的。**
    """
    hdr = _auth(client, make_user, ledger)
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
    hdr = _auth(client, make_user, ledger)
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
    hdr = _auth(client, make_user, ledger)

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


# ══════════════════════════════════════════════════════════════════════
# 清單本身的守門 —— **下一支端點加進來時，有人得做一個決定**
# ══════════════════════════════════════════════════════════════════════

def test_every_endpoint_is_either_covered_or_explicitly_exempt():
    """🟢 **`dashboard.py` 的每一支 GET 端點都要有歸屬。**

    ⚠️ 上面那三組題目的覆蓋率，取決於 `DASHBOARD_PATHS` 這張**手寫**清單 ——
    而手寫清單的失敗方式是**安靜的**：新增一支端點不會讓任何題目變紅，
    它只是**不在清單上**。🔑 〈量測比變化慢＝輸出一印出來就過期〉。

    📌 所以讀的是 **`dash.router.routes`（真的被註冊的路由）**，不是原始碼文字 ——
    〈診斷的層級決定覆蓋率〉：**文字比對答的是「有沒有被提到」，不是「有沒有被掛上去」。**
    """
    registered = {
        r.path for r in dash.router.routes
        if "GET" in getattr(r, "methods", set())
    }
    assert registered, "前提不成立：`dash.router` 一支 GET 路由都沒有"

    accounted = set(DASHBOARD_PATHS) | set(EXEMPT)
    unaccounted = registered - accounted
    assert not unaccounted, (
        "這幾支端點既不在 `DASHBOARD_PATHS`，也不在 `EXEMPT`：\n  "
        + "\n  ".join(sorted(unaccounted))
        + "\n⇒ 請做一個決定：它查資料庫就加進 `DASHBOARD_PATHS`，"
        "不查就加進 `EXEMPT` 並寫下理由。"
    )

    stale = accounted - registered
    assert not stale, (
        "清單上有這幾支，但它們已經不是註冊中的路由了（改名或刪掉了？）：\n  "
        + "\n  ".join(sorted(stale))
    )


@pytest.mark.parametrize("path", sorted(EXEMPT))
def test_an_exempt_endpoint_really_does_not_touch_the_database(
        client, make_user, ledger, monkeypatch, path):
    """🟢 **反向控制：`EXEMPT` 裡的每一支，真的一個連線都不開。**

    ☠️ 沒有這一題，上面那張表就是一個**可以自己開給自己的赦免** ——
    把一支會洩漏的端點寫進 `EXEMPT`，整組測試照樣全綠。
    📌 〈守門要驗「有沒有人做過決定」〉那條的配套：
    **⚙️ 要配反向控制，否則可以靠「全部寫進排除清單」變綠。**

    ⚠️ 兩支 GCIS 端點會對外連線 ⇒ 這裡把 **`_gcis_get` 這個產品自己的接縫**換掉，
    而不是放行 NETGUARD。**放行的話這一題會變成一個對外連線的測試。**
    """
    monkeypatch.setattr(dash, "_gcis_get", lambda *a, **kw: ([], None),
                        raising=False)
    hdr = _auth(client, make_user, ledger)

    url = path.replace("{tax_id}", "12345678")
    if url.endswith("/api/company/search"):
        url += "?q=motrix"

    r = client.get(url, headers=hdr)
    assert r.status_code in (200, 404), f"{url} 回 {r.status_code}：{r.text[:200]}"

    assert ledger["open"] == 0, (
        f"{path} 被列在 `EXEMPT`（理由：{EXEMPT[path]}），"
        f"但它開了 {ledger['open']} 個連線。\n"
        "⇒ 那個排除理由已經不成立了，把它移回 `DASHBOARD_PATHS`。"
    )
