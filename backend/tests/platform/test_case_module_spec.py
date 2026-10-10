"""CA-O3（M01-PLAN §3-8 ③）：M01 的提供者一律由 `modules/case` 的 ModuleSpec.providers 宣告，不在 import 時登記。

為什麼：import 時登記的提供者，在模組停用、未授權或載入失敗時照樣留在登記表（只要有人 import 過那支檔）——
`case.access` 是「M01 在不在」的唯一訊號（helpers.case_access.CASE_PRESENT），殘留就會讓 L1 以為 M01 在。

① `modules/case/` 底下沒有任何 `registry.provide(...)`（掃描器＋反向控制）
② ModuleSpec 宣告的就是這 13 個（能力, 名稱）
③ 執行期：這 13 個都不在 import 時登記表（`_LEGACY_PROVIDERS`）裡；模組在時由載入器提供
"""
import ast
from pathlib import Path

import pytest

from core import registry, source_tree

BACKEND = Path(__file__).resolve().parents[2]
EXPECTED = {
    ("recyclebin.adapter", "quotation"), ("recyclebin.adapter", "extra_expense"),     # 第 53 班 P1（IP-RB1）：刪除暫存區的單據轉接
    ("recyclebin.adapter", "completion_note"), ("recyclebin.adapter", "material_order"),
    ("gl.events", "case"),                                   # W4 總帳 C4b：額外支出／叫料事件提供者（唯讀）
    ("case.shipped_summary", "case"),                        # 第 43 班（IP-SH5）：整案訂購／已出貨數量小計（營運報表匯出用；只有數量）
    ("material.shippable", "case"),                          # 34-S1：出貨單連動——已核准且已到貨確認的材料申請（唯讀；supply 經 registry 取用）
    ("case.access", "case"), ("case.summary", "case"), ("case.locations", "case"), ("case.recognition", "case"),
    ("case.default_terms", "case"), ("case.doc_version", "case"), ("daily.check", "case_deadlines"),
    ("approval.reassign", "quotation"), ("approval.reassign", "completion_note"),
    # c-approval-l1（2026-09-27）：佇列在 L1，M01 是 queue_items／detail 的提供者
    ("approval.queue_items", "case"), ("approval.detail", "quotation"), ("approval.detail", "completion_note"),
    ("approval.detail", "extra_expense"), ("approval.detail", "case_change"),
    ("calendar.writeback", "quotation"), ("calendar.writeback", "case_stage"),
    ("quotation.append_items", "quotations"), ("attachments.for_document", "case"),
    ("payables.pending", "case"),          # IP-100 請款待付款（2026-09-27）
    ("remit.reviews", "case"),             # IP-102 匯款差額審核（W1，2026-09-30）
    ("expense.entries", "remit_fee_case"),  # IP-9 額外支出匯款手續費（W1）
    ("uploads.path_access", "case"),        # IP-104 上傳檔讀取權限（sec-p0，2026-09-30）
    ("attachments.catalog", "case"),        # IP-105 附件目錄（P2，2026-09-30）
    # 31-C 叫料審核與匯款申請（2026-10-02）：佇列／詳情；出納待付（IP-100）與差額審核（IP-102）沿用既有名稱空間；手續費列報表支出（IP-9）
    ("approval.queue_items", "case_material"), ("approval.detail", "material_order"),
    ("approval.queue_items", "case_material_payment"), ("approval.detail", "material_payment"),
    ("approval.queue_items", "case_material_change"), ("approval.detail", "material_change"),       # 33-M2b 材料申請變更
    ("payables.pending", "case_material"), ("remit.reviews", "case_material"), ("expense.entries", "remit_fee_case_material"),
}


def import_time_provides(files_src):
    """{相對路徑: 原始碼} ⇒ [(路徑, 行, 能力)]：`X.provide("能力", "名稱", …)` 形式的 import 時登記。"""
    out = []
    for rel, src in files_src.items():
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "provide" \
               and len(n.args) >= 3 and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                out.append((rel, n.lineno, n.args[0].value))
    return out


def _case_sources():
    root = BACKEND / "modules" / "case"
    return {str(p.relative_to(BACKEND)).replace("\\", "/"): p.read_text(encoding="utf-8")
            for p in root.rglob("*.py") if "tests" not in p.parts and "__pycache__" not in p.parts}


@pytest.fixture
def case_installed():
    if not source_tree.module_installed("modules/case/"):
        pytest.skip("M01 不在這個安裝包（PLAYBOOK §B-11）")


def test_no_import_time_registration_in_m01(case_installed):
    srcs = _case_sources()
    assert len(srcs) >= 10                                   # 量尺：掃得到 M01 的檔
    bad = import_time_provides(srcs)
    assert not bad, "M01 仍在 import 時登記提供者（改成 modules/case/__init__.py 的 ModuleSpec.providers）：%s" % bad


def test_rc_scanner_catches_a_provide_call():
    srcs = {"modules/case/zz.py": "from core import registry as _r\n_r.provide('case.x', 'case', object)\n",
            "modules/case/ok.py": "from core import registry\nx = registry.providers('case.x')\n"}
    assert import_time_provides(srcs) == [("modules/case/zz.py", 2, "case.x")]


def test_module_spec_declares_every_m01_provider(case_installed):
    from modules.case import MODULE
    assert set(MODULE.providers) == EXPECTED, sorted(set(MODULE.providers) ^ EXPECTED)


def test_none_of_them_is_in_the_import_time_table(client, case_installed):
    """client 夾具＝載入器已掛好 M01：能力在（由 ModuleSpec 提供），但不在 import 時登記表。"""
    legacy = set(registry._LEGACY_PROVIDERS)
    assert not (EXPECTED & legacy), sorted(EXPECTED & legacy)
    for cap, name in EXPECTED:
        assert name in registry.providers(cap), (cap, name)
