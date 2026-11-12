# -*- coding: utf-8 -*-
"""公司資料的公開子集與「完整內容只給最高管理者」開關（2026-11-13，hichan-12 發現、PM 派工）。

事實：`GET /api/settings/company-profile` 只要求登入，任何角色都讀得到匯款帳號、統編、電話、地址、
每個據點自己的銀行欄位。非設定頁的呼叫者其實只要：名稱／統編／聯絡方式（勞報單、傳票）與據點的 id＋名稱（案件、核准、報價單）。
單據列印在伺服器端組（pdf_gen／company_identity），不經這個端點。

第一步（不改權限、不洩漏新東西）：新增 `/api/settings/company-profile/public`（白名單），五個呼叫者改打它。
第二步（預設關＝行為不變）：設定中心「登入與密碼」的 `company_profile_full_read_superadmin_only`＝1 時，
完整端點對非最高管理者回 403。A 裁（讀取登入即可）仍是預設；要不要打開由使用者決定。
"""
import json
import re

import pytest

SECRET_ACCOUNT = "0123-4567-8901-2345"
FULL_ONLY_KEYS = ("bank_name", "bank_branch", "bank_account_name", "bank_account_number", "address",
                  "phone", "email", "office_lat", "office_lon", "privacy_notice", "google_maps_api_key",
                  "google_maps_browser_key", "google_maps_map_id", "company_name_en", "confirmIdentity")
GROUP, FIELD = "account_security", "company_profile_full_read_superadmin_only"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def roles(client, make_user):
    out = {}
    for role, modules in (("superadmin", None), ("admin", ["settings"]), ("viewer", ["settings"]), ("engineer", None),
                          ("finance", None), ("sales", None)):
        kw = {"username": "cp_" + role, "role": role}
        if modules:
            kw["modules"] = modules
        u, p = make_user(**kw)
        out[role] = _login(client, u, p)
    return out


@pytest.fixture()
def seeded(client, roles):
    body = {"name": "摩特銳斯股份有限公司", "tax_id": "04595257", "contact_info": "02-1234-5678 / a@b.example",
            "bank_name": "某某銀行", "bank_branch": "信義分行", "bank_account_name": "摩特銳斯", "bank_account_number": SECRET_ACCOUNT,
            "address": "台北市信義區某路 1 號", "phone": "02-1234-5678", "email": "ops@b.example",
            "privacy_notice": "個資告知文字", "google_maps_api_key": "AIzaSyFAKEFAKEFAKEFAKEFAKEFAKE0123456789",
            "locations": [{"id": "L1", "name": "總公司", "address": "台北市信義區某路 1 號", "bank_account_number": "9999-0000"},
                          {"id": "L2", "name": "台中分公司", "address": "台中市西屯區某路 2 號", "tax_id": "12345678",
                           "phone": "04-0000-0000", "bank_name": "另一家銀行", "lat": 24.1, "lon": 120.6}]}
    r = client.put("/api/settings/company-profile", headers=roles["superadmin"], json=body)
    assert r.status_code == 200, r.text
    return body


def _set_switch(value):
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish(GROUP, {FIELD: value}, user="cp_sa", reason="test", conn=c)
        SR.invalidate()
    finally:
        c.close()


def _all_text(obj):
    return json.dumps(obj, ensure_ascii=False)


# ── /public：每個角色拿到的內容一樣、只有白名單 ─────────────────────────────

@pytest.mark.parametrize("role", ["superadmin", "admin", "viewer", "engineer", "finance", "sales"])
def test_public_subset_for_every_role_is_exactly_the_allowlist(client, roles, seeded, role):
    r = client.get("/api/settings/company-profile/public", headers=roles[role])
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d) == {"name", "tax_id", "contact_info", "locations"}, sorted(d)
    assert d["name"] == "摩特銳斯股份有限公司" and d["tax_id"] == "04595257" and d["contact_info"].startswith("02-1234")
    assert d["locations"] == [{"id": "L1", "name": "總公司"}, {"id": "L2", "name": "台中分公司"}]
    text = _all_text(d)
    for needle in (SECRET_ACCOUNT, "9999-0000", "某某銀行", "信義區", "ops@b.example", "AIza", "個資告知", "12345678", "04-0000-0000", "24.1"):
        assert needle not in text, needle


def test_public_requires_login(client, seeded):
    assert client.get("/api/settings/company-profile/public").status_code in (401, 403)
    assert client.get("/api/settings/company-profile/public", headers={"Authorization": "Bearer nope"}).status_code in (401, 403)


def test_public_is_an_allowlist_new_profile_keys_stay_private(client, roles, seeded):
    """變異：profile 裡多一個鍵（連同它的值）⇒ 不會出現在 /public。"""
    import db
    c = db.get_db()
    try:
        row = c.execute("SELECT value_json FROM system_settings WHERE key='company_profile'").fetchone()
        prof = json.loads(row["value_json"])
        prof["brand_new_secret"] = "TOPSECRET-VALUE"
        prof["locations"][0]["brand_new_location_secret"] = "LOC-SECRET"
        c.execute("UPDATE system_settings SET value_json=? WHERE key='company_profile'", (json.dumps(prof, ensure_ascii=False),))
        c.commit()
    finally:
        c.close()
    text = _all_text(client.get("/api/settings/company-profile/public", headers=roles["viewer"]).json())
    assert "TOPSECRET-VALUE" not in text and "LOC-SECRET" not in text and "brand_new" not in text


def test_public_legacy_install_without_locations_gets_the_migrated_head_office(client, roles, make_user):
    """舊安裝沒有 locations、只有 address ⇒ 與完整端點同樣補一筆「總公司」（只有 id＋名稱）。"""
    import db
    c = db.get_db()
    try:
        c.execute("UPDATE system_settings SET value_json=? WHERE key='company_profile'",
                  (json.dumps({"name": "舊公司", "address": "某地址 9 號"}, ensure_ascii=False),))
        c.commit()
    finally:
        c.close()
    d = client.get("/api/settings/company-profile/public", headers=roles["engineer"]).json()
    assert d["locations"] == [{"id": "loc_1", "name": "總公司"}] and d["name"] == "舊公司" and "某地址" not in _all_text(d)


# ── 完整端點：預設（開關關）行為不變 ───────────────────────────────────────

@pytest.mark.parametrize("role", ["superadmin", "admin", "viewer", "engineer", "finance", "sales"])
def test_full_endpoint_default_is_unchanged_every_logged_in_role_still_reads_it(client, roles, seeded, role):
    """預設關 ⇒ 與今天逐位元相同（A 裁：讀取登入即可）；SA4 的回歸守門仍成立。"""
    r = client.get("/api/settings/company-profile", headers=roles[role])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["bank_account_number"] == SECRET_ACCOUNT and d["tax_id"] == "04595257" and d["address"]
    assert d["google_maps_api_key"].startswith("•") and "AIza" not in _all_text(d)     # 金鑰照舊遮蔽


def test_switch_default_is_off_and_registered_as_a_tightening_setting():
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as SR
    f = SR.field_defs(GROUP)[FIELD]
    assert f.default == 0 and (f.min, f.max) == (0, 1) and f.loosen == "down" and f.risk == "security"
    assert SR.get(GROUP, FIELD) == 0


# ── 完整端點：開關開了以後 ─────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["admin", "viewer", "engineer", "finance", "sales"])
def test_switch_on_non_superadmin_is_refused_on_the_full_endpoint(client, roles, seeded, role):
    _set_switch(1)
    r = client.get("/api/settings/company-profile", headers=roles[role])
    assert r.status_code == 403
    assert SECRET_ACCOUNT not in r.text and "04595257" not in r.text
    # 公開子集照常（頁面不壞）
    assert client.get("/api/settings/company-profile/public", headers=roles[role]).status_code == 200


def test_switch_on_superadmin_still_reads_everything_and_can_save(client, roles, seeded):
    """正對照：只擋非最高管理者；少了這題，「一律 403」會讓上面全綠而設定頁壞掉。"""
    _set_switch(1)
    r = client.get("/api/settings/company-profile", headers=roles["superadmin"])
    assert r.status_code == 200 and r.json()["bank_account_number"] == SECRET_ACCOUNT
    assert client.put("/api/settings/company-profile", headers=roles["superadmin"], json={"phone": "02-0000-1111"}).status_code == 200


def test_switch_off_again_is_a_loosening_and_not_immediate(client, roles, seeded):
    """1→0 讓所有登入者讀得到完整資料 ＝ 放寬：走待生效（確認期間＋第二位最高管理者核准），當下仍維持限制。"""
    _set_switch(1)
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        res = SR.publish(GROUP, {FIELD: 0}, user="cp_sa", reason="test", conn=c)
        SR.invalidate()
    finally:
        c.close()
    assert res["pending"] and res["pending"][0]["field"] == FIELD and res["pending"][0]["approvalsRequired"] >= 1
    assert SR.get(GROUP, FIELD) == 1
    assert client.get("/api/settings/company-profile", headers=roles["viewer"]).status_code == 403


def test_unreadable_switch_fails_closed_for_non_superadmin_only(client, roles, seeded, monkeypatch):
    from helpers import settings_registry as SR

    def boom(*a, **k):
        raise RuntimeError("registry down")
    monkeypatch.setattr(SR, "get", boom)
    assert client.get("/api/settings/company-profile", headers=roles["viewer"]).status_code == 403
    assert client.get("/api/settings/company-profile", headers=roles["superadmin"]).status_code == 200


# ── 前端：除了設定頁，沒有人讀完整端點 ──────────────────────────────────────

#: 讀完整公司資料端點的名單：設定頁，以及公司設定精靈（T84，只有最高管理者進得去，非最高管理者看到「沒有權限」卡）。
FULL_ENDPOINT_READERS = {"company-profile-settings.html", "company-wizard.js"}
#: 裸的 `company-profile`（不論前面是 `settings/`、拼接的變數或 %2D 編碼）——後面不是 `-xxx`（頁面檔名）也不是 `/public`。
_FULL_URL = re.compile(r"company-profile(?![\w-])(?!/public)")


def test_only_the_settings_page_reads_the_full_endpoint():
    """守門：頁面／JS 讀公司資料一律打 /public；只有 FULL_ENDPOINT_READERS 可以讀完整端點。
    （搬家或新頁面照抄舊寫法 ⇒ 開關一開，那一頁的據點名稱等就靜默消失。伺服器端才是真正的控制，這題只是回歸網。）
    連拼接（`'/api/settings/' + 'company-profile'`）、變數基底（`B + '/company-profile'`）、%2D 編碼都算；純註解行不算。"""
    from urllib.parse import unquote
    from tests import _frontend_sources as FS
    from core import source_tree
    files = [FS.FRONTEND / "index.html"] + list(source_tree.page_files()) + list(FS.all_js())
    bad = []
    for f in files:
        if f.name in FULL_ENDPOINT_READERS:
            continue
        for line in unquote(f.read_text(encoding="utf-8", errors="replace")).splitlines():
            s = line.strip()
            if s.startswith(("//", "*", "/*", "<!--")):
                continue
            for m in _FULL_URL.finditer(line):
                bad.append("%s: …%s" % (f.name, line[max(0, m.start() - 24):m.end() + 12].strip()))
    assert not bad, "這些檔案讀的是完整公司資料端點（應改 /api/settings/company-profile/public）：" + chr(10) + chr(10).join(bad)


def test_guard_scanner_positive_control():
    """掃描樣式要抓得到各種寫法，且不誤報 /public、頁面檔名。"""
    from urllib.parse import unquote
    hit = lambda s: bool(_FULL_URL.search(unquote(s)))
    for bad in ("fetch('/api/settings/company-profile')", "fetch(`${API}/settings/company-profile`, {", "B + '/company-profile'",
                "'/api/settings/' + 'company-profile'", "/api/settings/company%2Dprofile", "/api/settings/company-profile?x=1"):
        assert hit(bad), bad
    for good in ("/api/settings/company-profile/public", "location.href='company-profile-settings.html'", "company-setup-required.html"):
        assert not hit(good), good


@pytest.mark.parametrize("name", ["case-management-core.js", "voucher.js"])
def test_js_callers_use_the_public_url(name):
    from tests import _frontend_sources as FS
    assert "/api/settings/company-profile/public" in FS.js_path(name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["approval-queue.html", "quotation-form.html", "payslip-form.html"])
def test_page_callers_use_the_public_url(name):
    from core import source_tree
    assert "settings/company-profile/public" in source_tree.page_file(name).read_text(encoding="utf-8")
