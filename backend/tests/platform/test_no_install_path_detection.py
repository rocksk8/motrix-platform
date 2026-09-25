# -*- coding: utf-8 -*-
"""守門：產品碼不可以用安裝路徑判定正式機（2026-09-25 使用者裁示）。

`\\V9.0\\` 判定讓「新版裝在別的路徑」＝正式機靜默停信；產品會賣給客戶自架，路徑本來就不固定。
⇒ 產品碼（`core.source_tree.product_files()`）的**程式碼與字串常值**出現 `V9.0` 就紅。
   註解與 docstring 不算（歷史說明要能寫）。
⇒ 非 Python 的腳本：只有白名單裡的**部署腳本**可以出現（它們本來就只在正式機跑，而且是人手動執行的）。

⚙️ 反向控制：白名單每一筆必須真的含 `V9.0`（過期的一筆＝紅）、只能是 .bat/.ps1/.vbs；
   偵測器對 V9 原版 email_notify 的寫法必須報出來。
"""
import ast
import io
import tokenize

from core import source_tree

NEEDLE = "V9.0"

#: 部署腳本（正式機上由人執行；不在產品執行路徑）
DEPLOY_SCRIPTS = frozenset({
    "autostart.bat",
    "autostart_hidden.vbs",
    "setup_autostart_task.ps1",
    "setup_heartbeat_task.ps1",
    "tools/apply_update.ps1",
    "tools/check_prod_drift.ps1",
    "tools/rollback_update.ps1",
    "tools/_dashboard_remote.ps1",
})


def _docstring_nodes(tree):
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def find_hits(src: str):
    """程式碼與非 docstring 字串常值中的 V9.0（行號）。註解由 tokenize 剝掉。"""
    tree = ast.parse(src)
    docs = _docstring_nodes(tree)
    hits = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and NEEDLE in n.value and id(n) not in docs]
    # 不在字串裡的（例：拼在 f-string 以外的名字不可能含 '.'，但保險起見掃非註解 token）
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING) and NEEDLE in tok.string:
            hits.append(tok.start[0])
    return sorted(set(hits))


V9_EMAIL_NOTIFY = '''
def _is_production_install() -> bool:
    """只認 C:\\\\Users\\\\Motrix\\\\Desktop\\\\V9.0 這個安裝路徑"""
    here = os.path.abspath(__file__).replace("/", "\\\\")
    return "\\\\V9.0\\\\" in here
'''


def test_positive_control_v9_email_notify_is_caught():
    assert find_hits(V9_EMAIL_NOTIFY) == [5]            # docstring 那一行不算，判定那一行算


def test_comments_and_docstrings_are_allowed():
    src = '"""原本只認 \\\\V9.0\\\\ 路徑"""\n# 歷史：\\V9.0\\ 判定已移除\nx = 1\n'
    assert find_hits(src) == []


def test_product_python_has_no_install_path_detection():
    bad = []
    for p in source_tree.product_files():
        for line in find_hits(p.read_text(encoding="utf-8")):
            bad.append("%s:%d" % (source_tree.rel(p), line))
    assert not bad, ("產品碼出現 %s（安裝路徑判定正式機）：\n  " % NEEDLE + "\n  ".join(bad)
                     + "\n⇒ 改用明確旗標（例：email 的 .no_email_send／MOTRIX_EMAIL_SEND）。")


def _scripts():
    b = source_tree.BACKEND
    files = [p for ext in ("*.bat", "*.ps1", "*.vbs") for p in b.glob(ext)]
    files += [p for ext in ("*.bat", "*.ps1", "*.vbs") for p in (b / "tools").glob(ext)]
    return files


def _read(p):
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp950"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def test_non_python_scripts_only_deploy_scripts_mention_install_path():
    bad = [source_tree.rel(p) for p in _scripts()
           if NEEDLE in _read(p) and source_tree.rel(p) not in DEPLOY_SCRIPTS]
    assert not bad, "非部署腳本出現 %s：%s" % (NEEDLE, bad)


def test_deploy_whitelist_is_live_and_scripts_only():
    by_rel = {source_tree.rel(p): p for p in _scripts()}
    stale = [r for r in DEPLOY_SCRIPTS if r not in by_rel or NEEDLE not in _read(by_rel[r])]
    assert not stale, "白名單過期（檔案不存在或已不含 %s）：%s" % (NEEDLE, stale)
    assert all(r.endswith((".bat", ".ps1", ".vbs")) for r in DEPLOY_SCRIPTS)
