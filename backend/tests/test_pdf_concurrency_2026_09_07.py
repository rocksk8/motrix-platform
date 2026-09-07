"""PDF 產生並發限制測試（2026-09-07）。見 helpers/startup.py::EDGE_PDF_SEMAPHORE
docstring——每份 PDF 匯出（報價單/出貨單/承攬商匯款申請/發票開立簽核單/請款單/
案件結案報表/網路架構規劃書/營運報表）都各自 spawn 一個 msedge.exe --headless
子行程，正式機是單一 Windows 主機沒有行程池限制，短時間內多人觸發匯出可能同時
開出一堆 Edge 行程拖垮單機。這裡直接測 semaphore 本身的並發限制邏輯，不需要
驅動完整的 PDF 產生流程（那部分已有既有的 generate_*_pdf_bytes 測試涵蓋）。
"""
import threading
import time

from helpers import EDGE_PDF_SEMAPHORE, startup


def test_semaphore_caps_concurrent_holders():
    max_concurrency = startup.EDGE_PDF_MAX_CONCURRENCY
    assert max_concurrency >= 1

    lock = threading.Lock()
    current = 0
    peak = 0
    workers = max_concurrency * 3  # 遠超過上限，確保真的會排隊

    def worker():
        nonlocal current, peak
        with EDGE_PDF_SEMAPHORE:
            with lock:
                current += 1
                peak = max(peak, current)
            time.sleep(0.05)
            with lock:
                current -= 1

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert peak <= max_concurrency, f"同時持有 semaphore 的執行緒數超過上限：{peak} > {max_concurrency}"
    assert peak == max_concurrency, "應該至少有一批真的頂到上限，否則這個測試沒有實際驗證到限制生效"


def test_semaphore_is_reusable_after_release():
    """確認不是一次性的 Semaphore（用完就報廢）——同一個全域物件要能反覆借用/歸還，
    對應伺服器長時間運行、陸續處理很多次 PDF 匯出請求的實際情境。"""
    for _ in range(10):
        with EDGE_PDF_SEMAPHORE:
            pass  # 借了就還，重複很多次都不該卡住或報錯


def test_pdf_gen_and_network_plan_export_share_the_same_semaphore():
    """pdf_gen.py／network_plan_export.py／routers/reports.py 三處各自 import
    的 EDGE_PDF_SEMAPHORE 必須是同一個物件，並發限制才是全站共用一份額度，
    不是三個各自獨立、加起來反而變相把上限乘以三。"""
    import pdf_gen
    import network_plan_export
    import routers.reports as reports_module

    assert pdf_gen.EDGE_PDF_SEMAPHORE is EDGE_PDF_SEMAPHORE
    assert network_plan_export.EDGE_PDF_SEMAPHORE is EDGE_PDF_SEMAPHORE
    assert reports_module.EDGE_PDF_SEMAPHORE is EDGE_PDF_SEMAPHORE
