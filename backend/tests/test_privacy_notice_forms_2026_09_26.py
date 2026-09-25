# -*- coding: utf-8 -*-
"""個資蒐集告知擴大到其他表單（2026-09-26；CUSTOMIZATION-SPEC §9.3，沿用 R3 機制）。

守住的規則：
① 告知文字依用途分開（承攬／聯絡人／使用者帳號），公司可各自改寫，空白 ⇒ 該用途的範本；不認得的用途 400。
② 客戶／供應商的每一位聯絡人、承攬商、使用者帳號：「已告知」由伺服器蓋時間、人員、當下告知文字的雜湊，
   存在設定鍵 `privacy_notice_acks`；已記錄的不能被覆蓋（告知文字改版後再記一次也不變），並寫稽核。
③ 沒有紀錄不擋存檔。
"""
import pytest

from helpers import privacy_notice as pn


def _hdr(client, make_user, username="pn2_root", role="superadmin"):
    u, p = make_user(username=username, role=role)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _audit_count(action, target_id):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT COUNT(*) FROM audit_log WHERE action=? AND target_id=?",
                            (action, str(target_id))).fetchone()[0]
    finally:
        conn.close()


# ── ① 用途別的告知文字 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("purpose", ["contact", "user"])
@pytest.mark.parametrize("must", ["蒐集者名稱", "蒐集目的", "個人資料類別", "利用期間", "地區", "對象", "方式",
                                  "個人資料保護法第 3 條", "不提供的影響"])
def test_purpose_templates_cover_article_8(purpose, must):
    assert must in pn.PURPOSES[purpose][0]


def test_purpose_texts_differ_and_default_stays_contractor(client, make_user):
    h = _hdr(client, make_user)
    assert client.put("/api/settings/company-profile", json={"name": "乙公司"}, headers=h).status_code == 200
    base = client.get("/api/legal-params/privacy-notice", headers=h).json()
    assert base["text"] == pn.template_for("乙公司"), "預設（沒帶 purpose）要維持 R3 的承攬範本"
    texts = {p: client.get("/api/legal-params/privacy-notice?purpose=" + p, headers=h).json() for p in pn.PURPOSES}
    assert len({t["text"] for t in texts.values()}) == 3
    assert all("乙公司" in t["text"] and t["isTemplate"] for t in texts.values())
    assert client.get("/api/legal-params/privacy-notice?purpose=nope", headers=h).status_code == 400


@pytest.mark.parametrize("purpose,key", [("contact", "privacy_notice_contact"), ("user", "privacy_notice_user")])
def test_company_can_customize_each_purpose(client, make_user, purpose, key):
    h = _hdr(client, make_user)
    r = client.put("/api/settings/company-profile", json={key: "自訂-" + purpose}, headers=h)
    assert r.status_code == 200, r.text
    assert client.get("/api/settings/company-profile", headers=h).json()[key] == "自訂-" + purpose
    d = client.get("/api/legal-params/privacy-notice?purpose=" + purpose, headers=h).json()
    assert (d["text"], d["isTemplate"], d["hash"]) == ("自訂-" + purpose, False, pn.notice_hash("自訂-" + purpose))
    # 其他用途不受影響
    assert client.get("/api/legal-params/privacy-notice", headers=h).json()["isTemplate"] is True


# ── ② 客戶／供應商的聯絡人 ─────────────────────────────────────────────────────

_CONTACT_KINDS = [("customers", "customer_contact", "customer.privacy_notice_ack"),
                  ("suppliers", "supplier_contact", "supplier.privacy_notice_ack")]


def _with_contacts(client, h, base):
    body = {"name": "聯絡測試公司", "data": {"contacts": [{"id": 111, "name": "王聯絡", "phone": "0912"},
                                                        {"id": "abc", "name": "李聯絡"}]}}
    r = client.post(f"/api/{base}", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.mark.parametrize("base,kind,action", _CONTACT_KINDS)
def test_contact_ack_is_stamped_once_and_audited(client, make_user, base, kind, action):
    h = _hdr(client, make_user)
    eid = _with_contacts(client, h, base)
    assert client.get(f"/api/{base}/{eid}/privacy-notice", headers=h).json()["acks"] == {}
    r1 = client.post(f"/api/{base}/{eid}/contacts/111/privacy-notice/ack", headers=h)
    assert r1.status_code == 200 and r1.json()["created"] is True, r1.text
    rec = r1.json()["ack"]
    assert rec["byUsername"] == "pn2_root" and rec["noticeHash"] == pn.notice_hash(pn.current_purpose_notice("contact"))
    # 告知文字改版後再記一次：原紀錄（時間、人員、當時的雜湊）不變
    assert client.put("/api/settings/company-profile", json={"privacy_notice_contact": "第二版"}, headers=h).status_code == 200
    r2 = client.post(f"/api/{base}/{eid}/contacts/111/privacy-notice/ack", headers=h)
    assert r2.json()["created"] is False and r2.json()["ack"] == rec
    acks = client.get(f"/api/{base}/{eid}/privacy-notice", headers=h).json()["acks"]
    assert acks == {"111": rec}, "只有記錄過的那一位"
    assert pn.get_ack(kind, f"{eid}:111") == rec
    assert _audit_count(action, f"{eid}:111") == 1
    # 另一位（字串 id）獨立記錄，雜湊是改版後的文字
    r3 = client.post(f"/api/{base}/{eid}/contacts/abc/privacy-notice/ack", headers=h)
    assert r3.json()["ack"]["noticeHash"] == pn.notice_hash("第二版")


@pytest.mark.parametrize("base,kind,action", _CONTACT_KINDS)
def test_contact_ack_unknown_contact_or_entity_is_404(client, make_user, base, kind, action):
    h = _hdr(client, make_user)
    eid = _with_contacts(client, h, base)
    assert client.post(f"/api/{base}/{eid}/contacts/999/privacy-notice/ack", headers=h).status_code == 404
    assert client.post(f"/api/{base}/999999/contacts/111/privacy-notice/ack", headers=h).status_code == 404
    assert client.get(f"/api/{base}/999999/privacy-notice", headers=h).status_code == 404
    assert pn.get_ack(kind, f"{eid}:999") is None


@pytest.mark.parametrize("base,kind,action", _CONTACT_KINDS)
def test_saving_without_ack_is_not_blocked_and_does_not_touch_acks(client, make_user, base, kind, action):
    h = _hdr(client, make_user)
    eid = _with_contacts(client, h, base)
    client.post(f"/api/{base}/{eid}/contacts/111/privacy-notice/ack", headers=h)
    before = pn.get_ack(kind, f"{eid}:111")
    # 前端把表單整包存回去（含偽造的 privacyAcks）：存檔照常成功，紀錄不變
    body = {"name": "聯絡測試公司", "data": {"contacts": [{"id": 111, "name": "王聯絡"}],
                                            "privacyAcks": {"111": {"at": "2000-01-01", "by": "x"}}}}
    assert client.put(f"/api/{base}/{eid}", json=body, headers=h).status_code == 200
    assert pn.get_ack(kind, f"{eid}:111") == before


# ── ② 承攬商、使用者帳號 ──────────────────────────────────────────────────────

def test_vendor_ack_is_recorded_once_and_needs_admin(client, make_user):
    h = _hdr(client, make_user)
    r = client.post("/api/vendor-contractors", json={"name": "承攬商甲", "contact_name": "陳窗口"}, headers=h)
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert client.get(f"/api/vendor-contractors/{vid}/privacy-notice", headers=h).json()["ack"] is None
    r1 = client.post(f"/api/vendor-contractors/{vid}/privacy-notice/ack", headers=h)
    assert r1.status_code == 200 and r1.json()["created"] is True, r1.text
    assert r1.json()["ack"]["noticeHash"] == pn.notice_hash(pn.current_purpose_notice("contact"))
    r2 = client.post(f"/api/vendor-contractors/{vid}/privacy-notice/ack", headers=h)
    assert r2.json()["created"] is False and r2.json()["ack"] == r1.json()["ack"]
    assert _audit_count("vendor.privacy_notice_ack", vid) == 1
    assert client.post("/api/vendor-contractors/999999/privacy-notice/ack", headers=h).status_code == 404
    hv = _hdr(client, make_user, "pn2_sales", role="sales")
    assert client.post(f"/api/vendor-contractors/{vid}/privacy-notice/ack", headers=hv).status_code == 403


def test_user_ack_is_recorded_once_and_needs_superadmin(client, make_user):
    h = _hdr(client, make_user)
    r = client.post("/api/users", json={"username": "pn2_target", "password": "Xy9#long-pass",
                                        "display_name": "被告知者"}, headers=h)
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert client.get(f"/api/users/{uid}/privacy-notice", headers=h).json()["ack"] is None
    r1 = client.post(f"/api/users/{uid}/privacy-notice/ack", headers=h)
    assert r1.status_code == 200 and r1.json()["created"] is True, r1.text
    assert r1.json()["ack"]["noticeHash"] == pn.notice_hash(pn.current_purpose_notice("user"))
    assert client.put("/api/settings/company-profile", json={"privacy_notice_user": "改版"}, headers=h).status_code == 200
    r2 = client.post(f"/api/users/{uid}/privacy-notice/ack", headers=h)
    assert r2.json()["created"] is False and r2.json()["ack"] == r1.json()["ack"]
    assert _audit_count("user.privacy_notice_ack", uid) == 1
    assert client.post("/api/users/999999/privacy-notice/ack", headers=h).status_code == 404
    ha = _hdr(client, make_user, "pn2_admin", role="admin")
    assert client.post(f"/api/users/{uid}/privacy-notice/ack", headers=ha).status_code == 403
