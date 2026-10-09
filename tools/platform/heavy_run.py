# -*- coding: utf-8 -*-
"""全機重型執行的排隊／優先序／可見度包裝（SPEEDUP-PIPELINE-T50 步驟 0＋2）。

[單位] tools:heavy_run    [層] 工具    [穩定度] 內部
[公開介面] can_start, load_tickets, status_line, run, main
[不變式] 只包在現有 conftest 鎖（`motrix-pytest-full-regression.lock*`，2 格＋獨佔登記）**外面**，不取代它——鎖仍是最後防線；
    不殺任何人的行程；票根壞掉／行程已死一律視為過期並清掉；`light` 不排隊（只在 `--track` 時留票根讓別人看得到）。
    **不讓任何快取結果取代凍結樹的正式閘門**（那是另案，需使用者書面同意）。

用法：
  python tools/platform/heavy_run.py --status                         一行：誰在跑、誰在等、conftest 鎖的持有者（唯讀）
  python tools/platform/heavy_run.py --class heavy --window ab -- python -m pytest ...   排隊後執行（低優先）
  python tools/platform/heavy_run.py --class e2e   --window ab -- python -m pytest ...   獨佔：等所有重型結束，且擋住之後才排的重型
  python tools/platform/heavy_run.py --class official --window b7 -- <正式閘門指令>        最高優先、獨佔、一般優先權（不降權）
級別（優先序：official > e2e > heavy > watcher；light 不排隊）：
  light    單檔、1 worker、< 2 分鐘；直接跑（`--track` 才留票根）
  heavy    pytest ≥ 2 worker、建包、modtest --full；全機同時只有一個
  e2e      瀏覽器測試；獨佔
  official 正式閘門（建包／run-stage 全段）；獨佔、不降權
  watcher  背景增量跑者（步驟 3，之後才有）；最低優先
目錄：環境變數 MOTRIX_CI_DIR（預設 D:\\開發測試檔\\_ci）下的 queue\\。票根 <時間>-<視窗>-<級別>.json。結束碼＝被包的指令的結束碼。
"""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CLASSES = ("official", "e2e", "heavy", "watcher", "light")
PRIORITY = {"official": 0, "e2e": 1, "heavy": 2, "watcher": 3, "light": 9}
EXCLUSIVE = {"official", "e2e"}
POLL_SECONDS = 2.0
STALE_SECONDS = 12 * 3600                      # 票根超過 12 小時一律視為過期（行程還在也一樣——與 conftest 的逾時同一個精神）


def ci_dir() -> Path:
    return Path(os.environ.get("MOTRIX_CI_DIR") or r"D:\開發測試檔\_ci")


def queue_dir() -> Path:
    return ci_dir() / "queue"


def pid_alive(pid) -> bool:
    """唯讀判斷（不用 os.kill）：Windows 走 OpenProcess(QUERY_LIMITED_INFORMATION)＋GetExitCodeProcess；pid 重用靠 STALE_SECONDS 兜底。"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            return k.GetLastError() == 5            # 存在但沒權限查 ⇒ 算活著
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def load_tickets(qdir: Path, now=None, alive=pid_alive, clean=True):
    """⇒ 依 (優先序, 入列時間) 排好的有效票根；壞檔／行程已死／逾時的刪掉（clean=True）。"""
    now = time.time() if now is None else now
    out = []
    if not qdir.is_dir():
        return out
    for f in sorted(qdir.glob("*.json")):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
            t["_file"] = str(f)
            ok = isinstance(t, dict) and t.get("class") in CLASSES and alive(t.get("pid")) and now - float(t.get("enqueued", 0)) <= STALE_SECONDS
        except (OSError, ValueError, TypeError):
            ok = False
        if not ok:
            if clean:
                try:
                    f.unlink()
                except OSError:
                    pass
            continue
        out.append(t)
    out.sort(key=lambda t: (PRIORITY[t["class"]], float(t.get("enqueued", 0)), t["_file"]))
    return out


def can_start(me: dict, tickets: list) -> bool:
    """純函式：這張票現在能不能開跑。
    - light 永遠能。
    - 已經在跑的（started 有值）：重型最多一個；有獨佔的在跑 ⇒ 誰都不能開（除了自己）。
    - 排在前面（優先序更高，或同級先入列）而還在等的票 ⇒ 我讓它先（不插隊）。
    - 我是獨佔 ⇒ 必須沒有任何其他票在跑。"""
    if me["class"] == "light":
        return True
    others = [t for t in tickets if t["_file"] != me["_file"] and t["class"] != "light"]
    running = [t for t in others if t.get("started")]
    if running and (me["class"] in EXCLUSIVE or any(t["class"] in EXCLUSIVE for t in running) or any(t["class"] != "watcher" for t in running)):
        return False
    if me["class"] == "watcher" and running:
        return False
    key = (PRIORITY[me["class"]], float(me.get("enqueued", 0)), me["_file"])
    for t in others:
        if t.get("started"):
            continue
        if (PRIORITY[t["class"]], float(t.get("enqueued", 0)), t["_file"]) < key:
            return False
    return True


def _age(sec) -> str:
    sec = int(max(0, sec))
    return "%dh%02dm" % (sec // 3600, sec % 3600 // 60) if sec >= 3600 else "%dm%02ds" % (sec // 60, sec % 60)


def conftest_locks(tmpdir=None):
    """conftest 的全機鎖持有者（唯讀）：⇒ [(檔名, pid, 開始至今秒, basetemp)]，只列行程還活著的。"""
    base = Path(tmpdir or tempfile.gettempdir())
    out = []
    for f in sorted(base.glob("motrix-pytest-full-regression.lock*")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and pid_alive(d.get("pid")):
            out.append((f.name, d.get("pid"), time.time() - float(d.get("started_at", time.time())), str(d.get("basetemp", ""))))
    return out


def status_line(tickets=None, locks=None, now=None) -> str:
    now = time.time() if now is None else now
    tickets = load_tickets(queue_dir(), now) if tickets is None else tickets
    locks = conftest_locks() if locks is None else locks
    run = ["%s %s(pid %s, %s)" % (t.get("window", "?"), t["class"], t.get("pid"), _age(now - float(t.get("started", now)))) for t in tickets if t.get("started")]
    wait = ["%s %s" % (t.get("window", "?"), t["class"]) for t in tickets if not t.get("started") and t["class"] != "light"]
    light = [t for t in tickets if t["class"] == "light"]
    lk = ["%s pid %s %s" % (n.replace("motrix-pytest-full-regression.lock", "lock") or "lock", p, _age(a)) for n, p, a, _b in locks]
    return "跑：%s｜等：%s｜輕：%d｜conftest 鎖：%s" % ("、".join(run) or "無", "、".join(wait) or "無", len(light), "、".join(lk) or "無")


def _enqueue(qdir: Path, cls: str, window: str, cmd: list) -> dict:
    qdir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    seq = 0
    while True:
        name = "%013d-%s-%s%s.json" % (int(now * 1000), "".join(c for c in window if c.isalnum() or c in "-_") or "x", cls, ("-%d" % seq) if seq else "")
        p = qdir / name
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            seq += 1
    t = {"pid": os.getpid(), "window": window, "class": cls, "cmd": " ".join(cmd)[:300], "enqueued": now, "started": None}
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(t, ensure_ascii=False))
    t["_file"] = str(p)
    return t


def _write(t: dict):
    d = {k: v for k, v in t.items() if k != "_file"}
    tmp = t["_file"] + ".tmp"
    Path(tmp).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, t["_file"])


def run(cmd: list, cls="heavy", window="x", track=False, qdir=None, runner=None, sleep=time.sleep, note=print, max_wait=None):
    """排隊 → 開跑 → 收票。回被包指令的結束碼；等超過 max_wait 秒 ⇒ 回 75（EX_TEMPFAIL），不跑。"""
    qdir = Path(qdir) if qdir else queue_dir()
    if cls == "light" and not track:
        return _spawn(cmd, cls, runner, {})
    me = _enqueue(qdir, cls, window, cmd)
    t0 = time.time()
    try:
        last = ""
        while True:
            tickets = load_tickets(qdir)
            mine = next((t for t in tickets if t["_file"] == me["_file"]), None)
            if mine is None:                                   # 票根被清掉（理論上不會）⇒ 重新入列
                me = _enqueue(qdir, cls, window, cmd)
                continue
            if can_start(mine, tickets):
                break
            if max_wait is not None and time.time() - t0 > max_wait:
                note("[heavy_run] 等超過 %ds，放棄（75）" % max_wait)
                return 75
            line = status_line(tickets, [])
            if line != last:
                note("[heavy_run] 排隊中（%s）：%s" % (cls, line))
                last = line
            sleep(POLL_SECONDS)
        me["started"] = time.time()
        _write(me)
        note("[heavy_run] 開跑（%s，%s）" % (cls, "一般優先權" if cls == "official" else "低優先權"))
        return _spawn(cmd, cls, runner, {"MOTRIX_CI_TICKET": me["_file"]})
    finally:
        try:
            os.unlink(me["_file"])
        except OSError:
            pass


def _spawn(cmd, cls, runner, extra_env):
    env = dict(os.environ)
    env.update(extra_env)
    flags = 0
    if os.name == "nt" and cls != "official":
        flags = 0x00004000                                      # BELOW_NORMAL_PRIORITY_CLASS
    if runner is not None:
        return runner(cmd, env, flags)
    return subprocess.run(cmd, env=env, creationflags=flags).returncode


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                           # noqa: BLE001
        pass
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = []
    if "--" in argv:
        i = argv.index("--")
        argv, cmd = argv[:i], argv[i + 1:]
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--class", dest="cls", choices=CLASSES, default="heavy")
    ap.add_argument("--window", default=os.environ.get("MOTRIX_WINDOW", "x"))
    ap.add_argument("--track", action="store_true", help="light 也留票根（讓 --status 看得到）")
    ap.add_argument("--max-wait", type=int, default=None, help="最多等幾秒（逾時回 75，不跑）")
    a = ap.parse_args(argv)
    if a.status:
        print(status_line())
        return 0
    if not cmd:
        ap.error("要執行的指令放在 -- 後面")
    return run(cmd, a.cls, a.window, a.track, max_wait=a.max_wait)


if __name__ == "__main__":
    sys.exit(main())
