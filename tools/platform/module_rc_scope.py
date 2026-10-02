"""單一模組真刪（反向控制，PLAYBOOK §B-11）的選題：模組 <key> 不在的樹上，要跑哪些測試檔。

為什麼要有（B，2026-09-28）：原本靠人手 grep「模組路徑／requires_module」，漏掉**只靠資料依賴模組**的題——
例：accounting 的傳票 e2e 自己塞 `quotations`、點 `data-testid=src-case`，沒有一個字提到 `modules/case`，
M01 不在時逾時紅，卻不在選題裡（B41 真刪 M01 時 4 題被別的條件順帶選到才發現；同型另有 7 題完全沒選到）。

選題＝`tests/platform`（整個目錄）＋下列任一條件成立的測試檔（`backend/tests/**`、`backend/modules/*/tests/**`，
扣掉 `modules/<key>/` 自己——它跟著模組一起不在）：
  path     提到模組的程式：`modules.<key>` ／ `modules/<key>`
  mark     `requires_module("<key>"` ／ `skip_module_unless("<key>"` ／ `module_installed("modules/<key>`
  api      字串裡有模組宣告的 API 前綴（module.json `provides.api_prefixes`）
  table    SQL 讀寫模組宣告的表（module.json `data.tables[].name` ∪ `tables`）：`INSERT INTO／UPDATE／DELETE FROM／FROM／JOIN <表>`
  fixture  用到會寫那些表的 fixture（各 conftest.py 裡 @pytest.fixture 函式的原始碼符合 table 條件）
訊號全部取自模組**自己的宣告**（module.json），不列舉題目名稱 ⇒ 新題不必登記就會被選到。
頁面選擇器（`data-testid=src-case`）沒有宣告可以對照，不當訊號；這類題幾乎都會塞資料，由 table／fixture 抓到。

用法（repo 根目錄，或 --repo 指一棵樹；模組資料夾不在的 sparse 樹也可以——module.json 改從 git HEAD 讀）：
  python tools/platform/module_rc_scope.py <key>            一行一個路徑（相對 backend/），可直接接在 pytest 後面
  python tools/platform/module_rc_scope.py <key> --why      每個檔附上命中的條件
輸出不含模組自己的 tests/；找不到 module.json（工作樹與 git HEAD 都沒有）⇒ exit 2（不猜）。
"""
import argparse
import ast
import json
import re
import subprocess
import sys
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def load_manifest(repo, key):
    """模組的 module.json：工作樹有就讀工作樹，沒有（sparse 樹）就讀 git HEAD；都沒有 ⇒ None。"""
    rel = "backend/modules/%s/module.json" % key
    p = Path(repo) / rel
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    r = subprocess.run(["git", "-C", str(repo), "show", "HEAD:" + rel], capture_output=True, text=True, encoding="utf-8")
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def signals(manifest, key):
    """module.json ⇒ {"api": [...], "tables": [...]}（排序、去重）。"""
    prov = (manifest or {}).get("provides") or {}
    data = (manifest or {}).get("data") or {}
    tables = set(manifest.get("tables") or []) if manifest else set()
    tables |= {t["name"] for t in data.get("tables") or [] if isinstance(t, dict) and t.get("name")}
    return {"api": sorted(set(prov.get("api_prefixes") or [])), "tables": sorted(tables)}


def _patterns(key, sig):
    k = re.escape(key)
    pats = {
        "path": re.compile(r"modules[./]%s\b" % k),
        "mark": re.compile(r"""(?:requires_module|skip_module_unless)\(\s*["']%s["']|module_installed\(\s*["']modules/%s\b""" % (k, k)),
    }
    if sig["api"]:
        pats["api"] = re.compile("|".join(re.escape(a) + r"(?![\w-])" for a in sig["api"]))
    if sig["tables"]:
        pats["table"] = re.compile(r"(?i)\b(?:INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM|FROM|JOIN)\s+[\"'`]?(?:%s)\b(?![\w-])"
                                   % "|".join(re.escape(t) for t in sig["tables"]))
    return pats


def _test_files(backend, key):
    own = (backend / "modules" / key).resolve()
    roots = [backend / "tests"] + sorted((backend / "modules").glob("*/tests"))
    for root in roots:
        for p in sorted(root.rglob("*.py")):
            if "__pycache__" in p.parts or own in p.resolve().parents:
                continue
            yield p


def seeding_fixtures(backend, table_pat):
    """各 conftest.py 裡、原始碼符合 table 條件的 @pytest.fixture 名稱。"""
    names = set()
    if table_pat is None:
        return names
    for cf in [backend / "conftest.py"] + sorted(backend.rglob("tests/**/conftest.py")):
        if not cf.is_file() or "__pycache__" in cf.parts:
            continue
        src = cf.read_text(encoding="utf-8")
        for node in ast.walk(_parse(src)):
            if isinstance(node, ast.FunctionDef) and any("fixture" in ast.unparse(d) for d in node.decorator_list):
                if table_pat.search(ast.get_source_segment(src, node) or ""):
                    names.add(node.name)
    return names


def _parse(src):
    with warnings.catch_warnings():          # 題目檔裡的無效跳脫字元（既有）不是本工具的事
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(src)


def _uses_fixture(src, names):
    if not names:
        return False
    try:
        tree = _parse(src)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if {a.arg for a in node.args.args + node.args.kwonlyargs} & names:
                return True
    return False


def select(repo, key):
    """⇒ (manifest 是否找到, [(相對 backend/ 的路徑, [命中條件])])；第一項永遠是 tests/platform。"""
    repo = Path(repo)
    backend = repo / "backend"
    manifest = load_manifest(repo, key)
    if manifest is None:
        return False, []
    sig = signals(manifest, key)
    pats = _patterns(key, sig)
    fixtures = seeding_fixtures(backend, pats.get("table"))
    out = [("tests/platform", ["always"])]
    for p in _test_files(backend, key):
        rel = p.relative_to(backend).as_posix()
        if rel.startswith("tests/platform/"):
            continue
        src = p.read_text(encoding="utf-8", errors="replace")
        why = [name for name, pat in pats.items() if pat.search(src)]
        if _uses_fixture(src, fixtures):
            why.append("fixture")
        if why:
            out.append((rel, why))
    return True, out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("key")
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--why", action="store_true")
    a = ap.parse_args(argv)
    found, rows = select(a.repo, a.key)
    if not found:
        print("找不到模組 %s 的 module.json（工作樹與 git HEAD 都沒有）" % a.key, file=sys.stderr)
        return 2
    for rel, why in rows:
        print("%s\t%s" % (rel, ",".join(why)) if a.why else rel)
    return 0


if __name__ == "__main__":
    try:                                                              # 背景執行不彈視窗（tools/platform/nowindow.py；MOTRIX_SHOW_WINDOWS=1 可關）
        import sys as _s, pathlib as _p
        _s.path.insert(0, str(_p.Path(__file__).resolve().parents[1] / "tools" / "platform"))
        import nowindow as _nw
        _nw.install()
    except ImportError:
        pass
    sys.exit(main())
