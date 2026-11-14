"""A1 M1 演練前的環境檢查（PM 要求：寫成腳本、演練前自動執行、任何一項不過就不跑）。

用法：
  python tools/platform/a1_drill_preflight.py [--root D:\\Claude-pm\\a1-drill\\<時間戳>]
  結束碼 0＝全部通過；1＝有未通過（或「無法確認」）⇒ 演練不可以開始。

原則：**無法確認＝不通過**（例如 PowerShell 查不到排程工作的狀態、連線測試出現無法判斷的錯誤）。

檢查項目：
  1. 排程工作「MOTRIX ERP Server Autostart」不存在（apply_update.ps1 會去停用／啟動它，那是別的安裝）。
  2. 演練目錄路徑不含 V9.0（V9 以路徑判斷正式機、會真的寄信），而且在 D:\\Claude-pm\\a1-drill\\ 底下。
  3. 演練用的 ERP 埠 6766、儀表板埠 8766 沒有人在聽；正式 ERP 埠 666 也沒有人在聽（本機不該是正式機）。
  4. 正式機 172.16.10.177 連不到：ping 不通、TCP 666／8765 連不上；而且本機沒有這個 IP。
     「連線被拒」代表對方主機有回應＝連得到主機 ⇒ 不通過；只有逾時、無路由才算連不到。
"""
import argparse
import errno
import os
import socket
import subprocess
import sys
from pathlib import Path

TASK_NAME = "MOTRIX ERP Server Autostart"
PROD_IP = "172.16.10.177"
PROD_PORTS = (666, 8765)
ERP_PORT = 6766
DASH_PORT = 8766
PROD_ERP_PORT = 666
DRILL_BASE = r"D:\Claude-pm\a1-drill"

# 10060／10051／10065＝WSAETIMEDOUT／WSAENETUNREACH／WSAEHOSTUNREACH；10035／10036＝WSAEWOULDBLOCK／WSAEINPROGRESS（Windows 上 connect 逾時時 connect_ex 回的值）
_UNREACHABLE_ERRNOS = {errno.ETIMEDOUT, errno.ENETUNREACH, errno.EHOSTUNREACH, 10060, 10051, 10065, 10035, 10036}
_REFUSED_ERRNOS = {errno.ECONNREFUSED, 10061}                                                          # 10061＝WSAECONNREFUSED：有主機回應（只是沒人聽）


class DrillAbort(Exception):
    """環境檢查沒過 ⇒ 不可以演練。str(e) 是逐項原因。"""


class Probes:
    """所有碰到本機環境的動作都在這裡（測試換掉它）。"""

    def scheduled_task_exists(self, name):
        """⇒ True／False；查不出來丟例外（呼叫端把它當「無法確認＝不通過」）。"""
        ps = "if (Get-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue) { 'EXISTS' } else { 'ABSENT' }" % name.replace("'", "''")
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60)
        out = (r.stdout or "").strip()
        if r.returncode != 0 or out not in ("EXISTS", "ABSENT"):
            raise RuntimeError("PowerShell 查詢排程工作沒有得到明確答案（rc=%s，輸出=%r，錯誤=%r）" % (r.returncode, out[:80], (r.stderr or "")[:120]))
        return out == "EXISTS"

    def is_listening(self, port):
        """本機有人在聽這個埠嗎？連 127.0.0.1 連得上就是有。⇒ True／False；其他錯誤丟例外。"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(6)                                      # Windows 對關閉的埠會重試 SYN 約 2 秒才回「被拒」
        try:
            rc = s.connect_ex(("127.0.0.1", port))
        finally:
            s.close()
        if rc == 0:
            return True
        if rc in _REFUSED_ERRNOS:
            return False
        # 連線沒有明確答案（逾時等）⇒ 改用「試著獨占這個埠」判斷：綁得上＝沒人聽；位址已被使用＝有人聽；其他＝無法判斷
        b = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            b.bind(("127.0.0.1", port))
            return False
        except OSError as e:
            if e.errno in (errno.EADDRINUSE, 10048, 10013):  # 10048＝WSAEADDRINUSE；10013＝WSAEACCES（Windows 獨占綁定被占用時也可能回這個）
                return True
            raise RuntimeError("測 127.0.0.1:%d 得到無法判斷的結果 connect errno=%s，bind=%s" % (port, rc, e))
        finally:
            b.close()

    def tcp_reach(self, host, port, timeout=3):
        """⇒ "open"（連上了）／"refused"（主機有回應但沒人聽）／"unreachable"（逾時、無路由）；其他錯誤丟例外。"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            rc = s.connect_ex((host, port))
        except socket.timeout:
            return "unreachable"
        finally:
            s.close()
        if rc == 0:
            return "open"
        if rc in _REFUSED_ERRNOS:
            return "refused"
        if rc in _UNREACHABLE_ERRNOS:
            return "unreachable"
        raise RuntimeError("連 %s:%d 得到無法判斷的結果 errno=%s" % (host, port, rc))

    def ping(self, host):
        """⇒ True（有回應）／False（沒有）。"""
        r = subprocess.run(["ping", "-n", "1", "-w", "2000", host], capture_output=True, text=True, timeout=30)
        return r.returncode == 0 and "TTL=" in (r.stdout or "").upper()

    def local_ips(self):
        ips = set()
        for info in socket.getaddrinfo(socket.gethostname(), None):
            ips.add(info[4][0])
        return ips


def _path_problem(root):
    p = str(root)
    low = p.lower().replace("/", "\\")
    if "v9.0" in low:
        return "演練目錄路徑含 V9.0（V9 以路徑判斷正式機）：%s" % p
    if not os.path.isabs(p):
        return "演練目錄不是絕對路徑：%s" % p
    if not low.startswith(DRILL_BASE.lower() + "\\"):
        return "演練目錄不在 %s 底下：%s" % (DRILL_BASE, p)
    if ".." in low.split("\\"):
        return "演練目錄含 ..：%s" % p
    return None


def check(root, probes=None, erp_port=ERP_PORT, dash_port=DASH_PORT, prod_ip=PROD_IP, prod_ports=PROD_PORTS):
    """⇒ [(項目, 通過 True／False, 說明)]。每一項各自抓例外：查不出來 ＝ 不通過。"""
    pr = probes or Probes()
    rows = []

    def run(label, fn):
        try:
            ok, detail = fn()
        except Exception as e:                                              # noqa: BLE001 — 無法確認＝不通過
            ok, detail = False, "無法確認：%s" % e
        rows.append((label, bool(ok), detail))

    def task():
        exists = pr.scheduled_task_exists(TASK_NAME)
        return (not exists), ("本機沒有排程工作「%s」" % TASK_NAME if not exists else "本機有排程工作「%s」：套用腳本會去啟動它（別的安裝）" % TASK_NAME)
    run("排程工作不存在", task)

    def path():
        prob = _path_problem(root)
        return prob is None, (prob or "路徑 %s 不含 V9.0、在 %s 底下" % (root, DRILL_BASE))
    run("演練路徑", path)

    for label, port, must_be_free_reason in (("ERP 埠 %d 沒人聽" % erp_port, erp_port, "演練 ERP 的埠已被占用"),
                                              ("儀表板埠 %d 沒人聽" % dash_port, dash_port, "演練儀表板的埠已被占用"),
                                              ("正式 ERP 埠 %d 本機沒人聽" % PROD_ERP_PORT, PROD_ERP_PORT, "本機有東西在聽正式 ERP 的埠，這台可能就是正式機或有別的 ERP 在跑")):
        def port_free(port=port, why=must_be_free_reason):
            listening = pr.is_listening(port)
            return (not listening), ("沒有人在聽 %d" % port if not listening else "%s（%d）" % (why, port))
        run(label, port_free)

    def not_prod_host():
        mine = pr.local_ips()
        return prod_ip not in mine, ("本機沒有 IP %s" % prod_ip if prod_ip not in mine else "本機就是正式機的 IP %s ⇒ 絕對不能在這台演練" % prod_ip)
    run("本機不是正式機", not_prod_host)

    def prod_ping():
        up = pr.ping(prod_ip)
        return (not up), ("ping %s 沒有回應" % prod_ip if not up else "ping %s 有回應：連得到正式機 ⇒ 不演練" % prod_ip)
    run("正式機 %s ping 不通" % prod_ip, prod_ping)

    for port in prod_ports:
        def prod_tcp(port=port):
            res = pr.tcp_reach(prod_ip, port)
            return res == "unreachable", {"unreachable": "連 %s:%d 逾時／無路由（連不到）" % (prod_ip, port),
                                          "open": "連得上 %s:%d ⇒ 連得到正式機，不演練" % (prod_ip, port),
                                          "refused": "%s:%d 連線被拒＝主機有回應，連得到正式機 ⇒ 不演練" % (prod_ip, port)}[res]
        run("正式機 %s:%d 連不上" % (prod_ip, port), prod_tcp)
    return rows


def require_ok(root, probes=None, **kw):
    """演練器入口的第一步：任何一項不過就丟 DrillAbort（演練不開始）。⇒ rows。"""
    rows = check(root, probes, **kw)
    bad = [r for r in rows if not r[1]]
    if bad:
        raise DrillAbort("演練環境檢查未通過，不執行演練：\n" + "\n".join("  ✗ %s：%s" % (b[0], b[2]) for b in bad))
    return rows


def format_rows(rows):
    return "\n".join("  %s %s：%s" % ("✓" if ok else "✗", label, detail) for label, ok, detail in rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=DRILL_BASE + "\\preflight-check", help="演練目錄（只檢查路徑，不建立）")
    a = ap.parse_args(argv)
    rows = check(a.root)
    print(format_rows(rows))
    bad = [r for r in rows if not r[1]]
    print("\n結果：%s" % ("全部通過，可以演練" if not bad else "%d 項未通過 ⇒ 不可以演練" % len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
