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


class _AllModules:
    """`load_all(disabled=ALL)`：每一個模組都當成停用（STATES-PLATFORM P-SW-05：停用清單讀不到、
    也沒有上次的紀錄 ⇒ 寧可少開，不可多開）。"""

    def __contains__(self, key):
        return True

    def __repr__(self):
        return "ALL"


ALL = _AllModules()

#: 管理者停用時狀態表的原因（`disabled_reason` 沒給時用這個）。
DISABLED_REASON = "管理者已停用（資料保留）"


def _read_manifest(folder):
    with open(os.path.join(folder, "module.json"), encoding="utf-8") as f:
        return json.load(f)


def load_all(modules_dir: str = None, package: str = None,
             license_check=None, disabled=frozenset(), disabled_reason=None):
    """回傳成功載入的 LoadedModule 清單（依資料夾名排序，結果可重現）。

    CORE-SPEC §9c 的優先順序：① 不在包內（沒有資料夾 ⇒ 根本不會出現）> ② 未授權 > ③ 管理者停用。
    ②③ 都**不 import** 該模組（路由不掛、排程不跑、提供者不登記），資料不動。

    `license_check(manifest) -> (ok, reason)`：由呼叫端（main.py）注入——L0 不依賴 L1 的授權實作。
    沒給 ⇒ 不檢查。`disabled`：管理者停用的模組 key 集合（啟動時讀一次；改了要重啟才生效），
    或 `ALL`（全部停用）；`disabled_reason`：寫進狀態表的原因（沒給 ⇒ `DISABLED_REASON`）。
    ok 時的 reason（例：「授權檢查未啟用」）不是錯誤，寫進狀態的 `note`，不寫進 `reason`
    （`reason` 非空＝有問題，模組管理頁與儀表板都這樣判斷）。
    `modules_dir`／`package` 沒給 ⇒ 讀呼叫當下的 MODULES_DIR／MODULES_PACKAGE。

    ⚠ 這裡只 import、不掛路由：路由要等所有 L1 router 都掛上之後由 `mount_modules(app)` 掛，
    才比得出衝突（P-LD-07）。
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
                why = disabled_reason or DISABLED_REASON
                registry.set_state(name, registry.STATE_DISABLED, why, manifest, note=note)
                logger.info("模組 %s 未載入：%s", name, why)
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


_PARAM = re.compile(r"\{[^}]*\}")


def _module_route_keys(router):
    """模組 router 的 (方法, 路徑) 清單。讀不出路徑（例：模組 router 裡再 include 別的 router——新版 FastAPI
    會把它包成沒有 path 的物件）⇒ None：**算不出來就不掛**，不猜。沒有方法清單的（WebSocket 等）記 `*`。"""
    keys = set()
    for r in router.routes:
        path = getattr(r, "path", None)
        if not isinstance(path, str):
            return None
        for m in (getattr(r, "methods", None) or {"*"}):
            keys.add((m, path))
    return keys


def _probe_scope(method, path):
    """把模組路由的路徑做成一個具體請求（路徑參數代入 "0"），給既有路由的 `matches()` 判斷。"""
    return {"type": "http", "method": "GET" if method == "*" else method, "path": _PARAM.sub("0", path),
            "root_path": "", "query_string": b"", "headers": [], "path_params": {}}


def _match_owner(routes, owners, method, path):
    """既有路由裡第一個會**完整接住**這個請求的（先掛者勝）⇒ 它的擁有者；沒有 ⇒ None。

    ⚠ 不讀路由物件的內部結構：FastAPI 0.141 起 `include_router` 把整支 router 包成一個沒有 `path` 的
    物件（0.133 是一條條 APIRoute）——讀 `route.path` 的比對在新版上**看不到任何 L1 路由**，衝突會默默
    放行（2026-09-25 在 3.12／FastAPI 0.141 抓到）。改用 starlette 公開的 `route.matches(scope)`，
    新舊版都是路由器本身用來選路由的同一個判斷。"""
    from starlette.routing import Match
    scope = _probe_scope(method, path)
    for idx, r in enumerate(routes):
        try:
            got, _ = r.matches(dict(scope))
        except Exception:                                  # noqa: BLE001 — 判斷不了的那一條不算接住
            continue
        if got == Match.FULL:
            return owners[idx] if idx < len(owners) else "L1"
    return None


def mount_modules(app) -> dict:
    """把已載入模組的路由掛到 `app` 上，回傳 `{key: 原因}`（因路由衝突而不掛的模組）。

    STATES-PLATFORM P-LD-07：兩條會接住同一個請求的路由都掛上時，**先掛的默默勝出**、沒有任何錯誤。
    ⇒ 呼叫端必須在**所有 L1 router 都掛好之後**、StaticFiles 之前才呼叫（模組不可以蓋掉 L1）；模組之間
    依載入順序（資料夾名排序）先到先得。模組的某條路由會被既有路由接走（同方法、路徑相同或被參數路徑
    涵蓋）⇒ 該模組**整個不掛**（不掛一半），經 `registry.unload` 改記 failed，原因寫明路徑與對方。
    路由讀不出路徑 ⇒ 同樣不掛。排程與啟動提示也要在這之後才從 `registry.loaded()` 取。
    """
    owners = ["L1"] * len(app.router.routes)
    refused = {}
    for m in registry.loaded():
        mine, unreadable = set(), False
        for router in m.spec.routers:
            keys = _module_route_keys(router)
            if keys is None:
                unreadable = True
                break
            mine |= keys
        if unreadable:
            clashes, reason = None, "路由無法判讀（router 內含巢狀 include_router），不掛載"
        else:
            clashes = sorted({(k, o) for k in mine
                              for o in [_match_owner(app.router.routes, owners, *k)] if o})
            reason = None
            if clashes:
                detail = "；".join("%s %s 已由 %s 提供" % (k[0], k[1], o) for k, o in clashes[:5])
                if len(clashes) > 5:
                    detail += "；另 %d 條" % (len(clashes) - 5)
                reason = "路由衝突：" + detail
        if reason:
            registry.unload(m.key, reason)
            refused[m.key] = reason
            logger.error("模組 %s 未載入：%s", m.key, reason)
            continue
        for router in m.spec.routers:
            app.include_router(router)
        owners += ["模組 %s" % m.key] * (len(app.router.routes) - len(owners))
    return refused
