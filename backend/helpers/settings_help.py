# -*- coding: utf-8 -*-
"""設定中心「?」說明（選單去工程師化 批次 9，2026-11-13）：每個設定欄位要嘛「標籤已夠清楚」（白名單），要嘛有四段說明。

[單位] helper:settings_help    [層] L1    [穩定度] 實驗
[公開介面] BUILTIN_EXTRA_TERMS, BUILTIN_SHARED_TERMS, OVERRIDE_KEY, SECTIONS, SINGLE_ADMIN_NOTE, forbidden_terms, get_override, has_hidden_chars, help_for, help_view, label_clear, problems_in, set_override, shared_terms_file, system_data, term_problems
[契約題] tests/test_settings_center_b9_2026_11_13.py
[不變式] ①讀取永不丟例外；②資料檔壞掉 ⇒ 空資料並記 ERROR（守門測試會紅）；③只讀設定欄位的 metadata，不改任何設定值、欄位 key、儲存位置或 API。

資料檔：`core/settings_help.json`：`{"version":1, "label_clear":["群組.欄位",…], "help":{"群組.欄位":{"what","when","impact","example"?}}}`。
    **文字不寫在 HTML 裡**；key 一律是「群組.欄位」（欄位代碼在不同群組會重複，例如 enabled）。
四段：①這是什麼（what）②什麼時候要改（when）③改了會影響什麼（impact）④預設值與建議——**第四段執行時由設定欄位的 metadata 產生**
    （預設值、建議值、範例），不手寫，所以不會與程式漂移。
公司可自訂（全部可自定）：覆寫存在 `system_settings.settings_help_override`：`{"群組.欄位":{what,when,impact,example}}`；沒覆寫＝系統預設。
    覆寫逐筆驗證（四段字數、不含標記、不含工程用語），壞掉的覆寫在讀取時被忽略並回系統預設。
工程用語守門：禁用詞的共用來源是 `backend/tools/ux_audit_config.json`（`forbidden_terms`、`deprecated_terms`；hichan-7 的 UX 守門工具使用同一份）。
    **檔案存在就用它（再加本檔自己多擋的 `BUILTIN_EXTRA_TERMS`）；檔案不存在時改用內建清單 `BUILTIN_SHARED_TERMS`＋`BUILTIN_EXTRA_TERMS`，不略過**
    （PM 2026-11-13：守門不可因為共用檔還沒落地就悄悄關掉，覆寫 API 也不可放行工程用語）。內建的「共用」那份是從共用檔複製的，
    守門測試在共用檔存在時逐項比對，少一項就紅（同步用）。環境變數 `MOTRIX_UX_AUDIT_CONFIG` 可指向別的路徑（測試用）。
比對方式：英文禁用詞**一律不分大小寫**（不看共用檔的 `ci` 旗標；「smtp」「Smtp」都擋）、先做全形轉半形（NFKC：「ＳＭＴＰ」也擋），
    且詞前面不能緊接英文字母（「capital」不會被「API」誤擋，「tokens」「APIs」仍擋）。中文詞用一般子字串比對。
不可見字元：名稱與說明不得含零寬字元、方向控制字元、控制字元（`has_hidden_chars`），且至少要有一個看得見的字。
"""
import json
import logging
import os
import re
import threading
import unicodedata

from core import paths as _paths

logger = logging.getLogger("motrix.settings_help")

OVERRIDE_KEY = "settings_help_override"
SECTIONS = ("what", "when", "impact")           # 手寫的三段；第四段（預設值與建議）由 metadata 產生
_TEXT_MAX = 400
_FILE = _paths.backend("core", "settings_help.json")
_UX_CONFIG = _paths.backend("tools", "ux_audit_config.json")
_cache = {"mtime": None, "data": None}
_lock = threading.Lock()

#: 內建禁用詞（共用檔不存在時使用）。「共用」那份＝複製自 hichan-7 的 `ux_audit_config.json`（2026-11-13），`tests/test_settings_center_b9_2026_11_13.py` 在共用檔存在時逐項比對。
BUILTIN_SHARED_TERMS = {
    "forbidden": [("token", True), ("SMTP", False), ("Schema", False), ("migration", True), ("JSON", False), ("endpoint", True),
                  ("Callback URL", True), ("Provider", False), ("channel", True), ("public_base_url", True),
                  ("影子模式", False), ("閘門", False), ("版本帳本", False)],
    "deprecated": [("待審核", "待簽核"), ("審核中", "待簽核"), ("送審中", "待簽核"), ("申請送出審核", "申請送出簽核"), ("刪除暫存區", "資源回收筒"),
                   ("歷史紀錄", "操作紀錄"), ("等我簽核", "待我簽核"), ("簽核佇列", "待我簽核"), ("估價單", "報價單"), ("超級管理員", "最高管理者"),
                   ("最高管理員", "最高管理者"), ("超管", "最高管理者"), ("拒絕結案", "駁回結案"), ("提交", "送出"), ("保存", "儲存")],
}
#: 本檔多擋的工程用語（共用檔沒有、但設定說明裡一定不該出現）
BUILTIN_EXTRA_TERMS = [("API", False), ("webhook", True), ("cron", True), ("localhost", True), ("SQL", False), ("HTTP", False), ("regex", True), ("hash", True)]
#: 「需要另一位最高管理者同意」的說明後面補的一句（公司只有一位最高管理者時，這類變更會一直卡住）
SINGLE_ADMIN_NOTE = "若公司只有一位最高管理者，這類變更無法完成同意，請先到「使用者管理」再新增一位最高管理者。"


def has_hidden_chars(s, allow_newline: bool = False) -> bool:
    """含零寬字元、方向控制字元、控制字元、行／段分隔符，或沒有任何看得見的字 ⇒ True。（一般空白與全形空白可以）"""
    if not isinstance(s, str):
        return True
    seen = False
    for ch in s:
        cat = unicodedata.category(ch)
        if ch == "\n" and allow_newline:
            continue
        if cat in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"):
            return True
        if cat == "Zs":
            if ch not in (" ", "\u3000"):
                return True
            continue
        seen = True
    return not seen


def system_data() -> dict:
    """系統預設說明資料（依檔案修改時間快取）；壞掉 ⇒ 空資料並記 ERROR。"""
    try:
        mt = os.path.getmtime(_FILE)
    except OSError:
        mt = None
    with _lock:
        if _cache["data"] is not None and _cache["mtime"] == mt:
            return _cache["data"]
        try:
            with open(_FILE, encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("version") != 1 or not isinstance(d.get("help"), dict) or not isinstance(d.get("label_clear"), list):
                raise ValueError("格式不符")
        except Exception as exc:  # noqa: BLE001
            logger.error("說明資料檔讀取失敗（%s）⇒ 暫用空資料：%s", _FILE, type(exc).__name__)
            d = {"version": 1, "label_clear": [], "help": {}}
        _cache["mtime"], _cache["data"] = mt, d
        return d


def shared_terms_file():
    """共用禁用詞檔的內容 ⇒ `{"forbidden":[…], "deprecated":[…]}`；不存在或壞掉 ⇒ `None`。"""
    path = os.environ.get("MOTRIX_UX_AUDIT_CONFIG") or _UX_CONFIG
    try:
        with open(path, encoding="utf-8") as fh:
            c = json.load(fh)
        return {"forbidden": [(t["term"], bool(t.get("ci"))) for t in c.get("forbidden_terms", []) if isinstance(t, dict) and t.get("term")],
                "deprecated": [(t["term"], t.get("use", "")) for t in c.get("deprecated_terms", []) if isinstance(t, dict) and t.get("term")]}
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("UX 禁用詞設定檔讀取失敗（%s）：%s", path, type(exc).__name__)
        return None


def forbidden_terms():
    """⇒ `{"forbidden":[(詞, 不分大小寫)], "deprecated":[(詞, 改用)]}`；**永不回 `None`**：共用檔存在就用它，否則用內建清單；再加上本檔多擋的詞。"""
    t = shared_terms_file() or BUILTIN_SHARED_TERMS
    have = {x[0] for x in t["forbidden"]}
    return {"forbidden": list(t["forbidden"]) + [x for x in BUILTIN_EXTRA_TERMS if x[0] not in have], "deprecated": list(t["deprecated"])}


def _term_hits(text: str, terms) -> list:
    out = []
    norm = unicodedata.normalize("NFKC", text)                 # 全形英文數字轉半形
    for term, _ci in terms["forbidden"]:                       # 共用檔的 ci 旗標不採用：英文一律不分大小寫
        if term.isascii():
            if re.search(r"(?<![A-Za-z])" + re.escape(term), norm, re.IGNORECASE):
                out.append("工程用語「%s」" % term)
        elif term in norm:
            out.append("工程用語「%s」" % term)
    for term, use in terms["deprecated"]:
        if term in norm:
            out.append("舊用語「%s」（請改用「%s」）" % (term, use))
    return out


def term_problems(text) -> list:
    """一段文字（例如分類名稱）含的工程用語／舊用語 ⇒ 說明清單（空＝乾淨）。用目前生效的禁用詞（共用檔或內建）。"""
    return _term_hits(text, forbidden_terms()) if isinstance(text, str) else []


def problems_in(entry, *, terms="auto") -> list:
    """一則說明的問題清單（空＝合格）：三段都要有內容、字數上限、不含標記、不含工程用語（有禁用詞檔才檢查）。純函式（`terms` 可注入）。"""
    if not isinstance(entry, dict):
        return ["說明必須是物件"]
    out = []
    t = forbidden_terms() if terms == "auto" else terms
    for k in SECTIONS + ("example",):
        v = entry.get(k)
        if k == "example" and v in (None, ""):
            continue
        if not isinstance(v, str) or not v.strip():
            out.append("「%s」不能是空的" % k)
            continue
        if len(v) > _TEXT_MAX:
            out.append("「%s」太長（最多 %d 字）" % (k, _TEXT_MAX))
        if any(c in v for c in "<>"):
            out.append("「%s」不可含標記符號" % k)
        if has_hidden_chars(v, allow_newline=True):
            out.append("「%s」含看不見的特殊字元，或沒有任何文字" % k)
        if t:
            out += ["「%s」含%s" % (k, h) for h in _term_hits(v, t)]
    extra = set(entry) - set(SECTIONS) - {"example"}
    if extra:
        out.append("多餘的欄位：%s" % "、".join(sorted(extra)))
    return out


def label_clear() -> set:
    return set(system_data()["label_clear"])


def get_override() -> dict:
    try:
        from .settings import _get_setting
        v = _get_setting(OVERRIDE_KEY, {}) or {}
        return v if isinstance(v, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("說明覆寫讀取失敗：%s", type(exc).__name__)
        return {}


def help_for(key: str, override=None):
    """`群組.欄位` 的說明（公司覆寫優先；覆寫不合格 ⇒ 忽略、用系統預設）；沒有說明 ⇒ `None`。回 `{what,when,impact,example?,custom:bool}`。"""
    ov = get_override() if override is None else override
    o = ov.get(key)
    if isinstance(o, dict) and not problems_in(o, terms=None):
        return {**{k: o[k] for k in SECTIONS}, **({"example": o["example"]} if o.get("example") else {}), "custom": True}
    s = system_data()["help"].get(key)
    if isinstance(s, dict):
        return {**{k: s[k] for k in SECTIONS if k in s}, **({"example": s["example"]} if s.get("example") else {}), "custom": False}
    return None


def help_view(group: str, field_view: dict, override=None) -> dict:
    """設定中心欄位的說明物件（附在欄位清單裡）：`{labelClear:true}`，或 `{labelClear:false, what, when, impact, suggest, custom}`。
    第四段 `suggest` 由欄位 metadata 產生：預設值、建議值（有才寫）、範例（有才寫）。"""
    key = "%s.%s" % (group, field_view.get("key"))
    h = help_for(key, override)
    if h is None:
        return {"labelClear": key in label_clear(), "missing": key not in label_clear()}
    parts = []
    if field_view.get("defaultText") not in (None, ""):
        parts.append("系統預設：%s" % field_view["defaultText"])
    if field_view.get("recommendedText") not in (None, "") and field_view.get("recommendedText") != field_view.get("defaultText"):
        parts.append("建議：%s" % field_view["recommendedText"])
    if h.get("example") and h["example"] != field_view.get("defaultText"):          # 範例跟預設值一樣就不重複寫
        parts.append("例如：%s" % h["example"])
    impact = h["impact"]
    if "另一位最高管理者" in impact and SINGLE_ADMIN_NOTE not in impact:
        impact = impact.rstrip() + SINGLE_ADMIN_NOTE
    return {"labelClear": False, "missing": False, "what": h["what"], "when": h["when"], "impact": impact,
            "suggest": "；".join(parts) or "沿用系統預設。", "custom": h["custom"]}


def set_override(patch: dict, user: str = "", token: str = "") -> dict:
    """合併公司的說明覆寫（`{"群組.欄位": {what,when,impact,example?} | null}`；`null`＝清掉該筆覆寫回系統預設）。
    只接受有登錄的群組.欄位（有說明或在白名單內都可以覆寫）；逐筆驗證（含工程用語），任何一筆不合格 ⇒ `ValueError`（整份不寫）。"""
    from .settings import _set_setting
    if not isinstance(patch, dict) or not patch:
        raise ValueError("沒有要變更的說明")
    if len(patch) > 200:
        raise ValueError("一次最多改 200 則")
    from . import settings_registry as sr
    known = {"%s.%s" % (g, f["key"]) for g, m in sr.groups().items() for f in m["fields"]}
    new = dict(get_override())
    for k, v in patch.items():
        if k not in known:
            raise ValueError("沒有這個設定欄位：%s" % k)
        if v is None:
            new.pop(k, None)
            continue
        probs = problems_in(v)
        if probs:
            raise ValueError("%s：%s" % (k, "；".join(probs[:3])))
        new[k] = {x: v[x].strip() for x in SECTIONS + ("example",) if isinstance(v.get(x), str) and v[x].strip()}
    _set_setting(OVERRIDE_KEY, new)
    try:
        from .audit import _audit
        _audit(token, "settings_help.override", "settings_help", "-", "調整設定說明的文字",
               {"by": user, "changed": len(patch), "total": len(new), "keys": sorted(patch)[:50]})        # 只記哪些欄位被改，不記文字內容
    except Exception as exc:  # noqa: BLE001
        logger.warning("說明覆寫稽核寫入失敗：%s", type(exc).__name__)
    return new
