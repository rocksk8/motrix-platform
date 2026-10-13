# -*- coding: utf-8 -*-
"""脊柱 E-b 測試夾具（設計 docs/platform/plans/SPINE-FIXTURES-T57.md；引擎 core/spine.py）。

資料驅動：每個案例＝一份合成的 `features[]` 宣告（＋它需要的設定群組／信件類型登記），加上**預期結果**。
- `CASES`：今天的引擎就該給出該結果的案例（好／壞）；`FUTURE`：設計要求、引擎尚未落地的檢查（P0 目錄、E-c 範本…），
  測試以非嚴格 xfail 跑——引擎補上時自動轉為 XPASS，提醒把案例搬到 `CASES`。
- `run_case(case)` 在隔離的沙盒內登錄→驗證→回 `(通過?, 說明)`；`sandbox()` 保證結束後還原脊柱／設定／信件登記（不污染其他測試）。
- 預期的寫法：`("ok",)`｜`("parse", 片語)`（登錄當下就回的問題）｜`("failed", 片語)`（validate_all 後功能失敗，問題含片語）｜`("pending", 區段)`。
消費者：`test_spine_fixture_cases.py`（本檔的驅動）；其他模組要測自己的 `features[]` 時可 `from tests.platform._spine_fixtures import sandbox, feat, group_ok`。
"""
import contextlib

from core import registry, spine
from helpers import mail_types
from helpers import settings_groups  # noqa: F401  群組在載入時登錄；驗證器在 import 時登記
from helpers import settings_registry as R

OWNER = "zz_fx1"
OTHER = "zz_fx2"
SCOPE = {"documents": ["測試單據"], "roles": ["測試角色"], "amounts": "測試用，沒有金額影響", "reversible": True, "effective": "pending"}


@contextlib.contextmanager
def sandbox():
    """乾淨的脊柱登錄＋不碰資料庫的啟動回呼；離開時還原，並移除 `zz_fx*` 的設定群組與信件類型。"""
    snap, rsnap, post = spine.snapshot(), registry.snapshot(), list(spine._POST_VALIDATE)
    spine.reset()
    spine._POST_VALIDATE[:] = []
    try:
        yield spine
    finally:
        spine._POST_VALIDATE[:] = post
        spine.restore(snap)
        registry.restore(rsnap)
        for g in [g for g in R._GROUPS if g.startswith("zz_fx")]:
            R._GROUPS.pop(g, None)
        for k in [k for k in mail_types._REGISTRY if k.startswith("zz_fx")]:
            mail_types._REGISTRY.pop(k, None)
        R.invalidate()


def feat(code="zz_fx_f", **kw):
    d = {"code": code, "label": "測試功能"}
    d.update(kw)
    return d


def _field(key="n", **kw):
    return R.SettingDef(key, "int", 1, min=0, max=9, question="這項要設多少？", label="測試項目", help="測試用的設定項目。",
                        impact="影響測試用的畫面。", **kw)


def group_ok(name="zz_fx_g", owner=OWNER):
    R.register_group(name, "測試群組", [_field()], help="測試用的設定群組。", owner=owner)


def group_other_owner():
    group_ok(owner=OTHER)


def group_money(scope=True):
    kw = dict(risk="money", risk_text="金額可能不一致。", requires_pending=True)
    if scope:
        kw["impact_scope"] = SCOPE
    R.register_group("zz_fx_g", "測試群組", [_field("a", **kw)], help="測試用的設定群組。", owner=OWNER)


def group_money_without_scope():
    group_money(scope=False)


def group_str_choices():
    R.register_group("zz_fx_g", "測試群組", [R.SettingDef(
        "m", "str", "a", question="選哪一個？", label="選項", help="測試用的選項欄位。", impact="影響測試用的畫面。",
        choices=[("a", "甲方案", "選甲的影響。"), ("b", "乙方案", "選乙的影響。")])], help="測試用的設定群組。", owner=OWNER)


def mail_owned(owner=OWNER):
    mail_types._REGISTRY["zz_fx_mail"] = mail_types.MailType("zz_fx_mail", "測試信", "business", "none", "", "影響", "處理", owner=owner)


def mail_other_owner():
    mail_owned(OTHER)


SETUPS = {None: None, "group_ok": group_ok, "group_other_owner": group_other_owner, "group_money": group_money,
          "group_money_without_scope": group_money_without_scope, "group_str_choices": group_str_choices,
          "mail_owned": mail_owned, "mail_other_owner": mail_other_owner}

G = {"settings": {"group": "zz_fx_g"}}


def case(id, features, expect, setup=None, caps=None, owner=OWNER):
    return {"id": id, "features": features, "expect": expect, "setup": setup, "caps": caps, "owner": owner}


#: 今天的引擎就該通過／拒絕的案例（一案一條規則）
CASES = [
    # ── 好 ──
    case("good_minimal", [feat()], ("ok",)),
    case("good_group_owned", [feat(**G)], ("ok",), "group_ok"),
    case("good_money_group_with_impact_scope", [feat(**G)], ("ok",), "group_money"),
    case("good_mail_owned", [feat(mail=["zz_fx_mail"])], ("ok",), "mail_owned"),
    case("good_capability_declared", [feat(capabilities=["zz_fx.obj.view"])], ("ok",), caps=[{"key": "zz_fx.obj.view"}]),
    case("good_planned_with_train", [feat(status="planned", planned_train="MS2", label="專案毛利警示", notes="設計稿 X.md")], ("ok",)),
    case("good_hidden", [feat(status="hidden")], ("ok",)),
    case("good_surface_owned", [feat(catalog={"fields": [], "surfaces": ["module:zz_fx1.form"]})], ("pending", "catalog")),
    case("good_catalog_pending_until_validator_lands", [feat(catalog={"fields": ["f"]})], ("pending", "catalog")),
    # ── 壞：解析（登錄當下就回問題）──
    case("bad_missing_code", [{"label": "沒有代號"}], ("parse", "code")),
    case("bad_code_format", [{"code": "Bad-Code", "label": "x"}], ("parse", "code")),
    case("bad_unknown_key", [feat(typo=1)], ("parse", "不認得的鍵")),
    case("bad_empty_label", [feat(label="")], ("parse", "label")),
    case("bad_settings_shape", [feat(settings={"group": "ok", "x": 1})], ("parse", "settings")),
    case("bad_duplicate_mail", [feat(mail=["a", "a"])], ("parse", "重複")),
    case("bad_capability_format", [feat(capabilities=["no_dots"])], ("parse", "capabilities")),
    case("bad_catalog_keys", [feat(catalog={"nope": []})], ("parse", "catalog")),
    case("bad_status_value", [feat(status="paused")], ("parse", "status")),
    case("bad_date_key", [feat(eta="2026-12")], ("parse", "日期")),
    case("bad_planned_without_train", [feat(status="planned")], ("parse", "planned_train")),
    case("bad_planned_with_dateish_label", [feat(status="planned", planned_train="MS2", label="預計 2026-12 上線")], ("parse", "日期或時程")),
    case("bad_train_on_open_feature", [feat(status="open", planned_train="MS2")], ("parse", "planned_train")),
    case("bad_duplicate_code_in_one_manifest", [feat(), feat()], ("parse", "重複")),
    case("bad_surface_of_another_module", [feat(catalog={"fields": [], "surfaces": ["module:zz_fx2.form"]})], ("parse", "surface_not_owned")),
    case("bad_surface_core_prefix_for_module", [feat(catalog={"fields": [], "surfaces": ["core:form"]})], ("parse", "surface_not_owned")),
    case("bad_not_an_object", ["not-a-dict"], ("parse", "物件")),
    # ── 壞：驗證（validate_all 後功能失敗）──
    case("bad_group_not_registered", [feat(**G)], ("failed", "沒有登錄")),
    case("bad_group_owned_by_another_module", [feat(**G)], ("failed", "擁有者是 zz_fx2"), "group_other_owner"),
    case("bad_new_money_group_without_impact_scope", [feat(**G)], ("failed", "impact_scope"), "group_money_without_scope"),
    case("bad_choices_not_integer", [feat(**G)], ("failed", "整數代碼"), "group_str_choices"),
    case("bad_group_shared_by_two_features", [feat("zz_fx_a", **G), feat("zz_fx_b", **G)], ("failed", "同時歸屬"), "group_ok"),
    case("bad_mail_not_registered", [feat(mail=["zz_fx_mail"])], ("failed", "沒有登記")),
    case("bad_mail_registered_by_another_module", [feat(mail=["zz_fx_mail"])], ("failed", "登記者是 zz_fx2"), "mail_other_owner"),
    case("bad_capability_not_in_module_json", [feat(capabilities=["zz_fx.obj.view"])], ("failed", "不在本模組"), caps=[{"key": "zz_fx.other.view"}]),
]

#: 設計（SPINE-FIXTURES-T57 §3）要求、引擎尚未落地的檢查：非嚴格 xfail，落地後轉 XPASS ⇒ 搬進 CASES
FUTURE = [
    {**case("future_money_field_in_customer_channel", [feat(catalog={"fields": ["zz_fx_money"], "surfaces": ["module:zz_fx1.form"]})],
            ("failed", "isMoney")), "needs": "P0 欄位目錄驗證器（isMoney 項不得進客戶通道；目錄 ⇔ financial_mask 雙向）"},
    {**case("future_label_key_that_does_not_exist", [feat(labels=["zz_fx.no.such.label"])], ("failed", "label")),
     "needs": "labels 區段驗證器（標籤鍵必須存在於 label_map）"},
]


def run_case(c):
    """沙盒內登錄→驗證，回 `(是否符合預期, 說明)`。"""
    kind, arg = c["expect"][0], (c["expect"][1] if len(c["expect"]) > 1 else None)
    with sandbox():
        setup = SETUPS[c["setup"]]
        if setup:
            setup()
        manifest = {"features": c["features"]}
        if c["caps"] is not None:
            manifest["capabilities"] = c["caps"]
        reg_problems = spine.register_manifest(manifest, c["owner"])
        if kind == "parse":
            hit = any(arg in p for p in reg_problems)
            return hit, "登錄問題=%r（期待含 %r）" % (reg_problems, arg)
        if reg_problems:
            return False, "登錄當下就有問題（此案例預期可登錄）：%r" % (reg_problems,)
        rep = spine.validate_all()
        feats = {f["code"]: f for f in rep["features"]}
        if kind == "ok":
            bad = [f for f in feats.values() if f["state"] != "ok"]
            return (not bad and bool(feats)), "狀態=%r" % ({k: v["state"] for k, v in feats.items()},)
        if kind == "pending":
            f = next(iter(feats.values()), None)
            return bool(f and f["state"] == "pending_validator" and arg in f["pendingSections"]), "狀態=%r" % (f,)
        if kind == "failed":
            probs = [p for f in feats.values() if f["state"] == "failed" for p in f["problems"]]
            return any(arg in p for p in probs), "問題=%r（期待含 %r）" % (probs, arg)
    raise ValueError("不認得的預期：%r" % (c["expect"],))
