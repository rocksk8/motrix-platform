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
    ("case.access", "case"), ("case.summary", "case"), ("case.locations", "case"), ("case.recognition", "case"),
    ("case.default_terms", "case"), ("case.doc_version", "case"), ("daily.check", "case_deadlines"),
    ("approval.reassign", "quotation"), ("approval.reassign", "completion_note"),
    ("calendar.writeback", "quotation"), ("calendar.writeback", "case_stage"),
    ("quotation.append_items", "quotations"), ("attachments.for_document", "case"),
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
