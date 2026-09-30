# -*- coding: utf-8 -*-
"""N1（2026-09-30）：承攬商報價單附件刪除申請（type `dispatch_file_delete`）進簽核佇列——附屬類型的覆蓋守門。

它不是 `APPROVAL_DOC_TYPES`（沒有 submit 端點），所以原本的 doc_type 覆蓋檢查掃不到；
`tools/check_approval_queue_coverage.EXTRA_QUEUE_TYPES` 補這個洞：擁有模組在 ⇒ 必須有 `approval.queue_items` 提供者列出它、
且 count 端點彙整提供者。正對照＝真源碼要乾淨；反向控制＝沒有提供者、假類型、count 端點不彙整提供者，各一次必須被抓到；
擁有模組不在 ⇒ 不適用（不算漏）。
"""
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BACKEND, "tools"))

import check_approval_queue_coverage as cov  # noqa: E402

COUNT_OK = "def get_approval_queue_count():\n    items = _queue_provider_items(conn)\n"


def _run(**kw):
    kw.setdefault("doc_types", [])
    kw.setdefault("queue_source", "")
    kw.setdefault("count_source", COUNT_OK)
    kw.setdefault("installed", lambda _k: True)
    kw.setdefault("extra_types", cov.EXTRA_QUEUE_TYPES)
    return cov.check_approval_queue_coverage(**kw)


def test_real_tree_is_clean_and_lists_the_extra_type():
    r = cov.check_approval_queue_coverage(installed=lambda _k: True)
    assert r["missing_extra"] == [] and cov.is_clean(r), r
    assert "dispatch_file_delete" in cov.EXTRA_QUEUE_TYPES          # 量尺：真的有登記這個類型


def test_missing_provider_is_caught():
    r = _run(provider_sources=[("x.py", "def f():\n    return []\n")])
    assert r["missing_extra"] == ["dispatch_file_delete"] and not cov.is_clean(r)


def test_fake_extra_type_is_caught():
    r = _run(provider_sources=[("x.py", 'type_ = "dispatch_file_delete"')], extra_types={"__fake__": "subcontract"})
    assert r["missing_extra"] == ["__fake__"]


def test_count_endpoint_not_aggregating_providers_is_caught():
    r = _run(provider_sources=[("x.py", 'type_ = "dispatch_file_delete"')], count_source="def g():\n    pass\n")
    assert r["missing_extra"] == ["dispatch_file_delete"]


def test_owner_module_absent_is_not_applicable_not_missing():
    r = _run(provider_sources=[], installed=lambda k: k != "subcontract")
    assert r["missing_extra"] == [] and "dispatch_file_delete" in r["not_applicable"] and cov.is_clean(r)
