# -*- coding: utf-8 -*-
"""2026-11-13：承攬派工「匯入報價單品項」（IP-17 `quotation.append_items`）寫入時就要有售價與金額。

舊版寫 `unitPrice=None`／`amount=0`，而報價單頁載入時只呼叫 calcTotals（不重算品項 amount）⇒ 畫面空白、
合計與 PDF 少算，要使用者逐列編輯才補得出來。現在寫入時用與前端 `calcUnitPrice`／`calcItem` 同式的算法算好。
觀測點打資料庫本身（data_json.items），不看端點回應。
"""
import json
import re
import shutil
import subprocess

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔打 M01 的 quotation.append_items 與報價單資料")

NODE = shutil.which("node")
COSTS = [1, 0.5, 87, 333, 1000, 1234.5, 20000, 47619.05, 99999, 100, 0, -5, 123456.78, 3.33, 47.62, 2000, 10000]


def _js_calc(costs, margin=0.30):
    from core import source_tree
    html = source_tree.page_file("quotation-form.html").read_text(encoding="utf-8")
    m = re.search(r"      calcUnitPrice\(cost, margin\) \{\n(.*?)\n      \},\n", html, re.S)
    assert m, "找不到 quotation-form.html 的 calcUnitPrice（前端改了寫法？同步改本測試與後端 _calc_unit_price）"
    js = "const f=function(cost, margin){%s};const v=JSON.parse(process.argv[1]);console.log(JSON.stringify(v.map(c=>f(c,%r))))" % (m.group(1), margin)
    r = subprocess.run([NODE, "-e", js, json.dumps(costs)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(NODE is None, reason="沒有 node，跳過跨語言比對")
def test_calc_unit_price_matches_frontend_calcUnitPrice():
    from modules.case.api.quotations import _calc_unit_price
    want = _js_calc(COSTS)
    got = [_calc_unit_price(c) for c in COSTS]
    assert got == want, [(c, g, w) for c, g, w in zip(COSTS, got, want) if g != w]


def test_calc_unit_price_bad_input_is_zero():
    from modules.case.api.quotations import _calc_unit_price
    for bad in (None, "", "abc", float("nan"), float("inf"), -float("inf"), 1e300, 1e13, -1, 0, "0"):
        assert _calc_unit_price(bad) == 0
    assert _calc_unit_price(1e12) > 0
    assert _calc_unit_price(1000, 1) == 0 and _calc_unit_price(1000, 2) == 0


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _make_draft_and_dispatch(quote_no, disp_items):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "草稿", "測試客戶", "測試專案", 0, 0,
             json.dumps({"items": [{"id": "orig-1", "description": "原有品項", "qty": 1, "unitPrice": 100, "amount": 100}]}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, total_amount, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (quote_no, "2026-01-01", "items", json.dumps(disp_items, ensure_ascii=False), 0, "pending",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"))
        did = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.commit()
        return did
    finally:
        conn.close()


def _items(quote_no):
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()["data_json"])["items"]
    finally:
        conn.close()


def test_import_writes_unit_price_and_amount(client, make_user):
    from helpers.legal_params import round_half_up
    from modules.case.api.quotations import _calc_unit_price
    from modules.case.profit_guard import item_amount
    username, password = make_user("t83_append_admin", role="admin")
    tok = _login(client, username, password)
    disp = [{"description": "配線施工", "qty": 3, "unit": "式", "unitPrice": 1200},
            {"description": "小數量", "qty": 2.5, "unit": "組", "unitPrice": 333},
            {"description": "贈品（成本 0）", "qty": 1, "unit": "式", "unitPrice": 0}]
    did = _make_draft_and_dispatch("MQ-T83-A01", disp)
    r = client.post(f"/api/contractor-dispatches/{did}/import-to-quote", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    rows = _items("MQ-T83-A01")
    assert [i.get("type") for i in rows] == [None, "header", None, None, None]
    assert rows[0]["amount"] == 100, "原有品項不可被動到"
    a, b, gift = rows[2], rows[3], rows[4]
    p1 = _calc_unit_price(1200)
    assert a["unitPrice"] == p1 > 1200 and a["cost"] == 1200 and a["margin"] == 0.30 and a["unitPriceOverride"] is False
    assert a["amount"] == round_half_up(3, p1)
    p2 = _calc_unit_price(333)
    assert b["unitPrice"] == p2 and b["amount"] == round_half_up(2.5, p2)
    assert gift["unitPrice"] is None and gift["amount"] == 0, "成本 0（沒填）維持 None／0，與舊行為相同"
    for it in rows[2:4]:
        assert it["amount"] == item_amount(it), "寫入的 amount 必須與伺服器重算（profit_guard.item_amount）逐位相同，否則 v2 存檔後金額會跳動"


def test_import_with_infinite_cost_does_not_500(client, make_user):
    """hichan-9 L1：派工品項 unitPrice＝1e999（合法 JSON，Python 讀成 inf）⇒ 不可 OverflowError／500；該列當沒填（None／0），其他列照常算。"""
    username, password = make_user("t83_append_inf", role="admin")
    tok = _login(client, username, password)
    import db
    did = _make_draft_and_dispatch("MQ-T83-A02", [{"description": "好列", "qty": 1, "unit": "式", "unitPrice": 1000}])
    conn = db.get_db()
    try:
        raw = '[{"description": "壞列", "qty": 1, "unit": "式", "unitPrice": 1e999}, {"description": "好列", "qty": 1, "unit": "式", "unitPrice": 1000}]'
        conn.execute("UPDATE contractor_dispatches SET items_json=? WHERE id=?", (raw, did))
        conn.commit()
    finally:
        conn.close()
    r = client.post(f"/api/contractor-dispatches/{did}/import-to-quote", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    rows = _items("MQ-T83-A02")
    bad, good = rows[2], rows[3]
    assert bad["description"] == "壞列" and bad["unitPrice"] is None and bad["amount"] == 0
    assert good["description"] == "好列" and good["unitPrice"] and good["amount"] == good["unitPrice"]


def test_import_with_infinite_cost_or_qty_leaves_the_quote_readable(client, make_user):
    """hichan-9 recheck（Medium）：品項的 cost／qty 是 inf 時，原值存進 data_json 會變成 `Infinity`（不是合法 JSON），
    該報價單的 GET 直接 500。壞值要在寫入前換成安全值（cost→0、qty→0），GET 必須 200、data_json 不含 Infinity。"""
    username, password = make_user("t83_append_inf2", role="admin")
    tok = _login(client, username, password)
    hd = {"Authorization": f"Bearer {tok}"}
    import db
    for qn, raw in (("MQ-T83-A03", '[{"description": "壞成本", "qty": 1, "unit": "式", "unitPrice": 1e999}]'),
                    ("MQ-T83-A04", '[{"description": "壞數量", "qty": 1e999, "unit": "式", "unitPrice": 1000}]'),
                    ("MQ-T83-A05", '[{"description": "超大數量", "qty": 1e12, "unit": "式", "unitPrice": 1000}]')):
        did = _make_draft_and_dispatch(qn, [{"description": "x", "qty": 1, "unit": "式", "unitPrice": 1}])
        conn = db.get_db()
        try:
            conn.execute("UPDATE contractor_dispatches SET items_json=? WHERE id=?", (raw, did))
            conn.commit()
            assert client.post(f"/api/contractor-dispatches/{did}/import-to-quote", headers=hd).status_code == 200
            data_json = conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (qn,)).fetchone()["data_json"]
        finally:
            conn.close()
        assert "Infinity" not in data_json and "NaN" not in data_json, (qn, data_json[:300])
        r = client.get(f"/api/quotations/{qn}", headers=hd)
        assert r.status_code == 200, (qn, r.status_code, r.text[:200])
        row = _items(qn)[-1]
        assert row["qty"] in (0, 0.0) or qn == "MQ-T83-A03", (qn, row)
        assert row["amount"] == 0, (qn, row)
        assert row["cost"] in (0, 0.0) or qn != "MQ-T83-A03", (qn, row)
