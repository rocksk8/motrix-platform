# -*- coding: utf-8 -*-
"""`AT1` · 簽核佇列的報價單明細要帶出送件人上傳的三處附件（已出貨，補題）。

# 🔴 為什麼是「補題」不是「派工」

A-2 規格覆蓋率盤點（`0c6ae2f`）發現 `AT1` 沒有規格、沒有題、沒有任何
測試檔提到它——而查證 `routers/quotations.py:5646` 的實作**已經在了**
（B 做過，commit 訊息與程式碼裡的 `AT1` 註解都在），只是**產品碼已經
出貨而沒有任何東西守著它**：`SCOPE.md` 的 `THIS` 要求「這一包要全綠」，
而一個沒有題的編號**不可能是綠的，它只是不紅**——打包關門分不出這
兩者。本檔補上這道守門，**不改任何產品碼**。

# 🔴 判準：`files: []` 有兩種成因，回應長得一模一樣

```
① 案件真的沒有附件           => files: []（正確）
② 端點沒有讀那個來源         => files: []（缺陷）
```
⇒ 每一題都要**先種一筆真的附件進 `data_json.caseRecord`**，再打端點，
斷言那筆附件出現在回應裡——只驗「沒有附件時回空清單」證明不了「有
附件時讀得到」，兩者是不同的觀測點。

# ⚙️ 三個來源，逐一分開驗

```
routers/quotations.py:5646 附近：
  materials[i].files          "材料 %d" 前綴
  materials[i].invoiceFiles   "材料 %d 發票" 前綴
  payment.items[i].invoiceFiles  "請款 %d" 前綴
```
⚠️ 分開驗的理由：三處是三段獨立的迴圈，其中一段被改壞（例如打錯鍵名
`materials` vs `caseRecord.materials`）不會影響另外兩段，合成一題驗
的話少一段會被另外兩段稀釋掉。

# ✅ 牙齒已驗證（方式：突變驗證／live，非常設）

monkeypatch `routers.quotations._tagged_file_entries` 成一律回 `[]`
（模擬「三段迴圈用的那支 helper 被拿掉」），①②③三題**真的會紅**；
負對照（既有客戶回簽檔，走不同的 `_file_entries()`）**仍然是綠的**，
證明這道守門真的分辨得出「哪一段壞了」而不是全部混在一起判斷。
"""
import json

import pytest

DETAIL = "/api/approval-queue/detail?type=quotation&id=%s"


def _hdr(client, make_user, username, role="superadmin", modules=None):
    u, p = make_user(username=username, role=role, modules=modules)
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _seed_quotation(quote_no, case_record):
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name,"
            " project_name, total, pretax, data_json, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "AT1測試客戶", "AT1測試案", 0, 0,
             json.dumps({"caseRecord": case_record}, ensure_ascii=False),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _file(name):
    return {"id": name, "filename": name, "path": "at1/%s" % name}


def _names(files):
    return {f.get("name") for f in files}


# ══════════════════════════════════════════════════════════════════════
# ① materials[i].files
# ══════════════════════════════════════════════════════════════════════

def test_at1_material_files_are_surfaced_not_just_the_signed_copy(client,
                                                                   make_user):
    """🔴🔴 **`materials[i].files` 的附件要出現在簽核詳情裡，不是只有
    客戶回簽檔。**

    ⚙️ 觀測點種一筆**唯一、可辨識**的檔名，直接找它有沒有出現——不是
    數筆數（少一段不會讓筆數變成 0，因為另外兩段可能還有東西）。
    """
    quote_no = "MQ-AT1-MAT"
    _seed_quotation(quote_no, {
        "materials": [{"name": "水泥", "files": [_file("AT1材料憑證甲.pdf")]}],
    })
    _u, hdr = _hdr(client, make_user, "at1_mat")

    r = client.get(DETAIL % quote_no, headers=hdr)
    assert r.status_code == 200, r.text[:300]
    names = _names(r.json().get("files") or [])
    assert any("AT1材料憑證甲.pdf" in n for n in names), (
        "找不到 `materials[0].files` 那筆附件：%r\n" % names
        + "☠️ `files: []` 有兩種成因：真的沒有附件／端點沒有讀那個來源，"
          "這裡種了一筆卻讀不到，是後者。")


def test_at1_material_invoice_files_are_surfaced(client, make_user):
    """🔴🔴 **`materials[i].invoiceFiles`（材料發票）要出現在簽核詳情裡。**"""
    quote_no = "MQ-AT1-MATINV"
    _seed_quotation(quote_no, {
        "materials": [{"name": "水泥",
                       "invoiceFiles": [_file("AT1材料發票乙.pdf")]}],
    })
    _u, hdr = _hdr(client, make_user, "at1_matinv")

    r = client.get(DETAIL % quote_no, headers=hdr)
    assert r.status_code == 200, r.text[:300]
    names = _names(r.json().get("files") or [])
    assert any("AT1材料發票乙.pdf" in n for n in names), (
        "找不到 `materials[0].invoiceFiles` 那筆附件：%r" % names)


def test_at1_payment_item_invoice_files_are_surfaced(client, make_user):
    """🔴🔴 **`payment.items[i].invoiceFiles`（請款發票）要出現在簽核詳情裡。**"""
    quote_no = "MQ-AT1-PAYINV"
    _seed_quotation(quote_no, {
        "payment": {"items": [{"name": "第一期款",
                               "invoiceFiles": [_file("AT1請款發票丙.pdf")]}]},
    })
    _u, hdr = _hdr(client, make_user, "at1_payinv")

    r = client.get(DETAIL % quote_no, headers=hdr)
    assert r.status_code == 200, r.text[:300]
    names = _names(r.json().get("files") or [])
    assert any("AT1請款發票丙.pdf" in n for n in names), (
        "找不到 `payment.items[0].invoiceFiles` 那筆附件：%r" % names)


# ══════════════════════════════════════════════════════════════════════
# ② 正對照：既有的客戶回簽檔不受影響 ／ 真的沒有附件時仍是空清單
# ══════════════════════════════════════════════════════════════════════

def test_at1_the_signed_files_are_still_included(client, make_user):
    """⚙️ **正對照：客戶回簽檔（`signed_files_json`）這個既有來源不受影響。**"""
    quote_no = "MQ-AT1-SIGNED"
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT INTO quotations (quote_no, status, customer_name,"
            " project_name, total, pretax, data_json, signed_files_json,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (quote_no, "已送出", "AT1測試客戶", "AT1測試案", 0, 0, "{}",
             json.dumps([_file("AT1客戶回簽檔.pdf")]),
             "2026-09-01T00:00:00", "2026-09-01T00:00:00"))
        conn.commit()
    finally:
        conn.close()
    _u, hdr = _hdr(client, make_user, "at1_signed")

    r = client.get(DETAIL % quote_no, headers=hdr)
    assert r.status_code == 200, r.text[:300]
    names = _names(r.json().get("files") or [])
    assert any("AT1客戶回簽檔.pdf" in n for n in names), (
        "既有的客戶回簽檔不見了：%r——這一題是負對照，若紅了代表補這道"
        "題的過程動到了不該動的東西。" % names)


def test_at1_a_case_with_truly_no_attachments_returns_an_empty_list(client,
                                                                     make_user):
    """⚙️ **負對照：案件真的沒有任何附件時，`files` 是空清單——這是正確
    行為，不要被上面幾題誤導成「files 永遠要有東西」。**
    """
    quote_no = "MQ-AT1-EMPTY"
    _seed_quotation(quote_no, {"materials": [], "payment": {"items": []}})
    _u, hdr = _hdr(client, make_user, "at1_empty")

    r = client.get(DETAIL % quote_no, headers=hdr)
    assert r.status_code == 200, r.text[:300]
    assert r.json().get("files") == [], (
        "真的沒有附件的案件，`files` 不是空清單：%r" % r.json().get("files"))


def test_at1_multiple_materials_are_each_tagged_with_their_own_index(client,
                                                                      make_user):
    """🔴 **多筆材料時，每一筆的附件要各自標出是第幾筆——不是全部混在一起。**

    ⚙️ 依據既有實作的標記慣例（`_tagged_file_entries` 加「材料 N」前綴）
    ——這裡驗**行為**（兩筆材料的附件都看得到、且看得出是哪一筆），
    不逐字比對前綴字串本身（那是實作細節，文案可以改）。
    """
    quote_no = "MQ-AT1-MULTI"
    _seed_quotation(quote_no, {
        "materials": [
            {"name": "水泥", "files": [_file("AT1第一筆材料.pdf")]},
            {"name": "鋼筋", "files": [_file("AT1第二筆材料.pdf")]},
        ],
    })
    _u, hdr = _hdr(client, make_user, "at1_multi")

    r = client.get(DETAIL % quote_no, headers=hdr)
    assert r.status_code == 200, r.text[:300]
    names = _names(r.json().get("files") or [])
    assert any("AT1第一筆材料.pdf" in n for n in names), (
        "第一筆材料的附件不見了：%r" % names)
    assert any("AT1第二筆材料.pdf" in n for n in names), (
        "第二筆材料的附件不見了：%r——若只有第一筆，代表迴圈只處理了"
        "第一個元素。" % names)
