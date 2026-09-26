"""自 `tests/test_module_history_2026_09_23.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import json
import re
import sqlite3
from pathlib import Path
import pytest
import db
from tests.test_module_history_2026_09_23 import (  # noqa: E402,F401  含 fixture
    _BACKEND,
)


def test_the_audit_action_naming_convention_is_already_in_use():
    """⚙️ **`<module>.<verb>` 這個命名不是我發明的** —— 既有 34 支已經在用。

    ```
    reports.py:2352  _audit(…, "reports.export", …)
    reports.py:2837  _audit(…, "reports.bank_reconcile", …)
    ```
    📌 ⇒ `③` 沿用 `audit_log` 時**不必發明新慣例**，跟上就好。
    ⚠️ 而我順手複核了施工圖的「reports.py 有 8 處寫入」：
       `_audit(` **4** ／ `_set_setting` **3** ／ 第 8 個是 `:24` 的 **import**
       ⇒ 真正的寫入是 **7**。結論成立，而數字要更正（已回報）。
    """
    src = (_BACKEND / "modules" / "analytics" / "api" / "reports.py").read_text(encoding="utf-8")
    actions = set(re.findall(r'_audit\([^,]+,\s*"([a-z_]+\.[a-z_]+)"', src))
    assert actions, (
        "`reports.py` 裡找不到 `<module>.<verb>` 形狀的 `_audit(` 呼叫 ——\n"
        + "🔑 那個慣例變了 ⇒ `③` 的命名規則要重訂。")
    assert all("." in a for a in actions), (
        "有 action 不是 `<module>.<verb>` 形狀：%s" % sorted(actions))
