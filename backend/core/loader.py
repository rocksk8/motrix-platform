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
from core import customization

logger = logging.getLogger("motrix.loader")

MODULES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modules")
#: 與 MODULES_DIR 成對：資料夾底下的模組以 `<MODULES_PACKAGE>.<key>` import。
#: 兩者都在 `load_all()` **呼叫當下**才讀（不綁在預設參數上）⇒ 子行程守門可以在 `import main`
#: 之前換成合成模組樹，驗「core-only＋合成模組」而不綁任何真實的 L2 模組（AUDIT-X-9c A-2）。
MODULES_PACKAGE = "modules"

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


def _current_modules_dir():
    """呼叫當下的 MODULES_DIR（程式碼目錄，不是資料；與原本的預設參數同一個值）。"""
    return MODULES_DIR


def _read_manifest(folder):
    with open(os.path.join(folder, "module.json"), encoding="utf-8") as f:
        return json.load(f)


def load_all(modules_dir: str = None, package: str = None,
             license_check=None, disabled=frozenset()):
    """回傳成功載入的 LoadedModule 清單（依資料夾名排序，結果可重現）。

    CORE-SPEC §9c 的優先順序：① 不在包內（沒有資料夾 ⇒ 根本不會出現）> ② 未授權 > ③ 管理者停用。
    ②③ 都**不 import** 該模組（路由不掛、排程不跑、提供者不登記），資料不動。

    `license_check(manifest) -> (ok, reason)`：由呼叫端（main.py）注入——L0 不依賴 L1 的授權實作。
    沒給 ⇒ 不檢查。`disabled`：管理者停用的模組 key 集合（啟動時讀一次；改了要重啟才生效）。
    ok 時的 reason（例：「授權檢查未啟用」）不是錯誤，寫進狀態的 `note`，不寫進 `reason`
    （`reason` 非空＝有問題，模組管理頁與儀表板都這樣判斷）。
    `modules_dir`／`package` 沒給 ⇒ 讀呼叫當下的 MODULES_DIR／MODULES_PACKAGE。
    """
    if modules_dir is None:
        modules_dir = _current_modules_dir()
    if package is None:
        package = MODULES_PACKAGE
    if not os.path.isdir(modules_dir):
        return []
    for name in sorted(os.listdir(modules_dir)):
        folder = os.path.join(modules_dir, name)
        if not os.path.isfile(os.path.join(folder, "module.json")):
            continue
        manifest = None
        note = ""
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
            customization.require_valid(manifest)   # 可自訂點格式錯誤 ⇒ 不載入（CUSTOMIZATION-SPEC P3）
            if license_check is not None:
                licensed, why = license_check(manifest)
                if not licensed:
                    registry.mark_failed(name, why)
                    registry.set_state(name, registry.STATE_UNLICENSED, why, manifest)
                    logger.warning("模組 %s 未載入（未授權）：%s", name, why)
                    continue
                note = why or ""
            if name in disabled:
                registry.set_state(name, registry.STATE_DISABLED, "管理者已停用（資料保留）", manifest, note=note)
                logger.info("模組 %s 未載入：管理者已停用", name)
                continue
            mod = importlib.import_module(f"{package}.{name}")
            spec = getattr(mod, "MODULE", None)
            if not isinstance(spec, registry.ModuleSpec) or spec.key != name:
                raise ValueError("MODULE missing or key mismatch")
        except Exception as e:  # 單一模組壞掉不可以拖垮整台
            registry.mark_failed(name, str(e))
            registry.set_state(name, registry.STATE_FAILED, str(e), manifest)
            logger.error("模組 %s 未載入：%s", name, e)
            continue
        registry.register(registry.LoadedModule(key=name, manifest=manifest, spec=spec))
        registry.set_state(name, registry.STATE_LOADED, "", manifest, note=note)
        logger.info("模組 %s %s 已載入", name, manifest.get("version", "?"))
    return registry.loaded()


def start_schedulers() -> int:
    """啟動已載入模組的排程（main.py 在排程閘門開著時呼叫），回傳呼叫了幾個。

    只迭代 `registry.loaded()`：停用、未授權、載入失敗的模組沒有被 import，排程自然不跑（CORE-SPEC §9c③）。
    抽成函式是為了讓子行程守門**真的呼叫到 main 用的同一條路**——測試 session 的排程閘門恆關
    （MOTRIX_DISABLE_SCHEDULERS=1），只看閘門的話「停用後排程沒跑」在測試裡恆真（AUDIT-X-9c B-3）。"""
    n = 0
    for m in registry.loaded():
        for sched in m.spec.schedulers:
            sched()
            n += 1
    return n
