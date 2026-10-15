# -*- coding: utf-8 -*-
"""T66 L2 清單檢視偏好的兩條寫入類路由金標案例（旗標『開』的狀態）：PUT（存每頁筆數）與 DELETE（回公司預設）。
旗標『關』（404、什麼都不寫）由 tests/platform/test_list_view_prefs_t66.py 守——同一條路由在 CASES 裡只能有一個鍵，所以金標記的是有資料的那一邊。
setup(conn) 直接用設定引擎發布旗標（SR.publish，與設定中心同一個寫入口）。DELETE 排在最後執行（執行器的順序），此時 PUT 已存過一筆。"""
_LIST = "supply:suppliers"


def _setup(conn):
    from helpers import list_view_prefs as LV
    from helpers import settings_registry as SR
    SR.publish("builder_governance", {"enabled": 1}, user="golden", reason="golden", conn=conn)
    SR.publish("list_prefs", {"enabled": 1}, user="golden", reason="golden", conn=conn)
    SR.invalidate()
    assert LV.enabled(conn), "金標前置：旗標沒有打開"


CASES = [
    {"key": "PUT /api/list-views/{list_id}", "url": "/api/list-views/%s" % _LIST, "body": {"pageSize": 20}, "setup": _setup},
    {"key": "DELETE /api/list-views/{list_id}", "url": "/api/list-views/%s" % _LIST, "setup": _setup},
]
WAIVE = {}
