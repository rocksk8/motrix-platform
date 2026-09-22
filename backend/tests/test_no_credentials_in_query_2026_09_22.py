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
import re
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
# FX23d · 倒過來問：**哪些參數的值，拿到就能做到一件原本需要授權的事？**
# ══════════════════════════════════════════════════════════════════════
#
# ☠️ A 的條文：**關鍵字清單不是一個完整的類別。**
# `challenge|token|secret|code|key|password|otp|nonce|sig` 是**我們想到的字**，
# 而 `pt` 就是那個「判準抓得到、字樣清單抓不到」的例子。
#
# 🔑 **這一版的判準不看名字，看流向**：
# 一個 query 參數，如果它的值**被交給一個在做「准不准」判斷的函式**，
# 那它就是憑證 —— 不管它叫什麼。
#
# 📌 D 今天的方法論直接套在這裡：
# **一個掃描工具要先能讓「已知的那一個」亮起來，才有資格報「沒有其他的」。**
# ⇒ `test_fx23d_c_` 用合成路由證明它**亮得起來也不會亂亮**。
#
# ⚠️⚠️ **而它仍然看不見的（寫下來，不要留在這次對話裡）**：
# ```
# 1  間接一層     param → helper(param) → helper 內部才 verify
# 2  跨檔         param 被存進物件／dict，別處才拿出來驗
# 3  否定形       「沒有這個參數就拒絕」（授權靠的是它的存在而不是它的值）
# ```
# 🔑 ⇒ 這道守門**縮小了盲區，沒有消滅它**。三者之中 1 最可能真的發生。

AUTHORITY_CALLS = re.compile(
    r"(^|_)(verify|validate|authenticate|authorize|require|check)"
    r"|compare_digest|decode_token",
    re.I,
)

#: 「你是誰」與「你准不准」。**400 不算** —— 那是「你給的格式不對」。
AUTHORITY_STATUS = (401, 403)


def _query_params():
    """每條 GET／DELETE 路由的 query 參數：`(檔, 路徑, 函式, 參數名)`。

    📌 與 `_query_credentials()` 共用同一套「什麼算 query 參數」的判斷，
    ⚠️ 但**刻意不套字樣清單** —— 那正是 FX23d 要繞開的那一層。
    """
    for filename, route, fn in _routes():
        template = {seg[1:-1].split(":")[0]
                    for seg in route.split("/")
                    if seg.startswith("{") and seg.endswith("}")}
        args = fn.args
        positional = list(args.posonlyargs) + list(args.args)
        defaults = ([None] * (len(positional) - len(args.defaults))
                    + list(args.defaults))
        pairs = list(zip(positional, defaults)) + list(
            zip(args.kwonlyargs, args.kw_defaults))
        for arg, default in pairs:
            if arg.arg in ("self", "request", "response") or arg.arg in template:
                continue
            if (isinstance(default, ast.Call)
                    and isinstance(default.func, ast.Name)
                    and default.func.id in SAFE_DEFAULTS):
                continue
            yield filename, route, fn, arg.arg


def _call_name(node):
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _mentions(node, name):
    """`name` 這個變數有沒有出現在這個運算式裡（含 f-string）。"""
    return any(isinstance(n, ast.Name) and n.id == name
               for n in ast.walk(node))


def _raised_statuses(node):
    """這段程式碼裡 `raise HTTPException(...)` 丟出的狀態碼。"""
    out = set()
    for n in ast.walk(node):
        if not (isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)):
            continue
        if _call_name(n.exc) != "HTTPException":
            continue
        cand = list(n.exc.args) + [kw.value for kw in n.exc.keywords
                                   if kw.arg == "status_code"]
        for c in cand:
            if isinstance(c, ast.Constant) and isinstance(c.value, int):
                out.add(c.value)
    return out


def _locals_raising_auth(path):
    """同一個檔裡，哪些函式**自己會丟 401／403**。

    ⚠️ 只看同一個檔（一層）。跨檔的 helper 看不到 —— 見本節的盲區清單。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _raised_statuses(node) & set(AUTHORITY_STATUS):
                out.add(node.name)
    return out


def _authority_flows():
    """回傳 `(檔, 路徑, 參數名, 被交給誰, 形狀)` —— 值決定授權的 query 參數。

    ## 🔑 判準：**這個值不對的時候，回的是 401／403。**

    ```
    _verify_photo_token(safe, pt)   回 bool，403 在呼叫點      ⇒ 形狀 A
    _validate_range(start, end)     400 在函式內部（格式錯）   ⇒ 不算
    _require_user(authorization)    401 在函式內部             ⇒ 形狀 B
    ```
    ☠️ **我第一版只比對函式名，而 `_validate_range` 也含 `validate`** ——
    一次掃出 4 筆日期參數。🔑 那正是 D 今天踩的 v2（子字串比對命中 37 條），
    📌 **而我在看過它的紀錄之後，當場又踩了一次。**
    ⇒ 修的不是清單，是**判準**：從「名字像不像」改成「錯了會回什麼」。
    """
    hits = []
    local_auth = {}
    for filename, route, fn, name in _query_params():
        if filename not in local_auth:
            local_auth[filename] = _locals_raising_auth(ROUTERS / filename)
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            called = _call_name(node)
            if not AUTHORITY_CALLS.search(called):
                continue
            passed = list(node.args) + [kw.value for kw in node.keywords]
            if not any(_mentions(a, name) for a in passed):
                continue

            shape = None
            if called in local_auth[filename]:
                shape = "B：被呼叫的函式自己丟 401／403"
            else:
                for guard in ast.walk(fn):
                    if (isinstance(guard, ast.If)
                            and _mentions(guard.test, name)
                            and any(_call_name(c) == called
                                    for c in ast.walk(guard.test)
                                    if isinstance(c, ast.Call))
                            and _raised_statuses(guard) & set(AUTHORITY_STATUS)):
                        shape = "A：呼叫點的 if 擋下來丟 401／403"
                        break
            if shape:
                hits.append((filename, route, name, called, shape))
                break
    return hits


def test_fx23d_b_the_known_one_lights_up():
    """📏📏 **正對照：`pt` 必須亮。不亮的話，下面那題的綠燈不算數。**

    ☠️ 沒有這一題，`_authority_flows()` 只要壞掉（regex 打錯、AST 走法改了、
    `ROUTERS` 指錯），它就回空集合 ⇒ **主題目立刻全綠**。
    🔑 D 今天的方法論，A 要寫進 §6：
    **一個掃描工具要先能讓「已知的那一個」亮起來，才有資格報「沒有其他的」。**

    📌 而 `pt` 正是那個「字樣清單抓不到、這個判準抓得到」的例子：
    它不含 `challenge|token|secret|code|key|password|otp|nonce|sig` 任何一個字。
    """
    hits = _authority_flows()
    assert any(name == "pt" for _f, _r, name, _c, _s in hits), (
        f"已知的 `?pt=` 沒有被這道判準看見：{hits}\n"
        "⇒ 這個掃描器現在**沒有資格**說「沒有其他的」。"
    )


def test_fx23d_c_the_criterion_is_flow_not_spelling(tmp_path):
    """🔴🔴 FX23d 反向控制：**看的是流向，不是名字。**

    ```
    /api/probe/nameless   ?widget=…  → _verify_widget() → 403   ← 名字完全無害，必須亮
    /api/probe/daterange  ?start=…   → _validate_range() → 400  ← 不可以亮（格式錯不是沒授權）
    /api/probe/unused     ?spare=…   （沒有人動它）             ← 不可以亮
    ```
    ⚠️ 第二條是我自己踩出來的：第一版判準只比對函式名，
    而 `_validate_range` 含 `validate` ⇒ **一次誤報 4 筆日期參數**。
    🔑 「這個值錯了會回 400」跟「會回 403」是兩件事，
    **而一個把它們混在一起的判準，會逼人把對的寫法改掉。**
    """
    probe = tmp_path / "probe_flow.py"
    probe.write_text(
        "from fastapi import APIRouter, Query, HTTPException\n"
        "router = APIRouter()\n"
        "def _verify_widget(v):\n"
        "    return False\n"
        "def _validate_range(a, b):\n"
        "    raise HTTPException(400, 'bad')\n"
        "@router.get('/api/probe/nameless')\n"
        "def nameless(widget: str = Query(None)):\n"
        "    if not _verify_widget(widget):\n"
        "        raise HTTPException(403, 'nope')\n"
        "    return {}\n"
        "@router.get('/api/probe/daterange')\n"
        "def daterange(start: str = Query(...), end: str = Query(...)):\n"
        "    _validate_range(start, end)\n"
        "    return {}\n"
        "@router.get('/api/probe/unused')\n"
        "def unused(spare: str = Query(None)):\n"
        "    return {}\n",
        encoding="utf-8")

    global ROUTERS
    original = ROUTERS
    try:
        ROUTERS = tmp_path
        found = {(r, n) for _f, r, n, _c, _s in _authority_flows()}
    finally:
        ROUTERS = original

    assert ("/api/probe/nameless", "widget") in found, (
        f"名字無害但**值決定授權**的參數沒有被抓到：{sorted(found)}\n"
        "☠️ 那就是 `pt` 的形狀 —— 字樣清單看不見它。"
    )
    assert ("/api/probe/daterange", "start") not in found, (
        f"日期區間參數被誤報了：{sorted(found)}\n"
        "⇒ `_validate_range` 丟的是 400（格式錯），不是 403（沒授權）。"
    )
    assert ("/api/probe/unused", "spare") not in found, (
        f"沒有任何人使用的參數被誤報了：{sorted(found)}"
    )


def test_fx23d_every_authority_deciding_query_parameter_has_been_reviewed():
    """🔴 FX23d：**值決定授權的 query 參數，一個都不可以沒被審過。**

    ## ☠️ A 的條文：關鍵字清單不是一個完整的類別

    > `challenge|token|secret|code|key|password|otp|nonce|sig`
    > **是我們想到的字。** 倒過來問比較接近真正的判準：
    > **「哪些參數的值，拿到就能做到一件原本需要授權的事？」**

    ## 📌 這一題現在是**綠的，而且是該綠的**

    掃出來只有 `pt` 一筆，而它已經在 `ALLOWED` 裡（HMAC、1 小時、綁單一路徑）。
    ⚠️ **綠燈在這裡的意思是「沒有新的」**，不是「這個判準完整」——
    🔑 它的價值是**下一個被加進來的**會在這裡撞到。

    ## ⚠️ 而它看不見的，見本節開頭的盲區清單（間接一層／跨檔／否定形）

    📌 那三項**不是被忽略，是被寫下來了** ——
    A 的話：把「我們用的是一個會漏的判準」寫成一個**有人負責的狀態**，
    而不是留在某一次對話裡。
    """
    unreviewed = [(f, r, n, c, s) for f, r, n, c, s in _authority_flows()
                  if (r, n) not in ALLOWED]
    assert not unreviewed, (
        "這些 query 參數的**值決定了授權**，而沒有人審過：\n"
        + "\n".join(f"  {f}  {r}  ?{n}=  → {c}（{s}）" for f, r, n, c, s
                    in unreviewed)
        + "\n\n⇒ 要嘛改走 header／POST body，要嘛進 `ALLOWED` 並寫下理由。"
    )


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

#: 🔴 本檔專屬的假來源 IP —— **登入一律帶它。**
#:
#: ## ☠️ `routers/auth.py:42` 的 `_rl_state` 是**行程級全域，以 IP 為鍵**
#:
#: 而 `conftest.py` 把資料庫隔離得很乾淨，**卻沒有重設這個 dict** ——
#: 🔑 `TestClient` 的預設來源是 `"testclient"`，**全套測試共用同一個鍵**
#: ⇒ 任何一支測試在這個 worker 裡累積 5 次登入失敗，
#:   **之後所有人的登入都被鎖 900 秒。**
#:
#: ## 📌 失敗的樣子：`KeyError: 'token'`
#:
#: 登入回 429 而程式碼直接 `.json()["token"]` ——
#: ☠️ **單獨跑永遠是綠的，全量跑才紅，而紅的理由跟這一題要驗的事完全無關。**
#: ⚠️ 2026-09-22 實測證實：把 `_rl_fail("testclient", …)` 呼叫六次，
#: 這個檔立刻出現同樣的 `KeyError` —— **不是推論，是重現過的。**
#:
#: 🔑 這個 repo 早就有這個慣例（`test_totp_qr_push_2026_09_08.py` 用
#: `203.0.113.201`／`.202`／`.203`），而我寫這個檔時沒有跟上。
#: 📌 `203.0.113.0/24` 是 RFC 5737 保留給文件用的網段，不會撞到真實位址。
RL_IP = {"X-Forwarded-For": "203.0.113.221"}


def _login(client, make_user, **kw):
    kw.setdefault("role", "superadmin")
    username, password = make_user(**kw)
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password},
                    headers=RL_IP)
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


def _decode_qr_png(data_uri):
    """把 `data:image/png;base64,…` 解成 QR 裡真正的那串字。

    ## 🔴 2026-09-22 加固：**舊版把「解不開」回報成空字串**

    ```python
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(arr)   # 解不開 ⇒ ''
    ...
    assert "?challenge=" not in url      # ← `'' ` 當然不含它 ⇒ **綠**
    ```
    ☠️ **一個安全斷言，因為觀測失敗而通過。**
    🔑 〈降級之後它還是會動〉套在觀測工具上：
    **量不到的時候它沒有報錯，它回報了一個「看起來像通過」的結果。**
    📌 抓到它的是同一題下面那行
    `assert f"#challenge={真值}" in url` —— **那一行是這一題唯一的底。**

    ## 📌 而根因不是「偶爾閃爍」，我實測過（不是推論）

    ```
    樣本 500 組隨機 challenge，每組產一張 QR 再解：
      cv2.QRCodeDetector()          失敗 42.5%   ← 近一半
      同一張圖重複解 20 次           結果全同     ⇒ **決定性，不是隨機閃爍**
      放大 2x／3x／4x／CUBIC        失敗 42.5%   ⇒ **加大完全無效**
      detectAndDecodeMulti          失敗 95.0%   ⇒ 更糟
      加 40px 白邊                  失敗  6.7%
      cv2.QRCodeDetectorAruco()     失敗  0.0%（500/500，每次 26ms）
    ```
    ⚠️ **「放大就會比較準」是一個聽起來很合理而實際上零效果的修法** ——
    🔑 而它會讓人以為問題解決了，**直到下一次它又紅在別人的打包裡**。

    ## ⇒ 三層，而最後一層才是真正的修復

    ```
    ① Aruco 偵測器              實測 0/500 失敗
    ② 古典偵測器 ＋ 40px 白邊    退路
    ③ 全部失敗 ⇒ **丟例外**      ← 絕對不回空字串
    ```
    🔑 ③ 才是根因的修復：**即使哪天兩個偵測器同時失效，
    也不會再有一個安全斷言靠著空字串變綠。**
    """
    import base64 as _b64

    import cv2
    import numpy as np

    prefix = "data:image/png;base64,"
    assert data_uri.startswith(prefix), f"不是 PNG data URI：{data_uri[:60]}"
    raw = _b64.b64decode(data_uri[len(prefix):])
    arr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    assert arr is not None, "PNG 解不開 —— 這張圖本身就壞了"

    attempts = []

    def _try(label, image, detector):
        try:
            text = detector.detectAndDecode(image)[0]
        except cv2.error as exc:                      # noqa: BLE001
            attempts.append(f"{label}: cv2.error {exc}")
            return ""
        attempts.append(f"{label}: {'讀到 %d 字元' % len(text) if text else '空字串'}")
        return text

    padded = cv2.copyMakeBorder(arr, 40, 40, 40, 40,
                                cv2.BORDER_CONSTANT, value=255)
    for label, image, detector in (
        ("Aruco 原圖", arr, cv2.QRCodeDetectorAruco()),
        ("Aruco 白邊", padded, cv2.QRCodeDetectorAruco()),
        ("古典 白邊", padded, cv2.QRCodeDetector()),
    ):
        text = _try(label, image, detector)
        if text:
            return text

    raise AssertionError(
        "這張 QR 三種解法都讀不出來（圖 %dx%d）：\n  %s\n"
        "☠️ **不可以回空字串** —— 空字串會讓 `\"?challenge=\" not in url` 通過，"
        "而那是一個安全斷言。\n"
        "⇒ 這一題現在紅在「量不到」而不是「洩漏了」，兩者要分得出來。"
        % (arr.shape[1], arr.shape[0], "\n  ".join(attempts))
    )


def test_the_qr_decoder_would_actually_see_a_leaked_challenge():
    """📏 **量尺：先證明這把解碼器看得見洩漏，下一題的綠燈才算數。**

    ☠️ 我第一版這題寫成 `"?challenge=" not in json.dumps(回應)` ——
    **而那句話永遠是真的**：`approve_url` 是編進 **PNG 圖**裡的，
    JSON 回應只有 `challengeToken` 與 base64 圖，
    ⇒ **就算產品真的退回 `?challenge=`，那個斷言也照樣綠。**
    🔑 〈假綠燈：斷言驗到自己設的值〉的另一種：
    **斷言找的東西，從一開始就不可能出現在我看的那個位置。**

    ⇒ 這一題用**產品之外**的一張合成 QR（明著含 `?challenge=`）
    證明：解碼這條路徑**真的會把那五個字帶出來**。
    """
    import io as _io

    import qrcode

    leaked = "http://example.test/pages/x.html?challenge=deadbeef"
    buf = _io.BytesIO()
    qrcode.make(leaked).save(buf, format="PNG")
    import base64 as _b64
    uri = "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()

    assert _decode_qr_png(uri) == leaked, (
        "解碼器讀不出我自己編進去的那串字 ⇒ **下一題的綠燈不能採信**，"
        "它只證明了『解不開』。"
    )


def test_the_decoder_refuses_to_report_failure_as_an_empty_string():
    """📏📏 **量尺的量尺：解不開的時候必須炸，不可以回空字串。**

    ## ☠️ 這一題防的是那個真正的根因

    2026-09-22 打包那一輪，這個檔紅在：
    ```
    assert '#challenge=02a03bb4…' in ''
                                    ^^ 解碼回了空字串
    ```
    而**前面兩個斷言都過了**：
    ```
    body.get("qrCodePng")        ✅ 有給 QR
    "?challenge=" not in url     ✅ 因為 url 是 ''，空字串當然不含它
    ```
    🔑 **那個「沒有洩漏」的綠，是空字串給的。**
    📌 而擋下它的只有 `#challenge=<真值>` 那一行 ——
    **一個「必須有」的斷言，救了一個「必須沒有」的斷言。**

    ## ⇒ 所以現在 `_decode_qr_png` 解不開就丟例外

    ⚠️ 即使哪天兩個偵測器同時失效，也不會再有安全斷言靠空字串變綠：
    **它會紅在「量不到」，而那與「洩漏了」分得出來。**
    🔑 〈降級之後它還是會動〉：**量不到的時候要拒絕那一筆，不要送空值。**
    """
    import base64 as _b64
    import io as _io

    import numpy as np
    from PIL import Image

    # 一張純雜訊圖 —— 它不是 QR，所以兩個偵測器都會回空字串。
    noise = (np.random.RandomState(0).rand(300, 300) * 255).astype("uint8")
    buf = _io.BytesIO()
    Image.fromarray(noise).save(buf, format="PNG")
    uri = "data:image/png;base64," + _b64.b64encode(buf.getvalue()).decode()

    with pytest.raises(AssertionError, match="三種解法都讀不出來"):
        _decode_qr_png(uri)


def test_the_qr_image_does_not_carry_the_challenge_in_the_query_string(
        client, make_user):
    """🔴 **QR 圖裡的網址不可以用 `?challenge=`。**

    ## ⏳ 編號：A 指定了 `FX22d`，**而規格裡沒有那一行**

    我實查 `docs/windows/STATE.md`：`FX22d` 一次都沒出現 ——
    它只存在於一則訊息裡。
    🔑 而 A 同一天才剛裁定：**規格是編號的權威**，
    並自己認了「寫在規格散文裡→守門看不見」那一條。
    ⇒ 📌 **我不自己登記**（自己發一個編號會讓守門變綠，
    而綠燈的意思會變成「我承認了我自己」）。
    ⚠️ 所以題名先維持**守門看不見**的描述式；
    A 把 `FX22d` 寫進規格之後，改名成 `test_fx22d_...` 即可。

    ## ☠️ B 發現的第三個洩漏點，而它是**另一個形狀**

    QR 原本編的是 `/pages/login-qr-approve.html?challenge=xxx`
    ⇒ 手機一掃就是 `GET /pages/…?challenge=xxx` ⇒ **照樣被 access log 記一筆**。
    🔑 **只改兩支 API 的話，我們會宣稱洩漏堵住了，而它沒有。**

    ## ⚠️ 而我的 `FX23a` **掃不到這一個**

    那道守門掃的是**路由參數**（函式簽名）。
    ☠️ 而這裡的憑證**從來不是任何函式的參數** ——
    它是被 `f"...{challenge_token}"` **組進一個字串**的。
    🔑 〈判準的寬窄都會騙人〉的新一面：
    **我的判準對「憑證會出現在哪裡」有一個隱含假設，而那個假設沒被寫下來。**

    ## 📌 兩邊都要驗，少一邊就是一個可以靠「拿掉」通過的守門

    ```
    不可以有  ?challenge=        ← 洩漏的那個形狀
    必須有    #challenge=<真值>  ← 否則「整個不帶 challenge」也會綠，而 QR 就廢了
    ```
    `#` 後面的東西瀏覽器**不會送給伺服器** ⇒ 不可能進任何伺服器端紀錄。
    ⚠️ 它仍然留在**那支手機的瀏覽器歷史**裡 —— 可接受（一次性、數分鐘、
    而那支手機就是要核准的本人）。
    """
    # ⚠️ 兩次登入都要帶 `RL_IP` —— 見那個常數的說明（行程級的 per-IP 鎖定）。
    username, password = make_user(role="superadmin")
    r = client.post("/api/auth/login",
                    json={"username": username, "password": password},
                    headers=RL_IP)
    assert r.status_code == 200, (
        f"第一次登入就失敗了（{r.status_code}）：{r.text[:200]}\n"
        "⇒ 429 的話是 per-IP 鎖定被別的測試累積到了，見 `RL_IP`。"
    )
    token = r.json()["token"]
    r = client.post("/api/auth/totp/setup", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    import pyotp
    r = client.post("/api/auth/totp/enable",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text

    r = client.post("/api/auth/login",
                    json={"username": username, "password": password},
                    headers=RL_IP)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("qrCodePng"), f"這次登入沒有給 QR ⇒ 這一題的前提不成立：{body}"

    url = _decode_qr_png(body["qrCodePng"])
    assert "?challenge=" not in url, (
        f"QR 裡的網址還帶著 `?challenge=`：{url}。"
        "☠️ 手機一掃就是一筆帶著憑證的 GET，而它進 access log。"
    )
    assert f"#challenge={body['challengeToken']}" in url, (
        f"QR 裡沒有帶上這次的 challenge（fragment 形式）：{url}。"
        "⇒ 若是被整個拿掉，上面那個斷言會綠，而 QR 核准登入直接廢掉。"
    )


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
