# -*- coding: utf-8 -*-
"""C7：小模組狀態／單位／用語顯示名稱（display_labels）。預設＝各畫面原本寫死的字（部署零行為變更）；只換顯示，不換狀態值。"""
import pathlib
import re

import pytest

import trail
from helpers import display_labels as DL
from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as SR
from modules.lodging import search as LS

FRONT = pathlib.Path(__file__).resolve().parents[3] / "frontend"
BACK = pathlib.Path(__file__).resolve().parents[2]


def _fields(g):
    return SR._g(g)["fields"]


def _override(monkeypatch, group, **changes):
    vals = dict(DL.DEFAULTS[group])
    vals.update(changes)
    real = SR.get_group
    monkeypatch.setattr(SR, "get_group", lambda g, **kw: dict(vals) if g == group else real(g, **kw))
    DL._MEMO.clear()


def test_groups_registered_as_core_display_only_with_legacy_defaults():
    for g, d in DL.DEFAULTS.items():
        assert SR.groups()[g]["owner"] == "core"
        f = _fields(g)
        assert list(f) == list(d)
        for k, v in d.items():
            assert f[k].default == v and f[k].type == "str" and f[k].risk == "none" and not f[k].loosen and not f[k].requires_pending
            assert "不改任何資料" in f[k].impact or "只換" in f[k].impact


def test_defaults_equal_the_literals_that_were_hardcoded():
    assert {k: DL.DEFAULTS["trail_labels"][k] for k in trail.KIND_LABELS} == trail.KIND_LABELS
    for code, key in trail._RESULT_KEY.items():
        assert DL.DEFAULTS["trail_labels"][key] == trail.STATUS_LABELS[code]
    assert {DL.DEFAULTS["lodging_labels"][k] for k in LS.QUOTE_UNITS} == set(LS.QUOTE_UNITS.values())
    assert all(DL.DEFAULTS["lodging_labels"][k] == v for k, v in {**LS.QUOTE_UNITS, **LS.QUOTE_CHANNELS}.items())
    from modules.netplan import api as NP
    assert tuple(DL.NETPLAN_KEY) == NP._STATUSES
    assert tuple(DL.DEFAULTS["netplan_labels"][DL.NETPLAN_KEY[s]] for s in NP._STATUSES) == NP._STATUSES
    assert DL.DEFAULTS["procurement_labels"] == {"suggested": "待下單", "ordered": "已下單", "received": "已到貨"}
    from helpers import procurement as PR
    assert tuple(DL.DEFAULTS["procurement_labels"]) == PR.STATUS_SEQUENCE


def test_js_defaults_match_python_defaults():
    src = (FRONT / "static" / "display-labels.js").read_text(encoding="utf-8")
    body = re.search(r"const DEF = \{(.*?)\n  \}\n", src, re.S).group(1)
    js = {}
    for g, inner in re.findall(r"(\w+_labels):\s*\{(.*?)\}", body, re.S):
        js[g] = dict(re.findall(r"(\w+):\s*'([^']*)'", inner))
    assert js == DL.DEFAULTS
    assert dict(re.findall(r"'(.+?)':\s*'(\w+)'", re.search(r"const NETPLAN_KEY = \{(.*?)\}", src).group(1))) == DL.NETPLAN_KEY


def test_labels_return_defaults_when_nothing_is_set():
    for g, d in DL.DEFAULTS.items():
        assert DL.labels(g) == d
    assert DL.label("lodging_labels", "per_night") == "每晚"
    assert DL.label("lodging_labels", "no_such_key") == "no_such_key"
    assert DL.status_text("規劃中") == "規劃中" and DL.status_text("不認得") == "不認得" and DL.status_text(None) == ""


def test_override_changes_only_the_shown_text(monkeypatch):
    _override(monkeypatch, "lodging_labels", per_night="每房每晚")
    assert DL.label("lodging_labels", "per_night") == "每房每晚"
    out = LS.quote_out({"id": 1, "quoted_on": "2026-10-01", "room_type": "雙人房", "price": 2800, "unit": "per_night", "includes": "",
                        "channel": "phone", "note": "", "entered_by": "u", "entered_at": "t"})
    assert out["unit"] == "per_night" and out["unitLabel"] == "每房每晚" and out["channelLabel"] == "電話"


def test_trail_uses_labels_and_default_is_unchanged(monkeypatch):
    assert trail.describe("GET", "/api/quotations")["kindLabel"] == "檢視"
    assert [trail.status_label(c) for c in (200, 204, 403, 409)] == ["成功", "成功", "沒有權限（被擋下）", "有人剛改過（衝突）"]
    assert trail.status_label(302) == "轉向" and trail.status_label(500) == "系統錯誤" and trail.status_label(418) == "失敗（418）"
    _override(monkeypatch, "trail_labels", view="查閱", ok="完成")
    d = trail.describe("GET", "/api/quotations")
    assert d["kind"] == "view" and d["kindLabel"] == "查閱"
    assert trail.status_label(200) == "完成" and trail.status_label(204) == "完成" and trail.status_ok(200)


def test_netplan_text_follows_label_but_state_values_stay(monkeypatch):
    from modules.netplan import api as NP
    _override(monkeypatch, "netplan_labels", planning="籌備中")
    assert DL.status_text("規劃中") == "籌備中" and DL.status_text("已確認") == "已確認"
    assert NP._STATUSES == ("規劃中", "已確認", "已交付")


def _msgs(group, values):
    return [(x["message"] if isinstance(x, dict) else x) for x in SR.validate_values(group, values, partial=True)]


@pytest.mark.parametrize("bad", ["", " 籌備中", "籌備中 ", "一二三四五六七八九十一二三", "已核准", "approved", "<b>x</b>", "籌​備"])
def test_bad_names_are_rejected(bad):
    assert _msgs("netplan_labels", {"planning": bad}), bad


def test_names_must_be_unique_in_a_group_and_default_official_wording_is_kept():
    assert _msgs("netplan_labels", {"planning": "已交付"})
    assert not _msgs("netplan_labels", {"planning": "籌備中"})
    assert not _msgs("netplan_labels", {"confirmed": "已確認"})              # 預設值本身含『確認』，不算違規
    assert not _msgs("trail_labels", {"view": "查閱"})


def test_unsaved_or_broken_values_fall_back_to_the_whole_default_group(monkeypatch):
    _override(monkeypatch, "netplan_labels", planning="已核准")
    assert DL.labels("netplan_labels") == DL.DEFAULTS["netplan_labels"]
    monkeypatch.setattr(SR, "get_group", lambda g, **kw: (_ for _ in ()).throw(RuntimeError("db down")))
    DL._MEMO.clear()
    assert DL.labels("trail_labels") == DL.DEFAULTS["trail_labels"]
    assert trail.describe("GET", "/api/x")["kindLabel"] == "檢視"


def test_pages_read_labels_but_logic_still_uses_state_values():
    for page, needles in {
        "network-plans.html": ["lb.netplan_labels.planning", "stText(p.status)", "display-labels.js", "statusTab==='規劃中'"],
        "network-plan-form.html": ["stText(plan.status)", "stText(s)", "display-labels.js", "plan.status==='規劃中'"],
        "inventory.html": ["lb.procurement_labels.suggested", "s.status === 'suggested'", "display-labels.js", "setSuggestionStatus(s, 'ordered')"],
        "lodging-records.html": ["lb.lodging_labels.per_night", 'value="per_night"', "display-labels.js", "lb.lodging_labels.other"],
    }.items():
        src = (FRONT / "pages" / page).read_text(encoding="utf-8")
        for n in needles:
            assert n in src, (page, n)


def test_no_new_route_is_needed():
    src = (FRONT / "static" / "display-labels.js").read_text(encoding="utf-8")
    assert "/api/settings-center/public?groups=" in src
    assert not (BACK / "routers" / "display_labels.py").exists()
