"""瀏覽器層級端對端 smoke test（2026-09-07，架構地圖 §6 建議事項之一）。

背景：全系統 400+ 個 pytest 都是後端 API 整合測試，前端 Alpine inline script
完全沒有任何自動化測試網——但過去好幾次真實回歸（`x-show` vs `x-if` 誤用、
badge 同步漏更新、日期字串排序、Alpine reactivity 相關 bug）恰好都是純前端
邏輯出的問題，後端 API 測試全綠也攔不下來，只能靠人工在瀏覽器裡肉眼發現。
這裡補一條最關鍵路徑（登入→建報價單→送出審核→另一位主管簽核）的 smoke test，
不求覆蓋率，只求「這條路徑還能走得通」有自動化訊號。

需要 `playwright`（`pip install playwright && playwright install chromium`）
——這是測試專用相依，刻意不放進 `backend/requirements.txt`（正式機執行 ERP
服務不需要瀏覽器引擎），沒裝的環境會直接 skip 整個檔案，不影響
`build_deploy_package.ps1` 既有的「先跑 pytest 再打包」流程。
"""
import threading
import time

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

import uvicorn


@pytest.fixture()
def live_server(client):
    """`client` fixture 已經把 db.DB_PATH/DEMO_DB_PATH/uploads 等全部導向這次
    測試專屬的隔離暫存路徑（見 conftest.py）；這裡額外把同一個 `main.app`
    再開一個真正的 loopback TCP 監聽，因為 Playwright 是真的瀏覽器程序、
    不能像 TestClient 一樣直接呼叫 ASGI app，需要一個真實網址可以打。"""
    import main
    config = uvicorn.Config(main.app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("uvicorn 測試伺服器在時限內沒有啟動")
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def _login(page, base_url, username, password):
    page.goto(f"{base_url}/pages/login.html")
    page.fill('input[x-model="username"]', username)
    page.fill('input[x-model="password"]', password)
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=10000)


@pytest.mark.e2e
def test_login_create_submit_approve_smoke(live_server, make_user):
    """golden path：建立者登入 → 新增報價單（客戶/案件/一項品項）→ 送出審核
    → 另一位 superadmin 登入 → 開啟同一張報價單 → 簽核 → 狀態變成「已送出」。
    無簽核流程設定時系統規則是「禁止申請人自簽」，所以刻意用兩個不同帳號。

    簽核解析走 `helpers/tiered_approval.py::resolve_submitter_manager_chain()`
    ——申請人部門主管自動簽核鏈是動態解析（非送審當下快照），申請人必須歸屬
    某個部門才解得出來，見該函式 docstring；這裡直接把建立者掛到一個以核准者
    為主管的部門下，讓核准者自然就是解析出來的簽核人。"""
    creator_user, creator_pw = make_user(username="e2e_creator", role="admin")
    approver_user, approver_pw = make_user(username="e2e_approver", role="superadmin")

    import db
    conn = db.get_db()
    now = "2026-01-01T00:00:00"
    approver_id = conn.execute("SELECT id FROM users WHERE username=?", (approver_user,)).fetchone()["id"]
    creator_id = conn.execute("SELECT id FROM users WHERE username=?", (creator_user,)).fetchone()["id"]
    div_id = conn.execute(
        "INSERT INTO divisions (name, sort_order, created_at) VALUES (?,?,?)",
        ("PW 測試處", 0, now),
    ).lastrowid
    dept_id = conn.execute(
        "INSERT INTO departments (division_id, name, sort_order, manager_user_id, created_at) VALUES (?,?,?,?,?)",
        (div_id, "PW 測試部門", 0, approver_id, now),
    ).lastrowid
    conn.execute("UPDATE users SET department_id=? WHERE id=?", (dept_id, creator_id))
    conn.commit()
    conn.close()

    project_name = f"PW-smoke-{int(time.time())}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            # ── 建立者：登入 → 新增報價單 → 送出審核 ──────────────────────
            ctx1 = browser.new_context()
            page1 = ctx1.new_page()
            page1.on("dialog", lambda d: d.accept())
            _login(page1, live_server, creator_user, creator_pw)

            page1.goto(f"{live_server}/pages/quotation-form.html")
            page1.fill('input[x-model="q.customerName"]', "PW 測試客戶")
            page1.fill('input[x-model="q.projectName"]', project_name)
            page1.locator('textarea[x-model="item.description"]').first.fill("測試品項 A")

            page1.click('button:has-text("申請送出審核")')
            page1.click('button:has-text("確認送出")')
            page1.wait_for_function(
                "document.querySelector('.form-quote-no')?.textContent?.trim().length > 0",
                timeout=10000,
            )

            quote_no = page1.locator(".form-quote-no").inner_text().strip()
            assert quote_no.startswith("MQ-"), f"未取得有效報價單號，實際: {quote_no!r}"
            ctx1.close()

            # ── 核准者：登入 → 開啟同一張報價單 → 簽核 ────────────────────
            ctx2 = browser.new_context()
            page2 = ctx2.new_page()
            dialogs = []
            page2.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))

            # 2026-09-08 臨時診斷探針（排查 flaky 根因用，見 MOTRIX-ERP-QUICK.md §12
            # 2026-09-08 條目）：記錄這個 page 從此刻起發出的每個 request 的耗時／
            # 狀態，以及 console 訊息——只有在下面 wait_for_selector 真的逾時失敗時
            # 才印出來，平常通過的執行不受影響、也不會弄髒輸出。
            _reqs = []
            _console = []

            def _on_request(req):
                _reqs.append({"url": req.url, "method": req.method, "start": time.time(), "end": None, "status": None})

            def _on_finished(req):
                for r in reversed(_reqs):
                    if r["url"] == req.url and r["end"] is None:
                        r["end"] = time.time()
                        try:
                            resp = req.response()
                            r["status"] = resp.status if resp else "no-response"
                        except Exception as e:
                            r["status"] = f"error:{e}"
                        break

            def _on_requestfailed(req):
                for r in reversed(_reqs):
                    if r["url"] == req.url and r["end"] is None:
                        r["end"] = time.time()
                        r["status"] = f"FAILED:{req.failure}"
                        break

            page2.on("request", _on_request)
            page2.on("requestfinished", _on_finished)
            page2.on("requestfailed", _on_requestfailed)
            page2.on("console", lambda m: _console.append(f"[{m.type}] {m.text}"))

            _login(page2, live_server, approver_user, approver_pw)

            _t_goto = time.time()
            page2.goto(f"{live_server}/pages/quotation-form.html?id={quote_no}")
            # 30 秒（已知這條測試偶爾會在這裡逾時，2026-09-07 兩輪觀察）：第一次
            # 只在整批 400+ 測試中間跑過一次時逾時過（當時 10 秒→20 秒），但同一天
            # 稍晚又在「單獨只跑這個檔案的 2 個測試」這種輕量情境下逾時過一次，
            # 代表不是單純「系統忙碌時才會慢」，根因還沒有抓到（懷疑跟 SQLite WAL
            # 模式下 approve 端點需要讀 quotations + tiered_approval 解析時偶發的
            # 鎖等待有關，但沒有實際證實）。目前的因應是持續加大這一處等待時限
            # 吸收，而不是照下修——之後若又觀察到逾時，先確認是不是同一個點卡住，
            # 而非重新從頭排查整條路徑。
            try:
                page2.wait_for_selector('button:has-text("預覽後簽核")', timeout=30000)
            except Exception:
                print(f"\n=== DIAGNOSTIC DUMP: elapsed since goto = {time.time() - _t_goto:.2f}s ===")
                try:
                    ready_state = page2.evaluate("document.readyState")
                    has_alpine = page2.evaluate("typeof window.Alpine !== 'undefined'")
                    print(f"document.readyState={ready_state}  window.Alpine defined={has_alpine}")
                except Exception as e:
                    print(f"(page2.evaluate failed: {e})")
                print("--- requests on page2 since ctx2 created ---")
                for r in _reqs:
                    dur = (r["end"] or time.time()) - r["start"]
                    print(f"  {dur:7.2f}s  status={r['status']!r:>14}  {r['method']} {r['url']}")
                print("--- console messages ---")
                for c in _console:
                    print(" ", c)
                raise
            page2.click('button:has-text("預覽後簽核")')
            page2.wait_for_selector('button:has-text("確認簽核")', timeout=20000)
            page2.click('button:has-text("確認簽核")')
            page2.wait_for_timeout(2500)  # apiSave() 非同步，等一下讓狀態更新回來
            # 第一個對話框是預期中的「確認簽核通過此報價單？」confirm()；若簽核 API
            # 失敗，approveQuote() 會再跳出第二個 alert('簽核失敗：...')。
            assert len(dialogs) == 1, f"簽核流程跳出未預期的額外對話框：{dialogs}"

            status_value = page2.locator("select.status-select-admin").input_value()
            assert status_value == "已送出", f"簽核後狀態應為已送出，實際: {status_value!r}"
            ctx2.close()
        finally:
            browser.close()


@pytest.mark.e2e
def test_inventory_purchase_suggestions_modal_smoke(live_server, make_user):
    """庫存頁「採購建議」按鈕→開啟 Modal→正確顯示低於安全庫存的料號與建議採購量
    （2026-09-07，架構地圖 §6.6）。後端邏輯已有 test_purchase_suggestions_2026_09_07.py
    完整涵蓋，這裡只驗證前端按鈕/Modal 這條路徑真的能點得通、資料有正確渲染出來
    ——純 API 測試看不出 x-show/Modal 綁定寫錯這類純前端問題。"""
    username, password = make_user(username="e2e_inv_admin", role="admin")

    import db
    conn = db.get_db()
    now = "2026-01-01T00:00:00"
    conn.execute(
        "INSERT INTO parts (part_no, name, brand, unit, cost, category, safety_stock, active, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,1,?,?)",
        ("E2E-LOWSTOCK", "E2E 測試低庫存料件", "", "台", 100, "其他", 10, now, now),
    )
    conn.commit()
    conn.close()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            _login(page, live_server, username, password)

            page.goto(f"{live_server}/pages/inventory.html")
            page.wait_for_selector('button:has-text("採購建議")', timeout=10000)
            page.click('button:has-text("採購建議")')

            # 底下主表格本來就會列出這個料號（未篩選），"E2E-LOWSTOCK" 文字在
            # Modal 開啟前就已經存在於畫面 DOM 裡——必須把查詢範圍限定在
            # 「採購建議」那個 Modal 本身內，不能用整頁的裸文字搜尋，否則會誤判
            # 成模組還沒載入資料就通過。
            modal = page.locator(".modal-box", has_text="採購建議")
            modal.locator("tr", has_text="E2E-LOWSTOCK").wait_for(timeout=10000)
            row_text = modal.locator("tr", has_text="E2E-LOWSTOCK").inner_text()
            assert "15" in row_text, f"應建議補到黃燈門檻 ceil(10*1.5)=15，實際列內容: {row_text!r}"
        finally:
            browser.close()
