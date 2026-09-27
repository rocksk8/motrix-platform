"""custom-records.html 的 JS 端 HTML 寫入點：只准白名單上審過的那幾處（BUILDER-UX §4；A，2026-09-28，稽核 AB42-S1）。

`test_custom_records_no_x_html_2026_09_28` 只擋 Alpine 屬性（x-html／:innerHTML）；同一類風險在 JS 端還有
`document.write`、`.innerHTML =`、`.outerHTML =`、`insertAdjacentHTML`，以及把字串當整頁 HTML 的 `:srcdoc`。
這一頁畫的全是使用者自訂內容（預覽時是編到一半的草稿）⇒ 新的寫入點一律要先審、登記在 `ALLOWED`（附理由）。

- 每一處寫入點以「種類＋所在位置」辨認：JS 的位置＝包住它的 Alpine 方法名稱；屬性的位置＝那個元素的 id。
  ⇒ 白名單是**逐處**的，不是整類排除：同一種寫法出現在別的方法裡照樣紅。
- 雙向：頁面上的寫入點 ⊆ 白名單（新的沒審 ⇒ 紅）；白名單每一筆都要真的在頁面上（改名、搬走 ⇒ 過期 ⇒ 紅）。
- 上限 `MAX_ALLOWED`＝5 筆，每筆理由至少 20 字：白名單不可以變成萬用排除。
- 正對照：植入一處新的 document.write ⇒ 紅。反向控制：白名單那兩處改名 ⇒ 紅（寫入點變成未登記、白名單同時過期）；
  字面相近的（比較、註解以外的屬性名、`innerHTMLx`）不算。真實題與對照走同一支 `sink_sites`／`check`。
"""
import re

#: (種類, 正規式)。`innerHTML ==`（比較）不算；`insertAdjacentHTML`／`document.write(ln)` 看呼叫。
SINK_KINDS = (
    ("document.write", re.compile(r"\bdocument\.write(?:ln)?\s*\(")),
    ("innerHTML=", re.compile(r"\.innerHTML\s*(?:\+)?=(?!=)")),
    ("outerHTML=", re.compile(r"\.outerHTML\s*(?:\+)?=(?!=)")),
    ("insertAdjacentHTML", re.compile(r"\binsertAdjacentHTML\s*\(")),
    ("srcdoc", re.compile(r"""(?<![\w-])(?:x-bind:|:)?srcdoc\s*=""", re.IGNORECASE)),
)
_METHOD = re.compile(r"^\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")
#: `if (w) {`、`for (…) {` 也長得像方法定義 ⇒ 排除（:682 那行本身就是 `if (w) { … document.write … }`）
_NOT_METHODS = frozenset({"if", "for", "while", "switch", "catch", "function", "with", "return"})
_ID = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""")

MAX_ALLOWED = 5
#: 審過的寫入點：(種類, 位置) → 理由（審核者、依據）
ALLOWED = {
    ("document.write", "openOutput"):
        "「輸出 HTML」把伺服器產生的輸出版型寫進新開的列印視窗；內容由後端 renderer 逐欄轉義"
        "（D 2026-09-27 23:52 稽核：草稿 XSS 前後端探針皆轉義），前端不拼接使用者字串。A 2026-09-28 審。",
    ("srcdoc", "cr-output-frame"):
        "單據頁內嵌的輸出預覽；iframe 帶 sandbox=\"\"（不給 scripts、不給 same-origin），"
        "就算內容含腳本也不會執行、讀不到登入資訊。A 2026-09-28 審。",
}


def sink_sites(text):
    """回傳 [(種類, 位置, 行號)]。位置：屬性 ⇒ 該行元素的 id（沒有 ⇒ "?"）；JS ⇒ 往上最近的方法名稱（沒有 ⇒ "?"）。"""
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        for kind, rx in SINK_KINDS:
            if not rx.search(line):
                continue
            if kind == "srcdoc":
                m = _ID.search(line)
                where = m.group(1) if m else "?"
            else:
                where = "?"
                for j in range(i, -1, -1):
                    m = _METHOD.match(lines[j])
                    if m and m.group(1) not in _NOT_METHODS:
                        where = m.group(1)
                        break
            out.append((kind, where, i + 1))
    return out


def check(sites, allowed=None):
    """⇒ 問題清單（空＝通過）：未登記的寫入點、過期的白名單、白名單超量或理由太短。"""
    allowed = ALLOWED if allowed is None else allowed
    problems = []
    found = {(k, w) for k, w, _n in sites}
    for k, w, n in sites:
        if (k, w) not in allowed:
            problems.append("第 %d 行：%s（位置 %s）沒有登記在白名單——先審，再附理由登記" % (n, k, w))
    for key in sorted(allowed):
        if key not in found:
            problems.append("白名單 %s 在頁面上找不到（改名或搬走了）⇒ 過期，重新審過再登記" % (key,))
    if len(allowed) > MAX_ALLOWED:
        problems.append("白名單 %d 筆，超過上限 %d" % (len(allowed), MAX_ALLOWED))
    for key, why in allowed.items():
        if len((why or "").strip()) < 20:
            problems.append("白名單 %s 的理由太短（至少 20 字）" % (key,))
    return problems


def _page_text():
    from core import source_tree
    return source_tree.page_file("custom-records.html").read_text(encoding="utf-8")


def test_custom_records_js_html_sinks_are_all_reviewed():
    problems = check(sink_sites(_page_text()))
    assert not problems, "\n".join(problems)


def test_positive_control_a_new_document_write_lights_up():
    """正對照：在真頁面植入一處新的 document.write（新的方法裡）⇒ 未登記 ⇒ 紅。"""
    src = _page_text()
    anchor = "        async openOutput() {"
    assert anchor in src, "植入點不見了（頁面改版）⇒ 換一個植入點，不可以讓對照失效"
    planted = src.replace(anchor, "        debugDump() {\n          document.write(this.errMsg)\n        },\n" + anchor, 1)
    problems = check(sink_sites(planted))
    assert len(problems) == 1 and "document.write" in problems[0] and "debugDump" in problems[0], problems


def test_reverse_control_renaming_an_allowed_site_is_red():
    """反向控制：白名單的兩處改名 ⇒ 各自變成未登記＋白名單過期（證明白名單是逐處、不是整類排除）。"""
    src = _page_text()
    renamed = src.replace("async openOutput() {", "async openOutput2() {", 1)
    p1 = check(sink_sites(renamed))
    assert any("openOutput2" in p for p in p1) and any("過期" in p and "openOutput" in p for p in p1), p1
    renamed = src.replace('id="cr-output-frame"', 'id="cr-output-frame2"', 1)
    p2 = check(sink_sites(renamed))
    assert any("cr-output-frame2" in p for p in p2) and any("過期" in p for p in p2), p2


def test_reverse_control_look_alikes_and_register_limits():
    text = ("        f() {\n"
            "          if (el.innerHTML == x) return\n"
            "          el.innerHTMLx = 1\n"
            "          el.textContent = s\n"
            "        },\n"
            '<i data-srcdoc-note="1"></i>\n')
    assert sink_sites(text) == []
    many = {("innerHTML=", "m%d" % i): "x" * 30 for i in range(MAX_ALLOWED + 1)}
    assert any("超過上限" in p for p in check([], many))
    assert any("理由太短" in p for p in check([("innerHTML=", "m0", 1)], {("innerHTML=", "m0"): "ok"}))
    assert check([("innerHTML=", "m0", 1)], {("innerHTML=", "m0"): "x" * 30}) == []
