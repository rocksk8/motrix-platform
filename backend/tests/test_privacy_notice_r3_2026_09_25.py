# -*- coding: utf-8 -*-
"""R3 個資蒐集告知（個資法 §8 I；CUSTOMIZATION-SPEC §9.3；BENCHMARK §6.6、§7）。

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

@pytest.mark.parametrize("must", [
    "蒐集者名稱", "蒐集目的", "個人資料類別", "利用期間", "地區", "對象", "方式",
    "個人資料保護法第 3 條", "不提供的影響",
])
def test_template_covers_the_items_of_article_8(must):
    assert must in pn.TEMPLATE


def test_template_takes_the_company_name():
    t = pn.template_for("測試股份有限公司")
    assert "測試股份有限公司" in t and pn.COMPANY_PLACEHOLDER not in t


def test_company_notice_round_trips_and_empty_falls_back_to_template(client, make_user):
    h = _hdr(client, make_user)
    assert client.put("/api/settings/company-profile", json={"name": "甲公司"}, headers=h).status_code == 200
    d = client.get("/api/legal-params/privacy-notice", headers=h).json()
    assert d["isTemplate"] is True and "甲公司" in d["text"]
    r = client.put("/api/settings/company-profile", json={"privacy_notice": "自訂告知文字"}, headers=h)
    assert r.status_code == 200, r.text
    assert client.get("/api/settings/company-profile", headers=h).json()["privacy_notice"] == "自訂告知文字"
    d = client.get("/api/legal-params/privacy-notice", headers=h).json()
    assert (d["text"], d["isTemplate"]) == ("自訂告知文字", False)
    assert d["hash"] == pn.notice_hash("自訂告知文字")


def test_notice_text_is_readable_by_any_logged_in_user(client, make_user):
    h = _hdr(client, make_user, "r3_viewer", role="viewer")
    assert client.get("/api/legal-params/privacy-notice", headers=h).status_code == 200


# ── ② 勞報單的已告知紀錄 ────────────────────────────────────────────────────────

def _slip(**kw):
    d = {"contractorName": "受領人", "incomeType": "9A", "grossAmount": 10000, "serviceContent": "測試",
         "contractorNationality": "本國籍", "contractorHasUnionInsurance": False, "slipDate": "2026-09-25"}
    d.update(kw)
    return {"data": d}


def test_ack_is_stamped_by_the_server(client, make_user):
    h = _hdr(client, make_user)
    forged = {"at": "2000-01-01T00:00:00", "by": "別人", "byUsername": "x", "noticeHash": "x"}
    r = client.post("/api/payslips", json=_slip(privacyNoticeAcked=True, privacyNotice=forged), headers=h)
    assert r.status_code == 201, r.text
    rec = client.get("/api/payslips/" + r.json()["slip_no"], headers=h).json()["data"]["privacyNotice"]
    assert rec["byUsername"] == "r3_root" and rec["at"].startswith("20") and rec["at"] != forged["at"]
    assert rec["noticeHash"] == pn.notice_hash(pn.current_notice())


def test_without_ack_nothing_is_recorded_and_forged_record_is_dropped(client, make_user):
    h = _hdr(client, make_user)
    forged = {"at": "2000-01-01T00:00:00", "by": "別人"}
    r = client.post("/api/payslips", json=_slip(privacyNotice=forged), headers=h)
    assert r.status_code == 201, r.text
    assert "privacyNotice" not in client.get("/api/payslips/" + r.json()["slip_no"], headers=h).json()["data"]


def test_recorded_ack_cannot_be_overwritten_or_cleared(client, make_user):
    h = _hdr(client, make_user)
    no = client.post("/api/payslips", json=_slip(privacyNoticeAcked=True), headers=h).json()["slip_no"]
    first = client.get("/api/payslips/" + no, headers=h).json()["data"]["privacyNotice"]
    # 前端不送紀錄（清除）
    r = client.put("/api/payslips/" + no, json=_slip(), headers=h)
    assert r.status_code == 200, r.text
    assert client.get("/api/payslips/" + no, headers=h).json()["data"]["privacyNotice"] == first, "被清掉了"
    # 告知文字改版後再勾一次＋送一筆偽造的：原紀錄（時間、人員、當時的文字雜湊）都不能變
    #   ⚠️ 不改告知文字的話，同一秒重蓋的新紀錄會跟原紀錄一模一樣 ⇒ 覆蓋了也看不出來（突變驗證抓到的假綠）
    assert client.put("/api/settings/company-profile", json={"privacy_notice": "第二版告知"}, headers=h).status_code == 200
    r = client.put("/api/payslips/" + no, json=_slip(privacyNoticeAcked=True,
                                                     privacyNotice={"at": "2000-01-01", "by": "x"}), headers=h)
    assert r.status_code == 200, r.text
    assert client.get("/api/payslips/" + no, headers=h).json()["data"]["privacyNotice"] == first


def test_ack_can_be_added_later_on_edit(client, make_user):
    h = _hdr(client, make_user)
    no = client.post("/api/payslips", json=_slip(), headers=h).json()["slip_no"]
    r = client.put("/api/payslips/" + no, json=_slip(privacyNoticeAcked=True), headers=h)
    assert r.status_code == 200 and r.json()["privacyNotice"]["byUsername"] == "r3_root", r.text


# ── ③ 承攬人員 ──────────────────────────────────────────────────────────────────

def _contractor(client, h, name="承攬甲"):
    r = client.post("/api/contractors", json={"name": name}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_merge_ack_keeps_the_existing_record():
    old = {"at": "2026-01-01T00:00:00", "by": "甲"}
    assert pn.merge_ack(old, True, {"username": "乙"}, "t") is old
    assert pn.merge_ack(None, False, {"username": "乙"}, "t") is None
    assert pn.merge_ack(None, True, {"username": "乙"}, "t")["byUsername"] == "乙"
