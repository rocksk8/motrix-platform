# -*- coding: utf-8 -*-
"""選單由登錄表產生（階段 C／C3，docs/platform/STAGE-C-DESIGN.md §4）。

[單位] plat:menu    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] ITEM_KEYS, MENU_L1, apply_layout, build, declaration, denied, load_l1, module_items, sidebar_point_id,
    validate, visible
[不變式] 選單項只來自 core/menu_l1.json 與已載入模組的 pages[].menu；群組固定鍵、模組不可自開群組；群組顯示＝底下至少一項可見
[契約題] tests/platform/test_menu_parity.py
[注意] C3 期間與 sidebar.js 舊選單並行，兩邊都要改（對等守門）

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


def _grouped(l1, mod_items, keep, with_perm):
    by = {g["key"]: [] for g in l1["groups"]}
    for it in list(l1["items"]) + list(mod_items):
        if it["group"] in by and keep(it):
            by[it["group"]].append(it)
    out = []
    for g in l1["groups"]:
        items = sorted(by[g["key"]], key=lambda it: (it["order"], it["href"]))
        if items:
            rows = []
            for it in items:
                row = {"href": it["href"], "label": it["label"], "active": list(it.get("active") or [it["href"]]),
                       "badge": it.get("badge"), "extra_badge": it.get("extra_badge"), "module": it.get("module")}
                if with_perm:
                    row["perm"] = it["perm"]
                rows.append(row)
            out.append({"key": g["key"], "label": g["label"], "items": rows})
    return out


def build(l1, mod_items, modules, superadmin):
    """⇒ [{"key", "label", "items": [{"href", "label", "active", "badge", "extra_badge", "module"}]}]（只含有可見項目的群組）。
    mod_items 只該含**已載入**模組的項目（呼叫端負責）。"""
    modules = set(modules or [])
    return _grouped(l1, mod_items, lambda it: visible(it["perm"], modules, superadmin), False)


def declaration(l1, mod_items):
    """與使用者無關的選單宣告（C4：sidebar.js 前置的 `window.MOTRIX_MENU.groups`）：build() 的排序，**不過濾**、每一項帶 perm；
    前端用 session 的模組權限同步過濾（規則同 visible）。過濾後必須等於 build(同一個使用者)——test_menu_inject 守。"""
    return _grouped(l1, mod_items, lambda it: True, True)


def sidebar_point_id(item):
    """選單項 ⇒ 它的 P9 側欄點 id（`<模組>:<頁面>/sidebar`，core.customization 衍生的同一個格式）；L1 項 ⇒ None。"""
    return "%s:%s/sidebar" % (item["module"], item["href"]) if item.get("module") else None


def apply_layout(groups, ops):
    """build() 的結果 ＋ 角色版面操作（只認 sidebar 點的 hide／show／move{index}）⇒ (新 groups, 套用的, 略過的)。
    - hide：那一項不顯示（**只是顯示，不是權限**——伺服器端權限不看版面；STAGE-C L79 更正 ③）
    - move：群組內第 index 項（0 起算；超出範圍 ⇒ 放最後），不換群組（§3.9：側欄 move 不可以帶 to）
    - 不是 sidebar 點的操作、target 不在選單上的 ⇒ 略過並列出（不猜）
    純函式；不改傳入的 groups。群組被 hide 到空 ⇒ 整個群組不出現（不留空標題）。"""
    by_id = {}
    out = []
    for g in groups:
        items = [dict(it) for it in g["items"]]
        out.append(dict(g, items=items))
        for it in items:
            pid = sidebar_point_id(it)
            if pid:
                by_id[pid] = (out[-1], it)
    applied, skipped = [], []
    hidden = set()
    for op in ops or []:
        tgt = (op or {}).get("target")
        if not isinstance(tgt, str) or not tgt.endswith("/sidebar") or op.get("op") not in ("hide", "show", "move"):
            skipped.append({"op": op, "reason": "不是側欄點的操作"})
            continue
        if tgt not in by_id:
            skipped.append({"op": op, "reason": "選單上沒有這一項（模組未載入或使用者沒有權限）"})
            continue
        if op["op"] == "hide":
            hidden.add(tgt)
        elif op["op"] == "show":
            hidden.discard(tgt)
        applied.append(op)
    for op in applied:
        if op["op"] != "move":
            continue
        g, it = by_id[op["target"]]
        if op["target"] in hidden:
            continue
        idx = op.get("index")
        if not isinstance(idx, int) or idx < 0:
            continue
        g["items"].remove(it)
        g["items"].insert(min(idx, len(g["items"])), it)
    final = []
    for g in out:
        g["items"] = [it for it in g["items"] if sidebar_point_id(it) not in hidden]
        if g["items"]:
            final.append(g)
    return final, applied, skipped
