"""測試時 Edge 重用 profile（conftest `_install_edge_profile_pool`，PLAN-TEST-PERF §5.3）。

🔑 只改測試端：產品預設不帶 `--user-data-dir`（每次新 profile）這件事不可以因為測試而改。
🔑 並發：同一份 profile 同時被兩個 Edge 用會被鎖 ⇒ 每個同時在跑的 Edge 各拿一份。
"""
import threading
import time
from pathlib import Path

import helpers
import helpers.startup as startup
import helpers.voucher_pdf as voucher_pdf
import pdf_gen

BACKEND = Path(__file__).resolve().parents[1]


def test_product_code_never_passes_a_user_data_dir():
    """產品預設行為不變：產品碼（tests 以外）沒有任何一處帶 `--user-data-dir`。"""
    hits = [str(p.relative_to(BACKEND)) for p in BACKEND.rglob("*.py")
            if "tests" not in p.relative_to(BACKEND).parts and p.name != "conftest.py"  # conftest.py 在 backend/ 根（2026-09-25 自 tests/ 上移），是測試設定不是產品碼
            and "--user-data-dir" in p.read_text(encoding="utf-8", errors="ignore")]
    assert hits == [], "產品碼帶了 --user-data-dir：%s" % hits


def _capture(monkeypatch, delay=0.0):
    seen = []
    lock = threading.Lock()

    def fake_run(cmd, **kw):
        with lock:
            seen.append(list(cmd))
        time.sleep(delay)
    monkeypatch.setattr(startup.subprocess, "run", fake_run)
    return seen


def test_every_import_site_uses_the_wrapper_and_the_product_function_is_untouched(client, monkeypatch):
    import sys
    w = pdf_gen.run_edge_pdf
    assert all(getattr(m, "run_edge_pdf") is w
               for m in (startup, helpers, voucher_pdf)), \
        "有一處呼叫端沒換到（依值綁定的 import 要逐一換）"
    # 模組的呼叫端（例：modules/netplan/export.py、modules/analytics/api/reports.py）由下面的 sys.modules 掃描一併涵蓋；模組自己的測試另有逐處斷言
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


def test_concurrent_edges_never_share_a_profile(client, monkeypatch):
    """🔴 產品並發上限內同時開的 Edge，各自拿到不同的 profile；用完歸還、之後重用同一批。"""
    seen = _capture(monkeypatch, delay=0.3)
    n = startup.EDGE_PDF_MAX_CONCURRENCY
    ts = [threading.Thread(target=pdf_gen.run_edge_pdf, args=(["msedge.exe", "--headless", "u%d" % i],))
          for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    dirs = [c[1] for c in seen]
    assert len(dirs) == n and len(set(dirs)) == n, "同時在跑的 Edge 共用了 profile：%s" % dirs
    before = set(dirs)
    pdf_gen.run_edge_pdf(["msedge.exe", "--headless", "again"])
    assert seen[-1][1] in before, "用完沒有歸還重用（每次又開新的）"


def test_a_profile_still_locked_by_a_leftover_edge_is_replaced(client, monkeypatch):
    seen = _capture(monkeypatch)
    pdf_gen.run_edge_pdf(["msedge.exe", "--headless", "a"])
    d = Path(seen[0][1].split("=", 1)[1])
    real_unlink = Path.unlink

    def locked_unlink(self, *a, **kw):
        if self.name == "lockfile":
            raise PermissionError("in use")
        return real_unlink(self, *a, **kw)
    (d / "lockfile").write_text("", encoding="utf-8")
    monkeypatch.setattr(Path, "unlink", locked_unlink)
    for i in range(startup.EDGE_PDF_MAX_CONCURRENCY + 1):   # 輪一圈一定會拿到 d
        pdf_gen.run_edge_pdf(["msedge.exe", "--headless", "b%d" % i])
    used_after = {c[1].split("=", 1)[1] for c in seen[1:]}
    assert str(d) not in used_after, "被殘留 Edge 鎖住的 profile 仍被拿來用"
