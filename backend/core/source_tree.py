# -*- coding: utf-8 -*-
"""守門測試要掃的原始碼範圍：唯一來源。

[單位] plat:source_tree    [層] L0    [穩定度] 契約（改介面照 PLAYBOOK §C-7 升版）
[公開介面] BACKEND, FRONTEND_PAGES, logic_files, module_dirs, module_installed, page_file, page_files, product_files, rel, router_files
[不變式] 「掃全部 router／邏輯檔」的守門一律從這裡取清單（模組搬進 modules/ 之後才不會安靜地少掃一塊）
[契約題] tests/platform/test_core_loader.py
[注意] 只給守門與工具用，產品碼不 import

模組搬進 `modules/<key>/` 之後，只掃 `routers/*.py` 的守門會**安靜地少掃一塊**
（斷言沒變、照樣綠，而被守的對象已經不在那裡）。所有「掃全部 router／邏輯檔」
的守門一律從這裡取清單。
"""
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def module_dirs():
    root = BACKEND / "modules"
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if (p / "module.json").is_file())


#: 模組內不算產品碼的子目錄（與 product_files() 同一份）
def _module_py(d):
    """模組資料夾底下所有層的 `*.py`，排除 tests／migrations 等非產品目錄。"""
    return sorted(p for p in d.rglob("*.py")
                  if not any(part in _NON_PRODUCT_DIRS + ("migrations",) for part in p.relative_to(d).parts))


def _is_api(d, p):
    """端點檔：`api.py`，或 CORE-SPEC §3 的 `api/` 目錄底下任一層的檔。"""
    rel = p.relative_to(d).parts
    return rel == ("api.py",) or rel[0] == "api"


def router_files():
    """定義 HTTP 端點的檔案：`routers/*.py` ＋ 各模組的 `api.py` 或 `api/` 底下的全部 `*.py`
    （稽核 Y-3：照 CORE-SPEC §3 用 `api/` 目錄的模組，原本會被靜默漏掉）。"""
    files = sorted((BACKEND / "routers").glob("*.py"))
    for d in module_dirs():
        files += [p for p in _module_py(d) if _is_api(d, p)]
    return files


def logic_files():
    """非端點的共用／業務邏輯：`helpers/*.py` ＋ 各模組所有層的 `*.py`（`service/` 等子目錄也算），
    扣掉端點檔（`api.py`、`api/`）與模組根的 `__init__.py`。"""
    files = sorted((BACKEND / "helpers").glob("*.py"))
    for d in module_dirs():
        files += [p for p in _module_py(d) if not _is_api(d, p) and p != d / "__init__.py"]
    return files


def rel(p) -> str:
    """相對 backend 的 POSIX 路徑，例：`routers/system.py`、`modules/tender_radar/api.py`。"""
    return Path(p).resolve().relative_to(BACKEND).as_posix()


#: 產品碼以外的 backend 子目錄（不隨產品執行路徑載入）
_NON_PRODUCT_DIRS = ("tests", "tools", "scripts", "migrations_frozen", "__pycache__")


def product_files():
    """全部產品碼：backend 根目錄 `*.py` ＋ `core/`、`routers/`、`helpers/` ＋ `modules/` 底下**所有層**的 `*.py`。

    與 `router_files()`／`logic_files()` 不同：這份含根目錄檔（db.py、archive.py…）與模組的子目錄
    （CORE-SPEC §3 `modules/<key>/api/`、`service/`）——「整個產品不可以出現 X」類守門用這份。
    """
    files = sorted(p for p in BACKEND.glob("*.py") if p.name != "conftest.py")  # conftest.py 在 backend/ 根（2026-09-25 自 tests/ 上移），是測試設定不是產品碼
    for sub in ("core", "routers", "helpers"):
        files += sorted((BACKEND / sub).glob("*.py"))
    root = BACKEND / "modules"
    if root.is_dir():
        files += sorted(p for p in root.rglob("*.py")
                        if not any(part in _NON_PRODUCT_DIRS for part in p.relative_to(root).parts))
    return files


# ── 前端頁面（階段 C／C2，docs/platform/STAGE-C-DESIGN.md）──────────────────
# 頁面會從 frontend/pages/ 逐模組搬進 modules/<key>/pages/（對外 URL 不變）。
# ☠️ 讀頁面原始碼的測試與工具一律從這裡取路徑：自己拼 `frontend/pages/x.html` 的，頁面搬走後會
#    找不到檔（紅，還好）；自己 glob `frontend/pages/*.html` 的，會**安靜地少掃搬走的那些**（綠，最糟）。
#    守門：tests/platform/test_page_paths_centralized.py（寫死的位置只准變少）。

#: L1 頁面（以及還沒搬家的模組頁面）所在
# 從 core.paths 取，不用 __file__ 推（test_no_file_relative_data_paths；全量抓到）
from core import paths as _paths  # noqa: E402
FRONTEND_PAGES = Path(_paths.FRONTEND_PAGES_DIR)


def _page_map():
    import json
    from core import pages
    manifests = {d.name: (json.loads((d / "module.json").read_text(encoding="utf-8")), d) for d in module_dirs()}
    return pages.build_page_map(manifests, FRONTEND_PAGES)


def page_file(name):
    """頁面檔名（`x.html`）⇒ 實體路徑，不論模組啟用與否（讀原始碼用）。找不到 ⇒ FileNotFoundError。"""
    from core import pages
    if not pages.valid_name(name):
        raise FileNotFoundError("不是合法的頁面檔名：%r" % (name,))
    hit = next((v for k, v in _page_map().items() if k.lower() == name.lower()), None)
    if hit is not None:
        return hit[1]
    p = FRONTEND_PAGES / name
    if p.is_file():
        return p
    raise FileNotFoundError("找不到頁面 %s（frontend/pages 與各模組 pages/ 都沒有）" % name)


def page_files():
    """全部頁面檔（frontend/pages/*.html ∪ modules/*/pages/*.html），依檔名排序。"""
    files = list(FRONTEND_PAGES.glob("*.html"))
    for d in module_dirs():
        files += list((d / "pages").glob("*.html"))
    return sorted(files, key=lambda p: p.name.lower())


def module_installed(path) -> bool:
    """`modules/<key>/…`（可帶 `backend/` 前綴、正反斜線皆可）⇒ 那個模組資料夾在不在；其他路徑一律 True。

    給「清單列著模組的檔案／端點」的守門用：模組被拿掉（產品選配、PLAYBOOK §B 步驟 11 反向控制）時，
    它的條目本來就不在，不算幽靈；模組在的時候照常比對。"""
    parts = str(path).replace(chr(92), "/").split("/")
    if "modules" not in parts:
        return True
    i = parts.index("modules")
    if i + 1 >= len(parts):
        return True
    return (BACKEND / "modules" / parts[i + 1]).is_dir()
