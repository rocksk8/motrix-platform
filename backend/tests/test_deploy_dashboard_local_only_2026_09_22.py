"""§8 HC1 · 部署儀表板只接受本機請求。

---

# ☠️ 原本的防線在 `if __name__ == "__main__":` 裡面

```python
if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
```
⇒ `uvicorn deploy_dashboard:app --host 0.0.0.0` **根本不會執行那一行**。
🔑 **而這個專案的 ERP 本體就是這樣起的** ——
`autostart.bat:31`／`restart.bat:40`／`start.bat:27` 全是 `--host 0.0.0.0`。
📌 同一台機器上的人用同一個習慣去起 dashboard，
**`POST /api/deploy` 與 `POST /api/rollback` 就是無驗證的。**

## 🔑 判準：防線要在**請求**這一層，不在**啟動**那一層

啟動參數是「這一次怎麼起它」，請求檢查是「不管怎麼起，誰打得到」。
⇒ 前者是一個**習慣**，後者是一個**性質**。
📌 〈守門守的對象被搬走〉的鏡像：這次不是守門被搬走，
**是守門從來沒有裝在被保護的東西上。**

---

# 🔴🔴 HC1b 的禁令：**不可以真的把它開起來測**

> ☠️ 用 `--host 0.0.0.0` 起它來測，**會在測試期間真的在這台機器上
> 開一個無驗證的部署控制端點。**

⇒ 全檔一律 `TestClient` ＋ 偽造 `request.client.host`，**零監聽**。
📌 這跟 §4 `_smtp_send_blocked` 的順序是同一族
（「為了測試而暫時降低防護」），**而在這裡的代價高得多**。

---

# ⚠️⚠️ 這支檔案自己的危險：**紅的時候會真的部署**

```
POST /api/build     → threading.Thread(_run_job, build_deploy_package.ps1)
POST /api/deploy    → apply_update.ps1          ☠️ 沒有任何視窗可以跑這支
GET  /api/prod-status → requests.get(https://172.16.10.177:666, verify=False)
                        ☠️ NETGUARD 擋 urllib 與 smtplib，**擋不到 requests**
```
🔑 **守門缺席的時候，請求會真的打到 handler** ——
⇒ **一個為了證明「沒有守門」而真的部署一次的測試。**

## 📌 所以順序是硬的，而且有一題在驗這個順序

```
① 載入模組
② 拆掉 subprocess／threading.Thread／requests／_run_job
③ test_the_fuses_are_pulled_first 確認②真的生效
④ 才輪到行為題
```
⚠️ 少了③，②寫錯（打錯屬性名、模組物件拿錯）會**安靜地沒有生效**，
而行為題照樣綠 —— 直到某一天它真的跑了一次 `apply_update.ps1`。

---

# ⑤ 反向驗證的結果（2026-09-22 實跑，不是推論）

B 在我寫題之前就把 HC1 做完了（`9fad854`）⇒ **這些題全部是到貨即綠。**
⇒ 用六個突變（寫到 `%TEMP%` 的副本，**沒有動 B 的檔案**）確認它們紅得起來：

```
M1  middleware 沒有被註冊        → every_route / testclient_default / unknown_path  紅
M2  白名單加進 "testclient"      → testclient_default                               紅
M3  _is_local 一律 True          → 五題全紅
M4  WebSocket 的檢查被拿掉       → websocket_closed                                 紅
M5  拿不到來源時 fail open       → unknown_origin                                   紅
M6  _is_local 一律 False         → local_allowed / ipv6_loopback                    紅
```
🔑 **每一題都至少被一個突變紅過**，而 M6 在的理由是：
☠️ 沒有正對照的話，「一律回 403」會讓前五題全綠，**而那個實作把工具整個關掉了。**

⚠️ 兩題不在表上，**而那是對的**：
`the_fuses_are_pulled_first`（量尺，驗的是測試自己）與
`the_seam_points_at_the_real_file`（突變期間本來就 skip）。

📌 重跑：`%TEMP%/claude/hc1_mutate.py`（腳本留著，B 每次動這支就能再跑一次）。

---

# 📌 這個檔的存在方式本身就是 HC1a 的證明

`TestClient(app)` 走的是**匯入模組**這條路，
**而 `if __name__ == "__main__":` 在這條路上永遠不會執行。**
⇒ 這裡量到的 403，**就是 `--host 0.0.0.0` 那條路上會量到的 403**。
🔑 不是「模擬了那個情境」，是**走在同一條路上**。
"""
import importlib.util
import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

REAL_DASHBOARD = (Path(__file__).resolve().parent.parent
                  / "tools" / "deploy_dashboard.py")

#: ⑤ 反向驗證用的接縫：指向一份**突變過的副本**，確認這些題真的紅得起來。
#:
#: 🔴 為什麼需要它：B 在我寫題之前就把 HC1 做完了（`9fad854`），
#: ⇒ **這八題全部是到貨即綠，一題都沒有經過紅。**
#: ☠️ 而「沒紅過的綠」證明不了它有拒絕能力 —— 〈證據的適用範圍〉。
#:
#: ⚠️ 這個接縫自己是個風險（可以把題目指到一個安全的假檔案讓它永遠綠），
#: ⇒ 所以 `test_the_seam_points_at_the_real_file` 釘住：
#:    **不給環境變數的時候，它就是真的那個檔。**
DASHBOARD = Path(os.environ.get("MOTRIX_HC1_DASHBOARD", REAL_DASHBOARD))

#: 非本機來源。`TestClient` 預設的 `"testclient"` 另外單獨測（見反向控制那題）。
REMOTE = ("203.0.113.7", 44321)
LOCAL = ("127.0.0.1", 44321)


class _Detonator:
    """被呼叫就炸 —— 拆引信要拆成「會響」，不是拆成「安靜」。

    ☠️ 換成 `lambda *a, **k: None` 的話，守門缺席時**什麼都不會發生**，
    測試安靜地通過，而我們永遠不知道那個請求真的打到了 handler。
    🔑 〈假綠燈〉：**一個什麼都不做的替身，跟一個沒被呼叫的替身長得一樣。**
    """

    def __init__(self, what):
        self.what = what
        self.calls = []

    def __call__(self, *a, **kw):
        self.calls.append((a, kw))
        raise AssertionError(
            f"☠️☠️ 測試期間真的呼叫了 `{self.what}` —— "
            "代表請求打到了 handler，而守門沒有擋下來。\n"
            f"參數：{a!r} {kw!r}"
        )

    def __getattr__(self, name):
        return _Detonator(f"{self.what}.{name}")


@pytest.fixture
def dash(monkeypatch):
    """載入部署儀表板，**並且在任何請求之前拆掉所有會真的動手的路徑**。"""
    spec = importlib.util.spec_from_file_location(
        "motrix_deploy_dashboard_under_test", DASHBOARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod, "subprocess", _Detonator("subprocess"))
    monkeypatch.setattr(mod, "requests", _Detonator("requests"))
    monkeypatch.setattr(mod, "_run_job", _Detonator("_run_job"))
    monkeypatch.setattr(mod.threading, "Thread",
                        _Detonator("threading.Thread"), raising=False)
    return mod


def _http_routes(mod):
    """`app` 上所有 HTTP 路由的 `(方法, 可以直接打的路徑)`。

    📌 動態列舉，不手寫清單 —— 🔑 **明天新增的那一支自動被涵蓋**，
    而手寫清單的漏法是「沒有人想到要把它加進來」。
    """
    out = []
    for route in mod.app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path:
            continue
        concrete = path
        for token in ("{job_id}", "{id}"):
            concrete = concrete.replace(token, "probe")
        for m in sorted(methods):
            if m in ("HEAD", "OPTIONS"):
                continue
            out.append((m, concrete))
    return out


# ══════════════════════════════════════════════════════════════════════
# ③ 先驗拆引信本身
# ══════════════════════════════════════════════════════════════════════

def test_the_fuses_are_pulled_first(dash):
    """📏 **量尺：②真的生效了，下面每一題的綠燈才算數。**

    ⚠️ `monkeypatch.setattr(mod, "subprocess", ...)` 打錯名字、
    或 `_run_job` 在別的模組裡被持有著，都會讓拆引信**安靜地沒有生效**。
    """
    for name in ("subprocess", "requests", "_run_job"):
        assert isinstance(getattr(dash, name), _Detonator), (
            f"`{name}` 沒有被拆掉 —— 這個檔案現在有能力真的部署一次。"
        )
    assert isinstance(dash.threading.Thread, _Detonator), (
        "`threading.Thread` 沒有被拆掉 —— `POST /api/build` 會真的起執行緒。"
    )
    with pytest.raises(AssertionError, match="真的呼叫了"):
        dash._run_job("x", "deploy", [])


def test_the_seam_points_at_the_real_file():
    """📏 **量尺：沒有人把這些題指到一份假的儀表板上。**

    ☠️ `MOTRIX_HC1_DASHBOARD` 是我為了⑤反向驗證開的接縫，
    而**一個可以換掉被測對象的接縫，就是一個可以讓題目永遠綠的開關**。
    🔑 〈守門守的對象被搬走〉：斷言沒變、字面值沒變，**而被測的已經不是它了。**
    ⇒ 平常跑（沒有環境變數）時，它必須就是 `tools/deploy_dashboard.py`。
    """
    if os.environ.get("MOTRIX_HC1_DASHBOARD"):
        pytest.skip("⑤ 反向驗證進行中 —— 正對著突變副本跑，這一題不適用")
    assert DASHBOARD == REAL_DASHBOARD, (
        f"這些題現在打的是 {DASHBOARD}，不是 {REAL_DASHBOARD}"
    )
    assert DASHBOARD.is_file(), f"找不到 {DASHBOARD}"


# ══════════════════════════════════════════════════════════════════════
# HC1a / HC1b · 每一支都要被拒
# ══════════════════════════════════════════════════════════════════════

def test_hc1b_every_route_refuses_a_non_local_client(dash):
    """🔴🔴 HC1b：**非本機來源 ⇒ 每一支路由都要被拒，一支都不能漏。**

    📌 判準是「**每一支**」不是「危險的那幾支」——
    🔑 `GET /api/dev-status` 洩漏的是分支名與 commit，
    `GET /api/history` 洩漏的是部署紀錄，
    **而「只擋會動手的那幾支」是一個看起來很合理的錯誤判準。**

    ⚠️ 這一題會真的送出 `POST /api/deploy` ——
    ☠️ **守門缺席時它會真的跑 `apply_update.ps1`**，
    ⇒ 所以 `dash` fixture 先把 `subprocess`／`threading.Thread`／`_run_job`
       換成會炸的替身（見本檔 ③）。
    """
    routes = _http_routes(dash)
    assert len(routes) >= 13, (
        f"只列舉到 {len(routes)} 支路由 —— 規格說有 13 支。\n"
        "☠️ 一個列舉不到東西的檢查，會給你它能給的最好結果。"
    )

    leaked = []
    with TestClient(dash.app, client=REMOTE) as client:
        for method, path in routes:
            r = client.request(method, path, json={})
            if r.status_code != 403:
                leaked.append((method, path, r.status_code))

    assert not leaked, (
        "這些路由沒有擋下非本機的請求：\n"
        + "\n".join(f"  {m} {p} → {c}" for m, p, c in leaked)
        + f"\n\n來源 IP：{REMOTE[0]}"
    )


def test_hc1b_the_testclient_default_origin_is_not_whitelisted(dash):
    """🔴🔴 反向控制：**`TestClient` 的預設來源也要被拒。**

    ☠️ 這一題防的是一個非常具體的未來：
    有人為了讓測試好寫，把 `"testclient"` 加進 `LOCAL_CLIENT_HOSTS`。
    🔑 那之後上面那題會**永遠綠**，而那道門對真實世界形同虛設 ——
    📌 〈守門要驗「有沒有人做過決定」〉的反面：
    **一個為了讓測試變綠而放寬的白名單，會讓測試不再驗任何東西。**
    """
    with TestClient(dash.app) as client:          # 預設 ("testclient", 50000)
        r = client.get("/api/pre-deploy-check")
    assert r.status_code == 403, (
        f"`TestClient` 的預設來源 `testclient` 被放行了（{r.status_code}）。\n"
        "⇒ 上面那題從此永遠綠。"
    )


def test_hc1a_a_local_client_is_still_allowed(dash):
    """🔴 HC1a 正對照：**本機仍然打得通。**

    ☠️ 少了這一題，「**一律回 403**」會讓上面兩題全綠，
    而那個實作把這個工具整個關掉了。
    🔑 〈判準的寬窄都會騙人〉：**拒絕全部是「拒絕該拒絕的」的超集。**

    📌 這裡只打 `/api/pre-deploy-check` —— 它只讀鎖與歷史檔，
    ⚠️ **不可以拿 `/api/prod-status` 當正對照**：那支會真的連正式機。
    """
    with TestClient(dash.app, client=LOCAL) as client:
        r = client.get("/api/pre-deploy-check")
    assert r.status_code == 200, (
        f"本機請求被擋掉了（{r.status_code}）—— 這個工具現在沒有人用得了。\n"
        f"回應：{r.text[:200]}"
    )


def test_hc1a_ipv6_loopback_is_allowed(dash):
    """🔴 HC1a：`::1` 也是本機。

    📌 瀏覽器打 `http://localhost:8765` 在這台機器上解析到的是 **`::1`**，
    ⚠️ 只放行 `127.0.0.1` 的話，**使用者自己會被擋在外面**，
    而症狀是「儀表板壞了」，不是「防護生效了」。
    """
    with TestClient(dash.app, client=("::1", 44321)) as client:
        r = client.get("/api/pre-deploy-check")
    assert r.status_code == 200, (
        f"IPv6 loopback 被擋掉了（{r.status_code}）—— `http://localhost:8765` 會壞。"
    )


def test_hc1a_an_unknown_origin_is_refused(dash):
    """🔴 HC1a：**拿不到來源 ⇒ 當成不是本機**（fail closed）。

    🔑 「我不知道它從哪來」不可以被當成「它從本機來」——
    📌 跟今天在 `SEND_UNKNOWN` 上裁過的是同一件事：
    **一個沒有確認的結果不可以被當成通過。**

    ⚠️ 這一題打的是 `_is_local()` 本身而不是走 HTTP ——
    因為 `TestClient` 給不出「scope 裡沒有 client」那個情境。
    ☠️ 所以它比上面幾題弱一級：**它驗的是那支函式，不是那條路徑。**
    """
    is_local = dash._is_local
    assert is_local(None) is False, "`client` 是 None 時必須拒絕"

    class _NoHost:
        pass

    assert is_local(_NoHost()) is False, "拿不到 `.host` 時必須拒絕"

    class _Empty:
        host = ""

    assert is_local(_Empty()) is False, "`host` 是空字串時必須拒絕（空字串不是本機）"


def test_hc1a_the_websocket_is_closed_for_a_non_local_client(dash):
    """🔴🔴 HC1a：**WebSocket 也要擋。**

    ☠️ `@app.middleware("http")` **只吃 http scope** ——
    ⇒ `/ws/prod-status` 不經過它。
    🔑 「HTTP 那一面關起來了而這一面還開著」——
    📌 **而那件事在畫面上完全看不出差別**，
    〈防護的副作用落在盲側〉：擋住的那一半會被注意到，漏掉的那一半不會。

    ⚠️ 這一支會推送正式機狀態（`requests.get` 到 172.16.10.177）
    ⇒ 守門缺席時，`dash` fixture 的引信會炸掉，而**不是靜靜地連出去**。
    """
    from starlette.websockets import WebSocketDisconnect

    with TestClient(dash.app, client=REMOTE) as client:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/ws/prod-status") as ws:
                ws.receive_json()
    assert excinfo.value.code == 1008, (
        f"WebSocket 被關掉了，但代碼是 {excinfo.value.code} 不是 1008（policy violation）。"
    )


# ══════════════════════════════════════════════════════════════════════
# HC1c · 這 13 支路由不可以搬到別人身上
# ══════════════════════════════════════════════════════════════════════

def test_hc1c_the_dashboard_cannot_be_mounted_into_the_erp(dash):
    """🔴🔴 HC1c：**它必須是自己的 `FastAPI()`，而且沒有人掛得上去。**

    ## ☠️ 為什麼這是一個不變量，不是一次性的查證

    A 原本寫「已經驗過，不用再做」—— 🔑 **那是錯的歸類。**
    有人哪天把 `app = FastAPI()` 改成 `router = APIRouter()`
    並 `include_router` 進 `main.py`：
    ```
    ⇒ 這 13 支部署路由會出現在 666 上
    ⇒ 而 HC1a 的 `@app.middleware("http")` **不會跟著過去**
    ```
    📌 〈守門守的對象被搬走〉最直白的一種：
    **防線綁在那支 app 上，而路由可以搬家。**

    ⚠️ 用 AST 不用 grep：上面三處 `deploy_dashboard` 的提及**全部在註解裡**
    （`main.py:93`／`routers/auth.py:320`／`check_endpoint_entrypoints.py:49`），
    ☠️ grep 會把它們全報成引用，而**註解不會讓路由搬家**。
    """
    import ast

    from fastapi import APIRouter, FastAPI

    assert isinstance(dash.app, FastAPI), (
        f"`app` 現在是 {type(dash.app).__name__} —— "
        "它必須是自己的 `FastAPI()`，才掛不進 ERP 本體。"
    )
    assert not isinstance(dash.app, APIRouter), "`app` 不可以是 `APIRouter`"

    backend = Path(__file__).resolve().parent.parent
    importers = []
    for path in backend.rglob("*.py"):
        parts = set(path.parts)
        if parts & {"rollback_snapshots", "deploy_packages", "__pycache__"}:
            continue
        if path.name.startswith("test_deploy_dashboard"):
            continue          # 本檔用 importlib 讀路徑，不是 import 陳述句
        if path.name == "deploy_dashboard.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            else:
                continue
            if any("deploy_dashboard" in n for n in names):
                importers.append(f"{path.relative_to(backend)}:{node.lineno}")

    assert not importers, (
        "有人開始 import 部署儀表板了：\n  " + "\n  ".join(importers)
        + "\n⇒ 那 13 支路由隨時可能被掛進一個沒有這道 middleware 的 app。"
    )


def test_hc1a_an_unknown_path_is_refused_before_it_is_matched(dash):
    """🔴 HC1a：**沒有這支路由，也要先回 403，不是 404。**

    🔑 判準：守門在**路由比對之前**。
    📌 這一題的價值是**它不依賴任何一支現存的路由** ——
    ⚠️ 換句話說，**明天新增的那一支不可能繞過它**，
    而「新增路由時忘了掛上檢查」正是這一族最常見的復發方式。
    """
    with TestClient(dash.app, client=REMOTE) as client:
        r = client.get("/api/this-route-does-not-exist")
    assert r.status_code == 403, (
        f"未知路徑回了 {r.status_code} 而不是 403 ——\n"
        "⇒ 守門掛在路由比對**之後**，新增的路由要各自記得掛上它。"
    )
