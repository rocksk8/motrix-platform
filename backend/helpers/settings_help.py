# -*- coding: utf-8 -*-
"""設定中心「?」說明（選單去工程師化 批次 9，2026-11-13）：每個設定欄位要嘛「標籤已夠清楚」（白名單），要嘛有四段說明。

[單位] helper:settings_help    [層] L1    [穩定度] 實驗
[公開介面] OVERRIDE_KEY, SECTIONS, forbidden_terms, help_for, help_view, label_clear, problems_in, set_override, system_data
[資料檔] `core/settings_help.json`：`{"version":1, "label_clear":["群組.欄位",…], "help":{"群組.欄位":{"what","when","impact","example"?}}}`。
    **文字不寫在 HTML 裡**；key 一律是「群組.欄位」（欄位代碼在不同群組會重複，例如 enabled）。
[四段] ①這是什麼（what）②什麼時候要改（when）③改了會影響什麼（impact）④預設值與建議——**第四段執行時由設定欄位的 metadata 產生**
    （預設值、建議值、範例），不手寫，所以不會與程式漂移。
[公司可自訂（全部可自定）] 覆寫存在 `system_settings.settings_help_override`：`{"群組.欄位":{what,when,impact,example}}`；沒覆寫＝系統預設。
    覆寫逐筆驗證（四段字數、不含標記、不含工程用語），壞掉的覆寫在讀取時被忽略並回系統預設。
[工程用語守門] 禁用詞單一來源是 `backend/tools/ux_audit_config.json`（`forbidden_terms`、`deprecated_terms`；hichan-7 的 UX 守門工具使用同一份）。
    **不複製清單**；檔案不存在（那個分支還沒落地）時，工程用語檢查略過並回 `None`，落地後自動生效。環境變數 `MOTRIX_UX_AUDIT_CONFIG` 可指向別的路徑（測試用）。
[不變式] ①讀取永不丟例外；②資料檔壞掉 ⇒ 空資料並記 ERROR（守門測試會紅）；③只讀設定欄位的 metadata，不改任何設定值、欄位 key、儲存位置或 API。
"""
import json
import logging
import os
import threading

logger = logging.getLogger("motrix.settings_help")

OVERRIDE_KEY = "settings_help_override"
SECTIONS = ("what", "when", "impact")           # 手寫的三段；第四段（預設值與建議）由 metadata 產生
_TEXT_MAX = 400
_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "settings_help.json")
_UX_CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "ux_audit_config.json")
_cache = {"mtime": None, "data": None}
_lock = threading.Lock()


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


def forbidden_terms():
    """⇒ `{"forbidden":[(詞, 不分大小寫)], "deprecated":[(詞, 改用)]}`；設定檔不存在或壞掉 ⇒ `None`（呼叫端略過檢查）。"""
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


def _term_hits(text: str, terms) -> list:
    out = []
    low = text.lower()
    for term, ci in terms["forbidden"]:
        if (term.lower() in low) if ci else (term in text):
            out.append("工程用語「%s」" % term)
    for term, use in terms["deprecated"]:
        if term in text:
            out.append("舊用語「%s」（請改用「%s」）" % (term, use))
    return out


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
    if h.get("example"):
        parts.append("例如：%s" % h["example"])
    return {"labelClear": False, "missing": False, "what": h["what"], "when": h["when"], "impact": h["impact"],
            "suggest": "；".join(parts) or "沿用系統預設。", "custom": h["custom"]}


def set_override(patch: dict, user: str = "") -> dict:
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
        _audit("", "settings_help.override", "settings_help", "-", "調整設定說明的文字", {"by": user, "changed": len(patch), "total": len(new)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("說明覆寫稽核寫入失敗：%s", type(exc).__name__)
    return new
