# -*- coding: utf-8 -*-
"""財務報表參數（應收帳齡區間切點；旗標 finance_reports.custom_aging 預設關）。
純函式題（可用 --noconftest 單跑）：
- 預設切點的分組與標籤，對 0～400 天逐天等於今天寫死在 reports.py 的運算式與字串（等價性）；突變正對照（把邊界 > 改成 >= 就會有天數翻面）
- 自訂切點：邊界、標籤、key 不變；不合法的切點（不遞增、非整數、布林、超範圍）一律退回預設；旗標關＝一律預設；讀設定失敗＝預設
- reports.py 的帳齡相關程式不再有寫死的 30／60／90 判斷（原始碼掃描）
需要資料庫的題（寫好未跑）：設定寫入後帳齡 API 的標籤與分組跟著變；旗標關時回應與今天相同。"""
import re
from pathlib import Path

import pytest

from helpers import finance_params as F

ROOT = Path(__file__).resolve().parents[1]


def legacy_band(days):
    return "90+" if days > 90 else "61-90" if days > 60 else "31-60" if days > 30 else "0-30"


LEGACY_LABELS = {"0-30": "0–30 天", "31-60": "31–60 天", "61-90": "61–90 天", "90+": "90+ 天"}


def test_default_cuts_reproduce_todays_banding_for_every_day():
    for d in range(-5, 401):
        assert F.aging_band(d) == legacy_band(d), d


def test_default_labels_are_byte_identical_to_todays_strings():
    assert F.aging_labels() == LEGACY_LABELS and F.BAND_KEYS == ("0-30", "31-60", "61-90", "90+")


def test_equivalence_is_sensitive_mutation_control(monkeypatch):
    real = F.aging_band
    assert real(30) == "0-30" and real(31) == "31-60"
    shifted = lambda days, cuts=F.DEFAULT_CUTS: real(days + 1, cuts)      # 邊界差一天 ⇒ 30 天那格翻面
    assert shifted(30) != legacy_band(30)


def test_custom_cuts_change_the_bands_and_labels_but_not_the_keys():
    cuts = (45, 90, 180)
    assert F.aging_band(45, cuts) == "0-30" and F.aging_band(46, cuts) == "31-60"
    assert F.aging_band(90, cuts) == "31-60" and F.aging_band(91, cuts) == "61-90" and F.aging_band(181, cuts) == "90+"
    lab = F.aging_labels(cuts)
    assert lab == {"0-30": "0–45 天", "31-60": "46–90 天", "61-90": "91–180 天", "90+": "180+ 天"}
    assert set(lab) == set(F.BAND_KEYS)                                    # key 是位置代號，前端上色靠它


@pytest.mark.parametrize("bad", [(0, 60, 90), (30, 30, 90), (60, 30, 90), (30, 60, 60), (30, 60, 99999), (-1, 5, 9),
                                 (30.5, 60, 90), ("30", 60, 90), (True, 60, 90), (30, 60), None, (30, 60, 90, 120)])
def test_invalid_cuts_are_rejected(bad):
    assert F._valid(bad) is False


def _fake_sr(monkeypatch, values):
    from helpers import settings_registry as SR

    def get(group, field, conn=None, **kw):
        if group != "finance_reports":
            raise KeyError(group)
        return values[field]
    monkeypatch.setattr(SR, "get", get)


def test_flag_off_always_gives_the_defaults(monkeypatch):
    _fake_sr(monkeypatch, {"custom_aging": 0, "aging_day1": 10, "aging_day2": 20, "aging_day3": 30})
    assert F.aging_cuts() == (30, 60, 90)


def test_flag_on_uses_the_saved_cuts_and_falls_back_when_they_are_unreasonable(monkeypatch):
    _fake_sr(monkeypatch, {"custom_aging": 1, "aging_day1": 45, "aging_day2": 90, "aging_day3": 180})
    assert F.aging_cuts() == (45, 90, 180)
    _fake_sr(monkeypatch, {"custom_aging": 1, "aging_day1": 90, "aging_day2": 60, "aging_day3": 30})
    assert F.aging_cuts() == (30, 60, 90)
    _fake_sr(monkeypatch, {"custom_aging": 1, "aging_day1": "abc", "aging_day2": 60, "aging_day3": 90})
    assert F.aging_cuts() == (30, 60, 90)


def test_settings_failure_gives_the_defaults(monkeypatch):
    from helpers import settings_registry as SR

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(SR, "get", boom)
    assert F.aging_cuts() == (30, 60, 90)


def test_reports_page_colours_by_the_returned_cuts_with_the_old_values_as_fallback():
    html = __import__("core.source_tree", fromlist=["x"]).page_file("reports.html").read_text(encoding="utf-8")
    assert "(arAging.cuts || [30, 60, 90])[2]" in html and "(arAging.cuts || [30, 60, 90])[1]" in html
    assert "it.daysElapsed > 90" not in html and "it.daysElapsed > 60" not in html


def test_the_group_is_registered_with_the_status_quo_defaults():
    from helpers import settings_registry as SR
    import helpers.settings_groups  # noqa: F401
    assert [SR.get("finance_reports", k) for k in ("custom_aging", "aging_day1", "aging_day2", "aging_day3")] == [0, 30, 60, 90]


def test_reports_source_has_no_hard_coded_aging_thresholds_left():
    src = (ROOT / "modules/analytics/api/reports.py").read_text(encoding="utf-8")
    start, end = src.index("def _compute_ar_aging"), src.index('@router.get("/api/reports/ar-aging")')
    body = src[start:end]
    assert not re.search(r"days\s*>\s*(30|60|90)\b", body), "帳齡計算不該再有寫死的天數切點"
    assert "aging_band" in body and "aging_labels" in body
    for name in ("days > _ar_cuts[2]", "d > _cuts[2]"):                    # Excel 與 PDF 的超期上色改讀同一組切點
        assert name in src, name


# ── 需要資料庫（寫好未跑）─────────────────────────────────────────────────────
@pytest.fixture()
def sa(client, make_user):
    u, p = make_user(username="fin_sa", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _set(values):
    import db
    from helpers import settings_registry as SR
    c = db.get_db()
    try:
        SR.publish("finance_reports", values, reason="t62", user="t62", conn=c)
        c.commit()
    finally:
        c.close()


def test_ar_aging_api_flag_off_is_todays_response(client, sa):
    j = client.get("/api/reports/ar-aging", headers=sa).json()
    assert [b["label"] for b in j["bands"]] == list(LEGACY_LABELS.values()) and [b["key"] for b in j["bands"]] == list(F.BAND_KEYS)
    assert set(j) == {"asOf", "note", "bands", "total"}


def test_ar_aging_api_follows_the_saved_cuts_but_keeps_keys(client, sa):
    _set({"custom_aging": 1, "aging_day1": 45, "aging_day2": 90, "aging_day3": 180})
    j = client.get("/api/reports/ar-aging", headers=sa).json()
    assert [b["label"] for b in j["bands"]] == ["0–45 天", "46–90 天", "91–180 天", "180+ 天"]
    assert [b["key"] for b in j["bands"]] == list(F.BAND_KEYS) and set(j) == {"asOf", "note", "bands", "total", "cuts"} and j["cuts"] == [45, 90, 180]
    _set({"custom_aging": 1, "aging_day1": 30, "aging_day2": 60, "aging_day3": 90})            # 自訂值剛好等於預設 ⇒ 不多 cuts 鍵
    assert "cuts" not in client.get("/api/reports/ar-aging", headers=sa).json()


def test_ar_aging_still_needs_the_reports_permission(client, make_user):
    u, p = make_user(username="fin_viewer", role="viewer")[:2]
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}
    assert client.get("/api/reports/ar-aging", headers=h).status_code in (401, 403)
