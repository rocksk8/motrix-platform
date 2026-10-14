# -*- coding: utf-8 -*-
"""正式機檢查：Edge 的『代理旗標』有沒有被遵守（H2；唯讀診斷，不寫任何系統／系統資料，只用暫存資料夾並在結束時刪掉）。

為什麼要檢查：PDF 渲染硬化用 `--proxy-server=http://127.0.0.1:9`（必定連不上的代理）讓『直接寫 IP 的網址』也連不出去。
受管機器上群組原則（Edge 的 ProxySettings／ProxyMode／ProxyServer 等）可能蓋掉命令列旗標——那時這一層就沒有作用（其他層：CSP、出入口標籤中和仍在）。

做什麼（全部在本機，不連外網）：
1. 讀（只讀）Edge 的代理相關群組原則登錄值與環境變數，列出來。
2. 在 127.0.0.1、127.0.0.2 以及本機的區網 IP（若有）各開一個臨時監聽埠。
3. 用 Edge headless 各渲染兩份只含 `<meta http-equiv=refresh>` 的 HTML：①對照組（不帶代理旗標）②硬化組（帶 H2 的代理旗標）。
   對照組應該『有連線』（證明這台機器上能偵測）；硬化組應該『0 次連線』（證明旗標有被遵守）。
4. 印出白話結論與 JSON；結束碼：0＝代理旗標有效；2＝無法判斷（對照組也沒有連線）；1＝旗標被蓋掉（硬化組仍有連線）。

用法（在 backend 資料夾、用正式機的 Python）：  python tools\\check_edge_proxy_hardening.py
只用標準函式庫；不 import 本系統任何模組、不讀資料庫、不寫 logs／uploads／資料庫。
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading

EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)
HARDEN_PROXY_FLAGS = ["--proxy-server=http://127.0.0.1:9", "--proxy-bypass-list=<-loopback>"]
TIMEOUT = 90


def find_edge():
    for p in EDGE_CANDIDATES:
        if os.path.exists(p):
            return p
    return shutil.which("msedge")


def read_policies():
    """Edge 代理相關群組原則（只讀登錄）。非 Windows 或讀不到 ⇒ 空。"""
    out = {}
    try:
        import winreg
    except ImportError:
        return out
    names = ("ProxySettings", "ProxyMode", "ProxyServer", "ProxyPacUrl", "ProxyBypassList", "ProxyServerMode")
    for hive_name, hive in (("HKLM", winreg.HKEY_LOCAL_MACHINE), ("HKCU", winreg.HKEY_CURRENT_USER)):
        try:
            key = winreg.OpenKey(hive, r"SOFTWARE\Policies\Microsoft\Edge")
        except OSError:
            continue
        for n in names:
            try:
                v, _t = winreg.QueryValueEx(key, n)
                out["%s\\%s" % (hive_name, n)] = v
            except OSError:
                pass
        winreg.CloseKey(key)
    return out


def lan_ip():
    """本機對外網卡的 IP（UDP connect 不會送封包）。取不到 ⇒ None。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


class Listener:
    def __init__(self, host):
        self.host = host
        self.hits = []
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind((host, 0))
        self.srv.listen(8)
        self.srv.settimeout(0.4)
        self.port = self.srv.getsockname()[1]
        self.stop = threading.Event()
        self.t = threading.Thread(target=self.loop, daemon=True)
        self.t.start()

    def loop(self):
        while not self.stop.is_set():
            try:
                c, _a = self.srv.accept()
            except (socket.timeout, OSError):
                continue
            try:
                c.settimeout(0.4)
                self.hits.append(c.recv(200))
                c.sendall(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            finally:
                c.close()

    def close(self):
        self.stop.set()
        self.t.join(2)
        self.srv.close()


def render(edge, tmp, name, url, extra_flags):
    page = os.path.join(tmp, name + ".html")
    with open(page, "w", encoding="utf-8") as f:
        f.write('<!DOCTYPE html><html><head><meta charset="UTF-8"><meta http-equiv="refresh" content="0;url=%s"></head><body>probe</body></html>' % url)
    cmd = [edge, "--user-data-dir=" + os.path.join(tmp, "profile_" + name), "--headless", "--disable-gpu", "--no-sandbox",
           "--print-to-pdf=" + os.path.join(tmp, name + ".pdf"), "--no-pdf-header-footer"] + list(extra_flags) + ["file:///" + page.replace("\\", "/")]
    try:
        subprocess.run(cmd, timeout=TIMEOUT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired:
        return "timeout"
    return "ok"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                      # noqa: BLE001
        pass
    edge = find_edge()
    result = {"edge": edge, "policies": read_policies(),
              "env": {k: os.environ[k] for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY") if k in os.environ}, "targets": []}
    if not edge:
        print("找不到 Edge（msedge.exe）。無法檢查。")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2
    hosts = ["127.0.0.1", "127.0.0.2"]
    ip = lan_ip()
    if ip:
        hosts.append(ip)
    tmp = tempfile.mkdtemp(prefix="motrix_proxy_check_")
    verdict = 0
    try:
        for host in hosts:
            try:
                lis = Listener(host)
            except OSError as e:
                result["targets"].append({"host": host, "skipped": "無法綁定：%s" % e})
                continue
            try:
                url = "http://%s:%d/nav" % (host, lis.port)
                r1 = render(edge, tmp, "ctl_" + host.replace(".", "_"), url, [])
                control = len(lis.hits)
                del lis.hits[:]
                r2 = render(edge, tmp, "hard_" + host.replace(".", "_"), url, HARDEN_PROXY_FLAGS)
                hardened = len(lis.hits)
            finally:
                lis.close()
            if control == 0:
                state = "無法判斷（對照組也沒有連線）"
                verdict = max(verdict, 2)
            elif hardened == 0:
                state = "有效（對照組有連線、硬化組 0 次）"
            else:
                state = "旗標被蓋掉（硬化組仍有連線）"
                verdict = 1
            result["targets"].append({"host": host, "controlHits": control, "hardenedHits": hardened, "controlRender": r1, "hardenedRender": r2, "state": state})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("== Edge 代理旗標檢查 ==")
    print("Edge：%s" % edge)
    print("Edge 代理相關群組原則：%s" % (result["policies"] or "（沒有）"))
    print("環境變數代理：%s" % (result["env"] or "（沒有）"))
    for t in result["targets"]:
        print("  %-15s %s" % (t["host"], t.get("state") or t.get("skipped")))
    print({0: "結論：代理旗標有被遵守（直接寫 IP 的導航連不出去）。",
           1: "結論：代理旗標被蓋掉——群組原則或環境覆蓋了命令列；『直接寫 IP』這一層無效（其他層仍在）。請把上面的『群組原則』一欄回報給開發。",
           2: "結論：無法判斷（這台機器上對照組偵測不到連線）。請把整份輸出回報給開發。"}[verdict])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return verdict


if __name__ == "__main__":
    sys.exit(main())
