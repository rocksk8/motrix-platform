"""自 `tests/test_navigation_destination_2026_09_23.py` 拆出（M08 搬遷反向控制：這幾題需要營運分析模組，拿掉模組時一起消失）。"""
import ast
import pathlib
import re
import pytest
from tests.test_navigation_destination_2026_09_23 import (  # noqa: E402,F401  含 fixture
    ROOT,
    _has_nav_tone,
    _page_text,
    _string_literals_in_py,
    _system_settings_pages,
)


def test_em10_annual_target_message_points_to_the_wrong_place():
    """🔴🔴 **`③` `reports.py:874`：訊息叫使用者去系統設定，年度目標其實在報表頁。**

    使用者照著「請於系統設定中配置年度目標」這句話，會去 `pg__eyebrow`
    標「系統設定」的那一批頁面裡找——而年度目標的設定按鈕
    （`openTargetModal()`）長在 `reports.html` 自己身上，不在那一批頁面
    裡的任何一頁。

    ⚙️ 核心斷言是**訊息本身不可以再提「系統設定」**——那是可以直接對
    訊息原始碼下的紅色斷言，不管 B 最後把措辭改成什麼樣子（例如「請在
    本頁『立即設定年度目標』按鈕設定」），只要不再指向錯的地方就過；
    下面兩段是**佐證**（釘住「系統設定」與「年度目標實際在哪裡」這兩個
    事實本身不會漂移），不是驗收的核心那一格。
    """
    msg = next((s for s in _string_literals_in_py(
                   ROOT / "backend" / "modules" / "analytics" / "api" / "reports.py")
               if "年度目標" in s and _has_nav_tone(s)), None)
    assert msg is not None, "找不到年度目標那句導航訊息——退回改本檔的錨點。"
    assert "系統設定" not in msg, (
        "`reports.py` 的年度目標訊息仍然說「系統設定」：%r\n" % msg
        + "☠️ 使用者會去系統設定翻一輪，而那裡沒有年度目標——\n"
          "   實際的設定按鈕在 `reports.html` 自己身上。")

    settings_pages = _system_settings_pages()
    assert settings_pages, "一頁『系統設定』分類的頁面都找不到——退回改本檔的判定法。"
    for name in settings_pages:
        text = _page_text(name)
        assert "年度目標" not in text, (
            "『系統設定』分類裡的 %s 找到了「年度目標」——\n" % name
            + "這一題的前提（系統設定裡沒有年度目標）已經不成立，"
              "請確認並更新本題。")
    report_text = _page_text("reports.html")
    assert "年度目標" in report_text and "openTargetModal" in report_text, (
        "`reports.html` 裡反而找不到年度目標的設定入口——前置不對。")
