"""`BN11` · 獎金分潤單 PDF 要含案件精算明細表（`SPEC-BN11-BN12.md` §2／§5）。

驗三件事：
① PDF 的 HTML 依 `SETTLEMENT_ROWS` 的**順序與標籤**印出 11 列
② 值是精算**存值原樣帶出**（不重算）：刻意給一組「照 10%／1% 算會對不上」的值，
   印出來的必須是存值
③ 守門：`SETTLEMENT_ROWS` 的 11 個標籤在 `settlement.html` 裡逐字找得到
   —— 那一份是前端寫死的表，本輪不動，靠這一題擋它漂移

🔴 **③ 誤報時，要改的是這一題，不是 `settlement.html` 的文案。**
   （`SPEC-BN11-BN12.md` §5：這種掃字面的守門，誤報時最省力的反應是去改被掃的那一邊。）
⚠️ 已知例外恰好 1 個：第 10 列 `netProfit` 在獎金單側多印「（＝獎金分潤基數）」——
   使用者 2026-09-23 裁示，不是漂移；那句 note 不拿去比對 `settlement.html`。
"""
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend" / "pages"

#: 每一格都不同、且**不符合** 10%／1% 係數 ⇒ 若實作重算，數字會對不上。
_SETTLE = {"summary": {
    "quotedPretax": 100000, "quotedTotal": 105000,
    "itemActualTotal": 41000, "extraTotal": 3500, "dispatchTotal": 12000,
    "totalActualCost": 56500, "grossProfit": 43500, "grossMarginPct": 43.5,
    "adminCost": 7777, "charityDonation": 333,
    "netProfit": 35390, "netMarginPct": 35.4,
}}


def _html(settle):
    from helpers.bonus_pdf import build_award_html
    award = {"id": 1, "award_no": "BA-BN11-001", "quote_no": "MQ-BN11-001",
             "status": "已核准", "voided_at": "", "created_by": "u", "created_at": "2026-09-24"}
    return build_award_html(award, [], {}, {}, "2026-09-24 00:00", settle=settle)


def _rows(html):
    """PDF HTML 裡精算表的 `(標籤, 值)`，照出現順序。"""
    from helpers.bonus import SETTLEMENT_ROWS
    labels = [lbl for _k, lbl, _kind, _n in SETTLEMENT_ROWS]
    out = []
    for m in re.finditer(r"<tr><td>(.*?)</td><td class='num'>(.*?)</td></tr>", html):
        lbl = re.sub(r"<small>.*?</small>", "", m.group(1))
        if lbl in labels:
            out.append((lbl, re.sub(r"<small>.*?</small>", "", m.group(2))))
    return out


#: `SPEC-BN11-BN12.md` §2 逐字（順序即顯示順序）。
#: ⚠️ 期望值**寫死在這裡**，不從 `SETTLEMENT_ROWS` 讀：第一版拿實作自己的常數當期望，
#:    把常數兩列對調 ⇒ PDF 跟著對調 ⇒ 題照樣綠（驗到的是自己設的值）。
_SPEC_ORDER = (
    "報價稅前收入", "品項實際成本", "額外支出", "承攬商派發成本", "實際總成本",
    "真實毛利", "真實毛利率", "管銷分攤（10%）", "公益捐款（1%）", "真實淨利", "真實淨利率",
)


def test_bn11_the_pdf_prints_the_eleven_rows_in_the_declared_order():
    got = [lbl for lbl, _v in _rows(_html(_SETTLE))]
    assert got == list(_SPEC_ORDER), (
        "PDF 精算表的列 %r\n與規格 §2 的 11 列 %r 不一致（順序或標籤）" % (got, list(_SPEC_ORDER)))


def test_bn11_the_values_are_the_stored_ones_not_recomputed():
    vals = dict(_rows(_html(_SETTLE)))
    assert vals["管銷分攤（10%）"] == "NT$ 7,777", (
        "管銷分攤印的是 %r —— 存值是 7,777（刻意不等於 10%%）。\n" % vals["管銷分攤（10%）"]
        + "☠️ 印出 10,000 表示 PDF 自己重算了，而規格要求值一律來自精算存值。")
    assert vals["公益捐款（1%）"] == "NT$ 333"
    assert vals["額外支出"] == "NT$ 3,500"
    assert vals["真實淨利"] == "NT$ 35,390"
    assert vals["真實淨利率"] == "35.4%"


def test_bn11_a_missing_settlement_still_prints_the_table_with_dashes():
    """反向控制：沒有精算時整張表仍然印出，11 格都是「—」（不是整段消失、不是 0）。"""
    rows = _rows(_html(None))
    assert len(rows) == 11, "沒有精算時表不見了：%r" % rows
    assert all(v == "—" for _l, v in rows), rows


def test_bn11_settlement_page_still_carries_every_label_verbatim():
    """🔴 **誤報時改這一題，不要改 `settlement.html` 的文案。**"""
    from helpers.bonus import SETTLEMENT_ROWS
    src = (FRONTEND / "settlement.html").read_text(encoding="utf-8")
    missing = [lbl for _k, lbl, _kind, _n in SETTLEMENT_ROWS if lbl not in src]
    assert not missing, (
        "`SETTLEMENT_ROWS` 的這些標籤在 settlement.html 找不到：%r\n" % missing
        + "⇒ 兩份精算表的列已經分岔。先確認是哪一邊改了、該不該改；"
          "**不要為了讓這一題變綠去改 settlement.html 的文案。**")
