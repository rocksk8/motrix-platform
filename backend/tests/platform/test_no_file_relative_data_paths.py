# -*- coding: utf-8 -*-
"""守門：產品碼不可以用 `__file__` 算資料路徑（DATA-COMPAT §2、§4 A-1）。

唯一例外是 `core/paths.py`。其餘檔案若把 `__file__`（或由它推出來的名字）跟一個字串組成路徑，
而那個字串不是程式碼目錄名 ⇒ 紅。

🔑 判準用**白名單**（程式碼目錄名）而不是黑名單（資料名稱）：資料名稱列不完，
   漏掉的永遠是沒有人想到的那一個；程式碼目錄只有幾個，而且列得出來。
⚙️ 反向控制：
   ① 正對照——偵測器對 V9 原版的 7 類寫法（逐字取自 c83dae6e）必須全部報出來；
   ② 白名單不可以含資料名稱（否則可以靠「把資料目錄加進白名單」變綠）。

範圍：`core.source_tree.product_files()`（含 modules/ 各層）。
"""
import ast
import textwrap

import pytest

from core import source_tree

ALLOWED_FILE = "core/paths.py"
#: 可以跟 __file__ 組合的字串：只限程式碼目錄
CODE_DIR_NAMES = frozenset({"modules", "routers", "helpers", "core"})


def _mentions(node, names):
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id in names:
            return True
    return False


def _strings(node):
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _is_path_build(node):
    """os.path.join(...)／Path(...)／.joinpath(...)／a / b"""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return [node.left, node.right]
    if isinstance(node, ast.Call):
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
        if name in ("join", "Path", "joinpath", "PurePath"):
            return list(node.args)
    return None


def find_violations(src: str):
    """回 [(行號, 違規字串)]。`__file__` 與由它賦值出來的名字（遞移）都算。"""
    tree = ast.parse(src)
    tainted = {"__file__"}
    changed = True
    while changed:                                  # 賦值鏈遞移到不動點
        changed = False
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and _mentions(n.value, tainted):
                for t in n.targets:
                    for x in ast.walk(t):
                        if isinstance(x, ast.Name) and x.id not in tainted:
                            tainted.add(x.id)
                            changed = True
    out = []
    for n in ast.walk(tree):
        parts = _is_path_build(n)
        if not parts or not any(_mentions(p, tainted) for p in parts):
            continue
        bad = [s for p in parts for s in _strings(p) if s not in CODE_DIR_NAMES]
        if bad:
            out.append((n.lineno, bad))
    return out


# ── 正對照：V9 原版寫法（c83dae6e，逐字）────────────────────────────────────
V9_SAMPLES = {
    "db.py": 'DB_PATH      = os.path.join(os.path.dirname(__file__), "motrix_erp.db")\n',
    "pdf_gen.py（多行）": textwrap.dedent('''
        _PDF_BASE_DEFAULT = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "報價單PDF",
        )
    '''),
    "archive.py（遞移）": textwrap.dedent('''
        _BACKEND_DIR      = os.path.dirname(os.path.abspath(__file__))
        _PROJECT_ROOT     = os.path.dirname(_BACKEND_DIR)
        _ALERT_DIR        = os.path.join(_PROJECT_ROOT, "backup_alerts")
    '''),
    "photos.py": '_PHOTO_UPLOAD_BASE = os.path.join(os.path.dirname(__file__), "..", "uploads", "projects")\n',
    "payslips.py": '_ARCHIVE_DIR = os.path.join(os.path.dirname(__file__), "..", "export_archive")\n',
    "daily_tasks.py": textwrap.dedent('''
        _CERT_PATH = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "certs", "cert.pem"
        )
    '''),
    "uploads.py（realpath 包一層）":
        "UPLOADS_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), '..', '..', 'uploads'))\n",
    "pathlib 寫法": 'BASE = Path(__file__).resolve().parent.parent\nDB = BASE / "motrix_erp.db"\n',
}


@pytest.mark.parametrize("name", sorted(V9_SAMPLES))
def test_positive_control_v9_patterns_are_caught(name):
    assert find_violations(V9_SAMPLES[name]), "偵測器漏報 V9 原版寫法：%s" % name


def test_code_dir_joins_are_not_flagged():
    """core/loader.py、core/source_tree.py 的寫法：組的是程式碼目錄，不是資料。"""
    src = ('MODULES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "modules")\n'
           'BACKEND = Path(__file__).resolve().parent.parent\nR = BACKEND / "routers"\n'
           'sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n')
    assert find_violations(src) == []


def test_allowlist_holds_no_data_names():
    data_like = ("upload", "pdf", "archive", "backup", "log", "cert", "db", "data", "export", "config", "front")
    assert not [n for n in CODE_DIR_NAMES if any(d in n.lower() for d in data_like)]


def test_product_code_has_no_file_relative_data_paths():
    bad = []
    for p in source_tree.product_files():
        rel = source_tree.rel(p)
        if rel == ALLOWED_FILE:
            continue
        for line, strs in find_violations(p.read_text(encoding="utf-8")):
            bad.append("%s:%d %s" % (rel, line, strs))
    assert not bad, (
        "產品碼用 __file__ 算資料路徑（模組搬家時會靜默指到新的空位置）：\n  " + "\n  ".join(bad)
        + "\n⇒ 改從 core.paths 取；新的資料位置加在 core/paths.py 並補 tests/platform/test_core_paths.py。")


def test_scan_covers_the_known_callers():
    """範圍守門：被改掉的那幾個檔必須在掃描範圍內（守門對象被搬走時這裡先紅）。"""
    rels = {source_tree.rel(p) for p in source_tree.product_files()}
    for must in ("db.py", "archive.py", "pdf_gen.py", "photos.py", "modules/payroll/api/payslips.py",
                 "helpers/system_checks.py", "helpers/uploads.py", "core/paths.py"):
        assert must in rels, must
