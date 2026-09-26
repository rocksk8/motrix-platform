# -*- coding: utf-8 -*-
"""金額捨入統一四捨五入（X-VAT，2026-09-26；R 稽核修正帶出：開票申請的營業稅用內建 round()）。

內建 `round()` 是銀行家捨入（.5 取偶數：round(1250.5) == 1250）；前端 `Math.round(a * b)` 在浮點乘積
落在 x.4999… 時少 1 元、負數 -1.5 取 -1。共用函式：後端 L1 `helpers.legal_params.round_half_up`
（`helpers.quotations.round_half_up` 轉呼叫它），前端 `static/legal-round.js` 的 `MotrixLegalRound.halfUp`。

每一處修改一題：挑會出現 .5 的金額，改之前會紅（註明舊值）；另有正對照（改前改後都一樣的值，
證明題目本身沒有把「正常的金額」也算錯）。守門：tests/platform/test_legal_amount_rounding_guard.py。
前端題用 node 載入頁面（或 case-management-*.js 分檔）的元件，直接呼叫方法；沒有 node ⇒ skip。
"""
import json
import pathlib
import shutil
import subprocess
from datetime import datetime

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


# ══════════════════════════════════════════════════════════════════════════════
# 共用函式
# ══════════════════════════════════════════════════════════════════════════════

def test_quotations_round_half_up_forwards_to_the_legal_params_service():
    from helpers import legal_params as lp
    from helpers.quotations import round_half_up
    assert round_half_up(1250.5) == 1251 and round_half_up(1250.4) == 1250      # 正對照＋.5
    assert round_half_up(1251, 0.05) == lp.round_half_up(1251, 0.05) == 63      # 62.55
    assert round_half_up(-2.5) == -3, "負數遠離 0（Decimal ROUND_HALF_UP）"


# ══════════════════════════════════════════════════════════════════════════════
# 報價：收款期別金額（helpers/quotations.py::payment_item_amounts）
# ══════════════════════════════════════════════════════════════════════════════

def test_payment_items_by_pct_round_half_up():
    """10,015 × 30% ＝ 3,004.5 ⇒ 3,005（舊：3,004；畫面 Math.round 一直是 3,005 ⇒ 前後端差 1 元）。"""
    from helpers.quotations import payment_item_amounts
    # 第 2 期由 pct 算（L329）；第 1 期＝總額 − 其他期（其他期也由 pct 算，L319）
    assert payment_item_amounts(10015, [{"pct": 70}, {"pct": 30}]) == [7010, 3005]
    # 正對照：沒有 .5 的比例
    assert payment_item_amounts(10000, [{"pct": 70}, {"pct": 30}]) == [7000, 3000]


def test_tax_exempt_item_converts_to_pretax_half_up():
    """沖銷免稅期別：含稅 24 × 未稅 30／含稅 32 ＝ 22.5 ⇒ 23（舊：22）。L331"""
    from helpers.quotations import payment_item_amounts
    assert payment_item_amounts(32, [{"amount": 24, "taxExempt": True}], pretax=30) == [23]
    assert payment_item_amounts(32, [{"amount": 16, "taxExempt": True}], pretax=30) == [15]    # 正對照


# ══════════════════════════════════════════════════════════════════════════════
# 開票申請（routers/invoice_vouchers.py）
# ══════════════════════════════════════════════════════════════════════════════

def _quote(no, pretax, total, data):
    import db
    now = datetime.now().isoformat()
    d = {"quoteNo": no, "caseRecord": {"payment": {"items": []}}}
    d.update(data)
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, total, pretax, data_json, created_at, updated_at, "
            "customer_name) VALUES (?,?,?,?,?,?,?,?)",
            (no, "已成案", total, pretax, json.dumps(d, ensure_ascii=False), now, now, "客戶"))
        conn.commit()
    finally:
        conn.close()


def _hdr(client, make_user):
    u, p = make_user(role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _voucher(client, h, body):
    r = client.post("/api/invoice-vouchers", json=body, headers=h)
    assert r.status_code in (200, 201), r.text
    r = client.get("/api/invoice-vouchers/" + r.json()["voucher_no"], headers=h)
    assert r.status_code == 200, r.text
    v = r.json()
    return v["pretaxAmount"], v["taxAmount"], v["amount"]


_ITEMS = [{"id": 1, "type": "item", "description": "設備", "qty": 10, "unitPrice": 1000, "amount": 10000}]


# ══════════════════════════════════════════════════════════════════════════════
# 請款單（routers/payment_requests.py）
# ══════════════════════════════════════════════════════════════════════════════

def _calc(scope, quote_total, quote_pretax, ratio=None, amount=None, items=None, data_items=None):
    from modules.arap.api.payment_requests import _calc_scope_amount, RequestItemIn   # M05（2026-09-26）
    data = {"items": data_items or _ITEMS}
    remaining = {"items": [{"itemId": it["id"], "remainingQty": it["qty"]} for it in data["items"]]}
    items_in = [RequestItemIn(**x) for x in items] if items else None
    return _calc_scope_amount(data, remaining, quote_total, quote_pretax, scope, ratio, amount, items_in)[:4]


def _pr_body(scope, **kw):
    return dict({"scope": scope, "stage": "deposit"}, **kw)


# ══════════════════════════════════════════════════════════════════════════════
# 外包派發稅額（vendor_contractors._dispatch_row／contractor_vouchers 建立匯款申請）
# ══════════════════════════════════════════════════════════════════════════════

def _dispatch(client, h, amount, no):
    r = client.post("/api/vendor-contractors", headers=h, json={"name": "廠商" + no, "data": {}})
    assert r.status_code == 201, r.text
    body = {"quote_no": no, "vendor_id": r.json()["id"], "status": "completed",
            "items_json": [{"description": "施工", "qty": 1, "unit": "式", "unitPrice": amount, "amount": amount}]}
    r = client.post("/api/contractor-dispatches", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ══════════════════════════════════════════════════════════════════════════════
# 營運報表／首頁／會計匯出（顯示與比對用的整數化）
# ══════════════════════════════════════════════════════════════════════════════

def _insert_dispatch_row(quote_no, total_amount, personnel=None):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, personnel_json, "
            "total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "2026-01-01", "amount", "[]", json.dumps(personnel or []), total_amount, "completed",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _stock(part_no, cost, created, category="其他"):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO parts (part_no, name, category) VALUES (?,?,?)", (part_no, part_no, category))
        conn.execute("INSERT INTO stock_items (part_no, serial_no, status, batch_no, cost, created_at, updated_at) "
                     "VALUES (?,?,?,?,?,?,?)", (part_no, part_no + "-" + str(cost), "in_stock", "", cost, created, created))
        conn.commit()
    finally:
        conn.close()


def test_recognition_flag_amount_rounds_half_up():
    """待補登標註的金額：10.5 ⇒ 11（舊：10）。recognition L339"""
    from helpers.recognition import _flag_item
    assert _flag_item("Q", "c", "d", "x", 10.5, "2026-01-01", True, "extra_no_invoice")["amount"] == 11
    assert _flag_item("Q", "c", "d", "x", None, "2026-01-01", True, "extra_no_invoice")["amount"] is None


def test_extra_expense_total_rounds_half_up_to_cents(client):
    """額外支出小計（元以下兩位）：1 × 0.145 ⇒ 0.15（舊：round(0.145, 2)＝0.14）。
    case_extra_expenses L172（_recalc）、L725（核准變更 _apply_change）"""
    import db
    from routers.case_extra_expenses import ExtraExpenseIn, _recalc, _apply_change
    assert _recalc(ExtraExpenseIn(qty=1, unitCost=0.145)) == 0.15
    assert _recalc(ExtraExpenseIn(qty=3, unitCost=100.1)) == 300.3                         # 正對照
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO case_extra_expenses (quote_no, description, qty, unit_cost, total_cost) "
                     "VALUES (?,?,?,?,?)", ("MQ-VAT-X1", "x", 1, 1, 1))
        row = conn.execute("SELECT * FROM case_extra_expenses WHERE quote_no='MQ-VAT-X1'").fetchone()
        total = _apply_change(conn, row, {"qty": 1, "unitCost": 0.145, "description": "x"}, "主管",
                              datetime.now().isoformat())
        conn.rollback()
    finally:
        conn.close()
    assert total == 0.15


# ══════════════════════════════════════════════════════════════════════════════
# 前端（node 載入元件，直接呼叫方法）
# ══════════════════════════════════════════════════════════════════════════════

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="需要 node 才能載入前端元件")

_NODE_HARNESS = r"""
const fs = require('fs'), vm = require('vm')
const [lr, kind, target, factory, body] = process.argv.slice(1)
const noop = () => {}
const ctx = { console, setTimeout, clearTimeout, setInterval, clearInterval, URLSearchParams, Intl,
  window: { addEventListener: noop, innerWidth: 1200, location: { search: '' } },
  document: { addEventListener: noop, querySelector: () => null, getElementById: () => null,
              documentElement: { setAttribute: noop } },
  localStorage: { getItem: () => null, setItem: noop }, location: { search: '', href: '' }, navigator: {},
  fetch: () => new Promise(noop) }
vm.createContext(ctx)
vm.runInContext('var window = globalThis.window;', ctx)
vm.runInContext(fs.readFileSync(lr, 'utf8'), ctx)
vm.runInContext('var MotrixLegalRound = window.MotrixLegalRound;', ctx)
let o
if (kind === 'js') {
  vm.runInContext(fs.readFileSync(target, 'utf8'), ctx, { filename: target })
  o = vm.runInContext(factory + '()', ctx)
} else if (kind === 'page') {
  const html = fs.readFileSync(target, 'utf8')
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1])
    .filter(s => s.includes('function ' + factory + '('))
  if (scripts.length !== 1) throw new Error('找不到元件 ' + factory + '：' + scripts.length)
  vm.runInContext(scripts[0], ctx)
  o = vm.runInContext(factory + '()', ctx)
} else {
  for (const f of target.split('|')) vm.runInContext(fs.readFileSync(f, 'utf8'), ctx, { filename: f })
  o = {}
  for (const p of ctx.window.CM_PARTS) Object.defineProperties(o, Object.getOwnPropertyDescriptors(p()))
}
ctx.__o = o
const out = vm.runInContext('(function (o) {' + body + '})(__o)', ctx)
console.log(JSON.stringify(out))
"""


def _js(kind, target, factory, body):
    r = subprocess.run([NODE, "-e", _NODE_HARNESS, str(FRONTEND / "static" / "legal-round.js"), kind, target,
                        factory, body], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _page(name, factory, body):
    from core import source_tree   # 頁面位置一律經 page_file（C1；列車 train/0926-0415 交會）
    return _js("page", str(source_tree.page_file(name)), factory, body)


def _cm(body):
    parts = sorted((FRONTEND / "js").glob("case-management-*.js"))
    parts.sort(key=lambda p: p.name != "case-management-core.js")
    return _js("cm", "|".join(str(p) for p in parts), "", body)


@needs_node
def test_frontend_quotation_item_amount_and_charity_round_half_up():
    """報價表單：數量 0.7 × 單價 45 ＝ 31.5 ⇒ 32（舊 Math.round(0.7*45)＝31，浮點 31.499…）；
    直接利潤 −150 的公益 1% ＝ −1.5 ⇒ −2（舊 Math.round(−1.5)＝−1）；稅額 9,810 × 5% ⇒ 491（正對照）。"""
    got = _page("quotation-form.html", "quotationForm", """
        const it = { type: 'item', qty: 0.7, unitPrice: 45, cost: 0, unitPriceOverride: true }
        o.q = { items: [it], discount: 0, freight: 0, taxRate: 5 }
        o.calcItem(it)
        const a = it.amount
        o.q = { items: [{ type: 'item', qty: 1, unitPrice: 100, amount: 100, cost: 238 }], discount: 0, freight: 0, taxRate: 5 }
        o.calcTotals()
        const t1 = o.tot
        o.q = { items: [{ type: 'item', qty: 1, unitPrice: 9810, amount: 9810, cost: 0 }], discount: 0, freight: 0, taxRate: 5 }
        o.calcTotals()
        return { a, directProfit: t1.directProfit, charity: t1.charityDonation, tax: o.tot.tax, total: o.tot.total }""")
    assert got == {"a": 32, "directProfit": -150, "charity": -2, "tax": 491, "total": 10301}


@needs_node
def test_frontend_payment_request_form_matches_the_backend():
    """請款單頁：品項 0.7 × 45 ⇒ 32（舊 31）；依金額 3,939 的未稅試算 3,939×10,004／10,504＝3,751.5 ⇒ 3,752
    （舊 3,939／(10,504／10,004) 浮點 3,751.4999… ⇒ 3,751）；比例 30% of 10,015 ⇒ 3,005（正對照）。"""
    got = _page("payment-request-form.html", "paymentRequestForm", """
        o.toggleItem({ itemId: 1, remainingQty: 0.7, unitPrice: 45 })
        const a = o.itemSelections[1].amount
        o.remaining = { quoteTotal: 10504, quotePretax: 10004 }
        o.q.scope = 'amount'; o.ratioInput = 0; o.amountInput = 3939
        const pre = o.currentPretax()
        o.remaining = { quoteTotal: 10015, quotePretax: 9538 }; o.ratioInput = 30
        return { a, pre, ratio: o.ratioToAmount() }""")
    assert got == {"a": 32, "pre": 3752, "ratio": 3005}


@needs_node
def test_frontend_case_finance_matches_the_backend():
    """案件財務（開票申請試算）：品項 0.7 × 45 ⇒ 32（舊 31）；依金額未稅 3,939 ⇒ 3,752（舊 3,751）；
    收款期別 10,015 × 30% ⇒ 3,005（正對照；後端舊值 3,004 見上面的題）。"""
    got = _cm("""
        o.ivItemSelections = {}
        o.ivToggleItem({ itemId: 1, remainingQty: 0.7, unitPrice: 45 })
        o.ivRemaining = { quoteTotal: 10504, quotePretax: 10004 }; o.ivAmountInput = 3939
        o.selected = { total: 10015, pretax: 9538 }
        o.paymentItems = () => [{ pct: 70 }, { pct: 30 }]
        return { a: o.ivItemSelections[1].amount, pre: o.ivAmountPretax(), p2: o.itemAmountWithTax(1) }""")
    assert got == {"a": 32, "pre": 3752, "p2": 3005}


@needs_node
def test_frontend_dispatch_and_extra_expense_match_the_backend():
    """派工品項 0.7 × 45 ⇒ 32（舊 31）；派工稅額 10,010 × 5% ⇒ 501（正對照，後端舊值 500）；
    額外支出 1 × 0.145 ⇒ 0.15（舊 Math.round(14.499…)／100＝0.14）——與後端 _recalc 一致。"""
    got = _cm("""
        o._recalcDispatchTotal = () => {}
        o.dispatchForm = { items: [{ qty: 0.7, unitPrice: 45 }], tax_rate: 0.05 }
        o.onDispatchItemPrice(0)
        const a = o.dispatchForm.items[0].amount
        o.dispatchForm = { items: [{ amount: 10010 }], tax_rate: 0.05 }
        const tax = o._dispatchTaxAmount()
        o.xe = { items: [{ qty: 1, unitCost: 0.145, change: { qty: 1, unitCost: 0.145 } }], msg: '' }
        o.xeRecalc(0); o.xeChangeRecalc(0)
        return { a, tax, x: o.xe.items[0].totalCost, c: o.xe.items[0].change.totalCost }""")
    assert got == {"a": 32, "tax": 501, "x": 0.15, "c": 0.15}


@needs_node
def test_frontend_settlement_rounds_half_up():
    """成本精算：實際 0.7 × 45 ⇒ 32（舊 31）；毛利 −150 的公益 1% ⇒ −2（舊 −1）；管理費 10% of 105 ⇒ 11（正對照）。"""
    got = _page("settlement.html", "settlementPage", """
        const it = { actualQty: 0.7, actualUnitCost: 45, actualCostTaxMode: 'untaxed' }
        o.calcItemCost(it)
        o._origTot = { pretax: 105, total: 110 }
        o.settlement = { items: [] }
        o.xeTotal = 255
        o.dispatchTotal = () => 0
        o.calcSummary()
        return { a: it.actualTotalCost, gross: o.summary.grossProfit, charity: o.summary.charityDonation,
                 admin: o.summary.adminCost }""")
    assert got == {"a": 32, "gross": -150, "charity": -2, "admin": 11}


@needs_node
def test_frontend_material_order_amounts_round_half_up_to_cents():
    """叫料小計（元以下兩位）：1 × 0.145 ⇒ 0.15（舊 Math.round(0.145*100)/100＝0.14，浮點 14.499…）；
    部分付款 0.145 ⇒ 0.15（同上）；2 × 100.1 ⇒ 200.2（正對照）。case-management-exec.js moRecalc／moSave"""
    got = _cm("""
        o.materialOrders = [{ quantity: 1, unitPrice: 0.145, paidStatus: 'paid' }, { quantity: 2, unitPrice: 100.1 }]
        o.moRecalc(0); o.moRecalc(1)
        return [o.materialOrders[0].totalPrice, o.materialOrders[0].paidAmount, o.materialOrders[1].totalPrice]""")
    assert got == [0.15, 0.15, 200.2]


@needs_node
def test_frontend_material_order_save_payload_rounds_half_up_to_cents():
    """送出前的正規化：小計 1 × 0.145 ⇒ 0.15、部分付款 0.145 ⇒ 0.15（舊 0.14／0.14）。moSave"""
    got = _cm("""
        let sent = null
        o.selected = { quote_no: 'Q' }; o.session = { token: 't' }
        o.materialOrders = [{ itemName: '線材', quantity: 1, unitPrice: 0.145, paidStatus: 'partial', paidAmount: 0.145, paidDate: '2026-09-26' }]
        const realFetch = globalThis.fetch
        globalThis.fetch = (url, opt) => { sent = JSON.parse(opt.body); return new Promise(() => {}) }
        o.moSave()
        globalThis.fetch = realFetch
        const m = sent && sent.materialOrders[0]
        return m ? [m.totalPrice, m.paidAmount] : ['no-payload', o.moMsg || '']""")
    assert got == [0.15, 0.15]


@needs_node
def test_frontend_reports_estimated_profit_rounds_half_up():
    """營運報表頁的預估淨利＝未稅 × 淨利率：100 × −1.5% ＝ −1.5 ⇒ −2（舊 Math.round(−1.5)＝−1）；
    10,000 × 12.3% ⇒ 1,230（正對照）。reports.js estGrossProfit"""
    got = _js("js", str(FRONTEND / "js" / "reports.js"), "reportsApp", """
        return [o.estGrossProfit({ pretax: 100, netMarginPct: -1.5 }), o.estGrossProfit({ pretax: 10000, netMarginPct: 12.3 })]""")
    assert got == [-2, 1230]
