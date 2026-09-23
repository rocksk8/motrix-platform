# -*- coding: utf-8 -*-
"""`EM3` · 例外物件不可以直接進 `HTTPException` 的 `detail`（`STATE.md §217`）。

```
A-2 實跑：
  撞 UNIQUE   -> 畫面顯示「建立失敗：**UNIQUE constraint failed: customers.code**」
  撞 NOT NULL -> 「建立失敗：**NOT NULL constraint failed: customers.name**」
11 處 `PDF 產生失敗：{e}` 包的是 `except Exception` 那一支
  => 它最可能裝的是 **FileNotFoundError 那種帶完整暫存檔路徑**的例外
```

# 🔴 而「把 `{e}` 拿掉」不是答案 —— 那會讓診斷能力一起消失

```
只驗「detail 不含表名／欄位名」  => 把 {e} 拿掉就綠
☠️ 而那時**沒有人查得出那一次到底發生了什麼**
```
🔑 **正式不等於含糊**（`WD1` 的同一條）。⇒ 要的是**追蹤碼**：
```
使用者看到  「建立失敗（代碼 7f3a9c）。請把代碼提供給系統管理員。」
log／audit  那個代碼旁邊有完整的例外
```

# ⚠️ 我沒有做到的那一格，**明著寫在這裡**

`§217` 要的 `(a)` 是「**走產品路徑**觸發一次真的 `IntegrityError`」。
我找過四條路，**四條都到不了**：
```
customers／suppliers   code 由 next_entity_code() 產生（**永遠 max+1**）=> 撞不到
network_plans          建立前**先查過** => 回 409「此案件已建立過…」
inventory              建立前**先查過** => 回 409「序號已存在於庫存：…」
```
⇒ 那 19 處的 `{e}` **是給「沒有預料到的例外」用的退路** ——
  而退路正是最難從產品路徑踩到的東西。
🔑 ⇒ 本檔改用**原始碼層**的守門（下面那幾題），
  而 `(a)` 那一格**要 A-2 說明他是怎麼跑到的** —— 我沒有把它寫成一個到不了的題。
☠️ 寫一個永遠紅或永遠綠的「產品路徑題」比沒有那一題更糟。
"""
import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTERS = ROOT / "routers"

#: ✅ **合法的例外**：`detail` 本來就該含使用者自己送進來的值。
#: A-2 查到的假陽性之一：`system.py:1271` 的 `path` 來自 `body.get("path")`
#: ⇒ **那一處必須留著，我的尺打到它就是尺壞了。**
ALLOWED = {
    # 檔名 -> 允許的行號（動了就要重新確認，不是自動放行）
}

#: 追蹤碼要長得像什麼：**不可猜**。
TRACE_RE = re.compile(r"[0-9a-f]{6,}", re.I)


def _exception_in_detail(path):
    """回 `[(行號, 片段)]` —— `HTTPException(...)` 的 detail 直接插了例外物件。

    ⚙️ 用 `ast` 找 `raise HTTPException(code, f"...{e}...")` 這種形狀：
    ```
    JoinedStr 的 FormattedValue 是一個**名字**，而那個名字是 except 綁的那個
    ```
    ⚠️ 只看 `raise`／`HTTPException` 的呼叫 ⇒ **docstring 與註解結構上進不來**。
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    caught = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.name:
            caught.add(node.name)
    if not caught:
        return []

    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "HTTPException"):
            continue
        for arg in node.args:
            if not isinstance(arg, ast.JoinedStr):
                continue
            for part in arg.values:
                if not isinstance(part, ast.FormattedValue):
                    continue
                v = part.value
                if isinstance(v, ast.Name) and v.id in caught:
                    lits = "".join(p.value for p in arg.values
                                   if isinstance(p, ast.Constant))
                    out.append((arg.lineno, (lits or "")[:30]))
    return out


def _offenders():
    hits = []
    for p in sorted(ROUTERS.glob("*.py")):
        for line, head in _exception_in_detail(p):
            if line in ALLOWED.get(p.name, ()):
                continue
            hits.append("%s:%d  %r" % (p.name, line, head))
    return hits


# ══════════════════════════════════════════════════════════════════════

def test_em3_the_detector_can_tell_the_two_shapes_apart(tmp_path):
    """⚙️ **正對照：尺分得出「插了例外」與「插了使用者的輸入」嗎？**

    ```
    raise HTTPException(409, f"建立失敗：{e}")      <= **要抓到**（e 是 except 綁的）
    raise HTTPException(404, f"找不到 {path}")      <= **不可以抓**（那是使用者送的值）
    ```
    ☠️ 抓錯的話我會去改一個**本來就該含使用者輸入**的訊息 ——
       A-2 查到的假陽性就是那一種（`system.py:1271` 的 `path` 來自 `body`）。
    """
    bad = tmp_path / "bad.py"
    bad.write_text(
        "def f():\n"
        "    try:\n"
        "        g()\n"
        "    except Exception as e:\n"
        '        raise HTTPException(409, f"建立失敗：{e}")\n',
        encoding="utf-8")
    assert _exception_in_detail(bad), "沒抓到 `{e}` —— **太窄**。"

    good = tmp_path / "good.py"
    good.write_text(
        '"""docstring 裡寫 f"建立失敗：{e}" 也不可以被抓到。"""\n'
        "def f(body):\n"
        "    path = body.get('path')\n"
        "    try:\n"
        "        g()\n"
        "    except Exception as e:\n"
        "        log(e)\n"
        '        raise HTTPException(404, f"找不到 {path}")\n',
        encoding="utf-8")
    assert _exception_in_detail(good) == [], (
        "把**使用者送進來的值**判成違規：%r —— **太寬**。\n"
        % _exception_in_detail(good)
        + "⚠️ 那一種必須留著（A-2 查到的假陽性就是它）。")


def test_em3_no_router_puts_an_exception_object_into_a_detail():
    """🔴 **`EM3`：`HTTPException` 的 `detail` 不可以插 `except … as e` 的那個 `e`。**

    ☠️ 使用者會看到：
    ```
    建立失敗：UNIQUE constraint failed: customers.code
    建立失敗：NOT NULL constraint failed: customers.name
    PDF 產生失敗：[Errno 2] No such file or directory: 'C:\\\\Users\\\\...\\\\tmp\\\\xxx.pdf'
    ```
    🔑 前兩句洩漏**資料表與欄位名**；第三句洩漏**這台機器的路徑**。
    ⚠️ 而修法**不是**把 `{e}` 拿掉 —— 那會讓診斷能力一起消失。
       要的是**追蹤碼**：畫面給代碼，log 留完整例外。
    """
    hits = _offenders()
    scanned = len(list(ROUTERS.glob("*.py")))
    assert scanned > 20, "只掃到 %d 個 router —— **尺量不到東西**。" % scanned
    assert not hits, (
        "有 %d 處把例外物件直接放進 `detail`：\n" % len(hits)
        + "".join("    %s\n" % h for h in hits[:15])
        + ("    …另外 %d 處\n" % (len(hits) - 15) if len(hits) > 15 else "")
        + "🔑 修法是**追蹤碼**，不是把 `{e}` 拿掉：\n"
          "    使用者看到「建立失敗（代碼 7f3a9c）」\n"
          "    log／audit 那個代碼旁邊有完整的例外\n"
        + "⚠️ 而 `detail` 本來就該含**使用者自己送進來的值**的地方**要留著** ——\n"
          "   那一種請登記進 `ALLOWED`，並寫下為什麼。")


def test_em3_an_injected_exception_does_not_reach_the_user(client, make_user,
                                                           monkeypatch):
    """🔴 **注入一個帶敏感字串的例外 ⇒ 使用者看不到它，而看得到追蹤碼。**

    ## ⚙️ 這一題怎麼繞過「產品路徑到不了」那件事

    ```
    A 的界線  不可以 **mock 一個例外丟進 HTTPException**
    而這裡    讓被 try 包住的那一支**自己丟** => 走的是**真的** except 那一條路
    ```
    🔑 差別在**注入點**：我沒有繞過那個 handler，我**餵給它**一個輸入。
    📌 A-2 建議的做法，而它解掉我先前那一格
      （四條產品路徑都到不了 —— 因為那 18 處是**非預期例外的退路**）。

    ⚙️ 注入點挑 `customers.py` 的 `next_entity_code()`：
    它**在那個 `try` 裡面**，而它丟出來的東西會原封不動進 `detail`。
    """
    import routers.customers as rc

    secret = "UNIQUE constraint failed: customers.code"

    def _boom(*_a, **_k):
        raise RuntimeError(secret)

    assert hasattr(rc, "next_entity_code"), (
        "`routers/customers.py` 沒有 `next_entity_code` —— **退回給我**改注入點。")
    monkeypatch.setattr(rc, "next_entity_code", _boom)

    u, p = make_user(username="em3_inj", role="superadmin",
                     modules=["customer"])
    tok = client.post("/api/auth/login",
                      json={"username": u, "password": p}).json()["token"]
    hdr = {"Authorization": "Bearer " + tok}

    r = client.post("/api/customers", headers=hdr,
                    json={"name": "測試客戶", "tax_id": "", "phone": ""})
    assert r.status_code >= 400, (
        "注入了例外而端點回 %s —— **注入沒有生效**，這一題量不到東西。"
        % r.status_code)

    assert secret not in r.text, (
        "使用者看到了例外原文：%s\n" % r.text[:200]
        + "☠️ 那一句話裡有**資料表名與欄位名**。\n"
        + "🔑 而修法不是把 `{e}` 拿掉 —— 要的是**追蹤碼**：\n"
          "   畫面給代碼，log／audit 那個代碼旁邊留完整的例外。")
    assert "constraint" not in r.text.lower(), (
        "回應裡還有 `constraint`：%s" % r.text[:200])
    assert TRACE_RE.search(r.text), (
        "擋住了原文，**而沒有給追蹤碼**：%s\n" % r.text[:200]
        + "☠️ 那是「把 `{e}` 拿掉」的樣子 —— 使用者看到一句「建立失敗」，\n"
          "   而**沒有人查得出那一次到底發生了什麼**。\n"
        + "📌 `WD1` 的同一條：**正式不等於含糊**。")


def test_em3_a_trace_code_exists_and_is_not_guessable():
    """🔴 **追蹤碼要存在、要查得到、而且**不可猜**。**

    ```
    可猜（遞增序號）=> 使用者報「代碼 18」，而那個號碼**別人也會拿到**
                     ⇒ 查 log 時對不起來
    ```
    ⚙️ 判準三格：
    ```
    ① 有一支產生追蹤碼的函式
    ② 連兩次**不相同**
    ③ 不是遞增序號（兩次的差不是 1，且不全是數字）
    ```
    ⚠️ 名字由 B 決定 —— 找不到就明說要哪一個。
    """
    import importlib

    fn = None
    for mod_name, attr in (("helpers.errors", "new_trace_code"),
                           ("helpers.errors", "trace_code"),
                           ("helpers.logging_ext", "new_trace_code")):
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        fn = getattr(mod, attr, None)
        if callable(fn):
            break
    assert callable(fn), (
        "找不到產生追蹤碼的函式（試過 `helpers.errors.new_trace_code`／"
        "`trace_code`／`helpers.logging_ext.new_trace_code`）。\n"
        + "📌 `EM3` 的修法是**追蹤碼**：畫面給代碼，log 留完整例外。\n"
        + "⚠️ 用別的名字**退回給我**；而**不要**改成把 `{e}` 拿掉 ——\n"
          "   那會讓診斷能力一起消失（`WD1`：正式不等於含糊）。")

    a, b = str(fn()), str(fn())
    assert a != b, (
        "連兩次產生的追蹤碼相同（%r）——\n" % a
        + "☠️ 那等於沒有代碼：兩次不同的失敗在 log 裡長得一樣。")
    assert TRACE_RE.search(a), (
        "追蹤碼 %r 看起來不像一個代碼（要有 6 碼以上的十六進位）。" % a)
    assert not (a.isdigit() and b.isdigit() and abs(int(b) - int(a)) == 1), (
        "追蹤碼是**遞增序號**（%r -> %r）——\n" % (a, b)
        + "☠️ 使用者報「代碼 18」，而那個號碼**別人也會拿到** ⇒ 查 log 對不起來。")
