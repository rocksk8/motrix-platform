"""需要應收應付（M05）的題：銀行對帳 POST /api/reports/bank-reconcile 已收回 M05（刪掉 modules/arap 時隨模組消失，PLAYBOOK §B-11）。

（2026-09-26 自 modules/analytics/tests/test_module_permission_fixes_2026_09_13.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
自 `tests/test_module_permission_fixes_2026_09_13.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。
"""
import json
from tests.test_module_permission_fixes_2026_09_13 import (  # noqa: E402,F401  含 fixture
    _auth,
    _login,
)


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
