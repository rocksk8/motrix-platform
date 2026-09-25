# -*- coding: utf-8 -*-
"""能力目錄（CUSTOMIZATION-SPEC P1；CORE-SPEC §7 端點登錄表的擴充）。

**唯一來源**：自訂模組建構器（P8）、排版器（P9）、內建模組都只從這裡挑。
目錄本身不擁有任何清單，只**收集**：

| 區段 | 來源（擁有者） |
|---|---|
| `modules[].endpoints` | 已載入模組的 `ModuleSpec.routers`（程式實際提供的路由，不是宣告） |
| `modules[].points` | `module.json` 的 `customization`＋`pages[].menu`，經 `_module_points` 過濾（＝`layout_points()` 同一份） |
| `providers` | `core.registry`（模組的 `ModuleSpec.providers`＋尚未搬遷模組的 `registry.provide`） |
| `events` | `core.events.declarations()` |
| 其他區段（`outputs`、`fieldTypes`、`formulaFunctions`…） | 擁有者以 `register_section(name, owner, fn)` 登記；**擁有者不在 ⇒ 區段標 unavailable 並說明**，不自己補一份清單 |

不在這裡寫死任何能力清單：寫死的那一份就是第二個來源。

**可自訂點的唯一入口**（稽核 P-M1）：`layout_points(module_key)`。過濾只在 `_module_points` 一處：
引用不存在端點／版型的點、選單裡被藏起的按鈕、未載入的模組。目錄 `build()`、排版守門 `check_layout()`
（P5 layout 驗證器與 P9 都必須呼叫它）都只經過這一處；`customization._raw_points` 不准在別處呼叫（守門）。
"""
import threading
from typing import Callable, Dict, Tuple

from core import customization, events, registry

#: 目錄回應的格式版本（欄位只准加；改名／刪除要升版）。
CATALOG_VERSION = 1

#: 規格要求目錄一定要回答的區段（CUSTOMIZATION-SPEC §2、§5 P1）。沒有擁有者登記時照樣列出、標缺口。
EXPECTED_SECTIONS = ("outputs", "fieldTypes", "formulaFunctions")

_lock = threading.Lock()
_SECTIONS: Dict[str, Tuple[str, Callable[[], object]]] = {}


def register_section(name: str, owner: str, fn: Callable[[], object]) -> None:
    """擁有者登記一個區段（通常在擁有者模組匯入時）。

    同名只准同一個擁有者重複登記（重新匯入）；不同擁有者搶同一個名字 ⇒ 兩個來源，直接報錯。"""
    if not isinstance(name, str) or not name or name in ("modules", "providers", "events", "catalogVersion", "coreVersion", "gaps"):
        raise ValueError("區段名稱不可用：%r" % (name,))
    with _lock:
        old = _SECTIONS.get(name)
        if old is not None and old[0] != owner:
            raise ValueError("能力目錄區段 %s 已由 %s 登記，%s 不可以再登記一份" % (name, old[0], owner))
        _SECTIONS[name] = (owner, fn)


def section(name: str):
    """單一區段的內容（給舊端點做投影用，例：P8 的 /api/custom-modules/catalog）。沒有擁有者 ⇒ KeyError。"""
    with _lock:
        owner, fn = _SECTIONS[name]
    return fn()


def _route_entries(router):
    """APIRouter ⇒ [(method, path, route)]。新舊 FastAPI 都適用（0.14x 起 include 進來的是 _IncludedRouter）。"""
    out = []
    for r in getattr(router, "routes", []) or []:
        contexts = getattr(r, "effective_route_contexts", None)
        if callable(contexts):
            items = [(c.path, c.methods, c) for c in contexts()]
        elif hasattr(r, "path"):
            items = [(r.path, getattr(r, "methods", None), r)]
        else:
            items = []
        for path, methods, obj in items:
            for m in sorted(methods or ()):
                if m in ("HEAD", "OPTIONS"):
                    continue
                out.append((m, path, obj))
    return out


def _params(route):
    dep = getattr(route, "dependant", None)
    if dep is None:
        return {}
    names = lambda ps: [p.name for p in ps if p.name != "authorization"]  # noqa: E731
    return {"path": names(dep.path_params), "query": names(dep.query_params),
            "body": bool(dep.body_params)}


def module_endpoints(spec) -> list:
    out = []
    for router in spec.routers:
        for method, path, route in _route_entries(router):
            doc = (getattr(route, "description", None) or getattr(getattr(route, "endpoint", None), "__doc__", None) or "").strip()
            out.append({"method": method, "path": path, "id": "%s %s" % (method, path),
                        "summary": doc.splitlines()[0] if doc else "", "params": _params(route)})
    out.sort(key=lambda e: (e["path"], e["method"]))
    return out


def endpoint_problems(pts, endpoints) -> list:
    """登記的點引用了程式沒有提供的端點 ⇒ 問題（CORE-SPEC §7：宣告了卻不存在）。"""
    have = {e["id"] for e in endpoints}
    out = []
    for p in pts:
        ep = p.get("endpoint")
        if ep and ep not in have:
            out.append({"point": p["id"], "message": "端點 %s 不存在於模組的路由（程式沒有提供）" % ep})
    return out


def output_problems(pts, templates) -> list:
    """輸出點引用的預設版型不存在 ⇒ 問題。`templates=None`（輸出引擎不在）⇒ 每一個輸出點都是問題。"""
    out = []
    for p in pts:
        if p.get("kind") != "output":
            continue
        if templates is None:
            out.append({"point": p["id"], "message": "輸出引擎沒有登記（outputs 區段不存在），無法確認版型 %s" % p["template"]})
        elif p["template"] not in templates:
            out.append({"point": p["id"], "message": "預設版型 %s 不存在（程式沒有提供）" % p["template"]})
    return out


def _templates_of(outputs_entry):
    """outputs 區段 ⇒ 可選版型 key 集合；區段不在或擁有者失敗 ⇒ None（每一個輸出點都是問題）。"""
    if not isinstance(outputs_entry, dict) or not outputs_entry.get("available"):
        return None
    return {t.get("key") for t in (outputs_entry.get("items") or {}).get("templates", [])}


def _outputs_entry():
    with _lock:
        owned = _SECTIONS.get("outputs")
    if owned is None:
        return None
    try:
        return {"available": True, "items": owned[1]()}
    except Exception:                                           # noqa: BLE001 與 build() 同一判準：失敗 ⇒ 沒有版型
        return None


def _module_points(m, templates, eps=None):
    """**唯一的過濾處**：已載入模組 ⇒ (可用的點, problems)。

    - 引用了模組路由沒有的端點 ⇒ 藏起、列 problems
    - 輸出點的預設版型不存在（或 outputs 區段不在）⇒ 藏起、列 problems；留下的輸出點帶 `templates`（可選版型）
    - 選單項目引用了被藏起的按鈕 ⇒ 從 items 拿掉；選單因此沒有項目 ⇒ 選單也藏起、列 problems
    """
    if eps is None:
        eps = module_endpoints(m.spec)
    pts = customization._raw_points(m.manifest or {})        # noqa: SLF001 唯一允許的呼叫點（守門）
    problems = endpoint_problems(pts, eps) + output_problems(pts, templates)
    bad = {p["point"] for p in problems}
    kept = []
    for p in pts:
        if p["id"] in bad:
            continue
        if p["kind"] == "menu":
            items = [it for it in p["items"] if it not in bad]
            if not items:
                problems.append({"point": p["id"], "message": "選單的按鈕全部被藏起（程式沒有提供）⇒ 選單不列出"})
                continue
            p = dict(p, items=items)
        elif p["kind"] == "output":
            p = dict(p, templates=sorted(templates))
        kept.append(p)
    return kept, problems


def layout_points(module_key=None) -> list:
    """可自訂點的**唯一入口**（目錄與排版守門同一份）。`module_key=None` ⇒ 全部已載入模組。

    未載入（停用／未授權／載入失敗／不存在）的模組 ⇒ 沒有任何點。"""
    templates = _templates_of(_outputs_entry())
    out = []
    for m in sorted(registry.loaded(), key=lambda x: x.key):
        if module_key is None or m.key == module_key:
            out += _module_points(m, templates)[0]
    return out


def check_layout(module_key, ops) -> list:
    """排版操作守門（P5 `layout` 驗證器與 P9 都必須呼叫它）：只能動 `layout_points(module_key)` 裡的點。
    ⇒ 問題清單 `[{path, message}]`，空＝合格。"""
    return customization._check_ops(layout_points(module_key), ops)   # noqa: SLF001


def _providers():
    rows = {}
    for (cap, name), fn in registry._LEGACY_PROVIDERS.items():   # noqa: SLF001 同屬 core，只讀
        rows[(cap, name)] = {"capability": cap, "name": name, "module": None, "source": "legacy",
                             "function": "%s.%s" % (getattr(fn, "__module__", "?"), getattr(fn, "__qualname__", "?"))}
    for m in registry.loaded():
        for (cap, name), fn in m.spec.providers.items():
            rows[(cap, name)] = {"capability": cap, "name": name, "module": m.key, "source": "module",
                                 "function": "%s.%s" % (getattr(fn, "__module__", "?"), getattr(fn, "__qualname__", "?"))}
    out = []
    for k in sorted(rows):
        r = rows[k]
        # 契約版本登記在 INTEGRATION-POINTS.md（文件不隨部署包出貨）；程式裡沒有機器可讀的版本 ⇒ 明說，不猜
        r["contractVersion"] = None
        out.append(r)
    return out


def build() -> dict:
    """整份目錄。只讀，不改任何狀態。"""
    gaps = []
    with _lock:
        sections = dict(_SECTIONS)
    extra = {}
    for name in sorted(set(sections) | set(EXPECTED_SECTIONS)):
        if name not in sections:
            extra[name] = {"available": False, "owner": None, "items": [],
                           "reason": "沒有擁有者登記這個區段（提供它的功能尚未安裝或尚未合回）"}
            gaps.append({"section": name, "message": extra[name]["reason"]})
            continue
        owner, fn = sections[name]
        try:
            extra[name] = {"available": True, "owner": owner, "items": fn()}
        except Exception as e:                                  # noqa: BLE001 一個區段壞掉不可以拖垮整份目錄
            extra[name] = {"available": False, "owner": owner, "items": [],
                           "reason": "擁有者回報失敗：%s: %s" % (type(e).__name__, e)}
            gaps.append({"section": name, "message": extra[name]["reason"]})

    templates = _templates_of(extra.get("outputs"))

    mods = []
    for m in sorted(registry.loaded(), key=lambda x: x.key):
        man = m.manifest or {}
        eps = module_endpoints(m.spec)
        pts, problems = _module_points(m, templates, eps)
        mods.append({
            "key": m.key, "name": man.get("name") or m.key, "version": man.get("version") or "",
            "core": man.get("core") or "", "permissions": list(man.get("permissions") or []),
            "pages": [pg.get("path") for pg in (man.get("pages") or []) if isinstance(pg, dict)],
            "customizationSchema": (man.get("customization") or {}).get("schema") if isinstance(man.get("customization"), dict) else None,
            "coreFields": customization.core_fields(man),
            "endpoints": eps,
            # 引用了程式沒有提供的東西的點不列出（排版器看不到它），改列在 problems
            "points": pts,
            "problems": problems,
        })

    evs = [{"name": d.name, "owner": d.owner, "version": d.version, "fields": list(d.fields),
            "description": d.description, "subscribers": events.subscribers(d.name)}
           for d in events.declarations()]

    return {"catalogVersion": CATALOG_VERSION, "coreVersion": registry.CORE_VERSION,
            "modules": mods, "providers": _providers(), "events": evs, **extra, "gaps": gaps}


# ── 測試用 ──────────────────────────────────────────────────────────────────
def snapshot():
    with _lock:
        return dict(_SECTIONS)


def restore(state):
    with _lock:
        _SECTIONS.clear()
        _SECTIONS.update(state)
