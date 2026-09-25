# -*- coding: utf-8 -*-
"""解析 frontend/static/sidebar.js 的舊選單（`computeFlags()`＋`buildSidebar()`）成結構資料（階段 C／C3）。

用途：
  - 產生 core/menu_l1.json 的初稿（逐項由舊程式碼轉出，對等成立於起點）
  - 對等守門（test_menu_parity）：每次重新解析舊選單，與宣告式選單逐項比對，直到 C4 切換、舊選單刪除為止

權限表示法（與 core.menu 相同）：
  perm = ["k1", "k2"]  ⇒ 有任一模組權限即可（最高管理者一律可）
  perm = "superadmin"  ⇒ 只限最高管理者（舊碼 `sa`）
  perm = "any"         ⇒ 任何登入者（舊碼 `true`）
"""
import json
import re
from pathlib import Path

SIDEBAR = Path(__file__).resolve().parents[3] / "frontend" / "static" / "sidebar.js"


def _body(src, fn):
    """`function fn() {` 之後到對應的 `}`（跳過字串與註解）。"""
    i = src.index("function %s(" % fn)
    i = src.index("{", i)
    depth, j = 0, i
    while j < len(src):
        c = src[j]
        if c in "'\"`":
            j = _skip_str(src, j)
            continue
        if src.startswith("//", j):
            j = src.index("\n", j)
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[i + 1:j]
        j += 1
    raise ValueError("unbalanced " + fn)


def _skip_str(s, j):
    q = s[j]
    j += 1
    while s[j] != q:
        j += 2 if s[j] == "\\" else 1
    return j + 1


def _js_str(tok):
    tok = tok.strip()
    assert tok[0] in "'\"" and tok[-1] == tok[0], tok
    return json.loads('"' + tok[1:-1].replace('"', '\\"').replace("\\'", "'") + '"')


def _strip_comments(s):
    """去掉 `//` 註解（字串內的不動）——註解裡會提到 `ni()`／`sec()`，不可以被當成呼叫。"""
    out, j = [], 0
    while j < len(s):
        c = s[j]
        if c in "'\"`":
            k = _skip_str(s, j)
            out.append(s[j:k])
            j = k
            continue
        if s.startswith("//", j):
            j = s.find("\n", j)
            if j < 0:
                break
            continue
        out.append(c)
        j += 1
    return "".join(out)


def _split_args(s):
    """頂層逗號切開（括號、方括號、字串內的逗號不切）。"""
    out, depth, cur, j = [], 0, [], 0
    while j < len(s):
        c = s[j]
        if c in "'\"":
            k = _skip_str(s, j)
            cur.append(s[j:k])
            j = k
            continue
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        if c == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        j += 1
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return out


def _calls(body, name):
    """body 裡每一個頂層 `name(...)` 的參數字串（依出現順序）。"""
    out = []
    for m in re.finditer(r"(?<![\w.])%s\(" % name, body):
        j, depth, start = m.end() - 1, 0, m.end()
        while True:
            c = body[j]
            if c in "'\"":
                j = _skip_str(body, j)
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append((m.start(), body[start:j]))
    return out


def flags(src=None):
    """computeFlags()：{旗標: set(模組 key)}；`sa` ⇒ {"superadmin"}。"""
    src = src if src is not None else SIDEBAR.read_text(encoding="utf-8")
    out = {"sa": {"superadmin"}}
    for m in re.finditer(r"^\s*(\w+)\s*=\s*(.+?)\s*$", _body(src, "computeFlags"), re.M):
        name, expr = m.group(1), re.sub(r"//.*", "", m.group(2)).strip()
        keys = re.findall(r"has\('(\w+)'\)", expr)
        if keys and re.fullmatch(r"(has\('\w+'\)\s*(\|\|\s*)?)+", expr):
            out[name] = set(keys)
    return out


def perm_of(expr, fl, group=False):
    """舊條件式 ⇒ "any"／"superadmin"／[keys]。看不懂 ⇒ ValueError（不猜）。
    group=True（sec 的條件，是各項的聯集）：允許混合，回傳含 "superadmin" 的 key 清單。"""
    parts = [p.strip() for p in expr.split("||")]
    if "true" in parts:
        return "any"
    keys = set()
    for p in parts:
        if p not in fl:
            raise ValueError("看不懂的選單條件：%r（在 %r 裡）" % (p, expr))
        keys |= fl[p]
    if group:
        return sorted(keys)
    if keys == {"superadmin"}:
        return "superadmin"
    if "superadmin" in keys:
        raise ValueError("混合 sa 與模組權限的單項條件：%r" % expr)
    return sorted(keys)


def _href(expr):
    m = re.fullmatch(r"pg\('([\w.-]+)'\)", expr.strip())
    if m:
        return m.group(1)
    m = re.fullmatch(r"up \+ '([\w.-]+)'", expr.strip())
    if m:
        return "/" + m.group(1)          # frontend 根目錄的頁（index.html）
    raise ValueError("看不懂的 href：%r" % expr)


def legacy_menu(src=None):
    """⇒ {"groups": [{"label", "perm"(sec 條件), "items": [...]}]}；item＝{href, icon, label, active, perm, badge, extra_badge}。"""
    src = src if src is not None else SIDEBAR.read_text(encoding="utf-8")
    fl = flags(src)
    body = _strip_comments(_body(src, "buildSidebar"))
    body = body[:body.index("].filter(Boolean)")]
    events = sorted([(pos, "sec", a) for pos, a in _calls(body, "sec")] +
                    [(pos, "ni", a) for pos, a in _calls(body, "ni")])
    groups = []
    for _, kind, args in events:
        a = _split_args(args)
        if kind == "sec":
            groups.append({"label": _js_str(a[0]), "perm": perm_of(a[1], fl, group=True), "items": []})
            continue
        extra = _js_str(a[6]) if len(a) > 6 else ""
        eb = None
        if extra:
            m = re.search(r'id="([\w-]+)"[^>]*background:(#[0-9A-Fa-f]{6})', extra)
            if not m:
                raise ValueError("看不懂的 extraBadge：%r" % extra)
            eb = {"id": m.group(1), "color": m.group(2)}
        groups[-1]["items"].append({
            "href": _href(a[0]), "icon": _js_str(a[1]), "label": _js_str(a[2]),
            "active": [_js_str(x) for x in _split_args(a[3].strip()[1:-1])],
            "perm": perm_of(a[4], fl),
            "badge": _js_str(a[5]) if len(a) > 5 and _js_str(a[5]) else None,
            "extra_badge": eb,
        })
    return {"groups": groups}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(legacy_menu(), ensure_ascii=False, indent=1))
