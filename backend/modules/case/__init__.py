# -*- coding: utf-8 -*-
"""M01 案件（case）：報價單、案件管理（階段、執行、動態、額外支出、叫料、完工單）、簽核佇列與簽核歷史、業務訂單。
只 import core／helpers／db（L1），其他模組的資料一律經串接點（INTEGRATION-POINTS）。"""
from core.registry import ModuleSpec

from modules.case import case_deadlines, quotations  # noqa: F401  import 時登記的提供者（③ 改成下方宣告）
# ⚠️ router 一律用別名：`from modules.case.api import quotations` 會把套件屬性 `modules.case.quotations`
#    （報價單 helper）蓋成 api 那一支，`from modules.case import quotations` 就拿錯檔
from modules.case.api import (case_action_items as _api_action_items, case_extra_expenses as _api_extra_expenses,
                              completion_notes as _api_completion_notes, material_orders as _api_material_orders,
                              quotations as _api_quotations)

MODULE = ModuleSpec(
    key="case",
    # 與搬遷前 main.py 的掛載順序相同（路由比對順序不變）
    routers=[_api_quotations.router, _api_material_orders.router, _api_extra_expenses.router,
             _api_completion_notes.router, _api_action_items.router],
)
