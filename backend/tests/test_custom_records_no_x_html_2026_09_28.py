"""custom-records.html 不准用 x-html（BUILDER-UX §4；B，2026-09-28）。

這一頁畫的內容全部來自使用者自訂：欄位標籤、說明、選項、紀錄的值——建構器預覽時還是**編到一半的草稿**。
x-html 會把這些字串當 HTML 解析 ⇒ 一律用 x-text（D 23:52 稽核：草稿 XSS 前後端探針皆轉義，這道守門把它固定下來）。
Alpine 另外兩種把字串塞進 innerHTML 的寫法（`x-bind:innerHTML`、`:innerHTML`）一併擋。

- 掃描對象用 `source_tree.page_file` 取（模組化後頁面搬家也找得到）；找不到 ⇒ 紅，不略過（§G5-15：略過條件不取自被檢查的東西）。
- 正對照：在真頁面的內容裡植入一處 x-html ⇒ 要亮，而且指出行號；三種寫法各植入一次。
- 反向控制：x-text、`data-x-html-note` 這類只是字面相近的不算。真實題與對照走同一支 `html_sinks`。
"""
import re

HTML_SINK = re.compile(r"""(?<![\w-])(?:x-html|x-bind:innerHTML|:innerHTML)\s*=""", re.IGNORECASE)


def html_sinks(text):
    """回傳 [(行號, 該行)]：每一處把字串當 HTML 放進 DOM 的 Alpine 綁定。"""
    return [(i, line.strip()) for i, line in enumerate(text.splitlines(), 1) if HTML_SINK.search(line)]


def _page_text():
    from core import source_tree
    return source_tree.page_file("custom-records.html").read_text(encoding="utf-8")


def test_custom_records_has_no_html_sink():
    hits = html_sinks(_page_text())
    assert hits == [], "custom-records.html 畫的是使用者自訂內容，要用 x-text：%r" % hits


def test_positive_control_planted_sink_lights_up():
    src = _page_text()
    anchor = '<body x-data="customRecordsPage()"'
    assert anchor in src, "植入點不見了（頁面改版）⇒ 換一個植入點，不可以讓對照失效"
    base_line = src[:src.index(anchor)].count("\n") + 1
    for attr in ('x-html="record.data.item"', 'x-bind:innerHTML="f.help"', ':innerHTML="f.label"'):
        planted = src.replace(anchor, '<span %s></span>\n%s' % (attr, anchor), 1)
        hits = html_sinks(planted)
        assert [n for n, _ in hits] == [base_line], (attr, hits)


def test_reverse_control_look_alikes_do_not_count():
    text = '<span x-text="f.label"></span>\n<i data-x-html-note="1"></i>\n<!-- 不用 x-html -->\n<b :title="f.help"></b>'
    assert html_sinks(text) == []
