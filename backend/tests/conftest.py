"""Shared fixtures for API-level integration tests.

Boots the *real* FastAPI app (main.app) — same middleware, same routers,
same startup sequence — but redirects every file-system touchpoint (SQLite
DBs, local backup snapshots, cloud archive dirs, backup alert files) into a
throwaway pytest tmp_path first. This lets tests exercise real HTTP requests
through the real auth/demo-isolation logic without ever touching the actual
motrix_erp.db or backend/db_backups/.

Two things make this delicate and are the reason for the extra patching below
(see inline comments): (1) main.py's startup code runs once, at module import
time, not inside an @app.on_event handler — so all patching must happen
*before* `import main` executes; (2) archive.py and main.py each do
`from db import ... DB_PATH` / `DEMO_DB_PATH` *by value*, so patching
db.DB_PATH alone does not update their already-bound copies — both modules'
own attributes need patching too.
"""
import importlib
import os as _bk19_os
import sys
import tempfile as _bk19_tempfile
from pathlib import Path as _Bk19Path

import pytest

# ══════════════════════════════════════════════════════════════════════
# BK19 · 測試期間不可以碰到真的雲端硬碟
# ══════════════════════════════════════════════════════════════════════
#
# BK11 結案（1593d8a）：2026-08-30／08-31／09-03 三天的雲端每日備份是**空庫**。
# 成因是這個檔的雲端隔離**死碼** —— patch 釘在五個大寫常數上，
# 而 archive.py 早就改成 `_archive_base()` 這種動態掃描磁碟機的函式
# ⇒ patch 什麼都沒隔離到 ⇒ 跑 pytest 時 DB 指向 tmp 空庫、
#   而 `_archive_base()` 真的掃到 G: ⇒ 空庫被覆寫進雲端當天的資料夾。
#
# 🔑 〈守門守的對象被搬走〉：隔離寫了、對象被搬走了、測試全綠 ——
# ☠️ **而這一次的代價落在 repo 之外，所以沒有任何一題會因此變紅。**
#
# ⇒ 這道守門在**每一題開始前**問一次「`_archive_base()` 現在指到哪」。
# ⚠️ 判準是「回傳值在不在 tmp 底下」，**不是「有沒有寫成功」**：
#    後者要真的寫一次才知道，而那正是這裡要避免的事。

#: `_app` 建立的隔離根目錄。⚠️ 用集合而不是單一值：xdist 每個 worker 一份。
_ISOLATION_ROOTS: set = set()


def archive_path_is_isolated(path) -> bool:
    """這個存檔路徑是不是在測試的 tmp 底下。

    ⚠️ **fail closed**：空字串／`None`／算不出來 ⇒ 一律回 `False`。
    🔑 「我不知道它指到哪」不可以被當成「它是安全的」——
    而 `_archive_base()` 掃不到任何磁碟機時回的正是 `""`。
    """
    if not path:
        return False
    try:
        resolved = _Bk19Path(str(path)).resolve()
    except (OSError, ValueError):
        return False
    roots = set(_ISOLATION_ROOTS)
    roots.add(_Bk19Path(_bk19_tempfile.gettempdir()).resolve())
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


#: BK19 診斷模式：設 `MOTRIX_BK19_REPORT=1` ⇒ 不 fail，只把寫入路徑收集起來。
#: 📌 它的用途是**先量再訂判準** —— 直接訂「tmp 之外一律 fail」會在 1,600 題上
#: 一次爆開，而那時分不出「真的越界」與「我沒想到的合法寫入」。
_BK19_WRITES: set = set()


def _bk19_write_allowed(path) -> bool:
    """這個**寫入**路徑允不允許。fail closed。"""
    if not path:
        return False
    try:
        resolved = _Bk19Path(str(path)).resolve()
    except (OSError, ValueError, TypeError):
        return False
    roots = set(_ISOLATION_ROOTS)
    roots.add(_Bk19Path(_bk19_tempfile.gettempdir()).resolve())
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


#: repo 根目錄。repo 內的越界寫入是**隔離缺口**，repo 外的是**事故**。
_BK19_REPO_ROOT = _Bk19Path(__file__).resolve().parent.parent.parent


def _bk19_inside_repo(path) -> bool:
    try:
        _Bk19Path(str(path)).resolve().relative_to(_BK19_REPO_ROOT)
        return True
    except (OSError, ValueError, TypeError):
        return False


@pytest.fixture(scope="session", autouse=True)
def _bk19_no_write_outside_tmp():
    """🔴 BK19：測試期間**任何寫入**都不可以落在 tmp 之外。

    ## ☠️ 為什麼不是釘 `_archive_base()` 的回傳值

    D 查證：那只守得住一條，另有三條繞得過去。
    ```
    甲  cloud_storage.s3_put_bytes()  完全不經過 _archive_base()
        ⇒ 開發者 shell 漏進來的 AWS 憑證會讓測試真的上傳
    乙  main.py:517 _ensure_archive_dirs() 在**模組層**執行
        ⇒ patch 生效前 import main 就已經在真實磁碟建好目錄（另立 BK20）
    丙  逐一 patch 的模組層常數 —— 新增一個而 conftest 沒跟上就重演 09-07
    ```
    🔑 ⇒ **斷言對象不是某一個函式的回傳值，是「實際寫到哪裡」。**

    ⚠️ 乙那一條**這道守門抓不到**：它在 import 當下就發生了，
    而這個 fixture 是在 import 之後才裝上去的。📌 那是 `BK20`。
    """
    import builtins
    import os as _os
    import shutil as _shutil

    report_only = _bk19_os.environ.get("MOTRIX_BK19_REPORT") == "1"
    real_open = builtins.open
    real_makedirs = _os.makedirs
    real_copy = _shutil.copy
    real_copy2 = _shutil.copy2
    real_copyfile = _shutil.copyfile

    def _check(path, what):
        if _bk19_write_allowed(path):
            return
        _BK19_WRITES.add(f"{what}: {path}")
        # 🔴 分兩級，而分級的依據是**量出來的**不是猜的
        #    （2026-09-22 用 `MOTRIX_BK19_REPORT=1` 實跑 60 題）：
        #    tmp 外的寫入共 11 種，**全部落在 repo 內**，沒有任何一條碰到
        #    G: 或別的磁碟機。
        #
        #    repo 外  ⇒ 立刻炸。那是 2026-08-30 三份空備份的那一類，
        #               而它的代價落在使用者的雲端硬碟上、repo 裡看不到。
        #    repo 內  ⇒ 只記錄。它們是真的隔離缺口（見
        #               `test_bk19_nothing_was_written_outside_tmp`），
        #               ⚠️ 而在這裡炸的話，60 題會同時紅在一個看不懂的地方 ——
        #               **一個講不清楚自己在說什麼的紅燈，會被當成雜訊關掉。**
        if not report_only and not _bk19_inside_repo(path):
            raise AssertionError(
                f"BK19：測試想寫到 repo 與 tmp 之外 —— {what} {path!r}. "
                "2026-08-30／08-31／09-03 三份空備份就是這樣寫進雲端硬碟的。")

    def _open(file, mode="r", *a, **kw):
        if isinstance(file, (str, bytes, _os.PathLike)) and any(
                c in str(mode) for c in ("w", "a", "x", "+")):
            _check(file, "open")
        return real_open(file, mode, *a, **kw)

    def _makedirs(name, *a, **kw):
        _check(name, "makedirs")
        return real_makedirs(name, *a, **kw)

    def _wrap_copy(fn, label):
        def _inner(src, dst, *a, **kw):
            _check(dst, label)
            return fn(src, dst, *a, **kw)
        return _inner

    builtins.open = _open
    _os.makedirs = _makedirs
    _shutil.copy = _wrap_copy(real_copy, "shutil.copy")
    _shutil.copy2 = _wrap_copy(real_copy2, "shutil.copy2")
    _shutil.copyfile = _wrap_copy(real_copyfile, "shutil.copyfile")
    try:
        yield
    finally:
        builtins.open = real_open
        _os.makedirs = real_makedirs
        _shutil.copy = real_copy
        _shutil.copy2 = real_copy2
        _shutil.copyfile = real_copyfile
        if report_only and _BK19_WRITES:
            print("[BK19] tmp 之外的寫入 %d 種：" % len(_BK19_WRITES))
            for line in sorted(_BK19_WRITES):
                print("   ", line)


@pytest.fixture(autouse=True)
def _no_politeness_delay(monkeypatch):
    """**把「對別人伺服器的禮貌延遲」在測試裡設成 0。**

    ## 🔴 它關掉了什麼

    ```
    helpers/tender_source.py:149  DETAIL_INTERVAL_SECONDS = 2
                           :596   if i: time.sleep(DETAIL_INTERVAL_SECONDS)
    ```
    ⇒ 在測試裡設成 **0**。**只有這一個常數**，沒有碰別的
    （`geo.GEOCODE_INTERVAL_SECONDS` 與重設端點的每日節流**都不在射程內**）。

    ## 🔴 要驗節流的測試，**必須自己把它設回去**

    ```python
    monkeypatch.setattr(ts, "DETAIL_INTERVAL_SECONDS", 2)   # 要正數才驗得到
    ```
    📌 現在這樣做的是 `test_tender_detail_2026_09_21.py::test_d3_…`，
    而它是**唯一**守「對別人伺服器的禮貌」那個承諾的題。
    ⚠️ **看到這裡是 0 不要以為那個延遲不存在** —— 它在產品裡是 2 秒。

    ## 📌 為什麼預設是 0（方向反過來）

    ```
    預設 2 秒  ⇒ 每一個新寫的題都要記得 patch ⇒ **第七題一定會再發生**
    預設 0     ⇒ 新題自動快；**唯一需要正數的那一題自己宣告**
    ⇒ 要慢的人舉手，不是要快的人舉手
    ```
    🔑 實測（2026-09-22）：六題各 24~33 秒，`cProfile` 顯示
    **16 次 `time.sleep` × 2.000 秒 ＝ 32.005 秒，而其餘加起來不到 3 秒。**
    ☠️ 而同一個檔裡**早就有一題**寫了這個 patch（`:667`）——
    **修法一直存在，只是沒有被套到其他題上。**

    ## ⚙️ 這支 fixture 自己的兩側對照

    ```
    生效這一側   test_conftest_the_politeness_delay_is_zero_in_tests（本檔下方）
    設回去那一側 test_d3_interval_between_detail_fetches（它把常數設回正數）
    ```
    ☠️ **只有前者的話，這支 fixture 以後壞掉不會有人發現。**
    """
    try:
        from helpers import tender_source
    except Exception:       # noqa: BLE001 —— 匯入不了就不是這支 fixture 的事
        return
    monkeypatch.setattr(tender_source, "DETAIL_INTERVAL_SECONDS", 0,
                        raising=False)


@pytest.fixture(autouse=True)
def _guard_archive_isolation(tmp_path_factory):
    """🔴 BK19：每一題開始前，確保存檔根目錄不是真的雲端硬碟。

    ## 🔴 這道守門一裝上去就抓到一個真的洞

    第一版只**斷言**，結果它在自己的測試檔上立刻紅：
    `_archive_base()` 回 `G:\\我的雲端硬碟\\系統存檔`。
    ☠️ 成因：隔離寫在 **session 級的 `_app` fixture 裡**
    ⇒ **只有用到 `client`／`_app` 的測試才受保護**。
    任何一支「只 `import archive`」的測試，看到的是真的磁碟機掃描結果。

    🔑 而那正是 2026-08-30／08-31／09-03 的形狀：
    **不是隔離寫錯了，是隔離的覆蓋範圍比大家以為的小。**

    ## ⇒ 所以它不只檢查，它還**負責把隔離建立起來**

    📌 〈修作法不要修結果〉：只斷言的話，下一個寫新測試檔的人
    會看到一個紅燈、然後去加 `client` fixture —— **而那是修結果。**
    ⚠️ 已經隔離好的（`_app` 跑過了）**不動它**，避免踩到別人的設定。
    """
    import archive
    base = archive._archive_base()
    if not archive_path_is_isolated(base):
        fallback = tmp_path_factory.mktemp("archive_fallback")
        _ISOLATION_ROOTS.add(str(_Bk19Path(fallback).resolve()))
        archive._archive_base = lambda: str(fallback)
        base = archive._archive_base()
    assert archive_path_is_isolated(base), (
        f"存檔根目錄是 {base!r}，不在測試的 tmp 底下。 "
        "☠️ 測試會把資料寫進去，而那裡可能是使用者真的雲端硬碟 —— "
        "2026-08-30／08-31／09-03 三份空備份就是這樣來的。"
    )
    yield


@pytest.fixture(scope="session")
def _app(tmp_path_factory):
    """Import main.app exactly once per test session, with all startup-time
    file I/O redirected into a session-scoped tmp dir. DB *content* isolation
    between individual tests is handled separately by the `client` fixture
    below (which re-points db.DB_PATH/DEMO_DB_PATH per test) — this fixture
    only needs to get `import main` to complete without touching real files."""
    if "main" in sys.modules:
        pytest.fail(
            "main.py was already imported before the integration-test fixture "
            "could patch its file paths — some other test/module imported it "
            "too early, so this fixture can no longer guarantee it won't touch "
            "the real motrix_erp.db / backend/db_backups/. Fix the import order."
        )

    base = tmp_path_factory.mktemp("motrix_app")

    # 背景排程一律停掉（2026-09-14）。`import main` 是 module-level 執行，
    # 每個 xdist worker 都會在 import 當下立刻跑一次完整備份（整庫快照＋41 張表
    # JSON＋月備份＋鏡像＋清理）＋逾期檢查補跑——`-n auto` 在 12 執行緒機器上
    # 等於**同一次測試跑了 12 遍完整備份**。
    # 停掉之後不只快，也拆掉了 QUICK.md 記載的 e2e flaky 放大因子：
    # 「背景排程整個 session 都在寫 db，SQLite 寫鎖被佔住時最多會等 30 秒」。
    # 必須在 `import main` 之前設好（main.py 是在 import 時就讀這個變數）。
    #
    # 需要驗排程本身的測試不受影響——它們是 import 之後自己呼叫那些函式，
    # 停掉的只有「啟動時自動跑一次」。
    import os as _os
    _os.environ["MOTRIX_DISABLE_SCHEDULERS"] = "1"

    # Edge 並發上限在 xdist 底下要再除以 worker 數（2026-09-15）。
    #
    # `EDGE_PDF_SEMAPHORE` 是 **threading**.BoundedSemaphore——只管得住同一個
    # 行程裡的執行緒。正式機是單一 uvicorn 行程，那裡「同時最多 3 個 Edge」是
    # 成立的；但 pytest-xdist 是**多行程**，8 個 worker 各自持有一份自己的
    # semaphore，實際上限變成 8×3＝24 個 msedge.exe 同時搶 CPU。
    #
    # 2026-09-15 打包時 `test_export_excel_and_pdf` 就是這樣倒的
    # （`subprocess.TimeoutExpired`）——那一題單獨跑 6 秒就過。
    #
    # **刻意改測試而不是改產品**：跨行程的上限要靠檔案鎖或具名 mutex，那會為了
    # 一個正式機根本不存在的情境（單行程）引進「行程被砍掉、鎖沒釋放」的新失敗
    # 模式。這裡把每個 worker 壓到 1，總量回到跟 worker 數同一個量級。
    if _os.environ.get("PYTEST_XDIST_WORKER"):
        import threading as _threading
        import helpers.startup as _startup
        _startup.EDGE_PDF_SEMAPHORE = _threading.BoundedSemaphore(1)

    import db
    db.DB_PATH = str(base / "motrix_erp.db")
    db.DEMO_DB_PATH = str(base / "motrix_erp_demo.db")

    import archive
    archive.DB_PATH = db.DB_PATH  # archive.py imported DB_PATH by value — repoint it too
    # 2026-09-07 修正：這裡曾經 patch archive._ARCHIVE_BASE/_REALTIME_DIR/_WEEKLY_DIR/
    # _DAILY_DIR/_UPLOADS_MIRROR_DIR 這五個大寫常數，但現在的 archive.py 早就沒有
    # 這些常數了（改成 _archive_base()/_realtime_dir() 等會動態掃描磁碟機代號的
    # 函式，見架構地圖 §6.4／2026-09-07 雲端備份可插拔重構）——這幾行 patch 對現在
    # 的程式碼完全是死碼，什麼都沒隔離到。實際驗證發現：任何透過 API 建立/更新
    # 報價單／客戶／供應商的測試都會 spawn_bg_thread 呼叫 _backup_quotation() 等
    # 背景函式，這些函式呼叫的 _archive_base() 完全不受這裡的 patch 影響，會做
    # 真正的磁碟機代號掃描——在這台開發機上（G: 剛好掛載著真實的公司雲端硬碟）
    # 這代表測試產生的假資料曾經真的寫進 G:\我的雲端硬碟\系統存檔\即時備份\ 底下
    # （已在 G: 找到多筆 MQ-TEST-*/MQ-MARKPAY-* 等測試專用假單號的殘留 JSON，
    # 應該是不同時期的測試留下的）。改成直接 patch `_archive_base` 這個函式本身，
    # 讓所有依賴它的 _realtime_dir()/_weekly_dir()/_daily_dir()/_uploads_mirror_dir()/
    # _pdf_mirror_dir() 全部自動跟著隔離，不用每個都個別 patch，也不會再重蹈
    #「archive.py 內部改了實作方式、conftest.py 沒跟著更新」的同一種錯誤。
    # 「這台機器不上傳雲端」的標記（2026-09-15，archive.cloud_archive_enabled）是
    # 專案根目錄下一個**真實存在**的檔案——開發機上它就是存在的。測試必須看不到它，
    # 否則整批雲端備份測試會因為「這台機器的政策」而紅，而不是因為程式碼壞了；
    # 而且那種紅燈會讓人以為備份功能壞掉。
    #
    # 指到 tmp 裡一個不存在的路徑 → 測試環境預設「允許上傳」（維持既有測試的前提）。
    # 要驗「停用」那條路徑的測試自己在這個路徑建檔案、或設環境變數（見
    # test_cloud_archive_policy_2026_09_15.py）。環境變數也一併清掉：它的優先序在
    # 檔案之前，從開發者的 shell 漏進來會讓整批測試莫名其妙地紅。
    _os.environ.pop("MOTRIX_CLOUD_ARCHIVE", None)
    archive._NO_CLOUD_MARKER_PATH = str(base / "no_cloud_archive_marker")

    archive_base = base / "archive_base"
    archive_base.mkdir()
    archive._archive_base = lambda: str(archive_base)
    # 🔴 BK19：把「這一刻的 tmp 根目錄」記下來，給下面那道 autouse 守門用。
    _ISOLATION_ROOTS.add(str(_Bk19Path(base).resolve()))
    archive._LOCAL_DB_BACKUP = str(base / "db_backups")
    archive._ALERT_DIR = str(base / "backup_alerts")
    archive._UPLOADS_DIR = str(base / "uploads")  # empty — don't let tests read the real uploads/

    # PDF 存檔目錄：**session 級**的安全網，跟下面 client fixture 那份 per-test
    # patch 是兩件事，兩個都要。
    #
    # 為什麼 per-test 不夠（2026-09-15 實測）：結案報表等 PDF 是
    # `spawn_bg_thread(_generate_case_closing_pdf, ...)` 在背景產生的
    # （routers/quotations.py），Edge headless 渲染要好幾秒，寫檔時那一題早就結束、
    # monkeypatch 也已經還原——於是那條執行緒讀到的又是專案裡的真實存檔路徑。
    # 症狀就是 `結案報表PDF/` 裡一直多出 `MQ-CLOSE-004_..._tester_N.pdf`。
    # 這裡用直接賦值（不是 monkeypatch）：整個 session 都不會被還原掉，晚到的
    # 執行緒也只會落在暫存區。
    pdf_base = base / "pdf_archive"
    pdf_base.mkdir()
    import pdf_gen
    for _const, _sub in (
        ("_PDF_BASE_DEFAULT", "報價單PDF"),
        ("_SHIPPING_PDF_BASE_DEFAULT", "出貨單PDF"),
        ("_CONTRACTOR_VOUCHER_PDF_BASE_DEFAULT", "承攬商匯款申請PDF"),
        ("_INVOICE_VOUCHER_PDF_BASE_DEFAULT", "開票申請憑據PDF"),
        ("_PAYMENT_REQUEST_PDF_BASE_DEFAULT", "請款單PDF"),
        ("_CASE_CLOSING_PDF_BASE_DEFAULT", "結案報表PDF"),
        ("DEMO_PDF_ARCHIVE_DIR", "demo_報價單PDF"),
        ("DEMO_SHIPPING_PDF_ARCHIVE_DIR", "demo_出貨單PDF"),
        ("DEMO_CONTRACTOR_VOUCHER_PDF_ARCHIVE_DIR", "demo_承攬商匯款申請PDF"),
        ("DEMO_INVOICE_VOUCHER_PDF_ARCHIVE_DIR", "demo_開票申請憑據PDF"),
        ("DEMO_PAYMENT_REQUEST_PDF_ARCHIVE_DIR", "demo_請款單PDF"),
        ("DEMO_CASE_CLOSING_PDF_ARCHIVE_DIR", "demo_結案報表PDF"),
    ):
        setattr(pdf_gen, _const, str(pdf_base / _sub))

    main = importlib.import_module("main")  # runs the real startup sequence now, isolated
    _install_edge_profile_pool(base)
    return main.app


def _install_edge_profile_pool(base):
    """測試時 Edge 產 PDF 重用固定的 profile 目錄（PLAN-TEST-PERF §5.3 方案 A，只改測試端）。

    ☠️ 產品每次 `msedge --headless --print-to-pdf` 都建一份新 profile：抽樣 msedge 寫入 374 MB，
       PDF 檔本身只有 3.5 MB。
    🔑 產品碼不動（它沒有 `--user-data-dir`，由 test_edge_profile_2026_09_25 守著）；這裡包一層：
       - 每個 worker 準備 EDGE_PDF_MAX_CONCURRENCY 份 profile（產品並發上限；單程序跑時真的會同時開 3 個 Edge，
         **同一份 profile 同時被兩個 Edge 用會被鎖**），用佇列發放，一次一個 Edge 用一份；
       - 上一個 Edge 逾時被殺、子行程還佔著 profile（`lockfile` 刪不掉）⇒ 換一份新的，
         否則新的 msedge 會把工作交給殘留的那個而不產出 PDF。
    ⚠️ 呼叫端是 `from helpers import run_edge_pdf`（依值綁定）⇒ 每個綁到它的名字都要換。
       第一版寫死 5 處，漏了 `routers/reports.py`（test_pdf_concurrency 抓到）⇒ 改成掃 sys.modules，
       凡是指向原函式的一律換掉，之後新增的呼叫處也不會漏。
    ⚠️ `MOTRIX_TEST_EDGE_FRESH_PROFILE=1` ⇒ 不裝（A/B 對照用）。
    """
    if os.environ.get("MOTRIX_TEST_EDGE_FRESH_PROFILE") == "1":
        return
    import queue
    import helpers.startup as startup

    original = startup.run_edge_pdf
    root = base / "edge_profiles"
    root.mkdir()
    pool = queue.Queue()
    serial = [0]

    def _new_dir():
        serial[0] += 1
        d = root / ("p%d" % serial[0])
        d.mkdir()
        return d

    for _ in range(max(1, int(getattr(startup, "EDGE_PDF_MAX_CONCURRENCY", 3)))):
        pool.put(_new_dir())

    def run_edge_pdf_with_profile(cmd):
        if any(str(a).startswith("--user-data-dir") for a in cmd):
            return original(cmd)
        d = pool.get()
        try:
            lock = d / "lockfile"
            try:
                if lock.exists():
                    lock.unlink()
            except OSError:
                d = _new_dir()              # 殘留的 Edge 還佔著 ⇒ 換一份
            return original([cmd[0], "--user-data-dir=%s" % d] + list(cmd[1:]))
        finally:
            pool.put(d)

    run_edge_pdf_with_profile.__wrapped__ = original
    for mod in list(sys.modules.values()):
        try:
            if getattr(mod, "run_edge_pdf", None) is original:
                setattr(mod, "run_edge_pdf", run_edge_pdf_with_profile)
        except Exception:  # noqa: BLE001 — 某些模組物件不讓讀／寫屬性，略過不影響其他
            continue


@pytest.fixture(scope="session")
def _template_db(_app, tmp_path_factory):
    """每個 session（每個 xdist worker）用**同一支 `db.init_db`** 建一份已遷移好的範本庫，
    `client` 每題從它複製，不再每題重跑 116 個 migration。

    📌 2026-09-25（PLAN-TEST-PERF §5.1，使用者選定）：每題建兩個庫 ＝ 中位數 0.55 s、
       寫入約 12 MB；2,315 題 ⇒ 每輪約 1,000 秒 CPU、27 GB 寫入。複製檔案 2 ms、1.19 MB。
    🔑 migration 仍然**每輪真的跑一次**（就在這裡），只是不再每題重跑同一件事。
       範本與新鮮 init_db 的等價由 test_template_db_2026_09_25 守著。
    ⚠️ 設 `MOTRIX_TEST_FRESH_DB=1` ⇒ 回到每題 init_db（A/B 對照用）。
    """
    import db
    import sqlite3

    path = str(tmp_path_factory.mktemp("template_db") / "template.db")
    db.init_db(path)
    # 把 WAL 併回主檔，複製主檔就是完整的庫（WAL 模式記在檔頭，複製後照樣以 WAL 開啟）
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    wal = path + "-wal"
    assert not (os.path.exists(wal) and os.path.getsize(wal) > 0), "範本庫的 WAL 沒有併回主檔"
    return path


@pytest.fixture()
def client(_app, _template_db, tmp_path, monkeypatch):
    """Function-scoped: every test gets its own fresh, empty, fully-migrated
    real+demo DB pair, so tests can't see each other's data.

    每題仍是**自己的一份新庫檔**、仍 monkeypatch `db.DB_PATH`／`DEMO_DB_PATH`
    （共用伺服器的 e2e 依賴這個介面：伺服器在 request 當下才讀 DB_PATH）；
    差別只在庫檔是從 `_template_db` 複製來的，不是每題重跑 init_db。"""
    import db
    import helpers
    import shutil

    real_path = str(tmp_path / "motrix_erp.db")
    demo_path = str(tmp_path / "motrix_erp_demo.db")

    # ☠️ 順序：**先把庫放好，再把 DB_PATH 指過去。**
    #    前一題的背景執行緒（例：結案後 spawn_bg_thread 產 PDF）在那一題結束後仍在跑，
    #    它每次 get_db() 都讀「當下的」db.DB_PATH。若先 setattr 再複製，中間那一瞬間
    #    它會在新路徑上建出一個空庫＋WAL；複製過來的主檔會被那份 WAL 蓋掉 ⇒ 本題
    #    `no such table: users`（2026-09-25 抽樣實際發生 2 次）。
    #    舊寫法（每題 init_db）也有同一個空窗，只是 init_db 會在那條連線之上把表建完而看不出來。
    if os.environ.get("MOTRIX_TEST_FRESH_DB") == "1":
        db.init_db(real_path)
        db.init_db(demo_path)
    else:
        shutil.copyfile(_template_db, real_path)
        shutil.copyfile(_template_db, demo_path)
    monkeypatch.setattr(db, "DB_PATH", real_path)
    monkeypatch.setattr(db, "DEMO_DB_PATH", demo_path)
    # `IA2`：`init_demo_account()` 現在靠 `demo_account_on()` 把關
    # （預設關，同 `helpers/tender_source.py::radar_on()` 的理由），
    # 測試環境要明著打開，同既有 `monkeypatch.setattr(ts,
    # "TENDER_RADAR_ENABLED", True)` 的用法——這不是產品碼要改，
    # 是測試環境的開關沒有跟著 IA2 一起打開。
    import helpers.startup as startup_helper
    monkeypatch.setattr(startup_helper, "DEMO_ACCOUNT_ENABLED", True)
    helpers.init_demo_account()  # seed the real-DB 'demo' gatekeeper row (see db.py comments)

    # helpers/uploads.py (signed-file attachments for quotations/shipping_notes/
    # invoice_vouchers) computes its own UPLOADS_ROOT independent of archive.py's
    # _UPLOADS_DIR — redirect it too, or tests would write real files into the
    # actual repo uploads/ directory (confirmed happening before this patch was
    # added: test PNGs landed in uploads/quotations/MQ-SIGN-001/ etc. on disk).
    import helpers.uploads as uploads_helper
    monkeypatch.setattr(uploads_helper, "UPLOADS_ROOT", str(tmp_path / "uploads"))

    # routers/uploads.py 算的是**第三份**獨立的 UPLOADS_ROOT（存檔在
    # helpers/uploads.py，讀檔在這裡）。2026-09-15 補上這一行之前只 patch 了
    # 存檔那邊，於是「寫進 tmp、讀真實 uploads/」——任何「傳完之後真的讀得
    # 回來嗎」的測試都必定 404，也就沒有人寫得出來。附件從上線起每一張都
    # 403（前端把 session token 當成 `pt` 送）能躲過整套測試，這個缺口是原因
    # 之一：讀取路徑在測試裡根本沒有被走過。
    import routers.uploads as uploads_router
    monkeypatch.setattr(uploads_router, "UPLOADS_ROOT", str(tmp_path / "uploads"))

    # photos.py computes its own project-photo storage roots independent of
    # archive.py/uploads_helper above too (used by projects.py's project-log
    # photos and, since 2026-08-26, system.py's work-log photos) — redirect
    # both the real and demo variants or tests would write into the actual
    # repo uploads/projects//_demo_projects/.
    import photos
    monkeypatch.setattr(photos, "_PHOTO_UPLOAD_BASE", str(tmp_path / "uploads" / "projects"))
    monkeypatch.setattr(db, "DEMO_PROJECT_PHOTOS_DIR", str(tmp_path / "uploads" / "_demo_projects"))

    # reports.py::_check_export_rate() keys its process-global cooldown dict by
    # (user_id, fmt) — user_id is a fresh DB's autoincrement value, so it gets
    # *recycled* across tests (each test starts a brand-new empty DB). Without
    # resetting this dict per test, a test in this file that calls an excel/pdf
    # export endpoint can spuriously 429 because some earlier, unrelated test's
    # user happened to land on the same recycled user_id within the last 5/30
    # seconds of wall-clock time (confirmed flaky failure 2026-09-01, only ever
    # reproduces in a full-suite run, never in isolation — see MOTRIX-ERP-QUICK.md
    # §12 2026-09-01 entries for the feature that surfaced it).
    import routers.reports as reports_module
    monkeypatch.setattr(reports_module, "_export_times", {})

    # routers/auth.py::_rl_state 是**同一個形狀的第二個** process-global dict，
    # 以「用戶端 IP」為鍵。而 TestClient 的預設來源是 `"testclient"` ——
    # 全套測試共用同一個鍵 ⇒ 任何一支測試在這個 worker 裡累積 5 次登入失敗，
    # 之後**所有人的登入都被鎖 900 秒**。
    #
    # 失敗的樣子是 `KeyError: 'token'`（登入回 429 而呼叫端直接
    # `.json()["token"]`），而它**單獨跑永遠是綠的、只在全量跑才紅**，
    # 紅的理由跟那一題要驗的事完全無關。2026-09-22 實測重現：對
    # `_rl_fail("testclient", …)` 呼叫六次，就能讓一個乾淨的檔案紅兩題。
    #
    # 在這一行之前，repo 的做法是「每支會失敗登入的測試自己挑一個
    # X-Forwarded-For 假 IP」（test_api_integration.py:127、
    # test_totp_2026_09_07.py:111、test_totp_qr_push_2026_09_08.py 都有）——
    # 那是**要求每個人記得**，而漏掉的那一支不會報錯，只會讓別人紅。
    # 那些假 IP 的宣告一個都不用拿掉：它們現在是第二道防線，而不是唯一那道。
    import routers.auth as auth_module
    monkeypatch.setattr(auth_module, "_rl_state", {})

    # pdf_gen.py 的 6 類 PDF 存檔目錄（報價單／出貨單／承攬商匯款申請／開票申請
    # 憑據／請款單／結案報表）各自算自己的路徑，跟上面 uploads/photos 一樣**不受
    # 任何既有 patch 影響**——這是 2026-09-07 那批隔離修正唯一漏掉的一個。
    #
    # 2026-09-15 查出來的後果有三層：
    #   ① 測試真的把 PDF 寫進專案根目錄的真實存檔：`報價單PDF` 1,181 檔裡有 136 個
    #      `MQ-TEST-*`／`MQ-CLOSE-004`／`_tester` 的測試產物，最早 2026-08-26；
    #      `結案報表PDF` 136 檔裡有 53 個。
    #   ② 那些測試檔接著被每日備份鏡像到**公司雲端存檔**（G: 的 PDF存檔鏡像 864 檔
    #      裡有 120 個測試檔，橫跨 5 個類別）——測試垃圾進了正式憑據的備份。
    #   ③ 每跑一次測試，`archive._mirror_pdf_archives()` 都會把那 1,617 個**真實**
    #      PDF 複製進該次的測試暫存（每個 xdist worker 一份），一次完整測試 3.5 GB
    #      ——這是 `%TEMP%` 累積到 136 GB 的主因。
    #
    # patch 模組常數而不是 getter：有幾題自己會 monkeypatch getter
    # （test_pdf_archive_mirror_2026_09_07.py），改常數不會跟它們互相打到。
    # demo 那組常數是 `from db import ...` **by value** 綁進 pdf_gen 的，所以要
    # patch `pdf_gen` 上的名字，patch `db` 上的沒有用（同 conftest 開頭的說明）。
    import pdf_gen
    _pdf_dirs = {
        "_PDF_BASE_DEFAULT":                          "報價單PDF",
        "_SHIPPING_PDF_BASE_DEFAULT":                 "出貨單PDF",
        "_CONTRACTOR_VOUCHER_PDF_BASE_DEFAULT":       "承攬商匯款申請PDF",
        "_INVOICE_VOUCHER_PDF_BASE_DEFAULT":          "開票申請憑據PDF",
        "_PAYMENT_REQUEST_PDF_BASE_DEFAULT":          "請款單PDF",
        "_CASE_CLOSING_PDF_BASE_DEFAULT":             "結案報表PDF",
        "DEMO_PDF_ARCHIVE_DIR":                       "demo_報價單PDF",
        "DEMO_SHIPPING_PDF_ARCHIVE_DIR":              "demo_出貨單PDF",
        "DEMO_CONTRACTOR_VOUCHER_PDF_ARCHIVE_DIR":    "demo_承攬商匯款申請PDF",
        "DEMO_INVOICE_VOUCHER_PDF_ARCHIVE_DIR":       "demo_開票申請憑據PDF",
        "DEMO_PAYMENT_REQUEST_PDF_ARCHIVE_DIR":       "demo_請款單PDF",
        "DEMO_CASE_CLOSING_PDF_ARCHIVE_DIR":          "demo_結案報表PDF",
    }
    for _const, _sub in _pdf_dirs.items():
        monkeypatch.setattr(pdf_gen, _const, str(tmp_path / "pdf_archive" / _sub))

    import threading
    threads_before = set(threading.enumerate())

    from fastapi.testclient import TestClient
    yield TestClient(_app)

    # ☠️ 背景執行緒隔離（test_bg_thread_isolation_2026_09_25）：產品的背景工作（產 PDF、寄信…）在題目結束後
    #    仍在跑，它每次 get_db() 讀「當下的」db.DB_PATH ⇒ 下一題換了庫之後就寫進下一題的庫。
    #    ⇒ 收尾時（monkeypatch 還原 DB_PATH 之前——client 依賴 monkeypatch，所以先收 client）等這一題
    #    起的、**我們自己程式碼的**背景執行緒結束。第三方函式庫的長壽執行緒不等（否則每題白等到上限）。
    _join_own_background_threads(threads_before)


_BACKEND_DIR = str(_Bk19Path(__file__).resolve().parents[1])
BG_JOIN_BUDGET_SECONDS = 30


def _is_own_background_thread(t) -> bool:
    import contextvars
    target = getattr(t, "_target", None)
    if target is None:
        return False
    owner = getattr(target, "__self__", None)
    if isinstance(owner, contextvars.Context):
        return True                          # db.spawn_bg_thread（以 ctx.run 起）
    mod = sys.modules.get(getattr(target, "__module__", "") or "")
    f = getattr(mod, "__file__", "") or ""
    return f.startswith(_BACKEND_DIR) and "tests" not in _Bk19Path(f).parts   # 產品碼直接 threading.Thread 起的


def _join_own_background_threads(threads_before):
    import threading
    deadline = time.time() + BG_JOIN_BUDGET_SECONDS
    for t in threading.enumerate():
        if t in threads_before or t is threading.current_thread() or not _is_own_background_thread(t):
            continue
        t.join(max(0.0, deadline - time.time()))
        if t.is_alive():
            _lock_say("\n[背景執行緒] %s 在 %d 秒內沒有結束 —— 它之後的寫入可能落到下一題的庫"
                      % (t.name, BG_JOIN_BUDGET_SECONDS))


@pytest.fixture()
def isolated_archive(client, tmp_path, monkeypatch):
    """每一題自己一個全新的雲端存檔根目錄，回傳該路徑（str）。

    **為什麼需要這個**：`_app` fixture 建的 archive_base 是 **session 級**的，
    整個 test session 共用一份。`client` fixture 只換 DB，不換存檔目錄——
    所以上一題跑完 `_daily_backup()` 留下的 `每日備份/{today}/.done`、
    `月備份/{YYYY-MM}/.done` 會原封不動留給下一題，讓下一題的備份直接早退，
    斷言看到的是**別題造成的狀態**。2026-09-14 寫月備份測試時就先踩到：
    「月備份失敗不寫 .done」那題紅在前一題留下的 marker 上，跟受測邏輯無關。

    只有真的會寫進存檔目錄的測試需要用它；一般 API 測試不必，維持原本的
    session 共用即可（那些測試根本不碰這個目錄）。
    """
    import archive
    base = tmp_path / "archive_base_isolated"
    base.mkdir()
    monkeypatch.setattr(archive, "_archive_base", lambda: str(base))
    monkeypatch.setattr(archive, "_LOCAL_DB_BACKUP", str(tmp_path / "db_backups_isolated"))
    # 存檔所有權判定有 300 秒 TTL 快取（archive._archive_owner_ok()）。換了存檔
    # 根目錄就一定要讓舊判定失效，否則上一題留下的結論會直接套用到這一題——
    # 2026-09-14 實測：所有權測試把快取設成 False 之後，同一個 xdist worker 裡
    # 接著跑的月備份測試全部被那個 False 擋掉（序列執行時剛好沒撞到，只有平行
    # 執行才紅，是最難查的那種）。
    monkeypatch.setitem(archive._owner_cache, "base", None)
    monkeypatch.setitem(archive._owner_cache, "ok", None)
    monkeypatch.setitem(archive._owner_cache, "checked_at", 0.0)
    monkeypatch.setitem(archive._owner_cache, "reason", "")
    return str(base)


# 角色預設模組——對應 frontend/pages/users.html 的 ROLE_MODULES，
# 再加上 2026-09-14 新建的幾個 key（見下方 _make 的說明）。
_ROLE_DEFAULT_MODULES = {
    "superadmin": [],          # superadmin 直通，給不給都一樣
    "admin": [
        "dashboard", "quotation", "case_manage", "customer", "procurement",
        "inventory", "equipment", "finance", "reports", "project_approve_eng",
        "project_approve_biz", "financial_view", "work_log", "daily_task",
        "env_guide", "netarch_guide", "switch_guide", "monitor_guide",
        "access_guide", "gateway_guide", "automation_guide", "cashier",
        "netplan", "audit_log", "shipping_export_log", "module_versions",
        "selection_overview",
    ],
    "sales": [
        "dashboard", "quotation", "case_manage", "customer", "financial_view",
        "project_approve_biz", "work_log", "daily_task",
    ],
    "engineer": [
        "dashboard", "case_manage", "project_approve_eng", "equipment",
        "work_log", "daily_task", "netplan",
    ],
    "viewer": ["dashboard"],
}


@pytest.fixture()
def make_user():
    """Insert a user directly into the (already-isolated) real DB and return
    (username, password, token-fetching helper info) — avoids depending on
    init_default_admin()'s random-password-to-file flow for tests."""
    import db
    from helpers.auth import _hash_pw

    def _make(username="tester", password="Test-Pass-123", role="admin", modules=None):
        """`modules=None`（不指定）→ 用該角色的預設模組樣板。

        2026-09-14 改的：在此之前預設是**空陣列**，而當時 `require_any_module()`
        讓 admin 直通，所以「admin 測試帳號一個模組都沒有」完全看不出問題。
        取消直通之後這個預設立刻讓 31 題變紅——但那不是產品壞了，是**測試帳號
        一直都不像真實帳號**：正式機的 admin 都持有完整的角色樣板。

        這正是 MODULE-AUDIT §5 記的那件事：「模組檢查最危險的失敗模式是擋錯人，
        而後端測試全綠，因為測試多半用 admin 帳號、admin 直通」。那層遮蔽現在
        沒了，所以測試帳號必須拿真實的模組清單。

        要驗「沒有模組會被擋」的測試請**明確傳 `modules=[]`**——空陣列不是 None，
        不會被樣板取代。
        """
        import json
        if modules is None:
            modules = _ROLE_DEFAULT_MODULES.get(role, [])
        conn = db.get_db()
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name, role, modules, "
                "active, created_at, must_change_password) VALUES (?,?,?,?,?,1,?,0)",
                (username, _hash_pw(password), username, role,
                 json.dumps(modules), "2026-01-01T00:00:00"),
            )
            conn.commit()
        finally:
            conn.close()
        return username, password

    return _make


@pytest.fixture()
def seed_extra_expense():
    """直接在 `case_extra_expenses` 表種一筆額外支出（2026-09-11，migration v75 之後）。

    在那之前額外支出是存在 `quotations.data_json` 的 `settlement.extraItems[]` 裡，
    所以舊測試都是「組一包 settlement 塞進 data_json」。資料搬到獨立表之後那個做法
    種出來的東西報表讀不到——不是測試壞了，是資料的家換了。這個 fixture 讓所有
    相關測試走同一條路徑，不必各自拼 INSERT。

    `status` 預設「已核准」：多數測試關心的是金額有沒有被算進報表，而不是簽核流程；
    要測「送審中也要照樣計入成本、但標記 pending」時才明確傳其他狀態。
    """
    import db

    def _seed(quote_no, *, total_cost=0, category="其他", description="",
              expense_date="", created_at="", doc_no="", files=None,
              status="已核准", created_by_name="", payer_name="", qty=1, unit="", unit_cost=0):
        import json as _json
        conn = db.get_db()
        try:
            cur = conn.execute(
                "INSERT INTO case_extra_expenses "
                "(quote_no, category, description, qty, unit, unit_cost, total_cost, "
                " expense_date, doc_no, files_json, created_by_name, payer_name, "
                " created_at, updated_at, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (quote_no, category, description, qty, unit, unit_cost, total_cost,
                 expense_date, doc_no, _json.dumps(files or [], ensure_ascii=False),
                 created_by_name, payer_name, created_at or expense_date,
                 created_at or expense_date, status),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    return _seed


# ══════════════════════════════════════════════════════════════════════════
# 守門：`--basetemp` 與「全量回歸互斥」（協定 §5-3／§5-5）
#
# 🔑 **這兩條規則早就寫在 `MULTIWIN-PROTOCOL.md:226-243` 與 §5-5 裡，而今天
#    兩個視窗各踩了一次。** ⇒ 結論不是「再寫一次規則」，是**規則沒有到達**。
#    文件擋不住「順手跑一下」，因為那不是一個會被當成決策的時刻。
#
# ⚠️ 兩條規則防的是**不同**的失敗，理由不可以互相代用：
#   `--basetemp`   防**檔案**互刪 —— 跟機器忙不忙**完全無關**，
#                  閒著的時候一樣會刪（我當初就是這樣推錯邊界的）。
#   全量回歸互斥   防**CPU** 競爭 —— 這一條才是「機器閒著就還好」。
#   🔑 **規則決定做什麼，理由決定什麼時候適用。理由寫錯＝邊界錯，
#      而規則本身看起來完全沒問題。**
# ══════════════════════════════════════════════════════════════════════════

import ctypes
import json
import os
import tempfile
import time
from pathlib import Path

#: basetemp 的名字以這個結尾 ⇒ 視為「全量回歸」，要搶鎖。
FULL_REGRESSION_SUFFIX = "-full"

#: 鎖多久之後一律視為過期。全量回歸實測 23~24 分鐘，這裡給 2.5 倍餘裕。
LOCK_MAX_AGE_SECONDS = 60 * 60

_STILL_ACTIVE = 259          # Windows GetExitCodeProcess 的「還在跑」
_ERROR_ACCESS_DENIED = 5

_lock_taken_by_me = False

#: 🔴 2026-09-24 使用者裁示「全機同時只准一套」：搶不到鎖改成**排隊等**，不是直接擋下。
#: 🔄 同日更正：使用者「開放兩個同時跑」⇒ 預設 2 格（見 `_lock_slots()`），第三套才排隊。
#:    多視窗同時各跑全量／平行 e2e ⇒ 12 核滿載、靠時序的題偶發紅，而紅的樣子跟真 bug 一樣。
#: 等多久（秒）；0＝不等、立刻擋下（守門題用，保留「被擋」的語意可測）。
LOCK_WAIT_SECONDS_DEFAULT = 90 * 60
#: 多久重試一次（秒）。
LOCK_POLL_SECONDS_DEFAULT = 10


def _env_seconds(name, default):
    try:
        return max(0.0, float(os.environ.get(name, default)))
    except ValueError:
        return float(default)


def _is_heavy_run(config) -> bool:
    """要搶全機鎖的：全量回歸（basetemp 以 -full 結尾），或任何用 xdist 平行（-n ≥ 2）的一輪。

    ⚠️ 單檔、不平行的臨時跑**不搶**：它輕，而且擋它會讓人開始刪鎖檔（見 T5）。
    """
    if str(config.option.basetemp).rstrip("\\/").endswith(FULL_REGRESSION_SUFFIX):
        return True
    if os.environ.get("MOTRIX_PYTEST_EXCLUSIVE") == "1":
        return True                  # 建包獨佔：e2e 段序列、名稱也不叫 -full，照樣要佔滿（§3.3）
    n = getattr(config.option, "numprocesses", None)
    try:
        return n is not None and (n == "auto" or n == "logical" or int(n) >= 2)
    except (TypeError, ValueError):
        return False


def _lock_path() -> Path:
    """鎖檔位置。**環境變數只是測試用的接縫**，不是給人繞過用的。

    ⚠️ 這道守門防的是「順手跑一下」，不是防惡意 —— 有人下定決心要繞過它，
    他也可以直接刪掉鎖檔。**把它做成防不住的樣子是對的**，做成防得住的樣子
    會讓下一個人以為它保證了互斥。
    """
    override = os.environ.get("MOTRIX_PYTEST_LOCK")
    if override:
        return Path(override)
    return Path(tempfile.gettempdir()) / "motrix-pytest-full-regression.lock"


def _lock_slots() -> list:
    """全機同時可跑幾套重型測試（2026-09-24 使用者：「開放兩個同時跑」）。

    第 1 格沿用原本的鎖檔名（舊版 conftest 只認得它，新舊之間仍互相擋得住），
    第 2 格起是 `<鎖檔>.slot2`…。格數由 `MOTRIX_PYTEST_SLOTS` 決定，預設 2；
    守門題以 1 格驗「被擋／排隊」語意，另有一題驗 2 格。
    """
    try:
        n = max(1, int(os.environ.get("MOTRIX_PYTEST_SLOTS", "2")))
    except ValueError:
        n = 2
    base = _lock_path()
    return [base] + [base.with_name(base.name + ".slot%d" % i) for i in range(2, n + 1)]


def _pid_alive(pid: int) -> bool:
    """這個 pid 現在還在跑嗎。

    ## ⚠️ 為什麼不用 `os.kill(pid, 0)`（Windows）

    我**實測過兩次**（2026-09-21，Python 3.11 / Windows 11）：
    `os.kill(pid, 0)` **沒有**殺掉目標，等 5 秒、再用 `tasklist` 獨立確認都還在。
    也就是說「它會殺掉行程」那個常見說法在這裡是**錯的**。

    **但我仍然不用它**，理由不是它危險，是**猜錯的代價不對稱**：
    CPython 在 Windows 走的是 `OpenProcess(PROCESS_ALL_ACCESS)` ＋ `TerminateProcess`，
    而我只在**一個** Python 版本上試過。猜錯的後果是**殺掉別人跑到一半的
    24 分鐘全量回歸**，那個代價不值得拿「我試過一次沒事」去換。
    ⇒ 改用**唯讀**的 `PROCESS_QUERY_LIMITED_INFORMATION`：它沒有任何一個版本會殺人。

    ## ⚠️ 光看 `OpenProcess` 成不成功是不夠的

    我第一次測的時候被自己誤導：`subprocess.Popen` 物件**還握著 handle**，
    行程已經結束了，`OpenProcess` 照樣成功 ⇒ 判成「還活著」。
    🔑 **「查得到」與「還活著」是兩件事** ⇒ 所以要再問一次結束碼。

    ## 殘留風險（誠實標註，兩個都靠 `LOCK_MAX_AGE_SECONDS` 兜底）

    1. **pid 會被重用** —— 一個無關的新行程剛好拿到同一個號碼 ⇒ 誤判成還活著。
    2. 行程若真的以 **259** 這個結束碼退出，會被誤判成 `STILL_ACTIVE`。
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)   # QUERY_LIMITED_INFORMATION
        if not handle:
            # 存在但我們沒權限查 ⇒ 仍然算活著（寧可誤擋，不要誤放）
            return kernel32.GetLastError() == _ERROR_ACCESS_DENIED
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return code.value == _STILL_ACTIVE
            return True
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_lock(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def pytest_configure(config):
    """在**任何一支測試跑起來之前**擋下來。

    ⚠️ 擋在這裡而不是擋在 fixture 裡，是因為 fixture 只在有測試用到它時才跑，
    而傷害（刪掉別人的 basetemp）發生在**第一支用到 `tmp_path` 的測試**——
    那時候已經來不及了。
    """
    global _lock_taken_by_me
    # e2e 逐題上限（檔尾那一段）：主控在 worker 起來之前寫好本次執行的目錄 id，worker 繼承同一個值
    if not hasattr(config, "workerinput"):
        import uuid as _uuid
        os.environ["MOTRIX_E2E_HARDCAP_RUN"] = _uuid.uuid4().hex[:12]

    basetemp = config.option.basetemp
    if basetemp is None:
        raise pytest.UsageError(
            "這個 repo 的 pytest 一律要帶 --basetemp（協定 §5-3）。\n"
            "  全量回歸    --basetemp=%s\\motrix-pytest-<視窗>-full\n"
            "  臨時單檔跑  --basetemp=%s\\motrix-pytest-<視窗>-adhoc\n"
            "⚠️ 不帶的話會共用 %s\\pytest-of-<user>\\pytest-current，"
            "而 pytest 會把它整個刪掉重建 —— **另一個視窗跑到一半的資料庫會在腳下消失**，"
            "錯誤訊息則指向一支完全無關的測試（2026-09-21 兩個視窗各踩一次）。"
            % (tempfile.gettempdir(), tempfile.gettempdir(), tempfile.gettempdir())
        )

    # xdist 的 worker 也會跑到這裡：鎖只由主行程持有
    if hasattr(config, "workerinput"):
        return
    if not _is_heavy_run(config):
        return                       # 單檔臨時跑，不搶鎖

    slots = _lock_slots()
    wait = _env_seconds("MOTRIX_PYTEST_LOCK_WAIT", LOCK_WAIT_SECONDS_DEFAULT)
    poll = _env_seconds("MOTRIX_PYTEST_LOCK_POLL", LOCK_POLL_SECONDS_DEFAULT) or 1.0
    deadline = time.time() + wait
    announced = 0.0
    try:
        slots[0].parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    # 建包獨佔（PLAN-TEST-PERF §3.3）：登記檔讓之後進來的一般測試不再佔新格子，等目前持有者跑完後一次佔滿。
    exclusive = os.environ.get("MOTRIX_PYTEST_EXCLUSIVE") == "1"
    intent = slots[0].with_name(slots[0].name + ".exclusive")
    mine = []
    while True:
        try:
            ok, held, path, why = _lock_attempt(slots, intent, exclusive, basetemp, mine)
        except OSError as exc:            # 寫不進去不該擋住測試
            _lock_say("\n[測試鎖] 寫不進鎖檔（%s）—— 這一輪沒有鎖" % exc)
            for p in mine:
                _unlink_if_mine(p)
            return
        if ok:
            _lock_taken_by_me = mine
            return
        held = held or {}
        try:
            age = time.time() - float(held.get("started_at", 0))
        except (TypeError, ValueError):
            age = 0.0
        now = time.time()
        if now >= deadline:
            for p in mine:                # 沒輪到就把已經佔的（含獨佔登記）全部還回去
                _unlink_if_mine(p)
            raise pytest.UsageError(
                "【" + why + "】\n"
                "其他測試已佔滿全機名額（全量回歸或 -n 平行，同時上限見 MOTRIX_PYTEST_SLOTS）%s。\n"
                "  持有者 pid=%s 視窗=%s 已跑 %d 分鐘\n"
                "  鎖檔 %s\n"
                "⚠️ CPU 是共用資源：兩套一起跑會把靠時序的斷言搞紅，"
                "而**失敗的樣子跟真的有 bug 一模一樣**。\n"
                "⇒ **等它跑完。**\n"
                "⚠️ 不要因為「它大概已經死了」就刪掉鎖檔 —— **持有者真的死掉、"
                "或鎖超過 %d 分鐘，這裡都會自己放行**，所以你會被擋，"
                "就代表那個行程很可能**真的還在跑**。\n"
                "   唯一該手動刪的情形是 **pid 被重用**（一個無關的新行程剛好拿到"
                "同一個號碼），而你不想等到年紀上限 —— 先去確認 pid=%s 是不是 pytest。"
                % ("（已排隊 %d 分鐘仍未輪到）" % (wait // 60) if wait else "",
                   held.get("pid"), held.get("basetemp"), age // 60, path,
                   LOCK_MAX_AGE_SECONDS // 60, held.get("pid"))
            )
        if now - announced >= 60:
            _lock_say("\n[測試鎖] %s（pid=%s、%s、已跑 %d 分鐘）—— 排隊中，最多再等 %d 分鐘"
                  % (why, held.get("pid"), held.get("basetemp"), age // 60, (deadline - now) // 60), flush=True)
            announced = now
        time.sleep(min(poll, max(0.05, deadline - now)))


def _create_lock(path, basetemp) -> bool:
    """🔑 原子建檔（O_EXCL）：兩個排隊的人同時看到「空了」，只有一個建得成。已存在回 False。"""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"pid": os.getpid(), "started_at": time.time(), "basetemp": str(basetemp)}))
    return True


#: 建包獨佔登記的年紀上限：建包（兩段＋打包）可能超過格子的 60 分鐘上限；持有者活著就有效，最多 3 小時。
EXCLUSIVE_MAX_AGE_SECONDS = 3 * 60 * 60


def _clear_if_stale(path, max_age=None) -> None:
    """鎖檔不可信、持有者已死、或過期 ⇒ 刪掉（**一個解不掉的鎖比沒有鎖更糟**）。"""
    max_age = LOCK_MAX_AGE_SECONDS if max_age is None else max_age
    if not path.exists():
        return
    info = _read_lock(path)
    # ⚠️ 取值也要包在 try 裡：一個不可信的鎖要當成「沒有鎖」，不是當成「拒絕所有人」
    try:
        age = time.time() - float(info.get("started_at", 0))
        pid = int(info.get("pid", -1))
    except (AttributeError, TypeError, ValueError):
        if path.exists():
            _lock_say("\n[測試鎖] 鎖檔內容不可信（%s）—— 當成沒有鎖" % path)
            _unlink_quietly(path)
        return
    alive = _pid_alive(pid)
    if not alive or age > max_age:
        _lock_say("\n[測試鎖] 接手一個%s的鎖：pid=%s、%d 分鐘前" %
                  ("已死" if not alive else "過期", info.get("pid"), age // 60))
        _unlink_quietly(path)


def _lock_attempt(slots, intent, exclusive, basetemp, mine):
    """搶一輪。回 (成功?, 擋住我的那份鎖內容, 它的路徑, 原因)。`mine` 累積自己已佔的檔。

    `MOTRIX_PYTEST_EXCLUSIVE_OWNER=<pid>`：登記是建包腳本（該 pid）建的，涵蓋它的兩段 pytest
    ⇒ 認得它、不建也不刪（否則兩段之間的空檔會被別的視窗插進來）。"""
    _clear_if_stale(intent, EXCLUSIVE_MAX_AGE_SECONDS)
    reg = _read_lock(intent)
    owner = os.environ.get("MOTRIX_PYTEST_EXCLUSIVE_OWNER")
    reg_is_ours = bool(reg) and str(reg.get("pid")) in {str(os.getpid()), str(owner)}
    if exclusive:
        if intent not in mine and not reg_is_ours:
            if _create_lock(intent, basetemp):
                mine.append(intent)
            else:
                return False, _read_lock(intent), intent, "另一個建包正在獨佔（或登記中）"
    elif reg and not reg_is_ours:
        return False, reg, intent, "建包獨佔中：等它跑完，不插隊到它前面"
    held = None
    for path in slots:
        if path in mine:
            continue
        _clear_if_stale(path)
        if _create_lock(path, basetemp):
            mine.append(path)
            if not exclusive:
                return True, None, None, ""
            continue
        if held is None:
            held = (_read_lock(path), path)
    if exclusive and all(p in mine for p in slots):
        return True, None, None, ""
    held = held or (None, slots[0])
    why = "建包獨佔：等目前的持有者跑完" if exclusive else "另一套測試正在跑"
    return False, held[0], held[1], why


def _unlink_if_mine(path) -> None:
    held = _read_lock(path)
    try:
        if held and int(held.get("pid", -1)) == os.getpid():
            path.unlink()
    except (OSError, TypeError, ValueError):
        pass


def _lock_say(msg, **kw):
    """排隊／接手訊息。**印不出來不可以讓整輪測試崩掉**。

    ☠️ 2026-09-24：輸出導到檔案時 Windows 的 stdout 編碼是系統 locale（cp932／cp950），
    中文訊息一印就 `UnicodeEncodeError` ⇒ pytest INTERNALERROR ⇒ 排隊中的那一輪直接死掉，
    而錯誤指向鎖、看起來像鎖壞了。⇒ 編不出來的字元換成替代字元後照印。
    """
    try:
        print(msg, **kw)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(msg.encode(enc, "replace").decode(enc, "replace"), **kw)


def _unlink_quietly(path):
    try:
        path.unlink()
    except OSError:
        pass


def _basetemp_safe_to_delete(path) -> bool:
    """只刪「一輪測試自己的 basetemp」，不可能刪到 TEMP 根、磁碟根或 repo。"""
    try:
        p = Path(path).resolve()
    except OSError:
        return False
    if not p.exists() or not p.is_dir():
        return False
    temp_root = Path(tempfile.gettempdir()).resolve()
    repo_root = Path(__file__).resolve().parents[2]
    if p == temp_root or p == Path(p.anchor) or p in repo_root.parents or p == repo_root:
        return False
    if repo_root in p.parents and "tests" not in p.parts:
        return False                      # repo 底下的一般目錄一律不動
    return len(p.parts) >= 3


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    """🔴 一輪跑完（綠或紅）就刪掉**這一輪自己的** basetemp。

    使用者 2026-09-24 明訂為核心規則：「測試的資料夾用完要記得刪掉，已經多次發生導致硬碟損耗過高」
    （09-14 清出 190 GB、09-24 又累積 228 GB）。靠人記得已經失敗三次 ⇒ 改成這裡自動做。
    - 只刪 `--basetemp` 指到的那一個目錄，**不用萬用字元**（09-24 有人用 motrix-pytest-* 整批刪，
      刪到別的視窗使用中的目錄）。
    - xdist worker 不刪（它們的目錄在主行程的 basetemp 底下，由主行程一次刪）。
    - 要留下來查紅燈：設 `MOTRIX_PYTEST_KEEP_BASETEMP=1`，查完自己刪。
    """
    config = session.config
    if hasattr(config, "workerinput"):
        return
    if os.environ.get("MOTRIX_PYTEST_KEEP_BASETEMP") == "1":
        return
    basetemp = config.option.basetemp
    if not basetemp or not _basetemp_safe_to_delete(basetemp):
        return
    import shutil
    shutil.rmtree(str(basetemp), ignore_errors=True)
    if Path(basetemp).exists():
        _lock_say("\n[暫存] %s 有部分檔案仍被佔用、沒刪乾淨，請稍後手動刪除" % basetemp)


def pytest_unconfigure(config):
    """只釋放**自己**拿到的鎖。

    ⚠️ 無條件刪檔的話，一個沒搶到鎖、被擋下來的行程會在結束時
    **把持有者的鎖刪掉** —— 那道守門就只對第一個人有效。
    """
    global _lock_taken_by_me
    if not _lock_taken_by_me:
        return
    paths = _lock_taken_by_me         # 拿到的是哪幾格（獨佔時含登記檔）就還哪幾格
    _lock_taken_by_me = False
    for path in paths:
        _unlink_if_mine(path)


# ══════════════════════════════════════════════════════════════════════════
# NETGUARD · 測試套件不可以真的對外連線
#
# ☠️ 2026-09-21：B 量到**測試套件每跑一次就對政府採購網發出數十次真實請求**，
#    而它從第 6 輪就存在了。單獨跑一題 `test_sl1` ⇒ 5 次對外嘗試。
#
#    成因：`_spy_fetch()` patch 的是 `fetch_raw`（清單頁）—— 而
#    `parse_list(REAL)` 解出來的 `url` 是**真的**
#    ⇒ `run_scan` → `_fetch_details` → `fetch_detail` → `urlopen` → 真的連出去。
#    **只有 SL10 記得 patch `fetch_detail`，其餘每一題都是真的。**
#
# 🔑 而它的諷刺值得寫在這裡：我們整晚在做的是
#    「**這台機器不會在沒有人知道的情況下對外連線**」——
#    `radar_on()`、出貨預設關、啟動 log、404 而不是 403。
#    **而測試套件每跑一次就對那個網站發出數十次請求，沒有任何人知道。**
#    ⇒ **我們守住了產品，沒有守住測試。**
#
# ⚠️ 逐題去 patch `fetch_detail` **不是**修法 —— 那正是「只有 SL10 記得加」
#    的成因。這一道攔的是**所有**同類的疏漏，包含還沒被寫出來的那些。
# ══════════════════════════════════════════════════════════════════════════

#: 允許對外連線的標記：`@pytest.mark.allow_outbound`
#: ⚠️ 目前**一個都不該有**。要加的話請在該題的 docstring 寫出為什麼。
_ALLOW_OUTBOUND = "allow_outbound"


def pytest_collection_modifyitems(config, items):
    """把 `allow_outbound` 註冊成已知標記，免得它變成一個安靜的錯字。

    ⚠️ 未註冊的 mark 只會噴 warning ⇒ `@pytest.mark.allow_outbund`（打錯字）
    會**靜默地不生效**，而那一題會在 NETGUARD 下紅得莫名其妙。
    """
    config.addinivalue_line(
        "markers", "%s: 這一題確實需要對外連線（目前一個都沒有）" % _ALLOW_OUTBOUND)


@pytest.fixture(autouse=True)
def _netguard(request, monkeypatch):
    """任何測試真的對外連線 ⇒ **那一題紅**。

    ## ⚠️ 三個限制，寫在這裡免得被當成比它實際更強

    1. **它攔的是 `urllib.request.urlopen` 與 `smtplib.SMTP`。**
       走 `requests`／`http.client`／裸 `socket` 的**不在射程內**。
       （這個 codebase 的對外連線目前都走這兩條，而那是今天的事實，不是保證。）

       ## 🔴 `smtplib` 是 2026-09-22 補的，而理由不是完整性

       §4 YA 那一輪要走到 SMTP，所以那個檔繞過了 `_smtp_send_blocked()` ——
       而那道擋存在的理由是**開發機真的對同仁寄出過兩次真實催辦信**。
       ☠️ 當時我自己寫下：「**NETGUARD 攔不到這一條 ⇒ 沒有第二道防線**」，
       🔑 而「**我知道那裡沒有防線**」與「**那裡有防線**」是兩件事。
       📌 現在補上了：即使某一題的 `monkeypatch` 失效，
       **也不會有真的信寄出去。**
       ⚠️ 而 `_smtp_send_blocked()` 仍然是產品那一側的第一道 ——
       **這一道只保護測試，不保護正式機。**
    2. **它只管這個行程。** 子行程（`tests/_subproc.py` 起的那些）**攔不到**。
    3. **它擋的是「測試對外連線」，不是「產品對外連線」。**
       產品那一側由 `radar_on()`／`geo_on()`／出貨預設關那幾道守著，
       **不要因為這裡綠了就以為產品被守住了。**

    ## 🔴 為什麼不能只靠丟例外

    第一版我只在攔截點 `raise`。**那是不夠的** ——
    `fetch_detail()` 有 `except Exception: return None, ...`
    ⇒ **它會把我的例外吞掉**，那一題照樣綠，而連線嘗試已經發生了。

    🔑 **守門的例外會被受測對象接住** ⇒ 所以要**記錄下來、在收尾時斷言**。
    ⚠️ 那正是今天反覆出現的那一族：**觀測手段與被測對象共用一條路徑**
    （這次共用的是例外傳播）。
    """
    if request.node.get_closest_marker(_ALLOW_OUTBOUND):
        yield
        return

    import smtplib
    import urllib.request

    attempts = []

    def _blocked(req, *args, **kwargs):
        url = req if isinstance(req, str) else getattr(req, "full_url", repr(req))
        attempts.append(url)
        raise OSError("NETGUARD：測試不可以真的對外連線（%s）" % url)

    class _BlockedSMTP:
        """任何試圖建立 SMTP 連線的動作都記帳並丟例外。

        ⚠️ 記帳的理由與 `urlopen` 那一條相同：`_send()` 有
        `except Exception: ...` ⇒ **它會把這個例外吞掉**，
        而那一題照樣綠 —— 🔑 所以要在收尾時斷言。
        """

        def __init__(self, host="", port=0, *a, **kw):
            attempts.append("smtp://%s:%s" % (host, port))
            raise OSError("NETGUARD：測試不可以真的連 SMTP（%s:%s）"
                          % (host, port))

    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
    monkeypatch.setattr(smtplib, "SMTP", _BlockedSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _BlockedSMTP, raising=False)
    yield
    assert not attempts, (
        "這一題對外發出了 %d 次真實連線嘗試：\n  %s\n"
        "⇒ 八成是 `fetch_raw` 被換掉了而 `fetch_detail` 沒有 —— "
        "樣本解出來的 `url` 是**真的網址**。\n"
        "⚠️ 若這一題確實需要連外，加 `@pytest.mark.%s` 並在 docstring 寫出理由。"
        % (len(attempts), "\n  ".join(attempts[:5]), _ALLOW_OUTBOUND)
    )


#: 瀏覽器端視為「本機」的網址（測試伺服器一律是 127.0.0.1 的 loopback）。
_BROWSER_LOCAL_PREFIXES = ("http://127.0.0.1", "http://localhost", "data:", "blob:", "about:")
#: 守門只攔「不是本機」的網址。🔴 用**正則**而不是 `**/*`：正則在 Playwright 的 node 端比對，
#: 本機請求**根本不會送到 Python**。
#: ☠️ 第一版用 `**/*`＋Python 端 fallback ⇒ 每個請求都要等 Python 回話；題目若在自己的
#:    route handler 裡 `time.sleep()` 製造競態（W-4、UR1 那一族），sync API 的分派被卡住，
#:    **其他請求一起被延後** ⇒ 競態被序列化、題目永遠綠（2026-09-25 以 W-4 突變實證：
#:    守門開著突變不紅、關掉就紅）。守門不可以改變被測對象的時序。
_BROWSER_EXTERNAL_URL = __import__("re").compile(
    r"^(?!(?:http://127\.0\.0\.1|http://localhost|data:|blob:|about:))")


def _assert_no_browser_outbound(attempts):
    assert not attempts, (
        "這一題的**瀏覽器**對外發出了 %d 次請求（已被攔下）：\n  %s\n"
        "⇒ 八成是地圖圖磚沒有攔：`context.route(\"**/tile.openstreetmap.org/**\", "
        "lambda r: r.fulfill(status=200, content_type=\"image/png\", body=<1×1 png>))`。\n"
        "⚠️ 若這一題確實需要連外，加 `@pytest.mark.%s` 並在 docstring 寫出理由。"
        % (len(attempts), "\n  ".join(attempts[:5]), _ALLOW_OUTBOUND)
    )


@pytest.fixture(autouse=True)
def _browser_netguard(request, monkeypatch):
    """瀏覽器對外連線 ⇒ **那一題紅**（2026-09-25）。

    `_netguard` 只看**這個 Python 行程**的 urlopen／SMTP ⇒ Playwright 起的瀏覽器
    發出的請求（例如地圖圖磚連 tile.openstreetmap.org）**完全看不到**：
    mp0／mp1／mp8 開了 map.html 卻沒攔圖磚，每跑一次就真的連 OSM 一次。

    作法：攔 `Browser.new_context`／`Browser.new_page`，對每個 context 裝一個
    **只匹配非本機網址**的 route（`_BROWSER_EXTERNAL_URL`，見那裡為什麼一定要用正則），
    命中的 **abort 並記帳**，收尾時斷言（同 `_netguard`：守門的例外可能被受測對象接住，
    所以記帳、收尾才判）。

    ## ⚠️ 限制
    - 它裝在**最早**，Playwright 的 route 是**後註冊的先處理** ⇒ 題目自己攔下並
      `fulfill` 的請求（例如圖磚回一張空白 png）不會走到這裡，這正是要的。
      但題目自己的 route 若對外部網址呼叫 `continue_()`，會**直接送出、繞過這一道**。
    - 只管透過 `Browser.new_context／new_page` 建的頁面（這個 codebase 全部是）；
      `launch_persistent_context` 不在射程內。
    """
    try:
        from playwright.sync_api._generated import Browser
    except Exception:  # 沒裝 Playwright 的環境：沒有瀏覽器可守
        yield
        return
    attempts = []
    request.node._browser_outbound = attempts          # 給正對照題讀

    def _guard(route):
        attempts.append(route.request.url)
        route.abort()

    orig_ctx, orig_page = Browser.new_context, Browser.new_page

    def _new_context(self, *a, **kw):
        ctx = orig_ctx(self, *a, **kw)
        ctx.route(_BROWSER_EXTERNAL_URL, _guard)
        return ctx

    def _new_page(self, *a, **kw):
        page = orig_page(self, *a, **kw)
        page.context.route(_BROWSER_EXTERNAL_URL, _guard)
        return page

    monkeypatch.setattr(Browser, "new_context", _new_context)
    monkeypatch.setattr(Browser, "new_page", _new_page)
    yield
    if not request.node.get_closest_marker(_ALLOW_OUTBOUND):
        _assert_no_browser_outbound(attempts)


# ══ e2e 共用瀏覽器與伺服器（PLAN-TEST-PERF #5，2026-09-25）═══════════════════════
#
# 每題各自起 uvicorn（0.23s）、各自 launch chromium（0.34s）改成**每個 worker 一套**：
# session scope 在 pytest-xdist 底下就是「每個 worker 行程一份」⇒ -n 4 時 4 套伺服器＋瀏覽器，
# 互不共用。**DB 仍然每題一份**：`client` 每題換 db.DB_PATH，伺服器在 request 當下才讀
# （main.py 沒有 startup／lifespan），共用伺服器看到的就是這一題的庫。
#
# ## 寫法（改寫前 → 改寫後）
#
#     # 前：每題自己起伺服器、自己開瀏覽器、走登入頁
#     from playwright.sync_api import sync_playwright
#     @pytest.fixture()
#     def live_server(client): ...uvicorn...
#     def test_x(live_server, make_user):
#         u = make_user(username="x", role="admin")
#         with sync_playwright() as p:
#             browser = p.chromium.launch()
#             try:
#                 page = browser.new_page(viewport={"width": 1440, "height": 900})
#                 page.goto(f"{live_server}/pages/login.html"); ...填帳密、按登入、等 index...
#                 page.goto(f"{live_server}/pages/case-management.html")
#             finally:
#                 browser.close()
#
#     # 後：不 import sync_playwright、不定義 live_server
#     def test_x(live_server, make_user, new_page, login_as):
#         u = make_user(username="x", role="admin")
#         page = new_page(viewport={"width": 1440, "height": 900})
#         login_as(page, u)                       # API 取 token 注入 localStorage（不經登入頁）
#         page.goto(f"{live_server}/pages/case-management.html")
#
# - 要多個頁面／分頁：`new_page()` 叫兩次（各自一個 context ⇒ 互不共用 localStorage），
#   或 `ctx = new_context(); p1 = ctx.new_page(); p2 = ctx.new_page()`（同一個 context ⇒ 共用）。
# - 要驗登入頁本身的題**保留走登入頁**（test_e2e_login_enter_submits 等），不要改成 login_as。
# - 收尾不用自己 close：題目結束時 fixture 關掉這一題開的所有 context。
#
# ## 與「還沒轉」的檔並存
#
# ⚠️ session 級的 sync_playwright 開著時，題內再 `with sync_playwright()` 會報
# 「using Playwright Sync API inside the asyncio loop」（實測）。
# ⇒ `_pw_coexist`：跑到**模組裡還 import 著 sync_playwright** 的題之前，先把共用的停掉，
#   下一個轉過的題要用時再重啟。所以轉換可以分批落地；全部轉完後這一段只剩守門作用。
#   🔴 轉過的檔**不可以**再 import sync_playwright，否則每一題都會被當成「還沒轉」而重啟瀏覽器。
#
# ## 給其他項目的掛點
#
# `E2E_CONTEXT_HOOKS`：每個 context 建好後依序呼叫 `hook(context, request)`
# （#6 擋圖片／媒體掛在這裡；用 marker 讓需要的題退出）。
#
# ## A／B 對照開關
#
# `MOTRIX_E2E_FRESH_BROWSER=1` ⇒ 退回改動前的成本模型：**每題**自己 launch 瀏覽器、自己起 uvicorn
# （題目寫法不用改）。給全量 A／B 量測用；平常不要設。

E2E_CONTEXT_HOOKS = []

_PW = {"pw": None, "browser": None}


def _shared_browser():
    if _PW["browser"] is None:
        from playwright.sync_api import sync_playwright
        _PW["pw"] = sync_playwright().start()
        _PW["browser"] = _PW["pw"].chromium.launch()
    return _PW["browser"]


def _stop_shared_browser():
    if _PW["pw"] is None:
        return
    try:
        _PW["browser"].close()
    finally:
        _PW["pw"].stop()
        _PW["pw"] = _PW["browser"] = None


def _module_opens_its_own_playwright(module):
    """還沒轉的模組：模組層仍 import 著 sync_playwright。"""
    return getattr(module, "sync_playwright", None) is not None


@pytest.fixture(autouse=True)
def _pw_coexist(request):
    """還沒轉的模組自己開 sync_playwright ⇒ 先停掉共用的（見上方「並存」）。"""
    if _module_opens_its_own_playwright(getattr(request, "module", None)):
        _stop_shared_browser()
    yield


@pytest.fixture(scope="session", autouse=True)
def _pw_shared_shutdown():
    """session 結束時關掉共用瀏覽器（不另寫 pytest_sessionfinish：那會蓋掉上面清 basetemp 的那一個）。"""
    yield
    try:
        _stop_shared_browser()
    except Exception:
        pass


def _e2e_fresh():
    """A／B 對照開關：設了就每題自開瀏覽器與伺服器（見上方說明）。"""
    return os.environ.get("MOTRIX_E2E_FRESH_BROWSER") == "1"


class _InflightCountingApp:
    """ASGI 外殼：數伺服器上**正在處理**的 HTTP 請求。

    🔴 共用伺服器的收尾要「排空」：前一題頁面發出、還在處理中的請求，若拖到前一題的 monkeypatch
    還原之後（甚至 `client` 已把 db.DB_PATH 換成**下一題的庫**）才執行 ⇒ 漏進下一題
    （2026-09-25 實測：tender-radar 前一題的 /api/map/points 在還原 no_tile_probe 之後才跑，
    真的探測了圖磚，被下一題的 NETGUARD 記到）。
    每題自起伺服器時，關伺服器本身會等處理中的請求 ⇒ 等於有排空；共用之後要自己做。
    """
    def __init__(self, app):
        import threading as _th
        self.app, self.n, self._lock = app, 0, _th.Lock()

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        with self._lock:
            self.n += 1
        try:
            return await self.app(scope, receive, send)
        finally:
            with self._lock:
                self.n -= 1


_SERVER_APPS = []      # 這個行程起過的 _InflightCountingApp（共用＋A／B 開關下每題的）


def _drain_servers(timeout=10.0):
    """等所有測試伺服器上處理中的請求都結束；逾時就讓這一題紅（不可以靜默漏到下一題）。"""
    import time as _time
    deadline = _time.monotonic() + timeout
    while True:
        busy = sum(a.n for a in _SERVER_APPS)
        if busy == 0:
            return
        if _time.monotonic() > deadline:
            pytest.fail("測試伺服器收尾時仍有 %d 個請求在處理（%.0fs 內沒結束）——"
                        "它們會落到下一題的庫與 monkeypatch 狀態裡" % (busy, timeout))
        _time.sleep(0.02)


def _start_uvicorn(app):
    import threading as _th
    import time as _time
    import uvicorn
    from tests._ports import free_safe_port
    app = _InflightCountingApp(app)
    _SERVER_APPS.append(app)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=free_safe_port(), log_level="warning"))
    t = _th.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(200):
        if server.started:
            break
        _time.sleep(0.05)
    else:
        pytest.fail("uvicorn 測試伺服器在時限內沒有啟動")

    def _stop():
        server.should_exit = True
        t.join(timeout=5)
    return "http://127.0.0.1:%d" % server.servers[0].sockets[0].getsockname()[1], _stop


@pytest.fixture(scope="session")
def _shared_server(_app):
    """每個 worker 一個 uvicorn（loopback、隨機安全埠），整個 session 共用。"""
    base, stop = _start_uvicorn(_app)
    yield base
    stop()


@pytest.fixture()
def live_server(client, _app, request):
    """function scope：先經過 `client`（這一題的新庫已就位），再給共用伺服器的網址。
    模組自己定義的 live_server 會蓋過這一個（還沒轉的檔照舊）。"""
    if _e2e_fresh():
        base, stop = _start_uvicorn(_app)
        request.addfinalizer(stop)
        return base
    request.addfinalizer(_drain_servers)    # 題目沒用 new_context（例如還沒轉、自開瀏覽器）也要排空
    return request.getfixturevalue("_shared_server")


@pytest.fixture()
def new_context(request):
    """開一個新的 browser context（每題隔離：localStorage／cookie 不跨題）；題目結束時全部關掉。"""
    opened = []
    own = {}                                   # A／B 開關：這一題自己的 playwright＋browser

    def _browser():
        if not _e2e_fresh():
            return _shared_browser()
        if "browser" not in own:
            _stop_shared_browser()             # 不與共用的並存（同一執行緒只能有一個 sync_playwright）
            from playwright.sync_api import sync_playwright
            own["pw"] = sync_playwright().start()
            own["browser"] = own["pw"].chromium.launch()
        return own["browser"]

    def _make(**kw):
        ctx = _browser().new_context(**kw)
        for hook in E2E_CONTEXT_HOOKS:
            hook(ctx, request)
        opened.append(ctx)
        return ctx

    yield _make
    for ctx in opened:
        try:
            ctx.close()
        except Exception:
            pass
    if own:
        try:
            own["browser"].close()
        finally:
            own["pw"].stop()
    # 頁面都關了 ⇒ 不會再有新請求；等處理中的跑完，才輪到 monkeypatch 還原與下一題換庫
    _drain_servers()


@pytest.fixture()
def e2e_browser(new_context):
    """轉換用的薄外殼：長得像 Playwright 的 Browser（new_context／new_page／close），底下是共用瀏覽器＋每題 context。
    舊寫法把 `browser` 傳進 helper 的，改成 `browser = e2e_browser` 之後 helper 不必改；close() 什麼都不做
    （這一題開的 context 由 new_context 在題末關）。"""
    class _Browser:
        def new_context(self, **kw):
            return new_context(**kw)

        def new_page(self, **kw):
            return new_context(**kw).new_page()

        def close(self):
            pass
    return _Browser()


@pytest.fixture()
def new_page(new_context):
    """`new_page(**context_kwargs)` ⇒ 一個新 context 裡的新頁面。"""
    return lambda **kw: new_context(**kw).new_page()


@pytest.fixture()
def login_as(client):
    """`login_as(page_or_context, (username, password))`：API 取 token，注入 localStorage（格式同 login.html
    `_storeSessionAndRedirect`），之後 goto 任何頁面都是登入狀態。要驗登入頁本身的題不要用這個。"""
    import json as _json

    def _login(target, user):
        r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
        assert r.status_code == 200, r.text
        d = r.json()
        assert not d.get("totpRequired"), "這個帳號要 TOTP：login_as 不處理，請走登入頁"
        sess = {k: d.get(k) for k in ("token", "userId", "username", "displayName", "role", "modules", "loginAt")}
        ctx = getattr(target, "context", target)
        from tests._e2e_login import session_init_script   # 含「已經過 index」的分頁旗標（見那裡）
        ctx.add_init_script(session_init_script(sess))
        return sess
    return _login


# ══ e2e 逐題上限（PLAN-TEST-PERF §3.2，建包 e2e -n 4 的前置條件；hichan-8d 2026-09-25）════════════
#
# 一題卡住（例如 page.evaluate 等一個沒人回答的對話框）會拖住一個 worker 直到整輪逾時，而最後只看得到
# 「整輪逾時」。⇒ 每一題 e2e 設上限（預設 120s，MOTRIX_E2E_HARD_CAP 覆寫）：超過就把所有執行緒的堆疊
# 寫下來（卡在哪一行）。不裝 pytest-timeout，用標準庫 faulthandler。
# - 在 xdist worker 裡 ⇒ 寫完結束那個 worker：xdist 判那題失敗、換新 worker 接著跑（共用瀏覽器與伺服器
#   由新 worker 按需重建）。☠️ worker 的 stderr 不會轉回主控 ⇒ 堆疊寫到**檔案**，主控在最後的摘要印出，
#   並補一行 `FAILED <題> - Timeout…`（xdist 自己那行被截成 `- w...`，建包閘門認不出是逾時）。
# - 單程序（沒有 -n）⇒ 只寫堆疊、不結束（結束會讓整個 pytest 停掉、剩下的題全都不跑——a3 提醒）；
#   題目收尾時若已超過上限，摘要照樣印出堆疊當警告（那一題本身沒有失敗，結束碼不變）。
# - 題目正常結束一定取消計時器，否則上限會累計到下一題。
# - autouse、最早建立 ⇒ 最晚拆掉：題目本體與收尾（含共用伺服器的排空）都在範圍內。
_E2E_HARD_CAP_DEFAULT = 120


def _e2e_hard_cap_seconds():
    try:
        return float(os.environ.get("MOTRIX_E2E_HARD_CAP") or _E2E_HARD_CAP_DEFAULT)
    except ValueError:
        return float(_E2E_HARD_CAP_DEFAULT)


def _e2e_hard_cap_dir():
    """同一次執行（主控＋所有 worker）共用一個目錄；不同視窗的執行互不相干。"""
    import tempfile
    # 主控在 pytest_configure（worker 起來之前）寫好 MOTRIX_E2E_HARDCAP_RUN，worker 繼承同一個值。
    # ⚠️ 不用 PYTEST_XDIST_TESTRUNUID：那個只有 worker 有，主控算出來的目錄會對不上（實測：摘要什麼都沒印）。
    run = os.environ.get("MOTRIX_E2E_HARDCAP_RUN") or ("pid%d" % os.getpid())
    return os.path.join(tempfile.gettempdir(), "motrix-e2e-hardcap-" + run)


@pytest.fixture(autouse=True)
def _e2e_hard_cap(request):
    if request.node.get_closest_marker("e2e") is None:
        yield
        return
    import faulthandler
    import time as _t
    import uuid as _uuid
    cap = _e2e_hard_cap_seconds()
    d = _e2e_hard_cap_dir()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "%s.txt" % _uuid.uuid4().hex)
    fh = open(path, "w", encoding="utf-8")
    fh.write(request.node.nodeid + "\n")
    fh.flush()
    faulthandler.dump_traceback_later(cap, exit=bool(os.environ.get("PYTEST_XDIST_WORKER")), file=fh)
    t0 = _t.monotonic()
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()
        fh.close()
        if _t.monotonic() - t0 < cap:
            try:
                os.remove(path)
            except OSError:
                pass


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """主控（或單程序）收尾：把逐題上限留下的堆疊印出來。"""
    if hasattr(config, "workerinput"):
        return
    import glob as _g
    d = _e2e_hard_cap_dir()
    files = sorted(_g.glob(os.path.join(d, "*.txt")))
    if not files:
        return
    cap = _e2e_hard_cap_seconds()
    tr = terminalreporter
    tr.section("e2e 逐題上限 %gs：超過上限的題（堆疊＝卡在哪一行）" % cap, red=True)
    worker_run = bool(getattr(config.option, "numprocesses", None))
    killed = []
    for f in files:
        try:
            body = open(f, encoding="utf-8", errors="replace").read()
        finally:
            try:
                os.remove(f)
            except OSError:
                pass
        nodeid, _, stack = body.partition("\n")
        tr.write_line("── %s" % nodeid)
        for line in stack.rstrip().splitlines():
            tr.write_line("   " + line)
        killed.append(nodeid)
    if worker_run:
        # 給建包閘門（_e2e_gate.ps1 認 `FAILED … Timeout`）；xdist 自己那行會被截斷、也不含 Timeout
        for nodeid in killed:
            tr.write_line("FAILED %s - Timeout: e2e 逐題上限 %gs（堆疊見上方）" % (nodeid, cap))
    try:
        os.rmdir(d)
    except OSError:
        pass
