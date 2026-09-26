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
import json
import os
import tempfile
import threading
import time

import pyotp
import pytest

pytest.importorskip("playwright.sync_api")

import uvicorn
from tests._e2e_login import inject_login  # noqa: E402
from tests._ports import free_safe_port


def _sync_extra_to_table(conn, quote_no):
    """把剛種進 data_json 的 settlement.extraItems 搬進 case_extra_expenses。

    2026-09-11（migration v75）之後額外支出住在獨立資料表，data_json 裡那份只是
    唯讀備份、財務總覽不再讀它。用 migration 自己那支搬移函式，欄位對應才不會漂移。"""
    import db as _db
    import json as _json
    row = conn.execute(
        "SELECT data_json, sales_person FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    if not row:
        return
    _db._move_extra_items_for_quote(
        conn, quote_no, _json.loads(row["data_json"] or "{}"), row["sales_person"] or "")


def _login(page, base_url, username, password):
    return inject_login(page, base_url, username, password)


@pytest.mark.e2e
def test_login_create_submit_approve_smoke(live_server, make_user, e2e_browser):
    """golden path：建立者登入 → 新增報價單（客戶/案件/一項品項）→ 送出審核
    → 另一位 superadmin 登入 → 開啟同一張報價單 → 簽核 → 狀態變成「已送出」。
    無簽核流程設定時系統規則是「禁止申請人自簽」，所以刻意用兩個不同帳號。

    簽核解析走 `helpers/tiered_approval.py::resolve_submitter_org_chain()`
    （2026-09-15 前叫 resolve_submitter_manager_chain()，當時回傳單一位簽核人）
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

    browser = e2e_browser
    # ── 建立者：登入 → 新增報價單 → 送出審核 ──────────────────────
    ctx1 = browser.new_context()
    page1 = ctx1.new_page()
    # 建立端跳出的對話框訊息要留著：送審失敗時 confirmSubmit() 會 alert
    # 『送出審核失敗…』，原本一律 accept 掉，等於把最關鍵的線索丟了。
    _p1_dialogs = []
    page1.on("dialog", lambda d: (_p1_dialogs.append(d.message), d.accept()))
    _p1_console = []
    page1.on("console", lambda m: _p1_console.append(f"[{m.type}] {m.text[:160]}"))

    # 2026-09-10 追加：建立端（page1）的取號／建立往來也要留證。原本只監測
    # approver 那一頁，抓到「approver 開了 002、資料庫只有 001」時無從判斷
    # 這個 002 是怎麼跑到畫面上的。這裡記下每一次 next-quote-no 與
    # POST /api/quotations 的請求與回應，只在下面失敗時才印。
    _p1 = []

    def _on_p1_response(resp):
        u = resp.url
        if "/api/" in u and "/static/" not in u:
            body = ""
            if "next-quote-no" in u or u.rstrip("/").endswith("/api/quotations"):
                try:
                    body = (resp.text() or "")[:200]
                except Exception as e:
                    body = f"<讀取失敗 {e}>"
            req_body = ""
            try:
                req_body = (resp.request.post_data or "")[:120]
            except Exception:
                pass
            _p1.append({
                "t": time.time(), "method": resp.request.method,
                "url": u.split("/api/")[-1], "status": resp.status,
                "req": req_body, "resp": body,
            })

    _p1_sent = []

    def _on_p1_request(req):
        if "/api/" in req.url and "/static/" not in req.url:
            _p1_sent.append((time.time(), req.method, req.url.split("/api/")[-1]))

    page1.on("request", _on_p1_request)
    page1.on("response", _on_p1_response)
    _login(page1, live_server, creator_user, creator_pw)

    page1.goto(f"{live_server}/pages/quotation-form.html")
    page1.fill('input[x-model="q.customerName"]', "PW 測試客戶")
    page1.fill('input[x-model="q.projectName"]', project_name)
    page1.locator('textarea[x-model="item.description"]').first.fill("測試品項 A")

    page1.click('button:has-text("申請送出審核")')
    page1.click('button:has-text("確認送出")')
    # 2026-09-10：原本只等「有內容」，但畫面在還沒拿到號碼時會顯示
    # 「（儲存後自動編號）」佔位字（見 quotation-form.html，取代舊版
    # 「拿不到號就寫死 MQ-{ym}-001」的危險行為），那也算有內容，會讓這裡
    # 在真正的號碼回填前就往下走。改成等真正的單號出現。
    # 等「存檔真的完成」而不是等畫面上出現 MQ- 字樣：載入時取到的單號一開始
    # 就在畫面上，等文字等於沒等，會在存檔回應回來前就把（可能不是最終的）
    # 號碼讀走，然後 ctx1.close() 把還在飛的 POST 一起中止掉——approver 就
    # 被送去一張不存在的單。2026-09-10 用測試診斷抓到，改成等 Alpine 的
    # isNewRecord 翻成 false（confirmSubmit() 只有在存檔成功後才會設）。
    #
    # 45 秒不是隨便給的：db.py 的 `sqlite3.connect(timeout=30)` 表示任何一次
    # 寫入在鎖被佔住時最多會等 30 秒。建立報價單在 commit 之後還要再寫
    # notification／audit_log／module activity 各自開新連線，只要此時有背景
    # 排程（月報、逾期檢查等，整個 pytest session 期間都在跑）正在寫，
    # 這支 POST 就會卡滿一輪 30 秒才回來。時限必須容得下它，否則測試會在
    # 「其實只是慢」的情況下報失敗。
    page1.wait_for_function(
        "() => { const el = document.querySelector('[x-data]');"
        " const d = el && window.Alpine && Alpine.$data(el);"
        " return d && d.isNewRecord === false"
        "   && (d.q && d.q.quoteNo || '').includes('MQ-'); }",
        timeout=45000,
    )

    quote_no = page1.locator(".form-quote-no").inner_text().strip()
    # ctx1 等一下就關了，先把建立端的最終狀態留下來給診斷用
    try:
        _p1_state = page1.evaluate(
            "() => { const el = document.querySelector('[x-data]');"
            " const d = el && window.Alpine && Alpine.$data(el); if (!d) return null;"
            " return { quoteNo: d.q && d.q.quoteNo, status: d.q && d.q.status,"
            "   isNewRecord: d.isNewRecord }; }")
    except Exception as _e:
        _p1_state = f"<讀取失敗 {_e}>"
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
    # ✅ 2026-09-10 根因已找到（先前這裡寫「根因還沒有抓到」）。
    # ⚠️ 更正：本註解一度寫「SQLite WAL 鎖等待那個推測方向是錯的」——
    # 那句才是錯的。後續用測試診斷追下去，鎖等待確實是其中一半的原因，
    # 原作者的直覺是對的，只是當時沒有證據。
    #
    # 真正的原因在前端：quotation-form.html 載入時會非同步打
    # /api/next-quote-no 取號，那個回應可能在使用者按下送審**之後**才回來，
    # 直接指派就把存檔回應剛回填的真正單號蓋成新 peek 到的下一號。畫面顯示
    # MQ-YYYYMM-002、資料庫其實只有 001，於是這裡的 approver 照畫面上的號碼
    # 開，開到一張不存在的單，自然等不到簽核按鈕。
    # 已用可控實驗重現（修復前 6 次中 2 次、修復後 8 次 0 次），完整 e2e
    # 連跑 6 輪全綠。修法見 quotation-form.html 該處的 `_peeked` 守門。
    #
    # 時限維持 30 秒即可（不需要再往上加）。若日後又在這裡逾時，先看下面的
    # 診斷 dump 印出的 `quotation-form.html?id=` 與 log 裡的
    # `approval tiers load — quote=` 是不是同一個單號 —— 不同就是同類的
    # 單號競態又回來了，相同才是別的問題。
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

        # 2026-09-10 追加：上面那幾項只能看出「頁面有沒有載入」，分辨不了
        # 三種不同的失敗原因。這三塊各自對應一種，看完就知道該往哪查：
        #   (a) 資料庫裡到底有哪幾張單、各自有沒有簽核層級
        #       → 單號對不上＝單號競態；單號對但 tiers 空＝簽核解析出問題
        #   (b) approver 這一頁的 Alpine 狀態（實際載到哪張單、狀態為何）
        #       → 跟 (a) 一比就知道是「開錯單」還是「開對單但沒渲染」
        #   (c) 頁面上真的存在哪些按鈕
        #       → 全部按鈕都在只差這一顆，才是純渲染／權限問題
        print("--- (0) 建立端 page1 的取號／建立往來 ---")
        _t0 = _p1[0]["t"] if _p1 else time.time()
        for _e1 in _p1:
            print(f"  +{_e1['t'] - _t0:6.2f}s  {_e1['method']:<5} {_e1['url']:<28} "
                  f"{_e1['status']}")
            if _e1["req"]:
                print(f"           req : {_e1['req']}")
            print(f"           resp: {_e1['resp']}")
        print(f"  page1 最終狀態: {_p1_state}")
        print(f"  page1 讀到的單號: {quote_no!r}")
        # 有送出但沒收到回應的請求＝卡在飛行中，這是「沒有 POST 紀錄」的另一種解釋
        _answered = {(e["method"], e["url"]) for e in _p1}
        _pending = [x for x in _p1_sent if (x[1], x[2]) not in _answered]
        print(f"  page1 送出但未收到回應的請求: "
              f"{[(m, u) for _t, m, u in _pending] or '（無）'}")
        print(f"  page1 對話框: {_p1_dialogs}")
        print("  page1 console:")
        for _c1 in _p1_console[-15:]:
            print(f"    {_c1}")

        print(f"--- (a) 資料庫實際內容（approver 開的是 {quote_no}）---")
        try:
            import db as _db
            _c = _db.get_db()
            try:
                for _r in _c.execute(
                    "SELECT quote_no, status, "
                    "json_extract(data_json,'$.approval.tiers') AS tiers, "
                    "json_extract(data_json,'$.approval.status') AS appr_status "
                    "FROM quotations ORDER BY quote_no"
                ).fetchall():
                    _t = _r["tiers"]
                    _n = len(json.loads(_t)) if _t else 0
                    _mark = " ←approver 開的就是這張" if _r["quote_no"] == quote_no else ""
                    print(f"  {_r['quote_no']}  status={_r['status']!r} "
                          f"approval={_r['appr_status']!r} tiers={_n}{_mark}")
                print("  quote_seq:", [dict(_x) for _x in
                                        _c.execute("SELECT * FROM quote_seq")])
                print("  quotations 建立時間:", [
                    (_x["quote_no"], _x["created_at"]) for _x in
                    _c.execute("SELECT quote_no, created_at FROM quotations")])
            finally:
                _c.close()
        except Exception as _e:
            print(f"  (讀資料庫失敗: {_e})")

        print("--- (b) approver 頁面的 Alpine 狀態 ---")
        try:
            _st = page2.evaluate(
                "() => { const el = document.querySelector('[x-data]');"
                " const d = el && window.Alpine && Alpine.$data(el); if (!d) return null;"
                " return { quoteNo: d.q && d.q.quoteNo, status: d.q && d.q.status,"
                "   isNewRecord: d.isNewRecord,"
                "   tiers: (d.q && d.q.approval && d.q.approval.tiers || []).length,"
                "   canApprove: typeof d.canApprove === 'boolean' ? d.canApprove : undefined }; }")
            print(f"  {_st}")
        except Exception as _e:
            print(f"  (讀 Alpine 狀態失敗: {_e})")

        print("--- (c) 頁面上現有的按鈕 ---")
        try:
            _btns = page2.evaluate(
                "() => [...document.querySelectorAll('button')]"
                ".filter(b => b.offsetParent !== null)"
                ".map(b => (b.innerText || '').trim().slice(0, 20)).filter(Boolean)")
            print(f"  {_btns}")
        except Exception as _e:
            print(f"  (讀按鈕失敗: {_e})")

        try:
            _shot = os.path.join(tempfile.gettempdir(),
                                 f"e2e_smoke_fail_{int(time.time())}.png")
            page2.screenshot(path=_shot, full_page=True)
            print(f"--- 失敗當下截圖：{_shot}")
        except Exception as _e:
            print(f"  (截圖失敗: {_e})")
        raise
    page2.click('button:has-text("預覽後簽核")')
    page2.wait_for_selector('button:has-text("確認簽核")', timeout=20000)
    # PERF #6：原本固定等 2.5 秒 ⇒ 等簽核請求回來，再等狀態欄更新（失敗時的第二個 alert 也在回應之後才跳）
    with page2.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/approve"),
                               timeout=20000):
        page2.click('button:has-text("確認簽核")')
    try:
        page2.wait_for_function(
            "() => { const s = document.querySelector('select.status-select-admin'); return s && s.value === '已送出' }",
            timeout=10000)
    except Exception:
        pass   # 判決留給下面有說明的斷言
    page2.evaluate("() => new Promise(r => setTimeout(r, 0))")   # 讓回應後同步排入的 alert 先跑
    # 第一個對話框是預期中的「確認簽核通過此報價單？」confirm()；若簽核 API
    # 失敗，approveQuote() 會再跳出第二個 alert('簽核失敗：...')。
    assert len(dialogs) == 1, f"簽核流程跳出未預期的額外對話框：{dialogs}"

    status_value = page2.locator("select.status-select-admin").input_value()
    assert status_value == "已送出", f"簽核後狀態應為已送出，實際: {status_value!r}"
    ctx2.close()


@pytest.mark.e2e
def test_login_qr_approve_smoke(live_server, make_user, e2e_browser, client):
    """手機掃 QR 核准登入 smoke test（2026-09-08，見 routers/auth.py 的
    login_qr_info/login_qr_approve/login_qr_status 與 login-qr-approve.html）。
    桌面登入頁顯示 QR 後，模擬手機另開一個獨立瀏覽器 context 開啟確認頁面、
    輸入密碼核准，桌面應該在輪詢週期內自動偵測到核准並完成登入，全程不需要
    在桌面上做任何其他操作（不輸入驗證碼、不用按任何按鈕）。"""
    username, password = make_user(role="superadmin")

    # 前置設定：用 Playwright 的 APIRequestContext 直接呼叫 API 幫這個帳號
    # 啟用 TOTP（不開瀏覽器頁面——這是測試前置設定，不是測試本身要驗證的路徑）。
    # PERF #5：原本用 Playwright 的 APIRequestContext；改用同一份庫的 client（共用伺服器也經過同一個 client）。
    login_resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert login_resp.status_code == 200, login_resp.text
    headers = {"Authorization": f"Bearer {login_resp.json()['token']}"}
    setup_resp = client.post("/api/auth/totp/setup", headers=headers)
    assert setup_resp.status_code == 200, setup_resp.text
    secret = setup_resp.json()["secret"]
    enable_resp = client.post("/api/auth/totp/enable", headers=headers,
                              json={"code": pyotp.TOTP(secret).now()})
    assert enable_resp.status_code == 200, enable_resp.text

    browser = e2e_browser   # PERF #5：共用瀏覽器
    try:
        # ── 桌面：輸入帳密，進入兩步驟驗證畫面，應該看到並列的 QR code ──
        ctx_desktop = browser.new_context()
        page_desktop = ctx_desktop.new_page()
        page_desktop.goto(f"{live_server}/pages/login.html")
        page_desktop.fill('input[x-model="username"]', username)
        page_desktop.fill('input[x-model="password"]', password)
        page_desktop.click('button:has-text("登入")')
        page_desktop.wait_for_selector('img[width="160"]', timeout=10000)

        # 真實情境是手機相機掃描 QR 圖片解碼出網址；這裡直接讀 Alpine 元件
        # 內部狀態拿 challengeToken 達到等價效果，不需要真的做影像辨識。
        challenge = page_desktop.evaluate(
            "window.Alpine.$data(document.body).challengeToken"
        )
        assert challenge, "桌面頁面沒有拿到 challengeToken，QR 流程沒有正確啟動"

        # ── 手機：另開一個完全獨立的 context（模擬另一台裝置），開確認頁面 ──
        ctx_phone = browser.new_context()
        page_phone = ctx_phone.new_page()
        # ⚠️ 2026-09-22 §8 FX22：challenge 改走 **URL fragment**。
        # ☠️ 原本是 `?challenge=` ⇒ 手機一掃就是
        #    `GET /pages/login-qr-approve.html?challenge=xxx`
        #    ⇒ **照樣被 access log 記一筆**。
        # 🔑 而那是 B 發現的第三個洩漏點：**只改兩支 API 的話，
        #    我們會宣稱洩漏堵住了，而它沒有。**
        # 📌 `#` 後面的東西**瀏覽器不會送給伺服器**。
        page_phone.goto(
            f"{live_server}/pages/login-qr-approve.html#challenge={challenge}")
        page_phone.wait_for_selector('input[type="password"]', timeout=10000)
        page_phone.fill('input[type="password"]', password)
        page_phone.click('button:has-text("核准登入")')
        page_phone.wait_for_selector('text=已核准登入', timeout=10000)
        ctx_phone.close()

        # ── 桌面：不做任何操作，應該在輪詢週期內（每 2 秒一次）自動完成登入 ──
        page_desktop.wait_for_url(lambda url: url.endswith("/index.html"), timeout=10000)
        ctx_desktop.close()
    finally:
        browser.close()


@pytest.mark.e2e
def test_case_finance_summary_smoke(live_server, make_user, e2e_browser):
    """案件管理－財務 Tab「應收應付總覽」smoke test（2026-09-09，見
    modules/case/api/quotations.py::get_finance_summary()）。後端彙總邏輯已有
    test_case_finance_summary_2026_09_09.py 完整涵蓋，這裡只驗證前端這一區
    真的渲染得出來——新增的 Alpine getter（finReceivable()/finPayable()）在
    financeSummary 還是 null 時被 template 讀到會直接整頁炸掉，這正是純 API
    測試看不出來、又只會在瀏覽器裡才發生的那類問題。"""
    import json

    username, password = make_user(username="e2e_fin_admin", role="superadmin")

    import db
    conn = db.get_db()
    now = "2026-01-01T00:00:00"
    data_json = json.dumps({
        "caseRecord": {"payment": {"items": [
            {"id": 1, "type": "訂金款", "pct": 40, "amount": 40000, "received": True,
             "receivedAt": "2026-03-05T00:00:00", "actualAmount": None, "feeAmount": 0},
            {"id": 2, "type": "尾款", "pct": 60, "amount": 60000, "received": False},
        ]}},
        # 刻意用「草稿」精算：使用者的作業順序是支出當下就先填、案件結束才做
        # 精算完結，總覽必須照樣列出來（含單號），不能等完結才顯示
        "settlement": {"status": "draft", "extraItems": [
            {"category": "運費", "description": "吊車運費", "docNo": "AB12345678",
             "totalCost": 8000, "expenseDate": "2026-04-02"},
        ]},
    }, ensure_ascii=False)
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
        "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("MQ-E2EFIN-001", "已送出", "E2E 財務客戶", "E2E 財務專案", 100000, 95238,
         data_json, now, now, "已成案"),
    )
    _sync_extra_to_table(conn, "MQ-E2EFIN-001")
    conn.commit()
    conn.close()

    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, username, password)

    page.goto(f"{live_server}/pages/case-management.html?q=MQ-E2EFIN-001")
    page.wait_for_selector('button.cm-tab:has-text("財務")', timeout=10000)
    # 必須等 selectCase() 整串 async 工作跑完再點分頁：它在兩個 await
    # 之後才設 activeTab='biz'，分頁列卻在那之前就已經渲染出來，太早點
    # 「財務」會被那行覆蓋回「案件資訊」（既有行為，非本功能造成）。
    # 用 state="attached" 等總覽區塊「進入 DOM」（x-if 在 financeSummary
    # 有值時才渲染，而 loadFinanceSummary() 排在 selectCase() 尾端、
    # activeTab='biz' 那行之後）——此時分頁還沒點開所以它是隱藏的，不能
    # 用預設的 visible 條件。刻意不從 Alpine.$data(querySelector('[x-data]'))
    # 讀狀態：sidebar.js 會另外注入自己的 x-data 元件，DOM 裡第一個
    # [x-data] 不保證是案件管理元件，實測會間歇性抓錯而提早往下跑。
    page.wait_for_selector("#fin-ar-ap-overview", state="attached", timeout=10000)
    page.click('button.cm-tab:has-text("財務")')

    # 斷言一律鎖定總覽區塊本身，不要用整頁 body 文字：案件標題列的 KPI
    # 跟左側案件清單卡本來就會顯示同一批金額（合約金額/已收款/未收款），
    # 用整頁搜尋會在財務分頁根本沒展開的情況下也「矇對」而假性通過——
    # 這正是這題第一版寫法踩到的坑。
    # 分頁沒切過去就再點一次（最多 3 次）：上面的 attached 等待已經排除
    # 大部分競態，但頁面初始化期間仍有其他 async 工作在跑，實測整套 e2e
    # 連跑時偶發點擊沒生效。這裡要驗證的是「總覽渲染得對不對」，不是
    # 「一次點擊能不能贏過頁面初始化」，所以容忍重點一次而不是讓整題紅掉。
    overview = page.locator("#fin-ar-ap-overview")
    for _ in range(3):
        try:
            overview.wait_for(state="visible", timeout=4000)
            break
        except Exception:
            page.click('button.cm-tab:has-text("財務")')
    else:
        overview.wait_for(state="visible", timeout=4000)
    page.wait_for_function(
        "() => document.querySelector('#fin-ar-ap-overview')"
        "?.innerText.includes('NT$ 60,000')",
        timeout=10000,
    )
    text = overview.inner_text()
    assert "NT$ 100,000" in text, f"應收總額應顯示 NT$ 100,000，實際: {text!r}"
    assert "NT$ 40,000" in text, f"已收應顯示 NT$ 40,000，實際: {text!r}"
    assert "未收" in text and "未匯款" in text, \
        f"應收/應付兩組 KPI 標籤都要在，實際總覽文字: {text!r}"

    # 精算額外支出明細（草稿精算也要列，含單號）：這一段專門防「Alpine
    # getter 沒定義」這種只有瀏覽器裡才看得出來的錯——x-show 呼叫到不存在
    # 的方法時 Alpine 只會靜靜當成 false，按鈕整個不出現，後端測試全綠也
    # 完全看不出來（2026-09-09 實際犯過一次，是靠人工截圖才發現）。
    overview.locator('button:has-text("精算額外支出明細")').click()
    # 點開後要等明細列真的渲染出來再讀文字：Alpine 的 x-show 切換不是同步
    # 的，click() 一回來就 inner_text() 會讀到還沒展開的內容
    overview.locator("text=吊車運費").wait_for(timeout=5000)
    detail_text = overview.inner_text()
    assert "AB12345678" in detail_text, \
        f"草稿精算的額外支出單號要顯示，實際總覽文字: {detail_text!r}"
