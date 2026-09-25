"""L1 契約：`helpers.auth._require_user()` 回傳的使用者 dict 形狀（PLAYBOOK §C-11a ⑤）。

為什麼在這裡：D1b 的名稱層級選題對 `_require_user` 只擴到直接使用者（router），不再擴到呼叫那些 router 的頁面
與它們的 e2e。反向控制（2026-09-26）：把回傳值拿掉 `modules` 鍵 ⇒ 沒被選中的 181 檔裡，出納的 2 題 e2e 紅了。
使用者裁示「L1 與模組之間靠契約題守，不靠擴大選題」⇒ 形狀改變要在這一題（tests/platform 每次必跑）紅。

鍵的清單＝固定必備 ＋ 掃描產品碼：接住 `_require_user(...)` 回傳值的變數被讀了哪些鍵（`u["k"]`、`u.get("k")`）。
新增一個讀取點，這一題自動涵蓋它。
"""
import ast
import json

import pytest

from core import source_tree

#: 權限判斷的基礎：少了任何一個，模組權限、角色判斷會靜默出錯（user_has_module 讀 modules、角色讀 role）
REQUIRED = {"id", "username", "role", "modules"}


def consumed_keys(sources=None):
    """產品碼（或給定的原始碼清單）裡 `x = _require_user(...)` 之後對 x 讀過的字串鍵。"""
    if sources is None:
        sources = [p.read_text(encoding="utf-8-sig") for p in source_tree.product_files()]
    keys = set()
    for src in sources:
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = set()
            for n in ast.walk(fn):
                if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and \
                        getattr(n.value.func, "id", getattr(n.value.func, "attr", None)) == "_require_user":
                    names |= {t.id for t in n.targets if isinstance(t, ast.Name)}
            if not names:
                continue
            for n in ast.walk(fn):
                if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id in names \
                        and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
                    keys.add(n.slice.value)
                elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" \
                        and isinstance(n.func.value, ast.Name) and n.func.value.id in names and n.args \
                        and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                    keys.add(n.args[0].value)
    return keys


def test_scanner_finds_consumers():
    """正對照：掃得到產品碼對 _require_user 回傳值的讀取（掃描壞掉時下一題會只驗固定鍵）。"""
    got = consumed_keys()
    assert {"role", "username"} <= got, got


def test_require_user_returns_every_consumed_key(client, make_user):
    from helpers.auth import _require_user
    u, p = make_user(username="contract_u", role="admin", modules=["cashier", "case_manage"])
    token = client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]
    user = _require_user("Bearer " + token)
    missing = sorted((REQUIRED | consumed_keys()) - set(user))
    assert not missing, "_require_user 回傳值少了使用端會讀的鍵：%s" % missing
    assert json.loads(user["modules"]) == ["cashier", "case_manage"], "modules 必須是可解析成清單的 JSON 字串"
    assert user["role"] == "admin" and user["username"] == u


def test_rc_scanner_sees_a_new_consumer():
    """反向控制：新的讀取點會被掃描器算進去（不然新增的鍵永遠不在契約裡）。"""
    src = ("def f(a):\n"
           "    me = _require_user(a)\n"
           "    return me['brand_new_key'], me.get('other_key')\n")
    assert consumed_keys([src]) == {"brand_new_key", "other_key"}
