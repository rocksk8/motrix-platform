"""名稱層級選題（PLAYBOOK §C-11a ③，tools/platform/scope_names.py）。合成原始碼；每一條判斷都有反向控制。"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import scope_names as SN  # noqa: E402

OLD = '''"""doc"""
import os

X = 1


def a():
    return 1


def b():
    return 2
'''


def test_changed_names_only_the_edited_function():
    assert SN.changed_names(OLD, OLD.replace("return 2", "return 3")) == {"b"}


def test_docstring_only_change_touches_no_name():
    assert SN.changed_names(OLD, OLD.replace('"""doc"""', '"""doc v2"""')) == set()


def test_rc_module_level_statement_change_is_all():
    """模組層級的 import／if 等有變 ⇒ 影響範圍看不出來 ⇒ ALL（保守）。"""
    assert SN.changed_names(OLD, OLD.replace("import os", "import os, sys")) is SN.ALL


def test_rc_syntax_error_is_all():
    assert SN.changed_names(OLD, "def (") is SN.ALL


def test_constant_change_is_named():
    assert SN.changed_names(OLD, OLD.replace("X = 1", "X = 2")) == {"X"}


# ── used_names ────────────────────────────────────────────────────────────

def test_from_import_names():
    assert SN.used_names("from helpers.email_notify import a, b\n", "helpers.email_notify") == {"a", "b"}


def test_module_alias_attributes():
    src = "import db\n\ndef f():\n    c = db.get_db()\n    return db.is_demo_mode()\n"
    assert SN.used_names(src, "db") == {"get_db", "is_demo_mode"}


def test_setattr_on_module_names_the_attribute():
    """conftest 的寫法：monkeypatch.setattr(db, "DB_PATH", …) ⇒ 用到 DB_PATH，不是整個模組被傳出去。"""
    src = "import db\n\ndef fx(monkeypatch):\n    monkeypatch.setattr(db, 'DB_PATH', 'x')\n    db.init_db()\n"
    assert SN.used_names(src, "db") == {"DB_PATH", "init_db"}


def test_rc_module_passed_around_is_all():
    src = "import db\n\ndef f(g):\n    return g(db)\n"
    assert SN.used_names(src, "db") is SN.ALL


def test_rc_star_import_is_all():
    assert SN.used_names("from helpers.auth import *\n", "helpers.auth") is SN.ALL


def test_package_alias_and_reexport():
    src = "from helpers import email_notify\nfrom helpers import send_x\n\nemail_notify.notify_y()\n"
    assert SN.used_names(src, "helpers.email_notify", {"send_x": "email_notify"}) == {"notify_y", "send_x"}


def test_relative_import_inside_package():
    assert SN.used_names("from .email_notify import a\n", "helpers.email_notify") == {"a"}


def test_not_imported_is_empty():
    assert SN.used_names("import os\n", "helpers.auth") == set()


def test_dotted_import_without_alias_is_all():
    assert SN.used_names("import helpers.auth\n\nhelpers.auth._tok()\n", "helpers.auth") is SN.ALL


# ── name_tables ───────────────────────────────────────────────────────────

def test_name_tables_only_the_changed_function():
    src = ("def a(c):\n    c.execute('SELECT * FROM users')\n\n"
           "def b(c):\n    c.execute('UPDATE quotations SET x=1')\n")
    got = SN.name_tables([src], {"b"}, {"users", "quotations"})
    assert got["tables_w"] == ["quotations"] and got["tables_r"] == [] and got["dynamic_sql"] is False


def test_rc_name_tables_sees_deleted_sql_in_the_old_version():
    old = "def b(c):\n    c.execute('DELETE FROM users')\n"
    new = "def b(c):\n    pass\n"
    assert SN.name_tables([old, new], {"b"}, {"users"})["tables_w"] == ["users"]


def test_dotted():
    assert SN.dotted("backend/helpers/email_notify.py") == "helpers.email_notify"
    assert SN.dotted("backend/db.py") == "db"
    assert SN.dotted("backend/modules/tender_radar/__init__.py") == "modules.tender_radar"


# ── 稽核 D S-M1：模組內引用閉包 ────────────────────────────────────────────

MOD = '''def _a():
    return 1


def b():
    return _a() + 1


def c():
    return b()


def d():
    return 4
'''


def test_expand_internal_follows_callers_transitively():
    assert SN.expand_internal([MOD], {"_a"}) == {"_a", "b", "c"}


def test_expand_internal_leaves_unrelated_names():
    assert "d" not in SN.expand_internal([MOD], {"_a"})


def test_expand_internal_uses_both_versions():
    """新版把呼叫拿掉了，舊版還有 ⇒ 仍然算（刪掉的呼叫也是改動的一部分）。"""
    new = MOD.replace("return _a() + 1", "return 2")
    assert "b" in SN.expand_internal([MOD, new], {"_a"})


def test_rc_expand_internal_all_stays_all():
    assert SN.expand_internal([MOD], SN.ALL) is SN.ALL


def test_rc_expand_internal_needs_repeated_rounds():
    """呼叫者定義在被呼叫者之前（c → b → _a）：單輪由上往下掃會漏掉 c，必須反覆到不再增加。"""
    src = "def c():\n    return b()\n\n\ndef b():\n    return _a()\n\n\ndef _a():\n    return 1\n"
    assert SN.expand_internal([src], {"_a"}) == {"_a", "b", "c"}
