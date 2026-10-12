# -*- coding: utf-8 -*-
"""材料申請「從採購單帶入」修正（第 57 班）：供應商必填改為設定選項（預設必填＝今天的行為）、被擋的項目寫伺服器 log、
自動存檔不送出連到未儲存列的連結、前端顯示第一層原因。"""
import json
import logging
from pathlib import Path

import pytest

from tests._requires import skip_module_unless

skip_module_unless("case", "本檔全部是 M01 的叫料審核")

NO = "MQ-MIMP-001"
REPO = Path(__file__).resolve().parents[4]


@pytest.fixture(autouse=True)
def _po_rule_off(monkeypatch):
    from modules.case import material_approval as _MA
    monkeypatch.setattr(_MA, "PO_REQUIRED", False)


def _x(sql, args=()):
    import db
    conn = db.get_db()
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def _cr():
    import db
    conn = db.get_db()
    try:
        return json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])["caseRecord"]
    finally:
        conn.close()


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _order(item, name="交換器", qty=2, price=1500, **kw):
    o = {"itemId": item, "itemName": name, "quantity": qty, "unit": "台", "unitPrice": price, "totalPrice": qty * price,
         "paidStatus": "pending", "paidAmount": 0, "paidDate": "", "notes": "", "supplierId": 1}
    o.update(kw)
    return o


@pytest.fixture
def adm(client, make_user):
    u, p = make_user(username="mi_adm", role="superadmin")
    _x("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
       "VALUES (?,?,?,?,?,?,?,?,?,?)",
       (NO, "已送出", "測試客戶", "測試專案", 1, 1, json.dumps({"dealTag": "已成案", "caseRecord": {"materialOrders": [_order("L1")], "materials": []}}),
        "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
    return _login(client, u, p)


def _patch_orders(client, h, extra):
    rows = _cr()["materialOrders"] + extra
    return client.patch("/api/quotations/%s/material-orders" % NO, json={"materialOrders": rows}, headers=h)


def _codes(r):
    return sorted((x["itemId"], x["code"]) for x in r.json().get("rejected", []))


# ── 供應商規則＝設定選項 ──────────────────────────────────────────────────────

def test_setting_default_is_required_and_registered_as_a_money_class_option():
    import helpers.settings_groups  # noqa: F401  群組在載入時登錄
    from helpers import settings_registry as R
    g = R.groups()["material_order"]
    f = {x["key"]: x for x in g["fields"]}["supplier_required"]
    assert f["default"] == 1 and f["recommended"] == 1 and f["loosen"] == "down" and f["risk"] == "money" and f["riskText"]
    assert [c["value"] for c in f["choices"]] == [1, 0] and all(c["label"] and c["impact"] for c in f["choices"])
    assert R.get("material_order", "supplier_required") == 1


def test_default_requires_a_supplier_even_for_po_linked_new_rows(client, adm):
    r = _patch_orders(client, adm, [_order("N1", "帶入列", 1, 100, supplierId=None, poDocCode="PO-1", poLine=1)])
    assert r.status_code == 200 and _codes(r) == [("N1", "supplier_required")]
    assert [o["itemId"] for o in _cr()["materialOrders"]] == ["L1"]


def test_option_off_exempts_only_po_linked_rows(client, adm, monkeypatch):
    from modules.case import material_guard as MG
    monkeypatch.setattr(MG, "supplier_policy", lambda: 0)
    monkeypatch.setattr(MG, "LINK_VALIDATOR", None)                                      # 本題只測供應商規則，不測採購單連結是否真的存在
    r = _patch_orders(client, adm, [_order("N1", "帶入列", 1, 100, supplierId=None, poDocCode="PO-1", poLine=1),
                                    _order("N2", "手動列", 1, 100, supplierId=None)])
    assert _codes(r) == [("N2", "supplier_required")]                                   # 手動新增的仍要選
    assert sorted(o["itemId"] for o in _cr()["materialOrders"]) == ["L1", "N1"]


def test_unreadable_setting_falls_back_to_required(monkeypatch):
    from helpers import settings_registry as R
    from modules.case import material_guard as MG

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(R, "get", boom)
    assert MG.supplier_policy() == 1


def test_code_level_kill_switch_still_wins(client, adm, monkeypatch):
    from modules.case import material_approval as MA
    monkeypatch.setattr(MA, "SUPPLIER_REQUIRED_ON_NEW", False)
    assert "rejected" not in _patch_orders(client, adm, [_order("N1", "沒供應商", 1, 100, supplierId=None)]).json()


def test_get_exposes_the_policy_to_the_page(client, adm, monkeypatch):
    from modules.case import material_guard as MG
    url = "/api/quotations/%s/material-orders" % NO
    assert client.get(url, headers=adm).json()["supplierRequiredAlways"] is True
    monkeypatch.setattr(MG, "supplier_policy", lambda: 0)
    assert client.get(url, headers=adm).json()["supplierRequiredAlways"] is False


# ── rejected[] 寫伺服器 log ────────────────────────────────────────────────────

def test_rejected_items_are_logged_on_both_save_paths_without_content(client, adm, caplog):
    caplog.set_level(logging.WARNING, logger="modules.case.material_guard")
    _patch_orders(client, adm, [_order("N1", "機密品名甲", 1, 100, supplierId=None)])
    msgs = [r.getMessage() for r in caplog.records if r.name == "modules.case.material_guard"]
    assert any("N1.supplierId=supplier_required" in m and "material-orders" in m and NO in m for m in msgs), msgs
    assert not any("機密品名甲" in m for m in msgs)                                         # 只記編號／欄位／代碼
    caplog.clear()
    cr = _cr()
    cr["materialOrders"] = cr["materialOrders"] + [_order("N2", "機密品名乙", 1, 100, supplierId=None)]
    r = client.patch("/api/quotations/%s/case-record" % NO, json={"case_record": cr}, headers=adm)
    assert r.status_code == 200 and _codes(r) == [("N2", "supplier_required")]
    msgs = [r.getMessage() for r in caplog.records if r.name == "modules.case.material_guard"]
    assert any("N2.supplierId=supplier_required" in m and "case-record" in m for m in msgs), msgs


def test_nothing_is_logged_when_nothing_is_rejected(client, adm, caplog):
    caplog.set_level(logging.WARNING, logger="modules.case.material_guard")
    r = _patch_orders(client, adm, [_order("N1", "有供應商", 1, 100)])
    assert "rejected" not in r.json()
    assert not [x for x in caplog.records if x.name == "modules.case.material_guard"]


# ── 前端靜態守門 ───────────────────────────────────────────────────────────────

def _src(rel):
    return (REPO / rel).read_text(encoding="utf-8")


def test_autosave_snapshot_blanks_links_to_unsaved_order_rows():
    core = _src("frontend/js/case-management-core.js")
    assert "_crForSave()" in core and "this._snapSegments(this._crForSave())" in core
    body = core[core.index("_crForSave() {"):core.index("_snapSegments(cr) {")]
    assert "_saved === false" in body and "orderItemId: ''" in body and "_mlHeldLink = true" in body
    exec_js = _src("frontend/js/case-management-exec.js")
    assert "_mlHeldLink" in exec_js and "this.setDirty()" in exec_js[exec_js.index("_mlHeldLink &&"):][:200]


def test_save_precheck_follows_the_option_and_shows_item_name_with_first_reason():
    js = _src("frontend/js/case-management-exec.js")
    assert "this.moSupplierAlways = moBody.supplierRequiredAlways !== false" in js
    assert "(this.moSupplierAlways || !m.poDocCode)" in js
    assert "const first = d.rejected[0]" in js and "first.message" in js
