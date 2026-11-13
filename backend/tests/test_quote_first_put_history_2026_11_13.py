# -*- coding: utf-8 -*-
"""新報價單第一次 PUT 不該多記一筆「其他內容」（2026-11-13，PM 派工；hichan-4 做估價單時發現、hichan-2 審查也記到）。

原因：建單時 `_sync_stages_to_json` 會把 caseRecord.stages 重建成 case_stages 表裡的樣子（配真實 id、補齊 dependsOn／visits／assignedTo…），
而使用者手上（前端記憶體）那份還是暫時 id、欄位不齊；第一次 PUT 把「資料庫現值」和「使用者送來的」整包比對，階段不同就補一筆「其他內容」，
但使用者什麼都沒改。**PUT 本來就完全忽略用戶端的 stages（case_stages 表才是權威）**，所以任何階段差異都是幻影——整包比對一律不看階段
（hichan-10 審查：只比「存檔欄位」仍會在舊分頁存檔、或改了名字但沒被存的情況下多記一筆）。另一個同型來源：款項日期只在 PUT 才正規化成 YYYY-MM-DD（建單不做）。
修法：整包比對前把兩邊都套同一個「正規化檢視」（略過 stages、款項日期同存檔規則）。會被存下來而且使用者真的改了的值仍然不同 ⇒ 仍記；
內容指紋（content_fp）不動、檢視不改輸入。
"""
import copy
import json

import pytest

from tests._requires import requires_module
from tests.test_doc_versions_2026_09_14 import _get_data, pdf_jobs, su  # noqa: F401  同一組夾具（登入／攔下 PDF 產生）

needs_m01 = requires_module("case", "本題打 M01（案件）的報價單端點")


def _payload(**case_over):
    case = {"roles": {}, "payment": {"items": []},
            "stages": [{"id": "tmp1", "label": "叫料", "done": False, "dueDate": "2026-10-01"},
                       {"id": "tmp2", "label": "安裝", "done": False}]}
    case.update(case_over)
    return {"status": "草稿", "data": {
        "customerName": "A", "projectName": "P", "quoteDate": "2026-09-14", "validDays": 30, "salesPerson": "S",
        "items": [{"name": "x", "qty": 1, "price": 100, "cost": 60}], "tot": {"total": 105, "pretax": 100},
        "taxType": "taxable", "taxRate": 5, "caseRecord": case}}


def _create(client, su, payload):
    r = client.post("/api/quotations", json=payload, headers=su)
    assert r.status_code == 201, r.text
    return r.json()["quote_no"]


def _put(client, su, no, payload):
    r = client.put(f"/api/quotations/{no}", json=payload, headers=su)
    assert r.status_code == 200, r.text


def _history(no):
    return _get_data(no).get("editHistory") or []


# ── 主題：第一次 PUT 不多記 ─────────────────────────────────────────────────────

@needs_m01
def test_first_put_of_an_untouched_new_quote_writes_no_history(client, su, pdf_jobs):
    """修之前這裡有一筆「其他內容」（階段 id／欄位被建單重建過）；修之後沒有。"""
    p = _payload()
    no = _create(client, su, p)
    stored = _get_data(no)["caseRecord"]["stages"]
    assert [s["id"] for s in stored] != ["tmp1", "tmp2"] and "visits" in stored[0], "前提：建單真的把階段重建過（否則這題在驗空氣）"
    _put(client, su, no, copy.deepcopy(p))
    assert _history(no) == []


@needs_m01
def test_repeated_saves_stay_quiet_too(client, su, pdf_jobs):
    p = _payload()
    no = _create(client, su, p)
    for _ in range(3):
        _put(client, su, no, copy.deepcopy(p))
    assert _history(no) == []


# ── 正向對照：真的改了就要記（少了這幾題，「一律不記」也會讓上面綠）──────────────────

@needs_m01
def test_stage_differences_are_phantoms_because_put_ignores_client_stages(client, su, pdf_jobs):
    """PUT 忽略用戶端 stages、表為權威：改名／改日期／改完成／刪階段送來也不會被存下來 ⇒ 不是使用者的變更，不記；
    而且（前提）資料庫裡的階段確實沒有被這些值改動——不然這題就變成「該記沒記」。"""
    for mutate in (lambda s: s[0].__setitem__("label", "叫料（改）"),
                   lambda s: s[1].__setitem__("dueDate", "2026-12-31"),
                   lambda s: s[1].__setitem__("done", True),
                   lambda s: s[0].__setitem__("assignedTo", ["u1"]),
                   lambda s: s.pop()):
        p = _payload()
        no = _create(client, su, p)
        before = _get_data(no)["caseRecord"]["stages"]
        p2 = copy.deepcopy(p)
        mutate(p2["data"]["caseRecord"]["stages"])
        _put(client, su, no, p2)
        assert _get_data(no)["caseRecord"]["stages"] == before, "前提：PUT 沒有採用用戶端的階段"
        assert _history(no) == [], mutate


@needs_m01
def test_first_put_with_an_untracked_top_level_field_change_is_still_recorded(client, su, pdf_jobs):
    p = _payload()
    no = _create(client, su, p)
    p2 = copy.deepcopy(p)
    p2["data"]["某個沒被追蹤的欄位"] = "有人改了這裡"
    _put(client, su, no, p2)
    assert [c["field"] for c in _history(no)[0]["changes"]] == ["其他內容"]


@needs_m01
def test_real_change_alongside_phantom_stage_differences_is_still_recorded(client, su, pdf_jobs):
    """幻影的階段差異（暫時 id、欄位不齊）與真的改動同時存在：真的改動（頂層未追蹤欄位）不能被一起吞掉。"""
    p = _payload()
    no = _create(client, su, p)
    p2 = copy.deepcopy(p)                      # 暫時 id 照舊、欄位不齊照舊
    p2["data"]["某個沒被追蹤的欄位"] = "x"
    _put(client, su, no, p2)
    assert len(_history(no)) == 1


# ── 款項日期：同一類來源（只在 PUT 才正規化）────────────────────────────────────────

def _pay(date, amount=1000):
    return {"items": [{"name": "頭期款", "amount": amount, "receivedAt": date}]}


@needs_m01
def test_payment_date_format_normalization_alone_is_not_a_change_but_amount_is(client, su, pdf_jobs):
    p = _payload(payment=_pay("2026/09/01"))
    no = _create(client, su, p)
    _put(client, su, no, copy.deepcopy(p))
    assert _get_data(no)["caseRecord"]["payment"]["items"][0]["receivedAt"] == "2026-09-01", "前提：PUT 真的把日期寫成標準格式"
    assert _history(no) == []
    p2 = _payload(payment=_pay("2026/09/01"))                 # 另一張單：日期寫法不同＋金額真的改了
    no2 = _create(client, su, p2)
    p2b = copy.deepcopy(p2)
    p2b["data"]["caseRecord"]["payment"]["items"][0]["amount"] = 2000
    _put(client, su, no2, p2b)
    assert len(_history(no2)) == 1


# ── 單元：檢視不改輸入、內容指紋不受影響 ─────────────────────────────────────────────

@needs_m01
def test_diff_view_does_not_mutate_input_and_leaves_the_content_fingerprint_alone():
    from modules.case import content_fp
    from modules.case.api import quotations as Q
    d = _payload(payment=_pay("2026/09/01"))["data"]
    d["caseRecord"]["stages"][0].update({"id": 7, "dependsOn": [1], "visits": [{"x": 1}]})
    before, fp = copy.deepcopy(d), content_fp.content_fingerprint(d)
    view = Q._diff_view(d)
    assert d == before and content_fp.content_fingerprint(d) == fp
    assert view["caseRecord"]["payment"]["items"][0]["receivedAt"] == "2026-09-01"
    assert "stages" not in view["caseRecord"] and "stages" in d["caseRecord"]


@needs_m01
def test_summarize_unit_stages_ignored_other_fields_not():
    from modules.case.api import quotations as Q
    old = _payload()["data"]
    old["caseRecord"]["stages"] = [{"id": 1, "label": "叫料", "done": True, "assignedTo": ["z"], "dependsOn": [], "visits": []}]
    new = _payload()["data"]
    assert Q._summarize_quote_changes(old, new) == [], "階段整個不比"
    new["caseRecord"]["roles"] = {"x": 1}
    assert Q._summarize_quote_changes(old, new) == [{"field": "其他內容", "from": "", "to": ""}]


@needs_m01
def test_payment_date_keys_are_one_shared_constant():
    """PUT 的正規化迴圈與整包比對用同一份清單（審查 L：不要兩處各寫一份）。"""
    import inspect
    from modules.case.api import quotations as Q
    assert Q._PAYMENT_DATE_KEYS == ("receivedAt", "expectedReceiptDate", "invoiceDate")
    src = inspect.getsource(Q)
    assert src.count('"receivedAt", "expectedReceiptDate", "invoiceDate"') == 1, "字面清單只該在常數定義處出現一次"
