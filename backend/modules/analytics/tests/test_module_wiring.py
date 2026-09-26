"""營運分析模組的 ModuleSpec 接線（稽核 ⑰ S-5：月報排程在 main.py 拿掉後改由 ModuleSpec.schedulers 啟動，原本沒有題驗這條接線）。"""


def test_monthly_report_scheduler_is_wired_through_the_module_spec(monkeypatch):
    """逐一呼叫 MODULE.schedulers ⇒ reports.schedule_monthly_report 被呼叫恰好一次。
    晚綁定（lambda 內取模組屬性）才讓 patch 看得到——改成直接放函式物件，這一題就紅（突變驗過）。"""
    import modules.analytics as A
    from modules.analytics.api import reports
    calls = []
    monkeypatch.setattr(reports, "schedule_monthly_report", lambda: calls.append("monthly"))
    for start in A.MODULE.schedulers:
        start()
    assert calls == ["monthly"]


def test_module_spec_declares_both_routers():
    import modules.analytics as A
    from modules.analytics.api import dashboard, reports
    assert A.MODULE.key == "analytics"
    assert dashboard.router in A.MODULE.routers and reports.router in A.MODULE.routers
