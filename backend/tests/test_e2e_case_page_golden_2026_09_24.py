"""案件管理頁行為 golden（CM12 前端拆分重構的守門，2026-09-24）。

CM12 是純重構：拆檔、集中重設狀態、樣式抽離，不可以改變使用者看到的東西與送出的請求。
這支題用一件多狀態案件＋數件清單案件，依序走過清單／看板／矩陣、打開案件、每個分頁與執行子分頁、
「更多」選單、結案檢查、多選，記下每一步的可見文字與整段期間的 API 請求（多重集合，不看順序）。
GOLDEN 檔在重構前的 master（58836e3）上錄：GOLDEN_WRITE=1 pytest …
正規化：今天的日期、相對天數（N 天前／後、逾期 N 天）；請求的查詢參數排序。
"""
import collections
import json
import os
import pathlib
import re
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlsplit

import pytest

pytest.importorskip("playwright.sync_api")

GOLDEN = pathlib.Path(__file__).with_name("golden_case_page_2026_09_24.json")
NO = "MQ-GOLD-001"
DATA_JS = "Alpine.$data(document.querySelector('[x-data]'))"
T0 = "2026-03-01T09:00:00"


def _seed():
    import db
    conn = db.get_db()
    try:
        vid = conn.execute("INSERT INTO vendor_contractors (name, address, active, created_at) VALUES (?,?,?,?)",
                           ("金牌承攬", "台中市西屯區", 1, T0)).lastrowid
        stages = []
        for i, (label, done, due) in enumerate([("訂單確認", 1, "2026-03-05"), ("叫料出貨", 0, "2020-01-01"),
                                               ("施工安裝", 0, "2099-06-30"), ("尾款結清", 0, "")]):
            sid = conn.execute(
                "INSERT INTO case_stages (quote_no, label, sort_order, done, done_at, due_date, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)", (NO, label, i, done, "2026-03-05" if done else "", due, T0, T0)).lastrowid
            stages.append({"id": sid, "label": label, "done": bool(done), "dueDate": due,
                           "doneAt": "2026-03-05" if done else ""})
        cr = {
            "contract": {"deliveryAddress": "台中市西屯區台灣大道三段99號", "deliveryTerms": "工地交貨",
                         "contactName": "林先生", "contactPhone": "0912-000-000", "note": "合約備註"},
            "payment": {"items": [
                {"id": 1, "type": "訂金款", "pct": 30, "received": True, "receivedAt": "2026-03-10",
                 "invoiceNo": "AB12345678", "invoiceDate": "2026-03-10", "expectedReceiptDate": "2026-03-10",
                 "note": "已收"},
                {"id": 2, "type": "交貨款", "pct": 30, "received": False, "receivedAt": "",
                 "expectedReceiptDate": "2020-02-01", "invoiceNo": "", "note": ""},
                {"id": 3, "type": "驗收款", "pct": 40, "received": False, "receivedAt": "",
                 "expectedReceiptDate": "2099-12-31", "invoiceNo": "", "note": ""}]},
            "materials": [{"id": 11, "name": "網路交換器", "qty": 2, "unit": "台", "ordered": True, "arrived": False,
                           "model": "SW-24", "devices": []}],
            "roles": {"filler": "", "sales": "", "executor": ""},
            "stages": stages,
        }
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
            " created_at, updated_at, deal_tag, quote_date, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (NO, "已送出", "金牌客戶", "監控系統建置", 105000, 100000,
             json.dumps({"dealTag": "已成案", "caseRecord": cr, "settlement": {"status": "draft"}},
                        ensure_ascii=False), T0, T0, "已成案", "2026-03-01", "golden_su"))
        for i, (tag, cust) in enumerate([("已成案", "乙客戶"), ("已結案", "丙客戶"), ("已成案", "丁客戶")]):
            conn.execute(
                "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json,"
                " created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"MQ-GOLD-10{i}", "已送出", cust, f"專案{i}", 1000 * (i + 1), 952 * (i + 1),
                 json.dumps({"dealTag": tag}, ensure_ascii=False), T0, T0, tag, f"2026-02-0{i + 1}"))
        conn.execute(
            "INSERT INTO shipping_notes (note_no, quote_no, status, ship_date, customer_name, project_name,"
            " delivery_address, items_json, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("SN-GOLD-1", NO, "草稿", "2026-03-12", "金牌客戶", "監控系統建置", "台中市西屯區",
             json.dumps([{"name": "網路交換器", "qty": 2, "unit": "台"}], ensure_ascii=False), "{}", T0, T0))
        conn.execute(
            "INSERT INTO completion_notes (note_no, quote_no, status, customer_name, project_name, data_json,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("CN-GOLD-1", NO, "草稿", "金牌客戶", "監控系統建置", "{}", T0, T0))
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, vendor_id, dispatch_date, scope, items_json, personnel_json,"
            " total_amount, tax_rate, status, notes, created_by, created_at, updated_at, files_json, invoice_files_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (NO, vid, "2026-03-08", "管線施工", json.dumps([{"name": "配管", "qty": 1, "price": 8000}],
                                                           ensure_ascii=False),
             "[]", 8000, 5, "進行中", "派工備註", "golden_su", T0, T0, "[]", "[]"))
        conn.execute(
            "INSERT INTO case_extra_expenses (quote_no, category, description, total_cost, status, expense_date,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (NO, "運費", "吊車運費", 3500, "待審核", "2026-03-09", T0, T0))
        conn.execute("INSERT INTO case_updates (quote_no, author, content, type, created_at) VALUES (?,?,?,?,?)",
                     (NO, "現場同仁", "今天完成配管", "comment", "2026-03-08 17:30:00"))
        conn.execute(
            "INSERT INTO invoice_vouchers (voucher_no, quote_no, scope, status, amount, snapshot_json, data_json,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("IV-GOLD-1", NO, "amount", "已核准", 31500, "{}", "{}", T0, T0))
        conn.execute(
            "INSERT INTO payment_requests (request_no, quote_no, scope, stage, status, amount, terms_json,"
            " snapshot_json, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("PR-GOLD-1", NO, "amount", "訂金款", "已核准", 31500, "{}", "{}", "{}", T0, T0))
        conn.commit()
    finally:
        conn.close()


def _norm(text: str) -> str:
    today = datetime.now()
    for d in (today, today - timedelta(days=1), today + timedelta(days=1)):
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y/%-m/%-d" if os.name != "nt" else "%Y/%#m/%#d"):
            text = text.replace(d.strftime(fmt), "<DAY>")
        text = text.replace(d.strftime("%m-%d"), "<MD>").replace(d.strftime("%m/%d"), "<MD>")
    text = re.sub(r"\d+\s*天(前|後|內)", r"<N>天\1", text)
    text = re.sub(r"(逾期|已逾|剩|還有)\s*\d+\s*天", r"\1<N>天", text)
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _norm_url(method, url):
    u = urlsplit(url)
    q = sorted(parse_qsl(u.query, keep_blank_values=True))
    q = "&".join(f"{k}={v}" for k, v in q)
    return _norm(f"{method} {u.path}" + (f"?{q}" if q else ""))




class _Net:
    """追蹤在途請求：每一步做完等到 600ms 內沒有新請求、也沒有在途的才截圖（文字）。"""

    def __init__(self, page):
        self.inflight = 0
        self.last = time.time()
        self.calls = collections.Counter()
        page.on("request", self._req)
        page.on("requestfinished", self._done)
        page.on("requestfailed", self._done)

    # 側欄／通知／在線狀態的輪詢與案件頁無關，而且次數隨執行時間漂移 ⇒ 不記
    _IGNORE = ("/api/auth/me", "/api/build-info", "/api/notifications", "/api/online-users",
               "/api/approval-queue/count", "/api/reads/module-counts", "/api/edit-presence")

    def _req(self, r):
        if "/api/" in r.url:
            self.inflight += 1
            self.last = time.time()
            if not any(x in r.url for x in self._IGNORE):
                self.calls[_norm_url(r.method, r.url)] += 1

    def _done(self, r):
        if "/api/" in r.url:
            self.inflight -= 1
            self.last = time.time()

    def settle(self, page, quiet=0.6, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            page.wait_for_timeout(100)
            if self.inflight <= 0 and time.time() - self.last >= quiet:
                return
        raise AssertionError("網路一直沒有靜下來")


def _text(page, selector):
    return _norm(page.evaluate(
        "(s) => [...document.querySelectorAll(s)].filter(e => e.offsetParent !== null || e.getClientRects().length)"
        ".map(e => e.innerText).join('\\n----\\n')", selector))


#: 在 ui.js 設定 window.MotrixUI 的那一刻包起 confirm／prompt：立刻「取消」並記錄
_AUTO_DISMISS_MOTRIX_UI = """
(() => {
  window.__goldenDialogs = []
  let real
  Object.defineProperty(window, 'MotrixUI', {
    configurable: true,
    get() { return real },
    set(v) {
      real = Object.assign({}, v, {
        confirm: (m) => { window.__goldenDialogs.push(['confirm', String(m)]); return Promise.resolve(false) },
        prompt: (m) => { window.__goldenDialogs.push(['prompt', String(m)]); return Promise.resolve(null) },
      })
    },
  })
})()
"""


def _record(live_server, make_user, e2e_browser):
    u = make_user(username="golden_su", role="superadmin")
    _seed()
    steps = {}
    browser = e2e_browser
    page = browser.new_context(viewport={"width": 1440, "height": 1000}).new_page()
    page.on("dialog", lambda d: d.dismiss())
    # CM12 P4：對話框逐步改為 MotrixUI（非原生）。golden 錄製時的語意是「一律取消」——
    # 對 MotrixUI 用同一個語意：confirm 立刻回 false、prompt 立刻回 null（與原生 dismiss 相同），
    # 呼叫記在 window.__goldenDialogs。原生那一行留到 B 包也換完為止。
    page.add_init_script(_AUTO_DISMISS_MOTRIX_UI)
    # golden 是「重構前」用登入頁錄的：登入流程要一致，否則 API 請求清單會多出 index 上才會發的請求
    page.goto(f"{live_server}/pages/login.html")
    page.fill('input[x-model="username"]', u[0])
    page.fill('input[x-model="password"]', u[1])
    page.click('button:has-text("登入")')
    page.wait_for_url(lambda url: url.endswith("/index.html"), timeout=15000)
    net = _Net(page)
    page.goto(f"{live_server}/pages/case-management.html")
    page.wait_for_function(f"() => {DATA_JS} && {DATA_JS}.session && {DATA_JS}.session.token"
                           f" && !{DATA_JS}.loading && {DATA_JS}.caseCounts", timeout=20000)
    net.settle(page)
    steps["01 清單"] = _text(page, ".cm-list")
    page.click(".cm-view-toggle button:text-is('看板'):visible")
    net.settle(page)
    steps["02 看板"] = _text(page, ".cm-list")
    page.click(".cm-view-toggle button:text-is('矩陣'):visible")
    net.settle(page)
    steps["03 矩陣"] = _text(page, "main")
    page.click(".cm-view-toggle button:text-is('清單'):visible")
    net.settle(page)
    page.click(f".cm-card[data-quote-no='{NO}']")
    page.wait_for_function(f"() => {DATA_JS}.selected && {DATA_JS}.selected.quote_no === '{NO}'",
                           timeout=15000)
    net.settle(page)
    steps["04 標頭"] = _text(page, ".cm-header")
    tabs = page.locator(".cm-tabs > .cm-tab")
    labels = [t.strip() for t in tabs.all_inner_texts()]
    steps["05 分頁列"] = "\n".join(labels)
    for i, label in enumerate(labels):
        btn = tabs.nth(i)
        if not btn.is_visible():
            continue
        btn.click()
        net.settle(page)
        key = re.sub(r"\d+$", "", label).strip()
        steps[f"06 分頁 {i:02d} {key}"] = _text(page, ".cm-body")
        if page.evaluate(f"() => {DATA_JS}.activeTab") == "exec":
            sub_js = ("(i) => { const b = [...document.querySelectorAll('button.cm-tab')]"
                      ".filter(e => (e.getAttribute('@click') || '').startsWith('execSubTab'));"
                      " if (i == null) return b.map(e => e.innerText.trim()); b[i].click() }")
            sub_labels = page.evaluate(sub_js)
            for j, sl in enumerate(sub_labels):
                page.evaluate(sub_js, j)
                net.settle(page)
                steps[f"07 執行子分頁 {j:02d} {sl}"] = _text(page, ".cm-body")
            page.evaluate(sub_js, 0)
            net.settle(page)
            page.locator(".stage-segbar__seg").nth(1).click()
            net.settle(page)
            steps["08 展開第二階段"] = _text(page, ".cm-body")
    page.click("[data-testid=cm-more]")
    page.locator(".cm-more__menu").wait_for(state="visible", timeout=5000)
    steps["09 更多選單"] = _text(page, ".cm-more__menu")
    page.keyboard.press("Escape")
    page.evaluate(f"() => {DATA_JS}.closeCaseAction()")
    page.locator("[data-testid=close-check]").wait_for(state="visible", timeout=10000)
    net.settle(page)
    steps["10 結案檢查"] = _text(page, "[data-testid=close-check]")
    page.keyboard.press("Escape")
    page.click("[data-testid=batch-toggle]")
    page.locator(f".cm-card[data-quote-no='{NO}'] [data-testid=batch-check]").click()
    steps["11 多選"] = _text(page, "[data-testid=batch-bar]")
    net.settle(page)
    steps["99 API 請求"] = "\n".join(f"{k} ×{v}" for k, v in sorted(net.calls.items()))
    return steps


@pytest.mark.e2e
def test_case_page_behaviour_matches_golden(live_server, make_user, e2e_browser):
    got = _record(live_server, make_user, e2e_browser=e2e_browser)
    if os.environ.get("GOLDEN_WRITE") == "1":
        GOLDEN.write_text(json.dumps(got, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        pytest.skip(f"已寫入 {GOLDEN.name}（{len(got)} 步）")
    exp = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert sorted(got) == sorted(exp), (sorted(set(got) ^ set(exp)))
    for k in sorted(exp):
        assert got[k] == exp[k], f"「{k}」與重構前不同"
