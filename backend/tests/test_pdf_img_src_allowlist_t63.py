"""T63 SHOULD-5：PDF 的 `<img src>` 只放行 data:image/(png|jpeg|gif|webp);base64。
儲存的圖片欄位（存簿／身分證／傳票快照）寫入路徑不全有檢查（承攬商 POST/PUT 的 data.bankPassbookImage 是原樣存），
渲染時一律過 `safe_img_src`。"""
import re

import pytest

from helpers.doc_template import safe_img_src

OK = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


@pytest.mark.parametrize("val", [OK, "data:image/png;base64,iVBOR==", "DATA:IMAGE/WEBP;base64,AAAA", "data:image/gif;base64,R0lG"])
def test_data_image_passes(val):
    assert safe_img_src(val) == val


@pytest.mark.parametrize("val", [
    "file:///C:/Windows/win.ini", "file:///D:/secret.png", "http://127.0.0.1:8000/i.png", "https://evil.example/x.png",
    "//evil/x.png", "uploads/a.png", "C:\\a.png", "data:image/svg+xml;base64,PHN2Zz4=", "data:text/html;base64,PGI+",
    'data:image/png;base64,AA" onerror="x', "data:image/png;base64,AA'><script>", "javascript:alert(1)", "", None, 123,
])
def test_everything_else_dropped(val):
    assert safe_img_src(val) == ""


def _no_unsafe_img(html):
    return [m for m in re.findall(r'<img src="([^"]*)"', html) if m and not m.startswith("data:image/")]


def test_payslip_attachments_drop_file_src():
    import pdf_gen
    evil = "file:///C:/Windows/win.ini"
    d = {"contractorName": "甲", "slipNo": "S1", "_bank_passbook": evil, "_id_card_front": evil, "_id_card_back": OK}
    html = pdf_gen._payslip_passbook_html(d) + pdf_gen._payslip_id_card_html(d)
    assert "file:" not in html and OK in html
    assert _no_unsafe_img(html) == []
