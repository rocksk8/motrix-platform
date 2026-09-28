# -*- coding: utf-8 -*-
"""apply_module_update.ps1 的 Python 步驟（B55 單一模組更新包 §1.3；ps1 只管流程，判斷放在這裡才測得到）。

[單位] tool:module_apply_steps    [層] 部署工具
[公開介面] build_overlay, check_states, disable_module, main
[不變式] 疊加樹只複製安裝目錄 backend\\ 底下 core.upgrade.classify(rel)=="program" 的檔（白名單，D 審 DB-M1），
    另排除 .apply.lock；不複製任何 db／data／config；模組資料夾換成包裡那一份。
    載入狀態檔（logs/module_states.json，B 的 loader._write_module_states）必須是「重啟之後、正在聽 port 的那個行程」寫的，
    且該模組狀態／版本相符；任一條不成立 ⇒ 失敗並說原因（讀不到檔也是失敗，不是通過）。
[契約題] tests/platform/test_module_apply_steps_2026_09_28.py
[注意] 跑的是**安裝目錄**這一份（ps1 以 <ROOT>\\backend\\tools\\module_apply_steps.py 呼叫）：classify 用已安裝的 core.upgrade。

子命令（每個成功印一行 `<NAME>_OK …`，失敗印 `<NAME>_FAIL <原因>` 並 exit 2）：
  overlay  --install <ROOT> --pkg <PKG> --key <K> --dest <DIR>        → OVERLAY_OK <檔數>
  states   --file <module_states.json> --key <K> --since <ISO 時間> --pids <p1,p2,…>
           [--version <V>] [--state loaded|disabled]                  → STATES_OK
  disable  --key <K>                                                   → DISABLE_OK（寫安裝目錄主庫的停用清單）
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: 會被 classify 判成 program、但不可以進疊加樹的檔（載入器會誤判「套用中」）
OVERLAY_EXCLUDE = {"backend/.apply.lock"}


def _classify():
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    from core.upgrade import classify
    return classify


def build_overlay(install_root, pkg, key, dest):
    """回複製的檔數。dest 已存在 ⇒ 拒絕（不覆蓋別人的目錄）。"""
    classify = _classify()
    install_root, pkg, dest = os.path.abspath(install_root), os.path.abspath(pkg), os.path.abspath(dest)
    if os.path.exists(dest):
        raise ValueError("疊加樹目錄已存在：%s" % dest)
    src_backend = os.path.join(install_root, "backend")
    pkg_mod = os.path.join(pkg, "backend", "modules", key)
    if not os.path.isdir(pkg_mod):
        raise ValueError("包裡沒有 backend/modules/%s" % key)
    n = 0
    mod_prefix = "backend/modules/%s/" % key
    for dirpath, dirnames, filenames in os.walk(src_backend):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, install_root).replace("\\", "/")
            if rel in OVERLAY_EXCLUDE or rel.startswith(mod_prefix):
                continue
            if classify(rel) != "program":
                continue
            out = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(full, out)
            n += 1
    shutil.copytree(pkg_mod, os.path.join(dest, "backend", "modules", key),
                    ignore=shutil.ignore_patterns("__pycache__"))
    for _d, subdirs, files in os.walk(os.path.join(dest, "backend", "modules", key)):
        subdirs[:] = [x for x in subdirs if x != "__pycache__"]
        n += len(files)
    return n


def check_states(path, key, since, pids, version=None, state="loaded"):
    """回 (ok, 原因)。since：重啟那一刻（datetime）；pids：正在聽 port 的行程。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return False, "還沒有載入狀態檔（%s）——服務可能還沒啟動完成，或這一版的 L1 不寫它" % path
    except (OSError, ValueError) as e:
        return False, "載入狀態檔讀不到或不是 JSON：%s" % e
    try:
        started = datetime.fromisoformat(str(data.get("started_at")))
    except (TypeError, ValueError):
        return False, "載入狀態檔沒有可讀的 started_at：%r" % data.get("started_at")
    if started < since:
        return False, "載入狀態檔是重啟之前寫的（started_at %s < 重啟 %s）——還是舊行程的結果" % (
            started.isoformat(timespec="seconds"), since.isoformat(timespec="seconds"))
    if pids and int(data.get("pid") or 0) not in set(pids):
        return False, "載入狀態檔的 pid %s 不是正在聽 port 的行程 %s" % (data.get("pid"), sorted(set(pids)))
    if not pids:
        return False, "沒有任何行程在聽 port ⇒ 服務沒起來"
    mods = {m.get("key"): m for m in data.get("modules") or []}
    m = mods.get(key)
    if m is None:
        return False, "載入狀態檔裡沒有模組 %s" % key
    if m.get("state") != state:
        extra = "（排程閘門關閉）" if data.get("schedulers_disabled") else ""
        return False, "模組 %s 的狀態是 %s，預期 %s：%s%s" % (key, m.get("state"), state, m.get("reason") or "", extra)
    if version is not None and str(m.get("version") or "") != version:
        return False, "模組 %s 載入的版本是 %s，預期 %s" % (key, m.get("version") or "（空）", version)
    return True, ""


def disable_module(key):
    """寫安裝目錄主庫的停用清單（與模組管理頁同一機制）。回新的停用清單。"""
    if BACKEND not in sys.path:
        sys.path.insert(0, BACKEND)
    from helpers import module_switches
    return module_switches.set_enabled(key, False)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("overlay")
    o.add_argument("--install", required=True)
    o.add_argument("--pkg", required=True)
    o.add_argument("--key", required=True)
    o.add_argument("--dest", required=True)
    s = sub.add_parser("states")
    s.add_argument("--file", required=True)
    s.add_argument("--key", required=True)
    s.add_argument("--since", required=True, help="重啟那一刻（ISO，本機時間）")
    s.add_argument("--pids", default="", help="正在聽 port 的行程，逗號分隔")
    s.add_argument("--version")
    s.add_argument("--state", default="loaded", choices=("loaded", "disabled"))
    d = sub.add_parser("disable")
    d.add_argument("--key", required=True)
    a = ap.parse_args(argv)
    name = a.cmd.upper()
    try:
        if a.cmd == "overlay":
            n = build_overlay(a.install, a.pkg, a.key, a.dest)
            print("OVERLAY_OK %d" % n)
        elif a.cmd == "states":
            pids = [int(x) for x in a.pids.split(",") if x.strip()]
            ok, why = check_states(a.file, a.key, datetime.fromisoformat(a.since), pids, a.version, a.state)
            if not ok:
                print("STATES_FAIL %s" % why)
                return 2
            print("STATES_OK")
        else:
            lst = disable_module(a.key)
            print("DISABLE_OK %s" % ",".join(sorted(lst)))
    except Exception as e:  # noqa: BLE001 — ps1 要一行原因，不要 traceback 淹沒
        print("%s_FAIL %s: %s" % (name, e.__class__.__name__, e))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
