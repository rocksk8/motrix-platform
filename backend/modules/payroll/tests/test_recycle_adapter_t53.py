# -*- coding: utf-8 -*-
"""第 53 班 P1：勞報單進刪除暫存區（IP-RB1 adapter；規格 modules/recyclebin/SPEC.md、modules/payroll/SPEC.md）。
釘住：① 草稿勞報單（含派發連結）進暫存區、還原後本體與連結逐欄相等、`contractor_guess_id` 與 `contractor_id` 分開 ② 鎖定狀態一律不可刪（D1 不放寬）、
『刪除已核可』不開放 ③ 詳情（遮罩視圖）看不到銀行帳號等，還原用原文 ④ 還原衝突：單號被占／受領人不在 ⇒ 不覆蓋；推測受領人不在 ⇒ 清除並註記；
派發已不存在的連結略過 ⑤ 暫存區模組不在 ⇒ 照舊硬刪並明說。"""
import json

import pytest

import db
from helpers import recycle_bin as RB

_MAKE_USER_DEFAULT_ROLE = "superadmin"
SLIP = "LB-RB-001"


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def su(client, make_user):
    u, p = make_user(username="rbp_su", role="superadmin")
    return _login(client, u, p)


def _q(sql, *a):
    cn = db.get_db()
    try:
        return [dict(r) for r in cn.execute(sql, a).fetchall()]
    finally:
        cn.close()


def _x(sql, *a):
    cn = db.get_db()
    try:
        cur = cn.execute(sql, a)
        cn.commit()
        return cur.lastrowid
    finally:
        cn.close()


@pytest.fixture(autouse=True)
def seed(client):
    cn = db.get_db()
    cn.execute("DELETE FROM payslip_dispatch_links")
    cn.execute("DELETE FROM payslips")
    cn.execute("DELETE FROM recycle_bin")
    cn.commit()
    cn.close()


def _contractor(name="王小明"):
    return _x("INSERT INTO contractors (name, id_number, phone, bank_account_number, created_at) VALUES (?,?,?,?,?)", name, "A123456789", "0912345678", "012345678901",
              "2026-01-01T00:00:00")


def _slip(status="草稿", cid=None, gid=None, no=SLIP):
    d = {"slipNo": no, "bankAccountNumber": "012345678901", "calc": {"gross": 1000}}
    _x("INSERT INTO payslips (slip_no, contractor_id, contractor_name, status, data_json, created_by, created_at, updated_at, contractor_guess_id)"
       " VALUES (?,?,?,?,?,?,?,?,?)", no, cid, "王小明", status, json.dumps(d), "rbp_su", "2026-01-02T00:00:00", "2026-01-02T00:00:00", gid)
    _x("INSERT INTO payslip_dispatch_links (slip_no, dispatch_id, note, created_by, created_at) VALUES (?,?,?,?,?)", no, 901, "備註", "rbp_su", "2026-01-03T00:00:00")


def _row(no=SLIP):
    r = _q("SELECT * FROM payslips WHERE slip_no=?", no)
    return r[0] if r else None


def _links(no=SLIP):
    return _q("SELECT slip_no, dispatch_id, note, created_by, created_at FROM payslip_dispatch_links WHERE slip_no=?", no)


def _bin():
    return _q("SELECT * FROM recycle_bin WHERE entity_type='payslip' ORDER BY id DESC")


def _dispatch_exists(monkeypatch):
    from core import registry
    monkeypatch.setattr(registry, "single_provider", lambda cap, _o=registry.single_provider: (lambda conn, did: {"personnelIds": []}) if cap == "dispatch.brief" else _o(cap))


def test_draft_goes_to_bin_with_links_and_round_trips(client, su, monkeypatch):
    _dispatch_exists(monkeypatch)
    cid = _contractor()
    _slip(cid=cid, gid=None)
    before, links = _row(), _links()
    assert client.delete("/api/payslips/%s" % SLIP, headers=su).status_code == 204
    assert _row() is None and _links() == []
    b = _bin()
    assert len(b) == 1 and b[0]["entity_id"] == SLIP and b[0]["file_count"] == 0
    r = client.post("/api/recycle-bin/%d/restore" % b[0]["id"], headers=su)
    assert r.status_code == 200, r.text
    assert _row() == before and _links() == links


def test_locked_statuses_cannot_be_deleted_and_not_binned(client, su):
    for i, st in enumerate(("待審核", "已核准", "已匯出", "已簽回", "已付款", "已作廢")):
        no = "LB-L%d" % i
        _slip(st, no=no)
        r = client.delete("/api/payslips/%s" % no, headers=su)
        assert r.status_code == 400 and "須保留備查" in r.text, (st, r.text)
        assert _row(no) is not None and len(_links(no)) == 1
    assert _bin() == []


def test_delete_approved_entry_is_not_offered_for_payslips(client, su):
    _slip("已核准")
    imp = client.get("/api/recycle-bin/impact", params={"entity_type": "payslip", "entity_id": SLIP}, headers=su).json()
    assert imp["supported"] is False and "作廢" in imp["reason"]
    assert any(i["kind"] == "locked" and i["blocking"] for i in imp["impact"])
    r = client.post("/api/recycle-bin/delete-approved", json={"entity_type": "payslip", "entity_id": SLIP, "confirm": True, "confirm_text": SLIP}, headers=su)
    assert r.status_code == 409 and _row() is not None and _bin() == []


def test_detail_masks_sensitive_values_but_restore_keeps_original(client, su):
    _slip()
    assert client.delete("/api/payslips/%s" % SLIP, headers=su).status_code == 204
    bid = _bin()[0]["id"]
    d = client.get("/api/recycle-bin/%d" % bid, headers=su).json()
    text = json.dumps(d, ensure_ascii=False)
    assert "012345678901" not in text and RB.MASK in text
    assert client.post("/api/recycle-bin/%d/restore" % bid, headers=su).status_code == 200
    assert json.loads(_row()["data_json"])["bankAccountNumber"] == "012345678901"


def test_restore_conflict_and_missing_contractor(client, su):
    cid = _contractor()
    _slip(cid=cid)
    assert client.delete("/api/payslips/%s" % SLIP, headers=su).status_code == 204
    bid = _bin()[0]["id"]
    _x("INSERT INTO payslips (slip_no, status, data_json) VALUES (?,?,?)", SLIP, "草稿", "{}")                 # 同號新單
    r = client.post("/api/recycle-bin/%d/restore" % bid, headers=su)
    assert r.status_code == 409 and "已被占用" in r.text and _row()["data_json"] == "{}"
    _x("DELETE FROM payslips WHERE slip_no=?", SLIP)
    _x("DELETE FROM contractors WHERE id=?", cid)
    r = client.post("/api/recycle-bin/%d/restore" % bid, headers=su)
    assert r.status_code == 409 and "外包名冊" in r.text and _row() is None
    assert _bin()[0]["restore_status"] == "restore_failed"


def test_guess_is_cleared_when_missing_and_never_promoted(client, su):
    gid = _contractor("推測人")
    _slip(cid=None, gid=gid)
    assert client.delete("/api/payslips/%s" % SLIP, headers=su).status_code == 204
    _x("DELETE FROM contractors WHERE id=?", gid)
    r = client.post("/api/recycle-bin/%d/restore" % _bin()[0]["id"], headers=su)
    assert r.status_code == 200, r.text
    row = _row()
    assert row["contractor_guess_id"] is None and row["contractor_id"] is None
    assert any("推測" in n for n in r.json().get("notes", []))


def test_guess_kept_when_still_there(client, su):
    gid = _contractor("推測人")
    _slip(cid=None, gid=gid)
    assert client.delete("/api/payslips/%s" % SLIP, headers=su).status_code == 204
    assert client.post("/api/recycle-bin/%d/restore" % _bin()[0]["id"], headers=su).status_code == 200
    assert _row()["contractor_guess_id"] == gid and _row()["contractor_id"] is None


def test_links_to_vanished_dispatch_are_skipped(client, su, monkeypatch):
    _slip()
    assert client.delete("/api/payslips/%s" % SLIP, headers=su).status_code == 204
    from core import registry
    monkeypatch.setattr(registry, "single_provider", lambda cap, _o=registry.single_provider: (lambda conn, did: None) if cap == "dispatch.brief" else _o(cap))
    r = client.post("/api/recycle-bin/%d/restore" % _bin()[0]["id"], headers=su)
    assert r.status_code == 200 and _row() is not None and _links() == []
    assert any("派發連結" in n for n in r.json().get("notes", []))


def test_fallback_hard_delete_when_bin_absent(client, su, monkeypatch):
    _slip()
    monkeypatch.setattr(RB, "delete", lambda *a, **k: None)
    assert client.delete("/api/payslips/%s" % SLIP, headers=su).status_code == 204
    assert _row() is None and _links() == [] and _bin() == []
    labels = [a["target_label"] for a in _q("SELECT target_label FROM audit_log WHERE action='payslip.delete'")]
    assert labels and "暫存區未啟用" in labels[-1]


def test_adapter_registered():
    assert RB.adapters()["payslip"].label == "勞報單"
