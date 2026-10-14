# -*- coding: utf-8 -*-
"""BP-5 P1：流程定義的文法、驗證器、靜態分析、寬嚴比較、內建 v1 與有效定義解析（純函式，不需要資料庫）。
- 內建 v1（完工單／出貨單）通過同一份驗證器；字面值對得上端點原始碼（狀態名稱、錯誤訊息、寫入動作）
- 驗證器：金額／會計類單據不接受公司版本；守門與回呼只能從目錄挑；代號、語意標籤、起始狀態；寫入類回呼的位置；關簽核必須有豁免
- 靜態分析：不可達、卡死、不經簽核就到 approved、簽核層轉換必須從待簽狀態出發
- 比較器：每個方向正反各一例；不可比＝放寬；突變正對照（把方向規則互換，分類必須翻面）
- 有效定義：旗標未登記／關 ⇒ 內建版；絕不丟例外；壞掉的已發布版 ⇒ 內建版
- 旗標 OFF 時 def_pipeline 的既有行為不變（比較函式表只多一項、ACTIVE_KINDS 只多一項）"""
import copy
from pathlib import Path

import pytest

from helpers import workflow_defaults as W
from helpers import workflow_defs as WD
from helpers import workflow_grammar as G

ROOT = Path(__file__).resolve().parents[1]


def base(doc="completion"):
    return W.builtin(doc)


def problems(body, doc="completion"):
    return G.validate_workflow(body, doc)


def tr(body, tid):
    return next(t for t in body["transitions"] if t["id"] == tid)


# ── 內建 v1 ───────────────────────────────────────────────────────────────────
def test_builtin_definitions_are_valid_and_only_for_plain_documents():
    assert W.doc_types() == ("completion", "shipping")
    for d in W.doc_types():
        assert problems(base(d), d) == [], d
    assert W.builtin("quotation") is None and W.builtin("nope") is None


def test_builtin_returns_a_deep_copy():
    a = base()
    a["states"][0]["label"] = "被改過"
    a["transitions"][0]["guards"].append("x")
    assert base()["states"][0]["label"] == "草稿" and "x" not in base()["transitions"][0]["guards"]


def test_builtin_literals_match_the_endpoint_source():
    """內建版是『今天行為』的登記：狀態名稱、守門訊息、寫入動作都能在端點原始碼找到（改端點而沒改基準＝這題紅）。"""
    comp = (ROOT / "modules/case/api/completion_notes.py").read_text(encoding="utf-8")
    ship = (ROOT / "modules/supply/api/shipping_notes.py").read_text(encoding="utf-8")
    labels = {s["id"]: s["label"] for s in base()["states"]}
    for src in (comp, ship):
        for lab in ("草稿", "待審核", "已核准"):
            assert "status='%s'" % lab in src, lab
        assert "簽核中" in src
        assert "僅草稿狀態可送出審核" in src and "僅草稿狀態可編輯" in src and "僅草稿狀態可刪除" in src       # submit／editLock
        assert "不可撤銷核准" in src and "已回簽" in src                                                      # not_customer_signed
        assert "require_reject_reason" in src                                                              # reject／revoke 原因必填
        assert "僅超級管理員可執行此操作" in src                                                           # 無簽核層的後備路徑
    assert labels == {"draft": "草稿", "pending": "待審核", "in_approval": "簽核中", "approved": "已核准"}
    assert "完工日期" in comp and "至少需要一項" in comp                                                      # completion submit 守門
    assert "以下序號已不在庫" in ship and "UPDATE stock_items" in ship and "status='in_stock'" in ship.replace(" ", "").replace("\n", "") or "in_stock" in ship
    assert "_generate_shipping_pdf" in ship and "push_event_for_shipping_note" in ship                    # gen_pdf／calendar_push
    assert "_ML.check_note" in ship                                                                         # material_link_check
    assert "stock_deduct" in tr(base("shipping"), "approve")["callbacks"] and "stock_return" in tr(base("shipping"), "revoke")["callbacks"]
    assert "stock_deduct" not in str(base("completion"))                                                    # 完工單不碰庫存（端點檔頭明寫）


# ── 驗證器 ────────────────────────────────────────────────────────────────────
def test_money_and_ledger_documents_accept_no_company_version():
    b = base()
    for doc in ("quotation", "payment_request", "invoice_voucher", "contractor_voucher", "bonus", "extra_expense"):
        assert problems(dict(b, docType=doc), doc), doc                                                     # money：第一期唯讀
    assert any("會計" in p["message"] for p in problems(dict(b, docType="voucher"), "voucher"))             # ledger
    assert problems(b, "never_registered")                                                                  # 未登記類型 ⇒ 當 money ⇒ 擋


@pytest.mark.parametrize("mut", [
    lambda b: b.update(docType="shipping"),
    lambda b: b["states"].append(dict(b["states"][0])),                                                     # 重複代號
    lambda b: b["states"][0].update(semantic="weird"),
    lambda b: b["states"][0].update(id="Bad-Id"),
    lambda b: b["states"][3].update(label=""),
    lambda b: b["states"][3].update(tone="purple"),
    lambda b: b["states"].pop(3),                                                                           # 沒有 approved 語意
    lambda b: tr(b, "approve").update(who="everyone"),
    lambda b: tr(b, "approve").update(reason="maybe"),
    lambda b: tr(b, "approve").update(log="verbose"),
    lambda b: tr(b, "approve").update(**{"from": []}),
    lambda b: tr(b, "approve").update(to="ghost"),
    lambda b: tr(b, "submit")["guards"].append("run_any_code"),                                             # 守門只能從目錄挑
    lambda b: tr(b, "approve")["callbacks"].append("send_webhook"),                                         # 回呼只能從目錄挑
    lambda b: tr(b, "submit")["guards"].extend(["has_items", "has_items"]),
    lambda b: b["transitions"].append(dict(tr(b, "submit"))),                                               # 轉換代號重複
    lambda b: b.update(returnLog="everything"),
    lambda b: b["editLock"].update(editableIn=["ghost"]),
    lambda b: b.update(approval={"required": "yes"}),
    lambda b: b.pop("approval"),
])
def test_structural_errors_are_reported(mut):
    b = base()
    mut(b)
    assert problems(b), "沒有報錯"


def test_validator_never_raises_on_garbage():
    for junk in (None, 1, [], "x", {}, {"docType": "completion"}, {"docType": "completion", "states": [1], "transitions": []},
                 {"docType": "completion", "states": [{"id": "a"}], "transitions": [1]}):
        assert isinstance(problems(junk), list) and problems(junk)


def test_write_callbacks_only_on_the_right_transitions():
    b = base("shipping")
    tr(b, "submit")["callbacks"].append("stock_deduct")                                                    # 扣庫存掛在 submit ⇒ 錯
    assert any("stock_deduct" in p["message"] for p in problems(b, "shipping"))
    b = base("shipping")
    tr(b, "approve")["callbacks"].append("stock_return")                                                   # 還庫存掛在進入 approved ⇒ 錯
    assert any("stock_return" in p["message"] for p in problems(b, "shipping"))
    b = base("shipping")
    tr(b, "reject")["callbacks"].append("stock_deduct")
    assert problems(b, "shipping")


def test_write_callbacks_cannot_be_removed_against_the_builtin_baseline():
    b = base("shipping")
    tr(b, "approve")["callbacks"].remove("stock_deduct")
    assert problems(b, "shipping") == []                                                                    # 純結構合法，但……
    assert G.removed_write_callbacks(base("shipping"), b) == [("approve", "stock_deduct")]                  # ……對照內建版被抓到
    out = WD._validator(b, "shipping")
    assert out and "stock_deduct" in out[0]["message"]
    b2 = base("shipping")
    tr(b2, "approve")["callbacks"].remove("gen_pdf")                                                        # 非寫入類可以拿掉
    assert WD._validator(b2, "shipping") == []
    assert WD._validator(base(), "quotation")                                                              # 沒有內建版的單據 ⇒ 不開放


# ── 靜態分析 ──────────────────────────────────────────────────────────────────
def test_unreachable_and_dead_end_states():
    b = base()
    b["states"].append({"id": "orphan", "label": "孤兒", "semantic": "closed"})
    assert any("無法到達" in p["message"] for p in problems(b))
    b = base()
    b["states"].append({"id": "stuck", "label": "卡住", "semantic": "pending"})
    tr(b, "advance")["to"] = "stuck"                                                                       # 進得去、出不來
    assert any("卡死" in p["message"] for p in problems(b))


def test_every_path_to_approved_must_pass_a_tier_unless_exempt():
    b = base()
    b["transitions"].append({"id": "shortcut", "from": ["draft"], "to": "approved", "who": "admin", "reason": "none", "log": "basic", "guards": [], "callbacks": []})
    msgs = [p["message"] for p in problems(b)]
    assert any("不經簽核" in m for m in msgs)
    b = base()
    tr(b, "approve")["who"] = "admin"                                                                      # 把簽核層換成角色
    assert any("簽核層" in p["message"] or "不經簽核" in p["message"] for p in problems(b))
    b = base()
    b["approval"] = {"required": False, "exemption": None}                                                  # 關簽核卻沒有豁免紀錄
    assert any("豁免" in p["message"] for p in problems(b))
    b["approval"] = {"required": False, "exemption": {"policy": 7}}
    b["transitions"].append({"id": "direct", "from": ["draft"], "to": "approved", "who": "admin", "reason": "none", "log": "basic", "guards": [], "callbacks": []})
    assert problems(b) == []                                                                               # 有記錄在案的豁免 ⇒ 可以不經簽核


def test_tier_transitions_must_start_from_a_pending_state():
    b = base()
    tr(b, "reject")["from"] = ["approved"]
    assert any("待簽狀態" in p["message"] for p in problems(b))


def test_self_loop_on_approved_is_not_an_approval_bypass():
    assert problems(base()) == [] and tr(base(), "signed_toggle")["to"] == "approved"


# ── 寬嚴比較 ──────────────────────────────────────────────────────────────────
def c(old, new):
    return G.compare(old, new)[0]


def test_identical_and_cosmetic_changes_are_neutral():
    b = base()
    assert c(b, base()) == "neutral"
    n = base()
    n["states"][0]["label"] = "起草"
    n["states"][1]["tone"] = "red"
    assert c(b, n) == "neutral"


def test_approval_switch_and_exemption():
    b, n = base(), base()
    n["approval"] = {"required": False, "exemption": {"policy": 1}}
    assert c(b, n) == "loosen" and c(n, b) == "tighten"
    m = copy.deepcopy(n)
    m["approval"]["exemption"] = {"policy": 2}
    assert c(n, m) == "loosen"


@pytest.mark.parametrize("field,weak,strong", [("who", "owner_or_admin", "admin"), ("who", "admin", "superadmin"),
                                                ("reason", "none", "optional"), ("reason", "optional", "required"),
                                                ("log", "none", "basic"), ("log", "basic", "full")])
def test_direction_per_field(field, weak, strong):
    a, b = base(), base()
    tr(a, "revoke")[field] = weak
    tr(b, "revoke")[field] = strong
    assert c(a, b) == "tighten" and c(b, a) == "loosen"


def test_tier_vs_role_is_not_comparable_so_it_loosens():
    a, b = base(), base()
    tr(b, "reject")["who"] = "admin"
    assert c(a, b) == "loosen" and c(b, a) == "loosen"


def test_guards_and_edit_lock_and_from_sets():
    a, b = base(), base()
    tr(b, "revoke")["guards"].remove("not_customer_signed")
    assert c(a, b) == "loosen" and c(b, a) == "tighten"
    a, b = base(), base()
    b["editLock"]["editableIn"] = ["draft", "pending"]
    assert c(a, b) == "loosen" and c(b, a) == "tighten"
    a, b = base(), base()
    tr(b, "reject")["from"] = ["pending"]
    assert c(a, b) == "tighten" and c(b, a) == "loosen"
    a, b = base(), base()
    b["returnLog"] = "full"
    assert c(a, b) == "tighten" and c(b, a) == "loosen"


def test_structure_changes_and_unknowns_are_loosen():
    a = base()
    b = base()
    b["transitions"].append({"id": "extra", "from": ["draft"], "to": "pending", "who": "admin", "reason": "none", "log": "basic", "guards": [], "callbacks": []})
    assert c(a, b) == "loosen" and c(b, a) == "loosen"                                                      # 新增或移除轉換都算
    b = base()
    tr(b, "approve")["to"] = "pending"
    assert c(a, b) == "loosen"
    b = base()
    b["states"][3]["semantic"] = "closed"
    assert c(a, b) == "loosen"
    b = base()
    tr(b, "submit")["guards"].append("unknown_guard")
    assert c(a, b) == "loosen"
    b = base()
    tr(b, "approve")["callbacks"].append("unknown_cb")
    assert c(a, b) == "loosen"
    assert c(a, None) == "loosen" and c({}, a) == "loosen" and c(a, {"transitions": "x"}) == "loosen"
    assert c(a, dict(base(), docType="shipping")) == "loosen"
    b = base()
    b["editLock"] = "x"
    assert c(a, b) == "loosen"


def test_write_callback_change_is_loosen_and_notify_change_is_neutral():
    a = base("shipping")
    b = base("shipping")
    tr(b, "approve")["callbacks"].remove("stock_deduct")
    assert c(a, b) == "loosen"
    b = base("shipping")
    tr(b, "approve")["callbacks"].remove("gen_pdf")
    assert c(a, b) == "neutral"


def test_reasons_name_the_transition():
    a, b = base(), base()
    tr(b, "revoke")["reason"] = "none"
    cls, why = G.compare(a, b)
    assert cls == "loosen" and any("revoke" in x for x in why)


def test_mutation_control_swapping_the_direction_flips_the_answer(monkeypatch):
    a, b = base(), base()
    tr(a, "revoke")["reason"] = "none"
    tr(b, "revoke")["reason"] = "required"
    assert c(a, b) == "tighten"
    monkeypatch.setattr(G, "_REASON_RANK", {"none": 2, "optional": 1, "required": 0})
    assert c(a, b) == "loosen"                                                                              # 方向寫反 ⇒ 結果翻面 ⇒ 上面的每個方向題會紅


# ── 有效定義與旗標 ────────────────────────────────────────────────────────────
def test_flag_is_off_and_group_not_registered_in_p1():
    from helpers import settings_registry as SR
    assert WD.flag_on() is False and WD.enabled() is False
    assert "builder_workflow" not in SR._GROUPS                       # 第一期不登記設定群組：設定中心與基準檔與今天相同


def test_effective_is_the_builtin_when_off_and_never_raises(monkeypatch):
    assert WD.effective("completion") == base() and WD.effective("shipping") == base("shipping")
    assert WD.effective("quotation") is None
    monkeypatch.setattr(WD, "flag_on", lambda conn=None: True)
    monkeypatch.setattr("routers.def_pipeline.enabled", lambda conn=None: True)
    mine = base()
    mine["states"][0]["label"] = "起草"
    monkeypatch.setattr(WD.D, "get", lambda conn, kind, key, scope: {"body": mine})
    assert WD.effective("completion", conn=object())["states"][0]["label"] == "起草"                        # 已發布公司版生效
    bad = base()
    bad["transitions"].append({"id": "shortcut", "from": ["draft"], "to": "approved", "who": "admin", "reason": "none", "log": "basic", "guards": [], "callbacks": []})
    monkeypatch.setattr(WD.D, "get", lambda conn, kind, key, scope: {"body": bad})
    assert WD.effective("completion", conn=object()) == base()                                              # 壞掉的已發布版 ⇒ 內建版
    monkeypatch.setattr(WD.D, "get", lambda conn, kind, key, scope: (_ for _ in ()).throw(RuntimeError("db down")))
    assert WD.effective("completion", conn=object()) == base()                                              # 讀不到 ⇒ 內建版
    monkeypatch.setattr("routers.def_pipeline.enabled", lambda conn=None: False)
    assert WD.enabled() is False                                                                            # 沒開建構器治理 ⇒ 不生效


def test_ensure_registered_registers_once_and_import_registers_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(WD.D, "kinds", lambda: [])
    monkeypatch.setattr(WD.D, "register_kind", lambda *a, **k: calls.append(("kind", a, k)))
    monkeypatch.setattr(WD._spine, "has_kind_gate", lambda k: False)
    monkeypatch.setattr(WD._spine, "register_kind_gate", lambda k, fn: calls.append(("gate", k, fn)))
    WD.ensure_registered()
    assert [x[0] for x in calls] == ["kind", "gate"] and calls[0][1][0] == "workflow"
    assert calls[1][2]("completion") == "hidden"                                                                        # 旗標關 ⇒ 通用定義路由 404


def test_default_for_unknown_key_is_empty_and_known_key_is_the_builtin():
    assert WD._default("completion") == base() and WD._default("quotation") == {}


# ── def_pipeline 接線 ─────────────────────────────────────────────────────────
def test_pipeline_knows_the_workflow_kind_and_existing_entries_are_unchanged():
    from routers import def_pipeline as P
    assert P.ACTIVE_KINDS[:2] == ("custom_fields", "layout") and "workflow" in P.ACTIVE_KINDS
    assert set(P.COMPARATORS) >= {"custom_fields", "layout", "workflow"}
    assert P.classify("workflow", base(), base()) == ("neutral", [])
    b = base()
    tr(b, "revoke")["reason"] = "none"
    assert P.classify("workflow", base(), b)[0] == "loosen"
    assert P.classify("workflow", base(), "garbage")[0] == "loosen"
