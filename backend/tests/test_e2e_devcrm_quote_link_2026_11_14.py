"""T86 業務開發→報價單（報價單這一側）：quotation-form.html 接收 ?customer=&project=&type=&devCase=，
預填客戶與案件名稱、選好報價單／估價單，第一次存檔成功後呼叫既有 PATCH /api/dev-cases/<id>/convert；
連結失敗要有看得見的橫幅（不准靜默失敗），可重試。不改後端、不加端點。"""
import re
from pathlib import Path

import pytest

from tests._requires import requires_module  # noqa: E402

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402

pytestmark = requires_module("crm", "本檔的題打業務開發（/api/dev-cases）")

_MAKE_USER_DEFAULT_ROLE = "superadmin"
ROOT = Path(__file__).resolve().parents[2]
DATA_JS = "Alpine.$data(document.body)"


# ── 靜態釘：業務開發送出的網址參數，報價單頁都要有讀（避免兩頁各改各的，出現「說預填卻沒預填」） ──────────────
def test_every_param_dev_crm_sends_is_read_by_the_quotation_form():
    crm = (ROOT / "frontend/pages/dev-crm.html").read_text(encoding="utf-8")
    m = re.search(r"doConvert\(\)\s*\{(.*?)\n    \},", crm, re.S)
    assert m, "dev-crm.html 找不到 doConvert()"
    sent = set(re.findall(r"""\.set\(\s*['"]([A-Za-z]+)['"]""", m.group(1)))
    assert sent, "doConvert() 沒有任何 URLSearchParams.set"
    qf = (ROOT / "frontend/pages/quotation-form.html").read_text(encoding="utf-8")
    missing = {k for k in sent if not re.search(r"""\.get\(\s*['"]%s['"]\s*\)""" % re.escape(k), qf)}
    assert not missing, "業務開發送了、報價單頁沒讀的網址參數：%s" % sorted(missing)


def test_quotation_form_reads_the_agreed_params_and_calls_the_existing_endpoint():
    qf = (ROOT / "frontend/pages/quotation-form.html").read_text(encoding="utf-8")
    for k in ("customer", "project", "devCase", "type"):
        assert re.search(r"""\.get\(\s*['"]%s['"]\s*\)""" % k, qf), "報價單頁沒讀 ?%s=" % k
    assert "/dev-cases/${this.devCaseId}/convert" in qf, "連結要走既有的 PATCH /api/dev-cases/<id>/convert"


# ── e2e ───────────────────────────────────────────────────────────────────────────────────────────────
def _hdr(sess):
    return {"Authorization": "Bearer " + sess["token"], "Content-Type": "application/json"}


def _mk_customer(page, base, sess, name):
    r = page.context.request.post(f"{base}/api/customers", data={"name": name}, headers=_hdr(sess))
    assert r.ok, r.text()[:200]


def _mk_case(page, base, sess, name, customer=""):
    r = page.context.request.post(f"{base}/api/dev-cases", data={"case_name": name, "customer_name": customer}, headers=_hdr(sess))
    assert r.ok, r.text()[:200]
    return r.json()["id"]


def _get_case(page, base, sess, cid):
    r = page.context.request.get(f"{base}/api/dev-cases", headers=_hdr(sess))
    assert r.ok, r.text()[:200]
    rows = r.json()
    rows = rows.get("items", rows) if isinstance(rows, dict) else rows
    return next(c for c in rows if c["id"] == cid)


def _open(page, base, query):
    page.on("dialog", lambda d: d.dismiss())   # 存檔後「客戶管理尚無資料是否建立」的 confirm：一律不建
    page.goto(f"{base}/pages/quotation-form.html?{query}")
    page.wait_for_function(f"() => {{ const d = {DATA_JS}; return d && d._initSettled }}", timeout=30000)


def _save(page):
    page.locator("button", has_text="儲存草稿").first.click()


def _login(live_server, make_user, e2e_browser, name):
    u = make_user(username=name)
    page = e2e_browser.new_context(viewport={"width": 1400, "height": 900}).new_page()
    sess = inject_login(page, live_server, *u)
    return page, sess


@pytest.mark.e2e
def test_estimate_prefill_then_first_save_links_back_to_the_dev_case(live_server, make_user, e2e_browser):
    page, sess = _login(live_server, make_user, e2e_browser, "dcq_ok")
    _mk_customer(page, live_server, sess, "轉建客戶甲")
    cid = _mk_case(page, live_server, sess, "轉建案：大樓網路", "轉建客戶甲")
    _open(page, live_server, "customer=%E8%BD%89%E5%BB%BA%E5%AE%A2%E6%88%B6%E7%94%B2&project=%E8%BD%89%E5%BB%BA%E6%A1%88%EF%BC%9A%E5%A4%A7%E6%A8%93%E7%B6%B2%E8%B7%AF&type=estimate&devCase=" + str(cid))
    # 預填：客戶（比對得到 ⇒ 走一般選客戶流程，帶 customerId）、案件名稱、估價單
    page.wait_for_function(f"() => {DATA_JS}.q.customerId", timeout=10000)
    st = page.evaluate(f"() => ({{c: {DATA_JS}.q.customerName, p: {DATA_JS}.q.projectName, t: {DATA_JS}.q.docType}})")
    assert st == {"c": "轉建客戶甲", "p": "轉建案：大樓網路", "t": "estimate"}
    banner = page.locator("[data-testid=qf-devcase-banner]")
    banner.wait_for(state="visible", timeout=5000)
    assert "第一次存檔後會自動連回" in page.locator("[data-testid=qf-devcase-msg]").inner_text()
    assert page.locator("[data-testid=qf-devcase-retry]").is_hidden()
    # 還沒存檔：商機沒被連結
    assert not _get_case(page, live_server, sess, cid)["convertedQuoteNo"]
    _save(page)
    page.wait_for_function("() => /已連結：/.test(document.querySelector('[data-testid=qf-devcase-msg]').innerText)", timeout=20000)
    no = page.evaluate(f"() => {DATA_JS}.q.quoteNo")
    assert no.startswith("ME-"), no
    got = _get_case(page, live_server, sess, cid)
    assert got["convertedQuoteNo"] == no and got["status"] == "成案"
    assert "估價單" in page.locator("[data-testid=qf-devcase-msg]").inner_text()
    # 之後再存檔不會重打 convert（devCaseId 已清）
    calls = []
    page.on("request", lambda r: calls.append(r.url) if "/convert" in r.url else None)
    page.evaluate(f"() => {{ {DATA_JS}.q.projectName += '（改）'; }}")
    _save(page)
    page.wait_for_function(f"() => !{DATA_JS}.isDirty", timeout=10000)
    assert calls == []


@pytest.mark.e2e
def test_quote_type_default_and_unmatched_customer_is_typed_name(live_server, make_user, e2e_browser):
    page, sess = _login(live_server, make_user, e2e_browser, "dcq_quote")
    cid = _mk_case(page, live_server, sess, "無客戶檔的案", "客戶檔裡沒有的公司")
    _open(page, live_server, "customer=%E5%AE%A2%E6%88%B6%E6%AA%94%E8%A3%A1%E6%B2%92%E6%9C%89%E7%9A%84%E5%85%AC%E5%8F%B8&project=%E7%84%A1%E5%AE%A2%E6%88%B6%E6%AA%94%E7%9A%84%E6%A1%88&type=quote&devCase=" + str(cid))
    st = page.evaluate(f"() => ({{c: {DATA_JS}.q.customerName, id: {DATA_JS}.q.customerId, t: {DATA_JS}.q.docType}})")
    assert st["c"] == "客戶檔裡沒有的公司" and not st["id"] and st["t"] != "estimate"
    _save(page)
    page.wait_for_function("() => /已連結：/.test(document.querySelector('[data-testid=qf-devcase-msg]').innerText)", timeout=20000)
    no = page.evaluate(f"() => {DATA_JS}.q.quoteNo")
    assert no.startswith("MQ-") and _get_case(page, live_server, sess, cid)["convertedQuoteNo"] == no


@pytest.mark.e2e
def test_link_failure_is_visible_with_reason_and_retry(live_server, make_user, e2e_browser):
    """商機已被連結（409）／商機不存在（404）：存檔照成功，但橫幅要持續顯示後端原因＋重試鈕，不准靜默。"""
    page, sess = _login(live_server, make_user, e2e_browser, "dcq_fail")
    cid = _mk_case(page, live_server, sess, "已被連結的案")
    # 先讓商機連到別張單（種一張報價單當連結目標）
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, quote_date)"
                     " VALUES ('MQ-202611-777','已送出','X','Y',1,1,'{}','2026-11-14T00:00:00','2026-11-14T00:00:00','2026-11-14')")
        conn.commit()
    finally:
        conn.close()
    r = page.context.request.patch(f"{live_server}/api/dev-cases/{cid}/convert", data={"quote_no": "MQ-202611-777"}, headers=_hdr(sess))
    assert r.ok, r.text()[:200]
    _open(page, live_server, f"project=%E5%B7%B2%E9%80%A3%E7%B5%90&devCase={cid}")
    _save(page)
    msg = page.locator("[data-testid=qf-devcase-msg]")
    page.wait_for_function("() => /連回.*失敗/.test(document.querySelector('[data-testid=qf-devcase-msg]').innerText)", timeout=20000)
    assert "已連結報價單" in msg.inner_text(), msg.inner_text()
    retry = page.locator("[data-testid=qf-devcase-retry]")
    retry.wait_for(state="visible", timeout=5000)
    # 報價單本身已存好，連結沒被覆蓋
    assert page.evaluate(f"() => !{DATA_JS}.isNewRecord") and _get_case(page, live_server, sess, cid)["convertedQuoteNo"] == "MQ-202611-777"
    # 重試：仍失敗 ⇒ 橫幅仍在（不消失、不重複建單）
    no_before = page.evaluate(f"() => {DATA_JS}.q.quoteNo")
    retry.click()
    page.wait_for_function(f"() => !{DATA_JS}.devCaseBusy", timeout=10000)
    assert page.locator("[data-testid=qf-devcase-banner]").is_visible() and retry.is_visible()
    assert page.evaluate(f"() => {DATA_JS}.q.quoteNo") == no_before


@pytest.mark.e2e
def test_missing_dev_case_shows_error_and_bad_param_is_ignored(live_server, make_user, e2e_browser):
    page, sess = _login(live_server, make_user, e2e_browser, "dcq_404")
    _open(page, live_server, "project=%E4%B8%8D%E5%AD%98%E5%9C%A8&devCase=987654")
    _save(page)
    page.wait_for_function("() => /連回.*失敗/.test(document.querySelector('[data-testid=qf-devcase-msg]').innerText)", timeout=20000)
    assert "案件不存在" in page.locator("[data-testid=qf-devcase-msg]").inner_text()
    # 非正整數的 devCase 參數：忽略，不顯示橫幅、不打 convert
    page2 = page.context.new_page()
    calls = []
    page2.on("request", lambda r: calls.append(r.url) if "/convert" in r.url else None)
    _open(page2, live_server, "project=x&devCase=abc")
    _save(page2)
    page2.wait_for_function(f"() => !{DATA_JS}.isNewRecord", timeout=20000)
    assert page2.locator("[data-testid=qf-devcase-banner]").is_hidden() and calls == []
