# -*- coding: utf-8 -*-
"""T71：報價單列表對補登單的作廢入口（靜態＋HTTP）。畫面行為由瀏覽器實測另行驗證。"""
import os
import re

HTML = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "pages", "quotations.html")


def _src():
    return open(HTML, encoding="utf-8").read()


def test_void_button_only_for_superadmin_on_historical_rows():
    s = _src()
    assert "q.historical === true && session.role === 'superadmin'" in s
    # 一般草稿刪除條件原樣保留
    assert "canDelete && (q.status === '草稿' ||" in s


def test_void_sends_reason_query_and_ordinary_delete_does_not():
    s = _src()
    assert "'?reason=' + encodeURIComponent(reason)" in s
    assert re.search(r"await this\._doDelete\(quoteNo, ''\)", s)          # 一般刪除不帶 reason
    assert "reason.length < 5" in s                                       # 前端先擋 <5 字
    # 補登作廢走頁內視窗，不用 confirm()/prompt()
    seg = s[s.index("async submitVoid()"):s.index("async _doDelete")]
    assert "confirm(" not in seg and "prompt(" not in seg


def test_http_void_requires_reason_and_superadmin_contract_unchanged():
    # 後端契約已由 test_quote_backfill_t71／L1 測試鎖定；這裡只確認端點仍接受 ?reason=
    import inspect
    from modules.case.api import quotations as m
    assert "reason" in inspect.signature(m.delete_quotation).parameters
