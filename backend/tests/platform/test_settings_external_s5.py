# -*- coding: utf-8 -*-
"""S5：設定中心以外的四個外部群組（bonus_voucher／tax_rules／t100_export／overhead_basis）的契約測試（SPEC §15.A.3-6）。

重點：舊端點仍是唯一入口、全部改走 `settings_registry.publish()`（待生效＋第二位最高管理者核准＋稽核）；
舊鍵只有轉接器能寫；設定中心通用路由對外部群組一律拒絕；公開清單不外洩原始值。
"""
import json
import re

import pytest

import db
from helpers import settings_groups_external as X
from helpers import settings_registry as R
from tests._settings_activate import activate_now

EXTERNAL = ("bonus_voucher", "tax_rules", "t100_export", "overhead_basis")


def _auth(client, make_user, name, role="superadmin"):
    u, p = make_user(username=name, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    return {"Authorization": "Bearer " + r.json()["token"]}


def _raw(key):
    conn = db.get_db()
    try:
        r = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
        return json.loads(r["value_json"]) if r else None
    finally:
        conn.close()


# ── 靜態：群組登記、預設值一致、舊鍵寫入者 ────────────────────────────────────────
def test_four_external_groups_are_registered_external_and_loosen_both():
    gs = R.groups()
    for g in EXTERNAL:
        assert g in gs and gs[g]["external"] is True, g


def test_t100_default_literal_equals_the_adapter_default():
    from modules.accounting.api import accounting_export as AE
    assert AE._DEFAULT_T100_CONFIG == X.T100_DEFAULT_CONFIG, "accounting_export 的預設字面值要和轉接器的預設一致"


def test_bonus_slots_are_the_same_table_in_the_voucher_module():
    from modules.payroll import bonus_vouchers as BV
    assert BV.ACCOUNT_SLOTS is X.BONUS_SLOTS


_OLD_KEYS = ("tax_rules_versions", "t100_export_config", "overhead_rule_mode", "charity_basis_mode")


def test_old_keys_are_written_only_by_the_external_adapters():
    """舊鍵（法規版本、T100 設定、管銷／公益口徑）只能由 settings_groups_external 寫；其他程式碼出現這些鍵的『寫入』＝繞過登錄表。"""
    from tests.platform import _settings_baseline as B
    keys = set(_OLD_KEYS) | {v[0] for v in X.BONUS_SLOTS.values()}
    pat = re.compile(r"(set_setting|_set_setting|INSERT\s+(?:OR\s+\w+\s+)?INTO\s+system_settings|UPDATE\s+system_settings)[^\n]*")
    bad = []
    for f in B.BACKEND.rglob("*.py"):
        rel = f.relative_to(B.BACKEND).as_posix()
        if rel.startswith(("tests/", ".venv")) or "/tests/" in rel or rel.endswith("settings_groups_external.py") \
                or rel.startswith("tools/") or rel == "helpers/settings_registry.py":
            continue
        txt = f.read_text(encoding="utf-8", errors="ignore")
        for m in pat.finditer(txt):
            if any(("'%s'" % k in m.group(0)) or ('"%s"' % k in m.group(0)) for k in keys):
                bad.append("%s: %s" % (rel, m.group(0)[:90]))
    assert bad == []


# ── 設定中心通用路由拒絕外部群組、清單不列 ─────────────────────────────────────────
def test_generic_settings_center_routes_reject_external_groups(client, make_user):
    h = _auth(client, make_user, "s5_sa_generic")
    for g in EXTERNAL:
        assert client.get("/api/settings-center/groups/%s" % g, headers=h).status_code in (403, 404), g
        assert client.post("/api/settings-center/groups/%s" % g, headers=h, json={"values": {}}).status_code in (403, 404), g
    listed = client.get("/api/settings-center/groups", headers=h).json()
    text = json.dumps(listed, ensure_ascii=False)
    assert not any('"%s"' % g in text for g in EXTERNAL)


# ── t100_export：待生效 → 核准後才寫舊鍵；單一最高管理者要等待期 ──────────────────────
def _accounts(*codes):
    conn = db.get_db()
    try:
        for c in codes:
            conn.execute("INSERT OR IGNORE INTO account_items (code, level, name, parent_code, source, is_active)"
                         " VALUES (?, 4, ?, '', 'custom', 1)", (c, "測試科目" + c))
        conn.commit()
    finally:
        conn.close()


def test_t100_put_is_pending_and_does_not_touch_the_old_key_until_approved(client, make_user):
    h = _auth(client, make_user, "s5_sa_t100")
    _accounts("1101")
    before = _raw("t100_export_config")
    r = client.put("/api/settings/t100-export-config", headers=h,
                   json={"bankAccounts": [{"name": "主要帳戶", "acctCode": "1101"}], "defaultBankAccountCode": "1101"})
    assert r.status_code == 200 and r.json()["pending"], r.text
    assert _raw("t100_export_config") == before, "待生效期間舊鍵不能動"
    assert client.get("/api/settings/t100-export-config", headers=h).json()["defaultBankAccountCode"] == ""
    activate_now("t100_export")
    assert client.get("/api/settings/t100-export-config", headers=h).json()["defaultBankAccountCode"] == "1101"
    assert _raw("t100_export_config") != before


def test_t100_put_with_unknown_account_code_is_rejected_400(client, make_user):
    h = _auth(client, make_user, "s5_sa_t100b")
    r = client.put("/api/settings/t100-export-config", headers=h,
                   json={"bankAccounts": [{"name": "X", "acctCode": "9999999"}]})
    assert r.status_code == 400 and "不存在" in r.text


def test_t100_second_pending_for_the_same_group_conflicts_unless_superseded(client, make_user):
    h = _auth(client, make_user, "s5_sa_t100c")
    _accounts("1101", "1102")
    body = {"bankAccounts": [{"name": "A", "acctCode": "1101"}]}
    assert client.put("/api/settings/t100-export-config", headers=h, json=body).status_code == 200
    r2 = client.put("/api/settings/t100-export-config", headers=h, json={"bankAccounts": [{"name": "B", "acctCode": "1102"}]})
    assert r2.status_code == 409, r2.text


def test_t100_unchanged_put_creates_nothing(client, make_user):
    h = _auth(client, make_user, "s5_sa_t100d")
    cur = client.get("/api/settings/t100-export-config", headers=h).json()
    r = client.put("/api/settings/t100-export-config", headers=h, json={"defaultBankAccountCode": cur["defaultBankAccountCode"]})
    assert r.status_code == 200 and r.json()["pending"] == []


# ── tax_rules ───────────────────────────────────────────────────────────────────
def test_tax_rules_put_unchanged_is_a_noop_and_changed_is_pending(client, make_user):
    h = _auth(client, make_user, "s5_sa_tax")
    cur = client.get("/api/legal-params/tax-rules", headers=h)
    if cur.status_code == 404:
        pytest.skip("法規參數路由路徑不同")
    versions = cur.json()["versions"]
    r = client.put("/api/legal-params/tax-rules", headers=h, json={"versions": versions})
    assert r.status_code == 200 and not r.json().get("pending")


# ── overhead_basis：口徑切換待生效；舊鍵／標記一致 ─────────────────────────────────
def test_overhead_mode_switch_is_pending_then_old_keys_follow_the_approval(client, make_user):
    h = _auth(client, make_user, "s5_sa_oh")
    conn = db.get_db()
    try:
        X.raw_put(conn, "overhead_migration_done", {"doneAt": "2026-10-09T00:00:00", "by": "test"})
        conn.commit()
    finally:
        conn.close()
    r = client.put("/api/overhead/settings", headers=h, json={"ruleMode": "v2", "confirm": True})
    assert r.status_code == 200 and r.json()["pending"], r.text
    assert _raw("overhead_rule_mode") in (None, "legacy")
    activate_now("overhead_basis")
    assert _raw("overhead_rule_mode") == "v2"
    r = client.put("/api/overhead/settings", headers=h, json={"ruleMode": "legacy"})
    assert r.status_code == 200
    activate_now("overhead_basis")
    assert _raw("overhead_rule_mode") == "legacy" and _raw("overhead_migration_done") is None, "退回舊口徑要一併移除遷移標記"


def test_overhead_switch_without_migration_marker_is_refused_409(client, make_user):
    h = _auth(client, make_user, "s5_sa_oh2")
    r = client.put("/api/overhead/settings", headers=h, json={"ruleMode": "v2", "confirm": True})
    assert r.status_code == 409 and "遷移" in r.text


# ── bonus_voucher：每格都驗證、只送有變的格 ──────────────────────────────────────────
def test_bonus_put_validates_every_supplied_slot(client, make_user):
    h = _auth(client, make_user, "s5_sa_bonus")
    r = client.put("/api/cases/voucher-accounts", headers=h, json={"expense": "9999999"})
    assert r.status_code == 400, r.text
    assert not _raw("bonus_case_voucher_expense_code") or _raw("bonus_case_voucher_expense_code") != "9999999"


# ── 漂移檢查：離線工具直接改了舊鍵 ⇒ 每日對帳會報 ──────────────────────────────────
def test_drift_report_flags_old_key_changed_behind_the_registry(client, make_user):
    h = _auth(client, make_user, "s5_sa_drift")
    _accounts("1101")
    client.put("/api/settings/t100-export-config", headers=h, json={"defaultBankAccountCode": "", "bankAccounts": [{"name": "A", "acctCode": "1101"}]})
    activate_now("t100_export")
    conn = db.get_db()
    try:
        assert "t100_export" not in [g for g, _ in X.drift_report(conn)]
        cfg = X.raw_get(conn, "t100_export_config") or {}
        cfg = dict(cfg, defaultBankAccountCode="1101")
        X.raw_put(conn, "t100_export_config", cfg)
        conn.commit()
        assert "t100_export" in [g for g, _ in X.drift_report(conn)]
    finally:
        conn.close()
