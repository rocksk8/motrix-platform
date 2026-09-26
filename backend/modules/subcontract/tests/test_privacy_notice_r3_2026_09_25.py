# -*- coding: utf-8 -*-
"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_privacy_notice_r3_2026_09_25.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
R3 個資蒐集告知（個資法 §8 I；CUSTOMIZATION-SPEC §9.3；BENCHMARK §6.6、§7）。

守住的規則：
① 範本涵蓋 §8 I 六款；公司名稱代入；公司設定頁可以存自己的文字，空白 ⇒ 範本。
② 「已告知」由**伺服器**蓋時間與人員；前端送來的紀錄不採用；已記錄的不能被覆蓋或清除。
③ 承攬人員的紀錄存在設定鍵，重複記錄不改原紀錄，並寫稽核。
"""
import json

import pytest

from helpers import privacy_notice as pn


def _hdr(client, make_user, username="r3_root", role="superadmin"):
    u, p = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


# ── ① 告知文字 ──────────────────────────────────────────────────────────────────


# ── ② 勞報單的已告知紀錄 ────────────────────────────────────────────────────────

def _slip(**kw):
    d = {"contractorName": "受領人", "incomeType": "9A", "grossAmount": 10000, "serviceContent": "測試",
         "contractorNationality": "本國籍", "contractorHasUnionInsurance": False, "slipDate": "2026-09-25"}
    d.update(kw)
    return {"data": d}


# ── ③ 承攬人員 ──────────────────────────────────────────────────────────────────

def _contractor(client, h, name="承攬甲"):
    r = client.post("/api/contractors", json={"name": name}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_contractor_ack_is_recorded_once_and_audited(client, make_user):
    h = _hdr(client, make_user)
    cid = _contractor(client, h)
    assert client.get(f"/api/contractors/{cid}/privacy-notice", headers=h).json()["ack"] is None
    r1 = client.post(f"/api/contractors/{cid}/privacy-notice/ack", headers=h)
    assert r1.status_code == 200 and r1.json()["created"] is True, r1.text
    r2 = client.post(f"/api/contractors/{cid}/privacy-notice/ack", headers=h)
    assert r2.json()["created"] is False and r2.json()["ack"] == r1.json()["ack"]
    assert client.get(f"/api/contractors/{cid}/privacy-notice", headers=h).json()["ack"] == r1.json()["ack"]
    import db
    conn = db.get_db()
    try:
        n = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='contractor.privacy_notice_ack' "
                         "AND target_id=?", (str(cid),)).fetchone()[0]
    finally:
        conn.close()
    assert n == 1


def test_contractor_ack_for_unknown_person_is_404(client, make_user):
    h = _hdr(client, make_user)
    assert client.post("/api/contractors/999999/privacy-notice/ack", headers=h).status_code == 404
