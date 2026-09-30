# -*- coding: utf-8 -*-
"""去識別化：本公司兩個舊預設密碼不在程式庫，改放 own 資料檔的 `auth.legacy_weak_passwords`（使用者裁示 2026-09-30）。

契約（主持裁示）：本公司環境（有資料檔）`_LEGACY_WEAK_PASSWORDS` 與 `is_weak_password` 的行為與舊版完全相同；
客戶環境（沒有資料檔）其餘清單照常、且不丟例外；程式庫任何 .py 都不含這兩個值。

值只在記憶體裡出現：從固定的舊版 auth.py（git 歷史）取出來比對，不寫進本檔、不印出。
題目用子行程 import（`helpers.auth` 的清單是 import 當下決定的），以環境變數 MOTRIX_OWN_PAYLOAD 換資料檔。
"""
import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
sys.path.insert(0, str(REPO / "tools" / "platform"))
import own_payload as OP  # noqa: E402

FICT = "Fict-legacy-9Zq"          # 虛構的「舊預設密碼」（長度 ≥ MIN_PASSWORD_LEN，不在通用清單）
DB_BLOB = "cb3d1c27f5dfb30527b3554b9a272abaaffa99b4"      # db._OWN_PAYLOAD_SOURCE_BLOB
PROBE = r'''
import hashlib, json, sys
sys.path.insert(0, ".")
import helpers.auth as A
h = lambda v: hashlib.sha256(v.encode()).hexdigest()
print(json.dumps({"tuple_hashes": [h(x) for x in A._LEGACY_WEAK_PASSWORDS], "n": len(A._LEGACY_WEAK_PASSWORDS),
                  "fict_weak": A.is_weak_password(%r), "generic_weak": A.is_weak_password("admin123")}))
''' % FICT


def _payload(tmp_path, auth, name="p.json", **over):
    d = {"v": 1, "source_blob": DB_BLOB, "m008": {"correct": "x", "email": "y"}, "m106": {"company_name_en": "z"}}
    if auth is not None:
        d["auth"] = auth
    d.update(over)
    p = tmp_path / name
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def _probe(path):
    import os
    env = dict(os.environ, MOTRIX_OWN_PAYLOAD=str(path))
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=str(BACKEND), capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _h(v):
    return hashlib.sha256(v.encode("utf-8", "surrogatepass")).hexdigest()


GENERIC_H = [_h(x) for x in ("password", "123456", "admin", "motrix", "motrix123")]


def test_with_a_valid_auth_section_the_extra_values_come_first_then_the_generic_list(tmp_path):
    r = _probe(_payload(tmp_path, {"source_blob": "43f2afc70a683f0199d2e044d84e33352c8081c2", "legacy_weak_passwords": [FICT]}))
    assert r["tuple_hashes"] == [_h(FICT)] + GENERIC_H and r["fict_weak"] is True and r["generic_weak"] is True


@pytest.mark.parametrize("case", ["missing_file", "no_auth_section", "wrong_source_blob", "not_a_list", "list_of_junk", "broken_json"])
def test_customer_environment_keeps_the_generic_list_and_never_raises(tmp_path, case):
    if case == "missing_file":
        p = tmp_path / "nope.json"
    elif case == "no_auth_section":
        p = _payload(tmp_path, None)
    elif case == "wrong_source_blob":
        p = _payload(tmp_path, {"source_blob": "0" * 40, "legacy_weak_passwords": [FICT]})
    elif case == "not_a_list":
        p = _payload(tmp_path, {"source_blob": "43f2afc70a683f0199d2e044d84e33352c8081c2", "legacy_weak_passwords": FICT})
    elif case == "list_of_junk":
        p = _payload(tmp_path, {"source_blob": "43f2afc70a683f0199d2e044d84e33352c8081c2", "legacy_weak_passwords": [1, None, "", {}]})
    else:
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
    r = _probe(p)
    assert r["tuple_hashes"] == GENERIC_H and r["fict_weak"] is False and r["generic_weak"] is True, r


def test_no_python_string_literal_in_the_repo_equals_the_legacy_own_values():
    """程式庫（backend 底下所有 .py，含 tests）不得有任何字串字面值等於那兩個舊密碼。比對用 sha256，值只在記憶體。"""
    extras = OP.extract_auth(OP.pinned_auth_source())["legacy_weak_passwords"]
    assert len(extras) == 2, "舊版清單的本公司舊密碼應為 2 個（工具抽出的數量變了？）"
    bad = {_h(v) for v in extras}
    found = []
    for p in BACKEND.rglob("*.py"):
        if "__pycache__" in p.parts or "node_modules" in p.parts:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8-sig"))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and _h(n.value) in bad:
                found.append("%s:%d" % (p.relative_to(BACKEND).as_posix(), n.lineno))
    assert found == [], found


def test_extract_auth_rejects_a_source_that_lost_the_generic_entries_or_the_tuple():
    with pytest.raises(SystemExit):
        OP.extract_auth("_LEGACY_WEAK_PASSWORDS = ('a-b-c-d-e',)\n")
    with pytest.raises(SystemExit):
        OP.extract_auth("X = 1\n")


def test_verify_payload_requires_the_auth_section():
    ok = {"v": 1, "source_blob": OP.PINNED_BLOB, "m008": {"correct": "a", "email": "b"}, "m106": {"company_name_en": "c"},
          "auth": {"source_blob": OP.PINNED_AUTH_BLOB, "legacy_weak_passwords": ["x1"]}}
    assert OP.verify_payload(ok) == []
    no_auth = {k: v for k, v in ok.items() if k != "auth"}
    assert any("auth" in p for p in OP.verify_payload(no_auth))
    assert any("auth" in p for p in OP.verify_payload(dict(ok, auth={"source_blob": "0" * 40, "legacy_weak_passwords": ["x1"]})))
    assert any("auth" in p for p in OP.verify_payload(dict(ok, auth={"source_blob": OP.PINNED_AUTH_BLOB, "legacy_weak_passwords": []})))


def test_add_auth_patches_an_existing_payload_in_place_and_is_idempotent(tmp_path):
    old = {"v": 1, "source_blob": OP.PINNED_BLOB, "m008": {"correct": "a", "email": "b"}, "m106": {"company_name_en": "c"}}
    p = tmp_path / "p.json"
    p.write_text(json.dumps(old), encoding="utf-8")
    assert OP.add_auth(p).startswith("OWN_PAYLOAD_UPDATED")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert OP.verify_payload(d) == [] and d["m008"] == old["m008"]
    assert OP.add_auth(p).startswith("OWN_PAYLOAD_UNCHANGED")
    p.write_text(json.dumps(dict(old, source_blob="0" * 40)), encoding="utf-8")
    assert OP.add_auth(p).startswith("OWN_PAYLOAD_REFUSED")


@pytest.mark.needs_own_payload
def test_own_environment_behaves_exactly_like_the_old_list(tmp_path):
    """有真的資料檔時：清單（含順序）＝舊版 auth.py 的清單；兩個舊密碼仍被判弱。（沒有資料檔：開發機 skip、列車／建包紅。）"""
    old_vals = None
    tree = ast.parse(OP.pinned_auth_source())
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_LEGACY_WEAK_PASSWORDS":
            old_vals = [e.value for e in n.value.elts]
    assert old_vals and len(old_vals) == 7
    import os
    env = {k: v for k, v in os.environ.items() if k != "MOTRIX_OWN_PAYLOAD"}
    probe = PROBE.replace("A.is_weak_password(%r)" % FICT, "all(A.is_weak_password(x) for x in A._LEGACY_WEAK_PASSWORDS)")
    r = subprocess.run([sys.executable, "-c", probe], cwd=str(BACKEND), capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["tuple_hashes"] == [_h(v) for v in old_vals] and got["fict_weak"] is True
