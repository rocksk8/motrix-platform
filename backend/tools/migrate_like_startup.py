# -*- coding: utf-8 -*-
"""照服務啟動時的規則跑 migration：先載入模組、再 init_db、再確認模組 migration 都做完。

[單位] tool:migrate_like_startup    [層] 部署工具
[公開介面] run, main
[不變式] 載入模組與 main.py 走同一支（helpers.module_startup.load_modules_like_startup）；停用清單讀第一個 --db；
    模組 migration 未完成（core.migrations.incomplete 非空）或沒有結果（None）⇒ 失敗；
    模組載入失敗、停用清單讀不到 ⇒ 失敗（這次驗不到那些模組的 migration，不可以當通過）
[契約題] tests/platform/test_apply_plan_2026_09_28.py
[注意] 跑的是**這支檔案所在的那份程式**（backend/tools 的上一層）：乾跑用新包裡的，轉換用安裝目錄裡的。

為什麼需要它（2026-09-28）：模組 migration（ModuleSpec.migrations，CORE 1.58）只在載入器登記過才會被
init_db 跑到；乾跑與轉換原本只 `import db; db.init_db(p)` ⇒ 模組 migration 靜默不跑、乾跑照樣通過。
舊包（沒有 helpers/module_startup.py）沒有模組 migration ⇒ 只跑 init_db，與原本相同。

用法：python <backend>/tools/migrate_like_startup.py --db <主庫> [--db <demo 庫>] [--license <金鑰檔>]
  --license：授權檢查讀哪一份金鑰（乾跑在包目錄裡跑，要指到正式機那一份才與正式機啟動一致；只讀）
  exit 0 印 MIGRATE_LIKE_STARTUP_OK；失敗 exit 2 並印 MIGRATE_LIKE_STARTUP_FAIL 與原因
"""
import argparse
import os
import sys

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def has_module_startup(backend=BACKEND):
    return os.path.isfile(os.path.join(backend, "helpers", "module_startup.py"))


def run(dbs, license_path=None):
    """回問題清單（空＝通過）。"""
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    import db
    problems = []
    modular = has_module_startup()
    if modular:
        from helpers import licensing, module_startup, module_switches
        from core import registry
        if license_path:
            licensing.LICENSE_PATH = license_path
        module_startup.load_modules_like_startup(db_path=dbs[0])
        for s in registry.module_states():
            if s["state"] == registry.STATE_FAILED:
                problems.append("模組 %s 載入失敗：%s" % (s["key"], s["reason"]))
            elif s["state"] == registry.STATE_DISABLED and s["reason"] == module_switches.UNREADABLE_REASON:
                problems.append("模組 %s：%s（驗不到它的 migration）" % (s["key"], s["reason"]))
    for p in dbs:
        db.init_db(p)
    if modular:
        from core import migrations
        for p in dbs:
            inc = migrations.incomplete(p)
            if inc is None:
                problems.append("%s：沒有模組 migration 的結果（run_all 沒有對這個庫執行）" % p)
            else:
                for mod, (ver, reason) in sorted(inc.items()):
                    problems.append("%s：模組 %s 的 migration 停在 v%s：%s" % (p, mod, ver, reason))
    return problems


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", action="append", required=True)
    ap.add_argument("--license")
    a = ap.parse_args(argv)
    problems = run(a.db, a.license)
    print("modules=%s" % ("like_startup" if has_module_startup() else "none（舊包：只跑 init_db）"))
    if problems:
        for p in problems:
            print("  " + p)
        print("MIGRATE_LIKE_STARTUP_FAIL %d" % len(problems))
        return 2
    print("MIGRATE_LIKE_STARTUP_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
