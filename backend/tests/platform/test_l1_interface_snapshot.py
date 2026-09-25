"""G1：L0／L1 公開介面快照（MODULE-GUIDE §2；判定邏輯見 _l1_interface.py）。

介面一有變動就紅；修法：照規則升 CORE_VERSION（新增＝次版號、修改／刪除＝主版號）、
寫 backend/core/CHANGELOG.md，再跑 `python backend/tests/platform/_l1_interface.py --update` 重產快照。
"""
import pytest

from tests.platform import _l1_interface as G


def _fmt(items):
    return "\n  " + "\n  ".join(items)


def test_scanner_sees_the_l1_surface():
    """正對照：讀得到 L1 單位與介面（解析器壞掉時其餘幾題會安靜地綠）。"""
    cur = G.current_interface()
    assert len(cur) >= 10, sorted(cur)
    assert sum(len(v) for v in cur.values()) > 100
    missing = sorted(u for u, v in cur.items() if "__missing__" in v)
    assert not missing, "modules.json 的 L1 單位找不到檔案：" + _fmt(missing)


def test_interface_matches_snapshot():
    snap = G.load_snapshot()
    a, c, r = G.diff(snap["interface"], G.current_interface())
    need = G.required_bump(a, c, r)
    assert need is None, (
        "L0／L1 公開介面與快照不同（需要 %s 升版）：" % need
        + "".join(_fmt(["%s  %s" % (lbl, x) for x in xs]) for lbl, xs in (("新增", a), ("修改", c), ("刪除", r)) if xs)
        + "\n⇒ 升 CORE_VERSION（新增＝次版號、修改／刪除＝主版號）、寫 core/CHANGELOG.md，"
          "再跑 _l1_interface.py --update（版號不足會拒絕重產）。")


def test_snapshot_version_is_current():
    assert G.load_snapshot()["core_version"] == G.core_version(), (
        "快照記的 CORE_VERSION 與目前不同 ⇒ 升了版號卻沒重產快照（或反過來）")


def test_changelog_top_equals_core_version():
    assert G.changelog_top_version() == G.core_version(), (
        "core/CHANGELOG.md 最上面的版號 %s ≠ CORE_VERSION %s" % (G.changelog_top_version(), G.core_version()))


# ── 反向控制：判定函式在突變後必須報出來 ─────────────────────────────────────

def test_rc_signature_change_needs_major():
    old = {"plat:x": {"f": "def(a)"}}
    new = {"plat:x": {"f": "def(a, b)"}}
    a, c, r = G.diff(old, new)
    assert c and G.required_bump(a, c, r) == "major"
    assert not G.bump_ok("1.2", "1.3", "major") and G.bump_ok("1.2", "2.0", "major")


def test_rc_trailing_defaulted_params_are_a_compatible_extension():
    """尾端加有預設值的參數 ⇒ 相容擴充（次版號）；拿掉預設值、插在中間、改名 ⇒ 仍是修改（主版號）。"""
    ok = {"plat:x": {"f": "def(a, b=…)"}}
    for new, need in (("def(a, b=…, c=…)", "minor"), ("def(a, b=…, *, c=…)", "minor"), ("def(a, b=…, **kw)", "minor"),
                      ("def(a, b=…, c)", "major"), ("def(a, c=…, b=…)", "major"), ("def(a, bb=…)", "major"),
                      ("def(a, b)", "major")):
        a, c, r = G.diff(ok, {"plat:x": {"f": new}})
        assert G.required_bump(a, c, r) == need, (new, a, c)


def test_rc_removal_needs_major():
    a, c, r = G.diff({"plat:x": {"f": "def()", "g": "def()"}}, {"plat:x": {"f": "def()"}})
    assert r == ["plat:x::g"] and G.required_bump(a, c, r) == "major"


def test_rc_addition_needs_minor():
    a, c, r = G.diff({"plat:x": {"f": "def()"}}, {"plat:x": {"f": "def()", "g": "def()"}})
    assert a == ["plat:x::g"] and G.required_bump(a, c, r) == "minor"
    assert not G.bump_ok("1.2", "1.2", "minor") and G.bump_ok("1.2", "1.3", "minor")
    assert not G.bump_ok("1.2", "1.1", None), "倒退不可以"


def test_rc_real_source_mutation_is_seen():
    """真改原始碼形狀：加參數、加預設值、改成 keyword-only、刪函式、改 dataclass 欄位 ⇒ 都要看得出不同。"""
    base = "def f(a, b=1):\n    pass\n@dataclass\nclass C:\n    x: int\n    y: int = 0\n    def m(self, z):\n        pass\nLIMIT = 3\n"
    ref = G.interface_of(base)
    for mutated in (
        base.replace("def f(a, b=1)", "def f(a, b=1, c=2)"),
        base.replace("def f(a, b=1)", "def f(a, b)"),
        base.replace("def f(a, b=1)", "def f(a, *, b=1)"),
        base.replace("def f(a, b=1):\n    pass\n", ""),
        base.replace("    x: int\n", "    x: int = 1\n"),
        base.replace("def m(self, z)", "def m(self, z, w=0)"),
        base.replace("LIMIT = 3\n", ""),
    ):
        assert G.interface_of(mutated) != ref, mutated
    # 對照：私有名稱、函式內容、常數值的改動不算介面
    benign = (base.replace("pass\n@", "return 1\n@", 1).replace("LIMIT = 3", "LIMIT = 4")
              + "def _private(q):\n    pass\n")
    assert G.interface_of(benign) == ref


def test_rc_update_refuses_without_bump(tmp_path, monkeypatch):
    """重產工具在版號不足時拒絕（否則「改了介面就重產快照」會讓守門失效）。"""
    import json
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps({"core_version": "1.2", "interface": {"plat:x": {"f": "def(a)"}}}), encoding="utf-8")
    monkeypatch.setattr(G, "SNAPSHOT", snap)
    monkeypatch.setattr(G, "current_interface", lambda units=None: {"plat:x": {"f": "def(a, b)"}})
    monkeypatch.setattr(G, "core_version", lambda: "1.3")
    assert G.main(["--update"]) == 1
    assert json.loads(snap.read_text(encoding="utf-8"))["interface"]["plat:x"]["f"] == "def(a)"
    monkeypatch.setattr(G, "core_version", lambda: "2.0")
    assert G.main(["--update"]) == 0
    assert json.loads(snap.read_text(encoding="utf-8"))["core_version"] == "2.0"
