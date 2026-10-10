# -*- coding: utf-8 -*-
"""第 53 班獨立稽核（node-39，b7280c979）回饋的修正 R5：
M1 連帶刪除中途失敗，已搬進隔離區的子單據附件要搬回；S-a 刪除已核可必填原因；S-b 精確 30 天；S-c 稽核與操作同一交易（寫不進去 ⇒ 整筆失敗）。"""
import json
import os
from datetime import datetime, timedelta

import pytest

import db
from core import registry
from helpers import recycle_bin as RB
from modules.recyclebin import quarantine as Q, service as S
from modules.recyclebin.tests.test_recyclebin_p0_t53 import ET, SynAdapter, _abs, _delete, _doc, _q, env, who  # noqa: F401  (env 是 autouse fixture)

PET = "rbn_parent"


class ParentAdapter(SynAdapter):
    """父單據：連帶刪除子單據 C1（ET 類型）；快照階段可被測試指定失敗。"""
    entity_type = PET
    fail = True

    def can_delete(self, conn, entity_id, user):
        return True, ""

    def cascade_children(self, conn, entity_id):
        return [(ET, "C1")]

    def snapshot(self, conn, entity_id):
        if ParentAdapter.fail:
            raise RB.BinError("too_large: 測試用：父單據快照失敗")
        return {"rows": {}, "files": [], "label": "父 " + entity_id, "meta": {}}

    def delete_in_tx(self, conn, entity_id):
        pass


def _quarantine_tokens():
    root = Q.root_dir()
    return [n for n in os.listdir(root)] if os.path.isdir(root) else []


def test_m1_cascade_failure_moves_the_children_files_back(monkeypatch, who):
    rels = _doc("C1")
    monkeypatch.setitem(registry._LEGACY_PROVIDERS, (RB.CAP_ADAPTER, PET), ParentAdapter)
    ParentAdapter.fail = True
    cn = db.get_db()
    try:
        with pytest.raises(RB.BinError):
            S.delete(cn, PET, "P1", {"username": "u1", "role": "admin"}, "測試")
        cn.rollback()                                         # 呼叫端的 rollback
    finally:
        cn.close()
    for rel in rels:
        assert os.path.isfile(_abs(rel)), "子單據附件要回到原路徑：" + rel
    assert _quarantine_tokens() == [], "隔離區不留空資料夾或殘檔"
    assert _q("SELECT COUNT(*) n FROM recycle_bin")[0]["n"] == 0 and _q("SELECT COUNT(*) n FROM rbn_doc")[0]["n"] == 1


def test_m1_caller_can_undo_the_moves_after_delete_returned(who):
    rels = _doc("D1")
    cn = db.get_db()
    try:
        res = S.delete(cn, ET, "D1", {"username": "u1", "role": "admin"}, "測試")
        assert all(not os.path.exists(_abs(r)) for r in rels), "delete() 回來時附件已在隔離區"
        cn.rollback()                                         # 呼叫端後續失敗 ⇒ rollback
        res["rollback_files"]()
    finally:
        cn.close()
    assert all(os.path.isfile(_abs(r)) for r in rels) and _quarantine_tokens() == []


def test_a_delete_approved_requires_a_reason(client, who):
    su, ad, _u = who
    _doc("A1", status="已核准")
    base = {"entity_type": ET, "entity_id": "A1", "confirm": True, "confirm_text": "A1"}
    assert client.post("/api/recycle-bin/delete-approved", json=base, headers=su).status_code == 422
    assert client.post("/api/recycle-bin/delete-approved", json=dict(base, reason="   "), headers=su).status_code == 422
    assert _q("SELECT COUNT(*) n FROM rbn_doc")[0]["n"] == 1, "沒填原因就什麼都不動"
    r = client.post("/api/recycle-bin/delete-approved", json=dict(base, reason="客戶撤單"), headers=su)
    assert r.status_code == 200, r.text
    assert _q("SELECT reason FROM recycle_bin")[0]["reason"] == "客戶撤單"


def test_b_purge_after_is_exactly_thirty_days_and_due_uses_the_clock(who):
    _doc("B1", nfiles=0)
    res = _delete("B1", {"username": "u1", "role": "admin"})
    row = _q("SELECT deleted_at, purge_after FROM recycle_bin WHERE id=?", res["bin_id"])[0]
    delta = datetime.fromisoformat(row["purge_after"]) - datetime.fromisoformat(row["deleted_at"])
    assert abs(delta - timedelta(days=30)) < timedelta(seconds=2), delta
    cn = db.get_db()
    try:
        now = datetime.now()
        for after, due in ((now + timedelta(hours=1), False), (now - timedelta(seconds=1), True)):
            cn.execute("UPDATE recycle_bin SET purge_after=? WHERE id=?", (after.isoformat(timespec="seconds"), res["bin_id"]))
            cn.commit()
            assert (res["bin_id"] in S.due_ids(cn)) is due, after
        cn.execute("UPDATE recycle_bin SET purge_after=? WHERE id=?", (now.date().isoformat(), res["bin_id"]))      # 舊資料：只有日期 ⇒ 當天 00:00 起視為到期
        cn.commit()
        assert res["bin_id"] in S.due_ids(cn)
    finally:
        cn.close()


def test_c_delete_approved_audit_failure_rolls_everything_back(monkeypatch, client, who):
    su, ad, _u = who
    rels = _doc("C9", status="已核准")

    def boom(*a, **k):
        raise RuntimeError("audit down")
    monkeypatch.setattr(S, "audit_tx", boom)
    try:
        r = client.post("/api/recycle-bin/delete-approved", json={"entity_type": ET, "entity_id": "C9", "confirm": True, "confirm_text": "C9", "reason": "測試"}, headers=su)
        assert r.status_code >= 400
    except RuntimeError:
        pass                                                  # TestClient 把伺服器例外丟出來也算失敗
    assert _q("SELECT COUNT(*) n FROM rbn_doc")[0]["n"] == 1 and _q("SELECT COUNT(*) n FROM recycle_bin")[0]["n"] == 0
    assert all(os.path.isfile(_abs(r)) for r in rels), "稽核寫不進去 ⇒ 附件搬回原處"
    assert _quarantine_tokens() == []


def test_c_purge_audit_failure_deletes_nothing(who):
    _doc("C8", nfiles=1)
    res = _delete("C8", {"username": "u1", "role": "admin"})

    def boom(conn, x):
        raise RuntimeError("audit down")
    cn = db.get_db()
    try:
        with pytest.raises(RB.BinError):
            S.purge(cn, res["bin_id"], by="su", audit=boom)
    finally:
        cn.close()
    assert os.path.isdir(Q.bin_dir(res["token"])), "稽核失敗 ⇒ 隔離檔還在"
    assert _q("SELECT restore_status FROM recycle_bin WHERE id=?", res["bin_id"])[0]["restore_status"] == "in_bin"


def test_c_restore_audit_failure_keeps_the_item_in_the_bin(who):
    _doc("C7", nfiles=1)
    res = _delete("C7", {"username": "u1", "role": "admin"})

    def boom(conn, x):
        raise RuntimeError("audit down")
    cn = db.get_db()
    try:
        with pytest.raises(RB.BinError):
            S.restore(cn, res["bin_id"], {"username": "su", "role": "superadmin"}, audit=boom)
    finally:
        cn.close()
    assert _q("SELECT COUNT(*) n FROM rbn_doc")[0]["n"] == 0, "還原被撤銷"
    assert _q("SELECT restore_status FROM recycle_bin WHERE id=?", res["bin_id"])[0]["restore_status"] != "restored"


def test_c_successful_flows_write_their_audit_in_the_same_transaction(client, who):
    su, ad, _u = who
    _doc("C6", nfiles=1)
    res = _delete("C6", {"username": "u1", "role": "admin"})
    assert client.post("/api/recycle-bin/%d/restore" % res["bin_id"], headers=su).status_code == 200
    assert len(_q("SELECT * FROM audit_log WHERE action='recyclebin.restore'")) == 1
    res2 = _delete("C6", {"username": "u1", "role": "admin"})
    assert client.delete("/api/recycle-bin/%d?confirm=永久刪除" % res2["bin_id"], headers=su).status_code == 200
    assert len(_q("SELECT * FROM audit_log WHERE action='recyclebin.purge_manual'")) == 1
