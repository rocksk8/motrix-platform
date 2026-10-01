"""A2-2：費用單據類型定義（`helpers.expense_types`）。
① 四個預設定義全部通過驗證、前綴各不相同、`payable` 與計畫一致（請購單否）
② `validate_expense_type` 的每一條規則各有一題反向（缺前綴／payable／lines、docType 未登記、明細欄不成立、保留鍵型別、editableBy、前綴撞名、ui 引用不到）
③ 讀取：沒有發布版＝程式預設（版本 0）；公司發布後覆蓋；單據釘住的版本取得舊內容；停用的不列
④ `normalize_lines`：qty×unitCost 四捨五入、amount 權威、未知鍵原樣保留、負數／非數字報錯
⑤ `validate_values`：locked 預填以伺服器為準、必填／未知鍵／型別、出納欄位只有出納可填、明細未知鍵不丟、合計是唯一來源
⑥ API：`GET /api/expense-types[/{code}]` 任何登入者；草稿→發布走既有 `/api/definitions/expense_type`（超級管理員）
反向控制：`normalize_lines` 改成信任前端 amount ⇒ ④ 必須紅；`validate_values` 不蓋 locked ⇒ ⑤ 必須紅。"""
import copy

import pytest

import db
from core import definitions as D
from helpers import expense_types as ET

CODES = ET.DEFAULT_KINDS


def _tok(client, u):
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]}


def _dept():
    conn = db.get_db()
    try:
        conn.execute("INSERT OR IGNORE INTO divisions (name, created_at) VALUES ('測試處', '2026-10-01')")
        div = conn.execute("SELECT id FROM divisions WHERE name='測試處'").fetchone()["id"]
        conn.execute("INSERT OR IGNORE INTO departments (division_id, name, created_at) VALUES (?, '測試部', '2026-10-01')", (div,))
        did = conn.execute("SELECT id FROM departments WHERE name='測試部'").fetchone()["id"]
        conn.commit()
        return did
    finally:
        conn.close()


# ── ① 預設定義 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code", CODES)
def test_default_definitions_validate(code):
    body = ET._default_for(code)
    assert ET.validate_expense_type(body, code) == []


def test_default_prefixes_and_payable_follow_plan():
    got = {c: (ET._default_for(c)["numbering"]["prefix"], ET._default_for(c)["payable"]) for c in CODES}
    assert got == {"purchase_req": ("PR", False), "purchase_order": ("PO", True), "travel": ("TE", True), "petty_cash": ("PC", True)}
    assert ET._default_for("nope") is None and ET._default_for("../x") is None


# ── ② 驗證規則（每條一題反向）────────────────────────────────────────────────

def _mut(fn, code="travel"):
    b = copy.deepcopy(ET._default_for(code))
    fn(b)
    return ET.validate_expense_type(b, code)


def _paths(problems):
    return [p["path"] for p in problems]


def test_validator_reverse_cases():
    assert "numbering.prefix" in _paths(_mut(lambda b: b.pop("numbering")))
    assert "numbering.prefix" in _paths(_mut(lambda b: b["numbering"].update(prefix="lower")))
    assert "numbering" in _paths(_mut(lambda b: b["numbering"].update(digits=6)))
    assert "numbering.prefix" in _paths(_mut(lambda b: b["numbering"].update(prefix="PR")))                 # 撞請購單
    assert "payable" in _paths(_mut(lambda b: b.pop("payable")))
    assert "docType" in _paths(_mut(lambda b: b.update(docType="not_registered")))
    assert "name" in _paths(_mut(lambda b: b.update(name=" ")))
    assert "fields" in _paths(_mut(lambda b: b.update(fields=[])))
    assert "fields" in _paths(_mut(lambda b: b.update(fields=[f for f in b["fields"] if f["key"] != "lines"])))   # 沒有 lines
    def drop_col(b, k):
        lines = next(f for f in b["fields"] if f["key"] == "lines")
        lines["columns"] = [c for c in lines["columns"] if c["key"] != k]
    for k in ("category", "summary", "amount"):
        assert any("必須有欄位 %s" % k in p["message"] for p in _mut(lambda b, k=k: drop_col(b, k)))
    assert any("必須一起出現" in p["message"] for p in _mut(lambda b: drop_col(b, "unitCost")))
    assert any("lines 必須是明細表" in p["message"] for p in _mut(lambda b: next(f for f in b["fields"] if f["key"] == "lines").update(type="text")))
    assert any("保留鍵 applicant" in p["message"] for p in _mut(lambda b: next(f for f in b["fields"] if f["key"] == "applicant").update(type="text")))
    assert any("editableBy" in p["path"] for p in _mut(lambda b: next(f for f in b["fields"] if f["key"] == "city").update(editableBy="cashier")))
    assert any("locked" in p["path"] for p in _mut(lambda b: next(f for f in b["fields"] if f["key"] == "applicant").update(locked="yes")))
    assert any("引用不到的欄位" in p["message"] for p in _mut(lambda b: b["ui"]["form"]["groups"][0]["fields"].append("ghost")))
    assert ET.validate_expense_type([], "x") and ET.validate_expense_type({}, "Bad-Code")
    assert any("只能有一個明細表" in p["message"] for p in _mut(lambda b: b["fields"].append(
        {"key": "other_t", "label": "x", "type": "table", "columns": [{"key": "a", "label": "a", "type": "text"}]})))


def test_camel_case_line_keys_are_accepted_but_unknown_formula_refs_are_not():
    def bad_formula(b):
        next(c for f in b["fields"] if f["key"] == "lines" for c in f["columns"] if c["key"] == "amount")["formula"] = "qty * nope"
    assert any("引用不到欄位" in p["message"] for p in _mut(bad_formula))


# ── ③ 讀取 ─────────────────────────────────────────────────────────────────

def test_get_and_list_types(client):
    conn = db.get_db()
    try:
        t = ET.get_type(conn, "travel")
        assert t["version"] == 0 and t["body"]["name"] == "差旅費用請款單"            # 沒發布＝程式預設
        assert {x["code"] for x in ET.list_types(conn)} >= set(CODES)
        body = copy.deepcopy(ET._default_for("travel"))
        body["name"] = "差旅（公司版）"
        D.save_draft(conn, "expense_type", "travel", "company", body, "boss")
        D.publish(conn, "expense_type", "travel", "company", "v1", "boss")
        assert ET.get_type(conn, "travel")["body"]["name"] == "差旅（公司版）" and ET.get_type(conn, "travel")["version"] == 1
        assert ET.get_type(conn, "travel", 0)["body"]["name"] == "差旅費用請款單"     # 釘在版本 0 的舊單
        assert ET.get_type(conn, "travel", 1)["body"]["name"] == "差旅（公司版）"
        assert ET.get_type(conn, "travel", 9) is None and ET.get_type(conn, "nope") is None and ET.get_type(conn, "../x") is None
        body2 = dict(body, enabled=False)
        D.save_draft(conn, "expense_type", "travel", "company", body2, "boss")
        D.publish(conn, "expense_type", "travel", "company", "停用", "boss")
        assert "travel" not in {x["code"] for x in ET.list_types(conn)}
        with pytest.raises(D.DefinitionError):                                           # 發布前驗證器擋下壞的定義
            D.save_draft(conn, "expense_type", "travel", "company", dict(body, payable="yes"), "boss")
            D.publish(conn, "expense_type", "travel", "company", "壞", "boss")
    finally:
        conn.rollback()
        conn.close()


# ── ④ 明細金額 ─────────────────────────────────────────────────────────────

def test_normalize_lines_rules():
    rows, total = ET.normalize_lines([
        {"category": " 交通 ", "summary": "高鐵", "qty": 2, "unitCost": 100.5, "amount": 1, "categoryCode": "TRAVEL", "files": [{"path": "p"}], "custom": "x"},
        {"category": "雜支", "summary": "文具", "amount": 49.5},
    ])
    assert [r["amount"] for r in rows] == [201, 50] and total == 251                     # qty×unitCost 蓋掉前端 amount；其餘四捨五入
    assert rows[0]["category"] == "交通" and rows[0]["categoryCode"] == "TRAVEL" and rows[0]["files"] == [{"path": "p"}] and rows[0]["custom"] == "x"
    assert ET.normalize_lines(None) == ([], 0) and ET.normalize_lines([]) == ([], 0)
    for bad in ([{"summary": "x"}], [{"amount": -1}], [{"qty": -1, "unitCost": 5}], [{"amount": "12"}], [{"amount": True}],
                [{"amount": float("nan")}], ["x"], "x", [{"summary": 5, "amount": 1}], [{}] * 201):
        with pytest.raises(ValueError):
            ET.normalize_lines(bad)


# ── ⑤ 值驗證 ───────────────────────────────────────────────────────────────

@pytest.fixture()
def actors(client, make_user):
    me = make_user(username="et_me", role="admin")
    other = make_user(username="et_other", role="admin")
    cash = make_user(username="et_cash", role="admin", modules=["cashier"])
    return {"me": {"username": me[0], "role": "admin", "modules": []}, "other": other[0],
            "cash": {"username": cash[0], "role": "admin", "modules": ["cashier"]}}


def _line(**kw):
    d = {"category": "交通", "summary": "高鐵", "qty": 2, "unitCost": 100, "invoiceNo": "AB123"}
    d.update(kw)
    return d


def test_validate_values_happy_path_locked_and_total(actors):
    did = _dept()
    defn = ET._default_for("travel")
    conn = db.get_db()
    try:
        data = {"applicant": actors["other"], "dept": str(did), "cost_dept": str(did), "place": "國內", "city": "台北",
                "period": {"from": "2026-10-01", "to": "2026-10-02"}}
        clean, lines, total, problems = ET.validate_values(conn, defn, data, [_line(categoryCode="TRAVEL", extra="keep")], viewer=actors["me"])
        assert problems == [], problems
        assert clean["applicant"] == actors["me"]["username"]                               # locked：前端送別人也以伺服器預填為準
        assert clean["req_date"] and clean["total"] == 200 and total == 200
        assert lines[0]["amount"] == 200 and lines[0]["categoryCode"] == "TRAVEL" and lines[0]["extra"] == "keep"     # 未知鍵不丟
        assert "lines" not in clean
    finally:
        conn.close()


def test_validate_values_reports_required_unknown_and_type_errors(actors):
    did = _dept()
    defn = ET._default_for("travel")
    conn = db.get_db()
    try:
        _c, _l, _t, problems = ET.validate_values(conn, defn, {"dept": str(did), "ghost": 1, "place": "火星"}, [], viewer=actors["me"])
        keys = {p["key"] for p in problems}
        assert {"ghost", "place", "city", "cost_dept", "period", "lines"} <= keys, keys
        _c, _l, _t, problems = ET.validate_values(conn, defn, {"dept": str(did)}, [_line(qty=-1)], viewer=actors["me"])
        assert any(p["key"] == "lines" for p in problems)                                    # 明細金額錯 ⇒ 整批擋下、不回合計
        assert _c == {} and _t == 0
        _c, _l, _t, problems = ET.validate_values(conn, defn, {"dept": "99999"}, [_line()], viewer=actors["me"])
        assert any(p["key"] == "dept" for p in problems)                                     # 參照不到的部門
    finally:
        conn.close()


def test_cashier_only_fields(actors):
    did = _dept()
    defn = ET._default_for("purchase_order")
    base = {"dept": str(did), "vendor": "甲廠商", "pay_terms": "月結 30 天", "remit_date": "2026-10-31"}
    conn = db.get_db()
    try:
        clean, _l, _t, problems = ET.validate_values(conn, defn, base, [_line()], viewer=actors["me"])
        assert {p["key"] for p in problems} >= {"pay_terms", "remit_date"}                     # 一般人送出納欄位 ⇒ 回報＋丟掉
        assert "pay_terms" not in clean and "remit_date" not in clean
        clean, _l, _t, problems = ET.validate_values(conn, defn, base, [_line()], viewer=actors["cash"])
        assert problems == [] and clean["pay_terms"] == "月結 30 天" and clean["remit_date"] == "2026-10-31"
        assert ET.cashier_field_keys(defn) == ["pay_terms", "remit_date"]
    finally:
        conn.close()


@pytest.mark.parametrize("code,extra", [("purchase_req", {"ptype": "辦公庶務用品", "remark": "x", "need_period": {"from": "2026-10-01", "to": "2026-10-05"}}),
                                          ("purchase_order", {"vendor": "甲"}),
                                          ("petty_cash", {"payee": "文具行"})])
def test_every_default_type_accepts_a_minimal_valid_document(actors, code, extra):
    did = _dept()
    defn = ET._default_for(code)
    conn = db.get_db()
    try:
        data = dict(extra, dept=str(did))
        lines = [_line()] if code != "petty_cash" else [{"category": "雜支", "summary": "文具", "amount": 88}]
        clean, _l, total, problems = ET.validate_values(conn, defn, data, lines, viewer=actors["me"])
        assert problems == [], problems
        assert total == (200 if code != "petty_cash" else 88) and clean["total"] == total
    finally:
        conn.close()


# ── ⑥ API ─────────────────────────────────────────────────────────────────

def test_api_read_and_definition_editing(client, make_user):
    boss = _tok(client, make_user(username="et_boss", role="superadmin")[:2])
    user = _tok(client, make_user(username="et_user", role="viewer")[:2])
    r = client.get("/api/expense-types", headers=user)
    assert r.status_code == 200 and {x["code"] for x in r.json()} >= set(CODES), r.text
    pr = next(x for x in r.json() if x["code"] == "purchase_req")
    assert pr["prefix"] == "PR" and pr["payable"] is False and pr["defVersion"] == 0
    r = client.get("/api/expense-types/travel", headers=user)
    assert r.status_code == 200 and r.json()["defVersion"] == 0 and r.json()["definition"]["numbering"]["prefix"] == "TE"
    assert client.get("/api/expense-types/travel?version=0", headers=user).status_code == 200
    assert client.get("/api/expense-types/nope", headers=user).status_code == 404
    assert client.get("/api/expense-types").status_code in (401, 403)
    # 編輯走既有定義庫路由：viewer 403；superadmin 存草稿（壞的被驗證擋下）、發布後讀取端看到新版
    body = copy.deepcopy(ET._default_for("petty_cash"))
    body["name"] = "零用金（改名）"
    assert client.put("/api/definitions/expense_type/petty_cash/draft", headers=user, json={"body": body}).status_code == 403
    bad = dict(body, payable="yes")
    v = client.post("/api/definitions/expense_type/petty_cash/validate", headers=boss, json={"body": bad})
    assert v.status_code == 200 and any(p["path"] == "payable" for p in (v.json().get("problems") or []))
    assert client.put("/api/definitions/expense_type/petty_cash/draft", headers=boss, json={"body": body}).status_code == 200
    pub = client.post("/api/definitions/expense_type/petty_cash/publish", headers=boss, json={"note": "改名"})
    assert pub.status_code == 200, pub.text
    got = client.get("/api/expense-types/petty_cash", headers=user).json()
    assert got["defVersion"] == 1 and got["definition"]["name"] == "零用金（改名）"
    assert client.get("/api/expense-types/petty_cash?version=0", headers=user).json()["definition"]["name"] == "零用金支付單"
