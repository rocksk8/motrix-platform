# -*- coding: utf-8 -*-
"""稽核 D R1～R3：勞報單的捨入、並行修改、個資告知紀錄（需要本模組）。

（2026-09-26 自 tests/test_legal_audit_d_r1_r3_2026_09_26.py 拆出：這幾題需要本模組在，隨模組搬走。原檔的說明：）
稽核 AUDIT-D-R1-R3-legal（2026-09-26）的修正：法規金額捨入、並行修改、單據凍結、告知紀錄。

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


def test_nhi_supplement_matches_half_up_for_every_amount_from_20000_to_2000000():
    """全域掃描（稽核 D-1）：後端勞報單計算 vs 四捨五入，逐元比對；扣繳 vs 元以下捨去。
    正對照：同一個範圍內，內建 round() 與四捨五入不同的金額要恰好是稽核數到的 99 個（題目看得到差異）。"""
    from modules.payroll.api.payslips import _calc
    rules = lp.DEFAULT_TAX_RULE_VERSIONS[0]
    nhi = Fraction(repr(rules["nhi"]["rate"]))
    tax = Fraction(repr(rules["resident"]["9A"]["tax_rate"]))
    th_tax = rules["resident"]["9A"]["tax_threshold"]
    bad, banker_diff = [], 0
    for g in range(20000, 2000001):
        want_nhi = _half_up_oracle(g * nhi.numerator, nhi.denominator)
        want_tax = (g * tax.numerator) // tax.denominator if g >= th_tax else 0
        got = _calc(g, "9A", "本國籍", False, rules)
        if got["nhiSupplement"] != want_nhi or got["taxWithheld"] != want_tax:
            bad.append((g, got["nhiSupplement"], want_nhi, got["taxWithheld"], want_tax))
            if len(bad) > 20:
                break
        if round(g * float(nhi)) != want_nhi:
            banker_diff += 1
    assert not bad, "後端與四捨五入／捨去不一致（金額, 補充保費, 應為, 扣繳, 應為）：%s" % bad[:20]
    assert banker_diff == 99, "正對照：內建 round() 在這個範圍應該有 99 個金額不同，實得 %d" % banker_diff


def test_api_stores_739_for_35000(client, make_user):
    h = _hdr(client, make_user)
    r = client.post("/api/payslips", json={"data": _data(35000, "9A", "2026-10-01")}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["calc"]["nhiSupplement"] == 739
    row = client.get("/api/payslips/" + r.json()["slip_no"], headers=h).json()
    assert row["nhi_supplement"] == 739 and row["net_amount"] == 35000 - 3500 - 739


# ── D-2 並行修改 ────────────────────────────────────────────────────────────────

def test_concurrent_edits_do_not_clear_a_recorded_ack(client, make_user, monkeypatch):
    """A 修改（沒勾已告知）讀完舊單後停在計算；B 同時勾「已告知」。放行 A 之後，紀錄不可以消失。
    修好：A 拿著寫鎖，B 等 A 寫完才讀（讀到 A 的結果再加上紀錄）。
    交易外讀（突變）：B 先寫完紀錄，A 用自己讀到的舊單整包蓋回 ⇒ 紀錄被清掉。"""
    from modules.payroll.api import payslips as ps
    h = _hdr(client, make_user)
    no = client.post("/api/payslips", json={"data": _data()}, headers=h).json()["slip_no"]

    real_calc = ps._calc
    paused, release = threading.Event(), threading.Event()

    def slow_calc(*a, **k):
        if threading.current_thread().name == "editor-A":
            paused.set()
            release.wait(15)
        return real_calc(*a, **k)

    monkeypatch.setattr(ps, "_calc", slow_calc)
    errors = []

    def edit(ack):
        try:
            ps.update_payslip(no, ps.PayslipIn(data=_data(remarks="A" if not ack else "B",
                                                           **({"privacyNoticeAcked": True} if ack else {}))),
                              authorization=h["Authorization"])
        except Exception as e:          # noqa: BLE001
            errors.append(e)

    a = threading.Thread(target=edit, args=(False,), name="editor-A")
    a.start()
    try:
        assert paused.wait(15), "A 沒有走到計算"
        b = threading.Thread(target=edit, args=(True,), name="editor-B")
        b.start()
        b.join(2.0)                    # 修好：B 卡在寫鎖；突變：B 已經寫完
    finally:
        release.set()
    a.join(30)
    b.join(30)
    assert not a.is_alive() and not b.is_alive()
    assert not errors, errors
    rec = client.get("/api/payslips/" + no, headers=h).json()["data"].get("privacyNotice")
    assert rec and rec.get("at") and rec["byUsername"] == "dfix_su", "並行修改把已告知紀錄清掉了"


def test_edit_refusals_release_the_write_lock(client, make_user):
    """寫交易裡的 4xx（找不到、已匯出、版本不存在）要放掉寫鎖：之後的寫入不可以卡住。"""
    import db
    h = _hdr(client, make_user)
    assert client.put("/api/payslips/PS-209901-001", json={"data": _data()}, headers=h).status_code == 404
    no = client.post("/api/payslips", json={"data": _data()}, headers=h).json()["slip_no"]
    conn = db.get_db()
    try:
        conn.execute("UPDATE payslips SET status='已匯出' WHERE slip_no=?", (no,))
        conn.commit()
    finally:
        conn.close()
    assert client.put("/api/payslips/" + no, json={"data": _data()}, headers=h).status_code == 409
    conn = db.get_db()
    try:
        conn.execute("PRAGMA busy_timeout=500")
        conn.execute("BEGIN IMMEDIATE")        # 還被鎖著 ⇒ 0.5 秒後 database is locked
        conn.rollback()
    finally:
        conn.close()


# ── S-6 單據凍結 ────────────────────────────────────────────────────────────────

def test_editing_uses_the_snapshot_even_if_its_future_version_was_changed(client, make_user, frozen_today):
    """突變 M12（改用版本號查）存活處：未生效的版本可以改；改了之後修改舊單，仍要沿用建立時的快照。"""
    h = _hdr(client, make_user)
    r = client.put("/api/legal-params/tax-rules", json={"versions": lp.load_versions() + [_v2027()]}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post("/api/payslips", json={"data": _data(31000, "50", "2027-01-05")}, headers=h)
    assert r.status_code == 201 and r.json()["calc"]["nhiSupplement"] == 654, r.text     # 31,000 ≥ 30,900
    no = r.json()["slip_no"]
    vs = lp.load_versions()
    v27 = next(v for v in vs if v["version"] == "2027")
    v27["minimum_wage"]["monthly"] = 32000
    v27["nhi"]["thresholds"]["50"] = 32000
    r = client.put("/api/legal-params/tax-rules", json={"versions": vs}, headers=h)
    assert r.status_code == 200, r.text                                                   # 未生效 ⇒ 可以改
    r = client.put("/api/payslips/" + no, json={"data": _data(31000, "50", "2027-01-05")}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["calc"]["nhiSupplement"] == 654, "沒勾重算 ⇒ 沿用快照（門檻 30,900），不是改過的 2027 版"
    snap = client.get("/api/payslips/" + no, headers=h).json()["data"]["taxRulesSnapshot"]
    assert snap["minimum_wage"]["monthly"] == 30900


def test_create_ignores_a_snapshot_sent_by_the_client(client, make_user):
    """突變 M16（建立時收前端快照）存活處：建立時送來的快照與版本號一律不採用。"""
    h = _hdr(client, make_user)
    fake = copy.deepcopy(lp.DEFAULT_TAX_RULE_VERSIONS[0])
    fake["nhi"]["rate"] = 0.0
    fake["version"] = "偽造"
    r = client.post("/api/payslips", json={"data": _data(taxRulesSnapshot=fake, taxRulesVersion="偽造")}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["calc"]["nhiSupplement"] == 633 and r.json()["taxRulesVersion"] == "2026"
    no = r.json()["slip_no"]
    row = client.get("/api/payslips/" + no, headers=h).json()
    assert row["data"]["taxRulesSnapshot"]["nhi"]["rate"] == 0.0211 and row["tax_rules_version"] == "2026"
    r = client.put("/api/payslips/" + no, json={"data": _data()}, headers=h)
    assert r.status_code == 200 and r.json()["calc"]["nhiSupplement"] == 633, "存下來的快照也不可以是前端的"


# ── S-3 設定值損毀 ──────────────────────────────────────────────────────────────


def test_corrupted_text_archive_refuses_the_ack_but_not_the_save(client, make_user):
    h = _hdr(client, make_user)
    no = client.post("/api/payslips", json={"data": _data()}, headers=h).json()["slip_no"]
    _set_raw_setting(pn.TEXTS_KEY, "not json")
    r = client.put("/api/payslips/" + no, json={"data": _data(privacyNoticeAcked=True)}, headers=h)
    assert r.status_code == 409 and "損毀" in r.json()["detail"], r.text
    assert "privacyNotice" not in client.get("/api/payslips/" + no, headers=h).json()["data"]
    r = client.put("/api/payslips/" + no, json={"data": _data(remarks="沒勾")}, headers=h)
    assert r.status_code == 200, "沒勾已告知的存檔不受影響（§9.3 不擋存檔）"
    assert _raw_setting(pn.TEXTS_KEY) == "not json"


# ── S-5 告知全文 ────────────────────────────────────────────────────────────────

def test_the_acknowledged_text_can_be_looked_up_after_the_notice_changes(client, make_user):
    h = _hdr(client, make_user)
    assert client.put("/api/settings/company-profile", json={"privacy_notice": "第一版告知全文"},
                      headers=h).status_code == 200
    no = client.post("/api/payslips", json={"data": _data(privacyNoticeAcked=True)}, headers=h).json()["slip_no"]
    h1 = client.get("/api/payslips/" + no, headers=h).json()["data"]["privacyNotice"]["noticeHash"]
    assert client.put("/api/settings/company-profile", json={"privacy_notice": "第二版告知全文"},
                      headers=h).status_code == 200
    cid = client.post("/api/contractors", json={"name": "承攬全文"}, headers=h).json()["id"]
    h2 = client.post(f"/api/contractors/{cid}/privacy-notice/ack", headers=h).json()["ack"]["noticeHash"]
    assert h1 != h2
    r1 = client.get("/api/legal-params/privacy-notice/texts/" + h1, headers=h)
    r2 = client.get("/api/legal-params/privacy-notice/texts/" + h2, headers=h)
    assert (r1.status_code, r2.status_code) == (200, 200), (r1.text, r2.text)
    assert r1.json()["text"] == "第一版告知全文" and r2.json()["text"] == "第二版告知全文"
    assert client.get("/api/legal-params/privacy-notice/texts/0000000000000000", headers=h).status_code == 404
    assert client.get("/api/legal-params/privacy-notice/texts/..%2F..", headers=h).status_code == 404
    # 只增不改：同一版再記一次不改第一次存的時間
    first = json.loads(_raw_setting(pn.TEXTS_KEY))[h2]["firstAckAt"]
    cid2 = client.post("/api/contractors", json={"name": "承攬全文二"}, headers=h).json()["id"]
    client.post(f"/api/contractors/{cid2}/privacy-notice/ack", headers=h)
    assert json.loads(_raw_setting(pn.TEXTS_KEY))[h2]["firstAckAt"] == first
