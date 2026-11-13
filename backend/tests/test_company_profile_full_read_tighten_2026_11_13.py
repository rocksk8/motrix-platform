# -*- coding: utf-8 -*-
"""公司資料完整版預設只限最高管理者——既有環境的一次性收緊（T84，使用者裁示 2026-11-13，方案 A 的 (a)）。

背景：開關 `account_security.company_profile_full_read_superadmin_only` 預設 0→1，但設定中心存檔會把整個群組（含這個開關）存成明確值，
所以曾存過「登入與密碼」的既有環境仍是 0，預設值看不到。`helpers/startup._tighten_company_profile_full_read_once` 在啟動時**每庫只跑一次**：
生效值是 0 ⇒ 經設定中心引擎發布 1（寫變更明細與稽核：系統升級、0→1、原因）；已是 1 ⇒ 只記標記；標記在之後不再動
（使用者自己調回 0 要保留）。

釘住：舊存值 0 → 升級後 1（含稽核）；跑過之後手動改回 0 → 再啟動仍是 0；全新安裝 → 1、不寫稽核；失敗不記標記、下次再試；main.py 真的有呼叫。
"""
import json
import re
from pathlib import Path

import pytest

GROUP, FIELD = "account_security", "company_profile_full_read_superadmin_only"
MARK = "migration_company_profile_full_read_tighten_t84"
AUDIT_ACTION = "settings.account_security.update"
MAIN_PY = Path(__file__).resolve().parents[1] / "main.py"


def _sql(sql, args=()):
    import db
    c = db.get_db()
    try:
        rows = c.execute(sql, args).fetchall()
        c.commit()
        return rows
    finally:
        c.close()


def _effective():
    import db
    from helpers import settings_registry as SR
    SR.invalidate()
    c = db.get_db()
    try:
        return int(SR.get(GROUP, FIELD, conn=c))
    finally:
        c.close()


def _store_switch(value):
    """模擬「曾在設定中心存過『登入與密碼』」的庫：整個群組存成明確值，開關為 `value`（直接發布定義版本，不走引擎的放寬核准）。"""
    import db
    from core import definitions as D
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        vals = dict(SR.get_group(GROUP, conn=c))
        vals[FIELD] = value
        D.publish_direct(c, SR.KIND, GROUP, SR.SCOPE, {"group": GROUP, "values": vals}, "legacy", "legacy_admin")
    finally:
        c.close()
    SR.invalidate()


def _mark():
    rows = _sql("SELECT value_json FROM system_settings WHERE key=?", (MARK,))
    return json.loads(rows[0][0]) if rows else None


def _clear_mark():
    _sql("DELETE FROM system_settings WHERE key=?", (MARK,))


def _audits():
    return _sql("SELECT username, display_name, detail FROM audit_log WHERE action=? ORDER BY id", (AUDIT_ACTION,))


def _run():
    from helpers import startup
    from helpers import settings_registry as SR
    startup._tighten_company_profile_full_read_once()
    SR.invalidate()


@pytest.fixture()
def fresh(client):
    """每題從乾淨的庫開始：沒有標記、沒有存過的群組版本、沒有這個動作的稽核。"""
    _clear_mark()
    _sql("DELETE FROM audit_log WHERE action=?", (AUDIT_ACTION,))
    return client


def test_legacy_stored_zero_is_tightened_once_with_an_audit_record(fresh):
    _store_switch(0)
    assert _effective() == 0, "前置：模擬舊庫，生效值要是 0"
    _run()
    assert _effective() == 1
    assert _mark()["result"] == "tightened"
    rows = _audits()
    assert len(rows) == 1
    username, display, detail = rows[0]
    d = json.loads(detail)
    assert username == "system" and display == "系統升級"
    assert d["changes"] == [{"field": FIELD, "old": 0, "new": 1}]
    assert "T84" in d["reason"] and "0→1" in d["reason"] and "設定中心" in d["reason"]
    ch = _sql("SELECT actor, actor_display, field, old_json, new_json, reason FROM config_changes WHERE domain=? AND key=? AND field=?",
              ("setting:%s" % GROUP, GROUP, FIELD))
    assert len(ch) == 1, "變更明細要有一列（真的走設定中心引擎發布）：%r" % (ch,)
    actor, actor_display, field, old, new, reason = ch[0]
    assert (actor, actor_display, field, json.loads(old), json.loads(new)) == ("system", "系統升級", FIELD, 0, 1)
    assert "T84" in reason


def test_running_again_changes_nothing(fresh):
    _store_switch(0)
    _run()
    before = (_effective(), len(_audits()), _mark())
    _run()
    _run()
    assert (_effective(), len(_audits()), _mark()) == before


def test_user_loosening_after_the_migration_is_kept(fresh):
    """跑過遷移之後使用者自己調回 0（放寬、經核准後生效）⇒ 再升級／再啟動仍是 0：標記擋住第二次。"""
    _store_switch(0)
    _run()
    assert _effective() == 1
    _store_switch(0)                                   # 核准後的放寬在庫裡就是一份存 0 的版本
    assert _effective() == 0
    audits = len(_audits())
    _run()
    assert _effective() == 0, "標記存在後不可以再被收緊"
    assert len(_audits()) == audits


def test_fresh_install_is_already_on_and_writes_no_audit(fresh):
    assert _effective() == 1, "全新安裝：預設 1"
    _run()
    assert _effective() == 1
    assert _mark()["result"] == "already_on"
    assert _audits() == []
    # 之後使用者放寬成 0：保留
    _store_switch(0)
    _run()
    assert _effective() == 0 and _audits() == []


def test_stored_one_is_left_alone_and_marked(fresh):
    _store_switch(1)
    _run()
    assert _effective() == 1 and _mark()["result"] == "already_on" and _audits() == []


def test_failure_does_not_mark_and_never_raises_then_retries(fresh, monkeypatch):
    from helpers import settings_registry as SR
    _store_switch(0)

    def boom(*a, **k):
        raise RuntimeError("publish failed")

    monkeypatch.setattr(SR, "publish", boom)
    _run()                                             # 不丟例外
    assert _mark() is None and _effective() == 0
    monkeypatch.undo()
    _run()                                             # 下次啟動再試成功
    assert _effective() == 1 and _mark()["result"] == "tightened"


def test_the_migration_only_touches_this_one_field(fresh):
    """整個群組是一起存的：收緊時其他欄位（例：登入天數）維持原值。"""
    import db
    from core import definitions as D
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        vals = dict(SR.get_group(GROUP, conn=c))
        vals[FIELD] = 0
        vals["login_days"] = 7
        D.publish_direct(c, SR.KIND, GROUP, SR.SCOPE, {"group": GROUP, "values": vals}, "legacy", "legacy_admin")
    finally:
        c.close()
    SR.invalidate()
    _run()
    c = db.get_db()
    try:
        now = SR.get_group(GROUP, conn=c)
    finally:
        c.close()
    assert now[FIELD] == 1 and now["login_days"] == 7


def test_migration_makes_non_superadmin_get_403_on_the_full_endpoint(fresh, make_user):
    u, p = make_user(username="cp_t84_viewer", role="viewer", modules=["settings"])
    su, sp = make_user(username="cp_t84_sa", role="superadmin")
    h = {}
    for name, (uu, pp) in (("viewer", (u, p)), ("sa", (su, sp))):
        r = fresh.post("/api/auth/login", json={"username": uu, "password": pp})
        assert r.status_code == 200, r.text
        h[name] = {"Authorization": "Bearer " + r.json()["token"]}
    _store_switch(0)
    assert fresh.get("/api/settings/company-profile", headers=h["viewer"]).status_code == 200, "前置：舊庫登入即可讀"
    _run()
    assert fresh.get("/api/settings/company-profile", headers=h["viewer"]).status_code == 403
    assert fresh.get("/api/settings/company-profile", headers=h["sa"]).status_code == 200
    assert fresh.get("/api/settings/company-profile/public", headers=h["viewer"]).status_code == 200


def test_main_calls_the_migration_at_startup_after_init():
    src = MAIN_PY.read_text(encoding="utf-8")
    assert re.search(r"^_tighten_company_profile_full_read_once\(\)", src, re.M), "main.py 沒有呼叫一次性收緊遷移"
    assert src.index("init_unlock_passwords()\n_startup_step") < src.index("\n_tighten_company_profile_full_read_once()"), "要在 init 之後"
    assert "_tighten_company_profile_full_read_once," in src.split("from archive import")[0], "main.py 沒有 import"
