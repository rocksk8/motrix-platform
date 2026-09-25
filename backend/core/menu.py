# -*- coding: utf-8 -*-
"""選單由登錄表產生（階段 C／C3，docs/platform/STAGE-C-DESIGN.md §4）。

來源：
  - `core/menu_l1.json`：群組（固定鍵，裁示 D4：模組不可以自己開群組）＋ L1 頁面的選單項
  - 已載入模組的 module.json `pages[].menu`：`{group, label, order, perm, active?, badge?, extra_badge?}`
    （模組沒載入 ⇒ 它的項目不出現：選單與頁面 404 同一個判準）

權限（perm）：
  - `["k1", "k2"]`：有任一模組權限即可；最高管理者一律可（同 sidebar.js `has()`）
  - `"superadmin"`：只限最高管理者
  - `"any"`：任何登入者
群組**不另設條件**：群組顯示＝底下至少一項可見（舊碼 UI8 那一類「群組條件與項目條件各自演進」從結構上消失）。
排序：群組依 menu_l1.json 的順序；群組內依 `order`（同 order 依 href）。
"""
import json
from pathlib import Path

MENU_L1 = Path(__file__).with_name("menu_l1.json")
ITEM_KEYS = {"group", "href", "label", "order", "perm", "active", "badge", "extra_badge"}


def load_l1(path=MENU_L1):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def module_items(manifests):
    """{模組key: manifest} ⇒ [item（帶 "href"＝頁面檔名、"module"＝key）]。"""
    out = []
    for key in sorted(manifests):
        for p in (manifests[key] or {}).get("pages") or []:
            menu = p.get("menu") if isinstance(p, dict) else None
            if menu:
                out.append(dict(menu, href=p.get("path"), module=key))
    return out


def _perm_ok(perm):
    return perm in ("any", "superadmin") or (isinstance(perm, list) and perm and all(isinstance(k, str) and k for k in perm))


def validate(l1, mod_items=()):
    """宣告有問題 ⇒ 問題清單（守門與啟動檢查共用）。"""
    problems = []
    groups = [g.get("key") for g in l1.get("groups") or []]
    if len(set(groups)) != len(groups) or not all(groups):
        problems.append("群組鍵重複或空白：%r" % groups)
    seen = {}
    for it in list(l1.get("items") or []) + list(mod_items):
        where = "模組 %s" % it["module"] if it.get("module") else "L1"
        extra = set(it) - ITEM_KEYS - {"module"}
        if extra:
            problems.append("%s 的選單項 %s 有不認得的欄位：%s" % (where, it.get("href"), sorted(extra)))
        if it.get("group") not in groups:
            problems.append("%s 的選單項 %s 用了不存在的群組 %r（群組只能在 L1 定義）" % (where, it.get("href"), it.get("group")))
        if not isinstance(it.get("order"), int):
            problems.append("%s 的選單項 %s 缺整數 order" % (where, it.get("href")))
        if not _perm_ok(it.get("perm")):
            problems.append("%s 的選單項 %s 的 perm 不合法：%r" % (where, it.get("href"), it.get("perm")))
        if not it.get("label") or not it.get("href"):
            problems.append("%s 有選單項缺 label 或 href：%r" % (where, it))
        if it.get("href") in seen:
            problems.append("選單項 %s 重複（%s 與 %s）" % (it.get("href"), seen[it["href"]], where))
        seen[it.get("href")] = where
    return problems


def visible(perm, modules, superadmin):
    if perm == "any":
        return True
    if perm == "superadmin":
        return bool(superadmin)
    return bool(superadmin) or any(k in modules for k in perm)


def denied(l1, mod_items, modules, superadmin):
    """使用者看不到的選單項的 active 名單（舊碼 `_deniedPages`：站在這些頁上 ⇒ 顯示「沒有權限」，不導轉）。"""
    modules = set(modules or [])
    out = []
    for it in list(l1["items"]) + list(mod_items):
        if not visible(it["perm"], modules, superadmin):
            out += list(it.get("active") or [it["href"]])
    return sorted(set(out))


def build(l1, mod_items, modules, superadmin):
    """⇒ [{"key", "label", "items": [{"href", "label", "active", "badge", "extra_badge", "module"}]}]（只含有可見項目的群組）。
    mod_items 只該含**已載入**模組的項目（呼叫端負責）。"""
    modules = set(modules or [])
    by = {g["key"]: [] for g in l1["groups"]}
    for it in list(l1["items"]) + list(mod_items):
        if it["group"] in by and visible(it["perm"], modules, superadmin):
            by[it["group"]].append(it)
    out = []
    for g in l1["groups"]:
        items = sorted(by[g["key"]], key=lambda it: (it["order"], it["href"]))
        if items:
            out.append({"key": g["key"], "label": g["label"], "items": [
                {"href": it["href"], "label": it["label"], "active": list(it.get("active") or [it["href"]]),
                 "badge": it.get("badge"), "extra_badge": it.get("extra_badge"), "module": it.get("module")}
                for it in items]})
    return out
