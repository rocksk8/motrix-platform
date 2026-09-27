"""畫使用者自訂內容的前端檔：JS 端 HTML 寫入點只准白名單上審過的那幾處（BUILDER-UX §4；A，2026-09-28，稽核 AB42-S1、D BS1／BO1）。

`test_custom_records_no_x_html_2026_09_28` 只擋 Alpine 屬性（x-html／:innerHTML）；同一類風險在 JS 端還有
`document.write`、`.innerHTML =`、`.outerHTML =`、`insertAdjacentHTML`、`setHTMLUnsafe`、`createContextualFragment`，
以及把字串當整頁 HTML 的 `srcdoc`。

掃描的檔（`TARGETS`）：custom-records.html（單據頁；預覽時畫編到一半的草稿）、static/form-preview.js（建構器的即時預覽與縮圖，
D BS1：管理員互相看得到草稿，這一檔出一次疏失＝管理員之間的儲存型 XSS）、static/custom-layout.js（欄位排版，目前 0 處）。

- 每一處寫入點以「種類＋所在位置」辨認：JS 的位置＝包住它的函式名稱（Alpine 方法、`function 名稱(`、`名稱: function (`）；
  帶 id 的屬性（例 `:srcdoc`）＝那個元素的 id。⇒ 白名單是**逐處**的，不是整類排除：同一種寫法出現在別的函式裡照樣紅。
- 雙向：檔裡的寫入點 ⊆ 該檔白名單（新的沒審 ⇒ 紅）；白名單每一筆都要真的在檔裡（改名、搬走 ⇒ 過期 ⇒ 紅）。
- 上限 `MAX_ALLOWED`＝每個檔 5 筆，每筆理由至少 20 字：白名單不可以變成萬用排除。
- 正對照：植入一處新的 document.write ⇒ 紅。反向控制：白名單的位置改名 ⇒ 紅；字面相近的不算。真實題與對照走同一支 `sink_sites`／`check`。

⚠ **已知限制（D BO1；刻意不擋，寫在這裡）**：本守門偵測「不小心寫出來」的形狀，不防刻意繞過——
`el['innerHTML'] = s`（中括號寫法）、`Object.assign(el, {innerHTML: s})`、`document` 換行後接 `.write(s)` 都不會亮。
同一種寫法在同一個已登記的函式裡多出第二處也不會亮（D BO2）。這些由稽核讀碼負責；守門擋的是新的一般寫法。
"""
import re

#: (種類, 正規式)。`innerHTML ==`（比較）不算；`insertAdjacentHTML`／`document.write(ln)`／`setHTMLUnsafe`／
#: `createContextualFragment` 看呼叫。
SINK_KINDS = (
    ("document.write", re.compile(r"\bdocument\.write(?:ln)?\s*\(")),
    ("innerHTML=", re.compile(r"\.innerHTML\s*(?:\+)?=(?!=)")),
    ("outerHTML=", re.compile(r"\.outerHTML\s*(?:\+)?=(?!=)")),
    ("insertAdjacentHTML", re.compile(r"\binsertAdjacentHTML\s*\(")),
    ("setHTMLUnsafe", re.compile(r"\bsetHTMLUnsafe\s*\(")),
    ("createContextualFragment", re.compile(r"\bcreateContextualFragment\s*\(")),
    ("srcdoc", re.compile(r"""(?<![\w-])(?:x-bind:|:)?srcdoc\s*=(?!=)""", re.IGNORECASE)),
)
#: 函式的三種寫法：Alpine 方法 `名稱(…) {`（行首）、`function 名稱(`、`名稱: function (`
_FUNC_PATTERNS = (
    re.compile(r"^\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{"),
    re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\("),
    re.compile(r"\b([A-Za-z_$][\w$]*)\s*:\s*(?:async\s+)?function\s*\("),
)
#: `if (w) {`、`for (…) {` 也長得像方法定義 ⇒ 排除（custom-records.html:682 那行本身就是 `if (w) { … document.write … }`）
_NOT_METHODS = frozenset({"if", "for", "while", "switch", "catch", "function", "with", "return"})
_ID = re.compile(r"""\bid\s*=\s*["']([^"']+)["']""")

MAX_ALLOWED = 5
#: 審過的寫入點：檔 → {(種類, 位置): 理由（審核者、依據）}
ALLOWED_BY_FILE = {
    "custom-records.html": {
        ("document.write", "openOutput"):
            "「輸出 HTML」把伺服器產生的輸出版型寫進新開的列印視窗；內容由後端 renderer 逐欄轉義"
            "（D 2026-09-27 23:52 稽核：草稿 XSS 前後端探針皆轉義），前端不拼接使用者字串。A 2026-09-28 審。",
        ("srcdoc", "cr-output-frame"):
            "單據頁內嵌的輸出預覽；iframe 帶 sandbox=\"\"（不給 scripts、不給 same-origin），"
            "就算內容含腳本也不會執行、讀不到登入資訊。A 2026-09-28 審。",
    },
    "static/form-preview.js": {
        ("srcdoc", "pump"):
            "建構器的輸出預覽：iframe 的 sandbox 只給 allow-same-origin（form-preview.js 建 iframe 那段，不給 scripts），"
            "內容是後端正式 renderer 畫的輸出（已轉義）。D BS1 讀碼判定安全；A 2026-09-28 登記。",
        ("innerHTML=", "paint"):
            "步驟縮圖的 SVG 字串：使用者字串一律經同檔 esc()（轉義 & < > \"）才拼進去。D BS1 讀碼判定安全；A 2026-09-28 登記。",
        ("innerHTML=", "destroy"):
            "縮圖銷毀時清空（寫入空字串），不含任何內容。D BS1；A 2026-09-28 登記。",
    },
    "static/custom-layout.js": {},
}
#: 相容舊名：custom-records.html 的白名單
ALLOWED = ALLOWED_BY_FILE["custom-records.html"]


def _enclosing(lines, i, col):
    """第 i 行第 col 欄的寫入點由哪一個函式包住：先看同一行寫入點之前的文字（取最後一個），再往上逐行找。"""
    def last_name(text):
        best = None
        for rx in _FUNC_PATTERNS:
            for m in rx.finditer(text):
                if m.group(1) not in _NOT_METHODS and (best is None or m.start() >= best[0]):
                    best = (m.start(), m.group(1))
        return best[1] if best else None
    name = last_name(lines[i][:col])
    if name:
        return name
    for j in range(i - 1, -1, -1):
        name = last_name(lines[j])
        if name:
            return name
    return "?"


def sink_sites(text):
    """回傳 [(種類, 位置, 行號)]。位置：該行有元素 id 的屬性寫法 ⇒ id；其他 ⇒ 包住它的函式名稱（沒有 ⇒ "?"）。"""
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        for kind, rx in SINK_KINDS:
            m = rx.search(line)
            if not m:
                continue
            mid = _ID.search(line) if kind == "srcdoc" else None
            where = mid.group(1) if mid else _enclosing(lines, i, m.start())
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
            problems.append("白名單 %s 在檔裡找不到（改名或搬走了）⇒ 過期，重新審過再登記" % (key,))
    if len(allowed) > MAX_ALLOWED:
        problems.append("白名單 %d 筆，超過上限 %d" % (len(allowed), MAX_ALLOWED))
    for key, why in allowed.items():
        if len((why or "").strip()) < 20:
            problems.append("白名單 %s 的理由太短（至少 20 字）" % (key,))
    return problems


def _text(name):
    """頁面經 source_tree.page_file（模組化後搬家也找得到）；static 的 js 是 L1 檔，固定在 frontend/static。
    找不到 ⇒ 例外（紅），不略過（§G5 #15）。"""
    from pathlib import Path
    from core import source_tree
    if name.endswith(".html"):
        return source_tree.page_file(name).read_text(encoding="utf-8")
    return (Path(__file__).resolve().parents[2] / "frontend" / name).read_text(encoding="utf-8")


def _page_text():
    return _text("custom-records.html")


def test_custom_records_js_html_sinks_are_all_reviewed():
    problems = check(sink_sites(_page_text()))
    assert not problems, "\n".join(problems)


def test_every_target_file_is_reviewed():
    """D BS1：建構器的 form-preview.js、custom-layout.js 也掃；每個檔各自雙向、各自上限。"""
    for name, allowed in ALLOWED_BY_FILE.items():
        problems = check(sink_sites(_text(name)), allowed)
        assert not problems, "%s：\n%s" % (name, "\n".join(problems))


def test_positive_control_a_new_document_write_lights_up():
    """正對照：在真頁面植入一處新的 document.write（新的方法裡）⇒ 未登記 ⇒ 紅。"""
    src = _page_text()
    anchor = "        async openOutput() {"
    assert anchor in src, "植入點不見了（頁面改版）⇒ 換一個植入點，不可以讓對照失效"
    planted = src.replace(anchor, "        debugDump() {\n          document.write(this.errMsg)\n        },\n" + anchor, 1)
    problems = check(sink_sites(planted))
    assert len(problems) == 1 and "document.write" in problems[0] and "debugDump" in problems[0], problems


def test_positive_control_form_preview_and_the_new_api_kinds_light_up():
    """正對照（D BS1／BO1）：form-preview.js 新增一處 innerHTML、setHTMLUnsafe、createContextualFragment ⇒ 各自紅。"""
    src = _text("static/form-preview.js")
    anchor = "  function esc(s) {"
    assert anchor in src, "植入點不見了（檔案改版）⇒ 換一個植入點"
    for stmt, kind in (("el.innerHTML = s", "innerHTML="), ("el.setHTMLUnsafe(s)", "setHTMLUnsafe"),
                       ("range.createContextualFragment(s)", "createContextualFragment")):
        planted = src.replace(anchor, "  function sneak(el, s) {\n    %s\n  }\n%s" % (stmt, anchor), 1)
        problems = check(sink_sites(planted), ALLOWED_BY_FILE["static/form-preview.js"])
        assert len(problems) == 1 and kind in problems[0] and "sneak" in problems[0], (stmt, problems)


def test_reverse_control_renaming_an_allowed_site_is_red():
    """反向控制：白名單的位置改名 ⇒ 各自變成未登記＋白名單過期（證明白名單是逐處、不是整類排除）。"""
    src = _page_text()
    renamed = src.replace("async openOutput() {", "async openOutput2() {", 1)
    p1 = check(sink_sites(renamed))
    assert any("openOutput2" in p for p in p1) and any("過期" in p and "openOutput" in p for p in p1), p1
    renamed = src.replace('id="cr-output-frame"', 'id="cr-output-frame2"', 1)
    p2 = check(sink_sites(renamed))
    assert any("cr-output-frame2" in p for p in p2) and any("過期" in p for p in p2), p2
    fp = _text("static/form-preview.js")
    assert "function paint(d) {" in fp
    p3 = check(sink_sites(fp.replace("function paint(d) {", "function paint2(d) {", 1)), ALLOWED_BY_FILE["static/form-preview.js"])
    assert any("paint2" in p for p in p3) and any("過期" in p and "paint" in p for p in p3), p3


def test_enclosing_function_forms():
    """位置判定：同一行多個 `名稱: function` 取寫入點之前最近的；`function 名稱(`；往上找時跳過 if／for。"""
    text = ("  function outer() {\n"
            "    if (x) {\n"
            "      el.innerHTML = a\n"
            "    }\n"
            "    return { update: paint, setHighlight: function () {}, destroy: function () { el.innerHTML = '' } }\n"
            "  }\n")
    assert [(k, w) for k, w, _n in sink_sites(text)] == [("innerHTML=", "outer"), ("innerHTML=", "destroy")]


def test_reverse_control_look_alikes_and_register_limits():
    text = ("        f() {\n"
            "          if (el.innerHTML == x) return\n"
            "          el.innerHTMLx = 1\n"
            "          el.textContent = s\n"
            "          if (a.srcdoc == b) return\n"
            "        },\n"
            '<i data-srcdoc-note="1"></i>\n')
    assert sink_sites(text) == []
    many = {("innerHTML=", "m%d" % i): "x" * 30 for i in range(MAX_ALLOWED + 1)}
    assert any("超過上限" in p for p in check([], many))
    assert any("理由太短" in p for p in check([("innerHTML=", "m0", 1)], {("innerHTML=", "m0"): "ok"}))
    assert check([("innerHTML=", "m0", 1)], {("innerHTML=", "m0"): "x" * 30}) == []
