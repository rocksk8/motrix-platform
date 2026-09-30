"""建包：同一份 tree 已全綠就沿用測試結果（PLAN-TEST-PERF §3.1）。由 build_deploy_package.ps1 呼叫。

用法：
  python build_test_reuse.py fingerprint                         → {"fingerprint": "...", "components": {...}}（工作樹不乾淨 ⇒ fingerprint 為 null）
  python build_test_reuse.py lookup --records F --fp X           → 可沿用的那一筆（JSON），或 null
  python build_test_reuse.py record --records F --fp X --green 1 --commit C

🔑 指紋＝整棵 tracked tree（`HEAD^{tree}`；2026-09-30 起改算 `ls-tree -r HEAD` 扣掉 REUSE_EXCLUDE）＋執行環境。文件不排除：測試會讀 docs/（見
   tests/test_build_test_reuse_2026_09_25.py 的說明）。
🔑 沿用條件：同指紋、**嚴格全綠**（兩段 exit 0，逾時放行不算）、**同一天**、12 小時內；
   同指紋的最新一筆若是紅的，不沿用更早的綠。

## 分段沿用（2026-09-30，建包優化「避免非正常情況的失敗」；正反論證見 PLAYBOOK §D-建包）
  python build_test_reuse.py records-path                                   → 主工作樹的紀錄檔（建包與 modtest 共用）
  python build_test_reuse.py lookup-stage --fp X --stage not_e2e|e2e        → 可沿用的那一段（JSON），或 null
  python build_test_reuse.py record-stage --fp X --stage S --green 1 [--flaky-from R] [--reused-at T] [--flaky ID…]
- 每一行可帶 `stages: {not_e2e|e2e: {green, tested_at, flaky_retried[]}}`；舊格式（沒有 stages）的一行＝兩段同一個結果。
- 一段的判定＝同指紋、**帶有這一段**的最新一筆（沒帶這一段的行跳過：例如只跑完非 e2e 就中斷的那一行不影響 e2e）；
  該段綠、同一天、12 小時內——以**該段原本實跑的時間**算（沿用後再記錄時帶原時間，窗口不會被一路延長）。
- 段的綠＝該段閘門通過：exit 0，或失敗題經隔離重跑通過且已登記在 known_flakes（`flaky_retried` 清單跟著沿用、寫進 manifest）。
  頂層 `green` 仍只代表「這一行兩段都嚴格 exit 0」（舊版建包只看它）。
- `modtest --full` 在乾淨工作樹、無縮小範圍的參數時也寫進同一份紀錄（record_full_run），建包就不必把同一份 tree 再跑一次。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

MAX_HOURS = 12
#: 影響測試結果的 MOTRIX_* 以外的前綴不列；鎖／暫存相關的不影響結果，排除以免每輪指紋都不同。
_ENV_IGNORE = {"MOTRIX_PYTEST_LOCK", "MOTRIX_PYTEST_LOCK_WAIT", "MOTRIX_PYTEST_LOCK_POLL", "MOTRIX_PYTEST_SLOTS",
               "MOTRIX_PYTEST_EXCLUSIVE", "MOTRIX_PYTEST_EXCLUSIVE_OWNER", "MOTRIX_PYTEST_KEEP_BASETEMP",
               # 2026-09-30：建包與 modtest 共用紀錄 ⇒ 兩邊各自會有、而不決定「過或不過」的也排除：
               # worker 上限（影響快慢與負載，不影響題目本身；反方論證見 PLAYBOOK §D-建包）、失敗先行 log、建包守門
               "MOTRIX_FULL_MAX_WORKERS", "MOTRIX_PARTIAL_MAX_WORKERS", "MOTRIX_E2E_MAX_WORKERS",
               "MOTRIX_FAIL_STREAM_RUN", "MOTRIX_FAIL_STREAM_STAGE", "MOTRIX_FAIL_STREAM_DIR",
               "MOTRIX_PYTEST_BUILD_CHILD", "MOTRIX_PYTEST_BUILD_GUARD"}
#: 不進指紋的檔（repo 相對路徑）：只決定「建包放不放行」、不決定任何一題過或不過（2026-09-30）
REUSE_EXCLUDE = frozenset({"tools/platform/known_flakes.json"})
#: 分段沿用認得的段名（建包與 modtest --full 都是這兩段）
STAGES = ("not_e2e", "e2e")
TS_FMT = "%Y-%m-%d %H:%M:%S"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


def current_env():
    """執行環境的組成（會影響測試結果的）。"""
    freeze = subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True).stdout
    try:
        from importlib.metadata import version
        pw = version("playwright")
    except Exception:  # noqa: BLE001 — 沒裝就記成 None，指紋照樣算
        pw = None
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright")
    browsers = sorted(p.name for p in root.iterdir()) if root.is_dir() else []
    env = {
        "python": sys.version,
        "pip_freeze": "\n".join(sorted(freeze.splitlines())),
        "playwright": pw,
        "browsers": browsers,
        "motrix_env": {k: v for k, v in sorted(os.environ.items()) if k.startswith("MOTRIX_") and k not in _ENV_IGNORE},
    }
    # 稽核 W4：PYTEST_ADDOPTS 會悄悄改變跑哪些題（-k／-m／--deselect 縮小範圍）與怎麼跑 ⇒ 進指紋。
    # 只在有設時才加這個鍵：沒設的環境指紋與之前相同（既有紀錄照樣可沿用）。
    addopts = os.environ.get("PYTEST_ADDOPTS")
    if addopts is not None:
        env["pytest_addopts"] = addopts
    return env


def fingerprint(repo, env=None):
    """工作樹不乾淨（含未追蹤檔）⇒ None（不沿用）。"""
    if _git(repo, "status", "--porcelain").strip():
        return None
    # 整棵 tracked tree，扣掉 REUSE_EXCLUDE（建包政策檔：登記一題偶發不改變任何題目過或不過，
    # 而它非改不可才能重建——不扣掉的話「登記 → 重建」一定整套重跑，分段沿用就落空）
    listing = [ln for ln in _git(repo, "ls-tree", "-r", "HEAD").splitlines()
               if ln.split("\t", 1)[-1] not in REUSE_EXCLUDE]
    tree = hashlib.sha256("\n".join(listing).encode("utf-8")).hexdigest()
    env = current_env() if env is None else env
    blob = json.dumps({"tree": tree, "env": env}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def find_reusable(records, fp, now, max_hours=MAX_HOURS):
    """同指紋的**最新一筆**：嚴格全綠、同一天、max_hours 內 ⇒ 回它；否則 None。純函式。"""
    if not fp:
        return None
    same = [r for r in records if r.get("fingerprint") == fp]
    if not same:
        return None
    last = same[-1]          # 紀錄依時間附加 ⇒ 檔案順序就是先後（同一秒寫兩筆時比時間戳分不出來）
    try:
        t = datetime.strptime(last["tested_at"], TS_FMT)
    except (KeyError, ValueError):
        return None
    if last.get("green") is not True or t.date() != now.date():
        return None
    if (now - t).total_seconds() > max_hours * 3600 or t > now:
        return None
    return last


def _stage_ok(entry, now, max_hours):
    try:
        t = datetime.strptime(entry["tested_at"], TS_FMT)
    except (KeyError, TypeError, ValueError):
        return False
    if entry.get("green") is not True or t.date() != now.date():
        return False
    return not ((now - t).total_seconds() > max_hours * 3600 or t > now)


def find_reusable_stage(records, fp, stage, now, max_hours=MAX_HOURS):
    """同指紋、**帶有這一段**的最新一筆決定這一段能不能沿用。純函式。
    回 {green, tested_at, flaky_retried, commit, source} 或 None。
    舊格式（沒有 stages）：green 為真 ⇒ 兩段都綠（時間＝該行時間）；為假 ⇒ 兩段都不可沿用（分不出是哪段紅）。"""
    if not fp or stage not in STAGES:
        return None
    for r in reversed([r for r in records if r.get("fingerprint") == fp]):
        stages = r.get("stages")
        if isinstance(stages, dict):
            if stage not in stages:
                continue              # 這一行沒有這一段的資訊 ⇒ 看更早的
            s = stages.get(stage)
            entry = dict(s) if isinstance(s, dict) else {}
        else:
            entry = {"green": r.get("green"), "tested_at": r.get("tested_at")}
        if not _stage_ok(entry, now, max_hours):
            return None
        flaky = entry.get("flaky_retried") or []
        return {"green": True, "tested_at": entry["tested_at"],
                "flaky_retried": list(flaky) if isinstance(flaky, list) else [],
                "commit": r.get("commit"), "source": r.get("source") or "build"}
    return None


def _read(records):
    p = Path(records)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def lookup(records, fp, now=None):
    return find_reusable(_read(records), fp, now or datetime.now())


def lookup_stage(records, fp, stage, now=None):
    return find_reusable_stage(_read(records), fp, stage, now or datetime.now())


def _append(records, line):
    p = Path(records)
    p.parent.mkdir(parents=True, exist_ok=True)
    # 單次 os.write（O_APPEND）：建包與 modtest 可能同時寫（不同 worktree），整行一次寫完才不會交錯
    fd = os.open(str(p), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def record(records, fp, green, commit, stages=None, source=None):
    """一行紀錄。`green`＝這一行**嚴格全綠**（舊版建包只看它）；`stages` 給了就一併記分段結果。"""
    line = {"fingerprint": fp, "tested_at": datetime.now().strftime(TS_FMT),
            "green": bool(green), "commit": commit}
    if stages is not None:
        line["stages"] = stages
    if source:
        line["source"] = source
    _append(records, line)


def stage_entry(green, tested_at=None, flaky=None):
    e = {"green": bool(green), "tested_at": tested_at or datetime.now().strftime(TS_FMT)}
    if flaky:
        e["flaky_retried"] = list(flaky)
    return e


def default_records(repo=None):
    """紀錄檔固定在**主工作樹**（worktree 用完就刪；建包與 modtest 不論在哪個 worktree 跑都寫同一份）。"""
    here = Path(repo) if repo else Path(__file__).resolve().parent
    common = _git(here, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    return Path(common).parent / "backend" / "tools" / "deploy_logs" / "test_results.jsonl"


def _flaky_from(path):
    """flaky_retry.py 的結果檔 ⇒ 通過且已登記的題（nodeid 清單）。讀不到 ⇒ 例外（呼叫端不記綠）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    return [r["nodeid"] for r in data.get("flaky_retried", [])]


#: modtest --full 可以寫進沿用紀錄的額外參數（只影響輸出或平行度，不影響選到哪些題）
_SAFE_EXTRA = re.compile(r"^(-q|-v+|-r[a-zA-Z]+|--tb=\w+|--durations=\d+|-n\d*|\d+|-p|no:cacheprovider|fail_stream)$")


def extra_is_full_selection(extra):
    """modtest --full 帶的額外參數會不會縮小題目範圍（-k、-m、路徑、--deselect、-x…）⇒ 會就不寫沿用紀錄。"""
    return all(_SAFE_EXTRA.match(str(x)) for x in (extra or []))


def fingerprint_via(python_exe, timeout=180):
    """用**跑測試的那支直譯器**算指紋（pip freeze 要是它的）；算不出來回 None。"""
    try:
        r = subprocess.run([str(python_exe), str(Path(__file__).resolve()), "fingerprint"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return json.loads(r.stdout.strip().splitlines()[-1]).get("fingerprint")
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def record_full_run(records, fp_start, fp_end, commit, codes, extra, interrupted=False):
    """modtest --full 的結果寫進建包的沿用紀錄。回 (是否寫了, 原因)。
    條件：開跑與結束的指紋相同且非 None（工作樹乾淨、環境與 HEAD 沒變）、額外參數不縮小範圍。
    - 兩段都跑完 ⇒ 一行兩段；頂層 green＝兩段都 exit 0。
    - 只跑完非 e2e（e2e 被中斷）⇒ 只記非 e2e（它的綠仍可讓建包只跑 e2e）。
    - 紅也照記：同指紋之前的綠不可以再被沿用（與建包同一條規則）。"""
    if not fp_start or fp_start != fp_end:
        return False, "指紋不同或算不出來（工作樹不乾淨、或跑到一半環境／HEAD 變了）"
    if not extra_is_full_selection(extra):
        return False, "帶了會縮小範圍的參數（%s）" % " ".join(map(str, extra))
    stages = {}
    if "main" in codes:
        stages["not_e2e"] = stage_entry(codes["main"] == 0)
    if "e2e" in codes and not interrupted:
        stages["e2e"] = stage_entry(codes["e2e"] == 0)
    if not stages:
        return False, "沒有任何一段跑完"
    green = len(stages) == 2 and all(s["green"] for s in stages.values())
    record(records, fp_start, green, commit, stages=stages, source="modtest --full")
    return True, "已記錄（%s）" % "、".join("%s=%s" % (k, "綠" if v["green"] else "紅") for k, v in stages.items())


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fingerprint")
    lk = sub.add_parser("lookup")
    lk.add_argument("--records", required=True)
    lk.add_argument("--fp", required=True)
    rc = sub.add_parser("record")
    rc.add_argument("--records", required=True)
    rc.add_argument("--fp", required=True)
    rc.add_argument("--green", required=True)
    rc.add_argument("--commit", default="")
    sub.add_parser("records-path")
    ls = sub.add_parser("lookup-stage")
    ls.add_argument("--records")
    ls.add_argument("--fp", required=True)
    ls.add_argument("--stage", required=True, choices=STAGES)
    rs = sub.add_parser("record-stage")
    rs.add_argument("--records")
    rs.add_argument("--fp", required=True)
    rs.add_argument("--stage", required=True, choices=STAGES)
    rs.add_argument("--green", required=True)
    rs.add_argument("--commit", default="")
    rs.add_argument("--reused-at", help="這一段是沿用來的：原本實跑的時間（窗口不延長）")
    rs.add_argument("--flaky-from", help="flaky_retry.py 的結果檔（通過且已登記的題）")
    rs.add_argument("--flaky", nargs="*", default=[], help="沿用來的 flaky_retried（原樣帶過來）")
    rs.add_argument("--source", default="build")
    a = ap.parse_args(argv)
    repo = _git(Path(__file__).resolve().parent, "rev-parse", "--show-toplevel").strip()
    if a.cmd == "fingerprint":
        print(json.dumps({"fingerprint": fingerprint(repo)}))
    elif a.cmd == "lookup":
        print(json.dumps(lookup(a.records, a.fp), ensure_ascii=False))
    elif a.cmd == "records-path":
        print(default_records(repo))
    elif a.cmd == "lookup-stage":
        # ASCII 輸出：PowerShell 5.1 以系統 locale 解碼原生程式的輸出
        print(json.dumps(lookup_stage(a.records or default_records(repo), a.fp, a.stage)))
    elif a.cmd == "record-stage":
        flaky = list(a.flaky or [])
        if a.flaky_from:
            flaky += _flaky_from(a.flaky_from)
        # 一段一行；頂層 green 恆為 False（不是「兩段都跑過」的完整紀錄 ⇒ 舊版建包看到它不會誤沿用）
        record(a.records or default_records(repo), a.fp, False, a.commit,
               stages={a.stage: stage_entry(a.green == "1", a.reused_at, flaky)}, source=a.source)
    else:
        record(a.records, a.fp, a.green == "1", a.commit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
