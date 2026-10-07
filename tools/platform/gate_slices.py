# -*- coding: utf-8 -*-
"""全閘門切片（第 45 班 O1）：slice0＝靜態／掃描／產生檔守門先跑，綠了才開其餘。清單單一來源 tools/platform/gate_slices.json。

[單位] tools:gate_slices          [層] 工具          [穩定度] 內部
[不變式] slice0 ∪ rest ＝ 全部（非 e2e）題的 nodeid 集合，不增不減；slice0 的檔在 rest 一律 --ignore／--deselect；
         讀不到或讀不懂清單 ⇒ 回傳 None（呼叫端走舊行為＝單一段全跑，不是跳過守門）
[用法] modtest.run_full（全閘門）與 pre_train_check（GUARDS）讀同一份；`python tools/platform/gate_slices.py --check` 驗集合
"""
import glob
import hashlib
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BACKEND = REPO / "backend"
SLICES_FILE = HERE / "gate_slices.json"
OFF_ENV = "MOTRIX_GATE_SLICES"          # 0 ⇒ 關閉切片（回到單一段全跑）


def enabled():
    return os.environ.get(OFF_ENV, "").strip().lower() not in ("0", "false", "no", "off")


def load(path=None):
    """⇒ dict（含 slice0.paths／failfast）；讀不到、格式不對 ⇒ None。"""
    try:
        data = json.loads(Path(path or SLICES_FILE).read_text(encoding="utf-8"))
        paths = data["slice0"]["paths"]
        if not isinstance(paths, list) or not paths or not all(isinstance(p.get("path"), str) and p.get("label") for p in paths):
            return None
        return data
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def guards(data=None):
    """pre_train_check 的 GUARDS：slice0 去掉整個 tests/platform（那一項它另外全跑）⇒ [(label, path)]。"""
    data = data or load()
    if not data:
        return []
    return [(p["label"], p["path"]) for p in data["slice0"]["paths"] if p["path"].rstrip("/") != "tests/platform"]


def expand(data=None, backend=None):
    """slice0 的路徑展開 ⇒ (targets 相對 backend/ 的清單, missing 標籤清單)。glob 在 backend/ 底下展開；找不到 ⇒ 列 missing（守門被改名也要看得見）。
    目錄原樣保留；`檔::nodeid` 原樣保留（pytest 認得）。"""
    data = data or load()
    backend = Path(backend or BACKEND)
    targets, missing = [], []
    if not data:
        return targets, ["gate_slices.json 讀不到"]
    for p in data["slice0"]["paths"]:
        file_pat, _, node = p["path"].partition("::")
        hits = sorted(Path(h).relative_to(backend).as_posix() for h in glob.glob(str(backend / file_pat)))
        if not hits:
            missing.append("%s（%s）" % (p["label"], p["path"]))
            continue
        targets += [h + ("::" + node if node else "") for h in hits]
    return list(dict.fromkeys(targets)), missing


def rest_args(targets):
    """第二片要排除 slice0 的東西：檔／目錄 ⇒ --ignore=，帶 ::nodeid 的 ⇒ --deselect=（整檔不能 ignore，其餘題仍要在第二片跑）。"""
    out = []
    for t in targets:
        out.append("--deselect=" + t if "::" in t else "--ignore=" + t)
    return out


def nodeid_sha(ids):
    return hashlib.sha256("\n".join(sorted(set(ids))).encode("utf-8")).hexdigest()


def judge_sets(all_ids, slice0_ids, rest_ids):
    """集合驗證（純函式）⇒ (ok, 原因清單)：slice0 ∪ rest 要等於全部、兩片不重疊。"""
    a, s, r = set(all_ids), set(slice0_ids), set(rest_ids)
    why = []
    if s | r != a:
        why.append("slice0∪rest 與全部不同：漏 %d 題、多 %d 題" % (len(a - (s | r)), len((s | r) - a)))
    if s & r:
        why.append("兩片重疊 %d 題" % len(s & r))
    if not s:
        why.append("slice0 沒有收集到任何題")
    return (not why), why


def judge_counts(collected, executed):
    """全綠 run：執行題數（passed+failed+errors+skipped+xfailed…）必須等於收集題數。⇒ (ok, 原因)。"""
    if collected is None or executed is None:
        return False, "拿不到題數（收集 %r／執行 %r）" % (collected, executed)
    return (collected == executed), ("" if collected == executed else "收集 %d 題、執行 %d 題" % (collected, executed))


def measure(workers):
    """--measure：只跑 slice0（量測用；**不**寫 full_results、不寫建包沿用紀錄，所以不會被當成這個 commit 的全量結果）。
    -n workers（共用機器 2）、worksteal、failfast 關（要量完整耗時）；印牆鐘時間與最慢 25 題。回 pytest 的 exit code。"""
    import time
    sys.path.insert(0, str(HERE))
    import modtest as MT
    data = load()
    targets, missing = expand(data) if data else ([], ["gate_slices.json 讀不到"])
    if missing:
        print("[gate_slices] slice0 找不到：" + "；".join(missing))
        return 1
    args = ["-m", "not e2e", "-n", str(workers)] + MT.dist_args() + ["-q", "-rfE", "--tb=short", "--durations=25"]
    t0 = time.time()
    code, out = MT.run_pytest(targets, MT.cap_workers(args, MT.full_max_workers()), "gsm", full=True,
                              env_extra={"MOTRIX_TRAIN": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    dt = time.time() - t0
    print("[gate_slices] slice0 量測：%d 個目標、-n %d、牆鐘 %.1f 秒（%.1f 分）、exit %s；%s" % (
        len(targets), workers, dt, dt / 60.0, code, (out.strip().splitlines() or ["?"])[-1]))
    return code


def collect_ids(collect, targets, extra=()):
    """collect(targets, extra) ⇒ (exit code, 輸出)（collect-only）。⇒ (code, nodeid 清單)。"""
    code, out = collect(list(targets), ["-m", "not e2e", *extra])
    return code, [ln.strip() for ln in (out or "").splitlines() if "::" in ln and not ln.startswith(("=", " ", "FAILED", "ERROR"))]


def expected(collect, roots, targets):
    """開跑前的切片驗證（全閘門用；只收集不執行）：收集「全部非 e2e」與「slice0」兩次，其餘＝全部 − slice0（第二片用 --ignore／--deselect 排除，
    跑完後以執行題數對帳）。⇒ {ok, why[], all, slice0, rest, sha}。收集失敗、slice0 空、slice0 不是全部的子集 ⇒ ok=False（呼叫端退回一段全跑）。"""
    c1, all_ids = collect_ids(collect, roots)
    c2, s_ids = collect_ids(collect, targets)
    a, s = set(all_ids), set(s_ids)
    why = []
    if c1 != 0 or c2 != 0:
        why.append("collect-only 失敗（exit %s／%s）" % (c1, c2))
    if not s:
        why.append("slice0 沒有收集到任何題")
    if not a:
        why.append("全部沒有收集到任何題")
    if s - a:
        why.append("slice0 有 %d 題不在全部裡" % len(s - a))
    return {"ok": not why, "why": why, "all": len(a), "slice0": len(s), "rest": len(a - s), "sha": nodeid_sha(all_ids)[:16]}


def main(argv=None):
    """--check：用 modtest 的 collect-only 比三份 nodeid 集合（全部／slice0／rest）。只收集不執行，輕量。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--measure" in argv:
        w = int(argv[argv.index("--workers") + 1]) if "--workers" in argv else 2
        return measure(w)
    sys.path.insert(0, str(HERE))
    import modtest as MT
    data = load()
    if not data:
        print("[gate_slices] gate_slices.json 讀不到或格式不對")
        return 1
    targets, missing = expand(data)
    if missing:
        print("[gate_slices] slice0 找不到：" + "；".join(missing))
        return 1

    def ids(tg, extra):
        code, out = MT.run_pytest(tg, extra, "gsck", full=False, collect_only=True)
        got = [ln.strip() for ln in out.splitlines() if "::" in ln and not ln.startswith(("=", " ", "FAILED"))]
        return code, got
    c1, all_ids = ids(MT.TEST_ROOTS, ["-m", "not e2e"])
    c2, s_ids = ids(targets, ["-m", "not e2e"])
    c3, r_ids = ids(MT.TEST_ROOTS, ["-m", "not e2e"] + rest_args(targets))
    if any(c not in (0,) for c in (c1, c2, c3)):
        print("[gate_slices] collect-only 失敗 exit=%s／%s／%s" % (c1, c2, c3))
        return 1
    ok, why = judge_sets(all_ids, s_ids, r_ids)
    print("[gate_slices] 全部 %d 題（sha %s）；slice0 %d；rest %d" % (len(set(all_ids)), nodeid_sha(all_ids)[:12], len(set(s_ids)), len(set(r_ids))))
    for w in why:
        print("[gate_slices] ✗ " + w)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
