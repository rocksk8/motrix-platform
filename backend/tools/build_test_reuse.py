"""建包：同一份 tree 已全綠就沿用測試結果（PLAN-TEST-PERF §3.1）。由 build_deploy_package.ps1 呼叫。

用法：
  python build_test_reuse.py fingerprint                         → {"fingerprint": "...", "components": {...}}（工作樹不乾淨 ⇒ fingerprint 為 null）
  python build_test_reuse.py lookup --records F --fp X           → 可沿用的那一筆（JSON），或 null
  python build_test_reuse.py record --records F --fp X --green 1 --commit C

🔑 指紋＝整棵 tracked tree（`HEAD^{tree}`；2026-09-30 起改算 `ls-tree -r HEAD` 扣掉 REUSE_EXCLUDE）＋執行環境。文件不排除：測試會讀 docs/（見
   tests/test_build_test_reuse_2026_09_25.py 的說明）。
🔑 沿用條件：同指紋、**嚴格全綠**（兩段 exit 0，逾時放行不算）、12 小時內（不再要求同一個日曆日：跨午夜照樣沿用，使用者 2026-10-13 書面裁示；
   把關靠整棵 tree 的指紋＋12 小時新鮮度，時間相依的題由 `test_no_import_time_clock_2026_10_09` 這類守門處理）；
   同指紋的最新一筆若是紅的，不沿用更早的綠。

## 分段沿用（2026-09-30，建包優化「避免非正常情況的失敗」；正反論證見 PLAYBOOK §D-建包）
  python build_test_reuse.py records-path                                   → 主工作樹的紀錄檔（建包與 modtest 共用）
  python build_test_reuse.py run-stage --stage not_e2e|e2e                  → 獨立跑一段（同建包指令）並記錄（source=standalone）：建包同指紋時直接沿用
  python build_test_reuse.py explain [--last N] [--json]                    → 唯讀診斷：這一段為什麼沒被沿用、最近每筆紀錄為何與現在的指紋不同（tree 差在哪幾個檔／環境哪個元件）
  python build_test_reuse.py lookup-stage --fp X --stage not_e2e|e2e        → 可沿用的那一段（JSON），或 null
  python build_test_reuse.py record-stage --fp X --stage S --green 1 [--flaky-from R] [--reused-at T] [--flaky ID…]
- 每一行可帶 `stages: {not_e2e|e2e: {green, tested_at, flaky_retried[]}}`；舊格式（沒有 stages）的一行＝兩段同一個結果。
- 一段的判定＝同指紋、**帶有這一段**的最新一筆（沒帶這一段的行跳過：例如只跑完非 e2e 就中斷的那一行不影響 e2e）；
  該段綠、12 小時內（可跨午夜）——以**該段原本實跑的時間**算（沿用後再記錄時帶原時間，窗口不會被一路延長）。
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
               "MOTRIX_PYTEST_BUILD_CHILD", "MOTRIX_PYTEST_BUILD_GUARD",
               # 2026-11-13（T83／T84：T82 打包沒沿用 run-stage 的結果、多花約 45 分鐘）：heavy_run／整合者的排隊與鎖插件會在子行程環境塞
               # **每輪都不同**的值——MOTRIX_CI_TICKET（票根檔路徑，每次排隊一個新的）、MOTRIX_GATE_TOKEN（每把閘門鎖一個）、
               # MOTRIX_WINDOW（誰在跑）、MOTRIX_CI_DIR／MOTRIX_REQUIRE_QUEUE／MOTRIX_QUEUE_GUARD（排隊機制）。
               # 它們只決定「排不排隊、拿不拿得到鎖」，不決定哪些題存在或過不過；進指紋 ⇒ 經 heavy_run 跑的 run-stage 與直接跑的建包永遠對不上。
               "MOTRIX_CI_TICKET", "MOTRIX_GATE_TOKEN", "MOTRIX_WINDOW", "MOTRIX_CI_DIR", "MOTRIX_REQUIRE_QUEUE", "MOTRIX_QUEUE_GUARD",
               # 2026-10-02（建包優化 2 項 1）：fail-fast／failure-first 只決定「何時停、先跑誰」，不決定哪些題存在或過不過（停止＝該段記紅）
               "MOTRIX_FAILFAST", "MOTRIX_FAILFAST_N", "MOTRIX_FAILFAST_QUIET_MIN", "MOTRIX_FAILFAST_FLAKES",
               "MOTRIX_FAILFIRST", "MOTRIX_FAILFIRST_BASE", "MOTRIX_FAILFIRST_HISTORY", "MOTRIX_FAILFIRST_RECORDS",
               # 2026-10-07（第 45 班全閘門優化 O1／O2／O4／O6）：只決定「用幾個 worker、先跑誰、要不要先對帳題數／重疊兩段／出紅後單獨重跑診斷」，
               # 不決定哪些題存在、過或不過（切片聯集＝全部題由 gate_slices 的 collect-only 與題數對帳證明；偶發放行規則不變）⇒ 不進指紋，
               # 否則「共用機器設 MOTRIX_GATE_WORKERS=2 跑全閘門」寫下的紀錄，換一個沒設的 shell 建包就對不上、整套重跑。
               # ⚠ MOTRIX_TRAIN 不在這裡：它決定「只在列車跑」的守門題是跑還是 skip（結果不同）。
               "MOTRIX_GATE_WORKERS", "MOTRIX_GATE_DIST", "MOTRIX_GATE_LPT", "MOTRIX_GATE_RECORD", "MOTRIX_GATE_VERIFY", "MOTRIX_GATE_SLICES",
               "MOTRIX_FULL_OVERLAP", "MOTRIX_FULL_OVERLAP_MIN_GB", "MOTRIX_FULL_FLAKY_RETRY"}
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


def reuse_blockers(python=None, env=None):
    """這個行程算出的指紋裡，有哪些「換個環境建包就對不上」的成分（只列名字，不列值）。run-stage 結束時印出來。
    ① 進指紋的 MOTRIX_* 環境變數（_ENV_IGNORE 以外；例如 MOTRIX_TRAIN、MOTRIX_PROJECT_VENV）② PYTEST_ADDOPTS
    ③ 算指紋的直譯器（sys.executable）不是跑測試的那支（pip freeze 會是別的環境的）。"""
    env = dict(os.environ) if env is None else env
    out = []
    names = sorted(k for k in env if k.startswith("MOTRIX_") and k not in _ENV_IGNORE)
    if names:
        out.append("進指紋的環境變數：%s（建包 shell 沒設成一樣的值就不會沿用）" % "、".join(names))
    if env.get("PYTEST_ADDOPTS") is not None:
        out.append("PYTEST_ADDOPTS 有設（進指紋）")
    if python and os.path.normcase(os.path.abspath(str(python))) != os.path.normcase(os.path.abspath(sys.executable)):
        out.append("算指紋的直譯器（%s）不是跑測試的（%s）⇒ pip freeze 來自不同環境" % (sys.executable, python))
    return out


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


def _tree_listing(repo, rev="HEAD"):
    """{路徑: 'mode type sha'}（扣掉 REUSE_EXCLUDE）；rev 解不開 ⇒ None。"""
    try:
        out = _git(repo, "ls-tree", "-r", rev)
    except (subprocess.CalledProcessError, OSError):
        return None
    d = {}
    for ln in out.splitlines():
        meta, _, path = ln.partition("\t")
        if path not in REUSE_EXCLUDE:
            d[path] = meta
    return d


def components(repo, env=None):
    """指紋的組成（診斷用）：{"tree": sha256, "env": {元件名: 該元件內容 sha256 前 12 碼}}；工作樹不乾淨 ⇒ None。
    與 `fingerprint()` 同一份輸入（tree＋env），所以「哪個元件不同」就等於「為什麼指紋不同」。"""
    if _git(repo, "status", "--porcelain").strip():
        return None
    listing = [ln for ln in _git(repo, "ls-tree", "-r", "HEAD").splitlines() if ln.split("\t", 1)[-1] not in REUSE_EXCLUDE]
    env = current_env() if env is None else env
    return {"tree": hashlib.sha256("\n".join(listing).encode("utf-8")).hexdigest(),
            "env": {k: hashlib.sha256(json.dumps(v, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
                    for k, v in sorted(env.items())}}


def parts_path(records):
    return Path(records).with_name("fp_parts.jsonl")


def remember_parts(records, fp, comps):
    """每次算指紋就記一行「指紋 → 組成」（去重；只存元件雜湊，不含任何環境變數的值）——事後 `explain` 才答得出『環境哪一項不同』。"""
    try:
        p = parts_path(records)
        if p.exists() and any(('"%s"' % fp) in ln for ln in p.read_text(encoding="utf-8").splitlines()[-200:]):
            return
        _append(p, {"fingerprint": fp, "t": datetime.now().strftime(TS_FMT), "parts": comps})
    except OSError:
        pass


def _parts_for(records, fp):
    p = parts_path(records)
    if not p.exists():
        return None
    got = None
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("fingerprint") == fp:
            got = r.get("parts")
    return got


def _stage_verdict(records_list, fp, stage, now):
    """這一段現在能不能沿用？⇒ (能否, 原因)。與 `find_reusable_stage` 同一套規則，只是把「為什麼不行」說出來。"""
    same = [r for r in records_list if r.get("fingerprint") == fp]
    if not same:
        return False, "沒有任何同指紋的紀錄"
    for r in reversed(same):
        stages = r.get("stages")
        if isinstance(stages, dict):
            if stage not in stages:
                continue
            s_ = stages.get(stage)
            entry = dict(s_) if isinstance(s_, dict) else {}
        else:
            entry = {"green": r.get("green"), "tested_at": r.get("tested_at")}
        if entry.get("green") is not True:
            return False, "同指紋帶這一段的最新一筆是紅的（%s，來源 %s）" % (entry.get("tested_at") or r.get("tested_at"), r.get("source") or "build")
        if not _stage_ok(entry, now, MAX_HOURS):
            return False, "同指紋的綠已過期（需 %d 小時內；實跑於 %s）" % (MAX_HOURS, entry.get("tested_at"))
        return True, "可沿用（%s 實跑於 %s，來源 %s）" % (r.get("commit"), entry["tested_at"], r.get("source") or "build")
    return False, "同指紋的紀錄都沒有帶這一段"


def explain(records, repo, env=None, now=None, last=12):
    """為什麼某段沒被沿用／為什麼同一份東西跑了兩次（建包優化 2 項 2 的診斷；純讀）。
    回 dict：dirty、fingerprint、components、stages{段:{reuse,reason}}、rows[最近 `last` 筆紀錄各自的比對]。
    每一筆紀錄：fp_match；不同時——① 該紀錄 commit 的 tree vs 現在（相同 ⇒ 差在環境；不同 ⇒ 列出不同的檔）
    ② 有 fp_parts 旁表時列出環境哪些元件不同。"""
    now = now or datetime.now()
    recs = _read(records)
    dirty = [ln for ln in _git(repo, "status", "--porcelain").splitlines() if ln.strip()]
    env_ = current_env() if env is None else env
    comps = None if dirty else components(repo, env_)
    fp = None if dirty else fingerprint(repo, env_)
    cur_listing = _tree_listing(repo, "HEAD") or {}
    out = {"dirty": dirty[:20], "fingerprint": fp, "components": comps, "stages": {}, "rows": []}
    for st in STAGES:
        if not fp:
            out["stages"][st] = {"reuse": False, "reason": "工作樹不乾淨 ⇒ 沒有指紋、不沿用（含未追蹤檔）"}
        else:
            ok, why = _stage_verdict(recs, fp, st, now)
            out["stages"][st] = {"reuse": ok, "reason": why}
    for r in recs[-last:]:
        row = {"tested_at": r.get("tested_at"), "source": r.get("source") or "build", "commit": r.get("commit"),
               "stages": {k: ("綠" if (v or {}).get("green") else "紅") for k, v in (r.get("stages") or {}).items()}
               or {"(舊格式)": "綠" if r.get("green") else "紅"},
               "fp_match": bool(fp) and r.get("fingerprint") == fp}
        if fp and not row["fp_match"]:
            old = _tree_listing(repo, str(r.get("commit") or "")) if r.get("commit") else None
            if old is None:
                row["why"] = "紀錄的 commit %s 不在這個 repo ⇒ 無法比對 tree" % r.get("commit")
            else:
                changed = sorted(k for k in set(old) | set(cur_listing) if old.get(k) != cur_listing.get(k))
                if changed:
                    row["why"] = "tree 不同：%d 個檔不同（前 8：%s）" % (len(changed), "、".join(changed[:8]))
                    row["changed_files"] = len(changed)
                else:
                    row["why"] = "tree 相同 ⇒ 差在執行環境"
                    parts = _parts_for(records, r.get("fingerprint"))
                    if parts and comps:
                        diff = sorted(k for k in set(parts.get("env", {})) | set(comps["env"]) if parts.get("env", {}).get(k) != comps["env"].get(k))
                        row["env_diff"] = diff
                        row["why"] += "：不同的元件 %s" % ("、".join(diff) or "（旁表看不出）")
                    else:
                        row["why"] += "（該指紋沒有旁表記錄，無法指出是哪一項；之後算過的指紋都會有）"
        out["rows"].append(row)
    return out


def render_explain(res):
    L = []
    if res["dirty"]:
        L.append("工作樹不乾淨（含未追蹤檔）⇒ 沒有指紋、所有段都不沿用：")
        L += ["  " + x for x in res["dirty"]]
    else:
        L.append("目前指紋 %s…" % (res["fingerprint"] or "")[:16])
    for st, v in res["stages"].items():
        L.append("[%s] %s：%s" % (st, "可沿用" if v["reuse"] else "不沿用", v["reason"]))
    L.append("最近 %d 筆紀錄（舊→新）：" % len(res["rows"]))
    for r in res["rows"]:
        L.append("  %s  %-14s %-9s %s  %s%s" % (r["tested_at"], r["source"], r["commit"], r["stages"],
                                              "指紋相同" if r["fp_match"] else "指紋不同", ("  ← " + r["why"]) if r.get("why") else ""))
    return "\n".join(L)


#: 建包一段的 pytest 指令（與 build_deploy_package.ps1 同一組；tests/test_build_stage_reuse_2026_10_02.py 逐項對照腳本文字，防漂移）
STAGE_PYTEST = {"not_e2e": ["-q", "-m", "not e2e", "--durations=20"],
                "e2e": ["-q", "-rf", "-m", "e2e", "--durations=20"]}


def default_workers(stage):
    """建包的 worker 數：非 e2e＝max(2, min(實體核心, 4))；e2e 固定 4（build_deploy_package.ps1 :659／:898）。"""
    if stage == "e2e":
        return 4
    try:
        import psutil
        phys = psutil.cpu_count(logical=False) or 2
    except Exception:  # noqa: BLE001 — 沒有 psutil：用邏輯核心的一半估
        phys = max(2, (os.cpu_count() or 4) // 2)
    return max(2, min(int(phys), 4))


def stage_command(stage, python, workers, basetemp):
    return [str(python), "-m", "pytest", *STAGE_PYTEST[stage], "-n", str(workers), "--basetemp=%s" % basetemp,
            "-p", "fail_stream", "-p", "failfast", "-p", "no:cacheprovider"]


def collect_reds(fail_stream_dir, limit=500):
    """讀 fail_stream 的 JSONL（只讀 type=fail／node_down），回不重複的紅題 nodeid 清單（依出現順序）。"""
    out, seen = [], set()
    d = Path(fail_stream_dir)
    for f in sorted(d.glob("*.jsonl")) if d.is_dir() else []:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for ln in lines:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            nid = r.get("nodeid")
            if r.get("type") in ("fail", "node_down") and nid and nid not in seen:
                seen.add(nid)
                out.append(nid)
                if len(out) >= limit:
                    return out
    return out


#: run-stage 一段跑完後，紅的題數 ≤ 這個數就自動在安靜環境單獨重跑一次（0＝關）。**不是 flake 登記**：known_flakes 不動，
#: 每次重試都留證據（紀錄的 stages.<段>.retry＋retry_log.jsonl），同一題累計次數給雜訊排行榜用。
RETRY_MAX_DEFAULT = 5
RETRY_LOG_NAME = "retry_log.jsonl"


def retry_log_path(records):
    return Path(records).with_name(RETRY_LOG_NAME)


def stream_status(fail_stream_dir):
    """讀 fail_stream 目錄 ⇒ {"reds": [nodeid…（依出現順序、不重複）], "info": {nodeid: {type, when, summary}}, "summary": 最後一筆 type=summary 或 None}。
    只讀 type=fail／node_down（aborted 不算紅）。"""
    reds, info, summary = [], {}, None
    d = Path(fail_stream_dir)
    for f in sorted(d.glob("*.jsonl")) if d.is_dir() else []:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for ln in lines:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("type") == "summary":
                summary = r
            elif r.get("type") in ("fail", "node_down") and r.get("nodeid") and r["nodeid"] not in info:
                info[r["nodeid"]] = {"type": r.get("type"), "when": r.get("when"), "summary": str(r.get("summary") or "")[:300]}
                reds.append(r["nodeid"])
    return {"reds": reds, "info": info, "summary": summary}


def retry_eligibility(rc, st, limit):
    """這一段紅了，能不能只重試紅的題？⇒ (可, 原因)。純函式。
    鐵則：**只有「這一輪確定跑完了、紅的就是這幾題」才准重試**——否則沒跑到的題會被當成過了：
    - rc 必須是 1（pytest 的 TESTS_FAILED）；2（中斷）、3（內部錯誤）、4（用法）、5（沒題）都不是「跑完但有紅」。
    - fail_stream 的 summary 必須在，且不是 aborted／failfast 提早停（停了＝後面的題沒跑）。
    - 紅清單不能比 summary 的 failed＋errors 少（少了＝有紅沒被抓到）、不能有 collect 階段的紅（檔案載入失敗＝那檔的題根本沒跑）。
    - 紅題數 ≤ limit；nodeid 都得是 路徑::題名。"""
    if limit <= 0:
        return False, "重試關閉（--no-retry）"
    if rc != 1:
        return False, "exit code=%s 不是「跑完但有紅」(1)" % rc
    summ = (st or {}).get("summary")
    if not summ:
        return False, "沒有 fail_stream summary，無法確認這輪跑完"
    reds = (st or {}).get("reds") or []
    if len(reds) > limit:
        return False, "紅 %d 題 > %d 題上限：不重試（這不是雜訊，是真的問題）" % (len(reds), limit)
    if summ.get("aborted") or summ.get("aborted_by"):
        return False, "這輪被中斷／提早停止（%s）：沒跑到的題不能靠重試補" % (summ.get("aborted_by") or "aborted")
    if not reds:
        return False, "沒抓到任何紅題（紅清單是空的）"
    if len(reds) < int(summ.get("failed", 0)) + int(summ.get("errors", 0)):
        return False, "紅清單（%d）比 summary 的失敗＋錯誤（%d）少，有紅沒被抓到" % (len(reds), int(summ.get("failed", 0)) + int(summ.get("errors", 0)))
    if any((st["info"].get(n) or {}).get("when") == "collect" for n in reds):
        return False, "有 collect 階段的紅（檔案載入失敗，那檔的題根本沒跑）"
    if any("::" not in n for n in reds):
        return False, "紅清單裡有不是 路徑::題名 的項目"
    return True, ""


def retry_command(stage, python, nodeids, basetemp):
    """只重跑紅的題：同一個段的標記（-m）、單程序（-n 0）、fail_stream 照載（留明細）、不載 failfast。"""
    args = [a for a in STAGE_PYTEST[stage] if not a.startswith("--durations")]
    return [str(python), "-m", "pytest", *args, *nodeids, "-n", "0", "--basetemp=%s" % basetemp, "-p", "fail_stream", "-p", "no:cacheprovider"]


def append_retry_log(records, stage, commit, fp, rows):
    """每次重試都留證據：每題一行（時間、段、commit、指紋、題、原始紅的摘要、重試結果）。累計次數從這裡算（retry_counts）。"""
    try:
        t = datetime.now().strftime(TS_FMT)
        for r in rows:
            _append(retry_log_path(records), {"t": t, "stage": stage, "commit": commit, "fingerprint": fp, "kind": "retry_failed", **r})
    except OSError:
        pass


def retry_counts(records):
    """retry_log.jsonl ⇒ {nodeid: {"retries": 次數, "passed": 重試過的次數, "failed": 重試仍紅的次數, "last": 最後一次時間}}（雜訊排行榜的來源）。"""
    out = {}
    p = retry_log_path(records)
    if not p.exists():
        return out
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        n = r.get("nodeid")
        if not n:
            continue
        e = out.setdefault(n, {"retries": 0, "passed": 0, "failed": 0, "last": ""})
        e["retries"] += 1
        e["passed" if r.get("result") == "pass" else "failed"] += 1
        e["last"] = r.get("t") or e["last"]
    return out


def gate_hold(repo, stage, note=print, hr=None, window=None):
    """run-stage 跑的這一段**就是閘門**：沒有人持有閘門鎖時自己取（綁行程；TTL 3 小時兜底），跑完放。回 release()。
    取到之後，conftest 會拒絕其他視窗的 pytest（含單檔），PM 不必再人工通知全視窗暫停（T82）。
    - 已經有人持有（整合者顯式取的、或別的 run-stage）⇒ 什麼都不動、release 是空的（絕不放別人的鎖）。
    - 行程被殺／當機：鎖綁著這個 pid，read_gate 見到持有者已死就當沒有鎖。
    - 任何錯誤 ⇒ 不取（fail-open；只是少一道保護）。"""
    noop = (lambda: None)
    try:
        if hr is None:
            import importlib.util as _iu
            sp = _iu.spec_from_file_location("_bt_heavy_run_gate", str(Path(repo) / "tools" / "platform" / "heavy_run.py"))
            hr = _iu.module_from_spec(sp)
            sp.loader.exec_module(hr)
        if hr.read_gate():
            return noop
        window = window or os.environ.get("MOTRIX_WINDOW") or "run-stage"
        ok, lock = hr.gate_acquire(window, note="run-stage %s（自動取、跑完放）" % stage, ttl=3 * 3600, holder_pid=os.getpid())
        if not ok:
            return noop
        note("[run-stage] 取閘門鎖（%s）：跑的期間其他視窗的 pytest（含單檔）會被拒絕；跑完自動放" % window)
        token = lock["token"]

        def release():
            try:
                cur = hr.read_gate()
                if cur and cur.get("token") == token:
                    hr.gate_release(window)
            except Exception:                           # noqa: BLE001 — 放不掉靠 holder_pid／TTL 兜底
                pass
        return release
    except Exception:                                   # noqa: BLE001
        return noop


def run_stage(repo, stage, records, python=None, runner=None, workers=None, note=print, no_failfast=False, retry_failed=RETRY_MAX_DEFAULT):
    """run-stage 本體（`_run_stage`）外包一層閘門鎖：真的要跑（沒注入 runner）時自己持有閘門鎖，跑完放（見 gate_hold）。
    回 (exit code, 是否寫了紀錄, 說明)。其餘說明見 `_run_stage`。"""
    release = gate_hold(repo, stage, note) if runner is None else (lambda: None)
    try:
        return _run_stage(repo, stage, records, python, runner, workers, note, no_failfast, retry_failed)
    finally:
        release()


def _run_stage(repo, stage, records, python=None, runner=None, workers=None, note=print, no_failfast=False, retry_failed=RETRY_MAX_DEFAULT):
    """**獨立跑一段也算數**（建包優化 2 項 2）：跑與建包同一組指令；開跑與結束的指紋相同且工作樹乾淨 ⇒ 把這一段（綠或紅）寫進沿用紀錄
    （source=standalone）。之後建包遇到同指紋、12 小時內的綠就直接沿用這一段，不再跑第二次。
    - 紅也照記（同指紋之前的綠不可以再被沿用，與建包同一條規則）；fail-fast 提前停止的一段是紅。
    - 指紋不同（跑到一半 HEAD／工作樹／環境變了）或一開始就不乾淨 ⇒ 照跑、回傳 exit code，但**不寫紀錄**。
    - 不做偶發**登記**（known_flakes 不動）。但一段跑完且紅的題數 ≤ `retry_failed`（預設 5）時，**只把紅的題在安靜環境（單程序、無 failfast）重跑一次**：
      全部通過 ⇒ 這一段記「綠（重試 k 題）」，stages.<段>.retry 帶原始紅、重試結果、明細目錄，retry_log.jsonl 每題一行（累計次數＝雜訊排行榜）；
      重試仍紅 ⇒ 這一段記紅。只有「跑完、確定紅的就是這幾題」才重試（retry_eligibility）：被中斷／failfast 提早停／collect 紅／紅太多 ⇒ 不重試。
      為了讓「紅 ≤ 上限」的一輪能跑完，failfast 改成「紅超過上限才停」（MOTRIX_FAILFAST_N＝上限＋1、關掉靜默分鐘那條）；`--no-retry` 回舊值（10／3 分鐘）。
    - `no_failfast=True`（`--no-failfast`）：**找出全部紅**——只把 `MOTRIX_FAILFAST=0`，其餘指令／plugin／指紋完全相同；紅的段多記 `reds` 清單。
      全綠的 run 本來就不可能被 failfast 截斷（執行題數＝收集題數）⇒ 無 failfast 的全綠與有 failfast 的全綠是同一份證據，照舊可被沿用；有紅照舊不沿用。
    回 (exit code, 是否寫了紀錄, 說明)。`runner(cmd, cwd, env)` 供測試注入（回 returncode）。"""
    import tempfile
    python = python or sys.executable
    repo = Path(repo)
    fp0 = fingerprint(repo)
    backend = repo / "backend"
    base = os.path.join(tempfile.gettempdir(), "motrix-runstage-%s-%s-%s" % (stage, datetime.now().strftime("%Y%m%d_%H%M%S"), os.urandom(3).hex()))   # 末尾隨機：同一秒起兩輪也不共用 fail_stream 目錄（舊明細會被當成這一輪的紅）
    cmd = stage_command(stage, python, workers or default_workers(stage), base)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(repo / "tools" / "platform")] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    try:                                           # 這就是閘門本身：整合者持有閘門鎖時自動帶 token（conftest 的重型直接跑檢查認它），不靠人記得 export
        import importlib.util as _iu
        _sp = _iu.spec_from_file_location("_bt_heavy_run", str(repo / "tools" / "platform" / "heavy_run.py"))
        _hr = _iu.module_from_spec(_sp)
        _sp.loader.exec_module(_hr)
        _lock = _hr.read_gate()
        if _lock:
            env[_hr.GATE_TOKEN_ENV] = _lock["token"]
    except Exception:                              # noqa: BLE001 — 讀不到就不帶（fail-open；只是少一個放行憑證）
        pass
    env.update({"MOTRIX_FAIL_STREAM_STAGE": stage, "MOTRIX_FAILFAST": "1", "MOTRIX_FAILFAST_N": "10", "MOTRIX_FAILFAST_QUIET_MIN": "3",
                "MOTRIX_FAILFIRST": "1", "MOTRIX_FAILFIRST_BASE": "auto"})
    # 失敗明細一律落在這一輪專用目錄（failfast 提早停也一樣）：run-stage 結束時讀回、印出路徑與紅題，不必再去主工作樹翻 jsonl
    # （T53：failfast 停下時明細其實有寫，但 run-stage 只印「紅」，別的視窗看不到哪一題）
    fs_dir = base + "-failstream"
    env["MOTRIX_FAIL_STREAM_DIR"] = fs_dir
    env["MOTRIX_FAIL_STREAM_RUN"] = "runstage-%s-%s" % (stage, datetime.now().strftime("%H%M%S"))
    if no_failfast:
        env["MOTRIX_FAILFAST"] = "0"
    elif retry_failed > 0:
        # 要讓「紅 ≤ 上限」的一輪**跑完**（否則沒跑到的題沒有證據、不能重試）：紅超過上限才停；靜默分鐘那條關掉（它會在第一個紅之後 3 分鐘就截斷）
        env["MOTRIX_FAILFAST_N"] = str(retry_failed + 1)
        env["MOTRIX_FAILFAST_QUIET_MIN"] = "0"
    note("[run-stage] %s：%s" % (stage, " ".join(cmd)))
    if runner is None:
        rc = subprocess.run(cmd, cwd=str(backend), env=env).returncode
    else:
        rc = runner(cmd, str(backend), env)
    st0 = stream_status(fs_dir) if rc != 0 else None
    retry, retry_rows, retry_note = None, [], ""
    if st0 is not None:
        try:
            ok_r, why_r = retry_eligibility(rc, st0, retry_failed)
            if ok_r and (not fp0 or fingerprint(repo) != fp0):
                ok_r, why_r = False, "指紋已變（HEAD／工作樹／環境），這一輪不會寫紀錄，不重試"
            if ok_r:
                ids = list(st0["reds"])
                rdir = base + "-retry-failstream"
                renv = dict(env)
                renv.update({"MOTRIX_FAILFAST": "0", "MOTRIX_FAILFIRST": "0", "MOTRIX_FAIL_STREAM_DIR": rdir,
                             "MOTRIX_FAIL_STREAM_RUN": env["MOTRIX_FAIL_STREAM_RUN"] + "-retry"})
                renv.pop("MOTRIX_FAILFIRST_BASE", None)
                rcmd = retry_command(stage, python, ids, base + "-retry")
                note("[run-stage] %s 紅 %d 題（≤ %d）⇒ 只在安靜環境重跑這幾題一次：%s" % (stage, len(ids), retry_failed, "、".join(ids)))
                t_r = datetime.now()
                rrc = subprocess.run(rcmd, cwd=str(backend), env=renv).returncode if runner is None else runner(rcmd, str(backend), renv)
                rst = stream_status(rdir)
                rsum = rst["summary"] or {}
                still = [n for n in ids if n in rst["reds"]]
                green_r = (rrc == 0 and not rst["reds"] and int(rsum.get("passed", 0)) >= len(ids) and not int(rsum.get("skipped", 0))
                           and not rsum.get("aborted") and not rsum.get("aborted_by"))
                if not green_r and not still:
                    still = list(ids)                        # 重試沒有「每題都明確過」的證據 ⇒ 全部當仍紅（寧可紅）
                retry = {"limit": retry_failed, "count": len(ids), "original_reds": ids, "retried_green": bool(green_r),
                         "still_red": still, "seconds": round((datetime.now() - t_r).total_seconds(), 1), "dir": rdir}
                retry_rows = [{"nodeid": n, "original": st0["info"].get(n), "result": "fail" if n in still else "pass", "run": env["MOTRIX_FAIL_STREAM_RUN"]}
                              for n in ids]
                if green_r:
                    rc = 0
            elif retry_failed > 0:
                retry_note = "；未重試：" + why_r
        except Exception as e:                               # noqa: BLE001 — 重試出任何錯 ⇒ 照原本的紅，不吞
            retry, retry_rows = None, []
            retry_note = "；重試出錯（%r），照原本的紅" % (e,)
    fp1 = fingerprint(repo)
    if not fp0 or fp0 != fp1:
        return rc, False, "不寫紀錄：%s" % ("開跑時工作樹不乾淨（含未追蹤檔）" if not fp0 else "跑到一半指紋變了（HEAD／工作樹／環境）")
    commit = _git(repo, "rev-parse", "--short", "HEAD").strip()
    try:                                                                # 診斷旁表：事後 explain 才指得出「環境哪一項不同」（run-stage 原本不寫，T82 查不出原因）
        remember_parts(records, fp1, components(repo))
    except Exception:                                                   # noqa: BLE001 — 診斷用，寫不進去不影響結果
        pass
    found = collect_reds(fs_dir) if rc != 0 else None
    reds = found if no_failfast else None                              # 沿用紀錄的欄位維持原樣：只有 --no-failfast 才多記 reds
    record(records, fp1, False, commit, stages={stage: stage_entry(rc == 0, reds=reds, failfast=False if no_failfast else None, retry=retry)}, source="standalone")
    extra = retry_note
    if retry:
        append_retry_log(records, stage, commit, fp1, retry_rows)
        counts = retry_counts(records)
        extra += "；重試 %d 題：%s（原始紅明細：%s；重試明細：%s）；累計重試次數：%s" % (
            retry["count"], "全部通過 ⇒ 記綠" if retry["retried_green"] else "仍紅 %d 題（%s）⇒ 記紅" % (len(retry["still_red"]), "、".join(retry["still_red"])),
            fs_dir, retry["dir"], "、".join("%s×%d" % (n, counts.get(n, {}).get("retries", 0)) for n in retry["original_reds"]))
    elif found:
        extra += "；紅 %d 題（%s）：%s；明細（longrepr）：%s" % (
            len(found), "無 failfast，全部列出" if no_failfast else "failfast 提早停，只含已出現的", "、".join(found[:20]) + ("…" if len(found) > 20 else ""), fs_dir)
    blockers = reuse_blockers(python)
    warn = ("；⚠ 建包不一定沿用這份結果——" + "；".join(blockers)) if blockers else ""
    label = ("綠（重試 %d 題）" % retry["count"]) if (rc == 0 and retry) else ("綠" if rc == 0 else "紅")
    return rc, True, "已記錄：%s=%s（建包同指紋、%d 小時內會沿用，可跨午夜）%s%s" % (stage, label, MAX_HOURS, extra, warn)


def find_reusable(records, fp, now, max_hours=MAX_HOURS):
    """同指紋的**最新一筆**：嚴格全綠、max_hours 內（可跨午夜）、時間戳不在未來 ⇒ 回它；否則 None。純函式。"""
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
    if last.get("green") is not True:
        return None
    if (now - t).total_seconds() > max_hours * 3600 or t > now:
        return None
    return last


def _stage_ok(entry, now, max_hours):
    try:
        t = datetime.strptime(entry["tested_at"], TS_FMT)
    except (KeyError, TypeError, ValueError):
        return False
    if entry.get("green") is not True:
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


def stage_entry(green, tested_at=None, flaky=None, reds=None, failfast=None, retry=None):
    e = {"green": bool(green), "tested_at": tested_at or datetime.now().strftime(TS_FMT)}
    if retry:
        e["retry"] = dict(retry)                     # run-stage 的「只重試失敗題」證據（原始紅、重試結果、明細目錄）；綠（重試 k 題）與紅都會帶
    if flaky:
        e["flaky_retried"] = list(flaky)
    if reds:
        e["reds"] = list(reds)                       # 無 failfast 跑完的紅題清單（只供人看；紅的段不會被沿用）
    if failfast is False:
        e["failfast"] = False                        # 這一段是『找出全部紅』模式跑的；全綠時與有 failfast 的全綠是同一份證據（failfast 截不到全綠的 run）
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
    rn = sub.add_parser("run-stage", help="獨立跑一段（與建包同一組指令）並把結果寫進沿用紀錄——建包就不必再跑一次")
    rn.add_argument("--stage", required=True, choices=STAGES)
    rn.add_argument("--records")
    rn.add_argument("--workers", type=int)
    rn.add_argument("--retry-failed", type=int, default=RETRY_MAX_DEFAULT, metavar="N",
                    help="一段跑完、紅的題數 ≤ N 時，只把紅的題在安靜環境重跑一次（預設 %d；全過⇒記綠（重試 k 題）、仍紅⇒記紅；不是 flake 登記）" % RETRY_MAX_DEFAULT)
    rn.add_argument("--no-retry", action="store_true", help="不重試（等於 --retry-failed 0；failfast 回舊值）")
    rn.add_argument("--no-failfast", action="store_true", help="找出全部紅（只關 failfast，其餘同正式指令）；紅的段記 reds 清單")
    rcn = sub.add_parser("retry-counts", help="run-stage 重試過的題累計次數（雜訊排行榜的來源；唯讀）")
    rcn.add_argument("--records")
    rcn.add_argument("--json", action="store_true")
    ex = sub.add_parser("explain", help="為什麼這一段沒被沿用／同一份東西為何跑兩次（唯讀診斷）")
    ex.add_argument("--records")
    ex.add_argument("--last", type=int, default=12)
    ex.add_argument("--json", action="store_true")
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
        env = current_env()
        fp = fingerprint(repo, env)
        comps = components(repo, env) if fp else None
        if fp:
            remember_parts(default_records(repo), fp, comps)      # 診斷旁表（只存元件雜湊）；寫不進去不影響指紋
        print(json.dumps({"fingerprint": fp, "components": comps}))
    elif a.cmd == "run-stage":
        rc, wrote, why = run_stage(repo, a.stage, a.records or default_records(repo), workers=a.workers, no_failfast=a.no_failfast,
                                   retry_failed=0 if a.no_retry else max(0, a.retry_failed))
        print("[run-stage] " + why)
        return rc
    elif a.cmd == "retry-counts":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        cnt = retry_counts(a.records or default_records(repo))
        rows = sorted(cnt.items(), key=lambda kv: (-kv[1]["retries"], kv[0]))
        if a.json:
            print(json.dumps(dict(rows), ensure_ascii=False, indent=1))
        else:
            for n, v in rows:
                print("%3d 次（過 %d／仍紅 %d，最近 %s）  %s" % (v["retries"], v["passed"], v["failed"], v["last"], n))
            if not rows:
                print("（還沒有重試紀錄）")
    elif a.cmd == "explain":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        res = explain(a.records or default_records(repo), repo, last=a.last)
        print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else render_explain(res))
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
    try:                                                              # 背景執行不彈視窗（tools/platform/nowindow.py；MOTRIX_SHOW_WINDOWS=1 可關）
        import sys as _s, pathlib as _p
        _s.path.insert(0, str(_p.Path(__file__).resolve().parents[2] / "tools" / "platform"))
        import nowindow as _nw
        _nw.install()
    except ImportError:
        pass
    sys.exit(main())
