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


# ── autostart.bat 依 audience 分流（sale 是客戶範本；own 維持嚴格檢查）──────────────────────────────

TEMPLATE = BACKEND.parent / "product" / "sale_files" / "autostart.bat"
OWN_STYLE = ('@echo off\nset MOTRIX_TENDER_RADAR=1\nset MOTRIX_GEO=1\ncd /d "C:\srv\erp\backend"\n')


def _autostart_gates(tmp_path, audience, text):
    root = tmp_path / "pkg"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / "autostart.bat").write_text(text, encoding="utf-8")
    if audience:
        (root / "deploy_manifest.json").write_text(json.dumps({"audience": audience}), encoding="utf-8")
    old = VP.R
    VP.R = VP.Report()
    try:
        VP.check_autostart(str(root))
        return [g for g, _ in VP.R.fails]
    finally:
        VP.R = old


def test_the_shipped_sale_template_passes_the_sale_check_and_fails_the_own_check(tmp_path):
    text = TEMPLATE.read_text(encoding="utf-8")
    assert _autostart_gates(tmp_path / "a", "sale", text) == []
    assert _autostart_gates(tmp_path / "b", "own", text), "own 的嚴格檢查（開關必須開、路徑必須絕對）不可以被範本滿足"
    assert _autostart_gates(tmp_path / "c", None, text), "舊格式（沒有 audience）視為 own"


def test_an_own_style_autostart_passes_own_and_fails_sale(tmp_path):
    assert _autostart_gates(tmp_path / "a", "own", OWN_STYLE) == []
    assert _autostart_gates(tmp_path / "b", None, OWN_STYLE) == []
    gates = _autostart_gates(tmp_path / "c", "sale", OWN_STYLE)
    assert "autostart 開關" in gates and "autostart 路徑" in gates


@pytest.mark.parametrize("mutate,expect", [
    (lambda t: t + "set MOTRIX_GEO=1\n", "autostart 開關"),
    (lambda t: t + "set MOTRIX_TENDER_RADAR=1\n", "autostart 開關"),
    (lambda t: t.replace('cd /d "%~dp0"', 'cd /d "C:\srv\erp\backend"'), "autostart 路徑"),
    (lambda t: t.replace('cd /d "%~dp0"', "rem no cd"), "autostart 路徑"),
    (lambda t: t + 'echo C:' + chr(92) + 'Users' + chr(92) + 'someone' + chr(92) + 'Desktop' + chr(10), "autostart 路徑"),
])
def test_sale_check_reverse_controls(tmp_path, mutate, expect):
    assert expect in _autostart_gates(tmp_path, "sale", mutate(TEMPLATE.read_text(encoding="utf-8")))


def test_commented_switches_do_not_count_as_enabled(tmp_path):
    text = TEMPLATE.read_text(encoding="utf-8")
    assert ":: set MOTRIX_GEO=1" in text and ":: set MOTRIX_TENDER_RADAR=1" in text
    assert _autostart_gates(tmp_path, "sale", text) == []


def test_template_is_ascii_only_and_has_no_company_data():
    raw = TEMPLATE.read_bytes()
    assert all(b < 128 for b in raw), "範本刻意只用 ASCII（cmd 在 chcp 之前就會讀到內容）"
    for needle in (b"Motrix", b"miactw", b"172.16", b"C:\Users"):
        assert needle not in raw
