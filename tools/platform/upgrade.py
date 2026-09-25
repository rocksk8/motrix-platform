# -*- coding: utf-8 -*-
"""V9 → 新版 升級轉換與回滾（CORE-SPEC §9b）。操作步驟見 docs/platform/UPGRADE-RUNBOOK.md。

用法（每一步都要明確給安裝根目錄；本工具不猜路徑、不連任何遠端）：
  python tools/platform/upgrade.py preflight --root <安裝根目錄> [--v9-port 666]
  python tools/platform/upgrade.py backup    --root <安裝根目錄> --backup-dir <新的空目錄>
  python tools/platform/upgrade.py convert   --root <安裝根目錄> --backup-dir <同上> --new-source <新版程式目錄>
  python tools/platform/upgrade.py verify    --root <安裝根目錄> --backup-dir <同上> [--port 6671]
  python tools/platform/upgrade.py rollback  --root <安裝根目錄> --backup-dir <同上> --mode code|full [--yes]
                                             [--ping-port 6671 | --no-ping]

- backup 完成後自動試還原並比對雜湊；不過 ⇒ exit 2，不可以往下做 convert。印出 manifest 的 SHA256：抄到備份目錄以外。
- convert 動手前重驗備份（manifest 是這個安裝的、逐檔雜湊、試還原）；不過就拒絕。
- verify 不過 ⇒ exit 3，並印出建議的回滾指令；**是否回滾由人決定**（CORE-SPEC §9b 主持裁示 2026-09-25：
  回滾不是原子動作，儀表板與 RUNBOOK 都設計成由人逐步確認）。
- rollback 動手前重驗備份；不過 ⇒ exit 7，一個檔都沒動。--mode full 會列出轉換後寫入、回滾會失去的資料，
  沒有 --yes 就不執行（exit 4）。回滾比對通過後自動在非正式 port 啟動 V9 並 ping，**只印結果**：
  比對不過 ⇒ exit 5；比對通過但 V9 ping 不過 ⇒ exit 6。
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
    print("manifest SHA256：%s（抄到備份目錄以外；回滾前對照）" % U.manifest_sha256(a.backup_dir))
    return 0


def convert(root: str, backup_dir: str, new_source: str) -> dict:
    verify_path = os.path.join(backup_dir, "backup_verify.json")
    if not os.path.isfile(os.path.join(backup_dir, U.MANIFEST_NAME)) or not os.path.isfile(verify_path):
        raise RuntimeError("沒有已驗證的備份（先跑 backup）")
    with open(verify_path, encoding="utf-8") as f:
        if json.load(f).get("problems"):
            raise RuntimeError("備份試還原沒有通過，不可以轉換")
    # 稽核 X-9b S-1：backup_verify.json 是過去的結果；動手前重驗（備份之後才被改、拿錯安裝的備份）
    pre = U.check_backup(root, backup_dir)
    if pre:
        raise RuntimeError("轉換前重驗備份不通過，沒有動任何檔案：" + "；".join(pre))
    rep = {"replace_program": U.replace_program(root, new_source)}
    rep["package_default_config"] = U.sync_package_default_config(root, new_source)
    mig = run_migrations(root)
    rep["migrate"] = {"returncode": mig.returncode, "ok": "MIGRATE_OK" in mig.stdout,
                      "stderr_tail": mig.stderr[-2000:]}
    if not rep["migrate"]["ok"]:
        _write_log(backup_dir, "conversion_log.json", rep)
        raise RuntimeError("migration 失敗：%s" % mig.stderr[-800:])
    rep["settings_added"] = U.add_missing_settings(os.path.join(root, U.DB_FILES[0]))
    rep["company_profile"] = U.fill_company_profile_blanks(os.path.join(root, U.DB_FILES[0]))
    U.record_post_conversion(root, backup_dir)
    _write_log(backup_dir, "conversion_log.json", rep)
    return rep


def cmd_convert(a):
    rep = convert(a.root, a.backup_dir, a.new_source)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    differs = rep["package_default_config"]["kept_differs_from_package"]
    if differs:
        print("⚠ 以下設定檔保留了這台機器的版本，與新版包不同——請人工比對新版有沒有要加的內容：%s" % differs)
    gone = rep["replace_program"]["removed_without_replacement"]
    if gone:
        print("ℹ 以下檔案新版沒有，已從安裝目錄移除（備份裡還有）：%d 個，清單在 conversion_log.json" % len(gone))
    return 0


def verify(root: str, backup_dir: str, port: int, warnings: list = None) -> list:
    m = U.load_manifest(backup_dir)
    warnings = [] if warnings is None else warnings
    problems = U.verify_conversion(root, m, warnings)          # 先比資料（伺服器啟動前）
    if not problems:
        r = start_and_ping(root, port)
        if not r["ok"]:
            problems.append("新版啟動或 /api/ping 失敗（status=%s）：%s" % (r["status"], r["log"][-600:]))
        # 啟動本身可以**新增**執行期狀態（例：archive_instance_id），但不可以改寫既有設定。
        # 判準與 verify_conversion 共用 U.settings_changes（稽核 X-9b M-1：補空值不是改寫）
        after = U.settings_rows(os.path.join(root, U.DB_FILES[0]))
        changed = U.settings_changes(m["pre"]["settings"], after)
        if changed:
            problems.append("新版啟動後改寫了既有設定：%s" % changed)
    _write_log(backup_dir, "verify_log.json", {"problems": problems, "warnings": warnings})
    return problems


def rollback_commands(root: str, backup_dir: str) -> list:
    """驗證不過時印給人的回滾指令（先只回程式）。"""
    tool = os.path.abspath(__file__)
    return ['python "%s" rollback --root "%s" --backup-dir "%s" --mode code' % (tool, root, backup_dir),
            'python "%s" rollback --root "%s" --backup-dir "%s" --mode full'
            '   （會失去轉換後寫入的資料；先不加 --yes 看清單，確認後再加）' % (tool, root, backup_dir)]


def cmd_verify(a):
    w = []
    p = verify(a.root, a.backup_dir, a.port, w)
    for x in w:
        print("警告（不擋升級）：" + x)
    if not p:
        print("驗證通過")
        return 0
    print("驗證不通過：\n  " + "\n  ".join(p))
    # CORE-SPEC §9b 主持裁示（2026-09-25）：不自動回滾；明確建議並附指令，由人決定
    print("\n建議執行回滾（UPGRADE-RUNBOOK §6；先只回程式）：\n  "
          + "\n  ".join(rollback_commands(a.root, a.backup_dir)))
    return 3


def _print_changes(rep: dict) -> None:
    base = "轉換完成當下" if rep["baseline"] == "post_convert" else "備份當下（轉換沒做完；含轉換本身的寫入）"
    print("完整回滾會失去的資料（基準：%s）：" % base)
    print("  新增的列：%s" % json.dumps(rep["rows_added"], ensure_ascii=False))
    print("  被刪的列（回滾會回來）：%s" % json.dumps(rep["rows_removed"], ensure_ascii=False))
    print("  被改寫的表：%s" % rep["rewritten"])
    print("  新表裡的列：%s" % json.dumps(rep["new_tables"], ensure_ascii=False))


def rollback_and_ping(root: str, backup_dir: str, mode: str, ping_port: int = None) -> tuple:
    """回滾；比對通過且 `ping_port` 不是 None ⇒ 在該 port 啟動 V9 並 ping（只記結果，不做決定）。

    回 (exit_code, log)。exit：0 通過／5 比對不過／6 比對通過但 V9 ping 不過／7 回滾前檢查不過（沒動任何檔）。
    """
    info = {}
    problems = U.rollback(root, backup_dir, mode, info)
    log = {"problems": problems, "info": info, "v9_ping": None}
    if info.get("precheck_failed"):
        code = 7
    elif problems:
        code = 5
    else:
        code = 0
        if ping_port is None:
            log["v9_ping"] = "略過（--no-ping）"
        else:
            r = start_and_ping(root, ping_port)
            log["v9_ping"] = {k: v for k, v in r.items() if k != "log"}
            log["v9_ping_log_tail"] = r["log"][-800:]
            if not r["ok"]:
                code = 6
    _write_log(backup_dir, "rollback_%s.json" % mode, log)
    return code, log


def cmd_rollback(a):
    if a.mode == "full":
        changes = U.changes_since_conversion(a.backup_dir, os.path.join(a.root, U.DB_FILES[0]))
        _print_changes(changes)
        if not a.yes:
            print("確認後加 --yes 再執行；建議先用 --mode code。")
            return 4
    code, log = rollback_and_ping(a.root, a.backup_dir, a.mode, None if a.no_ping else a.ping_port)
    info = log["info"]
    if code == 7:
        print("\n  ".join(["回滾沒有執行："] + log["problems"]))
        return code
    if info.get("data_added"):
        print("ℹ 轉換後新增的資料檔（保留在原位，不算問題）：%d 個 %s" % (len(info["data_added"]), info["data_added"][:10]))
    if info.get("data_rotated"):
        print("ℹ 本機每日快照有輪替（保留期限清除或當日重做）：%s" % info["data_rotated"][:10])
    for rel, msg in (info.get("db_logical") or {}).items():
        print("資料庫 %s：%s" % (rel, msg))
    if code == 5:
        print("回滾後比對不通過：\n  " + "\n  ".join(log["problems"]))
        return code
    print("回滾（%s）完成：程式檔%s與備份逐檔雜湊相等"
          % (a.mode, "、設定檔、資料庫（另比邏輯內容）" if a.mode == "full" else ""))
    # CORE-SPEC §9b 主持裁示：回滾後的 V9 ping 由工具自動做並印出結果，不自動做決定
    ping = log["v9_ping"]
    if isinstance(ping, dict):
        print("V9 啟動 ping（port %d）：%s" % (a.ping_port, "200 OK" if ping["ok"] else "失敗 status=%s" % ping["status"]))
        if not ping["ok"]:
            print(log["v9_ping_log_tail"])
    else:
        print("V9 啟動 ping：%s——請照 RUNBOOK §6 手動確認" % ping)
    return code


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
    sub.choices["rollback"].add_argument("--ping-port", type=int, default=6671)
    sub.choices["rollback"].add_argument("--no-ping", action="store_true")
    a = ap.parse_args(argv)
    return {"preflight": cmd_preflight, "backup": cmd_backup, "convert": cmd_convert,
            "verify": cmd_verify, "rollback": cmd_rollback}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
