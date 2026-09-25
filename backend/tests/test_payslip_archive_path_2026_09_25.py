# -*- coding: utf-8 -*-
"""勞報單存檔目錄納入 L1 路徑規則（DATA-COMPAT §4 A-3）。

V9 只有寫死的 backend/export_archive；現在比照 6 種 PDF：預設值來自 core.paths，
system_settings.payslip_archive_path 可覆寫，demo 帳號一律走隔離目錄。
"""
import os

from core import paths
from helpers.settings import _set_setting


def test_default_is_v9_location(client):
    from modules.payroll.api import payslips
    assert payslips._archive_dir() == paths.PDF_ARCHIVES["payslip"][1]
    assert os.path.basename(payslips._archive_dir()) == "export_archive"


def test_setting_overrides_and_archive_path_uses_it(client, tmp_path):
    from modules.payroll.api import payslips
    _set_setting("payslip_archive_path", str(tmp_path))
    assert payslips._archive_dir() == str(tmp_path)
    p = payslips._archive_path("PS-202609-001", 1)
    assert os.path.dirname(p) == str(tmp_path)
    assert os.path.isdir(str(tmp_path))


def test_blank_setting_falls_back_to_default(client):
    from modules.payroll.api import payslips
    _set_setting("payslip_archive_path", "   ")
    assert payslips._archive_dir() == paths.PDF_ARCHIVES["payslip"][1]


def test_demo_ignores_setting(client, tmp_path, monkeypatch):
    from modules.payroll.api import payslips
    _set_setting("payslip_archive_path", str(tmp_path))
    monkeypatch.setattr(payslips, "is_demo_mode", lambda: True)
    assert payslips._archive_dir() == payslips.DEMO_PAYSLIP_ARCHIVE_DIR
