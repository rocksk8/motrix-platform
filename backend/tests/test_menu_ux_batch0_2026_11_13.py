"""選單去工程師化 批 0（2026-11-13）：稱呼統一、預設系統網址、開發機測試模式顯示條件、載入失敗白話提示、改名不留舊稱。

守的是「畫面上不再看到工程師字眼」這件事本身，不是某個字串的拼法：
  ① 使用者看得到的檔案（前端頁面、選單與總覽卡資料）不再出現「超級管理員／最高管理員」（統一為「最高管理者」）。
  ② 新安裝不預填任何一台機器的內部位址；升級安裝（資料庫已有設定）維持舊行為。
  ③ （五頁載入失敗提示已拿掉，改由 hichan-2 的 motrix-error.js 統一處理）
  ④ 選單／總覽卡的舊名稱（Schema 狀態、刪除暫存區、在線時數統計、稽核頁的「歷史紀錄」）已換掉。
"""
import json
import pathlib
import re

import pytest

from core import source_tree
from tests import _frontend_sources as FS

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONT = ROOT / "frontend"
BACK = ROOT / "backend"


def _read(p):
    return pathlib.Path(p).read_text(encoding="utf-8")


def _page(name):
    """頁面位置一律經 core.source_tree（頁面可能住在模組的 pages/ 底下）。"""
    return source_tree.page_file(name)


def test_visible_files_never_say_old_admin_titles():
    bad = []
    for p in list(source_tree.page_files()) + list(FS.all_js()) + [BACK / "core" / "menu_l1.json", BACK / "core" / "system_hub_l1.json"] + list((BACK / "modules").glob("*/module.json")):
        t = _read(p)
        for old in ("超級管理員", "最高管理員", "超管"):
            if old in t:
                bad.append("%s 含「%s」" % (p.relative_to(ROOT).as_posix(), old))
    assert not bad, "使用者可見稱呼請統一寫「最高管理者」：\n" + "\n".join(bad)


def _shown_strings(obj):
    """選單／總覽卡資料裡『會顯示給人看』的欄位值（label／title／name／desc／impact）；keywords 不算（舊名放在關鍵字讓人還搜得到，是刻意的）。"""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("label", "title", "name", "desc", "impact") and isinstance(v, str):
                out.append(v)
            else:
                out += _shown_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _shown_strings(v)
    return out


@pytest.mark.parametrize("old", ["Schema 狀態", "刪除暫存區", "在線時數統計"])
def test_old_menu_names_are_gone_from_shown_text_but_kept_as_search_keywords(old):
    shown, kws = [], []
    for p in [BACK / "core" / "menu_l1.json", BACK / "core" / "system_hub_l1.json"] + list((BACK / "modules").glob("*/module.json")):
        data = json.loads(_read(p))
        shown += _shown_strings(data)
        kws.append(_read(p))
    assert not [s for s in shown if old in s], "%s 仍出現在顯示文字" % old
    assert any(('"keywords"' in t and old in t) for t in kws), "舊名 %s 應保留在 keywords，讓舊名也搜得到" % old


def test_audit_page_is_called_operation_log():
    menu = json.loads(_read(BACK / "core" / "menu_l1.json"))
    txt = json.dumps(menu, ensure_ascii=False)
    assert "操作紀錄" in txt and '"歷史紀錄"' not in txt
    assert "<title>操作紀錄" in _read(_page("audit-log.html"))



def test_online_stats_has_no_literal_markdown_stars():
    assert "**" not in _read(_page("online-stats.html"))


def test_recycle_bin_reason_is_marked_required_and_blocks_the_button():
    html = _read(_page("recycle-bin.html"))
    assert "原因（選填）" not in html and "原因（必填" in html
    assert "!ap.reason_text" in html


def test_planned_cards_do_not_show_train_codes():
    html = _read(_page("settings-center.html"))
    assert "預計 ' + p.plannedTrain" not in html and "版提供" not in html


# ── 預設系統網址 ────────────────────────────────────────────────────────────────
def test_base_url_key_presence_decides_not_truthiness(monkeypatch):
    """H1（hichan-6 審查）：新安裝存過空 base_url ⇒ 就是空，不可退回舊內部位址；只有「升級前存的舊設定、根本沒有 base_url 這個鍵」才沿用舊預設。"""
    from helpers import email_notify as EN
    monkeypatch.setattr(EN, "_cfg", lambda: {})
    assert EN._base_url() == "", "全新安裝不可預填內部位址"
    monkeypatch.setattr(EN, "_cfg", lambda: {"enabled": True, "smtp_host": "x"})
    assert EN._base_url() == EN._LEGACY_DEFAULT_BASE_URL, "升級前存的舊設定（沒有 base_url 鍵）要維持舊行為"
    monkeypatch.setattr(EN, "_cfg", lambda: {"enabled": True, "base_url": ""})
    assert EN._base_url() == "", "有這個鍵、值是空 ⇒ 空（不退回舊預設）"
    monkeypatch.setattr(EN, "_cfg", lambda: {"base_url": "https://erp.example.com/"})
    assert EN._base_url() == "https://erp.example.com", "已儲存的值一律優先、不被覆蓋"


def test_fresh_install_saving_an_empty_base_url_keeps_it_empty(client, make_user):
    """新安裝實際走一遍：PUT 存一個空的 base_url，之後信件用的網址仍是空字串（不是舊內部位址）。"""
    from helpers import email_notify as EN
    su, sp = make_user(username="b0_su2", role="superadmin")
    h = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": su, "password": sp}).json()["token"]}
    r = client.put("/api/settings/email-notify", json={"enabled": False, "base_url": ""}, headers=h)
    assert r.status_code == 200, r.text
    assert EN._base_url() == ""
    assert client.get("/api/settings/email-notify", headers=h).json()["base_url"] == ""


def _notif_page_src():
    """通知設定頁＋從它抽出去的寄信卡元件（批次 3：static/email-setup.js）。"""
    return _read(FRONT / "pages" / "notification-settings.html") + _read(FRONT / "static" / "email-setup.js")


def test_frontend_no_longer_hardcodes_the_internal_address():
    html = _notif_page_src()
    assert "172.16.10.177" not in html
    assert "location.origin" in html and "baseUrlWarn" in html


def test_email_defaults_base_url_is_empty():
    from routers import system as S
    assert S._EMAIL_DEFAULTS["base_url"] == ""


def test_dev_mode_toggle_always_lives_in_the_collapsed_dev_section():
    """M1：不用環境判斷顯示／隱藏（那樣寫反了）；一律放進預設收合的「開發用設定」區，且回應不再多帶 send_allowed_here。"""
    html = _notif_page_src()
    m = re.search(r'<details data-testid="ns-dev-section"[^>]*>(.*?)</details>', html, re.S)
    assert m and 'data-testid="ns-dev-mode-row"' in m.group(1) and "chk-dev-mode" in m.group(1)
    assert " open" not in m.group(0).split(">")[0], "預設要收合"
    assert "send_allowed_here" not in html
    assert "send_allowed_here" not in _read(BACK / "routers" / "system.py")


def test_empty_base_url_has_a_plain_hint_and_the_private_check_parses_ips():
    html = _notif_page_src()
    assert "信件裡的按鈕會沒有連結" in html
    assert "10\." not in html or "o[0] === 10" in html            # 不再用 /^(10\.…)/ 前綴比對（會誤報 10.example.com）
    assert "o[0] === 100 && o[1] >= 64 && o[1] <= 127" in html       # 100.64.0.0/10
    assert "local|lan|internal" in html                              # .local／.lan 之類內部名稱
    assert "!/^(localhost|127" in html                               # 用 localhost 開頁時不預填


def test_blocked_send_message_is_plain():
    src = _read(BACK / "helpers" / "email_notify.py")
    assert "_smtp_send_blocked 說明" not in src


def test_role_keys_are_not_shown_as_labels():
    users = _read(_page("users.html"))
    for k in ("superadmin", "admin", "sales", "engineer", "finance", "viewer"):
        assert ('letter-spacing:.05em">%s</div>' % k) not in users, k
    assert "（僅 superadmin 可修改" not in _read(_page("cashier.html"))
    ns = _notif_page_src()
    assert "為 admin 或 superadmin 帳號" not in ns and "<strong>superadmin</strong>" not in ns


def test_role_codes_are_never_printed_on_screen():
    """儀表板右上「登入身分」、職責角色清單、選單／按鈕預覽：一律走中文名（MotrixRole.label／roleLabel），不直接印 role 代碼。"""
    idx = _read(FRONT / "index.html")
    assert "' · ' + (session.role || '')" not in idx and "MotrixRole.label(session.role)" in idx
    assert "static/role-label.js" in idx
    dr = _read(_page("duty-roles.html"))
    assert 'x-text="u.role"' not in dr and "MotrixRole.label(u.role)" in dr and "static/role-label.js" in dr
    assert "st.preview.role + '）" not in _read(FRONT / "static" / "menu-editor.js")
    assert "previewResult.role + " not in _read(FRONT / "static" / "user-buttons.js")
    js = _read(FRONT / "static" / "role-label.js")
    for code, zh in (("superadmin", "最高管理者"), ("finance", "財務"), ("admin", "管理員")):
        assert "%s: '%s'" % (code, zh) in js
