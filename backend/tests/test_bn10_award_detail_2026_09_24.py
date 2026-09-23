"""`BN10` · 點開一張獎金分潤單要有完整詳細內容（精算明細＋拆發明細＋簽核狀態）。

端點：`GET /api/bonus/awards/{id}`（`routers/bonus.py::get_award`）。
驗：
① 一次拿齊三件：`settlement`／`lines`／`signatures`
② `settlement` 是精算**存值原樣帶出**（刻意種一組不符 10%／1% 係數的值；重算就對不上）
③ 可見性與清單同一條規則：非管理者只看到自己那一列、**看不到 `base_amount`**；
   管理者看得到 —— 管理者那一格是對照組，少了它「沒有 base_amount」可能只是欄位根本不存在
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_bonus_award_approval_2026_09_23 import AWARDS, _hdr, _seed_award  # noqa: E402

_SUMMARY = {"quotedPretax": 200000, "quotedTotal": 210000, "itemActualTotal": 90000,
            "extraTotal": 3500, "dispatchTotal": 20000, "totalActualCost": 113500,
            "grossProfit": 86500, "grossMarginPct": 43.3, "adminCost": 12345,
            "charityDonation": 678, "netProfit": 73477, "netMarginPct": 36.7}


def _seed_case(quote_no):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name,"
            " total, pretax, deal_tag, data_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "BN10 客戶", "BN10 案", 0, 0, "已結案",
             json.dumps({"settlement": {"status": "finalized", "summary": _SUMMARY}}),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def test_bn10_the_detail_carries_settlement_lines_and_signatures(client, make_user):
    _seed_case("MQ-BN10-1")
    staff, _ = _hdr(client, make_user, "bn10_staff", role="user")
    _u, sup = _hdr(client, make_user, "bn10_sup")
    aid = _seed_award("MQ-BN10-1", [staff])

    r = client.get("%s/%s" % (AWARDS, aid), headers=sup)
    assert r.status_code == 200, r.text[:200]
    d = r.json()
    for k in ("settlement", "lines", "signatures"):
        assert d.get(k), "明細缺 `%s`（或是空的）：%r" % (k, sorted(d))
    for k, v in _SUMMARY.items():
        assert d["settlement"].get(k) == v, (
            "精算 `%s` 回 %r，存值是 %r —— 明細頁的數字不是精算存值（重算或讀錯來源）。"
            % (k, d["settlement"].get(k), v))
    assert "base_amount" in d, "對照組：管理者應該看得到 base_amount"


def test_bn10_a_non_manager_sees_only_their_line_and_no_base_amount(client, make_user):
    _seed_case("MQ-BN10-2")
    staff, staff_hdr = _hdr(client, make_user, "bn10_me", role="user")
    other, _ = _hdr(client, make_user, "bn10_other", role="user")
    aid = _seed_award("MQ-BN10-2", [staff, other])

    r = client.get("%s/%s" % (AWARDS, aid), headers=staff_hdr)
    assert r.status_code == 200, r.text[:200]
    d = r.json()
    assert {ln["username"] for ln in d["lines"]} == {staff}, (
        "非管理者看到了別人的拆發列：%r" % [ln["username"] for ln in d["lines"]])
    assert "base_amount" not in d, "非管理者看得到 base_amount —— 用明細頁繞過了清單已擋住的東西"
