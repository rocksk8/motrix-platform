# -*- coding: utf-8 -*-
"""V9 → 新版 升級轉換與回滾（CORE-SPEC §9b）。操作步驟見 docs/platform/UPGRADE-RUNBOOK.md。

用法（每一步都要明確給安裝根目錄；本工具不猜路徑、不連任何遠端）：
  python tools/platform/upgrade.py preflight --root <安裝根目錄> [--v9-port 666]
  python tools/platform/upgrade.py backup    --root <安裝根目錄> --backup-dir <新的空目錄>
  python tools/platform/upgrade.py convert   --root <安裝根目錄> --backup-dir <同上> --new-source <新版程式目錄>
  python tools/platform/upgrade.py verify    --root <安裝根目錄> --backup-dir <同上> [--port 6671]
  python tools/platform/upgrade.py rollback  --root <安裝根目錄> --backup-dir <同上> --mode code|full [--yes]

- backup 完成後自動試還原並比對雜湊；不過 ⇒ exit 2，不可以往下做 convert。
- convert 會先檢查 backup 驗證過（manifest 存在且試還原通過）。
- verify 不過 ⇒ exit 3；是否回滾由人決定（runbook 建議先「只回程式」）。
- rollback --mode full 會列出轉換後新增的列數，沒有 --yes 就不執行。
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "backend"))
from core import upgrade as U  # noqa: E402

#: 啟動驗證用的環境：不跑排程、不上雲、不寄信（V9 另以安裝路徑擋信）
SAFE_ENV = {
    "MOTRIX_DISABLE_SCHEDULERS": "1",
    "MOTRIX_CLOUD_ARCHIVE": "off",
    "MOTRIX_EMAIL_SEND": "off",
    "PYTHONIOENCODING": "utf-8",
}


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def start_and_ping(root: str, port: int, timeout: float = 120.0, log_path: str = None) -> dict:
    """在 `port` 啟動 `<root>/backend` 的 uvicorn，等 /api/ping 200，然後停掉。回 {ok, status, seconds, log}。"""
    if port_open(port):
        return {"ok": False, "status": None, "seconds": 0, "log": "port %d 已被佔用" % port}
    env = {**os.environ, **SAFE_ENV}
    env.pop("MOTRIX_CREATE_NEW_DB", None)
    log_path = log_path or os.path.join(root, "backend", "logs", "upgrade_verify_%d.log" % port)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    t0 = time.monotonic()
    with open(log_path, "w", encoding="utf-8") as logf:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=os.path.join(root, "backend"), env=env, stdout=logf, stderr=subprocess.STDOUT)
        status = None
        try:
            while time.monotonic() - t0 < timeout:
                if proc.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=2) as r:
                        status = r.status
                        break
                except Exception:                            # noqa: BLE001
                    time.sleep(1)
        finally:
            _stop(proc)
    with open(log_path, encoding="utf-8", errors="replace") as f:
        tail = f.read()[-3000:]
    return {"ok": status == 200, "status": status, "seconds": round(time.monotonic() - t0, 1), "log": tail}


def _stop(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_migrations(root: str) -> subprocess.CompletedProcess:
    """用**新版**的 db.init_db 補跑基準＋模組表（子行程；不 import main，避免啟動副作用）。"""
    env = {**os.environ, **SAFE_ENV}
    code = "import db; db.init_db(); db.init_db(db.DEMO_DB_PATH); print('MIGRATE_OK')"
    return subprocess.run([sys.executable, "-c", code], cwd=os.path.join(root, "backend"),
                          env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")


def _write_log(backup_dir: str, name: str, data) -> None:
    with open(os.path.join(backup_dir, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def cmd_preflight(a):
    r = U.preflight(a.root, v9_port_open=port_open(a.v9_port))
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r["ok"] else 1


def cmd_backup(a):
    U.backup(a.root, a.backup_dir)
    problems = U.verify_backup_restorable(a.backup_dir)
    _write_log(a.backup_dir, "backup_verify.json", {"problems": problems})
    if problems:
        print("備份試還原不通過，中止：\n  " + "\n  ".join(problems))
        return 2
    print("備份完成並已試還原比對雜湊：%s" % a.backup_dir)
    return 0


def convert(root: str, backup_dir: str, new_source: str) -> dict:
    verify_path = os.path.join(backup_dir, "backup_verify.json")
    if not os.path.isfile(os.path.join(backup_dir, U.MANIFEST_NAME)) or not os.path.isfile(verify_path):
        raise RuntimeError("沒有已驗證的備份（先跑 backup）")
    with open(verify_path, encoding="utf-8") as f:
        if json.load(f).get("problems"):
            raise RuntimeError("備份試還原沒有通過，不可以轉換")
    rep = {"replace_program": U.replace_program(root, new_source)}
    mig = run_migrations(root)
    rep["migrate"] = {"returncode": mig.returncode, "ok": "MIGRATE_OK" in mig.stdout,
                      "stderr_tail": mig.stderr[-2000:]}
    if not rep["migrate"]["ok"]:
        _write_log(backup_dir, "conversion_log.json", rep)
        raise RuntimeError("migration 失敗：%s" % mig.stderr[-800:])
    rep["settings_added"] = U.add_missing_settings(os.path.join(root, U.DB_FILES[0]))
    rep["company_profile"] = U.fill_company_profile_blanks(os.path.join(root, U.DB_FILES[0]))
    _write_log(backup_dir, "conversion_log.json", rep)
    return rep


def cmd_convert(a):
    rep = convert(a.root, a.backup_dir, a.new_source)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


def verify(root: str, backup_dir: str, port: int, warnings: list = None) -> list:
    m = U.load_manifest(backup_dir)
    warnings = [] if warnings is None else warnings
    problems = U.verify_conversion(root, m, warnings)          # 先比資料（伺服器啟動前）
    if not problems:
        r = start_and_ping(root, port)
        if not r["ok"]:
            problems.append("新版啟動或 /api/ping 失敗（status=%s）：%s" % (r["status"], r["log"][-600:]))
        # 啟動本身可以**新增**執行期狀態（例：archive_instance_id），但不可以改寫既有設定
        after = U.settings_rows(os.path.join(root, U.DB_FILES[0]))
        changed = [k for k, v in m["pre"]["settings"].items() if after.get(k) != v]
        if changed:
            problems.append("新版啟動後改寫了既有設定：%s" % changed)
    _write_log(backup_dir, "verify_log.json", {"problems": problems, "warnings": warnings})
    return problems


def cmd_verify(a):
    w = []
    p = verify(a.root, a.backup_dir, a.port, w)
    for x in w:
        print("警告（不擋升級）：" + x)
    print("驗證通過" if not p else "驗證不通過：\n  " + "\n  ".join(p))
    return 0 if not p else 3


def cmd_rollback(a):
    m = U.load_manifest(a.backup_dir)
    if a.mode == "full":
        added = U.rows_added_since(m, os.path.join(a.root, U.DB_FILES[0]))
        if added and not a.yes:
            print("轉換後已新增的列（完整回滾會失去它們）：%s\n確認後加 --yes 再執行；建議先用 --mode code。"
                  % json.dumps(added, ensure_ascii=False))
            return 4
    problems = U.rollback(a.root, a.backup_dir, a.mode)
    _write_log(a.backup_dir, "rollback_%s.json" % a.mode, {"problems": problems})
    print("回滾（%s）完成，雜湊逐一相等" % a.mode if not problems else "回滾後比對不通過：\n  " + "\n  ".join(problems))
    return 0 if not problems else 5


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("preflight", "backup", "convert", "verify", "rollback"):
        p = sub.add_parser(name)
        p.add_argument("--root", required=True)
        if name != "preflight":
            p.add_argument("--backup-dir", required=True)
    sub.choices["preflight"].add_argument("--v9-port", type=int, default=666)
    sub.choices["convert"].add_argument("--new-source", required=True)
    sub.choices["verify"].add_argument("--port", type=int, default=6671)
    sub.choices["rollback"].add_argument("--mode", choices=("code", "full"), required=True)
    sub.choices["rollback"].add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    return {"preflight": cmd_preflight, "backup": cmd_backup, "convert": cmd_convert,
            "verify": cmd_verify, "rollback": cmd_rollback}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
