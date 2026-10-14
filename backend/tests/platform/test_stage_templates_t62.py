# -*- coding: utf-8 -*-
"""S-ST1：案件階段樣板的定義、驗證與治理分類（純函式；設計 docs/platform/plans/CASE-STAGE-TEMPLATE-INVESTIGATION-T62.md）。

①驗證：鍵、名稱（白名單／相似字／斜線）、天數範圍、比例（有設就全設、合計 10000）、前置階段（存在、不自指、不循環）
②治理分類：新增階段（無比例）＝收緊；移除階段＝放寬；比例新增／改值／拿掉＝放寬；改名／工期／順序／前置＝中性；看不懂＝放寬
③旗標關：kind 不登記、功能狀態閘門 hidden、沒有任何程式讀這個定義
④共用的 safe_text：階段名稱允許狀態字樣（「客戶核准」），其他規則不變
"""
import copy

import pytest

from helpers import safe_text as T
from helpers import stage_templates as ST
from routers.def_pipeline import ACTIVE_KINDS, classify

KIND = ST.KIND

OK = {"version": 1, "label": "標準施工案", "stages": [
    {"key": "survey", "label": "現場勘查", "offsetDays": 0, "durationDays": 3, "dependsOn": []},
    {"key": "install", "label": "設備安裝", "offsetDays": 3, "durationDays": 14, "dependsOn": ["survey"]},
    {"key": "accept", "label": "客戶核准", "offsetDays": 17, "durationDays": 2, "dependsOn": ["install"]}]}


def _msgs(mutate, key="std"):
    b = copy.deepcopy(OK)
    mutate(b)
    return [p["message"] for p in ST.definition_problems(key, b)]


def _paths(mutate):
    b = copy.deepcopy(OK)
    mutate(b)
    return {p["path"] for p in ST.definition_problems("std", b)}


def _with_ratios(b, *r):
    for st, v in zip(b["stages"], r):
        st["ratioBp"] = v
    return b


# ── ① 驗證 ──────────────────────────────────────────────────────────────────
def test_a_valid_template_passes_and_stage_names_may_contain_status_words():
    assert ST.definition_problems("std", OK) == []          # 「客戶核准」是合理的階段名稱


def test_template_key_rules():
    assert ST.definition_problems("Bad Key", OK) and ST.definition_problems("", OK) and ST.definition_problems("a" * 31, OK)
    assert ST.definition_problems("ok_key1", OK) == []


@pytest.mark.parametrize("mutate,path", [
    (lambda b: b.update(version=2), "version"),
    (lambda b: b.update(extra=1), "extra"),
    (lambda b: b.update(label=""), "label"),
    (lambda b: b.update(stages=[]), "stages"),
    (lambda b: b.update(stages="x"), "stages"),
    (lambda b: b["stages"][0].update(extra=1), "stages[0].extra"),
    (lambda b: b["stages"][0].update(key="Bad"), "stages[0].key"),
    (lambda b: b["stages"][1].update(key="survey"), "stages[1].key"),
    (lambda b: b["stages"][0].update(label="<b>x</b>"), "stages[0].label"),
    (lambda b: b["stages"][0].update(label="аpproved"), "stages[0].label"),   # 首字是西里爾 а
    (lambda b: b["stages"][0].update(label="水電/空調"), "stages[0].label"),
    (lambda b: b["stages"][0].update(label="x" * 21), "stages[0].label"),
    (lambda b: b["stages"][1].update(label="現場勘查"), "stages[1].label"),
    (lambda b: b["stages"][0].update(offsetDays=-1), "stages[0].offsetDays"),
    (lambda b: b["stages"][0].update(durationDays=731), "stages[0].durationDays"),
    (lambda b: b["stages"][0].update(durationDays=True), "stages[0].durationDays"),
    (lambda b: b["stages"][0].update(durationDays="3"), "stages[0].durationDays"),
    (lambda b: b["stages"][0].update(ratioBp=10001), "stages[0].ratioBp"),
    (lambda b: b["stages"][0].update(dependsOn="x"), "stages[0].dependsOn"),
    (lambda b: b["stages"][1].update(dependsOn=["survey", "survey"]), "stages[1].dependsOn"),
])
def test_validator_rejects(mutate, path):
    assert path in _paths(mutate)


def test_stage_count_limit():
    def many(b):
        b["stages"] = [{"key": "s%d" % i, "label": "階段%d" % i, "offsetDays": 0, "durationDays": 1, "dependsOn": []} for i in range(ST.MAX_STAGES + 1)]
    assert "stages" in _paths(many)


def test_dependencies_must_exist_not_self_reference_and_not_cycle():
    assert any("不存在" in m for m in _msgs(lambda b: b["stages"][0].update(dependsOn=["nope"])))
    assert any("自己" in m for m in _msgs(lambda b: b["stages"][0].update(dependsOn=["survey"])))
    assert any("循環" in m for m in _msgs(lambda b: b["stages"][0].update(dependsOn=["accept"])))


def test_ratio_rules_all_or_none_and_sum_to_10000():
    assert ST.definition_problems("std", _with_ratios(copy.deepcopy(OK), 0, 7000, 3000)) == [], "0＝這個階段不認列，合法"
    assert any("每個階段都要設" in m for m in _msgs(lambda b: b["stages"][1].update(ratioBp=7000)))
    assert any("10000" in m for m in _msgs(lambda b: _with_ratios(b, 0, 7000, 2000)))
    assert any("10000" in m for m in _msgs(lambda b: _with_ratios(b, 5000, 5000, 5000)))
    assert ST.definition_problems("std", _with_ratios(copy.deepcopy(OK), 10000, 0, 0)) == []


# ── ② 治理分類 ──────────────────────────────────────────────────────────────
def _cls(old, mutate):
    new = copy.deepcopy(old)
    mutate(new)
    return classify(KIND, old, new)[0]


def test_case_stage_template_is_an_active_governed_kind():
    assert KIND in ACTIVE_KINDS


def test_comparator_classes():
    assert _cls(OK, lambda b: b["stages"].append({"key": "extra", "label": "追加", "offsetDays": 0, "durationDays": 1, "dependsOn": []})) == "tighten"
    assert _cls(OK, lambda b: b["stages"].pop()) == "loosen", "移除階段＝結案關卡變容易"
    assert _cls(OK, lambda b: b["stages"][0].update(label="勘查", durationDays=9)) == "neutral"
    assert _cls(OK, lambda b: b["stages"].reverse()) == "neutral"
    assert _cls(OK, lambda b: b["stages"][2].update(dependsOn=["survey"])) == "neutral"
    assert _cls(OK, lambda b: b.update(label="另一個名字")) == "neutral"
    assert _cls(OK, lambda b: _with_ratios(b, 0, 7000, 3000)) == "loosen", "新增比例＝影響認列"
    withr = _with_ratios(copy.deepcopy(OK), 0, 7000, 3000)
    assert _cls(withr, lambda b: _with_ratios(b, 0, 6000, 4000)) == "loosen", "改比例"
    assert _cls(withr, lambda b: [s.pop("ratioBp") for s in b["stages"]]) == "loosen", "拿掉比例（認列方式改變）"
    assert _cls(withr, lambda b: None) == "neutral"
    assert _cls(OK, lambda b: b["stages"].append({"key": "z", "label": "含比例", "offsetDays": 0, "durationDays": 1, "dependsOn": [], "ratioBp": 0})) == "loosen"
    assert _cls(OK, lambda b: b["stages"][0].update(weird=1)) == "loosen", "看不懂的鍵"
    assert _cls(OK, lambda b: b.update(unknown=1)) == "loosen"


def test_comparator_removing_a_stage_and_adding_one_together_is_loosen():
    def swap(b):
        b["stages"].pop()
        b["stages"].append({"key": "other", "label": "別的", "offsetDays": 0, "durationDays": 1, "dependsOn": []})
    assert _cls(OK, swap) == "loosen", "鍵改了＝移除舊的＋新增新的，以放寬為準"


def test_first_publish_baseline_is_no_stages():
    assert classify(KIND, {}, OK)[0] == "tighten"
    assert classify(KIND, {}, _with_ratios(copy.deepcopy(OK), 0, 7000, 3000))[0] == "loosen"
    assert classify(KIND, OK, {"version": 1, "label": "x", "stages": "z"})[0] == "loosen"


# ── ③ 旗標關：不登記、閘門 hidden ───────────────────────────────────────────
def test_flag_off_means_no_kind_hidden_gate_and_unreadable_setting_is_off(monkeypatch):
    from core import definitions as D, spine
    monkeypatch.setattr(ST, "enabled", lambda conn=None: False)
    assert spine.kind_info(KIND, "std")["status"] == "hidden"
    assert ST._kind_validator(OK, "std")[0]["message"] == ST.OFF_REASON
    monkeypatch.setattr(ST, "enabled", lambda conn=None: True)
    assert spine.kind_info(KIND, "std")["status"] == "open" and ST._kind_validator(OK, "std") == []
    assert D is not None


def test_enabled_is_fail_closed_when_settings_cannot_be_read(monkeypatch):
    import helpers.settings_registry as SR

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(SR, "get", boom)
    assert ST.enabled() is False


def test_setting_default_is_off():
    from helpers import settings_groups  # noqa: F401  登記設定群組
    from helpers import settings_registry as SR
    assert int(SR.get(ST.GROUP, ST.FIELD)) == 0


# ── ④ safe_text ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,ok", [("現場勘查", True), ("Phase 2 (A-1)", True), ("客戶核准", True), ("", False), ("   ", False), ("a" * 40, False),
                                      ("<b>x</b>", False), ("a&b", False), ("a/b", False), ("bit.ly", False), ("😀", False), ("а", False),
                                      ("a​b", False), ("a\nb", False), ("{x}", False)])
def test_safe_text_allow_status(text, ok):
    assert (T.problem(text, 30, allow_status=True) == "") is ok


@pytest.mark.parametrize("text", ["已核准", "approved", "Final", "批准", "已 通 過"])
def test_safe_text_bans_status_words_unless_allowed(text):
    assert T.problem(text, 30) != "" and T.problem(text, 30, allow_status=True) == ""


@pytest.mark.parametrize("text", ["finally", "unpaid", "avoid"])
def test_safe_text_english_uses_word_boundaries(text):
    assert T.problem(text, 30) == ""


# ── 04 第二輪：fullmatch、NFKC 名稱重複、version 型別、種類清單 ─────────────────────────
def test_keys_use_fullmatch_so_a_trailing_newline_is_rejected():
    assert ST.definition_problems("tpl\n", OK), "樣板鍵結尾換行"
    assert any("種類鍵" in m for m in _msgs(lambda b: b["stages"][0].update(key="survey\n")))
    assert ST.definition_problems("tpl", OK) == []


def test_duplicate_stage_names_are_compared_after_nfkc_and_casefold():
    assert any("重複" in m for m in _msgs(lambda b: b["stages"][1].update(label="ＡＢ")) + _msgs(lambda b: (b["stages"][0].update(label="ＡＢ"), b["stages"][1].update(label="ab"))))
    assert _msgs(lambda b: (b["stages"][0].update(label="ＡＢ"), b["stages"][1].update(label="ＣＤ"))) == []


@pytest.mark.parametrize("v", [1.0, True, "1", 2, None, 0])
def test_version_must_be_the_integer_one(v):
    assert "version" in _paths(lambda b: b.update(version=v))


def test_kind_list_hides_the_kind_when_the_flag_is_off(monkeypatch):
    from routers import definitions as DEFS
    monkeypatch.setattr(ST, "enabled", lambda conn=None: False)
    assert ST.KIND in DEFS._disabled_lazy_kinds()
    monkeypatch.setattr(ST, "enabled", lambda conn=None: True)
    assert ST.KIND not in DEFS._disabled_lazy_kinds()

    def boom(conn=None):
        raise RuntimeError("x")
    monkeypatch.setattr(ST, "enabled", boom)
    assert ST.KIND in DEFS._disabled_lazy_kinds(), "讀不到旗標 ⇒ 視為關（不列出）"


def test_url_like_stage_names_are_rejected_and_the_help_text_says_so():
    assert _msgs(lambda b: b["stages"][0].update(label="Phase 1.20"))
    from helpers import settings_groups  # noqa: F401
    from helpers import settings_registry as SR
    # 設定中心畫面上的說明文字來自群組定義（SR.groups()），不是 group_info（那只回功能狀態 {status, plannedTrain, feature}）
    g = SR.groups()[ST.GROUP]
    help_text = g["help"] + " ".join(str(f.get("help", "")) for f in g["fields"])
    assert "像網址" in help_text, "使用者要在設定說明看到『像網址的名稱會被拒絕』"
