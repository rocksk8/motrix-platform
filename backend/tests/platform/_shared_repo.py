# -*- coding: utf-8 -*-
"""「讀整個真實 repo」的守門題共用的唯讀資料（2026-11-13 chore/test-prune，D3＋D7）。

原本每個檔（甚至每個 module scope 夾具）各自把 backend 全部 .py 讀進來、parse 成 AST，再逐模組重掃；同一輪全量裡
同一份原始碼被讀、parse 十幾次。這裡讓**每個行程（xdist worker）只做一次**：

- `ST`：tools/platform/ship_tier.py 只載入一份（各檔原本各載一份，類別不同 ⇒ 已解析檔不能互通）。
- `real_sources()`：{repo 相對路徑: 原始碼}，backend 底下所有 .py（不含 __pycache__）。**唯讀，不要改它。**
- `new_real_repo()`：回**全新的** `ST.Repo`（自己的 used_const_nodes／used_arg_nodes），底層「已解析檔」（_File）共用。
  ⚠️ 不共用 Repo 物件本身：used_* 集合會隨掃描累積，stray_capability_strings 把它們當「已解析的取用」放行，
  共用會讓前一題的掃描替後一題放行（漏抓）。_File 建好後不會被改，所以共用安全。
  ⚠️ 只給「來源就是真實 repo」的 Repo 用：_File 以 rel 為鍵，合成來源的 Repo 不能拿這個字典。
"""
import functools
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


@functools.lru_cache(maxsize=None)
def _ship_tier():
    spec = importlib.util.spec_from_file_location("_ship_tier_shared", REPO / "tools" / "platform" / "ship_tier.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ST = _ship_tier()


@functools.lru_cache(maxsize=None)
def real_sources():
    src = {}
    for p in (REPO / "backend").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        src[p.relative_to(REPO).as_posix()] = p.read_text(encoding="utf-8")
    return src


_SHARED_FILES = {}                                      # rel ⇒ _File；Repo.file() 會懶加載進來


def new_real_repo():
    return ST.Repo(real_sources(), files=_SHARED_FILES)
