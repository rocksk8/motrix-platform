# -*- coding: utf-8 -*-
"""S6：「我要收的 Email 通知（自己的）」以獨立頁登記在設定外框（保留 my-account.html?tab=notify），並讓全域搜尋找得到。"""
import re

from core import source_tree
from helpers import settings_pages as SP
from helpers import settings_shell as SH

_ID = "my_email_prefs"


def test_my_email_prefs_is_registered_as_a_standalone_page():
    rows = [p for p in SP.pages() if p["id"] == _ID]
    assert len(rows) == 1, "S6 的獨立頁沒登記（或重複）"
    p = rows[0]
    assert p["standalone"] is True and p["category"] in SP.CATEGORIES and p["groups"] == []
    assert p["href"] == "my-account.html?tab=notify"


def test_the_link_target_exists_and_the_tab_is_deep_linkable():
    page = source_tree.page_file("my-account.html").read_text(encoding="utf-8")
    assert re.search(r"key:\s*'notify'", page), "我的帳號沒有 notify 分頁，連結會落空"
    assert "URLSearchParams(location.search).get('tab')" in page, "my-account 不吃 ?tab=，深連結會落到第一個分頁"
    assert 'id="email-prefs-card"' in page


def test_global_search_finds_the_page_by_its_plain_name_and_keywords(client):
    hits = [i for i in SH.search_index() if i["kind"] == "page" and i["page"] == _ID]
    assert len(hits) == 1
    for word in ("Email", "退訂", "不要收", "通知"):
        assert word in hits[0]["text"], word
    assert hits[0]["href"] == "my-account.html?tab=notify"
