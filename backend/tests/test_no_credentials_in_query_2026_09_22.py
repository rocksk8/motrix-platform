"""§8 FX21–FX23 · 憑證不可以走 query string。

---

# ☠️ 為什麼：**query string 會被記錄，而記錄的人不是我們**

今天 §3n 已經演過一次：uvicorn 的 access log 把整個 URL
（含 query string）追加進 `logs\\server.log`。
🔑 **而那次漏掉的原因是「我們列的是我們會寫入的地方」** ——
📌 這一節是同一條線的下一步：**把會被記錄的東西從那個位置移開**。

而憑證比座標更糟：
```
座標    洩漏的是「那個人當時在哪」
token   洩漏的是「那個人是誰」—— 而它在有效期內可以被直接使用
```

---

# 🔴 三處（A 掃出來的，我複核過行號）

```
routers/auth.py:550     GET /api/auth/login/qr-info     challenge: str          ← 純 str
routers/auth.py:636     GET /api/auth/login/qr-status   challenge: str          ← 每 2 秒輪詢
routers/uploads.py:81   GET /api/uploads/{file_path}    token: str = Query(None) ← **完整 session token**
```

## 🔑 FX23b 是這一族的關鍵，而它是「判準太窄」的標準案例

```python
login_qr_status(challenge: str)               # ← 純 str，**沒有預設值**
serve_upload(..., token: str = Query(None))   # ← 有 Query(...)
```
☠️ **兩種寫法都是 query string，而第一種看起來最無害。**
⚠️ **一個只找 `Query(` 的守門會漏掉 `qr-status`** ——
🔑 **而那正是這一節的起點**（D 只看到一處，A 掃出三處）。

---

# ⚠️ `?pt=` 那一條路要**保留**，而且要有題釘住它還在

`pt` 是 **HMAC、1 小時、綁定單一路徑** ——
🔑 **它是解同一個問題的正確做法**（`<img src>` 設不了 header）。
☠️ **B 拿掉 `?token=` 的時候順手把 `?pt=` 一起拿掉的話，
8 處附件預覽會同時壞掉** —— 而那個壞法是「圖片破圖」，
**沒有人會把它跟這一次的安全修正連起來。**
"""
import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROUTERS = Path(__file__).resolve().parent.parent / "routers"

#: 參數名裡出現這些字樣 ⇒ 它是憑證類的東西。
#: ⚠️ 刻意用**子字串**比對而不是完全相等：`access_token`／`api_key`／
#: `otp_code` 都要被抓到。🔑 這一側寧可寬 —— 誤報的代價是加一列豁免，
#: 而漏報的代價是一個 token 進了永久 log。
CREDENTIAL_WORDS = ("challenge", "token", "secret", "code", "key",
                    "password", "otp", "nonce", "sig")

#: 🔴 **短名字用完全相等比對。**
#:
#: ⚠️ 我第一版只有子字串清單 ⇒ **`pt` 完全沒有被抓到**
#: （它是 HMAC 簽章，而 `pt` 不含上面任何一個字樣）
#: ⇒ 我替它寫的那一列豁免變成**幽靈**，而 `FX23c` 立刻抓到了。
#:
#: 🔑 而那個結果是錯的方向：**一個真的憑證沒有被守門看見，
#: 而我卻以為我審查過它了** —— 那比漏掉一個沒審查過的更糟，
#: 因為**豁免清單讓它看起來像被審查過**。
#: ⇒ 短名字用相等比對（`pt` 當子字串會命中 `script`／`option`／`captcha`）。
CREDENTIAL_EXACT = ("pt", "sig", "hmac", "nonce", "jwt", "auth")

#: 這些預設值表示「**不是** query 參數」。
SAFE_DEFAULTS = ("Header", "Depends", "Body", "Cookie", "Form", "File")

#: 🔴 明文豁免：目前已知而**刻意保留**的。
#: ⚠️ 每一列都要寫出「為什麼它是對的」，不是「為什麼還沒改」。
ALLOWED = {
    ("/api/uploads/{file_path:path}", "pt"):
        "HMAC、1 小時、綁定單一路徑。`<img src>` 設不了 header ⇒ "
        "這是解同一個問題的**正確**做法，不是欠帳。",
}


def _routes():
    """所有 GET／DELETE 路由：`(檔名, 路徑, 函式)`。

    📌 用 `ast` 不用 grep —— 🔑 註解與 docstring 不在 AST 裡，
    而今天 A 因為 grep 吃到註解誤報過三次、我因為它誤報過一次（U5c）。
    """
    out = []
    for path in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in node.decorator_list:
                if not (isinstance(deco, ast.Call)
                        and isinstance(deco.func, ast.Attribute)
                        and deco.func.attr in ("get", "delete")):
                    continue
                if not (deco.args and isinstance(deco.args[0], ast.Constant)
                        and isinstance(deco.args[0].value, str)):
                    continue
                out.append((path.name, deco.args[0].value, node))
    return out


def _query_credentials():
    """回傳 `(檔, 路徑, 參數名, 寫法)` —— 走 query string 的憑證類參數。"""
    hits = []
    for filename, route, fn in _routes():
        template = {seg[1:-1].split(":")[0]
                    for seg in route.split("/")
                    if seg.startswith("{") and seg.endswith("}")}
        args = fn.args
        positional = list(args.posonlyargs) + list(args.args)
        defaults = ([None] * (len(positional) - len(args.defaults))
                    + list(args.defaults))
        pairs = list(zip(positional, defaults))
        pairs += list(zip(args.kwonlyargs, args.kw_defaults))

        for arg, default in pairs:
            name = arg.arg
            if name in ("self", "request", "response"):
                continue
            if name in template:
                continue                      # 路徑樣板裡的，不是 query
            low = name.lower()
            if not (any(w in low for w in CREDENTIAL_WORDS)
                    or low in CREDENTIAL_EXACT):
                continue
            kind = "純 str（沒有預設值）"
            if default is not None:
                if (isinstance(default, ast.Call)
                        and isinstance(default.func, ast.Name)):
                    if default.func.id in SAFE_DEFAULTS:
                        continue              # Header／Depends／Body ⇒ 安全
                    kind = f"{default.func.id}(...)"
                else:
                    kind = "有預設值"
            hits.append((filename, route, name, kind))
    return hits


# ══════════════════════════════════════════════════════════════════════
# FX23 · 守門本體
# ══════════════════════════════════════════════════════════════════════

def test_fx23a_no_get_route_takes_a_credential_in_the_query_string():
    """🔴🔴 FX23a：**GET／DELETE 路由的憑證類參數不可以走 query string。**

    ☠️ query string 會進 **uvicorn 的 access log**（`logs\\server.log`，
    永久追加）、瀏覽器歷史、Referer 標頭、反向代理的記錄。
    🔑 **而記錄的人不是我們** —— 那是 §3n 已經演過一次的那條線。

    ⚠️ 而憑證比座標更糟：座標洩漏「那個人當時在哪」，
    **token 洩漏「那個人是誰」—— 而它在有效期內可以被直接使用。**
    """
    hits = [h for h in _query_credentials() if (h[1], h[2]) not in ALLOWED]
    assert not hits, (
        "這些 GET／DELETE 路由把憑證類參數放在 query string 裡：\n  "
        + "\n  ".join(f"{f}  {r}  參數 `{n}`（{k}）" for f, r, n, k in hits)
        + "\n\n⇒ 改走 header 或 POST body。\n"
        "📌 若某一條確實必須留在 query（像 `?pt=` 那種 HMAC、限時、綁定"
        "單一路徑的簽章），把它加進 `ALLOWED` 並**寫出為什麼它是對的**，"
        "不是「為什麼還沒改」。"
    )


def test_fx23b_the_guard_sees_both_shapes(tmp_path):
    """🔴🔴 FX23b：**判準要同時涵蓋 `Query(...)` 與「純 `str` 沒有預設值」。**

    ## ☠️ 這一題是給我自己的判準做的反向控制

    ```python
    login_qr_status(challenge: str)                # ← 純 str，看起來最無害
    serve_upload(..., token: str = Query(None))    # ← 有 Query(...)
    ```
    ⚠️ **一個只找 `Query(` 的守門會漏掉第一種** ——
    🔑 **而那正是這一節的起點**（D 只看到一處，A 掃出三處）。

    📌 所以這一題餵**合成**的路由檔，確認兩種寫法都被抓到，
    而 `Header(...)` 那種**不會**被誤報。
    """
    probe = tmp_path / "probe_router.py"
    probe.write_text(
        "from fastapi import APIRouter, Query, Header\n"
        "router = APIRouter()\n"
        "@router.get('/api/probe/bare')\n"
        "def bare(challenge: str):\n"
        "    return {}\n"
        "@router.get('/api/probe/query')\n"
        "def q(token: str = Query(None)):\n"
        "    return {}\n"
        "@router.get('/api/probe/header')\n"
        "def h(authorization: str = Header(None)):\n"
        "    return {}\n"
        "@router.get('/api/probe/{token}')\n"
        "def tmpl(token: str):\n"
        "    return {}\n"
        "@router.post('/api/probe/post')\n"
        "def p(token: str = Query(None)):\n"
        "    return {}\n",
        encoding="utf-8")

    global ROUTERS
    original = ROUTERS
    try:
        ROUTERS = tmp_path
        found = {(r, n) for _f, r, n, _k in _query_credentials()}
    finally:
        ROUTERS = original

    assert ("/api/probe/bare", "challenge") in found, (
        f"**純 `str` 沒有預設值**的那種沒有被抓到：{sorted(found)}\n"
        "☠️ 那正是 `qr-status` 的寫法 —— 一個只找 `Query(` 的守門會漏掉它。"
    )
    assert ("/api/probe/query", "token") in found, (
        f"`Query(...)` 那種沒有被抓到：{sorted(found)}"
    )
    assert ("/api/probe/header", "authorization") not in found, (
        "`Header(...)` 被誤報了 —— 那是**正確**的做法，"
        "誤報它會逼人把對的寫法改掉。"
    )
    assert ("/api/probe/{token}", "token") not in found, (
        "路徑樣板裡的參數被誤報了 —— 它不是 query string。"
    )
    assert ("/api/probe/post", "token") not in found, (
        "POST 路由被誤報了 —— body 不會進 access log。"
    )


def test_fx23c_the_allow_list_points_at_something_real():
    """🔴 FX23c：`ALLOWED` 裡的每一列都要**指得到現存的路由與參數**。

    ⚠️ 一列指不到東西的豁免，讀起來像一個決定 ——
    📌 我今天已經刪過三列那種（`SL15`／`LK1`／`SL21`）。
    🔑 而在這裡它更貴：**它會讓人以為「那個 query 參數是被審查過的」**，
    而實際上那個參數早就被改名或刪掉了。
    """
    actual = {(r, n) for _f, r, n, _k in _query_credentials()}
    ghosts = sorted(k for k in ALLOWED if k not in actual)
    assert not ghosts, (
        f"`ALLOWED` 裡的這幾列指不到現存的參數：{ghosts}\n"
        "⇒ 那個參數被改名或刪掉了 ⇒ 把那一列也刪掉。"
    )


# ══════════════════════════════════════════════════════════════════════
# FX21 · uploads 的 ?token=
# ══════════════════════════════════════════════════════════════════════

def _login(client, make_user, **kw):
    kw.setdefault("role", "superadmin")
    username, password = make_user(**kw)
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_fx21a_the_upload_route_no_longer_declares_a_token_parameter():
    """🔴 FX21a：`serve_upload()` 不可以再有 `token: str = Query(None)`。

    ☠️ 那是**完整的 session token** —— 它進 access log 之後，
    🔑 **任何讀得到那個檔的人都可以直接用它登入**（在有效期內）。
    📌 而 `logs\\server.log` 是永久追加的，而且**不在每日備份的排除清單裡
    的理由是它根本不在備份裡** —— 也就是說沒有人在管它的生命週期。
    """
    hits = [h for h in _query_credentials()
            if "uploads" in h[1] and h[2] == "token"]
    assert not hits, (
        f"`/api/uploads/{{file_path}}` 還有 `token` query 參數：{hits}\n"
        "☠️ 那是完整的 session token，而它會進 access log。"
    )


def test_fx21b_a_valid_token_in_the_query_string_is_refused(
        client, make_user, tmp_path, monkeypatch):
    """🔴🔴 FX21b 反向控制：**帶 `?token=<有效的 session token>` 必須被拒絕。**

    ## 🔑 拿掉參數宣告 ≠ 那條路被擋住

    ⚠️ FastAPI 會忽略沒有宣告的 query 參數 ⇒ 帶了它**不會報錯**
    ⇒ **如果中介層仍然接受它，那條路還在，只是看不見了。**
    📌 〈守門守的對象被搬走〉的鏡像：**宣告拿掉了，而行為可能沒變。**

    ⇒ 判準：帶一個**真的有效**的 token 走 query string ⇒ **401／403**。
    ☠️ 帶一個無效的 token 測是沒有意義的（那本來就會被擋）——
    🔑 **要用有效的，才分得出「它被忽略了」與「它被接受了」。**
    """
    token = _login(client, make_user)
    r = client.get(f"/api/uploads/probe.png?token={token}")
    assert r.status_code in (401, 403), (
        f"帶著**有效**的 session token 走 query string 拿到 {r.status_code}"
        f"：{r.text[:200]}\n"
        "☠️ 那條路還在 —— 拿掉參數宣告不等於拿掉那條路。"
    )


def test_fx21c_the_signed_preview_path_is_still_there():
    """🔴 FX21c：**`?pt=` 那條路要保留。**

    ⚠️ 它是 **HMAC、1 小時、綁定單一路徑** ——
    🔑 **它是解同一個問題的正確做法**（`<img src>` 設不了 header）。

    ☠️ B 拿掉 `?token=` 的時候**順手把 `?pt=` 一起拿掉**的話，
    **8 處附件預覽會同時壞掉** —— 而那個壞法是「**圖片破圖**」，
    📌 **沒有人會把它跟這一次的安全修正連起來。**

    🔑 這一題是〈已知的代價 vs 要修的東西〉的反面：
    **一個看起來像同一類問題的東西，其實是那個問題的正確解。**
    """
    src = (ROUTERS / "uploads.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {a.arg
             for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             for a in list(node.args.args) + list(node.args.kwonlyargs)}
    assert "pt" in names, (
        "`routers/uploads.py` 裡再也沒有 `pt` 參數 ——\n"
        "☠️ 8 處附件預覽會同時壞掉，而症狀是「圖片破圖」，"
        "沒有人會把它跟這一次的安全修正連起來。"
    )


# ══════════════════════════════════════════════════════════════════════
# FX22 · QR 登入的 challenge
# ══════════════════════════════════════════════════════════════════════

QR_ROUTES = ("/api/auth/login/qr-info", "/api/auth/login/qr-status")


def _assert_no_query_credential(route):
    hits = [h for h in _query_credentials() if h[1] == route]
    assert not hits, (
        f"`{route}` 的憑證參數還在 query string 裡：{hits}。"
        "⇒ 改走 header 或 POST body（比照座標改走 `X-Map-Position`）。"
    )


def test_fx22a_qr_info_does_not_take_the_challenge_in_the_query_string():
    """🔴 FX22a：`qr-info` 的 `challenge` 改走 header 或 POST body。"""
    _assert_no_query_credential("/api/auth/login/qr-info")


def test_fx22b_qr_status_is_changed_together_with_qr_info():
    """🔴 FX22b：**兩支要一起改 —— 只改一支等於沒改。**

    🔑 `qr-status` 是**每 2 秒輪詢**的
    ⇒ ☠️ 它在 access log 裡留下的不是一筆，**是一整串**。
    📌 而兩支用的是**同一個** challenge ⇒ 改一支，另一支照樣把它洩出去。
    """
    _assert_no_query_credential("/api/auth/login/qr-status")


def test_fx22c_a_challenge_in_the_query_string_is_refused(client):
    """🔴🔴 FX22c 反向控制：**challenge 走 query string ⇒ 422**（比照 §3n 的 G10）。

    ## 🔑 拿掉參數宣告 ≠ 那條路被擋住

    ⚠️ FastAPI **會忽略沒有宣告的 query 參數** ⇒ 帶了它不會報錯
    ⇒ ☠️ **如果舊的前端還在送，它會靜靜地送、而伺服器靜靜地忽略**，
    而那個 challenge **仍然進了 access log**。
    📌 〈守門守的對象被搬走〉：**宣告拿掉了，而那條路可能還通。**

    ⇒ 判準：帶 `?challenge=...` ⇒ **422，而且訊息要指路**。
    🔑 不指路的話，下一個人會以為只是格式寫錯 —— **而那是 G10 教的**。

    ⚠️ 這兩支在 `_PUBLIC_API_PATHS` 裡（未登入流程）⇒ 不需要登入就能打，
    **而 `challenge` 就是那個流程裡唯一的憑證。**
    """
    for route in QR_ROUTES:
        r = client.get(f"{route}?challenge=probe-should-be-refused")
        assert r.status_code == 422, (
            f"{route} 帶 query string 的 challenge 回 {r.status_code}"
            f"（預期 422）：{r.text[:200]}。"
            "⇒ 舊的前端會靜靜地繼續送，而那個 challenge 仍然進 access log。"
        )
        body = r.text
        assert "header" in body.lower() or "body" in body.lower(), (
            f"422 的訊息沒有指路（該走 header 還是 body？）：{body[:200]}"
        )
