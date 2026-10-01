"""W2 稽核：`/api/approval-queue/count` 的單據標籤（approval_queue.py `_ITEM_TYPE_LABELS`）與簽核佇列頁的
`docTypeLabel()`（approval-queue.html）是兩份表，必須一致——否則首頁與佇列頁對同一張單講不同的話。
"""
import re
from pathlib import Path

from core import source_tree
from routers import approval_queue as aq

_RE = re.compile(r"item\.type === '([a-z_]+)'\) return (?:item\.typeLabel \|\| )?'([^']+)'")      # 費用單據（A2）卡片：`item.typeLabel || '案件額外支出'`，後者是預設標籤


def _html_labels():
    html = source_tree.page_file("approval-queue.html").read_text(encoding="utf-8")
    start = html.index("docTypeLabel(item) {")
    body = html[start:start + 4000]
    return dict(_RE.findall(body))


def test_label_tables_agree():
    html = _html_labels()
    assert html, "讀不到 docTypeLabel 的標籤（樣板改了寫法？這題要跟著改）"
    assert aq._ITEM_TYPE_LABELS == html, (
        "兩份標籤表不一致：\n only-py=%s\n only-html=%s\n diff=%s" % (
            sorted(set(aq._ITEM_TYPE_LABELS) - set(html)), sorted(set(html) - set(aq._ITEM_TYPE_LABELS)),
            {k: (aq._ITEM_TYPE_LABELS[k], html[k]) for k in set(aq._ITEM_TYPE_LABELS) & set(html)
             if aq._ITEM_TYPE_LABELS[k] != html[k]}))


def test_scanner_positive_control_sees_a_known_label():
    """量尺：解析器要認得已知的一筆（否則上一題會在「解析出空表」時被 assert html 擋住，但這裡再確認一次它真的解析得到）。"""
    assert _html_labels().get("shipping_note") == "出貨單"
