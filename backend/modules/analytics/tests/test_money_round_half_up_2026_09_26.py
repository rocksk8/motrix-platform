"""自 `tests/test_money_round_half_up_2026_09_26.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
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

# 稽核 ⑰ O-6：只有本模組的題用它，而它 import 營運分析 ⇒ 放在模組這一側（原本在 L1 測試檔，下一個人一呼叫就綁上 M08）
def _patch_entries(monkeypatch, contractor=(), material=(), other=()):
    from modules.case import recognition as rp   # 2026-09-26：M08 經 case.recognition，提供者轉呼叫這裡的函式

    def _mk(rows, **extra):
        return lambda *a, **k: [dict({"date": d, "quoteNo": "", "desc": "x", "amount": amt, "taxNote": "",
                                      "provisional": False}, **extra) for d, amt in rows]
    monkeypatch.setattr(rp, "dispatch_entries", _mk(contractor))
    monkeypatch.setattr(rp, "material_entries", _mk(material))
    monkeypatch.setattr(rp, "extra_entries", _mk(other, files=[], pending=False, category="其他"))


#: 跨 M04×M08 的題（2026-09-26 第六班列車交會：M08 精算快照過期檢查改走 IP-1 dispatch.row，外包工班不在時明說無法檢查）：
#: 同時需要外包工班；外包工班不在時略過（那時精算過期數回 None、報表明說無法檢查，由 M08 搬遷 ⑤ 456130ce 的缺席題負責）。
needs_subcontract = pytest.mark.skipif(not _source_tree.module_installed("modules/subcontract/"),
                                       reason="需要外包工班模組（M04）")


@needs_subcontract
def test_live_dispatch_total_tax_rounds_half_up(client):
    """精算過期比對用的即時派工含稅：10,010 ⇒ 10,010＋501＝10,511（舊：10,510）。reports L130"""
    import db
    from modules.analytics.api.reports import _live_dispatch_totals_by_quote
    _insert_dispatch_row("MQ-VAT-R1", 10010)
    _insert_dispatch_row("MQ-VAT-R2", 10000)
    conn = db.get_db()
    try:
        t = _live_dispatch_totals_by_quote(conn)
    finally:
        conn.close()
    assert (t["MQ-VAT-R1"], t["MQ-VAT-R2"]) == (10511, 10500)


@needs_subcontract
def test_stale_settlement_compare_rounds_half_up(client):
    """精算快照 dispatchTotal 10,510.5（前端加總外包人員 .5）vs 即時 10,511 ⇒ 一致、不算過期
    （舊：round(10,510.5)＝10,510 ≠ 10,511 ⇒ 誤報過期）。reports L481"""
    import db
    from modules.analytics.api.reports import _collect
    now = "2026-01-01T00:00:00"
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name, project_name, total, pretax, data_json, "
            "created_at, updated_at, deal_tag, quote_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("MQ-VAT-S1", "已送出", "客戶", "專案", 105000, 100000,
             json.dumps({"dealTag": "已結案", "settlement": {"status": "finalized", "summary": {
                 "dispatchTotal": 10510.5, "netProfit": 1, "netMarginPct": 1.0}}}),
             now, now, "已結案", "2026-01-05"))
        conn.commit()
    finally:
        conn.close()
    _insert_dispatch_row("MQ-VAT-S1", 10010)
    assert _collect("2026-01-01", "2026-12-31")["summary"]["staleSettlementCount"] == 0


def test_achievement_prorata_rounds_half_up(client):
    """過去年度 frac＝1 ⇒ 目標 1,000,000.5 的應達 ⇒ 1,000,001（舊：1,000,000）。reports L605"""
    from modules.analytics.api.reports import _compute_achievement
    ach = _compute_achievement(2020, {"year": 2020, "annual": {"revenue": 1000000.5, "grossProfit": 3000}}, [])
    assert ach["annual"]["revenue"]["prorata"] == 1000001
    assert ach["annual"]["grossProfit"]["prorata"] == 3000                                # 正對照


def test_expense_report_details_and_monthly_round_half_up(client, monkeypatch):
    """支出結構（reports._collect_expenses）：承攬商 20.5⇒21、叫料 40.5⇒41、料件 30.5⇒31、
    其他 10.5⇒11（舊：20／40／30／10）；月合計 20.5＋40.5＋30.5＋1＝92.5 ⇒ 93（舊：92）。
    reports L3602、L3613、L3645、L3658、L3675～L3677"""
    from modules.analytics.api.reports import _collect_expenses
    _patch_entries(monkeypatch, contractor=[("2019-03-05", 20.5)], material=[("2019-03-06", 40.5)],
                   other=[("2019-03-07", 1)])
    _stock("VAT-P1", 30.5, "2019-03-08T00:00:00")
    ex = _collect_expenses(2019)
    mar = next(m for m in ex["monthly"] if m["month"] == "2019-03")
    assert (mar["contractor"], mar["material"], mar["other"], mar["total"]) == (21, 71, 1, 93)      # 叫料 40.5＋料件 30.5＝71
    assert [d["amount"] for d in ex["details"]["contractor"]] == [21]
    assert sorted(d["amount"] for d in ex["details"]["material"]) == [31, 41]
    _patch_entries(monkeypatch, other=[("2018-04-07", 10.5)])
    ex = _collect_expenses(2018)
    assert [d["amount"] for d in ex["details"]["other"]] == [11]
    assert next(m for m in ex["monthly"] if m["month"] == "2018-04")["other"] == 11
    # 月合計的設備／料件欄（L3675 equipment、L3676 material）：設備 50.5⇒51、叫料 60.5⇒61（舊：50／60）
    _patch_entries(monkeypatch, material=[("2017-05-06", 60.5)])
    _stock("VAT-E1", 50.5, "2017-05-08T00:00:00", category="交換器")
    may = next(m for m in _collect_expenses(2017)["monthly"] if m["month"] == "2017-05")
    assert (may["equipment"], may["material"]) == (51, 61)
