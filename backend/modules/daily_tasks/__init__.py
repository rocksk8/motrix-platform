# -*- coding: utf-8 -*-
"""M12 每日任務（工作事項）。只 import core／helpers／db（L1），不 import 其他 L2 模組。"""
from core.registry import ModuleSpec

from modules.daily_tasks import api

MODULE = ModuleSpec(
    key="daily_tasks",
    routers=[api.router],
    providers={
        # IP-5：別組（M01 案件執行進度）經此建立／同步每日任務
        ("daily_task.external", "daily_tasks"): api._ExternalTasks,
        # IP-11：逾期與區間到期檢查登記給 L1 每日執行器（helpers/daily_checks.py）
        ("daily.check", "daily_tasks"): api.run_daily_checks,
    },
)
