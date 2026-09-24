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


def session_init_script(sess):
    """寫 localStorage 的 session＋sessionStorage 的「已經過 index」旗標（inject_login 與 conftest.login_as 共用）。"""
    flags = "".join("sessionStorage.setItem(%s, '1');" % json.dumps(k) for k in PREVISITED_TAB_FLAGS)
    return "try { localStorage.setItem('motrix_session', %s); %s } catch (e) {}" % (json.dumps(json.dumps(sess)), flags)


def inject_login(page_or_context, base_url, username, password):
    ctx = getattr(page_or_context, "context", page_or_context)
    r = ctx.request.post(f"{base_url}/api/auth/login", data={"username": username, "password": password})
    assert r.ok, "登入 API 失敗（%s）：%s" % (r.status, r.text()[:200])
    d = r.json()
    assert not d.get("totpRequired"), "這個帳號要 TOTP：inject_login 不處理，請走登入頁"
    sess = {k: d.get(k) for k in SESSION_KEYS}
    ctx.add_init_script(session_init_script(sess))
    return sess
