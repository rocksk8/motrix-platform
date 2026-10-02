# -*- coding: utf-8 -*-
"""視窗探針（唯讀）：背景測試時「是誰在彈視窗」——每 100 ms 列舉可見的最上層視窗，新出現的記下 hwnd／類別／標題／行程／父行程鏈。

用法（另開一個終端機，測試開跑前啟動；Ctrl+C 結束會印彙總）：
    python tools/platform/window_probe.py [--seconds 600] [--out probe.jsonl]
彙總依「行程名＋父行程名」計次，直接指出誰在彈（例如 `git.exe ← python.exe`、`msedge.exe ← python.exe`）。
只讀系統狀態，不送按鍵、不關視窗。僅 Windows。
"""
import argparse
import collections
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time

U, K = ctypes.windll.user32, ctypes.windll.kernel32
TH32CS_SNAPPROCESS = 0x2
PROCESS_QUERY_LIMITED = 0x1000


class PE32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG),
                ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]


def procs():
    snap = K.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    out = {}
    e = PE32()
    e.dwSize = ctypes.sizeof(PE32)
    ok = K.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out[e.th32ProcessID] = (e.szExeFile, e.th32ParentProcessID)
        ok = K.Process32NextW(snap, ctypes.byref(e))
    K.CloseHandle(snap)
    return out


def chain(pid, table, depth=4):
    names = []
    while pid in table and len(names) < depth:
        n, ppid = table[pid]
        names.append("%s(%d)" % (n, pid))
        if ppid == pid:
            break
        pid = ppid
    return names


def visible_windows():
    res = []
    cb_t = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(h, _):
        if U.IsWindowVisible(h) and not U.GetWindow(h, 4):                      # GW_OWNER：只看最上層、無擁有者
            ln = U.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(ln + 1)
            U.GetWindowTextW(h, buf, ln + 1)
            cls = ctypes.create_unicode_buffer(256)
            U.GetClassNameW(h, cls, 256)
            pid = wt.DWORD()
            U.GetWindowThreadProcessId(h, ctypes.byref(pid))
            res.append((int(h), cls.value, buf.value, pid.value))
        return True
    U.EnumWindows(cb_t(cb), 0)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    seen = {w[0] for w in visible_windows()}                 # 開始時已存在的視窗不算
    born = {}                                                # pid → (出現時間, 名稱, 父行程名稱)：Windows Terminal 會把新主控台視窗掛在自己名下，要靠「剛啟動的行程」找真兇
    known = set(procs())
    counts = collections.Counter()
    t0 = time.time()
    out = open(a.out, "a", encoding="utf-8") if a.out else None
    try:
        while time.time() - t0 < a.seconds:
            tbl = procs()
            now = time.time()
            for pid_ in set(tbl) - known:
                born[pid_] = (now, tbl[pid_][0], tbl.get(tbl[pid_][1], ("?", 0))[0])
            known = set(tbl)
            for h, cls, title, pid in visible_windows():
                if h in seen:
                    continue
                seen.add(h)
                table = procs()
                ch = chain(pid, table)
                recent = ["%s←%s" % (n, pn) for (bt, n, pn) in born.values() if now - bt < 1.5 and n.lower() not in ("conhost.exe", "openconsole.exe")]
                rec = {"t": round(time.time() - t0, 2), "hwnd": h, "class": cls, "title": title[:80], "chain": ch, "just_started": recent[:8]}
                key = " ← ".join(c.split("(")[0] for c in ch[:2]) or "pid%d" % pid
                if "WindowsTerminal" in key and recent:                         # 終端機視窗：改以剛啟動的行程歸因
                    key = "新主控台（疑：%s）" % "、".join(sorted(set(recent))[:3])
                counts[(key, cls)] += 1
                print(json.dumps(rec, ensure_ascii=False), flush=True)
                if out:
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    print("\n彙總（行程 ← 父行程，視窗類別：次數）")
    for (k, c), n in counts.most_common(30):
        print("  %-40s %-28s %d" % (k, c, n))
    if not counts:
        print("  （期間內沒有新的可見最上層視窗）")


if __name__ == "__main__":
    sys.exit(main())
