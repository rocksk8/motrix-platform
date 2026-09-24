"""瀏覽器端對端：案件頁的單筆操作以項目 id 定位（CM2，2026-09-24）。

API 層見 test_case_item_by_id_2026_09_24.py。這裡驗頁面真的帶了 itemId、且新增未存的
那一列在上傳前會先存檔（否則伺服器上沒有那一列）。觀測點打在資料庫落地值。
"""
import json

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright

from tests.test_e2e_case_concurrent_edit_2026_09_24 import (  # noqa: F401  (live_server 是 fixture)
    DATA_JS, NO, _cr, _open, _seed, live_server,
)

UPLOAD_JS = f"""async (idx) => {{
  const c = {DATA_JS}
  const f = new File([new Uint8Array([0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A])], 'inv.png', {{ type: 'image/png' }})
  await c.uploadPaymentItemInvoiceFiles(idx, {{ target: {{ files: [f], value: '' }} }})
}}"""


def _reverse_payment_items_in_db():
    import db
    conn = db.get_db()
    try:
        d = json.loads(conn.execute("SELECT data_json FROM quotations WHERE quote_no=?", (NO,)).fetchone()[0])
        d["caseRecord"]["payment"]["items"].reverse()
        conn.execute("UPDATE quotations SET data_json=? WHERE quote_no=?", (json.dumps(d, ensure_ascii=False), NO))
        conn.commit()
    finally:
        conn.close()


@pytest.mark.e2e
def test_upload_after_server_reorder_lands_on_the_item_on_screen(live_server, make_user):
    a = make_user(username="byid_e1", role="admin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pa = _open(browser, live_server, a)
            _reverse_payment_items_in_db()          # 畫面上第 0 列是 id=1，伺服器上已是 id=2
            pa.evaluate(UPLOAD_JS, 0)
            items = {it["id"]: it for it in _cr()["payment"]["items"]}
            assert len(items[1].get("invoiceFiles") or []) == 1, "發票掛到別期了"
            assert not items[2].get("invoiceFiles")
        finally:
            browser.close()


@pytest.mark.e2e
def test_upload_on_new_unsaved_item_saves_first(live_server, make_user):
    a = make_user(username="byid_e2", role="admin")
    _seed()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            pa = _open(browser, live_server, a)
            new_id = pa.evaluate(f"""() => {{
              const c = {DATA_JS}
              c.addPaymentItem()
              const items = c.cr.caseRecord.payment.items
              return items[items.length - 1].id
            }}""")
            idx = pa.evaluate(f"() => {DATA_JS}.cr.caseRecord.payment.items.length - 1")
            pa.evaluate(UPLOAD_JS, idx)
            items = {it["id"]: it for it in _cr()["payment"]["items"]}
            assert new_id in items, "上傳前沒有先存檔"
            assert len(items[new_id].get("invoiceFiles") or []) == 1
        finally:
            browser.close()
