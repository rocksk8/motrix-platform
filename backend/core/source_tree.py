# -*- coding: utf-8 -*-
"""守門測試要掃的原始碼範圍：唯一來源。

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


def router_files():
    """定義 HTTP 端點的檔案：`routers/*.py` ＋ 各模組的 `api.py`。"""
    files = sorted((BACKEND / "routers").glob("*.py"))
    files += [d / "api.py" for d in module_dirs() if (d / "api.py").is_file()]
    return files


def logic_files():
    """非端點的共用／業務邏輯：`helpers/*.py` ＋ 各模組除 `api.py`、`__init__.py` 以外的檔。"""
    files = sorted((BACKEND / "helpers").glob("*.py"))
    for d in module_dirs():
        files += sorted(p for p in d.glob("*.py") if p.name not in ("api.py", "__init__.py"))
    return files


def rel(p) -> str:
    """相對 backend 的 POSIX 路徑，例：`routers/system.py`、`modules/tender_radar/api.py`。"""
    return Path(p).resolve().relative_to(BACKEND).as_posix()
