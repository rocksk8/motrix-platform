"""額外支出正規化 migration（v75）——搬移、回填、可重跑。

規格見 `MOTRIX-ERP-QUICK.md` §5.10。這支 migration 會**搬資料**不只是建表，
所以測試重點不是「表有沒有建起來」，是「既有資料有沒有正確搬過去、有沒有搬兩次、
推定的填寫人有沒有被誠實標記」。
"""
import json

import pytest


def _seed(conn, quote_no, extra_items, *, finalized_by="", sales_person="", status="draft"):
    settlement = {"status": status, "extraItems": extra_items}
    if finalized_by:
        settlement["finalizedBy"] = finalized_by
    conn.execute(
        "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
        "data_json, created_at, updated_at, deal_tag, sales_person) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (quote_no, "已送出", "測客", "測專", 100000, 95238,
         json.dumps({"settlement": settlement}, ensure_ascii=False),
         "2026-01-01T00:00:00", "2026-01-01T00:00:00", "已成案", sales_person),
    )


def _run_m075(conn):
    import db
    db._m075_case_extra_expenses(conn)
    conn.commit()


def _rows(conn, quote_no):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM case_extra_expenses WHERE quote_no=? ORDER BY id", (quote_no,))]


@pytest.fixture()
def conn(client):
    """`client` 已把 db 導到隔離路徑；這裡直接拿連線來測 migration 本身。

    注意：migration 在建 db 時就已經跑過一次了（CURRENT_VERSION=75），所以
    測試裡的 `_run_m075()` 是「再跑一次」——正好也驗證了可重跑這件事。"""
    import db
    c = db.get_db()
    try:
        yield c
    finally:
        c.close()


def test_moves_items_into_table(conn):
    _seed(conn, "MQ-EX-001", [
        {"category": "差旅", "description": "台北出差", "qty": 2, "unit": "天",
         "unitCost": 1500, "totalCost": 3000, "note": "高鐵",
         "expenseDate": "2026-08-05", "docNo": "R-001", "files": [{"id": "f1"}],
         "createdDate": "2026-08-06", "createdBy": "jeff"},
    ])
    conn.commit()
    _run_m075(conn)

    rows = _rows(conn, "MQ-EX-001")
    assert len(rows) == 1
    r = rows[0]
    assert r["category"] == "差旅"
    assert r["description"] == "台北出差"
    assert r["qty"] == 2 and r["unit"] == "天"
    assert r["unit_cost"] == 1500 and r["total_cost"] == 3000
    assert r["note"] == "高鐵"
    assert r["expense_date"] == "2026-08-05"
    assert r["doc_no"] == "R-001"
    assert json.loads(r["files_json"]) == [{"id": "f1"}]
    assert r["created_at"] == "2026-08-06"


def test_existing_rows_are_marked_approved_not_pending(conn):
    """搬過來的一律「已核准」——標成待審核會讓既有案件突然冒出一堆待簽核，
    而且在核准前金額會從成本裡消失，是憑空製造的混亂。"""
    _seed(conn, "MQ-EX-002", [{"totalCost": 500, "description": "雜支"}])
    conn.commit()
    _run_m075(conn)

    r = _rows(conn, "MQ-EX-002")[0]
    assert r["status"] == "已核准"
    assert json.loads(r["approval_json"])["migrated"] is True


def test_real_created_by_is_kept_and_not_marked_inferred(conn):
    _seed(conn, "MQ-EX-003", [{"totalCost": 100, "createdBy": "queena"}],
          finalized_by="corbin", sales_person="kyle")
    conn.commit()
    _run_m075(conn)

    r = _rows(conn, "MQ-EX-003")[0]
    assert r["created_by_name"] == "queena", "有真實紀錄時不該被推定值蓋掉"
    assert r["created_by_inferred"] == 0


def test_missing_created_by_falls_back_to_finalized_by_and_is_flagged(conn):
    """既有資料的 createdBy 幾乎都是空的（前端取錯 session 路徑），
    使用者要求回填——但推定值必須標記出來，不能當成事實。"""
    _seed(conn, "MQ-EX-004", [{"totalCost": 100}], finalized_by="corbin", sales_person="kyle")
    conn.commit()
    _run_m075(conn)

    r = _rows(conn, "MQ-EX-004")[0]
    assert r["created_by_name"] == "corbin", "應優先用精算完結人"
    assert r["created_by_inferred"] == 1, "推定的一定要標記"
    assert r["created_by"] == "", "推定值不該偽造成 username"


def test_falls_back_to_sales_person_when_no_finalizer(conn):
    _seed(conn, "MQ-EX-005", [{"totalCost": 100}], sales_person="kyle")
    conn.commit()
    _run_m075(conn)

    r = _rows(conn, "MQ-EX-005")[0]
    assert r["created_by_name"] == "kyle"
    assert r["created_by_inferred"] == 1


def test_no_signal_at_all_leaves_blank_not_guessed(conn):
    """完全沒有線索時留空，不要硬編一個「系統」之類的假名字。"""
    _seed(conn, "MQ-EX-006", [{"totalCost": 100}])
    conn.commit()
    _run_m075(conn)

    r = _rows(conn, "MQ-EX-006")[0]
    assert r["created_by_name"] == ""
    assert r["created_by_inferred"] == 0


def test_rerun_does_not_duplicate(conn):
    """migration 必須可重跑——apply_update.ps1 的乾跑驗證會再跑一次。"""
    _seed(conn, "MQ-EX-007", [{"totalCost": 100}, {"totalCost": 200}])
    conn.commit()
    _run_m075(conn)
    first = len(_rows(conn, "MQ-EX-007"))
    _run_m075(conn)
    _run_m075(conn)
    assert len(_rows(conn, "MQ-EX-007")) == first == 2


def test_original_array_is_kept_as_readonly_backup(conn):
    """刻意不刪 data_json 裡的原陣列：新表出問題時還救得回來。"""
    _seed(conn, "MQ-EX-008", [{"totalCost": 777, "description": "保留測試"}])
    conn.commit()
    _run_m075(conn)

    row = conn.execute("SELECT data_json FROM quotations WHERE quote_no='MQ-EX-008'").fetchone()
    items = json.loads(row["data_json"])["settlement"]["extraItems"]
    assert len(items) == 1 and items[0]["totalCost"] == 777


def test_backfills_month_from_edit_history_so_money_does_not_vanish(conn):
    """兩個日期都空白時，要退回 editHistory 的精算存檔時間——**這一條是錢的問題**。

    舊的 `settlement_extra_expenses()` 歸月有四層 fallback，最後兩層來自 editHistory
    （精算完結時間／最後存檔時間）。實測開發機的 7 筆既有資料裡**有 6 筆 expenseDate
    與 createdDate 都是空的**，完全靠那兩層歸月。搬移時若不把這層一起搬過來，
    那 6 筆（共 7,990 元）會直接從月支出報表消失，而且不會有任何錯誤——正是
    2026-09-09 修過的那一類問題（當月花掉的錢在報表上憑空不見）。
    """
    _seed(conn, "MQ-EX-009", [{"totalCost": 8000, "description": "沒有任何日期"}])
    conn.execute(
        "UPDATE quotations SET data_json=json_set(data_json,'$.editHistory',json(?)) WHERE quote_no=?",
        (json.dumps([{"type": "settlement_draft", "at": "2026-08-20T09:00:00"}]), "MQ-EX-009"),
    )
    conn.commit()
    _run_m075(conn)

    r = _rows(conn, "MQ-EX-009")[0]
    assert r["created_at"] == "2026-08-20", f"應退回 editHistory 的存檔時間，實際 {r['created_at']!r}"


def test_finalized_time_wins_over_draft_time(conn):
    """兩種 editHistory 都有時，用精算完結時間（比較準）。"""
    _seed(conn, "MQ-EX-010", [{"totalCost": 500}])
    conn.execute(
        "UPDATE quotations SET data_json=json_set(data_json,'$.editHistory',json(?)) WHERE quote_no=?",
        (json.dumps([
            {"type": "settlement_draft", "at": "2026-07-01T09:00:00"},
            {"type": "settlement_finalized", "at": "2026-09-02T18:00:00"},
        ]), "MQ-EX-010"),
    )
    conn.commit()
    _run_m075(conn)

    assert _rows(conn, "MQ-EX-010")[0]["created_at"] == "2026-09-02"
