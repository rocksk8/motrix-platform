# -*- coding: utf-8 -*-
"""A2 S3：四種費用單據（請購 PR／採購 PO／差旅 TE／零用金 PC）的整條鏈 e2e（含截圖）——
建立 → 送審（費用類別驗證，代碼與名稱都收）→ 簽核人在簽核佇列按核准 → 出納頁登錄付款 → 總帳分錄草稿（引擎）→ 營運報表列。
每個動作都操作控制項、驗終點狀態（資料庫＋畫面）；請購單全程驗「不存在」（不進出納／總帳／報表）。
最後對帳：總帳費用科目借方合計 ＝ 營運報表（權責／現金）這四張單據的合計。

需要整合環境：W4 G1（費用類別、類別→科目對應、引擎的 `category` 行處理）與 W3／W1 的合入版；缺任一 ⇒ 略過並說明（單獨在 W2 分支跑不到真提供者）。
截圖：暫存夾（BK19），事後複製到 D:\\開發測試檔\\shots\\wip-w2-expense-a2-w2b\\。"""
import json
import os
import tempfile
import time
from datetime import date

import pytest

from tests._requires import requires_module, skip_module_unless

skip_module_unless("accounting", "總帳引擎與費用類別對應")
skip_module_unless("analytics", "營運報表")
skip_module_unless("arap", "出納頁")
pytest.importorskip("playwright.sync_api")
try:
    from modules.accounting.ledger import category_map as _cm  # noqa: F401
except ImportError:
    pytest.skip("需要 W4 G1（費用類別與類別→科目對應）；此分支沒有", allow_module_level=True)

from tests._e2e_login import inject_login  # noqa: E402

pytestmark = [pytest.mark.e2e, requires_module("case", "費用單據端點")]

SENT = "/api/quotations/-/extra-expenses"
def _today():
    return date.today().isoformat()   # 呼叫時才取，避免跨午夜與伺服器日期不一致
def _month0():
    return _today()[:8] + "01"


def _shot(page, name):
    try:
        d = os.path.join(os.environ.get("MOTRIX_SHOTS_DIR") or os.path.join(tempfile.gettempdir(), "w2-shots"), "wip-w2-expense-a2")
        os.makedirs(d, exist_ok=True)
        page.screenshot(path=os.path.join(d, name + ".png"), full_page=True)
    except Exception:  # noqa: BLE001
        pass


def _q(sql, args=()):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute(sql, args).fetchall()]
    finally:
        c.close()


def _wait(pred, timeout=20.0, what="條件"):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return
        time.sleep(0.3)
    raise AssertionError("等不到：" + what)


class Api:
    def __init__(self, ctx, base, token):
        self.ctx, self.base, self.h = ctx, base, {"Authorization": "Bearer " + token}

    def call(self, method, path, body=None):
        r = getattr(self.ctx, method)(self.base + path, headers=self.h, **({"data": body} if body is not None else {}))
        try:
            return r.status, r.json()
        except Exception:  # noqa: BLE001
            return r.status, r.text()


@pytest.fixture
def world(live_server, make_user, e2e_browser):
    import db
    from modules.accounting.ledger import roles as ROLES
    users = {n: make_user(username=n, role=r, modules=m) for n, r, m in (
        ("ch_form", "sales", ["expense_forms"]), ("ch_apr", "engineer", ["financial_view"]),
        ("ch_cash", "engineer", ["cashier"]), ("ch_sa", "superadmin", None))}
    ctx = e2e_browser.new_context().request

    def login(n):
        r = ctx.post(f"{live_server}/api/auth/login", data={"username": n, "password": users[n][1]})
        assert r.ok, r.text()
        return Api(ctx, live_server, r.json()["token"])
    api = {n: login(n) for n in users}
    c = db.get_db()
    try:
        ROLES.ensure_meta(c)
        ROLES.ensure_default_roles(c)
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  ("unified_approval_flow", json.dumps({"tiers": [{"approvers": [{"username": "ch_apr", "display_name": "ch_apr"}]}], "includeSubmitterManagerTier": False}),
                   "2026-01-01T00:00:00"))
        c.commit()
    finally:
        c.close()
    sa = api["ch_sa"]
    for code, name, acct in (("TRAVEL", "差旅", "6114"), ("FREIGHT", "運費", "6115"), ("POST", "郵電", "6116")):
        assert sa.call("put", "/api/ledger/expense-categories", {"code": code, "name": name})[0] == 200
        assert sa.call("put", "/api/ledger/category-map", {"category": code, "account_code": acct})[0] == 200
    assert sa.call("put", "/api/ledger/features/engine_drafts", {"enabled": True})[0] == 200
    return users, api


def _create_four(api):
    f = api["ch_form"]
    docs = {}
    for key, body in (
        ("PR", {"kind": "purchase_req", "lines": [{"category": "FREIGHT", "summary": "請購運費", "amount": 500}], "payeeType": "vendor", "payeeName": "請購廠商"}),
        ("PO", {"kind": "purchase_order", "lines": [{"category": "FREIGHT", "summary": "採購運費", "qty": 2, "unitCost": 1500}], "payeeType": "vendor", "payeeName": "力霸廠商"}),
        ("TE", {"kind": "travel", "lines": [{"category": "差旅", "summary": "高鐵", "amount": 1200}, {"category": "POST", "summary": "郵資", "amount": 300}],
                "payeeType": "employee", "payeeName": "王小明"}),
        ("PC", {"kind": "petty_cash", "lines": [{"category": "POST", "summary": "影印", "amount": 450}], "payeeType": "employee", "payeeName": "李小華"})):
        st, d = f.call("post", SENT, {**body, "data": {"applicant": "ch_form"}})
        assert st == 201, d
        docs[key] = d
    return docs


def test_four_types_end_to_end(world, live_server, e2e_browser):
    users, api = world
    docs = _create_four(api)
    ids = {k: v["id"] for k, v in docs.items()}
    code = {k: v["docCode"] for k, v in docs.items()}
    assert [code[k][:2] for k in ("PR", "PO", "TE", "PC")] == ["PR", "PO", "TE", "PC"]

    # ── 送審：類別驗證（未知類別 400、狀態不變；代碼與名稱都收，寫入代碼＋名稱＋科目快照）──
    bad = api["ch_form"].call("post", SENT, {"kind": "travel", "lines": [{"category": "NOPE", "summary": "x", "amount": 10}], "data": {"applicant": "ch_form"}})[1]["id"]
    st, d = api["ch_form"].call("post", "%s/%d/submit" % (SENT, bad))
    assert st == 400 and "NOPE" in json.dumps(d, ensure_ascii=False)
    assert _q("SELECT status FROM case_extra_expenses WHERE id=?", (bad,))[0]["status"] == "草稿"
    api["ch_form"].call("delete", "%s/%d" % (SENT, bad))
    for k in ("PR", "PO", "TE", "PC"):
        st, d = api["ch_form"].call("post", "%s/%d/submit" % (SENT, ids[k]))
        assert st == 200 and d["status"] == "待審核", (k, d)
    te_lines = json.loads(_q("SELECT lines_json FROM case_extra_expenses WHERE id=?", (ids["TE"],))[0]["lines_json"])
    assert [(l["categoryCode"], l["categoryName"], l["accountCode"]) for l in te_lines] == [("TRAVEL", "差旅", "6114"), ("POST", "郵電", "6116")]      # 名稱與代碼都收；科目由真提供者解出
    assert _q("SELECT status FROM case_extra_expenses WHERE id=?", (ids["PR"],))[0]["status"] == "待審核"

    # ── 簽核人：簽核佇列逐張按核准 ─────────────────────────────────────────────
    ctx = e2e_browser.new_context()
    page = ctx.new_page()
    page.on("dialog", lambda dlg: dlg.accept())                       # 簽核前的確認框（window.confirm）
    inject_login(page, live_server, *users["ch_apr"])
    page.goto(live_server + "/pages/approval-queue.html")
    for k in ("PR", "PO", "TE", "PC"):
        page.locator('[data-testid="aq-item-%s"]' % code[k]).first.wait_for(state="visible", timeout=20000)
    body = page.inner_text("body")
    assert "請購單" in body and "採購單" in body and "差旅費用請款單" in body and "零用金支付單" in body                  # 類型標籤（佇列契約 typeLabel）
    _shot(page, "30-approval-queue-four-types")
    for k in ("PR", "PO", "TE", "PC"):
        page.locator('[data-testid="aq-item-%s"]' % code[k]).first.click()
        btn = page.locator('[data-testid="aq-approve"]:visible').first
        btn.wait_for(state="visible", timeout=10000)
        btn.click()
        _wait(lambda k=k: _q("SELECT status FROM case_extra_expenses WHERE id=?", (ids[k],))[0]["status"] == "已核准", what="%s 核准" % k)
    _shot(page, "31-approval-queue-after")
    assert {r["status"] for r in _q("SELECT status FROM case_extra_expenses WHERE id IN (?,?,?,?)", tuple(ids.values()))} == {"已核准"}

    # ── 出納：請購單不在待付款；採購單／差旅／零用金各填必要欄位後登錄付款 ─────────────
    cash = e2e_browser.new_context().new_page()
    inject_login(cash, live_server, *users["ch_cash"])
    cash.goto(live_server + "/pages/cashier.html")
    tab = cash.locator('[data-testid="cashier-payreq-tab"]')
    tab.wait_for(state="visible", timeout=20000)
    tab.click()

    def row(k):
        return cash.locator('[data-testid="cashier-payreq-row-case-%d"]' % ids[k])
    row("PO").wait_for(timeout=15000)
    assert row("PR").count() == 0                                                                  # 請購單不進出納
    _shot(cash, "32-cashier-pending-three")

    def pay(k):
        cash.locator('[data-testid="cashier-payreq-pay-case-%d"]' % ids[k]).click()
        cash.wait_for_function("(id) => !document.querySelector('[data-testid=\"cashier-payreq-row-case-' + id + '\"]')", arg=ids[k], timeout=15000)
    cash.fill('[data-testid="cashier-payreq-date-case-%d"]' % ids["PO"], _today())
    cash.fill('[data-testid="cashier-payreq-remitdate-case-%d"]' % ids["PO"], _today())
    cash.fill('[data-testid="cashier-payreq-terms-case-%d"]' % ids["PO"], "月結 30 天")
    pay("PO")
    cash.fill('[data-testid="cashier-payreq-date-case-%d"]' % ids["TE"], _today())
    pay("TE")
    cash.fill('[data-testid="cashier-payreq-date-case-%d"]' % ids["PC"], _today())
    cash.select_option('[data-testid="cashier-payreq-method-case-%d"]' % ids["PC"], "petty_cash")
    pay("PC")
    _shot(cash, "33-cashier-all-paid")
    paid = {r["id"]: r for r in _q("SELECT id, paid_date, pay_method, pay_terms, remit_date FROM case_extra_expenses WHERE id IN (?,?,?,?)", tuple(ids.values()))}
    assert [paid[ids[k]]["paid_date"] for k in ("PO", "TE", "PC")] == [_today()] * 3 and paid[ids["PR"]]["paid_date"] == ""
    assert paid[ids["PO"]]["pay_terms"] == "月結 30 天" and paid[ids["PC"]]["pay_method"] == "petty_cash" and paid[ids["TE"]]["pay_method"] == "transfer"

    # ── 總帳：在「總帳作業」按「產生分錄草稿」──────────────────────────────────────
    gl = e2e_browser.new_context().new_page()
    inject_login(gl, live_server, *users["ch_sa"])
    gl.goto(live_server + "/pages/ledger-hub.html")
    gl.locator('[data-testid="hb-tab-engine_drafts"]').click()
    gl.fill('[data-testid="hb-eng-start"]', _month0())
    gl.fill('[data-testid="hb-eng-end"]', _today())
    gl.locator('[data-testid="hb-eng-run"]').click()
    _wait(lambda: len(_q("SELECT 1 FROM gl_source_events WHERE source_type LIKE 'case_extra_expense%'")) >= 6, what="分錄事件（PO／TE／PC 各 E11＋E11b）")
    gl.wait_for_selector('[data-testid="hb-eng-table"] tbody tr', timeout=15000)
    table = gl.inner_text('[data-testid="hb-eng-table"]')
    assert "E11" in table and "E11b" in table
    _shot(gl, "34-ledger-engine-drafts")

    def entries(k):
        out = {}
        for ev in _q("SELECT event_code, voucher_id FROM gl_source_events WHERE source_type LIKE 'case_extra_expense%' AND source_key=? ORDER BY id", (str(ids[k]),)):
            out[ev["event_code"]] = sorted((l["account_code"], l["debit"], l["credit"]) for l in _q("SELECT account_code, debit, credit FROM voucher_lines WHERE voucher_id=?", (ev["voucher_id"],)))
        return out
    assert entries("PR") == {}                                                                      # 請購單：沒有任何分錄事件
    ap = _q("SELECT account_code FROM gl_account_roles WHERE role='AP'")[0]["account_code"]
    bank = _q("SELECT account_code FROM gl_account_roles WHERE role='BANK'")[0]["account_code"]
    petty = _q("SELECT account_code FROM gl_account_roles WHERE role='PETTY'")[0]["account_code"]
    assert entries("PO") == {"E11": sorted([("6115", 3000, 0), (ap, 0, 3000)]), "E11b": sorted([(ap, 3000, 0), (bank, 0, 3000)])}
    assert entries("TE") == {"E11": sorted([("6114", 1200, 0), ("6116", 300, 0), (ap, 0, 1500)]), "E11b": sorted([(ap, 1500, 0), (bank, 0, 1500)])}   # 逐類別借方
    assert entries("PC") == {"E11": sorted([("6116", 450, 0), (ap, 0, 450)]), "E11b": sorted([(ap, 450, 0), (petty, 0, 450)])}                          # 零用金貸 PETTY
    assert petty != bank
    for v in _q("SELECT v.id FROM vouchers_all v JOIN gl_source_events e ON e.voucher_id=v.id WHERE e.source_type LIKE 'case_extra_expense%'"):
        s = _q("SELECT SUM(debit) AS d, SUM(credit) AS c FROM voucher_lines WHERE voucher_id=?", (v["id"],))[0]
        assert s["d"] == s["c"] and s["d"] > 0                                                      # 每張傳票借貸平衡
    gl_expense = sum(l["debit"] for ev in _q("SELECT voucher_id FROM gl_source_events WHERE source_type='case_extra_expense'")
                     for l in _q("SELECT debit FROM voucher_lines WHERE voucher_id=? AND account_code LIKE '61%'", (ev["voucher_id"],)))
    assert gl_expense == 4950                                                                       # 3000 + 1500 + 450

    # ── 營運報表：畫面與 API；與總帳對帳 ─────────────────────────────────────────
    rp = e2e_browser.new_context().new_page()
    inject_login(rp, live_server, *users["ch_sa"])
    rp.goto(live_server + "/pages/reports.html")
    rp.locator(".tab:has-text('月支出')").click()
    rp.locator(".period-type-btn:has-text('其他支出')").click()
    rp.wait_for_selector("text=%s" % code["TE"], timeout=20000)
    text = rp.inner_text("body")
    assert code["PO"] in text and code["TE"] in text and code["PC"] in text and code["PR"] not in text        # 請購單不在營運報表
    _shot(rp, "35-ops-report-month-expenses")
    for basis in ("accrual", "cash"):
        st, rep = api["ch_sa"].call("get", "/api/reports/expenses-monthly?year=%s&month=%s&basis=%s" % (_today()[:4], _today()[:7], basis))
        assert st == 200
        mine = [i for i in rep["monthExpenseItems"] if any(c in i["desc"] for c in code.values())]
        assert not [i for i in mine if code["PR"] in i["desc"]], basis
        by_doc = {}
        for i in mine:
            by_doc.setdefault(i["desc"].split("｜")[0], {})[i["category"]] = i["amount"]
        assert by_doc == {code["PO"]: {"運費": 3000}, code["TE"]: {"差旅": 1200, "郵電": 300}, code["PC"]: {"郵電": 450}}, (basis, by_doc)
        assert sum(i["amount"] for i in mine) == gl_expense == 4950                                 # 報表（權責／現金）＝總帳費用科目借方


def test_no_categories_defined_still_submits_and_posts_with_the_default_account(live_server, make_user, e2e_browser):
    """使用者裁示 A：公司尚未設定任何費用類別 ⇒ 送審不擋；核准、出納付款後總帳照樣出分錄（類別未對應 ⇒ 預設費用科目），借貸平衡。"""
    import db
    from modules.accounting.ledger import roles as ROLES
    users = {n: make_user(username=n, role=r, modules=m) for n, r, m in (
        ("nc_form", "sales", ["expense_forms"]), ("nc_cash", "engineer", ["cashier"]), ("nc_sa", "superadmin", None))}
    ctx = e2e_browser.new_context().request
    api = {}
    for n in users:
        r = ctx.post(f"{live_server}/api/auth/login", data={"username": n, "password": users[n][1]})
        api[n] = Api(ctx, live_server, r.json()["token"])
    c = db.get_db()
    try:
        ROLES.ensure_meta(c)
        ROLES.ensure_default_roles(c)
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": False}), "2026-01-01T00:00:00"))
        c.commit()
        assert not [r for r in c.execute("SELECT 1 FROM expense_categories")]                      # 前提：真的沒有任何類別
    finally:
        c.close()
    assert api["nc_sa"].call("put", "/api/ledger/features/engine_drafts", {"enabled": True})[0] == 200
    st, d = api["nc_form"].call("post", SENT, {"kind": "travel", "lines": [{"category": "隨便寫", "summary": "高鐵", "amount": 1200}],
                                                "data": {"applicant": "nc_form"}, "payeeType": "employee", "payeeName": "王小明"})
    assert st == 201, d
    eid = d["id"]
    st, d = api["nc_form"].call("post", "%s/%d/submit" % (SENT, eid))
    assert st == 200 and d["status"] == "已核准", d                                                  # 沒設類別 ⇒ 不擋（無簽核層 ⇒ 直接核准）
    assert api["nc_cash"].call("post", "/api/cashier/pending-payables/case/%d/pay" % eid, {"paidDate": _today()})[0] == 200
    st, run = api["nc_sa"].call("post", "/api/ledger/engine/run", {"start": _month0(), "end": _today()})
    assert st == 200 and run["stats"]["created"] >= 2, run
    evs = _q("SELECT event_code, voucher_id FROM gl_source_events WHERE source_type LIKE 'case_extra_expense%' AND source_key=?", (str(eid),))
    assert sorted(e["event_code"] for e in evs) == ["E11", "E11b"]
    for e in evs:
        s = _q("SELECT SUM(debit) AS d, SUM(credit) AS c FROM voucher_lines WHERE voucher_id=?", (e["voucher_id"],))[0]
        assert s["d"] == s["c"] == 1200
