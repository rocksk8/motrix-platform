# -*- coding: utf-8 -*-
"""M02 業務開發（crm）。只 import core／helpers／db（L1），不 import 其他 L2 模組。"""
from core.registry import ModuleSpec

from modules.crm import api

MODULE = ModuleSpec(
    key="crm",
    routers=[api.router],
    # 走模組屬性、晚綁定（直接放函式物件會凍結成副本，測試 patch 不到——tender_radar 的註解）
    schedulers=[lambda: api.schedule_dev_case_stale_check()],
    providers={
        # IP-11：M01 刪報價單時，轉建連結指到它的業務開發案件解除連結（同一筆交易）
        ("crm.quote_deleted", "crm"): api.unlink_deleted_quote,
    },
)
