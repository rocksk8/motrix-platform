# -*- coding: utf-8 -*-
"""census S-F1：款項期別名稱（案件 payment.items[].type）與請款單款項類別（stage 代碼）的顯示名稱可由選項清單改。

- 值（存進資料的字／代碼）不變：發布後不可刪、不可改字；案件款項期別可新增、改顯示名稱、重排、停用；請款單款項類別是『封閉清單』（只能改顯示名稱與順序）
- 選項清單關著或沒發布 ⇒ 所有消費者的輸出與過去**逐字相同**；開啟且已發布 ⇒ 只改『顯示』（報表、出納、儀表板、應收、行事曆、請款單 PDF）
- 自訂義 + customLabel 的顯示修正也在旗標後面（關著時仍顯示『自訂義』，與今天相同）
- 已入帳的傳票說明（receivables.py 的收款手續費說明）用原字串，不跟著改
"""
import re
from pathlib import Path

import pytest

from core.source_tree import page_file
from helpers import option_lists as OL

ROOT = Path(__file__).resolve().parents[3]
STAGES8 = ["訂金款", "交貨款", "驗收款", "進度款", "完工款", "收款後出貨", "自訂義", "其他"]


def _v(value, label=None, **kw):
    return dict({"value": value, "label": label or value}, **kw)


def _body(vals):
    return {"version": 1, "values": vals}


def _paths(p):
    return {x["path"] for x in p}


def legacy(item, idx):
    return item.get("type", f"第{idx+1}期")


ITEMS = [{}, {"type": ""}, {"type": None}, {"type": "訂金款"}, {"type": "自訂義", "customLabel": "設計費"}, {"type": "自訂義"}, {"type": "自訂義", "customLabel": "  "},
         {"type": "收款後出貨"}, {"type": "舊的名稱"}]


# ── 預設 = 今天寫死的名稱（逐項對照程式與頁面）────────────────────────────────
def test_defaults_equal_the_hard_coded_names_in_pages_and_backend():
    core = (ROOT / "frontend" / "js" / "case-management-core.js").read_text(encoding="utf-8")
    items = re.search(r"STAGE_ITEMS:\s*\[(.*?)\]\.map", core, re.S).group(1)
    assert re.findall(r"'([^']+)'", items) == STAGES8 == [d["value"] for d in OL.BUILTIN["payment_stage"]["defaults"]]
    page = page_file("case-management.html").read_text(encoding="utf-8")
    assert "<option>訂金款</option>" not in page and "stageOptions(item.type)" in page
    from modules.arap.api.payment_requests import PAYMENT_STAGES
    import pdf_gen
    assert {d["value"]: d["label"] for d in OL.BUILTIN["payment_request_stage"]["defaults"]} == PAYMENT_STAGES == pdf_gen._PAYMENT_STAGE_LABELS
    form = page_file("payment-request-form.html").read_text(encoding="utf-8")
    block = form.split("STAGES: [")[1].split("],")[0]
    assert re.findall(r"value: '(\w+)',\s*label: '([^']+)'", block) == [(k, v) for k, v in PAYMENT_STAGES.items()]


# ── OFF／沒發布 = 過去逐字相同 ─────────────────────────────────────────────
@pytest.mark.parametrize("item", ITEMS)
def test_off_or_unpublished_is_identical_to_the_old_expression(monkeypatch, item):
    OL._STAGE_CACHE.clear()
    monkeypatch.setattr(OL, "enabled", lambda conn=None: False)
    assert OL.payment_stage_name(item, 2) == legacy(item, 2)
    OL._STAGE_CACHE.clear()
    monkeypatch.setattr(OL, "enabled", lambda conn=None: True)
    monkeypatch.setattr(OL, "_published_body", lambda lid, conn=None: None)                 # 開了但沒發布
    assert OL.payment_stage_name(item, 2) == legacy(item, 2)
    assert OL.request_stage_label("deposit", "訂金款") == "訂金款"
    OL._STAGE_CACHE.clear()


def _on(monkeypatch, stage_vals=None, req_vals=None):
    OL._STAGE_CACHE.clear()
    monkeypatch.setattr(OL, "enabled", lambda conn=None: True)
    bodies = {"payment_stage": _body(stage_vals) if stage_vals else None, "payment_request_stage": _body(req_vals) if req_vals else None}
    monkeypatch.setattr(OL, "_published_body", lambda lid, conn=None: bodies.get(lid))


def test_on_changes_only_the_display_and_fixes_custom_label(monkeypatch):
    vals = [_v(v) for v in STAGES8]
    vals[0] = _v("訂金款", "頭期款")
    vals.append(_v("保留款"))
    _on(monkeypatch, stage_vals=vals)
    assert OL.payment_stage_name({"type": "訂金款"}, 0) == "頭期款"
    assert OL.payment_stage_name({"type": "驗收款"}, 0) == "驗收款", "沒改名的照舊"
    assert OL.payment_stage_name({"type": "保留款"}, 0) == "保留款", "新增的選項"
    assert OL.payment_stage_name({"type": "舊的名稱"}, 0) == "舊的名稱", "清單裡找不到 ⇒ 原字串"
    assert OL.payment_stage_name({}, 2) == "第3期", "缺 type 鍵 ⇒ 第N期（同過去）"
    assert OL.payment_stage_name({"type": "自訂義", "customLabel": " 設計費 "}, 0) == "設計費", "自訂義顯示使用者填的名稱（過去只顯示『自訂義』）"
    assert OL.payment_stage_name({"type": "自訂義"}, 0) == "自訂義"
    assert OL.payment_stage_name({"type": "自訂義", "customLabel": "  "}, 0) == "自訂義"
    OL._STAGE_CACHE.clear()


def test_request_stage_labels_follow_the_closed_list_and_fall_back(monkeypatch):
    vals = [_v("full", "全額"), _v("deposit", "頭期款"), _v("delivery", "交貨款"), _v("acceptance", "驗收款"), _v("final", "尾款")]
    _on(monkeypatch, req_vals=vals)
    assert OL.request_stage_label("deposit", "訂金款") == "頭期款" and OL.request_stage_label("final", "尾款") == "尾款"
    assert OL.request_stage_label("zzz", "未分類") == "未分類", "代碼不在清單 ⇒ 呼叫端的備用字"
    OL._STAGE_CACHE.clear()


def test_the_cache_is_short_lived():
    OL._STAGE_CACHE.clear()
    assert OL._STAGE_TTL <= 5.0


# ── 封閉清單（請款單 stage）與案件款項期別的驗證 ───────────────────────────
REQ = [_v("full", "全額"), _v("deposit", "訂金款"), _v("delivery", "交貨款"), _v("acceptance", "驗收款"), _v("final", "尾款")]


def test_closed_request_stage_list_only_allows_relabel_and_reorder():
    bad = lambda body: OL.definition_problems("payment_request_stage", body, live={})
    assert bad(_body(REQ)) == []
    assert bad(_body([REQ[1], dict(REQ[0], label="整筆"), *REQ[2:]])) == [], "改名＋重排可以"
    assert "values[5].value" in _paths(bad(_body(REQ + [_v("extra", "新的")]))), "不能新增代碼（後端字典驗證的是這五個）"
    assert "values[1].disabled" in _paths(bad(_body([REQ[0], dict(REQ[1], disabled=True), *REQ[2:]]))), "不能停用"
    assert any("不能少" in p["message"] for p in bad(_body(REQ[:4]))), "不能少"


def test_case_payment_stage_list_can_add_relabel_reorder_disable_but_not_drop_a_default():
    ok = lambda vals: OL.definition_problems("payment_stage", _body(vals), live={})
    base = [_v(v) for v in STAGES8]
    assert ok(base) == []
    assert ok([dict(base[0], label="頭期款")] + base[1:] + [_v("保留款")]) == []
    assert ok(base[:3] + [dict(base[3], disabled=True)] + base[4:]) == []
    assert any("不能少" in p["message"] for p in ok(base[1:]))
    assert "values[8].value" in _paths(ok(base + [_v("=x")]))


# ── 行事曆：改名不會重複建立事件，也不會自己觸發重送 ───────────────────────────
def _cal_items(label="訂金款", note=""):
    return [{"id": 7, "type": label, "received": False, "expectedReceiptDate": "2026-11-01", "note": note}]


def test_calendar_relabel_does_not_trigger_events_and_a_later_change_updates_the_same_event(monkeypatch):
    from modules.case import receipt_calendar as RC
    OL._STAGE_CACHE.clear()
    monkeypatch.setattr(OL, "enabled", lambda conn=None: False)
    old = _cal_items()
    assert RC.events_for_change(old, _cal_items()) == [], "沒變就不產生"
    vals = [_v(v) for v in STAGES8]
    vals[0] = _v("訂金款", "頭期款")
    _on(monkeypatch, stage_vals=vals)
    assert RC.events_for_change(old, _cal_items()) == [], "改了顯示名稱本身不觸發重送（簽章前後用同一組目前的名稱）"
    assert RC.events_for_change(old, _cal_items(note="x")) == [], "備註不在簽章裡 ⇒ 沒有事件"
    ev = RC.events_for_change(old, [dict(_cal_items()[0], expectedReceiptDate="2026-11-15")])
    assert len(ev) == 1 and ev[0][0] == "upsert" and ev[0][2] == "7", "下一次真的有變時：對同一個 id 更新同一個事件（以 id 為準，不會重複建立）"
    title, desc, day = RC._compose(RC.DUE, "MQ-1", "甲公司", "專案", ev[0][3])
    assert "頭期款" in title and "款項：頭期款" in desc, "新名稱用在事件標題"
    OL._STAGE_CACHE.clear()
    monkeypatch.setattr(OL, "enabled", lambda conn=None: False)
    assert "訂金款" in RC._compose(RC.DUE, "MQ-1", "甲公司", "專案", _cal_items()[0])[0], "旗標關 ⇒ 原字串"
    OL._STAGE_CACHE.clear()


# ── 靜態：消費者都走同一個函式；已入帳的說明維持原字串 ───────────────────────────
def test_consumers_use_the_shared_display_function_and_posted_text_keeps_the_stored_value():
    b = ROOT / "backend"
    rep = (b / "modules" / "analytics" / "api" / "reports.py").read_text(encoding="utf-8")
    assert rep.count("_stage_name(pi, idx)") == 4 and 'pi.get("type", f"第{idx+1}期")' not in rep
    cash = (b / "modules" / "arap" / "api" / "cashier.py").read_text(encoding="utf-8")
    assert cash.count("_stage_name(pi, idx)") == 1
    assert '_stage_display(p.get("type", ""), p)' in (b / "modules" / "analytics" / "api" / "dashboard.py").read_text(encoding="utf-8")
    rec = (b / "modules" / "arap" / "receivables.py").read_text(encoding="utf-8")
    assert "_stage_name(pi, idx)" in rec
    assert 'pi.get("type") or ("第%d期"' in rec, "收款手續費傳票說明用原字串（已入帳的不能被改名牽動）"
    pr = (b / "modules" / "arap" / "api" / "payment_requests.py").read_text(encoding="utf-8")
    assert "_request_stage_label(" in pr and "PAYMENT_STAGES" in pr, "代碼驗證仍用固定字典"
    pdf = (b / "pdf_gen.py").read_text(encoding="utf-8")
    assert "_rsl(v.get('stage') or ''" in pdf


def test_pages_declare_the_lists_and_never_load_the_editor_directly():
    for page, ids in (("case-management", "payment_stage"), ("payment-request-form", "payment_request_stage")):
        src = page_file(page + ".html").read_text(encoding="utf-8")
        assert '<script src="../static/option-lists.js"></script>' in src and '<meta name="motrix-option-lists" content="%s">' % ids in src, page
        assert "option-list-editor.js" not in src
    assert "motrix-options" in (ROOT / "frontend" / "js" / "case-management-core.js").read_text(encoding="utf-8")
