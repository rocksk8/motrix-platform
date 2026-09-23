# -*- coding: utf-8 -*-
"""`BN13` · 已作廢的獎金分潤單匯出的 PDF 沒有任何作廢標記——`JV23` 同一類的第二個。

D 盤點：全庫「有作廢概念且能匯出 PDF」的單據只有 2 種（傳票／獎金單），
`inventory.py` 零筆 PDF 程式碼、不適用。傳票那一半已在
`test_voucher_export_watermark_2026_09_23.py`（`JV23`）；本檔是**另一半**。

# 🔴 根因比 `JV23` 更徹底：**這支 builder 從來沒有浮水印機制**

```
helpers/bonus_pdf.py::build_award_html()
  只有 <div>狀態　{status}</div>（9.3pt 小字，`.head` 那一列）
  ── 完全沒有 .wm CSS class、沒有 watermark 參數、沒有任何呼叫
     `voucher_pdf.py::watermark_html()` 那種東西
```
⇒ 與 `JV23` 不同：`JV23` 是「邏輯對、接錯路徑」，這裡是**整支都不存在**。
🔑 而兩邊是**同一個舊假設沒跟上同一次政策放寬**：`can_export()` 允許
`voided_at` 的單放行匯出，是**與傳票 `JV11`／`JV15` 同一次裁定複製過來
的**——複製了「放行」，沒有複製「放行之後紙上要看得出來」那一半。

## ⚠️ 只標記「已作廢」，不做「未簽核完成」那一半

`can_export()` 已經把草稿／待審核／簽核中擋在匯出端點之外（`400`），
那些狀態根本到不了 `build_award_html()`——照 `JV23` 同一條理由，
印一句「尚未簽核完成」在紙上等於防一個不可能出現的狀態，本檔不寫這一格。

## ⚠️ 獎金單沒有「已過帳」這個終態

`BN8` 的狀態機只有草稿／待審核／簽核中／已核准四個（`bonus_pdf.py`
模組 docstring 已經逐字標過）——本檔**不寫**「已過帳不可有浮水印」那一題，
那個狀態今天不存在，寫了是一句測不到東西的空話（同 `JV20` 的處置）。

# 🔑 與 `JV23` 互相指名

`JV23`（`test_voucher_export_watermark_2026_09_23.py`）與本檔是**同一類
缺陷的兩半**——只做完其中一半、以為整件事完成了，是最容易發生的漏頁
方式。兩邊都要修才算 `JV23`／`BN13` 一起結案。
"""
import io
import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_bonus_award_approval_2026_09_23 import (  # noqa: E402
    AWARDS, _act, _award, _hdr, _seed_award, _set_flow,
)

PDF = "/api/bonus/awards/%s/pdf-download"

#: A 給的確切字串——`build_award_html()` 今天完全不存在這句話（連
#: 「已作廢」都只出現在 `.head` 狀態列，前面沒有「本獎金分潤單」）。
_VOID_TITLE = "本獎金分潤單已作廢"


def _pdf_text(body):
    """PDF 上印出來的文字，`NFKC` 正規化（Edge 會把漢字寫成康熙部首）。"""
    pypdf = pytest.importorskip("pypdf", reason="抽 PDF 文字要用它")
    reader = pypdf.PdfReader(io.BytesIO(body))
    return unicodedata.normalize(
        "NFKC", "\n".join((p.extract_text() or "") for p in reader.pages))


def _walk_to_approved(client, make_user, quote_no, tier_names):
    """建一張獎金單，設定簽核層，走完到「已核准」。回 `(hdr, aid)`。

    照抄 `test_bonus_award_pdf_export_2026_09_23.py::_walk_to_approved`
    的同一條路——不 import 那一支（它綁在那個檔的模組層級變數上），
    這三行本身不含規則，複製不算複製規則。
    """
    _u, hdr = _hdr(client, make_user, "bn13_owner_" + quote_no)
    signers = _set_flow(client, hdr, make_user, tier_names)
    aid = _seed_award(quote_no, ["bn13_payee_" + quote_no])
    assert _act(client, hdr, aid, "submit").status_code == 200, "送審失敗"
    for name, shdr in signers.items():
        r = _act(client, shdr, aid, "approve")
        assert r.status_code == 200, (
            "由 %r 簽核失敗：%s %s" % (name, r.status_code, r.text[:200]))
    a = _award(client, hdr, aid)
    assert a.get("status") == "已核准", "前置不對：簽完而狀態不是已核准。"
    return hdr, aid


# ══════════════════════════════════════════════════════════════════════
# ① 核心：已作廢的獎金單匯出要有作廢標記
# ══════════════════════════════════════════════════════════════════════

def test_bn13_a_voided_award_export_pdf_has_the_void_watermark(client,
                                                                make_user):
    """🔴🔴 **核心：已作廢的獎金分潤單匯出，紙上要有「本獎金分潤單已作廢」。**

    ⚙️ 用**從沒送審過的草稿**直接作廢（`test_bn7_a_voided_award_can_still_
    be_exported_regardless_of_status` 已經證明這條路匯得出來），本題再往
    前一步：匯出來的紙上有沒有**看得出來**它是作廢的。
    """
    _u, hdr = _hdr(client, make_user, "bn13_void")
    aid = _seed_award("MQ-BN13-VOID", ["someone"])
    v = client.post("%s/%s/void" % (AWARDS, aid), headers=hdr,
                    json={"reason": "BN13 測試作廢"})
    assert v.status_code == 200, "作廢失敗：%s %s" % (v.status_code, v.text[:200])

    r = client.get(PDF % aid, headers=hdr)
    assert r.status_code == 200, "匯出失敗：%s %s" % (r.status_code,
                                                    r.content[:200])
    text = _pdf_text(r.content)
    assert _VOID_TITLE in text, (
        "已作廢的獎金分潤單匯出的 PDF 上找不到「%s」：\n" % _VOID_TITLE
        + "☠️ `build_award_html()` 今天完全沒有浮水印機制，只有 9.3pt 小字\n"
          "   的「狀態　已作廢」——那句話在使用者眼裡等於沒有標記。\n"
        + "紙上前 300 字：\n  %s" % text[:300])


# ══════════════════════════════════════════════════════════════════════
# ② 負對照：已核准（未作廢）不可以被誤蓋
# ══════════════════════════════════════════════════════════════════════

def test_bn13_an_approved_not_voided_award_export_has_no_watermark(
        client, make_user):
    """⚙️🔴 **負對照：已核准、沒有作廢，匯出不可以印任何作廢字樣。**

    ☠️ 少了這一題，「匯出一律印『本獎金分潤單已作廢』」也會讓上一題變綠
    ——而那會讓**每一張正常的分潤單**都印上這句話。

    🔑 這一題**今天就是綠的**（今天完全沒有這句話，當然也不會誤印在
    正常單上）；價值在修完之後：確認變成「該印的印、不該印的仍然不印」。
    """
    hdr, aid = _walk_to_approved(client, make_user, "MQ-BN13-APPROVED",
                                 ("bn13_appr_signer",))
    r = client.get(PDF % aid, headers=hdr)
    assert r.status_code == 200, "匯出失敗：%s %s" % (r.status_code,
                                                    r.content[:200])
    text = _pdf_text(r.content)
    assert _VOID_TITLE not in text, (
        "已核准（未作廢）的獎金分潤單匯出卻印了「%s」：\n  %s"
        % (_VOID_TITLE, text[:300]))
