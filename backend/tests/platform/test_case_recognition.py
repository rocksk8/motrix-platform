"""`case.recognition`（M01 提供；M01-PLAN §3-6）與 L1 `helpers/recognition_basis.py` 的契約。

① 提供者：六個方法轉呼叫 `helpers.recognition` 的同名函式，參數原樣傳（簽章是契約）
② M08 不再直接 import `helpers.recognition`（只經提供者；口徑標籤走 L1 recognition_basis）
③ L1 recognition_basis：不讀表、不 import M01；`helpers.recognition` 的同名名稱是同一物件
④ M01 不在（拿掉提供者）：營運報表 200——權責口徑收入空且 `incomeNotice` 明說；支出的 `unavailable` 列出案件類；
   待補登為空。正對照：提供者在時 `incomeNotice` 空、`unavailable` 不含案件類
"""
import ast
from pathlib import Path

import pytest

from core import registry, source_tree
from tests.platform.test_tax_calc_contract import m01_imports, table_access

BACKEND = Path(__file__).resolve().parents[2]
METHODS = {
    "accrual_income_items": ("conn", "2026-01-01", "2026-01-31", 7),
    "dispatch_entries": ("conn", "cash"),
    "material_entries": ("conn", "accrual", 7),
    "extra_entries": ("conn", "cash"),
    "recognition_flags": ("conn", 2026, 7, False),
    "dispatch_unavailable": ("cash",),
}


@pytest.mark.parametrize("name", sorted(METHODS))
def test_provider_forwards_to_the_m01_function_with_the_same_arguments(name, monkeypatch):
    from helpers import recognition as r
    seen = {}

    def fake(*a):
        seen["args"] = a
        return ("sentinel", name)
    monkeypatch.setattr(r, name, fake)
    rec = registry.single_provider("case.recognition")
    assert rec is not None
    assert getattr(rec, name)(*METHODS[name]) == ("sentinel", name)
    assert seen["args"] == METHODS[name]


def test_m08_does_not_import_the_m01_recognition_module():
    src = (BACKEND / "modules" / "analytics" / "api" / "reports.py")
    if not src.is_file():
        pytest.skip("M08 不在這個安裝包")
    tree = ast.parse(src.read_text(encoding="utf-8"))
    bad = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "helpers.recognition"]
    bad += [n.lineno for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "helpers"
            and any(a.name == "recognition" for a in n.names)]
    assert not bad, "M08 仍直接 import helpers.recognition（行 %s）⇒ 改經 case.recognition" % bad


def test_recognition_basis_is_pure_l1_and_aliased():
    src = (BACKEND / "helpers" / "recognition_basis.py").read_text(encoding="utf-8")
    assert m01_imports(src) == [] and table_access(src) == []
    from helpers import recognition, recognition_basis
    for n in ("BASES", "BASIS_NOTES", "normalize_basis"):
        assert getattr(recognition, n) is getattr(recognition_basis, n), n


def _sa(client, make_user):
    u, p = make_user("rec_abs_sa", "Conn-Pass-123", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _report(client, h, basis):
    r = client.get("/api/reports/expenses-monthly?year=2026&month=2026-09&basis=" + basis, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_reports_without_m01_say_why(client, make_user, monkeypatch):
    if not source_tree.module_installed("modules/analytics/"):
        pytest.skip("M08 不在這個安裝包 ⇒ 報表端點本來就不在（PLAYBOOK §B-11）")
    from modules.analytics.api import reports as rp
    h = _sa(client, make_user)
    ok = _report(client, h, "accrual")                                    # 正對照：提供者在
    assert ok["incomeNotice"] == "" and not [u for u in ok["unavailable"] if u["category"] == "case"]
    orig = registry.single_provider
    monkeypatch.setattr(registry, "single_provider", lambda cap: None if cap == "case.recognition" else orig(cap))
    acc = _report(client, h, "accrual")
    assert acc["incomeNotice"] == rp.CASE_RECOGNITION_MISSING and acc["monthIncomeItems"] == []
    assert rp.CASE_EXPENSES_UNAVAILABLE in acc["unavailable"]
    assert acc["recognitionFlags"] == {}
    cash = _report(client, h, "cash")
    assert rp.CASE_EXPENSES_UNAVAILABLE in cash["unavailable"]              # 叫料／額外支出在現金口徑也來自 M01
