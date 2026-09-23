# -*- coding: utf-8 -*-
"""`JV23` · 已作廢的傳票匯出的 PDF 上沒有作廢浮水印（使用者回報：重大缺失）。

使用者原話：「重大缺失，已作廢的傳票按下匯出沒有作廢的浮水印」。

# 🔴 動工前獨立追過一次根因，與 A 的回報一致

```
helpers/voucher_pdf.py:172  watermark_html(voucher)
    voided_at 有值 => 回 "<div class='wm'>…本傳票已作廢…僅供稽核存查…</div>"
    （title/sub 各鋪 12 份，3x4 格線平鋪，見 §283-286 的 CSS）
    否則走 approval_done() 未完成 => 回「傳票尚未簽核完成／預覽稿・尚未正式生效」
    approval_done() 通過（已核准／已過帳） => 回 ""

helpers/voucher_pdf.py:466  export_voucher_pdf() 第一次組本體：
    body = _render(build_html(v, images, missing, exported_at))
    🔴 **沒有傳 `watermark=` 這個關鍵字參數** => 用預設值 ""
helpers/voucher_pdf.py:474  併不進去 PDF 而要重印本體時，第二次呼叫：
    body = _render(build_html(v, images, missing, exported_at))
    🔴 **同一個坑，兩處都漏**

helpers/voucher_pdf.py:507  preview_html()：
    return build_html(v, [], [], exported_at, watermark=watermark_html(v))
    ✅ 預覽路徑**有**傳
```
⇒ `watermark_html()` 本身對「作廢」的判斷完全正確（`voided_at` 優先於
`approval_done()`，使用者裁示②已經落地在這支函式裡）——**沒有人壞掉的
是這支，壞掉的是「匯出路徑從來沒有呼叫它」**。

# 🔑 兩個各自正確的決定合起來的洞，而沒有任何舊題會紅

```
JV11 當時：浮水印是**預覽稿**專屬 —— 前提是「未簽核完成根本匯不出來」，
     所以匯出的一定是有效單，不需要浮水印。**當時這個推論是對的。**
JV15 之後：「已過帳／已作廢一律放行匯出」 —— **前提被推翻**，
     而 watermark="" 沒有跟著這個裁定一起翻面。
```
📌〈裁示翻面而守門不會自己翻面〉：兩邊規格各自對自己負責的那件事做對了，
而中間那條「匯出路徑要不要蓋浮水印」的線，從來沒有人在兩次裁定之間重新走過。

## ⚠️ 為什麼既有的 `test_jv11_a_voided_voucher_can_still_be_exported` 沒有抓到

那一題斷言 PDF 文字裡有「已作廢」——**而 `build_html()` 的 `.head` 那一列
本來就會印 `狀態　已作廢`**（`voucher_pdf.py:340`，這與浮水印無關，是每張
傳票都有的狀態列）。「已作廢」三個字**兩個地方都會印**，那一題的斷言
只用了子字串，兩種來源長得一樣，測不出浮水印到底有沒有蓋上去。
⇒ 本檔改用**只有浮水印才會印的字**當觀測點：`僅供稽核存查`（浮水印的
副標題，不在 `.head` 狀態列或版面任何其他地方出現）。

# ⚙️ 觀測點打在**匯出的 PDF 位元組**上，不是 `watermark_html()` 的回傳值

`watermark_html()` 今天單獨呼叫就是對的——這是〈觀測點要挑「成功後才會
被寫入」的下游欄位〉：要驗的是「匯出路徑有沒有呼叫它」，不是「它算得
對不對」，所以一律走 HTTP 端點 `pdf-download`，用 `pypdf` 抽出實際印出來
的文字。
"""
import io
import unicodedata

import pytest

PDF = "/api/vouchers/%s/pdf-download"

_LINES = [{"account_code": "1113", "debit": 1000, "credit": 0},
          {"account_code": "4111", "debit": 0, "credit": 1000}]

#: 浮水印**專屬**的字——不在版面其他任何地方出現，用來與 `.head` 狀態列
#: 的「已作廢」三個字（每張傳票都有）分開，避免子字串誤判成假綠燈。
_VOID_MARK = "僅供稽核存查"
_VOID_TITLE = "本傳票已作廢"
_UNSIGNED_MARK = "預覽稿・尚未正式生效"
_UNSIGNED_TITLE = "傳票尚未簽核完成"


def _hdr(client, make_user, username, role="superadmin", modules=("cashier",)):
    u, p = make_user(username=username, role=role, modules=list(modules))
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return u, {"Authorization": "Bearer " + r.json()["token"]}


def _create(client, hdr, summary="JV23 浮水印測試"):
    r = client.post("/api/vouchers", headers=hdr,
                    json={"summary": summary, "lines": _LINES})
    assert r.status_code == 200, "建不起來：%s %s" % (r.status_code, r.text[:200])
    return r.json()["id"]


def _sign_off(client, hdr, vid):
    r = client.post("/api/vouchers/%s/submit" % vid, json={}, headers=hdr)
    assert r.status_code == 200, "送審失敗：%s %s" % (r.status_code, r.text[:160])
    for _ in range(2):
        r = client.post("/api/vouchers/%s/approve" % vid, json={}, headers=hdr)
        assert r.status_code == 200, "簽核失敗：%s %s" % (r.status_code, r.text[:160])


def _pdf_text(body):
    """PDF 上印出來的文字，`NFKC` 正規化（Edge 會把漢字寫成康熙部首）。"""
    pypdf = pytest.importorskip("pypdf", reason="抽 PDF 文字要用它")
    reader = pypdf.PdfReader(io.BytesIO(body))
    return unicodedata.normalize(
        "NFKC", "\n".join((p.extract_text() or "") for p in reader.pages))


# ══════════════════════════════════════════════════════════════════════
# ① 核心：已作廢的傳票匯出要有浮水印
# ══════════════════════════════════════════════════════════════════════

def test_jv23_a_voided_voucher_export_pdf_has_the_void_watermark(client,
                                                                  make_user):
    """🔴🔴 **核心：已作廢的傳票匯出（不含附件），紙上要有作廢浮水印。**

    ⚙️ 這一支同時是 AC④（作廢優先於未簽核）的驗收：這裡用的是**從沒送審
    過的草稿**直接作廢，若判斷順序錯了（先看未簽核再看作廢），印出來的
    會是「尚未簽核完成」而不是「本傳票已作廢」——两句話同時檢查。
    """
    _u, hdr = _hdr(client, make_user, "jv23_void")
    vid = _create(client, hdr)
    v = client.post("/api/vouchers/%s/void" % vid,
                    json={"reason": "JV23 測試作廢"}, headers=hdr)
    assert v.status_code == 200, "作廢失敗：%s %s" % (v.status_code, v.text[:200])

    r = client.get(PDF % vid, headers=hdr)
    assert r.status_code == 200, "匯出失敗：%s %s" % (r.status_code, r.text[:200])
    text = _pdf_text(r.content)

    assert _VOID_MARK in text, (
        "已作廢的傳票匯出的 PDF 上找不到「%s」——這是浮水印**專屬**的字，\n"
        "找不到代表匯出路徑沒有蓋浮水印。\n" % _VOID_MARK
        + "☠️ 使用者拿到一張看起來完全有效的會計憑證，而它已經作廢了。\n"
        + "紙上前 300 字：\n  %s" % text[:300])
    assert _VOID_TITLE in text, (
        "找不到浮水印標題「%s」（`.head` 狀態列印的是「已作廢」三個字，\n"
        "與浮水印標題不是同一串——兩個都要有）。" % _VOID_TITLE)
    assert _UNSIGNED_MARK not in text, (
        "作廢單上同時印出了「尚未簽核」浮水印——\n"
        "☠️ **作廢優先於未簽核**（使用者裁示②）：印錯句話會讓人去把它簽完。")


def test_jv23_a_voided_voucher_export_with_attachments_also_has_the_watermark(
        client, make_user):
    """🔴 **`?with_attachments=1` 是另一次 `build_html()` 呼叫，也要有浮水印。**

    ⚠️ 本題只驗**沒有附件併不進去**時的那一次呼叫（`voucher_pdf.py:466`）。
    另有一條「PDF 附件併不進去而重印本體」的第二次呼叫（`:474`），
    需要一個會匯併失敗的附件才會走到，**本檔沒有造這個情境**——
    若 B 的修法是「算一次 `watermark_html(v)` 存成變數，兩次呼叫共用」，
    這條分支自然一起修好；若修法是「在其中一個呼叫點各自補參數」，
    這一格仍然是查不到的，先記在這裡（§8）。
    """
    _u, hdr = _hdr(client, make_user, "jv23_void_att")
    vid = _create(client, hdr)
    v = client.post("/api/vouchers/%s/void" % vid,
                    json={"reason": "JV23 含附件測試作廢"}, headers=hdr)
    assert v.status_code == 200, "作廢失敗：%s %s" % (v.status_code, v.text[:200])

    r = client.get(PDF % vid + "?with_attachments=1", headers=hdr)
    assert r.status_code == 200, "匯出失敗：%s %s" % (r.status_code, r.text[:200])
    text = _pdf_text(r.content)
    assert _VOID_MARK in text, (
        "`with_attachments=1` 匯出的 PDF 上找不到浮水印專屬字「%s」。\n"
        "紙上前 300 字：\n  %s" % (_VOID_MARK, text[:300]))


# ══════════════════════════════════════════════════════════════════════
# ② 負對照：正常放行的匯出不可以被誤蓋浮水印
# ══════════════════════════════════════════════════════════════════════

def test_jv23_an_approved_not_voided_export_has_no_watermark(client,
                                                              make_user):
    """⚙️🔴 **負對照（AC③）：已核准、沒有作廢，匯出不可以有任何浮水印字樣。**

    ☠️ 少了這一題，B 最省力的修法（「匯出一律蓋浮水印」或「一律傳
    `watermark_html(v)` 但 `approval_done()` 判斷寫錯」）也會讓上面①②變綠
    ——而那會讓**每一張正常憑證**印上多餘的字，比原本的缺陷更糟。

    🔑 這一題**今天就是綠的**（匯出路徑今天完全不蓋浮水印，只是連該蓋的
    也沒蓋）；它的價值在**修完之後**：確認變成「該蓋的蓋、不該蓋的仍然
    不蓋」，不是「全部都蓋」。
    """
    _u, hdr = _hdr(client, make_user, "jv23_approved")
    vid = _create(client, hdr)
    _sign_off(client, hdr, vid)

    r = client.get(PDF % vid, headers=hdr)
    assert r.status_code == 200, "匯出失敗：%s %s" % (r.status_code, r.text[:200])
    text = _pdf_text(r.content)

    assert _VOID_MARK not in text, (
        "已核准（未作廢）的傳票匯出卻印了作廢浮水印「%s」：\n  %s"
        % (_VOID_MARK, text[:300]))
    assert _UNSIGNED_MARK not in text, (
        "已核准的傳票匯出卻印了「尚未簽核完成」浮水印——\n"
        "☠️ 這張單已經簽核完成，印這句話等於防一個不存在的狀態。")


def test_jv23_a_posted_voucher_export_has_no_watermark(client, make_user):
    """⚙️🔴 **負對照（AC⑤）：已過帳的傳票匯出不可以有浮水印——它是有效憑證。**"""
    _u, hdr = _hdr(client, make_user, "jv23_posted")
    vid = _create(client, hdr)
    _sign_off(client, hdr, vid)

    p = client.post("/api/vouchers/%s/post" % vid, json={}, headers=hdr)
    assert p.status_code == 200, "過帳失敗：%s %s" % (p.status_code, p.text[:200])

    r = client.get(PDF % vid, headers=hdr)
    assert r.status_code == 200, "匯出失敗：%s %s" % (r.status_code, r.text[:200])
    text = _pdf_text(r.content)

    assert _VOID_MARK not in text, (
        "已過帳的傳票匯出卻印了作廢浮水印「%s」：\n  %s"
        % (_VOID_MARK, text[:300]))
    assert _UNSIGNED_MARK not in text, (
        "已過帳的傳票匯出卻印了「尚未簽核完成」浮水印——\n"
        "帳已經動了，這句話對已過帳的單沒有意義。")


# ══════════════════════════════════════════════════════════════════════
# §8 我沒查什麼
# ══════════════════════════════════════════════════════════════════════
#
# ① `voucher_pdf.py:474` 那一次重印（PDF 附件併不進去時）沒有造情境測到，
#    見 `test_jv23_a_voided_voucher_export_with_attachments_also_has_the_
#    watermark` 的 docstring。
# ② 其他單據（報價單／請款單／獎金單）匯出的 PDF 是否也有「作廢卻沒蓋章／
#    浮水印」同一族缺陷——A 的訊息要我順手量，這是另一件事，不在本檔範圍，
#    量完會是另一個編號。
