"""自 `tests/test_xlsx_out_l1_2026_09_25.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import ast
import io
from pathlib import Path
import openpyxl
import pytest
from fastapi import HTTPException
from helpers import xlsx_out
from tests.test_xlsx_out_l1_2026_09_25 import (  # noqa: E402,F401  含 fixture
    BACKEND,
)


def test_no_hardcoded_company_name_left():
    for rel in ("modules/analytics/api/reports.py",):   # 其餘兩處：tests/test_xlsx_out_l1_2026_09_25.py
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        names = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                 for t in n.targets if isinstance(t, ast.Name)}
        assert "_COMPANY" not in names, rel
