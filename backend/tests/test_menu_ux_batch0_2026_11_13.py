"""選單去工程師化 批 0（2026-11-13）：稱呼統一、預設系統網址、開發機測試模式顯示條件、載入失敗白話提示、改名不留舊稱。

守的是「畫面上不再看到工程師字眼」這件事本身，不是某個字串的拼法：
  ① 使用者看得到的檔案（前端頁面、選單與總覽卡資料）不再出現「超級管理員／最高管理員」（統一為「最高管理者」）。
  ② 新安裝不預填任何一台機器的內部位址；升級安裝（資料庫已有設定）維持舊行為。
  ③ 五個原本載入失敗就空白的頁面，各有一個 role=alert 的白話錯誤區。
  ④ 選單／總覽卡的舊名稱（Schema 狀態、刪除暫存區、在線時數統計、稽核頁的「歷史紀錄」）已換掉。
"""
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONT = ROOT / "frontend"
BACK = ROOT / "backend"


def _read(p):
    return pathlib.Path(p).read_text(encoding="utf-8")


def test_visible_files_never_say_old_admin_titles():
    bad = []
    for p in list(FRONT.rglob("*.html")) + list(FRONT.rglob("*.js")) + [BACK / "core" / "menu_l1.json", BACK / "core" / "system_hub_l1.json"] + list((BACK / "modules").glob("*/module.json")):
        t = _read(p)
        for old in ("超級管理員", "最高管理員"):
            if old in t:
                bad.append("%s 含「%s」" % (p.relative_to(ROOT).as_posix(), old))
    assert not bad, "使用者可見稱呼請統一寫「最高管理者」：\n" + "\n".join(bad)


@pytest.mark.parametrize("old", ["Schema 狀態", "刪除暫存區", "在線時數統計"])
def test_old_menu_names_are_gone_from_menu_and_hub_data(old):
    hits = []
    for p in [BACK / "core" / "menu_l1.json", BACK / "core" / "system_hub_l1.json"] + list((BACK / "modules").glob("*/module.json")):
        if old in _read(p):
            hits.append(p.name)
    assert not hits, "%s 仍出現在 %s" % (old, hits)


def test_audit_page_is_called_operation_log():
    menu = json.loads(_read(BACK / "core" / "menu_l1.json"))
    txt = json.dumps(menu, ensure_ascii=False)
    assert "操作紀錄" in txt and '"歷史紀錄"' not in txt
    assert "<title>操作紀錄" in _read(FRONT / "pages" / "audit-log.html")


@pytest.mark.parametrize("page", ["audit-log", "online-stats", "schema-status", "module-versions", "shipping-export-history"])
def test_five_pages_show_a_plain_error_when_loading_fails(page):
    html = _read(FRONT / "pages" / (page + ".html"))
    assert 'data-testid="load-error"' in html and 'role="alert"' in html, page
    assert "loadError" in html and "請重新整理" in html, page
    assert "連不上系統" in html, page


def test_online_stats_has_no_literal_markdown_stars():
    assert "**" not in _read(FRONT / "pages" / "online-stats.html")


def test_recycle_bin_reason_is_marked_required_and_blocks_the_button():
    html = _read(FRONT / "pages" / "recycle-bin.html")
    assert "原因（選填）" not in html and "原因（必填" in html
    assert "!ap.reason_text" in html


def test_planned_cards_do_not_show_train_codes():
    html = _read(FRONT / "pages" / "settings-center.html")
    assert "預計 ' + p.plannedTrain" not in html and "版提供" not in html


# ── 預設系統網址 ────────────────────────────────────────────────────────────────
def test_base_url_new_install_is_empty_and_upgrade_keeps_legacy(monkeypatch):
    from helpers import email_notify as EN
    monkeypatch.setattr(EN, "_cfg", lambda: {})
    assert EN._base_url() == "", "全新安裝不可預填內部位址"
    monkeypatch.setattr(EN, "_cfg", lambda: {"enabled": True, "smtp_host": "x"})
    assert EN._base_url() == EN._LEGACY_DEFAULT_BASE_URL, "升級安裝（已有設定、沒存 base_url）要維持舊行為"
    monkeypatch.setattr(EN, "_cfg", lambda: {"base_url": "https://erp.example.com/"})
    assert EN._base_url() == "https://erp.example.com", "已儲存的值一律優先、不被覆蓋"


def test_frontend_no_longer_hardcodes_the_internal_address():
    html = _read(FRONT / "pages" / "notification-settings.html")
    assert "172.16.10.177" not in html
    assert "location.origin" in html and "baseUrlWarn" in html


def test_email_defaults_base_url_is_empty():
    from routers import system as S
    assert S._EMAIL_DEFAULTS["base_url"] == ""


def test_get_email_notify_reports_whether_this_machine_sends(client, make_user, monkeypatch):
    from helpers import email_notify as EN
    su, sp = make_user(username="b0_su", role="superadmin")
    r = client.post("/api/auth/login", json={"username": su, "password": sp})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    monkeypatch.setattr(EN, "email_send_policy", lambda env=None: (True, "x"))
    assert client.get("/api/settings/email-notify", headers=h).json()["send_allowed_here"] is True
    monkeypatch.setattr(EN, "email_send_policy", lambda env=None: (False, "x"))
    assert client.get("/api/settings/email-notify", headers=h).json()["send_allowed_here"] is False


def test_dev_mode_row_is_hidden_unless_this_machine_does_not_send():
    html = _read(FRONT / "pages" / "notification-settings.html")
    m = re.search(r'<div class="ns-toggle"[^>]*data-testid="ns-dev-mode-row"', html)
    assert m and 'x-show="cfg.dev_mode || cfg.send_allowed_here === false"' in m.group(0)


def test_blocked_send_message_is_plain():
    src = _read(BACK / "helpers" / "email_notify.py")
    assert "_smtp_send_blocked 說明" not in src
