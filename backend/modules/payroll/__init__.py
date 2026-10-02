# -*- coding: utf-8 -*-
"""M07 薪資獎金（payroll）：勞務報酬單、獎金分潤（項目、分組、案件獎金、簽核、發放、扣繳與補充保費）。
只 import core／helpers／db（L1），不 import 其他 L2 模組。"""
from core.registry import ModuleSpec

import importlib

from modules.payroll import bank_account, bonus, bonus_correction, bonus_payouts, bonus_queue, gl_events, payslip_payouts, remit_link
from modules.payroll.api import bank_account as bank_account_api, bonus as bonus_api, bonus_correction as bonus_correction_api, payslips as payslips_api
from modules.payroll import attachments   # 要在 api 之後：提供者用 payslips 的 _signed_path／_archive_dir

_m0001 = importlib.import_module("modules.payroll.migrations.0001_payslip_void_signed_paid")
_m0002 = importlib.import_module("modules.payroll.migrations.0002_bonus_corrections")
_m0003 = importlib.import_module("modules.payroll.migrations.0003_user_bank_accounts")

MODULE = ModuleSpec(
    key="payroll",
    routers=[payslips_api.router, bonus_correction_api.router, bonus_api.router, bank_account_api.router],
    migrations=[(1, _m0001.up), (2, _m0002.up), (3, _m0003.up)],
    providers={
        # IP-8：出納頁的獎金待發放與發放紀錄（M05）
        ("bonus.payouts", "payroll"): bonus_payouts._Payouts,
        # IP-105：附件目錄（attachments.catalog，2026-09-30 P2）
        ("attachments.catalog", "payroll"): attachments._PayrollCatalog,
        # IP-BK1（A2 收款人）：員工收款帳號（依檢視者回完整／遮蔽；完整必帶稽核 token）
        ("payee.bank_profile", "payroll"): bank_account.payee_bank_profile,
        # IP-9：已發放的獎金列入營運報表與月支出（M08）
        ("expense.entries", "bonus"): bonus_payouts._expense_entries,
        # IP-9：獎金更正單的補發（補發日）與追回（核准日）列入營運報表與月支出（M08，名稱 bonus_correction）
        ("expense.entries", "bonus_correction"): bonus_correction.expense_entries,
        # IP-103：出納頁的勞報單待付款（M05）；IP-9：已付款勞報單列入營運報表與月支出（M08，名稱 payslip）
        ("payslip.payables", "payroll"): payslip_payouts._Payables,
        ("expense.entries", "payslip"): payslip_payouts._expense_entries,
        # IP-105（R12）：承攬商匯款單關聯勞報單、匯款時一併記為已付款
        ("payslip.remit", "payroll"): remit_link._Remit,
        # IP-16：L1 /api/system/bonus-module-status
        ("bonus.module_status", "payroll"): bonus.bonus_module_on,
        # IP-GL1（W4 總帳 C3）：勞報單應付（E06）與付款（E06b）事件；唯讀
        ("gl.events", "payroll"): gl_events.gl_events,
        # IP-10（M01-PLAN §3-7）：M01「待我簽核」佇列的獎金分潤單與案件獎金分潤
        ("approval.queue_items", "payroll"): bonus_queue.queue_items,
    },
)
