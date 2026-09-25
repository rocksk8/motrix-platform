"""自 `tests/test_em1_screen_words_in_long_messages_2026_09_24.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import ast
import pathlib
from tests.test_em1_screen_words_in_long_messages_2026_09_24 import (  # noqa: E402,F401  含 fixture
    _UNTOUCHED,
    _all_details,
)


def test_em1_the_other_long_messages_did_not_change_a_single_character():
    missing = []
    cache = {}
    for rel, msg in _UNTOUCHED:
        if not rel.startswith("modules/analytics/"):   # 其餘：tests/test_em1_screen_words_in_long_messages_2026_09_24.py
            continue
        if rel not in cache:
            cache[rel] = set(_all_details(rel))
        if msg not in cache[rel]:
            missing.append((rel, msg[:60]))
    assert not missing, (
        "這些長訊息被改了或不見了（EM1 只改 5 條，其餘一個字都不動）：\n%s"
        % "\n".join("  %s  %r" % x for x in missing))
