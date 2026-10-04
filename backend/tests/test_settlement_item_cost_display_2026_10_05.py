"""案件頁（案件→精算摘要）與報表（結案精算明細）的「成本品項」顯示——遵守第 39 班的存檔契約：
settlement.schemaVersion >= 2 ⇒ actualTotalCost 是數字（含 0）＝有填；null／空＝未填。舊存檔（沒有標記）0＝未填，顯示不變。
node 載入分檔直接呼叫方法（與 test_money_round_half_up 同一套沙盒）。"""
import json
import re

import pytest

from tests.test_money_round_half_up_2026_09_26 import FRONTEND, _cm, _js, needs_node


def _cm_cost(settlement, item):
    return _cm("o.selected = { data: { settlement: %s } }; const it = %s; return { filled: o.caseSettleItemFilled(it), text: o.caseSettleItemCost(it) }"
               % (json.dumps(settlement), json.dumps(item)))


def _rp_cost(settlement, item):
    return _js("js", str(FRONTEND / "js" / "reports.js"), "reportsApp",
               "o.settlement = { settlement: %s }; const it = %s; return { filled: o.stlItemFilled(it), text: o.stlItemCost(it) }"
               % (json.dumps(settlement), json.dumps(item)))


@needs_node
def test_case_page_shows_a_real_zero_for_the_new_save_format():
    st = {"schemaVersion": 2, "status": "finalized"}
    assert _cm_cost(st, {"actualTotalCost": 0}) == {"filled": True, "text": "NT$ 0"}
    assert _cm_cost(st, {"actualTotalCost": 1234}) == {"filled": True, "text": "NT$ 1,234"}
    assert _cm_cost(st, {"actualTotalCost": None}) == {"filled": False, "text": "未填寫"}
    assert _cm_cost(st, {}) == {"filled": False, "text": "未填寫"}
    assert _cm_cost(st, {"actualTotalCost": ""}) == {"filled": False, "text": "未填寫"}


@needs_node
def test_case_page_legacy_save_keeps_zero_as_unfilled():
    for st in ({"status": "finalized"}, {"status": "draft", "schemaVersion": 1}, {"schemaVersion": 0}):
        assert _cm_cost(st, {"actualTotalCost": 0}) == {"filled": False, "text": "未填寫"}, st
        assert _cm_cost(st, {"actualTotalCost": None}) == {"filled": False, "text": "未填寫"}
        assert _cm_cost(st, {"actualTotalCost": 500}) == {"filled": True, "text": "NT$ 500"}


@needs_node
def test_report_modal_shows_a_real_zero_for_the_new_save_format():
    st = {"schemaVersion": 2, "status": "finalized"}
    assert _rp_cost(st, {"actualTotalCost": 0}) == {"filled": True, "text": "NT$ 0"}
    assert _rp_cost(st, {"actualTotalCost": 1234}) == {"filled": True, "text": "NT$ 1,234"}
    assert _rp_cost(st, {"actualTotalCost": None}) == {"filled": False, "text": "—"}
    assert _rp_cost(st, {}) == {"filled": False, "text": "—"}


@needs_node
def test_report_modal_legacy_save_keeps_zero_as_unfilled():
    for st in ({"status": "finalized"}, {"schemaVersion": 1}):
        assert _rp_cost(st, {"actualTotalCost": 0}) == {"filled": False, "text": "—"}, st
        assert _rp_cost(st, {"actualTotalCost": 500}) == {"filled": True, "text": "NT$ 500"}


def test_pages_use_the_helpers_and_the_known_readers_do_not_hide_a_zero():
    """兩個頁面都改走輔助函式；案件頁與報表這幾支前端檔不再有 `actualTotalCost||0 > 0` 這種把 0 當未填的判斷
    （只掃明確列出的檔，不掃整棵樹——整棵樹掃描要登記到 bottom_layer.json 的 global_tests）。"""
    from core import source_tree      # 頁面位置一律經 source_tree（PLAYBOOK §G5 #16）
    cm = source_tree.page_file("case-management.html").read_text(encoding="utf-8")
    rp = source_tree.page_file("reports.html").read_text(encoding="utf-8")
    assert "caseSettleItemCost(item)" in cm and "stlItemCost(it)" in rp
    bad = []
    for name, text in (("case-management.html", cm), ("reports.html", rp),
                       ("case-management-fin.js", (FRONTEND / "js" / "case-management-fin.js").read_text(encoding="utf-8")),
                       ("reports.js", (FRONTEND / "js" / "reports.js").read_text(encoding="utf-8"))):
        for n, line in enumerate(text.splitlines(), 1):
            if re.search(r"actualTotalCost\s*\|\|\s*0\s*\)\s*(>|!==?)\s*0|actualTotalCost\s*\|\|\s*0\)>0", line):
                bad.append("%s:%d" % (name, n))
    assert not bad, "仍有把 actualTotalCost 的 0 當未填的讀取端（須依 schemaVersion）：%s" % bad
