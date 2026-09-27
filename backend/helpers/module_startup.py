# -*- coding: utf-8 -*-
"""啟動時載入 L2 模組：main.py 與「只做 init_db 的工具」（乾跑 migration、V9→新版轉換）共用同一段。

[單位] helper:module_startup    [層] L1    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] fail_incomplete_modules, load_modules_like_startup
[不變式] 與 main.py 啟動時逐字相同：讀停用清單（P-SW-05）→ registry.set_disabled_list → loader.load_all(授權、停用、原因)。
         模組 migration（ModuleSpec.migrations，CORE 1.58）只在 load_all 登記過才會被 init_db 的 core.migrations.run_all 跑到
         ⇒ 只 `import db; db.init_db(p)` 而沒先呼叫這支 ＝ 模組 migration 靜默不跑。
[契約題] tests/platform/test_module_startup.py
[注意] 停用清單讀 `db_path` 那個庫：乾跑／轉換**必須**帶被試跑的那個庫（不可以讀正式庫）；None ⇒ `db.DB_PATH`（main.py）。
       快取檔寫在該庫旁（`core.paths.modules_disabled_cache`）。授權讀本機金鑰檔（`helpers.licensing.LICENSE_PATH`），不看庫。
       `read_disabled_list` 經模組屬性呼叫、不 from-import：子行程守門在 import main 之前換掉它（tests/platform/child_module_gate.py）。
"""
from core import loader as _loader, registry as _registry
from helpers import licensing as _licensing
from helpers import module_switches as _module_switches


def load_modules_like_startup(db_path: str = None) -> list:
    """讀 `db_path` 的停用清單並載入模組（授權 ＞ 停用；讀不到停用清單也沒有快取 ⇒ 全部暫不載入）。回 `registry.loaded()`。"""
    disabled = _module_switches.read_disabled_list(db_path)
    _registry.set_disabled_list(disabled.source, disabled.message)
    return _loader.load_all(license_check=_licensing.module_license_check,
                            disabled=_loader.ALL if disabled.all_disabled else disabled.keys,
                            disabled_reason=_module_switches.UNREADABLE_REASON if disabled.all_disabled else None)


def fail_incomplete_modules(db_paths) -> dict:
    """`init_db` 之後、`mount_modules` 之前呼叫（稽核 A AB-S3）：任一個庫的 `core.migrations.incomplete` 列了某個模組
    ⇒ 該模組改記 failed（`registry.unload`：移出已載入清單，路由不掛、提供者不在；原因＝migration 回的那句），
    交給模組管理頁與「缺席明說」接手——不讓程式去讀還沒加上的欄位而 500。

    回 `{模組: 原因}`。`incomplete` 回 None（沒對那個庫跑過 run_all）⇒ 那個庫不算（不猜）；
    不是已載入模組的名稱（例：`core`）⇒ 只記 ERROR，不動登錄表。"""
    import logging
    from core import migrations as _migrations
    log = logging.getLogger("motrix.module_startup")
    loaded = {m.key for m in _registry.loaded()}
    out = {}
    for p in db_paths:
        for key, (v, why) in sorted((_migrations.incomplete(p) or {}).items()):
            out.setdefault(key, "資料庫升級未完成（%s v%d），模組暫不載入：%s" % (key, v, why))
    for key, reason in out.items():
        if key in loaded:
            _registry.unload(key, reason)
        log.error("%s", reason)
    return out
