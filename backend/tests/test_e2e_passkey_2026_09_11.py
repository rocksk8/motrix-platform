"""瀏覽器端對端：Passkey 註冊與登入的完整流程（用 CDP 虛擬認證器）。

**為什麼非要這支測試不可**

2026-09-10～11 這條路一連撞了四個 bug，每一個都只有在真人用真的瀏覽器按下去
才會現形，而且錯誤訊息一個比一個難懂：

  1. `Incorrect padding`             後端用標準 base64 解 base64url
  2. `Credential had unexpected type` credential 少了 `type` 欄位
  3. `not of type '(ArrayBuffer...)'` 前端漏轉 `excludeCredentials[].id`
  4. `Cannot read properties of undefined` 登入時讀了只存在於註冊的 `opts.user`

每一輪都是「修好一個 → 使用者再試 → 冒出下一個」。純後端測試攔不下 3、4，
而 1、2 雖然後端測得到，我第一次寫的斷言（只驗「錯誤不是 padding」）又太寬鬆，
放過了 2。

Chrome DevTools Protocol 的 WebAuthn 虛擬認證器可以把整條路自動走完——不需要
真的 Windows Hello，也不需要有人按確認。

**兩個設計上非做不可的取捨（第一版都做錯了，記在這裡免得再犯）**

① **測 `excludeCredentials` 不能靠「第二張要註冊成功」。**
   它在帳號還沒有任何 Passkey 時是空陣列，所以第一張永遠踩不到；要踩到就得
   有第二次註冊。但第二次註冊在同一個認證器上**本來就應該失敗**——那正是
   `excludeCredentials` 存在的目的。第一版為了讓它「成功」而外掛了第二台虛擬
   認證器，結果 Chrome 沒有把請求路由過去，變成不明原因的靜默逾時。
   真正要驗的其實是「options 有沒有被瀏覽器**解析成功**」：漏轉 base64 的話，
   `navigator.credentials.create()` 連叫都叫不起來就丟 TypeError。所以這裡改成
   **期待第二次註冊以「已註冊過」的語意失敗**，並斷言它不是型別錯誤。

② **Passkey 登入必須在同一個 browser context 裡做。**
   虛擬認證器的憑證存在該 context 的認證器裡，換 context 等於換一台全新的空白
   認證器，`navigator.credentials.get()` 一定找不到憑證。第一版另開 context
   「模擬重新開瀏覽器」，那在真實世界成立（憑證在 Windows Hello 裡），在虛擬
   認證器下必然失敗。改成清掉 localStorage 的 session 來模擬登出。
"""
import json
import random
import socket
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn

# ── 2026-09-16：Passkey 功能暫緩使用（使用者裁示）───────────────────────────
# 整檔 skip，**不是刪掉、也不是 xfail**：程式碼與資料表都原樣留著，開關一開
# 這些測試就要立刻跟著回來把關。xfail 會讓功能恢復後的真實失敗被當成預期失敗
# 而靜靜吞掉，刪掉則是恢復時沒有任何東西守著。
#
# 開關在 backend/helpers/auth.py::PASSKEY_ENABLED。
# ⚠️ 「停用本身有沒有生效」由 tests/test_passkey_disabled_2026_09_16.py 驗，
# 那一檔**不會**被這個開關 skip——否則整組 Passkey 測試全 skip 時，端點是真的
# 回 404 還是路由根本壞了，沒有任何一題分得出來。
from helpers.auth import PASSKEY_ENABLED
from tests._ports import free_safe_port

pytestmark = pytest.mark.skipif(
    not PASSKEY_ENABLED,
    reason="Passkey 功能暫緩（backend/helpers/auth.py::PASSKEY_ENABLED=False）")



# 🔴 2026-09-21：這裡原本有一支自己的挑埠函式（寫於 2026-09-11，起因是抽到
# 1723/PPTP）。它是對的，但**只住在這一個檔裡** —— 十天後同一個 bug 在
# `test_e2e_material_orders` 又咬了一次（2049/NFS），而第 5 輪的⑥才抓到。
#
# 🔑 **修好一個實例，不等於認得那個模式。**
# 已抽成 `tests/_ports.py::free_safe_port()`（21 個 e2e 檔共用），
# 完整診斷與守門見那一支與 `test_ports_helper_2026_09_21.py`。


@pytest.fixture()
def live_server(client):
    """WebAuthn 規格只允許 localhost 走 http，其餘一律要 https。測試伺服器是
    純 http，所以 RP ID 用 localhost、瀏覽器也從 localhost 進——這條路徑
    `_validate_webauthn_pair()` 本來就明文放行（見該函式最後一段）。"""
    import main
    config = uvicorn.Config(main.app, host="127.0.0.1", port=free_safe_port(),
                            log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("uvicorn 測試伺服器在時限內沒有啟動")
    port = server.servers[0].sockets[0].getsockname()[1]

    import db
    conn = db.get_db()
    try:
        for k, v in (("webauthn_rp_id", "localhost"),
                     ("webauthn_origin", f"http://localhost:{port}")):
            conn.execute(
                "INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (k, json.dumps(v), "2026-09-11T00:00:00"))
        conn.commit()
    finally:
        conn.close()

    try:
        yield f"http://localhost:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _add_virtual_authenticator(context, page):
    """掛一個永遠會同意的平台認證器，取代真實的 Windows Hello。"""
    cdp = context.new_cdp_session(page)
    cdp.send("WebAuthn.enable")
    cdp.send("WebAuthn.addVirtualAuthenticator", {
        "options": {
            "protocol": "ctap2",
            "transport": "internal",
            "hasResidentKey": True,
            "hasUserVerification": True,
            "isUserVerified": True,
            "automaticPresenceSimulation": True,
        }
    })
    return cdp


def _collect_console(page):
    """把 console、未捕捉例外、以及 WebAuthn 設定端點的回應收進一個 list。

    login.html 的 `checkWebauthnConfig()` 整段包在 `try { } catch {}` 裡，
    fetch 掛掉不會留下任何痕跡——畫面上只會看到按鈕沒出現。這裡從瀏覽器側
    把那個缺口補起來，失敗時才有東西可看。
    """
    sink = []
    page.on("console", lambda m: sink.append(f"[console.{m.type}] {m.text}"))
    page.on("pageerror", lambda e: sink.append(f"[pageerror] {e}"))

    def _on_response(resp):
        if "webauthn-config-status" in resp.url:
            try:
                body = resp.text()
            except Exception as exc:
                body = f"(讀不到 body: {exc})"
            sink.append(f"[net] {resp.status} {resp.url} -> {body}")

    page.on("response", _on_response)
    return sink


def _wait_alpine(page):
    """等 Alpine 把這一頁的元件掛好再往下做。

    2026-09-11：少了這一步會出現兩種都很難查的症狀——
      * `page.click()` 打在還沒綁上 @click 的按鈕上，什麼事都沒發生；
      * `page.fill()` 之後 Alpine 才初始化，把欄位值又蓋回去。
    `page.goto()` 只等到 `load`，而 Alpine 是在那之後才跑的。
    """
    page.wait_for_function(
        "() => { const el = document.querySelector('[x-data]');"
        " return !!(window.Alpine && el && Alpine.$data(el)); }", timeout=15000)


def _alpine(page, expr):
    """在 body 的 Alpine 元件範圍內求值（這幾個頁面都只有一個 x-data 根）。"""
    return page.evaluate(
        "(src) => { const el = document.querySelector('[x-data]');"
        " const d = el && window.Alpine && Alpine.$data(el);"
        " if (!d) return '(讀不到 Alpine 狀態)';"
        " return (new Function('d', 'return (' + src + ')'))(d); }", expr)


def _passkey_count(username=None):
    import db
    conn = db.get_db()
    try:
        if username:
            return conn.execute(
                "SELECT COUNT(*) c FROM webauthn_credentials w JOIN users u ON u.id=w.user_id "
                "WHERE u.username=?", (username,)).fetchone()["c"]
        return conn.execute("SELECT COUNT(*) c FROM webauthn_credentials").fetchone()["c"]
    finally:
        conn.close()


def _cred_row(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute(
            "SELECT w.sign_count, w.last_used_at FROM webauthn_credentials w "
            "JOIN users u ON u.id=w.user_id WHERE u.username=?", (username,)).fetchone()
    finally:
        conn.close()


def _login_with_password(page, base_url, username, password):
    page.goto(f"{base_url}/pages/login.html")
    page.fill('input[x-model="username"]', username)
    page.fill('input[x-model="password"]', password)
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)


def _click_register(page):
    """按下「新增 Passkey」並等它跑完，回傳當下的狀態。

    刻意把「逾時」也當成一種結果回傳而不是就地吞掉：第一版在這裡 `except: pass`，
    於是註冊卡住不動時 `err` 是空的、斷言照樣通過，最後只在「資料庫沒有第二筆」
    這個離事發點很遠的地方炸掉。

    完成訊號看的是 `passkeys.ok` 或 `passkeys.err` 出現，**不是**等 `busy` 變回
    false。等 `busy` 有個致命的漏洞：點擊如果根本沒生效（Alpine 還沒綁好事件），
    `busy` 從頭到尾都是 false，`wait_for_function` 立刻就滿足，於是「什麼都沒發生」
    被判定成「順利完成」。2026-09-11 為此白追了兩輪。
    """
    _wait_alpine(page)
    # 清掉上一輪的結果，否則舊的 ok 會讓這一輪瞬間「完成」
    page.evaluate(
        "() => { const el = document.querySelector('[x-data]');"
        " const d = el && window.Alpine && Alpine.$data(el);"
        " if (d) { d.passkeys.ok = ''; d.passkeys.err = ''; } }")
    page.click('button:has-text("新增 Passkey")')
    timed_out = False
    try:
        page.wait_for_function(
            "() => { const el = document.querySelector('[x-data]');"
            " const d = el && window.Alpine && Alpine.$data(el);"
            " return d && !d.passkeys.busy && (d.passkeys.ok || d.passkeys.err); }",
            timeout=20000)
    except Exception:
        timed_out = True
    state = _alpine(
        page, "{err: d.passkeys.err || '', ok: d.passkeys.ok || '', busy: !!d.passkeys.busy}")
    if isinstance(state, dict):
        state["timedOut"] = timed_out
    return state


def _assert_not_a_marshalling_bug(state, seq):
    """這個字串是「前端漏轉某個 base64 欄位」的招牌症狀，單獨點出來，
    免得下次又要從一句 TypeError 反推是哪個欄位沒轉。"""
    err = state.get("err", "") if isinstance(state, dict) else str(state)
    assert "ArrayBuffer" not in err, (
        f"第 {seq} 次註冊：options 裡有 base64 欄位沒轉成 ArrayBuffer"
        f"（challenge / user.id / excludeCredentials[].id 逐一檢查）：{err}")


def _register_one(page, seq):
    state = _click_register(page)
    _assert_not_a_marshalling_bug(state, seq)
    assert isinstance(state, dict), f"第 {seq} 次註冊：{state}"
    assert not state["err"], f"第 {seq} 次註冊 Passkey 失敗：{state}"
    assert not state["timedOut"], f"第 {seq} 次註冊沒有在時限內結束：{state}"


def _logout(page, base_url, sink=None):
    """清掉 session 回到未登入狀態。

    不另開 browser context——虛擬認證器的憑證是綁在 context 上的，換 context
    等於換一台空白認證器，Passkey 就找不到憑證了（見檔頭②）。

    順序很重要：**先在目前這頁清掉 session，再導去 login.html**。反過來做的話，
    login.html 一載入就會因為 session 還在而自動跳回 index.html，接著的 reload
    會撞上那個重導，得到 `net::ERR_ABORTED; maybe frame was detached?`。
    """
    page.evaluate("() => { localStorage.removeItem('motrix_session'); }")
    # 只保留這次載入之後的事件，診斷才看得出「這一頁到底有沒有去查設定」。
    # 必須在 goto **之前**清——放在之後就會把要看的那一筆一起清掉。
    if sink is not None:
        sink.clear()
    page.goto(f"{base_url}/pages/login.html")
    _wait_alpine(page)


def _wait_passkey_login_button(page, sink):
    """等「或使用 Passkey 登入」出現；沒等到就把成因一次挖出來。"""
    try:
        page.wait_for_selector('button:has-text("或使用 Passkey 登入")', timeout=20000)
        return
    except Exception as exc:
        # 先把事件快照下來——下面的 recheck／probe 自己也會打同一支端點，
        # 混在一起就分不出「頁面載入時到底有沒有查過」。
        before_probe = list(sink)
        state = page.evaluate(
            "() => { const el = document.querySelector('[x-data]');"
            " const d = el && window.Alpine && Alpine.$data(el);"
            " return { alpine: !!window.Alpine, hasData: !!d,"
            "          configured: d ? d.webauthnConfigured : '(讀不到)' }; }")
        # 直接叫元件自己再查一次：會翻成 true 就是「載入當下還沒設定好」的時序
        # 問題，維持 false 則要往端點或元件以外的方向找。
        recheck = page.evaluate(
            "async () => { const el = document.querySelector('[x-data]');"
            " const d = el && window.Alpine && Alpine.$data(el);"
            " if (!d) return '(讀不到 Alpine 狀態)';"
            " await d.checkWebauthnConfig();"
            " return d.webauthnConfigured; }")
        probe = page.evaluate(
            "async () => { try { const r = await fetch('/api/system/webauthn-config-status');"
            " return { status: r.status, body: await r.text() }; }"
            " catch (e) { return { fetchError: String(e) }; } }")
        raise AssertionError(
            f"""Passkey 登入按鈕沒有出現（x-show 綁的 webauthnConfigured 是 false）。
  Alpine 狀態    : {state}
  再呼叫一次元件 : {recheck}
  端點直接打一次 : {probe}
  頁面載入時的事件: {before_probe or "(無 —— 代表 init() 根本沒跑去查設定)"}
  原始錯誤       : {exc}"""
        ) from None


def _passkey_login(page, base_url, username, sink):
    _logout(page, base_url, sink)
    page.fill('input[x-model="username"]', username)
    _wait_passkey_login_button(page, sink)
    page.click('button:has-text("或使用 Passkey 登入")')
    try:
        page.wait_for_url(lambda u: u.endswith("/index.html"), timeout=25000)
    except Exception:
        err = _alpine(page, "d.error || '(沒有錯誤訊息)'")
        raise AssertionError(
            f"Passkey 登入沒有完成：{err}\n  瀏覽器事件：{sink or '(無)'}") from None


@pytest.mark.e2e
def test_passkey_register_duplicate_rejected_then_login(live_server, make_user):
    """註冊 → 同一個認證器重複註冊必須被擋 → 用 Passkey 登入。"""
    username, password = make_user(username="e2e_pk", role="admin")
    assert _passkey_count() == 0, "測試前提：一開始不該有任何 Passkey"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        sink = _collect_console(page)
        _add_virtual_authenticator(context, page)
        try:
            _login_with_password(page, live_server, username, password)
            page.goto(f"{live_server}/pages/change-password.html")
            page.wait_for_selector('button:has-text("新增 Passkey")', timeout=20000)

            # 第一張：踩得到 base64url padding 與 credential 缺 type 兩個坑
            _register_one(page, 1)
            assert _passkey_count(username) == 1, "第一張 Passkey 沒有寫進資料庫"

            # 第二次：excludeCredentials 這時才非空。前端漏轉 id 的話，
            # navigator.credentials.create() 會在解析 options 時就丟 TypeError，
            # 連認證器都還沒叫到；轉對了則會走到認證器、被它以「這張已經註冊過」
            # 拒絕——後者才是正確結果。
            page.reload()
            page.wait_for_selector('button:has-text("新增 Passkey")', timeout=20000)
            state = _click_register(page)
            _assert_not_a_marshalling_bug(state, 2)
            assert isinstance(state, dict), f"第 2 次註冊：{state}"
            assert state["err"], (
                "同一個認證器重複註冊竟然成功了——excludeCredentials 沒有生效，"
                f"狀態：{state}")
            assert _passkey_count(username) == 1, "被擋下的註冊不該留下資料庫紀錄"

            _passkey_login(page, live_server, username, sink)
        finally:
            context.close()
            browser.close()


@pytest.mark.e2e
def test_passkey_login_updates_sign_count(live_server, make_user):
    """登入成功要更新 sign_count／last_used_at——那是重放攻擊偵測的依據，
    只要它沒被寫回去，防護就等於不存在，而且不會有任何錯誤跡象。"""
    username, password = make_user(username="e2e_pk2", role="admin")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()
        sink = _collect_console(page)
        _add_virtual_authenticator(context, page)
        try:
            _login_with_password(page, live_server, username, password)
            page.goto(f"{live_server}/pages/change-password.html")
            page.wait_for_selector('button:has-text("新增 Passkey")', timeout=20000)
            _register_one(page, 1)

            before = _cred_row(username)
            assert before["last_used_at"] is None, "才剛註冊，last_used_at 應該還是空的"

            _passkey_login(page, live_server, username, sink)
        finally:
            context.close()
            browser.close()

    after = _cred_row(username)
    assert after["last_used_at"] is not None, (
        "Passkey 登入成功了，但 last_used_at 沒有被寫回去——重放偵測讀的就是"
        "這一欄（auth.py 那句 UPDATE 是否真的有 commit？）")
    assert after["sign_count"] > before["sign_count"], (
        f"sign_count 沒有前進（{before['sign_count']} → {after['sign_count']}）。"
        "認證器每次簽章都應該遞增，不增加就代表重放偵測形同虛設")
