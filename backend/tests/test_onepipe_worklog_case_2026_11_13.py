# -*- coding: utf-8 -*-
"""onepipe P0b（2026-11-13）：工作日誌可選案件。旗標 `onepipe.worklog_case`（預設關）。

守的不變式：
  ① 旗標關＝和今天逐位元相同：新路由 404、寫入不檢查案件（照舊收任何 case_no）、列表與回應形狀不變、畫面不出現案件欄位、送出的內容不帶 case_no。
  ② 旗標開：日誌只能掛「自己看得到該案動態」的案件（與 `GET /api/quotations/{no}/updates` 同一條規則）；掛不上＝404（看不到＝不存在）且不寫入。
  ③ 日誌可見範圍不變：誰看得到日誌（`GET /api/work-logs`）與旗標無關；掛上案件之後只會出現在**看得到該案**的人的動態裡。
  ④ 掛上案件的日誌出現在該案動態與專案報告；選單只列進行中、看得到的案件、只有案號／客戶／案名。
"""
import json

import pytest

from core import source_tree


def _login(client, username, password="Test-Pass-123"):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]}


def _uid(username):
    import db
    c = db.get_db()
    try:
        return c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        c.close()


def _seed_case(quote_no, owner=None, tag="已成案", customer=None, project="專案"):
    import db
    at = "2026-11-10T09:00:00"
    uid = _uid(owner) if owner else None
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, "
                  "deal_tag, sales_person, sales_person_id, assigned_user_ids) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (quote_no, "已成案" if tag == "已成案" else tag, customer or ("客戶" + quote_no), project, 1000, 952,
                   json.dumps({"quoteNo": quote_no, "dealTag": tag}, ensure_ascii=False), at, at, tag, owner or "", uid, "[]"))
        c.commit()
    finally:
        c.close()


def _set_flag(on):
    import db
    from helpers import settings_groups  # noqa: F401  # 單獨跑時要先把群組登錄進去
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish("onepipe", {"worklog_case": 1 if on else 0}, reason="測試", user="onepipe_p0b_test", conn=c)
        c.commit()
    finally:
        c.close()
    SR.invalidate("onepipe")


@pytest.fixture(autouse=True)
def _flag_off_unless_asked(client):
    """預設值之後會改成「開」（一條龍上線＝預設開，由 h1 統一遷移）：本檔的『關』路徑測試一律先明確關掉，不靠預設值；要開的用 flag_on。"""
    _set_flag(False)
    yield
    _set_flag(False)


@pytest.fixture()
def flag_on():
    _set_flag(True)
    yield
    _set_flag(False)


def _post(client, h, **kw):
    body = {"log_date": "2026-11-13", "user_id": kw.pop("user_id"), "content": kw.pop("content", "今天去現場"), "hours": 4}
    body.update(kw)
    return client.post("/api/work-logs", json=body, headers=h)


def _rows(case_no=None):
    import db
    c = db.get_db()
    try:
        if case_no is None:
            return [dict(r) for r in c.execute("SELECT * FROM work_logs ORDER BY id").fetchall()]
        return [dict(r) for r in c.execute("SELECT * FROM work_logs WHERE case_no=? ORDER BY id", (case_no,)).fetchall()]
    finally:
        c.close()


# ── ① 旗標關＝今天 ───────────────────────────────────────────────────────────
def test_flag_is_registered_as_a_0_1_switch():
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as SR
    assert int(SR.get("onepipe", "worklog_case")) in (0, 1)           # 不釘預設值（預設開關由一條龍統一遷移決定）
    assert "onepipe" in SR.groups()


def test_flag_off_new_route_is_404_and_writes_do_not_check_the_case(client, make_user):
    u, p = make_user(username="p0b_off1", role="engineer", modules=["work_log"])
    h = _login(client, u, p)
    r = client.get("/api/work-logs/case-options", headers=h)
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    uid = _uid(u)
    r = _post(client, h, user_id=uid, case_no="MQ-NOPE-999")                 # 今天的行為：不檢查案件存不存在、看不看得到
    assert r.status_code == 200 and set(r.json()) == {"id", "ok"}
    assert _rows("MQ-NOPE-999")
    r = client.put("/api/work-logs/%d" % r.json()["id"], json={"case_no": "MQ-OTHER-1"}, headers=h)
    assert r.status_code == 200 and _rows("MQ-OTHER-1")


def test_flag_on_without_case_no_behaves_exactly_like_flag_off(client, make_user):
    u, p = make_user(username="p0b_same", role="engineer", modules=["work_log"])
    h = _login(client, u, p)
    uid = _uid(u)

    def lifecycle():
        a = _post(client, h, user_id=uid, content="沒有案件的日誌")
        lst = client.get("/api/work-logs?date=2026-11-13", headers=h)
        e = client.put("/api/work-logs/%d" % a.json()["id"], json={"content": "改過"}, headers=h)
        d = client.delete("/api/work-logs/%d" % a.json()["id"], headers=h)
        shape = lambda r: (r.status_code, sorted(r.json()) if isinstance(r.json(), dict) else [sorted(x) for x in r.json()])
        return [shape(a), shape(lst), shape(e), shape(d)]
    off = lifecycle()
    _set_flag(True)
    try:
        on = lifecycle()
    finally:
        _set_flag(False)
    assert on == off


# ── ② 旗標開：只能掛看得到的案件 ─────────────────────────────────────────────
def test_flag_on_only_cases_the_author_can_see_the_feed_of(client, make_user, flag_on):
    owner, po = make_user(username="p0b_owner", role="sales", modules=["work_log"])
    other, _po2 = make_user(username="p0b_other", role="sales", modules=["work_log"])
    mgr, pm = make_user(username="p0b_mgr", role="engineer", modules=["work_log", "case_manage"])
    adm, pa = make_user(username="p0b_adm", role="admin")
    _seed_case("MQ-P0B-001", owner=owner)
    ho, hm, hx, ha = _login(client, owner, po), _login(client, mgr, pm), _login(client, other, _po2), _login(client, adm, pa)
    assert _post(client, ho, user_id=_uid(owner), case_no="MQ-P0B-001").status_code == 200        # 案件業務
    assert _post(client, hm, user_id=_uid(mgr), case_no="MQ-P0B-001").status_code == 200          # 持有案件管理模組（看得到動態）
    assert _post(client, ha, user_id=_uid(adm), case_no="MQ-P0B-001").status_code == 200          # 管理員直通
    before = len(_rows())
    r = _post(client, hx, user_id=_uid(other), case_no="MQ-P0B-001")                               # 別人的案件、沒有案件管理模組
    assert r.status_code == 404 and "MQ-P0B-001" in r.json()["detail"]
    r2 = _post(client, hx, user_id=_uid(other), case_no="MQ-NOT-EXIST")                            # 不存在 ⇒ 同一個 404（不洩漏存不存在）
    assert r2.status_code == 404 and r2.json()["detail"].replace("MQ-NOT-EXIST", "X") == r.json()["detail"].replace("MQ-P0B-001", "X")
    assert len(_rows()) == before                                                                  # 沒有寫入
    import db
    c = db.get_db()
    try:
        n = c.execute("SELECT COUNT(*) FROM audit_log WHERE action='case.access_denied'").fetchone()[0]
    finally:
        c.close()
    assert n >= 1                                                                                  # 真正原因另記稽核


def test_flag_on_update_checks_only_when_moving_to_a_different_case(client, make_user, flag_on):
    owner, po = make_user(username="p0b_up_o", role="sales", modules=["work_log"])
    other, pt = make_user(username="p0b_up_x", role="sales", modules=["work_log"])
    _seed_case("MQ-P0B-U1", owner=owner)
    _seed_case("MQ-P0B-U2", owner=other)
    ho, hx = _login(client, owner, po), _login(client, other, pt)
    lid = _post(client, ho, user_id=_uid(owner), case_no="MQ-P0B-U1").json()["id"]
    assert client.put("/api/work-logs/%d" % lid, json={"case_no": "MQ-P0B-U2"}, headers=ho).status_code == 404      # 改掛別人的案件
    assert _rows("MQ-P0B-U1") and not _rows("MQ-P0B-U2")
    assert client.put("/api/work-logs/%d" % lid, json={"content": "只改內容", "case_no": "MQ-P0B-U1"}, headers=ho).status_code == 200
    assert client.put("/api/work-logs/%d" % lid, json={"case_no": ""}, headers=ho).status_code == 200              # 清空不擋
    assert not _rows("MQ-P0B-U1")


def test_flag_on_unchanged_case_is_not_rechecked(client, make_user, flag_on):
    """舊日誌掛的案件，之後這個人不再看得到（例如不再是協作者）：只改內容、案件原樣不動不能被擋。"""
    a, pa = make_user(username="p0b_rc_a", role="sales", modules=["work_log"])
    _seed_case("MQ-P0B-R1", owner=a)
    h = _login(client, a, pa)
    lid = _post(client, h, user_id=_uid(a), case_no="MQ-P0B-R1").json()["id"]
    import db
    c = db.get_db()
    c.execute("UPDATE quotations SET sales_person_id=NULL, sales_person='別人' WHERE quote_no='MQ-P0B-R1'")
    c.commit()
    c.close()
    assert client.put("/api/work-logs/%d" % lid, json={"content": "只改內容", "case_no": "MQ-P0B-R1"}, headers=h).status_code == 200


# ── ③ 日誌可見範圍不變 ───────────────────────────────────────────────────────
def test_work_log_list_visibility_does_not_depend_on_the_flag(client, make_user):
    a, pa = make_user(username="p0b_v_a", role="sales", modules=["work_log"])
    b, pb = make_user(username="p0b_v_b", role="sales", modules=["work_log"])
    _seed_case("MQ-P0B-V1", owner=a)
    ha, hb = _login(client, a, pa), _login(client, b, pb)
    _post(client, ha, user_id=_uid(a), content="甲的日誌", case_no="MQ-P0B-V1")
    _set_flag(True)
    try:
        on_b = [x["content"] for x in client.get("/api/work-logs?date=2026-11-13", headers=hb).json()]
        on_a = [x["content"] for x in client.get("/api/work-logs?date=2026-11-13", headers=ha).json()]
        feed_b = client.get("/api/quotations/MQ-P0B-V1/updates", headers=hb)
    finally:
        _set_flag(False)
    off_b = [x["content"] for x in client.get("/api/work-logs?date=2026-11-13", headers=hb).json()]
    off_a = [x["content"] for x in client.get("/api/work-logs?date=2026-11-13", headers=ha).json()]
    assert on_b == off_b and on_a == off_a                       # 列表與旗標無關（今天的行為，不多也不少）
    assert feed_b.status_code == 404                              # 掛上案件之後，沒有權限的人仍然看不到那個案件的動態


# ── ④ 動態、專案報告、選單 ───────────────────────────────────────────────────
def test_tagged_log_shows_in_that_cases_feed_and_not_in_others(client, make_user, flag_on):
    a, pa = make_user(username="p0b_f_a", role="sales", modules=["work_log", "case_manage"])
    _seed_case("MQ-P0B-F1", owner=a)
    _seed_case("MQ-P0B-F2", owner=a)
    h = _login(client, a, pa)
    _post(client, h, user_id=_uid(a), content="F1 的日誌", case_no="MQ-P0B-F1")
    f1 = client.get("/api/quotations/MQ-P0B-F1/updates", headers=h).json()
    f2 = client.get("/api/quotations/MQ-P0B-F2/updates", headers=h).json()
    rows1 = f1 if isinstance(f1, list) else f1.get("items", f1)
    rows2 = f2 if isinstance(f2, list) else f2.get("items", f2)
    assert any(x.get("source") == "work_log" and x.get("content") == "F1 的日誌" for x in rows1)
    assert not any(x.get("source") == "work_log" for x in rows2)


def test_tagged_log_shows_in_the_project_execution_report(client, make_user, flag_on):
    import pdf_gen
    a, pa = make_user(username="p0b_r_a", role="sales", modules=["work_log"])
    _seed_case("MQ-P0B-P1", owner=a)
    _post(client, _login(client, a, pa), user_id=_uid(a), content="報告裡要有這筆", case_no="MQ-P0B-P1")
    data = pdf_gen._project_execution_report_data("MQ-P0B-P1")
    assert [w["content"] for w in data["workLogs"]] == ["報告裡要有這筆"]


def test_case_options_list_only_active_visible_cases_with_no_money_fields(client, make_user, flag_on):
    a, pa = make_user(username="p0b_o_a", role="sales", modules=["work_log"])
    b, pb = make_user(username="p0b_o_b", role="sales", modules=["work_log"])
    _seed_case("MQ-P0B-O1", owner=a, customer="甲公司", project="機房改造")
    _seed_case("MQ-P0B-O2", owner=a, tag="已結案", customer="結案公司")            # 已結案不列
    _seed_case("MQ-P0B-O3", owner=a, tag="", customer="報價中公司")                 # 還不是成案不列
    _seed_case("MQ-P0B-O4", owner=b, customer="乙公司")                             # 別人的案件不列
    _seed_case("MQ-P0B-O5", owner=a, customer="100%_特殊", project="含 % 與 _ 的案名")
    h = _login(client, a, pa)
    items = client.get("/api/work-logs/case-options", headers=h).json()["items"]
    assert sorted(x["quoteNo"] for x in items) == ["MQ-P0B-O1", "MQ-P0B-O5"]
    assert all(set(x) == {"quoteNo", "customer", "projectName"} for x in items)
    assert [x["quoteNo"] for x in client.get("/api/work-logs/case-options?q=甲公司", headers=h).json()["items"]] == ["MQ-P0B-O1"]
    assert [x["quoteNo"] for x in client.get("/api/work-logs/case-options?q=%25", headers=h).json()["items"]] == ["MQ-P0B-O5"]     # % 當一般字元
    assert client.get("/api/work-logs/case-options?q=" + "x" * 500, headers=h).status_code == 200
    r = client.get("/api/work-logs/case-options")
    assert r.status_code in (401, 403)
    nomod, pn = make_user(username="p0b_o_nm", role="viewer", modules=[])
    assert client.get("/api/work-logs/case-options", headers=_login(client, nomod, pn)).status_code == 403


def test_case_options_are_capped(client, make_user, flag_on):
    a, pa = make_user(username="p0b_cap", role="sales", modules=["work_log"])
    for i in range(45):
        _seed_case("MQ-P0B-C%03d" % i, owner=a)
    items = client.get("/api/work-logs/case-options", headers=_login(client, a, pa)).json()["items"]
    assert len(items) == 30 and items[0]["quoteNo"] == "MQ-P0B-C044"                # 最新的在前、最多 30 筆


# ── 靜態：畫面只在旗標開時才有案件欄位，送出的內容旗標關時不帶 case_no ─────────────────
def test_page_wires_the_flag_and_keeps_the_payload_unchanged_when_off():
    s = source_tree.page_file("work-log.html").read_text(encoding="utf-8")
    assert "public-flags.js" in s and "MotrixPublicFlags.read(['onepipe']" in s and "worklog_case" in s
    assert "...(this.caseLinkOn ? { case_no: this.caseNo || '' } : {})" in s            # 旗標關 ⇒ 不帶 case_no
    for tid in ("wl-case-field", "wl-case-th", "wl-case-td"):
        seg = s.split('data-testid="%s"' % tid)[0].rsplit("<template", 1)[-1]
        assert seg.startswith(' x-if="caseLinkOn"'), tid                              # 三處都包在 x-if 裡：旗標關時 DOM 完全沒有


# ── e2e：旗標關 vs 開 ───────────────────────────────────────────────────────
@pytest.mark.e2e
def test_e2e_flag_off_has_no_case_field_and_posts_no_case_no(live_server, make_user, new_page, login_as):
    pytest.importorskip("playwright.sync_api")
    creds = make_user(username="p0b_e2e_off", role="engineer", modules=["work_log"])
    page = new_page(viewport={"width": 1280, "height": 800})
    posted = []
    page.on("request", lambda rq: posted.append(rq.post_data) if rq.method == "POST" and rq.url.endswith("/api/work-logs") else None)
    login_as(page, creds)
    page.goto(f"{live_server}/pages/work-log.html")
    page.get_by_role("button", name="新增日誌").first.click()
    page.locator("textarea").first.fill("旗標關的日誌")
    from playwright.sync_api import expect
    expect(page.locator("[data-testid=wl-case-field]")).to_have_count(0)               # 旗標關 ⇒ DOM 沒有這欄（用 expect 等畫面穩定，不是動作後立刻 count()）
    expect(page.locator("[data-testid=wl-case-th]")).to_have_count(0)
    page.get_by_role("button", name="新增日誌").last.click()
    page.wait_for_timeout(800)
    assert posted and "case_no" not in json.loads(posted[-1])


@pytest.mark.e2e
def test_e2e_flag_on_picks_a_case_and_the_row_shows_it(live_server, make_user, new_page, login_as):
    pytest.importorskip("playwright.sync_api")
    creds = make_user(username="p0b_e2e_on", role="sales", modules=["work_log"])
    _seed_case("MQ-P0B-E1", owner=creds[0], customer="畫面測試公司")
    _set_flag(True)
    try:
        page = new_page(viewport={"width": 1280, "height": 800})
        posted = []
        page.on("request", lambda rq: posted.append(rq.post_data) if rq.method == "POST" and rq.url.endswith("/api/work-logs") else None)
        login_as(page, creds)
        page.goto(f"{live_server}/pages/work-log.html")
        page.get_by_role("button", name="新增日誌").first.click()
        page.locator("[data-testid=wl-case-field]").wait_for(state="visible", timeout=15000)
        page.locator("textarea").first.fill("旗標開的日誌")
        page.locator("[data-testid=wl-case-select]").select_option("MQ-P0B-E1")
        page.get_by_role("button", name="新增日誌").last.click()
        page.locator("[data-testid=wl-case-td]").first.wait_for(state="visible", timeout=15000)
        assert json.loads(posted[-1])["case_no"] == "MQ-P0B-E1"
        assert page.locator("[data-testid=wl-case-td]").first.inner_text().strip() == "MQ-P0B-E1"
    finally:
        _set_flag(False)
