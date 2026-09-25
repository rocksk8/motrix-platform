"""PDF 產生並發限制測試（2026-09-07）。見 helpers/startup.py::EDGE_PDF_SEMAPHORE
docstring——每份 PDF 匯出（報價單/出貨單/承攬商匯款申請/發票開立簽核單/請款單/
案件結案報表/網路架構規劃書/營運報表）都各自 spawn 一個 msedge.exe --headless
子行程，正式機是單一 Windows 主機沒有行程池限制，短時間內多人觸發匯出可能同時
開出一堆 Edge 行程拖垮單機。這裡直接測 semaphore 本身的並發限制邏輯，不需要
驅動完整的 PDF 產生流程（那部分已有既有的 generate_*_pdf_bytes 測試涵蓋）。
"""
import threading
import time

from helpers import EDGE_PDF_SEMAPHORE, run_edge_pdf, startup


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


def test_pdf_gen_and_network_plan_export_share_the_same_runner():
    """pdf_gen.py／network_plan_export.py／routers/reports.py 三處必須走同一支
    `run_edge_pdf()`，並發限制才是全站共用一份額度，不是三個各自獨立、加起來
    變相把上限乘以三。

    2026-09-15 改寫：在此之前比對的是三個模組各自 import 的 `EDGE_PDF_SEMAPHORE`
    是不是同一個物件。Edge 的呼叫（semaphore ＋ 逾時 ＋ 逾時記 log）已收斂進
    `helpers/startup.py::run_edge_pdf()`，三個模組不再自己持有 semaphore，所以
    改比對那支函式。
    """
    import pdf_gen
    import modules.netplan.export as network_plan_export
    import routers.reports as reports_module

    assert pdf_gen.run_edge_pdf is run_edge_pdf
    assert network_plan_export.run_edge_pdf is run_edge_pdf
    assert reports_module.run_edge_pdf is run_edge_pdf


def test_no_module_spawns_edge_outside_the_shared_runner():
    """沒有人繞過 `run_edge_pdf()` 自己 spawn Edge。

    這一題才是真正守得住的那道：上一題只確認「現有三處用的是同一支」，**第四處
    冒出來時它不會紅**——而 2026-09-15 那次就差點漏掉第三處（`routers/reports.py`
    的 timeout 寫的是 60 不是 40，用字面值搜尋掃不到它）。這裡直接掃原始碼：
    有人自己呼叫 subprocess 去跑 msedge，就是繞過了共用的並發上限與逾時處理。
    """
    import os
    import re

    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for root, dirs, files in os.walk(backend):
        dirs[:] = [d for d in dirs
                   if d not in ("tests", "rollback_snapshots", "deploy_packages",
                                "__pycache__", "tools")]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, backend)
            if rel.replace("\\", "/") == "conftest.py":  # conftest.py 在 backend/ 根（2026-09-25 自 tests/ 上移），是測試設定不是產品碼
                continue
            if rel.replace("\\", "/") == "helpers/startup.py":
                continue  # run_edge_pdf() 本人，就是那個唯一該碰 subprocess 的地方
            src = open(path, encoding="utf-8", errors="replace").read()
            if re.search(r"subprocess\.(run|Popen|call|check_output)", src) and                     re.search(r"--headless|msedge|print-to-pdf", src):
                offenders.append(rel)

    assert not offenders, (
        "這些檔案自己 spawn Edge，繞過了 run_edge_pdf() 的並發上限與逾時處理："
        f"{offenders}"
    )
