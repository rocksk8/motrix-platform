# -*- coding: utf-8 -*-
"""一條龍旗標預設開——既有環境的一次性遷移（T84，使用者裁示 2026-11-13：「一條龍上線就開啟，這班車結束就給使用者」）。

背景：群組 `onepipe` 每個旗標預設 0→1，但設定中心存檔會把整個群組存成明確值，所以曾存過這個群組的既有環境仍是 0。
`helpers/startup._enable_onepipe_defaults_once` 在啟動時**每庫只跑一次**：資料庫裡存成 0 的欄位（群組裡登錄的每一個欄位）⇒ 一次經設定中心引擎發布成 1
（寫設定變更明細與稽核：系統升級、0→1、原因含 T84）；之後使用者自己關掉要保留。

釘住：舊存值 0 → 1（含稽核與明細）；只跑一次；跑過之後使用者關掉的保留；已是 1／沒存過 ⇒ 只記標記、不寫稽核；
失敗不記標記、不丟例外、下次再試；其他欄位／其他鍵不動；main.py 真的有呼叫。
"""
import json
import re
from pathlib import Path

import pytest

GROUP = "onepipe"
MARK = "migration_onepipe_default_on_t84"
AUDIT_ACTION = "settings.onepipe.update"
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


def _fields():
    from helpers import settings_registry as SR
    import helpers.settings_groups  # noqa: F401
    return list(SR._g(GROUP)["fields"])


def _effective():
    import db
    from helpers import settings_registry as SR
    SR.invalidate()
    c = db.get_db()
    try:
        return {f: int(SR.get(GROUP, f, conn=c)) for f in _fields()}
    finally:
        c.close()


def _store(**over):
    """模擬曾在設定中心存過這個群組的庫：整個群組存成明確值（預設全 0，再用 over 覆蓋），直接發布定義版本（不走引擎）。"""
    import db
    from core import definitions as D
    from helpers import settings_registry as SR
    vals = {f: 0 for f in _fields()}
    vals.update(over)
    c = db.get_db()
    try:
        D.publish_direct(c, SR.KIND, GROUP, SR.SCOPE, {"group": GROUP, "values": vals}, "legacy", "legacy_admin")
    finally:
        c.close()
    SR.invalidate()


def _mark():
    rows = _sql("SELECT value_json FROM system_settings WHERE key=?", (MARK,))
    return json.loads(rows[0][0]) if rows else None


def _audits():
    return _sql("SELECT username, display_name, detail FROM audit_log WHERE action=? ORDER BY id", (AUDIT_ACTION,))


def _run():
    from helpers import startup
    from helpers import settings_registry as SR
    startup._enable_onepipe_defaults_once()
    SR.invalidate()


@pytest.fixture()
def fresh(client):
    _sql("DELETE FROM system_settings WHERE key=?", (MARK,))
    _sql("DELETE FROM audit_log WHERE action=?", (AUDIT_ACTION,))
    yield client
    _store(**{f: 1 for f in _fields()})                 # 不把「全 0」留給後面的測試
    _sql("DELETE FROM system_settings WHERE key=?", (MARK,))


def test_legacy_stored_zeros_are_enabled_once_with_an_audit_record(fresh):
    _store()
    assert set(_effective().values()) == {0}, "前置：模擬舊庫，每個旗標都存成 0"
    _run()
    assert set(_effective().values()) == {1}
    m = _mark()
    assert m["result"] == "enabled" and m["fields"] == sorted(_fields())
    rows = _audits()
    assert len(rows) == 1, "整批一次發布＝一筆稽核"
    username, display, detail = rows[0]
    d = json.loads(detail)
    assert username == "system" and display == "系統升級"
    assert sorted(c["field"] for c in d["changes"]) == sorted(_fields())
    assert all(c["old"] == 0 and c["new"] == 1 for c in d["changes"])
    assert "T84" in d["reason"] and "0→1" in d["reason"] and "設定中心" in d["reason"]
    ch = _sql("SELECT actor, actor_display, field, old_json, new_json, reason FROM config_changes WHERE domain=? AND key=?",
              ("setting:%s" % GROUP, GROUP))
    assert {r[2] for r in ch} >= set(_fields()), "每個欄位都有一列變更明細（真的走設定中心引擎發布）"
    for actor, actor_display, field, old, new, reason in ch:
        if field in _fields() and json.loads(old) == 0:
            assert (actor, actor_display, json.loads(new)) == ("system", "系統升級", 1) and "T84" in reason


def test_running_again_changes_nothing(fresh):
    _store()
    _run()
    before = (_effective(), len(_audits()), _mark())
    _run()
    _run()
    assert (_effective(), len(_audits()), _mark()) == before


def test_a_flag_the_user_turned_off_after_the_migration_is_kept(fresh):
    _store()
    _run()
    _store(**dict({f: 1 for f in _fields()}, links=0))       # 使用者之後在設定中心把「快速入口」關掉
    assert _effective()["links"] == 0
    audits = len(_audits())
    _run()                                             # 再升級／再啟動
    assert _effective()["links"] == 0, "標記存在後不可以再被打開"
    assert len(_audits()) == audits


def test_only_the_zero_fields_are_touched(fresh):
    """舊庫裡一部分已經是 1：只把 0 的改成 1，稽核只列這些欄位。"""
    _store(links=1, timeline=1)
    _run()
    assert set(_effective().values()) == {1}
    d = json.loads(_audits()[0][2])
    assert {c["field"] for c in d["changes"]} == set(_fields()) - {"links", "timeline"}


def test_already_on_is_only_marked_without_an_audit(fresh):
    _store(**{f: 1 for f in _fields()})
    _run()
    assert set(_effective().values()) == {1}
    assert _mark()["result"] == "already_on" and _audits() == []
    _store(links=0)                                     # 之後使用者關掉：保留
    _run()
    assert _effective()["links"] == 0 and _audits() == []


def test_failure_does_not_mark_and_never_raises_then_retries(fresh, monkeypatch):
    from helpers import settings_registry as SR
    _store()

    def boom(*a, **k):
        raise RuntimeError("publish failed")

    with monkeypatch.context() as m:                   # 不用 monkeypatch.undo()：它會連 client 夾具的環境設定一起還原（資料庫路徑跟著跑掉）
        m.setattr(SR, "publish", boom)
        _run()                                         # 不丟例外
    assert _mark() is None and set(_effective().values()) == {0}
    _run()                                             # 下次啟動再試成功
    assert set(_effective().values()) == {1} and _mark()["result"] == "enabled"


def test_other_keys_are_left_alone(fresh):
    """保固通知的靜默基準鍵（P0d）不在遷移範圍：遷移不清它。"""
    _sql("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
         ("onepipe.warranty_closed_baseline", json.dumps({"at": "2026-11-13"}), "2026-11-13T00:00:00"))
    try:
        _store()
        _run()
        assert _sql("SELECT value_json FROM system_settings WHERE key=?", ("onepipe.warranty_closed_baseline",))
    finally:
        _sql("DELETE FROM system_settings WHERE key=?", ("onepipe.warranty_closed_baseline",))


def test_migration_turns_entry_unify_on_for_a_legacy_database(fresh):
    """舊庫（entry_unify 存成 0）升級後，旗標讀出來是開（現場人員新增事項的守門跟著放行，行為見 daily_tasks 的 P4a 測試）。"""
    from helpers.onepipe_flags import flag_on
    _store()
    assert not flag_on("entry_unify")
    _run()
    assert flag_on("entry_unify")


def test_main_calls_the_migration_at_startup_after_init():
    src = MAIN_PY.read_text(encoding="utf-8")
    assert re.search(r"^_enable_onepipe_defaults_once\(\)", src, re.M), "main.py 沒有呼叫一次性遷移"
    assert src.index("init_unlock_passwords()\n_startup_step") < src.index("\n_enable_onepipe_defaults_once()"), "要在 init 之後"
    assert "_enable_onepipe_defaults_once," in src.split("from archive import")[0], "main.py 沒有 import"


def test_a_flag_deliberately_turned_off_in_the_ledger_is_kept_off_by_the_migration(fresh):
    """PM 裁示（2026-11-13）：設定變更明細對該欄位有過任何「新值＝0」的紀錄＝有人在設定中心明確關掉 ⇒ 遷移跳過不動；其餘 0 照開。
    （存值 0 本身分不出「舊預設」與「人為關閉」，所以看明細。）這個測試放在檔案最後：明細表只增不改不刪，這筆紀錄會留在同一個測試庫裡，
    它只影響「遷移要不要動 timeline」，不影響其他測試看的有效值。"""
    import db
    from helpers import config_ledger as L
    _store()                                                  # 舊庫：每個旗標都存成 0
    c = db.get_db()
    try:                                                      # 先前有人在設定中心把「時間軸」1→0（明細留著）
        L.record(c, "setting:%s" % GROUP, GROUP, [{"field": "timeline", "old": 1, "new": 0}], "管理員關閉時間軸",
                 {"username": "admin", "display_name": "管理員"})
        c.commit()
    finally:
        c.close()
    _run()
    eff = _effective()
    assert eff["timeline"] == 0, "明確關掉過的欄位遷移後仍是 0"
    assert all(v == 1 for k, v in eff.items() if k != "timeline"), "其他 0 照開"
    m = _mark()
    assert m["kept_off"] == ["timeline"] and "timeline" not in m["fields"] and m["result"] == "enabled"
    d = json.loads(_audits()[0][2])
    assert "timeline" not in {x["field"] for x in d["changes"]}, "稽核也不列被保留的欄位"
