# -*- coding: utf-8 -*-
"""L0 模組登錄表（docs/platform/CORE-SPEC.md §4、§5）。

[單位] plat:registry    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] CORE_VERSION, LoadedModule, ModuleSpec, RuntimeSwitch, STATES, disabled_list, failed, is_loaded,
    loaded, mark_failed, module_states, provide, providers, register, restore, runtime_switches,
    set_disabled_list, set_state, single_provider, snapshot, unload
[不變式] main.py 只迭代這張表、不指名模組；對方沒裝時 providers() 回空 dict、single_provider() 回 None（不是錯誤）
[契約題] tests/platform/test_core_loader.py, tests/platform/test_module_selection.py
[注意] CORE_VERSION 在合回時才定（§C-7，用 core_bump）；測試夾具一律用 snapshot()／restore()

L2 模組在 `modules/<key>/__init__.py` 宣告 `MODULE = ModuleSpec(...)`；
main.py 只迭代這張表，不指名任何模組 ⇒ 刪掉模組資料夾＝少一個功能，不是啟動失敗。

提供者（provider）：模組把能力登記在 `(capability, name)` 底下，
使用方用 `providers(capability)` 取；對方沒裝時拿到空 dict，使用方要當成「少一項」處理。
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

#: 共用核心的契約版本；模組以 module.json 的 `core` 範圍宣告相容性。
CORE_VERSION = "1.26"


@dataclass
class RuntimeSwitch:
    """會改變「這台機器會不會對外連線」的開關；由 /api/system/runtime-switches 列出。"""
    env: str
    label: str
    is_on: Callable[[], bool]


@dataclass
class ModuleSpec:
    key: str
    routers: list = field(default_factory=list)
    #: 只在排程閘門開著時呼叫（MOTRIX_DISABLE_SCHEDULERS != "1"）
    schedulers: List[Callable[[], None]] = field(default_factory=list)
    #: 不論排程開關都呼叫；回傳要記的 log 字串或 None
    startup_notices: List[Callable[[], Optional[str]]] = field(default_factory=list)
    runtime_switches: List[RuntimeSwitch] = field(default_factory=list)
    providers: Dict[Tuple[str, str], Callable] = field(default_factory=dict)


@dataclass
class LoadedModule:
    key: str
    manifest: dict
    spec: ModuleSpec


_LOADED: Dict[str, LoadedModule] = {}
_FAILED: Dict[str, str] = {}
#: 每個 modules/<key> 這次啟動的結果（CORE-SPEC §9c）：
#:   {"key","name","version","state","reason","note","pages","license_key"}，
#:   state ∈ STATES。reason 非空＝有問題（未授權／停用／失敗的原因）；note＝不是問題但要讓人看到的狀態
#:   （例：loaded 而「授權檢查未啟用」，CORE-SPEC §9c）。「不在包內」的模組沒有資料夾，這裡不會出現（優先順序最高）。
_STATES: Dict[str, dict] = {}
STATE_LOADED, STATE_UNLICENSED, STATE_DISABLED, STATE_FAILED = "loaded", "unlicensed", "disabled", "failed"
STATES = (STATE_LOADED, STATE_UNLICENSED, STATE_DISABLED, STATE_FAILED)
#: 這次啟動讀停用清單的結果（STATES-PLATFORM P-SW-05）：{"source", "message"}。
#: source ∈ db（讀到主庫）／no_db（主庫不存在）／cache（主庫讀不到，沿用上次成功讀到的清單）／
#: unreadable（讀不到也沒有快取 ⇒ 所有模組暫不載入）。沒有設定過＝空 dict（例：測試直接呼叫 load_all）。
_DISABLED_LIST: Dict[str, str] = {}
#: 尚未搬進 modules/ 的模組（仍在 routers/、helpers/）登記的提供者：{(capability, name): fn}。
#: 搬遷後改寫進 ModuleSpec.providers，這裡的登記一併刪掉。
_LEGACY_PROVIDERS: Dict[Tuple[str, str], Callable] = {}


def _reset():
    """測試用：清空登錄表（不動 _LEGACY_PROVIDERS——那是模組匯入時登記的，清了就回不來）。"""
    _LOADED.clear()
    _FAILED.clear()
    _STATES.clear()
    _DISABLED_LIST.clear()


def snapshot() -> tuple:
    """測試用：整份登錄表的複本。夾具一律用 snapshot()/restore()，不要自己列舉內部表——
    新增一張表時，自己列舉的夾具會漏掉它（2026-09-25 實例：_STATES 被清空沒還原，
    全量時同一個 worker 後面的題全紅）。_LEGACY_PROVIDERS 是模組匯入時登記的，不在這裡動。"""
    return dict(_LOADED), dict(_FAILED), {k: dict(v) for k, v in _STATES.items()}, dict(_DISABLED_LIST)


def restore(snap: tuple) -> None:
    _reset()
    _LOADED.update(snap[0])
    _FAILED.update(snap[1])
    _STATES.update(snap[2])
    _DISABLED_LIST.update(snap[3])


def set_state(key: str, state: str, reason: str = "", manifest: Optional[dict] = None, note: str = "") -> None:
    if state not in STATES:
        raise ValueError(f"unknown module state {state!r}")
    m = manifest or {}
    _STATES[key] = {"key": key, "name": m.get("name") or key, "version": m.get("version") or "",
                    "license_key": m.get("license_key") or key,
                    "pages": [pg.get("path") for pg in (m.get("pages") or []) if pg.get("path")],
                    "state": state, "reason": reason, "note": note or ""}


def set_disabled_list(source: str, message: str = "") -> None:
    """記下這次啟動的停用清單來源（管理頁與狀態端點顯示）。"""
    _DISABLED_LIST.clear()
    _DISABLED_LIST.update({"source": source, "message": message})


def disabled_list() -> dict:
    return dict(_DISABLED_LIST)


def module_states() -> List[dict]:
    """依 key 排序；給系統設定頁與選單用。"""
    return [dict(_STATES[k]) for k in sorted(_STATES)]


def provide(capability: str, name: str, fn: Callable) -> None:
    """給還沒搬進 modules/ 的模組在匯入時登記提供者（例：routers/vendor_contractors 的
    `dispatch.row`）。同名重複登記須是同一個函式，否則是兩份實作在搶，直接報錯。"""
    key = (capability, name)
    if key in _LEGACY_PROVIDERS and _LEGACY_PROVIDERS[key] is not fn:
        raise ValueError(f"provider {capability}/{name} 已登記為另一個函式")
    _LEGACY_PROVIDERS[key] = fn


def register(loaded: LoadedModule) -> None:
    _LOADED[loaded.key] = loaded


def mark_failed(key: str, reason: str) -> None:
    _FAILED[key] = reason


def unload(key: str, reason: str) -> None:
    """已 import、但不可以掛上的模組（例：路由衝突，STATES-PLATFORM P-LD-07）改記為 failed：
    移出已載入清單（provider、runtime switch、排程、路由都不會再從這裡取到它）。"""
    lm = _LOADED.pop(key, None)
    mark_failed(key, reason)
    set_state(key, STATE_FAILED, reason, lm.manifest if lm else None)


def loaded() -> List[LoadedModule]:
    return list(_LOADED.values())


def failed() -> Dict[str, str]:
    return dict(_FAILED)


def is_loaded(key: str) -> bool:
    return key in _LOADED


def runtime_switches() -> List[RuntimeSwitch]:
    return [s for m in _LOADED.values() for s in m.spec.runtime_switches]


def providers(capability: str) -> Dict[str, Callable]:
    """回傳 {name: fn}；沒有任何模組提供時是空 dict（不是錯誤）。"""
    out = {}
    for (cap, name), fn in _LEGACY_PROVIDERS.items():
        if cap == capability:
            out[name] = fn
    for m in _LOADED.values():
        for (cap, name), fn in m.spec.providers.items():
            if cap == capability:
                out[name] = fn
    return out


def single_provider(capability: str) -> Optional[Callable]:
    """單一提供者的能力（例：`dispatch.row` 只有 M04 會提供）。沒有 ⇒ None，使用方退化處理。
    超過一個 ⇒ 兩份實作在搶同一件事，報錯而不是隨便挑一個。"""
    found = providers(capability)
    if len(found) > 1:
        raise RuntimeError(f"{capability} 有多個提供者：{sorted(found)}")
    return next(iter(found.values()), None)
