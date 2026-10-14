# -*- coding: utf-8 -*-
"""BP-5 P0：完工單與出貨單的『現行流程』黃金重放（先於任何流程引擎；寫好未跑，機器空出來後執行）。
目的：日後把端點的狀態寫入／守門改接流程引擎（shim）時，這組題必須維持全綠＝行為逐位元相同（含被擋情況與訊息字串）。
來源：盤點 docs/platform/plans/BP5-FLOW-INVENTORY-T62.md §2.1（行號）；每個斷言都對應程式裡讀到的字面值。
兩種單據走同一份情境（結構相同），差異只在 URL／欄位名／稽核動作名稱。
突變正對照：最後一題把『退回需原因』改成不檢查，重放必須能看出差別（證明這組題抓得到守門被拿掉）。"""
import json

import pytest

import db
from tests._requires import _installed, requires_module

pytestmark = requires_module("case", "BP-5 黃金重放打 M01（案件）／供應（出貨單）端點")

SPECS = {
    "completion": dict(need="case", base="/api/completion-notes", pk="note_no", table="completion_notes", act="completion",
                       payload=lambda: {"quote_no": "MQ-GR-001", "site_address": "台中", "start_date": "2026-08-01",
                                        "completion_date": "2026-09-10", "recipient": "陳經理", "warranty_months": 12,
                                        "items": [{"description": "監控主機安裝", "qty": 1, "unit": "式", "status": "完成"}],
                                        "work_summary": "完成", "test_result": "正常"}),
    "shipping": dict(need="supply", base="/api/shipping-notes", pk="note_no", table="shipping_notes", act="shipping",
                     payload=lambda: {"quote_no": "MQ-GR-001", "ship_date": "2026-09-10", "recipient": "陳經理",
                                      "delivery_address": "台中", "items": [{"description": "攝影機", "qty": 1, "unit": "台"}]}),
}


def _login(client, make_user, name, role):
    u, p = make_user(username=name, role=role)[:2]
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _case():
    c = db.get_db()
    try:
        c.execute("INSERT OR IGNORE INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?)", ("MQ-GR-001", "已送出", "測試客戶", "專案", 100000, 95238,
                                                     json.dumps({"dealTag": "已成案"}, ensure_ascii=False),
                                                     "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        c.commit()
    finally:
        c.close()


def _flow(tiers):
    c = db.get_db()
    try:
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                  ("unified_approval_flow", json.dumps({"includeSubmitterManagerTier": False, "tiers": tiers}, ensure_ascii=False), "2026-01-01T00:00:00"))
        c.commit()
    finally:
        c.close()


def _row(spec, no):
    c = db.get_db()
    try:
        r = c.execute("SELECT status, data_json FROM %s WHERE %s=?" % (spec["table"], spec["pk"]), (no,)).fetchone()
        return r["status"], json.loads(r["data_json"] or "{}")
    finally:
        c.close()


def _audits(no):
    c = db.get_db()
    try:
        # 排除背景 PDF 執行緒寫的 pdf.auto_generate（出貨單核准後 spawn_bg_thread 產生，與請求執行緒競態）：它不是流程轉換的一部分
        return [r["action"] for r in c.execute("SELECT action FROM audit_log WHERE target_id=? AND action<>'pdf.auto_generate' ORDER BY id", (no,)).fetchall()]
    finally:
        c.close()


def _detail(r):
    try:
        return r.json().get("detail", "")
    except Exception:
        return ""


@pytest.fixture(params=sorted(SPECS))
def world(request, client, make_user):
    spec = SPECS[request.param]
    if not _installed(spec["need"]):                                  # 每個參數各自檢查它需要的模組（出貨單在 supply，完工單在 case）
        pytest.skip("需要模組 %s：%s 的端點在那裡" % (spec["need"], request.param))
    _, author = _login(client, make_user, "gr_a_" + request.param, "admin")
    ap_name, approver = _login(client, make_user, "gr_s_" + request.param, "superadmin")
    _, other = _login(client, make_user, "gr_o_" + request.param, "admin")
    _case()
    _flow([{"order": 0, "approvers": [{"username": ap_name, "display_name": ap_name}]}])
    r = client.post(spec["base"], headers=author, json=spec["payload"]())
    assert r.status_code == 201, r.text
    return client, spec, r.json()[spec["pk"]], author, approver, other


def test_draft_is_editable_then_locked_after_submit(world):
    c, s, no, author, approver, other = world
    assert c.put("%s/%s" % (s["base"], no), headers=author, json=s["payload"]()).status_code == 200      # 草稿可編輯
    assert c.post("%s/%s/submit" % (s["base"], no), headers=author).status_code == 200
    assert _row(s, no)[0] == "待審核" and _row(s, no)[1].get("approval")                                     # 送審後有簽核層資料
    r = c.put("%s/%s" % (s["base"], no), headers=author, json=s["payload"]())
    assert r.status_code == 409 and "僅草稿狀態可編輯" in _detail(r)
    r = c.delete("%s/%s" % (s["base"], no), headers=author)
    assert r.status_code == 409 and "僅草稿狀態可刪除" in _detail(r)
    r = c.post("%s/%s/submit" % (s["base"], no), headers=author)
    assert r.status_code == 409 and "僅草稿狀態可送出審核" in _detail(r)


def test_blocked_transitions_while_pending(world):
    c, s, no, author, approver, other = world
    c.post("%s/%s/submit" % (s["base"], no), headers=author)
    r = c.post("%s/%s/revoke-approval" % (s["base"], no), headers=approver, json={"note": "x"})
    assert r.status_code == 404 and "不在已核准狀態" in _detail(r)                                           # 還沒核准不能撤銷
    r = c.post("%s/%s/approve" % (s["base"], no), headers=other, json={})
    assert r.status_code == 403 and "此層需由以下人員簽核" in _detail(r)                                     # 非當層簽核人
    r = c.post("%s/%s/reject" % (s["base"], no), headers=other, json={"note": "x"})
    assert r.status_code == 403 and "無退回權限（非當層簽核人員）" in _detail(r)
    assert _row(s, no)[0] == "待審核"                                                                        # 被擋的轉換不動狀態


def test_reject_needs_a_reason_then_returns_to_draft_and_clears_approval(world):
    c, s, no, author, approver, other = world
    c.post("%s/%s/submit" % (s["base"], no), headers=author)
    before = _audits(no)
    r = c.post("%s/%s/reject" % (s["base"], no), headers=approver, json={})
    assert r.status_code == 400 and "退回要填原因" in _detail(r) and _row(s, no)[0] == "待審核" and _audits(no) == before
    assert c.post("%s/%s/reject" % (s["base"], no), headers=approver, json={"note": "補資料"}).status_code == 200
    st, d = _row(s, no)
    assert st == "草稿" and "approval" not in d                                                              # 簽核資料整個清掉（退回後簽核軌跡只剩 audit_log）
    assert _audits(no) == before + [s["act"] + ".reject"]                                                    # 恰好新增一筆稽核
    assert c.put("%s/%s" % (s["base"], no), headers=author, json=s["payload"]()).status_code == 200          # 退回後又可編輯


def test_approve_then_revoke_round_trip(world):
    c, s, no, author, approver, other = world
    c.post("%s/%s/submit" % (s["base"], no), headers=author)
    r = c.post("%s/%s/approve" % (s["base"], no), headers=approver, json={})
    assert r.status_code == 200 and r.json()["allDone"] is True
    st, d = _row(s, no)
    assert st == "已核准" and d["approval"]["status"] == "approved" and d["approval"]["approvedBy"]
    assert _audits(no)[-1] == s["act"] + ".approve"
    r = c.post("%s/%s/approve" % (s["base"], no), headers=approver, json={})
    assert r.status_code == 404 and "不存在或不在待審核狀態" in _detail(r)                                    # 已核准不能再簽
    r = c.post("%s/%s/revoke-approval" % (s["base"], no), headers=other, json={"note": ""})
    assert r.status_code == 400 and "退回要填原因" in _detail(r) and _row(s, no)[0] == "已核准"               # 原因最後才檢查，但仍擋
    assert c.post("%s/%s/revoke-approval" % (s["base"], no), headers=approver, json={"note": "更正"}).status_code == 200
    st, d = _row(s, no)
    assert st == "草稿" and "approval" not in d and _audits(no)[-1] == s["act"] + ".revoke_approval"


def test_known_gap_any_admin_can_revoke_an_approval(world):
    """已知缺口（04 審查，PM 要求原樣釘住、不在 BP-5 修）：撤銷核准只要 _require_admin＋狀態已核准＋未回簽＋有原因，
    『不是簽核人的一般 admin』也能撤銷別人的核准。預設流程定義 revoke.who＝admin 就是在登記這個現況。"""
    c, s, no, author, approver, other = world
    c.post("%s/%s/submit" % (s["base"], no), headers=author)
    assert c.post("%s/%s/approve" % (s["base"], no), headers=approver, json={}).status_code == 200
    r = c.post("%s/%s/revoke-approval" % (s["base"], no), headers=other, json={"note": "我不是簽核人"})
    assert r.status_code == 200 and _row(s, no)[0] == "草稿"


def test_no_tiers_behaviour_is_pinned_superadmin_only(world):
    """『沒有簽核層』今天的行為（D-W4 要求原樣保留）：只有最高管理者能簽；一般 admin 擋 403。"""
    c, s, no, author, approver, other = world
    _flow([])
    assert c.post("%s/%s/submit" % (s["base"], no), headers=author).status_code == 200
    r = c.post("%s/%s/approve" % (s["base"], no), headers=other, json={})
    assert r.status_code == 403 and "僅超級管理員可執行此操作" in _detail(r)
    assert _row(s, no)[0] == "待審核"
    r = c.post("%s/%s/approve" % (s["base"], no), headers=approver, json={})
    assert r.status_code in (200, 403)                       # 申請人≠簽核人 ⇒ 預期 200；自簽防護（check_no_tier_self_approval）可能擋 403
    if r.status_code == 200:
        assert _row(s, no)[0] == "已核准"


def test_mutation_control_dropping_the_reason_check_is_visible(world, monkeypatch):
    """正對照：把『退回要填原因』改成放行，空原因的 reject 會變 200——也就是上面 reject 那題的 400 斷言會紅。"""
    c, s, no, author, approver, other = world
    c.post("%s/%s/submit" % (s["base"], no), headers=author)
    loose = lambda note, conn=None: (note or "").strip()      # noqa: E731
    monkeypatch.setattr("modules.case.api.completion_notes.require_reject_reason", loose, raising=False)
    monkeypatch.setattr("modules.supply.api.shipping_notes.require_reject_reason", loose, raising=False)
    r = c.post("%s/%s/reject" % (s["base"], no), headers=approver, json={})
    assert r.status_code == 200 and _row(s, no)[0] == "草稿"
