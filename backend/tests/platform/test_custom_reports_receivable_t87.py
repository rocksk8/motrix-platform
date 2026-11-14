# -*- coding: utf-8 -*-
"""T87 B2 D2：自訂報表的資料來源「應收帳款」（receivable）。

釘住的規則（PM／使用者裁示）：
- 不另寫第二套口徑：自訂報表算出的未收合計＝B1 應收帳齡（/api/reports/ar-aging、標準報表 ar-aging）的合計，逐筆也相同；
- 閘門＝B1 應收帳齡的閘門；沒有閘門的人（業務、工程師…）來源清單看不到、預覽／存檔／匯出一律 404；
- 金額欄（請款／已收／未收）依 can_see_financial 遮罩：通過閘門但沒有財務身分的人（營運報表＋出納）看得到非金額欄，金額欄被拿掉、不可篩選／分組／排序；
- 匯出以執行者自己的權限重算：隱藏欄的名稱與數值都不在檔裡；
- 列範圍（row_access receivable）併入每一支查詢：未登錄 ⇒ 恆假。
"""
import io
import json
import zipfile
import html as _html

import openpyxl
import pytest

from db import get_db
from helpers import report_catalog as RC
from helpers import row_access
from helpers import settings_registry as R
from helpers import xlsx_out as X
from modules.analytics.api import custom_reports as CR

BASE = "/api/custom-reports"
SENT = 8123457          # 未收金額的哨兵值（只該出現在有權限者的檔）


@pytest.fixture(autouse=True)
def _on(client):
    CR.reset_rate_limit()
    X._export_times.clear()
    c = get_db()
    try:
        R.publish("custom_reports", {"enabled": 1}, reason="測試", user="sa_ar", conn=c)
    finally:
        c.close()
    R.invalidate()
    yield
    X._export_times.clear()
    R.invalidate()


def _login(client, make_user, name, role="viewer", modules=None):
    kw = {"username": name, "role": role}
    if modules is not None:
        kw["modules"] = modules
    u, p = make_user(**kw)
    tok = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _case(no, customer, pay, quote_date="2026-10-05", total=105000, pretax=100000):
    data = {"dealTag": "已成案", "caseRecord": {"payment": {"items": pay}}}
    c = get_db()
    try:
        c.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at,"
            " deal_tag, quote_date, sales_person, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (no, "已送出", customer, "專案" + no, total, pretax, json.dumps(data, ensure_ascii=False), "2026-10-01T00:00:00",
             "2026-10-01T00:00:00", "已成案", quote_date, "業務甲", "[]"))
        c.commit()
    finally:
        c.close()


@pytest.fixture
def world(client):
    _case("AR-1", "甲公司", [{"type": "訂金", "amount": 52500, "received": True, "receivedAt": "2026-10-20"},
                              {"type": "尾款", "amount": SENT, "received": False, "expectedReceiptDate": "2026-12-31"}])
    _case("AR-2", "乙公司", [{"type": "全額", "amount": 210000, "received": False}], quote_date="2026-08-01", total=210000, pretax=200000)
    _case("AR-3", "丙公司", [{"type": "全額", "amount": 1000, "received": True}], total=1000, pretax=1000)   # 全部已收：預設（未收）看不到


@pytest.fixture
def no_financial(monkeypatch):
    """「通過閘門、但沒有財務身分」：目前預設設定下閘門與 can_see_financial 同一組人（財務角色／superadmin），這種人只會在職責角色化
    把財務能力個別扣掉之後出現。這裡直接讓指定帳號的 can_see_financial 回 False、閘門（has_finance_access）照舊放行——模擬那個狀態。"""
    from helpers import auth
    deny = set()
    real = auth.can_see_financial
    monkeypatch.setattr(auth, "can_see_financial", lambda u: False if (u or {}).get("username") in deny else real(u))
    return deny


def _def(**kw):
    d = {"version": 1, "source": "receivable", "columns": ["quote_no", "customer_name", "outstanding", "days", "band"]}
    d.update(kw)
    return d


def _preview(client, h, **kw):
    return client.post(BASE + "/preview", json=_def(**kw), headers=h)


def _col_index(j, label):
    return [c["label"] for c in j["columns"]].index(label)


# ── 口徑：與 B1 應收帳齡相同 ─────────────────────────────────────────────

def test_total_outstanding_equals_b1_ar_aging_total_and_rows_match_item_by_item(client, make_user, world):
    sa = _login(client, make_user, "ar_sa", role="superadmin")
    b1 = client.get("/api/reports/ar-aging", headers=sa).json()
    assert b1["total"]["amount"] == SENT + 210000 and b1["total"]["count"] == 2           # 正對照：B1 的母體不是空的
    r = _preview(client, sa, layout="detail", columns=["quote_no", "outstanding", "days", "band"],
                 aggregates=[{"field": "outstanding", "fn": "sum"}], sort=[{"field": "quote_no", "dir": "asc"}])
    assert r.status_code == 200, r.text
    j = r.json()
    total = next(x for x in j["rows"] if x["k"] == "total")
    assert b1["total"]["amount"] in total["v"]                                          # 總計列的未收合計＝B1 的未收合計
    rows = [x["v"] for x in j["rows"] if x["k"] == "row"]
    assert len(rows) == b1["total"]["count"]                                             # 預設只看未收＝B1 的母體
    b1_items = {i["quoteNo"]: i for b in b1["bands"] for i in b["items"]}
    q, o, d, band = (_col_index(j, "案件號"), _col_index(j, "未收金額"), _col_index(j, "帳齡天數"), _col_index(j, "帳齡區間"))
    labels = {b["key"]: b["label"] for b in b1["bands"]}
    for v in rows:
        it = b1_items[v[q]]
        assert v[o] == it["amount"] and v[d] == it["daysElapsed"]
        assert v[band] == next(b["label"] for b in b1["bands"] if it in b["items"])
    assert set(labels.values()) >= {v[band] for v in rows}


def test_summary_total_equals_b1_total_and_includes_billed_received_columns(client, make_user, world):
    sa = _login(client, make_user, "ar_sa2", role="superadmin")
    b1 = client.get("/api/reports/ar-aging", headers=sa).json()["total"]["amount"]
    r = _preview(client, sa, layout="summary", columns=[], filters=[],            # 空條件＝含已收
                 aggregates=[{"field": "outstanding", "fn": "sum"}, {"field": "received_amt", "fn": "sum"}, {"field": "billed", "fn": "sum"}])
    assert r.status_code == 200, r.text
    j = r.json()
    row = next(x for x in j["rows"] if x["k"] == "row")["v"]
    labels = [c["label"] for c in j["columns"]]
    by = dict(zip(labels, row))
    assert by["未收金額（合計）"] == b1
    assert by["已收金額（合計）"] == 52500 + 1000
    assert by["請款金額（合計）"] == b1 + 52500 + 1000                                 # 請款＝已收＋未收，沒有第二套算法


def test_default_filter_is_unreceived_and_can_be_changed_to_received_only(client, make_user, world):
    sa = _login(client, make_user, "ar_sa3", role="superadmin")
    default = _preview(client, sa, columns=["quote_no", "status"]).json()
    assert {x["v"][1] for x in default["rows"] if x["k"] == "row"} == {"未收"}
    got = _preview(client, sa, columns=["quote_no", "status", "outstanding", "days", "band"],
                   filters=[{"field": "status", "op": "eq", "value": "已收"}], sort=[{"field": "quote_no", "dir": "asc"}]).json()
    rows = [x["v"] for x in got["rows"] if x["k"] == "row"]
    assert [v[0] for v in rows] == ["AR-1", "AR-3"] and all(v[2] == 0 for v in rows) and all(v[3] in (None, "") for v in rows)


# ── 閘門 ──────────────────────────────────────────────────────────────────

def test_users_without_the_b1_gate_do_not_see_the_source_and_get_404(client, make_user, world):
    for name, role, mods in (("ar_sales", "sales", ["quotation", "case_manage"]), ("ar_eng", "engineer", ["quotation"]),
                             ("ar_dev", "viewer", ["dev_crm"])):
        h = _login(client, make_user, name, role=role, modules=mods)
        ids = [s["id"] for s in client.get(BASE + "/sources", headers=h).json()["sources"]]
        assert "receivable" not in ids, name
        assert _preview(client, h).status_code == 404, name
        assert client.post(BASE, json={"name": "x" + name, "definition": _def()}, headers=h).status_code in (404, 422), name
        assert RC.source_available("receivable", {"id": 0, "role": role, "modules": mods, "username": name}) is False


def test_a_report_saved_before_the_gate_was_lost_cannot_be_run_or_exported(client, make_user, world):
    """存檔時有閘門、之後失去閘門：預覽／匯出一律 404（每次重算，不存授權）。"""
    h = _login(client, make_user, "ar_lost", role="finance", modules=["quotation", "reports"])
    r = client.post(BASE, json={"name": "我的應收", "definition": _def()}, headers=h)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    c = get_db()
    try:
        c.execute("UPDATE users SET role='viewer', modules=? WHERE username='ar_lost'", (json.dumps(["quotation"]),))
        c.commit()
    finally:
        c.close()
    h2 = _login_again(client, "ar_lost")
    assert "receivable" not in [s["id"] for s in client.get(BASE + "/sources", headers=h2).json()["sources"]]
    assert client.post("%s/%d/export" % (BASE, rid), headers=h2).status_code == 404
    assert _preview(client, h2).status_code == 404


def _login_again(client, name):
    c = get_db()
    try:
        row = c.execute("SELECT username FROM users WHERE username=?", (name,)).fetchone()
    finally:
        c.close()
    assert row
    # make_user 建立的密碼固定；重新登入拿到新權限
    p = client.post("/api/auth/login", json={"username": name, "password": "Test-Pass-123"})
    assert p.status_code == 200, p.text
    return {"Authorization": "Bearer " + p.json()["token"]}


# ── 金額遮罩（通過閘門但沒有財務身分）──────────────────────────────────────

def test_gate_holder_without_financial_sees_non_money_columns_but_money_columns_are_masked(client, make_user, world, no_financial):
    h = _login(client, make_user, "ar_cash", role="finance", modules=["quotation", "reports"])
    no_financial.add("ar_cash")
    ids = [s["id"] for s in client.get(BASE + "/sources", headers=h).json()["sources"]]
    assert "receivable" in ids                                                           # 閘門過了（reports＋money_visible）
    src = next(s for s in client.get(BASE + "/sources", headers=h).json()["sources"] if s["id"] == "receivable")
    vis = {f["id"]: f.get("visible", True) for f in src["fields"]}
    assert vis["outstanding"] is False and vis["billed"] is False and vis["received_amt"] is False
    assert vis["quote_no"] is True and vis["days"] is True and vis["band"] is True
    r = _preview(client, h, columns=["quote_no", "customer_name", "outstanding", "billed", "days", "band"], sort=[{"field": "days", "dir": "desc"}])
    assert r.status_code == 200, r.text
    j = r.json()
    assert [c["label"] for c in j["columns"]] == ["案件號", "客戶", "帳齡天數", "帳齡區間"]
    assert j["hiddenCount"] == 2 and str(SENT) not in r.text and "210000" not in r.text
    assert len([x for x in j["rows"] if x["k"] == "row"]) == 2                            # 非金額欄的列照給
    for field, body in (("filters", [{"field": "outstanding", "op": "gte", "value": 1}]),
                        ("groupBy", [{"field": "outstanding"}]), ("sort", [{"field": "outstanding", "dir": "desc"}])):
        rr = _preview(client, h, **{field: body})
        assert rr.status_code == 422 and rr.json()["detail"]["reason"] == "no_permission", field
    agg = _preview(client, h, layout="summary", columns=[], groupBy=[{"field": "customer_name"}], aggregates=[{"field": "outstanding", "fn": "sum"}])
    assert agg.status_code == 200 and agg.json()["hiddenCount"] == 1 and str(SENT) not in agg.text


def test_finance_role_sees_money_columns(client, make_user, world):
    h = _login(client, make_user, "ar_fin", role="finance", modules=["quotation", "reports"])
    j = _preview(client, h, columns=["quote_no", "outstanding"]).json()
    assert [c["label"] for c in j["columns"]] == ["案件號", "未收金額"] and j["hiddenCount"] == 0
    assert SENT in [x["v"][1] for x in j["rows"] if x["k"] == "row"]


# ── 匯出 ──────────────────────────────────────────────────────────────────

def _all_text(data: bytes) -> str:
    z = zipfile.ZipFile(io.BytesIO(data))
    return _html.unescape("\n".join(z.read(n).decode("utf-8", "ignore") for n in z.namelist()))


def test_export_recomputed_with_the_executors_own_permissions_hidden_columns_are_not_in_the_file(client, make_user, world, no_financial):
    owner = _login(client, make_user, "ar_exo", role="superadmin")
    r = client.post(BASE, json={"name": "應收匯出", "definition": _def(columns=["quote_no", "customer_name", "outstanding", "billed", "days"])}, headers=owner)
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    full = client.post("%s/%d/export" % (BASE, rid), headers=owner)
    assert full.status_code == 200, full.text
    assert str(SENT) in _all_text(full.content) and "未收金額" in _all_text(full.content)                  # 正對照：有權限者的檔含金額
    ws = openpyxl.load_workbook(io.BytesIO(full.content))["報表"]
    assert "請款金額" in [c.value for c in ws[5]]
    # 同一份報表由「通過閘門但沒有財務身分」的人自己建、自己匯出：金額欄名稱與數值都不在整包 xlsx 裡
    cash = _login(client, make_user, "ar_exc", role="finance", modules=["quotation", "reports"])
    no_financial.add("ar_exc")
    r2 = client.post(BASE, json={"name": "出納應收", "definition": _def(columns=["quote_no", "customer_name", "outstanding", "billed", "days"])}, headers=cash)
    assert r2.status_code == 201, r2.text
    ex = client.post("%s/%d/export" % (BASE, r2.json()["id"]), headers=cash)
    assert ex.status_code == 200, ex.text
    text = _all_text(ex.content)
    assert "AR-1" in text and "甲公司" in text                                                       # 非金額欄在
    assert str(SENT) not in text and "未收金額" not in text and "請款金額" not in text and "210000" not in text
    info = {row[0].value: row[1].value for row in openpyxl.load_workbook(io.BytesIO(ex.content))["說明"].iter_rows()}
    assert info["已隱藏欄位數"] == 2


# ── 列範圍 ────────────────────────────────────────────────────────────────

def test_row_scope_is_applied_to_every_query_and_fails_closed_when_unregistered(client, make_user, world, monkeypatch):
    sa = _login(client, make_user, "ar_row", role="superadmin")
    assert len([x for x in _preview(client, sa).json()["rows"] if x["k"] == "row"]) == 2           # 正對照
    monkeypatch.setattr(row_access, "_REGISTRY", {k: v for k, v in row_access._REGISTRY.items() if k != "receivable"})
    d = _preview(client, sa).json()
    assert d["totalRows"] == 0 and [x for x in d["rows"] if x["k"] == "row"] == []
    monkeypatch.undo()
    assert row_access.filter_sql("receivable", {"id": 1, "role": "viewer", "modules": json.dumps(["quotation"])}, scope="read")[0].strip() == "AND 0"
    assert row_access.filter_sql("receivable", {"id": 1, "role": "viewer", "modules": json.dumps(["reports"])}, scope="read")[0] == ""
    assert row_access.filter_sql("receivable", {"id": 1, "role": "finance", "modules": "[]"}, scope="read")[0] == ""


def test_catalog_registration_is_valid_and_amounts_are_in_the_field_catalog():
    s = RC.get_source("receivable")
    assert s and s["label"] == "應收帳款" and s["table"] == "receivable_items" and callable(s["gate"])
    assert RC.source_problems("receivable", s) == []
    money = {f["id"]: f["catalogId"] for f in s["fields"] if f["type"] == "money"}
    assert money == {"billed": "receivable.billed", "received_amt": "receivable.received", "outstanding": "receivable.outstanding"}
    assert [f["id"] for f in s["fields"] if f.get("catalogId") is None and "amount" in f["id"]] == []
