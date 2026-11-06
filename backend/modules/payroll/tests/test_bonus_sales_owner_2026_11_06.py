"""業務獎金讀源改 `caseRecord.roles.sales`（2026-11-06 產品負責人裁示，經窗口轉達）。

裁示：業務獎金名單（以案件為中心的分潤，`api/bonus.py::_auto_members`）改讀案件「業務負責」`roles.sales`；
`roles.sales` **完全沒填**才退回報價人 `quotations.sales_person`；兩欄位仍各自存、互不寫入。
D1 已有分潤單的案件不回溯（名單在建立當下已凍結）；D2 `roles.sales` 有值但對不到可用帳號 ⇒ 不退回報價人、不帶人並提示手動指定；
D4 `person_source` 鍵名 `sales_person` 保留；舊版項目式獎金路徑（`/awards/plan`、`_case_people`）凍結不處理（D3：正式機從未啟用）。

題目：
1. 有值且不同人 ⇒ 帶 `roles.sales`；沒填 ⇒ 退回報價人（逐字沿用舊行為，正向控制）；兩邊同人 ⇒ 同一人。
2. 有值但對不到（舊字串查無／同名、帳號停用或不存在）⇒ 不帶人＋說明；**且不退回報價人**（反向控制：同案件把 roles.sales 清空，報價人就會被帶入）。
3. 已有分潤單 ⇒ 之後改 `roles.sales` 也不動名單、金額（不回溯）。
4. 留痕：`PERSON_SOURCES` 註解同時含兩次裁示的日期；舊路徑標凍結。
"""
import json
from pathlib import Path

import pytest

from modules.payroll.tests.test_bonus_case_api_2026_09_24 import (  # noqa: F401  (people 是 fixture)
    _auth, _create, _seed_case, _set_display, _uid, people,
)

HERE = Path(__file__).resolve().parent
BONUS_PY = HERE.parent / "bonus.py"
BONUS_API = HERE.parent / "api" / "bonus.py"


def _set_roles_sales(no, value):
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()[0])
        d["caseRecord"]["roles"]["sales"] = value
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), no))
        conn.commit()
    finally:
        conn.close()


def _row(no):
    import db
    conn = db.get_db()
    try:
        r = conn.execute("SELECT sales_person, sales_person_id, data_json FROM quotations WHERE quote_no=?", (no,)).fetchone()
        return r["sales_person"], r["sales_person_id"], r["data_json"]
    finally:
        conn.close()


def _preview(client, tok, no):
    d = client.get(f"/api/bonus/cases/{no}", headers=_auth(tok)).json()
    return [m["username"] for m in d["autoMembers"]["sales"]], d["memberNotes"].get("sales", "")


# ── 1. 讀源 ───────────────────────────────────────────────────────────────────
def test_roles_sales_object_wins_over_sales_person(client, people):
    _seed_case("MQ-SO-001", sales_id=_uid("bc_s1"), sales_name="報價人甲")
    _set_roles_sales("MQ-SO-001", {"username": "bc_other", "display": "舊顯示名"})
    got, note = _preview(client, people["bc_sa"], "MQ-SO-001")
    assert got == ["bc_other"] and note == ""
    assert _create(client, people["bc_sa"], "MQ-SO-001").status_code == 200
    lines = client.get("/api/bonus/cases/MQ-SO-001", headers=_auth(people["bc_sa"])).json()["lines"]
    assert {(l["category"], l["username"], l["source"]) for l in lines if l["category"] == "sales"} == {("sales", "bc_other", "auto_sales")}


def test_empty_roles_sales_falls_back_to_sales_person(client, people):
    """沒填 ⇒ 退回報價人（與改版前逐字相同）。"""
    for i, empty in enumerate(("", None, "  ", {}, {"username": "", "display": ""})):
        no = "MQ-SO-01%d" % i
        _seed_case(no, sales_id=_uid("bc_s1"), sales_name="報價人甲")
        _set_roles_sales(no, empty)
        got, note = _preview(client, people["bc_sa"], no)
        assert got == ["bc_s1"] and note == "", (empty, got, note)


def test_same_person_on_both_sides(client, people):
    _seed_case("MQ-SO-002", sales_id=_uid("bc_s1"), sales_name="同一人")
    _set_roles_sales("MQ-SO-002", {"username": "bc_s1", "display": "同一人"})
    assert _preview(client, people["bc_sa"], "MQ-SO-002")[0] == ["bc_s1"]


def test_legacy_string_unique_display_resolves(client, people):
    _set_display("bc_p1", "唯一的名字")
    _seed_case("MQ-SO-003", sales_id=_uid("bc_s1"), sales_name="報價人甲")
    _set_roles_sales("MQ-SO-003", "唯一的名字")
    assert _preview(client, people["bc_sa"], "MQ-SO-003") == (["bc_p1"], "")


# ── 2. 有值但對不到 ⇒ 不退回報價人 ───────────────────────────────────────────
@pytest.mark.parametrize("label,setup,value,needle", [
    ("舊字串查無", lambda: None, "查無此人", "對不到唯一的帳號"),
    ("舊字串同名", lambda: (_set_display("bc_p1", "同名"), _set_display("bc_p2", "同名")), "同名", "對不到唯一的帳號"),
    ("帳號不存在", lambda: None, {"username": "no_such_user", "display": "幽靈"}, "已停用或不存在"),
    ("帳號已停用", lambda: _deactivate("bc_p2"), {"username": "bc_p2", "display": "停用者"}, "已停用或不存在"),
])
def test_unresolvable_roles_sales_is_not_silently_replaced_by_sales_person(client, people, label, setup, value, needle):
    setup()
    no = "MQ-SO-2" + str(abs(hash(label)) % 1000)
    _seed_case(no, sales_id=_uid("bc_s1"), sales_name="報價人甲")        # 報價人本來解析得出（bc_s1）
    _set_roles_sales(no, value)
    got, note = _preview(client, people["bc_sa"], no)
    assert got == [] and "案件「業務負責」" in note and needle in note, (label, got, note)
    # 正向控制：同一張案件把業務負責清空 ⇒ 才會退回報價人 bc_s1（證明上面的空名單不是報價人解析壞掉）
    _set_roles_sales(no, "")
    assert _preview(client, people["bc_sa"], no) == (["bc_s1"], "")
    # 不能建立出一張帶錯人的單：未指定名單時建立，業務類沒有任何人
    _set_roles_sales(no, value)
    r = _create(client, people["bc_sa"], no)
    if r.status_code == 200:
        lines = client.get(f"/api/bonus/cases/{no}", headers=_auth(people["bc_sa"])).json()["lines"]
        assert [l for l in lines if l["category"] == "sales"] == []


def _deactivate(username):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE users SET active=0 WHERE username=?", (username,))
        conn.commit()
    finally:
        conn.close()


# ── 3. 不回溯：已有分潤單 ────────────────────────────────────────────────────
def test_existing_award_is_frozen_when_roles_sales_changes_later(client, people):
    _seed_case("MQ-SO-004", net=100, sales_id=_uid("bc_s1"), sales_name="報價人甲")
    _set_roles_sales("MQ-SO-004", {"username": "bc_other", "display": "高晟耀"})
    assert _create(client, people["bc_sa"], "MQ-SO-004").status_code == 200
    before = client.get("/api/bonus/cases/MQ-SO-004", headers=_auth(people["bc_sa"])).json()
    # 之後業務負責改成別人、報價人也改 ⇒ 分潤單名單與金額完全不變
    _set_roles_sales("MQ-SO-004", {"username": "bc_s1", "display": "又換人"})
    after = client.get("/api/bonus/cases/MQ-SO-004", headers=_auth(people["bc_sa"])).json()
    assert after["lines"] == before["lines"] and after["summary"] == before["summary"]
    assert {l["username"] for l in after["lines"] if l["category"] == "sales"} == {"bc_other"}
    # 不重新帶入：有單時回應沒有 autoMembers 預覽（那是無單時才算的）
    assert "autoMembers" not in after


def test_sales_person_columns_are_not_written_by_bonus_paths(client, people):
    """兩個欄位仍各自存、互不寫入：取預覽、建立分潤單後 quotations.sales_person／sales_person_id 位元組不變。"""
    _seed_case("MQ-SO-005", net=100, sales_id=_uid("bc_s1"), sales_name="報價人甲")
    _set_roles_sales("MQ-SO-005", {"username": "bc_other", "display": "高晟耀"})
    b = _row("MQ-SO-005")
    _preview(client, people["bc_sa"], "MQ-SO-005")
    assert _create(client, people["bc_sa"], "MQ-SO-005").status_code == 200
    a = _row("MQ-SO-005")
    assert a == b


# ── 4. 留痕與舊路徑凍結 ──────────────────────────────────────────────────────
def test_person_sources_comment_keeps_both_rulings_and_legacy_path_is_marked_frozen():
    src = BONUS_PY.read_text(encoding="utf-8")
    seg = src[src.index("#: 每個獎金項目各自綁一個人員來源"):src.index("PERSON_SOURCES = ")]
    assert "2026-09-23" in seg and "2026-11-06" in seg                      # 新舊裁示都留痕（不可只留最新的）
    assert "業務獎金→`sales_person`" in seg                                  # 舊裁示原話不刪
    assert "roles.sales" in seg and "推翻" in seg
    assert "凍結" in seg and "/awards/plan" in seg                           # 舊版項目式路徑標凍結（D3：正式機從未啟用）
    assert '"sales_person",' in src                                          # D4：鍵名保留
    api = BONUS_API.read_text(encoding="utf-8")
    i = api.index("def _case_people(")
    assert "凍結" in api[i:i + 3000]


# ── _roles_sales_of 單元 ─────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expect", [
    ({"username": "u1", "display": "甲"}, ("user", "u1", "甲")),
    ({"username": "u1"}, ("user", "u1", "u1")),
    ({"display": "乙"}, ("name", None, "乙")),
    ({"username": "", "display": ""}, ("empty", None, "")),
    ("丙", ("name", None, "丙")),
    ("  ", ("empty", None, "")),
    ("", ("empty", None, "")),
    (None, ("empty", None, "")),
    ({}, ("empty", None, "")),
    (123, ("empty", None, "")),
])
def test_roles_sales_of_shapes(raw, expect):
    from modules.payroll.api import bonus
    dj = json.dumps({"caseRecord": {"roles": {"sales": raw}}}, ensure_ascii=False)
    assert bonus._roles_sales_of(dj) == expect


@pytest.mark.parametrize("dj", ["", "{not json", "null", "[]", json.dumps({"caseRecord": None}), json.dumps({"caseRecord": {"roles": None}})])
def test_roles_sales_of_broken_or_missing_is_empty_not_exception(dj):
    from modules.payroll.api import bonus
    assert bonus._roles_sales_of(dj) == ("empty", None, "")


# ── D1：已建立分潤單的中性註記（只讀、只給最高管理者）────────────────────────────
def _set_status(no, status):
    import db
    conn = db.get_db()
    try:
        conn.execute("UPDATE bonus_case_awards SET status=? WHERE quote_no=?", (status, no))
        conn.commit()
    finally:
        conn.close()


def test_frozen_award_gets_neutral_note_when_current_sales_owner_differs(client, people):
    _seed_case("MQ-SO-006", net=100, sales_id=_uid("bc_s1"), sales_name="報價人甲")
    _set_display("bc_s1", "報價人甲")
    assert _create(client, people["bc_sa"], "MQ-SO-006").status_code == 200           # 建立當下業務負責沒填 ⇒ 帶報價人 bc_s1
    _set_status("MQ-SO-006", "待發放")
    get = lambda: client.get("/api/bonus/cases/MQ-SO-006", headers=_auth(people["bc_sa"])).json()
    assert "salesOwnerNote" not in get()                                              # 業務負責沒填 ⇒ 沒有註記
    _set_roles_sales("MQ-SO-006", {"username": "bc_s1", "display": "報價人甲"})
    assert "salesOwnerNote" not in get()                                              # 現行業務負責就在名單內 ⇒ 沒有註記
    _set_roles_sales("MQ-SO-006", {"username": "bc_other", "display": "高晟耀"})
    d = get()
    assert "報價人甲" in d["salesOwnerNote"] and "高晟耀" in d["salesOwnerNote"] and "已凍結" in d["salesOwnerNote"]
    # 只是註記：名單與金額與沒有註記時完全相同
    assert {l["username"] for l in d["lines"] if l["category"] == "sales"} == {"bc_s1"}
    _set_status("MQ-SO-006", "草稿")
    assert "salesOwnerNote" not in get()                                              # 草稿可直接看到、不需要註記


def test_note_is_not_shown_to_non_superadmin_scopes(client, people):
    _seed_case("MQ-SO-007", net=100, sales_id=_uid("bc_s1"), sales_name="報價人甲")
    assert _create(client, people["bc_sa"], "MQ-SO-007", members={"sales": [{"username": "bc_s1"}]}).status_code == 200
    _set_status("MQ-SO-007", "待發放")
    _set_roles_sales("MQ-SO-007", {"username": "bc_other", "display": "高晟耀"})
    for who in ("bc_cash", "bc_s1"):                       # 出納、名單上的本人
        r = client.get("/api/bonus/cases/MQ-SO-007", headers=_auth(people[who]))
        assert r.status_code == 200 and "salesOwnerNote" not in r.json(), who
