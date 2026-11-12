# -*- coding: utf-8 -*-
"""首頁「我的工作」的案件分組（提供者 `dashboard.mine_groups`，名稱 `case`）。

只回「現在要處理」的數字與前幾筆：我的案件（進行中／階段逾期／應收逾期）、錢的那一組（應收逾期，財務／最高管理者）。
權限＝與案件清單同一份 `row_access.filter_sql("case", user)`（看不到的案件不計入）；沒有案件管理模組權限 ⇒ 不回「我的案件」。
"""
import logging

from db import db_conn
from helpers import row_access, user_has_module
from helpers.auth import has_finance_access
from modules.case.api import quotations as _q
from modules.case.quotations import SQL_DEAL_TAG

logger = logging.getLogger(__name__)

HREF = "pages/case-management.html"


def _today() -> str:
    from routers.dashboard_mine import _now
    return _now().strftime("%Y-%m-%d")


def mine_groups(user: dict) -> list:
    out = []
    can_case = user_has_module(user, "case_manage") or user_has_module(user, "quotation")
    money = has_finance_access(user)
    if not (can_case or money):
        return out
    today = _today()
    with db_conn() as conn:
        frag, fp = row_access.filter_sql("case", user, scope="read")
        base = "SELECT COUNT(*) FROM quotations WHERE 1=1" + frag
        if can_case:
            mine_params = [user["id"], user["display_name"], user["id"]] + [user["username"]] * 3
            def n(extra_sql, extra_params):
                return conn.execute(base + " AND " + extra_sql, fp + extra_params).fetchone()[0]
            active = n(f"{SQL_DEAL_TAG} = '已成案' AND " + _q._CASE_MINE_SQL, mine_params)
            # 與案件清單「全部」頁籤同一個母體（已成案、未結案）⇒ 點進去看到的件數＝首頁寫的件數
            stage = n(f"{SQL_DEAL_TAG} = '已成案' AND " + _q._CASE_STAGE_OVERDUE_SQL + " AND " + _q._CASE_MINE_SQL, [today] + mine_params)
            recv = n(f"{SQL_DEAL_TAG} = '已成案' AND " + _q._CASE_RECV_OVERDUE_SQL + " AND " + _q._CASE_MINE_SQL, [today] + mine_params)
            items = []
            if stage:
                items.append({"title": "有階段已過預定日", "sub": "%d 件案件" % stage, "href": HREF + "?quick=mine,stage_overdue", "tone": "crit"})
            if recv:
                items.append({"title": "有款項已過預計收款日", "sub": "%d 件案件" % recv, "href": HREF + "?quick=mine,recv_overdue", "tone": "crit"})
            out.append({"key": "my_cases", "title": "我的案件", "count": active, "href": HREF + "?quick=mine",
                        "hrefLabel": "看我的案件", "items": items, "kind": "work", "order": 40,
                        "empty": "目前沒有進行中的案件"})
        if money:
            recv_all = conn.execute(base + f" AND {SQL_DEAL_TAG} = '已成案' AND " + _q._CASE_RECV_OVERDUE_SQL, fp + [today]).fetchone()[0]
            items = ([{"title": "款項已過預計收款日", "sub": "%d 件案件" % recv_all, "href": HREF + "?quick=recv_overdue", "tone": "crit"}]
                     if recv_all else [])
            out.append({"key": "receivable_overdue", "title": "應收款項追蹤", "count": recv_all, "href": HREF + "?quick=recv_overdue",
                        "hrefLabel": "去追款", "items": items, "kind": "money", "order": 60,
                        "empty": "沒有逾期未收的款項"})
    return out
