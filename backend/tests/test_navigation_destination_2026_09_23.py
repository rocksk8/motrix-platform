# -*- coding: utf-8 -*-
"""`EM10` · 導航指示要走得到（`docs/windows/SPEC-EM10-NAVIGATION.md`）。

```
EM1   問「這個字懂不懂」  —— 比對字串（訊息裡的詞 vs 畫面上的詞）
EM10  問「照著這句話走，走得到嗎」 —— **照著指示點一次**
```

# 🔴 動工前自己掃過一次母體，而**不是 46**

規格 `§2` 寫「46 條」（A-2「實掃」）。獨立寫一支不同的掃描器（backend
用 `ast` 取字串常數、frontend 用剝掉註解後的逐行掃描）重新量：

```
backend  89 條（ast 走過 backend/**（排除 scripts/、rollback_snapshots/、
              tests/），只取字串常數節點，**排除 docstring 位置的節點**
              —— 這個 repo 的 docstring 大量用「請」開頭的句子寫文件，
              第一版沒排除時連自己剛寫的程式檔都撿到假警報）
frontend 55 條（frontend/**/*.html／*.js（排除 rollback），剝掉
              `<!--…-->`／`/*…*/`／整行 `//` 之後逐行找語氣詞）
合計     **144**
```
⚠️ **不是 46 錯，是兩把尺量的範圍不同**——A-2 的「實掃」大概率是人工
篩過、只算「站得住的獨立訊息」，我這把尺是機械掃描，不分辨同一組
email 樣板裡重複出現幾次、也不刻意排除掉重複率高的樣板文字。兩個數字
不必調和成同一個：**本檔的反向控制用自己這把尺量出來的 144，不是拿
46 硬套**——量測方式必須可重跑（見 `_scan_all_nav_messages()`），
數字才有意義；照抄一個量不出來的數字才是真正的風險。

⇒ 已核對：`§3` 的 5 條、`§4` 的 2 個負對照，**全部都在這 144 條掃得到的
範圍內**（見下面各題），證明這把尺至少涵蓋了規格點名的全部已知案例。

# ⚙️ 本檔做的與刻意不做的

```
✅ ① 反向控制：nav-tone 訊息總數不可以下降（防「守門逼刪訊息」那個坑）
✅ ② §3 的 4 條個別釘死（第 5 條 `STATE` 提到未落檔，待 A 補，不寫）
✅ ③ §4 的 2 個負對照（證明判準不是「全部都紅」）
❌ 不做 §5／§6 完整的「兩層判準」機械化（要求全部 144 條逐一都有可比對
   引號目的地）——那需要對每一條訊息個別判定「引號目的地在不在畫面上」，
   而 144 條裡大多數的「畫面」需要人工核對是哪一頁，機械掃描做不到
   規格 §7③ 要求的「照著指示點一次」；那件事本身就是規格寫明的**人工
   驗收**，不是這裡能自動化的部分。本檔只覆蓋規格點名的、已經人工核對
   過目的地的 4＋2 條。
```
"""
import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

NAV_PHRASES = ("請至", "請於", "請到", "前往", "請先至", "請先到",
               "可至", "可於", "改由")

QUOTE_RE = re.compile(r"[「『]([^」』]{1,60})[」』]")


def _has_nav_tone(s):
    return any(p in s for p in NAV_PHRASES)


def _docstring_const_ids(tree):
    """`module`／`function`／`class` 的 docstring 常數節點 id 集合。

    docstring 是文件散文不是使用者可見訊息，混進來會撿到幽靈——這個 repo
    的 docstring 大量用「請」開頭的句子寫文件，不排除的話連測試檔自己都
    會被掃到假警報。
    """
    ids = set()
    candidates = [tree] + [n for n in ast.walk(tree)
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                             ast.ClassDef))]
    for node in candidates:
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr):
            val = body[0].value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                ids.add(id(val))
    return ids


def _string_literals_in_py(path):
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except SyntaxError:
        return []
    doc_ids = _docstring_const_ids(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in doc_ids:
                out.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            parts = [v.value for v in node.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            out.append("".join(parts))
    return out


def _backend_py_files():
    for p in (ROOT / "backend").rglob("*.py"):
        parts = p.relative_to(ROOT).parts
        if "scripts" in parts or "rollback_snapshots" in parts or "tests" in parts:
            continue
        if "__pycache__" in parts:
            continue
        yield p


def _frontend_files():
    for pat in ("*.html", "*.js"):
        for p in (ROOT / "frontend").rglob(pat):
            if "rollback" in p.relative_to(ROOT).parts:
                continue
            yield p


def _scan_all_nav_messages():
    """回傳 `[(檔案相對路徑, 訊息文字), …]`——backend 用 `ast` 取字串常數，
    frontend 剝掉常見註解後逐行找語氣詞。見檔頭「動前查母體」。
    """
    hits = []
    for p in _backend_py_files():
        for s in _string_literals_in_py(p):
            if _has_nav_tone(s):
                hits.append((str(p.relative_to(ROOT)), s))
    for p in _frontend_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        text_nc = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        text_nc = re.sub(r"/\*.*?\*/", "", text_nc, flags=re.S)
        for line in text_nc.splitlines():
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            if _has_nav_tone(line):
                hits.append((str(p.relative_to(ROOT)), stripped))
    return hits


def _page_text(rel):
    return (ROOT / "frontend" / "pages" / rel).read_text(
        encoding="utf-8", errors="replace")


def _system_settings_pages():
    """帶著 `pg__eyebrow">系統設定<` 這個分類標籤的頁面——這是畫面自己
    對「系統設定」這個分類的定義，不是我自己猜一個頁面名稱。
    """
    out = []
    for p in (ROOT / "frontend" / "pages").glob("*.html"):
        text = p.read_text(encoding="utf-8", errors="replace")
        if 'pg__eyebrow">系統設定<' in text:
            out.append(p.name)
    return out


# ══════════════════════════════════════════════════════════════════════
# ① 反向控制：nav-tone 訊息總數不可以下降
# ══════════════════════════════════════════════════════════════════════

#: 本檔自己這把尺量出來的基準——**只能因為新增／移除語氣詞、改變掃描
#: 範圍而調整，並且要在這裡寫下理由**；不可以因為某次改動讓訊息變少
#: 而往下調（那正是規格 §5 要防的「守門逼對方刪訊息」）。
_BASELINE_COUNT = 144


def test_em10_the_navigation_tone_message_count_does_not_drop():
    """🔴🔴 **反向控制：含導航語氣的可見字串總數不可以低於基準。**

    ☠️ 若沒有這一題，「兩層判準」的守門（要求訊息附上可比對的目的地）
    最省力的反應是**把整句導航直接刪掉**——刪掉之後判準全綠，而使用者
    連一個錯的指路牌都沒有了，比原本更糟。這一題釘住「訊息只能變得
    更可比對，不能就地消失」。
    """
    hits = _scan_all_nav_messages()
    assert len(hits) >= _BASELINE_COUNT, (
        "含導航語氣的可見字串只掃到 %d 條，低於基準 %d：\n" % (
            len(hits), _BASELINE_COUNT)
        + "\n".join("  %s :: %r" % (p, s[:80]) for p, s in hits[:20])
        + "\n☠️ 若是因為某次改動把導航語句直接刪掉才變少的，"
          "那正是這一題要擋住的事。")


# ══════════════════════════════════════════════════════════════════════
# ② `§3` 的四條——個別釘死，目的地字串要對得上畫面
# ══════════════════════════════════════════════════════════════════════

def test_em10_edge_path_message_points_to_a_findable_label():
    """🔴🔴 **`①` `startup.py:42`：訊息說「Edge 執行檔路徑」，畫面上沒有這個字。**

    實際畫面（`company-profile-settings.html`）那張卡片的標題是
    「**Edge 瀏覽器路徑**」——使用者在正確的頁面上，看著正確的欄位，
    而不認得它。
    """
    src = (ROOT / "backend" / "helpers" / "startup.py").read_text(
        encoding="utf-8", errors="replace")
    msg = next((s for s in _string_literals_in_py(
                   ROOT / "backend" / "helpers" / "startup.py")
               if "Edge 執行檔" in s), None)
    assert msg is not None, "找不到 Edge 執行檔的訊息——退回改本檔的錨點。"
    m = QUOTE_RE.search(msg)
    assert m, "訊息裡找不到引號目的地：%r" % msg
    target = m.group(1).split("→")[-1].strip()
    page = _page_text("company-profile-settings.html")
    assert target in page, (
        "訊息說要去「%s」，而 `company-profile-settings.html` 裡找不到\n"
        "這個字——實際的卡片標題是「Edge 瀏覽器路徑」。" % target)


def test_em10_tender_radar_health_message_points_to_a_findable_label():
    """🔴🔴 **`②` `email_notify.py`：訊息說去看「雷達健康狀態」，畫面上沒有這五個字。**

    `tender-radar.html` 那個健康區塊的標題是 `x-text="healthText"`——
    動態文字，沒有固定的「雷達健康狀態」這個標籤。⚠️ 待 A 裁定修法方向
    （改訊息措辭，或是在畫面上加一個固定小標）——本題只釘現況：兩者選
    哪一種修完之後這裡都會變，改完請回來確認這一題還站不站得住。
    """
    hits = _scan_all_nav_messages()
    msg = next((s for p, s in hits if "雷達健康狀態" in s), None)
    assert msg is not None, "找不到那句訊息——退回改本檔的錨點。"
    page = _page_text("tender-radar.html")
    assert "雷達健康狀態" not in page, (
        "『雷達健康狀態』現在已經出現在 `tender-radar.html` 裡了——\n"
        "這一題的前提（畫面上沒有固定標籤）已經不成立，請確認訊息是否\n"
        "也已經改到指得對，然後把本題改成正對照或刪掉。")


def test_em10_annual_target_message_points_to_the_wrong_place():
    """🔴🔴 **`③` `reports.py:874`：訊息叫使用者去系統設定，年度目標其實在報表頁。**

    使用者照著「請於系統設定中配置年度目標」這句話，會去 `pg__eyebrow`
    標「系統設定」的那一批頁面裡找——而年度目標的設定按鈕
    （`openTargetModal()`）長在 `reports.html` 自己身上，不在那一批頁面
    裡的任何一頁。

    ⚙️ 核心斷言是**訊息本身不可以再提「系統設定」**——那是可以直接對
    訊息原始碼下的紅色斷言，不管 B 最後把措辭改成什麼樣子（例如「請在
    本頁『立即設定年度目標』按鈕設定」），只要不再指向錯的地方就過；
    下面兩段是**佐證**（釘住「系統設定」與「年度目標實際在哪裡」這兩個
    事實本身不會漂移），不是驗收的核心那一格。
    """
    msg = next((s for s in _string_literals_in_py(
                   ROOT / "backend" / "routers" / "reports.py")
               if "年度目標" in s and _has_nav_tone(s)), None)
    assert msg is not None, "找不到年度目標那句導航訊息——退回改本檔的錨點。"
    assert "系統設定" not in msg, (
        "`reports.py` 的年度目標訊息仍然說「系統設定」：%r\n" % msg
        + "☠️ 使用者會去系統設定翻一輪，而那裡沒有年度目標——\n"
          "   實際的設定按鈕在 `reports.html` 自己身上。")

    settings_pages = _system_settings_pages()
    assert settings_pages, "一頁『系統設定』分類的頁面都找不到——退回改本檔的判定法。"
    for name in settings_pages:
        text = _page_text(name)
        assert "年度目標" not in text, (
            "『系統設定』分類裡的 %s 找到了「年度目標」——\n" % name
            + "這一題的前提（系統設定裡沒有年度目標）已經不成立，"
              "請確認並更新本題。")
    report_text = _page_text("reports.html")
    assert "年度目標" in report_text and "openTargetModal" in report_text, (
        "`reports.html` 裡反而找不到年度目標的設定入口——前置不對。")


def test_em10_t100_account_code_message_points_to_the_wrong_place():
    """🔴🔴 **`④` `accounting_export.py:422`：訊息叫使用者去系統設定，
    T100 科目代號其實在出納頁的 T100 子頁籤。**

    `FN3` 把這個功能從報表頁搬到出納頁，訊息沒有跟著搬——同一個成因，
    `③` 是搬家前的舊指標，這一題是搬家前的另一個舊指標。核心斷言與
    `③` 同一種形狀：訊息不可以再提「系統設定」，下面兩段是佐證。
    """
    # ⚠️ 這句訊息在原始碼裡是三段字串常數用 `+` 接起來的
    # （`"…科目代號：" + "、".join(...) + "（請至系統設定…）"`），
    # `ast` 把它們拆成三個獨立的 `Constant` 節點——「科目代號」與
    # 「請至系統設定」不在同一個節點裡，錨點只能定在含語氣詞的那一段。
    msg = next((s for s in _string_literals_in_py(
                   ROOT / "backend" / "routers" / "accounting_export.py")
               if "匯入 T100" in s and _has_nav_tone(s)), None)
    assert msg is not None, "找不到 T100 那句導航訊息——退回改本檔的錨點。"
    assert "系統設定" not in msg, (
        "`accounting_export.py` 的科目代號訊息仍然說「系統設定」：%r\n"
        % msg
        + "☠️ 實際的設定入口在出納頁的 T100 子頁籤，不在系統設定裡。")

    settings_pages = _system_settings_pages()
    assert settings_pages, "一頁『系統設定』分類的頁面都找不到——退回改本檔的判定法。"
    for name in settings_pages:
        text = _page_text(name)
        assert "科目代號" not in text, (
            "『系統設定』分類裡的 %s 找到了「科目代號」——\n" % name
            + "這一題的前提已經不成立，請確認並更新本題。")
    cashier_text = _page_text("cashier.html")
    assert "科目代號" in cashier_text and "toggleT100Config" in cashier_text, (
        "`cashier.html` 裡反而找不到 T100 科目代號的設定入口——前置不對。")


# ══════════════════════════════════════════════════════════════════════
# ③ `§4` 的負對照——判準不是「全部都紅」
# ══════════════════════════════════════════════════════════════════════

def test_em10_the_daily_tasks_password_message_is_a_correct_positive_control():
    """⚙️ **正對照：`daily-tasks.html` 那句「請至使用者管理…」逐段都對得上。**

    ☠️ 少了正對照，判準若壞成「只要含語氣詞就紅」，`②` 那四題會全部
    通過而**理由是錯的**（不是因為判準真的比對過目的地）。
    """
    hits = _scan_all_nav_messages()
    msg = next((s for p, s in hits
               if "每日工作事項密碼" in s and "使用者管理" in s
               and p.endswith("daily-tasks.html")), None)
    assert msg is not None, "找不到那句訊息——退回改本檔的錨點。"

    users_page = _page_text("users.html")
    # 逐段驗：目的地頁面標題／欄位標籤都要在 users.html 裡找得到。
    assert 'pg__t">使用者管理' in users_page, (
        "`users.html` 找不到「使用者管理」這個頁面標題。")
    assert "每日工作事項密碼" in users_page, (
        "`users.html` 找不到「每日工作事項密碼」這個欄位標籤——\n"
        "訊息叫使用者去那裡設定，而那裡沒有這個欄位。")


def test_em10_the_notification_email_message_is_a_correct_positive_control():
    """⚙️ **第二個正對照：`notification-settings.html` 那句話也逐段對得上。**

    ⚙️ 與上一題**同一種形狀、不同頁**——兩個負對照都是「引號目的地 →
    前端標籤」，確認判準不是只在一個特例上剛好對。
    """
    hits = _scan_all_nav_messages()
    msg = next((s for p, s in hits
               if "使用者管理" in s and "Email" in s), None)
    assert msg is not None, "找不到那句訊息——退回改本檔的錨點。"

    users_page = _page_text("users.html")
    assert 'pg__t">使用者管理' in users_page
    assert 'type="email"' in users_page and "x-model=\"form.email\"" in users_page, (
        "`users.html` 找不到 Email 欄位——訊息叫使用者去那裡填，\n"
        "而那裡沒有這個欄位。")
