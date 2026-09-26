"""需要應收應付（M05）的題：銀行對帳 POST /api/reports/bank-reconcile 已收回 M05（刪掉 modules/arap 時隨模組消失，PLAYBOOK §B-11）。

（2026-09-26 自 modules/analytics/tests/test_money_round_half_up_2026_09_26.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
自 `tests/test_money_round_half_up_2026_09_26.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。
"""
import json
import pathlib
import shutil
import subprocess
from datetime import datetime
import pytest
from tests.test_money_round_half_up_2026_09_26 import (  # noqa: E402,F401  含 fixture
    _hdr,
    _insert_dispatch_row,
    _stock,
)

from core import source_tree as _source_tree

#: 跨 M04×M08 的題（2026-09-26 第六班列車交會：M08 精算快照過期檢查改走 IP-1 dispatch.row，外包工班不在時明說無法檢查）：
#: 同時需要外包工班；外包工班不在時略過（那時精算過期數回 None、報表明說無法檢查，由 M08 搬遷 ⑤ 456130ce 的缺席題負責）。
needs_subcontract = pytest.mark.skipif(not _source_tree.module_installed("modules/subcontract/"),
                                       reason="需要外包工班模組（M04）")


def test_bank_reconcile_matches_amounts_rounded_half_up(client, make_user):
    """匯款申請含稅 10,500.5 ↔ 銀行 10,501；匯款申請 20,001 ↔ 銀行 20,000.5 ⇒ 兩筆都配對
    （舊：10,500.5⇒10,500、20,000.5⇒20,000，都配不上）。reports L2825（申請金額）、L2830（銀行金額）"""
    import db
    h = _hdr(client, make_user)
    conn = db.get_db()
    try:
        for i, gt in enumerate((10500.5, 20001), 1):
            conn.execute("INSERT INTO contractor_dispatches (quote_no, dispatch_date, scope, items_json, "
                         "total_amount, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                         ("MQ-VAT-B%d" % i, "2026-01-01", "amount", "[]", 0, "completed", "x", "x"))
            did = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("INSERT INTO contractor_payment_vouchers (voucher_no, dispatch_id, quote_no, status, "
                         "snapshot_json, is_paid) VALUES (?,?,?,?,?,0)",
                         ("CV-VAT-%d" % i, did, "MQ-VAT-B%d" % i, "已核准",
                          json.dumps({"grandTotal": gt, "vendorName": "廠商"})))
        conn.commit()
    finally:
        conn.close()
    csv_bytes = "日期,金額,摘要\n2026-01-02,10501,甲\n2026-01-02,20000.5,乙\n2026-01-02,777,正對照\n".encode("utf-8")
    r = client.post("/api/reports/bank-reconcile", headers=h, files={"file": ("b.csv", csv_bytes, "text/csv")})
    assert r.status_code == 200, r.text
    got = {row["amount"]: (row["match"] or {}).get("voucherNo") for row in r.json()["bankRows"]}
    assert got == {10501.0: "CV-VAT-1", 20000.5: "CV-VAT-2", 777.0: None}
