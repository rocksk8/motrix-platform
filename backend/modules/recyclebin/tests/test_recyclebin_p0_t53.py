# -*- coding: utf-8 -*-
"""第 53 班 P0：刪除暫存區（recyclebin）——以**合成 adapter**驗 RBN1～RBN11（規格 modules/recyclebin/SPEC.md）。
P0 沒有任何真實單據 adapter；合成單據 `rbn_doc`（含子表 `rbn_item`、附件在 uploads 下）只存在於測試。"""
import json
import os
import time
from datetime import datetime, timedelta

import pytest

import db
from core import registry
from helpers import recycle_bin as RB
from helpers import uploads as UP
from modules.recyclebin import jobs, quarantine as Q, service as S

ET = "rbn_doc"


class SynAdapter(RB.Adapter):
    entity_type = ET
    label = "合成單據"

    def can_delete(self, conn, entity_id, user):
        r = conn.execute("SELECT status FROM rbn_doc WHERE no=?", (entity_id,)).fetchone()
        if r is None:
            return False, "找不到單據"
        return (True, "") if r["status"] == "草稿" else (False, "只有草稿可以刪除")

    def can_delete_approved(self, conn, entity_id, user):
        r = conn.execute("SELECT status FROM rbn_doc WHERE no=?", (entity_id,)).fetchone()
        return (True, "") if r is not None and r["status"] != "已付款" else (False, "已付款的單據不可走此入口")

    def impact(self, conn, entity_id):
        return [{"kind": "signed_back", "label": "已回簽 1 份", "blocking": False}]

    def snapshot(self, conn, entity_id):
        d = conn.execute("SELECT * FROM rbn_doc WHERE no=?", (entity_id,)).fetchone()
        items = [dict(r) for r in conn.execute("SELECT * FROM rbn_item WHERE doc_no=?", (entity_id,)).fetchall()]
        files = [{"root": "uploads", "rel": f} for f in json.loads(d["files_json"] or "[]")]
        return {"rows": {"rbn_doc": [dict(d)], "rbn_item": items}, "files": files, "label": "單據 " + entity_id, "meta": {}}

    def delete_in_tx(self, conn, entity_id):
        conn.execute("DELETE FROM rbn_item WHERE doc_no=?", (entity_id,))
        conn.execute("DELETE FROM rbn_doc WHERE no=?", (entity_id,))

    def restore_in_tx(self, conn, snap, ctx):
        d = snap["rows"]["rbn_doc"][0]
        if conn.execute("SELECT 1 FROM rbn_doc WHERE no=?", (d["no"],)).fetchone():
            raise RB.BinError("conflict: 單號 %s 已被占用" % d["no"])
        files = [ctx.file_path("uploads", f) for f in json.loads(d["files_json"] or "[]")]
        conn.execute("INSERT INTO rbn_doc (no, status, owner, bank_account, files_json) VALUES (?,?,?,?,?)",
                     (d["no"], d["status"], d["owner"], d["bank_account"], json.dumps(files)))
        for it in snap["rows"]["rbn_item"]:
            conn.execute("INSERT INTO rbn_item (doc_no, name) VALUES (?,?)", (it["doc_no"], it["name"]))
        return {"entity_id": d["no"], "renumbered": False, "notes": []}


@pytest.fixture(autouse=True)
def env(client, monkeypatch):
    """合成單據表＋adapter 登記；隔離區換到暫存（default_dir 隨 UPLOADS_ROOT 走，不寫真的安裝目錄）。"""
    cn = db.get_db()
    cn.executescript("""DROP TABLE IF EXISTS rbn_doc; DROP TABLE IF EXISTS rbn_item;
        CREATE TABLE rbn_doc (no TEXT PRIMARY KEY, status TEXT, owner TEXT, bank_account TEXT, files_json TEXT DEFAULT '[]');
        CREATE TABLE rbn_item (id INTEGER PRIMARY KEY AUTOINCREMENT, doc_no TEXT, name TEXT);""")
    cn.commit()
    cn.close()
    monkeypatch.setitem(registry._LEGACY_PROVIDERS, (RB.CAP_ADAPTER, ET), SynAdapter)
    yield
    cn = db.get_db()
    cn.executescript("DROP TABLE IF EXISTS rbn_doc; DROP TABLE IF EXISTS rbn_item; DELETE FROM recycle_bin;")
    cn.commit()
    cn.close()


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def who(client, make_user):
    su, sp = make_user(username="rb_su", role="superadmin")
    ad, ap = make_user(username="rb_admin", role="admin")
    return _login(client, su, sp), _login(client, ad, ap), {"username": su, "display_name": su, "role": "superadmin"}


def _doc(no="D1", status="草稿", nfiles=2):
    rels = []
    for i in range(nfiles):
        rel = "rbn/%s/f%d.txt" % (no, i)
        p = os.path.join(UP.UPLOADS_ROOT, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("內容 %s %d" % (no, i))
        rels.append(rel)
    cn = db.get_db()
    cn.execute("INSERT INTO rbn_doc (no, status, owner, bank_account, files_json) VALUES (?,?,?,?,?)", (no, status, "王小明", "012345678901", json.dumps(rels)))
    cn.execute("INSERT INTO rbn_item (doc_no, name) VALUES (?, '品項A'), (?, '品項B')", (no, no))
    cn.commit()
    cn.close()
    return rels


def _abs(rel):
    return os.path.join(UP.UPLOADS_ROOT, *rel.split("/"))


def _delete(no, user, approved=False):
    cn = db.get_db()
    try:
        res = S.delete(cn, ET, no, user, "測試", approved)
        cn.commit()
        return res
    finally:
        cn.close()


def _q(sql, *a):
    cn = db.get_db()
    try:
        return [dict(r) for r in cn.execute(sql, a).fetchall()]
    finally:
        cn.close()


def _audits(action):
    return _q("SELECT * FROM audit_log WHERE action=?", action)


# ── RBN1 ────────────────────────────────────────────────────────────────────
def test_rbn1_every_endpoint_is_superadmin_only(client, who):
    su, ad, _u = who
    _doc()
    res = _delete("D1", {"username": "x", "role": "admin"})
    calls = [("get", "/api/recycle-bin"), ("get", "/api/recycle-bin/status"), ("get", "/api/recycle-bin/impact?entity_type=%s&entity_id=D1" % ET),
             ("get", "/api/recycle-bin/%d" % res["bin_id"]), ("post", "/api/recycle-bin/%d/restore" % res["bin_id"]),
             ("delete", "/api/recycle-bin/%d?confirm=永久刪除" % res["bin_id"]),
             ("post", "/api/recycle-bin/delete-approved"), ("put", "/api/recycle-bin/settings")]
    for m, url in calls:
        kw = {"json": {}} if m in ("post", "put") else {}
        assert getattr(client, m)(url, headers=ad, **kw).status_code == 403, (m, url)
        assert getattr(client, m)(url, **kw).status_code in (401, 403), (m, url)
    assert client.get("/api/recycle-bin", headers=su).status_code == 200
    import json as _j
    mod = _j.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "module.json"), encoding="utf-8"))
    assert mod["pages"][0]["menu"]["perm"] == ["superadmin"]


# ── RBN2 / RBN3 / RBN4 / RBN9 ───────────────────────────────────────────────
def test_rbn2_delete_moves_rows_and_files_and_sets_thirty_days(who):
    rels = _doc()
    res = _delete("D1", {"username": "u1", "display_name": "U1", "role": "admin"})
    assert not _q("SELECT * FROM rbn_doc") and not _q("SELECT * FROM rbn_item"), "資料列刪除"
    for rel in rels:
        assert not os.path.exists(_abs(rel)), "原路徑不再有檔（搬、不是複製）"
        assert os.path.isfile(os.path.join(Q.bin_dir(res["token"]), "uploads", *rel.split("/")))
    row = _q("SELECT * FROM recycle_bin")[0]
    snap = json.loads(row["snapshot_json"])
    assert snap["rows"]["rbn_doc"][0]["bank_account"] == "012345678901" and len(snap["rows"]["rbn_item"]) == 2
    assert row["file_count"] == 2 and row["via"] == "normal" and row["deleted_by"] == "u1"
    assert row["purge_after"] == (datetime.now() + timedelta(days=30)).date().isoformat()
    assert RB.RETENTION_DAYS == 30


def test_rbn3_refusal_changes_nothing_and_approved_needs_superadmin(who):
    su, ad, su_user = who
    rels = _doc("D2", status="已核可")
    with pytest.raises(RB.BinError, match="只有草稿"):
        _delete("D2", {"username": "u1", "role": "admin"})
    assert _q("SELECT * FROM rbn_doc") and all(os.path.exists(_abs(r)) for r in rels) and not _q("SELECT * FROM recycle_bin")
    with pytest.raises(RB.BinError, match="只有最高管理者"):
        _delete("D2", {"username": "u1", "role": "admin"}, approved=True)
    res = _delete("D2", su_user, approved=True)
    row = _q("SELECT via, impact_json FROM recycle_bin WHERE id=?", res["bin_id"])[0]
    assert row["via"] == "approved" and json.loads(row["impact_json"])[0]["kind"] == "signed_back"
    _doc("D3", status="已付款")
    with pytest.raises(RB.BinError, match="已付款"):
        _delete("D3", su_user, approved=True)


def test_rbn4_absent_module_or_adapter_is_explicit(monkeypatch, who, client):
    monkeypatch.setattr(registry, "single_provider", lambda cap: None)
    cn = db.get_db()
    assert RB.delete(cn, ET, "D1", {"role": "admin"}) is None and RB.available() is False, "模組不在 ⇒ None（呼叫端照舊硬刪並明說）"
    cn.close()
    monkeypatch.undo()
    cn = db.get_db()
    with pytest.raises(RB.BinError, match="adapter"):
        S.delete(cn, "no_such_type", "X", {"role": "admin"})
    cn.close()


def test_rbn9_oversized_snapshot_is_refused_and_nothing_is_touched(monkeypatch, who):
    rels = _doc()
    monkeypatch.setattr(RB, "MAX_SNAPSHOT_BYTES", 200)
    with pytest.raises(RB.BinError, match="too_large"):
        _delete("D1", {"username": "u1", "role": "sales"})        # 一般使用者上限 5 MB（管理員較大，見 hardening 的 rbn9 題）
    assert _q("SELECT * FROM rbn_doc") and all(os.path.exists(_abs(r)) for r in rels) and not _q("SELECT * FROM recycle_bin")


# ── RBN5 / RBN7 ─────────────────────────────────────────────────────────────
def test_rbn5_restore_roundtrip_and_conflict_keeps_everything_in_the_bin(client, who):
    su, ad, su_user = who
    rels = _doc()
    res = _delete("D1", su_user)
    r = client.post("/api/recycle-bin/%d/restore" % res["bin_id"], headers=su)
    assert r.status_code == 200, r.text
    assert _q("SELECT status FROM rbn_doc")[0]["status"] == "草稿" and len(_q("SELECT * FROM rbn_item")) == 2
    assert all(open(_abs(x), encoding="utf-8").read().startswith("內容") for x in rels), "附件搬回原路徑"
    assert _q("SELECT restore_status, restored_by FROM recycle_bin")[0] == {"restore_status": "restored", "restored_by": su_user["username"]}
    assert _audits("recyclebin.restore")
    # 再刪一次、單號被占用 ⇒ 衝突：留在暫存區、附件回到隔離區
    res2 = _delete("D1", su_user)
    _doc("D1", nfiles=0)                                            # 占用單號
    r = client.post("/api/recycle-bin/%d/restore" % res2["bin_id"], headers=su)
    assert r.status_code == 409 and "已被占用" in r.text, r.text
    row = _q("SELECT restore_status, restore_note FROM recycle_bin WHERE id=?", res2["bin_id"])[0]
    assert row["restore_status"] == "restore_failed" and "已被占用" in row["restore_note"]
    assert all(os.path.isfile(os.path.join(Q.bin_dir(res2["token"]), "uploads", *x.split("/"))) for x in rels), "附件仍在隔離區"
    assert not any(os.path.exists(_abs(x)) for x in rels)
    assert _audits("recyclebin.restore_failed")
    cn = db.get_db()
    cn.execute("DELETE FROM rbn_doc WHERE no='D1'")                  # 排除衝突後可再還原
    cn.commit()
    cn.close()
    assert client.post("/api/recycle-bin/%d/restore" % res2["bin_id"], headers=su).status_code == 200


def test_rbn5_restore_renames_files_when_the_original_path_is_taken(client, who):
    su, ad, su_user = who
    rels = _doc(nfiles=1)
    res = _delete("D1", su_user)
    os.makedirs(os.path.dirname(_abs(rels[0])), exist_ok=True)
    open(_abs(rels[0]), "w", encoding="utf-8").write("別人的新檔")        # 原路徑被別的檔占用
    assert client.post("/api/recycle-bin/%d/restore" % res["bin_id"], headers=su).status_code == 200
    assert open(_abs(rels[0]), encoding="utf-8").read() == "別人的新檔", "不覆蓋既有檔"
    newp = json.loads(_q("SELECT files_json FROM rbn_doc")[0]["files_json"])[0]
    assert newp != rels[0] and "還原" in newp and open(_abs(newp), encoding="utf-8").read().startswith("內容"), "adapter 拿到實際路徑"


def test_rbn7_list_and_detail_mask_sensitive_values_but_restore_uses_the_original(client, who):
    su, ad, su_user = who
    _doc()
    res = _delete("D1", su_user)
    d = client.get("/api/recycle-bin/%d" % res["bin_id"], headers=su).json()
    txt = json.dumps(d, ensure_ascii=False)
    assert "012345678901" not in txt and RB.MASK in txt and "王小明" in txt, "帳號遮罩、非敏感欄位照顯示"
    lst = client.get("/api/recycle-bin", headers=su).json()
    assert "012345678901" not in json.dumps(lst, ensure_ascii=False) and lst["items"][0]["label"] == "單據 D1" and lst["types"][ET] == "合成單據"
    assert client.post("/api/recycle-bin/%d/restore" % res["bin_id"], headers=su).status_code == 200
    assert _q("SELECT bank_account FROM rbn_doc")[0]["bank_account"] == "012345678901"


def test_rbn7_default_mask_rules():
    m = RB.mask_obj({"bankAccountNumber": "123", "id_number": "A1", "phone": "09", "email": "a@b", "address": "x", "passbookImage": "data:..", "name": "王", "qty": 3,
                     "nested": [{"Account_Number": "9", "note": "ok"}], "empty_phone": None, "phoneX": ""})
    assert m["bankAccountNumber"] == m["id_number"] == m["phone"] == m["email"] == m["address"] == m["passbookImage"] == RB.MASK
    assert m["name"] == "王" and m["qty"] == 3 and m["nested"][0]["Account_Number"] == RB.MASK and m["nested"][0]["note"] == "ok"
    assert m["empty_phone"] is None and m["phoneX"] == ""


# ── RBN6 / RBN8 ─────────────────────────────────────────────────────────────
def test_rbn6_daily_job_purges_only_due_items_with_audit_and_notice(client, who):
    su, ad, su_user = who
    _doc("D1")
    _doc("D2")
    r1, r2 = _delete("D1", su_user), _delete("D2", su_user)
    cn = db.get_db()
    cn.execute("UPDATE recycle_bin SET purge_after=? WHERE id=?", ((datetime.now() - timedelta(days=1)).date().isoformat(), r1["bin_id"]))
    cn.commit()
    cn.close()
    out = jobs.run_daily()
    assert out["purged"] == 1 and out["failed"] == 0
    a, b = _q("SELECT * FROM recycle_bin WHERE id=?", r1["bin_id"])[0], _q("SELECT * FROM recycle_bin WHERE id=?", r2["bin_id"])[0]
    assert a["restore_status"] == "purged" and a["snapshot_json"] == "{}" and a["purged_by"] == "system" and not os.path.exists(Q.bin_dir(r1["token"]))
    assert b["restore_status"] == "in_bin" and os.path.isdir(Q.bin_dir(r2["token"])), "未到期的不碰"
    assert len(_audits("recyclebin.purge_auto")) == 1
    assert _q("SELECT * FROM notifications WHERE type='recyclebin_daily' AND username=?", su_user["username"])
    assert jobs.run_daily()["purged"] == 0, "冪等"
    assert client.post("/api/recycle-bin/%d/restore" % r1["bin_id"], headers=su).status_code == 409, "已清除的不能還原"


def test_rbn6_tick_runs_once_per_day_after_the_run_hour(monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "run_daily", lambda now=None: calls.append(1))
    assert jobs.tick(datetime(2026, 10, 12, 2, 0)) is False, "凌晨 3 點前不跑"
    assert jobs.tick(datetime(2026, 10, 12, 4, 0)) is True and jobs.tick(datetime(2026, 10, 12, 9, 0)) is False and jobs.tick(datetime(2026, 10, 13, 4, 0)) is True
    assert len(calls) == 2


def test_rbn8_rolled_back_delete_is_reconciled_by_moving_files_back(monkeypatch, who, client):
    rels = _doc()
    cn = db.get_db()
    res = S.delete(cn, ET, "D1", {"username": "u1", "role": "admin"})     # 還沒 commit
    cn.rollback()                                                         # 呼叫端的交易回滾
    cn.close()
    assert _q("SELECT * FROM rbn_doc") and not _q("SELECT * FROM recycle_bin"), "資料列回來了、暫存區沒有列"
    assert not any(os.path.exists(_abs(r)) for r in rels) and os.path.isdir(Q.bin_dir(res["token"])), "檔案卻在隔離區"
    cn = db.get_db()
    assert S.reconcile(cn) == 0, "寬限時間內不動（交易可能還在進行）"
    old = time.time() - 7200
    os.utime(Q.bin_dir(res["token"]), (old, old))
    assert S.reconcile(cn) == 1
    cn.close()
    assert all(os.path.exists(_abs(r)) for r in rels) and not os.path.exists(Q.bin_dir(res["token"])), "搬回原路徑"


# ── RBN10 / RBN11 ───────────────────────────────────────────────────────────
def test_rbn10_manual_purge_needs_confirmation_and_is_audited(client, who):
    su, ad, su_user = who
    _doc()
    res = _delete("D1", su_user)
    url = "/api/recycle-bin/%d" % res["bin_id"]
    assert client.delete(url, headers=su).status_code == 422 and client.delete(url + "?confirm=ok", headers=su).status_code == 422
    assert os.path.isdir(Q.bin_dir(res["token"]))
    assert client.delete(url + "?confirm=永久刪除", headers=su).status_code == 200
    assert not os.path.exists(Q.bin_dir(res["token"])) and _q("SELECT restore_status, snapshot_json FROM recycle_bin")[0] == {"restore_status": "purged", "snapshot_json": "{}"}
    assert _audits("recyclebin.purge_manual")
    assert client.delete(url + "?confirm=永久刪除", headers=su).status_code == 409


def test_delete_approved_endpoint_needs_double_confirmation(client, who):
    su, ad, su_user = who
    _doc("D9", status="已核可")
    body = {"entity_type": ET, "entity_id": "D9"}
    assert client.post("/api/recycle-bin/delete-approved", json=body, headers=su).status_code == 422
    assert client.post("/api/recycle-bin/delete-approved", json=dict(body, confirm=True, confirm_text="D8"), headers=su).status_code == 422
    assert client.post("/api/recycle-bin/delete-approved", json=dict(body, confirm="true", confirm_text="D9"), headers=su).status_code == 422, "旗標只收真布林"
    assert client.post("/api/recycle-bin/delete-approved", json=dict(entity_type="nope", entity_id="D9", confirm=True, confirm_text="D9"), headers=su).status_code == 404
    imp = client.get("/api/recycle-bin/impact?entity_type=%s&entity_id=D9" % ET, headers=su).json()
    assert imp["supported"] is True and imp["impact"][0]["kind"] == "signed_back"
    r = client.post("/api/recycle-bin/delete-approved", json=dict(body, confirm=True, confirm_text="D9", reason="客戶撤單"), headers=su)
    assert r.status_code == 200, r.text
    assert not _q("SELECT * FROM rbn_doc") and _q("SELECT via FROM recycle_bin")[0]["via"] == "approved" and _audits("recyclebin.delete_approved")


def test_rbn11_settings_dir_rules(client, who, tmp_path):
    su, ad, su_user = who
    put = lambda d: client.put("/api/recycle-bin/settings", json={"dir": d}, headers=su)               # noqa: E731
    assert put("relative/dir").status_code == 422
    assert put(os.path.join(UP.UPLOADS_ROOT, "x")).status_code == 422, "不可在 uploads 底下"
    assert put(str(tmp_path / "no_parent" / "bin")).status_code == 422
    target = str(tmp_path / "outside_bin")
    assert put(target).status_code == 200 and Q.root_dir() == os.path.abspath(target) and os.path.isdir(target)
    _doc()
    res = _delete("D1", su_user)
    assert os.path.isdir(os.path.join(target, res["token"])), "新目錄生效"
    assert put("").status_code == 409, "暫存區有項目時不准改"
    assert _audits("recyclebin.settings")
    client.delete("/api/recycle-bin/%d?confirm=永久刪除" % res["bin_id"], headers=su)
    assert put("").status_code == 200 and Q.root_dir() == Q.default_dir()


def test_rbn11_only_quarantine_py_touches_files():
    import ast
    import pathlib
    base = pathlib.Path(__file__).resolve().parents[1]
    bad = []
    for f in base.glob("*.py"):
        if f.name == "quarantine.py":
            continue
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Attribute) and n.attr in ("remove", "unlink", "rmtree", "replace", "rename", "move", "copy2") and isinstance(n.value, ast.Name) and n.value.id in ("os", "shutil"):
                bad.append("%s:%d" % (f.name, n.lineno))
    assert not bad, "本模組只有 quarantine.py 可以動檔案：%s" % bad


def test_status_endpoint_and_pagination(client, who):
    su, ad, su_user = who
    for i in range(3):
        _doc("S%d" % i)
        _delete("S%d" % i, su_user)
    st = client.get("/api/recycle-bin/status", headers=su).json()
    assert st["counts"]["in_bin"] == 3 and st["retentionDays"] == 30 and st["fileCount"] == 6 and st["usedBytes"] > 0 and ET in st["adapters"]
    lst = client.get("/api/recycle-bin?size=2&page=2", headers=su).json()
    assert lst["total"] == 3 and len(lst["items"]) == 1
    assert client.get("/api/recycle-bin?q=S1", headers=su).json()["total"] == 1
    assert client.get("/api/recycle-bin/99999", headers=su).status_code == 404
