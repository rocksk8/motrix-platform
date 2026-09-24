"""簽核設定頁不可以把內部設定鍵（unified_approval_flow、quotation_approval_flow…）顯示給使用者。

2026-09-25 使用者：「簽核設定的文字都顯示 unified_approval_flow 跟 quotation_approval_flow」。
成因：AS1（09-23）在「統一流程／獨立設定」兩側各加了一個 <code> 顯示寫入的設定鍵，
那是給工程看的資訊，畫面上只該有「統一流程／獨立設定」與目前生效的簽核人。
觀測點：頁面上任何 x-text／x-html 綁定都不可以輸出 flowSettingKeys 的值。
正對照：flowSettingKeys 本身仍存在（存檔要用），只是不顯示。
"""
import re
from pathlib import Path

PAGE = Path(__file__).resolve().parents[2] / "frontend" / "pages" / "approval-settings.html"


def test_internal_setting_keys_are_not_rendered():
    src = PAGE.read_text(encoding="utf-8")
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    assert "flowSettingKeys" in src, "正對照：設定鍵對照表本身應仍存在（存檔要用）"
    bound = re.findall(r'x-(?:text|html)="([^"]*)"', src)
    leaking = [b for b in bound if "flowSettingKeys" in b or "_approval_flow" in b]
    assert not leaking, "畫面把內部設定鍵顯示出來：%s" % leaking
