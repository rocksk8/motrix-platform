# -*- coding: utf-8 -*-
"""migrate_like_startup --expect-module（B55 單一模組更新包 §1.3 步驟 5；apply_module_update.ps1 的載入乾跑）。

照啟動規則載入之後，指定模組必須 state=loaded 且版本＝新版 ⇒ `MODULE_LOAD_OK`；否則 `MODULE_LOAD_FAIL`＋exit 2。
與 migration 失敗分開印（ps1 據此給 module_load_dryrun_failed 或 migration_dryrun_failed）。
夾具沿用 test_migrate_like_startup_modular_2026_09_28（合成模組套件、隔離登錄表、init_db 替身）。
"""
from tests.platform.test_migrate_like_startup_modular_2026_09_28 import (  # noqa: F401
    MLS, OK_MODULE, _pkg, _settings_db, _stub_init_db, iso)


def _run(argv, capsys):
    code = MLS.main(argv)
    return code, capsys.readouterr().out


def test_loaded_module_with_the_expected_version_passes(tmp_path, monkeypatch, iso, capsys):
    _pkg(tmp_path, monkeypatch, "zzexp_ok", {"zz_a": OK_MODULE % "zz_a"})
    main_db = _settings_db(tmp_path / "main.db")
    _stub_init_db(monkeypatch, {main_db: {}})
    code, out = _run(["--db", main_db, "--expect-module", "zz_a=0.0.1"], capsys)
    assert code == 0 and "MODULE_LOAD_OK zz_a=0.0.1" in out and "MIGRATE_LIKE_STARTUP_OK" in out, out


def test_wrong_version_fails_with_module_load_fail(tmp_path, monkeypatch, iso, capsys):
    _pkg(tmp_path, monkeypatch, "zzexp_ver", {"zz_a": OK_MODULE % "zz_a"})
    main_db = _settings_db(tmp_path / "main.db")
    _stub_init_db(monkeypatch, {main_db: {}})
    code, out = _run(["--db", main_db, "--expect-module", "zz_a=0.0.2"], capsys)
    assert code == 2 and "MODULE_LOAD_FAIL zz_a" in out and "0.0.2" in out and "MODULE_LOAD_OK" not in out, out


def test_module_that_fails_to_load_fails(tmp_path, monkeypatch, iso, capsys):
    _pkg(tmp_path, monkeypatch, "zzexp_bad", {"zz_b": "raise RuntimeError('壞了')\n"})
    main_db = _settings_db(tmp_path / "main.db")
    _stub_init_db(monkeypatch, {main_db: {}})
    code, out = _run(["--db", main_db, "--expect-module", "zz_b=0.0.1"], capsys)
    assert code == 2 and "MODULE_LOAD_FAIL zz_b" in out, out


def test_missing_module_fails(tmp_path, monkeypatch, iso, capsys):
    _pkg(tmp_path, monkeypatch, "zzexp_missing", {"zz_a": OK_MODULE % "zz_a"})
    main_db = _settings_db(tmp_path / "main.db")
    _stub_init_db(monkeypatch, {main_db: {}})
    code, out = _run(["--db", main_db, "--expect-module", "zz_nope=1.0.0"], capsys)
    assert code == 2 and "MODULE_LOAD_FAIL zz_nope" in out, out


def test_old_package_without_module_startup_cannot_verify(tmp_path, monkeypatch, iso, capsys):
    monkeypatch.setattr(MLS, "has_module_startup", lambda backend=None: False)
    main_db = str(tmp_path / "main.db")
    _stub_init_db(monkeypatch, {})
    code, out = _run(["--db", main_db, "--expect-module", "zz_a=0.0.1"], capsys)
    assert code == 2 and "MODULE_LOAD_FAIL zz_a" in out and "舊包" in out, out


def test_reverse_control_without_expect_nothing_changes(tmp_path, monkeypatch, iso, capsys):
    _pkg(tmp_path, monkeypatch, "zzexp_none", {"zz_a": OK_MODULE % "zz_a"})
    main_db = _settings_db(tmp_path / "main.db")
    _stub_init_db(monkeypatch, {main_db: {}})
    code, out = _run(["--db", main_db], capsys)
    assert code == 0 and "MODULE_LOAD" not in out, out


def test_bad_expect_format_is_rejected():
    import pytest
    with pytest.raises(SystemExit):
        MLS._parse_expect(["zz_a"])
