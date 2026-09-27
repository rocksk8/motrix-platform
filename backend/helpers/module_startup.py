# -*- coding: utf-8 -*-
"""啟動時載入 L2 模組：main.py 與「只做 init_db 的工具」（乾跑 migration、V9→新版轉換）共用同一段。

[單位] helper:module_startup    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] demo_absent_reason, fail_incomplete_modules, load_modules_like_startup
[不變式] 與 main.py 啟動時逐字相同：讀停用清單（P-SW-05）→ registry.set_disabled_list → loader.load_all(授權、停用、原因)。
         模組 migration（ModuleSpec.migrations，CORE 1.58）只在 load_all 登記過才會被 init_db 的 core.migrations.run_all 跑到
         ⇒ 只 `import db; db.init_db(p)` 而沒先呼叫這支 ＝ 模組 migration 靜默不跑。
         模組上下線由**主庫**決定（AB-S7）：只有 demo 庫未完成 ⇒ 不下線，只在 demo 模式對該模組的 API 明說缺席。
[契約題] tests/platform/test_module_startup.py
[注意] 停用清單讀 `db_path` 那個庫：乾跑／轉換**必須**帶被試跑的那個庫（不可以讀正式庫）；None ⇒ `db.DB_PATH`（main.py）。
       快取檔寫在該庫旁（`core.paths.modules_disabled_cache`）。授權讀本機金鑰檔（`helpers.licensing.LICENSE_PATH`），不看庫。
       `read_disabled_list` 經模組屬性呼叫、不 from-import：子行程守門在 import main 之前換掉它（tests/platform/child_module_gate.py）。
"""
import logging

from core import loader as _loader, registry as _registry
from helpers import licensing as _licensing
from helpers import module_switches as _module_switches

_log = logging.getLogger("motrix.module_startup")

#: 只有 demo 庫的 migration 沒完成的模組 ⇒ {模組: 對使用者說的話}（fail_incomplete_modules 寫、demo_absent_reason 讀）
_DEMO_ABSENT = {}


def load_modules_like_startup(db_path: str = None) -> list:
    """讀 `db_path` 的停用清單並載入模組（授權 ＞ 停用；讀不到停用清單也沒有快取 ⇒ 全部暫不載入）。回 `registry.loaded()`。"""
    disabled = _module_switches.read_disabled_list(db_path)
    _registry.set_disabled_list(disabled.source, disabled.message)
    return _loader.load_all(license_check=_licensing.module_license_check,
                            disabled=_loader.ALL if disabled.all_disabled else disabled.keys,
                            disabled_reason=_module_switches.UNREADABLE_REASON if disabled.all_disabled else None)


def _incomplete_of(path) -> dict:
    """`incomplete(path)`；path 沒給 ⇒ {}（呼叫端沒有那個庫）；**有給而查不到紀錄（None）⇒ None**，由呼叫端 fail-closed。"""
    from core import migrations as _migrations
    return _migrations.incomplete(path) if path else {}


def fail_incomplete_modules(main_db_path, demo_db_path=None) -> dict:
    """`init_db`（主庫、demo 庫）之後、`mount_modules` 之前呼叫（稽核 A AB-S3；AB-S7 使用者裁示：由**主庫**決定上下線）。

    - **主庫**的 `core.migrations.incomplete` 列到的已載入模組 ⇒ `registry.unload` 改記 failed（原因＝migration 回的那句），
      路由不掛、提供者不在，交給模組管理頁與缺席明說——不讓程式去讀還沒加上的欄位而 500。
    - **只有 demo 庫**未完成 ⇒ 不下線（正式使用者照常），記 ERROR；demo 模式的請求打到該模組的 API 前綴時，
      由 `demo_absent_reason` 回明說缺席的原因。
    - `incomplete` 回 None（對那個庫查不到 run_all 的紀錄：路徑對不上、或根本沒跑）⇒ **fail-closed**（稽核 D PO1）：
      主庫 ⇒ 所有已載入模組下線；demo 庫 ⇒ demo 模式所有模組明說缺席。與乾跑工具「None＝失敗」同一個方向——
      「不知道升級有沒有完成」不可以當成「完成」。不是已載入模組的名稱（例：`core`）⇒ 只記 ERROR。

    回 `{"offline": {模組: 原因}, "demo_absent": {模組: 原因}}`；每次呼叫重設 demo 缺席表。"""
    loaded = {m.key for m in _registry.loaded()}
    offline, demo = {}, {}
    main_inc = _incomplete_of(main_db_path)
    if main_inc is None:
        for key in sorted(loaded):
            offline[key] = "無法確認資料庫升級是否完成（主庫 %s 查不到升級紀錄），模組暫不載入" % main_db_path
    else:
        for key, (v, why) in sorted(main_inc.items()):
            offline[key] = "資料庫升級未完成（%s v%d），模組暫不載入：%s" % (key, v, why)
    demo_inc = _incomplete_of(demo_db_path)
    if demo_inc is None:
        demo_inc = {k: (0, "示範庫 %s 查不到升級紀錄" % demo_db_path) for k in loaded}
    for key, (v, why) in sorted(demo_inc.items()):
        if key not in offline:
            demo[key] = "示範資料的資料庫升級未完成（%s v%d），示範模式暫不提供這個模組：%s" % (key, v, why)
    for key, reason in offline.items():
        if key in loaded:
            _registry.unload(key, reason)
        _log.error("%s", reason)
    for reason in demo.values():
        _log.error("%s", reason)
    _DEMO_ABSENT.clear()
    _DEMO_ABSENT.update({k: r for k, r in demo.items() if k in loaded})
    return {"offline": offline, "demo_absent": demo}


def demo_absent_reason(path: str):
    """demo 模式的請求路徑 ⇒ 該模組缺席的原因（字串），不是 demo 缺席模組的前綴 ⇒ None。
    前綴取已載入模組 module.json 的 `provides.api_prefixes`（完全相同或其下的路徑）。只在 demo 模式呼叫（main.py auth middleware）。"""
    if not _DEMO_ABSENT:
        return None
    for m in _registry.loaded():
        why = _DEMO_ABSENT.get(m.key)
        if not why:
            continue
        for p in ((m.manifest or {}).get("provides") or {}).get("api_prefixes") or []:
            if path == p or path.startswith(p.rstrip("/") + "/"):
                return why
    return None
