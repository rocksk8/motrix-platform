# -*- coding: utf-8 -*-
"""合併之後一個指令收拾所有「基準檔」衝突（整合者在 `git merge` 衝突後、或乾淨合併後跑一次）。

[單位] tools:resolve_baselines    [層] 工具    [穩定度] 內部
[公開介面] resolve（純流程）, main；規則本體在 merge_drivers.py（git 合併驅動與本工具共用同一份）
[不變式]
  - 只處理下面「看得懂」的檔；其他衝突（程式碼、測試）原樣留給人，列在報告最後；**絕不替人決定程式碼衝突**。
  - 能結構合併（兩邊的新增都留）就合併；兩邊把同一個值改成不一樣 ⇒ 不猜，列為未解決。
  - 合併完再「從合併後的樹重算」會依賴程式碼的衍生值（快照、路由合計、MAX_ENTRIES、sha256）；
    **新增的未範圍讀取不會被自動登記**（那是要人判斷的，報告會列出來）。
  - 預設會 `git add` 已解決的檔（讓 `git merge --continue`／commit 可以接著做）；`--no-add` 只寫檔；`--check` 完全不寫檔、
    只回報「有沒有東西要處理」。本工具不 commit。
  - 重的重錄（route_inventory 的 endpoints、response_keys_baseline）要開整個 app：預設不跑，`--verify`／`--regen-slow` 才跑。

處理對象（每一項：衝突時怎麼解 ／ 之後怎麼重算）
  core 與各模組 CHANGELOG       兩邊的 `## (next)` 都留（併成一塊）；驅動看不懂的形狀 ⇒ 逐行聯集後再併 (next)（會標「請目視」）
                                合併後（不論有沒有衝突）(next) 段落不在最上面——上游疊了號碼段落時 git 會把它悄悄放到下面——就搬回最上面
  version_manifest.json         兩邊新增的條目都留（同 git 驅動）
  l1_interface_snapshot.json    結構合併 ／ 之後比對目前介面，有差就 `_l1_interface.py --update --pending`（CHANGELOG 最上面是 (next) 才會重產；否則報「需要升版」）
  route_inventory.json          結構合併，summary 由 endpoints 重算、select_star 兩邊增量相加 ／ 之後用原始碼重算 summary／select_star
  response_keys_baseline.json   結構合併（鍵集聯集）／ 之後要 `--verify`（或 `--regen-slow` 重錄）才知道對不對
  unscoped_reads_baseline.json  結構合併（聯集）／ 之後掃描：程式碼有、基準沒有的 ⇒ 報告（不自動登記）
  test_unscoped_reads_ratchet.py 的 MAX_ENTRIES   數字＝基底＋兩邊增量、說明註解兩邊都留 ／ 之後若小於聯集後的基準筆數 ⇒ 調成基準筆數
  docs/platform/modules.json    結構合併（手排的檔：逐行聯集且解析後必須等於結構合併的結果）
  其他棘輪基準（EXTRA_JSON：recyclebin／write_golden／page_path／json_extract／l2_import／settings_deploy／field_policy_exits／pdf_raw_sinks）
                                結構合併（各新增不同的 id ⇒ 聯集）；之後沒有重算（那些由各自的測試守門）
  apply_update.version.json／apply_module_update.version.json   重算 .ps1 的 sha256（去 BOM、CRLF→LF）與 $…ScriptVersion

用法（任何一棵 MOTRIX-PLATFORM 樹；Python 用 D:\\MOTRIX-PLATFORM\\.venv312\\Scripts\\python.exe）：
  python tools/platform/resolve_baselines.py                 解決衝突中的基準檔＋重算衍生值；已解決的 git add
  python tools/platform/resolve_baselines.py --check         只看：還有什麼要處理（exit 1＝有）
  python tools/platform/resolve_baselines.py --verify        解決之後串列跑單檔測試確認（L1／unscoped／route_inventory／manifest×4／AH-O7）
  python tools/platform/resolve_baselines.py --regen-slow    重錄 route_inventory endpoints 與 response_keys_baseline（開整個 app，分鐘級），
                                                             再跑上面那些＋回應鍵集基準測試確認；程式碼合好、確定要重錄時才用
  python tools/platform/resolve_baselines.py --no-add        只寫檔不 git add
退出碼：0 全部處理完；1 還有要人處理的（報告最後列出）；2 工具自己出錯。
另有 git 合併驅動（tools/platform/setup_merge_drivers.py 登記後，上述檔案在 `git merge`／cherry-pick 時第一道自動合）；
驅動只看得到三份檔案、看不到合併後的程式碼，所以「重算」那一半仍要靠本工具。
"""
import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load_drivers():
    spec = importlib.util.spec_from_file_location("_motrix_merge_drivers", HERE / "merge_drivers.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MD = _load_drivers()

CHANGELOG_RE = re.compile(r"^backend/(core|modules/[^/]+)/CHANGELOG\.md$")
MANIFEST = "backend/version_manifest.json"
SNAPSHOT = "backend/tests/platform/l1_interface_snapshot.json"
ROUTE_INV = "backend/tests/platform/route_inventory.json"
RESP_KEYS = "backend/tests/platform/response_keys_baseline.json"
UNSCOPED = "backend/tests/platform/unscoped_reads_baseline.json"
RATCHET = "backend/tests/platform/test_unscoped_reads_ratchet.py"
MODULES = "docs/platform/modules.json"
CORE_CHANGELOG = "backend/core/CHANGELOG.md"
#: 其他『只准縮小』的棘輪基準（id→說明的字典；兩邊各新增不同的 id ⇒ 聯集）。新增這類基準檔時加在這裡＋.gitattributes
EXTRA_JSON = (
    "backend/tests/platform/recyclebin_baseline_t53.json",
    "backend/tests/platform/write_golden_baseline.json",
    "backend/tests/platform/page_path_baseline.json",
    "backend/tests/platform/json_extract_baseline.json",
    "backend/tests/platform/l2_import_baseline.json",
    "backend/tests/platform/settings_deploy_baseline.json",
    "backend/tests/platform/field_policy_exits_baseline.json",
    "backend/tests/pdf_raw_sinks_baseline.json",
)
JSON_FILES = (SNAPSHOT, ROUTE_INV, RESP_KEYS, UNSCOPED, MODULES) + EXTRA_JSON
#: (版本檔, .ps1, 版本變數)
PS1_REG = (
    ("backend/tools/apply_update.version.json", "backend/tools/apply_update.ps1", "ApplyScriptVersion"),
    ("backend/tools/apply_module_update.version.json", "backend/tools/apply_module_update.ps1", "ApplyModuleScriptVersion"),
)
PS1_JSON = {j for j, _, _ in PS1_REG}


def kind_of(path):
    if CHANGELOG_RE.match(path):
        return "changelog"
    if path == MANIFEST:
        return "manifest"
    if path in JSON_FILES:
        return "json"
    if path == RATCHET:
        return "maxentries"
    if path in PS1_JSON:
        return "ps1sha"
    return None


# ── git 小工具 ────────────────────────────────────────────────────────────

def git(repo, *args, check=True, text=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if check and r.returncode != 0:
        raise RuntimeError("git %s 失敗：%s" % (" ".join(args), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout.decode("utf-8", "replace") if text else r.stdout


def unmerged(repo):
    """⇒ {路徑: {階段(1 基底／2 我方／3 對方): blob sha}}。"""
    out = {}
    raw = git(repo, "ls-files", "-u", "-z", text=False).decode("utf-8", "replace")
    for rec in filter(None, raw.split("\0")):
        meta, _, path = rec.partition("\t")
        _mode, sha, stage = meta.split()
        out.setdefault(path, {})[int(stage)] = sha
    return out


def blob_text(repo, sha):
    raw = git(repo, "cat-file", "blob", sha, text=False)
    if raw.startswith(b"\xef\xbb\xbf") or b"\r\n" in raw:
        return None                                   # BOM／CRLF：不是本 repo 的排版 ⇒ 不碰
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def read_worktree(repo, rel):
    p = Path(repo) / rel
    if not p.is_file():
        return None
    raw = p.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r\n" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def has_markers(text):
    return bool(re.search(r"^(<<<<<<< |>>>>>>> )", text or "", re.M))


# ── 衝突中的檔：三方合併 ─────────────────────────────────────────────────────

def _union_changelog(o, a, b):
    """驅動看不懂的 CHANGELOG 形狀：逐行聯集，再把多塊 (next) 併成一塊。⇒ 文字或 None。"""
    text = MD._union_text(o, a, b)
    if text is None or has_markers(text):
        return None
    pre, secs = MD.split_sections(text)
    return pre + "".join(MD.coalesce_next(secs))


def merge_conflicted(repo, path, stages):
    """⇒ (新文字 or None, 說明)。None＝這個檔我不解，留給人。"""
    kind = kind_of(path)
    if kind == "ps1sha":
        return None, "ps1sha"                      # 內容由重算決定，不用合併
    if 1 not in stages or 2 not in stages or 3 not in stages:
        return None, "缺少基底／我方／對方其中一份（刪除或兩邊各自新增的衝突）：請人看"
    o, a, b = (blob_text(repo, stages[n]) for n in (1, 2, 3))
    if None in (o, a, b):
        return None, "檔案含 BOM／CRLF 或不是 UTF-8：不是本 repo 的排版，請人看"
    try:
        if kind == "changelog":
            got = MD.merge_changelog(o, a, b)
            if got is not None:
                return got, "兩邊的新增都留（(next) 併成一塊）"
            got = _union_changelog(o, a, b)
            return got, ("驅動看不懂這個形狀，改用逐行聯集再併 (next) —— 請目視確認內容" if got is not None else "兩邊改了同一段舊內容：請人看")
        if kind == "manifest":
            got = MD.merge_manifest(o, a, b)
            return got, ("兩邊新增的條目都留" if got is not None else "兩邊改了同一筆舊條目或排版不符：請人看")
        if kind == "json":
            got = MD.merge_json(o, a, b, path=path)
            return got, ("結構合併" if got is not None else "兩邊把同一個值改成不一樣：請人看")
        if kind == "maxentries":
            got = MD.merge_maxentries(o, a, b)
            return got, ("MAX_ENTRIES 數字相加、註解兩邊都留" if got is not None else "檔案其餘部分兩邊都改了：請人看")
    except Exception as exc:                        # noqa: BLE001
        return None, "合併時例外 %r：請人看" % (exc,)
    return None, "不認得的種類"


# ── 重算：從合併後的樹 ───────────────────────────────────────────────────────

def _py_run(repo, code, cwd, timeout=600):
    r = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=str(cwd), capture_output=True, timeout=timeout,
                       env=_env(repo))
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def _env(repo):
    import os
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(Path(repo) / "backend") + (";" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def _write(repo, rel, text, dry):
    if not dry:
        (Path(repo) / rel).write_bytes(text.encode("utf-8"))


def ps1_digest(raw):
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def next_to_top(text):
    """CHANGELOG 的 `## (next)` 段落必須在最上面（G4／test_version_slots）。上游在最上面又疊了號碼段落時，git 的文字合併會把我方的 (next)
    放到它們下面（沒有衝突、安靜地放錯位置）⇒ 搬回最上面（只搬 (next) 段落；多塊併成一塊）。⇒ 新文字，或 None（本來就對／不是本 repo 排版）。"""
    pre, secs = MD.split_sections(text)
    if not secs:
        return None
    is_next = [s.startswith("## (next") for s in secs]
    if not any(is_next) or (is_next[0] and not any(is_next[1:])):
        return None
    nexts = [s if s.endswith("\n\n") else s.rstrip("\n") + "\n\n" for s, n in zip(secs, is_next) if n]
    rest = [s for s, n in zip(secs, is_next) if not n]
    out = pre + "".join(MD.coalesce_next(nexts) + rest)
    return out if out != text else None


def post_changelog_order(repo, dry, skip):
    """所有 core／模組 CHANGELOG：(next) 不在最上面就搬上去 ⇒ (改過的檔, 問題)。"""
    changed, problems = [], []
    rels = [CORE_CHANGELOG] + sorted(p.relative_to(repo).as_posix() for p in (Path(repo) / "backend" / "modules").glob("*/CHANGELOG.md"))
    for rel in rels:
        if rel in skip:
            continue
        text = read_worktree(repo, rel)
        if text is None or has_markers(text):
            continue
        new = next_to_top(text)
        if new is not None:
            _write(repo, rel, new, dry)
            changed.append(rel)
    return changed, problems


def post_ps1(repo, dry, skip):
    """重算 .ps1 的 sha256 與版本變數 ⇒ (改過的檔, 問題)。"""
    changed, problems = [], []
    for jrel, prel, var in PS1_REG:
        jp, pp = Path(repo) / jrel, Path(repo) / prel
        if jrel in skip or prel in skip or not jp.is_file() or not pp.is_file():
            continue
        raw = pp.read_bytes()
        if has_markers(raw.decode("utf-8", "replace")):
            problems.append("%s 還有衝突標記，先解 .ps1 再重算 %s" % (prel, jrel))
            continue
        m = re.search(r'^\$%s = "([^"]+)"' % var, raw.decode("utf-8-sig", "replace"), re.M)
        if not m:
            problems.append("%s 找不到 $%s" % (prel, var))
            continue
        try:
            reg = json.loads(jp.read_text(encoding="utf-8"))
        except ValueError:
            reg = {}                                       # 衝突標記或壞檔：重寫整個（說明欄從 HEAD 那份帶回來）
        new = dict(reg) if isinstance(reg, dict) else {}
        if "_說明" not in new:
            try:
                head = json.loads(git(repo, "show", "HEAD:%s" % jrel))
                if isinstance(head, dict) and "_說明" in head:
                    new = {"_說明": head["_說明"], **new}
            except (RuntimeError, ValueError):
                pass
        new["version"], new["sha256"] = m.group(1), ps1_digest(raw)
        if new != reg:
            text = json.dumps(new, ensure_ascii=False, indent=1) + "\n"
            _write(repo, jrel, text, dry)
            changed.append(jrel)
    return changed, problems


def post_unscoped(repo, dry, skip):
    """掃描目前程式碼 vs 合併後的基準；MAX_ENTRIES 不足就調成基準筆數 ⇒ (改過的檔, 問題, 說明)。"""
    changed, problems, notes = [], [], []
    code = ("import json;from tests.platform import _unscoped_reads as U;"
            "print(json.dumps({'cur':U.scan_all(),'base':U.load_baseline()}))")
    rc, out, err = _py_run(repo, code, Path(repo) / "backend")
    if rc != 0:
        return changed, ["未範圍讀取掃描跑不起來（%s）" % (err.strip().splitlines() or ["?"])[-1][:200]], notes
    d = json.loads(out.strip().splitlines()[-1])
    cur, base = d["cur"], d["base"]
    new = sorted(k for k in cur if k not in base)
    if new:
        problems.append("程式碼裡有基準沒有的未範圍讀取 %d 筆（不自動登記；改走 filter_sql／核准 helper，或有理由才登記）：%s"
                        % (len(new), "；".join(new[:8]) + ("…" if len(new) > 8 else "")))
    stale = sorted(k for k in base if k not in cur)
    if stale:
        notes.append("基準有 %d 筆程式碼已不存在（不自動刪；要縮小基準請手動）：%s" % (len(stale), "；".join(stale[:5])))
    text = read_worktree(repo, RATCHET)
    if text is not None and RATCHET not in skip:
        sp = MD.split_cap(text)
        if sp is not None:
            cap = MD._cap_n(sp[1])
            if cap < len(base):
                first = sp[1][0]
                sp[1][0] = re.sub(r"^MAX_ENTRIES\s*=\s*\d+", "MAX_ENTRIES = %d" % len(base), first)
                _write(repo, RATCHET, "\n".join(sp[0] + sp[1] + sp[2]), dry)
                changed.append(RATCHET)
                notes.append("MAX_ENTRIES %d → %d（＝聯集後的基準筆數）" % (cap, len(base)))
            elif cap > len(base):
                notes.append("MAX_ENTRIES %d 比基準筆數 %d 大 %d（有餘裕，沒動；要縮小請手動）" % (cap, len(base), cap - len(base)))
    return changed, problems, notes


def post_route_summary(repo, dry, skip):
    """route_inventory.json 的 summary 由 endpoints 重算、select_star 由原始碼重算 ⇒ (改過的檔, 問題)。"""
    if ROUTE_INV in skip:
        return [], []
    p = Path(repo) / ROUTE_INV
    if not p.is_file():
        return [], []
    try:
        inv = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return [], ["%s 讀不出來（還有衝突標記？）" % ROUTE_INV]
    code = ("import json;from tests.platform import _route_inventory as RI;"
            "inv=json.load(open(%r,encoding='utf-8'))['endpoints'];"
            "print(json.dumps({'summary':RI.summarize(inv),'select_star':RI.count_select_star()}))" % str(p))
    rc, out, err = _py_run(repo, code, Path(repo) / "backend")
    if rc != 0:
        return [], ["路由盤點合計重算跑不起來（%s）" % (err.strip().splitlines() or ["?"])[-1][:200]]
    want = json.loads(out.strip().splitlines()[-1])
    if inv.get("summary") == want["summary"] and inv.get("select_star") == want["select_star"]:
        return [], []
    inv["summary"], inv["select_star"] = want["summary"], want["select_star"]
    _write(repo, ROUTE_INV, json.dumps(inv, ensure_ascii=False, indent=1, sort_keys=False) + "\n", dry)
    return [ROUTE_INV], []


def _changelog_pending(repo):
    text = read_worktree(repo, CORE_CHANGELOG) or ""
    m = re.search(r"^## .*$", text, re.M)
    return bool(m and m.group(0).startswith("## (next"))


def post_l1(repo, dry, skip):
    """目前介面 vs 快照；有差就重產（只在 CORE CHANGELOG 最上面是 (next) 時）⇒ (改過的檔, 問題, 說明)。"""
    if SNAPSHOT in skip:
        return [], [], []
    script = Path(repo) / "backend" / "tests" / "platform" / "_l1_interface.py"
    run = lambda *a: subprocess.run([sys.executable, "-X", "utf8", str(script), *a], cwd=str(Path(repo) / "backend"),   # noqa: E731
                                    capture_output=True, env=_env(repo), timeout=600)
    r = run()
    out = r.stdout.decode("utf-8", "replace")
    m = re.search(r"快照 (\S+)／目前 (\S+)；新增 (\d+)、修改 (\d+)、刪除 (\d+)", out)
    if r.returncode != 0 or not m:
        return [], ["L1 介面比對跑不起來：%s" % (r.stderr.decode("utf-8", "replace").strip().splitlines() or [out[:120]])[-1][:200]], []
    snap_ver, _cur, a, c, d = m.group(1), m.group(2), int(m.group(3)), int(m.group(4)), int(m.group(5))
    pending = _changelog_pending(repo)
    consistent = (snap_ver == "next") == pending
    if (a, c, d) == (0, 0, 0) and consistent:
        return [], [], []
    if not pending and (a, c, d) == (0, 0, 0):
        return [], ["L1 快照是版號佔位（core_version=next）但 CORE CHANGELOG 最上面不是 (next) 段落：列車樹跑 tools/platform/train_number.py assign；"
                    "分支樹補 (next) 段落並跑 core_bump.py --pending —— 工具不替人決定"], []
    if not pending:
        return [], ["L1 介面與快照不同（新增 %d／修改 %d／刪除 %d）而 CORE CHANGELOG 最上面不是 (next)：要升 CORE_VERSION 或補 (next) 段落，工具不替人決定" % (a, c, d)], []
    if dry:
        return [SNAPSHOT], [], ["L1 快照需要重產（新增 %d／修改 %d／刪除 %d；快照 core_version=%s）" % (a, c, d, snap_ver)]
    r2 = run("--update", "--pending")
    if r2.returncode != 0:
        return [], ["L1 快照重產被拒：%s" % r2.stdout.decode("utf-8", "replace").strip()[:200]], []
    return [SNAPSHOT], [], ["L1 快照已重產（--update --pending；新增 %d／修改 %d／刪除 %d）" % (a, c, d)]


VERIFY_TESTS = (
    ("L1 介面快照", ["tests/platform/test_l1_interface_snapshot.py"]),
    ("未範圍讀取棘輪", ["tests/platform/test_unscoped_reads_ratchet.py"]),
    ("路由盤點", ["tests/platform/test_route_inventory.py"]),
    ("版本清單（4 個守門）", ["tests/test_version_manifest_2026_09_22.py", "tests/test_version_manifest_no_future_stamps_2026_10_07.py",
                       "tests/test_version_manifest_shipped_is_immutable_2026_09_25.py", "tests/test_version_manifest_unique_version_2026_09_25.py"]),
    ("apply 腳本雜湊（AH-O7）", ["tests/platform/test_apply_plan_2026_09_28.py", "-k", "aho7"]),
)
SLOW_TESTS = (("回應鍵集基準（開整個 app，分鐘級）", ["tests/platform/test_response_keys_baseline.py"]),)


def run_tests(repo, label_args, dry):
    """⇒ [(標籤, 通過?, 摘要)]；一次一個檔、串列跑（不平行，免得吃光機器）。"""
    import os
    out = []
    for label, args in label_args:
        cmd = [sys.executable, "-X", "utf8", "-m", "pytest", *args, "-q", "-p", "no:cacheprovider", "-x"]
        if dry:
            out.append((label, None, "（--check：不跑）"))
            continue
        env = _env(repo)
        env.pop("MOTRIX_TRAIN", None)
        r = subprocess.run(cmd, cwd=str(Path(repo) / "backend"), capture_output=True, env=env, timeout=1800)
        tail = (r.stdout.decode("utf-8", "replace").strip().splitlines() or ["(無輸出)"])[-1]
        out.append((label, r.returncode == 0, tail))
    return out


def regen_slow(repo, dry):
    """重錄 route_inventory endpoints（U0B_RECORD）與 response_keys_baseline（U0A_RECORD）。"""
    res = []
    for label, env_var, test in (("路由盤點", "U0B_RECORD", "tests/platform/test_route_inventory.py::test_inventory_matches_committed"),
                                 ("回應鍵集基準", "U0A_RECORD", "tests/platform/test_response_keys_baseline.py::test_record_or_compare_against_baseline")):
        if dry:
            res.append((label, None, "（--check：不跑）"))
            continue
        env = _env(repo)
        env.pop("MOTRIX_TRAIN", None)
        env[env_var] = "1"
        r = subprocess.run([sys.executable, "-X", "utf8", "-m", "pytest", test, "-q", "-p", "no:cacheprovider"],
                           cwd=str(Path(repo) / "backend"), capture_output=True, env=env, timeout=3600)
        tail = (r.stdout.decode("utf-8", "replace").strip().splitlines() or ["(無輸出)"])[-1]
        res.append((label, r.returncode in (0, 5), tail))
    return res


# ── 主流程 ───────────────────────────────────────────────────────────────────

def resolve(repo=REPO, dry=False, add=True, verify=False, slow=False, post=True):
    """⇒ 報告 dict：resolved／unresolved（要人處理）／regenerated／notes／problems／tests。純流程，不印。"""
    repo = Path(repo)
    rep = {"resolved": [], "kept_for_human": [], "regenerated": [], "notes": [], "problems": [], "tests": [], "unmerged_other": []}
    um = unmerged(repo)
    skip = set()
    regen_snapshot = None
    for path, stages in sorted(um.items()):
        kind = kind_of(path)
        if kind is None:
            rep["unmerged_other"].append(path)
            continue
        if kind == "ps1sha":
            continue                                         # 內容由後面的重算決定（不合併）
        text, why = merge_conflicted(repo, path, stages)
        if text is None and path == SNAPSHOT and 2 in stages:
            regen_snapshot = stages                          # 快照可以重產：合併不出來就以我方為底，等程式碼合好後從程式碼重產
            continue
        if text is None:
            rep["kept_for_human"].append((path, why))
            skip.add(path)
            continue
        if not dry:
            (repo / path).write_bytes(text.encode("utf-8"))
            if add:
                git(repo, "add", "--", path)
        rep["resolved"].append((path, why))
    to_add = []
    if regen_snapshot is not None:
        if rep["unmerged_other"]:
            rep["kept_for_human"].append((SNAPSHOT, "快照兩邊衝突，等程式碼衝突解完後重跑本工具（會以我方為底、從程式碼重產）"))
            skip.add(SNAPSHOT)
        else:
            ours = blob_text(repo, regen_snapshot[2])
            if ours is None:
                rep["kept_for_human"].append((SNAPSHOT, "快照含 BOM／CRLF：請人看"))
                skip.add(SNAPSHOT)
            else:
                _write(repo, SNAPSHOT, ours, dry)
                to_add.append(SNAPSHOT)
                rep["resolved"].append((SNAPSHOT, "兩邊衝突 ⇒ 以我方為底，從合併後的程式碼重產"))
    if rep["unmerged_other"]:
        rep["notes"].append("還有程式碼／測試檔的衝突（%d 個）：先解完再重跑本工具，快照／路由／未範圍讀取的重算要等程式碼合好才準。"
                            % len(rep["unmerged_other"]))
    ps_changed, ps_prob = post_ps1(repo, dry, skip | set(rep["unmerged_other"])) if post else ([], [])
    rep["regenerated"] += ps_changed
    rep["problems"] += ps_prob
    if post:
        ch, pr = post_changelog_order(repo, dry, skip | set(rep["unmerged_other"]))
        rep["regenerated"] += ch
        rep["problems"] += pr
    if not post:
        pass
    elif not rep["unmerged_other"] and not rep["kept_for_human"]:
        for fn in (post_route_summary,):
            ch, pr = fn(repo, dry, skip)
            rep["regenerated"] += ch
            rep["problems"] += pr
        ch, pr, nt = post_unscoped(repo, dry, skip)
        rep["regenerated"] += ch; rep["problems"] += pr; rep["notes"] += nt
        ch, pr, nt = post_l1(repo, dry, skip)
        rep["regenerated"] += ch; rep["problems"] += pr; rep["notes"] += nt
    elif not rep["unmerged_other"]:
        rep["notes"].append("有基準檔留給人處理，所以先不重算依賴程式碼的衍生值；處理完再重跑。")
    if add and not dry:
        for rel in dict.fromkeys(rep["regenerated"] + to_add):
            if rel in skip or (rel == SNAPSHOT and any(x.startswith("L1") for x in rep["problems"])):
                continue                                     # 沒解完的不 add（留著讓人看得到還在衝突）
            git(repo, "add", "--", rel)
    if slow:
        rep["tests"] += regen_slow(repo, dry)
    if verify or slow:
        rep["tests"] += run_tests(repo, VERIFY_TESTS + (SLOW_TESTS if slow else ()), dry)
    return rep


def format_report(rep, dry):
    L = []
    tag = "（--check：只看，沒寫檔）" if dry else ""
    L.append("基準檔處理結果%s" % tag)
    for p, why in rep["resolved"]:
        L.append("  ✔ 已合併  %s —— %s" % (p, why))
    for p in rep["regenerated"]:
        L.append("  ✔ 已重算  %s" % p)
    for n in rep["notes"]:
        L.append("  ℹ %s" % n)
    for label, ok, tail in rep["tests"]:
        L.append("  %s 測試 %s：%s" % ("✔" if ok else ("–" if ok is None else "✘"), label, tail))
    todo = []
    for p, why in rep["kept_for_human"]:
        todo.append("%s —— %s" % (p, why))
    for p in rep["unmerged_other"]:
        todo.append("%s —— 程式碼／測試檔衝突（本工具不碰）" % p)
    todo += rep["problems"]
    todo += ["測試未過：%s —— %s" % (l, t) for l, ok, t in rep["tests"] if ok is False]
    if todo:
        L.append("要人處理（%d）：" % len(todo))
        L += ["  ✘ " + t for t in todo]
    else:
        L.append("沒有要人處理的項目。")
    return "\n".join(L), bool(todo)


def check_needed(rep):
    return bool(rep["resolved"] or rep["regenerated"] or rep["kept_for_human"] or rep["unmerged_other"] or rep["problems"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=None, help="要處理的樹（預設：目前所在目錄的 git 根；不是本檔所在的樹）")
    ap.add_argument("--check", action="store_true", help="只看，不寫檔")
    ap.add_argument("--no-add", action="store_true", help="只寫檔，不 git add")
    ap.add_argument("--no-post", action="store_true", help="只處理衝突中的檔，不做『從程式碼重算』那一半（快、不載入專案）")
    ap.add_argument("--verify", action="store_true", help="之後串列跑單檔測試確認（不含回應鍵集基準；那個要 --regen-slow）")
    ap.add_argument("--regen-slow", action="store_true", help="重錄 route_inventory endpoints 與 response_keys_baseline（開整個 app）")
    a = ap.parse_args(argv)
    if a.repo is None:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, encoding="utf-8")
        a.repo = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else str(REPO)
    try:
        rep = resolve(a.repo, dry=a.check, add=not a.no_add, verify=a.verify, slow=a.regen_slow, post=not a.no_post)
    except Exception as exc:                          # noqa: BLE001
        print("resolve_baselines 出錯：%r" % (exc,), file=sys.stderr)
        return 2
    text, todo = format_report(rep, a.check)
    print(text)
    if a.check:
        return 1 if check_needed(rep) else 0
    return 1 if todo else 0


if __name__ == "__main__":
    try:                                                              # 背景執行不彈視窗（tools/platform/nowindow.py；MOTRIX_SHOW_WINDOWS=1 可關）
        sys.path.insert(0, str(HERE))
        import nowindow as _nw
        _nw.install()
    except ImportError:
        pass
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
