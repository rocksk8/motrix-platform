"""全站用詞統一（CU2b，2026-09-24）：案件頁已統一的用詞擴到其他頁與後端訊息。

使用者表單（案件管理頁用詞，見 test_case_page_wording_2026_09_24.py）：代辦→待辦、備注→備註、完結案→結案。
這裡把同一條規則擴到全站：前端所有頁面／腳本的可見文字（剝 HTML／CSS／JS 註解），以及後端送到畫面、
信件、PDF、Excel 的字串常值（只看 Python 字串 token，docstring 不算）。模組 key 不動，只改顯示文字。

例外只有一種：**匯入**讀欄名時同時收新舊標題（舊匯出檔的欄名是「備注」）——同一行必須同時有新詞。
"""
import io
import pathlib
import re
import tokenize

ROOT = pathlib.Path(__file__).resolve().parents[2]
OLD_WORDS = {"代辦": "待辦", "備注": "備註", "完結案": "結案"}


def _fe_lines(path):
    s = path.read_text(encoding="utf-8", errors="replace")
    keep_nl = lambda m: "\n" * m.group(0).count("\n")          # noqa: E731 行號要對得上
    if path.suffix == ".html":
        s = re.sub(r"<!--.*?-->", keep_nl, s, flags=re.S)
    s = re.sub(r"/\*.*?\*/", keep_nl, s, flags=re.S)
    for n, line in enumerate(s.split("\n"), 1):
        st = line.lstrip()
        if st.startswith("//") or st.startswith("*"):
            continue
        yield n, re.sub(r"\s//\s.*$", "", line)


def _py_strings(path):
    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, SyntaxError):
        return
    prev = None
    for t in toks:
        if t.type == tokenize.STRING:
            triple = t.string.lstrip("rRbBuUfF").startswith(('"""', "'''"))
            is_doc = triple and (prev is None or prev.type in (tokenize.INDENT, tokenize.NEWLINE, tokenize.DEDENT))
            if not is_doc:
                yield t.start[0], t.string
        if t.type not in (tokenize.COMMENT, tokenize.NL):
            prev = t


def _frontend_files():
    for p in sorted((ROOT / "frontend").rglob("*")):
        if p.suffix in (".html", ".js") and "vendor" not in p.parts:
            yield p


def _backend_files():
    for p in sorted((ROOT / "backend").rglob("*.py")):
        if "tests" not in p.parts and "__pycache__" not in p.parts:
            yield p


def _hits(pred):
    out = []
    for p in _frontend_files():
        for n, line in _fe_lines(p):
            if pred(line):
                out.append((p, n, line.strip()))
    for p in _backend_files():
        for n, s in _py_strings(p):
            if pred(s):
                out.append((p, n, s.strip()))
    return out


def _is_import_compat(text, old, new):
    """匯入時新舊欄名都收：同一行同時出現新詞與舊詞（例如 n['備註'] || n['備注']）。"""
    return old in text and new in text and ("n['" in text or 'n["' in text)


def test_old_words_are_gone_from_what_users_see_site_wide():
    for old, new in OLD_WORDS.items():
        bad = [f"{p.relative_to(ROOT)}:{n}: {t[:100]}" for p, n, t in _hits(lambda s, o=old: o in s)
               if not _is_import_compat(t, old, new)]
        assert not bad, f"「{old}」應改為「{new}」：\n" + "\n".join(bad)


def test_import_still_accepts_old_note_header():
    """匯出改成「備註」之後，舊的匯出檔（欄名「備注」）仍要匯得進來。"""
    for rel in ("frontend/pages/parts.html", "frontend/pages/vendor-contractors.html"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert re.search(r"n\['備註'\]\s*\|\|\s*n\['備注'\]", text), rel


def test_positive_control_the_scanner_sees_visible_text_and_strings():
    """正對照：掃描器看得到可見文字與後端字串（否則上面那題可能是空集合的綠）。"""
    assert any("module_registry.py" in str(p) and "案件待辦" in t for p, _, t in _hits(lambda s: "待辦" in s))
    assert any("quotations.py" in str(p) for p, _, _ in _hits(lambda s: "無法結案" in s))
    assert any(p.name == "parts.html" for p, _, _ in _hits(lambda s: "備註" in s))
    # 反向：註解與 docstring 裡的字不算（case_action_items.py 的模組 docstring 寫著「案件代辦事項」）
    doc = (ROOT / "backend" / "routers" / "case_action_items.py").read_text(encoding="utf-8").split('"""')[1]
    assert "代辦" in doc, "量尺：這支 docstring 應該還保留舊詞（歷史說明），否則這條反向對照量不到東西"
    assert not any(p.name == "case_action_items.py" and n == 1 for p, n, _ in _hits(lambda s: "代辦" in s))
