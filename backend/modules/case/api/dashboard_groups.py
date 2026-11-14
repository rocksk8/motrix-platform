# -*- coding: utf-8 -*-
"""首頁「我的工作」的案件分組（提供者 `dashboard.mine_groups`，名稱 `case`）。

只回「現在要處理」的數字與前幾筆：我的案件（進行中／階段逾期／應收逾期）、錢的那一組（應收逾期，財務／最高管理者）。
件數一律經案件清單的本體 `list_quotations_for`（limit=0，只取總數）：與案件頁同一份篩選與權限（row_access）、同一個母體
（已成案、未結案）⇒ 首頁寫的件數＝點進去清單看到的件數；這支檔自己不寫 SQL、不碰 data_json。
沒有案件管理模組權限 ⇒ 不回「我的案件」；沒有案件頁權限的財務帳號：「應收款項追蹤」只給數字、不給連結。
"""
import logging

from db import db_conn
from helpers import user_has_module
from helpers.auth import has_finance_access
from modules.case.api.quotations import list_quotations_for

logger = logging.getLogger(__name__)

HREF = "pages/case-management.html"
_TAG = "已成案"


def _n(user: dict, mine: int = 0, stage_overdue: int = 0, recv_overdue: int = 0) -> int:
    """明列關鍵字（棘輪禁止用 ** 傳參數）；全部照原樣交給清單本體，不改它的語意。"""
    res = list_quotations_for(user, deal_tag=_TAG, limit=0, mine=mine, stage_overdue=stage_overdue, recv_overdue=recv_overdue)
    return int(res.get("total") or 0)


def mine_groups(user: dict) -> list:
    out = []
    can_case = user_has_module(user, "case_manage") or user_has_module(user, "quotation")
    money = has_finance_access(user)
    if not (can_case or money):
        return out
    if can_case:
        active = _n(user, mine=1)
        stage = _n(user, mine=1, stage_overdue=1)
        recv = _n(user, mine=1, recv_overdue=1)
        items = []
        if stage:
            items.append({"title": "有階段已過預定日", "sub": "%d 件案件" % stage, "href": HREF + "?quick=mine,stage_overdue", "tone": "crit"})
        if recv:
            items.append({"title": "有款項已過預計收款日", "sub": "%d 件案件" % recv, "href": HREF + "?quick=mine,recv_overdue", "tone": "crit"})
        out.append({"key": "my_cases", "title": "我的案件", "count": active, "href": HREF + "?quick=mine",
                    "hrefLabel": "查看我的案件", "items": items, "kind": "work", "order": 40,
                    "empty": "尚無進行中的案件"})
    if money:
        recv_all = _n(user, recv_overdue=1)
        link = (HREF + "?quick=recv_overdue") if can_case else ""
        items = ([{"title": "款項已過預計收款日", "sub": "%d 件案件" % recv_all, "href": link, "tone": "crit"}]
                 if recv_all else [])
        out.append({"key": "receivable_overdue", "title": "應收款項追蹤", "count": recv_all, "href": link,
                    "hrefLabel": "前往催收", "items": items, "kind": "money", "order": 60,
                    "empty": "尚無逾期未收的款項"})
    return out


def new_quotes_since(since_iso: str) -> int:
    """`greeting.new_quotes`：某個本地時間（ISO 字串，精確到秒）之後建立的報價單張數（登入問候語的「離開期間新增 N 張報價單」；
    呼叫端只對看得到全部案件的最高管理者使用這個數字）。建立時間是本地時間的 ISO 字串 ⇒ 逐字比較。"""
    with db_conn() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM quotations WHERE created_at > ?", (str(since_iso),)).fetchone()[0] or 0)
