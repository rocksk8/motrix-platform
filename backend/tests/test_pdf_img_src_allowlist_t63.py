"""T63 SHOULD-5：PDF 的 `<img src>` 只放行 data:image/(png|jpeg|gif|webp);base64（整串比對）；不合格 ⇒ 不輸出 <img> 標籤。
儲存的圖片欄位（存簿／身分證／傳票快照）寫入路徑不全有檢查，渲染時一律過 `img_tag`／`safe_img_src`。"""
import re

import pytest

from helpers.doc_template import img_tag, is_safe_img_value, safe_img_src

OK = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="
PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"


@pytest.mark.parametrize("val", [OK, PNG, "DATA:IMAGE/WEBP;base64,AAAA", "data:image/gif;base64,R0lG"])
def test_data_image_passes(val):
    assert is_safe_img_value(val) and safe_img_src(val) == val


@pytest.mark.parametrize("val", [
    "file:///C:/Windows/win.ini", "file:///D:/secret.png", "http://127.0.0.1:8000/i.png", "https://evil.example/x.png",
    "//evil/x.png", "uploads/a.png", "C:\a.png", "data:image/svg+xml;base64,PHN2Zz4=", "data:text/html;base64,PGI+",
    'data:image/png;base64,AA" onerror="x', "data:image/png;base64,AA'><script>", "javascript:alert(1)", "", None, 123, [], {},
    "data:image/png;charset=utf-8;base64,AAAA",                 # 有 ;charset= 參數
    "data:image/png;base64,AA\x00AA", "data:image/png;base64,AAAA\x00",   # NUL
    "\ndata:image/png;base64,AAAA", "data:image/png;base64,AAAA\n", " data:image/png;base64,AAAA", "data:image/png;base64,AA\nAA",
    "data:image/png;base64,AAAA\r\n",
    "data:image/png;baſe64,AAAA", "data:image/png;base64,AAAA\u212a",   # ſ（長 s）／ K（Kelvin sign）Unicode 折疊
    "data:ımage/png;base64,AAAA", "data:image/pnɡ;base64,AAAA", "data:image/png;base64,ＡＡＡＡ",   # 全形／相似字
])
def test_everything_else_dropped(val):
    assert not is_safe_img_value(val) and safe_img_src(val) == "" and img_tag(val, "x:y") == ""


def test_img_tag_legit_shape():
    assert img_tag(OK, "max-width:1px") == '<img src="%s" style="max-width:1px">' % OK


def _bad_imgs(html):
    return [m for m in re.findall(r'<img\b[^>]*>', html) if 'src="data:image/' not in m]


def test_payslip_attachments_drop_file_src():
    import pdf_gen
    evil = "file:///C:/Windows/win.ini"
    d = {"contractorName": "甲", "slipNo": "S1", "_bank_passbook": evil, "_id_card_front": evil, "_id_card_back": OK}
    html = pdf_gen._payslip_passbook_html(d) + pdf_gen._payslip_id_card_html(d)
    assert "file:" not in html and OK in html
    assert _bad_imgs(html) == [] and 'src=""' not in html
    only_evil = pdf_gen._payslip_passbook_html(d) + pdf_gen._payslip_id_card_html(dict(d, _id_card_back=""))
    assert "<img" not in only_evil                              # 全部不合格 ⇒ 一個 <img> 都沒有


@pytest.mark.parametrize("evil", ["file:///C:/Windows/win.ini", "http://127.0.0.1/x.png", 'x" onerror="alert(1)', "data:image/svg+xml;base64,PHN2Zz4="])
def test_contractor_voucher_builder_drops_evil(client, evil):
    """:1585（外包人員 passbook）與 :1723（承攬商 bankPassbookImage）兩個 sink。"""
    import pdf_gen
    v = {"voucherNo": "CV-T63", "status": "已核准", "vendorName": "乙", "bankPassbookImage": evil,
         "personnel": [{"name": "丙", "bankAccountNumber": "123", "bankPassbookImage": evil}]}
    html = pdf_gen._build_contractor_voucher_html(v)
    assert "<img" not in html and "file:" not in html and "onerror" not in html
    good = pdf_gen._build_contractor_voucher_html(dict(v, bankPassbookImage=PNG, personnel=[dict(v["personnel"][0], bankPassbookImage=OK)]))
    assert 'src="%s"' % PNG in good and 'src="%s"' % OK in good and _bad_imgs(good) == []
