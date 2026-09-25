# -*- coding: utf-8 -*-
"""L0 模組登錄表（docs/platform/CORE-SPEC.md §4、§5）。

L2 模組在 `modules/<key>/__init__.py` 宣告 `MODULE = ModuleSpec(...)`；
main.py 只迭代這張表，不指名任何模組 ⇒ 刪掉模組資料夾＝少一個功能，不是啟動失敗。

提供者（provider）：模組把能力登記在 `(capability, name)` 底下，
使用方用 `providers(capability)` 取；對方沒裝時拿到空 dict，使用方要當成「少一項」處理。
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

#: 共用核心的契約版本；模組以 module.json 的 `core` 範圍宣告相容性。
CORE_VERSION = "1.0"


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


def _reset():
    """測試用：清空登錄表。"""
    _LOADED.clear()
    _FAILED.clear()


def register(loaded: LoadedModule) -> None:
    _LOADED[loaded.key] = loaded


def mark_failed(key: str, reason: str) -> None:
    _FAILED[key] = reason


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
    for m in _LOADED.values():
        for (cap, name), fn in m.spec.providers.items():
            if cap == capability:
                out[name] = fn
    return out
