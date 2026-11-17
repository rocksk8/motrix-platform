# -*- coding: utf-8 -*-
"""作者交件前快檢（precheck）：一支指令、約 2 分鐘，把整合者最常抓到的紅燈在作者手上先抓出來。

[單位] tools:precheck   [層] 工具   [穩定度] 內部
[公開介面] classify_static, classify_failure, build_report, final_line, main
[不變式] 只編排既有工具、不重寫它們：靜態＝prepush_check（train_preflight 的 A1～A8、wip 不帶產生檔 P0、CHANGELOG C1、表單版號 F1）；
    守門測試＝tools/platform/precheck_sets.json 的檔清單（唯一一份）＋ preflight_guards.json 的便宜題組（precheck_sets 的 preflight_groups），
    合成**一次** pytest（跑法同 preflight_guards：MOTRIX_TRAIN、分支佔位模式、junit 題數下限、重型排隊）。只讀：不寫追蹤檔、不 commit、不 push。
    「沒拿到結果」「題數低於下限」「清單裡的檔沒跑到」一律是未能檢查，不當綠。最後一行 `PRECHECK PASS|FAIL|INCOMPLETE …` 可整行貼進交件訊息。
    **PRECHECK PASS ≠ 閘門綠**：只代表整合者最常退件的那幾類在你手上已清；完整守門仍由列車／author_gate／建包負責。

用法（repo 任一棵工作樹的根目錄；Python 用 .venv312）：
  python tools/platform/precheck.py                    靜態＋守門測試（預設 2 worker）；基準＝merge-base origin/platform
  python tools/platform/precheck.py --static-only      只跑靜態（秒級）
  python tools/platform/precheck.py --base <ref> --workers 1 --json-out <檔> --log <檔>
  python tools/platform/precheck.py --hook             給 git pre-push 用：FAIL ⇒ exit 1；PASS／INCOMPLETE ⇒ 0（INCOMPLETE 只警告）
輸出分兩類：
  「作者要修」：你的改動造成、你要在這個分支修掉的紅燈（附一行修法）。
  「收尾類（整合者處理）」：版號取號、產生檔重產等列車統一處理的項目；列出給你知道，**不擋交件**。
結束碼：0 PASS；1 FAIL；2 工具本身出錯；3 INCOMPLETE（沒跑完或排隊逾時＝不是綠）。
"""
import argparse
import importlib.util
import warnings
from concurrent.futures import ThreadPoolExecutor
import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SETS = HERE / "precheck_sets.json"
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
#: 靜態旗標裡屬於「整合者在列車上處理」的代號（DEV-RULES-TOKEN 第 7 條：manifest 日期、version_slots、changelog、FORM_VERSION 台帳、
#: UNIT-INDEX／test_map／dep_graph／A0 產生檔）。A1＝CHANGELOG 佔位格式、C1＝CHANGELOG 跟著程式、F1＝FORM_VERSION 台帳、A0＝產生檔過期；其餘是作者自己的改動造成的
CLOSING_CODES = {"A0", "A1", "C1", "F1"}
MAX_SHOW = 30                       # 每類最多印幾項（其餘用 --json-out 看）
DEFAULT_BUDGET_SEC = 180            # 牆鐘上限（目標 120 秒；多給一點避免冷機誤殺，仍算未完成）
sys.path.insert(0, str(HERE))
warnings.filterwarnings("ignore", category=SyntaxWarning)      # 被載入的舊工具檔有未跳脫的正規式字串，不要讓警告洗版


def _load(name):
    p = HERE / (name + ".py")
    spec = importlib.util.spec_from_file_location("_pc_" + name, str(p))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=_NOWIN)
    return r.stdout.strip() if r.returncode == 0 else ""


def pick_base(repo, head="HEAD"):
    """預設基準＝最近的整合線：origin/platform 與所有 train/* 分支（遠端、本機）中，與 HEAD 的 merge-base 離 HEAD 最近（領先提交數最少）者。
    分支從 train/tNN-int 開出來時，基準就是那條列車，而不是更舊的 origin/platform（否則整班列車的改動都算成你的）。⇒ (merge-base sha, 參照名)；找不到 ⇒ ('', '')。"""
    refs = ["origin/platform"] + [r for r in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/train", "refs/heads/train").splitlines() if r.strip()]
    best = ("", "", None)
    for r in refs:
        mb = _git(repo, "merge-base", head, r)
        if not mb:
            continue
        n = _git(repo, "rev-list", "--count", "%s..%s" % (mb, head))
        n = int(n) if n.isdigit() else None
        if n is not None and (best[2] is None or n < best[2]):
            best = (mb, r, n)
    return best[0], best[1]


def load_sets(path=SETS):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    seen = set()
    for f in d["files"]:
        if f["path"] in seen:
            raise ValueError("precheck_sets 檔重複：%s" % f["path"])
        seen.add(f["path"])
        if f.get("class", "author") not in ("author", "closing"):
            raise ValueError("class 只能是 author／closing：%s" % f["path"])
        if not f.get("why") or not f.get("fix"):
            raise ValueError("precheck_sets 條目缺 why／fix：%s" % f["path"])
    return d


# ── 純函式（有題）────────────────────────────────────────────────────────

def classify_static(finding):
    """靜態旗標 dict{code, where, msg, fix, unchecked} ⇒ 'closing'｜'author'。"""
    return "closing" if finding.get("code") in CLOSING_CODES else "author"


def classify_failure(nodeid, sets, file_group=None, closing_groups=()):
    """測試失敗題 ⇒ (類別, 修法, 來源描述)。先看 precheck_sets 的檔條目，再看 preflight_guards 題組（題組的 fix 是它自己登記的標準修法）。"""
    f = nodeid.split("::", 1)[0].replace("\\", "/")
    if f.startswith("backend/"):
        f = f[len("backend/"):]
    for e in sets["files"]:
        if e["path"] == f:
            return e.get("class", "author"), e["fix"], e["why"]
    gid = (file_group or {}).get(f)
    if gid:
        return ("closing" if gid in closing_groups else "author"), "", "題組 %s" % gid
    return "author", "", ""


def touches_code(changed):
    """變動檔裡有沒有會影響測試結果的東西（純文件的推送不必跑測試）。"""
    return any(re.search(r"\.(py|js|html|css|json|sql|ps1|bat)$", p) and not p.startswith("docs/") for p in changed)


def build_report(ctx):
    """ctx ⇒ 報告行清單。ctx 欄位：branch, head, base, dirty, secs, author[], closing[], unchecked[], warns[], static_n, tests{files,passed,failed,skipped}, status, log。
    author／closing 的每一項：{where, msg, fix, why}。"""
    L = ["══ PRECHECK  %s @ %s  基準 %s（%s）  %s ══" % (ctx["branch"], ctx["head"][:9], (ctx["base"] or "（無）")[:9], ctx.get("base_ref") or "?", "⚠ 工作樹未提交（結果不是這個 commit）" if ctx["dirty"] else "樹乾淨")]
    for w in ctx["warns"]:
        L.append("⚠ " + w)
    for x in ctx["unchecked"]:
        L.append("⚠ 未能檢查：%s" % x)

    def block(title, items):
        L.append("【%s】%d 項" % (title, len(items)))
        for i, x in enumerate(items[:MAX_SHOW], 1):
            L.append("  %d. %s" % (i, x["where"]))
            if x.get("msg"):
                L.append("     %s" % x["msg"][:220])
            if x.get("fix"):
                L.append("     修法：%s" % x["fix"])
        if len(items) > MAX_SHOW:
            L.append("  …另 %d 項（--json-out 看全部）" % (len(items) - MAX_SHOW))
    block("作者要修", ctx["author"])
    block("收尾類（整合者處理，不擋交件）", ctx["closing"])
    t = ctx["tests"]
    L.append("測試：%s；靜態 %d 項旗標；%.0f 秒；完整 log：%s" % (
        "未執行（--static-only／純文件）" if t is None else "%d 個守門檔，過 %d　紅 %d　略過 %d" % (t["files"], t["passed"], t["failed"], t["skipped"]),
        ctx["static_n"], ctx["secs"], ctx["log"] or "（無）"))
    L.append(final_line(ctx))
    return L


def final_line(ctx):
    """⇒ 最後一行（整行貼進交件訊息）。"""
    return "PRECHECK %s — 作者要修 %d／收尾類 %d／未能檢查 %d；%s；%.0f 秒；head=%s %s" % (
        ctx["status"], len(ctx["author"]), len(ctx["closing"]), len(ctx["unchecked"]),
        "測試未執行" if ctx["tests"] is None else "守門檔 %d 個 過 %d 紅 %d" % (ctx["tests"]["files"], ctx["tests"]["passed"], ctx["tests"]["failed"]),
        ctx["secs"], ctx["head"][:9], "dirty" if ctx["dirty"] else "clean")


def decide_status(author, unchecked, incomplete):
    """FAIL：有作者要修；INCOMPLETE：沒跑完／排隊逾時／有未能檢查（但沒有確定的紅）；PASS：都沒有。"""
    if author:
        return "FAIL"
    if incomplete or unchecked:
        return "INCOMPLETE"
    return "PASS"


# ── 執行 ──────────────────────────────────────────────────────────────

def static_stage(repo, base):
    """⇒ (flag dict 清單, 警告清單, 變動檔)。重用 prepush_check：A1～A8（train_preflight）、P0、C1（只對動到的模組）、F1。"""
    pp = _load("prepush_check")
    changed = pp.changed_files(repo, base)
    found = list(pp.static_findings(Path(repo), changed, base, False))
    found += pp.changelog_findings(Path(repo), pp.touched_modules(changed))
    found += pp.form_version_findings(Path(repo), changed)
    TP = pp.TP
    out = [dict(f.as_dict(), unchecked=isinstance(f, TP.Unchecked)) for f in found]
    warns = list(pp.warnings(changed))
    if not base:
        warns.append("找不到 origin/platform 的分叉點（先 git fetch）；沒有比較基準 ⇒ 靜態檢查幾乎沒有東西可看")
    return out, warns, changed


def test_stage(repo, sets, workers, window, budget_sec, log=None):
    """⇒ dict：targets, rc, out, secs, counts, fails, file_group, unchecked[], incomplete(bool)。"""
    pg = _load("preflight_guards")
    rts = _load("run_tests_summary")
    backend = Path(repo) / "backend"
    cfg = pg.load_config()
    wanted = list(sets.get("preflight_groups", []))
    tg, file_group, missing = pg.expand_groups(backend, cfg, only=set(wanted))
    targets, unchecked = [], []
    for e in sets["files"]:
        if (backend / e["path"]).is_file():
            targets.append(e["path"])
        else:
            unchecked.append("清單裡的檔不存在（改名或刪除？）：%s" % e["path"])
    for t in tg:
        if t not in targets:
            targets.append(t)
    for gid, pat, req in missing:
        if req:
            unchecked.append("題組 %s 找不到檔：%s" % (gid, pat))
    rc, out, secs, xml = pg.run_pytest(repo, targets, workers, window, budget_min=budget_sec / 60.0, tee=False, tb="line")
    counts, fails = rts.parse_junit_failures(xml, backend) if xml else (None, [])
    incomplete = rc in (pg.INCOMPLETE_RC, 75)
    if counts is None and not incomplete:
        unchecked.append("沒有拿到 junit 結果檔（pytest exit %s）：無法證明題有跑" % rc)
    ran = set()
    if xml:
        ran = _ran_files(xml, backend)
        gcount = pg.parse_junit(xml, file_group)
        floors = {g["id"]: g.get("min_tests", 0) for g in cfg["groups"]}
        bad, _skipped = pg.judge_counts(set(file_group.values()), gcount, floors)
        unchecked += list(bad)
        for e in sets["files"]:
            if (backend / e["path"]).is_file() and e["path"] not in ran and not incomplete:
                unchecked.append("守門檔沒有任何題被收集到（全被略過或收集失敗）：%s" % e["path"])
    return {"targets": targets, "rc": rc, "out": out, "secs": secs, "counts": counts, "fails": fails, "file_group": file_group,
            "unchecked": unchecked, "incomplete": incomplete, "cfg": cfg}


def _ran_files(xml_text, backend):
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return set()
    seen = set()
    for tc in root.iter("testcase"):
        parts = (tc.get("classname") or "").split(".")
        for k in range(len(parts), 0, -1):
            rel = "/".join(parts[:k]) + ".py"
            if (Path(backend) / rel).is_file():
                seen.add(rel)
                break
    return seen


def run(repo=REPO, base=None, static_only=False, workers=2, window="precheck", budget_sec=DEFAULT_BUDGET_SEC, hook=False, log=None, sets=None):
    """⇒ (exit_code, 報告行, ctx)。"""
    t0 = time.time()
    repo = Path(repo)
    sets = sets or load_sets()
    base_ref = ""
    if base is None:
        base, base_ref = pick_base(repo)
    else:
        base_ref = base
        base = _git(repo, "rev-parse", "--verify", "-q", base + "^{commit}") or base
    head = _git(repo, "rev-parse", "HEAD") or "?" * 9
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "detached"
    dirty = bool(_git(repo, "status", "--porcelain", "--untracked-files=normal"))
    with ThreadPoolExecutor(max_workers=1) as ex:                  # 靜態（約 45 秒、純 CPU／git）與測試子行程並行，總時間取兩者較長者
        fut = ex.submit(static_stage, repo, base)
        r = None
        early = _git(repo, "diff", "--name-only", "%s...HEAD" % base).splitlines() if (hook and base) else None
        if not static_only and not (early is not None and not touches_code(early)):     # hook：純文件的推送不跑測試
            try:
                r = test_stage(repo, sets, workers, window, budget_sec, log)
            except Exception as e:                                 # noqa: BLE001  測試段本身出錯也要等靜態結束再回報
                r = {"error": e}
        flags, warns, changed = fut.result()
    if r is not None and "error" in r:
        raise r["error"]
    author, closing, unchecked = [], [], []
    for f in flags:
        if f.get("unchecked"):
            unchecked.append("%s %s" % (f["code"], f["msg"]))
            continue
        item = {"where": "[%s] %s" % (f["code"], f["where"]), "msg": f["msg"], "fix": f["fix"]}
        (closing if classify_static(f) == "closing" else author).append(item)
    tests, log_path, incomplete = None, None, False
    if r is not None:
        unchecked += r["unchecked"]
        incomplete = r["incomplete"]
        log_path = _write_log(r["out"], branch, t0, log)
        cg = set(sets.get("closing_groups", []))
        for f in r["fails"]:
            cls, fix, why = classify_failure(f["nodeid"], sets, r["file_group"], cg)
            if not fix:
                gid = r["file_group"].get(f["nodeid"].split("::", 1)[0])
                for g in r["cfg"]["groups"]:
                    if g["id"] == gid:
                        fix = g.get("fix", "")
            item = {"where": "[測試] %s" % f["nodeid"], "msg": ("%s　%s" % (why, f["message"])).strip("　 ") if why else f["message"], "fix": fix}
            (closing if cls == "closing" else author).append(item)
        c = r["counts"] or {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
        tests = {"files": len(r["targets"]), "passed": c["passed"], "failed": c["failed"] + c["error"], "skipped": c["skipped"]}
        if r["rc"] == 75:
            warns.append("排隊逾時：有人持有全機閘門鎖，測試沒有跑；等放鎖後重跑（INCOMPLETE 不是綠）")
        elif r["incomplete"]:
            warns.append("超過 %d 秒預算被停掉：不是綠；把機器上的其他重型工作停掉再重跑，或加 --workers 1 看是哪一檔拖慢" % budget_sec)
        if r["rc"] not in (0, 1, None) and not r["incomplete"] and not r["fails"] and r["counts"] is not None and not unchecked:
            unchecked.append("pytest exit %s 但沒有任何失敗題：看完整 log" % r["rc"])
    status = decide_status(author, unchecked, incomplete)
    ctx = {"branch": branch, "head": head, "base": base, "dirty": dirty, "secs": time.time() - t0, "author": author, "closing": closing,
           "unchecked": unchecked, "warns": warns, "base_ref": base_ref, "static_n": len(flags), "tests": tests, "status": status, "log": log_path}
    code = {"PASS": 0, "FAIL": 1, "INCOMPLETE": 3}[status]
    return code, build_report(ctx), ctx


def _write_log(out, branch, t0, log):
    import tempfile
    p = Path(log) if log else Path(tempfile.gettempdir()) / ("precheck_%s_%d.log" % (re.sub(r"[^\w.-]", "_", branch), int(t0)))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out or "", encoding="utf-8")
        return str(p)
    except OSError:
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="作者交件前快檢（約 2 分鐘）", formatter_class=argparse.RawDescriptionHelpFormatter, epilog="結束碼：0 PASS；1 FAIL；2 工具出錯；3 INCOMPLETE")
    ap.add_argument("--base")
    ap.add_argument("--static-only", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--window", default="precheck")
    ap.add_argument("--budget-sec", type=int, default=DEFAULT_BUDGET_SEC)
    ap.add_argument("--hook", action="store_true", help="git pre-push：FAIL ⇒ 1；PASS／INCOMPLETE ⇒ 0（INCOMPLETE 只警告）")
    ap.add_argument("--json-out")
    ap.add_argument("--log")
    ap.add_argument("--repo", default=str(REPO))
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    try:
        code, lines, ctx = run(a.repo, a.base, a.static_only, a.workers, a.window, a.budget_sec, a.hook, a.log)
    except Exception as e:                                                   # noqa: BLE001
        print("precheck 本身出錯：%s" % e, file=sys.stderr)
        return 2
    print("\n".join(lines))
    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json_out).write_text(json.dumps(ctx, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if a.hook:
        if ctx["status"] == "INCOMPLETE":
            print("[precheck] 未完成：放行這次推送，但交件訊息不能附 PRECHECK PASS（補跑 precheck）", file=sys.stderr)
        return 1 if ctx["status"] == "FAIL" else 0
    return code


if __name__ == "__main__":
    sys.exit(main())
