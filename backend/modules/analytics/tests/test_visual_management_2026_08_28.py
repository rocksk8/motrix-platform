"""自 `tests/test_visual_management_2026_08_28.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import json
from datetime import datetime
from tests.test_visual_management_2026_08_28 import (  # noqa: E402,F401  含 fixture
    _auth,
    _insert_case_with_stage,
    _login,
    _make_dept_setup,
)
import pytest

from core import source_tree as _source_tree

#: 跨 M04×M08 的題（2026-09-26 第六班列車交會：外包工班與營運分析兩邊都把它搬進自己的 tests/，只留這一份）：
#: 同時需要外包工班；外包工班不在時略過——那時的行為（報表明說少了派工）由 test_reports_dispatch_row_consumer 負責。
needs_subcontract = pytest.mark.skipif(not _source_tree.module_installed("modules/subcontract/"),
                                       reason="需要外包工班模組（M04）")



@needs_subcontract
def test_expenses_monthly_filters_contractor_and_material_by_department(client, make_user):
    admin_user, admin_pw = make_user(role="admin")
    token = _login(client, admin_user, admin_pw)
    dept_a, dept_b, sales_a, sales_b = _make_dept_setup(make_user)
    _insert_case_with_stage("MQ-EXP-A01", sales_a)
    _insert_case_with_stage("MQ-EXP-B01", sales_b)

    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, total_amount, "
            "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("MQ-EXP-A01", "2026-03-10", "amount", "[]", 10000, "completed",
             "2026-03-10T00:00:00", "2026-03-10T00:00:00"),
        )
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, total_amount, "
            "status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("MQ-EXP-B01", "2026-03-11", "amount", "[]", 20000, "completed",
             "2026-03-11T00:00:00", "2026-03-11T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    r_all = client.get("/api/reports/expenses-monthly?year=2026", headers=_auth(token))
    assert r_all.status_code == 200, r_all.text
    march_all = next(m for m in r_all.json()["expenses"]["monthly"] if m["month"] == "2026-03")
    # 2026-09-24 AC2：預設權責口徑＝承攬商未稅（原本含稅 ×1.05）；本題驗的是部門篩選
    assert march_all["contractor"] == 10000 + 20000

    r_a = client.get(f"/api/reports/expenses-monthly?year=2026&department_id={dept_a}", headers=_auth(token))
    assert r_a.status_code == 200, r_a.text
    march_a = next(m for m in r_a.json()["expenses"]["monthly"] if m["month"] == "2026-03")
    assert march_a["contractor"] == 10000
