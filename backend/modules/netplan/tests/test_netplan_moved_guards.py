"""M10 的端點與頁面在 L1 共用守門裡的那幾項（2026-09-26 自 tests/ 移入，PLAYBOOK §B-11）。

拿掉 M10 時這些項目跟著消失；檢查本身仍是 L1 那幾支（以別名匯入，不重複收集）。
"""
import pytest

from tests.test_module_no_admin_bypass_2026_09_14 import (
    _login as _nab_login,
    test_admin_with_module_passes as _admin_with_module_passes,
    test_admin_without_module_is_blocked as _admin_without_module_is_blocked,
    test_superadmin_always_passes as _superadmin_always_passes,
)
from tests.test_module_permission_fixes_2026_09_13 import _auth, _make_case, _outsider

_PROBE = ("/api/network-plans", "netplan", "網路架構規劃書")


def test_admin_without_netplan_is_blocked(client, make_user):
    _admin_without_module_is_blocked(client, make_user, *_PROBE)


def test_admin_with_netplan_passes(client, make_user):
    _admin_with_module_passes(client, make_user, *_PROBE)


def test_superadmin_passes_netplan(client, make_user):
    _superadmin_always_passes(client, make_user, *_PROBE)


def test_network_plan_read_accepts_case_manage_consumer(client, make_user):
    """`js/case-management.js` 也會打 /api/network-plans。只認 netplan 會把
    案件管理那條路徑打死——MODULE-AUDIT §5 說的「擋錯人」失敗模式。"""
    u, p = make_user(username="cm_only", role="sales", modules=["case_manage"])
    r = client.get("/api/network-plans", headers=_nab_login(client, u, p))
    assert r.status_code == 200, \
        f"案件管理模組打不開規劃書 API（{r.status_code}）——會讓案件頁一片 403"


def test_case_network_plan_lookup_is_guarded(client, make_user):
    _make_case("MQ-SWEEP-005", sales_person="sw_owner")
    tok = _outsider(client, make_user, "sw_v5")
    assert client.get("/api/quotations/MQ-SWEEP-005/network-plan",
                      headers=_auth(tok)).status_code == 404   # M01-O1：看不到＝不存在（同一個 404）


def test_netplan_export_uses_the_shared_edge_runner():
    """全站共用一份 Edge 並發額度（原 test_pdf_concurrency／test_edge_profile 的網路規劃那一處）。"""
    import pdf_gen
    import modules.netplan.export as network_plan_export
    assert network_plan_export.run_edge_pdf is pdf_gen.run_edge_pdf


@pytest.mark.e2e
@pytest.mark.parametrize("page_name,spec", [
    ("network-plans", (["caseSearch"], "createForm.siteName")),
    ("network-plan-form?id={pid}", (["stockSearch"], "plan.siteName")),
])
def test_netplan_filter_fields_do_not_mark_the_page_dirty(live_server, make_user, monkeypatch, e2e_browser, page_name, spec):
    pytest.importorskip("playwright.sync_api")
    import tests.test_e2e_filter_fields_no_leave_warning_2026_09_25 as w8
    monkeypatch.setitem(w8.PAGES, page_name, spec)
    w8.test_filter_fields_do_not_mark_the_page_dirty(live_server, make_user, monkeypatch, page_name, e2e_browser)
