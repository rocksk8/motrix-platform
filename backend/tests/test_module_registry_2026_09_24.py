# -*- coding: utf-8 -*-
"""權限模組唯一來源 `helpers/module_registry.py`（B7，2026-09-24 使用者裁示「整併成一份」）。

## golden：整併**不改變任何一個值**

下面三份是 2026-09-24 整併前，從 users.html（allModules、ROLE_MODULES）與
helpers/auth.py（_SUPERADMIN_MODULES）逐字抄下來的**凍結副本**。
registry 必須與它們逐項相同 ⇒ 正式機帳號身上的 `modules` JSON 零影響
（沒有 key 改名、沒有 key 消失、新安裝的第一個管理員寫進去的字串與今天相同）。

📌 之後要**新增**模組：把新 key 同時加進 registry 與這裡的副本（兩處都改是刻意的摩擦：
   它逼人想一下「這是新增，不是改名」）。**改名或刪除**要先有 migration 與裁示。
📌 2026-09-24（CU2b，使用者裁示的用詞統一「代辦→待辦」）：兩個模組的**顯示名稱**
   「案件代辦－…」改為「案件待辦－…」。key（project_approve_eng／biz）不動，帳號身上的
   modules JSON 只存 key ⇒ 零影響。這是這份 golden 唯一一次改 label，理由是用詞裁示。
📌 2026-09-24（實走 7-SL，使用者裁示「業務預設開地圖」）：sales 樣板末尾加 `map`。
   只影響之後套用樣板的帳號；既有帳號身上的 modules JSON 不動。
☠️ 產生 registry 時第一版就踩到一次：`("dashboard")` 少一個逗號，viewer 樣板變成
   字串、長度 9 ——這一題會抓到那種錯。
"""
import pytest


GOLDEN_MODULES = [
    ("dashboard", "儀表板", "基本"),
    ("dev_crm", "業務開發 CRM", "業務"),
    ("tender_radar", "標案雷達", "業務"),
    ("map", "地圖", "業務"),
    ("quotation", "報價單／簽核佇列", "業務"),
    ("case_manage", "案件管理", "業務"),
    ("project_manage", "案件叫料－修改", "業務"),
    ("customer", "客戶管理", "業務"),
    ("financial_view", "財務金額可視", "財務"),
    ("finance", "應收帳款／銷售訂單", "財務"),
    ("reports", "營運報表", "財務"),
    ("cashier", "出納（標記已匯款/已收款、銀行對帳）", "財務"),
    ("procurement", "供應商／料號／採購", "採購"),
    ("inventory", "庫存管理", "採購"),
    ("equipment", "設備登載／保固", "設備"),
    ("netplan", "網路架構規劃書－檢視", "網路架構規劃書"),
    ("netplan_edit", "網路架構規劃書－新增修改刪除", "網路架構規劃書"),
    ("project_approve_eng", "案件待辦－工程主管確認", "專案"),   # CU2b 用詞裁示：代辦→待辦
    ("project_approve_biz", "案件待辦－業務確認", "專案"),
    ("work_log", "工作日誌", "工作"),
    ("daily_task", "每日工作事項", "工作"),
    ("contractor_list", "外包名冊", "勞務"),
    ("payslip", "勞報單", "勞務"),
    ("settings", "系統設定", "系統"),
    ("audit_log", "歷史紀錄（全系統操作軌跡）", "系統"),
    ("shipping_export_log", "出貨單歷史紀錄", "系統"),
    ("module_versions", "版本紀錄", "系統"),
]

GOLDEN_ROLE_TEMPLATES = {
    "superadmin": ["dashboard", "quotation", "case_manage", "customer", "procurement", "inventory", "equipment", "finance", "reports", "settings", "project_approve_eng", "project_approve_biz", "financial_view", "work_log", "daily_task", "cashier", "netplan", "audit_log", "shipping_export_log", "module_versions"],
    "admin": ["dashboard", "quotation", "case_manage", "customer", "procurement", "inventory", "equipment", "finance", "reports", "project_approve_eng", "project_approve_biz", "financial_view", "work_log", "daily_task", "cashier"],
    "sales": ["dashboard", "quotation", "case_manage", "customer", "financial_view", "project_approve_biz", "work_log", "daily_task", "map"],
    "engineer": ["dashboard", "case_manage", "project_approve_eng", "equipment", "work_log", "daily_task"],
    "viewer": ["dashboard"],
}

GOLDEN_SUPERADMIN = ["dashboard", "quotation", "case_manage", "customer", "procurement", "inventory", "equipment", "finance", "reports", "cashier", "settings", "project_approve_eng", "project_approve_biz", "financial_view", "work_log", "daily_task", "netplan", "audit_log", "shipping_export_log", "module_versions"]


def test_catalogue_is_unchanged_key_label_group_and_order():
    from helpers.module_registry import MODULES
    assert [tuple(m) for m in MODULES] == [tuple(m) for m in GOLDEN_MODULES]


def test_role_templates_are_unchanged():
    from helpers.module_registry import ROLE_TEMPLATES
    assert {r: list(v) for r, v in ROLE_TEMPLATES.items()} == GOLDEN_ROLE_TEMPLATES


def test_superadmin_default_keeps_its_order():
    from helpers.module_registry import SUPERADMIN_DEFAULT, ROLE_TEMPLATES
    assert list(SUPERADMIN_DEFAULT) == GOLDEN_SUPERADMIN
    assert set(SUPERADMIN_DEFAULT) == set(ROLE_TEMPLATES["superadmin"])


def test_every_template_key_is_in_the_catalogue():
    from helpers.module_registry import ROLE_TEMPLATES, MODULE_KEYS, BADGE_PREFIXES, BADGE_EXCLUDE
    for role, keys in ROLE_TEMPLATES.items():
        assert isinstance(keys, tuple) and set(keys) <= MODULE_KEYS, role
    assert set(BADGE_PREFIXES) <= MODULE_KEYS
    assert set(BADGE_EXCLUDE) <= set(BADGE_PREFIXES)


def _hdr(client, make_user, username, role):
    u, p = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_catalog_endpoint_serves_the_registry_to_superadmin(client, make_user):
    from helpers.module_registry import catalog
    h = _hdr(client, make_user, "root", "superadmin")
    r = client.get("/api/modules/catalog", headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == catalog()
    assert len(r.json()["modules"]) == len(GOLDEN_MODULES)


@pytest.mark.parametrize("role", ["admin", "sales", "viewer"])
def test_catalog_endpoint_is_not_wider_than_the_users_page(client, make_user, role):
    """使用者管理頁只給 superadmin（sidebar.js `sa`）⇒ 這支也只給 superadmin，不放寬。"""
    h = _hdr(client, make_user, "u_" + role, role)
    assert client.get("/api/modules/catalog", headers=h).status_code == 403


def test_catalog_endpoint_needs_login(client):
    assert client.get("/api/modules/catalog").status_code == 401


# ── 第二階段：各處改成引用 registry，不可以再抄一份 ──────────────────────────

import os
import re

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _src(*parts):
    return open(os.path.join(_ROOT, *parts), encoding="utf-8").read()


def test_users_page_has_no_hardcoded_module_lists():
    """權限畫面改由 `/api/modules/catalog` 取得；寫死的清單＝又多一份會漂移的副本。"""
    html = _src("frontend", "pages", "users.html")
    assert "/api/modules/catalog" in html
    assert not re.search(r"allModules:\s*\[\s*\{key:", html), "users.html 又寫死了權限目錄"
    assert not re.search(r"ROLE_MODULES\s*=\s*\{\s*\n?\s*superadmin:\s*\[", html), "users.html 又寫死了角色樣板"


def test_backend_copies_are_the_registry_itself():
    """auth.py／system.py 的名稱保留（既有呼叫端不用改），但值就是 registry 那一份。"""
    import helpers.auth as auth
    import routers.system as system
    from helpers import module_registry as reg
    assert list(auth._SUPERADMIN_MODULES) == list(reg.SUPERADMIN_DEFAULT)
    assert system._MODULE_ACTION_PREFIXES is reg.BADGE_PREFIXES
    assert system._MODULE_EXCLUDE_ACTIONS is reg.BADGE_EXCLUDE
    assert "from helpers.module_registry import" in _src("backend", "helpers", "auth.py")


# ── 第三階段：後端驗證「這次新增的」key（使用者：「要，只驗這次新增的」）───────

def _set_user_modules(username, modules):
    import json
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET modules=? WHERE username=?", (json.dumps(modules), username))
        conn.commit()
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def test_creating_a_user_with_an_unknown_module_is_refused(client, make_user):
    h = _hdr(client, make_user, "root", "superadmin")
    r = client.post("/api/users", json={"username": "newbie", "password": "Str0ng-Pass-9x",
                                        "role": "sales", "modules": ["dashboard", "bogus_key"]},
                    headers=h)
    assert r.status_code == 400, r.text
    assert "bogus_key" in r.json()["detail"]


def test_creating_a_user_with_known_modules_still_works(client, make_user):
    h = _hdr(client, make_user, "root", "superadmin")
    r = client.post("/api/users", json={"username": "newbie", "password": "Str0ng-Pass-9x",
                                        "role": "sales", "modules": ["dashboard", "quotation"]},
                    headers=h)
    assert r.status_code == 201, r.text


def test_a_legacy_key_already_on_the_account_is_kept(client, make_user):
    """零影響：帳號身上本來就有的舊 key（例如已停用的 `sales`）存檔時照樣放行。"""
    h = _hdr(client, make_user, "root", "superadmin")
    make_user(username="old", role="sales")
    uid = _set_user_modules("old", ["dashboard", "sales"])
    r = client.put("/api/users/%d" % uid, json={"modules": ["dashboard", "sales", "quotation"]},
                   headers=h)
    assert r.status_code == 200, r.text


def test_adding_a_new_unknown_key_to_an_existing_account_is_refused(client, make_user):
    h = _hdr(client, make_user, "root", "superadmin")
    make_user(username="old", role="sales")
    uid = _set_user_modules("old", ["dashboard", "sales"])
    r = client.put("/api/users/%d" % uid, json={"modules": ["dashboard", "sales", "bogus_key"]},
                   headers=h)
    assert r.status_code == 400, r.text


def test_custom_role_refuses_a_new_unknown_key_but_keeps_its_own_legacy_ones(client, make_user):
    from helpers.settings import _set_setting
    h = _hdr(client, make_user, "root", "superadmin")
    r = client.post("/api/settings/custom-roles",
                    json={"name": "新角色", "baseRole": "sales", "modules": ["bogus_key"]}, headers=h)
    assert r.status_code == 400, r.text
    _set_setting("custom_roles", [{"id": "r1", "name": "舊角色", "baseRole": "sales",
                                   "modules": ["dashboard", "sales"]}])
    r = client.put("/api/settings/custom-roles/r1",
                   json={"name": "舊角色", "baseRole": "sales", "modules": ["dashboard", "sales"]},
                   headers=h)
    assert r.status_code == 200, r.text
    r = client.put("/api/settings/custom-roles/r1",
                   json={"name": "舊角色", "baseRole": "sales", "modules": ["dashboard", "bogus_key"]},
                   headers=h)
    assert r.status_code == 400, r.text


# ── 頁面實測：權限畫面真的從目錄端點長出來 ─────────────────────────────────

@pytest.mark.e2e
def test_users_page_builds_its_module_list_from_the_catalog(live_server, make_user, e2e_browser):
    """行為不變守門（誠實記錄：用整併前的 users.html 跑也綠——值本來就相同）。
    先紅的是 `test_users_page_has_no_hardcoded_module_lists`。"""
    pytest.importorskip("playwright.sync_api")
    from tests._e2e_login import inject_login as _login
    u, pw = make_user(username="root", role="superadmin")
    browser = e2e_browser
    page = browser.new_page()
    _login(page, live_server, u, pw)
    page.goto(live_server + "/pages/users.html")
    page.wait_for_function("() => window.Alpine && document.querySelector('[x-data]')"
                           " && Alpine.$data(document.querySelector('[x-data]')).allModules.length > 0",
                           timeout=15000)
    page.wait_for_selector(".access-chip", timeout=15000)   # 帳號列表載完才有徽章
    got = page.evaluate("""() => {
        const d = Alpine.$data(document.querySelector('[x-data]'))
        d.openCreate()
        return { n: d.allModules.length, first: d.allModules[0].key,
                 salesDefault: [...d.form.modules], chips: document.querySelectorAll('.access-chip').length }
    }""")
    from helpers.module_registry import ROLE_TEMPLATES
    assert got["n"] == len(GOLDEN_MODULES) and got["first"] == "dashboard"
    assert got["salesDefault"] == list(ROLE_TEMPLATES["sales"])
    assert got["chips"] >= len(GOLDEN_MODULES)          # 每個帳號列一排徽章
