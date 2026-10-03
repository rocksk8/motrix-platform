# -*- coding: utf-8 -*-
"""test_map／dep_graph 現場計算結果的內容簽章快取（T35 L3'；開發者互動呼叫用，建包／列車／最終閘門一律不用）。

為什麼：modtest 每次呼叫都現場重算 test_map＋dep_graph（純 CPU 掃描，這棵樹約 41 秒）；同一棵樹上 author_gate → modtest →
建包前預演會重算好幾次，tests/platform 裡 5 題以上的真樹呼叫也各付一次。

失敗模式只有一種而且很糟：**陳舊的圖 ⇒ 該選的題沒選 ⇒ 假綠燈**。所以這裡的規則是「懷疑就重算」：
  1. 簽章 = 內容 sha256（不是 mtime／size）：涵蓋 dep_scan 與 test_map 實際讀的每個檔——
     backend/**/*.py、frontend/**/*.html／*.js（dep_scan 走檔案系統 rglob，**含被 .gitignore 的檔**，所以不能只看 git status）、
     `git ls-files --cached --others --exclude-standard` 列出的每個檔（test_map 的輸入），以及 tools/platform/*.py（算圖的工具原始碼，
     工具一改就 miss）。檔名集合本身也進簽章 ⇒ 刪除、改名、新增都會 miss。
  2. 另含：repo 根絕對路徑（兩棵 worktree 同內容也不共用）、Python 主次版本、本模組的格式版號。
  3. 任何讀／寫／解析錯誤 ⇒ 重算（現行行為）。寫入是 tmp＋os.replace（原子）。
  4. 位置 %TEMP%\\motrix-map-cache（固定小名稱），只留最近 KEEP 份，不會變成下一個暫存肥大來源。
  5. MOTRIX_MAP_CACHE=0 ⇒ 完全不讀不寫。建包（build_deploy_package.ps1）、build_test_reuse run-stage、modtest --full／--train
     會明確設 0（不靠簽章本身）；modtest --refresh-map ⇒ 不讀、仍寫（強制刷新）。
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORMAT = 1
KEEP = 8
ENV_FLAG = "MOTRIX_MAP_CACHE"
_stats = {"hit": 0, "miss": 0, "bypass": 0}
#: 同一個 CLI 行程內只掃一次輸入檔內容（modtest main 開啟；行程內不會改檔）。預設關：函式庫式呼叫（測試）每次都重算簽章。
MEMO = False
_memo = {}


def enabled():
    return os.environ.get(ENV_FLAG, "1") != "0"


def cache_dir():
    return Path(tempfile.gettempdir()) / "motrix-map-cache"


def stats():
    return dict(_stats)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _file_digest(p):
    try:
        return _sha(Path(p).read_bytes())
    except OSError:
        return "MISSING"


def _input_files(root):
    """簽章涵蓋的檔（絕對路徑，排序）。"""
    root = Path(root)
    files = set()
    for pat_root, pats in ((root / "backend", ("*.py",)), (root / "frontend", ("*.html", "*.js"))):
        if pat_root.is_dir():
            for pat in pats:
                files.update(p for p in pat_root.rglob(pat) if p.is_file())
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, check=True).stdout
    files.update(root / p for p in out.decode("utf-8").split("\0") if p)
    files.update(HERE.glob("*.py"))
    return sorted(files, key=lambda p: p.as_posix())


def _inputs_digest(root):
    if MEMO and root in _memo:
        return _memo[root]
    h = hashlib.sha256()
    for p in _input_files(root):
        try:
            name = p.resolve().relative_to(root).as_posix()
        except ValueError:
            name = "ABS:" + p.as_posix()
        h.update(name.encode("utf-8") + b"\x1f" + _file_digest(p).encode("ascii") + b"\x1f")
    d = h.hexdigest()
    if MEMO:
        _memo[root] = d
    return d


def signature(kind, root):
    """⇒ sha256 十六進位；讀不到任何東西時丟例外（呼叫端轉成重算）。"""
    root = Path(root).resolve()
    h = hashlib.sha256()
    h.update(("%d|%s|%d.%d|%s\x1f" % (FORMAT, kind, sys.version_info[0], sys.version_info[1], root.as_posix())).encode("utf-8"))
    h.update(_inputs_digest(root).encode("ascii"))
    return h.hexdigest()


def _prune(d):
    try:
        entries = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in entries[KEEP:]:
            p.unlink(missing_ok=True)
        for p in d.glob("*.tmp*"):
            if p.stat().st_mtime < _now() - 3600:
                p.unlink(missing_ok=True)
    except OSError:
        pass


def _now():
    import time
    return time.time()


def get_or_compute(kind, compute, root, refresh=False):
    """cache 有效 ⇒ 回快取；否則 compute() 並寫入。任何例外 ⇒ 直接 compute()（行為同沒有快取）。"""
    if not enabled():
        _stats["bypass"] += 1
        return compute()
    try:
        sig = signature(kind, root)
        d = cache_dir()
        path = d / ("%s-%s.json" % (kind, sig[:24]))
        if not refresh and path.is_file():
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
                if rec.get("sig") == sig and rec.get("kind") == kind and rec.get("v") == FORMAT:
                    _stats["hit"] += 1
                    try:
                        os.utime(path)           # 最近使用：_prune 留得住
                    except OSError:
                        pass
                    return rec["data"]
            except (OSError, ValueError, KeyError):
                pass                              # 壞檔 ⇒ 重算
    except Exception:                             # noqa: BLE001 — 簽章算不出來 ⇒ 不碰快取
        _stats["bypass"] += 1
        return compute()
    _stats["miss"] += 1
    data = compute()
    try:
        if json.loads(json.dumps(data)) != data:      # 不是純 JSON 型別（tuple／set…）⇒ 回放後型別會變，不快取
            return data
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / ("%s-%s.tmp%d" % (kind, sig[:24], os.getpid()))
        tmp.write_text(json.dumps({"v": FORMAT, "kind": kind, "sig": sig, "data": data}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        _prune(d)
    except Exception:                             # noqa: BLE001 — 寫不進去不影響結果
        pass
    return data
