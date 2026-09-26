# -*- coding: utf-8 -*-
"""獎金精算金額四捨五入（需要本模組）。

（2026-09-26 自 tests/test_money_round_half_up_2026_09_26.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
金額捨入統一四捨五入（X-VAT，2026-09-26；R 稽核修正帶出：開票申請的營業稅用內建 round()）。

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

ROOT = pathlib.Path(__file__).resolve().parents[4]
FRONTEND = ROOT / "frontend"


# ══════════════════════════════════════════════════════════════════════════════
# 共用函式
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# 報價：收款期別金額（helpers/quotations.py::payment_item_amounts）
# ══════════════════════════════════════════════════════════════════════════════


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
# 請款單（M05 modules/arap/api/payment_requests.py；M05 不在 ⇒ 這一段 skip）
# ══════════════════════════════════════════════════════════════════════════════

def _calc(scope, quote_total, quote_pretax, ratio=None, amount=None, items=None, data_items=None):
    _pr = pytest.importorskip("modules.arap.api.payment_requests")   # M05 不在這個安裝包 ⇒ skip（PLAYBOOK §B-11）
    _calc_scope_amount, RequestItemIn = _pr._calc_scope_amount, _pr.RequestItemIn
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


def _patch_entries(monkeypatch, contractor=(), material=(), other=()):
    import routers.reports as rp

    def _mk(rows, **extra):
        return lambda *a, **k: [dict({"date": d, "quoteNo": "", "desc": "x", "amount": amt, "taxNote": "",
                                      "provisional": False}, **extra) for d, amt in rows]
    monkeypatch.setattr(rp, "dispatch_entries", _mk(contractor))
    monkeypatch.setattr(rp, "material_entries", _mk(material))
    monkeypatch.setattr(rp, "extra_entries", _mk(other, files=[], pending=False, category="其他"))


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


def test_bonus_settlement_money_rounds_half_up():
    """獎金精算明細金額：10.5 ⇒ NT$ 11（舊：NT$ 10）。bonus_pdf L160"""
    from modules.payroll.bonus_pdf import _settle_money
    assert _settle_money(10.5) == "NT$ 11"
    assert _settle_money(None) == "—" and _settle_money(0) == "NT$ 0"


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
