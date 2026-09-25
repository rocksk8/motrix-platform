"""CORE-SPEC 裁示 K-O2（2026-09-26）：服務啟動時對資料庫的寫入只能經 `helpers/startup.py`（結構與 migration 另計）。

原本的守門（test_core_upgrade::test_every_setting_written_at_startup_is_classified）只掃 startup.py 的字面 `_set_setting("…")`，
抓不到其他檔在啟動路徑的寫入。這裡改成實際啟動：複製產品碼 → 建庫 → 再啟動一次並記下每一句寫入的呼叫堆疊
（tools/platform/startup_writes.py）。
① 判定函式：合成紀錄的正對照與反向控制
② 真實啟動：違規 0 組；正對照＝確實量到經 startup.py 的寫入（量不到任何東西時「0 違規」是假綠）
③ 反向控制：在複本的 main.py 多一句啟動時寫入 ⇒ 被抓到、指出呼叫鏈
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import startup_writes as SW  # noqa: E402


def _rec(sql, *files):
    return {"sql": sql, "stack": [(f, 1, "fn") for f in files]}


def test_violations_positive_and_reverse_controls():
    ok = [_rec("INSERT INTO system_settings", "main.py", "helpers/startup.py"),
          _rec("CREATE TABLE IF NOT EXISTS x", "main.py", "db.py"),
          _rec("INSERT INTO module_schema_versions", "main.py", "core/loader.py", "core/migrations.py")]
    assert SW.violations(ok) == []
    bad = ok + [_rec("DELETE FROM login_rate_limit", "main.py", "routers/auth.py"),
                _rec("DELETE FROM login_rate_limit", "main.py", "routers/auth.py")]           # 同一組只列一次
    assert SW.violations(bad) == [("DELETE FROM login_rate_limit", "main.py:fn > routers/auth.py:fn")]


@pytest.fixture(scope="module")
def product_copy(tmp_path_factory):
    work = tmp_path_factory.mktemp("startup_writes")
    backend = SW.copy_product(str(work))
    return str(work), backend, SW.measure(backend, str(work))


def test_startup_writes_only_via_startup_py(product_copy):
    _work, _backend, rec = product_copy
    via = [r for r in rec if "helpers/startup.py" in {f for f, _, _ in r["stack"]}]
    assert via, "量不到任何經 startup.py 的寫入（正對照：至少有 module_versions 同步）"
    bad = SW.violations(rec)
    assert not bad, "啟動時在 helpers/startup.py 以外寫 DB（CORE-SPEC 裁示 K-O2；搬進 startup.py 並在 core.upgrade 分類）：\n" + \
        "\n".join("  %s\n    ← %s" % b for b in bad)


def test_reverse_control_a_write_added_to_main_is_caught(product_copy):
    work, backend, _rec0 = product_copy
    main = Path(backend) / "main.py"
    main.write_text(main.read_text(encoding="utf-8") +
                    "\n_zz = get_db()\n_zz.execute(\"DELETE FROM login_rate_limit WHERE ip='zz-probe'\")\n"
                    "_zz.commit()\n_zz.close()\n", encoding="utf-8")
    rec = SW.start_and_record(backend, str(Path(work) / "third.json"))
    assert [b for b in SW.violations(rec) if "zz-probe" in b[0]] == [
        ("DELETE FROM login_rate_limit WHERE ip='zz-probe'", "main.py:<module>")]
