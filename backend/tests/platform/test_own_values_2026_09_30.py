# -*- coding: utf-8 -*-
"""去識別化：伺服器 IP 移出程式碼，改放 own 資料檔的 `network` 區段（helpers/own_values.py）。

契約：本公司環境（有資料檔）的 CORS 預設與通知信系統網址預設和舊版逐字相同；客戶環境（沒有）只有本機四筆、系統網址留空；
資料檔壞掉／版本不符都退回客戶行為，不丟例外。值只在記憶體裡出現（取自 git 歷史的固定舊版 main.py）。
"""
import ast
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
sys.path.insert(0, str(REPO / "tools" / "platform"))
import own_payload as OP  # noqa: E402

FICT_IP = "192.0.2.77"          # RFC 5737 文件用網段
DB_BLOB = OP.PINNED_BLOB


@pytest.fixture()
def OV(tmp_path, monkeypatch):
    """own_values；庫路徑指到不存在的檔（不去讀真實的開發庫）——要用庫的題改用 client fixture。"""
    sys.path.insert(0, str(BACKEND))
    import db
    from helpers import own_values
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "no_such.db"))
    return own_values


def _payload(tmp_path, network, monkeypatch):
    d = {"v": 1, "source_blob": DB_BLOB, "m008": {"correct": "a", "email": "b"}, "m106": {"company_name_en": "c"}}
    if network is not None:
        d["network"] = network
    p = tmp_path / "p.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(p))


def test_blob_constants_agree_between_the_tool_and_the_runtime_module(OV):
    assert OV.NETWORK_SOURCE_BLOB == OP.PINNED_NET_BLOB


def test_with_a_valid_network_section_the_defaults_carry_the_ip_in_the_old_order(tmp_path, monkeypatch, OV):
    _payload(tmp_path, {"source_blob": OV.NETWORK_SOURCE_BLOB, "server_ip": FICT_IP}, monkeypatch)
    assert OV.server_ip() == FICT_IP
    assert OV.default_cors_origins() == ["http://localhost:666", "http://127.0.0.1:666", "http://%s:666" % FICT_IP,
                                         "https://localhost:666", "https://127.0.0.1:666", "https://%s:666" % FICT_IP]
    assert OV.default_base_url() == "https://%s:666" % FICT_IP


@pytest.mark.parametrize("case", ["missing_file", "no_section", "wrong_blob", "not_an_ip", "not_a_string", "ipv6", "broken_json"])
def test_customer_environment_gets_local_only_and_an_empty_base_url_and_never_raises(tmp_path, monkeypatch, OV, case):
    if case == "missing_file":
        monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(tmp_path / "nope.json"))
    elif case == "broken_json":
        (tmp_path / "b.json").write_text("{nope", encoding="utf-8")
        monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(tmp_path / "b.json"))
    else:
        net = {"no_section": None,
               "wrong_blob": {"source_blob": "0" * 40, "server_ip": FICT_IP},
               "not_an_ip": {"source_blob": OV.NETWORK_SOURCE_BLOB, "server_ip": "erp.example.com"},
               "not_a_string": {"source_blob": OV.NETWORK_SOURCE_BLOB, "server_ip": 12345},
               "ipv6": {"source_blob": OV.NETWORK_SOURCE_BLOB, "server_ip": "::1"}}[case]
        _payload(tmp_path, net, monkeypatch)
    assert OV.server_ip() == ""
    assert OV.default_cors_origins() == ["http://localhost:666", "http://127.0.0.1:666", "https://localhost:666", "https://127.0.0.1:666"]
    assert OV.default_base_url() == ""


def test_extract_network_needs_exactly_one_non_local_ip():
    ok = OP.extract_network('X = ["http://localhost:666", "http://127.0.0.1:666", "http://10.9.8.7:666", "https://10.9.8.7:666"]')
    assert ok["server_ip"] == "10.9.8.7" and ok["source_blob"] == OP.PINNED_NET_BLOB
    for bad in ('X = ["http://localhost:666"]', 'X = ["http://10.0.0.1:666", "http://10.0.0.2:666"]'):
        with pytest.raises(SystemExit):
            OP.extract_network(bad)


def test_verify_payload_requires_the_network_section():
    ok = {"v": 1, "source_blob": OP.PINNED_BLOB, "m008": {"correct": "a", "email": "b"}, "m106": {"company_name_en": "c"},
          "auth": {"source_blob": OP.PINNED_AUTH_BLOB, "legacy_weak_passwords": ["x1"]},
          "network": {"source_blob": OP.PINNED_NET_BLOB, "server_ip": "10.1.1.1"}}
    assert OP.verify_payload(ok) == []
    assert any("network" in p for p in OP.verify_payload({k: v for k, v in ok.items() if k != "network"}))
    assert any("network" in p for p in OP.verify_payload(dict(ok, network={"source_blob": "0" * 40, "server_ip": "10.1.1.1"})))
    assert any("network" in p for p in OP.verify_payload(dict(ok, network={"source_blob": OP.PINNED_NET_BLOB, "server_ip": ""})))


def test_add_auth_now_patches_both_sections_and_is_idempotent(tmp_path):
    old = {"v": 1, "source_blob": OP.PINNED_BLOB, "m008": {"correct": "a", "email": "b"}, "m106": {"company_name_en": "c"}}
    p = tmp_path / "p.json"
    p.write_text(json.dumps(old), encoding="utf-8")
    assert OP.add_auth(p).startswith("OWN_PAYLOAD_UPDATED")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert OP.verify_payload(d) == [] and "network" in d and "auth" in d
    assert OP.add_auth(p).startswith("OWN_PAYLOAD_UNCHANGED")


def test_no_product_source_file_contains_the_server_ip():
    """程式庫的 .py／.html／.js（backend、frontend；含 tests）不得含伺服器 IP。值取自固定舊版 main.py，只在記憶體比對。
    例外（另案處理中，逐檔登記）：部署／維運腳本與部署儀表板。"""
    ip = OP.extract_network(OP.pinned_net_source())["server_ip"]
    allowed = {"backend/tools/deploy_dashboard.py", "backend/tools/deploy_dashboard.html", "backend/tools/deploy_insights.py",
               "backend/tests/platform/test_deploy_dashboard_health.py", "backend/tests/test_deploy_dashboard_local_only_2026_09_22.py",
               "backend/version_manifest.json"}
    hits = []
    for base in ("backend", "frontend"):
        for p in (REPO / base).rglob("*"):
            if not p.is_file() or p.suffix.lower() not in (".py", ".html", ".js") or "__pycache__" in p.parts or "node_modules" in p.parts:
                continue
            rel = p.relative_to(REPO).as_posix()
            if rel in allowed or "/vendor/" in rel:
                continue
            try:
                if ip in p.read_text(encoding="utf-8-sig", errors="ignore"):
                    hits.append(rel)
            except OSError:
                pass
    assert hits == [], hits


@pytest.mark.needs_own_payload
def test_own_environment_defaults_equal_the_pre_change_values(OV, monkeypatch):
    monkeypatch.delenv("MOTRIX_OWN_PAYLOAD", raising=False)
    tree = ast.parse(OP.pinned_net_source())
    old = None
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_DEFAULT_CORS_ORIGINS":
            old = [e.value for e in n.value.elts]
    assert old and len(old) == 6
    assert OV.default_cors_origins() == old
    assert OV.default_base_url() == "https://%s:666" % OV.server_ip() and OV.server_ip()


# ── 庫裡的設定（穩態來源）、啟動時的 ensure、遺失資料檔的行為、apply_plan 不刪資料檔 ─────────────────────

def _set_db_ip(ip):
    from helpers.settings import _set_setting
    _set_setting("own_network", {"server_ip": ip})


def _del_db_ip():
    from db import get_db
    conn = get_db()
    try:
        conn.execute("DELETE FROM system_settings WHERE key='own_network'")
        conn.commit()
    finally:
        conn.close()


def _notes():
    from db import get_db
    conn = get_db()
    try:
        return conn.execute("SELECT username, type, ref_id, message FROM notifications WHERE ref_id='own_network'").fetchall()
    finally:
        conn.close()


def test_db_setting_wins_over_the_payload_and_payload_is_the_fallback(client, tmp_path, monkeypatch):
    from helpers import own_values as OV
    _payload(tmp_path, {"source_blob": OV.NETWORK_SOURCE_BLOB, "server_ip": "192.0.2.20"}, monkeypatch)
    assert OV.server_ip() == "192.0.2.20"                      # 庫裡沒有 ⇒ 資料檔
    _set_db_ip("192.0.2.21")
    assert OV.server_ip() == "192.0.2.21"                      # 庫裡有 ⇒ 庫
    _set_db_ip("not-an-ip")
    assert OV.server_ip() == "192.0.2.20", "庫裡的值不合法 ⇒ 忽略、退回資料檔"
    _del_db_ip()
    monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(tmp_path / "gone.json"))
    assert OV.server_ip() == ""


def test_drill_prod_like_upgrade_first_boot_then_payload_lost_gives_byte_identical_defaults(client, tmp_path, monkeypatch):
    """(a) 演練：本公司安裝升級後第一次啟動（有資料檔、庫裡還沒有）→ ensure 存進庫 → 之後資料檔不見 → CORS 預設與通知網址逐位元組不變。"""
    from helpers import own_values as OV
    _payload(tmp_path, {"source_blob": OV.NETWORK_SOURCE_BLOB, "server_ip": "192.0.2.30"}, monkeypatch)
    first_cors, first_base = OV.default_cors_origins(), OV.default_base_url()       # CORS 是 main 載入時算的：此時庫裡還沒有值 ⇒ 靠資料檔
    assert OV.ensure_own_network() == "stored"
    monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(tmp_path / "gone.json"))            # 資料檔遺失
    assert OV.ensure_own_network() == "present"
    assert (OV.default_cors_origins(), OV.default_base_url()) == (first_cors, first_base)
    assert first_cors == ["http://localhost:666", "http://127.0.0.1:666", "http://192.0.2.30:666",
                          "https://localhost:666", "https://127.0.0.1:666", "https://192.0.2.30:666"]
    assert first_base == "https://192.0.2.30:666"


def test_ensure_never_overwrites_an_existing_value(client, tmp_path, monkeypatch):
    from helpers import own_values as OV
    _set_db_ip("192.0.2.40")
    _payload(tmp_path, {"source_blob": OV.NETWORK_SOURCE_BLOB, "server_ip": "192.0.2.41"}, monkeypatch)
    assert OV.ensure_own_network() == "present" and OV.server_ip() == "192.0.2.40"


def test_customer_environment_is_silent(client, monkeypatch, tmp_path, caplog):
    from helpers import own_values as OV
    monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(tmp_path / "gone.json"))
    monkeypatch.setattr(OV, "_is_own_install", lambda: False)
    with caplog.at_level("ERROR"):
        assert OV.ensure_own_network() == "customer"
    assert not [r for r in caplog.records if r.levelname == "ERROR"] and _notes() == []


def test_own_install_without_any_value_logs_an_error_notifies_the_admin_and_still_starts(client, monkeypatch, tmp_path, caplog):
    """(b) 本公司安裝、庫裡沒有、資料檔也沒有：不拒絕啟動（回 missing）、記 ERROR、站內通知預設管理員；每次啟動重試。"""
    from helpers import own_values as OV
    monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(tmp_path / "gone.json"))
    monkeypatch.setattr(OV, "_is_own_install", lambda: True)
    with caplog.at_level("ERROR"):
        assert OV.ensure_own_network() == "missing"
    assert [r for r in caplog.records if r.levelname == "ERROR" and "own_network" in r.getMessage()]
    rows = _notes()
    assert len(rows) == 1 and rows[0]["type"] == "system_alert" and "own_payload.json" in rows[0]["message"]
    assert OV.default_cors_origins() == ["http://localhost:666", "http://127.0.0.1:666", "https://localhost:666", "https://127.0.0.1:666"]
    assert OV.ensure_own_network() == "missing"                                       # 重試；資料檔一放回來就補上
    _payload(tmp_path, {"source_blob": OV.NETWORK_SOURCE_BLOB, "server_ip": "192.0.2.50"}, monkeypatch)
    assert OV.ensure_own_network() == "stored"


def test_ensure_never_raises(client, monkeypatch):
    from helpers import own_values as OV
    monkeypatch.setattr(OV, "_db_ip", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert OV.ensure_own_network() == "customer"


def test_main_calls_ensure_after_init_db_at_module_level():
    """main 載入有副作用 ⇒ 用 AST 驗接線：模組層級有 `_ensure_own_network()` 呼叫，且在 `init_db()` 之後。"""
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8-sig"))
    order = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = getattr(f, "id", None)
            if name in ("init_db", "_ensure_own_network"):
                order.append((node.lineno, name, len(node.args)))
    lines = {n: ln for ln, n, a in order if not (n == "init_db" and a)}
    assert "_ensure_own_network" in lines and lines["_ensure_own_network"] > lines["init_db"]


def test_apply_plan_never_deletes_or_lists_the_own_payload():
    """(c) 舊包的清單（baseline）含資料檔、新包沒有它 ⇒ 也不可以被列進刪除候選；也不進包清單。"""
    sys.path.insert(0, str(BACKEND))
    from core import upgrade as U
    from tools import apply_plan as AP
    rel = "backend/migrations_frozen/own_payload.json"
    assert U.classify(rel) == "program"                         # 它本來會被當成程式檔
    assert AP.deletable(rel, U) is False and AP.OWN_PAYLOAD_REL == rel
    assert AP.deletable("backend/migrations_frozen/__init__.py", U) is True, "只豁免資料檔本身，同目錄的程式檔照常"


def test_apply_plan_end_to_end_keeps_the_installed_payload_when_the_new_package_lacks_it(tmp_path):
    """子行程執行：apply_plan.load_classifier 會改 sys.path 並匯入新包的 core（同行程跑會污染其他題）。"""
    import shutil
    import subprocess
    root, pkg = tmp_path / "inst", tmp_path / "pkg"
    for base in (root, pkg):
        (base / "backend" / "migrations_frozen").mkdir(parents=True)
        (base / "backend" / "migrations_frozen" / "keep_me.txt").write_text("x", encoding="utf-8")
    (root / "backend" / "migrations_frozen" / "own_payload.json").write_text("{}", encoding="utf-8")
    (root / "backend" / "migrations_frozen" / "old_program_file.py").write_text("y", encoding="utf-8")
    (root / "backend" / ".deployed_files.json").write_text(json.dumps({"commit": "c", "files": [
        "backend/migrations_frozen/keep_me.txt", "backend/migrations_frozen/own_payload.json", "backend/migrations_frozen/old_program_file.py"]}), encoding="utf-8")
    shutil.copytree(BACKEND / "core", pkg / "backend" / "core", ignore=shutil.ignore_patterns("__pycache__"))   # make_plan 用「新包的」分類器
    code = ("import sys, json; sys.path.insert(0, %r)\nfrom tools import apply_plan as AP\n"
            "plan = AP.make_plan(%r, %r, 200)\nprint('PLAN=' + json.dumps(plan, default=str, ensure_ascii=False))") % (str(BACKEND), str(root), str(pkg))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr[-600:]
    plan = json.loads(r.stdout.split("PLAN=", 1)[1])
    deleted = [d["rel"] for d in plan["delete"]]
    assert "backend/migrations_frozen/own_payload.json" not in deleted, plan["delete"]
    assert "backend/migrations_frozen/own_payload.json" not in plan["package_files"]
    assert deleted == ["backend/migrations_frozen/old_program_file.py"], "對照：舊包有、新包沒有的一般程式檔照常進刪除清單（否則這題什麼都沒證明）"
