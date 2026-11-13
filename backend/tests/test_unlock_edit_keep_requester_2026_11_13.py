# -*- coding: utf-8 -*-
"""最高管理者解鎖編輯存檔：送審人維持原送審人、已簽的人收到通知、稽核記清楚（fix/unlock-edit-keep-requester，使用者裁示 2026-11-13）。

以前：解鎖存檔把 `approval.requestedBy` 換成這位最高管理者 ⇒ 原送審人看到「他人送審」、不能收回；已簽的層被清掉卻沒有人知道。
現在：①送審人維持原送審人，改內容的人另記 `editedBy`；②簽核鏈重建時，原送審人與改內容的人都不在簽核層裡（不能簽自己的單／自己改的內容）；
③被清掉的已簽簽核人收到站內通知＋信件（＋LINE，預設關），只發給本人；④editHistory 與稽核記：誰改的、原送審人、清掉哪幾層。
"""
import json

import pytest

from tests._requires import requires_module

pytestmark = requires_module("case", "本檔的題打 M01（案件）的報價單解鎖編輯端點與通知")

NO = "MQ-KEEPREQ-001"


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _flow(approvers_by_tier):
    from db import get_db
    conn = get_db()
    try:
        tiers = [{"approvers": [{"username": u, "display_name": u} for u in tier]} for tier in approvers_by_tier]
        conn.execute("INSERT OR REPLACE INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)",
                     ("unified_approval_flow", json.dumps({"tiers": tiers, "includeSubmitterManagerTier": False}, ensure_ascii=False),
                      "2026-11-13T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _seed(status="簽核中", *, requester="ke_req", signed=("ke_a1",), pending=("ke_a2",), with_approval=True):
    """第 1 層 `signed`（已簽）、第 2 層 `pending`（未簽）；`currentTier`＝1。"""
    from db import get_db
    data = {"quoteNo": NO, "customerName": "解鎖客戶", "projectName": "解鎖案", "items": [{"id": "i1", "description": "品項", "qty": 1, "price": 100}]}
    if with_approval:
        data["approval"] = {
            "requestedBy": requester, "requestedByDisplay": requester + "（顯示）", "requestedAt": "2026-11-12T09:00:00", "currentTier": 1,
            "tiers": [{"approvers": [{"username": u, "displayName": u + "（顯示）", "status": "approved", "approvedAt": "2026-11-12T10:00:00"} for u in signed]},
                      {"approvers": [{"username": u, "displayName": u, "status": "pending"} for u in pending]}]}
    conn = get_db()
    try:
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, data_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                     (NO, status, "解鎖客戶", "解鎖案", 100, json.dumps(data, ensure_ascii=False), "2026-11-12", "2026-11-12"))
        conn.commit()
    finally:
        conn.close()


def _state():
    from db import get_db
    conn = get_db()
    try:
        r = conn.execute("SELECT data_json, status FROM quotations WHERE quote_no=?", (NO,)).fetchone()
    finally:
        conn.close()
    return json.loads(r["data_json"]), r["status"]


def _unlock_put(client, headers, desc="品項（改）"):
    return client.put(f"/api/quotations/{NO}", headers=headers, json={
        "status": "待審核",
        "data": {"customerName": "解鎖客戶", "projectName": "解鎖案", "items": [{"id": "i1", "description": desc, "qty": 1, "price": 100}],
                 "_isUnlockEdit": True}})


@pytest.fixture
def world(client, make_user, monkeypatch):
    """使用者＋同步的通知（只讓本模組的 fire 同步跑，其他背景工作略過）＋攔截信件。"""
    from modules.case import quote_edit_notify as QEN
    from modules.case.api import quotations as Q
    users = {}
    for name, role in (("ke_req", "admin"), ("ke_a1", "admin"), ("ke_a2", "admin"), ("ke_sa", "superadmin"), ("ke_sa2", "superadmin")):
        users[name] = make_user(username=name, role=role, modules=["quotation"])
    sent = []
    monkeypatch.setattr(QEN._en, "send_registered", lambda key, **kw: sent.append((key, kw)) or True)

    def fake(target, args=(), kwargs=None, daemon=True):
        if getattr(target, "__module__", "") == "modules.case.quote_edit_notify":
            target(*args, **(kwargs or {}))
        return None                                              # 備份／PDF 快照等其他背景工作略過
    monkeypatch.setattr(Q, "spawn_bg_thread", fake)
    return {"users": users, "sent": sent, "headers": _login(client, *users["ke_sa"])}


def test_requester_is_kept_and_editor_is_recorded_as_edited_by(client, world):
    _flow([["ke_a1"], ["ke_a2"], ["ke_sa"]])
    _seed()
    r = _unlock_put(client, world["headers"])
    assert r.status_code == 200, r.text
    d, status = _state()
    appr = d["approval"]
    assert status == "待審核"
    assert appr["requestedBy"] == "ke_req" and appr["requestedByDisplay"] == "ke_req（顯示）", "送審人要維持原送審人"
    assert appr["editedBy"] == "ke_sa" and appr["isEditApproval"] is True


def test_rebuilt_chain_excludes_both_the_original_requester_and_the_editor(client, world):
    """原送審人不可以變成能簽自己的單；改內容的最高管理者也不簽自己改的內容（以前他是送審人，所以本來就被剔除——行為不變）。"""
    _flow([["ke_a1"], ["ke_req"], ["ke_a2"], ["ke_sa"]])
    _seed()
    assert _unlock_put(client, world["headers"]).status_code == 200
    names = [[a["username"] for a in t["approvers"]] for t in _state()[0]["approval"]["tiers"]]
    assert names == [["ke_a1"], ["ke_a2"]], names
    assert all("ke_req" not in t and "ke_sa" not in t for t in names)


def test_neither_requester_nor_editor_may_self_approve_when_there_are_no_tiers(client, world):
    from db import get_db
    from helpers.tiered_approval import check_no_tier_self_approval
    conn = get_db()
    try:
        appr = {"requestedBy": "ke_req", "editedBy": "ke_sa"}
        assert check_no_tier_self_approval(conn, appr, {"username": "ke_sa"}), "改內容的最高管理者不可自簽（還有另一位最高管理者）"
        assert check_no_tier_self_approval(conn, {"requestedBy": "ke_sa"}, {"username": "ke_sa"}), "舊行為：送審人不可自簽（不變）"
        assert check_no_tier_self_approval(conn, appr, {"username": "ke_sa2"}) is None, "另一位最高管理者可以簽"
        assert check_no_tier_self_approval(conn, {"requestedBy": "ke_req"}, {"username": "ke_sa"}) is None, "一般送審（沒有 editedBy）行為不變"
    finally:
        conn.close()


def test_signed_approvers_are_notified_in_app_and_by_mail_and_only_them(client, world):
    _flow([["ke_a1"], ["ke_a2"]])
    _seed()
    assert _unlock_put(client, world["headers"]).status_code == 200
    from db import get_db
    conn = get_db()
    try:
        rows = conn.execute("SELECT username, message FROM notifications WHERE type='approval_content_edited' AND ref_id=?", (NO,)).fetchall()
    finally:
        conn.close()
    assert [r["username"] for r in rows] == ["ke_a1"], "只通知被清掉的已簽簽核人（未簽的 ke_a2、送審人、修改人都不收這則）"
    assert NO in rows[0]["message"] and "重新簽核" in rows[0]["message"]
    mails = [(k, kw) for k, kw in world["sent"] if k == "approval_content_edited"]
    assert len(mails) == 1 and mails[0][1]["usernames"] == ["ke_a1"], mails
    assert not mails[0][1].get("to_group"), "預設只發給本人，不加群組"
    assert all("金額" not in str(v) and "100" not in str(v) for v in mails[0][1]["rows"]), "信內不放金額"


def test_edit_history_and_audit_record_who_original_requester_and_cleared_layers(client, world):
    _flow([["ke_a1"], ["ke_a2"]])
    _seed(signed=("ke_a1",))
    assert _unlock_put(client, world["headers"]).status_code == 200
    d, _ = _state()
    h = d["editHistory"][-1]
    assert h["by"] == "ke_sa" and h["originalRequester"] == "ke_req" and h["clearedSigners"] == [{"tier": 1, "username": "ke_a1"}], h
    from db import get_db
    conn = get_db()
    try:
        row = conn.execute("SELECT detail FROM audit_log WHERE action='quotation.unlock_edit' AND target_id=? ORDER BY id DESC", (NO,)).fetchone()
    finally:
        conn.close()
    detail = json.loads(row["detail"]) if isinstance(row["detail"], str) else row["detail"]
    assert detail["editedBy"] == "ke_sa" and detail["originalRequester"] == "ke_req" and detail["clearedSigners"] == [{"tier": 1, "username": "ke_a1"}], detail


def test_finished_quote_clears_every_signed_layer_and_notifies_all_of_them(client, world):
    """已送出（簽完）的單解鎖存檔：所有簽過的層都被清掉，每位簽核人各收一則（同一人多層只收一則）。"""
    _flow([["ke_a1"], ["ke_a2"]])
    _seed(status="已送出", signed=("ke_a1",), pending=("ke_a2",))
    d, _ = _state()
    d["approval"]["tiers"][1]["approvers"][0].update(status="approved", approvedAt="2026-11-12T11:00:00")
    from db import get_db
    conn = get_db()
    try:
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO))
        conn.commit()
    finally:
        conn.close()
    assert _unlock_put(client, world["headers"]).status_code == 200
    conn = get_db()
    try:
        users = sorted(r["username"] for r in conn.execute("SELECT username FROM notifications WHERE type='approval_content_edited' AND ref_id=?", (NO,)).fetchall())
    finally:
        conn.close()
    assert users == ["ke_a1", "ke_a2"]
    assert _state()[0]["editHistory"][-1]["clearedSigners"] == [{"tier": 1, "username": "ke_a1"}, {"tier": 2, "username": "ke_a2"}]


def test_legacy_quote_without_an_approval_record_falls_back_to_the_editor_as_requester(client, world):
    """沒有原送審紀錄的舊單：退回舊行為（送審人記為改內容的人），editedBy 仍記；沒有人被清掉 ⇒ 沒有通知。"""
    _flow([["ke_a1"]])
    _seed(status="已送出", with_approval=False)
    assert _unlock_put(client, world["headers"]).status_code == 200
    appr = _state()[0]["approval"]
    assert appr["requestedBy"] == "ke_sa" and appr["editedBy"] == "ke_sa"
    assert _state()[0]["editHistory"][-1]["clearedSigners"] == []
    assert not [k for k, _kw in world["sent"] if k == "approval_content_edited"]


def test_original_requester_can_now_recall_the_edited_quote(client, world, make_user):
    """以前送審人被換成最高管理者 ⇒ 原送審人收回會 403；現在維持原送審人 ⇒ 他可以收回。"""
    _flow([["ke_a1"], ["ke_a2"]])
    _seed()
    assert _unlock_put(client, world["headers"]).status_code == 200
    req_headers = _login(client, *world["users"]["ke_req"])
    r = client.post(f"/api/quotations/{NO}/recall", headers=req_headers)
    assert r.status_code == 200, r.text


def test_signed_layers_helper_ignores_shapes_it_does_not_understand():
    from modules.case import quote_edit_notify as QEN
    assert QEN.signed_layers(None) == [] and QEN.signed_layers({}) == [] and QEN.signed_layers({"tiers": "x"}) == []
    assert QEN.signed_layers({"tiers": [None, {"approvers": [None, {"status": "approved"}, {"username": "u", "status": "pending"}]}]}) == []
    got = QEN.signed_layers({"tiers": [{"approvers": [{"username": "u", "displayName": "U", "status": "approved", "approvedAt": "t"}]}]})
    assert got == [{"tier": 1, "username": "u", "displayName": "U", "approvedAt": "t"}]


def test_new_mail_type_is_registered_in_the_quote_approval_line_group():
    from helpers import line_catalog, mail_types
    assert mail_types.get("approval_content_edited") is not None
    assert line_catalog.group_of("approval_content_edited") == "報價單與簽核"


def test_departed_original_requester_falls_back_to_the_editor(client, world):
    """h9 S1：原送審人已停用 ⇒ 他不能收回、也收不到退件通知，所以退回「沒有原送審紀錄」的行為（送審人記為改內容的人）。"""
    from db import get_db
    conn = get_db()
    try:
        conn.execute("UPDATE users SET active=0 WHERE username='ke_req'")
        conn.commit()
    finally:
        conn.close()
    _flow([["ke_a1"], ["ke_a2"]])
    _seed()
    assert _unlock_put(client, world["headers"]).status_code == 200
    appr = _state()[0]["approval"]
    assert appr["requestedBy"] == "ke_sa" and appr["editedBy"] == "ke_sa"
    assert _state()[0]["editHistory"][-1]["originalRequester"] == "ke_sa"


def test_cleared_signers_come_from_the_value_read_inside_the_write_transaction(client, world, monkeypatch):
    """h9 S2：寫鎖之前讀的那份只用來建簽核層；被清掉的已簽層（通知、editHistory、稽核）以交易內讀到的現值為準。
    這裡讓第一次（鎖前）的計算回空、第二次（交易內）用真的 ⇒ 結果必須是第二次的。"""
    from modules.case import quote_edit_notify as QEN
    real = QEN.signed_layers
    calls = []

    def fake(appr):
        calls.append(1)
        return [] if len(calls) == 1 else real(appr)
    monkeypatch.setattr(QEN, "signed_layers", fake)
    _flow([["ke_a1"], ["ke_a2"]])
    _seed()
    assert _unlock_put(client, world["headers"]).status_code == 200
    assert len(calls) == 2, "鎖前一次、交易內一次"
    assert _state()[0]["editHistory"][-1]["clearedSigners"] == [{"tier": 1, "username": "ke_a1"}]
    assert [kw["usernames"] for k, kw in world["sent"] if k == "approval_content_edited"] == [["ke_a1"]]


def test_reject_final_also_notifies_the_editor_not_only_the_original_requester(client, world):
    """h9 S1（一行加碼）：改這份內容的最高管理者（editedBy）也收到駁回結案通知。"""
    _flow([["ke_a1"], ["ke_a2"]])
    _seed()
    assert _unlock_put(client, world["headers"]).status_code == 200
    r = client.post(f"/api/quotations/{NO}/reject-final", headers=_login(client, *world["users"]["ke_a1"]), json={"note": "不行"})
    assert r.status_code == 200, r.text
    from db import get_db
    conn = get_db()
    try:
        who = sorted(x["username"] for x in conn.execute("SELECT username FROM notifications WHERE type='approval_rejected' AND ref_id=?", (NO,)).fetchall())
    finally:
        conn.close()
    assert who == ["ke_req", "ke_sa"], who


def test_when_the_requester_is_the_only_other_superadmin_recall_is_the_way_out(client, world, make_user):
    """h9 N1：原送審人本身是最高管理者、且另一位最高管理者就是改內容的人、沒有簽核層 ⇒ 兩個人都不能自簽；原送審人收回草稿是唯一出路。"""
    from db import get_db
    from helpers.tiered_approval import check_no_tier_self_approval
    _flow([])
    _seed(requester="ke_sa2", signed=(), pending=())
    assert _unlock_put(client, world["headers"]).status_code == 200
    appr = _state()[0]["approval"]
    assert appr["requestedBy"] == "ke_sa2" and appr["editedBy"] == "ke_sa"
    conn = get_db()
    try:
        assert check_no_tier_self_approval(conn, appr, {"username": "ke_sa"}), "改內容的人不可自簽"
        assert check_no_tier_self_approval(conn, appr, {"username": "ke_sa2"}), "原送審人不可自簽"
    finally:
        conn.close()
    r = client.post(f"/api/quotations/{NO}/recall", headers=_login(client, *world["users"]["ke_sa2"]))
    assert r.status_code == 200, r.text


def _queue_item(client, user):
    q = client.get("/api/approval-queue", headers=_login(client, *user)).json()["queue"]
    return next((it for g in q for it in g["items"] if it.get("quoteNo") == NO), None)


def test_queue_item_carries_edited_by_only_for_unlock_edited_quotes(client, world):
    """N2：待我簽核的卡片要看得到「誰改了內容」；沒被解鎖改過的單，佇列項目沒有 editedBy／editedByDisplay 這兩個鍵（回應不變）。"""
    _flow([["ke_a1"], ["ke_a2"]])
    _seed(status="待審核", signed=(), pending=("ke_a1",))
    before = _queue_item(client, world["users"]["ke_a1"])
    assert before is not None and "editedBy" not in before and "editedByDisplay" not in before, before
    from db import get_db
    conn = get_db()
    try:
        conn.execute("DELETE FROM quotations WHERE quote_no=?", (NO,))
        conn.commit()
    finally:
        conn.close()
    _seed(status="簽核中", signed=("ke_a1",), pending=("ke_a2",))
    assert _unlock_put(client, world["headers"]).status_code == 200
    after = _queue_item(client, world["users"]["ke_a1"])
    assert after is not None, "解鎖改版後第 1 層重簽，ke_a1 應在待簽佇列"
    assert after["editedBy"] == "ke_sa" and after["editedByDisplay"], after
    assert after["requestedBy"] == "ke_req", "送審人欄位仍是原送審人"


def test_pages_show_the_edited_by_row_only_when_edited_by_exists():
    """N2 靜態檢查：兩個畫面都有「修改人」那一行，且以 `editedBy` 為顯示條件（真瀏覽器版放在 e2e 批次）。"""
    from core import source_tree
    q = source_tree.page_file("approval-queue.html").read_text(encoding="utf-8")
    f = source_tree.page_file("quotation-form.html").read_text(encoding="utf-8")
    assert 'data-testid="aq-edited-by"' in q and 'x-show="selected?.editedBy"' in q and "修改人" in q
    assert 'data-testid="qf-edited-by"' in f and 'x-show="q.approval?.editedBy"' in f and "<b>修改人：</b>" in f
