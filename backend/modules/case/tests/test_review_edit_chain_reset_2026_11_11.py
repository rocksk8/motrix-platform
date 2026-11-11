# -*- coding: utf-8 -*-
"""簽核人在審核中改報價單（POST /review-edit）——2026-11-11 業主需求：

1. 第 3 層（含）以後（`currentTier>=2`，0 起算）編輯 ⇒ **整條簽核鏈回第 1 層重跑**：所有已簽條目（含舊單沒有 signedFp 的、編輯者自己的）回待簽，`currentTier=0`。
2. 第 1、2 層編輯 ⇒ 維持原行為（不整條重跑）。
3. 存檔成功後寄信給「送審人＋全部啟用中、有 email 的超級管理員」；`editHistory` 照常寫一筆 `review_edit`。
兩種情境各自分開驗。
"""
import json

import pytest

from modules.case import content_fp as C
from modules.case.tests.test_content_fp_s1_2026_11_06 import NO, _login, _row, _seed
from modules.case.tests.test_reconcile_txn_s3b_2026_11_06 import (
    _approve, _audits, _entries, _fresh_mode_cache, _funnel_edit, _notes, _qty, _set_mode)
from modules.case.tests.test_review_edit_s4_2026_11_07 import _edit, _get, _three_tiers_two_signed
from tests._requires import requires_module

pytestmark = requires_module("case", "打 M01 的報價單複查編輯端點")

_ = _fresh_mode_cache


def _make_legacy_signed(upto):
    """把前 `upto` 個條目改成「舊單已簽（沒有 signedFp）」，currentTier 指到下一層（模擬 signedFp 機制上線前就已簽的單）。"""
    import db
    d, _s, _u = _row()
    for i, t in enumerate(d["approval"]["tiers"]):
        for a in t["approvers"]:
            if i < upto:
                a.update(status="approved", approvedAt="2026-11-06T02:00:00")
                a.pop("signedFp", None)
    d["approval"]["currentTier"] = upto
    c = db.get_db()
    c.execute("UPDATE quotations SET data_json=?, status='簽核中' WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO))
    c.commit()
    c.close()


# ═════════ 第 3 層（含）以後：整條重跑 ═════════
def test_tier3_edit_resets_whole_chain_to_tier1_and_the_chain_then_reruns_in_order(client, make_user):
    hs, names = _three_tiers_two_signed(client, make_user)
    r = _edit(client, hs[2], qty=9)                                   # T3（currentTier==2）首次編輯
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chainReset"] is True
    es, ap, _st = _entries()
    d, status, _u = _row()
    assert [e["status"] for e in es] == ["pending", "pending", "pending"], "整條回待簽"
    assert es[0]["reconfirm"] and es[1]["reconfirm"] and not es[2].get("reconfirm"), "曾經簽過的 T1／T2 標待複查；T3 是首次待簽"
    assert ap["currentTier"] == 0 and status == "待審核", "回第 1 層；沒有人簽著 ⇒ 狀態回待審核（比照 approve：簽核中＝currentTier>0）"
    assert sorted(body["invalidated"]) == sorted(names[:2])
    assert ap["changeLog"][-1].get("chainReset") is True
    audit = json.loads(_audits("quotation.review_edit")[-1]["detail"])
    assert audit["chainReset"] is True and audit["tier"] == 3
    # 依序重跑：T2、T3 不能搶在 T1 前；T1→T2→T3 之後才算完成
    fp = _get(client, hs[0])["contentFp"]
    for h in (hs[1], hs[2]):
        assert client.post("/api/quotations/%s/approve" % NO, headers=h, json={"expectedFp": fp, "choice": "keep"}).status_code == 403
    for i, h in enumerate(hs):
        fp = _get(client, h)["contentFp"]
        r2 = client.post("/api/quotations/%s/approve" % NO, headers=h, json={"expectedFp": fp, "choice": "keep"})
        assert r2.status_code == 200, (i, r2.text)
    assert r2.json()["allDone"] is True
    assert _row()[1] == "已送出"


def test_tier3_edit_also_resets_legacy_signed_entries_and_the_editors_own_earlier_signature(client, make_user):
    """舊單（沒有 signedFp，一般規則永不作廢）在第 3 層編輯時也要整條重跑；第 1、2 層編輯則維持不動（下一題）。"""
    hs, names = _seed(client, make_user, tiers=3)
    _set_mode(2)
    _make_legacy_signed(2)
    r = _edit(client, hs[2], qty=9)
    assert r.status_code == 200, r.text
    es, ap, st = _entries()
    assert [e["status"] for e in es] == ["pending", "pending", "pending"] and ap["currentTier"] == 0 and st == "待審核"
    assert sorted(r.json()["invalidated"]) == sorted(names[:2])


def test_tier3_editor_who_had_signed_before_is_not_auto_resigned_either(client, make_user):
    """原已簽、正在複查的編輯者：第 1、2 層編輯會視為簽新版（原規則）；第 3 層以後整條重跑 ⇒ 連他自己也回待簽。"""
    hs, names = _seed(client, make_user, tiers=3)
    _set_mode(2)
    _approve(client, hs[0]); _approve(client, hs[1]); _approve(client, hs[2])      # 三層簽到底前先停在最後一層：用資料模擬 T3 也簽過、之後內容被改回「簽核中」
    d, _s, _u = _row()
    appr = d["approval"]
    assert appr["status"] == "approved" or _row()[1] == "已送出"
    # 重新打開：最後一層回待複查（別人改了內容之後）
    import db
    d["approval"].pop("status", None); d["approval"].pop("approvedAt", None); d["approval"].pop("approvedBy", None); d["approval"].pop("approvedByDisplay", None)
    d["approval"]["currentTier"] = 2
    a2 = d["approval"]["tiers"][2]["approvers"][0]
    a2["status"] = "pending"; a2["reconfirm"] = True; a2["prevSignedFp"] = a2.get("signedFp")
    a2.pop("approvedAt", None)
    c = db.get_db()
    c.execute("UPDATE quotations SET data_json=?, status='簽核中' WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    r = _edit(client, hs[2], qty=9)
    assert r.status_code == 200, r.text
    es, ap, st = _entries()
    assert [e["status"] for e in es] == ["pending"] * 3 and ap["currentTier"] == 0 and st == "待審核"
    assert r.json()["resigned"] == [], "整條重跑不做編輯者自動重簽"
    assert all(e["reconfirm"] for e in es)


# ═════════ 第 1、2 層：維持原行為（不整條重跑）═════════
def test_tier2_edit_keeps_existing_behavior_and_does_not_reset_the_chain(client, make_user):
    hs, names = _seed(client, make_user, tiers=3)
    _set_mode(2)
    _approve(client, hs[0])                                           # T1 簽；currentTier==1（第 2 層）
    d, status, _u = _row()
    assert status == "簽核中" and d["approval"]["currentTier"] == 1
    r = _edit(client, hs[1], qty=9)                                   # T2 編輯（索引 1 < 2）
    assert r.status_code == 200, r.text
    assert r.json()["chainReset"] is False
    es, ap, st = _entries()
    assert es[0]["status"] == "pending" and es[0]["reconfirm"], "原規則：已簽的 T1 回待複查"
    assert es[1]["status"] == "pending" and not es[1].get("reconfirm"), "首次待簽的編輯者不自動簽"
    assert ap["currentTier"] == 0 and st == "簽核中", "原行為：狀態不被改成待審核"
    assert "chainReset" not in ap["changeLog"][-1]
    assert "chainReset" not in json.loads(_audits("quotation.review_edit")[-1]["detail"])


def test_tier2_edit_leaves_legacy_signed_tier1_untouched_unlike_tier3(client, make_user):
    hs, names = _seed(client, make_user, tiers=3)
    _set_mode(2)
    _make_legacy_signed(1)                                            # T1 是舊單已簽（無 signedFp）；currentTier==1
    r = _edit(client, hs[1], qty=9)
    assert r.status_code == 200, r.text
    es, ap, _st = _entries()
    assert es[0]["status"] == "approved", "第 2 層編輯：舊單已簽的 T1 維持原樣（原行為不變）"
    assert ap["currentTier"] == 1 and r.json()["chainReset"] is False


def test_tier1_edit_keeps_existing_behavior(client, make_user):
    hs, names = _seed(client, make_user, tiers=3)
    _set_mode(2)
    r = _edit(client, hs[0], qty=9)
    assert r.status_code == 200, r.text
    assert r.json()["chainReset"] is False
    es, ap, st = _entries()
    assert ap["currentTier"] == 0 and st == "待審核" and [e["status"] for e in es] == ["pending"] * 3
    assert "chainReset" not in ap["changeLog"][-1]


# ═════════ 通知信收件人／editHistory ═════════
@pytest.fixture()
def mails(monkeypatch):
    from helpers import email_notify as EN
    sent = []
    monkeypatch.setattr(EN, "_async_send", lambda to, subject, html: sent.append({"to": sorted(to), "subject": subject, "html": html}))
    return sent


def _set_email(username, email, active=1, role=None):
    import db
    c = db.get_db()
    c.execute("UPDATE users SET email=?, active=? WHERE username=?", (email, active, username))
    if role:
        c.execute("UPDATE users SET role=? WHERE username=?", (role, username))
    c.commit()
    c.close()


def _prep_recipients(make_user):
    """送審人 fp_req；超管 sa1／sa2（有 email）、sa_off（停用）、sa_noemail（沒信箱）；一般管理員 bystander（有 email、不該收到）。"""
    _set_email("fp_req", "req@example.test")
    for n, active, em in (("sa1", 1, "sa1@example.test"), ("sa2", 1, "sa2@example.test"), ("sa_off", 0, "sa_off@example.test"), ("sa_noemail", 1, "")):
        make_user(username=n, role="superadmin")
        _set_email(n, em, active)
    make_user(username="bystander", role="admin")
    _set_email("bystander", "bystander@example.test")
    import db
    c = db.get_db()
    c.execute("UPDATE users SET email=NULL WHERE role='superadmin' AND username NOT IN ('sa1','sa2')")   # 預設超管帳號（admin）不要混進收件人
    c.commit()
    c.close()


@pytest.mark.parametrize("tier_idx", [0, 2], ids=["tier1-edit", "tier3-chain-reset"])
def test_review_edit_mails_requester_and_all_superadmins_only(client, make_user, mails, tier_idx):
    hs, names = _seed(client, make_user, tiers=3)
    _prep_recipients(make_user)
    _set_mode(2)
    for i in range(tier_idx):
        _approve(client, hs[i])
    r = _edit(client, hs[tier_idx], qty=9)
    assert r.status_code == 200, r.text
    assert len(mails) == 1, mails
    m = mails[0]
    assert m["to"] == sorted(["req@example.test", "sa1@example.test", "sa2@example.test"]), "送審人＋全部可寄的超管；停用／無信箱／一般管理員／編輯者本人都不在內"
    assert NO in m["subject"]
    assert ("已回到第 1 層" in m["html"]) == (tier_idx == 2)
    assert "9" not in m["subject"]


def test_failed_review_edit_sends_no_mail(client, make_user, mails):
    hs, names = _seed(client, make_user, tiers=2)
    _prep_recipients(make_user)
    _set_mode(2)
    req_h = _login(client, "fp_req", "Test-Pass-123")
    assert _edit(client, req_h, qty=9).status_code == 403              # 送審人不能 review-edit
    assert _edit(client, hs[0], qty=9, fp="1:stale").status_code == 409
    assert mails == []


def test_edit_history_gets_a_review_edit_entry_in_both_scenarios(client, make_user, mails):
    hs, names = _three_tiers_two_signed(client, make_user)
    assert _edit(client, hs[2], qty=9).status_code == 200              # tier3：整條重跑
    d, _s, _u = _row()
    h = d.get("editHistory") or []
    assert h and h[-1]["type"] == "review_edit" and h[-1]["by"] == names[2], h
    assert h[-1].get("changes"), "有逐欄變更摘要"
    # tier1（整條重跑之後第 1 層自己再編輯）：同樣寫一筆
    assert _edit(client, hs[0], qty=11).status_code == 200
    d, _s, _u = _row()
    assert [e["type"] for e in d["editHistory"]][-2:] == ["review_edit", "review_edit"] and d["editHistory"][-1]["by"] == names[0]
    assert d["editHistory"][-1]["rev"] == d["editHistory"][-2]["rev"] + 1


def test_tier3_with_two_approvers_first_already_signed_second_edits_resets_everyone(client, make_user):
    """K 審（hichan-12）建議：第 3 層有兩位簽核人、第一位已簽，第二位編輯 ⇒ 兩位都回待簽、currentTier=0。"""
    import db
    hs, names = _seed(client, make_user, tiers=3)
    extra, pw = make_user(username="fp_ap2b", role="admin")
    h_extra = _login(client, extra, pw)
    d, _s, _u = _row()
    d["approval"]["tiers"][2]["approvers"].append({"username": extra, "displayName": extra, "status": "pending"})
    c = db.get_db()
    c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    _set_mode(2)
    for h in hs:
        _approve(client, h)                                          # T1、T2、T3 第一位；currentTier 仍是 2（第 3 層還有第二位）
    es, ap, _st = _entries()
    assert [e["status"] for e in es] == ["approved", "approved", "approved", "pending"] and ap["currentTier"] == 2
    r = _edit(client, h_extra, qty=9)
    assert r.status_code == 200, r.text
    es, ap, st = _entries()
    assert r.json()["chainReset"] is True
    assert [e["status"] for e in es] == ["pending"] * 4 and ap["currentTier"] == 0 and st == "待審核"
    assert sorted(r.json()["invalidated"]) == sorted(names)


def test_chain_reset_tells_tier1_it_is_their_turn_with_in_app_notice_and_mail(client, make_user, monkeypatch):
    """K 審（hichan-12）：整條重跑後第 1 層握著「輪到你」——要有 approval_request 站內通知＋信（比照一般送審），被作廢者的通知文字講清楚是整條重跑。"""
    from helpers import email_notify as EN
    sent = []
    monkeypatch.setattr(EN, "_async_send", lambda to, subject, html: sent.append((sorted(to), subject)))
    hs, names = _three_tiers_two_signed(client, make_user)
    for n in names:
        _set_email(n, n + "@example.test")
    sent.clear()
    n0, n1 = len(_notes(names[0], "approval_request")), len(_notes(names[1], "approval_request"))      # 更早的核准流程留下的舊通知不算
    r = _edit(client, hs[2], qty=9)
    assert r.status_code == 200, r.text
    assert len(_notes(names[0], "approval_request")) == n0 + 1, "第 1 層收到新的站內「待簽核」通知"
    assert len(_notes(names[1], "approval_request")) == n1, "第 2 層還沒輪到：不發待簽核"
    assert any(names[0] + "@example.test" in to and "待審核" in subj for to, subj in sent), sent
    assert not any(names[1] + "@example.test" in to and "待審核" in subj for to, subj in sent)
    txt = [n["message"] for n in _notes(names[1], "approval_reconfirm")]
    assert txt and "整條簽核已回到第 1 層" in txt[0] and "請重新複查確認" not in txt[0], txt
