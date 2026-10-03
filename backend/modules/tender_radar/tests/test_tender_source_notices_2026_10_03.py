# -*- coding: utf-8 -*-
"""2026-10-03 標案雷達頁的「來源網站狀態」：格式異動／詳細頁要求驗證碼／當日無公告／今天不寄信／假日表未涵蓋，
各自一句不同的話（「不可用要明說、不可以長得像 0 筆」），文字一律 x-text，沒有 tender_radar 權限的人拿不到。

為什麼先前頁面沒有任何提示（調查結論）：
  ① 前端從來沒讀 `suspectRedesign`（grep 全 repo 只有 api.py 一處）；
  ② API 算這個旗標時拿「資料庫裡全部標案數」當分母（標案一多，dropped=1 永遠不成立）；
  ③ 健康燈只看 `recognised`：只要認得表頭就是「✓ 雷達正常」。
"""
import re
from datetime import date, datetime
from pathlib import Path

import pytest

import modules.tender_radar.source as ts

USES_REAL_CALENDAR = True        # tests/conftest.py 的 _mail_day_independent_of_the_real_weekday 不介入：本檔自己注入日期

def _page_text():
    """頁面原始碼：走 core.source_tree.page_file()（page_paths 棘輪：頁面路徑不可在測試裡寫死）。"""
    from core import source_tree
    return source_tree.page_file("tender-radar.html").read_text(encoding="utf-8")


def _day(monkeypatch, iso):
    d = date.fromisoformat(iso)
    monkeypatch.setattr(ts, "today", lambda: d)
    monkeypatch.setattr(ts, "now_dt", lambda: datetime(d.year, d.month, d.day, 9, 0, 0))


def _admin(client, make_user):
    u, p = make_user(role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _state(**kw):
    import db
    conn = db.get_db()
    try:
        ts._save_scan_state(conn, **kw)
        ts._log_fetch(conn, 1, kw.get("dropped", 0), "", suspected=0)
        conn.commit()
    finally:
        conn.close()


def _notices(client, hdr):
    r = client.get("/api/tender-radar/status", headers=hdr)
    assert r.status_code == 200, r.text
    return r.json(), {n["kind"]: n for n in r.json()["notices"]}


def test_format_changed_is_stated_with_the_scan_numbers_and_is_not_the_green_health_light(client, make_user, monkeypatch):
    _day(monkeypatch, "2026-10-05")
    _state(list="format_changed", parsed=1, dropped=9, scan_at="x")
    body, n = _notices(client, _admin(client, make_user))
    assert body["health"] == "ok" and body["suspectRedesign"] is True and body["listState"] == "format_changed"
    t = n["format_changed"]["text"]
    assert "來源網站格式異動" in t and "成功解析 1 筆" in t and "解析失敗 9 筆" in t and "不是「沒有符合的標案」" in t
    assert "empty_day" not in n and "detail_captcha" not in n


def test_suspect_flag_uses_the_scans_own_numbers_not_the_size_of_the_tenders_table(client, make_user, monkeypatch):
    """舊寫法：suspect_redesign(資料庫全部標案數, dropped)——標案一多就永遠不成立。"""
    _day(monkeypatch, "2026-10-05")
    import db
    conn = db.get_db()
    try:
        for i in range(30):
            conn.execute("INSERT INTO tenders (case_no, org, name, url) VALUES (?,?,?,?)", ("C%d" % i, "機關", "標案%d" % i, "u"))
        conn.commit()
    finally:
        conn.close()
    _state(list="format_changed", parsed=1, dropped=9)
    body, _ = _notices(client, _admin(client, make_user))
    assert body["tenderCount"] == 30 and body["suspectRedesign"] is True


def test_detail_captcha_is_stated_separately_from_format_change(client, make_user, monkeypatch):
    _day(monkeypatch, "2026-10-05")
    _state(list="ok", detail="captcha", parsed=3, dropped=0)
    _, n = _notices(client, _admin(client, make_user))
    assert "驗證碼" in n["detail_captcha"]["text"] and "未取得" in n["detail_captcha"]["text"] and "不會嘗試破解" in n["detail_captcha"]["text"]
    assert "format_changed" not in n


def test_an_empty_day_is_stated_as_not_an_error(client, make_user, monkeypatch):
    _day(monkeypatch, "2026-10-05")
    _state(list="empty_day", parsed=0, dropped=0)
    body, n = _notices(client, _admin(client, make_user))
    assert "當日沒有公告" in n["empty_day"]["text"] and "不是錯誤" in n["empty_day"]["text"] and n["empty_day"]["tone"] == "idle"
    assert body["suspectRedesign"] is False and "format_changed" not in n


def test_no_mail_day_notice_names_the_reason_and_is_informational(client, make_user, monkeypatch):
    hdr = _admin(client, make_user)
    for iso, reason in (("2026-10-03", "週末"), ("2026-10-09", "國定假日：補假")):
        _day(monkeypatch, iso)
        _, n = _notices(client, hdr)
        assert reason in n["no_mail_day"]["text"] and "順延" in n["no_mail_day"]["text"] and n["no_mail_day"]["tone"] == "idle"
    _day(monkeypatch, "2026-10-05")
    _, n = _notices(client, hdr)
    assert "no_mail_day" not in n


def test_uncovered_year_and_near_expiry_are_stated(client, make_user, monkeypatch):
    hdr = _admin(client, make_user)
    _day(monkeypatch, "2028-03-01")
    _, n = _notices(client, hdr)
    assert "假日表未涵蓋 2028 年" in n["calendar_uncovered"]["text"] and n["calendar_uncovered"]["tone"] == "warn"
    _day(monkeypatch, "2027-11-15")                                      # 離 2027-12-31 還有 46 天（<=60）
    _, n = _notices(client, hdr)
    assert "46 天後到期" in n["calendar_expiring"]["text"] and "calendar_uncovered" not in n
    _day(monkeypatch, "2026-10-05")
    _, n = _notices(client, hdr)
    assert "calendar_expiring" not in n and "calendar_uncovered" not in n


def test_the_expiry_warning_is_logged_once_per_day(client, monkeypatch, caplog):
    _day(monkeypatch, "2027-11-15")
    import logging
    with caplog.at_level(logging.WARNING):
        ts._check_holiday_table_expiry()
        ts._check_holiday_table_expiry()
    assert sum("假日表" in r.getMessage() for r in caplog.records) == 1
    caplog.clear()
    _day(monkeypatch, "2026-10-05")                                      # 離到期還很遠 ⇒ 不記
    with caplog.at_level(logging.WARNING):
        ts._check_holiday_table_expiry()
    assert not any("假日表" in r.getMessage() for r in caplog.records)


def test_status_notices_require_the_tender_radar_permission(client, make_user, monkeypatch):
    _day(monkeypatch, "2026-10-03")
    _state(list="format_changed", parsed=1, dropped=9)
    assert client.get("/api/tender-radar/status").status_code in (401, 403)
    u, p = make_user(role="sales", modules=[])
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    hdr = {"Authorization": "Bearer " + r.json()["token"]}
    denied = client.get("/api/tender-radar/status", headers=hdr)
    assert denied.status_code in (401, 403, 404)
    assert "格式異動" not in denied.text and "驗證碼" not in denied.text and "notices" not in denied.text


def test_status_notices_carry_only_status_text_no_tender_content(client, make_user, monkeypatch):
    _day(monkeypatch, "2026-10-05")
    _state(list="format_changed", detail="captcha", parsed=1, dropped=9)
    r = client.get("/api/tender-radar/status", headers=_admin(client, make_user))
    for n in r.json()["notices"]:
        assert set(n) == {"kind", "tone", "text"}


# ── 頁面：x-text、不用 x-html；地點「未取得」──────────────────────────────

def test_page_renders_notices_with_x_text_only():
    html = _page_text()
    i = html.index('x-for="n in ((status && status.notices) || [])"')
    block = html[i:html.index("</template>", i)]
    assert 'x-text="n.text"' in block and "x-html" not in block and "innerHTML" not in block
    assert 'data-source-notice' in block


def test_page_marks_a_missing_location_as_not_obtained_instead_of_blank_or_dash():
    html = _page_text()
    m = re.search(r"case 'location':.*?\n(?=\s*case 'procurementType')", html, re.S)
    assert m and "未取得" in m.group(0) and "data-location-missing" in m.group(0)
    assert "_esc(t.location)" in m.group(0), "地點有值時仍要經過跳脫"
