# -*- coding: utf-8 -*-
"""`JV9`／`JV10`／`JV11`（`STATE.md §224`）。

# 🔴 `JV9` 是一行 bug，而**題要釘修法不是症狀**

```
helpers/settings.py:17   _get_setting() **已經 json.loads 過** => 回的是物件
helpers/voucher_pdf.py:82 又 loads 一次 => TypeError
                          => **被 except Exception 吞掉** => 印「（尚未設定公司抬頭）」
```
⚙️ A ast 掃 366 檔：**孤例 1 處**（正對照通過）。
⇒ 三格：
```
(a) 有設定時 PDF 上**不可以**出現「尚未設定公司抬頭」
(b) 🔴 TypeError／ValueError **要留下 log**
    ☠️ 只做 (a) 的話，「把 except 改成吞得更徹底」也會綠 ——
       **而下一個同類 bug 就再也查不到了**
(c) 正對照：設定真的**沒有** name 時，那句話**要出現**（它是對的行為）
```

# 🔴 `JV11`：**閘門在後端**

```
❌ 只驗前端按鈕不見了  => 任何人打端點照樣拿得到未簽核的傳票 PDF
✅ 直接打端點
```
⚠️ 而擋下來的訊息要說得出**還差誰簽／現在第幾關**，不是一句「不可匯出」。
☠️ 而**預覽**與**匯出**不可混：
```
預覽  **隨時可看**（帶紅字浮水印）
匯出  簽核通過才可以
```
🔑 混在一起的後果是「還沒簽核的單連看都看不到」—— 而**看是為了檢查**。
"""
import pathlib
import re

import pytest

PDF = "/api/vouchers/%s/pdf-download"

#: `JV9` 的那句話 —— 它是**沒有設定時**的正確輸出。
NO_ORG = "尚未設定公司抬頭"

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _create(client, hdr):
    r = client.post("/api/vouchers", headers=hdr,
                    json={"summary": "匯出閘門測試", "lines": _LINES})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    return r.json()["id"]


def _set_company(name):
    import db
    import json as _json
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value)"
            " VALUES ('company_profile', ?)",
            (_json.dumps({"name": name}),))
        conn.commit()
    finally:
        conn.close()


def _pdf_text(body):
    """PDF 上印出來的文字，`NFKC` 正規化（Edge 會把漢字寫成康熙部首）。"""
    import io
    import unicodedata
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(body))
    return unicodedata.normalize(
        "NFKC", "\n".join((p.extract_text() or "") for p in reader.pages))


# ══════════════════════════════════════════════════════════════════════
# JV9：公司抬頭讀不到
# ══════════════════════════════════════════════════════════════════════

def test_jv9_a_configured_company_name_reaches_the_pdf(client, make_user):
    """🔴 **`JV9(a)`：設定了抬頭，PDF 上就不可以印「尚未設定公司抬頭」。**

    ```
    _get_setting() 已經 loads 過 => 回物件
    voucher_pdf.py:82 又 loads 一次 => TypeError => 被 except 吞掉 => 印那句話
    ```
    🔑 使用者設定過了，而**每一張傳票印出來都說他沒設定** ——
      他會再去設定一次，然後再一次。
    """
    _set_company("摩崔思股份有限公司")
    _u, hdr = _hdr(client, make_user, "jv9_org")
    vid = _create(client, hdr)

    r = client.get(PDF % vid, headers=hdr)
    if r.status_code in (404, 405, 422):
        pytest.fail("匯出端點走不到（回 %s）。" % r.status_code)
    assert r.status_code == 200, "匯出失敗：%s" % r.content[:160]

    text = _pdf_text(r.content)
    assert NO_ORG not in text, (
        "設定了公司抬頭，而 PDF 上印的是「%s」——\n" % NO_ORG
        + "☠️ `_get_setting()` **已經 `json.loads` 過**，"
          "而 `voucher_pdf.py:82` 又 loads 一次\n"
          "   ⇒ `TypeError` 被 `except Exception` 吞掉 ⇒ 回空字串。\n"
        + "🔑 使用者設定過了，而**每一張傳票都說他沒設定**。")
    assert "摩崔思股份有限公司" in text, (
        "沒印那句錯話，**而也沒印公司名** ——\n"
        + "紙上是：\n  %s" % text[:200])


def test_jv9_a_missing_company_name_still_says_so(client, make_user):
    """⚙️ **`JV9(c)` 正對照：真的沒設定時，那句話**要**出現。**

    ☠️ 少了它，「把那句話整個拿掉」也會讓上一題綠 ——
       而那時使用者印出一張**沒有抬頭**的傳票，**而畫面沒說為什麼**。
    """
    _u, hdr = _hdr(client, make_user, "jv9_noorg")
    vid = _create(client, hdr)
    r = client.get(PDF % vid, headers=hdr)
    assert r.status_code == 200, "匯出失敗：%s" % r.content[:160]
    assert NO_ORG in _pdf_text(r.content), (
        "沒有設定公司抬頭，而 PDF 上**什麼都沒說** ——\n"
        + "☠️ 使用者印出一張沒有抬頭的傳票，而不知道是哪裡沒設定。")


def test_jv9_the_swallowed_error_leaves_a_trace(client, make_user, caplog):
    """🔴 **`JV9(b)`：`TypeError`／`ValueError` 要留下 log。**

    ☠️ 只做 `(a)` 的話，**「把 `except` 改成吞得更徹底」也會綠** ——
       而**下一個同類 bug 就再也查不到了**。
    🔑 這一題釘的是**診斷能力**，不是那一次的症狀
      （與 `EM3` 的追蹤碼是同一條：正式不等於含糊、安靜不等於正確）。
    ⚙️ 注入一個會丟 `TypeError` 的設定值，走真的那條路。
    """
    import logging

    import db
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value)"
            " VALUES ('company_profile', ?)", ("{不是合法的 JSON",))
        conn.commit()
    finally:
        conn.close()

    _u, hdr = _hdr(client, make_user, "jv9_log")
    vid = _create(client, hdr)
    with caplog.at_level(logging.WARNING):
        r = client.get(PDF % vid, headers=hdr)
    assert r.status_code == 200, (
        "抬頭讀不到而**整份 PDF 產不出來**（回 %s）——\n" % r.status_code
        + "📌 那一行的註解逐字：「抬頭讀不到**不該讓整份 PDF 產不出來**」。")

    said = any("company_profile" in rec.getMessage()
               or "抬頭" in rec.getMessage() for rec in caplog.records)
    assert said, (
        "設定值壞掉、PDF 照印，**而 log 裡一個字都沒有** ——\n"
        + "☠️ 那是「吞得更徹底」的樣子：症狀沒了，**而下一個同類 bug\n"
          "   再也查不到**。\n"
        + "🔑 `except` 要留一行 `log.warning(...)`，不是靜默 `return \"\"`。")


# ══════════════════════════════════════════════════════════════════════
# JV11：閘門在後端
# ══════════════════════════════════════════════════════════════════════

def test_jv11_an_unapproved_voucher_cannot_be_exported_from_the_api(
        client, make_user):
    """🔴🔴 **`JV11`：閘門在**後端** —— 直接打端點也要被擋。**

    ☠️ 只驗「前端按鈕不見了」的話：**任何人打端點照樣拿得到未簽核的傳票 PDF**
       —— 而那份 PDF 上有三個空的簽名格，看起來像一張正式單據。
    ⚠️ 而訊息要說得出**還差誰簽／現在第幾關**，不是一句「不可匯出」。
    🔑 「不可匯出」讓使用者無事可做；「還差主管簽核」讓他知道要去找誰。
    """
    _u, hdr = _hdr(client, make_user, "jv11_draft")
    vid = _create(client, hdr)

    r = client.get(PDF % vid, headers=hdr)
    if r.status_code in (404, 405, 422):
        pytest.fail("匯出端點走不到（回 %s）。" % r.status_code)
    assert r.status_code in (400, 403), (
        "**草稿**（還沒送審）的傳票匯得出 PDF（回 %s）——\n" % r.status_code
        + "☠️ 那份 PDF 上有三個空的簽名格，**看起來像一張正式單據**。\n"
        + "🔑 閘門要在**後端** —— 只藏按鈕的話，打端點照樣拿得到。")
    assert re.search(r"簽核|覆核|主管|第.{0,3}關", r.text), (
        "擋下來了，而訊息說不出**還差誰簽**：%s\n" % r.text[:200]
        + "☠️ 「不可匯出」讓使用者無事可做；\n"
          "   「還差主管簽核」讓他知道要去找誰。")


def test_jv11_preview_is_always_available_with_a_watermark(client, make_user):
    """🔴 **預覽**隨時可看**（帶浮水印），而匯出才要簽核通過。**

    ☠️ 兩者混在一起的後果：**還沒簽核的單連看都看不到** ——
       而**看是為了檢查**：簽核的人要先看過才知道要不要簽。
    ⚙️ 而預覽要**看得出它不是正式的** ⇒ 紙上要有浮水印字樣。
    🔑 少了浮水印，預覽檔被存下來、印出來，**就變成一張假的正式單據**。
    """
    _u, hdr = _hdr(client, make_user, "jv11_preview")
    vid = _create(client, hdr)

    r = client.get(PDF % vid + "?preview=1", headers=hdr)
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "預覽走不到（回 %s）——\n" % r.status_code
            + "⚠️ 參數名我單方面定成 `?preview=1`，**要換退回給我**。")
    assert r.status_code == 200, (
        "**預覽**也被擋掉了（回 %s）：%s\n" % (r.status_code, r.text[:200])
        + "☠️ 那讓「還沒簽核的單連看都看不到」——\n"
          "   **而看是為了檢查**：簽核的人要先看過才知道要不要簽。")
    text = _pdf_text(r.content)
    assert re.search(r"預覽|草稿|未簽核|尚未生效", text), (
        "預覽印得出來，**而紙上看不出它不是正式的**——\n"
        + "☠️ 它被存下來、印出來，**就變成一張假的正式單據**。\n"
        + "紙上是：\n  %s" % text[:200])


# ══════════════════════════════════════════════════════════════════════
# JV10：沒有附件時那顆按鈕
# ══════════════════════════════════════════════════════════════════════

def test_jv10_the_with_attachments_button_says_why_it_is_disabled():
    """🔴 **`JV10`：沒有附件時「含附件」那顆要停用**並說得出話**。**

    ☠️ 只停用而不說的話，使用者會一直點它 —— **而畫面不會回應**。
    ⚠️ 判準是「那顆按鈕的停用條件**綁到附件數**」，不是「它存在」。
    🔑 而這一顆與 `JV3` 的刪除鈕相反：
    ```
    刪除鈕（非草稿）  **不存在**（x-if）—— 那個動作在那個狀態下不該被想起
    含附件（沒附件）  **停用而看得見** —— 它提醒使用者「這裡可以放附件」
    ```
    """
    root = pathlib.Path(__file__).resolve().parents[2]
    html = (root / "frontend" / "pages" / "voucher.html").read_text(
        encoding="utf-8", errors="replace")
    html = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), html,
                  flags=re.S)

    m = re.search(r"<button[^>]*含附件[\s\S]{0,80}?</button>", html)
    if m is None:
        m = re.search(r"<button[^>]*>[^<]*含附件[^<]*</button>", html)
    assert m, (
        "`voucher.html` 上找不到「含附件」那顆按鈕 —— 匯出那一段還沒接。")
    tag = m.group(0)
    assert re.search(r":disabled=\"[^\"]*attach", tag, re.I), (
        "那顆按鈕的停用條件沒有綁到附件數：%s\n" % tag[:160]
        + "☠️ 沒有附件時它還按得下去 ⇒ 使用者拿到一份與「不含附件」\n"
          "   **一模一樣**的 PDF，而他以為附件沒傳成功。")
    assert re.search(r"title=|aria-label=|x-tooltip", tag), (
        "停用了，**而沒有說為什麼**：%s\n" % tag[:160]
        + "☠️ 使用者會一直點它，而畫面不會回應。")
