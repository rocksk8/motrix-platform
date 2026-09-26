"""2026-08-28（後續）營運報表邏輯稽核發現的 3 個修正：
①精算快照過期警訊（staleSettlementCount／summary 全域計數）
②已成案缺收款期別會靜默消失於金額類統計（casesWithoutPaymentItems）
③年度目標達成率（_compute_achievement）改用 wonMonth 而非直接 quoteDate，
  跟 monthly_trend() 已經修過的 quote_won_month_map() 邏輯一致。"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _insert_dispatch(quote_no, total_amount):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, "
            "total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (quote_no, "2026-01-01", "amount", "[]", total_amount, "completed",
             "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_case(quote_no, quote_date="2026-01-05", deal_tag="已成案",
                  payment_items=None, settlement=None, total=100000):
    import db
    conn = db.get_db()
    try:
        data = {"dealTag": deal_tag}
        if payment_items is not None:
            data["caseRecord"] = {"payment": {"items": payment_items}}
        if settlement is not None:
            data["settlement"] = settlement
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, "
            "data_json, created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "測試客戶", "測試專案", total, round(total / 1.05),
             json.dumps(data, ensure_ascii=False), "2026-01-01T00:00:00", "2026-01-01T00:00:00",
             deal_tag, quote_date),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_won_audit_event(quote_no, at_iso):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO audit_log (at, action, target_type, target_id, target_label, detail) "
            "VALUES (?,?,?,?,?,?)",
            (at_iso, "deal_tag.change", "quotation", quote_no, quote_no,
             json.dumps({"to": "已成案"}, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


# ── ①精算快照過期全域計數 ─────────────────────────────────────────────────────

def test_stale_settlement_count_detects_mismatch(client, make_user):
    from modules.analytics.api.reports import _collect
    _insert_case(
        "MQ-STALE-001", deal_tag="已結案",
        settlement={"status": "finalized", "summary": {
            "dispatchTotal": 40000, "netProfit": 100000, "netMarginPct": 50.0,
        }},
    )
    _insert_dispatch("MQ-STALE-001", total_amount=45000)  # 含稅後 47250，跟快照 40000 對不上

    data = _collect("2026-01-01", "2026-12-31")
    assert data["summary"]["staleSettlementCount"] == 1


def test_stale_settlement_count_zero_when_matching(client, make_user):
    from modules.analytics.api.reports import _collect
    # 快照跟即時值一致（無承攬商派發，dispatchTotal=0）
    _insert_case(
        "MQ-STALE-002", deal_tag="已結案",
        settlement={"status": "finalized", "summary": {
            "dispatchTotal": 0, "netProfit": 100000, "netMarginPct": 50.0,
        }},
    )
    data = _collect("2026-01-01", "2026-12-31")
    assert data["summary"]["staleSettlementCount"] == 0


# ── ②已成案缺收款期別 ────────────────────────────────────────────────────────

def test_missing_payment_items_listed_and_excluded_from_money_totals(client, make_user):
    from modules.analytics.api.reports import _collect
    _insert_case("MQ-NOPAY-001", payment_items=None, total=500000)  # 完全沒有 caseRecord
    _insert_case("MQ-NOPAY-002", payment_items=[
        {"type": "全額", "amount": 100000, "received": False},
    ], total=100000)

    data = _collect("2026-01-01", "2026-12-31")
    assert data["summary"]["missingPaymentItemsCount"] == 1
    missing_nos = {c["quoteNo"] for c in data["casesWithoutPaymentItems"]}
    assert "MQ-NOPAY-001" in missing_nos
    assert "MQ-NOPAY-002" not in missing_nos
    # 案件數量統計仍算得到，但金額類統計（totalReceivable）不含這筆
    quote_nos_all = {c["quoteNo"] for c in data["casesAll"]}
    assert "MQ-NOPAY-001" in quote_nos_all
    assert data["summary"]["totalReceivable"] == 100000  # 只有 NOPAY-002 那 10 萬進了 all_items


# ── ③年度目標達成率改用 wonMonth ────────────────────────────────────────────

def test_achievement_includes_case_with_missing_quote_date_via_audit_fallback(client, make_user):
    from modules.analytics.api.reports import _collect, _compute_achievement
    _insert_case("MQ-WON-001", quote_date="", total=200000)
    _insert_won_audit_event("MQ-WON-001", "2026-03-15T10:00:00")

    data = _collect("2026-01-01", "2026-12-31")
    targets = {"year": 2026, "annual": {"revenue": 1000000}}
    ach = _compute_achievement(2026, targets, data["casesAll"])
    assert ach["hasTargets"] is True
    assert ach["annual"]["revenue"]["actual"] == 200000  # 靠 audit_log fallback 才算得到


def test_achievement_reattributes_future_dated_quote_via_audit_fallback(client, make_user):
    """quote_date 誤填成未來日期（例如業務員手誤）時，quote_won_month_map() 會
    退回用 audit_log 實際成案時間戳，不該把這筆案子的業績算進 quote_date 那個
    （通常還沒到）的未來年度。"""
    from modules.analytics.api.reports import _collect, _compute_achievement
    _insert_case("MQ-WON-002", quote_date="2099-01-01", total=300000)
    _insert_won_audit_event("MQ-WON-002", "2026-02-10T00:00:00")

    data = _collect("2026-01-01", "2026-12-31")
    targets_2026 = {"year": 2026, "annual": {"revenue": 1000000}}
    ach_2026 = _compute_achievement(2026, targets_2026, data["casesAll"])
    assert ach_2026["annual"]["revenue"]["actual"] == 300000

    targets_2099 = {"year": 2099, "annual": {"revenue": 1000000}}
    ach_2099 = _compute_achievement(2099, targets_2099, data["casesAll"])
    assert ach_2099["annual"]["revenue"]["actual"] == 0
