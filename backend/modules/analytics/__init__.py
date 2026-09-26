# -*- coding: utf-8 -*-
"""M08 營運分析。只 import core／helpers／db（L1）；對 M01 的 3 條 import 為既有基線（ROADMAP：M01 搬遷時改 provider）。"""
from core.registry import ModuleSpec

from modules.analytics.api import dashboard, reports

MODULE = ModuleSpec(
    key="analytics",
    routers=[dashboard.router, reports.router],
    # 走模組屬性、晚綁定：直接放函式物件會凍結成副本，測試 patch 不到（同 tender_radar）
    schedulers=[lambda: reports.schedule_monthly_report()],
)
