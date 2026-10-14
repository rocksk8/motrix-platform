# -*- coding: utf-8 -*-
"""財務盤點 F2（銀行對帳單欄位別名）／F3（出納即將到期天數）／S-C1（結案條件只收緊）。純函式題可用 --noconftest 單跑。
- F2：預設別名逐字等於 cashier.py 原本的三個常數；旗標關＝預設；開＝用設定（順序、去重、全形逗號與頓號）；不合法的欄 ⇒ 該欄退回預設；
  設定讀取失敗 ⇒ 預設；用自訂別名可以讀懂陌生標頭的 CSV，找不到金額欄一樣 400
- F3：cashier.js 的預設仍是 7／3，只有旗標開且值合法才換；提示文字改由 plannedSoonDays 組出
- S-C1：opts 缺省／全關 ⇒ 與過去逐項相同；**單調性**：任何選項組合下，被擋的關卡集合只增不減（只收緊）；
  每個選項只翻它對應的那一關、且只在『原本是無需檢查』時；收款／單據／精算／額外支出四關沒有任何『關閉』選項；
  讀不到設定 ⇒ 全開（往嚴）；所有選項關閉都是放寬（loosen=down）
- 需要資料庫的題（寫好未跑）：設定寫入後 close-gates 端點與擋結案跟著變；旗標關時回應與今天相同"""
import itertools
import sqlite3
from pathlib import Path

import pytest

from helpers import finance_params as F

ROOT = Path(__file__).resolve().parents[1]
FRONT = ROOT.parent / "frontend"


# ── F2 ─────────────────────────────────────────────────────────────────────────
def test_default_aliases_equal_the_old_constants():
    from modules.arap.api import cashier as C
    assert F.DEFAULT_BANK_ALIASES == {"date": C._BANK_DATE_ALIASES, "amount": C._BANK_AMOUNT_ALIASES, "desc": C._BANK_DESC_ALIASES}


def test_the_group_defaults_are_the_joined_default_lists():
    from helpers import settings_registry as SR
    import helpers.settings_groups  # noqa: F401
    for k in ("date", "amount", "desc"):
        assert SR.get("finance_cashier", "bank_alias_" + k) == F.aliases_text(F.DEFAULT_BANK_ALIASES[k])
        assert F.parse_aliases(F.aliases_text(F.DEFAULT_BANK_ALIASES[k])) == F.DEFAULT_BANK_ALIASES[k]


def test_parse_aliases():
    assert F.parse_aliases("ab, bc，cd、 ab\n de") == ["ab", "bc", "cd", "de"]
    for bad in ("", "  ,, ", None, 5, "x" * 31, "ab, c", "金", ",".join("a%d" % i for i in range(21))):          # 單字別名（包含比對會誤配）整欄拒絕
        assert F.parse_aliases(bad) is None, bad


def _sr(monkeypatch, values):
    from helpers import settings_registry as SR

    def get(group, field, conn=None, **kw):
        if group != "finance_cashier":
            raise KeyError(group)
        return values[field]
    monkeypatch.setattr(SR, "get", get)


BASE_VALUES = {"custom_bank_aliases": 0, "bank_alias_date": "Booking Date", "bank_alias_amount": "Betrag", "bank_alias_desc": "Text"}


def test_flag_off_gives_the_defaults(monkeypatch):
    _sr(monkeypatch, BASE_VALUES)
    assert F.bank_aliases() == F.DEFAULT_BANK_ALIASES and F.bank_aliases() is not F.DEFAULT_BANK_ALIASES


def test_flag_on_uses_the_saved_lists_and_falls_back_per_field(monkeypatch):
    _sr(monkeypatch, dict(BASE_VALUES, custom_bank_aliases=1))
    assert F.bank_aliases() == {"date": ["Booking Date"], "amount": ["Betrag"], "desc": ["Text"]}
    _sr(monkeypatch, dict(BASE_VALUES, custom_bank_aliases=1, bank_alias_amount="  ,, "))
    out = F.bank_aliases()
    assert out["amount"] == F.DEFAULT_BANK_ALIASES["amount"] and out["date"] == ["Booking Date"]


def test_settings_failure_gives_the_defaults(monkeypatch):
    from helpers import settings_registry as SR
    monkeypatch.setattr(SR, "get", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    assert F.bank_aliases() == F.DEFAULT_BANK_ALIASES


def test_parse_bank_csv_defaults_and_custom_headers(monkeypatch):
    from fastapi import HTTPException
    from modules.arap.api import cashier as C
    csv_default = "交易日期,金額,摘要\n2026-10-01,1000,測試\n".encode("utf-8")
    _sr(monkeypatch, BASE_VALUES)
    rows = C._parse_bank_csv(csv_default)
    assert len(rows) == 1
    odd = "Booking Date,Betrag,Text\n2026-10-01,1000,hello\n".encode("utf-8")
    with pytest.raises(HTTPException) as e:
        C._parse_bank_csv(odd)                                             # 旗標關：看不懂陌生標頭 ⇒ 沒有金額欄 ⇒ 400（與今天相同）
    assert e.value.status_code == 400
    _sr(monkeypatch, dict(BASE_VALUES, custom_bank_aliases=1))
    assert len(C._parse_bank_csv(odd)) == 1                                # 旗標開：讀得懂
    with pytest.raises(HTTPException):
        C._parse_bank_csv("A,B\n1,2\n".encode("utf-8"))                    # 仍然不猜：找不到金額欄一樣擋下


# ── F3 ─────────────────────────────────────────────────────────────────────────
def test_cashier_js_defaults_and_wiring():
    js = (FRONT / "js/cashier.js").read_text(encoding="utf-8")
    assert "dueSoonDays: 7," in js and "plannedSoonDays: 3," in js
    assert "soon.setDate(soon.getDate() + this.dueSoonDays)" in js and "diff <= this.plannedSoonDays" in js
    assert "soon.getDate() + 7" not in js and "diff <= 3 ?" not in js
    assert "custom_due_soon !== 1" in js and "/api/settings-center/public?groups=finance_cashier" in js
    assert "this.loadDueSoonDays()" in js and js.count("loadDueSoonDays") == 2 + 0 or js.count("loadDueSoonDays") >= 2
    html = (FRONT / "pages/cashier.html").read_text(encoding="utf-8")
    assert html.count("plannedSoonDays + ' 天內到期'") == 2 and ">3 天內到期</div>" in html          # 預設文字仍是 3


# ── S-C1 ───────────────────────────────────────────────────────────────────────
def _q():
    from modules.case.api import quotations as Q
    return Q


ALL_OFF = {k: False for k in F.CLOSE_GATE_OPTIONS}
ALL_ON = {k: True for k in F.CLOSE_GATE_OPTIONS}


def _scenarios():
    stages = [(0, 0), (4, 4), (4, 2)]
    docs_ok = [("報價單", "quotations", 0, []), ("出貨單", "shipping_notes", 1, [])]
    docs_pend = [("出貨單", "shipping_notes", 2, ['{"tiers":[{"approvers":[{"username":"a","status":"x"}]}],"currentTier":0}'])]
    xes = [(0, 0), (3, 0), (3, 1)]
    pay = [None, [{"received": True}], [{"received": False}]]
    sett = [None, {"status": "finalized"}, {"status": "draft"}]
    for st, dc, xe, p, se, dr in itertools.product(stages, [docs_ok, docs_pend], xes, pay, sett, [0, 2]):
        facts = {"stages": st, "docs": dc, "xe": xe, "xe_draft": dr, "xe_mid": dr}
        d = {"caseRecord": {"payment": {"items": p}} if p else {}, "settlement": se} if (p or se) else {}
        if se:
            d["settlement"] = se
        yield facts, d


def test_opts_absent_or_all_off_is_identical_to_the_old_path():
    Q = _q()
    n = 0
    for facts, d in _scenarios():
        a = Q._gates_from_facts(facts, d)
        assert a == Q._gates_from_facts(facts, d, None) == Q._gates_from_facts(facts, d, ALL_OFF)
        n += 1
    assert n > 300


def test_old_path_keeps_the_na_semantics():
    Q = _q()
    g = {x["key"]: x for x in Q._gates_from_facts({"stages": (0, 0), "docs": [], "xe": (0, 0)}, {})}
    assert [g[k]["state"] for k in ("progress", "payment", "documents", "settlement", "extraExpense")] == ["na"] * 5


def test_options_only_tighten_never_unblock():
    """單調性：任何選項組合下，被擋的關卡集合 ⊇ 不加嚴時被擋的關卡集合。"""
    Q = _q()
    combos = [dict(zip(F.CLOSE_GATE_OPTIONS, bits)) for bits in itertools.product([False, True], repeat=len(F.CLOSE_GATE_OPTIONS))]
    for facts, d in _scenarios():
        base = {g["key"] for g in Q._gates_from_facts(facts, d) if g["state"] == "blocked"}
        for o in combos:
            now = {g["key"] for g in Q._gates_from_facts(facts, d, o) if g["state"] == "blocked"}
            assert base <= now, (facts, d, o)


def test_each_option_flips_only_its_own_gate_and_only_from_na():
    Q = _q()
    want = {"require_stages": "progress", "require_payment_items": "payment", "require_settlement": "settlement", "count_unfinished_extra_expenses": "extraExpense"}
    empty = {"stages": (0, 0), "docs": [], "xe": (3, 0), "xe_draft": 3, "xe_mid": 0}
    for opt, key in want.items():
        o = dict(ALL_OFF, **{opt: True})
        before = {g["key"]: g["state"] for g in Q._gates_from_facts(empty, {})}
        after = {g["key"]: g["state"] for g in Q._gates_from_facts(empty, {}, o)}
        changed = {k for k in before if before[k] != after[k]}
        assert changed == {key}, (opt, changed)
        assert after[key] == "blocked"
    done = {"stages": (4, 4), "docs": [], "xe": (3, 0), "xe_draft": 0, "xe_mid": 0}                # 資料俱全時，選項不會多擋
    d = {"caseRecord": {"payment": {"items": [{"received": True}]}}, "settlement": {"status": "finalized"}}
    assert all(g["state"] == "ok" or g["state"] == "na" for g in Q._gates_from_facts(done, d, ALL_ON))
    assert not any(g["state"] == "blocked" for g in Q._gates_from_facts(done, d, ALL_ON))


def test_mid_approval_extra_expenses_are_counted_only_with_the_option():
    """基礎缺口（見 FINANCE 文件 §5.1）：多層簽核簽到一半的額外支出狀態是『簽核中』，今天不擋結案；選項開啟才擋。"""
    Q = _q()
    facts = {"stages": (0, 0), "docs": [], "xe": (4, 0), "xe_draft": 0, "xe_mid": 2}
    off = {x["key"]: x for x in Q._gates_from_facts(facts, {})}
    assert off["extraExpense"]["state"] == "ok"                                                      # 今天的行為：不擋
    on = {x["key"]: x for x in Q._gates_from_facts(facts, {}, dict(ALL_OFF, count_unfinished_extra_expenses=True))}
    assert on["extraExpense"]["state"] == "blocked" and "2 筆簽核尚未完成" in on["extraExpense"]["reason"] and "結案條件加嚴" in on["extraExpense"]["reason"]
    both = {x["key"]: x for x in Q._gates_from_facts(dict(facts, xe=(6, 1), xe_draft=1), {}, dict(ALL_OFF, count_unfinished_extra_expenses=True))}
    r = both["extraExpense"]["reason"]
    assert "1 筆送審中" in r and "1 筆草稿未送審" in r and "2 筆簽核尚未完成" in r and both["extraExpense"]["value"] == "4 未完成"


def test_extra_expense_drafts_combine_with_pending_in_one_reason():
    Q = _q()
    g = {x["key"]: x for x in Q._gates_from_facts({"stages": (0, 0), "docs": [], "xe": (5, 2), "xe_draft": 3}, {}, dict(ALL_OFF, count_unfinished_extra_expenses=True))}
    assert g["extraExpense"]["state"] == "blocked" and "2 筆送審中" in g["extraExpense"]["reason"] and "3 筆草稿" in g["extraExpense"]["reason"]
    off = {x["key"]: x for x in Q._gates_from_facts({"stages": (0, 0), "docs": [], "xe": (5, 2), "xe_draft": 3}, {})}
    assert "草稿" not in off["extraExpense"]["reason"]


def test_there_is_no_option_that_switches_a_money_gate_off():
    assert F.CLOSE_GATE_OPTIONS == ("require_stages", "require_payment_items", "require_settlement", "count_unfinished_extra_expenses")
    from helpers import settings_registry as SR
    import helpers.settings_groups  # noqa: F401
    meta = SR._GROUPS["case_close_gates"]["fields"]
    assert set(meta) == {"enabled", *F.CLOSE_GATE_OPTIONS}
    for name, f in meta.items():
        assert f.default == 0 and f.loosen == "down", name                    # 預設關；降低（關閉）都是放寬 ⇒ 要第二位核准


def test_option_reading(monkeypatch):
    vals = {"enabled": 1, "require_stages": 1, "require_payment_items": 0, "require_settlement": 0, "count_unfinished_extra_expenses": 1}
    monkeypatch.setattr(F, "_strict", lambda conn, g, f: vals[f])
    assert F.close_gate_options(None) == {"require_stages": True, "require_payment_items": False, "require_settlement": False, "count_unfinished_extra_expenses": True}
    vals["enabled"] = 0
    assert F.close_gate_options(None) == ALL_OFF                               # 主開關關 ⇒ 全關（即使選項是 1）
    vals["enabled"] = 1
    vals["require_stages"] = 7                                                 # 格式不對 ⇒ 全開（往嚴）
    assert F.close_gate_options(None) == ALL_ON
    vals["require_stages"] = True                                              # 布林不是 0/1
    assert F.close_gate_options(None) == ALL_ON


def test_read_failure_is_the_strictest_not_the_loosest(monkeypatch):
    def boom(conn, g, f):
        raise RuntimeError("db locked")
    monkeypatch.setattr(F, "_strict", boom)
    assert F.close_gate_options(None) == ALL_ON


def test_close_gate_opts_is_none_when_everything_is_off(monkeypatch):
    Q = _q()
    monkeypatch.setattr(F, "close_gate_options", lambda conn: dict(ALL_OFF))
    assert Q._close_gate_opts(None) is None
    monkeypatch.setattr(F, "close_gate_options", lambda conn: dict(ALL_OFF, require_settlement=True))
    assert Q._close_gate_opts(None)["require_settlement"] is True


def test_facts_query_adds_the_draft_count_only_when_asked():
    Q = _q()
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""CREATE TABLE case_stages (quote_no TEXT, done INTEGER);
        CREATE TABLE case_extra_expenses (quote_no TEXT, status TEXT);
        INSERT INTO case_extra_expenses VALUES ('Q1','草稿'),('Q1','草稿'),('Q1','待審核'),('Q1','簽核中'),('Q1','已作廢'),('Q2','已核准');""")
    plain = Q._close_gate_facts(c, ["Q1", "Q2"])
    assert "xe_draft" not in plain["Q1"] and plain["Q1"]["xe"] == (4, 1) and plain["Q2"]["xe"] == (1, 0)
    withd = Q._close_gate_facts(c, ["Q1", "Q2"], xe_drafts=True)
    assert withd["Q1"]["xe_draft"] == 2 and withd["Q1"]["xe_mid"] == 1 and "xe_draft" not in withd["Q2"] and withd["Q1"]["xe"] == plain["Q1"]["xe"]


# ── 需要資料庫（寫好未跑）─────────────────────────────────────────────────────
def _set(group, values):
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish(group, values, reason="t62", user="t62", conn=c)
        c.commit()
    finally:
        c.close()


@pytest.fixture()
def sa(client, make_user):
    u, p = make_user(username="fin2_sa", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _case(no="Q-FIN2"):
    import json
    import db
    c = db.get_db()
    try:
        c.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (no, "已送出", "客戶", "專案", 1000, 952, json.dumps({"dealTag": "已成案"}, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))
        c.commit()
    finally:
        c.close()
    return no


def test_close_gates_endpoint_follows_the_options(client, sa):
    no = _case()
    base = client.get("/api/quotations/%s/close-gates" % no, headers=sa).json()
    assert base["canClose"] is True and all(g["state"] == "na" for g in base["gates"])
    _set("case_close_gates", {"enabled": 1, "require_settlement": 1})
    j = client.get("/api/quotations/%s/close-gates" % no, headers=sa).json()
    assert j["canClose"] is False and [g["key"] for g in j["gates"] if g["state"] == "blocked"] == ["settlement"]
    r = client.patch("/api/quotations/%s/deal-tag" % no, headers=sa, json={"deal_tag": "已結案"})
    assert r.status_code == 400 and "尚未建立成本精算" in r.text


def test_loosening_the_gate_option_goes_pending(client, sa):
    _set("case_close_gates", {"enabled": 1, "require_settlement": 1})
    r = client.put("/api/settings-center/groups/case_close_gates", headers=sa, json={"values": {"require_settlement": 0}, "reason": "測試"})
    assert r.status_code in (200, 202) and ("pending" in r.text or "待" in r.text)
