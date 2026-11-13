# -*- coding: utf-8 -*-
"""系統標語（UX P1.5，PM 2026-11-13 轉述使用者方針）：預設 `MOTRIX PLATFORM`、公司可自訂、不再寫「專案管理系統」。"""
import pathlib

import pytest

import helpers.settings_groups  # noqa: F401  登錄群組
from helpers import settings_groups_brand as B
from helpers import settings_registry as SR

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_default_is_motrix_platform_and_group_is_registered():
    assert B.DEFAULT_TAGLINE == "MOTRIX PLATFORM"
    g = SR.groups()["brand"]
    f = {x["key"]: x for x in g["fields"]}["tagline"]
    assert f["default"] == "MOTRIX PLATFORM" and f["recommended"] == "MOTRIX PLATFORM" and f["risk"] == "none"


@pytest.mark.parametrize("bad", ["", "   ", "x" * 25, "a\nb", "<b>x</b>"])
def test_cross_check_rejects_bad_values(bad):
    assert B._cross_check({"tagline": bad})


@pytest.mark.parametrize("ok", ["MOTRIX PLATFORM", "某某科技 PLATFORM", "一二三四五六七八九十一二三四五六七八九十一二三四"])
def test_cross_check_accepts_good_values(ok):
    assert B._cross_check({"tagline": ok}) == []


def test_reader_never_raises_and_falls_back(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(SR, "get_group", boom)
    assert B.brand_tagline() == "MOTRIX PLATFORM"
    monkeypatch.setattr(SR, "get_group", lambda g: {"tagline": "  "})
    assert B.brand_tagline() == "MOTRIX PLATFORM"
    monkeypatch.setattr(SR, "get_group", lambda g: {"tagline": " 我的系統 "})
    assert B.brand_tagline() == "我的系統"
    monkeypatch.setattr(SR, "get_group", lambda g: {"tagline": "<x>"})
    assert B.brand_tagline() == "MOTRIX PLATFORM"


def test_branding_endpoint_is_public_and_carries_tagline(client):
    r = client.get("/api/system/branding")
    assert r.status_code == 200 and r.json()["tagline"] == "MOTRIX PLATFORM"


def test_no_page_title_says_project_management_system():
    bad = []
    for p in (REPO / "frontend").rglob("*.html"):
        s = p.read_text(encoding="utf-8", errors="replace")
        if "專案管理系統" in s:
            bad.append(str(p.relative_to(REPO)))
    assert not bad, "畫面不再寫「專案管理系統」（改 MOTRIX PLATFORM／公司標語）：%s" % bad


def test_dashboard_kicker_uses_company_tagline():
    s = (REPO / "frontend/index.html").read_text(encoding="utf-8")
    assert "branding.tagline || 'MOTRIX PLATFORM'" in s
