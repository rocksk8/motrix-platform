# -*- coding: utf-8 -*-
"""建包開跑前的測試行程盤點（2026-09-30 使用者「安排建包的優化方式，避免非正常情況的失敗」；PLAYBOOK §D-建包）。

build_deploy_package.ps1 在登記獨佔之前呼叫：
  python tools/platform/build_preflight.py --self-pid <建包 pid> [--wait-minutes N] [--lock <鎖檔>]
1. 列出本機**其他**正在跑的 pytest／modtest 行程（排除建包自己的子孫），附父行程鏈 ⇒ 建包期間 CPU 被誰分走一目了然。
2. 測試鎖的持有者（各格＋獨佔登記）逐一判定是否**疑似孤兒**：
   - 父行程已不存在（或 pid 被重用：父行程比子行程晚建立）——例：timeout.exe／TaskStop 結束了外層，pytest 孫行程還在；
   - 祖先鏈上沒有任何存活的 Claude／殼（claude、node、powershell、pwsh、cmd、bash…）。
   **只報告、不結束任何行程**：孤兒也可能是別人刻意放著跑的，要人確認後自己 `taskkill /PID <pid> /T /F`。
3. --wait-minutes N：等其他（非孤兒）pytest 結束，最多 N 分鐘；時限到照常繼續（重型測試本來就由鎖排隊，這一步只是減少同時負載）。
永遠 exit 0（盤點失敗只警告）——這一步是**減少**非正常失敗，不可以自己變成新的失敗來源。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

#: 祖先鏈上有其中之一 ⇒ 有人（或某個 Claude 視窗）還握著它
LIVE_ANCESTORS = {"claude.exe", "node.exe", "powershell.exe", "pwsh.exe", "cmd.exe", "bash.exe", "sh.exe",
                  "windowsterminal.exe", "openconsole.exe", "code.exe", "mintty.exe", "explorer.exe"}
_PYTEST_RE = re.compile(r"(-m\s+pytest\b|[\\/\s]pytest(\.exe)?(\s|$)|py\.test|modtest\.py)", re.I)
_PS = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-CimInstance Win32_Process | ForEach-Object { "
       "[pscustomobject]@{pid=[int]$_.ProcessId; ppid=[int]$_.ParentProcessId; name=[string]$_.Name; cmd=[string]$_.CommandLine; "
       "created=$(if ($_.CreationDate) { ([DateTimeOffset]$_.CreationDate).ToUnixTimeSeconds() } else { 0 })} } | ConvertTo-Json -Compress")


def snapshot(timeout=60):
    """⇒ [{pid, ppid, name, cmd, created}]；取不到回 None。"""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS], capture_output=True,
                           timeout=timeout)
        data = json.loads(r.stdout.decode("utf-8-sig", errors="replace") or "null")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if isinstance(data, dict):
        data = [data]
    return data if isinstance(data, list) else None


def index(procs):
    return {int(p["pid"]): p for p in procs or [] if p.get("pid") is not None}


def _parent(p, idx):
    """父行程（還活著、而且比子行程早建立）；否則 None（父行程已不存在或 pid 被重用）。"""
    pp = idx.get(int(p.get("ppid") or 0))
    if pp is None or pp is p:
        return None
    if (pp.get("created") or 0) > (p.get("created") or 0) > 0:
        return None
    return pp


def ancestors(pid, idx, depth=40):
    out, seen = [], {pid}
    cur = idx.get(pid)
    while cur is not None and len(out) < depth:
        par = _parent(cur, idx)
        if par is None or int(par["pid"]) in seen:
            break
        seen.add(int(par["pid"]))
        out.append(par)
        cur = par
    return out


def classify(pid, idx):
    """⇒ {pid, alive, parent_gone, has_live_ancestor, orphan, reasons, chain}。純函式（吃 snapshot 的 index）。"""
    p = idx.get(pid)
    if p is None:
        return {"pid": pid, "alive": False, "orphan": False, "reasons": [], "chain": []}
    chain = ancestors(pid, idx)
    parent_gone = _parent(p, idx) is None
    has_live = any(str(a.get("name") or "").lower() in LIVE_ANCESTORS for a in chain)
    reasons = []
    if parent_gone:
        reasons.append("父行程已不存在（pid %s）" % p.get("ppid"))
    if not has_live:
        reasons.append("祖先鏈沒有存活的 Claude／殼")
    return {"pid": pid, "alive": True, "parent_gone": parent_gone, "has_live_ancestor": has_live,
            "orphan": bool(reasons), "reasons": reasons, "cmd": p.get("cmd") or "", "created": p.get("created"),
            "chain": ["%s(%s)" % (a.get("name"), a.get("pid")) for a in chain]}


def is_pytest(p):
    return str(p.get("name") or "").lower().startswith("python") and bool(_PYTEST_RE.search(p.get("cmd") or ""))


def descendants(root, procs):
    kids = {}
    for p in procs or []:
        kids.setdefault(int(p.get("ppid") or 0), []).append(int(p["pid"]))
    out, stack = set(), [root]
    while stack:
        for c in kids.get(stack.pop(), []):
            if c not in out and c != root:
                out.add(c)
                stack.append(c)
    return out


def other_pytests(procs, self_pid):
    """建包自己（self_pid）與它的子孫以外、正在跑的 pytest／modtest 主行程。"""
    mine = descendants(self_pid, procs) | {self_pid}
    found = [p for p in procs or [] if is_pytest(p) and int(p["pid"]) not in mine]
    # venv 的 python.exe 是轉呼叫器：它底下再起一個參數相同的真正直譯器 ⇒ 同一輪只列一次（留外層）
    by_pid = {int(p["pid"]): p for p in found}
    return [p for p in found
            if not (int(p.get("ppid") or 0) in by_pid and _args(by_pid[int(p["ppid"])]) == _args(p))]


def _args(p):
    """命令列去掉執行檔那一段（第一個 token，含引號的路徑）。"""
    cmd = (p.get("cmd") or "").strip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        return cmd[end + 1:].strip() if end > 0 else cmd
    return cmd.split(" ", 1)[1].strip() if " " in cmd else ""


def lock_files(lock):
    base = Path(lock)
    try:
        n = max(1, int(os.environ.get("MOTRIX_PYTEST_SLOTS", "2")))
    except ValueError:
        n = 2
    return [base] + [base.with_name(base.name + ".slot%d" % i) for i in range(2, n + 1)] + [base.with_name(base.name + ".exclusive")]


def lock_holders(lock):
    out = []
    for f in lock_files(lock):
        try:
            info = json.loads(f.read_text(encoding="utf-8"))
            out.append({"file": str(f), "pid": int(info.get("pid")), "started_at": info.get("started_at"),
                        "basetemp": info.get("basetemp")})
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return out


def report(procs, self_pid, lock, now=None):
    """⇒ (文字行, 其他非孤兒 pytest 的 pid 清單)。"""
    now = now or time.time()
    idx = index(procs)
    lines = []
    holders = lock_holders(lock)
    for h in holders:
        if h["pid"] == self_pid:
            continue
        c = classify(h["pid"], idx)
        age = (now - float(h.get("started_at") or now)) / 60
        if not c["alive"]:
            lines.append("[鎖] %s：pid %s 已結束（conftest 會自動接手，不必處理）" % (Path(h["file"]).name, h["pid"]))
        elif c["orphan"]:
            lines.append("[鎖] ⚠ 疑似孤兒持有者 %s：pid %s、已 %d 分鐘、%s\n      命令：%s\n      祖先：%s\n"
                         "      確認不是別人刻意放著跑的，再自行結束：taskkill /PID %s /T /F（建包不會自動結束任何行程）"
                         % (Path(h["file"]).name, h["pid"], age, "；".join(c["reasons"]), c["cmd"][:200],
                            " ← ".join(c["chain"]) or "（無）", h["pid"]))
        else:
            lines.append("[鎖] %s：pid %s 持有中（%d 分鐘，%s）；祖先：%s" % (Path(h["file"]).name, h["pid"], age, h.get("basetemp"),
                                                                    " ← ".join(c["chain"][:4])))
    waiting = []
    others = other_pytests(procs, self_pid)
    for p in others:
        c = classify(int(p["pid"]), idx)
        tag = "⚠ 疑似孤兒（%s）" % "；".join(c["reasons"]) if c["orphan"] else "執行中"
        if not c["orphan"]:
            waiting.append(int(p["pid"]))
        lines.append("[pytest] pid %s %s：%s\n      祖先：%s" % (p["pid"], tag, (p.get("cmd") or "")[:200],
                                                         " ← ".join(c["chain"][:6]) or "（無）"))
    if not others and not [h for h in holders if h["pid"] != self_pid]:
        lines.append("[盤點] 沒有其他 pytest 在跑、鎖是空的。")
    elif others:
        lines.append("[盤點] 其他 pytest %d 個（非孤兒 %d）——建包期間它們會分走 CPU，靠時序的 e2e 最容易因此偶發紅；"
                     "建包期間新的臨時 pytest 會被 conftest 拒絕（MOTRIX_PYTEST_BUILD_GUARD）。" % (len(others), len(waiting)))
    return lines, waiting


def _default_lock():
    return os.environ.get("MOTRIX_PYTEST_LOCK") or str(Path(tempfile.gettempdir()) / "motrix-pytest-full-regression.lock")


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-pid", type=int, required=True)
    ap.add_argument("--lock", default=None)
    ap.add_argument("--wait-minutes", type=float, default=0)
    ap.add_argument("--poll", type=float, default=15)
    a = ap.parse_args(argv)
    lock = a.lock or _default_lock()
    deadline = time.time() + a.wait_minutes * 60
    first = True
    while True:
        procs = snapshot()
        if procs is None:
            print("[盤點] ⚠ 取不到行程清單（Get-CimInstance 失敗）——略過盤點，照常繼續")
            return 0
        lines, waiting = report(procs, a.self_pid, lock)
        if first:
            print("\n".join(lines))
            first = False
        if not waiting or a.wait_minutes <= 0:
            return 0
        if time.time() >= deadline:
            print("[盤點] 等了 %.0f 分鐘仍有 %d 個 pytest 在跑（pid %s）——照常繼續；重型測試由鎖排隊"
                  % (a.wait_minutes, len(waiting), ", ".join(map(str, waiting))))
            return 0
        print("[盤點] 等 %d 個 pytest 結束（pid %s），最多再等 %.0f 分鐘…" % (len(waiting), ", ".join(map(str, waiting)),
                                                                   (deadline - time.time()) / 60), flush=True)
        time.sleep(a.poll)


if __name__ == "__main__":
    try:                                                              # 背景執行不彈視窗（tools/platform/nowindow.py；MOTRIX_SHOW_WINDOWS=1 可關）
        import sys as _s, pathlib as _p
        _s.path.insert(0, str(_p.Path(__file__).resolve().parents[1] / "tools" / "platform"))
        import nowindow as _nw
        _nw.install()
    except ImportError:
        pass
    try:
        sys.exit(main())
    except Exception as e:                    # noqa: BLE001 — 盤點不可以讓建包失敗
        print("[盤點] ⚠ 盤點本身出錯（%r）——照常繼續" % (e,))
        sys.exit(0)
