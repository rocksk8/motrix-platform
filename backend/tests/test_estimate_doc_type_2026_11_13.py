"""2026-11-13：估價單（開立報價單時可選「估價單」；流程與報價單完全相同，只有單號字首與用語不同）。

釘住：
1. 兩種類型的單號各自獨立（ME 不搶 MQ 的號，反之亦然）；字首可在設定中心改，改了不影響舊單。
2. 類型開立後鎖定（PUT 帶別的類型不採用）；舊資料（沒有 doc_type）一律是報價單。
3. 清單可依類型篩選、單號搜尋照常。
4. PDF 標題、站內通知、Email 主旨／內文隨類型換名稱；報價單的字一個都不變。
5. 簽核流程與報價單一致（同樣的鏈、同樣的核准結果）。
"""
from tests._requires import requires_module  # noqa: E402
import inspect
import json
import re

import pytest

pytestmark = requires_module("case", "本檔打 M01（案件）的端點與資料（報價單／估價單）")


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _payload(doc_type=None, status="草稿", customer="估價客戶", extra=None):
    data = {"customerName": customer, "projectName": "估價專案", "quoteDate": "2026-11-13",
            "items": [{"description": "品項"}],
            "tot": {"total": 1000, "pretax": 952, "directMarginPct": 0, "netMarginPct": 0}}
    if doc_type is not None:
        data["docType"] = doc_type
    if extra:
        data.update(extra)
    return {"status": status, "data": data}


def _row(quote_no):
    from db import get_db
    conn = get_db()
    try:
        return conn.execute("SELECT * FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
    finally:
        conn.close()


def _create(client, h, doc_type=None, **kw):
    r = client.post("/api/quotations", headers=h, json=_payload(doc_type, **kw))
    assert r.status_code == 201, r.text
    return r.json()["quote_no"]


def _seq(n):
    return int(n.rsplit("-", 1)[1])


# ── 1. 編號獨立 ───────────────────────────────────────────────────────────────

def test_numbers_are_independent_between_quote_and_estimate(client, make_user):
    u, pw = make_user(username="est_no", role="admin")
    h = _login(client, u, pw)
    q1 = _create(client, h)
    e1 = _create(client, h, "estimate")
    q2 = _create(client, h)
    e2 = _create(client, h, "estimate")
    assert q1.startswith("MQ-") and q2.startswith("MQ-")
    assert e1.startswith("ME-") and e2.startswith("ME-")
    assert _seq(q2) == _seq(q1) + 1, "估價單不該吃掉報價單的流水號"
    assert _seq(e1) == 1 and _seq(e2) == 2, "估價單流水號自己從 001 起算，不受報價單影響"
    assert re.fullmatch(r"ME-\d{6}-\d{3}", e1)
    assert _row(e1)["doc_type"] == "estimate" and _row(q1)["doc_type"] == "quote"


def test_next_quote_no_peek_follows_type(client, make_user):
    u, pw = make_user(username="est_peek", role="admin")
    h = _login(client, u, pw)
    _create(client, h)
    q = client.get("/api/next-quote-no", headers=h).json()
    e = client.get("/api/next-quote-no?doc_type=estimate", headers=h).json()
    assert q["quote_no"].startswith("MQ-") and q["doc_type"] == "quote"
    assert e["quote_no"].startswith("ME-") and e["doc_type"] == "estimate"
    assert _seq(e["quote_no"]) == 1
    assert client.get("/api/next-quote-no?doc_type=whatever", headers=h).json()["quote_no"].startswith("MQ-"), \
        "不認得的類型一律當報價單（與改版前相同）"


def test_prefix_is_adjustable_and_old_numbers_stay_valid(client, make_user):
    from helpers import settings_registry as sr
    u, pw = make_user(username="est_pfx", role="superadmin")
    h = _login(client, u, pw)
    e_old = _create(client, h, "estimate")
    assert e_old.startswith("ME-")
    sr.publish("quote_defaults", {"estimate_no_prefix": "EQ"}, user=u, reason="test")
    e_new = _create(client, h, "estimate")
    assert e_new.startswith("EQ-") and _seq(e_new) == 1, "新字首有自己的流水號"
    # 舊單仍可開啟、仍是估價單
    r = client.get(f"/api/quotations/{e_old}", headers=h)
    assert r.status_code == 200 and r.json()["data"]["docType"] == "estimate"
    # 報價單不受影響
    assert _create(client, h).startswith("MQ-")


@pytest.mark.parametrize("bad", ["", "M", "MEE", "me1", "MQ", "PO", "中文"])
def test_bad_prefix_is_rejected_by_settings(client, make_user, bad):
    from helpers import settings_registry as sr
    u, _ = make_user(username="est_badpfx", role="superadmin")
    with pytest.raises(sr.SettingError):
        sr.publish("quote_defaults", {"estimate_no_prefix": bad}, user=u, reason="test")


def test_client_supplied_estimate_no_must_match_prefix(client, make_user):
    u, pw = make_user(username="est_cno", role="admin")
    h = _login(client, u, pw)
    body = _payload("estimate")
    body["quote_no"] = "MQ-202611-777"           # 估價單不能拿 MQ 的號
    r = client.post("/api/quotations", headers=h, json=body)
    assert r.status_code == 201
    assert r.json()["quote_no"].startswith("ME-"), "字首不符的用戶端單號由後端改派"


# ── 2. 鎖定與舊資料 ───────────────────────────────────────────────────────────

def test_type_is_locked_after_first_save(client, make_user):
    u, pw = make_user(username="est_lock", role="admin")
    h = _login(client, u, pw)
    e = _create(client, h, "estimate")
    body = _payload("quote")                     # 用戶端想改回報價單
    r = client.put(f"/api/quotations/{e}", headers=h, json=body)
    assert r.status_code == 200, r.text
    assert _row(e)["doc_type"] == "estimate"
    assert client.get(f"/api/quotations/{e}", headers=h).json()["data"]["docType"] == "estimate"
    q = _create(client, h)
    r = client.put(f"/api/quotations/{q}", headers=h, json=_payload("estimate"))
    assert r.status_code == 200, r.text
    assert _row(q)["doc_type"] == "quote", "報價單也不能被改成估價單"


def test_old_rows_are_quotes(client, make_user):
    """舊資料（升級前建立、沒有帶 docType 的單）一律是報價單：欄位預設 quote、API 回 quote、篩選「報價單」找得到。"""
    u, pw = make_user(username="est_old", role="admin")
    h = _login(client, u, pw)
    q = _create(client, h)                         # 沒帶 docType ＝ 舊用戶端的行為
    assert _row(q)["doc_type"] == "quote"
    assert client.get(f"/api/quotations/{q}", headers=h).json()["data"]["docType"] == "quote"
    from helpers import doc_type as DT
    assert DT.norm(None) == "quote" and DT.norm("") == "quote" and DT.norm("???") == "quote"


def test_migration_is_idempotent_and_defaults_to_quote():
    import importlib.util
    import sqlite3
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "modules" / "case" / "migrations" / "0010_quote_doc_type.py"
    spec = importlib.util.spec_from_file_location("m0010", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    c = sqlite3.connect(":memory:")
    assert isinstance(m.up(c), str), "表不存在 ⇒ 回原因字串（未完成，下次啟動再補）"
    c.execute("CREATE TABLE quotations (quote_no TEXT PRIMARY KEY)")
    c.execute("INSERT INTO quotations VALUES ('MQ-202601-001')")
    assert m.up(c) is None
    assert m.up(c) is None                         # 重跑不炸
    assert c.execute("SELECT doc_type FROM quotations").fetchone()[0] == "quote", "舊資料一律是報價單"


# ── 3. 清單篩選 ───────────────────────────────────────────────────────────────

def test_list_filter_by_doc_type(client, make_user):
    u, pw = make_user(username="est_list", role="admin")
    h = _login(client, u, pw)
    q = _create(client, h)
    e = _create(client, h, "estimate")

    def nos(qs=""):
        j = client.get("/api/quotations" + qs, headers=h).json()
        rows = j["items"]
        return {x["quote_no"]: x for x in rows}

    allr = nos()
    assert q in allr and e in allr
    assert allr[e]["doc_type"] == "estimate" and allr[q]["doc_type"] == "quote"
    only_e = nos("?doc_type=estimate")
    assert e in only_e and q not in only_e
    only_q = nos("?doc_type=quote")
    assert q in only_q and e not in only_q


# ── 4. 用語：PDF／站內通知／Email ────────────────────────────────────────────

def test_pdf_title_follows_type():
    import pdf_gen
    base = {"quoteNo": "XX-202611-001", "customerName": "客", "projectName": "案", "items": [],
            "quoteDate": "2026-11-13", "tot": {"total": 0, "pretax": 0}}
    est = pdf_gen._build_quote_html(dict(base, docType="estimate"), base["tot"])
    quo = pdf_gen._build_quote_html(dict(base), base["tot"])
    assert "估　價　單" in est and "報　價　單" not in est
    assert "報　價　單" in quo and "估　價　單" not in quo


def test_inapp_messages_follow_type():
    from modules.case.api import quotations as Q
    assert "估價單" in Q._submitted_msg("ME-202611-001", "", "客", "estimate")
    assert "報價單" not in Q._submitted_msg("ME-202611-001", "", "客", "estimate")
    assert "報價單" in Q._submitted_msg("MQ-202611-001", "", "客")
    assert "報價單" in Q._submitted_msg("MQ-202611-001", "", "客", "quote")
    for fn, args in ((Q._tier_msg, ("N", "", "客", 1, 2)), (Q._approved_msg, ("N", "客", "某人")),
                     (Q._returned_msg, ("N-R1", "N", "客"))):
        assert "估價單" in fn(*args, "estimate") and "報價單" not in fn(*args, "estimate")
        assert "報價單" in fn(*args) and "估價單" not in fn(*args)


def test_email_text_follows_type(monkeypatch):
    from helpers import email_notify as E
    sent = []
    monkeypatch.setattr(E, "_async_send", lambda to, subject, html: sent.append((to, subject, html)))
    monkeypatch.setattr(E, "_get_email", lambda u: "a@example.com", raising=False)
    monkeypatch.setattr(E, "_resolve_email", lambda u: "a@example.com", raising=False)
    # 文字替換規則本身（不依賴寄信設定）
    assert E._dl("前往審核報價單", "估價單") == "前往審核估價單"
    assert E._dl("前往審核報價單", "報價單") == "前往審核報價單"
    assert E._dl("前往審核報價單", None) == "前往審核報價單"
    # 簽名：五支通知都有選填 doc_label，預設不改行為
    import inspect
    for name in ("notify_approval_request", "notify_next_tier", "notify_approved", "notify_returned",
                 "notify_resubmit_requester"):
        p = inspect.signature(getattr(E, name)).parameters["doc_label"]
        assert p.default == "報價單", name


# ── 5. 簽核流程一致 ──────────────────────────────────────────────────────────

def _flow_of(quote_no):
    from db import get_db
    conn = get_db()
    try:
        r = conn.execute("SELECT status, data_json FROM quotations WHERE quote_no=?", (quote_no,)).fetchone()
        a = (json.loads(r["data_json"]).get("approval") or {})
        return r["status"], [[x.get("username") for x in t.get("approvers", [])] for t in a.get("tiers", [])], a
    finally:
        conn.close()


def test_approval_flow_is_identical_for_estimate(client, make_user):
    from db import get_db
    me, pw = make_user(username="est_ap", role="superadmin")
    make_user(username="est_ap2", role="superadmin")
    conn = get_db()                     # 申請人身兼部門主管＋處主管 ⇒ 自簽兩層（與 test_org_chain_approval 同一套設定）
    try:
        uid = conn.execute("SELECT id FROM users WHERE username=?", (me,)).fetchone()["id"]
        div = conn.execute("INSERT INTO divisions (name, sort_order, created_at, manager_user_id) VALUES (?,?,?,?)",
                           ("估價測試處", 0, "2026-01-01T00:00:00", uid)).lastrowid
        dept = conn.execute("INSERT INTO departments (division_id, name, sort_order, manager_user_id, created_at) VALUES (?,?,?,?,?)",
                            (div, "估價測試部", 0, uid, "2026-01-01T00:00:00")).lastrowid
        conn.execute("UPDATE users SET department_id=? WHERE username=?", (dept, me))
        conn.execute("INSERT OR REPLACE INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)",
                     ("unified_approval_flow", json.dumps({"tiers": [], "includeSubmitterManagerTier": True}), "2026-11-13T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    h = _login(client, me, pw)
    appr = {"approval": {"requestedBy": me, "requestedByDisplay": me, "requestedAt": "2026-11-13T02:00:00"}}
    results = {}
    for dt in (None, "estimate"):
        no = _create(client, h, dt, status="待審核", extra=appr)
        st0, tiers0, _ = _flow_of(no)
        a = client.post(f"/api/quotations/{no}/approve", headers=h, json={"approvedByDisplay": me, "cascade": True})
        assert a.status_code == 200, a.text
        st1, _, ap = _flow_of(no)
        results[dt or "quote"] = (st0, len(tiers0), st1, bool(ap.get("approvedBy")))
    assert results["quote"] == results["estimate"], f"簽核流程應一致：{results}"

    conn = get_db()
    try:
        msgs = conn.execute("SELECT ref_id, message FROM notifications").fetchall()
    finally:
        conn.close()
    est_msgs = [m["message"] for m in msgs if str(m["ref_id"]).startswith("ME-")]
    quo_msgs = [m["message"] for m in msgs if str(m["ref_id"]).startswith("MQ-")]
    assert est_msgs and all("報價單" not in m for m in est_msgs), est_msgs
    assert quo_msgs and all("估價單" not in m for m in quo_msgs), quo_msgs


# ── 6. 單號規則（字首／日期格式／流水號位數由規則決定，不寫死 MQ）──────────────────────

def test_number_rule_shape_comes_from_the_rule():
    from helpers import doc_type as DT
    q = DT.rule_for("quote")
    assert (q.prefix, q.date_fmt, q.seq_digits, q.date_len) == ("MQ", "%Y%m", 3, 6)
    assert q.total_len == 13 and q.seq_start == 11 and q.max_seq == 999, "與舊程式寫死的 SUBSTR(quote_no,11,3)／LENGTH=13 同值"
    assert q.regex().match("MQ-202611-001") and not q.regex().match("ME-202611-001")
    assert q.regex(revision=True).match("MQ-202611-001-R2") and not q.regex().match("MQ-202611-001-R2")
    assert q.format("202611", 7) == "MQ-202611-007" and q.month_of("MQ-202611-007") == "202611" and q.seq_of("MQ-202611-007") == 7
    assert q.seq_of("MQ-202611-1000") == 1000, "流水號用完位數也要讀得出來"
    assert q.glob("202611") == "MQ-202611-???" and q.seq_key("202611") == "202611", "報價單的 quote_seq 鍵維持舊格式"
    e = DT.rule_for("estimate")
    assert e.seq_key("202611") == e.prefix + "-202611" and e.total_len == q.total_len


def test_old_mq_numbers_are_unaffected_by_estimate_rules():
    from helpers import doc_type as DT
    rx = DT.case_no_re()
    assert rx.search("quotation.update MQ-202601-005 改了客戶").group(0) == "MQ-202601-005"
    assert DT.rule_of_no("MQ-202601-005").doc_type == "quote" and DT.doc_type_of_no("MQ-202601-005") == "quote"
    assert DT.seq_key("MQ-202601-005") == "202601"
    from modules.case.api import quotations as Q
    assert Q._month_of_no("MQ-202601-005") == "202601"


def test_old_estimate_numbers_still_recognised_after_prefix_change(client, make_user):
    from helpers import doc_type as DT
    from helpers import settings_registry as sr
    u, pw = make_user(username="est_hist", role="superadmin")
    h = _login(client, u, pw)
    old = _create(client, h, "estimate")                       # ME-…
    sr.publish("quote_defaults", {"estimate_no_prefix": "EQ"}, user=u, reason="test")
    new = _create(client, h, "estimate")                       # EQ-…
    assert old.startswith("ME-") and new.startswith("EQ-")
    rx = DT.case_no_re()
    assert rx.search("x %s y" % old).group(0) == old, "改字首後舊單號仍要能從稽核／獎金文字裡認出來"
    assert rx.search("x %s y" % new).group(0) == new
    assert DT.doc_type_of_no(old) == "estimate" and DT.doc_type_of_no(new) == "estimate"
    assert DT.rule_of_no(old).prefix == "ME" and DT.rule_of_no(new).prefix == "EQ"
    # 新舊字首各自流水號、互不影響
    assert _seq(new) == 1
    again = _create(client, h, "estimate")
    assert again.startswith("EQ-") and _seq(again) == 2
    # 舊估價單照常開啟、再存檔不改號、類型不變
    assert client.put(f"/api/quotations/{old}", headers=h, json=_payload("estimate")).status_code == 200
    assert _row(old)["doc_type"] == "estimate"


def test_audit_and_bonus_case_no_inference_is_rule_derived(client, make_user):
    from helpers import audit
    from helpers import doc_type as DT
    u, pw = make_user(username="est_audit", role="superadmin")
    h = _login(client, u, pw)
    e = _create(client, h, "estimate")
    q = _create(client, h)
    for no in (e, q):
        d = audit._derive_fields("quotation.update", "quotation", no, "", "")
        assert d["case_no"] == no, (no, d)
    # 規則推導出來的 regex 就是 audit 用的那一支
    assert audit._case_no_re() is DT.case_no_re()


# ── 7. 審查修正（hichan-2，2026-11-13）：M1 月份／M2 編輯紀錄／M3 前綴撞號 ───────────────────────

def _prev_yyyymm():
    from datetime import date
    t = date.today()
    y, m = (t.year - 1, 12) if t.month == 1 else (t.year, t.month - 1)
    return "%04d%02d" % (y, m)


def _quote_seq(key):
    from db import get_db
    conn = get_db()
    try:
        r = conn.execute("SELECT seq FROM quote_seq WHERE month=?", (key,)).fetchone()
        return r["seq"] if r else None
    finally:
        conn.close()


@pytest.mark.parametrize("doc_type,prefix", [(None, "MQ"), ("estimate", "ME")])
def test_m1_provisional_number_from_last_month_reserves_that_months_sequence(client, make_user, doc_type, prefix):
    """月底取號、跨午夜才存檔：單號採用用戶端的上個月暫定號，quote_seq 要記在「單號的月份」，這個月的序號不能被推高。"""
    from datetime import date
    u, pw = make_user(username="est_m1_" + prefix.lower(), role="admin")
    h = _login(client, u, pw)
    prev, cur = _prev_yyyymm(), date.today().strftime("%Y%m")
    key = (lambda ym: ym) if prefix == "MQ" else (lambda ym: prefix + "-" + ym)
    before_cur = _quote_seq(key(cur))
    body = _payload(doc_type)
    body["quote_no"] = "%s-%s-050" % (prefix, prev)
    r = client.post("/api/quotations", headers=h, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["quote_no"] == "%s-%s-050" % (prefix, prev), "上個月的暫定號合法，照用"
    assert _quote_seq(key(prev)) == 50, "序號記在單號自己的月份"
    assert (_quote_seq(key(cur)) or 0) == (before_cur or 0), "這個月的序號不受影響（否則本月會從 051 起跳過 001–050）"


def test_m2_first_save_of_a_legacy_row_writes_no_edit_history(client, make_user):
    """升級前建立的單（data_json 沒有 docType）第一次原樣存檔，不該憑空多一筆編輯紀錄。"""
    import json as _json
    from db import get_db
    u, pw = make_user(username="est_m2", role="admin")
    h = _login(client, u, pw)
    q = _create(client, h)
    g0 = client.get(f"/api/quotations/{q}", headers=h).json()
    assert client.put(f"/api/quotations/{q}", headers=h, json={"status": g0["status"], "data": g0["data"]}).status_code == 200   # 先存一次：本文進入「存過檔」的穩定形狀
    conn = get_db()
    try:                                                       # 還原成「舊資料」：本文沒有 docType、沒有編輯紀錄
        d = _json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (q,)).fetchone()["data_json"])
        d.pop("docType", None)
        d["editHistory"] = []
        d["status"] = "草稿"                                   # 升級前存過檔的單，本文裡本來就有 status
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (_json.dumps(d, ensure_ascii=False), q))
        conn.commit()
    finally:
        conn.close()
    g = client.get(f"/api/quotations/{q}", headers=h).json()
    assert g["data"]["docType"] == "quote"                    # 讀取端點注入
    r = client.put(f"/api/quotations/{q}", headers=h, json={"status": g["status"], "data": g["data"]})
    assert r.status_code == 200, r.text
    after = client.get(f"/api/quotations/{q}", headers=h).json()["data"]
    assert not after.get("editHistory"), "只多了 docType 不是使用者改的：不寫編輯紀錄"


@pytest.mark.parametrize("p", ["BT", "LN", "HC", "LV", "OT", "QT", "TE", "PC"])
def test_m3_prefixes_of_in_box_forms_and_expense_types_are_taken(p):
    from helpers import doc_type as DT
    assert DT.validate_prefix(p), p
    assert p in DT.used_prefixes()


def test_m3_used_prefixes_are_dynamic_not_a_static_list(monkeypatch):
    """現在實際有效的前綴都算：已發布的自訂模組、公司另外發布的費用類型，不在靜態清單裡也要擋。"""
    from helpers import custom_modules as CM, doc_type as DT, expense_types as ET
    assert not DT.validate_prefix("ZY") and not DT.validate_prefix("ZX")
    monkeypatch.setattr(CM, "used_prefixes", lambda conn=None: {"ZY": "自訂模組「巡檢單」"})
    monkeypatch.setattr(ET, "used_prefixes", lambda conn=None: {"ZX": "費用類型「雜支」"})
    assert "巡檢單" in DT.validate_prefix("ZY")
    assert "雜支" in DT.validate_prefix("ZX")


def test_m3_template_files_and_expense_defaults_feed_used_prefixes(client):
    from db import get_db
    from helpers import custom_modules as CM, expense_types as ET
    assert {"BT", "LN", "HC", "LV", "OT", "QT"} <= set(CM.used_prefixes())
    conn = get_db()
    try:
        assert {"PC", "PO", "PR", "TE"} <= set(ET.used_prefixes(conn))
    finally:
        conn.close()


def test_m3_custom_module_and_expense_type_editors_reject_the_estimate_prefix(client, make_user):
    """反方向：自訂模組／費用類型的單號前綴不可等於估價單字首（目前的與曾經用過的）。"""
    import copy
    from helpers import custom_modules as CM, expense_types as ET, settings_registry as sr
    u, pw = make_user(username="est_m3rev", role="superadmin")
    h = _login(client, u, pw)

    def bad_paths_cm(prefix):
        return [x["path"] for x in CM._validate_numbering({"prefix": prefix, "date": "YYYYMM", "digits": 3})]

    def bad_paths_et(prefix):
        body = copy.deepcopy(ET._default_for("travel"))
        body["numbering"] = {"prefix": prefix}
        return [x["path"] for x in ET.validate_expense_type(body, "travel")]

    assert "numbering.prefix" in bad_paths_cm("ME") and "numbering.prefix" in bad_paths_et("ME")
    assert "numbering.prefix" not in bad_paths_cm("ZQ") and "numbering.prefix" not in bad_paths_et("ZQ")
    _create(client, h, "estimate")                            # 開過一張 ME 估價單
    sr.publish("quote_defaults", {"estimate_no_prefix": "EQ"}, user=u, reason="test")
    assert "numbering.prefix" in bad_paths_cm("EQ") and "numbering.prefix" in bad_paths_et("EQ"), "目前字首"
    assert "numbering.prefix" in bad_paths_cm("ME") and "numbering.prefix" in bad_paths_et("ME"), "曾用過的字首也擋"


# ── 8. 熱路徑（hichan-2 重驗 N1）：estimate_prefix／rule_for／case_no_re 不可做重事 ────────────────

def test_hot_path_runs_no_sql_and_never_scans_prefix_sources(client, monkeypatch):
    """`case_no_re()` 每次稽核寫入都會跑（獎金核准是在寫入交易內）：只能做格式＋靜態檢查，不碰資料庫、不讀檔；
    和別的單據前綴有沒有撞，只在「存設定」時查（used_prefixes）。"""
    import time
    import db
    from helpers import doc_type as DT
    DT.case_no_re()                                            # 暖機：設定快取、歷史字首快取
    DT.rule_for("estimate")

    calls = []                                                 # 只記錄、不丟例外（estimate_prefix 會吞掉例外，丟了也看不到）

    def _spy(name, ret):
        def _f(*a, **k):
            calls.append(name)
            return ret
        return _f
    monkeypatch.setattr(DT, "used_prefixes", _spy("used_prefixes", {}))
    real_get_db = db.get_db
    monkeypatch.setattr(db, "get_db", lambda *a, **k: (calls.append("get_db"), real_get_db(*a, **k))[1])
    best = None
    for _ in range(3):                                         # 取三輪最小：機器忙碌時單輪會被拖慢
        t0 = time.perf_counter()
        for _i in range(200):
            DT.case_no_re()
            DT.rule_for("estimate")
        per_call = (time.perf_counter() - t0) / 400
        best = per_call if best is None else min(best, per_call)
    assert not calls, "熱路徑不可呼叫 %s" % sorted(set(calls))
    assert best < 0.0001, "case_no_re／rule_for 每次 %.3f ms，超過 0.1 ms" % (best * 1000)


def test_runtime_prefix_ignores_a_reserved_or_malformed_setting_value(client):
    """熱路徑只做便宜檢查，但不合法／保留的字首值（例如被直接寫進資料庫的）仍然回 ME，不會拿去開單。"""
    from helpers import doc_type as DT, settings_registry as sr
    from helpers.settings_registry import SettingError
    u = "n1_admin"
    with pytest.raises(SettingError):
        sr.publish("quote_defaults", {"estimate_no_prefix": "PO"}, user=u, reason="test")
    assert DT.estimate_prefix() == "ME"


def test_preview_and_archive_paths_take_doc_type_from_the_column(client, make_user):
    """T83：預覽路由與存檔版 PDF 都以 `doc_type` 欄位為準（同 generate_pdf_bytes），前端帶舊／缺的 docType 不會印回報價字樣。"""
    import pdf_gen
    u, pw = make_user(username="est_prev", role="admin")
    h = _login(client, u, pw)
    e = _create(client, h, "estimate")
    q = _create(client, h)
    stale = dict(_payload()["data"])            # 沒有 docType（等同舊／缺值）
    r = client.post("/api/quotations/preview-html", headers=h, json={"quoteNo": e, "data": stale, "internal": False})
    assert r.status_code == 200, r.text
    assert "估價單號：" in r.json()["html"] and "報價編號：" not in r.json()["html"]
    r = client.post("/api/quotations/preview-html", headers=h, json={"quoteNo": q, "data": dict(stale, docType="estimate"), "internal": False})
    assert r.status_code == 200, r.text
    assert "報價編號：" in r.json()["html"] and "估價單號：" not in r.json()["html"]
    src = inspect.getsource(pdf_gen._generate_quotation_pdf)
    assert "location_id, doc_type FROM quotations" in src and 'q["docType"] = _DT.norm(row["doc_type"])' in src
