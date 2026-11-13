# -*- coding: utf-8 -*-
"""SPEC §15-3（S5 的「只通知」三項）：獎金預設、年度營運目標、報價條款（條款組＋預設付款條件）維持**立即生效**，**存檔後**發通知。

釘住的事：
  ① 立即生效沒變（值照存、回傳不變）；有變才發、沒變不發；一次存檔多欄＝一則（`SN.batch()`）。
  ② 通知內容＝誰（操作者）、哪一項（白話標籤）、舊→新（白話值）；種類前綴對（獎金預設變更／營運目標變更／報價條款變更）。
  ③ 風險＝ops ⇒ **不發 LINE**（只有 security／money／legal 才發）；收件人＝其他在職最高管理者（h9 的 S1d：操作者本人不收自己的站內通知）＋指定角色。
  ④ 通知失敗**不影響**設定已存好（呼叫端都在 commit 之後）；非最高管理者 403 ⇒ 不發。
依賴：`helpers.settings_notify.notify_change`（S1d；feat/settings-change-notify）。
"""
import pytest

from db import get_db
from helpers import settings_notify as SN


def _hdr(client, make_user, name, role="superadmin"):
    username, password = make_user(username=name, role=role)
    tok = client.post("/api/auth/login", json={"username": username, "password": password}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _notes(user, type_="settings_changed"):
    conn = get_db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT message, ref_id, ref_label, link FROM notifications WHERE username=? AND type=? ORDER BY id", (user, type_)).fetchall()]
        for r in rows:                                              # 標題（種類前綴）在 ref_label，內文在 message；測試一起比對
            r["message"] = (r["ref_label"] or "") + chr(10) + (r["message"] or "")
        return rows
    finally:
        conn.close()


@pytest.fixture()
def line_calls(monkeypatch):
    calls = []
    from helpers import line_notify as LN
    monkeypatch.setattr(LN, "notify_event", lambda *a, **kw: calls.append((a, kw)))
    return calls


@pytest.fixture()
def sa(client, make_user):
    h = _hdr(client, make_user, "s5n_sa1")
    make_user(username="s5n_obs", role="superadmin")               # 被檢查的收件人：另一位最高管理者（h9：操作者本人不再收到自己的站內通知）
    return h


def _bonus_put(client, h, rate, sales, project, admin):
    return client.put("/api/bonus/cases/settings", headers=h,
                      json={"rate_bp": rate, "split_bp": {"sales": sales, "project": project, "admin": admin}})


# ═══ 獎金預設 ═══════════════════════════════════════════════════

def test_bonus_defaults_change_notifies_superadmins_once_with_old_new_and_no_line(client, make_user, sa, line_calls):
    make_user(username="s5n_sa2", role="superadmin")
    make_user(username="s5n_sales", role="sales")
    r = _bonus_put(client, sa, 2000, 6000, 2000, 2000)          # 預設 10%／50%／30%／20% → 20%／60%／20%／20%
    assert r.status_code == 200 and r.json() == {"ok": True}      # ① 立即生效、回傳形狀不變
    got = client.get("/api/bonus/cases/settings", headers=sa).json()
    assert got == {"rate_bp": 2000, "split_bp": {"sales": 6000, "project": 2000, "admin": 2000}}
    for u in ("s5n_obs", "s5n_sa2"):                              # 其他在職最高管理者各一則（多欄合併；操作者本人不收自己的站內通知）
        n = _notes(u)
        assert len(n) == 1, (u, n)
        m = n[0]["message"]
        assert "獎金預設變更" in m
        assert "基本發放比例" in m and "10%" in m and "20%" in m
        assert "業務比例" in m and "50%" in m and "60%" in m
        assert "專案比例" in m and "30%" in m
        assert "後勤比例" not in m                                 # 後勤 20%→20% 沒變，不列
    assert _notes("s5n_sales") == []                               # 業務不是收件人
    assert line_calls == []                                        # ops 不發 LINE


def test_bonus_defaults_no_change_sends_nothing(client, sa, line_calls):
    assert _bonus_put(client, sa, 1000, 5000, 3000, 2000).status_code == 200      # 與預設相同
    assert _notes("s5n_obs") == []


def test_bonus_defaults_non_superadmin_forbidden_and_silent(client, make_user, line_calls):
    h = _hdr(client, make_user, "s5n_adm", role="admin")
    make_user(username="s5n_sa9", role="superadmin")
    assert _bonus_put(client, h, 2000, 6000, 2000, 2000).status_code == 403
    assert _notes("s5n_sa9") == []


def test_bonus_defaults_invalid_body_400_no_notify(client, sa):
    assert _bonus_put(client, sa, 2000, 1, 1, 1).status_code == 400
    assert _notes("s5n_obs") == []


def test_bonus_defaults_notify_failure_does_not_break_the_save(client, sa, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("notify down")
    monkeypatch.setattr(SN, "notify_change", boom)
    r = _bonus_put(client, sa, 2000, 6000, 2000, 2000)
    assert r.status_code == 200
    assert client.get("/api/bonus/cases/settings", headers=sa).json()["rate_bp"] == 2000


def test_bonus_defaults_calls_use_documented_kind_risk_link(client, sa, monkeypatch):
    calls = []
    monkeypatch.setattr(SN, "notify_change", lambda *a, **kw: calls.append((a, kw)))
    _bonus_put(client, sa, 2000, 5000, 3000, 2000)
    assert len(calls) == 1
    a, kw = calls[0]
    assert a[0] == "bonus_default" and a[1] == "獎金預設／基本發放比例" and a[2:] == ("10%", "20%")
    assert kw["risk"] == "ops" and kw["actor"] == "s5n_sa1" and kw["link"] == "bonus.html"


# ═══ 年度營運目標 ═══════════════════════════════════════════════

def _targets(year=2026, **annual):
    return {"year": year, "annual": annual, "salesperson": []}


def test_operating_targets_first_save_notifies_with_year_and_changed_fields(client, make_user, sa, line_calls):
    make_user(username="s5n_fin", role="finance")
    r = client.put("/api/settings/operating-targets", headers=sa, json=_targets(2026, revenue=5000000, newCases=12))
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get("/api/settings/operating-targets", headers=sa).json()["annual"]["revenue"] == 5000000
    m = _notes("s5n_obs")[0]["message"]
    assert "營運目標變更" in m and "2026 年度" in m and "營收目標" in m and "5,000,000" in m and "新成案數" in m
    assert "收款率" not in m                                       # 0→0 沒變
    assert len(_notes("s5n_fin")) == 1                             # 財務是指定角色（目標頁財務看得到）
    assert line_calls == []


def test_operating_targets_same_year_only_changed_fields_listed(client, sa):
    client.put("/api/settings/operating-targets", headers=sa, json=_targets(2026, revenue=5000000, newCases=12))
    client.put("/api/settings/operating-targets", headers=sa, json=_targets(2026, revenue=6000000, newCases=12))
    msgs = [n["message"] for n in _notes("s5n_obs")]
    assert len(msgs) == 2
    assert "營收目標" in msgs[1] and "6,000,000" in msgs[1] and "新成案數" not in msgs[1]


def test_operating_targets_salesperson_quota_change_is_one_line(client, sa):
    client.put("/api/settings/operating-targets", headers=sa, json=_targets(2026, revenue=1))
    body = _targets(2026, revenue=1)
    body["salesperson"] = [{"name": "小王", "revenue": 100, "cases": 2}]
    client.put("/api/settings/operating-targets", headers=sa, json=body)
    m = _notes("s5n_obs")[-1]["message"]
    assert "業務員配額" in m and "0 位" in m and "1 位" in m


def test_operating_targets_no_change_sends_nothing(client, sa):
    client.put("/api/settings/operating-targets", headers=sa, json=_targets(2026, revenue=1))
    n0 = len(_notes("s5n_obs"))
    client.put("/api/settings/operating-targets", headers=sa, json=_targets(2026, revenue=1))
    assert len(_notes("s5n_obs")) == n0


def test_operating_targets_other_year_is_reported_as_year_change(client, sa):
    client.put("/api/settings/operating-targets", headers=sa, json=_targets(2026, revenue=5000000))
    client.put("/api/settings/operating-targets", headers=sa, json=_targets(2027, revenue=5000000))
    m = _notes("s5n_obs")[-1]["message"]
    assert "目標年度" in m and "2026 年度" in m and "2027 年度" in m


def test_operating_targets_non_superadmin_forbidden(client, make_user):
    h = _hdr(client, make_user, "s5n_adm2", role="admin")
    make_user(username="s5n_sa8", role="superadmin")
    assert client.put("/api/settings/operating-targets", headers=h, json=_targets(2026, revenue=1)).status_code == 403
    assert _notes("s5n_sa8") == []


# ═══ 報價條款 ═══════════════════════════════════════════════════

def _preset(name, key="", **over):
    d = {"key": key, "name": name, "paymentTerms": name + " 付款", "deliveryTerms": name + " 交貨",
         "acceptanceTerms": name + " 驗收", "warrantyTerms": name + " 保固", "afterSales": name + " 售後"}
    d.update(over)
    return d


def test_payment_terms_change_notifies_old_and_new_text(client, make_user, sa, line_calls):
    make_user(username="s5n_sales2", role="sales")
    assert client.put("/api/settings/payment-terms", headers=sa, json={"text": "月結 30 天"}).status_code == 200
    r = client.put("/api/settings/payment-terms", headers=sa, json={"text": "三期 50/30/20"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get("/api/settings/payment-terms", headers=sa).json() == {"text": "三期 50/30/20"}
    m = _notes("s5n_obs")[-1]["message"]
    assert "報價條款變更" in m and "預設付款條件" in m and "月結 30 天" in m and "三期 50/30/20" in m
    assert len(_notes("s5n_sales2")) == 2                          # 業務是指定角色
    assert line_calls == []


def test_payment_terms_same_text_sends_nothing(client, sa):
    client.put("/api/settings/payment-terms", headers=sa, json={"text": "月結 30 天"})
    n0 = len(_notes("s5n_obs"))
    client.put("/api/settings/payment-terms", headers=sa, json={"text": "月結 30 天"})
    assert len(_notes("s5n_obs")) == n0


def test_payment_terms_non_superadmin_forbidden(client, make_user):
    h = _hdr(client, make_user, "s5n_sales3", role="sales")
    make_user(username="s5n_sa7", role="superadmin")
    assert client.put("/api/settings/payment-terms", headers=h, json={"text": "x"}).status_code == 403
    assert _notes("s5n_sa7") == []


def test_quote_terms_presets_add_rename_edit_delete_default_rows():
    from routers.system import _quote_terms_change_rows as rows_of
    old = {"presets": [_preset("甲", "a"), _preset("乙", "b"), _preset("丙", "c")], "defaultKey": "a"}
    new = {"presets": [_preset("甲", "a", warrantyTerms="保固改了"), _preset("乙二", "b", **{k: v for k, v in _preset("乙").items() if k.endswith(("Terms", "afterSales"))}), _preset("丁", "d")], "defaultKey": "d"}
    rows = {r[0]: r for r in rows_of(old, new)}
    assert rows["報價條款組／新增"][2] == "「丁」"
    assert rows["報價條款組／刪除"][1] == "「丙」"
    assert rows["報價條款組／改名"][1:] == ("「乙」", "「乙二」")
    assert rows["報價條款組／內容修改"][2] == "「甲」"
    assert rows["報價條款組／預設條款組"][1:] == ("「甲」", "「丁」")
    assert rows_of(old, old) == []                                  # 沒變 ⇒ 沒有列


def test_quote_terms_presets_save_sends_one_merged_message(client, make_user, sa, line_calls):
    make_user(username="s5n_sales4", role="sales")
    first = {"presets": [_preset("純購料", "k1")], "defaultKey": "k1"}
    assert client.put("/api/settings/quote-terms-presets", headers=sa, json=first).status_code == 200
    n0 = len(_notes("s5n_obs"))
    second = {"presets": [_preset("純購料", "k1", paymentTerms="貨到付款"), _preset("含施工", "k2")], "defaultKey": "k2"}
    r = client.put("/api/settings/quote-terms-presets", headers=sa, json=second)
    assert r.status_code == 200 and r.json()["defaultKey"] == "k2"      # 回傳形狀不變
    notes = _notes("s5n_obs")
    assert len(notes) == n0 + 1                                    # 新增＋內容修改＋預設改變 ⇒ 一則
    m = notes[-1]["message"]
    assert "報價條款變更" in m and "含施工" in m and "純購料" in m
    assert len(_notes("s5n_sales4")) == n0 + 1
    # 既有的 notify_module_activity（群組 LINE「module_activity」）原樣保留；新通知（ops）不發 settings_changed 的 LINE
    assert all(c[0][0] != SN.EVENT_KEY for c in line_calls)


def test_quote_terms_presets_no_change_sends_nothing(client, sa):
    body = {"presets": [_preset("純購料", "k1")], "defaultKey": "k1"}
    client.put("/api/settings/quote-terms-presets", headers=sa, json=body)
    n0 = len(_notes("s5n_obs"))
    client.put("/api/settings/quote-terms-presets", headers=sa, json=body)
    assert len(_notes("s5n_obs")) == n0


def test_quote_terms_presets_validation_error_400_sends_nothing(client, sa):
    bad = {"presets": [_preset("")], "defaultKey": ""}
    assert client.put("/api/settings/quote-terms-presets", headers=sa, json=bad).status_code == 400
    assert _notes("s5n_obs") == []


# ═══ h10 審查（M-／L1–L3）：寫入前讀舊值失敗不能害儲存失敗；年度換了／配額內容調整的顯示；非有限數字 ═══════════════

def test_prewrite_read_failure_never_breaks_the_save_bonus_defaults(client, sa, monkeypatch):
    from modules.payroll.api import bonus as B
    with monkeypatch.context() as m:
        m.setattr(B, "_case_defaults", lambda: (_ for _ in ()).throw(RuntimeError("settings read down")))
        r = _bonus_put(client, sa, 2000, 6000, 2000, 2000)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get("/api/bonus/cases/settings", headers=sa).json()["rate_bp"] == 2000     # 照存
    assert _notes("s5n_obs") == []                                                           # 不知道舊值 ⇒ 不發


def test_prewrite_read_failure_never_breaks_the_save_operating_targets(client, sa, monkeypatch):
    from routers import system as SY
    real = SY._get_setting
    with monkeypatch.context() as m:
        m.setattr(SY, "_get_setting", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("read down")))
        # _set_setting 走自己的連線，不經 _get_setting；寫入前的 _get_setting 會丟例外
        r = client.put("/api/settings/operating-targets", headers=sa, json=_targets(2026, revenue=5000000))
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get("/api/settings/operating-targets", headers=sa).json()["annual"]["revenue"] == 5000000
    assert _notes("s5n_obs") == []
    assert SY._get_setting is real


def test_prewrite_read_failure_never_breaks_the_save_payment_terms(client, sa, monkeypatch):
    from routers import system as SY
    with monkeypatch.context() as m:
        m.setattr(SY, "_quote_default_terms", lambda: (_ for _ in ()).throw(RuntimeError("provider down")))
        r = client.put("/api/settings/payment-terms", headers=sa, json={"text": "月結 30 天"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get("/api/settings/payment-terms", headers=sa).json() == {"text": "月結 30 天"}
    assert _notes("s5n_obs") == []


def test_prewrite_read_failure_never_breaks_the_save_quote_terms_presets(client, sa, monkeypatch):
    from routers import system as SY
    body = {"presets": [_preset("純購料", "k1")], "defaultKey": "k1"}
    with monkeypatch.context() as m:
        m.setattr(SY, "_quote_terms_presets", lambda: (_ for _ in ()).throw(RuntimeError("read down")))
        r = client.put("/api/settings/quote-terms-presets", headers=sa, json=body)
    assert r.status_code == 200 and r.json()["defaultKey"] == "k1"
    assert client.get("/api/settings/quote-terms-presets", headers=sa).json()["presets"][0]["name"] == "純購料"
    assert _notes("s5n_obs") == []


def test_operating_targets_year_change_shows_old_year_real_headcount(client, sa):
    old = _targets(2026, revenue=1)
    old["salesperson"] = [{"name": "甲", "revenue": 1, "cases": 1}, {"name": "乙", "revenue": 1, "cases": 1}]
    client.put("/api/settings/operating-targets", headers=sa, json=old)
    new = _targets(2027, revenue=1)
    new["salesperson"] = [{"name": "甲", "revenue": 1, "cases": 1}]
    client.put("/api/settings/operating-targets", headers=sa, json=new)
    m = _notes("s5n_obs")[-1]["message"]
    assert "業務員配額" in m and "2 位" in m and "1 位" in m and "0 位" not in m               # L1：舊年度實際人數，不是 0


def test_operating_targets_quota_edited_same_count_is_not_a_meaningless_line(client, sa):
    body = _targets(2026, revenue=1)
    body["salesperson"] = [{"name": "甲", "revenue": 100, "cases": 1}]
    client.put("/api/settings/operating-targets", headers=sa, json=body)
    body["salesperson"] = [{"name": "甲", "revenue": 200, "cases": 1}]
    client.put("/api/settings/operating-targets", headers=sa, json=body)
    m = _notes("s5n_obs")[-1]["message"]
    assert "業務員配額" in m and "內容已調整" in m                                            # L2：不是「1 位 → 1 位」


def test_target_num_guards_non_finite_numbers():
    from routers.system import _target_num
    assert _target_num(float("nan"), "元") == "0 元" and _target_num(float("inf"), "%") == "0%"   # L3：不丟例外，其他列照發
