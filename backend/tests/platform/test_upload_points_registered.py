# -*- coding: utf-8 -*-
"""上傳點登記守門（附件目錄 P2，設計 proposal-attachments-search-preview §4-5／§7；docs/platform/upload_points.json）。

- 掃描產品碼所有路由處理函式：參數含 `UploadFile`、呼叫 `save_document_files`／`request.form()`、或內文有 `data:image/` ⇒
  必須在 `upload_points.json`（新增上傳端點沒登記 ⇒ 紅）；json 裡的端點必須還存在（不留死列；擁有模組不在時略過）。
- 分類三種：`catalog`（source_type 必須被某個 `attachments.catalog` 提供者的 `CATEGORIES` 認領）、`excluded`（要有理由）、
  `pending`（已決定要進、尚未做）。
- 提供者的 `CATEGORIES` 兩兩不重疊；每個在場提供者的每個 category 都有上傳點餵它（不留沒人餵的類別）。
- 正對照：真實掃描必須看得到已知端點；反向控制：合成原始碼／合成 json。"""
import ast
import json
from pathlib import Path

from core import source_tree

REPO = Path(__file__).resolve().parents[3]
POINTS = REPO / "docs" / "platform" / "upload_points.json"
_METHODS = {"get", "post", "put", "patch", "delete"}


def scan_upload_routes(files_src):
    """{相對路徑: 原始碼} ⇒ {"METHOD /路徑": (檔, 函式, [偵測原因])}。"""
    out = {}
    for rel, src in files_src.items():
        tree = ast.parse(src)
        prefixes = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                f = n.value.func
                if (getattr(f, "id", "") or getattr(f, "attr", "")) == "APIRouter":
                    for kw in n.value.keywords:
                        if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                            for t in n.targets:
                                if isinstance(t, ast.Name):
                                    prefixes[t.id] = kw.value.value
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            routes = []
            for d in fn.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in _METHODS and d.args
                        and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str)):
                    base = d.func.value.id if isinstance(d.func.value, ast.Name) else ""
                    routes.append("%s %s%s" % (d.func.attr.upper(), prefixes.get(base, ""), d.args[0].value))
            if not routes:
                continue
            why = set()
            for a in list(fn.args.args) + list(fn.args.kwonlyargs):
                if a.annotation is not None and "UploadFile" in ast.unparse(a.annotation):
                    why.add("UploadFile")
            for n in ast.walk(fn):
                if isinstance(n, ast.Call):
                    name = getattr(n.func, "attr", "") or getattr(n.func, "id", "")
                    if name == "save_document_files":
                        why.add("save_document_files")
                    if name == "form" and isinstance(n.func, ast.Attribute):
                        why.add("request.form")
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and "data:image/" in n.value:
                    why.add("data:image")
            if why:
                for r in routes:
                    out[r] = (rel, fn.name, sorted(why))
    return out


def problems(found, points, installed=lambda key: True):
    """found＝掃到的端點、points＝json 的 points ⇒ 問題清單（空＝通過）。"""
    bad = []
    for ep, (rel, fn, why) in sorted(found.items()):
        if ep not in points:
            bad.append("上傳端點 %s（%s:%s，%s）沒有登記在 upload_points.json" % (ep, rel, fn, "/".join(why)))
    for ep, p in sorted(points.items()):
        kinds = [k for k in ("catalog", "excluded", "pending") if k in p]
        if len(kinds) != 1 or not str(p[kinds[0]]).strip():
            bad.append("%s：分類必須剛好一種（catalog／excluded／pending）且不可空白（excluded／pending 要有理由）" % ep)
        if ep not in found and installed(p.get("module", "")):
            bad.append("%s 已經不是上傳端點（過期，刪掉這一列）" % ep)
    return bad


def catalog_problems(points, categories_by_provider, installed=lambda key: True):
    """`categories_by_provider`＝{提供者: set(source_type)}（在場的模組）⇒ 問題清單。"""
    bad = []
    seen = {}
    for prov, cats in sorted(categories_by_provider.items()):
        for c in sorted(cats):
            if c in seen:
                bad.append("source_type %s 被 %s 與 %s 同時認領（兩兩不可重疊）" % (c, seen[c], prov))
            seen[c] = prov
    for ep, p in sorted(points.items()):
        if "catalog" in p and installed(p.get("module", "")) and p["catalog"] not in seen:
            bad.append("%s 登記為 catalog:%s，但沒有任何 attachments.catalog 提供者認領它" % (ep, p["catalog"]))
    fed = {p["catalog"] for p in points.values() if "catalog" in p}
    for c, prov in sorted(seen.items()):
        if c not in fed:
            bad.append("提供者 %s 的 category %s 沒有任何上傳點餵它（upload_points.json 沒有 catalog:%s）" % (prov, c, c))
    return bad


def _real_sources():
    return {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files()
            if "/tests/" not in source_tree.rel(p)}


def _points():
    return json.loads(POINTS.read_text(encoding="utf-8"))["points"]


def _installed(key):
    return key in ("", "L1") or source_tree.module_installed("modules/%s/" % key)


def _providers():
    from core import registry
    from helpers import uploads
    return registry.providers(uploads.ATTACHMENTS_CATALOG)


def test_every_upload_endpoint_is_registered(client):
    found = scan_upload_routes(_real_sources())
    # 正對照：掃描真的看得到各種寫法（掃不到東西時「沒有違規」是假綠）
    assert "POST /api/work-logs/{wid}/photos" in found and "PUT /api/settings/branding/{kind}" in found, sorted(found)
    if source_tree.module_installed("modules/case/"):
        assert "POST /api/quotations/{quote_no}/signed-files" in found and "POST /api/completion-notes/{note_no}/signed-files" in found
    if source_tree.module_installed("modules/accounting/"):
        assert "POST /api/vouchers/{voucher_id}/attachments" in found          # request.form 寫法
    bad = problems(found, _points(), _installed)
    assert not bad, "\n".join(bad)


def test_catalog_providers_cover_registry(client):
    cats = {}
    for key, prov in _providers().items():
        cats[key] = set(getattr(prov, "CATEGORIES", {}) or {})
        for c, info in prov.CATEGORIES.items():
            assert {"label", "doc", "module"} <= set(info), (key, c)
    assert cats, "沒有任何 attachments.catalog 提供者"
    bad = catalog_problems(_points(), cats, _installed)
    assert not bad, "\n".join(bad)


def test_voucher_module_tuple_matches_api():
    """attachments_catalog 複製了 `_VOUCHER_MODULES`（L2 之間不互 import，傳票 API 是同模組但避免循環）：兩份要一致。"""
    if not source_tree.module_installed("modules/accounting/"):
        return
    from modules.accounting import attachments_catalog as cat
    from modules.accounting.api import vouchers
    assert tuple(cat._VOUCHER_MODULES) == tuple(vouchers._VOUCHER_MODULES)


# ── 反向控制（合成資料）────────────────────────────────────────────────────

_SRC = ("from fastapi import APIRouter, UploadFile\n"
        "router = APIRouter(prefix='/api/zz')\n"
        "@router.post('/{id}/files')\n"
        "async def up(id: int, files: list[UploadFile]):\n    pass\n"
        "@router.get('/{id}')\ndef read(id):\n    return 1\n")


def test_rc_unregistered_upload_endpoint_is_red():
    found = scan_upload_routes({"modules/zz/api.py": _SRC})
    assert list(found) == ["POST /api/zz/{id}/files"]                     # prefix 有併進路徑；GET 不算
    assert problems(found, {}) and "沒有登記" in problems(found, {})[0]
    assert problems(found, {"POST /api/zz/{id}/files": {"module": "zz", "excluded": "暫存"}}) == []


def test_rc_detects_form_save_and_data_image_styles():
    src = ("@router.post('/a')\nasync def a(request):\n    f = await request.form()\n"
           "@router.post('/b')\ndef b(files):\n    return save_document_files('x', '1', files, 'u')\n"
           "@router.post('/c')\ndef c():\n    return 'data:image/png;base64,xx'\n")
    found = scan_upload_routes({"x.py": src})
    assert {k: v[2] for k, v in found.items()} == {"POST /a": ["request.form"], "POST /b": ["save_document_files"],
                                                   "POST /c": ["data:image"]}


def test_rc_dead_row_and_bad_classification():
    pts = {"POST /gone": {"module": "zz", "excluded": "x"}, "POST /b": {"module": "zz"},
           "POST /c": {"module": "zz", "excluded": "x", "catalog": "t"}, "POST /d": {"module": "zz", "excluded": " "}}
    bad = problems({}, pts)
    assert any("過期" in b and "/gone" in b for b in bad)
    assert sum("分類必須剛好一種" in b for b in bad) == 3
    assert problems({}, {"POST /gone": {"module": "zz", "excluded": "x"}}, installed=lambda k: False) == []   # 模組不在＝略過


def test_rc_catalog_overlap_unclaimed_and_unfed():
    pts = {"POST /a": {"module": "m1", "catalog": "t1"}}
    assert catalog_problems(pts, {"m1": {"t1"}}) == []
    assert any("同時認領" in b for b in catalog_problems(pts, {"m1": {"t1"}, "m2": {"t1"}}))
    assert any("沒有任何 attachments.catalog 提供者認領" in b for b in catalog_problems(pts, {}))
    assert any("沒有任何上傳點餵它" in b for b in catalog_problems(pts, {"m1": {"t1", "t2"}}))
    assert catalog_problems(pts, {}, installed=lambda k: False) == []       # 擁有模組不在 ⇒ 不要求有提供者
