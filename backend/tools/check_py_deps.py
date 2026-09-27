# -*- coding: utf-8 -*-
"""建包前的依賴檢查：這支 Python 是否滿足 backend/requirements.txt＋requirements-dev.txt 的**版本規格**。

用法：python backend/tools/check_py_deps.py [requirements 檔 ...]      （不給 ⇒ 上述兩份）
exit 0＝全部滿足；1＝有沒裝或版本不符（逐條列出）；2＝requirements 檔讀不到或寫法解析不了。

為什麼（2026-09-27，IMPROVEMENT-REPORT §6 第 3 項）：build_deploy_package.ps1 原本只檢查「import 得到」，
而這台機器 PATH 第一支是別的工具（hermes-agent）的 venv——什麼都 import 得到、版本卻不是我們要的 ⇒ D7 建包挑到它。
只用標準庫＋packaging（沒有獨立安裝就用 pip 內附的那份）；輸出只用 ASCII（PS 5.1 會用系統 locale 解讀子行程輸出）。
"""
import importlib.metadata as md
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_FILES = (HERE.parent / "requirements.txt", HERE.parent / "requirements-dev.txt")


def _packaging():
    try:
        from packaging.requirements import Requirement
        from packaging.version import InvalidVersion, Version
    except ImportError:                                      # 沒有獨立安裝 packaging ⇒ pip 內附的那份
        from pip._vendor.packaging.requirements import Requirement
        from pip._vendor.packaging.version import InvalidVersion, Version
    return Requirement, Version, InvalidVersion


def _norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def read_requirements(paths):
    """回 `[(「檔名:行號」, 需求字串)]`；註解、空行、`-r`／`--` 選項行略過。"""
    out = []
    for p in paths:
        p = Path(p)
        for i, raw in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if line and not line.startswith("-"):
                out.append(("%s:%d" % (p.name, i), line))
    return out


def installed_versions():
    out = {}
    for d in md.distributions():
        name = d.metadata["Name"]
        if name:
            out.setdefault(_norm(name), d.version)
    return out


def problems(reqs, installed):
    """`installed`：{正規化套件名: 版本字串}。回不滿足的項目（空＝全部滿足）；環境標記不適用的需求略過。"""
    Requirement, Version, InvalidVersion = _packaging()
    out = []
    for where, line in reqs:
        r = Requirement(line)
        if r.marker is not None and not r.marker.evaluate():
            continue
        v = installed.get(_norm(r.name))
        want = str(r.specifier) or "any version"
        if v is None:
            out.append("%s %s: not installed (need %s)" % (where, r.name, want))
            continue
        try:
            ok = not r.specifier or r.specifier.contains(Version(v), prereleases=True)
        except InvalidVersion:
            ok = False
        if not ok:
            out.append("%s %s: installed %s, need %s" % (where, r.name, v, want))
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    paths = [Path(a) for a in argv] or list(DEFAULT_FILES)
    try:
        reqs = read_requirements(paths)
        extra = os.environ.get("MOTRIX_DEPS_EXTRA_REQUIREMENT", "").strip()
        if extra:                                            # 乾跑驗證用：多加一條需求（例 httpx2>=999 ⇒ 每一支都該被判不合格）
            reqs.append(("MOTRIX_DEPS_EXTRA_REQUIREMENT", extra))
        bad = problems(reqs, installed_versions())
    except Exception as e:                                   # noqa: BLE001 — 讀不到／解析不了 ⇒ 不合格，不是略過
        print("cannot check requirements: %s: %s" % (type(e).__name__, e))
        return 2
    for b in bad:
        print(b)
    if not bad:
        print("ok: %d requirements satisfied (%s)" % (len(reqs), sys.executable))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
