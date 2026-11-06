# -*- coding: utf-8 -*-
"""簽核二擇一 S4：`POST /api/quotations/{no}/review-edit`、J1 `signedReasonEntries`、K3 旗標必填。
規格：docs/platform/plans/QUOTE-APPROVE-EDIT-CHOICE-PROPOSAL.md H2／H3／H7／H9、J1、K3。

驗收字句（H7，逐字進斷言）：
- 「選「編輯」＝存檔後 B 的簽視為新版，其他已簽層回 pending；C 收到「B 編輯」通知並看到新版。」
- 「送審人不能 review-edit；非當層待簽人不能；無金額權限不能；is_signed 單不能。」
- 「B 按「審核通過」時指紋與載入時不同 ⇒ 409；旗標成立未帶 choice ⇒ 409。」
"""
import json

import pytest

from modules.case import content_fp as C
from modules.case.tests.test_content_fp_s1_2026_11_06 import NO, _doc, _login, _row, _seed
from modules.case.tests.test_reconcile_txn_s3b_2026_11_06 import (
    _approve, _audits, _entries, _fresh_mode_cache, _funnel_edit, _notes, _qty, _set_mode, _signed_first_of_two)
from tests._requires import requires_module

pytestmark = requires_module("case", "S4 打 M01 的報價單複查編輯端點")

_ = _fresh_mode_cache                                    # autouse fixture：每題前後清模式快取（import 進來就生效）


def _get(client, h):
    r = client.get("/api/quotations/" + NO, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _edit(client, h, qty=9, fp=None, mutate=None, **extra):
    """複查編輯：先 GET（當下的本文與指紋）、改 qty、POST。"""
    g = _get(client, h)
    data = g["data"]
    data["items"][0]["qty"] = qty
    if mutate:
        mutate(data)
    body = {"data": data, "expectedFp": fp or g["contentFp"], **extra}
    return client.post("/api/quotations/%s/review-edit" % NO, headers=h, json=body)


def _three_tiers_two_signed(client, make_user):
    """三層（T1=ap0、T2=ap1 已簽；T3=ap2 待簽），旗標 on。回 (headers, names)。"""
    hs, names = _seed(client, make_user, tiers=3)
    _set_mode(2)
    _approve(client, hs[0])
    _approve(client, hs[1])
    es, _ap, _st = _entries()
    assert [e["status"] for e in es] == ["approved", "approved", "pending"]
    return hs, names


# ── H2／H7：編輯者的簽 ─────────────────────────────────────────────────────────────
def test_reviewer_who_had_signed_is_resigned_on_the_new_version_and_keeps_requester(client, make_user):
    """H7：「選「編輯」＝存檔後 B 的簽視為新版」。B＝原已簽、正在複查（內容被別人改過）。"""
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _funnel_edit(_qty(5))                                            # 別人改了內容 ⇒ B 的簽過期、回待複查
    es, ap, _st = _entries()
    assert es[0]["status"] == "pending" and es[0]["reconfirm"] and ap["currentTier"] == 0
    req_before = ap["requestedBy"]

    r = _edit(client, hs[0], qty=9)
    assert r.status_code == 200, r.text
    d, status, _u = _row()
    es, ap, _st = _entries()
    fp_new = C.content_fingerprint(d)
    assert d["items"][0]["qty"] == 9 and r.json()["contentFp"] == fp_new
    assert "moneyMasked" not in d and "contentFp" not in d, "讀取端點注入的顯示欄位不可存進 data_json（會變成內容鍵、改變指紋）"
    assert es[0]["status"] == "approved" and es[0]["signedFp"] == fp_new and es[0]["signedKeyHashes"] == C.key_hashes(d)
    assert "reconfirm" not in es[0] and "prevSignedFp" not in es[0]
    assert es[1]["status"] == "pending" and not es[1].get("reconfirm")
    assert ap["currentTier"] == 1 and status == "簽核中"
    assert ap["requestedBy"] == req_before, "送審人維持原申請人（B 不會變成送審人）"
    assert ap["contentFp"] == fp_new


def test_first_time_pending_editor_is_not_auto_signed_and_other_signed_layers_return_to_pending(client, make_user):
    """H7：「選「編輯」＝…其他已簽層回 pending；C 收到「B 編輯」通知並看到新版。」＋三層「T1、T2 依序複查，之後才輪 T3」。
    H9-①：首次待簽者編輯不自動算簽，仍須自己再按一次核准。"""
    hs, names = _three_tiers_two_signed(client, make_user)
    r = _edit(client, hs[2], qty=9)                                 # C＝ap2＝首次待簽
    assert r.status_code == 200, r.text
    es, ap, _st = _entries()
    d, _s, _u = _row()
    assert es[2]["status"] == "pending" and not es[2].get("signedFp") and not es[2].get("reconfirm"), "C 不自動簽"
    assert [e["status"] for e in es[:2]] == ["pending", "pending"] and all(e["reconfirm"] for e in es[:2]), "T1、T2 回待複查"
    assert ap["currentTier"] == 0, "之後的順序：T1 先複查，之後才輪 T2、T3"
    assert sorted(r.json()["invalidated"]) == sorted(names[:2]) and r.json()["resigned"] == []
    for n in names[:2]:
        assert _notes(n, "approval_reconfirm"), "被作廢的已簽層收到通知"
    assert _notes("fp_req", "approval_reconfirm_info"), "送審人收到通知"
    assert not _notes(names[2], "approval_reconfirm") and not _notes(names[2], "approval_reconfirm_info"), "編輯者自己不收複查通知"
    # T1 依序複查（維持）→ 才輪 T2
    fp = _get(client, hs[0])["contentFp"]
    assert client.post("/api/quotations/%s/approve" % NO, headers=hs[1], json={"expectedFp": fp, "choice": "keep"}).status_code == 403, "T2 不能搶在 T1 前"
    assert client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={"expectedFp": fp, "choice": "keep"}).status_code == 200


def test_when_nobody_had_signed_later_layers_and_requester_still_hear_about_the_edit(client, make_user):
    """H3：「通知：被作廢的已簽層（B）、送審人 A、後續層（C）都收通知」——沒有已簽層時，送審人與其他待簽人仍要知道內容被改了。"""
    hs, names = _seed(client, make_user, tiers=2)
    _set_mode(2)
    r = _edit(client, hs[0], qty=9)
    assert r.status_code == 200, r.text
    assert _notes(names[1], "approval_reconfirm_info") and _notes("fp_req", "approval_reconfirm_info")
    assert not _notes(names[0])
    es, _ap, _st = _entries()
    assert es[0]["status"] == "pending", "首次待簽的編輯者不自動簽"


def test_editor_who_is_the_last_one_left_is_not_auto_signed_so_the_quote_cannot_get_stuck(client, make_user):
    """其他條目全已簽（舊單沒有 signedFp、不被作廢）而編輯者是最後一個 ⇒ 自動簽會讓整單全部 approved 卻沒走核准收尾（狀態、PDF、通知）。
    改成他維持待簽（reconfirm），自己再按核准走正常收尾。"""
    hs, names = _seed(client, make_user, tiers=2)
    import db
    c = db.get_db()
    d, _s, _u = _row()
    t0 = d["approval"]["tiers"][0]["approvers"][0]
    t0.update(status="approved", approvedAt="2026-11-06T02:00:00")          # 舊單：沒有 signedFp
    d["approval"]["currentTier"] = 1
    c.execute("UPDATE quotations SET data_json=?, status='簽核中' WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    _set_mode(2)
    _approve(client, hs[1])                                                  # 新簽（有 signedFp）→ 全簽完、已送出；改回簽核中模擬「後來內容變動」
    d, _s, _u = _row()
    d["approval"]["tiers"][1]["approvers"][0].update(status="approved")
    d["approval"].pop("status", None); d["approval"].pop("approvedAt", None); d["approval"]["currentTier"] = 2
    d["items"][0]["qty"] = 5
    c = db.get_db()
    c.execute("UPDATE quotations SET data_json=?, status='簽核中' WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    # 第二層簽核人複查：伺服器先對帳（過期 ⇒ 待複查）再放行
    r = _edit(client, hs[1], qty=9)
    assert r.status_code == 200, r.text
    es, ap, st = _entries()
    assert es[1]["status"] == "pending" and es[1]["reconfirm"] and r.json()["resigned"] == []
    assert st == "簽核中" and ap["currentTier"] == 1
    assert _audits("quotation.review_edit")[0]["detail"] and "editorPending" in json.loads(_audits("quotation.review_edit")[0]["detail"])
    fp = _get(client, hs[1])["contentFp"]
    r2 = client.post("/api/quotations/%s/approve" % NO, headers=hs[1], json={"expectedFp": fp, "choice": "keep"})
    assert r2.status_code == 200 and r2.json()["allDone"] is True
    assert _row()[1] == "已送出"


# ── PM 交辦的順序題：先對帳、再查權限 ──────────────────────────────────────────────
def test_stale_approved_approver_can_review_edit_because_reconcile_runs_before_the_permission_check(client, make_user):
    """資料庫裡 B 是「已簽、但簽在舊內容上」（off 期間改的內容；之後切成 on）。currentTier 還指著下一層，
    若先查權限，B 不是「當層待簽人」⇒ 403、永遠進不了複查。先對帳：B 先被落地成待複查、輪到他，才查權限。"""
    hs, names = _seed(client, make_user, tiers=2)
    _approve(client, hs[0])                                                 # off：簽下去、signedFp＝舊指紋
    _funnel_edit(_qty(5))                                                   # off：內容變了，沒人對帳
    es, ap, _st = _entries()
    assert es[0]["status"] == "approved" and es[0]["signedFp"] != C.content_fingerprint(_row()[0]) and ap["currentTier"] == 1
    _set_mode(2)
    r = _edit(client, hs[0], qty=9)
    assert r.status_code == 200, r.text
    es, ap, _st = _entries()
    assert es[0]["status"] == "approved" and es[0]["signedFp"] == C.content_fingerprint(_row()[0]), "B 的簽視為新版"
    assert ap["currentTier"] == 1


def test_denied_review_edit_leaves_no_trace_of_the_pre_reconcile(client, make_user):
    """沒權限的人 ⇒ 連線不 commit：對帳寫的簽核狀態、通知、稽核一起消失（不能靠 403 探測／觸發對帳）。"""
    hs, names = _seed(client, make_user, tiers=2)
    _approve(client, hs[0])
    _funnel_edit(_qty(5))                                                   # off：過期但沒對帳
    _set_mode(2)
    before = _row()
    n_before = len(_notes())
    req_h = _login(client, "fp_req", "Test-Pass-123")
    r = _edit(client, req_h, qty=9)
    assert r.status_code == 403, r.text
    assert _row() == before and len(_notes()) == n_before and not _audits("quotation.reconfirm")


# ── 權限（H7：送審人／非當層待簽人／無金額權限／is_signed；超管；狀態；模式）────────────────────
def test_submitter_cannot_review_edit(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    _set_mode(2)
    req_h = _login(client, "fp_req", "Test-Pass-123")
    g = _get(client, req_h)
    r = client.post("/api/quotations/%s/review-edit" % NO, headers=req_h, json={"data": g["data"], "expectedFp": g["contentFp"]})
    assert r.status_code == 403 and "送審人" in r.text


def test_submitter_who_is_also_the_current_approver_still_cannot(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    d, _s, _u = _row()
    d["approval"]["requestedBy"] = names[0]
    import db
    c = db.get_db(); c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    _set_mode(2)
    assert _edit(client, hs[0]).status_code == 403


def test_non_current_tier_approver_cannot(client, make_user):
    hs, names = _seed(client, make_user, tiers=2)
    _set_mode(2)
    r = _edit(client, hs[1])
    assert r.status_code == 403 and _row()[0]["items"][0]["qty"] == 2


def test_user_without_quote_money_visibility_cannot(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    d, _s, _u = _row()
    v, vpw = make_user(username="fp_viewer", role="viewer")
    d["approval"]["tiers"][0]["approvers"][0].update(username=v, displayName=v)
    import db
    c = db.get_db(); c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    _set_mode(2)
    vh = _login(client, v, vpw)
    r = client.post("/api/quotations/%s/review-edit" % NO, headers=vh, json={"data": d, "expectedFp": C.content_fingerprint(d)})
    assert r.status_code == 403 and "財務" in r.text
    assert _row()[0]["items"][0]["qty"] == 2


def test_is_signed_alt_quote_cannot(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    import db
    c = db.get_db(); c.execute("UPDATE quotations SET is_signed=1 WHERE quote_no=?", (NO,)); c.commit(); c.close()
    _set_mode(2)
    r = _edit(client, hs[0])
    assert r.status_code == 409 and "回簽" in r.text and _row()[0]["items"][0]["qty"] == 2


def test_superadmin_is_sent_to_unlock_edit(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    s, spw = make_user(username="fp_super", role="superadmin")
    _set_mode(2)
    sh = _login(client, s, spw)
    r = client.post("/api/quotations/%s/review-edit" % NO, headers=sh, json={"data": _doc(), "expectedFp": "1:x"})
    assert r.status_code == 403 and "解鎖編輯" in r.text


@pytest.mark.parametrize("status", ["草稿", "已送出", "已成案"])
def test_only_pending_statuses_can_be_review_edited(client, make_user, status):
    hs, names = _seed(client, make_user, tiers=1, status=status)
    _set_mode(2)
    g = _get(client, hs[0])
    r = client.post("/api/quotations/%s/review-edit" % NO, headers=hs[0], json={"data": g["data"], "expectedFp": g.get("contentFp") or "1:x"})
    assert r.status_code == 409, r.text


@pytest.mark.parametrize("code", [0, 1])
def test_not_available_unless_mode_is_on(client, make_user, code):
    """off／shadow 不會作廢任何簽：開放編輯等於簽核人改完內容卻沒人複查（新的繞過）⇒ 一律不可用。"""
    hs, names = _seed(client, make_user, tiers=1)
    if code:
        _set_mode(code)
    before = _row()
    g = _get(client, hs[0])
    g["data"]["items"][0]["qty"] = 9
    r = client.post("/api/quotations/%s/review-edit" % NO, headers=hs[0], json={"data": g["data"], "expectedFp": C.content_fingerprint(before[0])})
    assert r.status_code == 409 and "尚未啟用" in r.text
    assert _row() == before


def test_delegate_of_current_approver_can_review_edit_but_is_not_auto_signed_for_them(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    dg, dpw = make_user(username="fp_dg", role="admin")
    import db
    c = db.get_db()
    c.execute("INSERT INTO approval_delegates (delegator_username, delegate_username, start_date, end_date, active, created_at, updated_at) "
              "VALUES (?,?,?,?,1,'2026-11-01','2026-11-01')", (names[0], dg, "2026-01-01", "2099-12-31")); c.commit(); c.close()
    _set_mode(2)
    r = _edit(client, _login(client, dg, dpw), qty=9)
    assert r.status_code == 200, r.text
    es, _ap, _st = _entries()
    assert es[0]["username"] == names[0] and es[0]["status"] == "pending" and not es[0].get("signedFp"), "代理人不替本人簽（S3a 只比對 username==編輯者）"


# ── expectedFp、無變動、輪次上限 ──────────────────────────────────────────────────────
def test_expected_fp_is_required_and_a_stale_one_is_409_without_writing(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    _set_mode(2)
    g = _get(client, hs[0])
    g["data"]["items"][0]["qty"] = 9
    assert client.post("/api/quotations/%s/review-edit" % NO, headers=hs[0], json={"data": g["data"]}).status_code == 422, "必填"
    _funnel_edit(_qty(7))                                                    # 開著畫面時有人改了內容
    before = _row()
    r = client.post("/api/quotations/%s/review-edit" % NO, headers=hs[0], json={"data": g["data"], "expectedFp": g["contentFp"]})
    assert r.status_code == 409 and "內容已更新" in r.text
    assert _row() == before


def test_no_change_is_400_and_writes_nothing(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    _set_mode(2)
    before = _row()
    g = _get(client, hs[0])
    r = client.post("/api/quotations/%s/review-edit" % NO, headers=hs[0], json={"data": g["data"], "expectedFp": g["contentFp"]})
    assert r.status_code == 400 and "沒有任何變動" in r.text
    assert _row() == before


def test_rounds_limit_blocks_review_edit_and_leaves_it_to_superadmin(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    d, _s, _u = _row()
    d["approval"]["reviewRounds"] = C.REVIEW_ROUNDS_LIMIT
    import db
    c = db.get_db(); c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    _set_mode(2)
    r = _edit(client, hs[0])
    assert r.status_code == 409 and "上限" in r.text and _row()[0]["items"][0]["qty"] == 2


# ── 伺服器自有欄位、同交易稽核、編輯紀錄 ─────────────────────────────────────────────────
def test_server_owned_fields_come_from_the_database_not_the_client(client, make_user):
    doc = dict(_doc(), dealTag="洽談中", settlement={"status": "未精算", "x": 1}, clauseTitles={"a": "原條款"}, salesPerson="原業務",
               caseRecord={"roles": {"sales": "a"}, "payment": {"paid": 0}})
    hs, names = _seed(client, make_user, tiers=1, doc=doc)
    _set_mode(2)
    db_before, _s, _u = _row()

    def forge(d):
        d.update(dealTag="已成案", settlement={"status": "已結案"}, clauseTitles={"a": "被改"}, salesPerson="別人", status="已送出",
                 editHistory=[{"rev": 99}], locationIdentity={"x": 1})
        d["caseRecord"] = {"roles": {"sales": "z"}, "payment": {"paid": 999}}
        d["approval"] = {"status": "approved", "tiers": []}

    r = _edit(client, hs[0], qty=9, mutate=forge)
    assert r.status_code == 200, r.text
    d, status, _u = _row()
    assert d["dealTag"] == "洽談中" and d["settlement"] == db_before["settlement"] and d["clauseTitles"] == {"a": "原條款"}
    assert d["salesPerson"] == "原業務" and d["caseRecord"] == db_before["caseRecord"] and status == "待審核"
    assert d.get("approval", {}).get("status") != "approved" and d["approval"]["tiers"], "用戶端送的 approval 不採用"
    assert "locationIdentity" not in d and [h.get("rev") for h in d["editHistory"]] == [1]
    assert d["items"][0]["qty"] == 9


def test_edit_history_and_audit_are_written_in_the_same_transaction_as_the_save(client, make_user, monkeypatch):
    hs, names = _seed(client, make_user, tiers=1)
    _set_mode(2)
    r = _edit(client, hs[0], qty=9, note="下修數量")
    assert r.status_code == 200, r.text
    d, _s, _u = _row()
    h = d["editHistory"][-1]
    assert h["type"] == "review_edit" and h["by"] == names[0] and h.get("changes"), h
    a = _audits("quotation.review_edit")
    assert len(a) == 1 and a[0]["username"] == names[0]
    det = json.loads(a[0]["detail"])
    assert det["fpBefore"] != det["fpAfter"] == C.content_fingerprint(d) and det["note"] == "下修數量"
    # 稽核寫不進去 ⇒ 存檔一起回滾（不是 commit 後吞錯的 _audit）
    hs2, _n = hs, names
    before = _row()
    monkeypatch.setattr(C, "audit_in_txn", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("audit down")))
    g = _get(client, hs[0])
    g["data"]["items"][0]["qty"] = 11
    with pytest.raises(Exception):
        client.post("/api/quotations/%s/review-edit" % NO, headers=hs[0], json={"data": g["data"], "expectedFp": g["contentFp"]})
    assert _row() == before, "稽核失敗 ⇒ 存檔回滾"


def test_denormalized_columns_follow_the_edit_but_ownership_does_not(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    _set_mode(2)
    import db
    c = db.get_db()
    c.execute("UPDATE quotations SET sales_person='原業務', sales_person_id=NULL WHERE quote_no=?", (NO,)); c.commit(); c.close()
    r = _edit(client, hs[0], qty=9, mutate=lambda d: d.update(customerName="乙公司", projectName="新專案", salesPerson="別人", tot={"total": 777, "pretax": 740}))
    assert r.status_code == 200, r.text
    c = db.get_db()
    row = c.execute("SELECT customer_name, project_name, total, pretax, sales_person, sales_person_id FROM quotations WHERE quote_no=?", (NO,)).fetchone()
    c.close()
    assert (row["customer_name"], row["project_name"]) == ("乙公司", "新專案") and row["total"] == 777
    assert row["sales_person"] == "原業務" and row["sales_person_id"] is None


# ── J1：signedReasonEntries ───────────────────────────────────────────────────────────
def test_every_sign_records_signed_reason_entries_from_the_server_algorithm(client, make_user):
    from modules.case import quote_terms as QT
    hs, names = _seed(client, make_user, tiers=1)
    _approve(client, hs[0])
    d, _s, _u = _row()
    e = d["approval"]["tiers"][0]["approvers"][0]
    assert e["signedReasonEntries"] == QT.current_reason_entries(d)
    assert all(set(x) <= {"key", "text", "margin", "value"} for x in e["signedReasonEntries"]), "只存 {key,text}（含 S2b 判定欄位）"


def test_review_edit_resign_records_reason_entries_of_the_new_version(client, make_user):
    from modules.case import quote_terms as QT
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _funnel_edit(_qty(5))
    assert _edit(client, hs[0], qty=9).status_code == 200
    d, _s, _u = _row()
    assert d["approval"]["tiers"][0]["approvers"][0]["signedReasonEntries"] == QT.current_reason_entries(d)


def test_reason_entries_failure_never_breaks_signing(client, make_user, monkeypatch):
    hs, names = _seed(client, make_user, tiers=1)
    monkeypatch.setattr("modules.case.quote_terms.current_reason_entries", lambda d: (_ for _ in ()).throw(RuntimeError("settings down")))
    _approve(client, hs[0])
    e = _row()[0]["approval"]["tiers"][0]["approvers"][0]
    assert e["status"] == "approved" and "signedReasonEntries" not in e


# ── K3：旗標成立時 expectedFp＋choice 一律必填（不受 EXPECTED_FP_REQUIRED 影響）─────────────────────
def _approve_raw(client, h, **body):
    return client.post("/api/quotations/%s/approve" % NO, headers=h, json=body)


def test_reconfirm_flag_requires_fp_and_choice_keep(client, make_user):
    """H7：「旗標成立未帶 choice ⇒ 409」。"""
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _funnel_edit(_qty(5))                                                     # B（ap0）回待複查
    fp = _get(client, hs[0])["contentFp"]
    assert C.EXPECTED_FP_REQUIRED is False, "K3 與全域開關無關：開關關著也要擋"
    r = _approve_raw(client, hs[0])
    assert r.status_code == 409 and r.headers.get("X-Approve-Flags") == "reconfirm", (r.status_code, r.text)
    assert _approve_raw(client, hs[0], expectedFp=fp).status_code == 409, "有 fp 沒 choice"
    assert _approve_raw(client, hs[0], choice="keep").status_code == 409, "有 choice 沒 fp"
    assert _approve_raw(client, hs[0], expectedFp=fp, choice="edit").status_code == 400, "要改內容走 review-edit"
    assert _approve_raw(client, hs[0], expectedFp="1:" + "0" * 32, choice="keep").status_code == 409, "fp 不符"
    es, _ap, _st = _entries()
    assert es[0]["status"] == "pending", "以上都沒簽成"
    r = _approve_raw(client, hs[0], expectedFp=fp, choice="keep", confirmNote="看過新數量")
    assert r.status_code == 200, r.text
    es, _ap, _st = _entries()
    assert es[0]["status"] == "approved" and es[0]["signedFp"] == fp
    det = json.loads(_audits("quotation.approve")[-1]["detail"])
    assert det["flags"] == ["reconfirm"] and det["choice"] == "keep" and det["fp"] == fp and det["confirmNote"] == "看過新數量"


def test_delegated_and_reassigned_flags_require_choice_only_when_mode_is_on(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    dg, dpw = make_user(username="fp_dg", role="admin")
    import db
    c = db.get_db()
    c.execute("INSERT INTO approval_delegates (delegator_username, delegate_username, start_date, end_date, active, created_at, updated_at) "
              "VALUES (?,?,?,?,1,'2026-11-01','2026-11-01')", (names[0], dg, "2026-01-01", "2099-12-31")); c.commit(); c.close()
    dh = _login(client, dg, dpw)
    fp = _get(client, dh)["contentFp"]
    _set_mode(2)
    r = _approve_raw(client, dh, expectedFp=fp)
    assert r.status_code == 409 and r.headers.get("X-Approve-Flags") == "delegated"
    r = _approve_raw(client, dh, expectedFp=fp, choice="keep")
    assert r.status_code == 200, r.text


def test_reassigned_flag(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    d, _s, _u = _row()
    d["approval"]["tiers"][0]["approvers"][0]["reassignedFrom"] = "someone"
    import db
    c = db.get_db(); c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    fp = _get(client, hs[0])["contentFp"]
    _set_mode(2)
    r = _approve_raw(client, hs[0], expectedFp=fp)
    assert r.status_code == 409 and r.headers.get("X-Approve-Flags") == "reassigned"
    assert _approve_raw(client, hs[0], expectedFp=fp, choice="keep").status_code == 200


@pytest.mark.parametrize("code", [0, 1])
def test_flags_do_not_change_approve_when_mode_is_off_or_shadow(client, make_user, code):
    """off／shadow 與今天逐位元相同：旗標存在也不要求 choice（S5 彈窗上線前不能把轉簽／代理的核准鎖死）。"""
    hs, names = _seed(client, make_user, tiers=1)
    d, _s, _u = _row()
    d["approval"]["tiers"][0]["approvers"][0]["reassignedFrom"] = "someone"
    import db
    c = db.get_db(); c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    if code:
        _set_mode(code)
    r = _approve_raw(client, hs[0])
    assert r.status_code == 200, r.text
    det = json.loads(_audits("quotation.approve")[-1]["detail"])
    assert det["flags"] == ["reassigned"] and det["choice"] is None, "稽核照記旗標：量得出「若強制會擋幾次」"


def test_no_flag_approve_is_unchanged_choice_optional(client, make_user):
    hs, names = _seed(client, make_user, tiers=1)
    _set_mode(2)
    assert _approve_raw(client, hs[0], expectedFp=_get(client, hs[0])["contentFp"]).status_code == 200


# ── 純函式：approve_flags、最後一人不自動簽 ───────────────────────────────────────────────
def test_approve_flags_pure():
    assert C.approve_flags({"username": "b"}, "b") == []
    assert C.approve_flags({"username": "b", "reconfirm": True}, "b") == ["reconfirm"]
    assert C.approve_flags({"username": "b", "reassignedFrom": "a"}, "b") == ["reassigned"]
    assert C.approve_flags({"username": "b"}, "x") == ["delegated"]
    assert C.approve_flags({"username": "b", "reconfirm": True, "reassignedFrom": "a"}, "x") == ["reconfirm", "reassigned", "delegated"]
    assert C.approve_flags(None, "x") == []


def test_in_memory_last_pending_editor_is_not_resigned_but_made_pending():
    d = {"items": [{"qty": 3}], "approval": {"currentTier": 2, "contentFp": "1:old", "tiers": [
        {"approvers": [{"username": "t1", "status": "approved"}]},                       # 舊單：沒有 signedFp，永不作廢
        {"approvers": [{"username": "t2", "status": "approved", "signedFp": "1:old"}]}]}}
    changed, notes = C.reconcile_in_memory(d, "2026-11-07T00:00:00", {"username": "t2"}, C.SOURCE_REVIEW_EDIT, status="簽核中", enabled=True)
    a = d["approval"]["tiers"][1]["approvers"][0]
    assert changed and a["status"] == "pending" and a["reconfirm"] and "signedFp" in a and a["prevSignedFp"] == "1:old"
    assert d["approval"]["currentTier"] == 1 and d["approval"]["tiers"][0]["approvers"][0]["status"] == "approved"
    log = d["approval"]["changeLog"][-1]
    assert log["resigned"] == [] and log["editorPending"] == ["t2"] and log["invalidated"] == []
    assert not d["approval"].get("reviewRounds"), "沒有作廢任何他人的簽 ⇒ 不加輪"


def test_in_memory_resign_when_someone_else_still_pending():
    d = {"items": [{"qty": 3}], "approval": {"currentTier": 0, "contentFp": "1:old", "tiers": [
        {"approvers": [{"username": "t1", "status": "pending", "reconfirm": True}]},
        {"approvers": [{"username": "t2", "status": "pending"}]}]}}
    C.reconcile_in_memory(d, "2026-11-07T00:00:00", {"username": "t1"}, C.SOURCE_REVIEW_EDIT, status="簽核中", enabled=True, reason_entries=[{"key": "k", "text": "t"}])
    a = d["approval"]["tiers"][0]["approvers"][0]
    assert a["status"] == "approved" and a["signedFp"] == C.content_fingerprint(d) and a["signedReasonEntries"] == [{"key": "k", "text": "t"}]
    assert d["approval"]["currentTier"] == 1


def test_review_edit_server_owned_key_list_is_pinned():
    """S0 掃描器把 `q[_k]=d[_k]` 的迴圈變數視為「另守」——這題就是那個守門：伺服器自有鍵＝排除清單（扣掉另行處理的 approval／editHistory）＋這 5 個。"""
    from modules.case.api import quotations as Q
    assert set(Q._REVIEW_EDIT_SERVER_KEYS) == (C.EXCLUDED_KEYS - {"approval", "editHistory"}) | {"dealTag", "settlement", "caseRecord", "historical", "salesPerson"}
