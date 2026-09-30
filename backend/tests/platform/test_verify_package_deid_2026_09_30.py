# -*- coding: utf-8 -*-
"""去識別化 S6：`verify_package.py::check_deid`——deploy_manifest 的 audience／deid 與包內容一致。

沿用 test_verify_package_2026_09_23 的做法：在暫存包目錄上直接呼叫檢查函式，讀 `Report` 的 fails。
"""
import importlib.util
import json
import os
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_vp_deid", BACKEND / "tools" / "verify_package.py")
VP = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VP)
SALE_CFG = json.loads((BACKEND.parent / "product" / "sale_prune.json").read_text(encoding="utf-8"))


def _gates(pkg):
    old = VP.R
    VP.R = VP.Report()
    try:
        VP.check_deid(str(pkg))
        return [(g, d) for g, d in VP.R.fails]
    finally:
        VP.R = old


def _pkg(tmp_path, manifest, files=()):
    root = tmp_path / "pkg"
    root.mkdir(parents=True)
    if manifest is not None:
        (root / "deploy_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for rel in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n", encoding="utf-8")
    return root


def _sale_files():
    return ["product/sale_prune.json"]


def _write_cfg(root):
    (root / "product" / "sale_prune.json").write_text(json.dumps(SALE_CFG), encoding="utf-8")


SALE = {"audience": "sale", "deid": {"audience": "sale", "hits": 0, "canary": True}, "env": {"python": ""}}
OWN = {"audience": "own", "deid": {"audience": "own", "hits": None}, "env": {"python": "C:/py/python.exe"}}


def test_legacy_manifest_without_audience_is_only_a_warning(tmp_path, capsys):
    assert _gates(_pkg(tmp_path, {"commit": "abc"})) == []
    assert "舊格式" in capsys.readouterr().out


def test_missing_manifest_is_skipped_not_failed(tmp_path):
    assert _gates(_pkg(tmp_path, None)) == []


@pytest.mark.parametrize("man", [{"audience": "both", "deid": {"audience": "both"}}, {"audience": "sale"},
                                 {"audience": "sale", "deid": {"audience": "own"}}, {"audience": "own", "deid": "x"}])
def test_invalid_or_inconsistent_audience_is_a_failure(tmp_path, man):
    assert _gates(_pkg(tmp_path, man))


def test_own_package_needs_the_payload_file(tmp_path):
    assert _gates(_pkg(tmp_path, OWN)), "own 包缺資料檔要擋"
    ok = _pkg(tmp_path / "ok", OWN, ["backend/migrations_frozen/own_payload.json"])
    assert _gates(ok) == []


def test_sale_package_clean_passes(tmp_path):
    root = _pkg(tmp_path, SALE, _sale_files())
    _write_cfg(root)
    assert _gates(root) == []


@pytest.mark.parametrize("mutate", ["payload", "hits", "canary", "python", "forbidden_docs", "forbidden_root", "no_cfg"])
def test_sale_package_problems_are_failures(tmp_path, mutate):
    man = json.loads(json.dumps(SALE))
    files = list(_sale_files())
    if mutate == "payload":
        files.append("backend/migrations_frozen/own_payload.json")
    elif mutate == "hits":
        man["deid"]["hits"] = 3
    elif mutate == "canary":
        man["deid"]["canary"] = False
    elif mutate == "python":
        man["env"]["python"] = "C:/Users/dev/python.exe"
    elif mutate == "forbidden_docs":
        files.append("docs/windows/STATE.md")
    elif mutate == "forbidden_root":
        files.append("NEXT-SESSION.md")
    elif mutate == "no_cfg":
        files = []
    root = _pkg(tmp_path, man, files)
    if mutate != "no_cfg":
        _write_cfg(root)
    assert _gates(root), mutate


def test_glob_semantics_match_the_projection_tool():
    g = VP._glob_re
    assert g("docs/**").match("docs/a/b.md") and g("*.md").match("a.md") and not g("*.md").match("d/a.md")
    assert g("backend/tests/**").match("backend/tests/x/y.py") and not g("backend/tests/**").match("backend/testsx/y.py")


def test_verify_package_main_calls_the_deid_check_last():
    src = (BACKEND / "tools" / "verify_package.py").read_text(encoding="utf-8")
    assert src.count("\n    check_deid(pkg)\n") == 1 and src.index("\n    check_deid(pkg)\n") > src.index("check_product_selection(pkg)\n")
