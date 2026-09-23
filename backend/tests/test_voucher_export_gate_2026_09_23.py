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
import io
import pathlib
import re

import pytest

PDF = "/api/vouchers/%s/pdf-download"

#: `§228` 裁定：預覽是**獨立端點**（回 HTML），不是 `pdf-download?preview=1`。
#: 🔑 **閘門綁在參數上，漏傳就穿透；綁在端點上，穿不過去。**
PREVIEW = "/api/vouchers/%s/preview"

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
    """設定（或清空）公司抬頭。

    ## 🔴 兩件我第一版都寫錯了，而它們讓題目紅在錯的地方

    ```
    ① 欄位叫 **value_json** 不是 value（`db.py:4035` 讀的就是它）
       => 我寫進一個**沒有人讀的欄位** => 看起來像「設定了而沒生效」
    ② `company_profile` 是 **db.py:708 預設就 seed 的**
       （name = 允碩整合集創股份有限公司）
       => 「沒有設定」這個狀態在乾淨的測試庫裡**不存在**
       => 我那個正對照的前提從一開始就不成立
    ```
    🔑 ② 特別值得記：我以為我在量「沒設定時的行為」，
      **而那個狀態要自己造出來**。
    """
    import db
    import json as _json
    conn = db.get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value_json,"
            " updated_at) VALUES ('company_profile', ?, '2026-09-23')",
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
    _set_company("")          # ⚠️ 預設有 seed ⇒ 「沒設定」要**自己造**
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

    ## 🔴 端點是 `GET /{id}/preview`，**不是** `pdf-download?preview=1`

    A 裁（`§228`），理由比我原本那個好：
    ```
    **閘門綁在參數上，漏傳就穿透；綁在端點上，穿不過去。**
    ```
    ☠️ 少寫一個 `not`、參數名打錯、預設值被改 —— 三種都讓閘門**靜默失效**，
       **而回應看起來完全正常**。
    ⚠️ 還有一層：一個參數同時改變**輸出格式**與**權限**是兩件事綁在一起
       ⇒ 日後有人要「預覽的 PDF」時，他會去**鬆那個閘門**。
    📌 而預覽回的是 **HTML** 不是 PDF ⇒ 這一題不抽 PDF 文字。

    ☠️ 兩者混在一起的後果：**還沒簽核的單連看都看不到** ——
       而**看是為了檢查**：簽核的人要先看過才知道要不要簽。
    🔑 少了浮水印，預覽被存下來、印出來，**就變成一張假的正式單據**。
    """
    _u, hdr = _hdr(client, make_user, "jv11_preview")
    vid = _create(client, hdr)

    r = client.get(PREVIEW % vid, headers=hdr)
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`GET %s` 走不到（回 %s）——\n" % (PREVIEW % "{id}", r.status_code)
            + "📌 `§228` 裁定：預覽是**獨立端點**，不是 `?preview=1`。")
    assert r.status_code == 200, (
        "**預覽**也被擋掉了（回 %s）：%s\n" % (r.status_code, r.text[:200])
        + "☠️ 那讓「還沒簽核的單連看都看不到」——\n"
          "   **而看是為了檢查**：簽核的人要先看過才知道要不要簽。")
    assert re.search(r"預覽|草稿|未簽核|尚未生效", r.text), (
        "預覽出得來，**而看不出它不是正式的**——\n"
        + "☠️ 它被存下來、印出來，**就變成一張假的正式單據**。\n"
        + "畫面上是：\n  %s" % r.text[:200])


def test_jv11_a_voided_voucher_can_still_be_exported(client, make_user):
    """⚙️🔴 **正對照：作廢單匯出要**成功** —— 那是一條既有裁定。**

    ```
    voucher_pdf.py:363 docstring 逐字：**「已作廢的傳票也要印得出來」**
    ```
    ⇒ 閘門的條件是「**未簽核完成**」，**不是**「狀態不等於已核准」。
    ☠️ 少了這一格，B 最省力的實作（**擋掉所有非已核准**）會**全綠而牴觸
       一條已經存在的裁定** —— 而作廢單是稽核一定要看的東西。
    🔑 那是〈守門守的對象被搬走〉的**鏡像**：**裁示已經存在，而新的題不知道它。**

    ## ⚠️ 而浮水印上「作廢優先於未簽核」（使用者裁示 ②）

    一張**還沒簽核就被作廢**的單，紙上要印「**已作廢**」不是「尚未簽核」——
    ☠️ 印「尚未簽核」的話，有人會去把它簽完。
    """
    _u, hdr = _hdr(client, make_user, "jv11_void")
    vid = _create(client, hdr)
    v = client.post("/api/vouchers/%s/void" % vid,
                    json={"reason": "打錯了"}, headers=hdr)
    assert v.status_code == 200, "作廢失敗：%s %s" % (v.status_code, v.text[:200])

    r = client.get(PDF % vid, headers=hdr)
    if r.status_code in (404, 405, 422):
        pytest.fail("匯出端點走不到（回 %s）。" % r.status_code)
    assert r.status_code == 200, (
        "**已作廢**的傳票匯不出來（回 %s）：%s\n" % (r.status_code, r.text[:200])
        + "☠️ 多半是閘門寫成「狀態不等於已核准就擋」——\n"
          "   而 `voucher_pdf.py:363` 的 docstring 逐字說\n"
          "   **「已作廢的傳票也要印得出來」**。\n"
        + "🔑 閘門的條件是「**未簽核完成**」，不是「不是已核准」。")

    text = _pdf_text(r.content)
    assert "已作廢" in text, (
        "作廢單印出來了，而紙上沒有「已作廢」：\n  %s" % text[:200])
    assert "尚未簽核" not in text, (
        "作廢單上印的是「尚未簽核」——\n"
        + "☠️ **作廢優先於未簽核**（使用者裁示 ②）：\n"
          "   印「尚未簽核」的話，**有人會去把它簽完**。")


# ══════════════════════════════════════════════════════════════════════
# JV10：沒有附件時那顆按鈕
# ══════════════════════════════════════════════════════════════════════

def test_jv10_an_export_that_merged_nothing_does_not_claim_it_did(client,
                                                                  make_user):
    """🔴🔴 **有附件而**一個都併不進去** ⇒ 訊息不可以說「已匯出（含附件）」。**

    ## ☠️ 今天就會出錯，而它比「沒附件時停用」深一層（A-2 實查）

    ```
    voucher_pdf.py:374  with_attachments 而 0 筆 => rows=[] => 產出**與不含附件一模一樣**
    voucher.js:287      訊息說「**已匯出（含附件）。**」
    ```
    🔑 **使用者分不出「附件沒被併進去」與「本來就沒有附件」——
      兩件事，同一個結果。**
    ☠️ 而「沒附件時那顆停用」那一題**擋不到這一條**：
       這裡**有**附件，只是一個都併不進去（例如兩個 `.docx`）。

    ⚙️ 觀測點：輸出裡要**說得出有東西沒進來** —— 那正是 `§5` 那一頁。
    📌 而使用者裁示 ④（預覽要標出哪些併得進 PDF）是給使用者的另一半。
    """
    _u, hdr = _hdr(client, make_user, "jv10_nomerge")
    vid = _create(client, hdr)

    r = client.post("/api/vouchers/%s/attachments" % vid, headers=hdr,
                    files={"files": ("報價.docx", io.BytesIO(
                        b"PK\x03\x04 not a pdf"),
                        "application/vnd.openxmlformats-officedocument."
                        "wordprocessingml.document")})
    if r.status_code in (404, 405, 422):
        pytest.fail("附件端點走不到（回 %s）—— `JV3` 先。" % r.status_code)
    if r.status_code != 200:
        pytest.fail(
            "`.docx` 附件上傳被擋（回 %s）：%s\n" % (r.status_code, r.text[:200])
            + "📌 `helpers/uploads.py` 只收 `.jpg/.jpeg/.png/.pdf` ——\n"
              "   若附件型別在上傳那一關就被擋住，這一條路**不存在**，\n"
              "   **退回給我**：那時這一題要刪掉，不是改成別的。")

    exp = client.get(PDF % vid + "?with_attachments=1", headers=hdr)
    assert exp.status_code == 200, "匯出失敗：%s" % exp.content[:160]
    text = _pdf_text(exp.content)
    assert "報價.docx" in text, (
        "有一個附件**一個都沒併進去**，而輸出裡沒有提到它 ——\n"
        + "☠️ 使用者拿到一份與「不含附件」一模一樣的 PDF，\n"
          "   **而訊息說「已匯出（含附件）」** ⇒ 他分不出\n"
          "   「附件沒被併進去」與「本來就沒有附件」。\n"
        + "紙上是：\n  %s" % text[:200])


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
