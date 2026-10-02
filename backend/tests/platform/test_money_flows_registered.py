# -*- coding: utf-8 -*-
"""金流串接守門（使用者 2026-09-30：「只要有收入、支出項，都需要跟營運報表或是相關模組數據串接」；docs/platform/MONEY-FLOWS.md）。

- 模組登記的金流提供者（`expense.entries`／`receivables.income_items`，來自各模組 `ModuleSpec.providers`）
  ⇔ `docs/platform/money_flows.json` 的宣告：兩邊逐一對帳。
  · 登記了卻沒宣告 ⇒ 紅（新增金流來源一定要在覆蓋表留名）
  · 宣告了卻沒登記 ⇒ 紅（表上寫有、實際沒接）
- 每一筆宣告的 `doc` 編號要出現在 MONEY-FLOWS.md（表與宣告不分家）。
- 只對「在場的模組」對帳（模組不在包內 ⇒ 該模組的宣告略過；本檔在任何模組不在時也要綠）。
- 正對照／反向控制：`_diff` 純函式用合成資料證明「多登記」「多宣告」都抓得到。
"""
import importlib
import json
from pathlib import Path

from core import source_tree

REPO = Path(__file__).resolve().parents[3]
FLOWS = REPO / "docs" / "platform" / "money_flows.json"
DOC = REPO / "docs" / "platform" / "MONEY-FLOWS.md"


def _declared():
    d = json.loads(FLOWS.read_text(encoding="utf-8"))
    return d, {(f["module"], f["capability"], f["name"]) for f in d["flows"]}


def _registered(caps):
    out = set()
    for d in sorted((REPO / "backend" / "modules").iterdir()):
        if not d.is_dir() or not (d / "module.json").is_file():
            continue
        if not source_tree.module_installed("modules/%s/" % d.name):
            continue
        spec = importlib.import_module("modules.%s" % d.name).MODULE
        for (cap, name) in spec.providers:
            if cap in caps:
                out.add((d.name, cap, name))
    return out


def _diff(declared, registered, installed):
    """⇒ (登記了卻沒宣告, 宣告了卻沒登記)；只看在場的模組。"""
    dec = {t for t in declared if t[0] in installed}
    reg = {t for t in registered if t[0] in installed}
    return sorted(reg - dec), sorted(dec - reg)


def _installed():
    return {d.name for d in (REPO / "backend" / "modules").iterdir()
            if d.is_dir() and source_tree.module_installed("modules/%s/" % d.name)}


def test_declared_flows_match_registered_providers():
    data, declared = _declared()
    caps = set(data["capabilities"])
    undeclared, unregistered = _diff(declared, _registered(caps), _installed())
    assert not undeclared, ("模組登記了金流提供者，但 docs/platform/money_flows.json 沒有宣告（同一個 commit 補宣告＋MONEY-FLOWS.md）：%s" % undeclared)
    assert not unregistered, ("money_flows.json 宣告了，但模組沒有登記對應的提供者：%s" % unregistered)


def test_every_declared_flow_is_in_the_coverage_table():
    data, _ = _declared()
    doc = DOC.read_text(encoding="utf-8")
    missing = [f for f in data["flows"] if "| %s |" % f["doc"] not in doc]
    assert not missing, "MONEY-FLOWS.md 的覆蓋表裡找不到這些編號（表與宣告要一起更新）：%s" % [f["doc"] for f in missing]


def test_diff_catches_both_directions_positive_control():
    installed = {"arap", "case"}
    declared = {("arap", "expense.entries", "receipt_fee")}
    registered = {("arap", "expense.entries", "receipt_fee"), ("case", "expense.entries", "new_thing")}
    assert _diff(declared, registered, installed) == ([("case", "expense.entries", "new_thing")], [])
    assert _diff(declared | {("case", "expense.entries", "ghost")}, registered, installed) == \
        ([("case", "expense.entries", "new_thing")], [("case", "expense.entries", "ghost")])
    assert _diff(declared, registered, {"arap"}) == ([], [])      # 模組不在 ⇒ 不對帳
    assert _diff(declared, declared, installed) == ([], [])       # 一致 ⇒ 空


def test_the_known_flows_are_all_present():
    """已知的六個來源不可被靜默刪掉（表面一致但少了一個＝守門形同虛設）。"""
    _, declared = _declared()
    assert {("arap", "receivables.income_items", "arap"), ("arap", "expense.entries", "receipt_fee"),
            ("subcontract", "expense.entries", "remit_fee_contractor"), ("case", "expense.entries", "remit_fee_case"),
            ("payroll", "expense.entries", "payslip"), ("payroll", "expense.entries", "bonus")} <= declared
