# -*- coding: utf-8 -*-
"""支出申請用語（第44班，使用者裁示）：屬於「支出申請」那一邊的畫面字樣不再出現「請款」；客戶「請款單」（M05 對客戶要款）不改。
只釘畫面字串（頁面、提示訊息、範本名稱），不釘資料鍵。"""
import json
from pathlib import Path

import pytest

from core import source_tree

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

#: （檔案, 不可再出現的舊字樣）——這些檔案的「請款」都屬支出申請那一邊
GONE = [
    (source_tree.page_file("payment-request.html"), ["② 請款內容", "我的請款", "還沒有請款"]),
    (source_tree.page_file("expense-types.html"), ["請款單的樣子"]),
    (source_tree.page_file("ledger-settings.html"), ["額外支出、請款"]),
    (source_tree.page_file("bank-account.html"), ["請款或報銷"]),
    (BACKEND / "modules" / "case" / "payables.py", ["這筆請款"]),
    (BACKEND / "modules" / "case" / "api" / "case_extra_expenses.py", ["這筆請款還沒核准", "請款人登錄"]),
    (BACKEND / "modules" / "arap" / "api" / "cashier.py", ["找不到請款來源", "請款付款明細", '"請款付款"']),
]

#: 客戶「請款單」不可被誤改
KEPT = [
    (source_tree.page_file("payment-request-form.html"), ["新增請款單", "編輯請款單"]),
    (BACKEND / "modules" / "arap" / "api" / "payment_requests.py", ["請款單 {request_no}", "請款單不存在"]),
    (BACKEND / "helpers" / "mail_types.py", ["請款單待審核"]),
]


@pytest.mark.parametrize("path,words", GONE, ids=lambda v: v.name if isinstance(v, Path) else "")
def test_expense_side_screens_no_longer_say_qingkuan(path, words):
    text = path.read_text(encoding="utf-8-sig")
    for w in words:
        assert w not in text, "%s 還有舊字樣「%s」（支出申請用語）" % (path.name, w)


@pytest.mark.parametrize("path,words", KEPT, ids=lambda v: v.name if isinstance(v, Path) else "")
def test_customer_payment_request_wording_is_untouched(path, words):
    text = path.read_text(encoding="utf-8-sig")
    for w in words:
        assert w in text, "%s 的客戶「請款單」字樣「%s」不該被改" % (path.name, w)


def test_standalone_expense_template_is_named_expense_application_but_keeps_its_key():
    d = json.loads((BACKEND / "helpers" / "form_templates" / "payment_request.json").read_text(encoding="utf-8-sig"))
    assert d["key"] == "payment_request", "範本 key 是資料鍵，不能改"
    assert d["name"] == "支出申請單" and d["body"]["name"] == "支出申請單"
    assert "請款" not in json.dumps({k: v for k, v in d.items() if k != "key"}, ensure_ascii=False)
