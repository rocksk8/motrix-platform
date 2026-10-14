# -*- coding: utf-8 -*-
"""S-ST2 階段樣板的兩條寫入類路由的金標案例（旗標『開』的狀態）。
旗標『關』（404、什麼都不寫）由 tests/platform/test_stage_apply_t63.py 的 test_flag_off_is_404_and_writes_nothing 守——
同一條路由在 CASES 裡只能有一個鍵，所以金標記的是有資料的那一邊。
setup(conn) 直接用設定引擎發布旗標（SR.publish，與設定中心同一個寫入口）並發布一份樣板定義，案件另外插一列（沒有任何階段）。"""

_TPL = {"version": 1, "label": "金標樣板", "stages": [
    {"key": "survey", "label": "現場勘查", "offsetDays": 0, "durationDays": 3, "ratioBp": 0, "dependsOn": []},
    {"key": "install", "label": "設備安裝", "offsetDays": 3, "durationDays": 14, "ratioBp": 7000, "dependsOn": ["survey"]},
    {"key": "accept", "label": "驗收", "offsetDays": 17, "durationDays": 2, "ratioBp": 3000, "dependsOn": ["install"]}]}
_QNO = "MQ-WG-ST1"


def _flags_and_template(conn):
    from core import definitions as D
    from helpers import settings_registry as SR
    from helpers import stage_templates as ST
    SR.publish("builder_governance", {"enabled": 1}, user="golden", reason="golden", conn=conn)
    SR.publish(ST.GROUP, {ST.FIELD: 1}, user="golden", reason="golden", conn=conn)
    SR.invalidate()
    assert ST.enabled(conn), "金標前置：旗標沒有打開"
    ST.ensure_kind()
    if D.get(conn, ST.KIND, "wg_std", "company") is None:
        D.save_draft(conn, ST.KIND, "wg_std", "company", _TPL, user="golden")
        D.publish(conn, ST.KIND, "wg_std", "company", note="golden", user="golden")


def _setup_preview(conn):
    _flags_and_template(conn)


def _setup_apply(conn):
    _flags_and_template(conn)
    if not conn.execute("SELECT 1 FROM quotations WHERE quote_no=?", (_QNO,)).fetchone():
        conn.execute("INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, updated_at, deal_tag) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?)",
                     (_QNO, "已送出", "金標客戶", "金標工程", 1000, 952, "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案"))


CASES = [
    {"key": "POST /api/quotations/stage-templates/preview", "url": "/api/quotations/stage-templates/preview",
     "body": {"key": "wg_std", "template": _TPL, "baseDate": "2026-10-01"}, "setup": _setup_preview},
    {"key": "POST /api/quotations/{quote_no}/stages/apply-template", "url": "/api/quotations/%s/stages/apply-template" % _QNO,
     "body": {"template": "wg_std", "mode": "new", "baseDate": "2026-10-01"}, "setup": _setup_apply},
]
WAIVE = {}
