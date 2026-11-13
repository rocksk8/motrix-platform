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
閘門鎖（整合者開閘門／合併窗口時持有；期間「不是閘門」的重型排隊一律自動等，不靠口頭約定）：
  python tools/platform/heavy_run.py --gate-lock acquire --window <整合者視窗> [--note "T82 閘門"] [--ttl-hours 4]   取鎖（印 token）；別人持有 ⇒ 退 1
  python tools/platform/heavy_run.py --gate-lock renew   --window <整合者視窗>                                    續期（再給一個 ttl）
  python tools/platform/heavy_run.py --gate-lock release --window <整合者視窗>                                    放鎖（只有持有者；--force 才能放別人的）
  python tools/platform/heavy_run.py --gate-lock status                                                          唯讀：誰持有、剩多久
  放行誰：`--class official`（正式閘門）、`--window` 與持有者相同的票、環境變數 MOTRIX_GATE_TOKEN 等於鎖內 token 的行程。其餘 heavy／e2e／watcher 一律等到放鎖或過期（預設 4 小時自動過期，不會卡死）。
  light（單檔、單 worker）不受影響。鎖檔 <MOTRIX_CI_DIR>/gate.lock。
  conftest 的「直接跑重型」檢查（backend/conftest.py `_queue_guard`）用同一份判斷：閘門鎖持有期間，沒走排隊、也不是持有者的重型 pytest 直接拒絕；沒有閘門鎖時只印警告
  （MOTRIX_REQUIRE_QUEUE=1 ⇒ 警告改拒絕；MOTRIX_QUEUE_GUARD=0 ⇒ 關閉檢查）。
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


def can_start(me: dict, tickets: list, gate=None) -> bool:
    """純函式：這張票現在能不能開跑。
    - light 永遠能。
    - 已經在跑的（started 有值）：重型最多一個；有獨佔的在跑 ⇒ 誰都不能開（除了自己）。
    - 排在前面（優先序更高，或同級先入列）而還在等的票 ⇒ 我讓它先（不插隊）。
    - 我是獨佔 ⇒ 必須沒有任何其他票在跑。
    - gate（有效的閘門鎖）給了：**還在等、而且自己被閘門鎖擋住的票不算「排在我前面」**（它在放鎖前根本不會開跑，
      讓它擋持有者的票就是死結：持有者等它、它等持有者）⇒ 持有者的票等於插隊。已經在跑的票照算。"""
    if me["class"] == "light":
        return True
    others = [t for t in tickets if t["_file"] != me["_file"] and t["class"] != "light"]
    if gate:
        others = [t for t in others if t.get("started") or gate_exempt(t["class"], t.get("window"), gate, {})]
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

# ── 閘門鎖 ──────────────────────────────────────────────────────────────────────
#: 鎖是「顯式」的（整合者取、整合者放），不綁行程：閘門跑完到下一輪開跑之間、合併／修紅的空檔也要擋住別人的重型，
#: 光看「有沒有 official 票在跑」會在空檔漏掉。代價是忘了放 ⇒ 靠 TTL 自動過期兜底（預設 4 小時）。
GATE_FILE = "gate.lock"
GATE_TTL_SECONDS = 4 * 3600
GATE_TOKEN_ENV = "MOTRIX_GATE_TOKEN"
CI_TICKET_ENV = "MOTRIX_CI_TICKET"


def gate_path() -> Path:
    return ci_dir() / GATE_FILE


def read_gate(path=None, now=None):
    """⇒ 有效的閘門鎖 dict（window／token／note／since／expires），沒有、壞檔、已過期 ⇒ None（唯讀；不清檔）。"""
    now = time.time() if now is None else now
    try:
        d = json.loads(Path(path or gate_path()).read_text(encoding="utf-8"))
        if isinstance(d, dict) and d.get("window") and d.get("token") and float(d.get("expires", 0)) > now:
            return d
    except (OSError, ValueError, TypeError):
        pass
    return None


def _gate_write(path: Path, d: dict, exclusive=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(d, ensure_ascii=False)
    if exclusive:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        return
    tmp = str(path) + ".tmp"
    Path(tmp).write_text(data, encoding="utf-8")
    os.replace(tmp, str(path))


def gate_acquire(window, note="", ttl=GATE_TTL_SECONDS, path=None, now=None, force=False):
    """取鎖 ⇒ (ok, lock)。已有別人的有效鎖 ⇒ (False, 對方的鎖)（force ⇒ 蓋掉）；同一視窗再取 ＝ 續期（token 不變）。"""
    path = Path(path or gate_path())
    now = time.time() if now is None else now
    cur = read_gate(path, now)
    if cur and cur["window"] != window and not force:
        return False, cur
    token = cur["token"] if cur and cur["window"] == window else "%08x%08x" % (int(now) & 0xFFFFFFFF, os.getpid() * 2654435761 & 0xFFFFFFFF)
    d = {"window": window, "token": token, "note": note or (cur or {}).get("note", ""), "pid": os.getpid(),
         "since": (cur or {}).get("since", now) if cur and cur["window"] == window else now, "expires": now + float(ttl)}
    if cur is None:
        try:
            path.unlink()                                       # 過期／壞檔 ⇒ 先清掉再用 O_EXCL 搶（兩人同時取鎖只有一個贏）
        except OSError:
            pass
        try:
            _gate_write(path, d, exclusive=True)
        except FileExistsError:
            other = read_gate(path, now)
            return False, other or d
    else:
        _gate_write(path, d)
    return True, d


def gate_release(window, path=None, now=None, force=False):
    """放鎖 ⇒ True（放了或本來就沒有）／False（別人持有且沒 force）。"""
    path = Path(path or gate_path())
    cur = read_gate(path, now)
    if cur and cur["window"] != window and not force:
        return False
    try:
        path.unlink()
    except OSError:
        pass
    return True


def gate_exempt(cls, window, lock, env=None) -> bool:
    """純函式：這張票／這個行程在閘門鎖持有期間能不能跑。official、持有者視窗、帶對 token 的行程放行。"""
    if not lock:
        return True
    env = os.environ if env is None else env
    return cls == "official" or window == lock["window"] or (bool(env.get(GATE_TOKEN_ENV)) and env.get(GATE_TOKEN_ENV) == lock["token"])


def gate_line(lock, now=None) -> str:
    now = time.time() if now is None else now
    if not lock:
        return "閘門鎖：無"
    left = float(lock["expires"]) - now
    return "閘門鎖：%s 持有%s（已 %s，剩 %s%s）" % (lock["window"], "「%s」" % lock["note"] if lock.get("note") else "",
                                                _age(now - float(lock.get("since", now))), _age(left),
                                                "　⚠ 即將過期（保護會自動停止）：整合者用 --gate-lock renew 續期" if left < 1800 else "")


def direct_run_verdict(env=None, lock=None, exclusive_env=("MOTRIX_PYTEST_BUILD_CHILD", "MOTRIX_PYTEST_EXCLUSIVE_OWNER")):
    """純函式（conftest 的 `_queue_guard` 用）：一輪**重型** pytest 沒有經 heavy_run 時的處置 ⇒ (level, 訊息)。
    level：ok（放行、不吭聲）／warn（印警告照跑）／refuse（拒絕）。
    - MOTRIX_QUEUE_GUARD=0 ⇒ ok（整道關閉）。
    - 有 MOTRIX_CI_TICKET（heavy_run 排過隊才會設）或建包的子行程標記 ⇒ ok（那邊各有自己的守門）。
    - 閘門鎖持有中：token 對、或 MOTRIX_WINDOW＝持有者視窗 ⇒ ok；否則 refuse。
    - 沒有閘門鎖：warn；MOTRIX_REQUIRE_QUEUE=1 ⇒ refuse。"""
    env = os.environ if env is None else env
    if env.get("MOTRIX_QUEUE_GUARD") == "0":
        return "ok", ""
    if env.get(CI_TICKET_ENV) or any(env.get(k) for k in exclusive_env):
        return "ok", ""
    if lock:
        if (env.get(GATE_TOKEN_ENV) and env.get(GATE_TOKEN_ENV) == lock["token"]) or (env.get("MOTRIX_WINDOW") and env.get("MOTRIX_WINDOW") == lock["window"]):
            return "ok", ""
        return "refuse", ("%s。這一輪是重型跑法（全量或 -n≥2）而且沒有經排隊、也不是閘門持有者的行程 ⇒ 拒絕。"
                          "要跑：用 `python tools/platform/heavy_run.py --class heavy --window <你的視窗> -- <指令>` 排隊（閘門鎖期間會自動等到放鎖），"
                          "單檔、單 worker 的臨時跑不受影響。" % gate_line(lock))
    msg = ("這一輪是重型跑法（全量或 -n≥2），沒有經 heavy_run 排隊。全機的排隊／優先序／閘門鎖只對有排隊的重型生效 ⇒ "
           "請改用 `python tools/platform/heavy_run.py --class heavy --window <你的視窗> -- <指令>`。")
    if env.get("MOTRIX_REQUIRE_QUEUE") == "1":
        return "refuse", msg + "（MOTRIX_REQUIRE_QUEUE=1）"
    return "warn", msg



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


def status_line(tickets=None, locks=None, now=None, gate=False) -> str:
    now = time.time() if now is None else now
    tickets = load_tickets(queue_dir(), now) if tickets is None else tickets
    locks = conftest_locks() if locks is None else locks
    run = ["%s %s(pid %s, %s)" % (t.get("window", "?"), t["class"], t.get("pid"), _age(now - float(t.get("started", now)))) for t in tickets if t.get("started")]
    wait = ["%s %s" % (t.get("window", "?"), t["class"]) for t in tickets if not t.get("started") and t["class"] != "light"]
    light = [t for t in tickets if t["class"] == "light"]
    lk = ["%s pid %s %s" % (n.replace("motrix-pytest-full-regression.lock", "lock") or "lock", p, _age(a)) for n, p, a, _b in locks]
    return "跑：%s｜等：%s｜輕：%d｜conftest 鎖：%s｜%s" % ("、".join(run) or "無", "、".join(wait) or "無", len(light), "、".join(lk) or "無",
                                                       gate_line(read_gate(now=now) if gate is False else gate, now))


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


def run(cmd: list, cls="heavy", window="x", track=False, qdir=None, runner=None, sleep=time.sleep, note=print, max_wait=None, gate_file=None, env=None):
    """排隊 → 開跑 → 收票。回被包指令的結束碼；等超過 max_wait 秒 ⇒ 回 75（EX_TEMPFAIL），不跑。
    閘門鎖持有期間，非閘門（見 gate_exempt）的票不開跑，自動等到放鎖或過期；放行的票把 token 帶進子行程環境（MOTRIX_GATE_TOKEN）。"""
    qdir = Path(qdir) if qdir else queue_dir()
    gate_file = Path(gate_file) if gate_file else qdir.parent / GATE_FILE      # 閘門鎖跟著佇列目錄走（測試用暫存佇列就不會讀到真的鎖）
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
            gate = read_gate(gate_file)
            gated = bool(gate) and cls != "light" and not gate_exempt(cls, window, gate, env)
            if not gated and can_start(mine, tickets, gate):
                break
            if max_wait is not None and time.time() - t0 > max_wait:
                note("[heavy_run] 等超過 %ds，放棄（75）" % max_wait)
                return 75
            line = status_line(tickets, [], gate=gate)
            if line != last:
                note("[heavy_run] 排隊中（%s）：%s" % (cls, line))
                last = line
            sleep(POLL_SECONDS)
        me["started"] = time.time()
        _write(me)
        note("[heavy_run] 開跑（%s，%s）" % (cls, "一般優先權" if cls == "official" else "低優先權"))
        extra = {CI_TICKET_ENV: me["_file"]}
        gate = read_gate(gate_file)
        if gate and gate_exempt(cls, window, gate, env):
            extra[GATE_TOKEN_ENV] = gate["token"]
        return _spawn(cmd, cls, runner, extra)
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


def _gate_cli(a) -> int:
    window = a.window
    if a.gate_lock == "status":
        print(gate_line(read_gate()))
        return 0
    if a.gate_lock == "release":
        ok = gate_release(window, force=a.force)
        print("[gate-lock] 已放鎖" if ok else "[gate-lock] 鎖在別人手上（%s），不是 %s；確定要放用 --force" % (read_gate()["window"], window))
        return 0 if ok else 1
    if a.gate_lock == "renew" and not (read_gate() or {}).get("window") == window:
        print("[gate-lock] 你（%s）沒有持有有效的閘門鎖，無法續期（用 acquire 取）" % window)
        return 1
    ok, lock = gate_acquire(window, a.note, a.ttl_hours * 3600, force=a.force)
    if not ok:
        print("[gate-lock] 取不到：%s（要接手用 --force）" % gate_line(lock))
        return 1
    print("[gate-lock] %s" % gate_line(lock))
    print("[gate-lock] token=%s" % lock["token"])
    print("[gate-lock] 你自己的 shell 建議設：$env:MOTRIX_WINDOW='%s'（持有者視窗；conftest 認它，直接跑的重型 pytest 與 run-stage 才不會被自己的鎖擋）；"
          "經 heavy_run／run_stage 的會自動帶 token" % window)
    return 0


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
    ap.add_argument("--gate-lock", choices=("acquire", "renew", "release", "status"), help="閘門鎖：整合者取／續／放（持有期間非閘門的重型自動等）")
    ap.add_argument("--note", default="", help="--gate-lock acquire 的備註（顯示在 --status）")
    ap.add_argument("--ttl-hours", type=float, default=GATE_TTL_SECONDS / 3600, help="--gate-lock 的自動過期小時數（預設 4）")
    ap.add_argument("--force", action="store_true", help="--gate-lock acquire／release 對別人持有的鎖也動手（只有 PM／整合者交接時用）")
    ap.add_argument("--class", dest="cls", choices=CLASSES, default="heavy")
    ap.add_argument("--window", default=os.environ.get("MOTRIX_WINDOW", "x"))
    ap.add_argument("--track", action="store_true", help="light 也留票根（讓 --status 看得到）")
    ap.add_argument("--max-wait", type=int, default=None, help="最多等幾秒（逾時回 75，不跑）")
    a = ap.parse_args(argv)
    if a.gate_lock:
        return _gate_cli(a)
    if a.status:
        print(status_line())
        return 0
    if not cmd:
        ap.error("要執行的指令放在 -- 後面")
    return run(cmd, a.cls, a.window, a.track, max_wait=a.max_wait)


if __name__ == "__main__":
    sys.exit(main())
