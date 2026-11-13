# -*- coding: utf-8 -*-
"""「讀整個真實 repo」的守門題共用的唯讀資料（2026-11-13 chore/test-prune，D3＋D7）。

原本每個檔（甚至每個 module scope 夾具）各自把 backend 全部 .py 讀進來、parse 成 AST，再逐模組重掃；同一輪全量裡
同一份原始碼被讀、parse 十幾次。這裡讓**原始碼每個行程（xdist worker）只讀一次、解析後的檔每個測試模組只做一次**（解析後約 1 GB，模組結束即釋放）：

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

def release_parsed_files():
    """放掉已解析的檔（約 1 GB）。tests/platform/conftest.py 的 module 夾具在每個測試模組結束時呼叫；
    之後再 new_real_repo() 會懶加載重 parse（只是慢一次，結果相同）。原始碼字串（約 60 MB）與 dep_scan 圖不放。"""
    _SHARED_FILES.clear()



def new_real_repo():
    return ST.Repo(real_sources(), files=_SHARED_FILES)


# ── 真實 repo 的 dep_scan 圖（D6／D7）：每個行程只掃一次 ──────────────────────────────────────────
# dep_scan.build() 約 12～15 秒；test_module_boundaries／test_generated_maps／test_route_ownership／_boundaries.scan_units
# 各自掃（有的一個檔掃三次）。同一個行程內原始碼不變 ⇒ 只算一次，之後給深拷貝（呼叫端會改 dict）。
# ⚠️ 只快取「真實 repo」（ROOT＝REPO）；合成樹（use_root／build_synthetic）與沙盒複本的掃描一律照舊直接 build，不經這裡。
_GRAPH = {}


def real_dep_graph(dep_scan=None):
    """真實 repo 的 dep_scan.build() 結果（深拷貝）。dep_scan 的 ROOT 不是真實 repo（合成樹／沙盒）⇒ 不快取，直接 build。"""
    import copy
    ds = dep_scan
    if ds is not None and Path(getattr(ds, "ROOT", REPO)).resolve() != REPO.resolve():
        return ds.build()
    if "g" not in _GRAPH:
        if ds is None:
            spec = importlib.util.spec_from_file_location("_platform_dep_scan_shared", REPO / "tools" / "platform" / "dep_scan.py")
            ds = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(ds)
        _GRAPH["g"] = ds.build()
    return copy.deepcopy(_GRAPH["g"])


# ── modtest 的現算 test_map／dep_graph（D4）：每個行程只算一次 ───────────────────────────────────
# modtest.load_map()（約 25 秒）＋load_graph()（約 15 秒）是現場掃整棵樹；測 modtest 本身的題（select／main）每一題都各算一次。
# 這些題驗的是「選題邏輯」，不是「掃描器」（掃描器由 test_generated_maps／test_dep_scan_* 守）⇒ 吃同一份真實 repo 的現算結果即可。
_MAPS = {}


def patch_real_maps(monkeypatch, mt):
    """把 mt（modtest 模組）的 load_map／load_graph 換成「真實 repo 的現算結果、每個行程只算一次、每次給深拷貝」的版本。
    use_files=True（讀產生檔）照舊；其餘行為與原函式一致（失敗退讀檔的邏輯也在原函式裡，第一次呼叫時照走）。"""
    import copy
    real_map, real_graph = mt.load_map, mt.load_graph

    def load_map(use_files=False):
        if use_files:
            return real_map(use_files)
        if "map" not in _MAPS:
            _MAPS["map"] = real_map(False)
        return copy.deepcopy(_MAPS["map"])

    def load_graph(use_files=False):
        if use_files:
            return real_graph(use_files)
        if "graph" not in _MAPS:
            _MAPS["graph"] = real_graph(False)
        return copy.deepcopy(_MAPS["graph"])
    monkeypatch.setattr(mt, "load_map", load_map)
    monkeypatch.setattr(mt, "load_graph", load_graph)
