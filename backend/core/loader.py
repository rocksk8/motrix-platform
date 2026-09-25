# -*- coding: utf-8 -*-
"""L0 模組載入器：掃 `modules/*/module.json`，相容且匯入成功的才登錄。

失敗一律「不載入＋記 ERROR＋記進 registry.failed()」，不讓整台伺服器起不來；
版本範圍看不懂時也是不載入——算不出相容性就不猜。
"""
import importlib
import json
import logging
import os
import re

from core import registry

logger = logging.getLogger("motrix.loader")

MODULES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modules")

_CMP = re.compile(r"^\s*(>=|<=|==|>|<)\s*(\d+(?:\.\d+)*)\s*$")


def _ver(s):
    return tuple(int(x) for x in s.split("."))


def _pad(a, b):
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def core_compatible(spec: str, core_version: str = registry.CORE_VERSION) -> bool:
    """`spec` 形如 ">=1.0,<2.0"。任何一段看不懂 ⇒ ValueError（呼叫端當成不相容）。"""
    parts = [p for p in (spec or "").split(",") if p.strip()]
    if not parts:
        raise ValueError("empty core range")
    cur = _ver(core_version)
    for p in parts:
        m = _CMP.match(p)
        if not m:
            raise ValueError(f"unparsable core range: {p!r}")
        op, v = m.group(1), _ver(m.group(2))
        a, b = _pad(cur, v)
        ok = {">=": a >= b, "<=": a <= b, "==": a == b, ">": a > b, "<": a < b}[op]
        if not ok:
            return False
    return True


def _read_manifest(folder):
    with open(os.path.join(folder, "module.json"), encoding="utf-8") as f:
        return json.load(f)


def load_all(modules_dir: str = MODULES_DIR, package: str = "modules"):
    """回傳成功載入的 LoadedModule 清單（依資料夾名排序，結果可重現）。"""
    if not os.path.isdir(modules_dir):
        return []
    for name in sorted(os.listdir(modules_dir)):
        folder = os.path.join(modules_dir, name)
        if not os.path.isfile(os.path.join(folder, "module.json")):
            continue
        try:
            manifest = _read_manifest(folder)
            if manifest.get("key") != name:
                raise ValueError(f"module.json key {manifest.get('key')!r} != folder {name!r}")
            try:
                ok = core_compatible(manifest.get("core", ""))
            except ValueError as e:
                raise ValueError(f"core range: {e}")
            if not ok:
                raise ValueError(f"requires core {manifest.get('core')}, have {registry.CORE_VERSION}")
            mod = importlib.import_module(f"{package}.{name}")
            spec = getattr(mod, "MODULE", None)
            if not isinstance(spec, registry.ModuleSpec) or spec.key != name:
                raise ValueError("MODULE missing or key mismatch")
        except Exception as e:  # 單一模組壞掉不可以拖垮整台
            registry.mark_failed(name, str(e))
            logger.error("模組 %s 未載入：%s", name, e)
            continue
        registry.register(registry.LoadedModule(key=name, manifest=manifest, spec=spec))
        logger.info("模組 %s %s 已載入", name, manifest.get("version", "?"))
    return registry.loaded()
