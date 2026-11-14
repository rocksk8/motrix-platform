# -*- coding: utf-8 -*-
"""M08 營運分析。只 import core／helpers／db（L1）；對 M01 的 3 條 import 為既有基線（ROADMAP：M01 搬遷時改 provider）。"""
import importlib

from core.registry import ModuleSpec

from modules.analytics import recycle_adapter
from modules.analytics.api import custom_reports, dashboard, ledger_diff, report_templates, reports

_m0001 = importlib.import_module("modules.analytics.migrations.0001_custom_reports")

MODULE = ModuleSpec(
    key="analytics",
    routers=[dashboard.router, reports.router, ledger_diff.router, report_templates.router, custom_reports.router],
    migrations=[(1, _m0001.up)],
    # IP-RB1（T87 B2 D5）：自訂報表進刪除暫存區（只有設定 custom_reports.recycle_deleted 開啟時才會用到）
    providers={("recyclebin.adapter", "custom_report"): lambda: recycle_adapter.CustomReportBinAdapter()},
    # 走模組屬性、晚綁定：直接放函式物件會凍結成副本，測試 patch 不到（同 tender_radar）
    schedulers=[lambda: reports.schedule_monthly_report()],
)
