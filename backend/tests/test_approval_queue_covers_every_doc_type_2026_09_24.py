# -*- coding: utf-8 -*-
"""每一種送審單據都必須出現在兩支簽核佇列端點裡（`GET /api/approval-queue`、`/count`）。

使用者裁示（2026-09-24 午，N8②）：`tools/check_approval_queue_coverage.py` 寫好之後
**沒有任何測試或建包腳本呼叫它** ⇒ 它守的那件事（`AS3`：送審端點對、簽核端點對，
而佇列裡沒有那一種單 ⇒ 沒有人知道有單在等）只在有人記得手動跑的時候才被守。
這裡把它接進測試：全量回歸就是建包的關卡。

判斷邏輯仍在工具裡（單一來源），這支只負責「每次都跑」與正對照。
"""
import os
import sys

import pytest

BE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BE, "tools"))
from check_approval_queue_coverage import check_approval_queue_coverage, is_clean  # noqa: E402


def test_every_approval_doc_type_is_in_both_queue_endpoints():
    r = check_approval_queue_coverage()
    assert is_clean(r), (
        "新增的送審單據類型沒有接進簽核佇列：\n"
        "  沒登記對照（tools/check_approval_queue_coverage.py _QUEUE_TYPE_FOR_DOC_TYPE）：%s\n"
        "  佇列 get_approval_queue() 找不到：%s\n"
        "  數量 get_approval_queue_count() 找不到：%s"
        % (r["missing_from_map"], r["missing_from_queue"], r["missing_from_count"]))


def test_the_check_reads_the_real_doc_type_list():
    """量尺：預設讀的是真正的 `APPROVAL_DOC_TYPES`，不是空清單（空清單永遠綠）。"""
    from helpers.tiered_approval import APPROVAL_DOC_TYPES
    assert len(APPROVAL_DOC_TYPES) >= 9
    assert "quotation" in APPROVAL_DOC_TYPES


def test_an_unmapped_doc_type_is_reported():
    r = check_approval_queue_coverage(doc_types=["quotation", "__fake_type__"])
    assert r["missing_from_map"] == ["__fake_type__"]


def test_a_mapped_type_missing_from_both_endpoints_is_reported():
    r = check_approval_queue_coverage(doc_types=["voucher"],
                                      queue_source="def f():\n    pass\n",
                                      count_source="def g():\n    pass\n", provider_sources=[])
    assert r["missing_from_queue"] == ["voucher"] and r["missing_from_count"] == ["voucher"]


def test_a_provider_type_counts_only_when_the_count_endpoint_aggregates_providers():
    """M01-PLAN §3-7：型別由 `approval.queue_items` 提供者列出 ⇒ 佇列算涵蓋；count 端點沒呼叫 `_queue_provider_items(`
    ⇒ count 仍算漏掉（提供者的項目只有經彙整才進角標）。"""
    prov = [("modules/x/api.py", 'def queue_items(conn):\n    conn.execute("SELECT 1 FROM vouchers_all")\n'
                                 '    return [{"type": "voucher"}]\n')]
    ok = check_approval_queue_coverage(doc_types=["voucher"], queue_source="", provider_sources=prov,
                                       count_source="items += _queue_provider_items(conn)")
    assert is_clean(ok)
    no_agg = check_approval_queue_coverage(doc_types=["voucher"], queue_source="", provider_sources=prov,
                                           count_source="def g():\n    pass\n")
    assert no_agg["missing_from_queue"] == [] and no_agg["missing_from_count"] == ["voucher"]


def test_the_real_provider_scan_finds_the_owner_modules():
    """量尺：真的登記處掃得到各單據模組的提供者（掃不到 ⇒ 每一種都判成漏掉，或只靠 M01 源碼殘留才綠）。"""
    from check_approval_queue_coverage import _provider_sources
    labels = {lbl.replace("\\", "/") for lbl, src in _provider_sources() if src}
    for f in ("routers/vouchers.py", "helpers/custom_modules.py"):
        assert f in labels, (f, sorted(labels))


def test_a_covered_type_is_not_reported():
    r = check_approval_queue_coverage(doc_types=["quotation"],
                                      queue_source='items.append({"type": "quotation"})',
                                      count_source="SELECT 1 FROM quotations")
    assert is_clean(r)


@pytest.mark.parametrize("doc_type", ["quotation", "voucher", "bonus"])
def test_known_types_are_found_in_the_real_source(doc_type):
    """對真原始碼：掃描機制讀得到兩支函式（不是回空字串 ⇒ 每一種都判成漏掉）。"""
    assert is_clean(check_approval_queue_coverage(doc_types=[doc_type]))
