# -*- coding: utf-8 -*-
"""跨檔守門的檔名樣式（唯一一份：guard_patterns.json）的載入與比對。作者端守門集（author_gate A2）與增量選題底板共用。

  import guard_patterns as GP
  GP.patterns()                       ⇒ 樣式 glob 的 tuple
  GP.match_files(tree_files)          ⇒ git tree 檔案清單裡符合樣式的測試檔（排序）
  GP.problems(data)                   ⇒ 資料本身的問題清單（空＝合格）
負責人 a3；回放驗證 d7。"""
import fnmatch
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
JSON_PATH = HERE / "guard_patterns.json"
_ROOT_CACHE = {}


def load(path=None):
    return json.loads(Path(path or JSON_PATH).read_text(encoding="utf-8"))


def patterns(data=None):
    return tuple(p["glob"] for p in (data or load())["patterns"])


def _root_res(data):
    key = tuple(data["roots"])
    if key not in _ROOT_CACHE:
        _ROOT_CACHE[key] = [re.compile("^" + re.escape(r).replace(r"\*", "[^/]+") + "/") for r in key]
    return _ROOT_CACHE[key]


def is_test_file(path, data=None):
    p = path.replace("\\", "/")
    return p.rsplit("/", 1)[-1].startswith("test_") and p.endswith(".py") and any(r.match(p) for r in _root_res(data or load()))


def match_files(tree_files, data=None, pats=None):
    d = data or load()
    pats = tuple(pats) if pats is not None else patterns(d)
    return sorted({f.replace("\\", "/") for f in tree_files
                   if is_test_file(f, d) and any(fnmatch.fnmatch(f.replace("\\", "/").rsplit("/", 1)[-1], p) for p in pats)})


def problems(data):
    out = []
    if data.get("version") != 1:
        out.append("version 必須是 1")
    if not data.get("roots") or not all(isinstance(r, str) and r.startswith("backend/") for r in data["roots"]):
        out.append("roots 必須是 backend/ 底下的路徑樣式清單")
    seen = set()
    for i, p in enumerate(data.get("patterns") or []):
        g, why = (p or {}).get("glob"), (p or {}).get("why")
        if not g or not isinstance(g, str) or "*" not in g:
            out.append("patterns[%d].glob 要是含 * 的字串" % i)
        elif g in seen:
            out.append("patterns[%d] 重複：%s" % (i, g))
        seen.add(g)
        if not why or not str(why).strip():
            out.append("patterns[%d]（%s）沒有 why" % (i, g))
    for g in data.get("static_in_e2e_named") or []:
        if g not in seen:
            out.append("static_in_e2e_named 的 %s 不在 patterns 裡" % g)
    if not data.get("patterns"):
        out.append("patterns 不可為空")
    return out
