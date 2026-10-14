# -*- coding: utf-8 -*-
"""使用者可編輯的短文字（樣板名稱、階段名稱…）共用的安全檢查（S-ST1 起；通知用語編輯器有一份同規則的副本，之後併入這裡）。

[單位] helper:safe_text    [層] L1    [穩定度] 實作
[公開介面] ALLOWED, RESERVED, RESERVED_EN, problem
[不變式] 純函式，不讀寫任何設定、不 import 業務模組。`problem(text, limit, allow_status)` 回傳白話原因（空字串＝通過）：
    ①必須是不空白的字串、長度上限；②不含控制／隱形／雙向／私用字元（NFKC 之前先擋）；③不含標記字元 < > & 引號 反斜線 與大括號；
    ④NFKC 之後只接受中文（含全形標點轉換後的標點）、ASCII 英數字、空白與 . , : ; ! ? ( ) [ ] - _ ~ ——西里爾／希臘字母等外觀相似字、emoji 一律擋；
    ⑤不含網址或斜線；⑥（`allow_status=False` 時）不含官方狀態字樣（已核准、已付款、正本…；中文比對在只留字母數字的骨架上，英文用字界）。
    階段名稱這類內部進度用語傳 `allow_status=True`（例如「客戶核准」是合理的階段名稱）；其餘檢查不變。
[契約題] tests/platform/test_stage_templates_t62.py
"""
import re
import unicodedata

#: 看起來是空白或會被隱形的字元（Hangul filler、Braille blank 等；其餘 Cc/Cf/Zl/Zp/Co/Cs 以字元類別擋）
_FILLERS = frozenset("ᅟᅠㅤﾠ⠀᠎͏؜឴឵­⁠")
_BAD = re.compile("[<>&\"'`\\\\{}]")
#: 字元白名單（NFKC 之後比對）
ALLOWED = re.compile(r"[一-鿿㐀-䶿　-〿A-Za-z0-9 .,:;!?()\[\]\-_~]*")
_URLISH = re.compile(r"https?|://|www\.|[A-Za-z0-9_]+\.[A-Za-z0-9_]{2,}|/", re.I)
RESERVED = ("正本", "副本", "已核准", "已核可", "核准", "核可", "簽核完成", "签核完成", "已付款", "已收款", "已簽回", "已簽收", "作廢", "作废",
            "已通過", "通過", "已通过", "通过", "批准", "審核通過", "审核通过", "簽核通過", "签核通过", "已簽核", "已签核", "已批", "已生效")
RESERVED_EN = ("approve", "approved", "passed", "paid", "original", "void", "signed", "final")
_EN_RE = re.compile(r"(?<![a-z])(?:%s)(?![a-z])" % "|".join(RESERVED_EN))


def _skeleton(v):
    return "".join(ch for ch in unicodedata.normalize("NFKC", v).casefold() if ch.isalnum())


def problem(text, limit, allow_status=False) -> str:
    if not isinstance(text, str) or not text.strip():
        return "必須是不空白的文字"
    if len(text) > limit:
        return "最多 %d 字" % limit
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp", "Co", "Cs") or ch in _FILLERS for ch in text):
        return "不可含控制、隱形、雙向或私用字元"
    if _BAD.search(text):
        return "不可含標記字元（< > & 引號 反斜線 大括號）"
    norm = unicodedata.normalize("NFKC", text)
    if not ALLOWED.fullmatch(norm):
        return "只能使用中文、英數字與常用標點（不接受外觀相似的其他文字）"
    if _URLISH.search(norm):
        return "不可含網址或連結（含斜線、網域寫法）"
    if not allow_status:
        hit = [w for w in RESERVED if _skeleton(w) in _skeleton(text)]
        hit += _EN_RE.findall(norm.casefold())
        if hit:
            return "不可含官方狀態字樣：%s" % "、".join(dict.fromkeys(hit))
    return ""
