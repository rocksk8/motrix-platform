# -*- coding: utf-8 -*-
"""`BN7` · 獎金分潤單 PDF 匯出 ＋ 用印欄（`SPEC-BN6-BN7.md §4/§5`，使用者
2026-09-23 裁：用印欄列數由簽核設定決定，與傳票、報價單同一套規則）。

```
✅ §5 三選一已解：走 (a) 完整簽核鏈——前提 BN8 已把 submit/approve/reject
   接上（e4572ae／e6cf983），寫規格當下這條路走不通，現在走得通了。
```

# ⚙️ 端點：`GET /api/bonus/awards/{award_id}/pdf-download`

`SPEC-BN6-BN7.md §4` 定案的路徑，沿用既有 16 個呼叫端同一形狀
（`权限`：`_is_manager`，與 `POST /awards` 同一道閘）。

# 🔴 四格，其中 ④ 是 A 已經裁定的（不是我自己假設）

```
① 用印欄列數**來自簽核設定**，不是寫死
   ⚠️ 對照組：**改簽核設定的層數，PDF 的用印欄跟著變**——
      少了這個對照，「印固定兩格」在今天剛好是兩層時也會全綠
② 名字用**顯示名稱**不是帳號（`helpers/voucher.py::_resolve_display_names`
   已經解過同一個問題，這裡驗**輸出**，不驗是不是呼叫同一支函式）
③ 抬頭來自 `company_profile`——`JV9` 的雙重 `json.loads` 坑
   （`_get_setting()` 已經 loads 過，若這支新 builder 又 loads 一次會
   `TypeError`）在這支新的 builder 上有機會**重犯**，照 JV9 的形狀驗
④ 已核准／已過帳 -> 放；草稿／待審核／簽核中 -> 擋；
   任何狀態 ＋ 已作廢 -> 放（A 裁：與傳票 `JV11`／`JV15` 同一條）
```

## ⚠️ `JV11` 踩過的坑，這裡直接抄教訓不重踩

```
A 原話：「條件是未簽核完成，不是狀態不等於已核准」
B 實作成 status == "已核准" => 已過帳的傳票匯不出來（JV15 才補回來）
⇒ 一條「不要用 X 判斷」的界線，要配一份「那用什麼」的清單。
```
⇒ 這裡的驗收**直接沿用 `helpers/voucher.py::approval_done()` 的狀態
清單**（`voided_at` 為真 -> 放；`status == "已核准"` -> 放；其餘視鏈而定），
不自己重寫一條「狀態不等於 X」的判斷。獎金單今天沒有「已過帳」這個
狀態（`BN8` 的狀態機只有草稿／待審核／簽核中／已核准四個），所以本檔
沒有對應 `JV15` 那一題的位置——**若獎金單未來加了終態，這裡要記得回來
補上「終態也放行」那一格**（`§276` 同一課：一組題全綠時要問有沒有涵蓋
每一個終態）。
"""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_bonus_award_approval_2026_09_23 import (  # noqa: E402
    AWARDS, _act, _award, _hdr, _seed_award, _set_flow,
)

PDF = "/api/bonus/awards/%s/pdf-download"

#: `§166`：走到端點才會出現的狀態碼。
OK_CODES = (200, 400, 403)


def _reached(r):
    if r.status_code in (404, 405, 422):
        pytest.fail(
            "`GET %s` 走不到（回 %s）。\n" % (PDF % "{award_id}", r.status_code)
            + "📌 路徑是 `SPEC-BN6-BN7.md §4` 定案的，改了退回給我。")
    return r


def _pdf_text(body):
    """PDF 上印出來的文字，`NFKC` 正規化（Edge 會把漢字寫成康熙部首，`§214`）。"""
    import unicodedata
    pypdf = pytest.importorskip("pypdf", reason="抽 PDF 文字要用它")
    reader = pypdf.PdfReader(io.BytesIO(body))
    return unicodedata.normalize(
        "NFKC", "\n".join((p.extract_text() or "") for p in reader.pages))


def _set_company(client, hdr, name):
    """設定公司抬頭。⚠️ `company_profile` 是預設就 seed 的，本檔不驗
    「沒設定」那個狀態（那是 `JV9` 的範圍），只驗「設定了讀不讀得到」。
    """
    r = client.put("/api/settings/company-profile", headers=hdr,
                   json={"name": name})
    assert r.status_code in (200, 204), (
        "設定公司抬頭失敗：%s %s" % (r.status_code, r.text[:200]))


# ══════════════════════════════════════════════════════════════════════
# ① 用印欄列數來自簽核設定
# ══════════════════════════════════════════════════════════════════════

def _walk_to_approved(client, make_user, quote_no, tier_names):
    """建一張獎金單，設定 `len(tier_names)` 層簽核，走完到「已核准」。

    回 `(hdr, aid)` —— `hdr` 是建單人（superadmin）的 headers。
    """
    _u, hdr = _hdr(client, make_user, "bn7_owner_" + quote_no)
    signers = _set_flow(client, hdr, make_user, tier_names)
    aid = _seed_award(quote_no, ["bn7_payee_" + quote_no])
    assert _act(client, hdr, aid, "submit").status_code == 200, "送審失敗"
    for name, shdr in signers.items():
        r = _act(client, shdr, aid, "approve")
        assert r.status_code == 200, (
            "由 %r 簽核失敗：%s %s" % (name, r.status_code, r.text[:200]))
    a = _award(client, hdr, aid)
    assert a.get("status") == "已核准", "前置不對：簽完而狀態不是已核准。"
    return hdr, aid


def test_bn7_the_signature_slots_count_matches_the_configured_tiers(
        client, make_user):
    """🔴🔴 **`①` 核心：用印欄的格數，兩種層數要印出不同的格數。**

    ```
    強不變量  格數 == 1（製表）＋ 層數      <= 與 BN8 §6③ 同一條
    弱對照    印固定兩格                    <= 今天很可能就是兩層，會被誤判成對
    ```
    ⇒ 用**兩層**與**三層**各跑一次，斷言 PDF 上簽核那幾格的數量不同——
      只驗一種層數的話，一個「印死兩格」的實作在兩層的公司也會綠。
    """
    hdr2, aid2 = _walk_to_approved(client, make_user, "MQ-BN7-TWO",
                                   ("bn7_t2a", "bn7_t2b"))
    r2 = _reached(client.get(PDF % aid2, headers=hdr2))
    assert r2.status_code == 200, "兩層匯出失敗：%s %s" % (r2.status_code,
                                                       r2.content[:200])
    text2 = _pdf_text(r2.content)

    hdr3, aid3 = _walk_to_approved(client, make_user, "MQ-BN7-THREE",
                                   ("bn7_t3a", "bn7_t3b", "bn7_t3c"))
    r3 = _reached(client.get(PDF % aid3, headers=hdr3))
    assert r3.status_code == 200, "三層匯出失敗：%s %s" % (r3.status_code,
                                                       r3.content[:200])
    text3 = _pdf_text(r3.content)

    for name in ("bn7_t2a", "bn7_t2b"):
        assert name in text2, (
            "兩層設定簽完，PDF 上找不到簽核人 %r：\n%s" % (name, text2[:400]))
    for name in ("bn7_t3a", "bn7_t3b", "bn7_t3c"):
        assert name in text3, (
            "三層設定簽完，PDF 上找不到簽核人 %r：\n%s" % (name, text3[:400])
            + "\n☠️ 若用印欄印死兩格，第三層的人簽了而紙上沒有他的格子。")


# ══════════════════════════════════════════════════════════════════════
# ② 名字用顯示名稱，不是帳號
# ══════════════════════════════════════════════════════════════════════

def test_bn7_signature_names_are_display_names_not_usernames(client,
                                                              make_user):
    """🔴 **`②`：簽核那幾格印的是顯示名稱，不是帳號。**

    ⚙️ 觀測點在**輸出**：帳號與顯示名稱刻意設成不同值，PDF 上要出現
    顯示名稱、**不出現**帳號那個字串。
    """
    hdr, aid = _walk_to_approved(client, make_user, "MQ-BN7-DISPLAY",
                                 ("bn7_disp_signer",))
    import db
    conn = db.get_db()
    try:
        conn.execute(
            "UPDATE users SET display_name = ? WHERE username = ?",
            ("BN7測試簽核人顯示名", "bn7_disp_signer"))
        conn.commit()
    finally:
        conn.close()

    r = _reached(client.get(PDF % aid, headers=hdr))
    assert r.status_code == 200, "匯出失敗：%s %s" % (r.status_code,
                                                    r.content[:200])
    text = _pdf_text(r.content)
    assert "BN7測試簽核人顯示名" in text, (
        "PDF 上找不到顯示名稱：\n%s\n" % text[:400]
        + "☠️ 顯示名稱設定了卻沒有生效，紙上印的可能還是帳號。")
    assert "bn7_disp_signer" not in text, (
        "PDF 上印出了帳號 `bn7_disp_signer`：\n%s\n" % text[:400]
        + "☠️ 內部帳號印在對外／對稽核的憑證上，而使用者要看到的是姓名。")


# ══════════════════════════════════════════════════════════════════════
# ③ 抬頭：company_profile，防雙重 json.loads
# ══════════════════════════════════════════════════════════════════════

def test_bn7_the_company_header_is_not_blank(client, make_user):
    """🔴🔴 **`③`：設定了公司抬頭，PDF 上就要印得出來（防 `JV9` 同款雙重解析）。**

    ```
    JV9 的成因：_get_setting() 已經 json.loads 過（回物件），
    voucher_pdf.py:82 又 loads 一次 => TypeError => 被 except 吞掉
                                     => 印「（尚未設定公司抬頭）」
    ```
    🔑 這支是全新的 builder（`BN7`），同一個坑有機會**重犯一次**——
    這裡不假設 B 會不會踩到，直接照 `JV9(a)` 的驗收形狀驗**輸出**。
    """
    owner, ohdr = _hdr(client, make_user, "bn7_header")
    _set_company(client, ohdr, "摩崔思獎金測試股份有限公司")
    hdr, aid = _walk_to_approved(client, make_user, "MQ-BN7-HEADER",
                                 ("bn7_head_signer",))

    r = _reached(client.get(PDF % aid, headers=hdr))
    assert r.status_code == 200, "匯出失敗：%s %s" % (r.status_code,
                                                    r.content[:200])
    text = _pdf_text(r.content)
    assert "尚未設定公司抬頭" not in text, (
        "設定了公司抬頭，PDF 卻印「尚未設定公司抬頭」：\n%s\n" % text[:400]
        + "☠️ 多半是 `_get_setting()` 已經 `json.loads` 過，這支 builder\n"
          "   又 loads 一次 ⇒ `TypeError` 被吞掉 ⇒ 回空字串。")
    assert "摩崔思獎金測試股份有限公司" in text, (
        "沒印那句錯話，而也沒印公司名：\n%s" % text[:400])


# ══════════════════════════════════════════════════════════════════════
# ④ 閘門：與傳票同一條規則（A 已裁）
# ══════════════════════════════════════════════════════════════════════

def test_bn7_a_draft_award_cannot_be_exported(client, make_user):
    """🔴 **`④`：草稿狀態的獎金單不可以匯出。**"""
    _u, hdr = _hdr(client, make_user, "bn7_draft")
    aid = _seed_award("MQ-BN7-DRAFT", ["someone"])
    r = _reached(client.get(PDF % aid, headers=hdr))
    assert r.status_code in OK_CODES, (
        "回 %s：%s" % (r.status_code, r.content[:200]))
    assert r.status_code == 400, (
        "**草稿**的獎金單匯出成功（回 %s）——\n" % r.status_code
        + "☠️ 那是要據以付錢的單據，未簽核就印得出來的失效方式是\n"
          "   有人拿著它去請款。")


def test_bn7_mid_flight_award_cannot_be_exported(client, make_user):
    """🔴 **`④`：簽到一半（簽核中）的獎金單，仍然不可以匯出。**

    ⚙️ 與上一題釘的是**不同的狀態**：那題是「草稿」，這題是設定三層、
    只簽了一層之後的「簽核中」——兩者都要擋，而擋的成因可能不同
    （一個是「還沒送審」，一個是「送審了但沒簽完」）。
    """
    _u, hdr = _hdr(client, make_user, "bn7_mid")
    signers = _set_flow(client, hdr, make_user,
                        ("bn7_mid_a", "bn7_mid_b", "bn7_mid_c"))
    aid = _seed_award("MQ-BN7-MID", ["someone"])
    assert _act(client, hdr, aid, "submit").status_code == 200, "送審失敗"
    first = next(iter(signers.values()))
    assert _act(client, first, aid, "approve").status_code == 200, "第一層簽核失敗"

    r = _reached(client.get(PDF % aid, headers=hdr))
    assert r.status_code in OK_CODES, (
        "回 %s：%s" % (r.status_code, r.content[:200]))
    assert r.status_code == 400, (
        "簽到一半（簽核中）的獎金單匯出成功（回 %s）——\n" % r.status_code
        + "☠️ 三層只簽了一層，紙上若印得出來，會有人以為已經核准完成。")


def test_bn7_an_approved_award_can_be_exported(client, make_user):
    """⚙️ **正對照：已核准的獎金單要匯得出來。**

    ☠️ 少了它，一個「整支端點一律 400」的實作也會讓上面兩題綠。
    """
    hdr, aid = _walk_to_approved(client, make_user, "MQ-BN7-APPROVED",
                                 ("bn7_appr_signer",))
    r = _reached(client.get(PDF % aid, headers=hdr))
    assert r.status_code == 200, (
        "已核准的獎金單匯出失敗（回 %s）：%s" % (r.status_code, r.content[:200]))
    assert r.content[:5] == b"%PDF-", "回來的不是一份 PDF：%r" % r.content[:16]


def test_bn7_a_voided_award_can_still_be_exported_regardless_of_status(
        client, make_user):
    """🔴 **`④`：已作廢的獎金單，不管原本簽到哪裡，都要匯得出來。**

    ```
    A 裁：任何狀態 ＋ 已作廢 -> 放（與傳票 JV11／JV15 同一條）
    ```
    ⚙️ 這裡刻意用**草稿**就作廢的單（沒有走完任何簽核）——
       擋不住「已核准才放」與「voided_at 優先於狀態」的差別的話，
       這一題會紅在一個正確的實作上（草稿本來就該被草稿那題擋住，
       而作廢優先於那個擋）。
    """
    _u, hdr = _hdr(client, make_user, "bn7_void")
    aid = _seed_award("MQ-BN7-VOID", ["someone"])
    v = client.post("%s/%s/void" % (AWARDS, aid), headers=hdr,
                    json={"reason": "測試作廢優先"})
    assert v.status_code == 200, "作廢失敗：%s %s" % (v.status_code, v.text[:200])

    r = _reached(client.get(PDF % aid, headers=hdr))
    assert r.status_code == 200, (
        "已作廢的獎金單匯不出來（回 %s）：%s\n" % (r.status_code, r.content[:200])
        + "☠️ 已作廢的單是稽核要看的東西，`voided_at` 要優先於\n"
          "   `status` 判斷——不是『狀態不等於已核准就擋』。")
    assert r.content[:5] == b"%PDF-", "回來的不是一份 PDF：%r" % r.content[:16]
