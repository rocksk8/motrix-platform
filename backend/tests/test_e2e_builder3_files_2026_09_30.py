# -*- coding: utf-8 -*-
"""建構器第三輪 S2 — 附件欄（畫面＋DB＋磁碟）：執行頁選檔上傳、清單顯示、移除、存檔綁單；單據檢視列出檔名連結；
建構器的元件列有「附件／圖片」、屬性面板的允許類型落到草稿。"""
import json
import os

import pytest

pytest.importorskip("playwright.sync_api")

from tests._builder_nav import go_step, start_blank  # noqa: E402
from tests._e2e_login import inject_login  # noqa: E402

KEY = "b3fe"


def _q(sql, args=()):
    import db
    conn = db.get_db()
    try:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def _exists(path):
    from helpers import uploads
    return os.path.isfile(os.path.join(uploads.UPLOADS_ROOT, path))


def _module(client, h):
    body = {"name": "附件頁", "permission": "custom." + KEY, "numbering": {"prefix": "FE", "period": "none", "digits": 3},
            "fields": [{"key": "title", "label": "標題", "type": "text", "required": True, "dataClass": "T1"},
                       {"key": "pics", "label": "照片", "type": "image", "maxFiles": 3, "dataClass": "T1"},
                       {"key": "doc", "label": "文件", "type": "file", "accept": ["pdf"], "dataClass": "T1"}],
            "workflow": {"initial": "draft", "states": [{"key": "draft", "label": "草稿"}, {"key": "done", "label": "完成", "final": True}],
                         "transitions": [{"key": "submit", "label": "送出", "from": "draft", "to": "done"}]}}
    assert client.put("/api/definitions/custom_module/%s/draft" % KEY, headers=h, json={"body": body}).json()["problems"] == []
    assert client.post("/api/definitions/custom_module/%s/publish" % KEY, headers=h, json={}).status_code == 200


@pytest.mark.e2e
def test_runtime_upload_list_remove_save_and_view_link(live_server, make_user, new_context, client, tmp_path):
    boss = make_user(username="b3fe_boss", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": boss[0], "password": boss[1]}).json()["token"]
    _module(client, {"Authorization": "Bearer " + tok})
    a = tmp_path / "a.png"
    a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 40)
    b = tmp_path / "b.png"
    b.write_bytes(b"\x89PNG\r\n\x1a\n" + b"2" * 40)

    errors = []
    page = new_context().new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, boss[0], boss[1])
    page.goto(live_server + "/pages/custom-records.html?key=" + KEY)
    page.click("#cr-new")
    page.wait_for_selector('[data-file-field="pics"]', timeout=15000)
    page.fill("#cr-in-title", "含附件")
    page.set_input_files("#cr-in-pics", [str(a), str(b)])
    page.wait_for_selector('[data-file-field="pics"] li', timeout=15000)
    assert page.locator('[data-file-field="pics"] li').count() == 2
    staged = _q("SELECT id, path, record_id FROM custom_record_files WHERE module_key=? ORDER BY uploaded_at, id", (KEY,))
    assert len(staged) == 2 and all(r["record_id"] == 0 and _exists(r["path"]) for r in staged)
    # 移除剛上傳的一張 ⇒ 暫存列與實體檔都刪
    first = staged[0]
    page.click('[data-file-remove="%s"]' % first["id"])
    page.wait_for_function("(id) => !document.querySelector('[data-file-id=\"' + id + '\"]')", arg=first["id"], timeout=10000)
    import time
    deadline = time.time() + 10                                              # 畫面先移除、DELETE 在背景：等到伺服器端終點狀態
    while time.time() < deadline and (_exists(first["path"]) or _q("SELECT 1 FROM custom_record_files WHERE id=?", (first["id"],))):
        page.wait_for_timeout(100)
    assert not _exists(first["path"]) and not _q("SELECT 1 FROM custom_record_files WHERE id=?", (first["id"],))
    # 不收的類型：文件欄只收 pdf ⇒ 選 png 顯示錯誤、沒有多一筆暫存
    page.set_input_files("#cr-in-doc", [str(a)])
    page.wait_for_selector('[data-field-error="doc"]', state="visible", timeout=10000)
    assert len(_q("SELECT 1 FROM custom_record_files WHERE module_key=?", (KEY,))) == 1
    page.click("#cr-save")
    page.wait_for_selector("#cr-record", timeout=15000)
    keep = staged[1]
    rec = _q("SELECT id, data_json FROM custom_records WHERE module_key=?", (KEY,))[0]
    assert json.loads(rec["data_json"])["pics"] == [keep["id"]]
    assert _q("SELECT record_id FROM custom_record_files WHERE id=?", (keep["id"],))[0]["record_id"] == rec["id"]
    # 單據檢視：檔名連結；點開得到簽章連結（新分頁）
    link = page.locator('[data-file-link="%s"]' % keep["id"])
    assert link.inner_text().strip() == "b.png"
    with page.context.expect_page() as newp:
        link.click()
    np_ = newp.value
    np_.wait_for_load_state()
    assert "/api/uploads/custom_records/%s/" % KEY in np_.url and "pt=" in np_.url
    assert not errors, errors


@pytest.mark.e2e
def test_builder_palette_has_file_and_image_and_accept_lands_in_the_draft(live_server, make_user, new_context):
    user = make_user(username="b3fe_builder", role="superadmin")
    ctx = new_context()
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    inject_login(page, live_server, user[0], user[1])
    page.goto(live_server + "/pages/module-builder.html")
    start_blank(page, "b3fe_bld")
    go_step(page, 2)
    assert page.locator('#mb-palette [data-palette-element="file"]').count() == 1
    assert page.locator('#mb-palette [data-palette-element="image"]').count() == 1
    page.click('#mb-palette [data-palette-element="file"]')
    page.wait_for_selector('#mb-props-pane [data-attr="accept"]')
    assert page.locator('#mb-props-pane [data-attr="accept"] [data-ext]').count() == 3        # jpg／png／pdf
    page.check('#mb-props-pane [data-attr="accept"] [data-ext="pdf"]')
    page.fill('#mb-props-pane [data-attr="maxFiles"] input', "4")
    page.wait_for_function("""() => { const e = document.getElementById('mb-save-state');
      return !!e && e.dataset.dirty === '0' && e.dataset.saving === '0' && e.dataset.state === 'saved' }""", timeout=15000)
    rows = _q("SELECT body_json FROM ui_definitions WHERE kind='custom_module' AND key=? AND status='draft'", ("b3fe_bld",))
    f = json.loads(rows[0]["body_json"])["fields"][0]
    assert f["type"] == "file" and f["accept"] == ["pdf"] and f["maxFiles"] == 4
    page.click('#mb-palette [data-palette-element="image"]')
    page.wait_for_selector('#mb-props-pane [data-attr="maxFiles"]')
    assert page.locator('#mb-props-pane [data-attr="accept"]').count() == 0       # 圖片型別沒有「允許類型」（固定 jpg／png）
    assert not errors, errors
