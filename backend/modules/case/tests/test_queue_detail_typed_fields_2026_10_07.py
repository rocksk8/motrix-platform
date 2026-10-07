# -*- coding: utf-8 -*-
"""簽核佇列詳情（approval.detail / extra_expense）要顯示費用單據的**類型欄位**（2026-10-07 使用者：請購單的「採購備註說明」在佇列詳情看不到）。

類型欄位存在 `case_extra_expenses.data_json`，標籤與順序取自類型定義（`helpers/expense_type_defs/*.json`）。只放 T1 一般資料的純文字類欄位（text／textarea／select／radio／date／daterange），
空值略過、長度有上限；表格、公式、參照、數字、出納專用、非 T1 的欄位一律不放。舊版額外支出（kind=''）的詳情不變。"""
import json

import pytest

from modules.case.api import quotations as Q
from tests._requires import requires_module

pytestmark = requires_module("case", "額外支出在 M01")

_MAKE_USER_DEFAULT_ROLE = "superadmin"


@pytest.fixture(autouse=True)
def _db_ready(client):
    """建好隔離的資料庫與表（`client` 夾具）；題目直接呼叫提供者函式也要有表。"""
    yield


def _db():
    import db
    return db.get_db()


def _seed(kind="purchase_req", data=None, note="舊備註", doc_code="PR-20310601-0001", def_version=0):
    c = _db()
    try:
        cur = c.execute(
            "INSERT INTO case_extra_expenses (quote_no, category, description, qty, unit, unit_cost, total_cost, expense_date, files_json, created_by, created_by_name,"
            " payer_name, created_at, updated_at, status, kind, doc_code, data_json, lines_json, def_version, note, approval_json)"
            " VALUES ('',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("請購", "線材", 1, "", 1000, 1000, "2031-06-01", "[]", "tq_eng", "工程師", "工程師", "2031-06-01", "2031-06-01", "待審核", kind, doc_code,
             json.dumps(data or {}, ensure_ascii=False), "[]", def_version, note, "{}"))
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _fields(eid):
    c = _db()
    try:
        d = Q.detail_extra_expense(c, str(eid))
    finally:
        c.close()
    return {f["label"]: f["value"] for f in d["fields"]}, d


PR = {"ptype": "辦公庶務用品", "urgency": "急件", "need_period": {"from": "2031-06-10", "to": "2031-06-20"}, "remark": "請於週五前到貨\n含發票",
      "dept": 3, "applicant": "tq_eng", "total": 1000}


def test_purchase_req_detail_shows_ptype_urgency_need_period_and_remark():
    f, d = _fields(_seed(data=PR))
    assert f["採購類型"] == "辦公庶務用品" and f["緊急程度"] == "急件"
    assert f["需求日期"] == "2031-06-10 ～ 2031-06-20"
    assert f["採購備註說明"] == "請於週五前到貨\n含發票"
    assert f["備註"] == "舊備註", "原有欄位不變"
    assert {"單號", "類型", "收款人", "類別", "項目"} <= set(f)
    assert d["caseless"] is True and d["title"].startswith("請購單")


def test_existing_fields_come_first_in_the_same_order_and_typed_ones_are_appended():
    _, d = _fields(_seed(data=PR))
    labels = [x["label"] for x in d["fields"]]
    assert labels.index("備註") < labels.index("收款人") < labels.index("採購類型") < labels.index("採購備註說明")
    assert labels.index("採購類型") < labels.index("緊急程度") < labels.index("需求日期")


def test_empty_values_tables_formulas_refs_and_numbers_are_not_shown():
    f, _ = _fields(_seed(data={"ptype": "其他", "remark": "   ", "urgency": "", "lines": [{"x": 1}], "total": 5000, "dept": 3, "applicant": "x"}))
    assert f["採購類型"] == "其他"
    for absent in ("採購備註說明", "緊急程度", "需求日期", "明細", "合計", "部門", "申請人", "total", "lines"):
        assert absent not in f, absent


def test_other_kinds_render_their_own_labels_and_a_clashing_label_gets_a_suffix():
    f, d = _fields(_seed("purchase_order", {"vendor": "甲廠商", "delivery_date": "2031-07-01", "urgency": "一般", "remark": "含運", "pay_terms": "月結30天",
                                             "remit_date": "2031-07-15", "pr_no": "PR-20310601-0001"}, doc_code="PO-20310601-0001"))
    assert f["廠商"] == "甲廠商" and f["預計交貨日"] == "2031-07-01" and f["付款條件"] == "月結30天" and f["匯款日"] == "2031-07-15" and f["請購單號"] == "PR-20310601-0001"
    assert f["備註"] == "舊備註" and f["備註（表單）"] == "含運", "撞名的標籤加後綴，原本的備註不被蓋掉"
    labels = [x["label"] for x in d["fields"]]
    assert len(labels) == len(set(labels)), "標籤不可重複（佇列前端用標籤當 key）"
    f, d = _fields(_seed("travel", {"place": "國內", "city": "台中", "period": {"from": "2031-06-01", "to": "2031-06-03"}, "pay_date": "2031-06-30", "remark": "客戶拜訪"}, doc_code="TE-20310601-0001"))
    assert f["地點"] == "國內" and f["國家／城市"] == "台中" and f["出差區間"] == "2031-06-01 ～ 2031-06-03" and f["付款日"] == "2031-06-30" and f["備註（表單）"] == "客戶拜訪"
    f, d = _fields(_seed("petty_cash", {"payee": "王小姐", "remark": "文具"}, doc_code="PC-20310601-0001"))
    assert f["支付對象／事由"] == "王小姐" and f["備註（表單）"] == "文具"


def test_legacy_kind_empty_detail_is_unchanged():
    f, d = _fields(_seed(kind="", data={"remark": "不該出現", "ptype": "x"}, doc_code=""))
    assert "不該出現" not in f.values() and "採購類型" not in f
    assert [x["label"] for x in d["fields"]] == ["類別", "項目", "數量", "單價", "小計", "支出日期", "單據號碼", "支出人", "填寫人", "備註"]
    assert "caseless" not in d


def test_non_t1_cashier_and_long_values_are_handled(monkeypatch):
    from helpers import expense_types as ET
    real = ET.get_type

    def patched(conn, code, version=None):
        t = real(conn, code, version)
        body = json.loads(json.dumps(t["body"]))
        body["fields"] += [{"key": "secret", "label": "個資欄", "type": "text", "dataClass": "F2"},
                           {"key": "cashier_note", "label": "出納專用", "type": "text", "dataClass": "T1", "cashier": True},
                           {"key": "long", "label": "長文", "type": "textarea", "dataClass": "T1"}]
        return dict(t, body=body)
    monkeypatch.setattr(ET, "get_type", patched)
    f, _ = _fields(_seed(data=dict(PR, secret="A123456789", cashier_note="內部", long="字" * 900)))
    assert "個資欄" not in f and "出納專用" not in f, "非 T1／出納專用欄位不顯示"
    assert "A123456789" not in json.dumps(f, ensure_ascii=False)
    assert len(f["長文"]) == Q._TYPED_DETAIL_MAX + 1 and f["長文"].endswith("…"), "長度有上限"


def test_broken_data_or_missing_definition_does_not_break_the_detail(monkeypatch):
    c = _db()
    try:
        eid = _seed(data=PR)
        c.execute("UPDATE case_extra_expenses SET data_json='{壞掉' WHERE id=?", (eid,))
        c.commit()
    finally:
        c.close()
    f, _ = _fields(eid)
    assert f["項目"] == "線材" and "採購備註說明" not in f
    from helpers import expense_types as ET
    monkeypatch.setattr(ET, "get_type", lambda *a, **k: None)
    f2, _ = _fields(_seed(data=PR, doc_code="PR-20310601-0002"))
    assert f2["項目"] == "線材" and "採購類型" not in f2


def test_endpoint_shows_remark_to_the_approver_and_hides_it_from_outsiders(client, make_user):
    """經 L1 `/api/approval-queue/detail`：簽核人（最高管理者）看得到；無案件單據（caseless）非簽核鏈／非送審人／非最高管理者 ⇒ 404。"""
    eid = _seed(data=PR)
    u, p = make_user(username="tq_sa", role="superadmin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    r = client.get("/api/approval-queue/detail", params={"type": "extra_expense", "id": str(eid)}, headers=h)
    assert r.status_code == 200, r.text
    vals = {f["label"]: f["value"] for f in r.json()["fields"]}
    assert vals["採購備註說明"] == "請於週五前到貨\n含發票" and vals["緊急程度"] == "急件"
    u2, p2 = make_user(username="tq_plain", role="user", modules=["case_manage"], legacy_finance_flag=False)
    h2 = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u2, "password": p2}).json()["token"]}
    r2 = client.get("/api/approval-queue/detail", params={"type": "extra_expense", "id": str(eid)}, headers=h2)
    assert r2.status_code == 404 and "請於週五前到貨" not in r2.text
