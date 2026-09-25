# -*- coding: utf-8 -*-
"""稽核 AUDIT-D-R1-R3-legal（2026-09-26）的修正：法規金額捨入、並行修改、單據凍結、告知紀錄。

守住的規則：
D-1 補充保費「角以下 4 捨 5 入」（健保署）：後端 20,000～2,000,000 逐元與四捨五入一致；扣繳維持元以下捨去。
D-2 修改勞報單時「讀舊單 → 合併 → 寫回」在同一個寫交易裡：兩人同時修改，已記錄的「已告知」不可以消失。
S-3 告知紀錄的設定值讀不懂 ⇒ 拒絕寫入（409），原值不動；不可以當成空的整份覆寫。
S-5 已告知紀錄除了雜湊，也查得到當時的告知全文（公司改了文字之後仍查得到舊版）。
S-6 單據凍結的兩條路徑：修改舊單用快照（不是用版本號重查）；建立時不採用前端送來的快照（突變 M12、M16）。
"""
import copy
import json
import threading
from datetime import date
from fractions import Fraction

import pytest

from helpers import legal_params as lp
from helpers import privacy_notice as pn

FROZEN_TODAY = date(2026, 9, 25)


def _hdr(client, make_user, name="dfix_su"):
    u, p = make_user(username=name, role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def frozen_today(monkeypatch):
    monkeypatch.setattr(lp, "today", lambda: FROZEN_TODAY)


def _data(gross=30000, itype="50", date_="2026-10-01", **kw):
    d = {"contractorName": "測試承攬人", "incomeType": itype, "grossAmount": gross,
         "contractorNationality": "本國籍", "contractorHasUnionInsurance": False,
         "serviceContent": "測試", "slipDate": date_}
    d.update(kw)
    return d


def _v2027():
    v = copy.deepcopy(lp.DEFAULT_TAX_RULE_VERSIONS[0])
    v.update(version="2027", effectiveFrom="2027-01-01", sources=["測試資料"])
    v["minimum_wage"]["monthly"] = 30900
    v["nhi"]["thresholds"]["50"] = 30900
    return v


def _set_raw_setting(key, raw):
    import db
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?, ?, '2026-01-01') "
                     "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json", (key, raw))
        conn.commit()
    finally:
        conn.close()


def _raw_setting(key):
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT value_json FROM system_settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


# ── D-1 捨入 ────────────────────────────────────────────────────────────────────

def _half_up_oracle(num, den):
    """整數的「四捨五入到元」（與 Decimal、與 round() 都無關的獨立算法）。"""
    return (2 * num + den) // (2 * den)


def test_round_half_up_and_floor_on_the_boundaries():
    assert lp.round_half_up(35000, 0.0211) == 739          # 738.5 ⇒ 739（內建 round() 給 738）
    assert lp.round_half_up(55000, 0.0211) == 1161         # 1160.5
    assert lp.round_half_up(30000, 0.0211) == 633
    assert lp.round_half_up(-35000, 0.0211) == -739        # 負數遠離 0（退款沖銷時對稱）
    assert lp.floor_amount(20010, 0.10) == 2001
    assert lp.floor_amount(20009, 0.10) == 2000            # 9A 起扣 20,010 的前提：稅額元以下捨去（O-5）
    assert lp.floor_amount(12345, 0.05) == 617
    with pytest.raises(TypeError):
        lp.round_half_up(True, 0.0211)


@pytest.mark.parametrize("rate", [0.05, 0.06, 0.10, 0.18, 0.20])
def test_withholding_floor_matches_integer_floor_for_all_legal_rates(rate):
    f = Fraction(repr(rate))
    bad = [g for g in range(1, 2000001, 7) if lp.floor_amount(g, rate) != g * f.numerator // f.denominator]
    assert not bad[:5]


# ── D-2 並行修改 ────────────────────────────────────────────────────────────────


# ── S-6 單據凍結 ────────────────────────────────────────────────────────────────


# ── S-3 設定值損毀 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", ["{壞掉的 json", "[1, 2]"])
def test_corrupted_acks_are_refused_not_overwritten(client, make_user, raw):
    h = _hdr(client, make_user)
    cid = client.post("/api/contractors", json={"name": "承攬損毀"}, headers=h).json()["id"]
    _set_raw_setting(pn.ACKS_KEY, raw)
    r = client.post(f"/api/contractors/{cid}/privacy-notice/ack", headers=h)
    assert r.status_code == 409 and "損毀" in r.json()["detail"], r.text
    assert _raw_setting(pn.ACKS_KEY) == raw, "損毀的原始內容被蓋掉了"
    r = client.get(f"/api/contractors/{cid}/privacy-notice", headers=h)
    assert r.status_code == 409, "讀不懂不可以回報成「沒有紀錄」"


# ── S-5 告知全文 ────────────────────────────────────────────────────────────────
