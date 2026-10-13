# -*- coding: utf-8 -*-
"""脊柱 E-b：`core/spine.py`（features[] 解析與驗證、功能狀態 open／planned／hidden、group_status／feature_enabled）＋
設定登錄表的引擎層攔截（publish／plan／預設組／待生效的讀取時覆蓋與取消）。"""
import json
import sys
from datetime import datetime, timedelta

import pytest

from core import loader, registry, spine
from db import get_db
from helpers import config_ledger as L
from helpers import mail_types
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as R

SCOPE = {"documents": ["測試單據"], "roles": ["測試角色"], "amounts": "測試用，沒有金額影響", "reversible": True, "effective": "pending"}


@pytest.fixture
def sp(monkeypatch):
    """乾淨的脊柱登錄＋關掉啟動回呼（避免單元測試碰資料庫）；結束時還原。"""
    snap, rsnap = spine.snapshot(), registry.snapshot()
    spine.reset()
    monkeypatch.setattr(spine, "_POST_VALIDATE", [])
    yield spine
    spine.restore(snap)
    registry.restore(rsnap)
    for g in [g for g, v in R._GROUPS.items() if g.startswith("zz_eb")]:
        R._GROUPS.pop(g, None)
    for k in [k for k in mail_types._REGISTRY if k.startswith("zz_eb")]:
        mail_types._REGISTRY.pop(k, None)
    R.invalidate()


def _feat(code="zz_eb_f", **kw):
    d = {"code": code, "label": "測試功能"}
    d.update(kw)
    return d


def _reg(feats, owner="zz_eb1", caps=None):
    m = {"features": feats}
    if caps is not None:
        m["capabilities"] = caps
    return spine.register_manifest(m, owner)


def _field(key="n", **kw):
    return R.SettingDef(key, "int", 1, min=0, max=9, question="這項要設多少？", label="測試項目", help="測試用的設定項目。", impact="影響測試用的畫面。", **kw)


def _group(name, owner="zz_eb1", *fields):
    R.register_group(name, "測試群組", list(fields) or [_field()], help="測試用的設定群組。", owner=owner)


# --- 解析 ---------------------------------------------------------------------------------------

def test_valid_feature_is_parsed_with_defaults(sp):
    assert _reg([_feat(settings={"group": "zz_eb_g"}, mail=["zz_eb_mail"], capabilities=["zz_eb.x.view"], labels=["a.b"],
                       catalog={"fields": ["f1"], "surfaces": ["module:zz_eb1.y"]}, notes="CRM-X.md")]) == []
    f = spine.report()["features"][0]
    assert (f["code"], f["owner"], f["status"], f["plannedTrain"]) == ("zz_eb_f", "zz_eb1", "open", None)


@pytest.mark.parametrize("bad,needle", [
    ({"label": "沒有代號"}, "code"),
    ({"code": "Bad-Code", "label": "x"}, "code"),
    (_feat(typo=1), "不認得的鍵"),
    (_feat(label=""), "label"),
    (_feat(settings={"group": "Bad"}), "settings"),
    (_feat(settings={"group": "ok", "x": 1}), "settings"),
    (_feat(mail="not-a-list"), "mail"),
    (_feat(mail=["a", "a"]), "重複"),
    (_feat(capabilities=["no_dots"]), "capabilities"),
    (_feat(catalog={"nope": []}), "catalog"),
    (_feat(status="paused"), "status"),
    (_feat(eta="2026-12"), "日期"),
    (_feat(date="x"), "日期"),
    ("not-a-dict", "物件"),
])
def test_bad_declarations_are_named(sp, bad, needle):
    probs = _reg([bad])
    assert probs and any(needle in p for p in probs), probs


def test_features_must_be_a_list_or_the_module_is_refused(sp):
    with pytest.raises(ValueError):
        spine.register_manifest({"features": {"code": "x"}}, "zz_eb1")
    assert spine.parse_features({}, "zz_eb1") == ([], [])


@pytest.mark.parametrize("train,ok", [("MS1", True), ("MS2", True), ("MS99", True), ("MS0", False), ("MS100", False), ("ms2", False), ("MS 2", False), ("", False), (None, False)])
def test_planned_train_format(sp, train, ok):
    kw = {"status": "planned"}
    if train is not None:
        kw["planned_train"] = train
    probs = _reg([_feat(**kw)])
    assert (probs == []) is ok, probs


def test_planned_train_only_on_planned_and_dates_are_refused(sp):
    assert _reg([_feat(status="open", planned_train="MS2")])
    spine.reset()
    assert _reg([_feat(status="hidden", planned_train="MS2")])
    spine.reset()
    for txt in ("預計 2026-12 上線", "12/25 完成", "兩週", "30天內", "Q4 提供", "下週", "本月底", "年底前"):
        spine.reset()
        probs = _reg([_feat(status="planned", planned_train="MS2", label=txt)])
        assert any("日期或時程" in p for p in probs), (txt, probs)
        spine.reset()
        assert any("日期或時程" in p for p in _reg([_feat(status="planned", planned_train="MS2", notes=txt)])), txt
    spine.reset()
    assert _reg([_feat(status="planned", planned_train="MS2", label="專案毛利警示", notes="設計稿 CRM-DIRECTIVE.md")]) == []   # 一般文字不誤判
    spine.reset()
    assert _reg([_feat(status="open", label="30天內提醒")]) == []                                                   # 只限 planned 功能


def test_duplicate_codes_within_and_across_owners(sp):
    probs = _reg([_feat(), _feat()])
    assert any("重複" in p for p in probs)
    probs = _reg([_feat()], owner="zz_eb2")
    assert any("已被 zz_eb1 使用" in p for p in probs)
    assert spine.report()["orphans"]["zz_eb2"]
    assert [f["owner"] for f in spine.report()["features"]] == ["zz_eb1"]


def test_same_code_from_two_owners_fails_both_regardless_of_load_order(sp):
    for first, second in (("zz_eb1", "zz_eb2"), ("zz_eb2", "zz_eb1")):
        spine.reset()
        _reg([_feat()], owner=first)
        _reg([_feat()], owner=second)
        r = spine.validate_all()
        assert len(r["features"]) == 1 and r["features"][0]["state"] == "failed"
        assert "同時被多個模組宣告：zz_eb1、zz_eb2" in r["features"][0]["problems"][0]
        assert r["orphans"]                                                                  # 沒被收下的那一方也有問題記錄
        assert spine.feature_enabled("zz_eb_f") is False
    spine.drop_owner("zz_eb2")                                                               # 其中一方卸載 ⇒ 另一方恢復
    spine.drop_owner("zz_eb1")
    _reg([_feat()], owner="zz_eb1")
    assert spine.validate_all()["features"][0]["state"] == "ok" and spine.feature_enabled("zz_eb_f") is True


def test_due_pending_keeps_its_docstring_and_guard():
    assert R._due_pending.__doc__ and "非 open" in R._due_pending.__doc__


def test_group_of_a_rejected_duplicate_declaration_is_hidden_in_both_load_orders(sp):
    """同一功能代號被兩個模組宣告：贏家被存、輸家的宣告被丟掉——輸家指名的群組不能因此變成可寫的 open。兩種載入順序結果相同。"""
    _group("zz_eb_g1", "zz_eb1")
    _group("zz_eb_g2", "zz_eb2")
    a, b = ("zz_eb1", "zz_eb_g1"), ("zz_eb2", "zz_eb_g2")
    for first, second in ((a, b), (b, a)):
        spine.reset()
        _reg([_feat(settings={"group": first[1]})], owner=first[0])
        _reg([_feat(settings={"group": second[1]})], owner=second[0])
        spine.validate_all()
        assert spine.group_status("zz_eb_g1") == "hidden" and spine.group_status("zz_eb_g2") == "hidden", (first, second)
        assert spine.feature_enabled("zz_eb_f") is False
    spine.drop_owner("zz_eb2")                                                               # 輸家／贏家其一卸載 ⇒ 另一方重新登錄後恢復
    _reg([_feat(settings={"group": "zz_eb_g1"})], owner="zz_eb1")
    spine.validate_all()
    assert spine.group_status("zz_eb_g1") == "open" and spine.group_status("zz_eb_g2") == "open"       # g2 已無任何宣告 ⇒ 未歸屬＝open


def test_settings_center_hub_card_is_superadmin_only():
    import json
    from pathlib import Path
    cards = json.loads((Path(__file__).resolve().parents[2] / "core" / "system_hub_l1.json").read_text(encoding="utf-8"))["cards"]
    c = [x for x in cards if x["id"] == "settings-center"][0]
    assert c["perm"] == "superadmin"                  # 徽章（含『已隱藏 M 項』）只附在有權限者看得到的卡片上


# --- 驗證 ---------------------------------------------------------------------------------------

def test_settings_group_must_exist_and_belong_to_the_owner(sp):
    _reg([_feat(settings={"group": "zz_eb_missing"})])
    r = spine.validate_all()
    assert r["features"][0]["state"] == "failed" and "沒有登錄" in r["features"][0]["problems"][0]
    spine.reset()
    _group("zz_eb_g", owner="zz_other")
    _reg([_feat(settings={"group": "zz_eb_g"})])
    assert "擁有者是 zz_other" in spine.validate_all()["features"][0]["problems"][0]
    spine.reset()
    R._GROUPS["zz_eb_g"]["owner"] = "zz_eb1"
    _reg([_feat(settings={"group": "zz_eb_g"})])
    assert spine.validate_all()["features"][0]["state"] == "ok"


def test_new_high_risk_fields_need_impact_scope_and_choices_need_int(sp):
    risky = dict(risk="money", risk_text="金額可能不一致。", requires_pending=True)
    _group("zz_eb_g", "zz_eb1", _field("a", **risky))
    _reg([_feat(settings={"group": "zz_eb_g"})])
    assert any("impact_scope" in p for p in spine.validate_all()["features"][0]["problems"])
    R._GROUPS.pop("zz_eb_g")
    _group("zz_eb_g", "zz_eb1", _field("a", impact_scope=SCOPE, **risky))
    assert spine.validate_all()["features"][0]["state"] == "ok"
    R._GROUPS.pop("zz_eb_g")
    _group("zz_eb_g", "zz_eb1", R.SettingDef("m", "str", "a", question="選哪一個？", label="選項", help="測試用的選項欄位。", impact="影響測試用的畫面。",
                                              choices=[("a", "甲方案", "選甲的影響。"), ("b", "乙方案", "選乙的影響。")]))
    assert any("整數代碼" in p for p in spine.validate_all()["features"][0]["problems"])


def test_one_group_cannot_belong_to_two_features(sp):
    _group("zz_eb_g")
    _reg([_feat("zz_eb_a", settings={"group": "zz_eb_g"}), _feat("zz_eb_b", settings={"group": "zz_eb_g"})])
    st = {f["code"]: f for f in spine.validate_all()["features"]}
    assert st["zz_eb_a"]["state"] == "ok" and st["zz_eb_b"]["state"] == "failed" and "同時歸屬" in st["zz_eb_b"]["problems"][0]


def test_mail_types_must_be_registered_by_the_owner(sp):
    _reg([_feat(mail=["zz_eb_mail"])])
    assert "沒有登記" in spine.validate_all()["features"][0]["problems"][0]
    mail_types._REGISTRY["zz_eb_mail"] = mail_types.MailType("zz_eb_mail", "測試信", "business", "none", "", "影響", "處理", owner="zz_other")
    assert "登記者是 zz_other" in spine.validate_all()["features"][0]["problems"][0]
    mail_types._REGISTRY["zz_eb_mail"] = mail_types.MailType("zz_eb_mail", "測試信", "business", "none", "", "影響", "處理", owner="zz_eb1")
    assert spine.validate_all()["features"][0]["state"] == "ok"


def test_declared_capabilities_must_exist_in_the_same_module_json(sp):
    _reg([_feat(capabilities=["zz_eb.obj.view"])], caps=[{"key": "zz_eb.other.view"}])
    assert "不在本模組" in spine.validate_all()["features"][0]["problems"][0]
    spine.reset()
    _reg([_feat(capabilities=["zz_eb.obj.view"])], caps=[{"key": "zz_eb.obj.view"}])
    assert spine.validate_all()["features"][0]["state"] == "ok"


def test_validator_exception_fails_the_feature_and_unvalidated_sections_are_pending(sp, monkeypatch):
    monkeypatch.setattr(spine, "_VALIDATORS", dict(spine._VALIDATORS))

    def boom(feat):
        raise RuntimeError("down")
    spine.register_validator("zz_eb_boom", boom)
    _reg([_feat()])
    r = spine.validate_all()["features"][0]
    assert r["state"] == "failed" and "zz_eb_boom" in r["problems"][0]
    spine._VALIDATORS.pop("zz_eb_boom")
    spine.reset()
    _reg([_feat(catalog={"fields": ["f"]})])
    r = spine.validate_all()["features"][0]
    assert r["state"] == "pending_validator" and r["pendingSections"] == ["catalog"]            # 目錄驗證器尚未落地：不算失敗
    spine.register_validator("zz_eb_cat", lambda f: [], covers=("catalog",))
    assert spine.validate_all()["features"][0]["state"] == "ok"
    with pytest.raises(ValueError):
        spine.register_validator("zz_eb_cat", lambda f: [])                                     # 同名不同函式


# --- 狀態查詢 -------------------------------------------------------------------------------------

def test_status_queries(sp):
    _group("zz_eb_ga")
    _group("zz_eb_gb")
    _group("zz_eb_gc")
    _reg([_feat("zz_eb_open", settings={"group": "zz_eb_ga"}),
          _feat("zz_eb_plan", settings={"group": "zz_eb_gb"}, status="planned", planned_train="MS3"),
          _feat("zz_eb_hide", settings={"group": "zz_eb_gc"}, status="hidden")])
    # validate_all 之前：群組一律 open（保守），功能只看宣告狀態
    assert [spine.group_status(g) for g in ("zz_eb_ga", "zz_eb_gb", "zz_eb_gc")] == ["open"] * 3
    assert [spine.feature_enabled(c) for c in ("zz_eb_open", "zz_eb_plan", "zz_eb_hide")] == [True, False, False]
    spine.validate_all()
    assert [spine.group_status(g) for g in ("zz_eb_ga", "zz_eb_gb", "zz_eb_gc", "zz_not_declared")] == ["open", "planned", "hidden", "open"]
    assert spine.feature_status("zz_eb_plan") == "planned" and spine.planned_train("zz_eb_plan") == "MS3" and spine.planned_train("zz_eb_open") is None
    assert spine.feature_enabled("zz_never_declared") is True and spine.feature_status("zz_never_declared") == "open"
    assert spine.report()["problems"] == 0


def test_failed_feature_is_disabled_and_its_group_is_hidden(sp):
    _group("zz_eb_g")
    _reg([_feat(settings={"group": "zz_eb_g"}, mail=["zz_eb_nomail"])])
    spine.validate_all()
    assert spine.feature_enabled("zz_eb_f") is False and spine.group_status("zz_eb_g") == "hidden"
    assert spine.report()["problems"] == 1


def test_invalid_status_value_is_fail_closed(sp):
    _group("zz_eb_g")
    _reg([_feat(settings={"group": "zz_eb_g"}, status="paused")])
    spine.validate_all()
    assert spine.feature_enabled("zz_eb_f") is False and spine.group_status("zz_eb_g") == "hidden"


def test_owner_failure_or_unload_drops_its_features(sp):
    _reg([_feat()])
    assert spine.report()["features"]
    registry.mark_failed("zz_eb1", "測試")
    assert spine.report()["features"] == [] and spine.feature_enabled("zz_eb_f") is True


# --- 載入器整合 -----------------------------------------------------------------------------------

def _make_pkg(tmp_path, pkg, mods):
    root = tmp_path / pkg
    root.mkdir()
    (root / "__init__.py").write_text("", encoding="utf-8")
    for key, (manifest, src) in mods.items():
        d = root / key
        d.mkdir()
        (d / "module.json").write_text(json.dumps(manifest), encoding="utf-8")
        (d / "__init__.py").write_text(src, encoding="utf-8")
    return root


_SRC = "from core.registry import ModuleSpec\nMODULE = ModuleSpec(key='%s')\n"
_SRC_G = ("from core.registry import ModuleSpec\nfrom helpers import settings_registry as R\n"
          "R.register_group('%s', '測試群組', [R.SettingDef('n', 'int', 1, min=0, max=9, question='這項要設多少？', label='測試項目', help='測試用的設定項目。', impact='影響測試用的畫面。')], help='測試用的設定群組。')\n"
          "MODULE = ModuleSpec(key='%s')\n")


def test_loader_registers_features_validates_after_all_modules_and_isolates_bad_ones(tmp_path, monkeypatch, sp):
    pkg = "fake_mods_eb"
    root = _make_pkg(tmp_path, pkg, {
        "eb_a": ({"key": "eb_a", "core": ">=1.0,<2.0", "settings": {"groups": ["zz_eb_pg"]},
                  "features": [{"code": "zz_eb_plan", "label": "規劃中的功能", "status": "planned", "planned_train": "MS2", "settings": {"group": "zz_eb_pg"}}]},
                 _SRC_G % ("zz_eb_pg", "eb_a")),
        "eb_b": ({"key": "eb_b", "core": ">=1.0,<2.0", "features": [{"code": "zz_eb_bad", "label": "壞功能", "mail": ["zz_eb_nomail"]}]}, _SRC % "eb_b"),
        "eb_c": ({"key": "eb_c", "core": ">=1.0,<2.0", "features": {"not": "a list"}}, _SRC % "eb_c"),
        "eb_d": ({"key": "eb_d", "core": ">=1.0,<2.0"}, _SRC % "eb_d"),                       # 沒有 features：不受影響
    })
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        got = loader.load_all(str(root), pkg)
        assert sorted(m.key for m in got if m.key.startswith("eb_")) == ["eb_a", "eb_b", "eb_d"]      # features 不是清單 ⇒ 整個模組不載入（load_all 回傳全域已載入清單：組裝樹上還有真實模組，只看自己的夾具）
        assert "features" in registry.failed()["eb_c"]
        rep = {f["code"]: f for f in spine.report()["features"]}
        assert spine.report()["validated"] is True
        assert rep["zz_eb_plan"]["status"] == "planned" and rep["zz_eb_plan"]["state"] == "ok" and rep["zz_eb_plan"]["plannedTrain"] == "MS2"
        assert rep["zz_eb_bad"]["state"] == "failed"                                         # 功能層級的問題不擋模組載入
        assert spine.group_status("zz_eb_pg") == "planned"
    finally:
        for k in list(sys.modules):
            if k.startswith(pkg):
                del sys.modules[k]


# --- 設定登錄表的引擎層攔截（需要資料庫）---------------------------------------------------------------

def _later(days=30):
    return (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")


def _counts(c):
    return (c.execute("SELECT COUNT(*) FROM config_changes").fetchone()[0],
            c.execute("SELECT COUNT(*) FROM ui_definitions WHERE kind=?", (R.KIND,)).fetchone()[0])


def _setup_group(owner_status, **fkw):
    R._GROUPS.pop("zz_eb_g", None)
    risky = dict(risk="money", risk_text="金額可能不一致。", requires_pending=True, impact_scope=SCOPE)
    R.register_group("zz_eb_g", "引擎測試群組", [
        R.SettingDef("limit", "int", 100, min=1, max=1000, question="額度上限要設多少？", label="額度上限", help="單筆核准的額度上限。",
                     impact="影響之後送出的單據。", presets={"嚴格": 50}, **risky),
        R.SettingDef("note", "int", 7, min=1, max=30, question="提醒要提前幾天？", label="提前提醒", help="到期前幾天提醒。", impact="影響之後的提醒。", presets={"嚴格": 3})],
        help="引擎測試用群組。", risk="money", owner="zz_eb1")
    kw = {"status": owner_status}
    if owner_status == "planned":
        kw["planned_train"] = "MS2"
    spine.reset()
    spine.register_manifest({"features": [{"code": "zz_eb_f", "label": "引擎測試功能", "settings": {"group": "zz_eb_g"}, **kw}]}, "zz_eb1")
    spine.validate_all()
    R.invalidate()


@pytest.fixture
def eng(client, make_user, monkeypatch):
    snap = spine.snapshot()
    monkeypatch.setattr(spine, "_POST_VALIDATE", [])
    make_user(username="eb_a", role="superadmin")
    make_user(username="eb_b", role="superadmin")
    c = get_db()
    R.invalidate()
    yield c
    c.close()
    spine.restore(snap)
    R._GROUPS.pop("zz_eb_g", None)
    R.invalidate()


@pytest.mark.parametrize("st,msg", [("planned", "開發中"), ("hidden", "沒有這個設定群組")])
def test_publish_plan_and_impact_refuse_non_open_groups(eng, st, msg):
    _setup_group(st)
    before = _counts(eng)
    with pytest.raises(R.SettingError) as e:
        R.publish("zz_eb_g", {"note": 9}, reason="測試", user="eb_a", conn=eng)
    assert msg in str(e.value)
    p = R.plan("zz_eb_g", {"note": 9}, user="eb_a", conn=eng)
    assert p["ok"] is False and msg in p["problems"][0]["message"] and p["fields"] == []
    assert R.live_impact("zz_eb_g", "note", 9)["live"] is None
    assert _counts(eng) == before
    assert R.get("zz_eb_g", "note", conn=eng) == 7                                          # 讀取（預設值）照常
    assert R.group_status("zz_eb_g") == st and "zz_eb_g" in R.groups()                       # 登錄表本身完整（基準仍被比對）


def test_open_group_still_publishes_normally(eng):
    _setup_group("open")
    out = R.publish("zz_eb_g", {"note": 9}, reason="測試", user="eb_a", conn=eng)
    assert out["changed"] is True and R.get("zz_eb_g", "note", conn=eng) == 9


def test_profiles_skip_non_open_groups_and_say_so(eng):
    _setup_group("planned")
    assert "嚴格" not in R.profiles()                                                       # 只有這個非 open 群組有『嚴格』⇒ 預設組不存在
    assert R.profile_preview("嚴格", conn=eng) == []
    sk = [s for s in R.profile_skipped("嚴格") if s["group"] == "zz_eb_g"]
    assert sk and sk[0]["status"] == "planned" and sk[0]["fields"] == 2 and sk[0]["reason"] == "開發中"
    before = _counts(eng)
    with pytest.raises(R.SettingError):
        R.apply_profile("嚴格", reason="測試", user="eb_a", conn=eng)
    assert _counts(eng) == before and R.get("zz_eb_g", "limit", conn=eng) == 100             # 沒有動到略過的群組
    _setup_group("hidden")
    assert [s["reason"] for s in R.profile_skipped("嚴格") if s["group"] == "zz_eb_g"] == ["隱藏"]
    _setup_group("open")
    assert any(c["group"] == "zz_eb_g" for c in R.profile_preview("嚴格", conn=eng)) and not [s for s in R.profile_skipped("嚴格") if s["group"] == "zz_eb_g"]


def test_due_and_approved_pending_item_is_ignored_at_read_time_when_group_turns_planned(eng):
    _setup_group("open")
    out = R.publish("zz_eb_g", {"limit": 200}, reason="調高", user="eb_a", conn=eng)
    cid = out["pending"][0]["id"]
    if out["pending"][0]["approvalsRequired"]:
        assert L.approve(eng, cid, "eb_b")["ok"]
    eng.commit()
    assert R.get_group("zz_eb_g", conn=eng, now=_later())["limit"] == 200                    # 開放時：到期（且核准）就生效
    _setup_group("planned")
    assert R.get_group("zz_eb_g", conn=eng, now=_later())["limit"] == 100                    # 翻成 planned：讀到的是已儲存的值
    assert R.materialize_due(eng, now=_later()) == 0                                         # 不寫入
    eng.commit()
    assert L.state_of(eng, cid) == "cancelled"
    ev = eng.execute("SELECT actor FROM config_change_events WHERE change_id=? AND event='cancelled'", (cid,)).fetchall()
    assert [e["actor"] for e in ev] == ["system"]
    _setup_group("open")                                                                     # 翻回 open：票不復活
    assert L.pending(eng, "setting:zz_eb_g") == []
    assert R.get_group("zz_eb_g", conn=eng, now=_later())["limit"] == 100


def test_startup_callback_cancels_every_pending_item_of_non_open_groups(eng):
    _setup_group("open")
    cid = R.publish("zz_eb_g", {"limit": 300}, reason="調高", user="eb_a", conn=eng)["pending"][0]["id"]
    eng.commit()
    _setup_group("hidden")
    assert R.cancel_pending_of_nonopen(eng) == 1 and L.state_of(eng, cid) == "cancelled"
    assert R.cancel_pending_of_nonopen(eng) == 0                                             # 再跑一次沒有東西可取消（冪等）
    _setup_group("open")
    assert R.cancel_pending_of_nonopen(eng) == 0


def test_publish_never_fails_because_the_spine_is_broken_or_uninitialised(eng, monkeypatch):
    def boom(group):
        raise RuntimeError("spine down")
    monkeypatch.setattr(spine, "group_status", boom)
    assert R.group_status("retention") == "open"
    out = R.publish("retention", {"local_db_keep_days": 40}, reason="測試", user="eb_a", conn=eng)       # 延長＝立即生效
    assert out["changed"] is True
    spine.reset()
    monkeypatch.undo()
    assert R.group_status("retention") == "open" and spine.group_status("retention") == "open"


# --- 稽核去重與健康卡徽章 -------------------------------------------------------------------------

def test_failed_features_are_audited_once_per_distinct_problem_set(eng):
    spine.reset()
    spine.register_manifest({"features": [{"code": "zz_eb_bad", "label": "壞功能", "mail": ["zz_eb_nomail"]}]}, "zz_eb1")
    spine.validate_all()
    q = "SELECT detail FROM audit_log WHERE action='spine.validation_failed' AND target_id='zz_eb_bad'"
    assert R.audit_spine_failures(eng) == 1 and len(eng.execute(q).fetchall()) == 1
    assert R.audit_spine_failures(eng) == 0 and len(eng.execute(q).fetchall()) == 1          # 重啟再跑：不再灌
    spine.reset()
    spine.register_manifest({"features": [{"code": "zz_eb_bad", "label": "壞功能", "mail": ["zz_eb_nomail2"]}]}, "zz_eb1")
    spine.validate_all()
    assert R.audit_spine_failures(eng) == 1 and len(eng.execute(q).fetchall()) == 2          # 問題變了才再記
    spine.reset()
    spine.register_manifest({"features": [{"code": "zz_eb_ok", "label": "好功能"}]}, "zz_eb1")
    spine.validate_all()
    assert R.audit_spine_failures(eng) == 0


def test_orphan_problems_are_audited_too(eng):
    spine.reset()
    spine.register_manifest({"features": [{"label": "沒有代號"}]}, "zz_eb1")
    spine.validate_all()
    assert R.audit_spine_failures(eng) == 1
    assert eng.execute("SELECT COUNT(*) FROM audit_log WHERE action='spine.validation_failed' AND target_id='owner:zz_eb1'").fetchone()[0] == 1


def test_hub_badge_reports_failures_info_and_ok(sp):
    from core import registry as _r
    from routers import settings_center as SC
    assert _r.providers("system.hub_badge")["settings-center"] is SC._hub_badge
    assert SC._hub_badge(None, None) == {"text": "功能登錄正常", "tone": "ok"}
    _reg([_feat("zz_eb_p", status="planned", planned_train="MS2"), _feat("zz_eb_h", status="hidden")])
    spine.validate_all()
    b = SC._hub_badge(None, None)
    assert b == {"text": "開發中 1 項・已隱藏 1 項", "tone": "plan"}                                 # 資訊，不是失敗
    _reg([_feat("zz_eb_bad", mail=["zz_eb_nomail"])], owner="zz_eb2")
    spine.validate_all()
    b = SC._hub_badge(None, None)
    assert b["tone"] == "bad" and b["count"] == 1 and "1 項功能登錄未通過驗證" in b["text"] and len(b["text"]) <= 40


# --- 核心功能宣告（core/features_l1.json）＝灰色『開發中』卡片 ---------------------------------------

def test_core_declaration_file_is_valid_plain_and_all_planned(sp):
    import json
    import re
    assert spine.register_core_declarations() == []                                   # 真的檔案：沒有任何驗證問題
    r = spine.validate_all()
    assert r["problems"] == 0 and r["features"] and all(f["state"] == "ok" and f["owner"] == "core" for f in r["features"])
    codes = [f["code"] for f in r["features"]]
    assert len(codes) == len(set(codes)) >= 10
    for f in r["features"]:
        assert f["status"] == "planned" and re.match(r"^MS[1-9][0-9]?$", f["plannedTrain"]), f
        plain = re.sub(r"Excel|CSV|PDF", "", f["label"])                                      # 使用者熟悉的產品名稱可以出現，其餘不放英文代號／數字
        assert not re.search(r"[A-Za-z0-9_]", plain), "label 要是白話（不放英文代號／數字）：%r" % f["label"]
    raw = json.loads(spine.CORE_FEATURES_FILE.read_text(encoding="utf-8"))
    assert all(set(x) == {"code", "label", "status", "planned_train"} for x in raw["features"])      # 目前沒有設定群組＝只有狀態的卡片
    assert not any("settings" in x for x in raw["features"])


def test_planned_cards_lists_only_status_only_planned_features_sorted_by_train(sp):
    _group("zz_eb_g")
    _reg([_feat("zz_eb_c3", label="後面的卡片", status="planned", planned_train="MS3"),
          _feat("zz_eb_c2b", label="乙卡片", status="planned", planned_train="MS2"),
          _feat("zz_eb_c2a", label="甲卡片", status="planned", planned_train="MS2"),
          _feat("zz_eb_with_group", label="有群組的", status="planned", planned_train="MS2", settings={"group": "zz_eb_g"}),
          _feat("zz_eb_hidden", label="隱藏的", status="hidden"),
          _feat("zz_eb_open", label="已開放的"),
          _feat("zz_eb_bad", label="壞的", status="planned", planned_train="MS2", mail=["zz_eb_nomail"])])
    spine.validate_all()
    assert [c["code"] for c in spine.planned_cards()] == ["zz_eb_c2a", "zz_eb_c2b", "zz_eb_c3"]
    assert spine.planned_cards()[0] == {"code": "zz_eb_c2a", "label": "甲卡片", "plannedTrain": "MS2"}


def test_core_declaration_file_problems_never_break_loading(sp, tmp_path):
    bad = tmp_path / "features_l1.json"
    bad.write_text("{not json", encoding="utf-8")
    probs = spine.register_core_declarations(bad)
    assert probs and "讀不懂" in probs[0] and spine.report()["orphans"]["core"]
    assert spine.register_core_declarations(tmp_path / "missing.json") == [] and spine.report()["features"] == []
    bad.write_text('{"features": [{"code": "x_f", "label": "壞掉的", "status": "planned"}]}', encoding="utf-8")        # 缺 planned_train
    assert any("planned_train" in p for p in spine.register_core_declarations(bad))


@pytest.mark.parametrize("raw", ["[1]", '"x"', "5", "null", "true", '{"features": 5}', '{"features": {"a": 1}}',
                                 '{"features": [1, "x", null, [], {"code": "ok_f"}]}'])
def test_core_declaration_file_with_any_json_shape_never_raises(sp, tmp_path, raw):
    """0d：非物件的最上層、features 不是清單、features 裡有非物件項目——都只能變成問題，不可丟例外（否則 load_all 會讓 app 開不了機）。"""
    f = tmp_path / "features_l1.json"
    f.write_text(raw, encoding="utf-8")
    probs = spine.register_core_declarations(f)                 # 不丟例外
    assert probs, raw                                            # 每一種都有問題記錄
    spine.validate_all()                                         # 驗證階段也不丟例外


def test_loader_survives_a_core_declaration_reader_that_raises(tmp_path, sp, monkeypatch):
    """loader 層自己的保險：就算 register_core_declarations 丟例外，load_all 仍照常回傳（正對照：拿掉 try／except 這題就紅）。"""
    def boom(path=None):
        raise RuntimeError("reader down")
    monkeypatch.setattr(spine, "register_core_declarations", boom)
    assert loader.load_all(str(tmp_path / "nope"), "nope") == []


def test_no_feature_code_is_declared_by_both_core_and_a_module():
    """一個功能代號不可同時出現在 core/features_l1.json 與任何 module.json 的 features[]：否則 _CLAIMS 會讓兩邊都失敗。
    某模組正式宣告該功能的那個提交，必須同時把 core 的那一筆移除（或改為不重複的代號）。"""
    from pathlib import Path
    core = {x["code"] for x in json.loads(spine.CORE_FEATURES_FILE.read_text(encoding="utf-8"))["features"]}
    clash = {}
    for m in sorted((Path(__file__).resolve().parents[2] / "modules").glob("*/module.json")):
        for f in (json.loads(m.read_text(encoding="utf-8")).get("features") or []):
            if isinstance(f, dict) and f.get("code") in core:
                clash[f["code"]] = m.parent.name
    assert clash == {}, "功能代號同時出現在 core/features_l1.json 與模組宣告：%s（請在同一提交移除 core 的那一筆）" % clash


def test_loader_registers_core_declarations_even_without_a_modules_dir(tmp_path, sp):
    assert loader.load_all(str(tmp_path / "nope"), "nope") == []
    rep = spine.report()
    assert rep["validated"] is True and any(f["code"] == "rule_engine" and f["plannedTrain"] == "MS3" for f in rep["features"])
