# -*- coding: utf-8 -*-
"""瀏覽器端對端：系統設定 → 儲存位置（CORE-SPEC 裁示表「儲存位置可設定」；A，2026-09-28）。

- 交付資料夾不存在 ⇒ 儲存被擋、錯誤顯示在那一欄、出現「建立」＋權限提醒 ⇒ 按建立 ⇒ 資料夾真的建了 ⇒ 再儲存 ⇒ 資料庫落地。
- 個資資料夾放在雲端存檔根目錄裡 ⇒ 畫面說明原因、資料庫不變。
觀測點：資料庫（system_settings）、磁碟、錯誤列的 DOM 文字；等待的是按鈕 busy 解除與 DOM 出現，不看 Alpine 模型。
全部用 tmp 目錄；不碰真實雲端資料夾。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")

from tests._e2e_login import inject_login  # noqa: E402


def _stored():
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT value_json FROM system_settings WHERE key='storage_locations'").fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()


def _open(live_server, make_user, new_context, name):
    sa = make_user(username=name, role="superadmin")
    page = new_context().new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, *sa)
    page.goto(live_server + "/pages/storage-settings.html")
    page.locator('[data-testid="st-now-archive_root"]').wait_for(timeout=20000)
    page.wait_for_function("() => document.querySelector('[data-testid=\"st-now-archive_root\"]').textContent.length > 0")
    return page, errors


@pytest.mark.e2e
def test_missing_delivery_folder_is_explained_created_on_request_then_saved(live_server, make_user, new_context, tmp_path):
    from helpers import storage_locations as SL
    SL.invalidate()
    target = tmp_path / "MOTRIX-交付"
    page, errors = _open(live_server, make_user, new_context, "st_e2e_sa")
    page.fill('[data-testid="st-in-delivery_root"]', str(target))
    page.click('[data-testid="st-save"]')
    err = page.locator('[data-testid="st-field-err-delivery_root"]')
    err.wait_for(state="visible", timeout=15000)
    assert "不存在" in err.text_content()
    assert page.locator('[data-testid="st-err"]').is_visible()
    assert _stored() is None and not target.exists()
    create = page.locator('[data-testid="st-create-delivery_root"]')
    assert create.is_visible()
    create.click()
    done = page.locator('[data-testid="st-created-delivery_root"]')
    done.wait_for(state="visible", timeout=15000)
    assert "共用權限" in done.text_content() and target.is_dir()
    page.click('[data-testid="st-save"]')
    page.locator('[data-testid="st-ok"]').wait_for(state="visible", timeout=15000)
    assert _stored() == {"archive_root": "", "pii_root": "", "delivery_root": str(target)}
    assert "依設定" in page.text_content('[data-testid="st-now-delivery_root"]')
    assert not errors, errors


@pytest.mark.e2e
def test_pii_inside_the_archive_root_is_refused_on_screen(live_server, make_user, new_context, tmp_path):
    from helpers import storage_locations as SL
    SL.invalidate()
    root = tmp_path / "系統存檔"
    (root / "個資").mkdir(parents=True)
    page, errors = _open(live_server, make_user, new_context, "st_e2e_sa2")
    page.fill('[data-testid="st-in-archive_root"]', str(root))
    page.fill('[data-testid="st-in-pii_root"]', str(root / "個資"))
    page.click('[data-testid="st-save"]')
    err = page.locator('[data-testid="st-field-err-pii_root"]')
    err.wait_for(state="visible", timeout=15000)
    assert "互相包含" in err.text_content()
    assert _stored() is None, "沒通過就不存"
    assert not page.locator('[data-testid="st-create-pii_root"]').is_visible(), "資料夾存在時不提供「建立」"
    assert not errors, errors
