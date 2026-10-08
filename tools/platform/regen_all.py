# -*- coding: utf-8 -*-
"""一次重產全部「產生檔」，順序固定（建包優化 O2；第 47 班）。

[單位] tools:regen_all    [層] 工具    [穩定度] 內部
[公開介面] STEPS, plan, run, main
[不變式] 順序＝ 取號（選配）→ dep_graph.json → UNIT-INDEX.md → test_map.json（與 pre_train_check／列車相同）；
    `--check` 不寫任何檔（dep_graph 重產到暫存目錄再比對）；寫入模式只改這三份產生檔（取號另算），絕不 git add／commit；
    任何一步的子行程出錯（exit ≠ 0、非「過期」的那種）⇒ exit 2，且不繼續後面的步驟（後面的步驟讀前面的輸出）；
    取號只在 `--take-number` 時動（分支上本來就有佔位，檢查它們「還沒取號」不是問題）。

為什麼（第 46 班）：作者分支加了一個測試／模組檔就使 dep_graph.json、test_map.json 過期；全量閘門跑到第 12～44 分鐘才紅
（本班 2 次），重產只要 1～2 分鐘。這支把「該重產哪幾份、什麼順序、怎麼確認已是最新」收成一個指令。

`--check` 的 stdout 約定：過期檔路徑一行一個（沒有過期＝空）；人看的說明走 stderr。

用法（在任何一棵 MOTRIX-PLATFORM 樹；Python 用 D:\\MOTRIX-PLATFORM\\.venv312\\Scripts\\python.exe）：
  python tools/platform/regen_all.py                      重產三份；印出有改動的檔（之後由列車／作者自己 add、commit）
  python tools/platform/regen_all.py --check              只檢查：有過期的 ⇒ exit 1 並列出重產指令；不寫檔
  python tools/platform/regen_all.py --take-number [--base origin/platform]
                                                          列車樹用：先 train_number assign，再重產三份
  python tools/platform/regen_all.py --json               機器可讀（給 preflight 跑器）
退出碼：0 全是最新（--check）／重產成功；1 有過期（--check）；2 工具出錯。

⚠ 產生檔只由列車提交（GENERATED-FILES-PROPOSAL §0、PLAYBOOK §G3）：分支上用 `--check` 看會不會過期、必要時本機重產驗證即可，
  是否提交照列車規則。本工具不碰 git。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

#: (名稱, 產生檔相對路徑, 寫入指令, 檢查指令；檢查指令為 None ⇒ 重產到暫存再比對)
#: 順序即執行順序。指令裡的 {py}／{out} 由 plan() 展開。
STEPS = (
    ("dep_graph", "docs/platform/dep_graph.json",
     ["{py}", "tools/platform/dep_scan.py"], None),
    ("unit_index", "docs/platform/UNIT-INDEX.md",
     ["{py}", "tools/platform/unit_index.py"], ["{py}", "tools/platform/unit_index.py", "--check"]),
    ("test_map", "docs/platform/test_map.json",
     ["{py}", "tools/platform/test_map.py"], ["{py}", "tools/platform/test_map.py", "--check"]),
)
TAKE_NUMBER = ("train_number", None, ["{py}", "tools/platform/train_number.py", "assign", "--base", "{base}"],
               ["{py}", "tools/platform/train_number.py", "--check"])


def plan(py, base="origin/platform", take_number=False):
    """⇒ [(名稱, 產生檔, 寫入指令, 檢查指令 or None)]（已展開 {py}／{base}）。純函式。"""
    steps = ([TAKE_NUMBER] if take_number else []) + list(STEPS)
    out = []
    for name, rel, wcmd, ccmd in steps:
        def fill(cmd):
            return None if cmd is None else [a.format(py=py, base=base) if "{" in a else a for a in cmd]
        out.append((name, rel, fill(wcmd), fill(ccmd)))
    return out


def _read(path):
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def _run_cmd(cmd, repo, runner):
    r = runner(cmd, cwd=str(repo), capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, ((r.stdout or "") + (r.stderr or ""))[-1500:]


def run(repo=REPO, check_only=False, take_number=False, base="origin/platform", py=None, runner=None):
    """⇒ {"ok", "stale", "changed", "steps", "error"}。ok：--check＝全是最新；寫入＝全部成功。
    runner 供測試注入（簽名同 subprocess.run）。"""
    repo = Path(repo)
    py = py or sys.executable
    runner = runner or subprocess.run                 # 呼叫時才取（測試換得掉 subprocess.run）
    res = {"ok": True, "stale": [], "changed": [], "steps": [], "error": None}
    for name, rel, wcmd, ccmd in plan(py, base, take_number):
        step = {"name": name, "file": rel}
        res["steps"].append(step)
        target = repo / rel if rel else None
        if check_only:
            if ccmd is None:                                          # dep_graph：重產到暫存目錄再逐位元組比對
                with tempfile.TemporaryDirectory(prefix="regen_all_") as td:
                    tmp = os.path.join(td, "out.json")
                    rc, tail = _run_cmd(wcmd + ["--out", tmp], repo, runner)
                    step["rc"] = rc
                    if rc != 0:
                        res.update(ok=False, error="%s 產生器失敗（exit %d）：%s" % (name, rc, tail))
                        return res
                    stale = _read(tmp) != _read(target)
            else:
                rc, tail = _run_cmd(ccmd, repo, runner)
                step["rc"] = rc
                if rc not in (0, 1):
                    res.update(ok=False, error="%s 檢查失敗（exit %d）：%s" % (name, rc, tail))
                    return res
                stale = rc == 1
            step["stale"] = stale
            if stale:
                res["stale"].append(name)
                res["ok"] = False
        else:
            before = _read(target) if target else None
            rc, tail = _run_cmd(wcmd, repo, runner)
            step["rc"] = rc
            if rc != 0:
                res.update(ok=False, error="%s 失敗（exit %d）：%s" % (name, rc, tail))
                return res
            if target is not None and _read(target) != before:
                res["changed"].append(rel)
                step["changed"] = True
    return res


def _fix_hint(py):
    return "python tools/platform/regen_all.py   （或個別：dep_scan.py、unit_index.py、test_map.py）"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="只檢查，不寫檔；過期 ⇒ exit 1")
    ap.add_argument("--take-number", action="store_true", help="先跑 train_number assign（列車樹用）")
    ap.add_argument("--base", default="origin/platform")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--repo", default=str(REPO))
    a = ap.parse_args(argv)
    res = run(a.repo, a.check, a.take_number, a.base)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    elif res["error"]:
        print("regen_all 失敗：" + res["error"], file=sys.stderr)
    elif a.check:
        # 約定（train_preflight 讀這個）：stdout＝過期檔的路徑，一行一個；沒有過期 ⇒ stdout 空。說明一律走 stderr。
        files = {st["name"]: st["file"] for st in res["steps"]}
        for name in res["stale"]:
            print(files.get(name) or name)
        print(("過期的產生檔：%s ⇒ %s" % ("、".join(res["stale"]), _fix_hint(sys.executable))) if res["stale"]
              else "產生檔都是最新", file=sys.stderr)
    else:
        print("已重產；有改動：%s" % ("、".join(res["changed"]) or "（沒有）"))
    if res["error"]:
        return 2
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.exit(main())
