# -*- coding: utf-8 -*-
"""第 53 班 P0 稽核（node-39）六個必修＋兩個建議的回歸題：RBN12～RBN17（規格 modules/recyclebin/SPEC.md）。
每一題都是稽核時用拋棄式測試重現過的缺口——原本的 P0 測試全綠，是覆蓋缺口，不是巧合。"""
import json
import logging
import os
import shutil
import subprocess

import pytest

import db
from core import paths, registry
from helpers import recycle_bin as RB
from helpers import uploads as UP
from modules.recyclebin import jobs, quarantine as Q, service as S
from modules.recyclebin.tests.test_recyclebin_p0_t53 import ET, SynAdapter, _abs, _audits, _delete, _doc, _q, env, who  # noqa: F401  (env 是 autouse fixture)


# ── RBN12 遮罩：JSON 字串、整個值、寬字典 ─────────────────────────────────────────────
def test_rbn12_json_string_columns_are_unpacked_and_masked():
    data_json = json.dumps({"contractorName": "王小明", "contractorIdNumber": "A123456789", "bankAccountNumber": "0123456789", "contractorPhone": "0900",
                            "nested": {"list": [{"email": "a@b.c", "note": "ok"}]}}, ensure_ascii=False)
    m = RB.mask_obj({"data_json": data_json, "slip_no": "PS-1"})
    inner = json.loads(m["data_json"])
    assert inner["contractorIdNumber"] == inner["bankAccountNumber"] == inner["contractorPhone"] == RB.MASK and inner["nested"]["list"][0]["email"] == RB.MASK
    assert inner["contractorName"] == "王小明" and inner["nested"]["list"][0]["note"] == "ok" and m["slip_no"] == "PS-1"
    assert "A123456789" not in json.dumps(m) and "0123456789" not in json.dumps(m)
    deep = json.dumps({"a": json.dumps({"b": json.dumps({"phone": "0911"})})})           # JSON 裡的 JSON 字串
    assert "0911" not in json.dumps(RB.mask_obj({"x": deep}))
    assert RB.mask_obj({"note": "{not json"}) == {"note": "{not json"}, "不是 JSON 的字串原樣保留"


def test_rbn12_a_container_under_a_sensitive_key_is_masked_as_a_whole_and_keys_are_wide():
    m = RB.mask_obj({"account": {"no": "123", "bank": "812"}, "payee": [{"n": "x"}], "bank": {"code": "812"}})
    assert m["account"] == RB.MASK and m["payee"] == RB.MASK and m["bank"] == {"code": "812"}, "敏感鍵底下整個值遮罩；銀行代碼是機構資訊"
    for k in ("account_no", "acct_no", "id_no", "idNo", "national_id", "nationalId", "birthday", "birth_date", "payee_account", "credit_card", "creditCardNo",
              "card_number", "telNo", "tel", "mobile", "Phone", "EMail", "passportImage", "signature_image", "salary"):
        assert RB.mask_obj({k: "v1"})[k] == RB.MASK, k
    for k in ("name", "qty", "label", "hotel", "identifier", "nodes", "status", "amount"):
        assert RB.mask_obj({k: "v1"})[k] == "v1", k
    assert RB.mask_obj({"p": "data:image/png;base64," + "A" * 80})["p"] == RB.MASK, "內嵌影像一律遮罩"
    assert RB.mask_obj({"phone": "", "id_number": None, "email": 0}) == {"phone": "", "id_number": None, "email": 0}, "空值不變"


def test_rbn12_detail_endpoint_masks_json_columns_even_without_an_adapter(client, who):
    su, ad, su_user = who
    snap = {"rows": {"payslips": [{"slip_no": "PS-9", "data_json": json.dumps({"contractorIdNumber": "Z999888777", "grossAmount": 1000})}]}, "files": [], "label": "x"}
    cn = db.get_db()
    cn.execute("INSERT INTO recycle_bin (token, entity_type, entity_id, deleted_at, purge_after, snapshot_json) VALUES (?,?,?,?,?,?)",
               ("1" * 32, "payslip", "PS-9", "2026-10-10T00:00:00", "2099-01-01", json.dumps(snap, ensure_ascii=False)))
    cn.commit()
    bid = cn.execute("SELECT id FROM recycle_bin WHERE token=?", ("1" * 32,)).fetchone()[0]
    cn.close()
    txt = json.dumps(client.get("/api/recycle-bin/%d" % bid, headers=su).json(), ensure_ascii=False)
    assert "Z999888777" not in txt and "1000" in txt


# ── RBN13 隔離目錄位置規則 ────────────────────────────────────────────────────────────
def test_rbn13_settings_reject_dangerous_locations(client, who, tmp_path):
    su, ad, su_user = who
    bad = [r"\\server\share\bin", "//server/share/bin", paths.INSTALL_ROOT, os.path.join(paths.INSTALL_ROOT, "docs"), os.path.dirname(paths.INSTALL_ROOT),
           os.path.splitdrive(paths.INSTALL_ROOT)[0] + os.sep if os.path.splitdrive(paths.INSTALL_ROOT)[0] else "/"]
    for env_name in ("SystemRoot", "ProgramFiles", "ProgramData"):
        if os.environ.get(env_name):
            bad.append(os.environ[env_name])
            bad.append(os.path.join(os.environ[env_name], "x"))
    for d in bad:
        r = client.put("/api/recycle-bin/settings", json={"dir": d}, headers=su)
        assert r.status_code == 422, (d, r.status_code, r.text)
        assert Q.root_dir() == Q.default_dir(), "被拒絕就不能留下任何設定"
    ok = str(tmp_path / "ok_bin")
    assert client.put("/api/recycle-bin/settings", json={"dir": ok}, headers=su).status_code == 200
    assert client.put("/api/recycle-bin/settings", json={"dir": ""}, headers=su).status_code == 200, "留空＝預設位置（樹內）"


def test_rbn13_location_problem_unit():
    assert Q.location_problem("relative") and Q.location_problem(r"\\host\s") and Q.location_problem("")
    assert Q.location_problem(os.path.join(paths.INSTALL_ROOT, "x")) and Q.location_problem(paths.INSTALL_ROOT)


# ── RBN14 連點／競態：還原與清除要鎖內重讀、條件式更新 ─────────────────────────────────
def test_rbn14_second_restore_is_refused_and_does_not_flip_the_status(client, who):
    su, ad, su_user = who
    _doc()
    res = _delete("D1", su_user)
    assert client.post("/api/recycle-bin/%d/restore" % res["bin_id"], headers=su).status_code == 200
    r2 = client.post("/api/recycle-bin/%d/restore" % res["bin_id"], headers=su)
    assert r2.status_code == 409
    row = _q("SELECT restore_status, restore_note FROM recycle_bin WHERE id=?", res["bin_id"])[0]
    assert row["restore_status"] == "restored", "第二次還原不可以把已還原翻成 restore_failed"
    assert len(_q("SELECT * FROM rbn_doc")) == 1
    cn = db.get_db()
    S._fail(cn, res["bin_id"], "遲到的失敗回報")                                   # 即使有人呼叫 _fail，條件式 UPDATE 也不會動已還原的列
    cn.close()
    assert _q("SELECT restore_status FROM recycle_bin WHERE id=?", res["bin_id"])[0]["restore_status"] == "restored"
    assert client.delete("/api/recycle-bin/%d?confirm=永久刪除" % res["bin_id"], headers=su).status_code == 409, "已還原的不能永久刪除"


def test_rbn14_restore_and_purge_hold_the_write_lock_and_recheck(monkeypatch, who):
    su, ad, su_user = who
    _doc()
    res = _delete("D1", su_user)
    cn = db.get_db()
    seen = []
    orig = S.begin_write
    monkeypatch.setattr(S, "begin_write", lambda c: seen.append("lock") or orig(c))
    S.restore(cn, res["bin_id"], su_user)
    with pytest.raises(RB.BinError):
        S.purge(cn, res["bin_id"])
    cn.close()
    assert seen == ["lock", "lock"], "restore／purge 都先拿寫鎖"


# ── RBN15 刪除失敗又搬不回：隔離資料夾與檔案不可以被刪掉 ──────────────────────────────────
def test_rbn15_failed_delete_with_stuck_files_keeps_the_quarantine_folder(monkeypatch, who):
    su, ad, su_user = who
    rels = _doc()

    class Boom(SynAdapter):
        def delete_in_tx(self, conn, entity_id):
            raise RuntimeError("資料庫寫入失敗")

    monkeypatch.setitem(registry._LEGACY_PROVIDERS, (RB.CAP_ADAPTER, ET), Boom)
    real_move = Q._move

    def flaky(src, dst):
        if os.path.normcase(os.path.realpath(dst)).startswith(os.path.normcase(os.path.realpath(UP.UPLOADS_ROOT))):
            raise OSError("檔案被防毒軟體鎖住")
        return real_move(src, dst)

    monkeypatch.setattr(Q, "_move", flaky)
    cn = db.get_db()
    with pytest.raises(RB.BinError, match="搬不回"):
        S.delete(cn, ET, "D1", su_user)
    cn.rollback()
    cn.close()
    tokens = [d for d in os.listdir(Q.root_dir()) if len(d) == 32]
    assert len(tokens) == 1, "隔離資料夾要留著"
    kept = [os.path.join(Q.root_dir(), tokens[0], "uploads", *r.split("/")) for r in rels]
    assert all(os.path.isfile(k) for k in kept), "附件不可以被銷毀"
    monkeypatch.setattr(Q, "_move", real_move)
    cn = db.get_db()
    os.utime(os.path.join(Q.root_dir(), tokens[0]), (1, 1))                       # 超過寬限時間
    assert S.reconcile(cn) == 1
    cn.close()
    assert all(os.path.isfile(_abs(r)) for r in rels), "每日工作 reconcile 把檔案搬回原路徑"


def test_rbn15_move_in_keeps_the_folder_when_the_undo_fails(monkeypatch, who):
    rels = _doc()
    token = "2" * 32
    real_move = Q._move
    calls = {"n": 0}

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("第二個檔搬不進去")
        if os.path.normcase(os.path.realpath(dst)).startswith(os.path.normcase(os.path.realpath(UP.UPLOADS_ROOT))):
            raise OSError("搬回也失敗")
        return real_move(src, dst)

    monkeypatch.setattr(Q, "_move", flaky)
    with pytest.raises(OSError):
        Q.move_in(token, [{"root": "uploads", "rel": r} for r in rels])
    first = os.path.join(Q.bin_dir(token), "uploads", *rels[0].split("/"))
    assert os.path.isfile(first), "搬回失敗的檔不可以被 rmtree 一起刪掉"


# ── RBN16 清除要驗證真的刪乾淨 ────────────────────────────────────────────────────────
def test_rbn16_purge_that_cannot_delete_the_files_stays_live_and_is_audited(monkeypatch, client, who):
    su, ad, su_user = who
    _doc()
    res = _delete("D1", su_user)
    monkeypatch.setattr(shutil, "rmtree", lambda *a, **k: None)                 # 模擬檔案被占用、刪不掉
    r = client.delete("/api/recycle-bin/%d?confirm=永久刪除" % res["bin_id"], headers=su)
    assert r.status_code == 409 and "刪不乾淨" in r.text, r.text
    row = _q("SELECT restore_status, snapshot_json, files_manifest_json FROM recycle_bin WHERE id=?", res["bin_id"])[0]
    assert row["restore_status"] == "in_bin" and row["snapshot_json"] != "{}" and json.loads(row["files_manifest_json"]), "快照與清單不可清掉"
    assert os.path.isdir(Q.bin_dir(res["token"])) and _audits("recyclebin.purge_failed")
    cn = db.get_db()
    cn.execute("UPDATE recycle_bin SET purge_after='2000-01-01' WHERE id=?", (res["bin_id"],))
    cn.commit()
    cn.close()
    out = jobs.run_daily()
    assert out["purged"] == 0 and out["failed"] == 1, "每日工作也不可以把刪不掉的標成已清除"
    assert _q("SELECT restore_status FROM recycle_bin WHERE id=?", res["bin_id"])[0]["restore_status"] == "in_bin"
    monkeypatch.undo()


# ── RBN17 .gitignore ─────────────────────────────────────────────────────────────────
def test_rbn17_quarantine_folder_is_git_ignored():
    root = paths.INSTALL_ROOT
    gi = open(os.path.join(root, ".gitignore"), encoding="utf-8").read().splitlines()
    assert "資源回收筒/" in [x.strip() for x in gi], ".gitignore 要有『資源回收筒/』（隔離檔含個資，git add -A 不可帶走）"
    if os.path.isdir(os.path.join(root, ".git")) or os.path.isfile(os.path.join(root, ".git")):
        p = subprocess.run(["git", "check-ignore", "-q", "資源回收筒/abc/uploads/x.pdf"], cwd=root, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert p.returncode == 0, "git 不認為它被忽略"
    assert Q.DIRNAME == "資源回收筒"


# ── 建議：adapter 工廠錯誤要記 log；刪除已核可要通知其他最高管理者 ────────────────────────────
def test_rbn12_broken_adapter_factory_is_logged_not_swallowed(monkeypatch, caplog):
    def broken():
        raise RuntimeError("factory boom")
    monkeypatch.setitem(registry._LEGACY_PROVIDERS, (RB.CAP_ADAPTER, "broken_type"), broken)
    with caplog.at_level(logging.ERROR):
        found = RB.adapters()
    assert "broken_type" not in found and ET in found
    assert any("broken_type" in r.getMessage() for r in caplog.records)


def test_delete_approved_notifies_the_other_superadmins(client, make_user, who):
    su, ad, su_user = who
    other, _p = make_user(username="rb_su2", role="superadmin")
    _doc("N1", status="已核可")
    r = client.post("/api/recycle-bin/delete-approved", json={"entity_type": ET, "entity_id": "N1", "confirm": True, "confirm_text": "N1"}, headers=su)
    assert r.status_code == 200, r.text
    got = _q("SELECT username FROM notifications WHERE type='recyclebin_delete_approved'")
    names = [g["username"] for g in got]
    assert other in names and su_user["username"] not in names, "通知其他最高管理者；操作者自己不通知"
