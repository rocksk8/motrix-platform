"""業務開發（CRM）事件的 LINE 預設收件人：沒有「業務開發」模組權限的人不發（PM 2026-11-13，T82 小尾巴；比照審查 h8 M1 對「指定的人」的規則，這次套在業務收件人上）。

另含 `license_expiry`（授權即將到期）事件的接線：最高管理者群組、critical。
夾具沿用 `test_line_events_all_2026_11_13`。
"""
import pytest

from tests.test_line_events_all_2026_11_13 import _hdr, _targets, env, login_ready  # noqa: F401  夾具與小工具共用


def _set_modules(username, role, modules):
    import json
    from db import get_db
    c = get_db()
    c.execute("UPDATE users SET role=?, modules=? WHERE username=?", (role, json.dumps(modules), username))
    c.commit()
    c.close()


def test_business_recipients_without_dev_crm_get_no_line_but_those_with_it_do(env):
    from helpers import line_notify as L, line_recipients as LR
    key = "crm_case_status"
    L.set_event(key, True)
    _set_modules("amy", "sales", ["dev_crm"])            # 有業務開發權限
    _set_modules("dan", "engineer", [])                    # 沒有
    assert LR.permitted_users(key, ["amy", "dan"]) == {"amy"}, "前提：amy 有、dan 沒有業務開發權限"
    assert LR.resolve_audience(key, ["amy", "dan"]) == ["amy"]
    L.deliver_event(key, usernames=["amy", "dan"], title="案件階段變更")
    assert _targets(env) == ["amy"]


def test_superadmin_always_passes_and_other_groups_are_unchanged(env):
    from helpers import line_notify as L, line_recipients as LR
    key = "crm_case_created"
    L.set_event(key, True)
    _set_modules("dan", "engineer", [])
    assert LR.resolve_audience(key, ["sa", "dan"]) == ["sa"]
    # 其他分組（會計）的業務收件人維持舊行為：不做模組檢查（這次只動「業務開發」）
    other = "voucher_submitted"
    L.set_event(other, True)
    assert LR.resolve_audience(other, ["dan"]) == ["dan"]


def test_every_crm_and_dev_event_is_in_the_checked_group(env):
    from helpers import line_catalog as cat
    for k in ("crm_case_created", "crm_case_status", "crm_case_progress", "crm_visit_logged", "crm_log_approved",
              "crm_case_converted", "dev_case_unassigned", "dev_case_deadline_changed", "dev_log_directive_reply"):
        assert cat.needs_business_perm(k), k
    assert not cat.needs_business_perm("voucher_submitted") and not cat.needs_business_perm("module_activity")


def test_personal_settings_page_does_not_list_crm_events_for_someone_without_the_permission(env):
    from helpers import line_notify as L, line_recipients as LR
    key = "crm_case_status"
    L.set_event(key, True)
    _set_modules("amy", "sales", ["dev_crm"])
    _set_modules("dan", "engineer", [])
    assert LR.visible_to(key, "amy", "sales") is True
    assert LR.visible_to(key, "dan", "engineer") is False, "收不到的事件不列在個人設定頁，免得誤以為勾了會收到"


def test_designated_people_rule_still_applies_in_business_plus_mode(env):
    from helpers import line_notify as L, line_recipients as LR
    key = "crm_case_status"
    L.set_event(key, True)
    _set_modules("amy", "sales", ["dev_crm"])
    _set_modules("dan", "engineer", [])
    with pytest.raises(ValueError):
        L.set_audience(key, "business_plus", [], ["dan"])              # 指定的人沒權限：設定時擋下（原 M1 規則不變）
    L.set_audience(key, "business_plus", [], ["amy"])
    assert LR.resolve_audience(key, ["amy", "dan"]) == ["amy"]


def test_license_expiry_is_a_critical_system_alert_to_the_superadmin_group(env):
    from helpers import line_catalog as cat, line_notify as L
    spec = L.event_spec("license_expiry")
    assert spec["priority"] == "critical" and spec["digest"] is False
    assert cat.group_of("license_expiry") == "系統告警"
    assert cat.modules_needed("license_expiry") == ("settings",)
