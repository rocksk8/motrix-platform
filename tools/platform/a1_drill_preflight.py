"""A1 M1 演練的「不可能碰到正式機，而且要能證明」防線（PM 裁示 2026-11-14）。

三道，全部不主動連線正式機（不 ping、不連 TCP；可達性只看本機路由表，且只當資訊、不當放行條件）：
  1. 演練前（`check`）：排程工作「MOTRIX ERP Server Autostart」不存在；演練路徑不含 V9.0 且在 a1-drill 底下；
     6766／8766 沒人聽、正式 ERP 埠 666 本機沒人聽；本機沒有正式機的 IP。
  2. 安裝建好、啟動之前（`static_scan`）：掃演練目錄裡的設定與腳本副本（.ps1 .bat .cmd .env .ini .cfg .toml .yaml .yml .json），
     不得出現正式機位址、V9.0、或任何非本機的 ERP 位址；`apply_update.ps1` 副本的 `$ProdRoot`／`$Port`、`autostart.bat` 的埠與綁定位址必須指向演練。
  3. 演練期間（`ConnectionMonitor`）：每 2 秒用 netstat -ano 查演練程序樹（含子行程；Get-NetTCPConnection 在這台機器上查不到任何東西，會變成假綠燈，所以不用）有沒有連往任何非本機位址；
     一發現就殺掉整個程序樹、寫紀錄、演練中止。紀錄逐次落檔，演練報告附上它並寫明「整段演練對正式機 N 連線」。
     取樣有間隔：極短暫（<2 秒）的連線理論上可能漏看——所以第 1、2 道（沒有任何指向正式機的設定、ERP 位址只准本機）才是主要保證。

用法：
  python tools/platform/a1_drill_preflight.py [--root D:\\Claude-pm\\a1-drill\\<時間戳>]   # 只做第 1 道，結束碼 0＝可以建演練
  python tools/platform/a1_drill_preflight.py --scan <演練目錄> [--erp-port 6766]            # 第 2 道
「無法確認＝不通過」。
"""
import argparse
import errno
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

TASK_NAME = "MOTRIX ERP Server Autostart"
PROD_IP = "172.16.10.177"
ERP_PORT = 6766
DASH_PORT = 8766
PROD_ERP_PORT = 666
DRILL_BASE = r"D:\Claude-pm\a1-drill"

_REFUSED_ERRNOS = {errno.ECONNREFUSED, 10061}                          # 10061＝WSAECONNREFUSED：本機沒人聽
CONFIG_EXTS = {".ps1", ".bat", ".cmd", ".env", ".ini", ".cfg", ".toml", ".yaml", ".yml", ".json"}
# 隨產品出貨、本來就寫著正式機路徑／位址的檔案，而且**演練不會執行它們**（逐一列名、可審；新增的檔案提到正式機一律不通過）。
# 演練會執行或改寫的 apply_update.ps1、rollback_update.ps1、autostart.bat **不在這份名單**：它們必須是改寫後的演練副本。
KNOWN_PRODUCT_FILES = {
    r"backend\setup_autostart_task.ps1", r"backend\setup_heartbeat_task.ps1", r"backend\version_manifest.json",
    r"backend\tools\apply_module_update.ps1", r"backend\tools\fetch_root_ca.ps1", r"backend\tools\https_setup.ps1",
    r"backend\tools\setup_passkey_client.ps1",
}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "logs", ".venv", "venv", "docs", "tests", "frontend", "_rehearsal_work"}


class DrillAbort(Exception):
    """防線沒過 ⇒ 不可以演練（或演練中止）。str(e) 是逐項原因。"""


class Probes:
    """所有碰到本機環境的動作都在這裡（測試換掉它）。**沒有任何一個會對外連線。**"""

    def scheduled_task_exists(self, name):
        ps = "if (Get-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue) { 'EXISTS' } else { 'ABSENT' }" % name.replace("'", "''")
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        out = (r.stdout or "").strip()
        if r.returncode != 0 or out not in ("EXISTS", "ABSENT"):
            raise RuntimeError("PowerShell 查詢排程工作沒有得到明確答案（rc=%s，輸出=%r，錯誤=%r）" % (r.returncode, out[:80], (r.stderr or "")[:120]))
        return out == "EXISTS"

    def is_listening(self, port):
        """本機有人在聽這個埠嗎？只連 127.0.0.1。⇒ True／False；無法判斷丟例外。"""
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
        b = socket.socket(socket.AF_INET, socket.SOCK_STREAM)        # 連線沒有明確答案 ⇒ 試著獨占這個埠：綁得上＝沒人聽
        try:
            b.bind(("127.0.0.1", port))
            return False
        except OSError as e:
            if e.errno in (errno.EADDRINUSE, 10048, 10013):          # 10048＝WSAEADDRINUSE；10013＝WSAEACCES（獨占綁定被占用時也可能回這個）
                return True
            raise RuntimeError("測 127.0.0.1:%d 得到無法判斷的結果 connect errno=%s，bind=%s" % (port, rc, e))
        finally:
            b.close()

    def local_ips(self):
        return {info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None)}

    def route_info(self, ip):
        """被動：本機路由表怎麼走（Find-NetRoute 只做路由選擇，不送封包）。⇒ 一行文字；查不到回 None。只當資訊。"""
        ps = ("$r = Find-NetRoute -RemoteIPAddress '%s' -ErrorAction SilentlyContinue | Select-Object -First 1; "
              "if ($r) { 'ROUTE ' + $r.InterfaceAlias + ' ' + $r.NextHop } else { 'NOROUTE' }") % ip
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        out = (r.stdout or "").strip().splitlines()
        return out[-1] if out and r.returncode == 0 else None


# ── 第 1 道：演練前 ──────────────────────────────────────────────────────────

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


def check(root, probes=None, erp_port=ERP_PORT, dash_port=DASH_PORT, prod_ip=PROD_IP):
    """⇒ [(項目, 通過 True／False, 說明)]。每一項各自抓例外：查不出來 ＝ 不通過。不連線任何非本機位址。"""
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

    for label, port, why in (("ERP 埠 %d 沒人聽" % erp_port, erp_port, "演練 ERP 的埠已被占用"),
                             ("儀表板埠 %d 沒人聽" % dash_port, dash_port, "演練儀表板的埠已被占用"),
                             ("正式 ERP 埠 %d 本機沒人聽" % PROD_ERP_PORT, PROD_ERP_PORT, "本機有東西在聽正式 ERP 的埠，這台可能就是正式機或有別的 ERP 在跑")):
        def port_free(port=port, why=why):
            listening = pr.is_listening(port)
            return (not listening), ("沒有人在聽 %d" % port if not listening else "%s（%d）" % (why, port))
        run(label, port_free)

    def not_prod_host():
        mine = pr.local_ips()
        return prod_ip not in mine, ("本機不是正式機（沒有正式機的 IP）" if prod_ip not in mine else "本機就是正式機的 IP ⇒ 絕對不能在這台演練")
    run("本機不是正式機", not_prod_host)
    return rows


def route_note(probes=None, prod_ip=PROD_IP):
    """資訊行（不影響放行）：本機路由表有沒有到正式機網段的路。被動查詢；不送任何封包。"""
    try:
        info = (probes or Probes()).route_info(prod_ip)
    except Exception as e:                                                  # noqa: BLE001
        info = None
        err = str(e)
    else:
        err = ""
    if info is None:
        return "路由表查詢無結果%s（資訊用，不影響放行）" % (("：" + err) if err else "")
    return "本機路由表對正式機網段的結果：%s（資訊用：有路由代表理論上連得到，所以才需要第 2、3 道防線）" % info


def require_ok(root, probes=None, **kw):
    """演練器入口的第一步：任何一項不過就丟 DrillAbort（演練不開始）。⇒ rows。"""
    rows = check(root, probes, **kw)
    bad = [r for r in rows if not r[1]]
    if bad:
        raise DrillAbort("演練環境檢查未通過，不執行演練：\n" + "\n".join("  ✗ %s：%s" % (b[0], b[2]) for b in bad))
    return rows


def format_rows(rows):
    return "\n".join("  %s %s：%s" % ("✓" if ok else "✗", label, detail) for label, ok, detail in rows)


# ── 第 2 道：靜態掃描 ───────────────────────────────────────────────────────

_URL_LINE = re.compile(r"(?i)(erp[_-]?url|errurl|\$erpurl|base[_-]?url|DELIVERY_ERP)")
_URL = re.compile(r"(?i)https?://([^\s/\"'`:<>@]+@)?(\[[0-9a-f:]+\]|[A-Za-z0-9._-]+)(?::\d+)?")
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def _scan_text(rel, text, prod_ip, extra_patterns):
    out = []
    low = text.lower()
    if prod_ip in text:
        out.append((rel, "出現正式機位址"))
    if "v9.0" in low:
        out.append((rel, "出現 V9.0（正式機路徑）"))
    for pat in extra_patterns or ():
        if pat and pat.lower() in low:
            out.append((rel, "出現指定的禁用字串 %r" % pat))
    for line in text.splitlines():
        if _URL_LINE.search(line):
            for m in _URL.finditer(line):
                if m.group(2).lower() not in _LOOPBACK_HOSTS or m.group(1):
                    out.append((rel, "ERP 位址不是本機：%s" % m.group(0)[:80]))
    return out


def iter_config_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]
        for fn in filenames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in CONFIG_EXTS or fn.lower().startswith(".env"):
                yield p


def static_scan(root, erp_port=ERP_PORT, prod_ip=PROD_IP, extra_patterns=(), dash_port=DASH_PORT):
    """掃演練目錄的設定與腳本副本。⇒ {"files", "findings": [(相對路徑, 說明)], "allowed_product_files": [...]}；有任何 finding 就不可以演練。
    不讀程式原始碼（.py／.js）與文件資料夾：那是正式機也有的同一份程式，不是這次演練的設定。"""
    root = Path(root)
    findings, n, allowed = [], 0, []
    known = {k.lower() for k in KNOWN_PRODUCT_FILES}
    for p in iter_config_files(root):
        n += 1
        rel = str(p.relative_to(root))
        if rel.lower() in known:
            allowed.append(rel)
            continue
        try:
            text = p.read_text(encoding="utf-8-sig", errors="replace")
        except OSError as e:
            findings.append((rel, "讀不了，無法確認：%s" % e))
            continue
        findings += _scan_text(rel, text, prod_ip, extra_patterns)
    findings += _ps1_findings(root, erp_port)
    findings += _autostart_findings(root, erp_port)
    if n == 0:
        findings.append(("", "演練目錄裡沒有任何設定檔可掃，無法確認（目錄是否建好？）"))
    return {"files": n, "findings": findings, "allowed_product_files": allowed}


def _ps1_findings(root, erp_port):
    out = []
    for name in ("apply_update.ps1", "rollback_update.ps1"):            # 套用和「回復到套用前」（B5 演練會真的執行）兩支都要是演練副本
        out += _one_ps1_findings(root, name, erp_port)
    return out


def _one_ps1_findings(root, name, erp_port):
    ps1 = Path(root) / "backend" / "tools" / name
    rel = "backend\\tools\\" + name
    if not ps1.is_file():
        return [(rel, "找不到腳本副本，無法確認 $ProdRoot／$Port")]
    text = ps1.read_text(encoding="utf-8-sig", errors="replace")
    roots = re.findall(r'^\$ProdRoot = "(.*)"\s*$', text, re.M)
    ports = re.findall(r"^\$Port = (\d+)\s*$", text, re.M)
    if len(roots) != 1 or len(ports) != 1:
        return [(rel, "`$ProdRoot`／`$Port` 不是各恰好一行（%d／%d）⇒ 無法確認" % (len(roots), len(ports)))]
    out = []
    if os.path.normcase(os.path.normpath(roots[0].replace("`$", "$"))) != os.path.normcase(os.path.normpath(str(root))):
        out.append((rel, "$ProdRoot 沒有指向演練目錄：%s" % roots[0]))
    if int(ports[0]) != erp_port:
        out.append((rel, "$Port 不是演練埠 %d：%s" % (erp_port, ports[0])))
    return out


def _autostart_findings(root, erp_port):
    bat = Path(root) / "backend" / "autostart.bat"
    rel = "backend\\autostart.bat"
    if not bat.is_file():
        return [(rel, "找不到演練用的 autostart.bat，無法確認埠與綁定位址")]
    text = bat.read_text(encoding="utf-8-sig", errors="replace")
    out = []
    if not re.search(r"--port %d\b" % erp_port, text):
        out.append((rel, "autostart.bat 沒有 --port %d" % erp_port))
    if "--host 127.0.0.1" not in text:
        out.append((rel, "autostart.bat 沒有只綁 127.0.0.1"))
    return out


def require_static_ok(root, **kw):
    res = static_scan(root, **kw)
    if res["findings"]:
        raise DrillAbort("演練目錄靜態掃描未通過（掃了 %d 個設定檔），不啟動演練：\n%s" % (
            res["files"], "\n".join("  ✗ %s：%s" % f for f in res["findings"])))
    return res


# ── 第 3 道：動態監看 ───────────────────────────────────────────────────────

_TREE_PS = r"""
$roots = @(%(pids)s)
$all = Get-CimInstance Win32_Process | Select-Object ProcessId, ParentProcessId
$tree = New-Object 'System.Collections.Generic.HashSet[int]'
foreach ($r in $roots) { [void]$tree.Add([int]$r) }
$grew = $true
while ($grew) { $grew = $false; foreach ($p in $all) { if ($tree.Contains([int]$p.ParentProcessId) -and -not $tree.Contains([int]$p.ProcessId)) { [void]$tree.Add([int]$p.ProcessId); $grew = $true } } }
ConvertTo-Json -Compress @($tree)
"""
# 連線清單用 `netstat -ano`：這台機器上 Get-NetTCPConnection 什麼都查不到（CIM MSFT_NetTCPConnection 是空的），
# 用它監看會永遠「0 連線」＝假綠燈；netstat 正常。所以取樣前一定先做正對照（見 positive_control）。
_NETSTAT_LINE = re.compile(r"^\s*TCP\s+(\S+)\s+(\S+)\s+(\S+)\s+(\d+)\s*$", re.I)


def parse_netstat(text):
    """`netstat -ano` 輸出 ⇒ [{"pid", "local", "remote", "port", "state"}]（只含 TCP、不含 LISTENING）。"""
    out = []
    for line in text.splitlines():
        m = _NETSTAT_LINE.match(line)
        if not m:
            continue
        local, remote, state, pid = m.groups()
        if state.upper() == "LISTENING":
            continue
        host, _sep, port = remote.rpartition(":")
        host = host.strip("[]")
        host = host.split("%")[0]                      # fe80::1%12
        out.append({"pid": int(pid), "local": local, "remote": host, "port": int(port) if port.isdigit() else 0, "state": state})
    return out


_LOOPBACK_ADDRS = {"127.0.0.1", "::1", "0.0.0.0", "::", "::ffff:127.0.0.1"}


def is_loopback_addr(a):
    a = (a or "").strip().lower()
    return a in _LOOPBACK_ADDRS or a.startswith("127.")


def violations(conns, prod_ip=PROD_IP):
    """連線清單 ⇒ [{...連線, "kind": "prod"|"non_loopback"}]。連往正式機位址標 prod，其餘非本機標 non_loopback。"""
    out = []
    for c in conns or []:
        if not is_loopback_addr(c.get("remote")):
            out.append(dict(c, kind="prod" if c.get("remote") == prod_ip else "non_loopback"))
    return out


class ConnectionMonitor:
    """每 `interval` 秒查演練程序樹的 TCP 連線；非本機連線 ⇒ 殺程序樹、記下、`tripped`。紀錄每次取樣都落檔（jsonl）。
    `sampler(pids)` 預設用 PowerShell 取程序樹＋`netstat -ano`；測試換假的。**開跑前先呼叫 `positive_control()`。**"""

    def __init__(self, log_path, roots_fn, interval=2.0, sampler=None, killer=None, prod_ip=PROD_IP, clock=time.time):
        self.log_path, self.roots_fn, self.interval = Path(log_path), roots_fn, interval
        self.sampler, self.killer, self.prod_ip, self.clock = sampler or self._ps_sample, killer or self._ps_kill, prod_ip, clock
        self.ticks = self.errors = self.prod_hits = self.other_hits = self.max_conns = 0
        self.tripped = None
        self.tree_seen = set()
        self._stop = False
        self._thread = None

    @staticmethod
    def _ps_sample(pids):
        script = _TREE_PS % {"pids": ",".join(str(int(p)) for p in pids) or "0"}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=flags)
        if r.returncode != 0 or not r.stdout.strip():
            raise RuntimeError("監看取樣（程序樹）失敗 rc=%s %s" % (r.returncode, (r.stderr or "")[:120]))
        tree = json.loads(r.stdout.strip().splitlines()[-1])
        tree = [tree] if isinstance(tree, int) else [int(x) for x in tree]
        net = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=flags)
        if net.returncode != 0 or "TCP" not in net.stdout:
            raise RuntimeError("監看取樣（netstat）失敗 rc=%s" % net.returncode)
        mine = set(tree)
        return {"tree": tree, "conns": [c for c in parse_netstat(net.stdout) if c["pid"] in mine]}

    @staticmethod
    def _ps_kill(tree):
        for pid in sorted(tree, reverse=True):
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _log(self, rec):
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def tick(self):
        """取樣一次。⇒ 違規清單（空＝乾淨）。取樣失敗算一次錯誤並記下（連續失敗由呼叫端看 errors）。"""
        self.ticks += 1
        roots = list(self.roots_fn())
        try:
            snap = self.sampler(roots)
        except Exception as e:                                              # noqa: BLE001
            self.errors += 1
            self._log({"t": round(self.clock(), 1), "error": str(e)[:200]})
            return []
        self.tree_seen |= set(snap.get("tree") or [])
        conns = snap.get("conns") or []
        self.max_conns = max(self.max_conns, len(conns))
        bad = violations(conns, self.prod_ip)
        self.prod_hits += sum(1 for b in bad if b["kind"] == "prod")
        self.other_hits += sum(1 for b in bad if b["kind"] != "prod")
        self._log({"t": round(self.clock(), 1), "tree": len(snap.get("tree") or []), "conns": len(conns), "violations": bad})
        if bad and not self.tripped:
            self.tripped = bad
            try:
                self.killer(snap.get("tree") or roots)
            except Exception as e:                                          # noqa: BLE001 — 殺不掉也要記
                self._log({"t": round(self.clock(), 1), "kill_error": str(e)[:200]})
            self._log({"t": round(self.clock(), 1), "event": "TRIPPED", "violations": bad})
        return bad

    def positive_control(self):
        """演練開始前必做：本行程自己開一條本機連線，取樣器必須看得到它；看不到＝監看器是瞎的（這台機器的 Get-NetTCPConnection 就是），
        不能拿來證明「0 連線」⇒ DrillAbort。⇒ True。"""
        import os
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        cli = socket.create_connection(srv.getsockname())
        conn, _ = srv.accept()
        try:
            snap = self.sampler([os.getpid()])
        finally:
            cli.close()
            conn.close()
            srv.close()
        if not any(is_loopback_addr(c.get("remote")) for c in (snap.get("conns") or [])):
            raise DrillAbort("連線監看器的正對照沒過：看不到本行程剛開的一條本機連線，這個監看器是瞎的，不能用來證明沒有連到正式機")
        return True

    def start(self):
        import threading

        def loop():
            while not self._stop and not self.tripped:
                self.tick()
                end = self.clock() + self.interval
                while not self._stop and self.clock() < end:
                    time.sleep(0.2)
        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop = True
        if self._thread:
            self._thread.join(timeout=15)

    def check_clean(self):
        """演練各步驟之間呼叫：被中止就丟 DrillAbort。"""
        if self.tripped:
            raise DrillAbort("監看器發現演練程序連往非本機位址，已殺掉程序樹並中止：%s" % json.dumps(self.tripped, ensure_ascii=False))

    def summary(self):
        s = {"ticks": self.ticks, "sample_errors": self.errors, "max_connections_seen": self.max_conns,
             "prod_connections": self.prod_hits, "non_loopback_connections": self.other_hits, "processes_seen": len(self.tree_seen),
             "interval_seconds": self.interval, "tripped": bool(self.tripped), "log": str(self.log_path)}
        s["statement"] = ("整段演練對正式機 %d 連線；非本機連線 %d 次（共取樣 %d 次，每 %g 秒一次，取樣失敗 %d 次；取樣有間隔，極短暫連線可能漏看，"
                          "主要保證是靜態掃描與 ERP 位址只准本機）" % (self.prod_hits, self.other_hits, self.ticks, self.interval, self.errors))
        return s


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=DRILL_BASE + "\\preflight-check", help="演練目錄（第 1 道只檢查路徑，不建立）")
    ap.add_argument("--scan", help="第 2 道：掃這個演練目錄的設定與腳本副本")
    ap.add_argument("--erp-port", type=int, default=ERP_PORT)
    a = ap.parse_args(argv)
    if a.scan:
        res = static_scan(a.scan, erp_port=a.erp_port)
        for rel, why in res["findings"]:
            print("  ✗ %s：%s" % (rel, why))
        print("\n掃了 %d 個設定檔：%s" % (res["files"], "乾淨" if not res["findings"] else "%d 項問題 ⇒ 不可以演練" % len(res["findings"])))
        return 0 if not res["findings"] else 1
    rows = check(a.root)
    print(format_rows(rows))
    print("  ℹ " + route_note())
    bad = [r for r in rows if not r[1]]
    print("\n結果：%s" % ("全部通過，可以建演練（之後還要過靜態掃描，演練中有連線監看）" if not bad else "%d 項未通過 ⇒ 不可以演練" % len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
