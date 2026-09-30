# -*- coding: utf-8 -*-
"""去識別化段 1 契約題（SALE-PACKAGE-DEID.md §2.4.1／§9）：凍結 migration 改寫前後**行為等價**。

原則：**本檔不含任何本公司識別值。** 夾具需要的值一律在執行時從 git 歷史裡固定的舊版 db.py 取出（`tools/platform/own_payload.py`
的 `pinned_source()`／`extract()`，只在記憶體內用），舊函式也從同一份舊版原始碼取出來跑。

A 類（註解／docstring）  ⇒ 位元組碼（co_code＋排除 docstring 的 co_consts，遞迴）與舊版逐函式相同
B 類（比較條件）         ⇒ `_m008`、`_m106`：同一份夾具、固定時鐘，舊新跑完的資料表逐列相同；客戶／全新形狀新版不讀資料檔
C 類（要寫入的值）       ⇒ 開發者形狀需要資料檔（`@pytest.mark.needs_own_payload`）；缺檔／版本不符在**任何寫入之前**丟 `_FrozenOwnPayloadError`
"""
import ast
import contextlib
import datetime as _dt
import importlib.util
import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
sys.path.insert(0, str(REPO / "backend"))
import own_payload as OP  # noqa: E402

import db as NEW  # noqa: E402

M008 = "_m008_fix_legacy_owner_names"
M106 = "_m106_company_profile_identity_backfill"
#: 新版允許多出來的函式（去識別化的輔助）；其餘新增函式一律要有人決定
NEW_ONLY = {"_frozen_sha256", "_own_payload_path", "_frozen_own_payload", "_own_value", "_FrozenOwnPayloadError"}


@pytest.fixture(scope="module")
def old():
    src = OP.pinned_source(REPO)
    mod = types.ModuleType("_old_db_pinned")
    mod.__file__ = str(REPO / "backend" / "db.py")
    exec(compile(src, "old_db_pinned.py", "exec"), mod.__dict__)
    mod._src = src
    return mod


@pytest.fixture(scope="module")
def vals():
    return OP.extract(OP.pinned_source(REPO))[2]


# ── A 類 ────────────────────────────────────────────────────────────────────────

def _norm(code, doc_names):
    consts = []
    for i, c in enumerate(code.co_consts):
        if i == 0 and isinstance(c, str) and code.co_name in doc_names and c == doc_names[code.co_name]:
            continue                                            # docstring 排除
        consts.append(_norm(c, doc_names) if isinstance(c, types.CodeType) else c)
    return (code.co_code, code.co_names, code.co_varnames, tuple(consts))


def _functions(src):
    tree = ast.parse(src)
    docs = {n.name: ast.get_docstring(n, clean=False) for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and ast.get_docstring(n, clean=False)}
    mod = compile(src, "x.py", "exec")
    out = {}
    for c in mod.co_consts:
        if isinstance(c, types.CodeType):
            out[c.co_name] = _norm(c, docs)
    return out


def test_a_class_functions_have_identical_bytecode(old):
    """除了 `_m008`、`_m106`（B／C 類，H2R-S1 明列排除），每個 db.py 函式與舊版位元組碼相同——只改了註解／docstring。"""
    o, n = _functions(old._src), _functions((REPO / "backend" / "db.py").read_text(encoding="utf-8"))
    assert {M008, M106} <= set(o) and {M008, M106} <= set(n)
    changed = sorted(k for k in o if k not in (M008, M106) and (k not in n or o[k] != n[k]))
    assert changed == [], "位元組碼變了的函式（A 類只能改註解／docstring）：%s" % changed
    extra = sorted(set(n) - set(o) - NEW_ONLY)
    assert extra == [], "新版多出未登記的函式：%s" % extra


def test_sentinel_positive_control_bytecode_compare_detects_a_real_change(old):
    src = old._src.replace("def _m007_fix_legacy_display_names(conn):", "def _m007_fix_legacy_display_names(conn):\n    _x = 1", 1)
    assert _functions(old._src)["_m007_fix_legacy_display_names"] != _functions(src)["_m007_fix_legacy_display_names"]
    doc_only = old._src.replace("One-time: normalise display_name values", "One-time (改過的說明): normalise display_name values", 1)
    assert _functions(old._src)["_m007_fix_legacy_display_names"] == _functions(doc_only)["_m007_fix_legacy_display_names"]


# ── 夾具 ────────────────────────────────────────────────────────────────────────

class _FixedDT(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 30, 12, 0, 0)


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE customers (id INTEGER PRIMARY KEY, data_json TEXT);
        CREATE TABLE quotations (id INTEGER PRIMARY KEY, sales_person TEXT);
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, display_name TEXT, email TEXT);
        CREATE TABLE system_settings (key TEXT PRIMARY KEY, value_json TEXT, updated_at TEXT);
    """)
    return c


def _dump(c):
    out = {}
    for t, order in (("customers", "id"), ("quotations", "id"), ("users", "id"), ("system_settings", "key")):
        out[t] = [tuple(r) for r in c.execute("SELECT * FROM %s ORDER BY %s" % (t, order))]
    return out


def _m008_shapes(v):
    names = v["old_names"]
    u = v["username"]
    cj = lambda o: json.dumps({"ownerName": o}, ensure_ascii=False)
    fresh = {"customers": [], "quotations": [], "users": []}
    customer = {"customers": [(1, cj("someone else")), (2, cj(None)), (3, "{}"), (4, "not json"), (5, None), (6, cj(123))],
                "quotations": [(1, "someone else"), (2, None), (3, "")],
                "users": [(1, "admin", "Admin", ""), (2, "other", names[0] + " ", None), (3, "user3", "x", "x@example.com")]}
    developer = {"customers": [(1, cj(names[0])), (2, cj(names[-1])), (3, cj("keep")), (4, cj(names[1]))],
                 "quotations": [(1, names[0]), (2, names[-1]), (3, "keep"), (4, None)],
                 "users": [(1, u, names[0], ""), (2, u.upper(), names[0], ""), (3, "other", names[0], ""), (4, "zz", "zz", "")]}
    dev_email_null = {"customers": [], "quotations": [], "users": [(1, u, "already fine", None)]}
    dev_email_set = {"customers": [], "quotations": [], "users": [(1, u, names[2], "kept@example.com")]}
    edge = {"customers": [(1, cj(names[0] + " ")), (2, cj(names[0].lower() + "x"))],
            "quotations": [(1, names[0] + " "), (2, names[0].upper() if names[0].upper() != names[0] else names[0] + "!")],
            "users": [(1, u + " ", names[0], ""), (2, u.upper() + "x", names[0], "")]}
    #: 帳號相符但顯示名不是舊名、email 空 ⇒ 只有 email 那一支會動（也要資料檔）
    dev_edge = {"customers": [], "quotations": [], "users": [(1, u, "not legacy", "")]}
    return {"fresh": fresh, "customer": customer, "developer": developer, "dev_email_null": dev_email_null,
            "dev_email_set": dev_email_set, "edge": edge, "dev_edge": dev_edge}


def _load(c, shape):
    for r in shape["customers"]:
        c.execute("INSERT INTO customers (id, data_json) VALUES (?,?)", r)
    for r in shape["quotations"]:
        c.execute("INSERT INTO quotations (id, sales_person) VALUES (?,?)", r)
    for r in shape["users"]:
        c.execute("INSERT INTO users (id, username, display_name, email) VALUES (?,?,?,?)", r)
    c.commit()


@contextlib.contextmanager
def _fixed_clock(mod):
    saved = mod.datetime
    mod.datetime = _FixedDT
    try:
        yield
    finally:
        mod.datetime = saved


def _run(mod, name, shape, settings=None):
    with _fixed_clock(mod):
        return _run_inner(mod, name, shape, settings)


def _run_inner(mod, name, shape, settings=None):
    c = _conn()
    _load(c, shape)
    for k, val in (settings or {}).items():
        c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)", (k, val, "t"))
    c.commit()
    getattr(mod, name)(c)
    return _dump(c)


class _Boom(AssertionError):
    pass


# ── B 類：_m008 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("shape", ["fresh", "customer", "edge"])
def test_m008_no_match_shapes_are_identical_and_new_never_reads_the_payload(old, vals, monkeypatch, shape):
    """全新／客戶形狀（以及邊界：尾巴多一個空白、大小寫不同 ⇒ 都不命中）：舊新結果相同；新版**不讀資料檔**。"""
    def boom():
        raise _Boom("沒有命中的形狀不該讀 own 資料檔")
    monkeypatch.setattr(NEW, "_frozen_own_payload", boom)
    s = _m008_shapes(vals)[shape]
    assert _run(NEW, M008, s) == _run(old, M008, s)


@pytest.mark.needs_own_payload
@pytest.mark.parametrize("shape", ["developer", "dev_email_null", "dev_email_set", "dev_edge"])
def test_m008_developer_shapes_are_identical_to_the_old_behaviour(old, vals, shape):
    s = _m008_shapes(vals)[shape]
    got, want = _run(NEW, M008, s), _run(old, M008, s)
    assert got == want
    assert got != _dump_of(s), "夾具沒有真的觸發改寫（這題就驗不到東西）"


def _dump_of(shape):
    c = _conn()
    _load(c, shape)
    return _dump(c)


@pytest.mark.needs_own_payload
def test_m008_edge_shape_mixed_with_a_real_developer_row_still_matches_exactly(old, vals):
    s = _m008_shapes(vals)
    mix = {k: s["developer"][k] + s["edge"][k][:0] for k in s["developer"]}
    assert _run(NEW, M008, mix) == _run(old, M008, mix)


# ── B 類：_m106 ──────────────────────────────────────────────────────────────────

def _profiles(v):
    tid = v["tax_id"]
    base = {"name": "N", "tax_id": tid, "contact_info": "Tel: 04-1234-5678｜info@example.test", "company_name": "", "phone": "", "email": ""}
    other = dict(base, tax_id="12345675")
    return {"none": None, "other": json.dumps(other), "own": json.dumps(base), "own_spaces": json.dumps(dict(base, tax_id="  " + tid + " ")),
            "own_prefilled": json.dumps(dict(base, company_name="x", phone="y", email="z", company_name_en="e")),
            "other_type": json.dumps(dict(base, tax_id=12345675)), "own_as_number": json.dumps(dict(base, tax_id=int(tid) if tid.isdigit() else 1)),
            "bad_json": "{ not json"}


@pytest.mark.parametrize("which", ["none", "other", "other_type", "bad_json"])
def test_m106_non_own_profiles_are_identical_and_never_read_the_payload(old, vals, monkeypatch, which):
    def boom():
        raise _Boom("非本公司的資料列不該讀 own 資料檔")
    monkeypatch.setattr(NEW, "_frozen_own_payload", boom)
    p = _profiles(vals)[which]
    st = {} if p is None else {"company_profile": p}
    assert _run(NEW, M106, _m008_shapes(vals)["fresh"], st) == _run(old, M106, _m008_shapes(vals)["fresh"], st)


@pytest.mark.needs_own_payload
@pytest.mark.parametrize("which", ["own", "own_spaces", "own_prefilled", "own_as_number"])
def test_m106_own_profile_is_identical_to_the_old_behaviour_and_idempotent(old, vals, which):
    p = _profiles(vals)[which]
    fresh = _m008_shapes(vals)["fresh"]
    got, want = _run(NEW, M106, fresh, {"company_profile": p}), _run(old, M106, fresh, {"company_profile": p})
    assert got == want


# ── C 類：缺檔／版本不符 ⇒ 任何寫入之前丟例外 ────────────────────────────────────────

def _payload_error(monkeypatch, tmp_path, content):
    f = tmp_path / "p.json"
    if content is not None:
        f.write_text(content, encoding="utf-8")
    monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(f))


_FIELDS_OK = {"m008": {"correct": "x", "email": "y"}, "m106": {"company_name_en": "z"}}


@pytest.mark.parametrize("content", [None, "{ not json", json.dumps({"v": 1, "source_blob": "0" * 40, "m008": {}, "m106": {}}),
                                     json.dumps({"v": 2}), json.dumps([1]),
                                     # 欄位齊全、只有版本綁定不對：必須仍然被拒（突變「不驗 source_blob／v」要紅）
                                     json.dumps(dict(_FIELDS_OK, v=1, source_blob="0" * 40)),
                                     json.dumps(dict(_FIELDS_OK, v=2, source_blob=OP.PINNED_BLOB))])
def test_c_class_bad_or_missing_payload_raises_before_any_write(old, vals, monkeypatch, tmp_path, content):
    _payload_error(monkeypatch, tmp_path, content)
    s = _m008_shapes(vals)
    for name, shape, settings in ((M008, s["developer"], None), (M106, s["fresh"], {"company_profile": _profiles(vals)["own"]})):
        c = _conn()
        _load(c, shape)
        for k, val in (settings or {}).items():
            c.execute("INSERT INTO system_settings (key, value_json, updated_at) VALUES (?,?,?)", (k, val, "t"))
        c.commit()
        before = _dump(c)
        with _fixed_clock(NEW), pytest.raises(NEW._FrozenOwnPayloadError):
            getattr(NEW, name)(c)
        c.rollback()
        assert _dump(c) == before, "%s 在丟例外之前已經寫入" % name


def test_frozen_sha256_only_hashes_strings_like_the_original_comparisons():
    import hashlib
    assert NEW._frozen_sha256("abc") == hashlib.sha256(b"abc").hexdigest()
    assert NEW._frozen_sha256(None) is None and NEW._frozen_sha256(123) is None and NEW._frozen_sha256(b"abc") is None
    assert NEW._frozen_sha256("\ud800") == hashlib.sha256("\ud800".encode("utf-8", "surrogatepass")).hexdigest()


def test_the_payload_binding_constant_matches_the_pinned_blob():
    assert NEW._OWN_PAYLOAD_SOURCE_BLOB == OP.PINNED_BLOB


def test_hash_constants_in_db_match_the_pinned_values(vals):
    h = OP.extract(OP.pinned_source(REPO))[1]
    assert sorted(NEW._M008_OLD_NAME_SHA256) == h["m008_old_names"]
    assert NEW._M008_USERNAME_SHA256 == h["m008_username"] and NEW._M106_TAX_ID_SHA256 == h["m106_tax_id"]


def test_db_py_no_longer_contains_the_our_company_literals():
    """哨兵：既有的 `_our_company_literals` 掃描器對 db.py 命中 0（ALLOWED 的 db.py 各列同包降為 0）。"""
    spec = importlib.util.spec_from_file_location("_ocl_deid", REPO / "backend" / "tests" / "platform" / "_our_company_literals.py")
    ocl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ocl)
    hits = {k: v for k, v in ocl.scan(REPO).items() if k[0] == "backend/db.py"}
    assert hits == {}, "db.py 還有 %d 類命中：%s" % (len(hits), sorted(k[1] for k in hits))
