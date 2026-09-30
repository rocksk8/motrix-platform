# -*- coding: utf-8 -*-
"""M07 薪資獎金（payroll）：勞務報酬單、獎金分潤（項目、分組、案件獎金、簽核、發放、扣繳與補充保費）。
只 import core／helpers／db（L1），不 import 其他 L2 模組。"""
from core.registry import ModuleSpec

import importlib

from modules.payroll import bonus, bonus_payouts, bonus_queue, gl_events, payslip_payouts, remit_link
from modules.payroll.api import bonus as bonus_api, payslips as payslips_api

_m0001 = importlib.import_module("modules.payroll.migrations.0001_payslip_void_signed_paid")

MODULE = ModuleSpec(
    key="payroll",
    routers=[payslips_api.router, bonus_api.router],
    migrations=[(1, _m0001.up)],
    providers={
        # IP-8：出納頁的獎金待發放與發放紀錄（M05）
        ("bonus.payouts", "payroll"): bonus_payouts._Payouts,
        # IP-9：已發放的獎金列入營運報表與月支出（M08）
        ("expense.entries", "bonus"): bonus_payouts._expense_entries,
        # IP-103：出納頁的勞報單待付款（M05）；IP-9：已付款勞報單列入營運報表與月支出（M08，名稱 payslip）
        ("payslip.payables", "payroll"): payslip_payouts._Payables,
        ("expense.entries", "payslip"): payslip_payouts._expense_entries,
        # IP-104（R12）：承攬商匯款單關聯勞報單、匯款時一併記為已付款
        ("payslip.remit", "payroll"): remit_link._Remit,
        # IP-16：L1 /api/system/bonus-module-status
        ("bonus.module_status", "payroll"): bonus.bonus_module_on,
        # IP-GL1（W4 總帳 C3）：勞報單應付（E06）與付款（E06b）事件；唯讀
        ("gl.events", "payroll"): gl_events.gl_events,
        # IP-10（M01-PLAN §3-7）：M01「待我簽核」佇列的獎金分潤單與案件獎金分潤
        ("approval.queue_items", "payroll"): bonus_queue.queue_items,
    },
)
