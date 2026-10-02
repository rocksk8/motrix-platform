# -*- coding: utf-8 -*-
"""31-B S5：分期匯款申請的 PDF 帶款別／期別／本期稅前與該期發票號碼；舊式整筆申請的版面不變（沒有款別列、發票號碼仍讀派發的）。
反向控制：舊式整筆即使列上有 inv_no 也不顯示（它的發票在派發上）。"""
import json


def _row(**kw):
    base = {"voucher_no": "PV-1", "quote_no": "MQ-1", "status": "已核准", "is_paid": 0, "created_by": "x", "created_at": "2026-10-02T00:00:00",
            "snapshot_json": json.dumps({"vendorName": "測試承攬商", "invoiceNo": "DISP-INV", "grandTotal": 315}), "data_json": "{}"}
    base.update(kw)
    return base


def test_installment_pdf_shows_kind_period_pretax_and_its_own_invoice_number(client):
    import pdf_gen
    v = pdf_gen._contractor_voucher_dict(_row(kind="deposit", kind_name="訂金款", seq=1, pretax_amount=300, inv_no="AB-12345678", inv_date="2026-10-05"))
    assert v["kind"] == "deposit" and v["seq"] == 1 and v["pretaxAmount"] == 300 and v["invNo"] == "AB-12345678"
    html = pdf_gen._build_contractor_voucher_html(v)
    assert "款別／期別" in html and "訂金款" in html and "第 1 期" in html and "本期稅前 300" in html
    assert "AB-12345678" in html and "DISP-INV" not in html                          # 分期顯示該期發票，不顯示派發的


def test_whole_voucher_pdf_is_unchanged(client):
    import pdf_gen
    v = pdf_gen._contractor_voucher_dict(_row(inv_no="SHOULD-NOT-SHOW"))
    assert v["kind"] == ""
    html = pdf_gen._build_contractor_voucher_html(v)
    assert "款別／期別" not in html and "DISP-INV" in html and "SHOULD-NOT-SHOW" not in html
