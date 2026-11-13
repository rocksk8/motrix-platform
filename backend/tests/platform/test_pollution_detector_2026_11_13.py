# -*- coding: utf-8 -*-
"""T84 tools/platform/pollution_detector.py：測試汙染偵測（pytest plugin，只觀察、不改測試結果與 exit code）。

用真的子行程 pytest 跑合成小套件（不打專案自己的測試）。**正對照**：故意洩漏的檔必須被點名；乾淨的檔、有還原的檔、快取類必須不在清單上。
另驗：純函式（指紋、彙整）、mode=off 什麼都不寫、白名單常數的註解（PM 裁示：白名單寫死成常數並加註解）。
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PLAT = REPO / "tools" / "platform"
SRC = PLAT / "pollution_detector.py"
spec = importlib.util.spec_from_file_location("_pollution_detector_t", SRC)
PD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PD)

SUITE = {
    # 被測程式的「登記表」：大寫名字的模組級 dict（自動盤點）；CACHE_ 開頭的算快取
    "leaky_reg.py": "REG = {'a': 1}\nLIST_X = []\nCACHE_X = {}\n",
    # session DB：偵測器從 db.DB_PATH 找（建在 import 當下）
    "db.py": "import os, sqlite3\nDB_PATH = os.environ['PD_DB']\n_c = sqlite3.connect(DB_PATH)\n_c.execute('CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY, note TEXT)')\n_c.commit()\n_c.close()\n",
    "test_a_leaker.py": "import leaky_reg\n\ndef test_leaks_a_key():\n    leaky_reg.REG['leak'] = 1\n    leaky_reg.LIST_X.append('x')\n",
    "test_b_clean.py": "import leaky_reg\n\ndef test_clean(monkeypatch):\n    monkeypatch.setitem(leaky_reg.REG, 'tmp', 1)\n    monkeypatch.setenv('PD_TMP_ENV', '1')\n",
    "test_c_restores.py": (
        "import pytest, leaky_reg\n\n@pytest.fixture(scope='module', autouse=True)\ndef _restore():\n    snap = dict(leaky_reg.REG)\n    yield\n"
        "    leaky_reg.REG.clear(); leaky_reg.REG.update(snap)\n\ndef test_writes_but_restores():\n    leaky_reg.REG['c'] = 1\n"),
    "test_d_env.py": "import os\n\ndef test_leaks_env():\n    os.environ['PD_LEAKED_ENV'] = '1'\n",
    "test_e_cache.py": "import leaky_reg\n\ndef test_grows_a_cache():\n    leaky_reg.CACHE_X['k'] = 1\n",
    "test_f_db.py": (
        "import sqlite3, db\n\ndef test_writes_session_db():\n    c = sqlite3.connect(db.DB_PATH)\n"
        "    c.executemany('INSERT INTO audit_log(note) VALUES (?)', [('x',)] * 3)\n    c.commit(); c.close()\n"),
    "test_g_stub.py": "import sys, types\n\ndef test_leaves_a_stub_module():\n    sys.modules['pd_fake_dep'] = types.ModuleType('pd_fake_dep')\n",
    "test_h_red.py": "def test_fails_on_purpose():\n    assert 1 == 2\n",
}


def _run(tmp_path, mode="gate", sub="r"):
    tmp_path = tmp_path / sub
    proj = tmp_path / "proj"
    proj.mkdir(parents=True)
    for name, body in SUITE.items():
        (proj / name).write_text(body, encoding="utf-8")
    out = tmp_path / "out"
    env = dict(os.environ, PYTHONPATH=str(PLAT), PYTHONUTF8="1", MOTRIX_POLLUTION=mode, MOTRIX_POLLUTION_DIR=str(out),
               PD_DB=str(tmp_path / "session.db"), MOTRIX_FAIL_STREAM_RUN="pd1")
    for k in ("MOTRIX_TRAIN", "PYTEST_ADDOPTS"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, "-m", "pytest", "-p", "pollution_detector", "-p", "no:cacheprovider", "-q"],
                       cwd=str(proj), env=env, capture_output=True, text=True, encoding="utf-8", timeout=180)
    return p, out


def _polluters(out):
    f = out / "pd1.pollution-list.json"
    assert f.exists(), "沒有汙染清單"
    return json.loads(f.read_text(encoding="utf-8"))


def test_leaks_are_named_with_the_file_and_the_key_and_clean_files_are_not(tmp_path):
    p, out = _run(tmp_path)
    assert "1 failed" in p.stdout and p.returncode == 1, p.stdout[-800:]       # test_h_red 的紅燈照舊；偵測器不改結果、不加 exit code
    pol = _polluters(out)["polluters"]
    by = {x["state"]: x for x in pol}
    reg = by["leaky_reg.REG"]
    assert reg["files"] == ["test_a_leaker.py"] and "leak" in reg["keys"]                         # 洩漏的鍵與檔都點名；有還原的 test_c、monkeypatch 的 test_b 不在
    assert by["leaky_reg.LIST_X"]["files"] == ["test_a_leaker.py"]
    assert by["os.environ"]["files"] == ["test_d_env.py"] and "PD_LEAKED_ENV" in by["os.environ"]["keys"]
    assert "PD_TMP_ENV" not in json.dumps(pol)                                                    # monkeypatch.setenv 收尾還原 ⇒ 沒事
    sess = [x for x in pol if x["state"].startswith("session DB")]
    assert len(sess) == 1 and sess[0]["files"] == ["test_f_db.py"] and "audit_log +3" in sess[0]["keys"]    # 沒用 client 的題目讀到的前題殘留，就是這一類
    assert by["sys.modules"]["files"] == ["test_g_stub.py"]
    assert all("test_b_clean.py" not in x["files"] and "test_c_restores.py" not in x["files"] for x in pol)
    assert "leaky_reg.CACHE_X" not in by                                                          # 快取類照記（jsonl）但不進清單
    jl = (out / "pd1.pollution.jsonl").read_text(encoding="utf-8")
    assert '"class": "cache"' in jl and "test_e_cache.py" in jl


def test_detector_only_observes_it_never_changes_outcomes(tmp_path):
    p_on, _ = _run(tmp_path, sub="on")
    p_off, out_off = _run(tmp_path, mode="off", sub="off")
    last = lambda s: re.findall(r"(\d+ failed.*?)(?: in |\n|$)", s)[-1:]                          # noqa: E731
    assert last(p_on.stdout) == last(p_off.stdout) and p_on.returncode == p_off.returncode == 1
    assert not out_off.exists() or not list(out_off.glob("*.pollution*"))                       # off：什麼都不寫


def test_pollution_list_aggregation_is_pure_and_skips_cache_class():
    recs = [{"file": "a.py", "findings": [{"class": "registry", "state": "m.REG", "added": ["x"]}, {"class": "cache", "state": "m.CACHE_Z", "added": ["y"]}]},
            {"file": "b.py", "findings": [{"class": "registry", "state": "m.REG", "added": ["x"]}]},
            {"file": "c.py", "findings": []}]
    lst = PD.pollution_list(recs)
    assert lst == [{"state": "m.REG", "keys": ["x"], "files": ["a.py", "b.py"]}]
    assert PD._fp({"a": 1}) != PD._fp({"a": 1, "b": 2}) and PD._fp([1]) != PD._fp([1, 2]) and PD._fp({1, 2}) != PD._fp({1})        # noqa: SLF001


def test_every_whitelist_constant_is_hardcoded_and_commented():
    """PM 裁示：白名單寫死成常數並加註解（不從檔案／環境變數讀）。"""
    src = SRC.read_text(encoding="utf-8")
    for name in ("_ENV_IGNORE", "_PROC_IGNORE", "_CACHE_RE"):
        m = re.search(r"^%s = .*?(?:#.*)?$" % name, src, flags=re.M)
        assert m, name
        i = src.index(m.group(0))
        window = src[max(0, i - 400):i + len(m.group(0))]
        assert "#" in window, name                                                                # 同行或上方有註解
    head = src.split("class Detector")[0]
    assert "open(" not in head and "json.load" not in head                                       # 白名單區不讀外部檔
    assert "POL_DEBUG" not in src
