# -*- coding: utf-8 -*-
"""脊柱 E-b3：字面掃描器守門（掃描器本身見 _spine_scan.py）。含正對照：抓不到違規樣本 ⇒ 掃描器自己紅。"""
from datetime import date

from tests.platform import _spine_scan as S

GOOD_SRC = '''
_mt.register("zz_ok_mail", "測試信", "business", "none", "", "影響", "處理", owner="zz")
register_group("zz_ok_group", "測試群組", [], help="x")
'''
BAD_SRC = '''
_mt.register("zz_undeclared_mail", "測試信", "approval", "none", "", "影響", "處理", owner="zz")
register_group("zz_undeclared_group", "測試群組", [], help="x")
'''
MANS = {"zz": {"features": [{"code": "zz_f", "label": "x", "mail": ["zz_ok_mail"], "settings": {"group": "zz_ok_group"}}]}}


def _found(src, file="modules/zz/a.py"):
    return {(file, k, key): ln for k, key, ln in S.scan_source(src)}


def test_real_tree_has_no_undeclared_literal_registrations():
    found, mans, entries = S.scan_tree(), S.manifests(), S.allowlist_entries()
    assert found, "掃描器在真實樹上一筆都沒掃到——掃描器壞了（正對照）"
    assert S.problems(found, mans, entries) == []


def test_positive_control_undeclared_literals_are_caught():
    assert S.scan_source(GOOD_SRC) and S.scan_source(BAD_SRC)
    assert S.problems(_found(GOOD_SRC), MANS, []) == []                                  # 有宣告 ⇒ 通過
    p = S.problems(_found(BAD_SRC), MANS, [])
    assert len(p) == 2 and any("zz_undeclared_mail" in x for x in p) and any("zz_undeclared_group" in x for x in p)


def test_scanner_only_reads_exact_literals():
    src = "for _k in ('a', 'b'):\n    _mt.register(_k, 'n', 'business', 'none', '', 'i', 'a')\nregister_group(name_var, 'x', [])\nother.register('k', 'n', 'weird', 'none')\n"
    assert S.scan_source(src) == []                                                      # 變數鍵、非信件分類：不是字面案例，不掃


def _entry(**kw):
    e = {"kind": "mail_register", "file": "modules/zz/a.py", "keys": ["zz_undeclared_mail"], "reason": "既有", "owner": "zz", "expires": "2999-01-01"}
    e.update(kw)
    return e


def test_allowlist_entry_suppresses_but_must_stay_valid():
    found = _found(BAD_SRC)
    ok = [_entry(), _entry(kind="settings_group", keys=["zz_undeclared_group"])]
    assert S.problems(found, MANS, ok) == []
    assert any("對不上" in x for x in S.problems(_found(GOOD_SRC), MANS, [_entry()]))                       # 程式已移除 ⇒ 白名單失效
    declared_now = {"zz": {"features": [{"code": "zz_f", "label": "x", "mail": ["zz_undeclared_mail"]}]}}
    assert any("已不需要" in x for x in S.problems(_found(BAD_SRC), declared_now, [_entry()]))               # 已補宣告 ⇒ 請移出白名單
    assert any("已過期" in x for x in S.problems(found, MANS, [_entry(expires="2020-01-01"), _entry(kind="settings_group", keys=["zz_undeclared_group"])], today=date(2026, 10, 13)))
    for fld in ("reason", "owner", "expires"):
        assert any("缺 " + fld in x for x in S.problems(found, MANS, [_entry(**{fld: ""})]))
    assert any("格式不對" in x for x in S.problems(found, MANS, [_entry(expires="soon")]))


def test_allowlist_file_is_well_formed():
    for e in S.allowlist_entries():
        assert e["kind"] in ("mail_register", "settings_group") and e["file"].startswith("modules/") and e["keys"] == sorted(e["keys"])
