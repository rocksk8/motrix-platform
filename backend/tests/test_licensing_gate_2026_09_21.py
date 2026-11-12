# -*- coding: utf-8 -*-
"""授權守門（`LICENSE_GATE_ENABLED`，main.py::license_gate_middleware）**開著時**的行為。

這份檔案是 STATE 當年定的「解凍前置」：第 2 輪（middleware／kind／快取）的驗收條件，除了「關著時不介入」
之外沒有任何一條被測試跑過（`backend/tests/` 對 `LICENSE_GATE_ENABLED` 一度零命中，middleware 第一行就
`return`，所以 `main.py` 守門主體從未被執行過）。2026-11-11 使用者裁示把預設改為開，這份測試與預設值同一次交付。

四種情境（每一種都走**真的簽章路徑**：真的 `sign_license`、真的 `verify_license`，只換公鑰與機器指紋，見 conftest
`license_test_key`），都從 HTTP 進去、看業務 API 的狀態碼，不是只驗純函式：
  1. 沒有金鑰       → 402（reason=missing）
  2. 金鑰過期       → 年費 402（reason=expired）；永久授權 200（過期只是維護期結束）
  3. 金鑰無效       → 402：簽章不符／被竄改／格式損毀／發給別台機器
  4. 金鑰有效       → 200

⚠️ 這份檔案裡**沒有任何一題會呼叫真的 `machine_fingerprint`**（它在 Windows 上會跑 PowerShell `Get-CimInstance`
讀硬體）。conftest 把它換成固定值；本檔另外把 `licensing._run`（所有外部指令的唯一入口）換成「被呼叫就失敗」。

⚠️ 每一題打 API 的 402／200 斷言都同時看 `code`／`reason`，並用「同一請求換一把金鑰」的正對照證明
被擋的原因是授權，不是別的（`auth_middleware` 對沒登入的 `/api/*` 也會回 401，見 test_g）。
"""
import base64
import datetime as _dt
import json
import os

import pytest

from conftest import TEST_LICENSE_MACHINE
from helpers import licensing as lic

BUSINESS_API = "/api/customers"          # 一支一般的業務 API（登入後可讀）


# ── 固件 ─────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _no_external_commands(monkeypatch):
    """本檔不許碰硬體：`machine_fingerprint` 以外的外部指令入口也一併封死。"""
    def _boom(*a, **kw):
        pytest.fail("授權守門測試不該跑外部指令（PowerShell Get-CimInstance 讀硬體）：%r" % (a,))
    monkeypatch.setattr(lic, "_run", _boom)


@pytest.fixture()
def hdr(client, make_user):
    """已登入的一般管理者。登入端點在豁免清單裡，所以先登入再換金鑰也行；這裡在金鑰有效時登入。"""
    username, password = make_user(role="admin")
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def sign(license_test_key):
    """簽一把金鑰（預設：發給測試機、模組全開、年費、一年後到期）。回 blob 字串。"""
    def _sign(priv_pem=None, **overrides):
        payload = {
            "customer": "測試用公司", "tax_id": "00000000", "machine": TEST_LICENSE_MACHINE,
            "modules": ["*"], "issued": "2026-01-01",
            "expires": (_dt.date.today() + _dt.timedelta(days=365)).isoformat(),
            "kind": lic.LICENSE_KIND_SUBSCRIPTION,
        }
        payload.update(overrides)
        return lic.sign_license(payload, priv_pem or license_test_key["priv_pem"])
    return _sign


@pytest.fixture()
def install_key(monkeypatch, tmp_path):
    """把一段文字當成 license.key 裝到 LICENSE_PATH（None＝不裝）。每次呼叫都換一份新檔，路徑不變。"""
    path = tmp_path / "gate" / "license.key"
    path.parent.mkdir()
    monkeypatch.setattr(lic, "LICENSE_PATH", str(path))

    def _install(blob):
        if blob is None:
            if path.exists():
                path.unlink()
            return path
        path.write_text(blob, encoding="utf-8")
        # 同一路徑被改寫：mtime 解析度不保證，手動往後推，驗證「換檔會重讀」不靠運氣
        st = path.stat()
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        return path
    return _install


def _assert_blocked(r, reason):
    assert r.status_code == 402, f"預期 402，實際 {r.status_code}：{r.text}"
    body = r.json()
    assert body["code"] == "license_required", body
    assert body["reason"] == reason, body
    assert body["detail"] and any("一" <= c <= "鿿" for c in body["detail"]), \
        "402 的 detail 必須是給人看的中文訊息，不可以是空的"


# ── 出貨預設 ─────────────────────────────────────────────────────────────────

def test_gate_ships_enabled():
    """出貨預設值是**開**（2026-11-11 使用者裁示；原本是關，見 helpers/licensing.py 的沿革註解）。

    ⚠️ 這題故意不看 conftest：`license_test_key` 只換公鑰／金鑰路徑／指紋，沒有碰這個開關。
    有人把它改回 False，這題就紅——要改回去必須連同這份測試一起被看見。"""
    assert lic.LICENSE_GATE_ENABLED is True


def test_the_conftest_key_is_a_real_signed_key_not_a_stub(license_test_key):
    """量尺：測試 session 的「有效金鑰」是走真的驗章通過的，不是把 verify_license 換成假的。
    （否則這份檔案的 200 全是自己造出來的。）"""
    assert lic.machine_fingerprint() == TEST_LICENSE_MACHINE
    st = lic.verify_license()
    assert (st["valid"], st["reason"], st["env"], st["modules"]) == (True, "ok", "prod", ["*"]), st
    assert st["kind"] == lic.LICENSE_KIND_SUBSCRIPTION
    # 換一把別人簽的 ⇒ 同一條驗章路徑必須判無效
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    other = ed25519.Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    forged = lic.sign_license({"customer": "x", "tax_id": "1", "machine": TEST_LICENSE_MACHINE, "modules": ["*"],
                               "issued": "2026-01-01", "expires": "2099-12-31"}, other)
    assert lic.verify_license(forged)["reason"] == "bad_signature"


# ── 情境 4：金鑰有效 ─────────────────────────────────────────────────────────

def test_valid_key_lets_business_api_through(client, hdr):
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 200, r.text
    s = client.get("/api/license/status", headers=hdr)
    assert s.status_code == 200 and s.json()["valid"] is True and s.json()["reason"] == "ok", s.text


# ── 情境 1：沒有金鑰 ─────────────────────────────────────────────────────────

def test_no_key_blocks_business_api_with_402(client, hdr, install_key, sign):
    # 正對照：同一個請求，裝了有效金鑰是 200，拿掉金鑰變 402 ⇒ 擋的是授權
    install_key(sign())
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200
    install_key(None)
    assert lic.verify_license()["reason"] == "missing"
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "missing")


def test_blank_key_file_is_missing_not_malformed(client, hdr, install_key):
    install_key("  \n")
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "missing")


# ── 情境 2：金鑰過期 ─────────────────────────────────────────────────────────

def test_expired_subscription_is_blocked(client, hdr, install_key, sign):
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    install_key(sign(expires=yesterday))
    st = lic.verify_license()
    assert (st["reason"], st["kind"], st["days_left"]) == ("expired", "subscription", -1), st
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "expired")


def test_license_expiring_today_is_still_valid(client, hdr, install_key, sign):
    """邊界：今天到期 ＝ days_left 0 ＝ 還有效（昨天到期才擋）。差一天就是客戶被提早鎖在門外。"""
    install_key(sign(expires=_dt.date.today().isoformat()))
    assert lic.verify_license()["days_left"] == 0
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200


def test_expired_perpetual_is_not_blocked(client, hdr, install_key, sign):
    """永久授權過期的是維護期，不是使用權：不擋，只在 status 帶 expired 讓畫面提示。"""
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    install_key(sign(expires=yesterday, kind=lic.LICENSE_KIND_PERPETUAL))
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200
    s = client.get("/api/license/status", headers=hdr).json()
    assert (s["valid"], s["reason"], s["kind"]) == (False, "expired", "perpetual"), s


@pytest.mark.parametrize("kind", ["", "lifetime", 1, ["perpetual"]])
def test_unknown_kind_expired_is_treated_as_subscription_and_blocked(client, hdr, install_key, sign, kind):
    """`kind` 拼錯／型別不對 ⇒ 當年費（過期會擋）。把不認得的值當永久＝任何打錯字的金鑰都永不過期。"""
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    install_key(sign(expires=yesterday, kind=kind))
    assert lic.verify_license()["kind"] == lic.LICENSE_KIND_SUBSCRIPTION
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "expired")


def test_legacy_key_without_kind_field_is_subscription(client, hdr, install_key, license_test_key):
    """第 1 輪簽出來的金鑰沒有 `kind` 欄位：視為年費（過期會擋），不是突然變 malformed、也不是永久。"""
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    legacy = lic.sign_license({"customer": "舊金鑰", "tax_id": "0", "machine": TEST_LICENSE_MACHINE,
                               "modules": ["*"], "issued": "2026-01-01", "expires": yesterday},
                              license_test_key["priv_pem"])
    install_key(legacy)
    assert lic.verify_license()["reason"] == "expired"
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "expired")


def test_kind_is_normalised_perpetual_in_any_case_and_padding(client, hdr, install_key, sign):
    """`"Perpetual "`（大小寫、空白）被正規化成永久是**有意**的；過期也不擋。"""
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    install_key(sign(expires=yesterday, kind=" Perpetual "))
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200


def test_a_long_running_server_notices_the_day_the_license_expires(client, hdr, install_key, sign, monkeypatch):
    """檔案不變、日子變了：一台**不重啟**的正式機在到期那天必須開始擋（快取鍵含今天的日期）。
    少了這一項，年費授權會變成永久授權，而且沒有任何錯誤訊息（licensing.py 的 ⑤）。"""
    real_date = lic.date
    expires = _dt.date.today() + _dt.timedelta(days=2)
    install_key(sign(expires=expires.isoformat()))
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200          # 暖快取

    class _LaterDate(real_date):
        @classmethod
        def today(cls):
            return real_date.today() + _dt.timedelta(days=3)

    monkeypatch.setattr(lic, "date", _LaterDate)
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "expired")


def test_replacing_the_key_file_takes_effect_without_restart(client, hdr, install_key, sign):
    install_key(None)
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "missing")
    install_key(sign())
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200
    install_key(sign(expires=(_dt.date.today() - _dt.timedelta(days=5)).isoformat()))
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "expired")


# ── 情境 3：金鑰無效 ─────────────────────────────────────────────────────────

def _forge(blob, mutate):
    payload = json.loads(base64.b64decode(blob))
    mutate(payload)
    return base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")


def test_key_signed_by_someone_else_is_bad_signature(client, hdr, install_key, sign):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    other = ed25519.Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption())
    install_key(sign(priv_pem=other))
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "bad_signature")


@pytest.mark.parametrize("field,value", [
    ("expires", "2099-12-31"),                       # 把到期日往後改
    ("modules", ["*", "extra"]),
    ("customer", "別家公司"),
    ("kind", lic.LICENSE_KIND_PERPETUAL),            # 把年費竄改成永久：kind 也在簽章範圍內
])
def test_tampered_key_is_bad_signature(client, hdr, install_key, sign, field, value):
    blob = sign(expires=(_dt.date.today() + _dt.timedelta(days=10)).isoformat())
    forged = _forge(blob, lambda p: p.__setitem__(field, value))
    assert forged != blob
    install_key(forged)
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "bad_signature")


@pytest.mark.parametrize("label,blob", [
    ("亂碼", "!!!not base64!!!"),
    ("base64 但不是 JSON", base64.b64encode(b"hello").decode()),
    ("JSON 但不是物件", base64.b64encode(b"[1,2,3]").decode()),
    ("缺必要欄位", base64.b64encode(json.dumps({"sig": "AAAA"}).encode()).decode()),
])
def test_malformed_key_is_blocked(client, hdr, install_key, label, blob):
    install_key(blob)
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "malformed")


def test_truncated_valid_key_is_blocked(client, hdr, install_key, sign):
    install_key(sign()[:-12])
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 402 and r.json()["reason"] in ("malformed", "bad_signature"), r.text


def test_key_issued_to_another_machine_is_machine_mismatch(client, hdr, install_key, sign):
    install_key(sign(machine="ffffffffffffffff"))
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "machine_mismatch")


def test_unreadable_machine_id_is_refused_not_accepted(client, hdr, install_key, sign, monkeypatch):
    """讀不到本機指紋 ＝ 無法確認金鑰是發給這台的 ⇒ 擋，不是放行（『讀不到就當它對』是把鎖拆掉）。"""
    install_key(sign())
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200

    def _cannot():
        raise RuntimeError("無法取得任何硬體識別")
    monkeypatch.setattr(lic, "machine_fingerprint", _cannot)
    # 換一份檔案內容讓快取失效（快取鍵不含指紋；指紋壞掉是行程內的事，下一份金鑰才會重算）
    install_key(sign(customer="換一份才會重算"))
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "machine_mismatch")


# ── 豁免與順序 ───────────────────────────────────────────────────────────────

def test_exempt_paths_are_pinned():
    """豁免清單是具名常數，少一條或多一條都要被看見。"""
    assert lic.LICENSE_EXEMPT_PATHS == frozenset({
        "/api/ping", "/api/auth/login", "/api/auth/logout", "/api/license/status",
        # T83（授權匯入）：授權失效時唯一能救回系統的動作就是匯入新授權；兩條端點自己驗「最高管理者＋非示範帳號」
        # （tests/test_license_import_2026_11_13.py 釘住）
        "/api/license/overview", "/api/license/import",
    })


def test_without_a_key_the_customer_can_still_log_in_and_see_why(client, make_user, install_key):
    """客戶沒有金鑰時仍要能自救：登入、看 /api/license/status（知道為什麼被擋）、非 /api/ 的頁面載得出來。"""
    username, password = make_user(role="admin")
    install_key(None)
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}
    s = client.get("/api/license/status", headers=h)
    assert s.status_code == 200 and s.json()["valid"] is False and s.json()["reason"] == "missing", s.text
    assert client.get("/api/ping").status_code != 402
    assert client.get("/", follow_redirects=False).status_code != 402          # 靜態頁不擋
    assert client.options(BUSINESS_API).status_code != 402                      # CORS 預檢不擋
    _assert_blocked(client.get(BUSINESS_API, headers=h), "missing")


def test_existing_public_endpoints_stay_reachable_without_a_key(client, install_key):
    import main
    install_key(None)
    for path in sorted(main._PUBLIC_API_PATHS):
        r = client.get(path)
        assert r.status_code != 402, f"{path} 在沒有金鑰時被授權守門擋了（{r.status_code}）：公開端點必須照常"


def test_g_unauthenticated_request_gets_401_not_402(client, install_key):
    """順序：先確認是誰，再確認這台機器有沒有買。寫反了＝對還沒通過身分驗證的人洩漏「這台機器沒有授權」。
    （守門 middleware 要宣告在 auth_middleware 之前，Starlette 後宣告的在外層、先跑。）"""
    install_key(None)
    r = client.get(BUSINESS_API)
    assert r.status_code == 401, f"沒登入的請求要 401，不可以是 {r.status_code}：{r.text}"
    assert "license" not in r.text.lower()


@pytest.mark.parametrize("qs", ["pt=garbage", "pt=1", "pt=%00"])
def test_lg_s1_unauthenticated_uploads_pt_request_gets_401_not_402(client, install_key, qs):
    """T80稽核 LG-S1：`/api/uploads/*?pt=…` 是 auth_middleware 唯一放行「沒帶 Authorization」的非公開路徑，
    任何亂填的 pt 都會走進授權守門。沒有金鑰時它以前回 402＋完整 reason，對陌生人洩漏授權狀態。"""
    install_key(None)
    r = client.get("/api/uploads/anything/x.png?" + qs)
    assert r.status_code == 401, f"沒登入只帶 pt 的請求要 401，不可以是 {r.status_code}：{r.text}"
    assert "license" not in r.text.lower() and "reason" not in r.json(), r.text


def test_lg_s1_uploads_pt_request_still_reaches_the_route_when_licensed(client, install_key, sign):
    """正對照：有授權時 `?pt=` 照舊進路由（亂填的簽章 ⇒ 路由自己回 403，而不是被守門吃掉）。"""
    install_key(sign())
    r = client.get("/api/uploads/anything/x.png?pt=garbage")
    assert r.status_code == 403, r.text


def test_402_is_not_403(client, hdr, install_key):
    """402＝這台機器沒買、403＝這個人沒權限。客服現場要分得開。"""
    install_key(None)
    r = client.get(BUSINESS_API, headers=hdr)
    assert r.status_code == 402 and r.status_code != 403


# ── 關著時的那一條分支仍在 ───────────────────────────────────────────────────

def test_switching_the_gate_off_restores_pass_through_even_without_a_key(client, hdr, install_key, monkeypatch):
    """關著時完全不介入（連 verify_license 都不呼叫）：沒金鑰也 200。這一支是預設改開之後唯一留下這條分支的地方
    之一（另一處：test_procurement_leadtime 條件 8），拿掉開關的人會在這裡被攔下。"""
    install_key(None)
    _assert_blocked(client.get(BUSINESS_API, headers=hdr), "missing")
    monkeypatch.setattr(lic, "LICENSE_GATE_ENABLED", False)
    monkeypatch.setattr(lic, "verify_license", lambda blob=None: pytest.fail("關著時不該讀金鑰"))
    assert client.get(BUSINESS_API, headers=hdr).status_code == 200


# ── 模組授權（同一把金鑰也決定哪些模組載入）─────────────────────────────────

def test_module_license_check_follows_the_real_signed_key(install_key, sign):
    install_key(sign(modules=["case"]))
    assert lic.module_license_check({"key": "case"})[0] is True
    ok, why = lic.module_license_check({"key": "payroll"})
    assert ok is False and "未包含" in why
    install_key(sign(modules=["*"]))
    assert lic.module_license_check({"key": "payroll"})[0] is True
    install_key(None)
    ok, why = lic.module_license_check({"key": "case"})
    assert ok is False and "未授權" in why
