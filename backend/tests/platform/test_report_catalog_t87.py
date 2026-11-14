# -*- coding: utf-8 -*-
"""T87 B2-S0b：自訂報表來源登錄表（registry）的守門題。

① 驗證器：登記資料的每一種筆誤都被擋下（不登記、不丟例外）；運算式只認擁有模組登錄的同一個常數（`is`）。
② 真實登記（case／crm）：與清單端點引用同一批常數、列規則已登錄、金額欄都走欄位目錄、沒有內部欄位。
③ 欄位可見：逐角色與既有規則相等；`derivedFrom` 遞迴；D7 只放寬報價單層級、不碰商機預估金額。
④ 來源可用：能力不取代模組存取（模組鍵、擁有模組已載入、有 execute 缺一不可）。
"""
import pytest

from core import internal_cols as IC
from helpers import auth
from helpers import field_catalog as FC
from helpers import report_catalog as RC
from helpers import row_access
import modules.case.api.quotations as Q   # noqa: F401  登記 quotation／case
import modules.crm.api as CRM             # noqa: F401  登記 dev_case

_DEAL = "COALESCE(NULLIF(deal_tag,''), json_extract(data_json,'$.dealTag'), '')"


def _fresh(s):
    """內容相同、但不是同一個物件的字串（驗證 `is` 比對真的不是 `==`）。"""
    return "".join(list(s))


def _spec(**over):
    expr = _DEAL
    spec = {
        "label": "測試來源", "table": "t_things", "modules": ["m_x"], "rowAccess": {"kind": "case", "scope": "read"},
        "exprs": (expr,),
        "fields": [
            {"id": "name", "label": "名稱", "type": "text", "kind": "column", "column": "name", "select": True, "filter": True, "group": True,
             "aggregate": (), "sort": True},
            {"id": "tag", "label": "標記", "type": "enum", "kind": "expr", "expr": expr, "reads": ("deal_tag", "data_json"), "select": True,
             "filter": True, "group": True, "aggregate": (), "sort": False, "enum": (("a", "甲"),)},
            {"id": "amt", "label": "金額", "type": "money", "kind": "column", "column": "total", "catalogId": "quotation.total", "select": True,
             "filter": True, "group": False, "aggregate": ("sum", "count"), "sort": True},
        ],
        "defaults": {"columns": ["name", "tag"], "sort": {"field": "name", "dir": "asc"}},
    }
    spec.update(over)
    return spec


def _field(spec, fid):
    return next(f for f in spec["fields"] if f["id"] == fid)


@pytest.fixture(autouse=True)
def _isolate():
    snap = RC.snapshot()
    yield
    RC.restore(snap)


# ── ① 驗證器 ───────────────────────────────────────────────────────────────

def test_a_well_formed_source_registers_and_is_returned_as_a_copy():
    assert RC.register_source("t_src", "owner_x", _spec()) == []
    got = RC.get_source("t_src")
    assert got["label"] == "測試來源"
    got["fields"][0]["label"] = "被改了"
    assert RC.get_source("t_src")["fields"][0]["label"] == "名稱"             # 回傳複本，改它不影響登錄表


def _bad(mut, needle):
    s = _spec()
    mut(s)
    probs = RC.source_problems("t_src", s)
    assert any(needle in p for p in probs), probs
    assert RC.register_source("t_src", "owner_x", s) == probs                   # 有問題＝不登記、不丟例外
    assert RC.get_source("t_src") is None


@pytest.mark.parametrize("name, mut, needle", [
    ("expr_equal_but_not_same_object", lambda s: _field(s, "tag").update(expr=_fresh(_DEAL)), "同一個常數"),
    ("expr_arbitrary_text", lambda s: _field(s, "tag").update(expr="1; DROP TABLE users"), "同一個常數"),
    ("expr_without_reads", lambda s: _field(s, "tag").pop("reads"), "reads"),
    ("sort_expr_not_registered", lambda s: _field(s, "name").update(sortExpr="name DESC"), "sortExpr"),
    ("money_without_catalog_id", lambda s: _field(s, "amt").pop("catalogId"), "catalogId"),
    ("unknown_catalog_id", lambda s: _field(s, "amt").update(catalogId="nope.nothing"), "不在欄位目錄"),
    ("internal_column", lambda s: _field(s, "name").update(column="owner_unit_id"), "內部欄位"),
    ("data_json_column", lambda s: _field(s, "name").update(column="data_json"), "data_json"),
    ("bad_identifier_column", lambda s: _field(s, "name").update(column="name; --"), "column 不合法"),
    ("bad_table", lambda s: s.update(table="t x"), "table"),
    ("group_on_money", lambda s: _field(s, "amt").update(group=True), "不可分組"),
    ("sum_on_text", lambda s: _field(s, "name").update(aggregate=("sum",)), "aggregate"),
    ("duplicate_field_id", lambda s: _field(s, "tag").update(id="name"), "重複"),
    ("enum_without_options", lambda s: _field(s, "tag").pop("enum"), "enum"),
    ("no_modules", lambda s: s.update(modules=[]), "modules"),
    ("no_row_access", lambda s: s.pop("rowAccess"), "rowAccess"),
    ("bad_row_scope", lambda s: s.update(rowAccess={"kind": "case", "scope": "all"}), "rowAccess"),
    ("default_column_not_selectable", lambda s: _field(s, "name").update(select=False), "defaults.columns"),
    ("default_sort_on_unsortable", lambda s: s["defaults"].update(sort={"field": "tag", "dir": "asc"}), "defaults.sort"),
    ("is_me_without_mine", lambda s: _field(s, "name").update(isMe=True), "mine"),
    ("mine_param_count", lambda s: s.update(mine={"sql": _DEAL, "params": ("id",)}), "mine"),
    ("mine_sql_not_registered", lambda s: s.update(mine={"sql": "1=1", "params": ()}), "mine"),
    ("mine_without_reads", lambda s: s.update(mine={"sql": _DEAL, "params": ()}), "mine"),
    ("execute_not_callable", lambda s: s.update(execute="boom"), "execute"),
    ("default_filter_on_unfilterable", lambda s: s.update(defaultFilters=[{"field": "nope", "op": "eq", "value": 1}]), "defaultFilters"),
    ("date_group_without_bucket", lambda s: s["fields"].append(
        {"id": "d", "label": "日", "type": "date", "kind": "column", "column": "d", "select": True, "filter": True, "group": True,
         "aggregate": (), "sort": True}), "bucket"),
])
def test_validator_rejects(name, mut, needle):
    _bad(mut, needle)


def test_bad_source_id_and_non_dict_spec():
    assert RC.source_problems("Bad-Id", _spec())
    assert RC.source_problems("ok_id", "not a dict")


def test_same_id_from_another_owner_is_refused_but_same_owner_may_reregister():
    assert RC.register_source("t_src", "a", _spec()) == []
    assert RC.register_source("t_src", "a", _spec(label="改名")) == []
    with pytest.raises(ValueError):
        RC.register_source("t_src", "b", _spec())


def test_alias_extends_base_and_unknown_base_is_refused():
    assert RC.register_source("t_src", "a", _spec()) == []
    assert RC.register_source("t_alias", "a", {"extends": "t_src", "label": "別名",
                                                "defaultFilters": [{"field": "tag", "op": "in", "value": ["a"]}]}) == []
    al = RC.get_source("t_alias")
    assert al["label"] == "別名" and al["table"] == "t_things" and [f["id"] for f in al["fields"]] == ["name", "tag", "amt"]
    assert al["defaultFilters"][0]["field"] == "tag"
    assert RC.register_source("t_orphan", "a", {"extends": "no_such", "label": "孤兒"})


# ── ② 真實登記 ─────────────────────────────────────────────────────────────

REAL = ("quotation", "case", "dev_case")


def test_real_sources_are_registered_clean():
    snap = RC.snapshot()
    for sid in REAL:
        assert sid in snap, sid
        assert RC.source_problems(sid, snap[sid]["spec"]) == [], sid
    assert snap["quotation"]["owner"] == snap["case"]["owner"] == "case" and snap["dev_case"]["owner"] == "crm"


def test_case_sources_use_the_very_same_constants_as_the_list_endpoint():
    from modules.case import quotations as MQ
    q = RC.get_source("quotation")
    by = {f["id"]: f for f in q["fields"]}
    assert by["deal_tag"]["expr"] is MQ.SQL_DEAL_TAG
    assert by["settle_status"]["expr"] is MQ.SQL_SETTLE_STATUS
    assert by["quote_date"]["expr"] is MQ.SQL_QUOTE_DATE and by["quote_date"]["sortExpr"] is MQ.SQL_QUOTE_DATE
    assert q["mine"]["sql"] is Q._CASE_MINE_SQL                              # 「我」＝清單的「我負責的」，不是名稱相等
    assert q["mine"]["params"] == ("id", "display_name", "id", "username", "username", "username")
    assert Q.SQL_QUOTE_DATE is MQ.SQL_QUOTE_DATE                             # 清單排序也引用同一個常數


def test_case_alias_reuses_quotation_fields_with_the_case_page_population():
    c, q = RC.get_source("case"), RC.get_source("quotation")
    assert c["fields"] == q["fields"] and c["table"] == "quotations" and c["label"] == "案件"
    assert c["defaultFilters"] == [{"field": "deal_tag", "op": "in", "value": ["已成案", "已結案"]}]
    assert "defaultFilters" not in q                                        # 報價單來源預設不加條件（與清單預設同列，含估價單）


def test_row_rules_and_soft_delete_match_the_list_endpoints():
    assert row_access.rule_for("case") is not None and row_access.rule_for("dev_case") is not None
    assert RC.get_source("quotation")["rowAccess"] == {"kind": "case", "scope": "read"}
    assert RC.get_source("dev_case")["rowAccess"] == {"kind": "dev_case", "scope": "owner"}
    assert RC.get_source("dev_case")["softDelete"] == "is_deleted"
    assert RC.get_source("quotation").get("softDelete") is None             # quotations 表沒有軟刪除欄，清單也沒有此條件


def test_doc_type_is_a_registered_filterable_groupable_enum_from_helpers_doc_type():
    from helpers import doc_type as DT
    f = RC.field_of("quotation", "doc_type")
    assert f["type"] == "enum" and f["filter"] and f["group"]
    assert dict(f["enum"](None)) == dict(DT.LABELS)
    assert "doc_type" in RC.get_source("quotation")["defaults"]["columns"]


def test_dev_case_status_options_come_from_crm_and_amount_is_in_the_field_catalog():
    f = RC.field_of("dev_case", "status")
    assert [v for v, _ in f["enum"]] == list(CRM._STATUS_OPTIONS)
    a = RC.field_of("dev_case", "expected_amount")
    assert a["catalogId"] == "dev_case.expected_amount" and FC.by_id(a["catalogId"])["ceiling"] == "financial_view"


def test_every_money_field_goes_through_the_catalog_and_no_internal_or_protected_field_is_whitelisted():
    for sid in REAL:
        for f in RC.get_source(sid)["fields"]:
            if f["type"] in ("money", "percent"):
                e = FC.by_id(f["catalogId"])
                assert e is not None and e["moneyClass"] != "none", (sid, f["id"])
            if f.get("catalogId"):
                assert FC.by_id(f["catalogId"])["moneyClass"] != "protected"
            assert not IC.is_internal(f.get("column") or "") and not IC.is_internal(f["id"])
            for r in f.get("reads") or ():
                assert not IC.is_internal(r)
            assert f.get("column") != "data_json"


def test_no_dangerous_field_names_are_whitelisted():
    names = {f["id"] for sid in REAL for f in RC.get_source(sid)["fields"]}
    assert not names & {"data_json", "owner_unit_id", "unit_id", "legal_entity_id", "phone", "email", "address", "note", "notes", "password"}


def test_money_and_percent_fields_cannot_be_grouped_and_text_only_counts():
    for sid in REAL:
        for f in RC.get_source(sid)["fields"]:
            if f["type"] in ("money", "percent"):
                assert not f["group"], (sid, f["id"])
            if f["type"] in ("text", "enum"):
                assert set(f["aggregate"]) <= {"count"}, (sid, f["id"])


# ── ③ 欄位可見 ─────────────────────────────────────────────────────────────

ROLES = ("superadmin", "admin", "sales", "engineer", "viewer", "finance")


@pytest.fixture
def finance_env(monkeypatch):
    state = {"mode": "off", "grants": (set(), set())}
    monkeypatch.setattr(auth, "_finance_mode", lambda: state["mode"])
    monkeypatch.setattr(auth, "_finance_grants", lambda uid, cache: (set(state["grants"][0]), set(state["grants"][1])))
    monkeypatch.setattr(auth, "_finance_shadow_report", lambda *a, **k: None)
    return state


def _u(role, modules="[]", uid=7):
    return {"id": uid, "username": "u%d" % uid, "display_name": "U%d" % uid, "role": role, "modules": modules}


def _vis(sid, fid, user, wide=False):
    return RC.field_visible(RC.field_of(sid, fid), user, wide)


@pytest.mark.parametrize("fid", ["total", "pretax", "direct_margin_pct", "net_margin_pct"])
def test_quote_money_fields_follow_the_quote_ceiling_per_role(finance_env, fid):
    from helpers import financial_mask as FM
    for role in ROLES:
        u = _u(role)
        assert _vis("quotation", fid, u) is bool(FM.quote_money_visible(u)), role


def test_non_money_fields_are_visible_to_everyone(finance_env):
    for role in ROLES:
        for fid in ("quote_no", "customer_name", "status", "doc_type", "quote_date", "deal_tag"):
            assert _vis("quotation", fid, _u(role), False) is True


def test_expected_amount_equals_can_see_financial_both_ways(finance_env):
    for mode in ("off", "shadow", "on"):
        finance_env["mode"] = mode
        for role in ROLES:
            for mods in ("[]", '["cashier"]', '["dev_crm"]'):
                u = _u(role, mods)
                want = bool(auth.can_see_financial(u))
                for wide in (False, True):
                    assert _vis("dev_case", "expected_amount", u, wide) is want, (mode, role, mods, wide)


def test_margin_is_hidden_when_its_cost_source_is_hidden(monkeypatch):
    from helpers import field_policy as FP
    monkeypatch.setattr(FP, "tier_allowed", lambda c, u: c != "quote_money")
    assert _vis("quotation", "direct_margin_pct", _u("admin")) is False
    # 目錄項自己的天花板可見、但 derivedFrom 的成本不可見 ⇒ 仍不可見（遞迴）
    real_by_id = FC.by_id
    monkeypatch.setattr(FC, "by_id", lambda fid: {"ceiling": "financial_view", "derivedFrom": ("quote_item.cost",)} if fid == "quotation.total"
                        else real_by_id(fid))
    assert _vis("quotation", "total", _u("superadmin")) is False
    monkeypatch.setattr(FP, "tier_allowed", lambda c, u: True)
    assert _vis("quotation", "total", _u("superadmin")) is True                # 正對照：成本也可見 ⇒ 可見


def test_d7_wide_only_adds_the_money_visible_short_circuit_for_quote_level_fields(finance_env):
    """被授予 cashier 的工程師：money_visible 為真、quote_money_visible 為假。嚴格＝看不到；放寬＝報價單金額欄看得到，但商機預估金額仍看不到。"""
    finance_env["mode"] = "on"
    finance_env["grants"] = ({"cashier"}, set())
    u = _u("engineer", uid=2)
    for fid in ("total", "pretax", "direct_margin_pct", "net_margin_pct"):
        assert _vis("quotation", fid, u, False) is False
        assert _vis("quotation", fid, u, True) is True, fid
    assert _vis("dev_case", "expected_amount", u, True) is False


def test_d7_wide_never_shows_more_to_people_who_have_no_money_access(finance_env):
    for role in ("engineer", "viewer"):
        u = _u(role)
        for fid in ("total", "pretax", "direct_margin_pct", "net_margin_pct"):
            assert _vis("quotation", fid, u, True) is False, (role, fid)


def test_field_visible_follows_the_current_setting_when_wide_is_not_given(finance_env, monkeypatch):
    from helpers import report_policy as RP
    finance_env["mode"] = "on"
    finance_env["grants"] = ({"cashier"}, set())
    u = _u("engineer", uid=2)
    f = RC.field_of("quotation", "total")
    monkeypatch.setattr(RP, "quote_money_wide", lambda conn=None: False)
    assert RC.field_visible(f, u) is False
    monkeypatch.setattr(RP, "quote_money_wide", lambda conn=None: True)
    assert RC.field_visible(f, u) is True
    assert RC.visible_fields("quotation", u)["total"] is True


def test_visibility_fails_closed_on_errors(monkeypatch):
    from helpers import field_policy as FP
    monkeypatch.setattr(FP, "tier_allowed", lambda c, u: (_ for _ in ()).throw(RuntimeError("boom")))
    assert RC.field_visible(RC.field_of("quotation", "total"), _u("superadmin"), False) is False
    assert RC.field_visible({"id": "x", "catalogId": "no.such"}, _u("superadmin"), False) is False
    assert RC.field_visible({"id": "x", "catalogId": None}, _u("viewer"), False) is True
    assert RC.visible_fields("no_such_source", _u("superadmin")) == {}


# ── ④ 來源可用：能力不取代模組存取 ─────────────────────────────────────────

@pytest.fixture
def loaded_owner(monkeypatch):
    from core import registry
    state = {"loaded": {"owner_x"}}
    monkeypatch.setattr(registry, "is_loaded", lambda k: k in state["loaded"])
    return state


def _reg(**over):
    spec = _spec(execute=lambda *a, **k: None, **over)
    assert RC.register_source("t_src", "owner_x", spec) == []


def test_source_needs_execute_loaded_owner_and_a_module_key(loaded_owner):
    assert RC.register_source("t_src", "owner_x", _spec()) == []
    assert RC.source_available("t_src", _u("superadmin")) is False           # 沒有 execute ⇒ 不列出
    _reg()
    assert RC.source_available("t_src", _u("superadmin")) is True
    assert RC.source_available("t_src", _u("admin")) is False                # admin 不直通模組
    assert RC.source_available("t_src", _u("sales", '["m_x"]')) is True
    assert RC.source_available("t_src", _u("sales", '["other"]')) is False   # 持有別的模組、或只有報表能力 ⇒ 不可用
    loaded_owner["loaded"].clear()
    assert RC.source_available("t_src", _u("superadmin")) is False           # 擁有模組沒載入 ⇒ 連超管都不列出（fail-closed）


def test_admin_pass_is_only_for_sources_that_declare_it(loaded_owner):
    _reg(adminPass=True)
    assert RC.source_available("t_src", _u("admin")) is True
    assert RC.source_available("t_src", _u("sales")) is False


def test_unknown_source_and_missing_user_are_unavailable(loaded_owner):
    _reg()
    assert RC.source_available("no_such", _u("superadmin")) is False
    assert RC.source_available("t_src", None) is False
    assert RC.source_available("t_src", {}) is False


def test_sources_for_lists_only_available_sources_in_registration_order(loaded_owner):
    _reg()
    assert RC.register_source("t_two", "owner_x", _spec(execute=lambda *a, **k: None, modules=["m_y"])) == []
    assert [s for s in RC.sources_for(_u("sales", '["m_x"]')) if s.startswith("t_")] == ["t_src"]
    assert [s for s in RC.sources_for(_u("superadmin")) if s.startswith("t_")] == ["t_src", "t_two"]
    assert not any(s.startswith("t_") for s in RC.sources_for(_u("viewer")))


def test_real_sources_have_owner_execute_and_are_listed_for_the_right_people(monkeypatch):
    from core import registry
    monkeypatch.setattr(registry, "is_loaded", lambda k: True)
    for sid in REAL:
        assert callable(RC.get_source(sid)["execute"]), sid                       # 擁有模組登記了執行回呼
        assert RC.source_available(sid, _u("superadmin")) is True
    assert RC.source_available("quotation", _u("sales", '["quotation"]')) is True
    assert RC.source_available("case", _u("sales", '["case_manage"]')) is True
    assert RC.source_available("quotation", _u("sales", '[]')) is False            # 沒有來源的模組鍵 ⇒ 不列出（能力不取代模組存取）
    assert RC.source_available("dev_case", _u("admin")) is True                    # 與 _require_dev 一致：admin 直通
    assert RC.source_available("dev_case", _u("sales", '["dev_crm"]')) is True
    assert RC.source_available("dev_case", _u("sales", '["quotation","case_manage"]')) is False
