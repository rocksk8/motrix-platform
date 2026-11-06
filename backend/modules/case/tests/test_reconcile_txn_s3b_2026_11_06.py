# -*- coding: utf-8 -*-
"""簽核二擇一 S3b：`reconcile_txn` 外殼與各呼叫點（漏斗／approve／直接寫入）。純函式本體的題在 test_reconcile_in_memory_s3a_*。
設計 docs/platform/plans/QUOTE-APPROVE-EDIT-CHOICE-S3-HOOK-DESIGN.md §7（驗收清單編號見各題）。"""
import json

import pytest

from modules.case import content_fp as C
from modules.case.tests.test_content_fp_s1_2026_11_06 import NO, _doc, _login, _row, _seed
from tests._requires import requires_module

pytestmark = requires_module("case", "S3b 打 M01 的報價單簽核與寫入漏斗")


# ── 共用 ────────────────────────────────────────────────────────────────────────────────
def _set_mode(code):
    import db
    from helpers import settings_groups, settings_registry as SR       # noqa: F401
    c = db.get_db()
    try:
        out = SR.publish("quote_approval", {"reconfirm_mode": code}, reason="t", user="s3b", conn=c)
        c.commit()
    finally:
        c.close()
    return out


@pytest.fixture(autouse=True)
def _fresh_mode_cache():
    C._reset_mode_cache()
    yield
    C._reset_mode_cache()


def _funnel_edit(mutate, actor=None, source="funnel"):
    """走真的漏斗改內容（在 begin_write 之後讀、改、存）。回傳 reconcile 後寫進資料庫的 data。"""
    import db
    from core.txn import begin_write
    from modules.case.quotations import save_quotation_json
    conn = db.get_db()
    try:
        begin_write(conn)
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        mutate(d)
        save_quotation_json(conn, NO, d, reconcile_actor=actor, source=source)
        conn.commit()
    finally:
        conn.close()


def _qty(n):
    def m(d):
        d["items"][0]["qty"] = n
    return m


def _approve(client, h):
    fp = client.get("/api/quotations/" + NO, headers=h).json()["contentFp"]
    r = client.post("/api/quotations/%s/approve" % NO, headers=h, json={"expectedFp": fp})
    assert r.status_code == 200, r.text
    return fp


def _entries():
    d, status, _u = _row()
    return [a for t in d["approval"]["tiers"] for a in t["approvers"]], d["approval"], status


def _notes(username=None, type_=None):
    import db
    c = db.get_db()
    try:
        q, a = "SELECT username, type, message, is_read, link FROM notifications WHERE ref_id=?", [NO]
        if username:
            q += " AND username=?"; a.append(username)
        if type_:
            q += " AND type=?"; a.append(type_)
        return [dict(r) for r in c.execute(q + " ORDER BY id", a)]
    finally:
        c.close()


def _audits(action):
    import db
    c = db.get_db()
    try:
        return [dict(r) for r in c.execute("SELECT action, detail, username FROM audit_log WHERE action=? AND target_id=? ORDER BY id", (action, NO))]
    finally:
        c.close()


def _signed_first_of_two(client, make_user):
    """兩層；第 1 層（fp_ap0）已簽，第 2 層（fp_ap1）待簽。回傳 (headers, names)。"""
    hs, names = _seed(client, make_user, tiers=2)
    _HS.clear(); _HS.update(dict(zip(names, hs)))
    _approve(client, hs[0])
    es, _ap, _st = _entries()
    assert es[0]["status"] == "approved" and es[0]["signedFp"] and es[1]["status"] == "pending"
    return hs, names


# ── 設定與模式快取 ────────────────────────────────────────────────────────────────────────
def test_setting_is_registered_three_state_default_off_and_lowering_is_a_loosening(client):
    from helpers import settings_groups, settings_registry as SR           # noqa: F401
    f = SR._g("quote_approval")["fields"]["reconfirm_mode"]
    assert SR.get("quote_approval", "reconfirm_mode") == 0 and (f.min, f.max, f.loosen) == (0, 2, "down")
    import db
    assert C.reconfirm_mode(db.get_db()) == "off"
    assert not _set_mode(1)["pending"] and C.reconfirm_mode() == "shadow"          # 緊縮：立即生效
    assert not _set_mode(2)["pending"] and C.reconfirm_mode() == "on"
    down = _set_mode(1)
    assert down["pending"], "on→shadow 是放寬，必須走確認期間／雙人核准（Q5）"
    assert C.reconfirm_mode() == "on", "放寬待生效：現值不變"
    assert _set_mode(0)["pending"], "on→off 同上"


def test_mode_unreadable_or_garbage_is_on_the_strictest(client, monkeypatch):
    import db
    for bad in ("maybe", 7, None, True, 1.5):
        monkeypatch.setattr("helpers.settings_strict.strict_value", lambda conn, g, f, _b=bad: _b)
        assert C.reconfirm_mode(db.get_db()) == "on", bad

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr("helpers.settings_strict.strict_value", boom)
    assert C.reconfirm_mode(db.get_db()) == "on"


def test_off_adds_zero_queries_once_cached_and_funnel_never_selects_status(client, make_user):
    """驗收 1：off（預設）時，漏斗與 reconcile_txn 不多任何一句 SQL（含設定讀取）。"""
    import db
    from core.txn import begin_write
    from modules.case.quotations import save_quotation_json
    _seed(client, make_user)
    conn = db.get_db()
    try:
        assert C._mode_cached(conn) == "off"                                 # 暖機：第一次讀設定
        seen = []
        conn.set_trace_callback(seen.append)
        d = {"quoteNo": NO, "items": [], "approval": {"tiers": [{"approvers": [{"username": "x", "status": "approved", "signedFp": "1:zz"}]}]}}
        assert C.reconcile_txn(conn, NO, d, source="funnel") is False
        assert seen == [], seen
        begin_write(conn)
        row = conn.execute("SELECT data_json, updated_at FROM quotations WHERE quote_no=?", (NO,)).fetchone()
        seen.clear()
        save_quotation_json(conn, NO, json.loads(row["data_json"]), updated_at=row["updated_at"])
        sel = [s for s in seen if s.lstrip().upper().startswith("SELECT") and "FROM quotations" in s and "status" in s.split("FROM")[0]]
        sett = [s for s in seen if "definitions" in s.lower() or "settings" in s.lower()]
        assert sel == [] and sett == [], (sel, sett)
        conn.rollback()
    finally:
        conn.close()


def test_mode_is_cached_then_cleared_by_publish_and_failure_is_not_cached(client, monkeypatch):
    import db
    conn = db.get_db()
    try:
        seen = []
        assert C._mode_cached(conn) == "off"
        conn.set_trace_callback(seen.append)
        assert C._mode_cached(conn) == "off" and seen == [], "快取命中不碰資料庫"
        conn.set_trace_callback(None)
    finally:
        conn.close()
    _set_mode(2)
    c2 = db.get_db()
    try:
        assert C._mode_cached(c2) == "on", "設定發布要讓快取作廢（世代變了）"
    finally:
        c2.close()
    # 讀失敗：取 on，而且**不黏住**
    C._reset_mode_cache()
    real = C._read_mode
    calls = {"n": 0}

    def flaky(conn):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("blip")
        return real(conn)
    monkeypatch.setattr(C, "_read_mode", flaky)
    c3 = db.get_db()
    try:
        assert C._mode_cached(c3) == "on" and C._mode_cached(c3) == "on" and calls["n"] == 2, "失敗不快取：下一次要再讀"
        assert C._mode_cached(c3) == "on" and calls["n"] == 2, "讀成功之後才快取"
    finally:
        c3.close()


# ── 漏斗 ────────────────────────────────────────────────────────────────────────────────
def test_off_funnel_edit_changes_nothing_in_the_approval(client, make_user):
    hs, _ = _signed_first_of_two(client, make_user)
    before = _entries()[0]
    _funnel_edit(_qty(9))
    after, _ap, _st = _entries()
    assert [a["status"] for a in after] == [a["status"] for a in before] and not any(a.get("reconfirm") for a in after)
    assert _notes(type_="approval_reconfirm") == [] and _audits("quotation.reconfirm") == []


def test_on_funnel_edit_invalidates_the_signed_layer_notifies_and_audits(client, make_user):
    """驗收 2、5（兩層）：第 1 層已簽 → 改內容 → 第 1 層回待複查＋通知簽核人／第 2 層／送審人＋稽核。"""
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _funnel_edit(_qty(9), actor={"id": 1, "username": "someone", "display_name": "某人"})
    es, ap, _st = _entries()
    assert es[0]["status"] == "pending" and es[0]["reconfirm"] is True and es[0]["prevSignedFp"]
    assert ap["currentTier"] == 0 and ap["contentRev"] == 1 and ap["reviewRounds"] == 1
    assert [n["type"] for n in _notes(names[0])] == ["approval_reconfirm"]
    assert "某人" in _notes(names[0])[0]["message"] and "items" in _notes(names[0])[0]["message"]
    assert [n["type"] for n in _notes(names[1])] == ["approval_request", "approval_reconfirm_info"] or \
        "approval_reconfirm_info" in [n["type"] for n in _notes(names[1])]
    assert [n["type"] for n in _notes("fp_req")] == ["approval_reconfirm_info"]
    assert all(n["link"] == "approval-queue.html" for n in _notes(type_="approval_reconfirm"))
    a = _audits("quotation.reconfirm")
    assert len(a) == 1 and json.loads(a[0]["detail"])["invalidated"] == [names[0]] and a[0]["username"] == "someone"


def test_on_editor_who_is_the_signer_is_not_notified_of_their_own_edit(client, make_user):
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _funnel_edit(_qty(9), actor={"id": 1, "username": names[0], "display_name": names[0]})
    assert _notes(names[0], "approval_reconfirm") == []
    assert _entries()[0][0]["status"] == "pending", "自己改的，簽核仍作廢（只是不通知自己）"


def test_on_only_excluded_keys_do_not_invalidate_but_dealtag_does(client, make_user):
    """驗收 4。"""
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)

    def bookkeeping(d):
        d.setdefault("statusLog", []).append({"at": "x"}); d["docVersions"] = [{"seq": 1}]; d["googleCalendarEventId"] = "e1"
    _funnel_edit(bookkeeping)
    assert _entries()[0][0]["status"] == "approved"
    _funnel_edit(lambda d: d.__setitem__("dealTag", "hot"))
    assert _entries()[0][0]["status"] == "pending", "dealTag 從嚴算內容"


def test_legacy_entries_without_signed_fp_are_never_invalidated(client, make_user):
    """驗收 10。"""
    hs, names = _signed_first_of_two(client, make_user)
    import db
    c = db.get_db()
    d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    for t in d["approval"]["tiers"]:
        for a in t["approvers"]:
            a.pop("signedFp", None); a.pop("signedKeyHashes", None)
    d["approval"].pop("contentFp", None)
    c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    _set_mode(2)
    _funnel_edit(_qty(9))
    assert _entries()[0][0]["status"] == "approved"


def test_shadow_records_would_invalidate_once_per_fingerprint_and_changes_no_approval(client, make_user):
    """驗收 9。"""
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(1)
    _funnel_edit(_qty(9))
    _funnel_edit(_qty(9))                                                   # 同一份內容再存一次：不重複記
    es, ap, _st = _entries()
    assert es[0]["status"] == "approved" and not es[0].get("reconfirm") and not ap.get("reconfirmSuspended")
    a = _audits("quotation.reconfirm_shadow")
    assert len(a) == 1 and json.loads(a[0]["detail"])["wouldInvalidate"] == [names[0]], a
    assert _notes(type_="approval_reconfirm") == [] and _audits("quotation.reconfirm") == []
    _funnel_edit(_qty(10))                                                  # 新的指紋：再記一筆
    assert len(_audits("quotation.reconfirm_shadow")) == 2


def test_shadow_then_on_catches_up_in_one_round(client, make_user):
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(1)
    _funnel_edit(_qty(9)); _funnel_edit(_qty(10))
    _set_mode(2)
    _funnel_edit(lambda d: d.__setitem__("note", "x"))                       # 旗標開之後的下一次寫入：補追，只算 1 輪
    es, ap, _st = _entries()
    assert es[0]["status"] == "pending" and ap["reviewRounds"] == 1


def test_round_cap_stops_invalidating_and_tells_the_superadmin_once(client, make_user):
    """驗收 6。"""
    hs, names = _signed_first_of_two(client, make_user)
    su, _pw = make_user(username="fp_su", role="superadmin")
    _set_mode(2)
    n = [0]

    def bump_and_sign():
        n[0] += 1
        _funnel_edit(_qty(100 + n[0]))
    for _ in range(C.REVIEW_ROUNDS_LIMIT):
        bump_and_sign()
        es, ap, _st = _entries()
        assert es[0]["status"] == "pending"
        _approve_as(client, names[0], make_user)                             # 簽核人複查（重簽）
    assert _entries()[1]["reviewRounds"] == C.REVIEW_ROUNDS_LIMIT
    bump_and_sign()                                                          # 第 6 次：不再作廢
    es, ap, _st = _entries()
    assert es[0]["status"] == "approved" and ap["reconfirmSuspended"] is True
    assert [n_["type"] for n_ in _notes(su)] == ["approval_reconfirm_suspended"]
    bump_and_sign()
    assert len(_notes(su, "approval_reconfirm_suspended")) == 1, "只在第一次設旗標時通知"


_HS = {}


def _approve_as(client, username, make_user=None):
    """用 `_seed` 建好的該簽核人的登入標頭簽一次（帶當下指紋）。"""
    _approve(client, _HS[username])


def test_merged_notifications_keep_one_unread_row_and_a_new_one_after_it_is_read(client, make_user):
    """驗收 7。"""
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _funnel_edit(_qty(9))
    c = __import__("db").get_db()
    n0 = c.execute("SELECT COUNT(*) n FROM notifications WHERE ref_id=? AND type='approval_reconfirm_info' AND username=?", (NO, "fp_req")).fetchone()["n"]
    c.close()
    assert n0 == 1
    # 同一簽核人連續被通知：第 1 層回 pending 後，第 2 次內容變動沒有已簽層可作廢 ⇒ 不再通知（本來就在待複查）
    _funnel_edit(_qty(10))
    assert len(_notes(names[0], "approval_reconfirm")) == 1
    # 直接測合併規則：同 (type, ref_id, username) 已有未讀 ⇒ 改寫那一列；已讀後 ⇒ 新增
    import db
    from helpers.audit import _notify_in_txn
    c = db.get_db()
    try:
        for i in range(5):
            _notify_in_txn(c, "fp_ap1", "approval_reconfirm", NO, NO, "msg%d" % i, "approval-queue.html", merge_unread=True)
        c.commit()
        rows = [r for r in _notes("fp_ap1", "approval_reconfirm")]
        assert len(rows) == 1 and rows[0]["message"] == "msg4"
        c.execute("UPDATE notifications SET is_read=1 WHERE username='fp_ap1' AND type='approval_reconfirm'")
        _notify_in_txn(c, "fp_ap1", "approval_reconfirm", NO, NO, "after-read", "approval-queue.html", merge_unread=True)
        c.commit()
        assert len(_notes("fp_ap1", "approval_reconfirm")) == 2
    finally:
        c.close()


def test_notification_and_audit_roll_back_with_the_transaction(client, make_user):
    """驗收 8：交易回滾 ⇒ 資料與通知與稽核都不在。"""
    import db
    from core.txn import begin_write
    from modules.case.quotations import save_quotation_json
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    conn = db.get_db()
    try:
        begin_write(conn)
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
        d["items"][0]["qty"] = 77
        save_quotation_json(conn, NO, d)
        assert [n for n in conn.execute("SELECT 1 FROM notifications WHERE type='approval_reconfirm' AND ref_id=?", (NO,))], "同一連線看得到"
        conn.rollback()
    finally:
        conn.close()
    assert _notes(type_="approval_reconfirm") == [] and _audits("quotation.reconfirm") == []
    assert _entries()[0][0]["status"] == "approved"


def test_reading_paths_never_write(client, make_user):
    """讀路徑（GET、佇列詳情）只能純推導，不呼叫 reconcile、不寫入（§I2）。"""
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    import db
    c = db.get_db()
    d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    d["items"][0]["qty"] = 55                                                  # 走不經過漏斗的寫法改內容
    c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    before = _row()
    assert client.get("/api/quotations/" + NO, headers=hs[0]).status_code == 200
    assert client.get("/api/approval-queue/detail", params={"type": "quotation", "id": NO}, headers=hs[1]).status_code == 200
    assert _row() == before and _notes(type_="approval_reconfirm") == []


# ── approve：先對帳、再決定 ───────────────────────────────────────────────────────────────
def test_next_tier_approver_is_403_on_a_stale_row_and_nothing_is_persisted_then_the_signer_resigns(client, make_user):
    """先對帳再查權限之後：第 2 層簽核人在『第 1 層其實已過期』時按核准 ⇒ 對帳後輪不到他（403 此層需由第 1 層簽）；他不是被對帳通知的人、也沒權限 ⇒
    對帳寫的一切不 commit。第 1 層簽核人才是進得了對帳的人（409，作廢落地）；他複查簽完，第 2 層才簽得到。"""
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _stale_row_edit()
    before, rows0 = _row(), _reconfirm_rows()
    fp = client.get("/api/quotations/" + NO, headers=hs[1]).json()["contentFp"]
    r = client.post("/api/quotations/%s/approve" % NO, headers=hs[1], json={"expectedFp": fp})
    assert r.status_code == 403, r.text
    assert _row() == before and _reconfirm_rows() == rows0, "403 ⇒ 對帳不落地"
    fp0 = client.get("/api/quotations/" + NO, headers=hs[0]).json()["contentFp"]
    r0 = client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={"expectedFp": fp0})
    assert r0.status_code == 409 and "重算" in r0.text, r0.text
    es, ap, _st = _entries()
    assert es[0]["status"] == "pending" and es[0]["reconfirm"] and es[1]["status"] == "pending", "第 2 層沒被簽"
    assert ap["currentTier"] == 0 and [n["type"] for n in _notes(names[1], "approval_reconfirm_info")] == ["approval_reconfirm_info"]
    _approve_as(client, names[0], make_user)
    _approve(client, hs[1])
    assert _row()[1] == "已送出"


def test_approve_in_shadow_mode_behaves_like_today(client, make_user):
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(1)
    import db
    c = db.get_db()
    d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    d["items"][0]["qty"] = 55
    c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()
    _approve(client, hs[1])
    assert _row()[1] == "已送出" and len(_audits("quotation.reconfirm_shadow")) == 1


def _stale_row_edit(qty=55):
    """走不經過漏斗的寫法改內容（庫裡的簽核狀態沒更新）：模擬舊分頁／未掛鉤的路徑，或影子→開切換後的在途單。"""
    import db
    c = db.get_db()
    d = json.loads(c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()["data_json"])
    d["items"][0]["qty"] = qty
    c.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO)); c.commit(); c.close()


def _reconfirm_rows():
    import db
    c = db.get_db()
    try:
        n = c.execute("SELECT COUNT(*) n FROM notifications WHERE type LIKE 'approval_reconfirm%'").fetchone()["n"]
        a = c.execute("SELECT COUNT(*) n FROM audit_log WHERE action LIKE 'quotation.reconfirm%'").fetchone()["n"]
        return n, a
    finally:
        c.close()


def test_signer_whose_layer_is_stale_gets_409_not_403(client, make_user):
    """K 審必修：先對帳、再查權限。A 已簽第 1 層、內容在別處被改（mode=on、庫裡簽核沒更新）→ A 按核准要 409（不是 403：用庫裡舊的已簽狀態查權限
    會 403，被作廢的簽核人永遠進不了對帳）；409 之後 A 的層回待複查、通知與稽核已寫入，A 重簽才成功。"""
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _stale_row_edit()
    fp = client.get("/api/quotations/" + NO, headers=hs[0]).json()["contentFp"]
    r = client.post("/api/quotations/%s/approve" % NO, headers=hs[0], json={"expectedFp": fp})
    assert r.status_code == 409 and "重算" in r.text, r.text
    es, ap, _st = _entries()
    assert es[0]["status"] == "pending" and es[0]["reconfirm"] and ap["currentTier"] == 0
    assert _audits("quotation.reconfirm"), "對帳落地（簽核人自己觸發的，不通知自己）"
    _approve(client, hs[0])                                  # 重看之後再簽：成功
    assert _entries()[0][0]["status"] == "approved"


def test_approve_by_unauthorised_caller_never_reconciles(client, make_user):
    """沒權限的人：403，而且對帳寫的一切（簽核狀態、通知、稽核）都不留下——對帳在他的交易裡跑、沒 commit 就 close。"""
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _stale_row_edit()
    before, rows0 = _row(), _reconfirm_rows()
    other, pw = make_user(username="fp_other", role="admin")
    r = client.post("/api/quotations/%s/approve" % NO, headers=_login(client, other, pw), json={})
    assert r.status_code == 403, r.text
    assert _row() == before, "沒權限的人不能觸發任何寫入"
    assert _reconfirm_rows() == rows0, "通知／稽核零新增"


def test_approve_marks_my_reconfirm_notification_read(client, make_user):
    hs, names = _signed_first_of_two(client, make_user)
    _set_mode(2)
    _funnel_edit(_qty(9), actor={"id": 1, "username": "someone", "display_name": "某人"})
    assert _notes(names[0], "approval_reconfirm")[0]["is_read"] == 0
    _approve(client, hs[0])
    assert _notes(names[0], "approval_reconfirm")[0]["is_read"] == 1


# ── 直接寫入的掛鉤 ────────────────────────────────────────────────────────────────────────
def _with_order_doc():
    d = _doc()
    d["caseRecord"] = {"materialOrders": [{"itemId": "L1", "itemName": "料", "quantity": 1, "unitPrice": 100, "totalPrice": 100}]}
    return d


def test_sync_order_paid_reconciles_before_its_direct_update(client, make_user):
    from modules.case import material_payment as MP
    hs, names = _seed(client, make_user, tiers=2, doc=_with_order_doc())
    _HS.clear(); _HS.update(dict(zip(names, hs)))
    _approve(client, hs[0])
    _set_mode(2)
    import db
    c = db.get_db()
    try:
        from core.txn import begin_write
        begin_write(c)
        c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()
        assert MP.sync_order_paid(c, NO, "L1") is True
        c.commit()
    finally:
        c.close()
    es, ap, _st = _entries()
    assert es[0]["status"] == "pending" and es[0]["reconfirm"], "paid* 寫進叫料單內容 ⇒ 已簽層要複查"
    assert "系統" in _notes(names[0], "approval_reconfirm")[0]["message"]


def test_recycle_delete_and_restore_reconcile(client, make_user):
    from modules.case.recycle_adapter import MaterialOrderAdapter
    hs, names = _seed(client, make_user, tiers=2, doc=_with_order_doc())
    _HS.clear(); _HS.update(dict(zip(names, hs)))
    _approve(client, hs[0])
    _set_mode(2)
    import db
    from core.txn import begin_write
    ad = MaterialOrderAdapter()
    c = db.get_db()
    try:
        begin_write(c)
        c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()
        snap = ad.snapshot(c, "%s|L1" % NO)
        ad.delete_in_tx(c, "%s|L1" % NO)
        c.commit()
    finally:
        c.close()
    es, ap, _st = _entries()
    assert es[0]["status"] == "pending" and es[0]["reconfirm"] and ap["reviewRounds"] == 1
    _approve_as(client, names[0], make_user)
    c = db.get_db()
    try:
        begin_write(c)
        c.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()
        ad.restore_in_tx(c, snap, {})
        c.commit()
    finally:
        c.close()
    es, ap, _st = _entries()
    assert es[0]["status"] == "pending" and ap["reviewRounds"] == 2, "還原也是內容變動"


# ── UNREACHABLE_IN_APPROVAL：狀態閘 409（S0 守門引用這兩題）─────────────────────────────────
def _alt_doc():
    d = _doc()
    d["altPicks"] = {"g1": "i1"}                      # `alt_sign.applies`：altPicks 非空 ⇒ 走擇一回簽路徑
    return d


def _toggle(client, h, action, signed=False):
    import db
    c = db.get_db()
    c.execute("UPDATE quotations SET is_signed=? WHERE quote_no=?", (1 if signed else 0, NO)); c.commit(); c.close()
    return client.post("/api/quotations/%s/signed-toggle" % NO, headers=h, json={"action": action, "note": "t", "picks": {"g1": "i1"}})


@pytest.mark.parametrize("status", ["待審核", "簽核中"])
def test_alt_sign_is_409_while_in_approval(client, make_user, status):
    hs, _ = _seed(client, make_user, tiers=1, status=status, doc=_alt_doc())
    before = _row()
    r = _toggle(client, hs[0], "sign")
    assert r.status_code == 409 and "已送出" in r.text, r.text
    assert _row()[0] == before[0], "被擋 ⇒ 沒寫任何東西"


@pytest.mark.parametrize("status", ["待審核", "簽核中"])
def test_unsign_is_409_while_in_approval(client, make_user, status):
    from modules.case import alt_sign as AS
    assert "待審核" not in AS.UNSIGN_STATES and "簽核中" not in AS.UNSIGN_STATES
    hs, _ = _seed(client, make_user, tiers=1, status=status, doc=_alt_doc())
    before = _row()
    r = _toggle(client, hs[0], "unsign", signed=True)
    assert r.status_code == 409 and AS.IN_APPROVAL_MSG in r.text, r.text
    assert _row()[0] == before[0]
