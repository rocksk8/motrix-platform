# -*- coding: utf-8 -*-
"""報價表單 `FORM_VERSION` 守門：表單內容變了而版本號沒變 ⇒ 紅（擋建包）。

使用者表單原文：「加檢查，漏改就擋建包」。hichan-8d 查到 V2.0 之後有 24 個 commit 動過
`quotation-form.html` 而沒有遞增——這條規則（`docs/quick/mod-quotation.md`：「quotation-form.html
或其邏輯任何改動都須遞增——小改版 +0.1，大改版 +1」）在此之前完全靠人記。

# 做法

一本**帳**（`LEDGER`）：版本號 → 那一版表單的雜湊。雜湊前先：
- 拿掉 `const FORM_VERSION = '…'` 那一行（否則改版本號本身就會讓雜湊變）；
- 換行一律 LF（同一份內容在別台機器 checkout 成 CRLF 不可以變成「內容變了」）。

```
版本號在帳上、雜湊一樣     ⇒ 綠
版本號在帳上、雜湊不一樣   ⇒ 紅：內容變了而版本沒動 ⇒ 告訴你該 bump 成多少
版本號不在帳上、雜湊＝帳上最新那一版  ⇒ 綠（只改了版本號，A 要的對照組）
版本號不在帳上、雜湊也不同 ⇒ 紅：bump 了，但要把新版本登記進帳（印出那一行）
```
📌 帳以「推的當下 master 上的值」為基準（A 裁示）：V3.2 ＝ c0aa4d7。

# ⚠️ 範圍

只看 `frontend/pages/quotation-form.html` 本身。它引用的外部腳本（sidebar／notif／style.css…）
是全站共用，不是報價表單專屬；後端的報價版面（`pdf_gen`）也不在這一道守門裡。
"""
import hashlib
import pathlib
import re

FORM = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "pages" / "quotation-form.html"
_VERSION_LINE = re.compile(r"^\s*const FORM_VERSION = '(V\d+\.\d+)'\s*$")

#: 版本號 → 表單雜湊（拿掉版本號那一行、換行統一 LF 之後的 sha256）。
#: 🔑 bump 版本號時，照紅燈訊息把新的一行加在最後面。
LEDGER = {
    "V3.2": "298eb2e5e1a8ea8b55f229c7858f233beb745f02390af77bbe9129768f3eed0b",
    # V3.3（AC1，2026-09-24）：稅別選單取代 1～4% 稅率；舊單須改選法定稅別。
    "V3.3": "150f2ce783b0ce899ae070e0e145482fe83f7a67be5b017b98611f9f6ff76fe2",
    # V3.4（N14，2026-09-24）：內部成本區五個間接費改用文字框，接受千分位與全形數字。
    "V3.4": "d3ae947b74f10dfddbcc24ff1d5f3a16a453234424d11f6c3e8e30e6a3db7376",
    # V3.5（CU2b，2026-09-24）：用詞統一，成案確認視窗「完結案件」→「結案」。
    "V3.5": "50a278412a0931a70659f55dc94385b36489e6d0179b098c1ae77729165b29f1",
    # V3.6（2026-09-25）：新單載入期間使用者先點的條款組／打的條款，不再被預設組蓋回去；載入中點方塊不再誤跳「已改過」確認。
    "V3.6": "c41d54e353173dafdfb89de4f2a09e7e717dbb6e9c3205e9cb28da6c83bfbfec",
    # V3.7（R2，2026-09-25）：零稅率／免稅要選依據（營業稅法 §7、§8），送審前必填。
    "V3.7": "d9ef3bdcf0ff01d857837038d804e51e55bcd257cf5a534107dc917949d3e2df",
    # V3.8（X-R，2026-09-26，稽核 S-4）：免稅依據改營業稅法 §8 逐款下拉，下方顯示條文出處。
    "V3.8": "15882f3ed0ccf53a065a43b3a4c4cb24dc25c582dcc9d6d26740752eaa182e3a",
    # V3.9（個資蒐集告知，2026-09-26）：聯絡人下方加告知區塊（列印告知書、已告知紀錄）。
    "V3.9": "b1b934f524ce2a48a65e4275704a77096137b29ad60c0079ce4df76a9b453411",
}


def form_fingerprint(text):
    """回 `(版本號, 雜湊)`。找不到版本號那一行 ⇒ 版本號是 None。"""
    lines = text.replace("\r\n", "\n").split("\n")
    version, kept = None, []
    for line in lines:
        m = _VERSION_LINE.match(line)
        if m and version is None:
            version = m.group(1)
            continue
        kept.append(line)
    return version, hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()


def _next_versions(version):
    major, minor = (int(x) for x in version[1:].split("."))
    return "V%d.%d" % (major, minor + 1), "V%d.0" % (major + 1)


def verdict(text, ledger):
    """回 `(ok, 訊息)`。規則見本檔開頭的表。"""
    version, digest = form_fingerprint(text)
    if version is None:
        return False, "找不到 `const FORM_VERSION = 'Vx.y'` 那一行——守門量不到東西。"
    if version in ledger:
        if ledger[version] == digest:
            return True, ""
        minor, major = _next_versions(version)
        return False, (
            "quotation-form.html 的內容變了，而 FORM_VERSION 還是 %s。\n"
            "⇒ 小改版（欄位微調／樣式／文案）改成 %s；大改版（版型結構／新增區塊／流程變更）改成 %s。\n"
            "⇒ 改完之後，把新版本登記進 tests/test_form_version_bumped_2026_09_24.py 的 LEDGER。"
            % (version, minor, major))
    latest = list(ledger)[-1]
    if ledger[latest] == digest:
        return True, ""          # 只改了版本號，內容與帳上最新那一版相同
    return False, (
        "FORM_VERSION 已改成 %s，但帳上還沒有這一版。\n"
        "⇒ 在 tests/test_form_version_bumped_2026_09_24.py 的 LEDGER 最後加一行：\n"
        '    "%s": "%s",' % (version, version, digest))


def test_form_version_is_bumped_whenever_the_quotation_form_changes():
    ok, msg = verdict(FORM.read_text(encoding="utf-8"), LEDGER)
    assert ok, msg


# ══════════════════════════════════════════════════════════════════════
# 對照組：規則本身（合成輸入，不看真的表單）
# ══════════════════════════════════════════════════════════════════════

_BASE = "<html>\n  const FORM_VERSION = 'V3.2'\n  <div>報價</div>\n</html>\n"
_LEDGER = {"V3.2": form_fingerprint(_BASE)[1]}


def test_form_version_rule_same_content_same_version_is_green():
    assert verdict(_BASE, _LEDGER) == (True, "")


def test_form_version_rule_changed_content_without_a_bump_is_red_and_says_how_much():
    ok, msg = verdict(_BASE.replace("報價", "報價單"), _LEDGER)
    assert not ok and "V3.3" in msg and "V4.0" in msg, msg


def test_form_version_rule_only_bumping_the_version_is_green():
    """A 要的對照組：只改 FORM_VERSION ⇒ 綠。"""
    assert verdict(_BASE.replace("'V3.2'", "'V3.3'"), _LEDGER) == (True, "")


def test_form_version_rule_a_bump_with_new_content_must_be_registered():
    text = _BASE.replace("'V3.2'", "'V3.3'").replace("報價", "報價單")
    ok, msg = verdict(text, _LEDGER)
    assert not ok and '"V3.3": "%s"' % form_fingerprint(text)[1] in msg, msg


def test_form_version_rule_line_endings_do_not_count_as_a_change():
    """同一份內容 checkout 成 CRLF（別台機器）不可以被當成「內容變了」。"""
    assert verdict(_BASE.replace("\n", "\r\n"), _LEDGER) == (True, "")


def test_form_version_rule_a_comment_mentioning_the_version_is_still_content():
    """只拿掉**那一行宣告**；註解裡寫到 FORM_VERSION 的文字照樣算內容。"""
    ok, _msg = verdict(_BASE.replace("<div>", "<!-- FORM_VERSION 說明 --><div>"), _LEDGER)
    assert not ok
