# -*- coding: utf-8 -*-
"""W1b（第 48 班端點稽核；第 52 班擴大到全部）：**每一條 `/api/` 路由**，沒帶登入憑證時不得成功、也不得 5xx。

第 48 班只掃 case／subcontract／supply 三個模組宣告的前綴（768 條路由裡約 261 條）；第 46～50 班新增的 payroll／arap／核心路由
（payslips、cashier planned-pay-date、duty-roles、users…）完全沒被掃到（GOLDEN-DRIFT-T52 §二）。現在掃**整個 OpenAPI 的 `/api/` 路由**，
不再依模組前綴挑——新模組、核心路由、日後新增的都自動在內。

不靠原始碼樣式猜：直接把真的 app 的路由表走一遍，用假的路徑參數無憑證呼叫。
允許的結果：401／403（拒絕）、404（資源不存在，驗證先於查找的端點會先 401）、422（請求格式先被擋）、405、501；不允許 2xx／3xx 與 5xx。

公開路徑基準 `PUBLIC_BASELINE`：`main._PUBLIC_API_PATHS`（auth_middleware 在登入檢查**之前**放行的 `/api/` 路徑）的明列副本，每條附理由。
這裡的清單與 `main._PUBLIC_API_PATHS` 必須逐條相等——有人新增一條公開路徑，這個守門會紅，逼他在這裡寫下理由（＝有人做過決定）；
清單裡的路徑在路由表裡不存在也會紅（過期）。公開路徑本身不在掃描內（它們依設計不要求登入，各自驗證）；基準列的是具體路徑，路由表可能是樣板（`/api/system/branding/{kind}`），
樣板路由仍在掃描內（掃描用 `1` 代入，不是公開值 ⇒ 仍須被拒絕）。
非 `/api/` 的路由由 `test_non_api_routes_whitelist_2026_09_28.py` 管。
"""
import importlib
import re

# 與 main._PUBLIC_API_PATHS 逐條相等（見檔頭）。理由取自 main.py 該處的註解。
PUBLIC_BASELINE = {
    "/api/auth/login": "登入本身：未登入才需要打",
    "/api/auth/login/totp": "登入的第二步（兩階段驗證）：尚未取得 session",
    "/api/auth/logout": "登出：session 可能已失效，仍要能呼叫",
    "/api/ping": "健康檢查：部署工具與前端判斷服務是否在線，不含任何資料",
    "/api/system/version": "版本資訊：登入頁與部署工具使用，不含敏感內容",
    "/api/system/branding": "登入頁的公司名稱（統編只在帶有效登入時回；2026-09-26 A8d）",
    "/api/system/branding/logo": "品牌圖檔：登入頁 LOGO 由瀏覽器直接抓，沒有 header（2026-09-27 H10）",
    "/api/system/branding/logo-dark": "品牌圖檔（深色）：同上",
    "/api/system/branding/favicon": "品牌圖檔 favicon：由瀏覽器直接抓，沒有 header",
    "/api/auth/login/qr-info": "手機掃 QR 核准登入：手機端沒有任何 session，端點用 challenge_token 自行驗證（2026-09-08）",
    "/api/auth/login/qr-approve": "手機掃 QR 核准登入：用 challenge_token／密碼自行驗證",
    "/api/auth/login/qr-status": "手機掃 QR 核准登入：電腦端輪詢，用 challenge_token 自行驗證",
    "/api/auth/webauthn/login/begin": "WebAuthn 未登入登入流程：查詢帳號 Passkey 清單（2026-09-09）",
    "/api/auth/webauthn/login/complete": "WebAuthn 未登入登入流程：驗證認證器簽名，自行驗證",
    "/api/system/deployed-version": "本機部署儀表板查詢正式機目前部署版本：純讀 commit 資訊，無敏感內容（2026-09-08）",
    "/api/system/webauthn-config-status": "login.html／change-password.html 判斷是否顯示 Passkey 按鈕（2026-09-10）",
}
SWEPT_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def _fill(path):
    return re.sub(r"\{[^}]+\}", "1", path)


def sweep_targets(paths, public=None):
    """OpenAPI `paths`（{路徑: {方法: …}}）→ 要無憑證呼叫的 [(方法, 路徑)]：只取 `/api/`，扣掉公開基準。"""
    public = PUBLIC_BASELINE if public is None else public
    out = []
    for path, ops in sorted(paths.items()):
        if not path.startswith("/api/") or path in public:
            continue
        for method in sorted(ops):
            if method.upper() in SWEPT_METHODS:
                out.append((method.upper(), path))
    return out


def is_bad(status):
    """無憑證的回應不可為 2xx／3xx（成功或轉址）或 5xx（501 除外）。"""
    return status < 400 or (status >= 500 and status != 501)


def anonymous_failures(call, targets):
    """`call(method, path, **kw) -> status`；回傳 [(方法, 路徑, 狀態)]＝無憑證竟然沒被拒絕（或 5xx）的路由。"""
    bad = []
    for method, path in targets:
        kw = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
        status = call(method, _fill(path), **kw)
        if is_bad(status):
            bad.append((method, path, status))
    return bad


def public_baseline_problems(actual, baseline=None):
    """`main._PUBLIC_API_PATHS` 與本檔基準逐條相等；理由不可空泛。回傳問題清單，空＝一致。"""
    baseline = PUBLIC_BASELINE if baseline is None else baseline
    problems = []
    for p in sorted(set(actual) - set(baseline)):
        problems.append("main._PUBLIC_API_PATHS 多了 %s——公開路徑要在 PUBLIC_BASELINE 寫下理由（有人做過決定）才能放行" % p)
    for p in sorted(set(baseline) - set(actual)):
        problems.append("PUBLIC_BASELINE 的 %s 已不在 main._PUBLIC_API_PATHS（清單過期，請移除）" % p)
    for p, why in sorted(baseline.items()):
        if len(why.strip()) < 8:
            problems.append("PUBLIC_BASELINE 的 %s 理由太空泛：%r" % (p, why))
    return problems


def matching_template(path, templates):
    """具體路徑（例 `/api/system/branding/logo`）對上路由樣板（例 `/api/system/branding/{kind}`）；找不到回 None。
    公開基準列的是**具體路徑**（middleware 用 `path in _PUBLIC_API_PATHS` 精確比對），路由表裡卻可能是樣板。"""
    for t in templates:
        parts = re.split(r"\{[^}/]+\}", t)
        if re.fullmatch("[^/]+".join(re.escape(x) for x in parts), path):
            return t
    return None


def _call(client):
    return lambda method, path, **kw: client.request(method, path, **kw).status_code


def test_every_api_route_refuses_anonymous_calls(client):
    targets = sweep_targets(client.app.openapi()["paths"])
    assert len(targets) >= 500, "路由表走訪數量異常（%d），掃描器壞了？" % len(targets)
    bad = anonymous_failures(_call(client), targets)
    assert not bad, "這些路由無憑證竟然沒被拒絕（或 5xx）：\n" + "\n".join("  %s %s → %s" % b for b in bad)


def test_public_baseline_equals_the_middleware_list_and_every_entry_is_a_route(client):
    main = importlib.import_module("main")
    problems = public_baseline_problems(main._PUBLIC_API_PATHS)
    paths = client.app.openapi()["paths"]
    problems += ["PUBLIC_BASELINE 的 %s 不在路由表裡（清單過期，或該路由被拿掉了）" % p
                 for p in sorted(PUBLIC_BASELINE) if matching_template(p, paths) is None]
    assert not problems, "\n".join(problems)


def test_scanner_positive_control_sees_every_route_group(client):
    """正對照：case／subcontract／supply（原本就掃）加上 payroll／arap／accounting／核心（第 52 班新納入）都在掃描清單內。"""
    swept = set(sweep_targets(client.app.openapi()["paths"]))
    for want in [("GET", "/api/quotations/{quote_no}"),            # case
                 ("GET", "/api/contractors"),                       # subcontract
                 ("GET", "/api/shipping-notes/{note_no}"),          # supply
                 ("GET", "/api/bank-accounts"),                     # payroll
                 ("GET", "/api/cashier/bonus-queue"),               # arap
                 ("GET", "/api/account-items"),                     # accounting
                 ("GET", "/api/approval-queue")]:                   # 核心（不屬任何模組前綴）
        assert want in swept, "掃描清單少了 %s %s" % want
    assert not [t for t in swept if t[1] in PUBLIC_BASELINE], "公開基準的路徑不該在掃描清單內"


# ── 守門自己的控制／突變（合成資料，不載入 app）──
_PATHS = {"/api/a": {"get": {}, "post": {}}, "/api/ping": {"get": {}}, "/health": {"get": {}},
          "/api/b/{id}": {"delete": {}, "options": {}, "head": {}}}


def test_sweep_targets_take_only_api_routes_minus_the_public_ones():
    assert sweep_targets(_PATHS, public={"/api/ping": "x"}) == [("GET", "/api/a"), ("POST", "/api/a"), ("DELETE", "/api/b/{id}")]
    assert ("GET", "/api/ping") in sweep_targets(_PATHS, public={}), "不豁免時公開路徑就會被掃（反向控制）"


def test_matching_template_resolves_concrete_public_paths_to_route_templates():
    tpl = ["/api/system/branding", "/api/system/branding/{kind}", "/api/a/{x}/b"]
    assert matching_template("/api/system/branding/logo", tpl) == "/api/system/branding/{kind}"
    assert matching_template("/api/system/branding", tpl) == "/api/system/branding"
    assert matching_template("/api/a/9/b", tpl) == "/api/a/{x}/b"
    assert matching_template("/api/system/other", tpl) is None, "反向控制：沒有對應路由要回 None"
    assert matching_template("/api/system/branding/logo/extra", tpl) is None


def test_status_verdicts():
    for ok in (401, 403, 404, 405, 422, 501):
        assert not is_bad(ok), ok
    for bad in (200, 201, 204, 302, 500, 502, 503):
        assert is_bad(bad), bad


def test_mutation_a_route_that_answers_anonymous_calls_is_flagged():
    """突變：讓一條路由對無憑證呼叫回 200、一條回 500，掃描必須各抓到；全回 401 則乾淨。"""
    seen = []

    def fake(method, path, **kw):
        seen.append((method, path, "json" in kw))
        return {("GET", "/api/leak"): 200, ("POST", "/api/boom/1"): 500}.get((method, path), 401)
    targets = [("GET", "/api/leak"), ("POST", "/api/boom/{id}"), ("GET", "/api/fine"), ("PUT", "/api/fine")]
    assert anonymous_failures(fake, targets) == [("GET", "/api/leak", 200), ("POST", "/api/boom/{id}", 500)]
    assert ("PUT", "/api/fine", True) in seen and ("GET", "/api/fine", False) in seen, "寫入類要帶空 json、GET 不帶"
    assert anonymous_failures(lambda m, p, **kw: 401, targets) == []


def test_mutation_an_undecided_public_path_or_a_stale_entry_is_red():
    assert public_baseline_problems(set(PUBLIC_BASELINE)) == []
    extra = public_baseline_problems(set(PUBLIC_BASELINE) | {"/api/users"})
    assert len(extra) == 1 and "/api/users" in extra[0] and "多了" in extra[0]
    gone = public_baseline_problems(set(PUBLIC_BASELINE) - {"/api/ping"})
    assert len(gone) == 1 and "/api/ping" in gone[0] and "過期" in gone[0]
    thin = public_baseline_problems(set(PUBLIC_BASELINE), baseline=dict(PUBLIC_BASELINE, **{"/api/ping": "x"}))
    assert len(thin) == 1 and "太空泛" in thin[0]
