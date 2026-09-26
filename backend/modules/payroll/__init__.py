# -*- coding: utf-8 -*-
"""M07 薪資獎金（payroll）：勞務報酬單、獎金分潤（項目、分組、案件獎金、簽核、發放、扣繳與補充保費）。
只 import core／helpers／db（L1），不 import 其他 L2 模組。"""
from core.registry import ModuleSpec

from modules.payroll import bonus, bonus_payouts, bonus_queue
from modules.payroll.api import bonus as bonus_api, payslips as payslips_api

MODULE = ModuleSpec(
    key="payroll",
    routers=[payslips_api.router, bonus_api.router],
    providers={
        # IP-8：出納頁的獎金待發放與發放紀錄（M05）
        ("bonus.payouts", "payroll"): bonus_payouts._Payouts,
        # IP-9：已發放的獎金列入營運報表與月支出（M08）
        ("expense.entries", "bonus"): bonus_payouts._expense_entries,
        # IP-16：L1 /api/system/bonus-module-status
        ("bonus.module_status", "payroll"): bonus.bonus_module_on,
        # IP-10（M01-PLAN §3-7）：M01「待我簽核」佇列的獎金分潤單與案件獎金分潤
        ("approval.queue_items", "payroll"): bonus_queue.queue_items,
    },
)
