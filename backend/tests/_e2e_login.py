"""e2e 登入不走登入頁：API 取 token、注入 localStorage（PLAN-TEST-PERF #5，2026-09-25）。

走登入頁＝登入頁＋index.html 兩次頁面載入（約 1 秒／題），而絕大多數題要驗的不是登入。
session 的格式跟著 login.html `_storeSessionAndRedirect` 走（`test_e2e_shared_fixtures` 有一題比對兩邊同形）。
⚠️ 要驗登入頁本身的題不要用這個。注入後**不會換頁**：呼叫端要自己 goto 目標頁（寫在 add_init_script，
下一次載入任何頁面時生效）。
"""
import json

SESSION_KEYS = ("token", "userId", "username", "displayName", "role", "modules", "loginAt")

#: 走登入頁時，第一頁是 index：notif.js 的「每個分頁只跳一次」右上角橫幅（兩步驟驗證提醒、待簽核通知）
#: 會在 index 上跳掉並記下旗標。注入登入直接開目標頁 ⇒ 橫幅改跳在目標頁、蓋住右上角的按鈕
#: （2026-09-25 實測：#totp-reminder-banner 蓋住案件頁「儲存」，延遲約 1.4 秒出現 ⇒ 偶發紅）。
#: ⇒ 預先寫入旗標，等同「已經經過 index」——與改動前的分頁狀態相同。要驗這兩個橫幅的題請走登入頁。
PREVISITED_TAB_FLAGS = ("motrix_totp_reminder_shown", "motrix_approval_banner_shown")


#: D12（2026-10-03）：新設計器預設開之後，既有 e2e（驗舊畫面）一律釘在舊畫面——除非自己清掉（test_e2e_designer_default_on_2026_10_03.py）。
LEGACY_UI_PINS = ("mb_designer", "et_designer")


def session_init_script(sess):
    """寫 localStorage 的 session＋sessionStorage 的「已經過 index」旗標（inject_login 與 conftest.login_as 共用）。"""
    flags = "".join("sessionStorage.setItem(%s, '1');" % json.dumps(k) for k in PREVISITED_TAB_FLAGS)
    pins = "".join("if (!sessionStorage.getItem('_no_legacy_pin') && localStorage.getItem(%s) === null) localStorage.setItem(%s, '0');" % (json.dumps(k), json.dumps(k)) for k in LEGACY_UI_PINS)
    return "try { localStorage.setItem('motrix_session', %s); %s %s } catch (e) {}" % (json.dumps(json.dumps(sess)), flags, pins)


def bootstrap_unavailable(page_or_context):
    """讓 `GET /api/bootstrap` 回 404 ⇒ auth-guard.js 的 `window.MotrixBoot` 變 null ⇒ 各處退回打**原端點**（與 bootstrap 上線前相同）。

    2026-11-13（perf：bootstrap）：第一次要啟動區段（auth/me、platform/menu、system/branding、build-info、bonus-module-status、modules/availability、
    approval-queue/count、notifications/mine、reads/module-counts、online-users、auth/totp/status）時，頁面不再打原端點、改由 `/api/bootstrap` 供應。
    所以**用 page.route／window.fetch 包裝去攔這些原端點**的題目（回 500、扣住第一趟、數請求次數）看不到那一趟——要驗的是「原端點被攔／被扣住時頁面的行為」，
    先呼叫這個把 bootstrap 關掉，題目驗的東西就跟以前一樣。bootstrap 路徑自己的降級（區段在 200 的 bootstrap 裡失敗 ⇒ 退回原端點 ⇒ 同樣的結果）
    另有題目守（test_e2e_menu_layout.py::test_menu_failure_inside_a_200_bootstrap_*）。要在 goto 之前呼叫（context／page 皆可）。"""
    page_or_context.route("**/api/bootstrap", lambda route: route.fulfill(status=404, content_type="application/json", body='{"detail": "disabled by test"}'))


def wait_logged_in(page, timeout=10000):
    """登入成功後等「應用就緒」：網址到 /index.html（只等 DOMContentLoaded）＋ sidebar.js 已畫出頂欄（#app-topbar）。
    〔O5-S1：原本 `wait_for_url(...)` 預設等 `load`，而 load 被兩支約 5 MB 的字型綁住——這幾題要驗的是「有沒有登入成功」，
      不是子資源有沒有下載完（INVESTIGATION-D-O5 §3）〕"""
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=timeout, wait_until="domcontentloaded")
    page.wait_for_selector("#app-topbar", state="attached", timeout=timeout)


def inject_login(page_or_context, base_url, username, password):
    ctx = getattr(page_or_context, "context", page_or_context)
    r = ctx.request.post(f"{base_url}/api/auth/login", data={"username": username, "password": password})
    assert r.ok, "登入 API 失敗（%s）：%s" % (r.status, r.text()[:200])
    d = r.json()
    assert not d.get("totpRequired"), "這個帳號要 TOTP：inject_login 不處理，請走登入頁"
    sess = {k: d.get(k) for k in SESSION_KEYS}
    ctx.add_init_script(session_init_script(sess))
    return sess
