# -*- coding: utf-8 -*-
"""手動量測（不是測試，檔名不符 test_*.py 所以一般不會被收集）：/api/dashboard/stats 在 N 筆報價單下的耗時。

用法（需要 MOTRIX_BENCH=1；一次只跑一個大工作、-n 0）：
    MOTRIX_BENCH=1 MOTRIX_BENCH_ROWS=20000 python -m pytest modules/analytics/tests/bench_dashboard_stats.py -s -n 0 \
        -p no:cacheprovider --basetemp=%TEMP%\motrix-pytest-bench
修整前後各跑一次（git stash／checkout dashboard.py），比較中位數。資料全是假的、寫在測試暫存庫，跑完刪 basetemp。

資料分布（貼近正式機的粗略比例）：約 40% 草稿、15% 待審核／簽核中（帶核准流程 JSON）、15% 已送出、
30% 已成案／已結案（帶 caseRecord：付款、設備；其中一半帶精算 JSON）。
"""
import json
import os
import statistics
import time

import pytest

ROWS = int(os.environ.get("MOTRIX_BENCH_ROWS", "20000"))
RUNS = int(os.environ.get("MOTRIX_BENCH_RUNS", "7"))

pytestmark = pytest.mark.skipif(os.environ.get("MOTRIX_BENCH") != "1", reason="手動量測：設 MOTRIX_BENCH=1")


def _fake_rows(n):
    appr = {"requestedBy": "x", "requestedByDisplay": "申請人", "reasons": ["毛利低"], "currentTier": 0,
            "tiers": [{"approvers": [{"username": "bench_sales", "status": "pending"}]}]}
    cr = {"payment": {"items": [{"type": "訂金", "pct": 30, "received": True, "receivedAt": "2026-03-01", "actualAmount": 31500},
                                {"type": "尾款", "pct": 70, "received": False}]},
          "devices": [{"name": "設備", "sn": "S", "warrantyStart": "2020-01-01", "warrantyMonths": 12}],
          "notes": "x" * 2000}                                    # 真實 caseRecord 不小：備註、材料申請、派發…
    fin = {"status": "finalized", "summary": {"netProfit": 1000, "netMarginPct": 10.0, "quotedPretax": 10000, "profitDiff": 1,
                                              "items": ["y" * 3000]}}
    for i in range(n):
        k = i % 20
        if k < 8:
            status, tag, data = "草稿", "", {}
        elif k < 11:
            status, tag, data = ("待審核" if k == 8 else "簽核中"), "", {"approval": appr}
        elif k < 14:
            status, tag, data = "已送出", "", {}
        else:
            status, tag = "已送出", ("已成案" if k < 17 else "已結案")
            data = {"dealTag": tag, "caseRecord": dict(cr, ref=i)}
            if k % 2:
                data["settlement"] = fin
        yield (f"BN-{i:06d}", status, f"客戶{i % 500}", f"專案{i}", 105000, 100000, json.dumps(data, ensure_ascii=False),
               "2026-01-01T00:00:00", "2026-01-01T00:00:00", tag, "2026-02-03", 20.0)


def test_bench_dashboard_stats(client, make_user):
    import db
    u, p = make_user("bench_admin", role="superadmin")
    conn = db.get_db()
    try:
        conn.executemany(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, created_at, "
            "updated_at, deal_tag, quote_date, net_margin_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", _fake_rows(ROWS))
        conn.commit()
    finally:
        conn.close()
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    assert client.get("/api/dashboard/stats", headers=h).status_code == 200            # 暖機
    ts = []
    for _ in range(RUNS):
        t0 = time.perf_counter()
        r = client.get("/api/dashboard/stats", headers=h)
        ts.append(time.perf_counter() - t0)
        assert r.status_code == 200
    print("\nBENCH dashboard/stats rows=%d runs=%d  median=%.3fs  min=%.3fs  max=%.3fs  totalQuotes=%d" % (
        ROWS, RUNS, statistics.median(ts), min(ts), max(ts), r.json()["totalQuotes"]))
