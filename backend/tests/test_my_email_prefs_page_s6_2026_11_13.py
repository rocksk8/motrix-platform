# -*- coding: utf-8 -*-
"""S6（2026-11-13）：我的帳號 → 通知分頁 →「我要收的 Email 通知」的頁面結構（靜態檢查，不開瀏覽器）。
行為由 test_my_email_prefs_s6_2026_11_13.py（API）與 test_e2e_my_email_prefs_s6_2026_11_13.py（瀏覽器）驗。"""
import re

from core.source_tree import page_file as _page_file


def _src():
    return _page_file("my-account.html").read_text(encoding="utf-8")


def _script():
    s = _src()
    a = s.index("function accountEmailPrefs()")
    return s[a:s.index("</script>", a)]


def test_the_matrix_core_is_loaded_by_the_account_page():
    s = _src()
    assert "../css/settings-matrix.css" in s and "../static/settings-matrix.js" in s
    assert s.index("settings-matrix.js") < s.index("function accountEmailPrefs()"), "核心要先於使用它的內嵌腳本載入"


def test_the_email_card_sits_inside_the_notify_tab_before_the_line_card():
    s = _src()
    tab = s.index('data-testid="tab-notify"')
    card = s.index('id="email-prefs-card"')
    line = s.index('id="line-bind-card"')
    assert tab < card < line < s.index('data-testid="tab-profile"'), "Email 卡在通知分頁內、LINE 卡之前"
    tag = s[s.rfind("<div", 0, card):s.index(">", card)]
    assert 'x-data="accountEmailPrefs()"' in tag and 'data-testid="email-prefs"' in tag
    assert "tab === 'notify'" in tag and "!wiz" in tag, "只在進入通知分頁（且不在首次設定精靈裡）時才載入"
    assert 'id="ep-box"' in s and 'data-testid="ep-matrix"' in s


def test_the_card_talks_to_the_self_service_endpoint_only():
    js = _script()
    assert "/api/mail-types/mine" in js
    assert "/api/users/" not in js, "本人頁面不走管理員代設定的入口"
    assert "method: 'PUT'" in js


def test_save_is_a_draft_with_cas_and_a_server_enforced_confirm():
    js = _script()
    assert "draft: {" in js and "confirm: confirmSave" in js and "save: save" in js, "草稿模式：按儲存才寫入"
    assert "expect: version" in js, "帶版本，別人（管理員）改過就要重讀"
    assert re.search(r"confirm:\s*lastRisky\.length\s*>\s*0\s*&&\s*!!ctx\.confirmed", js), "高影響項目要使用者在視窗按過確認才帶 confirm=true"
    assert "preview: true" in js, "儲存前先問伺服器實際會變哪些／哪些是高影響"


def test_non_business_rows_cannot_be_batch_selected():
    js = _script()
    assert "selectable: !!it.lowRisk" in js and "selectableReason" in js
    assert "不能批次" in js


def test_dynamic_text_is_escaped():
    js = _script()
    assert "SettingsMatrix.esc" in js
    assert "esc(n)" in js and "esc(e.message)" in js, "確認視窗與錯誤訊息裡的動態文字要先跳脫"
    assert "raw: true" not in js and "SettingsMatrix.raw" not in js, "這一頁沒有需要放原始 HTML 的欄位"


def test_empty_hint_is_line_specific_and_the_line_card_is_untouched():
    s = _src()
    hint = s[s.index('data-testid="notify-empty-hint"'):]
    hint = hint[:hint.index("</div>\n      </div>")]
    assert "LINE" in hint and "目前沒有可以自己設定的通知" not in hint, "Email 卡永遠在，空狀態說明只談 LINE"
    assert "lineBindCard()" in s and 'data-testid="line-prefs"' in s


def test_the_admin_proxy_page_still_edits_notification_muted():
    u = _page_file("users.html").read_text(encoding="utf-8")
    assert "notification_muted" in u or "notificationMuted" in u
