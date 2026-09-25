"""M11 標案雷達在 L1／平台守門裡的正對照（2026-09-25 自各 L1 測試拆出）。

L1 守門改成不綁特定 L2 模組；「M11 的檔／端點／開關／通知 key／訊息真的被那些守門看見」由 M11 自己釘。
刪掉整個 modules/tender_radar 時這些題跟著消失，L1 守門不受影響。
"""
import ast
from pathlib import Path

import pytest

from core import source_tree
from tests.test_navigation_destination_2026_09_23 import _page_text, _scan_all_nav_messages  # noqa: F401

HERE =Path(__file__).resolve().parent
MOD = HERE.parent
REL = "modules/tender_radar"


def test_source_tree_covers_this_module():
    rels = {source_tree.rel(p) for p in source_tree.router_files()}
    assert REL + "/api.py" in rels
    logic = {source_tree.rel(p) for p in source_tree.logic_files()}
    assert REL + "/source.py" in logic
    assert REL + "/api.py" not in logic


def test_audit_scanner_sees_the_watch_post():
    from tests.test_write_endpoints_are_audited_2026_09_24 import _all, is_audited
    by = {(f, m, p): fn for f, m, p, fn in _all()}
    assert is_audited(by[(REL + "/api.py", "POST", "/api/tender-radar/watches")])


def test_runtime_switch_is_reported(client, make_user):
    from tests.test_runtime_switches_2026_09_22 import _get, _login
    body = _get(client, _login(client, make_user))
    names = {s.get("name") for s in body.get("switches") or []}
    assert "MOTRIX_TENDER_RADAR" in names, sorted(names)


def test_notify_event_keys_are_seen_and_registered():
    """搬出去的三個 key：notify.py 以 `_admin_emails("<key>", ...)` 使用，且都已註冊。"""
    from helpers.notification_prefs import EVENT_KEYS
    tree = ast.parse((MOD / "notify.py").read_text(encoding="utf-8"))
    used = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and (getattr(n.func, "attr", None) or getattr(n.func, "id", None)) \
                in ("_admin_emails", "_superadmin_emails") and n.args \
                and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
            used.add(n.args[0].value)
    keys = {"tender_found", "tender_fetch_failed", "tender_source_changed"}
    assert keys <= used, sorted(used)
    assert keys <= set(EVENT_KEYS), sorted(keys - set(EVENT_KEYS))


def test_the_settings_message_did_not_change():
    from tests.test_em1_screen_words_in_long_messages_2026_09_24 import _all_details
    assert "沒有要變更的設定（scanHours／notifyHours）" in _all_details(REL + "/api.py")


#: M11 的導航語氣訊息數（2026-09-25 量得 6）；只准變多，理由同 test_navigation_destination 的基準
_NAV_BASELINE = 6


def test_nav_messages_in_this_module_do_not_drop():
    from tests.test_navigation_destination_2026_09_23 import _scan_all_nav_messages
    hits = [(p, s) for p, s in _scan_all_nav_messages() if REL in str(p).replace("\\", "/")]
    assert len(hits) >= _NAV_BASELINE, hits


def test_tender_radar_health_message_points_to_a_findable_label():
    """（原 EM10 的一部分，2026-09-25 自 tests/test_navigation_destination 拆出；編號由原檔承擔，這裡不重複認領）

    🔴🔴 **`②` `email_notify.py`：訊息說去看「雷達健康狀態」，畫面上沒有這五個字。**

    `tender-radar.html` 那個健康區塊的標題是 `x-text="healthText"`——
    動態文字，沒有固定的「雷達健康狀態」這個標籤。

    ✅ **A 已裁定修法方向：乙**（在畫面上加一個固定小標，不是改訊息
    措辭）——判準：「便宜的修法」與「可被守門看見的修法」之間選後者，
    改措辭會把一個可比對的東西變成不可比對的，讓同一類缺陷下次可以
    再長出來而沒有人發現。⇒ 本題直接釘「乙」落地後的樣子：畫面上要
    找得到「雷達健康狀態」這個固定字串。
    """
    hits = _scan_all_nav_messages()
    msg = next((s for p, s in hits if "雷達健康狀態" in s), None)
    assert msg is not None, "找不到那句訊息——退回改本檔的錨點。"
    page = _page_text("tender-radar.html")
    assert "雷達健康狀態" in page, (
        "訊息說要去看「雷達健康狀態」，而 `tender-radar.html` 裡找不到\n"
        "這個固定字串——健康區塊的標題目前是 `x-text=\"healthText\"`\n"
        "（動態文字）。A 已裁乙案：請在畫面上加一個固定小標「雷達健康"
        "狀態」，讓這個目的地變得可比對。")


def test_the_politeness_delay_is_zero_in_tests():
    """⚙️ `_no_politeness_delay` 的**生效那一側**。

    ☠️ 少了這一題，那支 fixture 哪天失效（常數改名、模組搬家）
    會讓整個 suite **安靜地慢回去** —— 而慢不會讓任何一題紅。
    🔑 而「設回去真的會 sleep」那一側由
    `test_tender_detail_2026_09_21.py::test_d3_…` 守 —— **兩題成對。**

    ## ☠️ 而這一題原本寫在 `conftest.py` 裡，**pytest 根本不收集它**

    ```
    $ pytest tests/ --collect-only -k politeness
      no tests collected (1939 deselected)
    ```
    🔑 **一個不會被收集的「對照組」，與沒有對照組完全相同** ——
    而它在 `conftest.py` 裡看起來像一題（有 `def test_`、有斷言、有 docstring）。
    📌 是我跑 `--collect-only -k` 去查才發現的，**不是它報錯**。
    ⇒ 寫完一個新的對照組，**第一件事是確認它真的被收集到**。
    """
    from modules.tender_radar import source as tender_source
    assert tender_source.DETAIL_INTERVAL_SECONDS == 0, (
        f"測試裡的 `DETAIL_INTERVAL_SECONDS` 是 "
        f"{tender_source.DETAIL_INTERVAL_SECONDS}，預期 0 ——\n"
        "☠️ `_no_politeness_delay` 沒有生效（常數改名？模組搬家？），\n"
        "🔑 而它失效的症狀只有「整個 suite 慢回去」，**沒有任何一題會紅**。")
