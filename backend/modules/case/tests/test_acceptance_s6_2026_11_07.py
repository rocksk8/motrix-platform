# -*- coding: utf-8 -*-
"""簽核二擇一 S6 驗收收尾：`reconfirm_mode` 翻 on 之前的最後閘門（規格 H5 S6／H6／H7；K2 影子統計）。

這支檔案做四件事：
1. **H7 逐句對應表**（`H7_MAP`）：規格 H7 的每一句驗收字句 ⇒ 至少一個真的存在的測試（`test_h7_every_sentence_is_mapped_to_existing_tests` 用 ast 查證）。
2. **多層 HTTP E2E**：三層（T1、T2 已簽，T3＝C 編輯）完整走到核准；轉簽、代理成立旗標但不作廢任何簽；
   列表快速核准遇旗標（HTTP 層：409＋標頭、帶 choice 後成功；瀏覽器層見 S5 e2e／S4b 組合題）。
3. **稽核標籤**：「知情核准」（旗標成立仍選維持）、「自改自簽」（H6-3：唯一簽核人自己改）＋稽核頁篩選 `tag`。
4. **旗標切換演練** off→shadow→on：影子期間只記錄、統計查詢唯讀且僅超管、翻 on 後補追一輪、S3a 五輪上限與 `reconfirmSuspended` 超管通知。
"""
import ast
import json
from pathlib import Path

import pytest

from modules.case import content_fp as C
from modules.case.tests.test_content_fp_s1_2026_11_06 import NO, _login, _row, _seed
from modules.case.tests.test_reconcile_txn_s3b_2026_11_06 import (
    _HS, _approve, _audits, _entries, _fresh_mode_cache, _funnel_edit, _notes, _qty, _set_mode, _signed_first_of_two)
from modules.case.tests.test_review_edit_s4_2026_11_07 import _approve_raw, _edit, _get, _three_tiers_two_signed
from tests._requires import requires_module

pytestmark = requires_module("case", "S6 驗收：打 M01 的簽核、複查編輯、稽核頁端點")

_ = _fresh_mode_cache

# ══ 1. H7 逐句對應 ═══════════════════════════════════════════════════════════════════════════════════
_T = Path(__file__).resolve().parent                       # backend/modules/case/tests
_B = _T.parents[2]                                         # backend
_S1, _S3A, _S3B = "test_content_fp_s1_2026_11_06.py", "test_reconcile_in_memory_s3a_2026_11_06.py", "test_reconcile_txn_s3b_2026_11_06.py"
_S4, _S5 = "test_review_edit_s4_2026_11_07.py", "test_approve_choice_s5_2026_11_07.py"
_S6 = "test_acceptance_s6_2026_11_07.py"
_E5 = "../../../tests/test_e2e_approve_choice_s5_2026_11_07.py"

#: 規格 H7 原句（逐字）→ [(檔案, 測試函式名)]。新增／改寫 H7 句子時，這張表要同步（測試會驗每個函式都存在）。
H7_MAP = [
    ("簽核人 B 簽過後，任何人改了 `data_json`（非排除鍵）⇒ B 的條目回 pending 並標「需複查」，B 與送審人收到通知，內容變動者與區塊名可在簽核畫面看到。",
     [(_S3B, "test_on_funnel_edit_invalidates_the_signed_layer_notifies_and_audits"),
      (_S5, "test_get_exposes_reconfirm_review_for_the_pending_entry"),
      (_S6, "test_non_approver_edit_shows_who_and_which_block_to_the_signer")]),
    ("只動排除清單內的鍵（簽核本身、稽核、簿記）⇒ **不**觸發複查（突變控制：把排除鍵搬進內容，測試必須翻面）。",
     [(_S3B, "test_on_only_excluded_keys_do_not_invalidate_but_dealtag_does"),
      (_S1, "test_mutation_control_exclusion_list_really_drives_the_result")]),
    ("B 按「審核通過」時指紋與載入時不同 ⇒ 409；旗標成立未帶 `choice` ⇒ 409。",
     [(_S1, "test_approve_with_stale_fp_is_409_and_changes_nothing"),
      (_S4, "test_reconfirm_flag_requires_fp_and_choice_keep")]),
    ("B 複查選「維持」＝簽在目前指紋；選「編輯」＝存檔後 B 的簽視為新版，其他已簽層回 pending；C 收到「B 編輯」通知並看到新版。",
     [(_S5, "test_keep_with_new_reason_needs_note_409_then_ok_and_audited"),
      (_S4, "test_reviewer_who_had_signed_is_resigned_on_the_new_version_and_keeps_requester"),
      (_S4, "test_first_time_pending_editor_is_not_auto_signed_and_other_signed_layers_return_to_pending"),
      (_E5, "test_queue_edit_choice_goes_to_form_review_edit_and_resigns_the_editor")]),
    ("三層（T1、T2 已簽，T3＝C 編輯）：T1、T2 依序複查，之後才輪 T3。",
     [(_S6, "test_three_layer_full_cycle_t1_t2_review_in_order_then_t3"),
      (_S3A, "test_three_tier_t1_t2_signed_t3_edits_both_pending_current_tier_zero")]),
    ("轉簽、代理代簽成立旗標、跳提示；不作廢任何簽。",
     [(_S4, "test_delegated_and_reassigned_flags_require_choice_only_when_mode_is_on"),
      (_S6, "test_reassign_raises_flag_but_invalidates_no_signature"),
      (_S6, "test_delegate_raises_flag_but_invalidates_no_signature"),
      (_E5, "test_form_reassigned_flag_shows_dialog_and_keeps"),
      (_E5, "test_queue_quick_approve_of_flagged_item_is_not_stuck_on_409"),
      (_S6, "test_list_quick_approve_of_flagged_item_http_path_is_409_then_succeeds")]),
    ("送審人不能 `review-edit`；非當層待簽人不能；無金額權限不能；`is_signed` 單不能。",
     [(_S4, "test_submitter_cannot_review_edit"), (_S4, "test_non_current_tier_approver_cannot"),
      (_S4, "test_user_without_quote_money_visibility_cannot"), (_S4, "test_is_signed_alt_quote_cannot")]),
    ("解鎖編輯、轉簽既有測試**逐位元不變**；旗標關閉時全套行為與今天相同。",
     [(_S4, "test_superadmin_is_sent_to_unlock_edit"), ("test_approval_detail_and_reassign_edges.py", "test_reassign_refuses_an_unreadable_chain_without_needing_m05"),
      (_S3B, "test_off_funnel_edit_changes_nothing_in_the_approval"), (_S4, "test_flags_do_not_change_approve_when_mode_is_off_or_shadow"),
      (_S6, "test_drill_off_shadow_on_with_cap_and_suspended_notice")]),
    ("舊單（無 `signedFp`）核准流程不受影響。",
     [(_S1, "test_legacy_entries_without_signed_fp_are_never_stale"), (_S3B, "test_legacy_entries_without_signed_fp_are_never_invalidated"),
      (_S1, "test_approve_without_expected_fp_still_works_while_not_required")]),
]
H7_SENTENCE_COUNT = 9                                     # 規格 H7 的句數（H7 是九條）


def _defs(path: Path) -> set:
    return {n.name for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_h7_every_sentence_is_mapped_to_existing_tests():
    assert len(H7_MAP) == H7_SENTENCE_COUNT, "H7 句數變了 ⇒ 對應表要同步"
    assert len({s for s, _ in H7_MAP}) == len(H7_MAP)
    missing = []
    for sent, refs in H7_MAP:
        assert refs, "這句沒有任何對應測試：" + sent
        for f, name in refs:
            p = (_T / f).resolve() if f.startswith("..") else (_T / f)
            if not p.exists() or name not in _defs(p):
                missing.append("%s::%s" % (f, name))
    assert not missing, "對應表指到不存在的測試：\n  " + "\n  ".join(missing)


def test_h7_map_check_has_a_positive_control():
    """對照：對應表檢查器真的能抓到不存在的測試名（防止 `_defs` 永遠回傳全部而空過）。"""
    assert "test_h7_every_sentence_is_mapped_to_existing_tests" in _defs(Path(__file__))
    assert "test_this_name_does_not_exist_anywhere" not in _defs(_T / _S4)


# ══ 2. 多層 E2E（HTTP）═══════════════════════════════════════════════════════════════════════════════
def test_three_layer_full_cycle_t1_t2_review_in_order_then_t3(client, make_user):
    """H7：三層（T1、T2 已簽，T3＝C 編輯）：T1、T2 依序複查，之後才輪 T3——一路走到全部核准，沿途稽核／通知／簽章都對。"""
    hs, names = _three_tiers_two_signed(client, make_user)
    su, _pw = make_user(username="fp_su", role="superadmin")
    r = _edit(client, hs[2], qty=9)                                       # C 編輯（首次待簽，不自動簽）
    assert r.status_code == 200, r.text
    es, ap, _st = _entries()
    assert [e["status"] for e in es] == ["pending"] * 3 and ap["currentTier"] == 0
    assert es[0]["reconfirm"] and es[1]["reconfirm"] and not es[2].get("reconfirm")

    # 順序：T2、T3 都不能搶在 T1 前（待簽人不是他）
    for h in (hs[1], hs[2]):
        assert _approve_raw(client, h, expectedFp=_get(client, hs[0])["contentFp"], choice="keep").status_code == 403
    # T1 複查：選維持（旗標成立）
    fp = _get(client, hs[0])["contentFp"]
    assert _approve_raw(client, hs[0], expectedFp=fp).status_code == 409                    # 沒帶 choice
    assert _approve_raw(client, hs[0], expectedFp=fp, choice="keep").status_code == 200
    es, ap, _st = _entries()
    assert es[0]["status"] == "approved" and es[0]["signedFp"] == fp and ap["currentTier"] == 1
    assert _notes(names[0], "approval_reconfirm")[0]["is_read"], "T1 複查完，自己的待複查通知失效"
    # T2 複查
    assert _approve_raw(client, hs[1], expectedFp=fp, choice="keep").status_code == 200
    es, ap, st = _entries()
    assert es[1]["status"] == "approved" and ap["currentTier"] == 2
    # T3（C）：首次待簽者編輯過、沒有旗標，正常核准即收尾
    r = _approve_raw(client, hs[2], expectedFp=fp)
    assert r.status_code == 200 and r.json()["allDone"] is True, r.text
    es, ap, st = _entries()
    assert [e["status"] for e in es] == ["approved"] * 3 and all(e["signedFp"] == fp for e in es), "三層都簽在最後版本"
    d, _s, _u = _row()
    assert C.content_fingerprint(d) == fp and d["items"][0]["qty"] == 9
    assert ap["reviewRounds"] == 1, "整段只算一輪"
    # 稽核：編輯 1、作廢 1、核准（T1、T2 帶『知情核准』標籤；C 沒旗標 ⇒ 無標籤）
    assert len(_audits("quotation.review_edit")) == 1 and len(_audits("quotation.reconfirm")) == 1
    tags = [json.loads(a["detail"]).get("tag") for a in _audits("quotation.approve")]
    assert tags[-3:] == ["informed", "informed", None], tags
    assert not _notes(su, "approval_self_edit_sign"), "三層不是自改自簽"


def test_non_approver_edit_shows_who_and_which_block_to_the_signer(client, make_user):
    """H6-2：非簽核人（財務／工務）改款項 ⇒ 簽核人收到「你簽過的單內容有變」，訊息帶誰改、哪個區塊；稽核有操作者。"""
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _funnel_edit(_qty(9), actor={"id": 7, "username": "fin_x", "display_name": "財務小王"})
    msg = _notes(names[0], "approval_reconfirm")[0]["message"]
    assert "財務小王" in msg and "items" in msg
    a = _audits("quotation.reconfirm")
    assert a[0]["username"] == "fin_x" and json.loads(a[0]["detail"])["blocks"] == ["items"]
    rv = _get(client, hs[0])["approveReview"]
    assert rv["flags"] == ["reconfirm"] and rv["changedBlocks"] == ["items"], "簽核畫面看得到哪個區塊變了"


def _add_delegate(delegator, delegate):
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO approval_delegates (delegator_username, delegate_username, start_date, end_date, active, created_at, updated_at) "
                  "VALUES (?,?,?,?,1,'2026-11-01','2026-11-01')", (delegator, delegate, "2026-01-01", "2099-12-31"))
        c.commit()
    finally:
        c.close()


def test_reassign_raises_flag_but_invalidates_no_signature(client, make_user):
    """H7：轉簽成立旗標、跳提示；不作廢任何簽。T1 已簽、T2 被超管轉簽給 N ⇒ T1 簽章原封不動；N 核准要帶 choice，稽核有旗標與標籤。"""
    hs, names = _signed_first_of_two(client, make_user)
    su, spw = make_user(username="fp_su", role="superadmin")
    n, npw = make_user(username="fp_new", role="admin")
    _set_mode(2)
    before, _ap, _s = _entries()
    t1_before = dict(before[0])
    r = client.post("/api/approval-queue/reassign", headers=_login(client, su, spw),
                    json={"type": "quotation", "id": NO, "to_username": n, "reason": "原簽核人請假"})
    assert r.status_code == 200, r.text
    es, ap, _st = _entries()
    assert es[0] == t1_before, "已簽層的條目逐欄不變（簽章、signedFp、signedKeyHashes 都在）"
    assert es[0]["status"] == "approved" and not es[0].get("reconfirm")
    assert es[1]["username"] == n and es[1]["reassignedFrom"] == names[1] and ap["currentTier"] == 1
    nh = _login(client, n, npw)
    fp = _get(client, nh)["contentFp"]
    r = _approve_raw(client, nh, expectedFp=fp)
    assert r.status_code == 409 and r.headers.get("X-Approve-Flags") == "reassigned"
    assert _approve_raw(client, nh, expectedFp=fp, choice="keep").status_code == 200
    det = json.loads(_audits("quotation.approve")[-1]["detail"])
    assert det["flags"] == ["reassigned"] and det["choice"] == "keep" and det["tag"] == "informed"
    es, _ap, _st = _entries()
    assert es[0]["status"] == "approved" and es[0]["signedFp"] == t1_before["signedFp"], "核准完 T1 仍是原簽章"


def test_delegate_raises_flag_but_invalidates_no_signature(client, make_user):
    hs, names = _signed_first_of_two(client, make_user)
    dg, dpw = make_user(username="fp_dg", role="admin")
    _add_delegate(names[1], dg)
    _set_mode(2)
    t1_before = dict(_entries()[0][0])
    dh = _login(client, dg, dpw)
    fp = _get(client, dh)["contentFp"]
    r = _approve_raw(client, dh, expectedFp=fp)
    assert r.status_code == 409 and r.headers.get("X-Approve-Flags") == "delegated"
    assert _entries()[0][0] == t1_before, "409 與之後的代簽都不動 T1"
    assert _approve_raw(client, dh, expectedFp=fp, choice="keep").status_code == 200
    es, ap, _st = _entries()
    assert es[0] == t1_before and es[1]["status"] == "approved"
    assert json.loads(_audits("quotation.approve")[-1]["detail"])["flags"] == ["delegated"]
    assert ap.get("reviewRounds", 0) == 0, "代理不是內容變動，不計複查輪次"


def test_list_quick_approve_of_flagged_item_http_path_is_409_then_succeeds(client, make_user):
    """列表快速核准（沒載詳情、沒帶指紋）遇旗標單：mode=on ⇒ 409＋旗標標頭（畫面據此載詳情再彈窗）；帶詳情的指紋與 choice 後成功。
    瀏覽器層的『不卡死』在 S5 e2e `test_queue_quick_approve_of_flagged_item_is_not_stuck_on_409`（S4b 加列表指紋後的組合題由 S4b 分支自帶）。"""
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _funnel_edit(_qty(9))                                                  # 內容變 ⇒ T1 待複查（reconfirm 旗標）
    r = client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={})
    assert r.status_code == 409 and "reconfirm" in r.headers.get("X-Approve-Flags", "")
    det = client.get("/api/approval-queue/detail", params={"type": "quotation", "id": NO}, headers=hs[0])
    assert det.status_code == 200, det.text
    rv = det.json()["approveReview"]
    assert rv["flags"] == ["reconfirm"] and rv["contentFp"]
    assert _approve_raw(client, hs[0], expectedFp=rv["contentFp"], choice="keep").status_code == 200
    assert _entries()[0][0]["status"] == "approved"


# ══ 3. 稽核標籤與稽核頁篩選 ═══════════════════════════════════════════════════════════════════════════
def _audit_get(client, h, path="/api/audit-log", **params):
    r = client.get(path, headers=h, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_single_tier_review_edit_is_annotated_self_edit_sign_and_tells_superadmin_without_blocking(client, make_user):
    """H6-3：編輯者是唯一未簽層且前面無已簽層（整單只有他一個簽核人）⇒ 稽核加註「自改自簽」＋通知最高管理者；**不阻擋**（200）。"""
    hs, names = _seed(client, make_user, tiers=1)
    su, spw = make_user(username="fp_su", role="superadmin")
    _set_mode(2)
    r = _edit(client, hs[0], qty=9)
    assert r.status_code == 200, r.text                                  # 不阻擋
    det = json.loads(_audits("quotation.review_edit")[0]["detail"])
    assert det["selfEditSign"] is True and det["tag"] == "self_edit_sign"
    n = _notes(su, "approval_self_edit_sign")
    assert len(n) == 1 and "自改自簽" in n[0]["message"] and n[0]["link"] == "approval-queue.html"
    assert _notes(names[0], "approval_self_edit_sign") == [] and _notes("fp_req", "approval_self_edit_sign") == [], "只通知最高管理者"
    es, _ap, _st = _entries()
    assert es[0]["status"] == "pending", "不自動簽（H9-①）：自己仍要再按一次核准——只是這件事被標了出來"


def test_multi_tier_review_edit_is_not_self_edit_sign(client, make_user):
    hs, names = _seed(client, make_user, tiers=2)
    su, _pw = make_user(username="fp_su", role="superadmin")
    _set_mode(2)
    assert _edit(client, hs[0], qty=9).status_code == 200
    det = json.loads(_audits("quotation.review_edit")[0]["detail"])
    assert "tag" not in det and "selfEditSign" not in det
    assert _notes(su, "approval_self_edit_sign") == []


def test_self_edit_sign_helper_counts_every_approver_entry():
    one = [{"approvers": [{"username": "a"}]}]
    assert C.self_edit_sign(one) is True
    assert C.self_edit_sign(one + [{"approvers": [{"username": "b"}]}]) is False
    assert C.self_edit_sign([{"approvers": [{"username": "a"}, {"username": "b"}]}]) is False, "同層兩人＝有第二雙眼"
    assert C.self_edit_sign([]) is False and C.self_edit_sign(None) is False


def test_audit_page_filters_informed_and_self_edit_sign(client, make_user):
    """稽核頁篩選：`tag=informed`／`tag=self_edit_sign`；標籤只會命中各自的 action；與其他篩選 AND；未知標籤 400；不改權限。"""
    # 一張自改自簽單（NO）＋同單的知情核准在另一張單
    hs, names = _seed(client, make_user, tiers=1)
    su, spw = make_user(username="fp_su", role="superadmin")
    sh = _login(client, su, spw)
    _set_mode(2)
    assert _edit(client, hs[0], qty=9).status_code == 200                # → review_edit（自改自簽）
    fp = _get(client, hs[0])["contentFp"]
    assert _approve_raw(client, hs[0], expectedFp=fp, choice="keep").status_code == 200   # 沒旗標：choice 帶了無害，不算知情核准
    assert [i["action"] for i in _audit_get(client, sh, tag="informed")["items"]] == [], "沒有旗標的核准不是知情核准"
    got = _audit_get(client, sh, tag="self_edit_sign")
    assert [i["action"] for i in got["items"]] == ["quotation.review_edit"] and got["total"] == 1
    # 造一筆知情核准：兩層、T1 簽、內容被改、T1 複查選維持
    import db
    c = db.get_db()
    c.execute("DELETE FROM quotations WHERE quote_no=?", (NO,)); c.commit(); c.close()
    for u in ("fp_ap0", "fp_req"):                                       # `_seed` 會重建同名使用者：先清掉
        c = db.get_db(); c.execute("DELETE FROM users WHERE username=?", (u,)); c.commit(); c.close()
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _funnel_edit(_qty(11))
    fp = _get(client, hs[0])["contentFp"]
    assert _approve_raw(client, hs[0], expectedFp=fp, choice="keep", confirmNote="看過了").status_code == 200
    inf = _audit_get(client, sh, tag="informed")
    assert len(inf["items"]) == 1 and inf["items"][0]["action"] == "quotation.approve"
    assert json.loads(inf["items"][0]["detail"])["confirmNote"] == "看過了"
    # AND：標籤＋不相干的 action ⇒ 空；標籤＋案件單號 ⇒ 命中
    assert _audit_get(client, sh, tag="informed", action="quotation.review_edit")["items"] == []
    assert len(_audit_get(client, sh, tag="informed", case_no=NO)["items"]) == 1
    # 分層樹同一套篩選
    tree = _audit_get(client, sh, "/api/audit-log/tree", level="module", tag="informed")
    assert [(i["key"], i["count"]) for i in tree["items"]] == [("quotation", 1)]
    # 未知標籤 ⇒ 400（不靜默忽略成「全部」）
    assert client.get("/api/audit-log", headers=sh, params={"tag": "nope"}).status_code == 400
    assert client.get("/api/audit-log/tree", headers=sh, params={"tag": "nope"}).status_code == 400
    # LIKE 萬用字元不能繞出標籤（標籤白名單；字面裡的底線已跳脫）
    assert client.get("/api/audit-log", headers=sh, params={"tag": "self%"}).status_code == 400
    # 權限不變：沒有稽核模組權限的帳號仍被擋
    nm, npw = make_user(username="fp_nomod", role="admin", modules=[])
    assert client.get("/api/audit-log", headers=_login(client, nm, npw), params={"tag": "informed"}).status_code == 403


def test_audit_tag_literal_contract_between_writer_and_filter():
    """寫入端與篩選端的字面約定：detail 以 `json.dumps(ensure_ascii=False)` 序列化，篩選比對的是 `"tag": "<標籤>"`。"""
    from routers import system as S
    assert S._AUDIT_TAGS == {"informed": "quotation.approve", "self_edit_sign": "quotation.review_edit"}
    src = (_B / "modules" / "case" / "api" / "quotations.py").read_text(encoding="utf-8")
    for tag, action in S._AUDIT_TAGS.items():
        assert '"tag": "%s"' % tag in src, "寫入端沒有寫 %s 標籤" % tag
    assert json.dumps({"tag": "informed"}, ensure_ascii=False) == '{"tag": "informed"}'


# ══ 4. 旗標切換演練 off → shadow → on ═══════════════════════════════════════════════════════════════
def _stats(client, h, **params):
    return client.get("/api/quotations/reconfirm-shadow-stats", headers=h, params=params)


def test_drill_off_shadow_on_with_cap_and_suspended_notice(client, make_user):
    """演練（H4／H6-1④／K2）：
    off（今天）：改內容什麼都不記、統計為 0 ⇒ shadow：只記錄、簽核不動、統計可查（僅超管、唯讀）⇒ on：補追一輪、五輪上限、第六次起暫停＋超管通知。"""
    hs, names = _signed_first_of_two(client, make_user)
    _HS.clear(); _HS.update(dict(zip(names, hs)))
    su, spw = make_user(username="fp_su", role="superadmin")
    sh = _login(client, su, spw)

    # ── off：與今天相同
    _funnel_edit(_qty(5))
    es, ap, st = _entries()
    assert es[0]["status"] == "approved" and not ap.get("shadowLog") and not ap.get("changeLog")
    assert _audits("quotation.reconfirm_shadow") == []
    s0 = _stats(client, sh).json()
    assert s0["mode"] == "off" and s0["events"] == 0 and s0["wouldInvalidateEvents"] == 0 and s0["byBlock"] == []

    # ── shadow：只記錄
    _set_mode(1)
    for q_ in (6, 7):
        _funnel_edit(_qty(q_), actor={"id": 5, "username": "fin_x", "display_name": "財務"})
    _funnel_edit(lambda d: d.__setitem__("dealTag", "hot"), actor={"id": 6, "username": "sales_y", "display_name": "業務"})
    es, ap, st = _entries()
    assert es[0]["status"] == "approved" and ap.get("contentRev", 0) == 0 and ap.get("reviewRounds", 0) == 0, "影子不動簽核、不計輪次"
    assert len(ap["shadowLog"]) == 3 and all(x["wouldInvalidate"] == [names[0]] for x in ap["shadowLog"])
    assert _notes(names[0], "approval_reconfirm") == [], "影子不通知簽核人"
    s1 = _stats(client, sh).json()
    assert s1["mode"] == "shadow" and s1["events"] == 3 and s1["wouldInvalidateEvents"] == 3 and s1["quotes"] == 1
    assert {b["key"]: b["count"] for b in s1["byBlock"]} == {"items": 2, "dealTag": 1}
    assert [b["key"] for b in s1["byUser"]][0] == "fin_x" and {b["key"]: b["count"] for b in s1["bySource"]} == {"funnel": 3}
    assert s1["dealTagShare"] == round(1 / 3, 4) and s1["truncated"] is False
    assert s1["days"] == 7 and sum(d["count"] for d in s1["byDay"]) == 3
    # 統計查詢：唯讀（呼叫前後資料列、稽核列、通知都不變）、僅超管
    before = (_row(), len(_audits("quotation.reconfirm_shadow")), len(_notes()))
    _stats(client, sh, days=3)
    assert (_row(), len(_audits("quotation.reconfirm_shadow")), len(_notes())) == before
    assert _stats(client, hs[0]).status_code == 403 and client.get("/api/quotations/reconfirm-shadow-stats").status_code in (401, 403)
    assert _stats(client, sh, days=0).json()["days"] == 1 and _stats(client, sh, days=999).json()["days"] == 90

    # 已知偏差（已記入 CHANGELOG S3b／S6 已知限制）：K 的 Q5 裁定 shadow→off「不算放寬、立即生效」，但設定登錄的 `loosen="down"` 是整數方向判定，
    # 任何調小都走放寬流程（確認期間＋雙人）。後果只是「停止量測」要等確認期間，偏保守、不影響簽核安全；要照 Q5 做需改通用的 `_loosens`（動到全部設定欄位），不在 S6。
    # 這題鎖住現況：之後若有人改成 Q5 的行為，這裡會翻紅、迫使同步更新文件。
    assert _set_mode(0)["pending"] and C.reconfirm_mode() == "shadow", "shadow→off 目前走放寬流程（偏保守）"

    # ── on：補追一輪（H6／K 補充 5）
    _set_mode(2)
    _approve_as = lambda: _approve(client, hs[0])                       # noqa: E731
    _funnel_edit(_qty(8))
    es, ap, st = _entries()
    assert es[0]["status"] == "pending" and es[0]["reconfirm"] and ap["reviewRounds"] == 1, "影子期間改了多次，翻 on 後只算 1 輪"
    assert len(_audits("quotation.reconfirm")) == 1 and _notes(names[0], "approval_reconfirm")
    # 五輪上限：第 1 輪已用，再走 4 輪到上限，第 6 次起不再作廢、改通知超管（只一次）
    _approve_as()
    for i in range(C.REVIEW_ROUNDS_LIMIT - 1):
        _funnel_edit(_qty(20 + i))
        assert _entries()[0][0]["status"] == "pending"
        _approve_as()
    assert _entries()[1]["reviewRounds"] == C.REVIEW_ROUNDS_LIMIT
    assert _notes(su, "approval_reconfirm_suspended") == []
    _funnel_edit(_qty(99))
    es, ap, st = _entries()
    assert es[0]["status"] == "approved" and ap["reconfirmSuspended"] is True, "第 6 次不再作廢"
    sus = _notes(su, "approval_reconfirm_suspended")
    assert len(sus) == 1 and sus[0]["link"] == "approval-queue.html"
    assert len(_audits("quotation.reconfirm_suspended")) == 1
    _funnel_edit(_qty(100))
    assert len(_notes(su, "approval_reconfirm_suspended")) == 1, "只在第一次設旗標時通知"
    # 暫停期間讀取端點不再推導『需複查』（畫面與 approve 一致）
    g = _get(client, hs[1])
    ga = g["data"]["approval"]
    assert ga.get("reconfirmSuspended") is True and ga["tiers"][0]["approvers"][0]["status"] == "approved" and not ga["tiers"][0]["approvers"][0].get("reconfirm")
    # 統計在 on 之後仍可查，mode 欄位跟著變
    assert _stats(client, sh).json()["mode"] == "on"



def test_shadow_stats_count_only_edits_that_would_have_interrupted_a_signature(client, make_user):
    """沒有任何人簽過的單被改內容：影子有記一筆（`events`），但「本會作廢」是 0——不計入區塊／來源／操作者分布，否則會高估實際打斷頻率。"""
    hs, names = _seed(client, make_user, tiers=2)                         # 沒人簽
    su, spw = make_user(username="fp_su", role="superadmin")
    _set_mode(1)
    _funnel_edit(_qty(8))                                                 # 第一次對帳只建立基準（沒有簽核送審基準的單）
    _funnel_edit(_qty(9), actor={"id": 5, "username": "fin_x", "display_name": "財務"})
    s = _stats(client, _login(client, su, spw)).json()
    assert s["events"] == 1 and s["wouldInvalidateEvents"] == 0 and s["byBlock"] == [] and s["byUser"] == [] and s["dealTagShare"] == 0.0
