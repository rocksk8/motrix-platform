"""自 `tests/test_module_permission_fixes_2026_09_13.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import json
from tests.test_module_permission_fixes_2026_09_13 import (  # noqa: E402,F401  含 fixture
    _auth,
    _login,
)


def test_reports_module_actually_opens_the_reports_api(client, make_user):
    """勾了「營運報表」的業務要真的打得開報表 API（修正前一律 403）。"""
    u, p = make_user(username="r_sales", role="sales", modules=["dashboard", "reports"])
    tok = _login(client, u, p)
    r = client.get("/api/reports/financial?period=2026-09", headers=_auth(tok))
    assert r.status_code == 200, f"勾了營運報表卻還是進不去：{r.status_code} {r.text}"


def test_finance_module_also_opens_it(client, make_user):
    """`finance`（應收帳款／銷售訂單）同樣能進——側欄本來就用它顯示營運報表入口，
    而那兩頁的內容 2026-08-31 已經併進這一頁。比照 `cashier.py::_require_view_access`。"""
    u, p = make_user(username="r_fin", role="sales", modules=["dashboard", "finance"])
    tok = _login(client, u, p)
    assert client.get("/api/reports/financial?period=2026-09",
                      headers=_auth(tok)).status_code == 200


def test_user_without_either_module_is_still_blocked(client, make_user):
    """反向：沒有那兩個模組的非管理員仍然擋住——這次改的是「認模組」，不是開放。"""
    u, p = make_user(username="r_none", role="sales", modules=["dashboard", "quotation"])
    tok = _login(client, u, p)
    r = client.get("/api/reports/financial?period=2026-09", headers=_auth(tok))
    assert r.status_code == 403, f"沒有模組的人也進得去了：{r.status_code}"


def test_bank_reconcile_still_requires_admin_or_cashier(client, make_user):
    """對帳是「動作」不是報表查閱，維持 admin+／cashier，不跟著放寬。"""
    u, p = make_user(username="r_rep_only", role="sales", modules=["dashboard", "reports"])
    tok = _login(client, u, p)
    # 這支吃 multipart 檔案上傳；不帶檔案會在 FastAPI 驗證階段就 422，
    # 根本走不到權限檢查——那樣的 422 綠燈證明不了任何權限行為。
    r = client.post("/api/reports/bank-reconcile",
                    files={"file": ("t.csv", b"date,amount\n", "text/csv")},
                    headers=_auth(tok))
    assert r.status_code == 403, f"reports 模組不該打得開對帳：{r.status_code} {r.text}"


def test_modules_without_backend_checks_now_block(client, make_user):
    """只有 `dashboard` 的帳號打不開裝置清單（其餘三支在 tests/test_module_permission_fixes_2026_09_13.py）。"""
    u, p = make_user(username="mod_none", role="viewer", modules=["dashboard"])
    tok = _login(client, u, p)
    r = client.get("/api/devices", headers=_auth(tok))
    assert r.status_code == 403, f"/api/devices 沒有擋：{r.status_code}"
