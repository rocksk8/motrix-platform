# -*- coding: utf-8 -*-
"""需要外包工班（M04）的題：刪掉 modules/subcontract 時隨模組消失（PLAYBOOK §B-11，稽核 D M04-M1）。

（2026-09-26 自 tests/test_legal_audit_d_r1_r3_2026_09_26.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
稽核 AUDIT-D-R1-R3-legal（2026-09-26）的修正：法規金額捨入、並行修改、單據凍結、告知紀錄。

守住的規則：
D-1 補充保費「角以下 4 捨 5 入」（健保署）：後端 20,000～2,000,000 逐元與四捨五入一致；扣繳維持元以下捨去。
D-2 修改勞報單時「讀舊單 → 合併 → 寫回」在同一個寫交易裡：兩人同時修改，已記錄的「已告知」不可以消失。
S-3 告知紀錄的設定值讀不懂 ⇒ 拒絕寫入（409），原值不動；不可以當成空的整份覆寫。
S-5 已告知紀錄除了雜湊，也查得到當時的告知全文（公司改了文字之後仍查得到舊版）。
S-6 單據凍結的兩條路徑：修改舊單用快照（不是用版本號重查）；建立時不採用前端送來的快照（突變 M12、M16）。
"""
import copy
import json
import threading
from datetime import date
from fractions import Fraction

import pytest

from helpers import legal_params as lp
from helpers import privacy_notice as pn

FROZEN_TODAY = date(2026, 9, 25)


def _hdr(client, make_user, name="dfix_su"):
    u, p = make_user(username=name, role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def frozen_today(monkeypatch):
    monkeypatch.setattr(lp, "today", lambda: FROZEN_TODAY)


def _data(gross=30000, itype="50", date_="2026-10-01", **kw):
    d = {"contractorName": "測試承攬人", "incomeType": itype, "grossAmount": gross,
         "contractorNationality": "本國籍", "contractorHasUnionInsurance": False,
         "serviceContent": "測試", "slipDate": date_}
    d.update(kw)
    return d


def _v2027():
    v = copy.deepcopy(lp.DEFAULT_TAX_RULE_VERSIONS[0])
    v.update(version="2027", effectiveFrom="2027-01-01", sources=["測試資料"])
    v["minimum_wage"]["monthly"] = 30900
    v["nhi"]["thresholds"]["50"] = 30900
    return v


def _set_raw_setting(key, raw):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, '2026-01-01') "
                     "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (key, raw))
        conn.commit()
    finally:
        conn.close()


def _raw_setting(key):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ── D-1 捨入 ────────────────────────────────────────────────────────────────────

def _half_up_oracle(num, den):
    """整數的「四捨五入到元」（與 Decimal、與 round() 都無關的獨立算法）。"""
    return (2 * num + den) // (2 * den)


# ── D-2 並行修改 ────────────────────────────────────────────────────────────────


# ── S-6 單據凍結 ────────────────────────────────────────────────────────────────


# ── S-3 設定值損毀 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["{壞掉的 json", "[1, 2]"])
def test_corrupted_acks_are_refused_not_overwritten(client, make_user, raw):
    h = _hdr(client, make_user)
    cid = client.post("/api/contractors", json={"name": "承攬損毀"}, headers=h).json()["id"]
    _set_raw_setting(pn.ACKS_KEY, raw)
    r = client.post(f"/api/contractors/{cid}/privacy-notice/ack", headers=h)
    assert r.status_code == 409 and "損毀" in r.json()["detail"], r.text
    assert _raw_setting(pn.ACKS_KEY) == raw, "損毀的原始內容被蓋掉了"
    r = client.get(f"/api/contractors/{cid}/privacy-notice", headers=h)
    assert r.status_code == 409, "讀不懂不可以回報成「沒有紀錄」"


# ── S-5 告知全文 ────────────────────────────────────────────────────────────────

def test_the_acknowledged_text_can_be_looked_up_after_the_notice_changes(client, make_user):
    h = _hdr(client, make_user)
    assert client.put("/api/settings/company-profile", json={"privacy_notice": "第一版告知全文"},
                      headers=h).status_code == 200
    no = client.post("/api/payslips", json={"data": _data(privacyNoticeAcked=True)}, headers=h).json()["slip_no"]
    h1 = client.get("/api/payslips/" + no, headers=h).json()["data"]["privacyNotice"]["noticeHash"]
    assert client.put("/api/settings/company-profile", json={"privacy_notice": "第二版告知全文"},
                      headers=h).status_code == 200
    cid = client.post("/api/contractors", json={"name": "承攬全文"}, headers=h).json()["id"]
    h2 = client.post(f"/api/contractors/{cid}/privacy-notice/ack", headers=h).json()["ack"]["noticeHash"]
    assert h1 != h2
    r1 = client.get("/api/legal-params/privacy-notice/texts/" + h1, headers=h)
    r2 = client.get("/api/legal-params/privacy-notice/texts/" + h2, headers=h)
    assert (r1.status_code, r2.status_code) == (200, 200), (r1.text, r2.text)
    assert r1.json()["text"] == "第一版告知全文" and r2.json()["text"] == "第二版告知全文"
    assert client.get("/api/legal-params/privacy-notice/texts/0000000000000000", headers=h).status_code == 404
    assert client.get("/api/legal-params/privacy-notice/texts/..%2F..", headers=h).status_code == 404
    # 只增不改：同一版再記一次不改第一次存的時間
    first = json.loads(_raw_setting(pn.TEXTS_KEY))[h2]["firstAckAt"]
    cid2 = client.post("/api/contractors", json={"name": "承攬全文二"}, headers=h).json()["id"]
    client.post(f"/api/contractors/{cid2}/privacy-notice/ack", headers=h)
    assert json.loads(_raw_setting(pn.TEXTS_KEY))[h2]["firstAckAt"] == first
