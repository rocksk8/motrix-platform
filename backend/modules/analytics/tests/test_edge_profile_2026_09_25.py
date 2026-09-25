"""自 `tests/test_edge_profile_2026_09_25.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import threading
import time
from pathlib import Path
import helpers
import helpers.startup as startup
import helpers.voucher_pdf as voucher_pdf
import network_plan_export
import pdf_gen
from tests.test_edge_profile_2026_09_25 import (  # noqa: E402,F401  含 fixture
    _capture,
)


def test_every_import_site_uses_the_wrapper_and_the_product_function_is_untouched(client, monkeypatch):
    import sys
    import modules.analytics.api.reports as reports_module
    w = pdf_gen.run_edge_pdf
    assert all(getattr(m, "run_edge_pdf") is w
               for m in (startup, helpers, network_plan_export, voucher_pdf, reports_module)), \
        "有一處呼叫端沒換到（依值綁定的 import 要逐一換）"
    # 第一版寫死 5 處、漏了 routers/reports ⇒ 直接驗「沒有任何已載入模組還綁著原函式」
    stale = [name for name, m in list(sys.modules.items())
             if getattr(m, "run_edge_pdf", None) is w.__wrapped__]
    assert stale == [], "這些模組仍綁著原函式（產 PDF 時會用新 profile）：%s" % stale
    seen = _capture(monkeypatch)
    w(["msedge.exe", "--headless", "file:///x.html"])
    w.__wrapped__(["msedge.exe", "--headless", "file:///x.html"])
    assert seen[0][0] == "msedge.exe" and seen[0][1].startswith("--user-data-dir="), seen[0]
    assert "edge_profiles" in seen[0][1], "profile 不在測試暫存底下：%s" % seen[0][1]
    assert seen[1] == ["msedge.exe", "--headless", "file:///x.html"], "產品函式本身被改了：%s" % seen[1]
