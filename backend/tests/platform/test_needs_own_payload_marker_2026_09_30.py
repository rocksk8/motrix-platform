# -*- coding: utf-8 -*-
"""去識別化：`needs_own_payload` marker 的規則（SALE-PACKAGE-DEID.md §9；使用者裁示 2026-09-28：本公司資料不進程式庫）。

- 缺檔：一般開發機 ⇒ skip（印原因與產生指令）；列車（MOTRIX_TRAIN=1）或建包（MOTRIX_REQUIRE_OWN_PAYLOAD=1）⇒ **紅**，不可靜默略過
- 有檔：照跑
- 沒標 marker 的題完全不受影響
- 標了 marker 的題數不得少於基線（避免有人拿掉 marker 逃過「缺檔＝紅」）
"""
import ast
import types
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
#: 目前標了 needs_own_payload 的測試函式數（tests/platform/test_frozen_migrations_deid_2026_09_30.py：3 個函式，參數化展開更多）
MARKED_BASELINE = 3


def _gate():
    """從 conftest.py 抽出 `_needs_own_payload_gate` 的原始碼單獨執行（不 import conftest：它會做全域測試環境設定）。"""
    src = (BACKEND / "conftest.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_needs_own_payload_gate")
    ns = {"pytest": pytest}
    exec(compile("import pytest\n" + ast.get_source_segment(src, fn, padded=False).replace("@pytest.fixture(autouse=True)\n", "", 1), "gate", "exec"), ns)
    return ns["_needs_own_payload_gate"]


def _outcome(req):
    """gate 的結果：("none"|"skip"|"fail", 訊息)。**不用 pytest.raises**：Skipped 是 BaseException，被丟進 raises 外面會讓「這題」被記成 skip
    而不是紅——突變（把 fail 改成 skip）就會被悄悄放過。"""
    try:
        _gate()(req)
    except pytest.skip.Exception as e:
        return "skip", str(e)
    except pytest.fail.Exception as e:
        return "fail", str(e)
    return "none", ""


class _Node:
    def __init__(self, marked):
        self._m = marked

    def get_closest_marker(self, name):
        return object() if (self._m and name == "needs_own_payload") else None


class _Req:
    def __init__(self, marked):
        self.node = _Node(marked)


@pytest.fixture
def no_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(tmp_path / "missing.json"))
    monkeypatch.delenv("MOTRIX_TRAIN", raising=False)
    monkeypatch.delenv("MOTRIX_REQUIRE_OWN_PAYLOAD", raising=False)


def test_missing_payload_skips_on_a_dev_machine_and_says_how_to_generate(no_payload):
    kind, msg = _outcome(_Req(True))
    assert kind == "skip" and "own_payload.py generate" in msg and "缺本公司資料檔" in msg, (kind, msg)


@pytest.mark.parametrize("var", ["MOTRIX_TRAIN", "MOTRIX_REQUIRE_OWN_PAYLOAD"])
def test_missing_payload_is_red_on_the_train_or_when_building(no_payload, monkeypatch, var):
    monkeypatch.setenv(var, "1")
    kind, msg = _outcome(_Req(True))
    assert kind == "fail" and "缺檔視為紅" in msg, (kind, msg)


def test_unmarked_tests_are_never_affected(no_payload, monkeypatch):
    monkeypatch.setenv("MOTRIX_TRAIN", "1")
    assert _outcome(_Req(False)) == ("none", "")


def test_a_valid_payload_lets_marked_tests_run(monkeypatch, tmp_path):
    import json
    import sys
    sys.path.insert(0, str(BACKEND.parent / "tools" / "platform"))
    import own_payload as OP
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"v": 1, "source_blob": OP.PINNED_BLOB, "m008": {"correct": "x", "email": "y"}, "m106": {"company_name_en": "z"}}), encoding="utf-8")
    monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(f))
    monkeypatch.setenv("MOTRIX_TRAIN", "1")
    assert _outcome(_Req(True)) == ("none", "")


def test_a_payload_of_another_version_is_treated_as_missing(monkeypatch, tmp_path):
    import json
    f = tmp_path / "p.json"
    f.write_text(json.dumps({"v": 1, "source_blob": "0" * 40, "m008": {}, "m106": {}}), encoding="utf-8")
    monkeypatch.setenv("MOTRIX_OWN_PAYLOAD", str(f))
    monkeypatch.setenv("MOTRIX_TRAIN", "1")
    assert _outcome(_Req(True))[0] == "fail"


def _marked_function_count():
    n = 0
    for root in (BACKEND / "tests", BACKEND / "modules"):
        for p in root.rglob("test_*.py"):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for f in ast.walk(tree):
                if isinstance(f, ast.FunctionDef) and any("needs_own_payload" in ast.dump(d) for d in f.decorator_list):
                    n += 1
    return n


def test_the_number_of_marked_tests_never_drops_below_the_baseline():
    assert _marked_function_count() >= MARKED_BASELINE, "標了 needs_own_payload 的題變少了：有人拿掉 marker 逃過「缺檔＝紅」？"


def test_marker_is_registered_and_the_gate_exists():
    ini = (BACKEND / "pytest.ini").read_text(encoding="utf-8")
    assert "needs_own_payload:" in ini
    assert "_needs_own_payload_gate" in (BACKEND / "conftest.py").read_text(encoding="utf-8")
