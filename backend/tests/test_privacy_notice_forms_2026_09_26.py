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

def _supply_installed():
    from core import source_tree
    return source_tree.module_installed("modules/supply/")


_CONTACT_KINDS = [("customers", "customer_contact", "customer.privacy_notice_ack"),
                  # 供應商的端點在 M03（modules/supply）：模組不在時端點本來就不在（PLAYBOOK §B-11）
                  pytest.param("suppliers", "supplier_contact", "supplier.privacy_notice_ack",
                               marks=pytest.mark.skipif(not _supply_installed(), reason="M03 不在這個安裝包"))]


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


# ── ④ 單據上手動輸入的聯絡人（2026-09-26 主持裁示：報價單、案件、完工單、網路規劃書）─────────

def _insert_quote(quote_no, contact="林聯絡", site="趙現場"):
    import json as _json
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "告知測試", 1000, 952,
             _json.dumps({"dealTag": "已成案", "contactName": contact,
                          "caseRecord": {"contract": {"contactPerson": site}}}, ensure_ascii=False),
             "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("role,kind,name", [("contact", "quote_contact", "林聯絡"), ("site", "case_site_contact", "趙現場")])
def test_quotation_contact_ack_only_for_the_saved_contact(client, make_user, role, kind, name):
    h = _hdr(client, make_user)
    no = "PN-Q-" + role
    _insert_quote(no)
    base = f"/api/quotations/{no}/privacy-notice"
    assert client.get(base + "?role=" + role, headers=h).json()["acks"] == {}
    # 還沒存檔的聯絡人（畫面上改了名字）⇒ 409，不記錄
    r = client.post(base + "/ack", json={"role": role, "subject": "別人"}, headers=h)
    assert r.status_code == 409, r.text
    r1 = client.post(base + "/ack", json={"role": role, "subject": name}, headers=h)
    assert r1.status_code == 200 and r1.json()["created"] is True, r1.text
    assert r1.json()["ack"]["noticeHash"] == pn.notice_hash(pn.current_purpose_notice("contact"))
    r2 = client.post(base + "/ack", json={"role": role, "subject": name}, headers=h)
    assert r2.json()["created"] is False and r2.json()["ack"] == r1.json()["ack"]
    assert client.get(base + "?role=" + role, headers=h).json()["acks"] == {name: r1.json()["ack"]}
    assert pn.get_ack(kind, f"{no}:{name}") == r1.json()["ack"]
    assert _audit_count("quotation.privacy_notice_ack", no) == 1
    assert client.post(base + "/ack", json={"role": "nope", "subject": name}, headers=h).status_code == 400
    assert client.post("/api/quotations/NO-SUCH/privacy-notice/ack", json={"role": role, "subject": name},
                       headers=h).status_code == 404


def test_network_plan_contact_ack_follows_the_saved_contact(client, make_user):
    h = _hdr(client, make_user)
    r = client.post("/api/network-plans", json={"siteName": "告知案場", "contactName": "周窗口"}, headers=h)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    base = f"/api/network-plans/{pid}/privacy-notice"
    assert client.post(base + "/ack", json={"subject": "別人"}, headers=h).status_code == 409
    r1 = client.post(base + "/ack", json={"subject": "周窗口"}, headers=h)
    assert r1.status_code == 200 and r1.json()["created"] is True, r1.text
    # 換了聯絡人：舊紀錄留著；新聯絡人要另外告知
    assert client.put(f"/api/network-plans/{pid}", json={"contactName": "吳新窗口"}, headers=h).status_code == 200
    assert client.get(base, headers=h).json()["acks"] == {"周窗口": r1.json()["ack"]}
    assert client.post(base + "/ack", json={"subject": "周窗口"}, headers=h).status_code == 409
    r2 = client.post(base + "/ack", json={"subject": "吳新窗口"}, headers=h)
    assert r2.json()["created"] is True
    assert set(client.get(base, headers=h).json()["acks"]) == {"周窗口", "吳新窗口"}
    plan_no = client.get(f"/api/network-plans/{pid}", headers=h).json()["planNo"]
    assert _audit_count("network_plan.privacy_notice_ack", plan_no) == 2


def test_completion_note_recipient_ack(client, make_user):
    h = _hdr(client, make_user)
    _insert_quote("PN-CN-001")
    r = client.post("/api/completion-notes", json={"quote_no": "PN-CN-001", "recipient": "陳經理"}, headers=h)
    assert r.status_code == 201, r.text
    no = r.json()["note_no"]
    base = f"/api/completion-notes/{no}/privacy-notice"
    assert client.post(base + "/ack", json={"subject": "別人"}, headers=h).status_code == 409
    r1 = client.post(base + "/ack", json={"subject": "陳經理"}, headers=h)
    assert r1.status_code == 200 and r1.json()["created"] is True, r1.text
    assert client.get(base, headers=h).json()["acks"] == {"陳經理": r1.json()["ack"]}
    assert _audit_count("completion.privacy_notice_ack", no) == 1


@pytest.mark.parametrize("role", ["contact", "site"])
def test_quotation_privacy_endpoints_refuse_non_members(client, make_user, role):
    """稽核 D PN-S1（突變 PN8、PN9 原本存活）：不是這張案件的人，讀不到聯絡人與告知紀錄，也不能替它記一筆「已告知」。"""
    no = "PN-Q-OUT-" + role
    _insert_quote(no)
    h = _hdr(client, make_user, username="pn_out_" + role, role="engineer")
    base = f"/api/quotations/{no}/privacy-notice"
    assert client.get(base + "?role=" + role, headers=h).status_code == 404   # M01-O1：看不到＝不存在（同一個 404）
    name = "林聯絡" if role == "contact" else "趙現場"
    r = client.post(base + "/ack", json={"role": role, "subject": name}, headers=h)
    assert r.status_code == 404, r.text   # M01-O1：看不到＝不存在（同一個 404）
    kind = "quote_contact" if role == "contact" else "case_site_contact"
    assert pn.get_ack(kind, f"{no}:{name}") in (None, {}), "被擋下的請求不可以留下紀錄"
