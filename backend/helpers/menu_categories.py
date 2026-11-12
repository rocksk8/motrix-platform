# -*- coding: utf-8 -*-
"""共用分類資料檔（選單去工程師化 批次 9／批次 1「其餘」，2026-11-13）：系統總覽與設定中心都從 `core/menu_categories_l1.json` 讀「項目 → 分類」。

[單位] helper:menu_categories    [層] L1    [穩定度] 實驗
[公開介面] CATEGORY_KEYS, OVERRIDE_KEY, category_of, categories_view, default_data, effective, get_override, items_of, set_override, validate
[資料檔格式] `{"version":1, "categories":[{key,name,tier(1-3),order,blurb,when}], "items":{"<種類>:<代碼>":{category,section,order,tier,blurb,when,status,note}}}`
    項目鍵 `settings_group:<群組 key>`（設定中心）、`page:<html>`、`card:<代碼>`（系統總覽；之後由總覽那一批登錄）。
[公司可自訂（全部可自定）] 覆寫存在 `system_settings.menu_categories_override`：`{"categories":{key:{name,order}}, "items":{item:{name,order,category}}}`。
    沒覆寫＝用系統預設；覆寫只能改「名稱、順序、（項目的）所屬分類」，不能新增或刪除項目。
[不變式] ①每個項目恰好屬於一個分類（`validate` 與守門測試）；②讀取永不丟例外：資料檔壞掉或覆寫壞掉 ⇒ 回預設／忽略壞的那一筆並記 log；
    ③覆寫寫入只走 `set_override`（逐筆驗證、未知鍵拒絕、名稱長度與字元限制、寫稽核）；④這份檔案只管「放哪裡、叫什麼」，不碰任何設定值、欄位 key、儲存位置或 API。
"""
import json
import logging
import os
import threading

logger = logging.getLogger("motrix.menu_categories")

OVERRIDE_KEY = "menu_categories_override"
_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core", "menu_categories_l1.json")
_NAME_MAX = 30
_ITEM_KINDS = ("settings_group", "page", "card")
_STATUSES = ("keep", "related", "legacy")
_cache = {"mtime": None, "data": None}
_lock = threading.Lock()

#: 系統預設的分類代碼（資料檔的分類必須是這組的子集合；日後新增分類在這裡加一個、資料檔加一筆）
CATEGORY_KEYS = ("start", "company", "people", "flow", "numbering", "notify", "data", "records", "custom", "advanced")


def _clean_name(v):
    from .settings_help import has_hidden_chars
    return isinstance(v, str) and 1 <= len(v.strip()) <= _NAME_MAX and not any(c in v for c in "<>\n\r\t") and not has_hidden_chars(v)


def validate(data) -> list:
    """資料檔（或合併後的結果）的結構檢查 ⇒ 問題清單（空＝合格）。純函式。"""
    errs = []
    if not isinstance(data, dict) or data.get("version") != 1:
        return ["資料檔版本不是 1"]
    cats = data.get("categories")
    items = data.get("items")
    if not isinstance(cats, list) or not cats or not isinstance(items, dict):
        return ["缺少 categories（清單）或 items（物件）"]
    keys = []
    for c in cats:
        if not isinstance(c, dict) or not isinstance(c.get("key"), str):
            errs.append("分類缺少 key")
            continue
        k = c["key"]
        keys.append(k)
        if k not in CATEGORY_KEYS:
            errs.append("未知的分類代碼：%s" % k)
        if not _clean_name(c.get("name")):
            errs.append("分類 %s 的名稱不合法（1～%d 字、不含標記）" % (k, _NAME_MAX))
        if c.get("tier") not in (1, 2, 3):
            errs.append("分類 %s 的 tier 必須是 1、2 或 3" % k)
        if not isinstance(c.get("order"), int):
            errs.append("分類 %s 的 order 必須是整數" % k)
        for f in ("blurb", "when"):
            if not isinstance(c.get(f), str) or not c[f].strip():
                errs.append("分類 %s 缺少 %s（一句白話）" % (k, f))
    if len(set(keys)) != len(keys):
        errs.append("分類代碼重複")
    for ik, it in items.items():
        kind = ik.split(":", 1)[0] if isinstance(ik, str) else ""
        if kind not in _ITEM_KINDS or ":" not in ik or not ik.split(":", 1)[1]:
            errs.append("項目鍵格式不合法：%r（應為 settings_group:／page:／card: 開頭）" % (ik,))
            continue
        if not isinstance(it, dict):
            errs.append("項目 %s 不是物件" % ik)
            continue
        if it.get("category") not in keys:
            errs.append("項目 %s 的分類 %r 不存在（每個項目必須恰好屬於一個分類）" % (ik, it.get("category")))
        if not isinstance(it.get("order"), int):
            errs.append("項目 %s 的 order 必須是整數" % ik)
        if it.get("status") not in _STATUSES:
            errs.append("項目 %s 的 status 必須是 %s" % (ik, "／".join(_STATUSES)))
        if kind == "settings_group":
            for f in ("blurb", "when"):
                if not isinstance(it.get(f), str) or not it[f].strip():
                    errs.append("項目 %s 缺少 %s（一句白話）" % (ik, f))
    return errs


def default_data() -> dict:
    """系統預設分類資料（依檔案修改時間快取）；檔案壞掉 ⇒ 空骨架並記 ERROR（守門測試會紅）。"""
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
            probs = validate(d)
            if probs:
                raise ValueError("；".join(probs[:3]))
        except Exception as exc:  # noqa: BLE001
            logger.error("分類資料檔讀取失敗（%s）⇒ 暫用空分類：%s", _FILE, type(exc).__name__)
            d = {"version": 1, "categories": [], "items": {}}
        _cache["mtime"], _cache["data"] = mt, d
        return d


def get_override() -> dict:
    """公司的覆寫（壞掉的筆數會被忽略）。永不丟例外。"""
    try:
        from .settings import _get_setting
        v = _get_setting(OVERRIDE_KEY, {}) or {}
        return v if isinstance(v, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("分類覆寫讀取失敗：%s", type(exc).__name__)
        return {}


def effective(override=None) -> dict:
    """預設＋公司覆寫的合併結果（深複本；覆寫裡未知的鍵、不合法的名稱、不存在的分類一律略過）。"""
    base = default_data()
    ov = get_override() if override is None else override
    cats = {c["key"]: dict(c) for c in base["categories"]}
    items = {k: dict(v) for k, v in base["items"].items()}
    for k, o in ((ov.get("categories") or {}) if isinstance(ov.get("categories"), dict) else {}).items():
        if k in cats and isinstance(o, dict):
            if _clean_name(o.get("name")):
                cats[k]["name"] = o["name"].strip()
            if isinstance(o.get("order"), int) and not isinstance(o.get("order"), bool):
                cats[k]["order"] = o["order"]
    for k, o in ((ov.get("items") or {}) if isinstance(ov.get("items"), dict) else {}).items():
        if k in items and isinstance(o, dict):
            if _clean_name(o.get("name")):
                items[k]["name"] = o["name"].strip()
            if isinstance(o.get("order"), int) and not isinstance(o.get("order"), bool):
                items[k]["order"] = o["order"]
            if o.get("category") in cats:
                items[k]["category"] = o["category"]
    return {"version": 1, "categories": sorted(cats.values(), key=lambda c: (c["order"], c["key"])), "items": items}


def category_of(item_key: str) -> str:
    """項目所屬分類代碼；沒登記 ⇒ ""（呼叫端自己決定放哪）。"""
    it = effective()["items"].get(item_key)
    return it["category"] if it else ""


def items_of(category_key: str, kind: str = "") -> list:
    """分類底下的項目 `[(項目鍵, 項目)]`，依 order；`kind` 可篩 settings_group／page／card。"""
    e = effective()
    out = [(k, v) for k, v in e["items"].items() if v["category"] == category_key and (not kind or k.startswith(kind + ":"))]
    return sorted(out, key=lambda kv: (kv[1]["order"], kv[0]))


def categories_view(kind: str = "settings_group", labels: dict = None) -> list:
    """給畫面用：`[{key,name,tier,blurb,when,items:[{key,id,name,section,blurb,when,status,note,tier}]}]`（只列有項目的分類）。
    `labels`＝`{項目代碼: 預設顯示名稱}`（設定群組的名稱由登錄表提供；公司覆寫的名稱優先）。"""
    e = effective()
    out = []
    for c in e["categories"]:
        rows = []
        for k, v in sorted(((k, v) for k, v in e["items"].items() if v["category"] == c["key"] and k.startswith(kind + ":")),
                           key=lambda kv: (kv[1]["order"], kv[0])):
            ident = k.split(":", 1)[1]
            rows.append({"key": k, "id": ident, "name": v.get("name") or (labels or {}).get(ident) or ident, "section": v.get("section", ""),
                         "blurb": v.get("blurb", ""), "when": v.get("when", ""), "status": v.get("status", "keep"), "note": v.get("note", ""),
                         "tier": v.get("tier", c["tier"])})
        if rows:
            out.append({"key": c["key"], "name": c["name"], "tier": c["tier"], "blurb": c["blurb"], "when": c["when"], "items": rows})
    return out


def set_override(patch: dict, user: str = "", token: str = "") -> dict:
    """合併一份覆寫（`{"categories":{key:{name,order}|null}, "items":{item:{name,order,category}|null}}`；`null`＝清掉該筆覆寫回預設）。
    逐筆驗證：未知的分類／項目、不合法的名稱、不存在的分類 ⇒ `ValueError`（整份不寫）。成功回新的覆寫，並寫稽核。"""
    from .settings import _set_setting
    if not isinstance(patch, dict) or set(patch) - {"categories", "items"}:
        raise ValueError("只能有 categories 與 items 兩組")
    base = default_data()
    cats = {c["key"] for c in base["categories"]}
    cur = get_override()
    new = {"categories": dict(cur.get("categories") or {}), "items": dict(cur.get("items") or {})}
    for part, known in (("categories", cats), ("items", set(base["items"]))):
        sub = patch.get(part)
        if sub is None:
            continue
        if not isinstance(sub, dict):
            raise ValueError("%s 必須是物件" % part)
        for k, o in sub.items():
            if k not in known:
                raise ValueError("未知的%s：%s" % ("分類" if part == "categories" else "項目", k))
            if o is None:
                new[part].pop(k, None)
                continue
            if not isinstance(o, dict) or set(o) - ({"name", "order"} if part == "categories" else {"name", "order", "category"}):
                raise ValueError("%s 的覆寫只能含 %s" % (k, "name、order" if part == "categories" else "name、order、category"))
            clean = {}
            if "name" in o:
                if not _clean_name(o["name"]):
                    raise ValueError("%s 的名稱不合法（1～%d 字、不含標記）" % (k, _NAME_MAX))
                clean["name"] = o["name"].strip()
            if "order" in o:
                if not isinstance(o["order"], int) or isinstance(o["order"], bool) or not (-1000 <= o["order"] <= 100000):
                    raise ValueError("%s 的順序必須是整數" % k)
                clean["order"] = o["order"]
            if "category" in o:
                if o["category"] not in cats:
                    raise ValueError("%s 的分類不存在：%s" % (k, o["category"]))
                clean["category"] = o["category"]
            new[part][k] = clean
    new = {p: v for p, v in new.items() if v}
    _set_setting(OVERRIDE_KEY, new)
    try:
        from .audit import _audit
        _audit(token, "menu_categories.override", "menu_categories", "-", "調整系統分類的名稱／順序",
               {"by": user, "categories": len(new.get("categories", {})), "items": len(new.get("items", {})),
                "changed": {"categories": sorted(patch.get("categories") or {})[:50], "items": sorted(patch.get("items") or {})[:50]}})        # 只記哪些項目被改，不記名稱內容
    except Exception as exc:  # noqa: BLE001
        logger.warning("分類覆寫稽核寫入失敗：%s", type(exc).__name__)
    return new
