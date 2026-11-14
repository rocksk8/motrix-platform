# -*- coding: utf-8 -*-
"""T86（設定改版，2026-11-14）：使用者管理「Email 通知偏好」改成矩陣（共用 settings-matrix.js）。
伺服器端只多了兩個欄位（`/api/mail-types/receivable` 的 category／lowRisk，與 `/mine` 同一條規則）；其餘是靜態守門：
鍵值不變（存檔仍送 notification_muted）、矩陣掛得上、mixin 不可用 getter（spread 會當場求值）。"""
import re
from pathlib import Path

_MAKE_USER_DEFAULT_ROLE = "superadmin"
_FE = Path(__file__).resolve().parents[2] / "frontend"


def _h(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def test_receivable_carries_category_and_the_same_low_risk_rule_as_mine(client, make_user):
    sa = make_user(username="t86_sa", role="superadmin")
    items = client.get("/api/mail-types/receivable?user_id=%d" % _uid("t86_sa"), headers=_h(client, sa)).json()["items"]
    assert items and all({"key", "name", "categoryLabel", "category", "lowRisk", "receivable"} <= set(i) for i in items)
    assert all(i["lowRisk"] == (i["category"] == "business") for i in items)
    assert {i["category"] for i in items} >= {"business"} and any(not i["lowRisk"] for i in items)
    from helpers import mail_types as mt
    assert {i["key"]: i["category"] for i in items} == {t.key: t.category for t in mt.all_types()}


def test_receivable_still_requires_a_superadmin(client, make_user):
    adm = make_user(username="t86_adm", role="admin")
    assert client.get("/api/mail-types/receivable?user_id=1", headers=_h(client, adm)).status_code == 403


def _page():
    return (_FE / "pages" / "users.html").read_text(encoding="utf-8")


def _mixin():
    return (_FE / "static" / "users-email-prefs.js").read_text(encoding="utf-8")


def test_users_page_hosts_the_matrix_and_keeps_the_payload_keys():
    page = _page()
    assert 'id="up-email-box"' in page and "settings-matrix.js" in page and "settings-matrix.css" in page and "users-email-prefs.js" in page
    assert "usersEmailPrefsMixin" in page
    assert "notification_muted:   this.form.notificationMuted" in page, "存檔欄位與值必須不變"
    assert "/api/mail-types/receivable?user_id=" in page and "/api/mail-types'" in page
    # 舊的手風琴不可殘留（兩套並存會讓 form.notificationMuted 被兩個畫面各改各的）
    for gone in ("notifyGroups", "_notifyGroupOpen", "toggleNotifyType", "notifyGroupOnCount", "toggleNotifyGroup"):
        assert gone not in page, gone


def test_every_open_path_mounts_and_every_close_path_destroys():
    page = _page()
    assert page.count("emailPrefsMount()") >= 2, "新增帳號與編輯帳號都要掛矩陣"
    assert len(re.findall(r"emailPrefsDestroy\(\)", page)) >= 3, "openCreate／openEdit／closeModal 都要先拆掉舊的矩陣"


def test_mixin_has_no_getter_because_spread_would_freeze_it():
    js = _mixin()
    assert not re.search(r"^\s*get \w+\s*\(", js, re.M), "mixin 用 `...` spread 進頁面物件，getter 會當場求值而不再更新"
    for need in ("emailPrefsMount", "emailPrefsDestroy", "emailPrefsStatText", "_emailApply", "_emailRows"):
        assert need in js, need


def test_mixin_keeps_the_s6_rules():
    js = _mixin()
    assert "selectable: !!t.receivable && !!low" in js, "收不到、或非業務類的列不能批次"
    assert "!v && !r.lowRisk" in js, "非業務類取消勾選要先確認"
    assert "if (!t || !t.receivable) return" in js, "收不到的類型不可被改動（與伺服器 receivable 檢查同向）"
    assert "snapshot" in js and "restore" in js and "groupActionsEnabled: true" in js
    assert "throw new Error" not in js, "restore 不可同步 throw（元件卡在忙碌、沒有提示）；要拒絕就回 Promise.reject"
    assert "fetch(" not in js, "矩陣只改表單狀態，不直接寫伺服器（寫入由使用者表單的儲存一起送）"


def test_matrix_layers_sit_above_the_users_modal():
    """矩陣的確認視窗與提示條（含「復原這一批」）掛在 body；若層級低於本頁彈窗（200）就整個被蓋住、點不到。"""
    page = _page()
    m1 = re.search(r"\.mx-modal\s*\{\s*z-index:\s*(\d+)", page)
    m2 = re.search(r"\.mx-toast\s*\{\s*z-index:\s*(\d+)", page)
    m3 = re.search(r"\.modal-overlay\s*\{[^}]*?z-index:\s*(\d+)", page, re.S)
    assert m1 and m2 and m3
    assert int(m1.group(1)) > int(m3.group(1)) and int(m2.group(1)) > int(m1.group(1))
