"""§4 YD／YE · GCIS 代理要登入＋上限；四支高風險路由補測試。

---

# ⚠️ YE2 的警告值得逐字留著，因為它是 A 自己的判準

> **「不要用『路徑字串有沒有出現在測試檔裡』當完成判準 ——
> 🔑 那正是我用來找出這四支的判準，而它是『太寬』的那一側。」**

⇒ 這個檔裡每一題都**真的打那一支路由**，不是 grep 檔案。
📌 而那讓一件事變得可能：**我發現了一支 A 的清單沒說的守衛位置**（見 YE1）。

---

# 🔴 而 YE 那四支，我查過之後有一個細節會改變寫法

FastAPI **先驗 body 才進函式** ⇒ **要測 403，body 必須是合法的**，
否則拿到的是 **422**，而 422 與 403 在「不是 200」這個判準下長得一樣。

☠️ 那正是「太寬的判準」最常見的樣子：
`assert r.status_code != 200` 會被 422 滿足，
**而它證明的是「我的測試資料寫壞了」，不是「權限有被檢查」。**
⇒ 每一題都斷言**確切的狀態碼**。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: GCIS 的兩支代理（`routers/dashboard.py`）。
GCIS_PATHS = ("/api/company/tax/12345678", "/api/company/search?q=motrix")

#: YE 的四支高風險路由：`(method, path, body)`。
#: ⚠️ `body` 都是**合法**的 —— 見檔頭：body 不合法會拿到 422 不是 403。
HIGH_RISK = (
    ("POST", "/api/quotations/YE-0001/payment/0/approve-writeoff",
     {"approve": True, "reject_reason": ""}),
    ("POST", "/api/auth/verify-unlock",
     {"password": "wrong-on-purpose", "ref": ""}),
    ("POST", "/api/auth/verify-daily-task-unlock",
     {"password": "wrong-on-purpose"}),
    ("PUT", "/api/settings/custom-roles/ye-role", {"name": "YE 測試角色"}),
    ("DELETE", "/api/settings/custom-roles/ye-role", None),
)


def _login(client, make_user, **kw):
    kw.setdefault("role", "superadmin")
    username, password = make_user(**kw)
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _call(client, method, path, body, headers=None):
    fn = {"POST": client.post, "PUT": client.put,
          "DELETE": client.delete}[method]
    kw = {"headers": headers} if headers else {}
    if body is not None:
        kw["json"] = body
    return fn(path, **kw)


# ══════════════════════════════════════════════════════════════════════
# YD1 / YD3 · GCIS 代理要通過登入檢查
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("path", GCIS_PATHS)
def test_yd1_the_gcis_proxy_refuses_an_unauthenticated_caller(client, path):
    """🔴 YD1：GCIS 兩支代理**未登入 ⇒ 401**。

    📌 而這一條的答案可能是「**已經是了，但不是因為那兩支自己**」：
    `main.py:326` 的 middleware 對所有 `/api/` 路徑要求 session，
    而那兩支**不在** `_PUBLIC_API_PATHS` 裡（我查過）。

    ⚠️ **那不代表這一題多餘** —— 它釘的是**結果**，
    而結果由哪一層保證由實作決定。
    🔑 但它確實只有一層在守（見 YD1b）。
    """
    r = client.get(path)
    assert r.status_code == 401, (
        f"{path} 未登入時回 {r.status_code}（預期 401）：{r.text[:200]}\n"
        "☠️ 那兩支是對外的政府開放資料代理 —— 未登入可用的話，"
        "任何人都能透過我們的伺服器去查統一編號，而額度算在我們頭上。"
    )


@pytest.mark.parametrize("path", GCIS_PATHS)
def test_yd1b_the_route_itself_also_checks_not_just_the_middleware(
        client, path, monkeypatch):
    """🔴🔴 YD1b：**把那條路徑加進 `_PUBLIC_API_PATHS` 之後，它自己也要擋。**

    ## ☠️ 這一題是「只有一層防線」的守門

    現況：`routers/dashboard.py` 的 `lookup_by_tax()` 與 `search_by_name()`
    **連 `authorization` 參數都沒有** ⇒ 它們自己不檢查任何東西，
    完全靠 `main.py` 的 middleware。

    🔑 而 A 今天才為 `_smtp_send_blocked()` 記過同一件事：
    **「一道只有一層、而且第二層明著不覆蓋的防線。」**
    ⇒ 這一題模擬「有人把它加進豁免清單」（那是一個**兩行**的改動，
    而豁免清單裡已經有 13 條，**再多一條不會有人注意**）。

    📌 判準刻意是「**不是 200**」的**反面**：我要的是它**確切**回 401／403。
    ⚠️ 而若這一題紅，處置**不是**把它加進豁免清單的排除名單 ——
    是讓那兩支路由自己拿 `authorization` 並呼叫 `_require_user()`。
    """
    import main
    import routers.dashboard as dash

    # ⚠️ **先換掉產品自己的接縫，再繞過 middleware。**
    # 繞過之後那一支會真的跑起來、真的去打 GCIS ——
    # NETGUARD 抓到了（「這一題對外發出了 2 次真實連線嘗試」），
    # 🔑 而那正是這一題想證明的事情的一部分：**沒有那一層擋，它會直接出門。**
    # 📌 順序與 YA 那個 SMTP 的檔同一條：**先斷掉出口，再開閘。**
    monkeypatch.setattr(dash, "_gcis_get", lambda *a, **kw: ([], None),
                        raising=False)

    bare = path.split("?")[0]
    if "{" not in bare:
        # 路徑參數會讓豁免清單比對失敗，所以用實際路徑
        monkeypatch.setattr(
            main, "_PUBLIC_API_PATHS",
            set(main._PUBLIC_API_PATHS) | {bare})

    r = client.get(path)
    assert r.status_code in (401, 403), (
        f"把 `{bare}` 加進 `_PUBLIC_API_PATHS` 之後，它回了 "
        f"{r.status_code} —— 那兩支自己一行檢查都沒有。\n"
        "🔑 一道只有一層的防線，而第二層（middleware）是一個"
        "**13 條的豁免清單**，再多一條不會有人注意。"
    )


def test_yd3_a_logged_in_caller_gets_through(client, make_user, monkeypatch):
    """🔴 YD3 反向控制：**帶合法 token ⇒ 正常回應**（不是 401）。

    ☠️ 少了這一題，一個「**一律 401**」的實作會讓 YD1 綠 ——
    而那會讓統一編號查詢整個功能消失，
    🔑 而症狀是「打統編沒反應」，使用者會以為是政府網站掛了。

    📌 換掉 `_gcis_get`（產品自己的接縫）**不放行 NETGUARD** ——
    放行的話這一題會變成一次真的對外連線。
    """
    import routers.dashboard as dash

    monkeypatch.setattr(dash, "_gcis_get", lambda *a, **kw: ([], None),
                        raising=False)
    hdr = _login(client, make_user)
    for path in GCIS_PATHS:
        r = client.get(path, headers=hdr)
        assert r.status_code != 401, (
            f"{path} 帶了合法 token 仍然回 401：{r.text[:200]}"
        )
        assert r.status_code in (200, 404), (
            f"{path} 回 {r.status_code}：{r.text[:200]}"
        )


# ══════════════════════════════════════════════════════════════════════
# YD2 · 每日上限，而且要能從設定讀
# ══════════════════════════════════════════════════════════════════════

def test_yd2_the_daily_limit_comes_from_settings(client, make_user, monkeypatch):
    """🔴 YD2：GCIS 代理要有**每日上限**，而**上限要能從設定讀**。

    ## 📌 「能從設定讀」怎麼驗：**改設定要改到行為**

    ⚠️ 我**不**斷言某個常數名存在 —— 那只證明「有一個名字」。
    🔑 判準是：**把上限設成 1，第二次呼叫就要被擋** ⇒
    那證明那個值**真的被讀了**，而不是被寫死在程式裡。
    📌 〈守門守的對象被搬走〉：釘字面值的題，在引入一層間接之後照樣全綠。

    ☠️ 而為什麼需要上限：那是**對外的政府 API**，
    額度算在我們的 IP 上，而這一支是**登入後任何人都能打的**
    ⇒ 一個寫壞的前端迴圈就能把當天的額度用完，
    **而畫面上只會是「查不到這個統編」。**
    """
    import routers.dashboard as dash
    from helpers.settings import _set_setting

    calls = []
    monkeypatch.setattr(
        dash, "_gcis_get",
        lambda *a, **kw: (calls.append(a[0] if a else None), ([], None))[1],
        raising=False)

    _set_setting("gcis_daily_limit", 1)
    hdr = _login(client, make_user)

    first = client.get(GCIS_PATHS[0], headers=hdr)
    assert first.status_code in (200, 404), first.text[:200]
    assert calls, "第一次呼叫沒有到達 `_gcis_get` —— 這一題的前提不成立"

    second = client.get("/api/company/tax/87654321", headers=hdr)
    assert second.status_code == 429, (
        f"上限設成 1，第二次呼叫回 {second.status_code}（預期 429）："
        f"{second.text[:200]}\n"
        "⇒ 要嘛沒有上限，要嘛那個上限沒有從設定讀。"
    )


# ══════════════════════════════════════════════════════════════════════
# YE1 · 四支高風險路由：擋得住＋走得通
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", HIGH_RISK,
                         ids=[f"{m} {p.split('/api/')[1][:34]}"
                              for m, p, _ in HIGH_RISK])
def test_ye1_an_unauthenticated_caller_is_refused(client, method, path, body):
    """🔴 YE1a：四支高風險路由**未登入 ⇒ 401**。

    📌 斷言**確切**的 401，不是「不是 200」——
    ☠️ 後者會被 **422**（body 寫壞）滿足，
    而那證明的是「我的測試資料錯了」不是「權限有被檢查」。
    """
    r = _call(client, method, path, body)
    assert r.status_code == 401, (
        f"{method} {path} 未登入時回 {r.status_code}（預期 401）："
        f"{r.text[:200]}"
    )


@pytest.mark.parametrize("method,path,body", HIGH_RISK,
                         ids=[f"{m} {p.split('/api/')[1][:34]}"
                              for m, p, _ in HIGH_RISK])
def test_ye1b_a_logged_in_non_superadmin_is_refused(
        client, make_user, method, path, body):
    """🔴🔴 YE1b：**登入了但不是 superadmin ⇒ 403**。

    ## ☠️ 這一題才是 YE 的本體

    未登入被擋是 middleware 的功勞（`main.py:326` 對所有 `/api/` 都擋）
    ⇒ **YE1a 對這四支來說幾乎是免費的**。
    🔑 真正要驗的是**這四支自己的那一行** ——
    我查過，四支都有 `require_superadmin=True` 或函式內的 role 檢查：

    ```
    approve-writeoff              quotations.py:3351  if user["role"] != "superadmin": 403
    verify-unlock                 auth.py:1521        _require_user(..., require_superadmin=True)
    verify-daily-task-unlock      auth.py:1571        同上
    custom-roles PUT / DELETE     system.py:1377/1400 同上
    ```

    📌 **而那個位置本身是一個發現**：`approve-writeoff` 的檢查**不在
    `_require_user()` 的參數裡，而在函式體內** ——
    ⚠️ 任何「掃 `require_superadmin=True`」的稽核工具**會漏掉它**，
    🔑 而那正是 YE2 說的「太寬的判準」的鏡像：**這次是太窄。**
    """
    hdr = _login(client, make_user, role="sales", modules=["dev_crm"])
    r = _call(client, method, path, body, headers=hdr)
    assert r.status_code == 403, (
        f"{method} {path} 由一般使用者呼叫回 {r.status_code}（預期 403）："
        f"{r.text[:200]}\n"
        "☠️ 這四支分別是：財務沖銷核准／解鎖驗證／解鎖驗證／角色權限 CRUD。"
    )


@pytest.mark.parametrize("method,path,body", HIGH_RISK,
                         ids=[f"{m} {p.split('/api/')[1][:34]}"
                              for m, p, _ in HIGH_RISK])
def test_ye1c_a_superadmin_gets_past_the_permission_check(
        client, make_user, method, path, body):
    """🔴 YE1c 反向控制：**superadmin 要過得了權限那一關。**

    ☠️ 少了這一題，一個「**一律 403**」的實作會讓 YE1a／YE1b 全綠 ——
    而那會讓沖銷永遠核准不了、鎖永遠解不開、角色永遠改不了，
    🔑 **而畫面上只會是「你沒有權限」—— 給一個真的有權限的人看。**

    📌 判準是「**不是 401 也不是 403**」——
    ⚠️ 刻意**不**要求 200：那四支之後的失敗（找不到那筆款項、密碼錯、
    角色不存在）是**正當的業務錯誤**（409／400／404），
    而要求 200 就會逼我去造四套完整的前置資料，
    🔑 **那會讓這一題變成在測別的東西。**
    """
    hdr = _login(client, make_user, role="superadmin")
    r = _call(client, method, path, body, headers=hdr)
    assert r.status_code not in (401, 403), (
        f"{method} {path} 由 superadmin 呼叫回 {r.status_code}："
        f"{r.text[:200]}\n"
        "⇒ 權限那一關把真的有權限的人也擋掉了。"
    )
