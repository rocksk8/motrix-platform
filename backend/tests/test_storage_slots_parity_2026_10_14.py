# -*- coding: utf-8 -*-
"""BP-4 S1：位置代號登錄表與 `save_document_files(policy=...)` 的同一性守門（設計 BP4-STORAGE-NOTIFY-DESIGN §3.5／§3.6）。

要證明的事：
1. 旗標 `builder_slots.enabled` 預設 0；內建政策逐碼等於**獨立寫死在本檔**的今天常數（副檔名、件數、合計上限）。
2. 每個寫入點（AST 掃描全 repo 的 `save_document_files(` 第一個引數）都落在登錄表內；掃描器有正對照。
3. 路徑黃金表：每個管理中的位置代號 ⇒ `uploads/<代號>/<單號>`；待核准暫存前綴與 demo 前綴維持原樣。
4. `policy=None` 與 `policy=builtin_policy(code)` 逐碼：回傳 metadata 形狀、磁碟上的檔案路徑、被拒絕的情況全部相同（真的存檔到暫存根）。
5. 政策只能縮小：硬底線擋 .exe／.html；子夾多一層、metadata 帶 slot；代號與資料夾對不上 ⇒ ValueError。
"""
import ast
import asyncio
import io
import os
import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from helpers import storage_slots as SS
from helpers import uploads as U

BACKEND = Path(__file__).resolve().parents[1]

# ── 獨立寫死的「今天的行為」（不從被測模組導出，否則等於自己驗自己） ──────────────────────────
BASE_EXTS = {".jpg", ".jpeg", ".png", ".pdf"}
EXPECTED_EXTRA = {"voucher_attachments": {".docx", ".xlsx", ".doc", ".xls"}, "case_extra_expense": {".heic", ".heif"}}
MANAGED = ["quotations", "quotation_payment_items", "quotation_materials", "quotation_materials_invoices", "case_updates",
           "case_extra_expense", "completion_notes", "shipping_notes", "invoice_vouchers", "contractor_dispatches",
           "contractor_dispatch_invoices", "dev_logs", "custom_records", "voucher_attachments"]
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _upload(name, data=PDF):
    return UploadFile(io.BytesIO(data), filename=name, headers=Headers({"content-type": "application/octet-stream"}))


# ── 1. 旗標與內建政策 ─────────────────────────────────────────────────────────
def test_flag_defaults_to_off_and_registry_matches_managed_codes():
    assert SS.enabled() is False
    assert [c for c, loc in SS.LOCATION_CODES.items() if loc.managed] == MANAGED
    assert all(not loc.managed for c, loc in SS.LOCATION_CODES.items() if c not in MANAGED)


@pytest.mark.parametrize("code", MANAGED)
def test_builtin_policy_equals_todays_constants(code):
    p = SS.builtin_policy(code)
    assert set(p.accept) == BASE_EXTS | EXPECTED_EXTRA.get(code, set())
    if code == "case_extra_expense":
        assert (p.max_files, p.max_request_bytes) == (10, 50 * 1024 * 1024)
    else:
        assert (p.max_files, p.max_request_bytes) == (0, 0)
    assert p.builtin and not p.subfolder and not p.slot and p.folder == code
    assert set(p.accept) <= SS.HARD_EXTS


def test_hard_floor_excludes_dangerous_types():
    for bad in (".html", ".htm", ".svg", ".js", ".exe", ".bat", ".ps1", ".py", ".php", ".aspx", ".dll", ".lnk", ".zip"):
        assert bad not in SS.HARD_EXTS


def test_policy_by_doc_type_is_builtin_and_unknown_doc_type_is_an_error():
    assert SS.policy("completion_note") == SS.builtin_policy("completion_notes")
    with pytest.raises(KeyError):
        SS.policy("no_such_doc")


# ── 2. 全 repo 的寫入點都在登錄表內（有正對照） ────────────────────────────────────────
def _call_site_codes(source):
    out = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == "save_document_files" and node.args:
                a = node.args[0]
                if isinstance(a, ast.Constant) and isinstance(a.value, str):
                    out.add(a.value)
                elif isinstance(a, ast.JoinedStr) and a.values and isinstance(a.values[0], ast.Constant):
                    out.add(a.values[0].value.rstrip("/"))
                else:
                    out.add("<dynamic>")
    return out


def test_scanner_positive_control():
    assert _call_site_codes("await save_document_files('x_unknown', 'n', f)") == {"x_unknown"}
    assert _call_site_codes('await save_document_files(f"_pending_case_changes/{i}", "n", f)') == {"_pending_case_changes"}
    assert _call_site_codes("await u.save_document_files(code, 'n', f)") == {"<dynamic>"}


def test_every_call_site_uses_a_registered_code():
    seen = set()
    for p in BACKEND.rglob("*.py"):
        rel = p.relative_to(BACKEND).as_posix()
        if "/tests/" in rel or rel.startswith(("tests/", "tools/")) or ".venv" in rel or rel == "helpers/uploads.py":
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "save_document_files" in src:
            seen |= _call_site_codes(src)
    assert seen, "掃描器沒有找到任何呼叫點（掃描壞了）"
    unknown = sorted(c for c in seen if c not in SS.LOCATION_CODES and c != SS.STAGING_PREFIX)
    assert not unknown, "這些寫入點的資料夾沒有登錄為位置代號：%s" % unknown
    assert set(MANAGED) <= seen | {"voucher_attachments"}


# ── 3. 路徑黃金表 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("code", MANAGED)
def test_path_golden_table(code):
    got = Path(U._safe_save_dir(code, "D-1")).relative_to(U.UPLOADS_ROOT).as_posix()      # noqa: SLF001
    assert got == "%s/D-1" % code
    assert SS.resolve_code(code) == code


def test_staging_prefix_and_demo_prefix_keep_their_shape():
    assert SS.resolve_code("_pending_case_changes/12") == "_pending_case_changes"
    assert Path(U._safe_save_dir("_pending_case_changes/12", "Q-1_0")).relative_to(U.UPLOADS_ROOT).as_posix() == "_pending_case_changes/12/Q-1_0"   # noqa: SLF001
    assert SS.resolve_code("nope") == ""


# ── 4. 真的存檔：policy=None 與 builtin policy 逐碼相同 ────────────────────────────────
def _tree(root):
    return sorted(str(p.relative_to(root)).replace(os.sep, "/").rsplit("/", 1)[0] for p in Path(root).rglob("*") if p.is_file())


def _save(root, monkeypatch, code, doc, filename, policy):
    monkeypatch.setattr(U, "UPLOADS_ROOT", str(root))
    return asyncio.run(U.save_document_files(code, doc, [_upload(filename)], "tester", policy=policy))


@pytest.mark.parametrize("code", MANAGED)
def test_policy_none_and_builtin_policy_write_the_same_files(code, tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    ma = _save(a, monkeypatch, code, "D-9", "x.pdf", None)
    mb = _save(b, monkeypatch, code, "D-9", "x.pdf", SS.builtin_policy(code))
    assert _tree(a) == _tree(b) == ["%s/D-9" % code] and len(ma) == len(mb) == 1
    strip = lambda m: re.sub(r"[0-9a-f]{16}", "<uuid>", m["path"])           # noqa: E731
    assert strip(ma[0]) == strip(mb[0]) == "%s/D-9/<uuid>.pdf" % code
    assert set(ma[0]) == set(mb[0])                                          # metadata 鍵完全相同（內建政策不帶 slot）


@pytest.mark.parametrize("code", ["quotations", "voucher_attachments", "case_extra_expense"])
def test_rejections_are_identical(code, tmp_path, monkeypatch):
    for n, fname in enumerate(("x.exe", "x.html", "x.docx", "x.heic", "x.pdf.exe")):
        outs = []
        for pol in (None, SS.builtin_policy(code)):
            d = tmp_path / ("r%d_%d" % (n, len(outs))); d.mkdir()
            try:
                _save(d, monkeypatch, code, "D-1", fname, pol)
                outs.append(("saved", _tree(d)))
            except HTTPException as e:
                outs.append((e.status_code, str(e.detail), _tree(d)))
        assert outs[0] == outs[1], (code, fname, outs)


def test_case_extra_expense_count_limit_is_the_same(tmp_path, monkeypatch):
    for pol in (None, SS.builtin_policy("case_extra_expense")):
        monkeypatch.setattr(U, "UPLOADS_ROOT", str(tmp_path))
        with pytest.raises(HTTPException) as e:
            asyncio.run(U.save_document_files("case_extra_expense", "D-1", [_upload("a.pdf")], "t", existing_count=10, policy=pol))
        assert e.value.status_code == 400 and "10" in e.value.detail


# ── 5. 政策只能縮小 ───────────────────────────────────────────────────────────
def test_policy_can_narrow_but_never_exceed_the_hard_floor(tmp_path, monkeypatch):
    wide = SS.SlotPolicy(code="completion_notes", folder="completion_notes", accept=frozenset({".pdf", ".exe", ".html"}))
    with pytest.raises(HTTPException):                       # .exe 不在硬底線 ⇒ 即使政策寫了也收不到
        _save(tmp_path, monkeypatch, "completion_notes", "N-1", "x.exe", wide)
    narrow = SS.SlotPolicy(code="completion_notes", folder="completion_notes", accept=frozenset({".pdf"}))
    with pytest.raises(HTTPException):                       # 政策只收 pdf ⇒ jpg 被擋（今天的白名單會收）
        _save(tmp_path, monkeypatch, "completion_notes", "N-1", "x.jpg", narrow)


def test_subfolder_adds_one_level_and_slot_is_recorded(tmp_path, monkeypatch):
    pol = SS.SlotPolicy(code="completion_notes", folder="completion_notes", accept=frozenset({".pdf"}), subfolder="驗收單", slot="accept", builtin=False)
    m = _save(tmp_path, monkeypatch, "completion_notes", "N-1", "x.pdf", pol)
    assert _tree(tmp_path) == ["completion_notes/驗收單/N-1"]
    assert m[0]["slot"] == "accept" and m[0]["path"].startswith("completion_notes/驗收單/N-1/")


def test_code_and_folder_mismatch_is_a_programming_error(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        _save(tmp_path, monkeypatch, "quotations", "Q-1", "x.pdf", SS.builtin_policy("completion_notes"))
    assert _tree(tmp_path) == []


def test_traversal_in_policy_subfolder_is_still_refused(tmp_path, monkeypatch):
    for bad in ("..", "a/b", "a\\b", "C:x"):
        pol = SS.SlotPolicy(code="completion_notes", folder="completion_notes", accept=frozenset({".pdf"}), subfolder=bad, builtin=False)
        with pytest.raises(HTTPException):
            _save(tmp_path, monkeypatch, "completion_notes", "N-1", "x.pdf", pol)
    assert _tree(tmp_path) == []
