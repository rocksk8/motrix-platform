"""案件管理頁用詞統一（2026-09-24 使用者表單）。

代辦→待辦、備注→備註、完結案→結案、按鈕的「+」一律全形「＋」、
外包名冊的個人一律稱「外包人員」（承攬商＝公司，見承攬商管理；外包人員＝外包名冊，點工）。
只看使用者看得到的字：HTML 註解與 JS 註解不算。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
HTML = ROOT / "frontend" / "pages" / "case-management.html"
JS = ROOT / "frontend" / "js" / "case-management.js"

OLD_WORDS = {"代辦": "待辦", "備注": "備註", "完結案": "結案", "外包名單人員": "外包人員"}


def _visible(path):
    s = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
        s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)          # <style> 內的 CSS 註解
    lines = []
    for line in s.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
            continue
        lines.append(re.sub(r"\s//\s.*$", "", line))       # 行尾 // 註解（前面要有空白，避開 http://）
    return lines


def _hits(pred):
    out = []
    for path in (HTML, JS):
        for n, line in enumerate(_visible(path), 1):
            if pred(line):
                out.append(f"{path.name}:{n}: {line.strip()[:100]}")
    return out


def test_old_words_are_gone_from_what_users_see():
    for old, new in OLD_WORDS.items():
        hits = _hits(lambda l, o=old: o in l)
        assert not hits, f"「{old}」應改為「{new}」：\n" + "\n".join(hits)


def test_plus_on_buttons_is_full_width():
    # 按鈕文字行首的半形「+ 」（例如「+ 上傳附件」）；運算用的 + 不會出現在行首接中文
    hits = _hits(lambda l: re.match(r"^\s*\+ ?[一-鿿]", l) is not None)
    assert not hits, "按鈕的「+」應為全形「＋」：\n" + "\n".join(hits)


def test_positive_control_the_scanner_sees_visible_text():
    # 正對照：確定掃描器看得到頁面上的字（否則上面兩題可能是空集合的綠）
    assert _hits(lambda l: "承攬商" in l), "掃描器沒看到任何「承攬商」——剝註解剝過頭了"
    assert _hits(lambda l: "＋ 新增" in l)
