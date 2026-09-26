"""自 `tests/test_pdf_concurrency_2026_09_07.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import threading
import time
from helpers import EDGE_PDF_SEMAPHORE, run_edge_pdf, startup


def test_reports_shares_the_same_pdf_runner():
    """tests/test_pdf_concurrency_2026_09_07.py 那一題的營運報表部分：同一支 `run_edge_pdf()`，全站共用一份並發額度。"""
    import modules.analytics.api.reports as reports_module
    assert reports_module.run_edge_pdf is run_edge_pdf
